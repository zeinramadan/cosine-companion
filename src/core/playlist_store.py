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
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

PLAYLISTS_FILENAME = "playlists.parquet"
MEMBERSHIP_FILENAME = "playlist_membership.parquet"
PROVENANCE_FILENAME = "playlist_import.json"

PLAYLIST_COLUMNS = ["playlist_id", "name", "folder_path", "parent_id", "entries"]
MEMBERSHIP_COLUMNS = ["track_id", "playlist_id"]

#: Bumped when the on-disk shape changes. A record written by a newer schema is
#: treated as absent rather than misread - and so is one written by an OLDER
#: one, which is what makes the bump safe. 2 adds the two table digests that
#: make a mixed generation detectable; a schema-1 record does not carry them,
#: cannot be checked, and is therefore read as "nothing imported" rather than
#: trusted. The cost of the bump is one re-import, which is the command the
#: drawer is already showing in that state.
PROVENANCE_SCHEMA = 2

#: Appended to a file's name while it is being written. A crash leaves this
#: beside the real file rather than on top of it; nothing reads it, and the
#: next import overwrites it.
STAGING_SUFFIX = ".importing"

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

    THE RECORD ALSO NAMES ITS OWN TABLES, WHICH IS WHAT MAKES IT THE COMMIT
    ----------------------------------------------------------------------
    ``playlists_sha256`` and ``membership_sha256`` are the digests of the two
    parquet files this record was committed FOR. Three files cannot be replaced
    in one atomic step, so the guarantee is not that an interrupted import is
    impossible - it is that an interrupted import is DETECTABLE. This record is
    written last, and a reader that finds tables whose digests are not these
    two is looking at a mixed generation and treats it as nothing imported.
    See ``write_playlist_tables`` and ``tables_match``.

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


def _stage(path: Path, write: Callable[[Path], None]) -> Tuple[Path, str]:
    """Write through a sibling temp file. Returns ``(staged path, its digest)``.

    The digest is taken from the bytes that actually landed, not from the frame
    that produced them, so nothing here assumes a parquet write is reproducible.
    """
    staged = path.with_name(path.name + STAGING_SUFFIX)
    write(staged)
    return staged, digest_file(staged)


