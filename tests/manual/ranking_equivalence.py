#!/usr/bin/env python3
"""Measure that consolidating the ranking policy changed nothing.

Before PR 2 the same two steps were written out three times:

  A  ui/recommendations_tab.py:236-247   topk=500, final_top=200, no extra truncation
  B  recommendations/playlist_exporter.py:101-116   ...then [:recommendations_per_track]
  C  recommendations/playlist_exporter.py:185-202   ...same, in the combined exporter

They now all call ``recommendations.ranking.ranked_recommendations``. The module
docstring of ``services/explore_session.py`` used to *assert* that the three were
behaviourally identical over 60 seeds x 3 truncation counts; that claim was prose
only, and the committed tests covered 15 and 3 seeds. This harness is the
measurement, so the claim can be re-run instead of believed.

Each of A, B and C is reproduced verbatim below from `main`, then diffed against
the consolidated policy over the real 1,307-track library. Any mismatch in
ordering or in any float is reported and the script exits non-zero.

    PYTHONPATH=src python tests/manual/ranking_equivalence.py
    PYTHONPATH=src python tests/manual/ranking_equivalence.py --seeds 200

`data/` is only ever READ.
"""

import argparse
import os
import random
import sys
from pathlib import Path

REPO = Path(os.environ.get("COCO_REPO", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO / "src"))

from core.loader import load_all  # noqa: E402
from recommendations.engine import recommend_for  # noqa: E402
from recommendations.ranking import ranked_recommendations  # noqa: E402

TRUNCATIONS = [10, 25, 50]

FIELDS = ("track_id", "artist", "title", "bpm", "key", "score", "cosine",
          "key_score", "bpm_score")


# --- the three originals, copied from main -------------------------------

def original_a(seed, meta_ix, emb_ix, idx):
    """ui/recommendations_tab.py:236-247 (Explore tab)."""
    recommendations = recommend_for(seed, meta_ix, emb_ix, idx, topk=500, final_top=200)
    recommendations.sort(key=lambda x: x["cosine"], reverse=True)
    return recommendations


def original_b(seed, meta_ix, emb_ix, idx, per_track):
    """recommendations/playlist_exporter.py:101-116 (per-seed exporter)."""
    recommendations = recommend_for(seed, meta_ix, emb_ix, idx, topk=500, final_top=200)
    if not recommendations:
        return []
    recommendations.sort(key=lambda x: x["cosine"], reverse=True)
    return recommendations[:per_track]


def original_c(seed, meta_ix, emb_ix, idx, per_track):
    """recommendations/playlist_exporter.py:185-202 (combined exporter)."""
    recommendations = recommend_for(seed, meta_ix, emb_ix, idx, topk=500, final_top=200)
    if not recommendations:
        return []
    recommendations.sort(key=lambda x: x["cosine"], reverse=True)
    return recommendations[:per_track]


# --- comparison -----------------------------------------------------------

def differences(expected, got):
    """Every field-level difference between two recommendation lists."""
    if [r["track_id"] for r in expected] != [r["track_id"] for r in got]:
        return [f"ordering: {[r['track_id'] for r in expected][:5]} != "
                f"{[r['track_id'] for r in got][:5]}"]
    out = []
    for e, g in zip(expected, got):
        for field in FIELDS:
            a, b = e[field], g[field]
            if a != b and not (a != a and b != b):  # NaN == NaN for this purpose
                out.append(f"{e['track_id']}.{field}: {a!r} != {b!r}")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=60)
    parser.add_argument("--random-seed", type=int, default=20260818)
    args = parser.parse_args()

    _meta, meta_ix, emb_ix, idx, _V, ids = load_all(REPO / "data")
    print(f"library: {len(ids)} tracks")

    random.seed(args.random_seed)
    seeds = random.sample(ids, min(args.seeds, len(ids)))
    print(f"comparing {len(seeds)} seeds x {len(TRUNCATIONS)} truncation counts "
          f"({len(seeds) * len(TRUNCATIONS)} comparisons per implementation)\n")

    mismatches = 0
    comparisons = 0

    for seed in seeds:
        # A: no extra truncation.
        expected = original_a(seed, meta_ix, emb_ix, idx)
        got = ranked_recommendations(seed, meta_ix, emb_ix, idx, topk=500, final_top=200)
        comparisons += 1
        for line in differences(expected, got):
            mismatches += 1
            print(f"  MISMATCH A {seed}: {line}")

        for per_track in TRUNCATIONS:
            consolidated = ranked_recommendations(
                seed, meta_ix, emb_ix, idx, topk=500, final_top=200, limit=per_track
            )
            for name, original in (("B", original_b), ("C", original_c)):
                expected = original(seed, meta_ix, emb_ix, idx, per_track)
                comparisons += 1
                for line in differences(expected, consolidated):
                    mismatches += 1
                    print(f"  MISMATCH {name} {seed} (limit={per_track}): {line}")

    print(f"\n{comparisons} comparisons, {mismatches} mismatches")
    if mismatches:
        print("FAIL - the consolidated policy is NOT equivalent")
        return 1
    print("PASS - A, B and C are reproduced exactly by "
          "recommendations.ranking.ranked_recommendations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
