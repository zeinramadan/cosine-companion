"""Shared fixtures for the service characterisation tests.

Two libraries are available:

``fixture_library``
    The twelve committed tracks from ``fixture_library.py``. Runs everywhere,
    including CI, and is what the golden values are pinned against.

``real_library``
    The fingerprinted library captured by the real-library goldens. ``data/``
    is gitignored, so on CI it does not exist. A missing or changed library is
    **skipped with a stated reason** rather than producing unrelated golden
    failures. Nothing here ever writes to it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_library import write_fixture_library  # noqa: E402
from real_library_guard import (  # noqa: E402
    fingerprint_mismatch_reason,
    load_expected_fingerprint,
)

REAL_LIBRARY_FILES = ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json")


def real_library_available(data_dir):
    return all((data_dir / name).is_file() for name in REAL_LIBRARY_FILES)


@pytest.fixture(scope="session")
def real_library_fingerprint():
    """The committed identity of the library used to capture the goldens."""
    return load_expected_fingerprint()


@pytest.fixture(scope="session")
def real_data_dir(real_library_fingerprint):
    """The matching real data directory, or an actionable skip."""
    from config import DATA

    if not real_library_available(DATA):
        pytest.skip(
            "the real-library fixture is not present: data/ is gitignored, so "
            "these assertions only run on a developer machine with all four "
            "index files. The committed fixture_library tests guard engine "
            "behaviour everywhere, including CI."
        )

    mismatch_reason = fingerprint_mismatch_reason(DATA, real_library_fingerprint)
    if mismatch_reason:
        pytest.skip(mismatch_reason)
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
