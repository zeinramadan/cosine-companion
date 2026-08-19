#!/usr/bin/env python3
"""Atomic generations for the four files that make up the cosine index.

The four files are one logical value: row ``i`` in ``index.npy`` is the vector
for ``ids.json[i]``, and the same IDs must exist in both parquet tables.  A
sequence of four ``os.replace`` calls cannot publish that value atomically.

Every writer therefore uses the same shape: write four immutable,
generation-scoped files, then atomically replace one small manifest that names
them.  A reader sees either the preceding manifest or the new one; it never has
to guess which four files belong together.  Flat files remain the
legacy/no-manifest representation for an existing installation and are kept as
compatibility hard links after the first write.

Disk use is bounded to the current generation and its immediate predecessor.
The manifest records that predecessor, so a commit reaps one exact generation;
it never scans for "apparently stale" files and can never mistake a suspended
writer's uncommitted generation for debris.  A small cross-process lock covers
only verified reads and the short reap/manifest/link commit region.  The four
large writes happen before the lock is taken.
"""

from contextlib import contextmanager
import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


INDEX_MANIFEST_FILENAME = "library_index.json"
INDEX_MANIFEST_SCHEMA = 1
INDEX_LOCK_FILENAME = ".library-index.lock"
STAGING_SUFFIX = ".tmp"

_KINDS = ("meta", "embeddings", "index", "ids")
_SUFFIXES = {
    "meta": ".parquet",
    "embeddings": ".parquet",
    "index": ".npy",
    "ids": ".json",
}
_DIGEST_BLOCK_BYTES = 1 << 20


@dataclass(frozen=True)
class IndexGeneration:
    """The four immutable files named by one committed manifest."""

    generation: str
    paths: Dict[str, Path]
    sha256: Dict[str, str]
    previous_generation: Optional[str] = None

    def as_tuple(self) -> Tuple[Path, Path, Path, Path]:
        return tuple(self.paths[kind] for kind in _KINDS)


def index_manifest_path(data_dir) -> Path:
    return Path(data_dir) / INDEX_MANIFEST_FILENAME


def legacy_index_file_paths(data_dir) -> Tuple[Path, Path, Path, Path]:
    data_dir = Path(data_dir)
    return (
        data_dir / "meta.parquet",
        data_dir / "embeddings.parquet",
        data_dir / "index.npy",
        data_dir / "ids.json",
    )


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_DIGEST_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _mode(path: Path) -> Optional[int]:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return None


def _fsync(path: Path) -> None:
    with open(path, "rb") as handle:
        os.fsync(handle.fileno())


