#!/usr/bin/env python3
"""Compare a baseline recommendation benchmark with an exact-search run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCORE_TOLERANCE = 1e-7


def _queries_by_seed(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {query["seed_track_id"]: query for query in run["queries"]}


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    if baseline["collection"]["inputs_sha256"] != current["collection"]["inputs_sha256"]:
        raise ValueError("benchmark input file hashes differ")
    if baseline["parameters"] != current["parameters"]:
        raise ValueError("benchmark parameters differ")

    baseline_queries = _queries_by_seed(baseline)
    current_queries = _queries_by_seed(current)
    if baseline_queries.keys() != current_queries.keys():
        raise ValueError("benchmark seed track IDs differ")

    changes = []
    max_common_score_delta = 0.0
    for seed_id, baseline_query in baseline_queries.items():
        current_query = current_queries[seed_id]
        baseline_recommendations = {
            item["track_id"]: item for item in baseline_query["recommendations"]
        }
        current_recommendations = {
            item["track_id"]: item for item in current_query["recommendations"]
        }
        baseline_ids = list(baseline_recommendations)
        current_ids = list(current_recommendations)

        for track_id in baseline_recommendations.keys() & current_recommendations.keys():
            score_delta = abs(
                baseline_recommendations[track_id]["score"]
                - current_recommendations[track_id]["score"]
            )
            max_common_score_delta = max(max_common_score_delta, score_delta)

        if baseline_ids == current_ids:
            continue

        baseline_candidates = {
            item["track_id"]: item for item in baseline_query["search_candidates"]
        }
        current_candidates = {
            item["track_id"]: item for item in current_query["search_candidates"]
        }
        baseline_cutoff = min(item["score"] for item in baseline_candidates.values())
        recovered_ids = sorted(
            current_candidates.keys() - baseline_candidates.keys(),
            key=lambda track_id: current_candidates[track_id]["rank"],
        )
        dropped_ids = sorted(
            baseline_candidates.keys() - current_candidates.keys(),
            key=lambda track_id: baseline_candidates[track_id]["rank"],
        )
        recovered_candidates = [
            {
                **current_candidates[track_id],
                "above_faiss_cutoff": (
                    current_candidates[track_id]["score"]
                    > baseline_cutoff + SCORE_TOLERANCE
                ),
            }
            for track_id in recovered_ids
        ]
        is_recovered_miss = bool(recovered_candidates) and all(
            candidate["above_faiss_cutoff"] for candidate in recovered_candidates
        )

        changes.append(
            {
                "seed_track_id": seed_id,
                "classification": (
                    "RECOVERED MISS" if is_recovered_miss else "REGRESSION"
                ),
                "recommendations_added": [
                    track_id for track_id in current_ids if track_id not in baseline_ids
                ],
                "recommendations_removed": [
                    track_id for track_id in baseline_ids if track_id not in current_ids
                ],
                "faiss_candidate_cutoff": baseline_cutoff,
                "recovered_exact_candidates": recovered_candidates,
                "dropped_faiss_candidates": [
                    baseline_candidates[track_id] for track_id in dropped_ids
                ],
            }
        )

    load_before = baseline["timings_ms"]["app_data_load"]["median"]
    load_after = current["timings_ms"]["app_data_load"]["median"]
    query_before = baseline["timings_ms"]["recommendation_query"]["median"]
    query_after = current["timings_ms"]["recommendation_query"]["median"]
    regressions = [
        change for change in changes if change["classification"] == "REGRESSION"
    ]

    return {
        "baseline_git_revision": baseline["git_revision"],
        "current_git_revision": current["git_revision"],
        "inputs_match": True,
        "parameters_match": True,
        "seed_count": len(baseline_queries),
        "unchanged_seed_count": len(baseline_queries) - len(changes),
        "changed_seed_count": len(changes),
        "recovered_miss_count": len(changes) - len(regressions),
        "regression_count": len(regressions),
        "max_common_recommendation_score_delta": max_common_score_delta,
        "timings_ms": {
            "app_data_load_median": {
                "before": load_before,
                "after": load_after,
                "change_percent": (load_after / load_before - 1) * 100,
            },
            "recommendation_query_median": {
                "before": query_before,
                "after": query_after,
                "speedup": query_before / query_after,
            },
            "recommendation_query_p95": {
                "before": baseline["timings_ms"]["recommendation_query"]["p95"],
                "after": current["timings_ms"]["recommendation_query"]["p95"],
            },
        },
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    result = compare(baseline, current)

    print(
        f"{result['seed_count']} seeds: {result['unchanged_seed_count']} unchanged, "
        f"{result['recovered_miss_count']} recovered misses, "
        f"{result['regression_count']} regressions"
    )
    for change in result["changes"]:
        print(
            f"{change['seed_track_id']}: {change['classification']} "
            f"+{','.join(change['recommendations_added'])} "
            f"-{','.join(change['recommendations_removed'])}"
        )

    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")

    if result["regression_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
