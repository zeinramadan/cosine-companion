"""The Library destination's full browse document and delete mutation."""

import json

import numpy as np
import pandas as pd
import pytest

from core.loader import index_file_paths
from services.library_session import LibrarySession
from web.api import CocoApi


@pytest.fixture
def api(web_library, settings):
    return CocoApi(web_library, settings)


def post(api, body):
    return api.handle("POST", "/api/library/tracks/delete", {}, body)


def test_library_tracks_returns_every_field_needed_by_the_destination(api):
    status, body = api.handle("GET", "/api/library/tracks", {})

    assert status == 200
    assert len(body["tracks"]) == body["total"] == 14
    assert set(body["tracks"][0]) == {
        "track_id",
        "artist",
        "title",
        "album",
        "key",
        "bpm",
        "path_local",
    }
    json.dumps(body, allow_nan=False)


def test_delete_removes_every_selected_track_and_reports_the_new_count(
    api, web_library
):
    status, body = post(api, {"track_ids": "f02\nf05"})

    assert status == 200
    assert body == {
        "deleted": 2,
        "track_ids": ["f02", "f05"],
        "library": {"track_count": 12, "is_empty": False},
    }
    assert web_library.get_track("f02") is None
    assert web_library.get_track("f05") is None


def test_delete_records_metadata_beside_the_session_library(api, web_data_dir):
    post(api, {"track_ids": "f02"})

    recorded = json.loads((web_data_dir / "deleted_tracks.json").read_text())
    assert recorded == {"f02": {"artist": "Blawan", "title": "Why They Hide"}}


def test_committed_generation_stays_row_aligned_and_reloads(api, web_data_dir):
    post(api, {"track_ids": "f02\nf05"})

    meta_path, emb_path, index_path, ids_path = index_file_paths(web_data_dir)
    meta = pd.read_parquet(meta_path)
    embeddings = pd.read_parquet(emb_path)
    vectors = np.load(index_path)
    ids = json.loads(ids_path.read_text())

    assert len(meta) == len(embeddings) == len(vectors) == len(ids) == 12
    assert embeddings["track_id"].tolist() == ids
    emb_vectors = embeddings[
        [column for column in embeddings.columns if column != "track_id"]
    ].to_numpy()
    assert np.array_equal(vectors, emb_vectors)
    assert set(meta["track_id"]) == set(ids)
    reloaded = LibrarySession.load(web_data_dir)
    assert reloaded.ids == ids
    assert reloaded.index.ids == ids


def test_deleting_the_last_track_commits_a_reloadable_empty_matrix(
    web_library, settings, web_data_dir
):
    api = CocoApi(web_library, settings)
    all_ids = "\n".join(web_library.ids)

    status, body = post(api, {"track_ids": all_ids})

    assert status == 200
    assert body["library"] == {"track_count": 0, "is_empty": True}
    _meta, _emb, index_path, ids_path = index_file_paths(web_data_dir)
    assert np.load(index_path).shape == (0, 8)
    assert json.loads(ids_path.read_text()) == []
    reloaded = LibrarySession.load(web_data_dir)
    assert reloaded.track_count == 0
    assert reloaded.is_empty is True
    assert reloaded.vectors.shape == (0, 8)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "f01",
        {},
        {"track_ids": []},
        {"track_ids": ""},
        {"track_ids": "f01\n"},
        {"track_ids": "f01\nf01"},
        {"track_ids": "f01", "extra": True},
    ],
)
def test_delete_rejects_every_malformed_document_without_mutating(api, body):
    status, response = post(api, body)

    assert status == 400
    assert response["error"]["code"] == "bad_request"
    assert api.library.track_count == 14


def test_delete_rejects_an_unknown_track_as_one_atomic_selection(api):
    status, body = post(api, {"track_ids": "f01\nunknown\nf02"})

    assert status == 404
    assert body["error"]["code"] == "unknown_track"
    assert api.library.track_count == 14
    assert api.library.get_track("f01") is not None


def test_a_failed_generation_write_leaves_the_preceding_index_readable(
    api, web_data_dir, monkeypatch
):
    before = tuple(path.read_bytes() for path in index_file_paths(web_data_dir))

    def fail_before_commit(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(np, "save", fail_before_commit)
    with pytest.raises(OSError, match="disk full"):
        post(api, {"track_ids": "f02"})

    assert tuple(path.read_bytes() for path in index_file_paths(web_data_dir)) == before
    assert api.library.track_count == 14
    assert LibrarySession.load(web_data_dir).track_count == 14
    assert not (web_data_dir / "library_index.json").exists()
    assert list(web_data_dir.glob(".*.tmp")) == []
