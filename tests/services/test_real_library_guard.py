import json

from real_library_guard import (
    REGENERATE_COMMAND,
    fingerprint_ids,
    fingerprint_mismatch_reason,
)


def write_ids(data_dir, ids):
    data_dir.mkdir()
    (data_dir / "ids.json").write_text(json.dumps(ids), encoding="utf-8")


def test_matching_real_library_fingerprint_is_not_skipped(tmp_path):
    ids = ["track-1", "track-2"]
    data_dir = tmp_path / "matching-library"
    write_ids(data_dir, ids)

    assert fingerprint_mismatch_reason(data_dir, fingerprint_ids(ids)) is None


def test_changed_real_library_fingerprint_has_an_actionable_skip_reason(tmp_path):
    expected = fingerprint_ids(["track-1", "track-2"])
    changed_ids = ["track-2", "track-1"]
    data_dir = tmp_path / "changed-library"
    write_ids(data_dir, changed_ids)

    reason = fingerprint_mismatch_reason(data_dir, expected)

    assert f"Expected track_count=2, ids_sha256={expected['ids_sha256']}" in reason
    assert (
        f"found track_count=2, ids_sha256={fingerprint_ids(changed_ids)['ids_sha256']}"
        in reason
    )
    assert f"run: {REGENERATE_COMMAND}" in reason
