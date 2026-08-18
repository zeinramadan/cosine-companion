# Exact NumPy Search Benchmark

The FAISS baseline was captured and committed before implementation changes in
`25175ec`. The corrected NumPy run uses the same SHA-256-verified, read-only
inputs and benchmark parameters:

- 1,307 tracks with 2,560-dimensional float32 embeddings
- 50 deterministic seed track IDs
- `topk=200`, `final_top=15`, and five app-data/index load runs
- `OMP_NUM_THREADS=1` and the same `dj-companion` conda environment

## Timing results

| Metric | FAISS HNSW | Exact NumPy | Change |
|---|---:|---:|---:|
| Median app data/index load | 316.483 ms | 65.163 ms | 79.41% lower (4.86x faster) |
| Median recommendation query | 131.709 ms | 4.955 ms | 26.58x faster |
| p95 recommendation query | 135.292 ms | 5.373 ms | 25.18x faster |

The NumPy run's slowest query was 8.218 ms; this includes lazy matrix
materialization on the first search after all rows have been added.

## Recommendation comparison

| Result | Seeds |
|---|---:|
| Same ordered top-15 track IDs | 35 |
| Changed due to recovered HNSW misses | 15 |
| Regressions | 0 |

For every changed seed, the exact search recovered one or more collection
vectors whose cosine score was above that seed's lowest FAISS nominee. The
full per-seed classifications, ranks, scores, and opaque track IDs are retained
in `faiss_to_numpy_diff.json`.

The retained benchmark evidence contains no artist names, titles, audio paths,
or other personal metadata. Track IDs are opaque numeric identifiers. Raw
capture files and their input hashes are local regenerated outputs and are
excluded by `.gitignore`.

## Reproduction

Run `benchmark_recommendations.py` at the baseline revision and the current
revision to create the ignored capture files, then compare them:

```bash
PYTHONPATH=src OMP_NUM_THREADS=1 KMP_DUPLICATE_LIB_OK=TRUE \
  python benchmarks/benchmark_recommendations.py \
  --output benchmarks/numpy_exact.json

python benchmarks/compare_recommendations.py \
  benchmarks/faiss_baseline.json \
  benchmarks/numpy_exact.json \
  --output benchmarks/faiss_to_numpy_diff.json
```
