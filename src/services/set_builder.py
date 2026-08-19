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

        ONE SNAPSHOT PER BUILD, not three property reads.
        ``self.library.meta_ix``, ``.emb_ix`` and ``.index`` are three separate
        reads of three separately rebound attributes. ``delete_tracks`` rebinds
        all of them in sequence (``library_session.py:203-224``), so a delete
        landing between two of these reads hands ``generate_set`` a post-delete
        ``meta_ix`` with a pre-delete ``index`` - a set ranked against vectors
        for tracks the metadata no longer has. Nothing in the Tkinter app could
        interleave that way, because the delete and the build are both on the Tk
        main thread; the web layer serves requests off it, and the sibling PR
        that adds a Library destination makes DELETE reachable while a set is
        being built.

        ``LibrarySession.snapshot()`` exists for exactly this, and
        ``ExportService`` already uses it the same way
        (``export_service.py:132``). It does not make the build atomic against a
        concurrent delete - its own docstring says the capture is itself a
        sequence of reads - it makes the window ONE per build instead of three,
        which is the guarantee the Tkinter caller had when it passed the three
        objects as arguments.
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
