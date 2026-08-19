#!/usr/bin/env python3
"""Reading and writing the two playlist tables and their provenance record.

Under the data directory, beside the four index files:

``playlist_import.json``
    The manifest, and the ONLY file this module ever replaces. It names the two
    tables of the generation it commits and carries their SHA-256 digests. See
    ``PlaylistProvenance``.

``playlists.<generation>.parquet``
    ``playlist_id``, ``name``, ``folder_path``, ``parent_id``, ``entries`` -
    one row per playlist, in the export's own document order. That order is the
    only thing that carries "the order Rekordbox lists them in", so it is
    preserved on write and relied on by the reader.

``playlist_membership.<generation>.parquet``
    ``track_id``, ``playlist_id``. Every ``<TRACK Key>`` in the export,
    including the ones naming a track CoCo has not indexed. Persisting the
    faithful record and resolving at read time is what makes a later reindex
    pick up the missing 153 entries without a re-import.

ONE MUTABLE POINTER, AND TABLE FILES THAT ARE NEVER TOUCHED AGAIN
-----------------------------------------------------------------
``import-playlists`` is a CLI command (``cosine_companion.py:83``) and the
drawer runs inside a long-lived webview process. The workflow leads straight to
running both at once - the drawer says the playlists are stale and names the
command, and the natural thing is to run it in a terminal with the app still
open - so **the reader and the writer are different processes by design** and no
in-process lock can order them. Two consequences drive the whole layout:

1. **A reader must parse the bytes it verified, not a path it verified.** The
   previous design hashed ``playlists.parquet`` and then re-opened it; a writer
   landing in between meant the digest described one generation and the parse
   another, and a mixed pair is served as a normal import with its dangling
   membership rows silently dropped. Here the manifest names its files, the
   reader reads THOSE bytes once, and the digest is checked against the buffer
   it is about to parse. There is no second read to disagree with the first.

2. **Two writers must never choose the same name.** The previous design staged
   every import to one shared ``.importing`` name, so a second import wrote the
   bytes a first was about to digest and commit - and because the digest was
   taken after the overwrite, the digests agreed and the reader trusted it.
   Here every import mints its own generation and CLAIMS it with ``O_EXCL``
   (see ``_claim_generation``), so two writers cannot collide: not unlikely to,
   unable to.

The commit is therefore a single ``os.replace`` of the manifest, which is
atomic on one filesystem. That is a real improvement on the previous design's
honest cost: an interrupted import no longer loses the PREVIOUS import, because
it never touched the previous import's files. It leaves orphan table files,
which accumulate. That is deliberate; see below.

SUPERSEDED GENERATIONS ARE NOT DELETED, ON PURPOSE
--------------------------------------------------
Nothing here removes a generation the manifest has stopped naming. Do not
"fix" that by adding it back.

Deleting them safely is not a tidying job, it is a cross-process mutual
exclusion problem, and this module had two goes at solving it with a
check-then-delete and got a data-destroying race both times. The shape is
always the same: the reaper reads the pointer, decides a file is not live, and
unlinks it - and a writer in ANOTHER PROCESS (the CLI; the reader is the web
server) commits in between, so the file that was debris when it was checked is
the live generation by the time it is deleted. An mtime grace period narrows
that window and does not close it, because the clock runs from when a file was
WRITTEN, not from when its writer last made progress: a writer suspended
mid-import - SIGSTOP, a full disk queue, a laptop lid closed on a running
import - resumes and commits tables that are by then hours old. See
``test_a_generation_COMMITTED_BETWEEN_THE_READ_AND_THE_UNLINK_survives``, which
reproduces it with one writer and no ``uuid4`` collision.

Closing it properly needs an ``fcntl.flock`` held by every writer across its
whole commit, and by the reaper across its whole scan. That is a new
cross-process primitive, with its own stale-lock question to answer - a
suspended writer would then block the next import instead of losing a
generation to it - and it would be bought for this: **~66 KB per import.** A
user re-importing weekly for a year accumulates about 3.4 MB. Trading a class
of bug that can silently destroy the live generation against 3.4 MB a year is
not a trade worth making.

So superseded generations stay. They are inert - no manifest names them, no
reader opens them - and the same is true of the zero-length debris a crash
between the two ``O_EXCL`` claims leaves behind. If they ever do need
collecting, collect them somewhere a writer cannot be running: on startup,
under a lock, or by the user. Not from inside an import.

The two flat schema-2 tables ARE removed, by ``clear_legacy_flat_tables``, and
that is not the racy case: they are names this build never writes, so no
import can be in flight on them.

NOT fsync'd, deliberately. fsync would change WHICH generation survives a power
cut; it cannot change whether an inconsistent one is trusted, because the check
is over content and not over ordering. Table bytes that land as zeroes,
truncated, stale or missing all fail the digest of the manifest that names
them, exactly like any other damage.

WHY THESE ARE SEPARATE FILES AND NOT COLUMNS ON ``meta.parquet``
----------------------------------------------------------------
Spec §6.2. Membership is many-to-many, and ``meta.parquet`` is rewritten
wholesale by ``core.persistence.save_index_data`` and again by
``LibrarySession._persist`` - either of which would silently drop a column
added here. Nothing in this module writes ``meta.parquet``,
``embeddings.parquet``, ``index.npy`` or ``ids.json``.

``track_id`` IS A STRING, EXACTLY AS IN ``meta.parquet``
--------------------------------------------------------
The join between ``playlist_membership.track_id`` and ``meta.track_id`` is an
exact string match. ``meta.parquet``'s column is object dtype holding ``str``
(Rekordbox TrackIDs are numeric-looking, so any inference step would happily
turn them into int64 and break the join silently, matching nothing). Everything
here is cast to ``str`` on the way in and asserted on the way out.
"""

