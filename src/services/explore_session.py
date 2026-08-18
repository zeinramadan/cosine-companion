#!/usr/bin/env python3
"""ExploreSession - seed track to ranked recommendations.

Holds the ranking policy that was duplicated in three places:
``ui/recommendations_tab.py:236-247``, ``recommendations/playlist_exporter.py:101-116``
and ``recommendations/playlist_exporter.py:185-202``. All three ran

    recommend_for(seed, meta_ix, emb_ix, idx, topk=..., final_top=...)
    recs.sort(key=lambda x: x["cosine"], reverse=True)

then truncated by a caller-supplied count. Diffed over 60 seeds x 3 truncation
counts before this refactor: zero ordering and zero value mismatches. They are
behaviourally identical, so there was no discrepancy to arbitrate.

Note what the two steps compose into: the *membership* of the result set is
decided by the weighted score (0.7 cosine + 0.2 key + 0.1 bpm), while the
*order* is by raw cosine. Measured over 40 seeds, that differs from a pure
cosine ranking of the same candidate pool in 40/40 seeds at top-200 and 11/40
at top-25. It is neither pure-score nor pure-cosine ranking, and it is
preserved exactly.

This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.
"""

from dataclasses import dataclass
from typing import Any, List, Optional

from config import DEFAULT_FINAL_TOP, DEFAULT_TOPK
from recommendations.engine import recommend_for


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
        results = recommend_for(
            track_id,
            self.library.meta_ix,
            self.library.emb_ix,
            self.library.index,
            topk=topk,
            final_top=final_top,
        )

        # Sort by cosine similarity (pure audio similarity). Stable, so ties keep
        # the score ordering recommend_for produced.
        results.sort(key=lambda x: x["cosine"], reverse=True)

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
