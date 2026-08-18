"""Characterisation tests for LibrarySession.

LibrarySession takes over the six loose attributes App used to hold (meta,
meta_ix, emb_ix, idx, V, ids) and the deletion logic that lived in
library_tab.py:213-273.

Read-only assertions run against the real 1,307-track library in data/, which is
treated as immutable input. Every destructive test builds its own small library
under tmp_path; nothing here writes to data/.

Known defects are pinned as CURRENT behaviour, not fixed - see
docs/UI_FEATURE_INVENTORY.md section 4 and spec 3.2.
"""

import json

import numpy as np
import pandas as pd
import pytest

import core.deleted_tracks as deleted_tracks_module
from services.library_session import LibrarySession

REAL_DATA_DIR = None  # resolved by the fixture below


@pytest.fixture(scope="module")
def real_library():
    """The real 1,307-track library. READ ONLY - never mutate through this."""
    from config import DATA

    return LibrarySession.load(DATA)


@pytest.fixture
def tmp_library(tmp_path, monkeypatch):
    """A four-track library on disk, plus an isolated deleted_tracks.json."""
    monkeypatch.setattr(
        deleted_tracks_module, "DELETED_TRACKS_JSON", tmp_path / "deleted_tracks.json"
    )
    _write_library(
        tmp_path,
        [
            ("t1", "Artist A", "Title One", "8A", 128.0, [1.0, 0.0, 0.0, 0.0]),
            ("t2", "Artist B", "Title Two", "9A", 130.0, [0.0, 1.0, 0.0, 0.0]),
            ("t3", "Artist C", "Title Three", "8B", 124.0, [0.0, 0.0, 1.0, 0.0]),
            ("t4", "Artist D", "Title Four", "5A", 126.0, [0.0, 0.0, 0.0, 1.0]),
        ],
    )
    return tmp_path


def _write_library(data_dir, rows):
    meta = pd.DataFrame(
        [
            {
                "track_id": tid,
                "path": f"file://localhost/tmp/{tid}.mp3",
                "artist": artist,
                "title": title,
                "album": "",
                "bpm": bpm,
                "key": key,
                "path_local": f"/tmp/{tid}.mp3",
            }
            for tid, artist, title, key, bpm, _ in rows
        ]
    )
    vectors = np.array([v for *_, v in rows], dtype="float32")
    emb = pd.concat(
        [
            pd.DataFrame({"track_id": [r[0] for r in rows]}),
            pd.DataFrame(vectors, columns=[f"v{i}" for i in range(vectors.shape[1])]),
        ],
        axis=1,
    )
    meta.to_parquet(data_dir / "meta.parquet", index=False)
    emb.to_parquet(data_dir / "embeddings.parquet", index=False)
    np.save(data_dir / "index.npy", vectors)
    (data_dir / "ids.json").write_text(json.dumps([r[0] for r in rows]))


# --------------------------------------------------------------------------
# Loading and read accessors
# --------------------------------------------------------------------------


def test_loads_the_real_library(real_library):
    assert real_library.track_count == 1307


def test_exposes_the_six_attributes_app_used_to_hold(real_library):
    assert isinstance(real_library.meta, pd.DataFrame)
    assert isinstance(real_library.meta_ix, pd.DataFrame)
    assert isinstance(real_library.emb_ix, pd.DataFrame)
    assert isinstance(real_library.vectors, np.ndarray)
    assert isinstance(real_library.ids, list)
    assert real_library.index is not None


def test_meta_ix_is_indexed_by_track_id(real_library):
    assert real_library.meta_ix.index.name == "track_id"
    assert "track_id" not in real_library.meta_ix.columns


def test_vectors_and_ids_agree_with_the_index(real_library):
    assert real_library.vectors.shape[0] == len(real_library.ids) == 1307
    assert real_library.index.ids == real_library.ids


def test_track_count_counts_metadata_rows(tmp_library):
    assert LibrarySession.load(tmp_library).track_count == 4


def test_is_empty_is_false_for_a_loaded_library(tmp_library):
    assert LibrarySession.load(tmp_library).is_empty is False


def test_get_track_round_trips_a_known_id(real_library):
    track = real_library.get_track("64638770")

    assert track["track_id"] == "64638770"
    assert track["artist"] == "Boris S."
    assert track["title"] == "Compression"
    assert track["key"] == "11B"
    assert track["bpm"] == 143.0


