#!/usr/bin/env python3
"""The ranking policy, in one place.

Before this module the same two steps were written out three times - in
``ui/recommendations_tab.py``, and twice in ``recommendations/playlist_exporter.py``:

    recs = recommend_for(seed, meta_ix, emb_ix, idx, topk=500, final_top=200)
    recs.sort(key=lambda x: x["cosine"], reverse=True)
    recs = recs[:count]

The service layer's first attempt consolidated them *in the service*, which left
the two exporter copies still in the source and merely unreachable. The policy
belongs in the pure layer, where the exporters, the Explore tab and
``ExportService`` can all call it, so this module is the single definition and
the copies are gone.

**What the composition means.** The two sorts are not redundant. Step one ranks
by the weighted score ``0.7*cosine + 0.2*key_compat + 0.1*bpm_compat`` and keeps
the best ``final_top``; step two re-orders exactly those by raw cosine. So the
*membership* of the result is decided by the weighted score and the *order* by
cosine - it is neither a pure-score nor a pure-cosine ranking, and it is
preserved exactly. ``tests/services/test_explore_session.py`` pins this against
committed golden values.

Both ``list.sort`` calls are stable, so candidates that tie on cosine keep the
score ordering ``recommend_for`` produced.
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from core.index_builder import NumpyCosIndex
from recommendations.engine import recommend_for

# The candidate-pool configuration the Explore tab and both exporters use.
# recommend_for's own defaults (DEFAULT_TOPK=200, DEFAULT_FINAL_TOP=15) are the
# CLI/library defaults and are deliberately different.
RANKING_TOPK = 500
RANKING_FINAL_TOP = 200


def ranked_recommendations(
    track_id: str,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx: NumpyCosIndex,
    topk: int = RANKING_TOPK,
    final_top: int = RANKING_FINAL_TOP,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return recommendations for ``track_id``, ordered by cosine descending.

    Args:
        track_id: Seed track ID.
        meta_ix: Metadata DataFrame indexed by track_id.
        emb_ix: Embeddings DataFrame indexed by track_id.
        idx: Exact cosine index for similarity search.
        topk: Cosine-similarity candidates to retrieve.
        final_top: How many of those to keep, by weighted score.
        limit: Optional final truncation, applied after the cosine re-sort.
            The exporters pass the user's per-track count here; the Explore tab
            passes nothing and truncates at render time instead.

    Returns:
        The same list of dictionaries ``recommend_for`` produces, re-ordered.
    """
    recommendations = recommend_for(
        track_id, meta_ix, emb_ix, idx, topk=topk, final_top=final_top
    )

    # Sort by cosine similarity (pure audio similarity) and take top N
    recommendations.sort(key=lambda x: x["cosine"], reverse=True)

    if limit is None:
        return recommendations
    return recommendations[:limit]
