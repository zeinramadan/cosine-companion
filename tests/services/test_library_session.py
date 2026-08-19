"""Characterisation tests for LibrarySession.

LibrarySession takes over the six loose attributes App used to hold (meta,
meta_ix, emb_ix, idx, V, ids) and the deletion logic that lived in
library_tab.py:213-273.

Read-only assertions run against the fingerprinted real library in data/, which
is treated as immutable input and skipped when that directory is absent or has
changed (it is absent on CI because it is gitignored). Every destructive test
builds its own small library under tmp_path; nothing here writes to data/.

The three divergent track searches are characterised in test_track_searches.py.

Known defects are pinned as CURRENT behaviour, not fixed - see
docs/UI_FEATURE_INVENTORY.md section 4 and spec 3.2.
"""

import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

import numpy as np
import pandas as pd
import pytest

from core.index_store import read_index_generation
from core.loader import index_file_paths
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


def test_loads_the_real_library(real_library, real_library_fingerprint):
    assert real_library.track_count == real_library_fingerprint["track_count"]


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


def test_vectors_and_ids_agree_with_the_index(
    real_library, real_library_fingerprint
):
    assert (
        real_library.vectors.shape[0]
        == len(real_library.ids)
        == real_library_fingerprint["track_count"]
    )
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


def test_snapshot_cannot_land_inside_the_delete_publication(
    tmp_library, monkeypatch
):
    session = LibrarySession.load(tmp_library)
    delete_reached_persist = threading.Event()
    release_delete = threading.Event()
    snapshot_attempted = threading.Event()
    snapshot_finished = threading.Event()
    captured = []
    real_persist = session._persist

    def pausing_persist(*args):
        real_persist(*args)
        delete_reached_persist.set()
        assert release_delete.wait(timeout=5), "the delete was never released"

    monkeypatch.setattr(session, "_persist", pausing_persist)

    delete_thread = threading.Thread(target=session.delete_tracks, args=(["t2"],))

    def capture():
        snapshot_attempted.set()
        captured.append(session.snapshot())
        snapshot_finished.set()

    snapshot_thread = threading.Thread(target=capture)
    delete_thread.start()
    assert delete_reached_persist.wait(timeout=5), "delete never reached persistence"
    snapshot_thread.start()
    assert snapshot_attempted.wait(timeout=5), "snapshot thread never started"
    try:
        assert not snapshot_finished.wait(timeout=0.05)
    finally:
        release_delete.set()
        delete_thread.join(timeout=5)
        snapshot_thread.join(timeout=5)

    assert not delete_thread.is_alive()
    assert not snapshot_thread.is_alive()
    assert captured[0].ids == ["t1", "t3", "t4"]
    assert "t2" not in captured[0].meta_ix.index


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
    _meta, _emb, index_path, ids_path = index_file_paths(tmp_library)
    assert json.loads(ids_path.read_text()) == ["t1", "t3", "t4"]
    assert np.load(index_path).shape == (3, 4)
    assert json.loads((tmp_library / "ids.json").read_text()) == ["t1", "t3", "t4"]
    assert np.load(tmp_library / "index.npy").shape == (3, 4)
    assert len(pd.read_parquet(tmp_library / "meta.parquet")) == 3


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
# Deletion publishes `meta` with the rest of the new generation. Inventory
# defect #14 is fixed by the Library destination PR.
# --------------------------------------------------------------------------


def test_deletion_rebuilds_meta(tmp_library):
    session = LibrarySession.load(tmp_library)
    before = session.meta

    session.delete_tracks(["t2"])

    assert session.meta is not before
    assert "t2" not in list(session.meta["track_id"].values)
    assert len(session.meta) == 3


