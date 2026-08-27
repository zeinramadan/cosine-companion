# Cosine Companion — Program Flow

> Related: [System Architecture](SYSTEM_ARCHITECTURE.md),
> [Embeddings Guide](EMBEDDINGS_GUIDE.md), and
> [Build Instructions](BUILD_INSTRUCTIONS.md).

Cosine Companion has one desktop frontend: a pywebview window over a
token-authenticated loopback JSON API. The CLI and web API share the same
headless services, processing pipeline, recommendation code, and persisted
library generation.

## Entry points

`src/cosine_companion.py` exposes these commands:

1. `index <xml> [--force] [--sample N]` — run the embedding pipeline directly.
2. `ui [--debug] [--data-dir DIR]` — open the desktop web interface.
3. `ui-web [--debug] [--data-dir DIR]` — compatibility alias for `ui`.
4. `import-playlists [xml] [--data-dir DIR]` — refresh playlist tables only.
5. `clean-duplicates <xml>` — report file-based duplicate candidates.

A frozen no-argument launch runs `ui` before Typer is imported. On macOS,
Finder may instead supply one `-psn_*` argument; that is treated identically.

## Desktop startup

```text
cosine_companion.py
  └─ _run_default_frontend()
      └─ web.host.run_web_ui(data_dir, debug)
          ├─ build_api(data_dir)
          │   ├─ LibrarySession.load(data_dir)
          │   │   └─ on missing/inconsistent index: unloaded LibrarySession
          │   ├─ SettingsStore(data_dir/settings.json)
          │   └─ CocoApi(library, settings)
          ├─ build_server(api)
          │   └─ bind 127.0.0.1 on an ephemeral port
          └─ webview.create_window(server.url)
              └─ webview.start()
```

The unloaded-session fallback is intentional: a missing or inconsistent index
must still open Settings so the user can select an XML export and rebuild.

If web infrastructure fails before or during startup, the launcher reports the
exception and exits 1. A terminal launch writes the diagnostic to stderr. A
frozen macOS launch uses `/usr/bin/osascript`; a frozen Windows launch uses
`MessageBoxW`. This keeps double-click failures visible without adding another
GUI runtime. `KeyboardInterrupt` remains an intentional quit and is not
converted into a startup failure.

## Browser/API request flow

```text
pywebview / browser
  └─ GET static HTML, CSS, and ES modules
  └─ JSON request with X-Coco-Token
      └─ web.server.CocoServer
          └─ web.api.CocoApi.handle()
              └─ services/*
                  ├─ LibrarySession
                  ├─ ExploreSession
                  ├─ SetBuilder
                  ├─ ExportService
                  ├─ PlaylistService
                  ├─ SettingsStore
                  └─ IndexingService
```

The server binds only to loopback and generates a per-process token. The page
receives that token in its bootstrap URL and sends it in a header for API
requests. Static assets require no token; every `/api/` route does.

The five destinations map to API surfaces as follows:

| Destination | Main API operations | Service owner |
|---|---|---|
| Explore | search, track detail, recommendations | `ExploreSession` |
| Library | list tracks, delete selected tracks | `LibrarySession` |
| Set Creator | build from positioned anchors | `SetBuilder` |
| Settings | read/update settings, start/stop re-index | `SettingsStore`, `IndexingService` |
| Export | start/stop export jobs | `ExportService` |

## Indexing flow

The direct CLI and background web job both reach
`processing.pipeline.index_library`:

```text
Rekordbox XML
  ├─ read_rekordbox_xml
  ├─ remove_simple_duplicates
  ├─ filter_deleted_tracks
  ├─ find_new_tracks
  ├─ DiscogsEffnetEmbedder.embed_file (per new track)
  ├─ merge metadata and embeddings
  ├─ build exact normalized NumPy matrix
  ├─ atomically publish one four-file index generation
  └─ refresh imported playlist tables
```

The four index files are:

- `meta.parquet`
- `embeddings.parquet`
- `index.npy`
- `ids.json`

`IndexingService` turns pipeline progress into `ProgressEvent` values. The web
API starts it through `POST /api/jobs/reindex`, and `web.jobs.JobRegistry`
publishes progress and terminal state for polling. Only one long-running job
may run at a time, so re-index and export cannot mutate/read the same generation
concurrently.

Cancellation is cooperative. The pipeline checks the cancellation event at the
start of each per-track iteration. An observed stop raises `KeyboardInterrupt`,
the job becomes `cancelled`, and no partial index generation is committed. A
stop delivered after the last checkpoint may arrive too late; the job then
finishes successfully with `cancel_requested: true`.

## Recommendation flow

```text
seed track id
  ├─ exact cosine scores against every normalized vector
  ├─ stable top-k selection
  ├─ key compatibility score
  ├─ BPM compatibility score, including half/double tempo
  ├─ weighted combined score
  └─ stable final ordering returned as JSON
```

Explore requests use a 500-track candidate pool and return at most 200 ranked
rows. The browser chooses how many to render and which supported sort key to
display.

## Set generation flow

The browser sends `{anchors, total_tracks}` to `POST /api/set`. Anchor positions
are one-based. `SetBuilder` captures one immutable library snapshot and delegates
to `recommendations.set_generator`, which fills the intervals around anchors
using transition-aware recommendation scores.

## Export flow

`POST /api/jobs/export` captures one library snapshot before accepting the job.
Per-seed mode writes one complete M3U per seed. Combined mode writes one
de-duplicated `Cosine_Recommendations.m3u`. Progress and cancellation use the
same job registry as re-indexing. Completed files remain on disk after an export
cancel; the terminal job record reports exactly what was written.

## Library deletion and its recovery gap

Deleting selected tracks rebuilds and atomically publishes a new index
generation, then records artist/title/path metadata in `deleted_tracks.json`.
`filter_deleted_tracks` consults that file on future indexing runs, preventing a
deleted track from immediately returning.

The product currently has no Undo control for this record. Recovering a mistaken
deletion requires closing the app, backing up and hand-editing
`deleted_tracks.json`, and re-indexing. The pure
`core.deleted_tracks.remove_from_deleted_tracks` function is intentionally kept
for a future recovery API, but no shipping path calls it today.

## Dependency direction

```text
web/ and cosine_companion.py
  └─ services/
      ├─ recommendations/
      ├─ processing/
      └─ core/
          └─ config/
```

`src/services/` and the headless parts of `src/web/` must not import a GUI
toolkit. The tests enforce that statically and by inspecting modules loaded in a
fresh subprocess. Processing and Essentia imports remain lazy so opening the UI
does not pay the TensorFlow import cost.

The retired desktop behavior used to review the rewrite is preserved separately
in [UI_FEATURE_INVENTORY.md](UI_FEATURE_INVENTORY.md) as a commit-addressed
historical record, not current product documentation.
