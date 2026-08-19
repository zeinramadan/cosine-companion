"""Fingerprint support for the developer-only real-library golden tests."""

import hashlib
import json
from pathlib import Path


FINGERPRINT_SCHEMA = 1
FINGERPRINT_PATH = (
    Path(__file__).resolve().parent / "golden" / "real_library_fingerprint.json"
)
REGENERATE_COMMAND = "python tests/services/golden/regenerate_real_goldens.py"


def fingerprint_ids(ids):
    """Return a stable fingerprint of the parsed, ordered ``ids.json`` list."""
    if not isinstance(ids, list) or any(
        not isinstance(track_id, str) for track_id in ids
    ):
        raise ValueError("ids.json must contain a list of string track IDs")

    canonical_ids = json.dumps(
        ids, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_version": FINGERPRINT_SCHEMA,
        "track_count": len(ids),
        "ids_sha256": hashlib.sha256(canonical_ids).hexdigest(),
    }


def fingerprint_data_dir(data_dir):
    """Fingerprint the ordered IDs in a library directory without loading vectors."""
    with (Path(data_dir) / "ids.json").open(encoding="utf-8") as ids_file:
        return fingerprint_ids(json.load(ids_file))


def load_expected_fingerprint(path=FINGERPRINT_PATH):
    """Load and validate the committed fingerprint captured with the goldens."""
    with Path(path).open(encoding="utf-8") as fingerprint_file:
        fingerprint = json.load(fingerprint_file)

    expected_keys = {"schema_version", "track_count", "ids_sha256"}
    if set(fingerprint) != expected_keys:
        raise ValueError(
            f"{path} must contain exactly {sorted(expected_keys)}; "
            f"found {sorted(fingerprint)}"
        )
    if fingerprint["schema_version"] != FINGERPRINT_SCHEMA:
        raise ValueError(
            f"unsupported real-library fingerprint schema "
            f"{fingerprint['schema_version']!r}"
        )
    if not isinstance(fingerprint["track_count"], int):
        raise ValueError("real-library fingerprint track_count must be an integer")
    digest = fingerprint["ids_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(
            "real-library fingerprint ids_sha256 must be a SHA-256 hex digest"
        )
    try:
        bytes.fromhex(digest)
    except ValueError as error:
        raise ValueError(
            "real-library fingerprint ids_sha256 must be a SHA-256 hex digest"
        ) from error
    return fingerprint


def describe_fingerprint(fingerprint):
    return (
        f"track_count={fingerprint['track_count']}, "
        f"ids_sha256={fingerprint['ids_sha256']}"
    )


def fingerprint_mismatch_reason(data_dir, expected):
    """Return an actionable skip reason, or ``None`` for an exact match."""
    try:
        found = fingerprint_data_dir(data_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return (
            "the real-library fixture has an unreadable or malformed ids.json "
            f"({type(error).__name__}: {error}). Restore or repair ids.json before "
            "running these tests; regenerating goldens cannot repair a corrupt "
            "library."
        )

    if found == expected:
        return None

    return (
        "the real library does not match the committed golden fingerprint. "
        f"Expected {describe_fingerprint(expected)}; "
        f"found {describe_fingerprint(found)}. "
        "These tests only characterize the library captured by the real-library "
        "goldens. To deliberately regenerate the real goldens and fingerprint "
        f"for this library, run: {REGENERATE_COMMAND}"
    )