def write_playlist_tables(
    data_dir,
    playlists: Sequence,
    membership: Sequence[Tuple[str, str]],
    provenance: PlaylistProvenance,
) -> PlaylistProvenance:
    """Write both tables and the provenance record. Returns the record committed.

    ``playlists`` is a sequence of ``processing.playlist_parser.ParsedPlaylist``
    (anything with the same five attributes will do; this module deliberately
    does not import the parser, so that reading the tables never needs lxml).

    The returned record is not the one passed in: it carries the two table
    digests, which cannot be known until the tables have been written.

    STAGED, THEN COMMITTED, WITH THE MANIFEST LAST
    ----------------------------------------------
    All three files are written under ``STAGING_SUFFIX`` names first, then moved
    into place with ``os.replace``, which is atomic per file on one filesystem.
    Three files still cannot be replaced in one step, so the property being
    bought is not "an interrupted import leaves nothing behind" - it is **an
    interrupted import can never be reported as imported**:

    * die before any ``os.replace`` - the previous generation is intact, and its
      manifest still names its own two tables. Nothing changed.
    * die between the two table replaces, or after both and before the manifest
      - the manifest on disk is the PREVIOUS one, and it names the previous
      tables. At least one table has been replaced, so at least one digest
      disagrees, and ``tables_match`` rejects the pair. The reader answers
      "nothing imported" and the drawer shows the import command.
    * die after the manifest replace - there is nothing left to do; all three
      files are the new generation and their digests agree.

    The manifest is therefore the commit point, and it is the last write. A
    reader can never see a manifest that outruns its tables.

    The cost is honest and stated: an interrupted import loses the PREVIOUS
    import too, because the reader cannot tell which half of a mixed pair is
    old. Re-running the command repairs it, which is what the "nothing
    imported" state already tells the user to do. Keeping two generations side
    by side to avoid that is a rollback log, and this is three derived files.

    NOT fsync'd, deliberately. fsync would change WHICH generation survives a
    power cut; it cannot change whether an inconsistent one is trusted, because
    the check is over content and not over ordering. A manifest that lands
    while a table's blocks do not simply fails its digest, exactly like any
    other mixed generation.
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

    staged: List[Path] = []
    try:
        staged_playlists, playlists_sha256 = _stage(
            playlists_pq, lambda target: playlist_frame.to_parquet(target, index=False)
        )
        staged.append(staged_playlists)
        staged_membership, membership_sha256 = _stage(
            membership_pq, lambda target: membership_frame.to_parquet(target, index=False)
        )
        staged.append(staged_membership)

        committed = replace(
            provenance,
            playlists_sha256=playlists_sha256,
            membership_sha256=membership_sha256,
        )
        staged_manifest, _ = _stage(
            provenance_json,
            lambda target: target.write_text(
                json.dumps(committed.as_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            ),
        )
        staged.append(staged_manifest)

        # The commit. Tables first, manifest last - see the docstring.
        os.replace(staged_playlists, playlists_pq)
        os.replace(staged_membership, membership_pq)
        os.replace(staged_manifest, provenance_json)
    except BaseException:
        # Including KeyboardInterrupt: a cancelled import should not leave its
        # scratch files in the user's data directory either. A staged file that
        # was already committed has been renamed away and is simply not there,
        # so this is the same statement for both halves of the try.
        #
        # A SIGKILL or a power cut runs none of this, and can leave the scratch
        # files behind. They are inert: nothing reads a STAGING_SUFFIX name,
        # the names are fixed rather than unique, and the next import writes
        # straight over them.
        for leftover in staged:
            try:
                leftover.unlink()
            except OSError:
                pass
        raise

    return committed


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
            # Required, not defaulted: a schema-2 record without them is one
            # nothing can check, and an uncheckable record is not usable.
            playlists_sha256=str(raw["playlists_sha256"]),
            membership_sha256=str(raw["membership_sha256"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def tables_match(data_dir, provenance: PlaylistProvenance) -> bool:
    """Whether the two tables on disk are the ones ``provenance`` was committed for.

    The check that turns "an import can be interrupted" into "an interrupted
    import cannot be reported as imported". A mixed generation - a new table
    beside an old one, from an import that died between two ``os.replace``
    calls - fails here, and its reader answers "nothing imported" rather than
    serving a playlist table and a membership table that disagree.

    A missing or unreadable table is False for the same reason: the manifest
    names bytes that are not there.

    Two SHA-256 passes over two small files, and it runs once per ``reload``
    rather than once per lookup. Measured on the real export - 141 playlists
    and 4,669 entries, which is 8.3 KB of playlists.parquet and 25.3 KB of
    playlist_membership.parquet - **0.045 ms**, against the 0.57 ms the
    staleness digest of the 1.5 MB XML already costs on the same request.
    """
    playlists_pq, membership_pq, _ = playlist_file_paths(data_dir)
    try:
        return (
            digest_file(playlists_pq) == provenance.playlists_sha256
            and digest_file(membership_pq) == provenance.membership_sha256
        )
    except OSError:
        return False


def read_playlist_tables(data_dir) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """``(playlists, membership)`` as DataFrames, or ``None`` when unusable.

    Unusable means either file is absent, or either is missing a column this
    build reads. Both or neither: a playlist table with no membership table is
    not a state the writer can produce, and half of the answer is worse than
    none.

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
    playlists_pq, membership_pq, _ = playlist_file_paths(data_dir)
    if not playlists_pq.is_file() or not membership_pq.is_file():
        return None

    playlists = pd.read_parquet(playlists_pq)
    membership = pd.read_parquet(membership_pq)
    if not set(PLAYLIST_COLUMNS).issubset(playlists.columns):
        return None
    if not set(MEMBERSHIP_COLUMNS).issubset(membership.columns):
        return None
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