def test_deletion_publishes_every_in_memory_view_together(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert "t2" not in session.meta_ix.index      # Library tab: updated
    assert "t2" not in session.emb_ix.index       # recommendations: updated
    assert "t2" not in session.ids                # index: updated
    assert session.index.ids == ["t1", "t3", "t4"]
    assert session.track_count == 3
    assert "t2" not in list(session.meta["track_id"].values)
    assert len(session.meta) == 3


def test_the_explore_picker_no_longer_finds_a_deleted_track(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    meta = session.meta
    q = "artist b"
    m = meta[
        (meta["artist"].str.lower().str.contains(q, na=False))
        | (meta["title"].str.lower().str.contains(q, na=False))
    ].head(50)
    assert list(m["track_id"].values) == []
    assert "t2" not in session.meta_ix.index


def test_the_all_tracks_export_list_drops_a_deleted_track(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert list(session.meta["track_id"].values) == ["t1", "t3", "t4"]


def test_the_all_tracks_count_and_export_list_agree_after_delete(tmp_library):
    session = LibrarySession.load(tmp_library)

    session.delete_tracks(["t2"])

    assert len(session.meta) == 3
    assert len(list(session.meta["track_id"].values)) == 3
    assert session.track_count == 3


def test_the_export_tab_label_source_reads_len_meta():
    """Guard against the label quietly reverting to track_count."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "ui" / "playlist_export_tab.py").read_text()

    assert "count = len(self.library.meta)" in source
    assert "self.library.track_count" not in source


def test_reload_preserves_the_already_refreshed_meta(tmp_library):
    session = LibrarySession.load(tmp_library)
    session.delete_tracks(["t2"])
    assert len(session.meta) == 3

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


def test_deleting_every_track_writes_a_reloadable_empty_index(tmp_library):
    LibrarySession.load(tmp_library).delete_tracks(["t1", "t2", "t3", "t4"])

    _meta, _emb, index_path, ids_path = index_file_paths(tmp_library)
    assert json.loads(ids_path.read_text()) == []
    assert np.load(index_path).shape == (0, 4)
    reloaded = LibrarySession.load(tmp_library)
    assert reloaded.is_empty is True
    assert reloaded.track_count == 0


def test_a_failure_before_the_manifest_commit_preserves_the_old_generation(
    tmp_library, monkeypatch
):
    session = LibrarySession.load(tmp_library)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(np, "save", boom)

    with pytest.raises(OSError, match="disk full"):
        session.delete_tracks(["t2"])

    # The legacy flat generation is still the committed generation. Partial
    # immutable files were never named by a manifest and are cleaned up.
    assert len(pd.read_parquet(tmp_library / "meta.parquet")) == 4
    assert len(pd.read_parquet(tmp_library / "embeddings.parquet")) == 4
    assert np.load(tmp_library / "index.npy").shape == (4, 4)
    assert json.loads((tmp_library / "ids.json").read_text()) == ["t1", "t2", "t3", "t4"]
    assert LibrarySession.load(tmp_library).track_count == 4
    assert not (tmp_library / "library_index.json").exists()


def test_a_failed_manifest_replace_preserves_the_previous_generation(
    tmp_library, monkeypatch
):
    import core.index_store as index_store

    session = LibrarySession.load(tmp_library)
    session.delete_tracks(["t2"])
    committed_paths = index_file_paths(tmp_library)
    committed_bytes = tuple(path.read_bytes() for path in committed_paths)
    real_replace = index_store.os.replace

    def fail_manifest_replace(source, destination):
        if destination == tmp_library / "library_index.json":
            raise OSError("replace refused")
        return real_replace(source, destination)

    monkeypatch.setattr(index_store.os, "replace", fail_manifest_replace)

    with pytest.raises(OSError, match="replace refused"):
        session.delete_tracks(["t3"])

    assert index_file_paths(tmp_library) == committed_paths
    assert tuple(path.read_bytes() for path in committed_paths) == committed_bytes
    assert session.ids == ["t1", "t3", "t4"]
    assert LibrarySession.load(tmp_library).ids == ["t1", "t3", "t4"]


def test_a_committed_generation_edited_in_place_is_rejected(tmp_library):
    LibrarySession.load(tmp_library).delete_tracks(["t2"])
    _meta, _emb, _index, ids_path = index_file_paths(tmp_library)
    ids_path.write_text('["different"]', encoding="utf-8")

    with pytest.raises(ValueError, match="ids file failed its SHA-256 check"):
        LibrarySession.load(tmp_library)


def test_a_malformed_manifest_never_falls_back_to_stale_flat_files(tmp_library):
    (tmp_library / "library_index.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="document is not an object"):
        LibrarySession.load(tmp_library)


def test_a_completed_indexing_write_uses_the_same_generation_commit(
    tmp_library, monkeypatch
):
    import core.loader as loader
    import core.persistence as persistence

    LibrarySession.load(tmp_library).delete_tracks(["t2"])
    assert (tmp_library / "library_index.json").is_file()
    deletion_generation = read_index_generation(tmp_library)

    monkeypatch.setattr(loader, "META_PQ", tmp_library / "meta.parquet")
    existing_meta, existing_embeddings = loader.load_existing_data()
    assert len(existing_meta) == len(existing_embeddings) == 3

    monkeypatch.setattr(persistence, "META_PQ", tmp_library / "meta.parquet")
    monkeypatch.setattr(persistence, "EMB_PQ", tmp_library / "embeddings.parquet")
    monkeypatch.setattr(persistence, "IDX_NPY", tmp_library / "index.npy")
    monkeypatch.setattr(persistence, "IDS_JSON", tmp_library / "ids.json")
    replacement = LibrarySession.load(tmp_library).snapshot()
    persistence.save_index_data(
        replacement.meta,
        replacement.emb_ix.reset_index(),
        replacement.vectors,
        replacement.ids,
    )

    indexing_generation = read_index_generation(tmp_library)
    assert indexing_generation.generation != deletion_generation.generation
    assert (
        indexing_generation.previous_generation == deletion_generation.generation
    )
    assert index_file_paths(tmp_library) == indexing_generation.as_tuple()
    assert all(
        flat.samefile(committed)
        for flat, committed in zip(
            (
                tmp_library / "meta.parquet",
                tmp_library / "embeddings.parquet",
                tmp_library / "index.npy",
                tmp_library / "ids.json",
            ),
            indexing_generation.as_tuple(),
        )
    )
    assert LibrarySession.load(tmp_library).ids == ["t1", "t3", "t4"]


def test_commits_retain_only_the_current_and_immediately_previous_generation(
    tmp_library,
):
    session = LibrarySession.load(tmp_library)

    committed = []
    for track_id in ("t1", "t2", "t3"):
        session.delete_tracks([track_id])
        generation = read_index_generation(tmp_library)
        committed.append(generation.generation)

    generation_ids_by_kind = []
    for stem, suffix in (
        ("meta", ".parquet"),
        ("embeddings", ".parquet"),
        ("index", ".npy"),
        ("ids", ".json"),
    ):
        generation_ids_by_kind.append(
            {
                path.name[len(stem) + 1 : -len(suffix)]
                for path in tmp_library.glob(f"{stem}.*{suffix}")
            }
        )

    expected = set(committed[-2:])
    assert all(generation_ids == expected for generation_ids in generation_ids_by_kind)
    current = read_index_generation(tmp_library)
    assert current.generation == committed[-1]
    assert current.previous_generation == committed[-2]
    assert committed[0] not in expected


def test_index_process_and_web_delete_serialize_their_generation_commits(
    tmp_library, monkeypatch
):
    """The CLI index path and web deletion may write from different processes.

    The child calls the exact ``save_index_data`` boundary used at the end of
    ``index_library``. It pauses while holding the short commit lock; the web
    deletion must reach that lock but cannot enter until the child releases it.
    """
    import core.index_store as index_store

    session = LibrarySession.load(tmp_library)
    attempted = threading.Event()
    acquired = threading.Event()
    failures = []
    real_lock = index_store._index_lock

    @contextlib.contextmanager
    def observed_lock(data_dir, exclusive):
        deleting = threading.current_thread().name == "web-delete"
        if deleting:
            attempted.set()
        with real_lock(data_dir, exclusive):
            if deleting:
                acquired.set()
            yield

    monkeypatch.setattr(index_store, "_index_lock", observed_lock)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.settimeout(30)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    repo_root = Path(__file__).resolve().parents[2]
    child_program = r"""
import contextlib
from pathlib import Path
import socket
import sys

import core.index_store as index_store
import core.persistence as persistence
from core.loader import load_all

data_dir = Path(sys.argv[1])
port = int(sys.argv[2])
meta, _meta_ix, emb_ix, _index, vectors, ids = load_all(data_dir)
persistence.META_PQ = data_dir / "meta.parquet"
persistence.EMB_PQ = data_dir / "embeddings.parquet"
persistence.IDX_NPY = data_dir / "index.npy"
persistence.IDS_JSON = data_dir / "ids.json"
real_lock = index_store._index_lock

@contextlib.contextmanager
def paused_lock(lock_data_dir, exclusive):
    with real_lock(lock_data_dir, exclusive):
        with socket.create_connection(("127.0.0.1", port), timeout=30) as barrier:
            barrier.settimeout(30)
            barrier.sendall(b"ready")
            if barrier.recv(1) != b"g":
                raise RuntimeError("parent did not release the commit")
        yield

index_store._index_lock = paused_lock
persistence.save_index_data(meta, emb_ix.reset_index(), vectors, ids)
"""
    child_environment = os.environ.copy()
    child_environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            [str(repo_root / "src"), child_environment.get("PYTHONPATH", "")],
        )
    )
    child = None
    barrier = None
    delete_thread = None

    def delete_in_web_process():
        try:
            session.delete_tracks(["t2"])
        except BaseException as error:  # noqa: BLE001 - asserted in parent
            failures.append(error)

    try:
        child = subprocess.Popen(
            [sys.executable, "-c", child_program, str(tmp_library), str(port)],
            cwd=str(repo_root),
            env=child_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        barrier, _address = listener.accept()
        barrier.settimeout(30)
        assert barrier.recv(5) == b"ready"

        delete_thread = threading.Thread(
            target=delete_in_web_process,
            name="web-delete",
        )
        delete_thread.start()
        assert attempted.wait(30), "web deletion never attempted its commit"
        assert not acquired.is_set(), "web deletion entered a child-held commit lock"

        barrier.sendall(b"g")
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, (stdout, stderr)
        delete_thread.join(30)
        assert not delete_thread.is_alive(), "web deletion never finished"
    finally:
        if barrier is not None:
            with contextlib.suppress(OSError):
                barrier.sendall(b"g")
            barrier.close()
        listener.close()
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=30)
        if delete_thread is not None:
            delete_thread.join(30)

    assert not failures
    assert acquired.is_set()
    assert LibrarySession.load(tmp_library).ids == ["t1", "t3", "t4"]
    current = read_index_generation(tmp_library)
    assert current.previous_generation is not None


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