def test_get_track_returns_none_for_an_unknown_id(real_library):
    assert real_library.get_track("no-such-track") is None


def test_get_track_includes_path_local(real_library):
    """The exporter needs path_local, which recommend_for does not return."""
    assert real_library.get_track("64638770")["path_local"].endswith(".mp3")


# --------------------------------------------------------------------------
# search_tracks - exposes implementation A (recommendations/search.py)
# --------------------------------------------------------------------------


def test_search_tracks_matches_the_implementation_the_ui_dialogs_call(real_library):
    """AddAnchorDialog and TrackSelectorDialog both call
    recommendations.search.search_tracks. LibrarySession exposes THAT one, not
    the regex variant in pick_current nor the album/key variant in
    filter_library. The three are NOT unified in this PR."""
    from recommendations.search import search_tracks

    for query in ["boris", "compression", "SUPERFUNK", "no such artist anywhere"]:
        assert real_library.search_tracks(query, limit=20) == search_tracks(
            query, real_library.meta_ix, limit=20
        )


def test_search_tracks_returns_display_name_with_an_en_dash(real_library):
    result = real_library.search_tracks("compression", limit=20)[0]

    assert set(result) == {"track_id", "artist", "title", "display_name"}
    assert result["display_name"] == "Boris S. – Compression"


def test_search_tracks_returns_nothing_for_a_blank_query(real_library):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. This is why AddAnchorDialog and
    TrackSelectorDialog both open showing an EMPTY list despite their
    '# Initialize with all tracks' intent. Inventory defect #9."""
    assert real_library.search_tracks("", limit=100) == []
    assert real_library.search_tracks("   ", limit=100) == []


def test_search_tracks_treats_the_query_literally_not_as_a_regex(real_library):
    """The divergence from pick_current, which uses pandas str.contains and so
    reads the query as a regular expression. Documented, not unified."""
    literal = real_library.search_tracks("s.", limit=100)
    regex = real_library.meta[
        real_library.meta["artist"].str.lower().str.contains("s.", na=False)
        | real_library.meta["title"].str.lower().str.contains("s.", na=False)
    ].head(100)

    assert len(literal) == 3
    assert len(regex) == 100
    assert all("s." in (r["artist"] + " " + r["title"]).lower() for r in literal)


def test_search_tracks_honours_the_limit(real_library):
    assert len(real_library.search_tracks("a", limit=5)) == 5


def test_search_tracks_defaults_to_a_limit_of_twenty(real_library):
    assert len(real_library.search_tracks("a")) == 20


# --------------------------------------------------------------------------
# delete_tracks
# --------------------------------------------------------------------------


