# Cosine Companion — UI Rewrite & Rekordbox Playlist Lookup

**Date:** 2026-08-18
**Status:** Design approved; ready for implementation planning
**Scope:** PRs 2–4. PR 1 (exact NumPy search) is merged as `2058da4`.

---

## 1. Context

Cosine Companion (CoCo) recommends DJ tracks by cosine similarity over 2,560-dimensional
Discogs-EffNet audio embeddings, blended with Camelot key and BPM compatibility. It ships as a
single PyInstaller bundle.

Three changes were requested:

1. Remove the ANN (FAISS HNSW) stage and score the entire collection exactly. — **done, merged**
2. Replace the Tkinter UI with something modern.
3. Add a feature to look up which Rekordbox playlists a given track belongs to.

This document covers (2) and (3), plus the refactor that has to happen between them.

### 1.1 What PR 1 already delivered

| Metric | FAISS | Exact NumPy |
|---|---:|---:|
| Median app/index load | 316.483 ms | 65.163 ms (4.86× faster) |
| Median query | 131.709 ms | 4.955 ms (26.58× faster) |
| p95 query | 135.292 ms | 5.373 ms (25.18× faster) |

Measured on the real 1,307-track library across 50 deterministic seeds: 35 seeds unchanged,
15 recovered ANN misses, **0 regressions**. `faiss-cpu` is gone. The repo went from **0 to 19
tests** with a macOS CI job.

---

## 2. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| UI stack | **pywebview + WKWebView + no-build frontend** | Measured +1 MB frozen vs +77 MB for PySide6. No Node toolchain. No JIT entitlement needed. |
| Frontend build | **None.** Hand-written HTML/CSS/JS, or ESM-vendored Preact/Alpine | Keeps PyInstaller packaging simple; no `npm` step in CI |
| App shell | **Sidebar + ⌘K global search** | Four destinations; playlist membership is a track *property*, not a destination |
| Playlist feature scope | **track → playlists only** | No browse-by-playlist. Explicitly out of scope. |
| Playlist source | **Rekordbox collection XML** | Zero new deps (`lxml` already required); no encryption; works whether Rekordbox is open or not |
| Staleness handling | **Prompt to re-import** | Never mutate the user's view silently |
| Platform | **macOS Apple Silicon only** | Intel and Windows deferred, not deleted |

### 2.1 Why Windows is deferred, not merely deprioritised

`essentia-tensorflow` has **never published a Windows wheel** — all 79 files ever released on
PyPI are macOS or manylinux. `pip install -r requirements.txt` on `windows-latest` cannot
succeed today. The existing `build-windows.yml` verify step never checked essentia, so this
failed quietly. Any future Windows port is an essentia problem first and a UI problem second.

---

## 3. Current state

### 3.1 The engine is clean; the UI is the problem

- ~1,807 lines of `recommendations/`, `core/`, `processing/` are already Tk-free and pure.
- ~3,437 lines across 12 UI files sit on top with **no service layer**.
- `App` *is* the model: it holds the metadata DataFrame, embeddings, index and vector array as
  attributes, and tab mixins mutate them directly.

### 3.2 Known defects the rewrite must not inherit

| Issue | Location | Impact |
|---|---|---|
| Export/delete data race | export worker vs `library_tab` delete | Worker reads index while it is replaced |
| Non-atomic four-file rewrite | `library_tab.py:213-273` | Partial write corrupts library state |
| Cancel discards all work | indexing pipeline | A cancelled 6.8-minute run loses everything |
| No reload after indexing | `reindex_window.py:304-321` | App calls `sys.exit(0)`, tells user to restart |
| Indeterminate progress bar | indexing | Pipeline knows `i/N` but does not report it |
| Progress via global `sys.stdout` swap | indexing worker | Process-global mutation from a thread |
| ~350 lines of macOS Tk workarounds | across UI | Fake Label-buttons, `focus_force`, colour re-application |

### 3.3 Measured baseline (1,307 tracks)

Startup `load_all()` 0.79 s with no splash · refresh suggestions 0.31 s · set generation 2.76 s
for 30 tracks · **full-collection export ≈ 6.8 minutes**.

### 3.4 Rekordbox join key — solved

CoCo's `track_id` **is** the Rekordbox `TrackID` (`xml_parser.py:44`), and playlist entries
reference tracks by that same ID (`<TRACK Key="…"/>`, `KeyType="0"` on all playlists).

