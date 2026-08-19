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

THE WRITER IS ANOTHER PROCESS, SO THE CACHE IS INVALIDATED FROM DISK
--------------------------------------------------------------------
``web/host.py:77`` builds one of these inside ``build_api`` and the window
holds it until it closes, while ``import-playlists`` - the command this service
tells the user to run - is a different process entirely. Nothing inside this
process is notified when that command commits, so an index cached behind a
"have I loaded yet" flag is an index that never changes again: the drawer shows
its import call-to-action, the user runs the command, it succeeds, and the
drawer keeps showing it until the app is restarted. The staleness prompt has
the same shape and is worse - it detects the re-export and then names a command
whose effect it cannot see.

So the cache is keyed on the pointer itself. Every accessor re-reads
``playlist_import.json`` and rebuilds only when those bytes differ from the
ones the current index was built from; see ``_current``.

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
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Tuple

from core.playlist_store import (
    PlaylistProvenance,
    digest_file,
    playlist_manifest_path,
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


@dataclass(frozen=True)
class _Generation:
    """One whole answer, captured together: the pointer, the record, the rows.

    WHY THE THREE OF THEM ARE ONE OBJECT
    ------------------------------------
    ``web/server.py`` is a ``ThreadingHTTPServer`` and ``web/host.py:77``
    builds ONE ``PlaylistService`` for the life of the window, so every drawer
    open is a request THREAD calling into the same instance. Held as three
    attributes, a generation can be observed half-swapped: a reader that has
    taken the provenance and not yet taken the rows gets the next generation's
    rows when a reload lands in between, and reports a manifest naming one
    export beside the playlists of another. That is precisely the blend
    ``core.playlist_store`` refuses to write to disk, reassembled in memory at
    the only layer the user can see - and a reader arriving while the fields
    were blanked for a rebuild was told nothing had been imported at all.

    So the three travel together and never change: ``reload`` builds one of
    these privately and publishes it with a SINGLE rebind of ``_state``. A
    reader takes ONE reference at the top of its call and reads every field
    from that reference, so what it read is what it keeps. No lock is needed
    on either side, because there is no window in which a reader can see a
    partly-updated generation - there is no partly-updated generation. It is
    the shape ``LibrarySnapshot`` uses next door, for the same reason.

    ``by_track`` is wrapped in a ``MappingProxyType`` so "never changes" is
    enforced rather than promised: a future accessor cannot mutate a
    generation that other threads are still reading from.
    """

    #: The manifest bytes this generation was built from, and the cache key:
    #: a reader rebuilds when the pointer on disk is no longer these bytes.
    #: ``None`` when there was no reading it.
    manifest: Optional[bytes]
    #: ``None`` for every "nothing imported" state, of which there are several
    #: - see ``PlaylistService.reload``. The rows are then empty too.
    provenance: Optional[PlaylistProvenance]
    by_track: Mapping[str, Tuple[PlaylistRef, ...]]
    #: False only for the sentinel below, which is what a service holds before
    #: it has looked at the disk at all. Distinct from "looked, found nothing":
    #: that one has a manifest key and must not be rebuilt on every access.
    loaded: bool = True

    @classmethod
    def nothing_imported(cls, manifest: Optional[bytes]) -> "_Generation":
        """The answer for every state in which there are no usable tables."""
        return cls(manifest=manifest, provenance=None, by_track=MappingProxyType({}))


#: What a freshly constructed service holds. Construction touches no disk, so
#: this cannot be a real generation; ``loaded=False`` is what makes the first
#: accessor read rather than trust a ``manifest`` of ``None``.
_UNLOADED = _Generation(
    manifest=None, provenance=None, by_track=MappingProxyType({}), loaded=False
)


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
        #: The whole cached generation, in ONE attribute so that a rebind
        #: cannot be observed half-done. Never mutated: ``reload`` replaces it.
        #: See ``_Generation``, and ``_current`` for how readers take it.
        self._state: _Generation = _UNLOADED

    # -- loading -----------------------------------------------------------

    def reload(self) -> None:
        """Re-read both tables, rebuild the reverse index, publish the result.

        ONE REBIND, AND NOTHING HALF-DONE BEFORE IT
        -------------------------------------------
        The whole generation is built into a private ``_Generation`` and
        published by the single assignment at the end. Until that line runs,
        this service still answers - completely and correctly - from the
        generation it already had, and a request thread that arrives mid-
        rebuild is served the old one rather than an empty one. The previous
        shape blanked three attributes at the top and refilled them at the
        bottom, and both edges of that window were visible to the
        ``ThreadingHTTPServer`` next door: a reader inside it was told nothing
        had been imported, and a reader that straddled it got one generation's
        manifest beside another's rows.

        Every failure below is therefore a ``return`` of a COMPLETE state - the
        "nothing imported" answer the drawer already knows how to render -
        rather than a return that leaves half an assignment behind. A function
        whose early exit has to remember to undo something is a function that
        will one day forget, and the thing it would leak into is
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

        THE POINTER IS READ FIRST, AND KEPT
        -----------------------------------
        The manifest's bytes are captured BEFORE anything is parsed out of
        them, and become the key this generation is cached against. Before, and
        not after, because the two orders fail differently: a writer committing
        between the two reads leaves this service holding the NEW tables under
        the OLD key, so the next accessor reloads once more and converges,
        which costs one wasted rebuild. Capturing the key afterwards would file
        the new pointer beside the old rows and serve them for the life of the
        process - the failure this is here to remove, reintroduced one line
        further down.
        """
        self._state = self._build()

    def _build(self) -> _Generation:
        """Read the disk and return one whole generation. Publishes nothing."""
        manifest = self._manifest_bytes()

        provenance = read_provenance(self.data_dir)
        if provenance is None:
            return _Generation.nothing_imported(manifest)

        try:
            tables = read_playlist_tables(self.data_dir, provenance)
        except Exception:  # noqa: BLE001 - a corrupt table is "nothing imported"
            return _Generation.nothing_imported(manifest)
        if tables is None:
            return _Generation.nothing_imported(manifest)

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
            return _Generation.nothing_imported(manifest)

        return _Generation(
            manifest=manifest,
            provenance=provenance,
            by_track=MappingProxyType(by_track),
        )

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

    def _manifest_bytes(self) -> Optional[bytes]:
        """The pointer's raw bytes, or ``None`` when there is no reading it.

        ``os.replace`` is atomic per file, so this returns one whole manifest
        or another - never a torn one - and never blocks a writer.
        """
        try:
            return playlist_manifest_path(self.data_dir).read_bytes()
        except OSError:
            return None

    def _current(self) -> _Generation:
        """The generation to answer from, rebuilt first if the pointer moved.

        RETURNS THE STATE, RATHER THAN LEAVING IT ON ``self``
        ----------------------------------------------------
        Every caller below reads its fields off THIS return value and
        never off ``self`` again, which is what makes one call one whole
        observation. Handing back the object closes the alternative by
        construction: there is no attribute left for a caller to re-read,
        so a caller cannot accidentally take its second field from a
        generation another request thread published in between.

        WHY THE BYTES, AND NOT mtime-AND-SIZE
        -------------------------------------
        The same argument ``PlaylistProvenance`` makes about the export, and
        here it is not even a judgement call: re-importing an unchanged export
        writes a manifest of *identical length*, because every field that
        differs is fixed-width - a 32-hex generation in each of the two
        filenames, two 64-hex digests, unchanged counts, and an ISO timestamp
        that is the same length whatever it says. Size can therefore never
        notice a re-import, and on a filesystem whose mtime granularity is a
        second, two imports inside the same second are indistinguishable as
        well. That is a false "fresh", which is the one answer this service is
        not allowed to give.

        WHY EVERY ACCESS, AND NOT A POLL OR AN EXPLICIT REFRESH
        -------------------------------------------------------
        A poll needs a clock and a thread and still answers late; an explicit
        refresh needs something in THIS process to know that a command in
        ANOTHER process has finished, which is exactly what nothing here knows.
        Checking on access is the only one of the three that cannot be wrong,
        and it is affordable. Measured against the real library: **14.5 us** to
        read the 757-byte manifest, against the **0.54 ms** SHA-256 of the
        1.5 MB export that ``staleness()`` already spends on the same call
        path. Under 3% of a cost the drawer is paying anyway, and ~0.1% of the
        ~15 ms request it is part of. ``lookup`` - which is what the drawer's
        request actually calls - checks once, not once per field.

        A rebuild is not free (two parquet files, ~66 KB on the real export),
        but it happens only when the pointer actually changed, which is once
        per import.
        """
        state = self._state
        if state.loaded and self._manifest_bytes() == state.manifest:
            return state
        state = self._build()
        # One rebind, of one immutable object. Two request threads racing here
        # both publish a whole generation, and whichever lands second wins;
        # neither can be seen half-published, and each answers from the state
        # it built rather than from whatever ``self`` holds afterwards.
        self._state = state
        return state

    # -- read accessors ----------------------------------------------------

    @property
    def imported(self) -> bool:
        """Whether a usable pair of tables was found."""
        return self._current().provenance is not None

    @property
    def provenance(self) -> Optional[PlaylistProvenance]:
        return self._current().provenance

    @property
    def track_count(self) -> int:
        """How many distinct tracks appear in the membership table."""
        return len(self._current().by_track)

    def staleness(self) -> StalenessVerdict:
        """Whether the XML on disk still matches what was imported.

        Recomputes the digest every call rather than caching against mtime; see
        ``PlaylistProvenance``'s docstring for why an mtime fast path would
        reintroduce the false "fresh" the digest exists to rule out. 0.53 ms on
        the real 1.5 MB export.
        """
        return self._staleness_of(self.provenance)

    @staticmethod
    def _staleness_of(provenance) -> StalenessVerdict:
        """The verdict for a provenance the caller has already settled on.

        Split out so ``lookup`` can ask about the record it is already holding
        instead of going back through ``self.provenance``, which would re-check
        the pointer and could answer about a different generation.
        """
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
        state = self._current()
        if state.provenance is None:
            return None
        return state.by_track.get(str(track_id), ())

    def lookup(self, track_id: str) -> PlaylistLookup:
        """Everything the drawer needs for one track, in one typed result.

        ONE POINTER CHECK, AND EVERY FIELD FROM THE GENERATION IT FOUND
        ---------------------------------------------------------------
        The accessors above each re-check the manifest, which is what lets a
        long-lived service follow an import committed by another process. Built
        out of four of those calls, this result would be free to straddle a
        commit: the rows from generation A because that is what was loaded when
        ``playlists_for`` ran, and the provenance from B because the importer
        landed a microsecond later. A manifest naming one export beside rows
        that came from another is precisely the corruption
        ``core.playlist_store`` is built to make impossible, and assembling it
        here out of four individually-correct answers would put it back at the
        only layer that matters - the one the drawer renders.

        So the check happens once, at the top, and every field below is read
        out of the state that check settled on. The drawer's request is one
        question and gets one generation's answer. A commit landing while this
        runs is picked up by the next request, which is the next thing the user
        does.
        """
        state = self._current()
        provenance = state.provenance
        playlists = (
            None if provenance is None else state.by_track.get(str(track_id), ())
        )
        return PlaylistLookup(
            imported=provenance is not None,
            playlists=playlists,
            provenance=provenance,
            staleness=self._staleness_of(provenance),
        )
