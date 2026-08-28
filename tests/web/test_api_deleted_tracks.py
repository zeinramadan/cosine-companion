"""Discovering and restoring tracks excluded from future index runs."""

import hashlib
import json

import pytest

import core.deleted_tracks as deleted_tracks_module
from web.api import CocoApi


@pytest.fixture
def deleted_path(web_data_dir):
    path = web_data_dir / "deleted_tracks.json"
    path.write_text(
        json.dumps(
            {
                "gone-2": {"artist": "Rene Wise", "title": "Tizer --skip"},
                "gone-1": {"artist": "Blawan", "title": "Toast"},
            }
        )
    )
    return path


@pytest.fixture
def api(web_library, settings, deleted_path):
    return CocoApi(web_library, settings)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore(api, track_ids):
    return api.handle(
        "POST",
        "/api/library/deleted-tracks/restore",
        {},
        {"track_ids": "\n".join(track_ids)},
    )


def test_deleted_tracks_are_discoverable_with_preserved_artist_and_title(api):
    status, body = api.handle("GET", "/api/library/deleted-tracks", {})

    assert status == 200
    assert body == {
        "tracks": [
            {
                "track_id": "gone-2",
                "artist": "Rene Wise",
                "title": "Tizer --skip",
            },
            {"track_id": "gone-1", "artist": "Blawan", "title": "Toast"},
        ],
        "total": 2,
    }
    json.dumps(body, allow_nan=False)


def test_restore_changes_only_the_explicit_session_data_dir(
    api, deleted_path, tmp_path, monkeypatch
):
    wrong_default = tmp_path / "default-data" / "deleted_tracks.json"
    wrong_default.parent.mkdir()
    wrong_default.write_text(
        json.dumps(
            {
                "gone-2": {"artist": "Default", "title": "Must stay"},
                "default-only": {"artist": "D", "title": "T"},
            }
        )
    )
    monkeypatch.setattr(deleted_tracks_module, "DELETED_TRACKS_JSON", wrong_default)
    explicit_before = _sha256(deleted_path)
    default_before = _sha256(wrong_default)

    status, body = restore(api, ["gone-2"])

    assert status == 200
    assert body == {
        "removed_from_deleted": 1,
        "track_ids": ["gone-2"],
        "remaining": 1,
        "reindex_required": True,
    }
    assert _sha256(deleted_path) != explicit_before
    assert json.loads(deleted_path.read_text()) == {
        "gone-1": {"artist": "Blawan", "title": "Toast"}
    }
    assert _sha256(wrong_default) == default_before


def test_the_same_restore_route_can_clear_every_deleted_track(api, deleted_path):
    status, body = restore(api, ["gone-2", "gone-1"])

    assert status == 200
    assert body["removed_from_deleted"] == 2
    assert body["remaining"] == 0
    assert json.loads(deleted_path.read_text()) == {}


def test_an_unknown_deleted_id_refuses_the_whole_selection(api, deleted_path):
    before = _sha256(deleted_path)

    status, body = restore(api, ["gone-2", "not-deleted"])

    assert status == 404
    assert body["error"]["code"] == "unknown_deleted_track"
    assert _sha256(deleted_path) == before


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "gone-2",
        {},
        {"track_ids": []},
        {"track_ids": ""},
        {"track_ids": "gone-2\n"},
        {"track_ids": "gone-2\ngone-2"},
        {"track_ids": "gone-2", "extra": True},
    ],
)
def test_restore_rejects_malformed_documents_without_mutating(
    api, deleted_path, body
):
    before = _sha256(deleted_path)

    status, response = api.handle(
        "POST", "/api/library/deleted-tracks/restore", {}, body
    )

    assert status == 400
    assert response["error"]["code"] == "bad_request"
    assert _sha256(deleted_path) == before
