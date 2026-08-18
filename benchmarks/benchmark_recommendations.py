#!/usr/bin/env python3
"""Capture deterministic recommendation output and search timings.

Run this script from the repository root with ``PYTHONPATH=src``. It only reads
the library files under ``data/`` and writes the requested JSON result file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from config import EMB_PQ, IDS_JSON, IDX_NPY, META_PQ
from config.defaults import DEFAULT_FINAL_TOP, DEFAULT_TOPK
from core.loader import load_all
from recommendations.engine import recommend_for, vector_for


DEFAULT_SAMPLE_SIZE = 50
SAMPLE_SALT = "exact-numpy-search-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _summary_ms(values: Iterable[float]) -> dict[str, float]:
    samples = list(values)
    return {
        "min": min(samples),
        "median": statistics.median(samples),
        "mean": statistics.fmean(samples),
        "p95": float(np.percentile(samples, 95)),
        "max": max(samples),
    }


def _sample_ids(ids: list[str], sample_size: int) -> list[str]:
    if sample_size < 1:
        raise ValueError("sample size must be positive")
    if sample_size > len(ids):
        raise ValueError(
            f"sample size ({sample_size}) exceeds collection size ({len(ids)})"
        )
    return sorted(
        ids,
        key=lambda track_id: hashlib.sha256(
            f"{SAMPLE_SALT}:{track_id}".encode("utf-8")
        ).digest(),
    )[:sample_size]


def _git_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


def capture(load_runs: int, sample_size: int) -> dict[str, Any]:
    if load_runs < 1:
        raise ValueError("load runs must be positive")

    load_ms = []
    loaded = None
    for _ in range(load_runs):
        started = time.perf_counter()
        loaded = load_all()
        load_ms.append((time.perf_counter() - started) * 1_000)

    assert loaded is not None
    _meta, meta_ix, emb_ix, idx, vectors, ids = loaded
    seed_ids = _sample_ids(ids, sample_size)

    queries = []
    query_ms = []
    for seed_id in seed_ids:
        started = time.perf_counter()
        recommendations = recommend_for(
            seed_id,
            meta_ix,
            emb_ix,
            idx,
            topk=DEFAULT_TOPK,
            final_top=DEFAULT_FINAL_TOP,
        )
        elapsed_ms = (time.perf_counter() - started) * 1_000
        query_ms.append(elapsed_ms)

        query_vector = vector_for(seed_id, emb_ix)
        assert query_vector is not None
        candidates = idx.search(query_vector, k=DEFAULT_TOPK + 1)

        queries.append(
            {
                "seed_track_id": seed_id,
                "elapsed_ms": elapsed_ms,
                "recommendations": [
                    {
                        "rank": rank,
                        "track_id": recommendation["track_id"],
                        "score": recommendation["score"],
                        "cosine": recommendation["cosine"],
                    }
                    for rank, recommendation in enumerate(recommendations, start=1)
                ],
                "search_candidates": [
                    {"rank": rank, "track_id": track_id, "score": score}
                    for rank, (track_id, score) in enumerate(candidates, start=1)
                ],
            }
        )

    return {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_revision": _git_revision(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "index_class": type(idx).__name__,
        "collection": {
            "track_count": len(ids),
            "vector_dimension": int(vectors.shape[1]),
            "inputs_sha256": {
                "meta.parquet": _sha256(META_PQ),
                "embeddings.parquet": _sha256(EMB_PQ),
                "index.npy": _sha256(IDX_NPY),
                "ids.json": _sha256(IDS_JSON),
            },
        },
        "parameters": {
            "sample_size": sample_size,
            "sample_salt": SAMPLE_SALT,
            "topk": DEFAULT_TOPK,
            "final_top": DEFAULT_FINAL_TOP,
            "load_runs": load_runs,
        },
        "timings_ms": {
            "app_data_load": {"runs": load_ms, **_summary_ms(load_ms)},
            "recommendation_query": _summary_ms(query_ms),
        },
        "queries": queries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--load-runs", type=int, default=5)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    args = parser.parse_args()

    result = capture(args.load_runs, args.sample_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    load = result["timings_ms"]["app_data_load"]
    query = result["timings_ms"]["recommendation_query"]
    print(
        f"{result['index_class']}: {result['collection']['track_count']} tracks, "
        f"{len(result['queries'])} queries"
    )
    print(
        f"app data load median {load['median']:.3f} ms; "
        f"query median {query['median']:.3f} ms, p95 {query['p95']:.3f} ms"
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
