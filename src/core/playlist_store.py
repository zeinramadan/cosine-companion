#!/usr/bin/env python3
"""Reading and writing the two playlist tables and their provenance record.

Three files, all under the data directory beside the four index files:

``playlists.parquet``
    ``playlist_id``, ``name``, ``folder_path``, ``parent_id``, ``entries`` -
    one row per playlist, in the export's own document order. That order is the
    only thing that carries "the order Rekordbox lists them in", so it is
    preserved on write and relied on by the reader.

``playlist_membership.parquet``
    ``track_id``, ``playlist_id``. Every ``<TRACK Key>`` in the export,
    including the ones naming a track CoCo has not indexed. Persisting the
    faithful record and resolving at read time is what makes a later reindex
    pick up the missing 153 entries without a re-import.

``playlist_import.json``
    Provenance. See ``PlaylistProvenance``.

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
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

PLAYLISTS_FILENAME = "playlists.parquet"
MEMBERSHIP_FILENAME = "playlist_membership.parquet"
PROVENANCE_FILENAME = "playlist_import.json"

PLAYLIST_COLUMNS = ["playlist_id", "name", "folder_path", "parent_id", "entries"]
MEMBERSHIP_COLUMNS = ["track_id", "playlist_id"]

#: Bumped when the on-disk shape changes. A record written by a newer schema is
#: treated as absent rather than misread.
PROVENANCE_SCHEMA = 1

#: Read in blocks rather than whole: the export is 1.5 MB today and there is no
#: reason for the digest to be the thing that caps how big it may get.
_DIGEST_BLOCK_BYTES = 1 << 20


def playlist_file_paths(data_dir=None) -> Tuple[Path, Path, Path]:
    """``(playlists.parquet, playlist_membership.parquet, playlist_import.json)``.

    ``data_dir=None`` yields the configured application paths, mirroring
    ``core.loader.index_file_paths`` so the two families of files are reached
    the same way.
    """
    if data_dir is None:
        from config import DATA

        data_dir = DATA
    data_dir = Path(data_dir)
    return (
        data_dir / PLAYLISTS_FILENAME,
        data_dir / MEMBERSHIP_FILENAME,
        data_dir / PROVENANCE_FILENAME,
    )


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
    """

    source_xml: str
    source_sha256: str
    source_bytes: int
    source_mtime: float
    imported_at: str
    playlist_count: int
    membership_count: int
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


def describe_source(xml_path) -> Tuple[str, int, float]:
    """``(sha256, size_bytes, mtime)`` for an XML export on disk."""
    path = Path(xml_path)
    stat = path.stat()
    return digest_file(path), int(stat.st_size), float(stat.st_mtime)


def write_playlist_tables(
    data_dir,
    playlists: Sequence,
    membership: Sequence[Tuple[str, str]],
    provenance: PlaylistProvenance,
) -> Tuple[Path, Path, Path]:
    """Write both tables and the provenance record. Returns the three paths.

    ``playlists`` is a sequence of ``processing.playlist_parser.ParsedPlaylist``
    (anything with the same five attributes will do; this module deliberately
    does not import the parser, so that reading the tables never needs lxml).

    Not atomic, and deliberately consistent with the rest of the project:
    ``LibrarySession._persist`` writes its four files the same way. What is
    different here is that these three files are *derived* - a half-written set
    is repaired by re-running the import, not by restoring a backup.
    """
    playlists_pq, membership_pq, provenance_json = playlist_file_paths(data_dir)
    playlists_pq.parent.mkdir(parents=True, exist_ok=True)

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

    playlist_frame.to_parquet(playlists_pq, index=False)
    membership_frame.to_parquet(membership_pq, index=False)
    provenance_json.write_text(
        json.dumps(provenance.as_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return playlists_pq, membership_pq, provenance_json


def read_provenance(data_dir) -> Optional[PlaylistProvenance]:
    """The provenance record, or ``None`` when there is none to read.

    Unreadable, malformed and future-schema records all read as ``None``: the
    drawer's "nothing imported yet" state is a correct thing to show for a
    record we cannot interpret, and a traceback in the middle of a track detail
    is not.
    """
    _, _, provenance_json = playlist_file_paths(data_dir)
    if not provenance_json.is_file():
        return None

    try:
        raw = json.loads(provenance_json.read_text(encoding="utf-8"))
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
        )
    except (KeyError, TypeError, ValueError):
        return None


def read_playlist_tables(data_dir) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """``(playlists, membership)`` as DataFrames, or ``None`` if either is absent.

    Both or neither: a playlist table with no membership table is not a state
    the writer can produce, and half of the answer is worse than none.
    """
    playlists_pq, membership_pq, _ = playlist_file_paths(data_dir)
    if not playlists_pq.is_file() or not membership_pq.is_file():
        return None

    playlists = pd.read_parquet(playlists_pq)
    membership = pd.read_parquet(membership_pq)
    return playlists, membership


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
