# Web Backbone — Local API + pywebview Shell (PR 3a) Implementation Plan

> **Historical plan.** This records the first web-backbone stage, when the
> retired desktop frontend was deliberately kept as the default. It is not
> current implementation guidance; `README.md` and
> `docs/SYSTEM_ARCHITECTURE.md` describe the completed web-only product.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a pywebview-hosted web UI that runs the **Explore** workflow against the existing
services layer over a token-authenticated loopback JSON API — without changing, degrading, or
removing the Tkinter app.

**Architecture:** A `ThreadingHTTPServer` bound to `127.0.0.1:0` runs in a daemon thread and
serves (a) static assets from `src/web/static/` and (b) a small JSON API that is a thin adapter
over `LibrarySession` / `ExploreSession` / `SettingsStore`. A pywebview window owns the macOS
main thread and loads `http://127.0.0.1:<port>/?key=<token>`. No business logic lives in
`src/web/` — it translates JSON to service calls and back, nothing more.

**Tech Stack:** Python 3.10 · stdlib `http.server.ThreadingHTTPServer` · `pywebview` (the only
new runtime dependency) · hand-written HTML/CSS/ES modules, no build step · pytest.

**Spec:** `docs/superpowers/specs/2026-08-18-ui-rewrite-and-playlist-lookup-design.md`

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.10+.** The codebase uses PEP 604 (`X | None`). CI runs 3.10. `python3` on the
  maintainer's Mac is 3.9 and will fail at collection — use the 3.10 interpreter explicitly.
- **macOS Apple Silicon only.** Do not add Windows or Intel handling.
- **No Node toolchain.** No `npm`, no bundler, no transpiler, no `package.json`. Frontend is
  hand-written HTML/CSS and native ES modules loaded with `<script type="module">`.
- **Exactly one new runtime dependency: `pywebview`.** Do **not** add FastAPI, uvicorn,
  starlette, pydantic, flask, or any other web framework. The bundle is already ~728 MB and
  every added dependency is a PyInstaller risk.
- **`src/services/` must never import a UI toolkit.** The existing subprocess guard test stays
  green and must not be modified.
- **`src/web/server.py` and `src/web/api.py` must not import `webview`, `tkinter`, or
  `essentia`** — directly or transitively at module scope. Only `src/web/host.py` imports
  `webview`. This is what lets the API tests run in CI.
- **Tkinter remains the default UI.** Nothing under `src/ui/` may be deleted, and no
  user-observable Tkinter behaviour may change. `python -m cosine_companion` with no arguments
  must still launch the Tkinter app.
- **All 315 existing tests stay green**, unmodified.
- **Tests must pass in a clean venv** installing only `numpy pandas pyarrow lxml pytest
  pywebview`. No essentia. Verify this, do not assume it.
