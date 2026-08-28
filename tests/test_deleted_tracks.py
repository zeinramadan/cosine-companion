"""Tests for deleted-track persistence independent of any UI surface."""

import hashlib
import json

import core.deleted_tracks as deleted_tracks_module
from core.deleted_tracks import remove_from_deleted_tracks


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_restore_writes_only_the_explicit_deleted_tracks_file(tmp_path, monkeypatch):
    target = tmp_path / "bound-data" / "deleted_tracks.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "restore-me": {"artist": "Artist A", "title": "Title A"},
                "keep-me": {"artist": "Artist B", "title": "Title B"},
            }
        )
    )
    wrong_default = tmp_path / "default-data" / "deleted_tracks.json"
    wrong_default.parent.mkdir()
    wrong_default.write_text(
        json.dumps({"default-only": {"artist": "D", "title": "T"}})
    )
    monkeypatch.setattr(deleted_tracks_module, "DELETED_TRACKS_JSON", wrong_default)
    target_before = _sha256(target)
    default_before = _sha256(wrong_default)

    remove_from_deleted_tracks({"restore-me"}, path=target)

    assert _sha256(target) != target_before
    assert json.loads(target.read_text()) == {
        "keep-me": {"artist": "Artist B", "title": "Title B"}
    }
    assert _sha256(wrong_default) == default_before
