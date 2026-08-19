# Golden values

Committed expectations for the recommendation engine, the set generator and the
playlist exporter. They exist because the first version of these tests computed
their "expected" result by calling the very function under test — so they would
have passed unchanged if the ordering, the scores or the transition choices
drifted. A tautology is not a baseline.

| File | Library | Runs on CI |
|---|---|---|
| `explore_fixture.json`, `set_builder_fixture.json`, `export_fixture.json` | the twelve committed tracks in `../fixture_library.py` | **yes** |
| `explore_real.json`, `set_builder_real.json` | the library identified by `real_library_fingerprint.json` | no — `data/` is gitignored, so those tests skip |

The fingerprint records the track count and a SHA-256 digest of the parsed,
ordered `ids.json` list. A developer's `data/` must match both values before the
real-library assertions run. This prevents routine library changes from looking
like engine regressions while keeping re-baselining explicit.

This identifies the ordered **track-ID set, not the library content**. Reindexing
with added, removed, or reordered IDs is detected. Re-embedding the same IDs with
a different model, re-running BPM/key analysis, or changing track metadata is
not: `meta.parquet`, `embeddings.parquet`, and `index.npy` may differ while the
fingerprint still matches. In that case a real-library golden failure can still
be a library-analysis change rather than an engine regression. This limitation
is deliberate because hashing serialized parquet or NumPy bytes would make the
fingerprint sensitive to writer/library-version details, not just semantic data.

## How exact is exact

Regenerating on two different NumPy builds of the same version (conda-forge and
the PyPI wheel, both 2.2.6, macOS arm64) gives:

* **identical ordering** — every golden track-id list matches exactly, for both
  libraries, at every truncation; and
* float values differing by at most `1.8e-7`, about one ulp of `float32`, which
  is what the `matrix @ v` in `core/index_builder.py` computes in.

So the tests compare **ids exactly** and **floats to `abs=1e-6`**. That tolerance
is ~30x the observed BLAS noise and still four orders of magnitude tighter than
any behavioural change: nudging one scoring weight moves a score by ~1e-2, and
`tests/services/test_golden_values_actually_fail.py` demonstrates the goldens
catching exactly that.

## Regenerating

Only ever regenerate deliberately, when a behaviour or real-library baseline
change is *intended*, and review the diff. The real-library command updates its
goldens and fingerprint together:

    python tests/services/golden/regenerate_fixture_goldens.py
    python tests/services/golden/regenerate_real_goldens.py   # needs data/

A silent regeneration defeats the entire point of this directory.
