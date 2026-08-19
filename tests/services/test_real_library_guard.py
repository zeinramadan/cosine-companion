import json

import pytest

from real_library_guard import (
    fingerprint_ids,
    fingerprint_mismatch_reason,
    load_expected_fingerprint,
)


def write_ids(data_dir, ids):
    data_dir.mkdir()
    (data_dir / "ids.json").write_text(json.dumps(ids), encoding="utf-8")


def write_fingerprint(path, fingerprint):
    path.write_text(json.dumps(fingerprint), encoding="utf-8")


def valid_fingerprint():
    return {
        "schema_version": 1,
        "track_count": 2,
        "ids_sha256": "0" * 64,
    }


def test_generated_fingerprint_matches_the_committed_file_format():
    committed = load_expected_fingerprint()
    generated = fingerprint_ids(["shape-probe"])

    assert set(generated) == set(committed) == {
        "schema_version",
        "track_count",
        "ids_sha256",
    }
    assert generated["schema_version"] == committed["schema_version"] == 1


@pytest.mark.parametrize(
    "ids",
    [None, {"track": "track-1"}, [1], ["track-1", None], [["track-1"]]],
    ids=["null", "object", "integer-item", "null-item", "nested-list"],
)
def test_fingerprint_rejects_ids_that_are_not_a_list_of_strings(ids):
    with pytest.raises(
        ValueError, match="ids.json must contain a list of string track IDs"
    ):
        fingerprint_ids(ids)


def test_load_expected_fingerprint_accepts_the_exact_committed_format(tmp_path):
    path = tmp_path / "fingerprint.json"
    expected = valid_fingerprint()
    write_fingerprint(path, expected)

    assert load_expected_fingerprint(path) == expected


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda fingerprint: fingerprint.pop("schema_version"),
            "must contain exactly",
        ),
        (
            lambda fingerprint: fingerprint.update({"unexpected": True}),
            "must contain exactly",
        ),
        (
            lambda fingerprint: fingerprint.update({"schema_version": 2}),
            "unsupported real-library fingerprint schema 2",
        ),
        (
            lambda fingerprint: fingerprint.update({"track_count": "2"}),
            "track_count must be an integer",
        ),
        (
            lambda fingerprint: fingerprint.update({"ids_sha256": None}),
            "ids_sha256 must be a SHA-256 hex digest",
        ),
        (
            lambda fingerprint: fingerprint.update({"ids_sha256": "0" * 63}),
            "ids_sha256 must be a SHA-256 hex digest",
        ),
        (
            lambda fingerprint: fingerprint.update({"ids_sha256": "g" * 64}),
            "ids_sha256 must be a SHA-256 hex digest",
        ),
    ],
    ids=[
        "missing-key",
        "extra-key",
        "wrong-schema",
        "non-integer-count",
        "non-string-digest",
        "wrong-length-digest",
        "non-hex-digest",
    ],
)
def test_load_expected_fingerprint_rejects_invalid_content(
    tmp_path, change, message
):
    path = tmp_path / "fingerprint.json"
    fingerprint = valid_fingerprint()
    change(fingerprint)
    write_fingerprint(path, fingerprint)

    with pytest.raises(ValueError, match=message):
        load_expected_fingerprint(path)


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
    assert (
        "run: python tests/services/golden/regenerate_real_goldens.py" in reason
    )


@pytest.mark.parametrize(
    ("corruption", "contents"),
    [
        ("missing", None),
        ("empty", ""),
        ("truncated-json", '["track-1"'),
        ("object-not-list", "{}"),
        ("list-of-integers", "[1, 2]"),
        ("null", "null"),
        ("nested-lists", '[["track-1"]]'),
        ("directory", None),
        ("unreadable", '["track-1"]'),
    ],
)
def test_corrupt_ids_json_skips_with_repair_advice(
    tmp_path, corruption, contents
):
    data_dir = tmp_path / corruption
    data_dir.mkdir()
    ids_path = data_dir / "ids.json"

    if corruption == "directory":
        ids_path.mkdir()
    elif corruption != "missing":
        ids_path.write_text(contents, encoding="utf-8")
    if corruption == "unreadable":
        ids_path.chmod(0)

    try:
        reason = fingerprint_mismatch_reason(data_dir, valid_fingerprint())
    finally:
        if corruption == "unreadable":
            ids_path.chmod(0o600)

    assert "unreadable or malformed ids.json" in reason
    assert "Restore or repair ids.json" in reason
    assert "regenerating goldens cannot repair a corrupt library" in reason
    assert "regenerate_real_goldens.py" not in reason
