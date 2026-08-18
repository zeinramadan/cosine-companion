# Services Layer Implementation Plan (PR 2)

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Each task ends with a green test run and a commit.

**Goal:** Extract a headless service layer from the Tkinter UI, with characterisation tests, so the
front end can later be replaced without losing behaviour.

**Architecture:** Create `src/services/` containing UI-free classes that own all application state
and business logic. Rewire the existing Tkinter tabs to call those services instead of mutating
`App` attributes directly. **Tkinter keeps working exactly as it does today** — this PR is strictly
behaviour-preserving.

**Tech Stack:** Python 3.10, pandas, numpy, pyarrow, lxml, pytest ≥7.0, Tkinter (unchanged).

**Spec:** `docs/superpowers/specs/2026-08-18-ui-rewrite-and-playlist-lookup-design.md`

## Global Constraints

- **Behaviour-preserving.** No user-visible change. No bug fixes. No feature work.
- **`src/services/` must never import `tkinter`** or any UI module. This is the whole point;
  a single stray import defeats the layer. Enforce it with a test.
- Python **3.10**. pytest **≥7.0** (`pythonpath` in `pytest.ini` is a 7.0+ feature).
- Platform: **macOS Apple Silicon only**.
- Existing 19 tests must stay green throughout. Never commit red.
- Known defects listed in spec §3.2 are **characterised, not fixed** — write tests asserting
  *current* behaviour and reference the backlog item. Fixing them here would make the tests
  useless as a rewrite baseline.
- Do not touch `data/` contents. The worktree copy is read-only input.

---

## File Structure

| File | Responsibility |
|---|---|
| `docs/UI_FEATURE_INVENTORY.md` | **Contract.** Every tab/window/dialog, every control, every rendered string |
| `src/services/__init__.py` | Public exports |
| `src/services/settings_store.py` | `SettingsStore` — all settings JSON I/O |
| `src/services/library_session.py` | `LibrarySession` — owns meta/emb/index/ids; single source of truth |
| `src/services/explore_session.py` | `ExploreSession` — seed → ranked recommendations |
| `src/services/set_builder.py` | `SetBuilder` — multi-hop set generation |
| `src/services/export_service.py` | `ExportService` — M3U writing |
| `src/services/indexing_service.py` | `IndexingService` — pipeline, progress events, cancellation |
| `tests/services/test_*.py` | Characterisation tests per service |
| `tests/test_services_are_ui_free.py` | Guard: no UI imports under `src/services/` |

Existing `src/recommendations/`, `src/core/`, `src/processing/` are already pure and should be
**called** by services, not absorbed into them. Services orchestrate; they do not reimplement.

---

## Task 1: Capture the UI feature inventory

This is the acceptance contract for PR 3. It must exist before any refactor, because it is the
only record of what the Tkinter app does.

**Files:**
- Create: `docs/UI_FEATURE_INVENTORY.md`

**Source files to read exhaustively** (3,400 lines total):
`onboarding.py` (639), `settings_window.py` (468), `playlist_export_tab.py` (464),
`recommendations_tab.py` (329), `reindex_window.py` (323), `dialogs.py` (291),
`library_tab.py` (273), `app.py` (215), `track_selector_dialog.py` (195),
`set_creator_tab.py` (163), `__init__.py` (40).

- [ ] **Step 1:** For every tab, window, and dialog, document: its name, every control (buttons,
      inputs, tables, sliders, menus, checkboxes), what each control does, and the user workflow
      it supports.
- [ ] **Step 2:** Record the exact user-facing strings rendered — labels, button text, error
      messages, dialog titles, column headers, empty states. PR 3 must reproduce these.
- [ ] **Step 3:** Record the exact per-track fields displayed and their formatting (title, artist,
      BPM, key/Camelot, path, score, and any rounding/truncation).
- [ ] **Step 4:** Record keyboard shortcuts, default values, sort orders, and any control whose
      enabled/disabled state is conditional.