import hashlib
import io
import json
import os
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

PROVENANCE_FILENAME = "playlist_import.json"

#: Generation file names are ``<stem>.<generation>.parquet``. The stems are
#: what the flat files used to be called without the generation, which keeps a
#: data directory readable to a human sorting it by name.
PLAYLISTS_STEM = "playlists"
MEMBERSHIP_STEM = "playlist_membership"

#: The two flat names the schema-2 layout wrote. Nothing reads them any more;
#: they are listed so ``clear_legacy_flat_tables`` can remove them once, on the
#: first import after an upgrade, rather than leaving two files that look
#: current forever.
LEGACY_TABLE_FILENAMES = ("playlists.parquet", "playlist_membership.parquet")

PLAYLIST_COLUMNS = ["playlist_id", "name", "folder_path", "parent_id", "entries"]
MEMBERSHIP_COLUMNS = ["track_id", "playlist_id"]

#: Bumped when the on-disk shape changes. A record written by a newer schema is
#: treated as absent rather than misread - and so is one written by an OLDER
#: one, which is what makes the bump safe. 3 makes the manifest NAME its two
#: tables instead of pointing at two fixed filenames, which is what lets the
#: reader verify the bytes it parsed. A schema-2 record names no files, cannot
#: be checked that way, and is therefore read as "nothing imported" rather than
#: trusted. The cost of the bump is one re-import, which is the command the
#: drawer is already showing in that state.
PROVENANCE_SCHEMA = 3

#: Appended to the manifest's name while it is being written. The manifest is
#: the only file replaced in place, so it is the only one that needs staging -
#: and its staged name carries the generation too, so two concurrent writers do
#: not share it either.
STAGING_SUFFIX = ".importing"

#: Read in blocks rather than whole: the export is 1.5 MB today and there is no
#: reason for the digest to be the thing that caps how big it may get.
_DIGEST_BLOCK_BYTES = 1 << 20


def playlist_manifest_path(data_dir=None) -> Path:
    """Where the manifest lives.

    ``data_dir=None`` yields the configured application path, mirroring
    ``core.loader.index_file_paths`` so the two families of files are reached
    the same way.
    """
    if data_dir is None:
        from config import DATA

        data_dir = DATA
    return Path(data_dir) / PROVENANCE_FILENAME


