"""Fixtures for the web layer: a running server, a client, synthetic libraries.

Two rules this file exists to keep:

* **Nothing here reads the maintainer's real ``data/`` directory.** Every
  library these tests see is built from scratch under ``tmp_path``. The
  services suite has a ``real_library`` fixture that skips when ``data/`` is
  absent; the web suite deliberately has no equivalent, because an API test
  that only runs on one machine cannot gate a merge.
* **No new test dependency.** The client is ``http.client`` from the standard
  library.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from webtest_support import (  # noqa: E402
    Client,
    StubApi,
    write_web_fixture_library,
)

from web.server import CocoServer  # noqa: E402


@pytest.fixture
def static_dir():
    """The real front end, so the static tests serve the files that ship."""
    from web import assets

    return assets.static_dir()


@pytest.fixture
def stub_api():
    return StubApi()


@pytest.fixture
def server(stub_api, static_dir):
    """A started CocoServer on an ephemeral loopback port, stopped on teardown."""
    running = CocoServer(stub_api, static_dir)
    running.start()
    try:
        yield running
    finally:
        running.stop()


@pytest.fixture
def client(server):
    return Client("127.0.0.1", server.port)


@pytest.fixture
def web_data_dir(tmp_path):
    """A synthetic fourteen-track library on disk, inside tmp_path only."""
    return write_web_fixture_library(tmp_path / "data", audio_dir=tmp_path / "audio")


@pytest.fixture
def web_library(web_data_dir):
    from services.library_session import LibrarySession

    return LibrarySession.load(web_data_dir)


@pytest.fixture
def empty_library(tmp_path):
    """A session that was never loaded: no index, no metadata, is_empty True.

    This is the only reachable "empty library" state. Deleting every track
    through ``LibrarySession.delete_tracks`` also empties ``meta_ix`` (and
    writes to the real deleted-tracks file unless that is patched out), so
    there is no way to hold a *known* track id in a library with no index.
    Constructing an unloaded session touches no disk at all.
    """
    from services.library_session import LibrarySession

    return LibrarySession(tmp_path / "empty-data")


@pytest.fixture
def settings(tmp_path):
    from services.settings_store import SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    store.set("xml_path", str(tmp_path / "collection.xml"))
    return store
