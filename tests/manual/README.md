# Manual verification harnesses

Not collected by pytest (no `test_*.py` names). These cover what unit tests
cannot: Tkinter wiring, and a real Essentia indexing pass.

Both drive the app against a **throwaway copy** of `data/`; the real data
directory is only ever read, and `smoke.py` verifies that by fingerprinting
every file's size and mtime before and after the run.

## `smoke.py` — workflow coverage

Drives the real `App` through 37 of the 38 workflows catalogued in
`docs/UI_FEATURE_INVENTORY.md` §5 and prints a pass/fail table. Workflow 34
(cancelling a reindex) needs a real indexing run and lives in the other script.

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
