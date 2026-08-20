"""Guard: no workflow may state a Python version inline.

For months CI tested 3.10 while ``.github/workflows/build-*.yml`` froze the
app on 3.11. Nothing detected it. It surfaced only because a compiled-in
Unicode digit table generated from the *test* interpreter disagreed with the
*shipped* one. Both are 3.11 today, so that bug is dormant -- but nothing
prevented it, because each workflow independently stated its own version.

Four earlier rounds tried to *detect* divergence by working out which Python
each workflow uses. Every one shipped a confident wrong answer on a
counterexample (flow mappings, escaped keys, block-scalar decoys,
``python-version-file``), and every fix was "teach it one more Actions shape".
That apparatus is gone. **This file does not determine which Python anything
uses.** If no workflow states a version, no two workflows can disagree, and
there is nothing to work out.

The one narrow question here is: *does any setup-python step still state a
version inline?* Everything else is fail-closed -- an unparseable workflow, an
unrecognised job or step shape, a setup-python step with no ``with:`` block,
or a missing ``.python-version`` is a FAILURE, never a skip and never a pass.

Keyed on the *parsed step*, never on a substring. ``test-macos.yml`` contains
the text ``python-version`` twice in places that are not setup-python inputs
(``uv pip compile --python-version 3.11`` and the ``--custom-compile-command``
string that records it). A text search reddens on a completely correct tree,
and a check that cries wolf gets weakened or deleted -- which is the mechanism
that produced this whole defect family. Parsing also means the shapes that
defeated rounds 5 and 6 need no special handling at all: ``python-version:``,
``"python-version":`` and ``{python-version: "3.10"}`` are the same dict key
once PyYAML is done.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
VERSION_FILE = REPO_ROOT / ".python-version"
VERSION_FILE_NAME = ".python-version"

# The action whose inputs this guard is about.
SETUP_PYTHON = ("actions", "setup-python")

# Inputs that state a version inline. setup-python takes ``python-version``;
# the other spellings never reach it, but a step carrying one is a shape this
# guard does not understand, so it fails rather than guessing.
INLINE_VERSION_KEYS = ("python-version", "python_version", "pythonVersion")

# Deliberately permissive about *form* (3.11, 3.11.9, 3.13) and strict about
# there being exactly one token. Judging the value is not this file's job.
VERSION_TOKEN = re.compile(r"^\d+(?:\.\d+)*$")


def _yaml():
    """Import PyYAML, or fail loudly and by name.

    PyYAML is not declared: it arrives as a transitive of
    essentia-tensorflow, which CI installs from
    ``requirements-macos-arm64-py311.lock`` with ``--require-hashes``. That
    makes it exactly the kind of dependency a ``pytest.importorskip`` would
    quietly turn into a green run. A skipped guard reads identically to a
    passing one, and this project has been bitten by that seven times. So:
    never skip.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised by a probe
        raise AssertionError(
            "PyYAML is required to check the workflows and is missing. "
            "It is an undeclared transitive of essentia-tensorflow via "
            "requirements-macos-arm64-py311.lock. This guard fails rather "
            f"than skipping, because a skip looks like a pass. ({exc})"
        ) from exc
    return yaml


def workflow_files():
    return sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))


def _parse(path):
    """Parse one workflow, or fail naming the file."""
    yaml = _yaml()
    text = path.read_text(encoding="utf-8")
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AssertionError(f"{path.name} is not parseable YAML: {exc}") from exc

    assert isinstance(document, dict), (
        f"{path.name} did not parse to a mapping (got {type(document).__name__}); "
        "this guard cannot read it, so it fails rather than passing by default"
    )
    return document


def _steps_of(path, document):
    """Yield ``(job_name, index, step)`` for every step, or fail on a shape
    this guard does not recognise."""
    jobs = document.get("jobs")
    assert isinstance(jobs, dict) and jobs, (
        f"{path.name} has no 'jobs' mapping; unrecognised workflow shape"
    )

    for job_name, job in sorted(jobs.items()):
        assert isinstance(job, dict), (
            f"{path.name}::{job_name} is not a mapping; unrecognised job shape"
        )

        steps = job.get("steps")
        if steps is None:
            # A reusable-workflow call has no steps here. Whatever Python it
            # sets up is stated somewhere this guard cannot see, so it fails
            # rather than reporting a green it did not verify. There are none
            # today. If one is added: inline the setup, or point this glob at
            # the called workflow too.
            raise AssertionError(
                f"{path.name}::{job_name} has no 'steps'"
                f" (uses={job.get('uses')!r}). This guard cannot see into a"
                " reusable workflow, so it fails instead of assuming."
            )

        assert isinstance(steps, list), (
            f"{path.name}::{job_name} 'steps' is not a list; unrecognised shape"
        )

        for index, step in enumerate(steps):
            assert isinstance(step, dict), (
                f"{path.name}::{job_name} step {index} is not a mapping; "
                "unrecognised step shape"
            )
            yield job_name, index, step


