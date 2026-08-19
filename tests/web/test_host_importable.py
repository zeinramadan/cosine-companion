"""The pywebview host: importable, wired correctly, and opening nothing on import.

No window is opened here. CI is headless, and a test that needed a display
would be a test that never runs where it matters. What is checked is everything
around the window: that ``web.host`` imports at all (pywebview is installed in
CI), that importing it does not drag Tkinter in, that it opens nothing as a
side effect of being imported, and that the session it builds is the right one -
including for a data directory with no index, where the window must still open
onto a stated empty state rather than a traceback.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from webtest_support import WEB_LIBRARY_TRACK_COUNT

SRC = Path(__file__).resolve().parent.parent.parent / "src"

webview = pytest.importorskip(
    "webview",
    reason="pywebview is the web UI's one runtime dependency; CI installs it",
)

from web import host  # noqa: E402


def _subprocess_modules(program):
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=str(SRC), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_the_host_imports():
    assert host.run_web_ui is not None


def test_importing_the_host_does_not_load_tkinter():
    """The web UI is an alternative to Tkinter, not a wrapper around it. A
    frozen build that loaded both would pay for both."""
    loaded = _subprocess_modules(
        "import sys\n"
        "import web.host\n"
        "print(','.join(sorted(m for m in sys.modules if m.split('.')[0] == 'tkinter')))\n"
    )

    assert loaded == ""


def test_importing_the_host_does_not_load_essentia():
    loaded = _subprocess_modules(
        "import sys\n"
        "import web.host\n"
        "print(','.join(sorted(m for m in sys.modules "
        "if m.split('.')[0] in ('essentia', 'tensorflow'))))\n"
    )

    assert loaded == ""


def test_importing_the_host_opens_no_window():
    """A module that creates a window at import time cannot be tested, cannot
    be introspected, and would open one the moment anything imported it."""
    output = _subprocess_modules(
        "import web.host, webview\n"
        "print(len(webview.windows))\n"
    )

    assert output == "0"


def test_the_window_is_the_size_the_plan_specifies():
    assert host.WINDOW_TITLE == "Cosine Companion"
    assert (host.WINDOW_WIDTH, host.WINDOW_HEIGHT) == (1280, 840)
    assert host.WINDOW_MIN_SIZE == (960, 640)


# -- what the host assembles ------------------------------------------------


def test_the_host_builds_an_api_over_the_given_data_directory(web_data_dir):
    api, library = host.build_api(web_data_dir)

    status, body = api.handle("GET", "/api/library", {})

    assert status == 200
    assert body["track_count"] == WEB_LIBRARY_TRACK_COUNT
    assert body["data_dir"] == str(web_data_dir)
    assert library.track_count == WEB_LIBRARY_TRACK_COUNT


def test_the_host_reads_settings_from_beside_the_index(web_data_dir):
    """The Tkinter app uses DATA/settings.json (ui/app.py:185); the web host
    must look in the same place or the two disagree about the XML path."""
    (web_data_dir / "settings.json").write_text(
        '{"xml_path": "/tmp/collection.xml"}', encoding="utf-8"
    )

    api, _ = host.build_api(web_data_dir)
    _, body = api.handle("GET", "/api/library", {})

    assert body["xml_path"] == "/tmp/collection.xml"


def test_a_data_directory_with_no_index_still_yields_a_usable_api(tmp_path):
    """The window must open. A missing or half-written index is exactly when a
    user needs to be told something, and a traceback before the first frame
    tells them nothing.

    LibrarySession.load raises here - FileNotFoundError for absent files, or
    ValueError from the loader's validation for inconsistent ones - so the host
    falls back to an unloaded session, which reports is_empty and drives the
    "No index yet" state.
    """
    api, library = host.build_api(tmp_path / "empty")

    status, body = api.handle("GET", "/api/library", {})

    assert status == 200
    assert body["is_empty"] is True
    assert body["track_count"] == 0
    assert library.is_empty


def test_an_inconsistent_index_does_not_stop_the_window_opening(web_data_dir):
    """The loader validates ids.json against index.npy and raises ValueError on
    a mismatch - the same condition the Tkinter app reports as "Inconsistent
    Index Data" (tests/test_app.py). Here it degrades to the empty state."""
    (web_data_dir / "ids.json").write_text('["only-one-id"]', encoding="utf-8")

    api, library = host.build_api(web_data_dir)
    _, body = api.handle("GET", "/api/library", {})

    assert body["is_empty"] is True
    assert library.is_empty


def test_the_api_the_host_builds_serves_recommendations(web_data_dir):
    api, _ = host.build_api(web_data_dir)

    status, body = api.handle("GET", "/api/tracks/f01/recommendations", {})

    assert status == 200
    assert body["recommendations"]


def test_the_server_the_host_builds_is_loopback_and_tokened(web_data_dir):
    """Assembled without starting a window, so the wiring is checkable in CI."""
    api, _ = host.build_api(web_data_dir)
    server = host.build_server(api)
    server.start()
    try:
        assert server.socket_address[0] == "127.0.0.1"
        assert server.url.startswith(f"http://127.0.0.1:{server.port}/?key=")
        assert server.authorises(server.token)
    finally:
        server.stop()


# -- the token is not printed ----------------------------------------------


def test_the_url_the_host_prints_does_not_carry_the_token(stub_api, static_dir):
    """``server.url`` has to carry ``?key=<token>`` - it is what bootstraps the
    page. Printing it to stdout writes a live credential into terminal
    scrollback and any log the launcher is piped into, where it outlives the
    process that could still use it."""
    from web.server import CocoServer

    running = CocoServer(stub_api, static_dir)
    running.start()
    try:
        assert running.token in running.url
        assert running.token not in running.display_url
        assert running.display_url == f"http://127.0.0.1:{running.port}"
    finally:
        running.stop()


def test_the_host_prints_the_redacted_url_and_not_the_other_one():
    """A source check: the printing happens inside ``webview.start()``'s
    caller, which cannot run without a display."""
    import inspect

    from web import host

    source = inspect.getsource(host.run_web_ui)
    printed = [line for line in source.splitlines() if "print(" in line]

    assert any("server.display_url" in line for line in printed)
    assert not any(
        "server.url" in line for line in printed
    ), f"the token-carrying URL is printed:\n{chr(10).join(printed)}"