- Join rate against the configured XML: **1307/1307 (100%)**.
- TrackID stability verified across five exports spanning Oct–Nov 2025: 1106/1106 identical each time.
- `xml_parser.py:26` already parses the whole tree and reads only `//COLLECTION/TRACK` —
  the `<PLAYLISTS>` half is loaded and discarded.
- Full parse + reverse index of the 1.2 MB XML measured at **14 ms**.

No path matching, no fuzzy matching, no fingerprinting required.

---

## 4. Architecture

### 4.1 Target structure

```
src/services/          # headless, zero UI imports
  library_session.py   # LibrarySession  — owns meta/emb/index/ids; single source of truth
  explore_session.py   # ExploreSession  — seed → recommendations
  set_builder.py       # SetBuilder      — multi-hop set generation
  export_service.py    # ExportService   — M3U writing
  indexing_service.py  # IndexingService — pipeline + progress events + cancellation
  settings_store.py    # SettingsStore   — replaces hand-rolled JSON I/O in 4 places
  playlist_service.py  # PlaylistService — Rekordbox playlist membership (new)

src/web/
  server.py            # 127.0.0.1, ephemeral port, token auth
  api.py               # thin JSON layer over services
  static/              # no-build frontend
```

**Rule: `src/services/` must never import a UI toolkit.** This is what makes the layer testable
and the front end replaceable.

### 4.2 Why the services land before the UI

The repo had zero tests until PR 1, and PR 1's 19 tests cover only the index and loader.
Characterisation tests written against the services **while Tkinter still runs on top** are the
only real evidence the rewrite preserved behaviour. Swapping the front end against an untested
backend would make every regression invisible.

### 4.3 Web layer

- Bind `127.0.0.1` only; ephemeral port. Loopback binding verified genuinely loopback-only
  (refused from a LAN address) during the packaging spike.
- Token auth on every request (401/200 verified). Prevents another local process from reading
  the API.
- Static assets shipped via PyInstaller `--add-data`, resolved at runtime under `sys._MEIPASS`.
  **Note:** under PyInstaller 6.x onedir this is `Contents/Frameworks`, *not* `Contents/Resources`.
- Devtools reachable via `debug=True`, including in the frozen app. Hot reload verified working.

---

## 5. UI design

### 5.1 Shell

Four sidebar destinations — **Explore, Set Creator, Library, Export** — plus a persistent ⌘K
global track search. Selecting a track anywhere opens a detail drawer.

### 5.2 The detail drawer

Shows track metadata (title, artist, BPM, Camelot key, path) and **playlist membership with
folder paths** (`Sets / 2025 / Peak Time`). This is where the new feature lives, and where
audio preview would later land.

### 5.3 Acceptance contract for the rewrite

The exhaustive per-control inventory of the existing Tkinter UI — every tab, window, dialog,
control, and rendered string — is the acceptance contract. The rewrite is complete when every
catalogued behaviour is reachable in the new UI. No feature may be dropped silently; anything
intentionally removed must be listed in the PR description.

**This inventory must be committed to the repository as
`docs/UI_FEATURE_INVENTORY.md` as a deliverable of PR 2.** It currently exists only as an
ephemeral report. A contract that can evaporate is not a contract, and PR 3 cannot be reviewed
without it. Generating it is a mechanical re-read of the 12 Tkinter files and belongs in the
same PR that extracts the services those controls call into.

### 5.4 Long-running work

`IndexingService` emits structured progress events (`i/N`, current file, phase) over the API.
Replaces the `sys.stdout` swap. Requirements:

- **Determinate** progress bar (the pipeline already knows `i/N`).
- **Cancellation checkpoints** so a cancelled run keeps completed embeddings.
- **In-place reload** after indexing — no `sys.exit(0)`, no restart prompt.

---

## 6. Rekordbox playlist lookup

### 6.1 Data flow

```
Rekordbox XML → parse <PLAYLISTS> → playlists.parquet
(already loaded,   (recursive NODE)   playlist_membership.parquet
 currently discarded)                        ↓
                                    PlaylistService reverse index
                                             ↓
                                    ⌘K search → track detail drawer
```

### 6.2 Schema

`playlists.parquet` — `playlist_id`, `name`, `folder_path`, `parent_id`, `entries`
`playlist_membership.parquet` — `track_id`, `playlist_id`

