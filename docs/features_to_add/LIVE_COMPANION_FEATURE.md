# Auto Current Track – Implementation Plan

**Status**: Proposed / not implemented in the current codebase.

This document lays out clean, incremental steps to add **automatic current track detection** to the Cosine Companion app. Start with **Option A (SQLite polling)** on laptop setups; later you can swap or extend to Pro DJ Link (CDJs/XDJ) or file-based history watchers.

---

## Option A: Poll Rekordbox SQLite DB (Recommended First)

**Goal:** In Performance mode on your laptop, detect the latest loaded/played track by reading Rekordbox’s SQLite database in **read-only** mode.

### 1) Locate the Rekordbox DB
- **macOS:** `~/Library/Application Support/Pioneer/rekordbox/rekordbox3.db`
- **Windows:** `C:\Users\<YOU>\AppData\Roaming\Pioneer\rekordbox\rekordbox3.db`

> Tip: The schema changes across versions. Start by connecting read-only and listing tables.

### 2) Add a Provider Module
Create `providers/rb_db.py` with a watcher function:

```python
# providers/rb_db.py
import sqlite3, time
from pathlib import Path

def _db_path():
    # TODO: add Windows path if needed
    return Path.home() / "Library/Application Support/Pioneer/rekordbox/rekordbox3.db"

def watch_rekordbox_db(callback, stop_event, interval=1.5):
    db = _db_path()
    if not db.exists():
        return
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = conn.cursor()
    last = None
    while not stop_event.is_set():
        try:
            cur.execute(
                """
                SELECT djmdSong.Title, djmdSong.Artist, djmdSong.Location
                  FROM djmdHistory
                  JOIN djmdSong ON djmdSong.ID = djmdHistory.SongID
                 ORDER BY djmdHistory.StartTime DESC LIMIT 1;
                """
            )
            row = cur.fetchone()
            if row and row != last:
                last = row
                title, artist, location = row[0], row[1], row[2]
                callback({"title": title, "artist": artist, "path": location})
        except Exception:
            pass
        time.sleep(interval)
```

### 3) Integrate with the UI (non-invasive)
In `src/ui/app.py` (or a dedicated mixin):
- Build a `by_path` mapping from `meta.parquet` once during init: `{path or path_local -> track_id}` (normalize paths by stripping `file://` and URL-decoding as needed).
- Add a method:

```python
def on_external_track_change(self, meta: dict):
    # meta = {"title":..., "artist":..., "path":...}
    tid = self.by_path.get(normalize(meta.get("path"))) or self.lookup_by_artist_title(meta)
    if tid:
        self.set_current(tid)
```

- Start the watcher thread on app start and stop it on close:

```python
import threading
from providers.rb_db import watch_rekordbox_db

self.stop_event = threading.Event()
threading.Thread(target=watch_rekordbox_db,
                 args=(self.on_external_track_change, self.stop_event),
                 daemon=True).start()

# on close handler:
self.stop_event.set()
```

### 4) Notes & Pitfalls
- Rekordbox may lock the DB; use `mode=ro` and handle exceptions so the UI never crashes.
- Poll every 1–2 s and **debounce** repeated rows (track didn’t change).
- Schema may differ; if the join above fails, inspect table names and adapt.

---

## Option B: Pro DJ Link Listener (CDJs/XDJ on LAN)

When performing with CDJs/XDJ connected over Ethernet/Wi‑Fi, listen for deck events and set current track on `track_loaded`.

### Steps
1. Add `providers/prolink.py` using a community lib (e.g., `python-prolink`) or your own UDP listener.
2. On `track_loaded`, emit `{title, artist, path}` and reuse `on_external_track_change()` in the UI.
3. Control which provider is active via a CLI flag or a config file (e.g., `--auto current=db|prolink|off`).

**Pros:** Works without Rekordbox running.  
**Cons:** Requires LAN access and proper packet handling.

---

## Option C: History XML/CSV Watcher

If you regularly export history to XML/CSV, watch that file for modifications and parse the last entry.

### Steps
1. Add `providers/history_file.py` using `watchdog` to detect changes.
2. Parse last `<TRACK>` (XML) or last row (CSV), map to `track_id`, call `set_current`.

**Pros:** Very simple to reason about.  
**Cons:** Requires manual/automated export; less real-time than DB polling.

---

## Path → Track ID Mapping

The indexer stores `meta.parquet` with columns:
`[track_id, path, path_local, artist, title, bpm, key]`.

Recommended mapping order:
1. **Exact path match**: Prefer Rekordbox’s `Location` (usually `file://...`). Normalize by stripping `file://` and URL-decoding.
2. **Fallback**: Title + Artist fuzzy match if path is missing/misaligned.

Create and cache dictionaries:
- `by_path` (normalized absolute path → track_id)
- `by_title_artist` (lowercased `artist|title` → list of track_ids)

---

## UI Hooks (Summary)
- Add `on_external_track_change(meta)` in `src/ui/app.py` (or a mixin).
- Start exactly one provider thread on app start (configurable).
- Stop it on window close.
- The rest of the UI remains unchanged.

---

## Optional: Config + CLI
Add a simple `config.toml` (or `typer` options) to select provider and polling interval:

```toml
[auto]
current = "db"   # db | prolink | file | off
interval = 1.5
```

Then wire `--auto current=db` in `cosine_companion.py` and pass to `ui.run_ui(auto_provider=...)`.

---

## Done Outcome
Once implemented, loading a new track in Rekordbox (or on a CDJ deck) will automatically update the **Current track** label and refresh the suggestions list—while keeping manual “Set Current Track” as a fallback.
