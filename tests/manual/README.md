# Manual verification harnesses

Not collected by pytest (no `test_*.py` names). These cover what unit tests
cannot: a real Essentia indexing pass and measurements over the whole real
library.

`web_jobs_real_export.py` reads `data/` and writes only into a temp directory.
`real_indexing.py` reads real track metadata and audio, but starts re-index jobs
through the shipping web API with a `LibrarySession` bound to a new scratch
directory. It fingerprints every source-data file by size, mtime, and SHA-256
before and after. The real data directory is only ever read.
`ranking_equivalence.py` only reads.

## `real_indexing.py` — real Essentia pass

Starts the real `POST /api/jobs/reindex` path with the actual embedder over N
real tracks (default 4), verifies the live library endpoint publishes the
committed index, then repeats and cancels partway through the real job route.
It asserts terminal wire states and persistence in both cases.

The Discogs-EffNet `.pb` model is gitignored, so point `COCO_MODELS` at a
checkout that has it:

```bash
COCO_MODELS=/path/to/models PYTHONPATH=src python tests/manual/real_indexing.py 4
```

Environment: `COCO_REPO` overrides the checkout root, `COCO_MODELS` the model
directory.

## `ranking_equivalence.py` — the consolidation measurement

Reproduces the three pre-PR-2 copies of the ranking policy verbatim from `main`
and diffs each against `recommendations.ranking.ranked_recommendations` over the
real 1,307-track library: 60 seeds x 3 truncation counts by default, every field
of every row compared. Exits non-zero on any mismatch.

This exists because the claim "diffed over 60 seeds x 3 truncations, zero
mismatches" used to live only in a docstring. Now it can be re-run:

```bash
PYTHONPATH=src python tests/manual/ranking_equivalence.py
PYTHONPATH=src python tests/manual/ranking_equivalence.py --seeds 200
```

Last run: **420 comparisons, 0 mismatches.**

## `web_jobs_real_export.py` — the job machinery at real size

Runs `web/jobs.py` and the `/api/jobs` routes over the real library, through a
real `CocoServer` and an HTTP client, with the real `ExportService`: starts a
full-collection export, checks that a second job is refused, watches progress,
cancels part-way, and asserts that what the terminal record claims is on disk
really is.

`tests/web/test_jobs_real_export.py` covers the same code against the committed
fourteen-track fixture and gates every merge — this one is the real-size
counterpart and is not a gate.

```bash
PYTHONPATH=src python tests/manual/web_jobs_real_export.py
PYTHONPATH=src python tests/manual/web_jobs_real_export.py --seeds 20 --pause-at 10
```

Last run, 1,532-track library: **22 checks, 0 failures.** Cancel at seed 3 left
3 complete `.m3u` files and a record saying exactly that; `GET /api/jobs/{id}`
measured at **0.46 ms** over 200 calls, which is the number behind the polling
decision in `web/jobs.py`.