- [ ] **Step 5:** Commit.

**Acceptance:** a reader who has never run the app could enumerate every user-reachable behaviour.

---

## Task 2: `SettingsStore`

Smallest service, no dependencies — establishes the pattern. Settings JSON I/O is currently
hand-rolled in **four** places.

**Files:**
- Create: `src/services/settings_store.py`, `tests/services/test_settings_store.py`
- Modify: the four existing settings read/write sites (find via `grep -rn "settings.json" src/`)

**Interfaces — Produces:**
- `SettingsStore(path: Path)`
- `.get(key: str, default: Any = None) -> Any`
- `.set(key: str, value: Any) -> None` — persists immediately
- `.all() -> dict`
- `.xml_path` property (the only key in use today)

- [ ] **Step 1:** Write failing characterisation tests: round-trips a value; returns default for a
      missing key; **tolerates a missing settings file** and **a corrupt/unparseable one** exactly
      as the current code does (determine which by reading the existing sites first — do not
      assume, and do not improve).
- [ ] **Step 2:** Run tests, confirm they fail.
- [ ] **Step 3:** Implement `SettingsStore`.
- [ ] **Step 4:** Run tests, confirm green.
- [ ] **Step 5:** Replace all four call sites. Verify no behaviour change by reading each site.
- [ ] **Step 6:** Full suite green. Commit.

---

## Task 3: Guard test — services stay UI-free

Cheap, and it protects every later task.

**Files:**
- Create: `tests/test_services_are_ui_free.py`

- [ ] **Step 1:** Write a test that walks every module under `src/services/`, parses it with `ast`,
      and asserts no import of `tkinter`, `src.ui`, or `ui`. Use AST parsing, not a string grep —
      a grep matches comments and docstrings.
- [ ] **Step 2:** Run it; it should pass against `SettingsStore` alone.
- [ ] **Step 3:** Commit.

---

## Task 4: `LibrarySession`

The core of the refactor. Today `App` holds `meta`, `meta_ix`, `emb_ix`, `idx`, `V`, `ids` as
attributes that tab mixins mutate directly (`src/ui/app.py:29`).

**Files:**
- Create: `src/services/library_session.py`, `tests/services/test_library_session.py`
- Modify: `src/ui/app.py` (hold a `LibrarySession` instead of six loose attributes)

**Interfaces — Produces:**
- `LibrarySession.load(data_dir: Path) -> LibrarySession` — wraps `core.loader.load_all()`
- `.meta`, `.meta_ix`, `.emb_ix`, `.index`, `.vectors`, `.ids` — read accessors
- `.track_count -> int`
- `.is_empty -> bool` (the current `idx is None` condition)
- `.get_track(track_id: str) -> dict | None`
- `.search_tracks(query: str) -> list[dict]` — see note below
- `.delete_tracks(track_ids: list[str]) -> None` — rebuild + persist, currently
  `library_tab.py:213-273`
- `.reload() -> None`

**Note — two divergent search implementations exist.** `src/recommendations/search.py` and a
second one in the UI. **Do not unify them in this PR.** Characterise both, document the
difference in the inventory, and expose the one the UI currently uses. Unification is PR 3+ work.

- [ ] **Step 1:** Write characterisation tests against the real 1,307-track fixture in `data/`:
      loads successfully; `track_count == 1307`; a known `track_id` round-trips through
      `get_track`; `search_tracks` returns the same results as the current UI path for a handful
      of queries.
- [ ] **Step 2:** Write characterisation tests for `delete_tracks` covering the **current**
      behaviour, including that it is **non-atomic across four files** and that an empty
      collection leaves the index in the `None`/empty state. Reference backlog
      `backlog-n3-ids-lag-race` and the export/delete race — **do not fix them here**.
- [ ] **Step 3:** Run tests, confirm they fail.
- [ ] **Step 4:** Implement `LibrarySession` by *moving* logic out of `app.py` and
      `library_tab.py`. Move, do not rewrite.
