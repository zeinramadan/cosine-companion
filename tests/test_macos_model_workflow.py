"""The macOS workflow must reject poisoned downloads and cache entries."""

from pathlib import Path

import yaml

import build_app


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "build-macos.yml"


def _job():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return workflow["jobs"]["build-macos"]


def _steps():
    return _job()["steps"]


def _step(name):
    matches = [step for step in _steps() if step.get("name") == name]
    assert len(matches) == 1, f"expected one {name!r} step, found {len(matches)}"
    return matches[0]


def test_model_cache_key_is_busted_and_derived_from_the_pinned_sha():
    job = _job()
    cache = _step("Cache Essentia model")

    assert job["env"]["ESSENTIA_MODEL_SHA256"] == build_app.ESSENTIA_MODEL_SHA256
    assert cache["with"] == {
        "path": "${{ env.ESSENTIA_MODEL_PATH }}",
        "key": "essentia-model-sha256-${{ env.ESSENTIA_MODEL_SHA256 }}",
    }


def test_model_download_is_fail_loud_and_only_promotes_a_completed_response():
    job = _job()
    download = _step("Download Essentia model")

    assert job["env"]["ESSENTIA_MODEL_URL"] == build_app.ESSENTIA_MODEL_URL
    assert download["run"] == (
        'mkdir -p "$(dirname "$ESSENTIA_MODEL_PATH")"\n'
        "curl --fail --show-error --location \\\n"
        '  --output "${ESSENTIA_MODEL_PATH}.download" \\\n'
        '  "$ESSENTIA_MODEL_URL"\n'
        'mv "${ESSENTIA_MODEL_PATH}.download" "$ESSENTIA_MODEL_PATH"\n'
    )


def test_model_verification_is_unconditional_and_runs_after_cache_or_download():
    steps = _steps()
    download_index = steps.index(_step("Download Essentia model"))
    verify = _step("Verify Essentia model")
    verify_index = steps.index(verify)
    build_index = steps.index(_step("Build app"))

    assert verify == {
        "name": "Verify Essentia model",
        "run": 'python build_app.py --verify-model "$ESSENTIA_MODEL_PATH"',
    }
    assert download_index < verify_index < build_index


def test_built_app_model_is_verified_before_the_dmg_is_created():
    steps = _steps()
    build = _step("Build app")

    assert build["run"] == (
        "python build_app.py\n"
        'test -f "dist/Cosine Companion.app/Contents/MacOS/Cosine Companion"\n'
        "python build_app.py --verify-model "
        '"dist/Cosine Companion.app/Contents/Resources/$ESSENTIA_MODEL_PATH"\n'
    )
    assert steps.index(build) < steps.index(_step("Create DMG"))
