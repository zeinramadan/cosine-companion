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
from typing import Optional, Tuple

import webview

from config import DATA
from services.explore_session import ExploreSession
from services.library_session import LibrarySession
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


def _load_library(data_dir: Path) -> LibrarySession:
    """Load the library, or return an unloaded session if it cannot be read.

    The window has to open. ``LibrarySession.load`` raises FileNotFoundError
    when the four index files are absent and ValueError when the loader's
    validation finds them inconsistent - and both are exactly the moments a
    user needs to be told something, which a traceback before the first frame
    does not do. An unloaded session reports ``is_empty``, which the frontend
    renders as "No index yet".

    This is not a silent repair: the reason is printed, and the Tkinter app's
    own "Inconsistent Index Data" dialog (tests/test_app.py) is unchanged.
    """
    try:
        return LibrarySession.load(data_dir)
    except Exception as error:  # noqa: BLE001 - any read failure ends the same way
        print(f"Could not load the library from {data_dir}: {error}", flush=True)
        return LibrarySession(data_dir)


def build_api(data_dir: Optional[Path] = None) -> Tuple[CocoApi, LibrarySession]:
    """Assemble the services and the JSON API over ``data_dir``.

    Separate from ``run_web_ui`` so the wiring is testable without a display.
    Returns the API and the library, because callers want to inspect both.
    """
    resolved = Path(data_dir) if data_dir is not None else DATA
    library = _load_library(resolved)
    settings = SettingsStore(resolved / SETTINGS_FILENAME)
    return CocoApi(library, settings, explore=ExploreSession(library)), library


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