- [ ] **Step 5:** Run tests, confirm green.
- [ ] **Step 6:** Rewire `app.py` and `library_tab.py` to use the session. **Launch the app and
      confirm it still works** — tests do not cover Tk wiring.
- [ ] **Step 7:** Full suite green. Commit.

---

## Task 5: `ExploreSession`

Ranking policy is currently **duplicated** between `recommendations_tab.py:236-247` and
`playlist_exporter.py:101-116`. This task makes one of them the single implementation.

**Files:**
- Create: `src/services/explore_session.py`, `tests/services/test_explore_session.py`
- Modify: `src/ui/recommendations_tab.py`

**Interfaces — Consumes:** `LibrarySession` (Task 4)
**Interfaces — Produces:**
- `ExploreSession(library: LibrarySession)`
- `.recommend(track_id: str, topk: int = 200, final_top: int = 15) -> list[Recommendation]`
- `Recommendation` — a dataclass carrying at minimum `track_id`, `artist`, `title`, `bpm`, `key`,
  `path_local`, `cosine`, `score`. Confirm the exact field set against the inventory; the UI must
  render every field it renders today.

- [ ] **Step 1:** **Before refactoring**, diff the two duplicated ranking implementations and
      write down every difference. If they differ behaviourally, the UI path is authoritative;
      record the discrepancy as a backlog item rather than silently picking one.
- [ ] **Step 2:** Write characterisation tests: for a fixed seed `track_id`, assert the exact
      ordered result list matches the current implementation. Cover `final_top` truncation,
      the self-match skip, and the `topk=500/final_top=200` Explore-tab configuration.
- [ ] **Step 3:** Run tests, confirm they fail.
- [ ] **Step 4:** Implement `ExploreSession` delegating to `recommendations.engine.recommend_for`.
- [ ] **Step 5:** Run tests, confirm green.
- [ ] **Step 6:** Rewire `recommendations_tab.py`. Launch the app and confirm Explore still works.
- [ ] **Step 7:** Full suite green. Commit.

---

## Task 6: `SetBuilder`

**Files:**
- Create: `src/services/set_builder.py`, `tests/services/test_set_builder.py`
- Modify: `src/ui/set_creator_tab.py`

**Interfaces — Consumes:** `LibrarySession`, `ExploreSession`
**Interfaces — Produces:**
- `SetBuilder(library: LibrarySession)`
- `.build(seed_track_id: str, length: int, **params) -> list[Recommendation]` — mirror the
  current `set_generator` signature exactly; read it before designing.

- [ ] **Step 1:** Characterisation tests for a fixed seed and length: assert the exact ordered
      output, including transition scoring `0.8·cos(prev→cand) + 0.2·cos(cand→next)` and the
      `topk=100/final_top=50` per-hop configuration.
- [ ] **Step 2:** Run tests, confirm they fail.
- [ ] **Step 3:** Implement, delegating to `recommendations.set_generator`.
- [ ] **Step 4:** Run tests, confirm green.
- [ ] **Step 5:** Rewire `set_creator_tab.py`. Launch and confirm Set Creator works.
- [ ] **Step 6:** Full suite green. Commit.

---

## Task 7: `ExportService`

**Files:**
- Create: `src/services/export_service.py`, `tests/services/test_export_service.py`
- Modify: `src/ui/playlist_export_tab.py`

**Interfaces — Consumes:** `LibrarySession`, `ExploreSession`
**Interfaces — Produces:**
- `ExportService(library: LibrarySession, explore: ExploreSession)`
- `.export_per_seed(track_ids, out_dir, progress=None, cancel=None) -> ExportResult`
- `.export_combined(track_ids, out_path, progress=None, cancel=None) -> ExportResult`

`progress` is `Callable[[int, int, str], None]`; `cancel` is a `threading.Event`.