@contextmanager
def _index_lock(data_dir: Path, exclusive: bool):
    """Coordinate readers and the short commit region across processes.

    POSIX ``flock`` locks are released by the kernel if a process exits.  The
    Windows branch uses the equivalent one-byte ``msvcrt`` region lock so this
    module remains importable in the shipped Windows build.
    """
    lock_path = Path(data_dir) / INDEX_LOCK_FILENAME
    with open(lock_path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLCK
            msvcrt.locking(handle.fileno(), mode, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(handle.fileno(), mode)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _claim_generation(data_dir: Path) -> Tuple[str, Dict[str, Path]]:
    """Claim all four names with O_EXCL, retrying a UUID collision as a unit."""
    while True:
        generation = uuid.uuid4().hex
        paths = {
            kind: data_dir / f"{kind}.{generation}{_SUFFIXES[kind]}"
            for kind in _KINDS
        }
        claimed = []
        try:
            for path in paths.values():
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
                claimed.append(path)
            return generation, paths
        except FileExistsError:
            for path in claimed:
                path.unlink(missing_ok=True)


def _manifest_document(
    generation: str,
    paths: Dict[str, Path],
    digests: Dict[str, str],
    previous_generation: Optional[str],
) -> Dict[str, object]:
    return {
        "schema_version": INDEX_MANIFEST_SCHEMA,
        "generation": generation,
        "previous_generation": previous_generation,
        "files": {kind: paths[kind].name for kind in _KINDS},
        "sha256": digests,
    }


def _generation_paths(data_dir: Path, generation: str) -> Tuple[Path, ...]:
    return tuple(
        data_dir / f"{kind}.{generation}{_SUFFIXES[kind]}" for kind in _KINDS
    )


def _reap_generation(data_dir: Path, generation: Optional[str]) -> None:
    """Remove the one generation the current manifest names as previous."""
    if generation is None:
        return
    for path in _generation_paths(data_dir, generation):
        path.unlink(missing_ok=True)


def write_index_generation(
    data_dir,
    meta: pd.DataFrame,
    embeddings: pd.DataFrame,
    vectors: np.ndarray,
    ids,
) -> IndexGeneration:
    """Write and atomically commit one complete four-file generation.

    All scratch paths are registered before any writer sees them.  The large
    writes are lock-free and use names no other writer can choose.  The lock is
    acquired only after they are durable; inside it, the current manifest is
    re-read, its explicitly recorded predecessor is reaped, and this generation
    is committed with that current generation as its own predecessor.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = index_manifest_path(data_dir)
    previous_paths = current_index_file_paths(data_dir)
    previous_modes = {
        kind: _mode(path) for kind, path in zip(_KINDS, previous_paths)
    }

    generation, paths = _claim_generation(data_dir)
    staged_manifest = data_dir / (
        f".{INDEX_MANIFEST_FILENAME}.{generation}{STAGING_SUFFIX}"
    )
    mine = [*paths.values(), staged_manifest]

    def discard_scratch() -> None:
        for path in mine:
            try:
                path.unlink()
            except OSError:
                pass

    document = None
    commit_attempted = False
    try:
        meta.to_parquet(paths["meta"], index=False)
        embeddings.to_parquet(paths["embeddings"], index=False)
        np.save(paths["index"], vectors)
        with open(paths["ids"], "w", encoding="utf-8") as handle:
            json.dump(list(ids), handle)
            handle.flush()
            os.fsync(handle.fileno())

        for kind, path in paths.items():
            if previous_modes[kind] is not None:
                os.chmod(path, previous_modes[kind])
            _fsync(path)
        digests = {kind: _digest(paths[kind]) for kind in _KINDS}

    except BaseException:
        discard_scratch()
        raise

    try:
        with _index_lock(data_dir, exclusive=True):
            previous = read_index_generation(data_dir)
            previous_id = None if previous is None else previous.generation
            document = _manifest_document(
                generation,
                paths,
                digests,
                previous_id,
            )

            with open(staged_manifest, "x", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2)
                handle.write("\n")
                old_manifest_mode = _mode(manifest)
                if old_manifest_mode is not None:
                    os.chmod(staged_manifest, old_manifest_mode)
                handle.flush()
                os.fsync(handle.fileno())

            # This is not a directory scan. The live manifest explicitly names
            # the one two-commits-old generation, and the lock prevents another
            # writer from moving the pointer or a reader from pinning it here.
            if previous is not None:
                _reap_generation(data_dir, previous.previous_generation)

            # From the instant replace is attempted, an asynchronous exception
            # cannot prove whether the commit landed. Never clean our files on
            # that ambiguous path: the manifest may already name them.
            commit_attempted = True
            try:
                os.replace(staged_manifest, manifest)
            except OSError:
                commit_attempted = False
                raise

            # Compatibility mirrors for code that reads one legacy path
            # directly (notably Tk Settings statistics and playlist import).
            # They are not the commit and core.loader never trusts them while a
            # manifest exists. Hard links avoid a second physical 38 MB copy.
            for kind, legacy in zip(_KINDS, legacy_index_file_paths(data_dir)):
                staged_link = data_dir / f".{legacy.name}.{generation}.link"
                try:
                    os.link(paths[kind], staged_link)
                    os.replace(staged_link, legacy)
                except OSError:
                    # The manifest already committed, so a stale mirror must
                    # not turn a successful logical commit into an API error.
                    staged_link.unlink(missing_ok=True)
    except BaseException:
        if not commit_attempted:
            discard_scratch()
        raise

    return IndexGeneration(
        generation=generation,
        paths=paths,
        sha256=document["sha256"],
        previous_generation=document["previous_generation"],
    )


def read_index_generation(data_dir) -> Optional[IndexGeneration]:
    """Return the committed generation, or ``None`` for the legacy flat layout.

    A present but malformed manifest is damage, not permission to fall back to
    possibly stale flat files, so it raises ``ValueError`` for ``load_all`` to
    surface as inconsistent index data.
    """
    data_dir = Path(data_dir)
    manifest = index_manifest_path(data_dir)
    if not manifest.is_file():
        return None

    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("the document is not an object")
        if document.get("schema_version") != INDEX_MANIFEST_SCHEMA:
            raise ValueError("unsupported schema version")
        generation = document["generation"]
        previous_generation = document.get("previous_generation")
        files = document["files"]
        digests = document["sha256"]
        if not isinstance(generation, str) or not generation:
            raise ValueError("missing generation")
        if previous_generation is not None and (
            not isinstance(previous_generation, str)
            or len(previous_generation) != 32
            or any(character not in "0123456789abcdef" for character in previous_generation)
            or previous_generation == generation
        ):
            raise ValueError("invalid previous generation")
        if set(files) != set(_KINDS) or set(digests) != set(_KINDS):
            raise ValueError("the file set is incomplete")

        paths = {}
        for kind in _KINDS:
            name = files[kind]
            expected = f"{kind}.{generation}{_SUFFIXES[kind]}"
            if not isinstance(name, str) or name != expected or Path(name).name != name:
                raise ValueError(f"invalid {kind} filename")
            digest = digests[kind]
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError(f"invalid {kind} digest")
            paths[kind] = data_dir / name
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{INDEX_MANIFEST_FILENAME} is invalid: {error}") from None

    return IndexGeneration(
        generation=generation,
        paths=paths,
        sha256=digests,
        previous_generation=previous_generation,
    )


def current_index_file_paths(data_dir) -> Tuple[Path, Path, Path, Path]:
    generation = read_index_generation(data_dir)
    if generation is None:
        return legacy_index_file_paths(data_dir)
    return generation.as_tuple()


def verified_index_payloads(data_dir) -> Tuple[bytes, bytes, bytes, bytes]:
    """Read each committed file once and verify the bytes that will be parsed."""
    data_dir = Path(data_dir)
    with _index_lock(data_dir, exclusive=False):
        generation = read_index_generation(data_dir)
        if generation is None:
            return tuple(
                path.read_bytes() for path in legacy_index_file_paths(data_dir)
            )

        payloads = []
        for kind in _KINDS:
            path = generation.paths[kind]
            try:
                payload = path.read_bytes()
            except OSError as error:
                raise ValueError(
                    f"committed {kind} file could not be read: {error}"
                ) from None
            actual = hashlib.sha256(payload).hexdigest()
            if actual != generation.sha256[kind]:
                raise ValueError(f"committed {kind} file failed its SHA-256 check")
            payloads.append(payload)
        return tuple(payloads)
