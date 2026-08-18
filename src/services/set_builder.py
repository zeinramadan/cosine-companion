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
        """
        return generate_set(
            anchor_tracks,
            total_tracks,
            self.library.meta_ix,
            self.library.emb_ix,
            self.library.index,
            exclude_tracks=exclude_tracks,
        )
