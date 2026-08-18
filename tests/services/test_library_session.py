"""Characterisation tests for LibrarySession.

LibrarySession takes over the six loose attributes App used to hold (meta,
meta_ix, emb_ix, idx, V, ids) and the deletion logic that lived in
library_tab.py:213-273.

Read-only assertions run against the real 1,307-track library in data/, which is
treated as immutable input and skipped when that directory is absent (it is
gitignored, so on CI it always is). Every destructive test builds its own small
library under tmp_path; nothing here writes to data/.

The three divergent track searches are characterised in test_track_searches.py.

Known defects are pinned as CURRENT behaviour, not fixed - see
docs/UI_FEATURE_INVENTORY.md section 4 and spec 3.2.
"""

import json

import numpy as np
import pandas as pd
import pytest

from services.library_session import LibrarySession, LibrarySnapshot


@pytest.fixture
def tmp_library(tmp_path, isolated_deleted_tracks):
    """A four-track library on disk, plus an isolated deleted_tracks.json."""
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
# snapshot
# --------------------------------------------------------------------------


def test_snapshot_carries_every_object_a_long_running_reader_needs(tmp_library):
    session = LibrarySession.load(tmp_library)

    snapshot = session.snapshot()

    assert isinstance(snapshot, LibrarySnapshot)
    assert snapshot.meta is session.meta
    assert snapshot.meta_ix is session.meta_ix
    assert snapshot.emb_ix is session.emb_ix
    assert snapshot.index is session.index
    assert snapshot.vectors is session.vectors
    assert snapshot.ids is session.ids


def test_snapshot_is_frozen(tmp_library):
    snapshot = LibrarySession.load(tmp_library).snapshot()

    with pytest.raises(Exception):
        snapshot.meta_ix = None


def test_snapshot_keeps_the_pre_delete_view(tmp_library):
    """The export/delete race, pinned: a snapshot taken before a delete still
    sees the deleted track, which is what the legacy export worker saw."""
    session = LibrarySession.load(tmp_library)
    snapshot = session.snapshot()

    session.delete_tracks(["t2"])

    assert "t2" in snapshot.meta_ix.index
    assert snapshot.index.ids == ["t1", "t2", "t3", "t4"]
    assert "t2" not in session.meta_ix.index
    assert session.index.ids == ["t1", "t3", "t4"]


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


def test_delete_tracks_records_artist_and_title_in_deleted_tracks_json(
    tmp_library, isolated_deleted_tracks
):
    LibrarySession.load(tmp_library).delete_tracks(["t2"])

    recorded = json.loads(isolated_deleted_tracks.read_text())
    assert recorded == {"t2": {"artist": "Artist B", "title": "Title Two"}}


def test_delete_tracks_appends_to_an_existing_deleted_list(
    tmp_library, isolated_deleted_tracks
):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])
    session.delete_tracks(["t3"])

    recorded = json.loads(isolated_deleted_tracks.read_text())
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
# Deletion leaves `meta` STALE. Inventory defect #14.
#
# perform_track_deletion never rebuilt App.meta, so every consumer that reads
# `meta` rather than `meta_ix` kept showing deleted tracks until the app was
# restarted. Rebuilding it in the service would silently repair that, and a
# baseline that quietly improves behaviour proves nothing about the next PR.
# --------------------------------------------------------------------------


def test_deletion_leaves_meta_stale(tmp_library):
    session = LibrarySession.load(tmp_library)
    before = session.meta

    session.delete_tracks(["t2"])

    assert session.meta is before, "meta was rebuilt; it must not be"
    assert "t2" in list(session.meta["track_id"].values)
    assert len(session.meta) == 4


def test_deletion_updates_meta_ix_ids_and_index_while_meta_lags(tmp_library):
    """The exact split: the Library tab (meta_ix) refreshes, the Explore picker
    and the all-tracks export (meta) do not."""
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert "t2" not in session.meta_ix.index      # Library tab: updated
    assert "t2" not in session.emb_ix.index       # recommendations: updated
    assert "t2" not in session.ids                # index: updated
    assert session.index.ids == ["t1", "t3", "t4"]
    assert session.track_count == 3
    assert "t2" in list(session.meta["track_id"].values)  # meta: STALE
    assert len(session.meta) == 4


def test_the_explore_picker_still_finds_a_deleted_track(tmp_library):
    """recommendations_tab.pick_current filters `library.meta`, so the deleted
    track is still offered - and choosing it then raises a KeyError from
    meta_ix.loc. Current behaviour; PR 3 backlog."""
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    meta = session.meta
    q = "artist b"
    m = meta[
        (meta["artist"].str.lower().str.contains(q, na=False))
        | (meta["title"].str.lower().str.contains(q, na=False))
    ].head(50)
    assert list(m["track_id"].values) == ["t2"]

    with pytest.raises(KeyError):
        session.meta_ix.loc["t2"]


def test_the_all_tracks_export_list_still_includes_a_deleted_track(tmp_library):
    """playlist_export_tab.get_export_track_ids reads
    list(meta['track_id'].values), so 'All tracks in collection' still exports
    the deleted one - it is skipped later, when create_m3u_playlist cannot find
    it in meta_ix."""
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert list(session.meta["track_id"].values) == ["t1", "t2", "t3", "t4"]


def test_the_all_tracks_count_label_reads_the_stale_table(tmp_library):
    """update_export_selection_info must use len(meta), NOT track_count, so the
    label and the export it describes agree. Using track_count made the label
    drop to 3 while the export still sent 4 ids."""
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert len(session.meta) == 4                       # what the label shows
    assert len(list(session.meta["track_id"].values)) == 4  # what it exports
    assert session.track_count == 3                     # the tempting wrong one


def test_the_export_tab_label_source_reads_len_meta():
    """Guard against the label quietly reverting to track_count."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "ui" / "playlist_export_tab.py").read_text()

    assert "count = len(self.library.meta)" in source
    assert "self.library.track_count" not in source


def test_reload_is_what_finally_refreshes_meta(tmp_library):
    """Restarting the app (or reload()) is the only thing that catches meta up -
    which is exactly why the user must restart to stop seeing deleted tracks."""
    session = LibrarySession.load(tmp_library)
    session.delete_tracks(["t2"])
    assert len(session.meta) == 4

    session.reload()

    assert len(session.meta) == 3
    assert "t2" not in list(session.meta["track_id"].values)


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


def test_delete_tracks_rebinds_rather_than_mutating(tmp_library):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. The export worker captures meta_ix /
    emb_ix / idx when it starts, then the main thread rebinds them here. This is
    the export/delete race in spec 3.2; the test pins that the rebind happens
    rather than pretending it is safe. What a captured view then *does* with
    that is covered by the interleaving tests in test_export_service.py."""
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
