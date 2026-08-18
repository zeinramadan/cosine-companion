# Manual verification harnesses

Not collected by pytest (no `test_*.py` names). These cover what unit tests
cannot: Tkinter wiring, a real Essentia indexing pass, and a measurement over
the whole real library.

`smoke.py` and `real_indexing.py` drive the app against a **throwaway copy** of
`data/`; the real data directory is only ever read, and `smoke.py` verifies that
by fingerprinting every file's size and mtime before and after the run.
`ranking_equivalence.py` only reads.

## `smoke.py` — workflow coverage

Drives the real `App` through the workflows catalogued in
`docs/UI_FEATURE_INVENTORY.md` §5 and prints a pass/fail table — 43 checks,
including the post-deletion stale-consumer set (22a–22f) that pins which
surfaces refresh after a delete and which keep showing the deleted track
(defect #14). Workflow 34 (cancelling a reindex) needs a real indexing run and
lives in the other script.

```bash
PYTHONPATH=src python tests/manual/smoke.py
PYTHONPATH=src python tests/manual/smoke.py --only 4,6,7
```

## `real_indexing.py` — real Essentia pass

Runs the actual `ReindexWindow` with the actual embedder over N real tracks
(default 4), then repeats and cancels partway, asserting the log lines,
terminal states and persistence in both cases.

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