- **Server binds `127.0.0.1` only, on an ephemeral port (`0`).** Never `0.0.0.0`.
- **Every `/api/*` request requires a valid token.** No exceptions, including `/api/health`.
- Frontend must render correctly in **WKWebView** (Safari's engine). No Chrome-only CSS or JS.

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `src/web/__init__.py` | Package marker. Must not import `webview`. |
| `src/web/assets.py` | Resolve the static asset directory in dev and under PyInstaller. |
| `src/web/server.py` | `ThreadingHTTPServer` setup, loopback binding, token auth, request routing, static file serving. No domain logic. |
| `src/web/api.py` | The JSON endpoints. Thin adapter over the services. |
| `src/web/host.py` | pywebview window creation and lifecycle. The only module importing `webview`. |
| `src/web/static/index.html` | Single page: sidebar shell, ⌘K palette, drawer, Explore view. |
| `src/web/static/css/tokens.css` | Design tokens — colour, type scale, spacing, radii, shadows. |
| `src/web/static/css/app.css` | Component styles built from tokens. |
| `src/web/static/js/api.js` | `fetch` wrapper that attaches the auth token; error handling. |
| `src/web/static/js/store.js` | Tiny observable app state. No framework. |
| `src/web/static/js/components/*.js` | `sidebar.js`, `palette.js`, `drawer.js`, `explore.js`. |
| `src/web/static/js/main.js` | Boot: read token, wire components, initial render. |
| `tests/web/test_server_auth.py` | Token auth and loopback binding. |
| `tests/web/test_api_library.py` | Library, search, browse and track-detail endpoints. |
| `tests/web/test_api_recommendations.py` | Recommendations endpoint. |
| `tests/web/test_static_assets.py` | Static serving, MIME types, path traversal. |
| `tests/web/test_no_heavy_imports.py` | `src/web/server.py` and `api.py` import without `webview`/`essentia`/`tkinter`. |
| `tests/web/conftest.py` | Fixtures: synthetic library on disk, running server, HTTP client. |

**Modify:**

| Path | Change |
|---|---|
| `requirements.txt` | Add `pywebview>=5.0`. |
| `.github/workflows/test-macos.yml` | Add `pywebview` to the install line. Keep `lxml`. |
| `src/cosine_companion.py` | Add a `ui-web` Typer command. Do not touch the frozen-launch branch or the existing default. |
| `docs/UI_FEATURE_INVENTORY.md` | Append a short "PR 3a coverage" section mapping the Explore controls this PR reimplements. Do not edit existing claims; `tests/test_inventory_self_consistency.py` must stay green. |
| `README.md` | Document `ui-web` as experimental and the extra dependency. |

**Do not create** `src/services/playlist_service.py` — that is PR 4.

---

## API Contract

All endpoints are under `/api/`. All require the token. All responses are `application/json;
charset=utf-8`. Errors use `{"error": {"code": "<slug>", "message": "<human text>"}}` with a
matching HTTP status.

| Method | Path | Query | 200 body |
|---|---|---|---|
| GET | `/api/health` | — | `{"ok": true, "app": "cosine-companion", "api_version": 1}` |
| GET | `/api/library` | — | `{"track_count": int, "is_empty": bool, "data_dir": str, "xml_path": str \| null}` |
| GET | `/api/tracks` | `limit` (default 50, max 500) | `{"tracks": [TrackSummary], "total": int}` — first `limit` tracks in `meta_ix` order, for the palette's empty state |
| GET | `/api/tracks/search` | `q` (required), `limit` (default 20, max 100) | `{"results": [TrackSummary], "query": str}` |
| GET | `/api/tracks/{track_id}` | — | `{"track": TrackDetail}` or 404 `unknown_track` |
| GET | `/api/tracks/{track_id}/recommendations` | `topk` (default 500), `final_top` (default 200), `limit` (default 50, max 200) | `{"seed": TrackDetail, "recommendations": [Recommendation]}` |

**`TrackSummary`** — exactly the dict `LibrarySession.search_tracks` returns:
`{"track_id", "artist", "title", "display_name"}`.

**`TrackDetail`** — `LibrarySession.get_track(track_id)` JSON-sanitised (see Task 3), plus a
`"playlists": null` field reserved for PR 4. Do not invent playlist data.

**`Recommendation`** — the `ExploreSession.Recommendation` dataclass as a dict:
`{"track_id", "artist", "title", "bpm", "key", "path_local", "cosine", "score", "key_score",
"bpm_score"}`.

**Error codes:** `unauthorized` (401), `unknown_track` (404), `not_found` (404),
`bad_request` (400), `empty_library` (409, when `library.is_empty` and the endpoint needs an
index), `internal` (500).

**Status codes are part of the contract** and are asserted by tests. A recommendations request
for a valid track in an empty library returns **409 `empty_library`**, not 500 and not an empty
list.

---

## Task 1: Package skeleton, asset resolution, and the import guard

**Files:**
- Create: `src/web/__init__.py`, `src/web/assets.py`, `tests/web/__init__.py`,
  `tests/web/test_no_heavy_imports.py`
- Modify: `requirements.txt`, `.github/workflows/test-macos.yml`

**Interfaces:**
- Produces: `assets.static_dir() -> pathlib.Path` — the directory containing `index.html`.
  Resolution order: (1) `sys._MEIPASS / "web" / "static"` when `getattr(sys, "frozen", False)`,
  (2) the directory adjacent to `assets.py`. Raises `FileNotFoundError` with the paths it tried
  when neither exists.

**Why this task exists first:** the spike found that under PyInstaller 6.x onedir, `--add-data`
payloads land in `Contents/Frameworks`, *not* `Contents/Resources`. Getting asset resolution
wrong is the single most likely way this PR passes locally and fails frozen.

- [ ] **Step 1:** Write `tests/web/test_no_heavy_imports.py`. It must launch a **subprocess**
      (not an in-process import) running the 3.10 interpreter with a script that imports
      `web.server` and `web.api`, then asserts that `"webview"`, `"tkinter"`, `"essentia"`,
      and `"tensorflow"` are all absent from `sys.modules`. Follow the pattern already used by
      the existing services UI-import guard test — read it first and match its style.
- [ ] **Step 2:** Run it. Expected: FAIL (`ModuleNotFoundError: web`).
- [ ] **Step 3:** Write a test for `assets.static_dir()`: it returns an existing directory
      containing `index.html`; and with `sys.frozen`/`sys._MEIPASS` monkeypatched to a temp dir
      laid out as `web/static/index.html`, it returns that path instead.
- [ ] **Step 4:** Run it. Expected: FAIL.
- [ ] **Step 5:** Create `src/web/__init__.py` (empty or docstring only — **no imports**),
      `src/web/assets.py`, and a placeholder `src/web/static/index.html` containing only
      `<!doctype html><title>Cosine Companion</title>`. Create empty `src/web/server.py` and
      `src/web/api.py` so the guard test can import them.
- [ ] **Step 6:** Run both tests. Expected: PASS.
- [ ] **Step 7:** Add `pywebview>=5.0` to `requirements.txt` under a `# Web UI` heading. Add
      `pywebview` to the `pip install` line in `.github/workflows/test-macos.yml`, preserving
      `lxml` and `"pytest>=7.0"` exactly.
- [ ] **Step 8:** Run the full suite. Expected: 315 + new tests, all pass.
- [ ] **Step 9:** Commit: `feat(web): package skeleton and PyInstaller-aware asset resolution`

---

## Task 2: HTTP server — loopback binding, token auth, routing

**Files:**
- Modify: `src/web/server.py`
- Test: `tests/web/test_server_auth.py`, `tests/web/conftest.py`

**Interfaces:**
- Consumes: `assets.static_dir()`.
- Produces:
  - `class CocoServer` with `__init__(self, api, static_dir, host="127.0.0.1", port=0)`,
    `.start() -> None` (spawns the daemon thread, returns once bound), `.stop() -> None`,
    and read-only properties `.port -> int`, `.token -> str`, `.url -> str`
    (`http://127.0.0.1:<port>/?key=<token>`).
  - The token is `secrets.token_urlsafe(32)`, generated per process in `__init__`.
  - `api` is any object exposing `handle(method: str, path: str, query: dict[str, list[str]])
    -> tuple[int, dict]` — status code and a JSON-serialisable body. Task 3 supplies the real
    one; Task 2's tests use a stub. **Define this protocol now and do not change it later.**

**Auth rules — assert every one of these:**
- A request to any `/api/*` path with no token → **401** `unauthorized`.
- With a wrong token → **401**.
- Token accepted from the `X-Coco-Token` header **or** the `key` query parameter.
- Token comparison uses `hmac.compare_digest`, not `==`.
- Static asset requests (`/`, `/css/…`, `/js/…`) are served **without** a token so the page can
  bootstrap; the page then reads `key` from its own URL and sends the header on API calls.
  The API is the thing being protected, not the static shell.

- [ ] **Step 1:** Write `tests/web/conftest.py` with a `server` fixture that constructs
      `CocoServer` with a stub api, starts it, yields it, and stops it. Use the real ephemeral
      port. Client calls use `http.client.HTTPConnection` — **do not add `requests`**.
- [ ] **Step 2:** Write `tests/web/test_server_auth.py` covering all five auth rules above,
      plus: the bound socket's host is exactly `127.0.0.1`; two `CocoServer` instances get
      different tokens; `.stop()` releases the port.
- [ ] **Step 3:** Run. Expected: FAIL.
- [ ] **Step 4:** Implement `CocoServer` on `http.server.ThreadingHTTPServer` +
      `BaseHTTPRequestHandler`. Suppress the default stderr access log (override
      `log_message`) — it would pollute the frozen app's output. `daemon_threads = True`.
- [ ] **Step 5:** Run. Expected: PASS.
- [ ] **Step 6:** Write `tests/web/test_static_assets.py`: `GET /` returns 200 `text/html`;
      `GET /css/app.css` returns 200 `text/css`; `GET /js/main.js` returns 200 with a
      JavaScript MIME type; a missing asset returns 404; **and `GET /../../etc/passwd` and
      `GET /%2e%2e/%2e%2e/etc/passwd` both return 404 or 403, never file contents.** Path
      traversal is a real risk in hand-rolled static serving — resolve the requested path and
      assert it is inside `static_dir` before opening it.
- [ ] **Step 7:** Run, implement, run. Expected: PASS.
- [ ] **Step 8:** Commit: `feat(web): loopback HTTP server with token auth and static serving`

---

## Task 3: Library, browse, search and track-detail endpoints

**Files:**
- Modify: `src/web/api.py`
- Test: `tests/web/test_api_library.py`, `tests/web/conftest.py`

**Interfaces:**
- Consumes: `LibrarySession` (`.track_count`, `.is_empty`, `.data_dir`, `.get_track`,
  `.search_tracks`, `.meta_ix`), `SettingsStore` (`.xml_path`), the `CocoServer` api protocol
  from Task 2.
- Produces: `class CocoApi` with `__init__(self, library, settings)` and
  `handle(method, path, query) -> tuple[int, dict]`, implementing `/api/health`,
  `/api/library`, `/api/tracks`, `/api/tracks/search`, `/api/tracks/{track_id}`.

**The JSON-sanitisation problem — this is the crux of the task.** `get_track` returns a dict
built from a pandas row. It will contain `numpy.float64`, `numpy.int64`, and `NaN`, none of
which `json.dumps` can serialise (`NaN` serialises to the literal `NaN`, which is invalid JSON
and **will** break `JSON.parse` in WKWebView). Write one `_jsonable(value)` helper that maps
numpy scalars to Python scalars and `NaN`/`NaT`/`None` to `null`, and route every service
value through it. Test it directly with a row containing a `NaN` bpm — the real library has
tracks with missing BPM.

**Fixture requirement:** `conftest.py` must build a **synthetic** library on disk in a
`tmp_path` — a small `meta.parquet`, `embeddings.parquet`, `index.npy`, `ids.json` with ~6
tracks, at least one with `NaN` bpm and one with a non-ASCII artist name. Tests must **never**
read the maintainer's real `data/` directory, and must never write anywhere outside `tmp_path`.
Reuse the existing fixture helpers under `tests/` if any already build such a library — look
before writing new ones.

- [ ] **Step 1:** Write the synthetic-library fixture and a `_jsonable` unit test.
- [ ] **Step 2:** Write `tests/web/test_api_library.py`: `/api/health` shape; `/api/library`
      returns the real count for the synthetic library; `/api/tracks?limit=3` returns 3 with
      `total` equal to the full count; `limit=9999` clamps to 500; `/api/tracks/search?q=` with
      a missing `q` returns **400 `bad_request`**; a matching query returns the expected
      `display_name` (note it uses an **en dash** `–`, not a hyphen); an unknown track id
      returns **404 `unknown_track`**; a known id returns a `track` object whose `bpm` is
      `null` for the NaN row and whose non-ASCII artist survives a round trip; every response
      body survives `json.loads(json.dumps(body))`.
- [ ] **Step 3:** Run. Expected: FAIL.
- [ ] **Step 4:** Implement `CocoApi` for these routes. Route matching may be a simple ordered
      list of `(method, compiled regex, handler)` — no routing library.
- [ ] **Step 5:** Run. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(web): library, browse, search and track-detail endpoints`

---

## Task 4: Recommendations endpoint

**Files:**
- Modify: `src/web/api.py`
- Test: `tests/web/test_api_recommendations.py`

**Interfaces:**
- Consumes: `ExploreSession.recommend(track_id, topk=DEFAULT_TOPK, final_top=DEFAULT_FINAL_TOP)
  -> List[Recommendation]`.
- Produces: `GET /api/tracks/{track_id}/recommendations` per the API Contract table.

**Behaviour requirements:**
- Defaults must be `topk=500, final_top=200` — the values the Tkinter Explore tab uses
  (`docs/UI_FEATURE_INVENTORY.md` documents this; confirm the exact numbers there before
  hardcoding, and cite the line you confirmed them from in the commit message).
- `limit` truncates the returned list **after** ranking. It must not be passed to `final_top`.
- Results must come back in the order `ExploreSession` returns them — do not re-sort.
- An unknown seed → 404 `unknown_track`. An empty library → 409 `empty_library`.
- Non-integer `topk`/`final_top`/`limit` → 400 `bad_request`, not a 500 traceback.

- [ ] **Step 1:** Write `tests/web/test_api_recommendations.py` covering: happy path against
      the synthetic library returns a non-empty list whose first element has all ten
      `Recommendation` fields; the seed itself is **not** in its own recommendations;
      `limit=2` returns 2; ordering matches a direct `ExploreSession.recommend(...)` call made
      in the test **with the same arguments** (compare `track_id` sequences); unknown seed
      404; empty library 409; `topk=abc` → 400.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the route.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Run the whole suite in the clean-venv configuration described in Verification.
- [ ] **Step 6:** Commit: `feat(web): exact-search recommendations endpoint`

---

## Task 5: Design system and application shell

**Files:**
- Modify: `src/web/static/index.html`
- Create: `src/web/static/css/tokens.css`, `src/web/static/css/app.css`,
  `src/web/static/js/api.js`, `store.js`, `main.js`,
  `components/{sidebar,palette,drawer}.js`

**This is the task the whole project was for.** The approved direction is mockup B: dark,
modern, generous whitespace, real typography. Concretely:

- **Tokens first.** Every colour, space, radius, font size and shadow is a CSS custom property
  in `tokens.css`. No hard-coded hex values anywhere in `app.css` or in JS.
- **Dark theme**, near-black surfaces with layered elevation rather than borders everywhere.
- **Type:** system font stack (`-apple-system, BlinkMacSystemFont, "SF Pro Text", …`).
  A clear scale — do not use more than six sizes.
- **Camelot keys render as pill badges**, coloured by key family so harmonic neighbours are
  visually adjacent. Colour must not be the *only* signal — the pill always shows its text.
- **Similarity renders as a score bar**, not a bare number. Show the numeric value too.
- **Motion:** transitions ≤200 ms; respect `prefers-reduced-motion`.
- **Accessibility:** every interactive element is a real `<button>`/`<a>` and is keyboard
  reachable with a visible `:focus-visible` ring. Contrast ≥4.5:1 for body text.

**Shell structure (locked decision "C"):**
- Left **sidebar** with four destinations: **Explore, Set Creator, Library, Export**. Only
  Explore is functional in this PR; the other three render a clearly-labelled
  "Coming in the next PR" placeholder. Do **not** hide them — the shell shape is part of what
  is being reviewed.
- A persistent **⌘K palette** (also `Ctrl+K`) that searches tracks via `/api/tracks/search`.
  With an empty query it shows the first 50 tracks from `/api/tracks` rather than nothing —
  the Tkinter dialogs' empty-on-blank-query behaviour is a defect this PR deliberately fixes
  (it is listed in the backlog and characterised by an existing test against the *service*;
  that test asserts service behaviour and must not be changed).
  `Esc` closes it. Arrow keys move selection. `Enter` opens the drawer.
- A right-hand **detail drawer** showing the selected track's metadata, with a **"Playlists"
  section rendering the placeholder "Playlist membership arrives in the next update."** Do not
  fabricate playlist data or call any playlist endpoint — it does not exist yet.

**No framework.** `store.js` is a ~40-line observable: `getState()`, `setState(patch)`,
`subscribe(fn)`. Components are functions that take a root element and subscribe.

- [ ] **Step 1:** Write `tokens.css` and `app.css`.
- [ ] **Step 2:** Write `index.html` with the shell markup and semantic landmarks
      (`<nav>`, `<main>`, `<aside>`).
- [ ] **Step 3:** Write `api.js` — reads `key` from `location.search` once, stores it, attaches
      `X-Coco-Token` to every request, throws a typed error carrying the API's `error.code`.
- [ ] **Step 4:** Write `store.js`, `sidebar.js`, `palette.js`, `drawer.js`, `main.js`.
- [ ] **Step 5:** Verify by hand: run `python -m cosine_companion ui-web` (available after
      Task 7) or serve the static dir, and confirm in **Safari** — not Chrome — that the
      palette opens on ⌘K, filters, and opens the drawer. Capture what you checked.
- [ ] **Step 6:** Commit: `feat(web): design system and application shell`

---

## Task 6: Explore destination

**Files:**
- Create: `src/web/static/js/components/explore.js`
- Modify: `src/web/static/js/main.js`, `app.css`

**Behaviour — this must match what the Tkinter Explore tab does.** Read the Explore section of
`docs/UI_FEATURE_INVENTORY.md` in full before writing this and implement every catalogued
control. At minimum: pick a seed track, view ranked recommendations with artist, title, BPM,
Camelot key and match score, and re-seed by selecting a recommendation.

**Anything from the inventory you deliberately do not implement in this PR must be listed in
the PR description under "Deferred to PR 3b", with the inventory line number.** Silent
omission is the one failure mode this PR cannot have — the inventory is the acceptance
contract for the whole rewrite.

- [ ] **Step 1:** Read the inventory's Explore/recommendations section and write down the
      control list you are implementing against.
- [ ] **Step 2:** Implement `explore.js`: seed card (gradient, per mockup B), recommendation
      rows with Camelot pill + score bar, empty state, error state, loading state.
- [ ] **Step 3:** Wire re-seeding: clicking a recommendation makes it the new seed.
- [ ] **Step 4:** Verify by hand in Safari against the real 1,307-track library in this
      worktree's `data/`. Confirm a query returns in well under a second — PR 1 measured
      5 ms per query, so anything sluggish is a frontend bug, not the engine.
- [ ] **Step 5:** Commit: `feat(web): Explore destination`

---

## Task 7: pywebview host and the `ui-web` entry point

**Files:**
- Create: `src/web/host.py`
- Modify: `src/cosine_companion.py`
- Test: `tests/web/test_host_importable.py`

**Interfaces:**
- Produces: `host.run_web_ui(data_dir: Optional[Path] = None, debug: bool = False) -> None` —
  constructs `LibrarySession.load()`, `SettingsStore`, `ExploreSession`, `CocoApi`,
  `CocoServer`; starts the server; creates the webview window at `server.url`; calls
  `webview.start()`; stops the server on return.

**Critical constraints:**
- `webview.start()` **must** run on the macOS main thread. The HTTP server runs in the daemon
  thread, not the reverse.
- Window title `Cosine Companion`, initial size 1280×840, `min_size` 960×640.
- `debug=True` enables devtools — the spike confirmed these work even in a frozen build.
- The new Typer command is `ui-web`. **Do not change the existing default launch path**: the
  frozen no-argument branch at the top of `cosine_companion.py` and the existing Tkinter
  command must behave exactly as they do today.

- [ ] **Step 1:** Write `tests/web/test_host_importable.py`: importing `web.host` succeeds
      (pywebview is installed in CI) and does **not** import `tkinter`. Do not attempt to open
      a window in tests — there is no display in CI.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `host.py` and the `ui-web` Typer command with `--debug` and
      `--data-dir` options.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Launch it for real against the worktree's `data/` and confirm the window
      opens, Explore works, and closing the window exits the process cleanly with no orphaned
      thread. Record what you observed.
- [ ] **Step 6:** Assert Tkinter is untouched: launch the Tkinter app once and confirm it still
      starts.
- [ ] **Step 7:** Commit: `feat(web): pywebview host and ui-web entry point`

---

## Task 8: Verification, docs, and PR

- [ ] **Step 1:** Full suite in the dev environment. Record the exact collected/passed counts.
- [ ] **Step 2:** **Clean-venv gate.** In a fresh clone of the branch (not this worktree — a
      clone has no `data/`), create a 3.10 venv, `pip install numpy pandas pyarrow lxml
      "pytest>=7.0" pywebview`, and run the suite. Record counts. Any test that silently
      *skips* here is a test that cannot gate a merge — call out every skip and why.
- [ ] **Step 3:** Confirm `python -c "import web.server, web.api"` succeeds with neither
      essentia nor tensorflow installed.
- [ ] **Step 4:** Update `README.md`: `ui-web` as experimental, the `pywebview` dependency, and
      that Tkinter remains the default.
- [ ] **Step 5:** Append the "PR 3a coverage" section to `docs/UI_FEATURE_INVENTORY.md`. Run
      `tests/test_inventory_self_consistency.py` and confirm it still passes.
- [ ] **Step 6:** Push and open a PR titled
      **"Web backbone: loopback API, pywebview host, and the Explore destination (PR 3a)"**.
      The description must contain: the API contract table; the clean-venv counts; a
      **"Deferred to PR 3b"** list with inventory line numbers; a screenshot or a precise
      description of what the window looks like; and an explicit statement that Tkinter is
      unchanged and still the default.
- [ ] **Step 7:** Confirm GitHub Actions `pytest` is green on the PR before reporting done.

---

## Self-Review Notes

- **Spec coverage:** §4.1 `src/web/` layout → Tasks 1–4, 7. §4.3 loopback + token + `_MEIPASS`
  → Tasks 1, 2. §5.1 shell → Task 5. §5.2 drawer → Task 5 (playlists deliberately stubbed;
  §6 is PR 4). §5.3 inventory as contract → Task 6, Task 8 Step 5. §8 "UI tests over the JSON
  API, not the DOM" → Tasks 2–4. §5.4 long-running work (progress, cancellation, in-place
  reload) is **PR 3b**, not this PR — Export and Reindex are not implemented here.
- **Known gap, accepted:** this PR has no automated test of the rendered UI. The API is tested;
  the frontend is verified by hand in Safari. Introducing a browser-automation dependency to
  test a 5-file frontend is not worth the packaging risk. PR 3c can revisit.
- **Risk:** `prefers-reduced-motion`, focus rings, and Camelot pill contrast are easy to
  claim and easy to skip. The reviewer should check these in the CSS, not take them on trust.
