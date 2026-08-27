# Cosine Companion — System Architecture

## 1. Overview

Cosine Companion is a local-first desktop application and CLI for searching a
DJ library by audio similarity, harmonic compatibility, and tempo. The desktop
surface is HTML/CSS/JavaScript hosted in a pywebview window. A small Python HTTP
server exposes the headless service layer only on loopback.

The supported packaged target is Apple Silicon macOS. Intel macOS and Windows
build infrastructure remains in the repository, but those packages are not
currently supported releases because of native Essentia constraints documented
in the README.

## 2. Layering

```text
┌───────────────────────────────────────────────────────────────┐
│ Desktop / CLI                                                 │
│ cosine_companion.py, web/host.py, web/static/                 │
├───────────────────────────────────────────────────────────────┤
│ Loopback transport                                            │
│ web/server.py, web/api.py, web/jobs.py                        │
├───────────────────────────────────────────────────────────────┤
│ Stateful application services                                 │
│ services/library_session.py, explore_session.py,              │
│ set_builder.py, export_service.py, indexing_service.py,       │
│ playlist_service.py, playlist_import.py, settings_store.py    │
├───────────────────────────────────────────────────────────────┤
│ Domain and processing                                         │
│ recommendations/, processing/, core/                          │
├───────────────────────────────────────────────────────────────┤
│ Configuration and persisted files                             │
│ config/, data/                                                │
└───────────────────────────────────────────────────────────────┘
```

Dependencies point downward. The services and headless web modules are kept
free of GUI-toolkit imports, and the test suite checks that both statically and
in fresh Python subprocesses. Essentia is loaded only when indexing starts;
ordinary settings, library, and recommendation imports do not load TensorFlow.

## 3. Desktop runtime

`web.host.run_web_ui` owns startup:

1. Resolve the selected data directory, or use the configured default.
2. Load `LibrarySession`; if files are absent or inconsistent, construct an
   unloaded session so the window can still reach Settings.
3. Bind `CocoServer` to `127.0.0.1` on an ephemeral port.
4. Generate a per-process bearer token for all `/api/` requests.
5. Create the pywebview window at the token-carrying bootstrap URL.
6. Start pywebview on the main thread and stop the server when the window ends.

The browser immediately removes the token from its visible URL and sends it in
`X-Coco-Token` for API requests. The display URL printed for developers is
redacted. Static assets are served directly from `src/web/static/` in source
runs and from `sys._MEIPASS/web/static/` in frozen runs.

The frontend has no compilation step. The checked-in HTML, CSS, and ES modules
are the production assets.

### Startup failure reporting

There is no secondary desktop frontend. Web startup failures are terminal and
exit with status 1. Terminal runs receive the technical cause on stderr. Frozen
double-click launches have no reliable stderr, so the entry point uses native
OS mechanisms: Standard Additions through `/usr/bin/osascript` on macOS and
`MessageBoxW` on Windows. These paths execute before Typer is imported.

## 4. API and security boundary

`web.server.CocoServer` is a `ThreadingHTTPServer` restricted to loopback. It
serves static files and delegates JSON routes to `CocoApi`. Security properties
include:

- every `/api/` route requires the per-process token;
- static paths are resolved under one fixed asset root;
- request bodies are bounded and parsed as JSON only for supported POST routes;
- response serialization rejects non-finite JSON values after normalization;
- `GET`/`HEAD` framing shares one response path;
- unknown routes and unsupported methods return explicit JSON errors.

The API is an adapter. It validates wire values, selects status codes, and calls
services; recommendation, indexing, export, and persistence policy do not live
in the transport layer.

## 5. Stateful services

### LibrarySession

`LibrarySession` is the in-process source of truth for a loaded index. It owns
metadata, embedding rows, the normalized matrix/index, and track-id order.
Readers capture immutable snapshots so long operations cannot combine fields
from different generations.

Deletion and indexing publication use a mutation lock. A replacement generation
is built privately, committed to disk, loaded, and published by rebinding the
session's references. Readers that already hold an earlier snapshot may finish;
new readers receive the new generation.

### ExploreSession

Explore takes a seed track and one library snapshot, requests exact cosine
neighbors, applies key/BPM scoring, and returns typed recommendation rows. The
desktop endpoint uses a candidate pool of 500 and a final cap of 200.

### SetBuilder

SetBuilder captures one library snapshot and fills positions around one-based
anchor tracks. The API bounds the requested set length and reports validation
errors without changing the underlying generator's policy.

### ExportService

An export captures its library view when the request is accepted. Per-seed mode
writes one M3U per seed; combined mode writes a single de-duplicated playlist.
The service reports real completion/failure counts and honors cooperative
cancellation.

### IndexingService

IndexingService binds a pipeline run to one explicit data directory and optional
live `LibrarySession`. It converts text progress into structured events and
refreshes the live session after a successful commit. The Essentia-backed
pipeline import is function-local.

