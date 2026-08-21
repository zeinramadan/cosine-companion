#!/usr/bin/env python3
"""SetBuilder - multi-hop DJ set generation.

Wraps ``recommendations.set_generator.generate_set``, which
``ui/set_creator_tab.py`` called directly with the App's loose attributes.

Signature note. The plan sketched ``.build(seed_track_id, length, **params)``
but also instructed "mirror the current set_generator signature exactly; read
it before designing". Those conflict: ``generate_set`` takes a
``{position: track_id}`` anchor map rather than a single seed, and returns
``SetTrack`` objects carrying ``position``, ``is_anchor``, ``icon`` and
``display_name`` that a ``Recommendation`` cannot express. The mirroring
instruction wins, because collapsing to a single seed or to Recommendation
would change what the Set Creator tab can render.

The per-hop policy inside ``generate_set`` is unchanged: ``topk=100,
final_top=50`` candidates, the top 20 re-scored by
``0.8 * cos(prev -> cand) + 0.2 * cos(cand -> next)``.

This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.
"""

from typing import Dict, List, Optional

from recommendations.models import SetTrack
from recommendations.set_generator import generate_set


class SetBuilder:
    """Builds a complete DJ set around anchor tracks at fixed positions."""

    def __init__(self, library):
        """Bind to a LibrarySession, read live so index rebuilds are seen."""
        self.library = library

    def build(
        self,
        anchor_tracks: Dict[int, str],
        total_tracks: int,
        exclude_tracks: Optional[List[str]] = None,
    ) -> List[SetTrack]:
        """Generate a set of ``total_tracks`` around ``{position: track_id}`` anchors.

        Raises ValueError when there are no anchors, or when an anchor position
        exceeds ``total_tracks`` - both propagate to the Set Creator tab's
        "Generation Error" dialog exactly as before.

        ONE CAPTURE PER BUILD, VIA ``snapshot()``. THIS IS AN IDIOM, NOT A FIX.
        ``self.library.meta_ix``, ``.emb_ix`` and ``.index`` are three separate
        reads of three separately rebound attributes, and ``delete_tracks``
        rebinds all of them in sequence (``library_session.py:203-224``). A
        delete interleaved with those reads hands ``generate_set`` a
        post-delete ``meta_ix`` with a pre-delete ``index`` - a set ranked
        against vectors the metadata no longer has a row for. Nothing in the
        Tkinter app could interleave that way, because the delete and the build
        are both on the Tk main thread; the web layer serves requests off it,
        and the sibling PR that adds a Library destination makes DELETE
        reachable while a set is being built.

        THE CHANGE DOES NOT CLOSE THAT WINDOW, AND AN EARLIER VERSION OF THIS
        DOCSTRING WRONGLY SAID IT NARROWED IT. It claimed the capture "makes the
        window ONE per build instead of three". That is false: the previous code
        passed the three properties as three arguments of ONE call, which is
        already one window per build. ``snapshot()`` is itself a plain sequence
        of unlocked attribute reads (``library_session.py:149-166``, whose own
        docstring says so), so the same three objects are still read one after
        another. The window MOVED from this function into ``snapshot()``; it did
        not get smaller.

        Reproduced, not theorised, on the twelve-track fixture library:

        * a delete landing between two of the reads ``snapshot()`` performs
          turns ``['f01','f02','f03','f05','f04']`` into
          ``['f01','f02','f03','f12','f10']``;
        * a reader that lands between ``delete_tracks``' ``meta_ix`` rebind
          (``library_session.py:202``) and its index rebuild (``:220``) gets
          ``KeyError: 'f05'`` out of this method.

        Inventory §6.6 records both as a known, declared limitation.

        WHAT THE CAPTURE IS ACTUALLY WORTH: it adopts the idiom this codebase
        already uses, so ``SetBuilder`` and ``ExportService``
        (``export_service.py:132``) read the library the same way and there is
        one place to fix rather than two. ``ExportService`` additionally went
        from one window per SEED to one per run, because it re-read the
        properties for every seed; there is no equivalent win here, because
        ``build`` read once either way.

        The fix is atomic publish inside ``LibrarySession`` - one immutable
        snapshot object rebound as a unit, so a reader's single attribute read
        is atomic by construction, which is the shape PR #15 (the transitions
        vector cache), PR #17 (``_Generation`` + ``MappingProxyType``) and
        PR #19 (generation files behind a manifest pointer) already use. It is
        deliberately NOT in this PR: it touches ``delete_tracks``, which the
        sibling Library PR rewrites, and a core-services concurrency change
        deserves its own review rather than riding inside a UI destination.
        """
        library = self.library.snapshot()

        return generate_set(
            anchor_tracks,
            total_tracks,
            library.meta_ix,
            library.emb_ix,
            library.index,
            exclude_tracks=exclude_tracks,
        )
