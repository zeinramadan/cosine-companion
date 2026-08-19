#!/usr/bin/env python3
"""Importing the playlist tables from a Rekordbox XML export.

The write half of the playlist feature, kept apart from ``PlaylistService`` so
that the read path - the one on every drawer open - imports neither lxml nor
the parser. ``PlaylistService`` never calls anything here: spec §6.4 says
**prompt, never auto-import**, so an import only ever happens because the user
ran the CLI command or an indexing run finished.

WHAT IS PERSISTED, AND WHAT IS NOT
----------------------------------
Every ``<TRACK Key>`` in the export is written to the membership table,
including the ones naming a track CoCo has not indexed. The tables are a
faithful record of the XML; whether a given entry resolves is a question about
``meta.parquet``, and ``meta.parquet`` changes underneath them. Filtering at
import time would mean a reindex that adds those tracks leaves their
memberships permanently missing until somebody remembers to re-import.

THE UNRESOLVABLE ENTRIES ARE REPORTED, NOT HIDDEN
-------------------------------------------------
Measured against the 1,532-track library in this worktree: **153 of 4,669
entries (3.28%)** name a Rekordbox track CoCo has not indexed, because the
export holds 1,610 tracks. (Spec §6.5 and the plan both say 514 / 11.01%; that
was measured against the older 1,307-track library and is superseded - the
library has since been reindexed. The shape of the finding is unchanged.)

Per spec §6.5 this is a line in the summary - *"N entries reference tracks not
in your library - reindex to include them"* - and not an error. Dropping them
silently would make playlist counts quietly wrong.

NOTHING HERE WRITES ``meta.parquet``, ``embeddings.parquet``, ``index.npy`` OR
``ids.json``. It reads ``meta.parquet`` to count, and writes only the playlist
manifest and the two table files of its own generation.

This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from core.playlist_store import (
    PlaylistProvenance,
    committed_table_paths,
    read_source,
    resolve_membership,
    write_playlist_tables,
)


@dataclass(frozen=True)
class PlaylistImportSummary:
    """What one import did, in the terms spec §6.5 asks to be reported.

    ``entries_unresolved`` is a count of ENTRIES, not of tracks: one unindexed
    track in six playlists is six entries, which is what the user's playlist
    counts would be short by.
    """

    source_xml: str
    playlists: int
    folders: int
    entries_total: int
    entries_resolved: int
    entries_unresolved: int
    indexed_tracks: int
    tracks_with_playlists: int
    #: Playlists whose ``KeyType`` is not ``"0"``. Their membership is by file
    #: path, which cannot be resolved to a TrackID, so they are catalogued
    #: without it. Zero on every export seen; reachable only by fixture.
    path_keyed_playlists: int
    #: Playlists whose ``Entries`` attribute disagreed with the real child
    #: count. Zero on the real export; the child count wins when they differ.
    entries_attribute_mismatches: int
    provenance: PlaylistProvenance

    @property
    def unresolved_percent(self) -> float:
        if not self.entries_total:
            return 0.0
        return 100.0 * self.entries_unresolved / self.entries_total

    def lines(self) -> List[str]:
        """The summary as the CLI prints it, one string per line.

        A list rather than a blob so the pipeline can hand each line to its
        ``report`` callback and the UI's progress plumbing sees them the same
        way it sees every other message.
        """
        out = [
            f"   Found {self.playlists} playlists in {self.folders} folders",
            f"   {self.entries_total} membership entries, "
            f"{self.entries_resolved} matched to indexed tracks",
        ]
        if self.entries_unresolved:
            out.append(
                f"   {self.entries_unresolved} entries reference tracks not in "
                f"your library - reindex to include them "
                f"({self.unresolved_percent:.2f}% of {self.entries_total})"
            )
        if self.path_keyed_playlists:
            out.append(
                f"   {self.path_keyed_playlists} playlist(s) use path-based "
                "membership (KeyType=1) and were catalogued without their tracks"
            )
        if self.entries_attribute_mismatches:
            out.append(
                f"   {self.entries_attribute_mismatches} playlist(s) declared an "
                "Entries count that disagreed with their contents; the contents won"
            )
        out.append(
            f"   {self.tracks_with_playlists} of {self.indexed_tracks} indexed "
            "tracks are in at least one playlist"
        )
        return out


def _indexed_track_ids(data_dir) -> Tuple[set, int]:
    """The track ids in ``meta.parquet``, or an empty set when there is none.

    Read, never written. An absent or unreadable ``meta.parquet`` is the
    "imported playlists before indexing" case: every entry is unresolvable, and
    saying so is more useful than refusing to import.
    """
    meta_pq = Path(data_dir) / "meta.parquet"
    if not meta_pq.is_file():
        return set(), 0

    import pandas as pd

    try:
        meta = pd.read_parquet(meta_pq, columns=["track_id"])
    except Exception:  # noqa: BLE001 - an unreadable index is not this job's error
        return set(), 0

    ids = {str(track_id) for track_id in meta["track_id"]}
    return ids, len(ids)


def import_playlists(
    xml_path, data_dir=None, now=None
) -> PlaylistImportSummary:
    """Parse ``xml_path``'s playlists and commit a generation under ``data_dir``.

    Args:
        xml_path: the Rekordbox XML export to read.
        data_dir: where the tables go. ``None`` uses the configured directory.
        now: injectable clock for ``imported_at``, so a test can assert the
            recorded timestamp rather than merely that one is present.

    Deterministic for an unchanged file apart from ``imported_at``: the ids are
    minted from the playlist paths (see
    ``processing.playlist_parser.mint_playlist_id``), so re-importing the same
    export writes byte-identical tables - under a new generation's names, since
    a committed table file is never written twice.
    """
    # Imported here, not at module scope. The parser lives under
    # ``processing``, whose package __init__ pulls in the indexing pipeline;
    # keeping it local means merely importing this service costs nothing and
    # does not require lxml to be installed.
    from processing.playlist_parser import parse_playlists_bytes

    xml_path = Path(xml_path).resolve()
    if data_dir is None:
        from config import DATA

        data_dir = DATA
    data_dir = Path(data_dir)

    # ONE read, hashed and parsed. The export used to be opened twice - once
    # by the parser and once by the digest - and Rekordbox rewrites this file
    # whenever the user re-exports, so a re-export landing between the two
    # reads left the tables holding one version and the manifest recording the
    # digest of another. ``staleness()`` then said "fresh" about data that did
    # not match the file on disk, which is precisely the lie the manifest
    # exists to make impossible. 1.5 MB in memory is free.
    data, sha256, size_bytes, mtime = read_source(xml_path)
    parsed = parse_playlists_bytes(data)
    membership = parsed.membership

    stamp = now if now is not None else datetime.now(timezone.utc)
    provenance = PlaylistProvenance(
        source_xml=str(xml_path),
        source_sha256=sha256,
        source_bytes=size_bytes,
        source_mtime=mtime,
        imported_at=stamp.isoformat(),
        playlist_count=len(parsed.playlists),
        membership_count=len(membership),
    )

    # The record that comes back is the one on disk: it carries the names and
    # digests of the two tables just committed, which are only knowable after
    # the write.
    provenance = write_playlist_tables(
        data_dir, parsed.playlists, membership, provenance
    )

    indexed, indexed_count = _indexed_track_ids(data_dir)
    resolved, unresolved = resolve_membership(membership, indexed)
    tracks_with_playlists = len(
        {track_id for track_id, _ in membership if track_id in indexed}
    )

    return PlaylistImportSummary(
        source_xml=str(xml_path),
        playlists=len(parsed.playlists),
        folders=len(parsed.folder_paths),
        entries_total=len(membership),
        entries_resolved=resolved,
        entries_unresolved=unresolved,
        indexed_tracks=indexed_count,
        tracks_with_playlists=tracks_with_playlists,
        path_keyed_playlists=len(parsed.unsupported_key_type),
        entries_attribute_mismatches=len(parsed.entries_attribute_mismatch),
        provenance=provenance,
    )


def playlist_tables_exist(data_dir=None) -> bool:
    """Whether a committed generation is on disk. The CLI words its output by it.

    Asks the manifest rather than probing for filenames: the tables are named
    by the manifest and nothing else knows what they are called, so "are the
    files there" and "is there an import" are the same question asked one way.
    """
    paths = committed_table_paths(data_dir)
    return paths is not None and all(path.is_file() for path in paths)
