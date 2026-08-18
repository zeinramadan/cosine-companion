"""Shared fixtures for the service characterisation tests.

Two libraries are available:

``fixture_library``
    The twelve committed tracks from ``fixture_library.py``. Runs everywhere,
    including CI, and is what the golden values are pinned against.

``real_library``
    The user's actual 1,307-track library in ``data/``. That directory is
    gitignored, so on CI it does not exist and every test that asks for this
    fixture is **skipped with a stated reason** rather than erroring. Nothing
    here ever writes to it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_library import write_fixture_library  # noqa: E402

REAL_LIBRARY_FILES = ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json")

REAL_LIBRARY_TRACK_COUNT = 1307


def real_library_available():
    from config import DATA

    return all((DATA / name).exists() for name in REAL_LIBRARY_FILES)


@pytest.fixture(scope="session")
def real_data_dir():
    """The real data directory, or a skip when it is not checked out."""
    from config import DATA

    if not real_library_available():
        pytest.skip(
            "the real 1,307-track library is not present: data/ is gitignored, "
            "so these assertions only run on a developer machine. The golden "
            "values that guard engine behaviour everywhere live in the "
            "fixture_library tests."
        )
    return DATA


@pytest.fixture(scope="session")
def real_library(real_data_dir):
    """READ ONLY. Never mutate the library through this fixture."""
    from services.library_session import LibrarySession

    return LibrarySession.load(real_data_dir)


@pytest.fixture
def fixture_data_dir(tmp_path):
    """The twelve committed tracks on disk, with real (empty) audio files."""
    return write_fixture_library(tmp_path / "data", audio_dir=tmp_path / "audio")


@pytest.fixture
def fixture_library(fixture_data_dir):
    from services.library_session import LibrarySession

    return LibrarySession.load(fixture_data_dir)


@pytest.fixture
def isolated_deleted_tracks(tmp_path, monkeypatch):
    """Point deleted_tracks.json at tmp_path so data/ is never touched."""
    import core.deleted_tracks as deleted_tracks_module

    target = tmp_path / "deleted_tracks.json"
    monkeypatch.setattr(deleted_tracks_module, "DELETED_TRACKS_JSON", target)
    return target