Two tables, **not** columns on `meta.parquet`: membership is many-to-many (mean 2.05, max 10
playlists per track), and `meta.parquet` is rewritten wholesale in two places that would clobber
it.

Sizes are trivial — ~2.7k membership rows, well under 100 KB.

### 6.3 XML structure

`<NODE Type="0">` = folder (attrs `Type`, `Name`, `Count`); `<NODE Type="1">` = playlist (attrs
`Type`, `Name`, `Entries`, `KeyType`). Membership is `<TRACK Key="…"/>` children. Observed max
nesting depth 3; all 67 playlist paths unique; zero duplicate leaf names.

### 6.4 Staleness

Persist `source_xml` and `imported_at` alongside the tables. Display provenance in the drawer
("from `242.xml`, imported 12 Aug"). Watch the XML's mtime; when it changes, **prompt** the user
to re-import. **Never auto-import.**

This matters concretely: the current export contains 67 playlists while the live Rekordbox
library has 166.

### 6.5 Edge cases

| Case | Behaviour |
|---|---|
| Track in CoCo, in no playlist | Drawer shows "In 0 playlists" |
| Track in Rekordbox but not CoCo | Not shown (CoCo's library is the universe) |
| Playlist references an unknown TrackID | Ignored; counted in an import summary |
| No XML imported yet | Drawer shows an import call-to-action |
| XML missing at recorded path | Show provenance + a re-pick action; do not crash |

---

## 7. Sequencing

| PR | Title | Depends on | Notes |
|---|---|---|---|
| 1 | Exact NumPy search | — | **Merged** (`2058da4`) |
| 2 | Services layer + characterisation tests + `docs/UI_FEATURE_INVENTORY.md` | PR 1 | Tkinter still on top; behaviour-preserving |
| 3 | pywebview UI | PR 2 | Against a green suite |
| 4 | Rekordbox playlist lookup | PR 2, PR 3 | New UI, clean service API |

PR 2 must be **behaviour-preserving**: no user-visible change. That is what makes its
characterisation tests trustworthy as a rewrite baseline.

---

## 8. Testing strategy

- **PR 2** — characterisation tests against each service, asserting current behaviour exactly,
  including quirks. Where a quirk is a known defect (§3.2), test the *current* behaviour and mark
  it with a linked follow-up rather than fixing it inline.
- **PR 3** — UI tests over the JSON API, not the DOM. The API is the contract.
- **PR 4** — fixture XML with nested folders, a track in multiple playlists, a track in none, and
  an unresolvable `Key`.
- All PRs — the existing macOS CI `pytest` job must stay green.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| PR 2 is a large refactor with weak existing coverage | Behaviour-preserving only; no feature work; reviewed by opposite vendor |
| The Tkinter inventory misses a behaviour | Inventory committed to the repo in PR 2; anything dropped must be declared in the PR description |
| Frozen app can't find static assets | Spike verified `sys._MEIPASS` → `Contents/Frameworks` under PyInstaller 6.x |
| macOS firewall prompt on a localhost listener | Not observed in the spike, but the test machine's firewall was **disabled** — must be re-verified with it enabled |
| Re-exported XML changes TrackIDs | Verified stable across five exports; re-check on import and report unmatched IDs |
| Bundle is already ~728 MB | 481 MB is essentia; no UI choice affects it. Out of scope. |

---

## 10. Out of scope (backlog)

Tracked in `.polly/registry.json`:

- `xml_parser.py:60-61` — an all-or-nothing `track_id` column swap: if **any** track lacks a
  TrackID, the entire column is replaced with file paths, orphaning every embedding. **Highest-value
  backlog item.**
- PyInstaller builds `onefile`, re-extracting ~730 MB on every launch.
- essentia wheels are tagged `macosx_15_0` while `LSMinimumSystemVersion` claims `10.13` — a
  likelier explanation for "only Apple Silicon works" than codesigning.
- `transitions.py:34-47` — 2–3 embedding lookups per candidate (~40–60 per hop).
- `NumpyCosIndex._rows` retained after `vstack` (~2× vector bytes in the index).
- `add()` appends row before id — a concurrent `search()` could `IndexError`. Pre-existing;
  folds into the export/delete race work.
- Startup recovery dialog names a source-checkout remedy; a DMG user would reindex the wrong
  directory.
- `V` and `idx.matrix` hold duplicate vector copies.