### Settings and playlists

`SettingsStore` atomically writes `settings.json`. `PlaylistService` reads the
imported playlist generation beside the selected index. `playlist_import`
refreshes those tables without paying the embedding cost of a full re-index.

## 6. Background jobs

Exports and re-indexes run through `web.jobs.JobRegistry` because they outlive
one HTTP request. One immutable `JobSnapshot` carries state, progress, terminal
result, error, and whether cancellation was delivered.

Only one long-running job is accepted at a time. This prevents two writers from
interleaving and prevents an export from unknowingly crossing an index
generation. The browser polls ordinary JSON endpoints; this keeps all response
framing on the server's one tested path and allows a page reload to reattach.

Cancellation is cooperative:

- export returns a partial accounting and leaves complete output files in the
  user-selected directory;
- indexing raises at the next per-track checkpoint and publishes no partial
  generation;
- a cancellation delivered after the last checkpoint may be recorded but not
  change an already successful result.

## 7. Recommendation engine

Each indexed track has a 2,560-value Discogs-EffNet representation: 1,280 means
and 1,280 standard deviations. Vectors are normalized before persistence.
`NumpyCosIndex` performs exact full-matrix cosine scoring rather than an
approximate nearest-neighbor search.

The ranking policy combines:

- 70% audio cosine similarity;
- 20% Camelot-key compatibility;
- 10% BPM compatibility, including half-time and double-time relationships.

Stable sorting keeps tied results deterministic.

## 8. Indexing and persistence

The pipeline performs:

```text
XML parse
  → duplicate filtering
  → deleted-track filtering
  → incremental-track detection
  → per-file Essentia embeddings
  → metadata/embedding merge
  → normalized exact index build
  → atomic generation commit
  → playlist-table refresh
```

The committed index generation consists of:

| File | Purpose |
|---|---|
| `meta.parquet` | track metadata and local paths |
| `embeddings.parquet` | one 2,560-value vector row per track |
| `index.npy` | normalized float32 search matrix |
| `ids.json` | matrix-row to track-id mapping |

An atomic manifest in `core.index_store` prevents readers from observing a mix
of old and new files while publication is in progress.

Additional data files include `settings.json`, `deleted_tracks.json`, and the
playlist tables.

## 9. Deleted tracks

Deleting from Library rebuilds the four-file generation without the selected
tracks and records their metadata in `deleted_tracks.json`. Future pipeline
runs call `filter_deleted_tracks`, so those tracks stay excluded.

The desktop product currently has no Undo action. Recovery requires manually
removing the relevant JSON entry and re-indexing. The pure
`remove_from_deleted_tracks` function remains in `core/deleted_tracks.py` for a
future recovery endpoint; it is intentionally not removed with the retired
frontend.

## 10. Packaging

PyInstaller builds an onedir bundle and then a macOS `.app`. The recipe
explicitly includes web assets and hidden imports for the web host, API, server,
jobs, pywebview, and its Cocoa backend. It explicitly excludes the retired GUI
runtime and image bridge so collection hooks cannot silently restore them.

The bundle contains the verified Discogs-EffNet model, application assets,
native Essentia libraries, and the Python runtime. `LSMinimumSystemVersion` is
15.2, matching the locked native binary floor.

The `Build macOS` workflow installs the hashed Python 3.11 lock, downloads or
restores the model, verifies its exact bytes and GraphDef loadability, builds
the app, verifies the bundled model, creates a DMG, and uploads the artifact.

## 11. Repository layout

```text
src/
├── config/             configuration and paths
├── core/               loading, atomic persistence, exact index, deletion
├── processing/         XML parsing and Essentia embeddings
├── recommendations/    ranking, transitions, sets, playlist export
├── services/           headless state and use-case orchestration
├── utils/              non-UI helpers
├── web/                host, API, server, jobs, static frontend
└── cosine_companion.py entry point and CLI

tests/
├── services/           service contracts and concurrency
├── web/                API/server/host/static contracts
├── web/js/             browser-module tests under Node
└── manual/             real-library and real-Essentia harnesses
```

## 12. Verification strategy

The Python suite uses committed fixture libraries for merge gating. Browser
modules run under Node without a browser build. Import-boundary tests execute in
fresh subprocesses so transitive GUI or Essentia imports are observable.

Manual harnesses cover properties unsuitable for the normal suite:

- `tests/manual/real_indexing.py` runs the real model through web re-index jobs
  against temporary data and proves source-data integrity;
- `tests/manual/web_jobs_real_export.py` runs real-size export/cancel through a
  loopback server;
- `tests/manual/ranking_equivalence.py` measures ranking equivalence over a real
  library.

The source behavior used as the web rewrite's acceptance contract remains in
[UI_FEATURE_INVENTORY.md](UI_FEATURE_INVENTORY.md). It is explicitly frozen at
the last commit containing the retired implementation and is not maintained as
current architecture documentation.
