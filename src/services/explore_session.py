#!/usr/bin/env python3
"""ExploreSession - seed track to ranked recommendations.

The ranking policy itself lives in ``recommendations.ranking``, not here. It
used to be written out three times - ``ui/recommendations_tab.py:236-247`` and
twice in ``recommendations/playlist_exporter.py`` - and consolidating it *in
this service* would have left both exporter copies in the source, merely
unreachable. So the policy went into the pure layer, and Explore, both
exporters and ExportService all call the same function. This class adds only
what the UI needs on top: ``Recommendation`` objects carrying ``path_local``.

Note what the policy's two steps compose into: the *membership* of the result
set is decided by the weighted score (0.7 cosine + 0.2 key + 0.1 bpm), while
the *order* is by raw cosine. It is neither pure-score nor pure-cosine ranking,
and it is preserved exactly - pinned by committed golden values in
``tests/services/test_explore_session.py``.

The three implementations were diffed before the refactor and found
behaviourally identical; the harness that measures that is committed as
``tests/manual/ranking_equivalence.py`` so the claim can be re-run rather than
merely asserted.

This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.
"""

from dataclasses import dataclass
from typing import Any, List, Optional

from config import DEFAULT_FINAL_TOP, DEFAULT_TOPK
from recommendations.ranking import ranked_recommendations


@dataclass
class Recommendation:
    """One ranked recommendation.

    Carries every field ``recommend_for`` returns, plus ``path_local``, which it
    does not - the exporter used to re-read that from ``meta_ix`` per track.
    """

    track_id: str
    artist: str
    title: str
    bpm: Optional[float]
    key: str
    path_local: str
    cosine: float
    score: float
    key_score: float
    bpm_score: float


class ExploreSession:
    """Produces ranked recommendations for a seed track."""

    def __init__(self, library):
        """Bind to a LibrarySession, read live so index rebuilds are seen."""
        self.library = library

    def recommend(
        self,
        track_id: str,
        topk: int = DEFAULT_TOPK,
        final_top: int = DEFAULT_FINAL_TOP,
    ) -> List[Recommendation]:
        """Return recommendations for ``track_id``, ordered by cosine descending.

        The Explore tab calls this with ``topk=500, final_top=200``; the
        playlist exporter uses the same configuration and then truncates to the
        user's per-track count.
        """
        results = ranked_recommendations(
            track_id,
            self.library.meta_ix,
            self.library.emb_ix,
            self.library.index,
            topk=topk,
            final_top=final_top,
        )

        return [self._to_recommendation(r) for r in results]

    def _to_recommendation(self, raw: dict) -> Recommendation:
        track = self.library.get_track(raw["track_id"]) or {}
        return Recommendation(
            track_id=raw["track_id"],
            artist=raw["artist"],
            title=raw["title"],
            bpm=raw["bpm"],
            key=raw["key"],
            path_local=track.get("path_local", ""),
            cosine=raw["cosine"],
            score=raw["score"],
            key_score=raw["key_score"],
            bpm_score=raw["bpm_score"],
        )