def _uses_path(path, where, step):
    """The ``uses`` value with any ``@ref`` stripped, or None for a run step."""
    if "uses" not in step:
        return None

    uses = step["uses"]
    assert isinstance(uses, str) and uses.strip(), (
        f"{where} has a non-string 'uses' ({uses!r}); unrecognised step shape"
    )
    return uses.split("@", 1)[0].strip()


def _is_setup_python(path, where, action_path):
    """True for actions/setup-python. Fails on a look-alike.

    Matching on the parsed owner/repo, not on the string: ``astral-sh/setup-uv``
    also takes a ``python-version`` input, and flagging it would be the false
    positive that gets this guard deleted. A fork or mirror of setup-python,
    on the other hand, is a hole -- so it fails as unrecognised rather than
    being skipped silently.
    """
    if action_path is None:
        return False

    segments = tuple(action_path.split("/"))
    if segments[:2] == SETUP_PYTHON:
        return True

    assert segments[-1] != SETUP_PYTHON[1], (
        f"{where} uses {action_path!r}, which looks like setup-python but is "
        f"not {'/'.join(SETUP_PYTHON)}. This guard does not know whether it "
        "reads .python-version, so it fails rather than skipping it."
    )
    return False


def setup_python_steps(path):
    """Every parsed setup-python step in one workflow, as (where, with-block)."""
    found = []
    document = _parse(path)
    for job_name, index, step in _steps_of(path, document):
        where = f"{path.name}::{job_name} step {index} ({step.get('name', 'unnamed')})"
        if _is_setup_python(path, where, _uses_path(path, where, step)):
            found.append((where, step.get("with")))
    return found


# --------------------------------------------------------------------------
# The guard is only worth anything if it has something to guard.
# --------------------------------------------------------------------------


def test_there_are_workflows_to_check():
    assert workflow_files(), f"no workflow files under {WORKFLOW_DIR}"


def test_at_least_one_setup_python_step_exists():
    """Deleting every setup-python step would otherwise make this file green
    while proving nothing."""
    total = sum(len(setup_python_steps(p)) for p in workflow_files())

    assert total, (
        "no actions/setup-python step found in any workflow; either the "
        "workflows stopped setting up Python or this guard stopped finding "
        "them, and both mean it is no longer checking anything"
    )


# --------------------------------------------------------------------------
# The property in the filename.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_no_setup_python_step_states_a_version_inline(workflow):
    """The whole point: a version stated here is a version that can drift."""
    for where, with_block in setup_python_steps(workflow):
        assert isinstance(with_block, dict), (
            f"{where} has no 'with:' mapping, so it cannot be pointing at "
            f"{VERSION_FILE_NAME}"
        )

        stated = [key for key in INLINE_VERSION_KEYS if key in with_block]
        assert not stated, (
            f"{where} states a Python version inline: "
            + ", ".join(f"{key}: {with_block[key]!r}" for key in stated)
            + f". Every workflow must read {VERSION_FILE_NAME} instead, so "
            "that no two workflows can disagree about the interpreter."
        )


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_every_setup_python_step_points_at_the_version_file(workflow):
    """Uniform and unambiguous: one input, one target, no alternatives.

    ``python-version-file`` rather than omitting the input, although
    setup-python does read ``.python-version`` when nothing is supplied. The
    two differ when the file is gone: omission logs a warning and falls back
    to whatever Python the runner preinstalled, while a stated file that does
    not exist throws. Fail-closed, and it names its source in the workflow.
    """
    for where, with_block in setup_python_steps(workflow):
        assert isinstance(with_block, dict), (
            f"{where} has no 'with:' mapping, so it cannot be pointing at "
            f"{VERSION_FILE_NAME}"
        )

        assert "python-version-file" in with_block, (
            f"{where} does not set python-version-file. Omitting it makes "
            "setup-python fall back to the runner's default Python with only "
            "a warning, which is the original defect arriving quietly."
        )

        target = with_block["python-version-file"]
        assert isinstance(target, str) and target.strip() == VERSION_FILE_NAME, (
            f"{where} points python-version-file at {target!r}; it must be "
            f"exactly {VERSION_FILE_NAME}, or there is more than one file "
            "claiming to hold the version"
        )


# --------------------------------------------------------------------------
# The file all of them point at.
# --------------------------------------------------------------------------


def test_the_version_file_exists():
    assert VERSION_FILE.is_file(), (
        f"{VERSION_FILE_NAME} is missing. Every workflow points at it, so "
        "every job would fail -- but this guard says so first, and by name."
    )


def test_the_version_file_holds_exactly_one_version():
    """One version, one line, no comments.

    pyenv reads every line of this file as a version name, so a second line or
    a trailing comment is not a note -- it is a second source of truth.
    """
    raw = VERSION_FILE.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]

    assert len(lines) == 1, (
        f"{VERSION_FILE_NAME} holds {len(lines)} non-empty lines ({lines!r}); "
        "it must hold exactly one version"
    )

    version = lines[0].strip()
    assert VERSION_TOKEN.match(version), (
        f"{VERSION_FILE_NAME} contains {version!r}, which is not a bare "
        "version token. Comments and extra text are not allowed: pyenv reads "
        "every line here as a version name."
    )
