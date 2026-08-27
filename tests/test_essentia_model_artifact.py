"""Executable contracts for the exact embedding graph shipped in builds."""

import hashlib
import sys
from types import ModuleType

import pytest

import build_app


CANONICAL_NAME = "discogs_multi_embeddings-effnet-bs64-1.pb"
CANONICAL_URL = (
    "https://essentia.upf.edu/models/feature-extractors/discogs-effnet/"
    f"{CANONICAL_NAME}"
)
CANONICAL_SIZE = 16_367_182
CANONICAL_SHA256 = (
    "2c964064951217e1e345461cf88884086a21f4bca2ae0d48187ee75edc263cd7"
)


def _pin_fixture(monkeypatch, payload, *, size=None, sha256=None, markers=None):
    monkeypatch.setattr(
        build_app,
        "ESSENTIA_MODEL_SIZE",
        len(payload) if size is None else size,
    )
    monkeypatch.setattr(
        build_app,
        "ESSENTIA_MODEL_SHA256",
        hashlib.sha256(payload).hexdigest() if sha256 is None else sha256,
    )
    monkeypatch.setattr(
        build_app,
        "ESSENTIA_GRAPHDEF_MARKERS",
        (b"PartitionedCall",) if markers is None else markers,
    )


def _write_fixture(tmp_path, payload):
    path = tmp_path / CANONICAL_NAME
    path.write_bytes(payload)
    return path


def test_model_identity_is_the_verified_canonical_essentia_artifact():
    assert build_app.ESSENTIA_MODEL_NAME == CANONICAL_NAME
    assert build_app.ESSENTIA_MODEL_URL == CANONICAL_URL
    assert build_app.ESSENTIA_MODEL_SIZE == CANONICAL_SIZE
    assert build_app.ESSENTIA_MODEL_SHA256 == CANONICAL_SHA256
    assert build_app.ESSENTIA_MODEL_OUTPUT == "PartitionedCall:1"


def test_model_verifier_accepts_bytes_matching_every_guard(tmp_path, monkeypatch):
    payload = b"\x0a\x05Const\x12\x05Const\x00PartitionedCall"
    path = _write_fixture(tmp_path, payload)
    _pin_fixture(monkeypatch, payload)

    assert build_app.verify_essentia_model_file(path) == path


def test_model_verifier_rejects_a_missing_artifact(tmp_path):
    path = tmp_path / CANONICAL_NAME

    with pytest.raises(build_app.ModelVerificationError, match="model is missing"):
        build_app.verify_essentia_model_file(path)


def test_model_verifier_reports_an_unreadable_artifact(tmp_path, monkeypatch):
    path = _write_fixture(tmp_path, b"present")

    def unreadable(_path):
        raise PermissionError("denied by probe")

    monkeypatch.setattr(build_app.Path, "read_bytes", unreadable)

    with pytest.raises(build_app.ModelVerificationError, match="cannot be read"):
        build_app.verify_essentia_model_file(path)


def test_model_verifier_rejects_html_even_if_identity_checks_are_patched_to_it(
    tmp_path, monkeypatch
):
    payload = b"<html><head><title>404</title></head>PartitionedCall</html>"
    path = _write_fixture(tmp_path, payload)
    _pin_fixture(monkeypatch, payload)

    with pytest.raises(build_app.ModelVerificationError, match="HTML response"):
        build_app.verify_essentia_model_file(path)


def test_model_verifier_rejects_wrong_size_even_if_hash_and_markers_match(
    tmp_path, monkeypatch
):
    payload = b"\x0a\x05Const PartitionedCall"
    path = _write_fixture(tmp_path, payload)
    _pin_fixture(monkeypatch, payload, size=len(payload) + 1)

    with pytest.raises(build_app.ModelVerificationError, match="wrong size"):
        build_app.verify_essentia_model_file(path)


def test_model_verifier_rejects_missing_graphdef_markers_at_right_size_and_hash(
    tmp_path, monkeypatch
):
    payload = b"\x0a\x05Const\x12\x05Const"
    path = _write_fixture(tmp_path, payload)
    _pin_fixture(
        monkeypatch,
        payload,
        markers=(b"serving_default_melspectrogram", b"PartitionedCall"),
    )

    with pytest.raises(build_app.ModelVerificationError, match="node marker"):
        build_app.verify_essentia_model_file(path)


def test_model_verifier_rejects_changed_sha_at_right_size_with_graphdef_markers(
    tmp_path, monkeypatch
):
    payload = b"\x0a\x05Const PartitionedCall"
    path = _write_fixture(tmp_path, payload)
    _pin_fixture(monkeypatch, payload, sha256="0" * 64)

    with pytest.raises(build_app.ModelVerificationError, match="checksum mismatch"):
        build_app.verify_essentia_model_file(path)


def test_graphdef_verifier_uses_the_runtime_loader_and_required_output(
    tmp_path, monkeypatch
):
    calls = []
    standard = ModuleType("essentia.standard")

    def predictor(**kwargs):
        calls.append(kwargs)

    standard.TensorflowPredictEffnetDiscogs = predictor
    essentia = ModuleType("essentia")
    essentia.__path__ = []
    essentia.standard = standard
    monkeypatch.setitem(sys.modules, "essentia", essentia)
    monkeypatch.setitem(sys.modules, "essentia.standard", standard)
    path = tmp_path / CANONICAL_NAME

    build_app.verify_essentia_graphdef(path)

    assert calls == [
        {
            "graphFilename": str(path),
            "output": "PartitionedCall:1",
        }
    ]


def test_graphdef_verifier_rejects_a_file_the_runtime_loader_cannot_parse(
    tmp_path, monkeypatch
):
    standard = ModuleType("essentia.standard")

    def predictor(**_kwargs):
        raise ValueError("not a graph")

    standard.TensorflowPredictEffnetDiscogs = predictor
    essentia = ModuleType("essentia")
    essentia.__path__ = []
    essentia.standard = standard
    monkeypatch.setitem(sys.modules, "essentia", essentia)
    monkeypatch.setitem(sys.modules, "essentia.standard", standard)

    with pytest.raises(build_app.ModelVerificationError, match="could not load"):
        build_app.verify_essentia_graphdef(tmp_path / CANONICAL_NAME)


def test_verify_model_cli_fails_before_building_a_bad_artifact(
    tmp_path, monkeypatch
):
    bad_model = _write_fixture(tmp_path, b"<html>404 Not Found</html>")
    built = []
    monkeypatch.setattr(build_app, "build_with_pyinstaller", lambda: built.append(True))

    with pytest.raises(SystemExit) as exit_info:
        build_app.main(["--verify-model", str(bad_model)])

    assert exit_info.value.code == 1
    assert built == []