def test_delete_tracks_removes_from_memory(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert session.track_count == 3
    assert session.ids == ["t1", "t3", "t4"]
    assert "t2" not in session.meta_ix.index
    assert "t2" not in session.emb_ix.index
    assert session.get_track("t2") is None


def test_delete_tracks_rebuilds_the_index(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert session.index.ids == ["t1", "t3", "t4"]
    assert session.vectors.shape == (3, 4)
    assert [tid for tid, _ in session.index.search(np.array([0.0, 1.0, 0.0, 0.0], dtype="float32"), k=3)] == ["t1", "t3", "t4"]


def test_delete_tracks_returns_the_number_of_metadata_rows_removed(tmp_library):
    session = LibrarySession.load(tmp_library)

    assert session.delete_tracks(["t2", "t3"]) == 2


def test_delete_tracks_persists_to_all_four_files(tmp_library):
    LibrarySession.load(tmp_library).delete_tracks(["t2"])

    reloaded = LibrarySession.load(tmp_library)
    assert reloaded.track_count == 3
    assert reloaded.ids == ["t1", "t3", "t4"]
    assert json.loads((tmp_library / "ids.json").read_text()) == ["t1", "t3", "t4"]
    assert np.load(tmp_library / "index.npy").shape == (3, 4)


def test_delete_tracks_records_artist_and_title_in_deleted_tracks_json(tmp_library):
    LibrarySession.load(tmp_library).delete_tracks(["t2"])

    recorded = json.loads((tmp_library / "deleted_tracks.json").read_text())
    assert recorded == {"t2": {"artist": "Artist B", "title": "Title Two"}}


def test_delete_tracks_appends_to_an_existing_deleted_list(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])
    session.delete_tracks(["t3"])

    recorded = json.loads((tmp_library / "deleted_tracks.json").read_text())
    assert set(recorded) == {"t2", "t3"}


def test_delete_tracks_writes_meta_parquet_without_an_index_column(tmp_library):
    LibrarySession.load(tmp_library).delete_tracks(["t2"])

    meta = pd.read_parquet(tmp_library / "meta.parquet")
    assert "track_id" in meta.columns
    assert list(meta.columns)[0] == "track_id"


def test_delete_tracks_with_an_empty_selection_changes_nothing(tmp_library):
    session = LibrarySession.load(tmp_library)

    assert session.delete_tracks([]) == 0
    assert session.track_count == 4


# --------------------------------------------------------------------------
# Known defects, pinned as current behaviour
# --------------------------------------------------------------------------


def test_deleting_every_track_leaves_the_index_none_and_empty_arrays(tmp_library):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. library_tab.py:251-255 sets idx to None
    and V to a 0-d empty array once nothing remains. is_empty reports exactly
    that condition. Inventory defect #3."""
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t1", "t2", "t3", "t4"])

    assert session.index is None
    assert session.is_empty is True
    assert session.ids == []
    assert session.vectors.size == 0
    assert session.track_count == 0


def test_deleting_every_track_leaves_a_stale_index_npy(tmp_library):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. index.npy is only rewritten when
    len(V) > 0, so wiping the library leaves the OLD vectors on disk beside an
    empty ids.json. The next launch fails load_all validation and shows the
    'Inconsistent Index Data' dialog. Inventory defect #3, backlog
    backlog-n3-ids-lag-race."""
    LibrarySession.load(tmp_library).delete_tracks(["t1", "t2", "t3", "t4"])

    assert json.loads((tmp_library / "ids.json").read_text()) == []
    assert np.load(tmp_library / "index.npy").shape == (4, 4)  # stale, not rewritten

    with pytest.raises(ValueError, match="0 track IDs but index.npy has 4"):
        LibrarySession.load(tmp_library)


def test_the_four_file_rewrite_is_not_atomic(tmp_library, monkeypatch):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. library_tab.py:257-270 writes
    meta.parquet, embeddings.parquet, index.npy and ids.json in sequence with no
    temp-file-and-rename and no rollback. A failure partway through leaves the
    four mutually inconsistent, and the next launch cannot load them. Inventory
    defect #2, spec 3.2."""
    session = LibrarySession.load(tmp_library)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(np, "save", boom)

    with pytest.raises(OSError, match="disk full"):
        session.delete_tracks(["t2"])

    # meta and embeddings were already rewritten; index.npy and ids.json were not.
    assert len(pd.read_parquet(tmp_library / "meta.parquet")) == 3
    assert len(pd.read_parquet(tmp_library / "embeddings.parquet")) == 3
    assert np.load(tmp_library / "index.npy").shape == (4, 4)
    assert json.loads((tmp_library / "ids.json").read_text()) == ["t1", "t2", "t3", "t4"]

    with pytest.raises(ValueError, match="do not match"):
        LibrarySession.load(tmp_library)


def test_delete_tracks_mutates_in_place_so_concurrent_readers_see_the_swap(tmp_library):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. The export worker captures meta_ix /
    emb_ix / idx when it starts, then the main thread rebinds them here. This is
    the export/delete race in spec 3.2; the test pins that the rebind happens
    rather than pretending it is safe."""
    session = LibrarySession.load(tmp_library)
    captured_index = session.index
    captured_meta_ix = session.meta_ix

    session.delete_tracks(["t2"])

    assert session.index is not captured_index
    assert session.meta_ix is not captured_meta_ix
    assert captured_index.ids == ["t1", "t2", "t3", "t4"]  # the stale view lives on
    assert "t2" in captured_meta_ix.index


# --------------------------------------------------------------------------
# reload
# --------------------------------------------------------------------------


def test_reload_picks_up_changes_written_by_another_process(tmp_library):
    session = LibrarySession.load(tmp_library)
    assert session.track_count == 4

    _write_library(
        tmp_library,
        [("t9", "New Artist", "New Title", "1A", 120.0, [1.0, 0.0, 0.0, 0.0])],
    )
    session.reload()

    assert session.track_count == 1
    assert session.ids == ["t9"]
    assert session.index.ids == ["t9"]


def test_reload_uses_the_same_data_dir(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.reload()

    assert session.data_dir == tmp_library
