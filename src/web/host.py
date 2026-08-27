#!/usr/bin/env python3
"""The pywebview host: the one module that owns a window.

This is the ONLY module under ``src/web/`` permitted to import ``webview``.
Everything else - the server, the API, the asset resolver - stays free of a GUI
toolkit so the whole API surface can be tested on a headless CI runner that has
no display and no Essentia. tests/web/test_no_heavy_imports.py enforces that,
including the exemption for this file.

**Thread ownership.** ``webview.start()`` must run on the macOS main thread; it
does not return until the last window closes. So the HTTP server is what goes
into a daemon thread, not the other way round, and the server is stopped in a
``finally`` once the window is gone.

Importing this module opens nothing. A window is created only inside
``run_web_ui``.
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

import webview

from config import DATA
from core.index_store import INDEX_MANIFEST_FILENAME, legacy_index_file_paths
from services.explore_session import ExploreSession
from services.library_session import LibrarySession
from services.playlist_service import PlaylistService
from services.settings_store import SettingsStore

from web import assets
from web.api import CocoApi
from web.server import CocoServer

WINDOW_TITLE = "Cosine Companion"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 840
WINDOW_MIN_SIZE = (960, 640)

#: Where the Tkinter app keeps its settings (``ui/app.py:185``). The two front
#: ends must agree about the configured XML path.
SETTINGS_FILENAME = "settings.json"

INDEX_LOAD_ERROR_CODE = "index_load_failed"
_INDEX_REBUILD_ROUTE = (
    "Open Settings, save the path to a Rekordbox XML export, then choose "
    "Rebuild All Embeddings."
)


def _has_index_artifacts(data_dir: Path) -> bool:
    """Whether ``data_dir`` contains a committed or partial index file set."""
    paths = (*legacy_index_file_paths(data_dir), data_dir / INDEX_MANIFEST_FILENAME)
    return any(path.exists() for path in paths)


def _index_load_error(error: Exception) -> Dict[str, str]:
    """Describe an unusable saved index without exposing exception details."""
    if isinstance(error, ValueError):
        reason = "The saved library index is inconsistent and could not be loaded."
    elif isinstance(error, FileNotFoundError):
        reason = "The saved library index is incomplete and could not be loaded."
    else:
        reason = "The saved library index could not be read."
    return {
        "code": INDEX_LOAD_ERROR_CODE,
        "message": f"{reason} {_INDEX_REBUILD_ROUTE}",
    }


class _HostApi(CocoApi):
    """Add the host's startup diagnosis to the library summary."""

    def __init__(self, *args, library_load_error=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._library_load_error = library_load_error

    def _library(self, query):
        status, body = super()._library(query)
        # A successful rebuild reloads this same session. Stop reporting the
        # startup failure as soon as that happens, including for a valid
        # zero-track index (``ids == []`` rather than an unloaded ``None``).
        if self._library_load_error is not None and self.library.snapshot().ids is None:
            body["load_error"] = dict(self._library_load_error)
        return status, body


def _load_library(
    data_dir: Path,
) -> Tuple[LibrarySession, Optional[Dict[str, str]]]:
    """Load the library and distinguish first run from an unusable saved index.

    The window has to open. ``LibrarySession.load`` raises FileNotFoundError
    when no index exists and ValueError when validation finds existing files
    inconsistent. Both cases return an unloaded session so the window opens,
    but only the genuine no-artifact case is first-run. Every other read
    failure is returned as a sanitized diagnosis for the web UI; the raw
    exception remains terminal-only developer output.
    """
    try:
        return LibrarySession.load(data_dir), None
    except Exception as error:  # noqa: BLE001 - any read failure ends the same way
        if isinstance(error, FileNotFoundError) and not _has_index_artifacts(data_dir):
            return LibrarySession(data_dir), None
        print(f"Could not load the library from {data_dir}: {error}", flush=True)
        return LibrarySession(data_dir), _index_load_error(error)


def build_api(data_dir: Optional[Path] = None) -> Tuple[CocoApi, LibrarySession]:
    """Assemble the services and the JSON API over ``data_dir``.

    Separate from ``run_web_ui`` so the wiring is testable without a display.
    Returns the API and the library, because callers want to inspect both.
    """
    resolved = Path(data_dir) if data_dir is not None else DATA
    library, library_load_error = _load_library(resolved)
    settings = SettingsStore(resolved / SETTINGS_FILENAME)
    # Passed explicitly rather than left to CocoApi's default so the wiring is
    # visible here with the rest of it. Constructing it reads nothing; the
    # tables are opened on the first drawer that asks for them, and their
    # absence is a state the drawer renders rather than an error.
    playlists = PlaylistService(resolved)
    api = _HostApi(
        library,
        settings,
        explore=ExploreSession(library),
        playlists=playlists,
        library_load_error=library_load_error,
    )
    return api, library


def build_server(api: CocoApi) -> CocoServer:
    """A loopback server for ``api``, not yet started."""
    return CocoServer(api, assets.static_dir())


def run_web_ui(data_dir: Optional[Path] = None, debug: bool = False) -> None:
    """Open the web UI and block until the window closes.

    Args:
        data_dir: the index directory. ``None`` uses the configured one.
        debug: enable devtools. The packaging spike confirmed these work in a
            frozen build too, which is the only practical way to debug one.
    """
    api, library = build_api(data_dir)
    server = build_server(api)
    server.start()

    try:
        # display_url, not url: url carries ?key=<token>, and printing that
        # writes a live credential into terminal scrollback, shell history and
        # whatever log the launcher is piped into - where it outlives the
        # process that could still use it. The webview is handed the real URL
        # below; nothing a human reads gets the token.
        #
        # flush=True: launched from a terminal the output is a pipe, not a
        # tty, so without it the URL sits in the buffer until the window closes
        # - which is exactly when it stops being useful.
        print(f"Cosine Companion web UI on {server.display_url}", flush=True)
        print(f"{library.track_count} tracks indexed", flush=True)

        webview.create_window(
            WINDOW_TITLE,
            server.url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=WINDOW_MIN_SIZE,
        )
        # Blocks on the main thread until the last window is closed.
        webview.start(debug=debug)
    finally:
        server.stop()