def digest_file(path) -> str:
    """SHA-256 of a file's bytes, as hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_DIGEST_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class PlaylistProvenance:
    """Where the playlist tables came from, and how to tell if they are stale.

    THE STALENESS CHECK IS A CONTENT DIGEST, NOT mtime-AND-SIZE
    -----------------------------------------------------------
    The brief was "the cheapest check that cannot produce a false *fresh*".
    mtime-and-size is cheaper and it CAN: an editor that rewrites a file in
    place and restores its timestamp, a restore from a backup, an export
    written by a tool that preserves mtime, or simply a second export that
    happens to be the same length all read as unchanged. A false "stale" only
    costs the user a re-import they did not need; a false "fresh" means the
    drawer confidently shows a playlist list that no longer exists, which is
    the failure this feature is supposed to prevent.

    A digest cannot do that, and it is not expensive: SHA-256 over the real
    1.5 MB export measures **0.53 ms**, against ~15 ms for the API request it
    is part of. There is no cache and no mtime fast path, because a fast path
    whose miss condition is mtime reintroduces exactly the false fresh it was
    added to avoid.

    ``source_bytes`` and ``source_mtime`` are recorded anyway - not as the
    check, but because "the file is 200 KB now and was 1.5 MB then" is the
    first thing a human wants when the digest disagrees.

    THIS RECORD IS THE COMMIT, AND IT NAMES ITS OWN TABLES
    -----------------------------------------------------
    ``playlists_file`` and ``membership_file`` are BASENAMES - never paths - of
    the two parquet files this record was committed for, and
    ``playlists_sha256`` / ``membership_sha256`` are their digests. Together
    they are what makes reading safe with a writer running in another process:
    the reader resolves the two names against the data directory, reads them
    once, and checks the digests against the buffers it is about to parse.
    Those files are immutable - no import ever writes a name another import
    chose - so there is no window in which the bytes could change between the
    check and the parse.

    Basenames rather than paths so a data directory can be moved or copied
    without rewriting its manifest, and so a manifest can never point outside
    the directory it was found in (see ``_resolve_table``).

    They are digests rather than the row counts already recorded beside them
    because a count answers "how many rows" and the question is "are these the
    same bytes". ``playlist_count`` and ``membership_count`` stay as the
    human-readable record they always were.
    """

    source_xml: str
    source_sha256: str
    source_bytes: int
    source_mtime: float
    imported_at: str
    playlist_count: int
    membership_count: int
    #: Filled in by ``write_playlist_tables`` once the bytes it is committing
    #: exist. Empty on a record that has been built but not yet committed,
    #: which is a state no reader ever sees.
    playlists_file: str = ""
    membership_file: str = ""
    playlists_sha256: str = ""
    membership_sha256: str = ""
    schema_version: int = PROVENANCE_SCHEMA

    @property
    def source_name(self) -> str:
        """The file's basename - what the drawer shows, per spec §6.4.

        The absolute path stays server-side. "from ``242.xml``, imported 12
        Aug" is the whole of what the spec's example puts in front of a user,
        and a home directory in a screenshot is a gift to nobody.
        """
        return Path(self.source_xml).name

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def read_source(xml_path) -> Tuple[bytes, str, int, float]:
    """``(bytes, sha256, size_bytes, mtime)`` from ONE read of the export.

    Replaces a ``describe_source`` that opened the file a second time to hash
    it. Rekordbox rewrites its export whenever the user re-exports, and an
    import takes long enough for that to land between two reads - after which
    the tables held one version and the manifest recorded the digest of
    another, and ``PlaylistService.staleness`` reported "fresh" for data that
    did not match the file. A false *stale* costs a re-import; a false *fresh*
    is the drawer lying, which is the failure this whole record exists to
    prevent.

    So the caller gets the bytes back, and hashes and parses the SAME buffer.
    The digest describes exactly what was parsed, by construction rather than
    by timing. The real export is 1.5 MB, so holding it is free.

    ``size_bytes`` is ``len(data)`` and not ``st_size`` for the same reason,
    and the ``stat`` comes from the open descriptor rather than the path, so
    all four values describe one file at one moment.
    """
    with open(xml_path, "rb") as handle:
        data = handle.read()
        stat = os.fstat(handle.fileno())
    return data, hashlib.sha256(data).hexdigest(), len(data), float(stat.st_mtime)


# ---------------------------------------------------------------------------
# Generations
# ---------------------------------------------------------------------------


def _create_exclusively(path: Path) -> None:
    """Create ``path`` as an empty file, or raise ``FileExistsError``.

    ``O_CREAT | O_EXCL`` is one syscall and the kernel resolves the race: of
    any number of processes racing on the same name, exactly one returns and
    the rest raise. That is the difference between "two writers are unlikely to
    pick the same name" and "two writers cannot both hold it".
    """
    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))


def _claim_generation(data_dir: Path) -> Tuple[str, Path, Path]:
    """Mint a generation and take exclusive ownership of both its table names.

    ``uuid4`` is what makes a second attempt essentially never needed; the
    exclusive create is what makes a collision impossible rather than merely
    unlikely, and it is the part that would still be correct if the id scheme
    were a counter. Both names are claimed before either is written, so a
    generation is all-or-nothing from the moment it exists.

    The two empty files it leaves are the generation's own; ``to_parquet``
    writes over them, and every exit path in ``write_playlist_tables`` removes
    them if the import does not reach its commit.
    """
    while True:
        generation = uuid.uuid4().hex
        playlists = data_dir / f"{PLAYLISTS_STEM}.{generation}.parquet"
        membership = data_dir / f"{MEMBERSHIP_STEM}.{generation}.parquet"
        try:
            _create_exclusively(playlists)
        except FileExistsError:
            continue
        try:
            _create_exclusively(membership)
        except FileExistsError:
            # Ours, and only ours: nothing else can have claimed the playlists
            # name while we held it.
            playlists.unlink(missing_ok=True)
            continue
        return generation, playlists, membership


def clear_legacy_flat_tables(data_dir) -> List[Path]:
    """Delete the two schema-2 flat tables, if an upgrade left them here.

    The ONE deletion this module does, and the one that has no race in it.
    ``playlists.parquet`` and ``playlist_membership.parquet`` are names no
    writer in this build ever creates, so no import can be in flight on either
    of them and no manifest this build writes can name either of them. There is
    therefore nothing to check against a pointer and no window to lose: the
    files are derived, superseded, and re-created under generation names by the
    import that is about to run.

    They are cleared rather than left because leaving them is visible: a fresh
    upgrade's data directory otherwise holds two stale tables that look
    current, sorted right beside the real ones, forever.

    Superseded GENERATIONS are a different question, and this module
    deliberately does not answer it - see the module docstring.
    """
    data_dir = Path(data_dir)
    removed: List[Path] = []
    for name in LEGACY_TABLE_FILENAMES:
        path = data_dir / name
        try:
            path.unlink()
        except OSError:
            # Absent, or not ours to delete. Neither is this import's problem.
            continue
        removed.append(path)
    return removed


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def write_playlist_tables(
    data_dir,
    playlists: Sequence,
    membership: Sequence[Tuple[str, str]],
    provenance: PlaylistProvenance,
) -> PlaylistProvenance:
    """Write both tables and the manifest. Returns the record committed.

    ``playlists`` is a sequence of ``processing.playlist_parser.ParsedPlaylist``
    (anything with the same five attributes will do; this module deliberately
    does not import the parser, so that reading the tables never needs lxml).

    The returned record is not the one passed in: it carries the two table
    names and their digests, which cannot be known until the tables have been
    written.

    THE COMMIT IS ONE ``os.replace``
    --------------------------------
    Both tables are written under names claimed by this import alone (see
    ``_claim_generation``) and are therefore invisible: no manifest names them,
    so no reader will open them. Only then is the manifest written - staged
    under a generation-scoped name of its own and moved into place with
    ``os.replace``, which is atomic per file on one filesystem.

    So there is no window and nothing to detect afterwards:

    * die before the replace - the previous manifest and the previous tables
      are untouched, and the previous import is still fully readable. What is
      left behind is two orphan table files, which nothing names and nothing
      reads. They stay; see the module docstring.
    * die after the replace - there is nothing left to do.

    NOTHING THAT RUNS AFTER THE COMMIT MAY DELETE A FILE
    -----------------------------------------------------
    ``import-playlists`` is the command the drawer tells the user to run in a
    terminal, so Ctrl-C at an arbitrary point in it is ordinary - and one of
    those points is after ``os.replace`` has taken effect. The cleanup below
    used to cover the replace, so an interrupt landing there deleted the two
    tables the manifest had just started naming: a pointer to two files that
    are gone, which every reader reports as "nothing imported". Interrupting an
    import destroyed the import the user already had, which is the one thing
    the "it never touches the previous import's files" guarantee was for.

    "Set a flag after the call returns" does not fix it. CPython delivers a
    pending signal at a bytecode boundary, and a ``KeyboardInterrupt`` can land
    between the syscall returning and the assignment on the next line - which
    is exactly the interval in question. So the commit is not inside a region
    that cleans up at all, and the only exception caught around it is
    ``OSError``: ``rename`` changes nothing when it fails, so an ``OSError`` is
    positive proof the pointer did not move and the scratch files are still
    nobody's but this call's. Anything else - a signal, a ``SystemExit``, a
    ``MemoryError`` - leaves the commit standing, because it may have happened
    and a wrong guess in that direction is unrecoverable while the other costs
    two inert files that no manifest names and no reader opens.

    A concurrent import is the same statement: it wrote different files and
    replaced the same pointer, so whichever ``os.replace`` lands second is the
    generation on disk, whole, with its own tables.

    Every path this function creates is registered BEFORE it is written, so a
    write that fails halfway leaves nothing behind either - the earlier version
    appended the staged path after the write returned, and a partial file from
    a raising write was therefore missed by its own cleanup.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Before anything of ours exists. The two flat names are not ones this
    # build writes, so nothing can be in flight on them.
    clear_legacy_flat_tables(data_dir)

    playlist_frame = pd.DataFrame(
        [
            {
                "playlist_id": str(playlist.playlist_id),
                "name": str(playlist.name),
                # A LIST column, not a joined string. Two folder names in the
                # real export contain '/', so any separator is ambiguous and
                # joining here would lose information irrecoverably. parquet
                # stores this natively as a LIST<STRING>.
                "folder_path": [str(segment) for segment in playlist.folder_path],
                "parent_id": str(playlist.parent_id),
                "entries": int(playlist.entries),
            }
            for playlist in playlists
        ],
        columns=PLAYLIST_COLUMNS,
    )

    membership_frame = pd.DataFrame(
        [
            {"track_id": str(track_id), "playlist_id": str(playlist_id)}
            for track_id, playlist_id in membership
        ],
        columns=MEMBERSHIP_COLUMNS,
    )
    # An empty frame infers object dtype for both columns already, but only
    # because there is nothing to infer FROM. Stated rather than inherited:
    # the join against meta.parquet is by exact string.
    membership_frame = membership_frame.astype({"track_id": "object", "playlist_id": "object"})

    generation, playlists_pq, membership_pq = _claim_generation(data_dir)
    staged_manifest = data_dir / f"{PROVENANCE_FILENAME}.{generation}{STAGING_SUFFIX}"
    mine: List[Path] = [playlists_pq, membership_pq, staged_manifest]

    def discard_this_imports_scratch_files() -> None:
        """Remove what this call made. Only ever reached BEFORE the commit.

        Nothing here can remove a file another import is using: every path in
        ``mine`` is one this call claimed exclusively.
        """
        for leftover in mine:
            try:
                leftover.unlink()
            except OSError:
                pass

    try:
        playlist_frame.to_parquet(playlists_pq, index=False)
        membership_frame.to_parquet(membership_pq, index=False)

        committed = replace(
            provenance,
            playlists_file=playlists_pq.name,
            membership_file=membership_pq.name,
            playlists_sha256=digest_file(playlists_pq),
            membership_sha256=digest_file(membership_pq),
        )
        staged_manifest.write_text(
            json.dumps(committed.as_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except BaseException:
        # Including KeyboardInterrupt: a cancelled import should not leave its
        # scratch files in the user's data directory either. Nothing this
        # region has done is referenced by anything - the manifest still names
        # the previous generation - so all of it goes.
        #
        # A SIGKILL or a power cut runs none of this and leaves the two table
        # files behind. They are inert: no manifest names them, so no reader
        # will open them.
        discard_this_imports_scratch_files()
        raise

    # THE COMMIT. Nothing below this line may delete a file, and the only
    # exception caught is the one that proves the rename did not happen.
    try:
        os.replace(staged_manifest, data_dir / PROVENANCE_FILENAME)
    except OSError:
        discard_this_imports_scratch_files()
        raise

    return committed


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_provenance(data_dir) -> Optional[PlaylistProvenance]:
    """The provenance record, or ``None`` when there is none to read.

    Unreadable, malformed, older-schema and future-schema records all read as
    ``None``: the drawer's "nothing imported yet" state is a correct thing to
    show for a record we cannot interpret, and a traceback in the middle of a
    track detail is not.
    """
    manifest = playlist_manifest_path(data_dir)
    if not manifest.is_file():
        return None

    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    if not isinstance(raw, dict) or raw.get("schema_version") != PROVENANCE_SCHEMA:
        return None

    try:
        return PlaylistProvenance(
            source_xml=str(raw["source_xml"]),
            source_sha256=str(raw["source_sha256"]),
            source_bytes=int(raw["source_bytes"]),
            source_mtime=float(raw["source_mtime"]),
            imported_at=str(raw["imported_at"]),
            playlist_count=int(raw["playlist_count"]),
            membership_count=int(raw["membership_count"]),
            # Required, not defaulted: a schema-3 record that does not name its
            # tables or carry their digests is one nothing can check, and an
            # uncheckable record is not usable.
            playlists_file=str(raw["playlists_file"]),
            membership_file=str(raw["membership_file"]),
            playlists_sha256=str(raw["playlists_sha256"]),
            membership_sha256=str(raw["membership_sha256"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _resolve_table(data_dir: Path, name: str) -> Optional[Path]:
    """``data_dir/name`` if ``name`` is a plain basename, else ``None``.

    The manifest is a file on disk in a directory the user can reach, so its
    contents are input. ``Path(name).name != name`` rejects a separator and an
    absolute path; ``.`` and ``..`` are named separately because ``Path("..")``
    reports ``".."`` as its own name and would otherwise sail through. A
    manifest can only ever name a file beside itself.
    """
    if not name or name in (".", "..") or Path(name).name != name:
        return None
    return data_dir / name


def committed_table_paths(data_dir) -> Optional[Tuple[Path, Path]]:
    """``(playlists, membership)`` paths the manifest names, or ``None``.

    The one supported way to find the tables. Nothing outside this module
    should build a table filename: the manifest is the pointer, and going
    around it is how a reader ends up looking at a generation nobody committed.
    """
    provenance = read_provenance(data_dir)
    if provenance is None:
        return None
    data_dir = Path(data_dir)
    playlists = _resolve_table(data_dir, provenance.playlists_file)
    membership = _resolve_table(data_dir, provenance.membership_file)
    if playlists is None or membership is None:
        return None
    return playlists, membership


def read_playlist_tables(
    data_dir, provenance: PlaylistProvenance
) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """``(playlists, membership)`` as DataFrames, or ``None`` when unusable.

    Takes the manifest rather than looking one up, because the caller has
    already decided which generation it is reading and re-reading the manifest
    here would be a second chance to disagree with the first.

    READ THE BYTES ONCE, CHECK THOSE BYTES, PARSE THOSE BYTES
    ---------------------------------------------------------
    The digests are verified against the buffers this function is about to
    hand to pyarrow - not against the files at those paths, which is a
    different question with a different answer whenever a writer is running.
    The previous design asked the second question: it hashed
    ``playlists.parquet`` and ``playlist_membership.parquet`` and then re-opened
    both, and an import landing in that window was served as a normal import
    under the old manifest's provenance. Nothing can open between an
    ``open().read()`` and the digest of what it returned.

    In this layout a concurrent writer cannot change these bytes anyway - it
    has its own generation - so the check is a guard against damage rather than
    against interleaving: a truncated, zeroed or hand-edited table, or one from
    a generation whose manifest was replaced by a restore from backup.

    Unusable means the manifest names something that is not a plain filename,
    either file is absent or unreadable, either digest disagrees, either file
    will not parse, or either is missing a column this build reads. Both or
    neither: half of the answer is worse than none.

    THE COLUMN CHECK IS WHY A FUTURE SCHEMA CANNOT 500 THE DRAWER
    -------------------------------------------------------------
    A parquet file that reads perfectly well and simply does not have the
    columns this build wants - what renaming one in a later PR produces - used
    to reach ``PlaylistService._build_refs`` and raise ``AttributeError`` out
    of ``row.playlist_id``. That is a 500 on ``GET /api/tracks/{id}``, which is
    the request the drawer makes for everything, so a schema change would have
    broken track detail entirely rather than merely losing playlists.

    A SUPERSET is fine and deliberate: a later schema that ADDS a column is
    still readable by this one, and only a column this build needs and cannot
    find is a refusal.
    """
    data_dir = Path(data_dir)
    wanted = (
        (provenance.playlists_file, provenance.playlists_sha256, PLAYLIST_COLUMNS),
        (provenance.membership_file, provenance.membership_sha256, MEMBERSHIP_COLUMNS),
    )

    frames = []
    for name, expected_sha256, columns in wanted:
        path = _resolve_table(data_dir, name)
        if path is None:
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            return None
        frame = pd.read_parquet(io.BytesIO(raw))
        if not set(columns).issubset(frame.columns):
            return None
        frames.append(frame)

    return frames[0], frames[1]


def resolve_membership(
    membership: Sequence[Tuple[str, str]], known_track_ids
) -> Tuple[int, int]:
    """``(resolved, unresolved)`` entry counts against a set of indexed ids.

    Counts ENTRIES, not distinct tracks: an unindexed track that appears in six
    playlists is six unresolvable entries, which is what "N entries reference
    tracks not in your library" means.
    """
    known = {str(track_id) for track_id in known_track_ids}
    resolved = sum(1 for track_id, _ in membership if str(track_id) in known)
    return resolved, len(membership) - resolved