- [ ] **Step 1:** Characterisation tests using `tmp_path`: M3U content matches byte-for-byte,
      including the `#EXTM3U` header, `#EXTINF:-1,{artist} - {title}` lines (duration is
      hardcoded `-1` because CoCo never captures it), the bare absolute `path_local`, the
      `{safe_artist} - {safe_title}.m3u` filename scheme, and that tracks whose `path_local`
      does not exist are **silently skipped** (current behaviour — characterise, do not fix).
- [ ] **Step 2:** Run tests, confirm they fail.
- [ ] **Step 3:** Implement, delegating to `recommendations.playlist_exporter`.
- [ ] **Step 4:** Run tests, confirm green.
- [ ] **Step 5:** Rewire `playlist_export_tab.py`. Launch and confirm export works. Full export
      takes ≈6.8 minutes — a small subset is fine for the smoke check.
- [ ] **Step 6:** Full suite green. Commit.

---

## Task 8: `IndexingService`

The most valuable and most delicate. Progress is currently reported by replacing **process-global
`sys.stdout`** with a queue writer from a worker thread.

**Files:**
- Create: `src/services/indexing_service.py`, `tests/services/test_indexing_service.py`
- Modify: `src/ui/reindex_window.py`, `src/ui/onboarding.py`

**Interfaces — Consumes:** `SettingsStore`
**Interfaces — Produces:**
- `IndexingService(settings: SettingsStore)`
- `.run(xml_path, force_full=False, progress=None, cancel=None) -> IndexResult`
- `ProgressEvent` — dataclass with `phase: str`, `current: int`, `total: int`, `message: str`

- [ ] **Step 1:** Write tests using a **small fixture XML** (do not run Essentia in tests — mock
      the embedder). Assert `ProgressEvent`s are emitted with real `current`/`total` values, that
      `cancel` stops the run, and that `run()` never writes to `sys.stdout`.
- [ ] **Step 2:** Run tests, confirm they fail.
- [ ] **Step 3:** Implement, delegating to `processing.pipeline.index_library`. Replace the
      `sys.stdout` swap with a structured callback. **This is the one place a mechanism changes**
      — it is internal plumbing, and the UI must render the same information as before.
- [ ] **Step 4:** Run tests, confirm green.
- [ ] **Step 5:** Rewire `reindex_window.py` and `onboarding.py`. The bar may stay indeterminate
      in this PR (making it determinate is PR 3 work) — but the service must now *supply* `i/N`.
- [ ] **Step 6:** **Run a real indexing pass on a handful of tracks** and confirm progress
      displays and cancellation behave as before. Mocked tests cannot prove this.
- [ ] **Step 7:** Full suite green. Commit.

---

## Task 9: Final wiring and verification

- [ ] **Step 1:** Confirm `src/ui/app.py` no longer holds `meta`, `meta_ix`, `emb_ix`, `idx`, `V`,
      `ids` as loose attributes; it holds services.
- [ ] **Step 2:** `grep -rn "import tkinter\|from ui\|import ui" src/services/` → **zero hits.**
- [ ] **Step 3:** Run the full suite. Report `python -m pytest --collect-only -q` and the run.
- [ ] **Step 4:** Manual smoke test of **every** workflow in `docs/UI_FEATURE_INVENTORY.md`.
      Record pass/fail per workflow in the PR description.
- [ ] **Step 5:** Confirm startup time has not regressed beyond ~0.79 s baseline.
- [ ] **Step 6:** Commit and open the PR.

---

## Self-Review Notes

**Spec coverage.** Spec §4.1 lists seven services; `PlaylistService` is deliberately excluded —
it is PR 4 work with no Tkinter caller to preserve. All six others have tasks. Spec §5.3's
`docs/UI_FEATURE_INVENTORY.md` is Task 1.

**Deliberate omission.** Implementation bodies are not pre-written here. Signatures, contracts,
and test intent are specified; the implementer writes the code and an independent
different-vendor reviewer checks it against this plan.

**Known risk.** Tasks 4 and 8 touch the most tangled code. If either balloons, stop and split it
rather than pushing a large unreviewable commit.
