#!/usr/bin/env python3
"""PlaylistService - the track -> playlists lookup, and nothing else.

The seventh service, following the six beside it: it orchestrates, the pure
layer does the work, and it holds no UI. What it owns is the reverse index -
``track_id -> [playlist, ...]`` - built once from the two tables
``services.playlist_import`` wrote, plus the verdict on whether those tables
still describe the XML on disk.

READ-ONLY, AND THAT IS THE WHOLE POINT
--------------------------------------
Spec §6.4: **prompt, never auto-import.** This service reports that the source
XML has changed; it does not act on it. A drawer that silently re-parsed a
1.5 MB file because the user happened to open a track would be a surprise, and
one whose cost lands on the wrong interaction.

DEGRADES, NEVER CRASHES
-----------------------
Every state below is reachable, and every one of them is an answer rather
than an error:

* the tables do not exist (nothing imported yet) -> ``lookup(...).imported`` is
  False and ``playlists`` is ``None``;
* the tables exist and this track is in no playlist -> ``playlists`` is an
  empty tuple. Distinct from the above, and the drawer renders them
  differently. Measured on the real export: **8 of 1,532 indexed tracks** are
  in zero playlists, so this state is reachable with real data - the spec's
  claim that every indexed track is in at least one playlist was true of the
  1,307-track library and is now false;
* the recorded ``source_xml`` is gone from disk -> ``source_missing``, with the
  provenance still shown;
* the tables are corrupt, truncated, no longer the bytes the manifest names,
  or written to a schema this build does not read -> all of them read as
  "nothing imported". Not one of them raises; ``reload`` is a funnel of guards
  and every one of them returns.

NO MODULE-LEVEL HEAVY IMPORTS
-----------------------------
pandas and pyarrow only. Nothing from ``processing`` is imported at any level,
not even lazily, because this module never parses anything - which also means
importing it does not need lxml. PR #8's blocker 0 was every service
transitively importing Essentia; ``tests/test_services_are_lightweight.py``
picks this module up automatically by globbing ``src/services/*.py``.

This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.playlist_store import (
    PlaylistProvenance,
    digest_file,
    read_playlist_tables,
    read_provenance,
)

#: What the drawer tells the user to run when nothing has been imported, and
#: again when the XML has changed. Defined here, beside the service that
#: reports the condition, so the command name has one home. The "re-import
#: now" BUTTON is PR 3b's - this PR has no write surface (plan §1).
IMPORT_COMMAND = "python src/cosine_companion.py import-playlists"


@dataclass(frozen=True)
class PlaylistRef:
    """One playlist a track belongs to, as the drawer needs it.

    ``folder_path`` is a tuple of SEGMENTS and is joined by the UI, never here.
    Two folder names in the real export contain a forward slash, so a
    pre-joined ``"Mischief / Collections/Hauls / ..."`` cannot be taken apart
    again. ``entries`` is the playlist's TOTAL size from the export, not the
    number of its tracks CoCo has indexed.
    """

    playlist_id: str
    name: str
    folder_path: Tuple[str, ...]
    entries: int

    @property
    def full_path(self) -> Tuple[str, ...]:
        return (*self.folder_path, self.name)


@dataclass(frozen=True)
class StalenessVerdict:
    """Whether the tables still describe the XML they were imported from."""

    #: The source file is not where it was imported from. Nothing can be said
    #: about freshness, and ``stale`` is False rather than True: the data is
    #: not known to be wrong, only unverifiable.
    source_missing: bool = False
    #: The file at ``source_xml`` no longer hashes to what was imported.
    stale: bool = False
    #: A sentence a human can act on, or ``""`` when everything is current.
    reason: str = ""


@dataclass(frozen=True)
class PlaylistLookup:
    """The answer for one track. A dataclass, matching the six other services.

    ``playlists`` is ``None`` when nothing has been imported and an empty tuple
    when the import happened and this track is in none - the distinction the
    API turns into ``null`` versus ``[]`` and the drawer renders as two
    different things.
    """

    imported: bool
    playlists: Optional[Tuple[PlaylistRef, ...]]
    provenance: Optional[PlaylistProvenance]
    staleness: StalenessVerdict

    @property
    def count(self) -> int:
        return 0 if self.playlists is None else len(self.playlists)


class PlaylistService:
    """Answers "which playlists is this track in?" from the imported tables."""

    def __init__(self, data_dir=None):
        """Bind to a data directory. Nothing is read until the first lookup.

        ``data_dir=None`` means the configured application directory, matching
        ``LibrarySession``. Construction touches no disk, so building the API
        on a machine with no library is free.
        """
        if data_dir is None:
            from config import DATA

            data_dir = DATA
        self.data_dir = Path(data_dir)
        self._loaded = False
        self._by_track: Dict[str, Tuple[PlaylistRef, ...]] = {}
        self._provenance: Optional[PlaylistProvenance] = None

    # -- loading -----------------------------------------------------------

    def reload(self) -> None:
        """Re-read both tables and rebuild the reverse index.

        Every failure below leaves the service in exactly the state it starts
        this method in - no provenance, no index - which is the "nothing
        imported" answer the drawer already knows how to render. That is why
        ``_provenance`` is assigned at the very END and not at the top: a
        function whose early return has to remember to undo an assignment is a
        function that will one day forget, and the thing it would leak into is
        ``GET /api/tracks/{id}``, the request every drawer open makes.

        The order is a funnel, cheapest and most decisive first:

        1. **no usable manifest** - absent, malformed, or a schema this build
           does not know. Nothing is read from the tables at all; there is
           nothing to say about bytes whose provenance cannot be read.
        2. **the files the manifest names cannot be read, do not hash to the
           digests it recorded, or have not got the columns this build reads**
           - see ``read_playlist_tables``, which reads each file's bytes ONCE
           and checks them against the manifest it was handed. The manifest is
           read here and passed down rather than looked up again: a reader that
           consults the pointer twice can be told two different things by a
           writer running in another process, which is the whole failure this
           layout removes.
        3. **the rows will not build an index** - a column of the right name
           holding something unusable.
        """
        self._loaded = True
        self._by_track = {}
        self._provenance = None

        provenance = read_provenance(self.data_dir)
        if provenance is None:
            return

        try:
            tables = read_playlist_tables(self.data_dir, provenance)
        except Exception:  # noqa: BLE001 - a corrupt table is "nothing imported"
            return
        if tables is None:
            return

        playlists, membership = tables
        try:
            refs = self._build_refs(playlists)
            by_track = self._build_reverse_index(membership, refs)
        except Exception:  # noqa: BLE001
            # Broad on purpose, and the narrow tuple that was here before is
            # the defect this replaces: it named KeyError, TypeError and
            # ValueError, and a table whose COLUMNS were not the expected ones
            # raised AttributeError out of `row.playlist_id`, straight through
            # this handler and out of the track-detail endpoint as a 500. The
            # contract of this module is that it degrades, so the handler has
            # to be the whole of what "the tables did not work out" can raise -
            # including whatever a future pandas or pyarrow decides to throw.
            return

        # Committed together, last: until here, this service reports that
        # nothing has been imported.
        self._by_track = by_track
        self._provenance = provenance

    @staticmethod
    def _build_refs(playlists) -> Dict[str, Tuple[int, PlaylistRef]]:
        """``playlist_id -> (row position, ref)``.

        The row position is kept because it is the export's own document order,
        and that is the order a DJ expects to see their playlists listed in.
        Sorting by name instead would put ``hard 1hr`` in two unrelated places.
        """
        refs: Dict[str, Tuple[int, PlaylistRef]] = {}
        for position, row in enumerate(playlists.itertuples(index=False)):
            playlist_id = str(row.playlist_id)
            refs[playlist_id] = (
                position,
                PlaylistRef(
                    playlist_id=playlist_id,
                    name=str(row.name),
                    # parquet gives a LIST<STRING> column back as a numpy
                    # array of objects, not a Python list.
                    folder_path=tuple(str(segment) for segment in row.folder_path),
                    entries=int(row.entries),
                ),
            )
        return refs

    @staticmethod
    def _build_reverse_index(membership, refs) -> Dict[str, Tuple[PlaylistRef, ...]]:
        """``track_id -> playlists``, each track's list in export order.

        Built once, in one pass, rather than filtering the membership frame per
        lookup: 4,669 rows is small, but a pandas boolean mask per drawer open
        is a scan per open for no reason.
        """
        collected: Dict[str, List[Tuple[int, PlaylistRef]]] = {}
        for row in membership.itertuples(index=False):
            entry = refs.get(str(row.playlist_id))
            if entry is None:
                # A membership row naming a playlist that is not in the
                # playlist table. The writer cannot produce this; a
                # hand-edited or half-written pair of files can.
                continue
            collected.setdefault(str(row.track_id), []).append(entry)

        return {
            track_id: tuple(ref for _, ref in sorted(entries, key=lambda item: item[0]))
            for track_id, entries in collected.items()
        }

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.reload()

    # -- read accessors ----------------------------------------------------

    @property
    def imported(self) -> bool:
        """Whether a usable pair of tables was found."""
        self._ensure_loaded()
        return self._provenance is not None

    @property
    def provenance(self) -> Optional[PlaylistProvenance]:
        self._ensure_loaded()
        return self._provenance

    @property
    def track_count(self) -> int:
        """How many distinct tracks appear in the membership table."""
        self._ensure_loaded()
        return len(self._by_track)

    def staleness(self) -> StalenessVerdict:
        """Whether the XML on disk still matches what was imported.

        Recomputes the digest every call rather than caching against mtime; see
        ``PlaylistProvenance``'s docstring for why an mtime fast path would
        reintroduce the false "fresh" the digest exists to rule out. 0.53 ms on
        the real 1.5 MB export.
        """
        provenance = self.provenance
        if provenance is None:
            return StalenessVerdict()

        source = Path(provenance.source_xml)
        try:
            current = digest_file(source)
        except OSError:
            return StalenessVerdict(
                source_missing=True,
                reason=(
                    f"{provenance.source_name} is no longer at the path it was "
                    "imported from, so its playlists cannot be checked for "
                    "changes."
                ),
            )

        if current == provenance.source_sha256:
            return StalenessVerdict()

        return StalenessVerdict(
            stale=True,
            reason=(
                f"{provenance.source_name} has changed since these playlists "
                f"were imported. Run  {IMPORT_COMMAND}  to update them."
            ),
        )

    def playlists_for(self, track_id: str) -> Optional[Tuple[PlaylistRef, ...]]:
        """This track's playlists, ``()`` if it is in none, ``None`` if no import.

        The three-way return is the contract the API and the drawer are written
        against; collapsing "nothing imported" into an empty list would make
        the drawer show "In 0 playlists" to a user who has never imported.
        """
        self._ensure_loaded()
        if self._provenance is None:
            return None
        return self._by_track.get(str(track_id), ())

    def lookup(self, track_id: str) -> PlaylistLookup:
        """Everything the drawer needs for one track, in one typed result."""
        playlists = self.playlists_for(track_id)
        return PlaylistLookup(
            imported=playlists is not None,
            playlists=playlists,
            provenance=self.provenance,
            staleness=self.staleness(),
        )
