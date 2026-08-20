"""Guard: every CI job takes its Python from ``.python-version``, and no file
anywhere states a version of its own.

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
uses.** It asserts that exactly one file states a version and that everything
else points at it. If nothing else states a version, nothing can disagree.

WHAT THIS FILE ASSERTS
----------------------
1. Every *ordinary* job -- a job with a ``steps:`` list -- in every workflow
   sets up Python from ``.python-version``, or is named in
   ``JOBS_EXEMPT_FROM_SETUP_PYTHON`` with a written reason.
2. No setup-python step states a version inline.
3. Every setup-python step is pinned to a full commit SHA, and all of them to
   the *same* one.
4. No ``run:`` block hands a literal version to ``--python-version`` (uv
   resolves against that flag, so a literal there is a second source of truth
   that only shows up as a wrong resolution).
5. ``environment.yml`` pins conda to the same version.
6. ``.python-version`` itself holds exactly one bare version token.

Assertion 1 is per **job**, not per repository, and that distinction is the
whole point. A previous revision asserted only "at least one setup-python step
exists somewhere" plus "every step it finds is correct". Deleting the entire
``Set up Python`` step from ``build-macos.yml`` left valid YAML, left the
repository-wide existence assertion satisfied by the other four workflows, and
left both per-workflow loops iterating an empty list -- 14 passed, while that
job went on to run ``pip install --require-hashes``, ``python -c`` and
``python build_app.py`` on whatever interpreter the runner image happened to
carry. A guard that proves a property only about the steps it *finds* proves
nothing about the steps that are gone. So the unit of assertion is the job:
every job must account for itself.

FAIL-CLOSED
-----------
An unparseable workflow, a job or step shape this file does not recognise, a
setup-python step with no ``with:`` block, a ``uses:``-only job, a
conditionally-run setup-python step, a stale exemption, or a missing
``.python-version`` is a FAILURE -- never a skip, never a pass by default.
There is no code path here that reaches "no problem found" without having
classified every job.

Keyed on the *parsed step*, never on a substring. ``test-macos.yml`` contains
the text ``python-version`` in places that are not setup-python inputs (the
``uv pip compile`` flag and the ``--custom-compile-command`` string that
records it). A text search reddens on a completely correct tree, and a check
that cries wolf gets weakened or deleted -- which is the mechanism that
produced this whole defect family. Parsing also means the shapes that defeated
rounds 5 and 6 need no special handling at all: ``python-version:``,
``"python-version":`` and ``{python-version: "3.10"}`` are the same dict key
once PyYAML is done.

KNOWN BLIND SPOTS
-----------------
Deliberate. Each is a way a job could obtain a Python this file would not
notice. None has an instance in this repository today, and each was left
undetected on purpose: detecting them is the "teach it one more Actions shape"
treadmill that produced four wrong answers. They are listed so the next reader
does not have to rediscover them.

* ``container:`` jobs -- the image's interpreter, not the runner's.
* Composite actions -- a ``uses:`` step whose own action.yml sets up Python.
* ``uv python install`` (and ``pyenv install``, ``conda create``) inside a
  ``run:`` block.
* Manual ``PATH`` manipulation, including ``$GITHUB_PATH`` writes.
* Step *order*: a ``run:`` step placed before the setup-python step in the
  same job runs on the runner's default Python. Presence is asserted here;
  position is not.
* ``setup.py`` declares ``python_requires=">=3.8"``. That is a lower bound on
  installability, not an interpreter selection -- it cannot make any job run a
  different Python -- so it is out of scope here. README.md already records
  that the bound is inaccurate.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
VERSION_FILE = REPO_ROOT / ".python-version"
VERSION_FILE_NAME = ".python-version"
CONDA_ENV_FILE = REPO_ROOT / "environment.yml"

# The action whose inputs this guard is about.
SETUP_PYTHON = ("actions", "setup-python")

# Inputs that state a version inline. setup-python takes ``python-version``;
# the other spellings never reach it, but a step carrying one is a shape this
# guard does not understand, so it fails rather than guessing.
INLINE_VERSION_KEYS = ("python-version", "python_version", "pythonVersion")

# Deliberately permissive about *form* (3.11, 3.11.9, 3.13) and strict about
# there being exactly one token. Judging the value is not this file's job.
VERSION_TOKEN = re.compile(r"^\d+(?:\.\d+)*$")

# A full-length git commit SHA, which is the only ref that cannot move.
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")

# ``--python-version <token>`` anywhere in a shell block. uv reads this flag to
# choose the interpreter it RESOLVES for, so a literal here does not fail
# loudly -- it silently resolves the dependency set for the wrong Python.
UV_PYTHON_VERSION_FLAG = re.compile(r"--python-version[=\s]+(\S+)")


# ---------------------------------------------------------------------------
# The one escape hatch, and the only one.
# ---------------------------------------------------------------------------

# Ordinary jobs allowed to have no setup-python step, keyed by
# ``(workflow file name, job name)``, with the reason as the value.
#
# An entry here is a written claim that **the job cannot execute Python at
# all** -- that no step in it starts an interpreter, so there is nothing for
# ``.python-version`` to select. It is not a claim that the job is fine, and
# it is not a place to park a job that is inconvenient to fix. Anything weaker
# recreates the exact defect this file exists to prevent, which is why the
# reason is stored rather than a bare marker: a reader must be able to judge
# the claim without leaving this file.
#
# It is deliberately EMPTY. Every job in this repository sets up Python from
# ``.python-version`` today. It exists at all because the alternative to a
# reviewable exemption is a silent one -- a job that quietly falls through --
# and because the tests below hold entries to their claim: an entry naming a
# job that no longer exists FAILS as stale, and an entry on a job that *does*
# set up Python FAILS as self-contradictory. An exemption therefore cannot rot
# into a hole; it either stays true or it goes red.
JOBS_EXEMPT_FROM_SETUP_PYTHON = {}


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


def stated_version_text():
    """The raw contents of the one file that states the version.

    Every reader goes through here so that a missing file fails by name in
    all of them, rather than one of them reporting a bare FileNotFoundError
    traceback that says nothing about what the file is for.
    """
    assert VERSION_FILE.is_file(), (
        f"{VERSION_FILE_NAME} is missing. Every workflow points at it, so "
        "every job would fail -- but this guard says so first, and by name."
    )
    return VERSION_FILE.read_text(encoding="utf-8")


def _parse(path):
    """Parse one YAML file, or fail naming it."""
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


def _jobs_of(name, document):
    """``(job_name, job)`` for every job, sorted, or fail on a bad shape."""
    jobs = document.get("jobs")
    assert isinstance(jobs, dict) and jobs, (
        f"{name} has no 'jobs' mapping; unrecognised workflow shape"
    )

    for job_name, job in sorted(jobs.items()):
        assert isinstance(job, dict), (
            f"{name}::{job_name} is not a mapping; unrecognised job shape"
        )
        yield job_name, job


def _steps_of(name, job_name, job):
    """``(index, step)`` for one job's steps, or fail on a bad shape.

    A job with no ``steps:`` yields nothing. That is not a pass: whether such
    a job is acceptable is decided by :func:`jobs_missing_setup_python`, which
    sees every job. Keeping that decision in one place is what lets an
    exemption cover a ``uses:``-only job without also blinding the
    step-shape checks below.
    """
    steps = job.get("steps")
    if steps is None:
        return

    assert isinstance(steps, list), (
        f"{name}::{job_name} 'steps' is not a list; unrecognised shape"
    )

    for index, step in enumerate(steps):
        assert isinstance(step, dict), (
            f"{name}::{job_name} step {index} is not a mapping; "
            "unrecognised step shape"
        )
        yield index, step


def _where(name, job_name, index, step):
    return f"{name}::{job_name} step {index} ({step.get('name', 'unnamed')})"


def _uses_ref(where, step):
    """``(action_path, ref)`` from ``uses``, or ``None`` for a run step."""
    if "uses" not in step:
        return None

    uses = step["uses"]
    assert isinstance(uses, str) and uses.strip(), (
        f"{where} has a non-string 'uses' ({uses!r}); unrecognised step shape"
    )
    action_path, _, ref = uses.strip().partition("@")
    return action_path.strip(), ref.strip()


def _is_setup_python(where, resolved):
    """True for actions/setup-python. Fails on a look-alike.

    Matching on the parsed owner/repo, not on the string: ``astral-sh/setup-uv``
    also takes a ``python-version`` input, and flagging it would be the false
    positive that gets this guard deleted. A fork or mirror of setup-python,
    on the other hand, is a hole -- so it fails as unrecognised rather than
    being skipped silently.
    """
    if resolved is None:
        return False

    action_path, _ref = resolved
    segments = tuple(action_path.split("/"))
    if segments[:2] == SETUP_PYTHON:
        return True

    assert segments[-1] != SETUP_PYTHON[1], (
        f"{where} uses {action_path!r}, which looks like setup-python but is "
        f"not {'/'.join(SETUP_PYTHON)}. This guard does not know whether it "
        "reads .python-version, so it fails rather than skipping it."
    )
    return False


def setup_python_steps_in_job(name, job_name, job):
    """``(where, step, ref)`` for each setup-python step in one job."""
    found = []
    for index, step in _steps_of(name, job_name, job):
        where = _where(name, job_name, index, step)
        resolved = _uses_ref(where, step)
        if _is_setup_python(where, resolved):
            found.append((where, step, resolved[1]))
    return found


def setup_python_steps(path):
    """Every parsed setup-python step in one workflow file."""
    document = _parse(path)
    found = []
    for job_name, job in _jobs_of(path.name, document):
        found.extend(setup_python_steps_in_job(path.name, job_name, job))
    return found


# ---------------------------------------------------------------------------
# Assertion 1: every job accounts for itself.
# ---------------------------------------------------------------------------


def jobs_missing_setup_python(name, document, exemptions=None):
    """Every job in one workflow that neither sets up Python nor is exempt.

    Returns a list of problem descriptions; empty means every job in this
    workflow is accounted for. Shapes this guard cannot read raise from the
    helpers above instead -- there is no third answer, and in particular no
    path that returns ``[]`` because a job was never looked at.
    """
    if exemptions is None:
        exemptions = JOBS_EXEMPT_FROM_SETUP_PYTHON

    problems = []

    for job_name, job in _jobs_of(name, document):
        reason = exemptions.get((name, job_name))
        setups = setup_python_steps_in_job(name, job_name, job)

        if reason and setups:
            problems.append(
                f"{name}::{job_name} is exempt from setting up Python "
                f"({reason!r}) but contains {len(setups)} setup-python "
                "step(s). The exemption claims the job cannot execute "
                "Python, and the job says otherwise. Remove the exemption."
            )
            continue

        if reason:
            continue

        if "steps" not in job:
            problems.append(
                f"{name}::{job_name} has no 'steps' (uses="
                f"{job.get('uses')!r}). This guard reads steps, so it cannot "
                "see which Python a called workflow sets up, and it will not "
                "report a green it did not verify. Resolve it by either (a) "
                "inlining the setup-python step into this job, or (b) adding "
                f"('{name}', '{job_name}') to "
                "JOBS_EXEMPT_FROM_SETUP_PYTHON with a reason. Pointing this "
                "guard's glob at the called workflow does NOT resolve it: "
                "that covers the callee's own jobs, while this caller still "
                "has no steps and still fails here. If the callee lives in "
                "this repository it is already covered by the glob, and the "
                "exemption reason should say so; if it lives elsewhere, the "
                "reason must say who guarantees its interpreter."
            )
            continue

        runnable = [
            (where, step) for where, step, _ref in setups if "if" not in step
        ]

        if setups and not runnable:
            problems.append(
                f"{name}::{job_name} sets up Python only in step(s) carrying "
                "an 'if:' condition, so this guard cannot prove the job ever "
                "runs setup-python -- and a job whose setup is skipped runs "
                "its remaining steps on the runner's default Python. Make "
                "the setup-python step unconditional, or add "
                f"('{name}', '{job_name}') to "
                "JOBS_EXEMPT_FROM_SETUP_PYTHON with a reason."
            )
            continue

        if not runnable:
            problems.append(
                f"{name}::{job_name} has {len(job['steps'])} step(s) and no "
                "actions/setup-python step. Every ordinary job must take its "
                f"interpreter from {VERSION_FILE_NAME}; without one, any "
                "Python this job runs is whatever the runner image happens "
                "to preinstall, which is the original defect arriving "
                f"quietly. Add a setup-python step with python-version-file: "
                f"{VERSION_FILE_NAME}, or -- only if no step in this job can "
                f"execute Python at all -- add ('{name}', '{job_name}') to "
                "JOBS_EXEMPT_FROM_SETUP_PYTHON with a reason."
            )

    return problems


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_every_job_sets_up_python_from_the_version_file(workflow):
    """The blocker: deleting a setup-python step must redden, by name.

    Parametrised over the file rather than the job so that collection stays a
    glob. Parametrising per job would mean parsing YAML at collection time,
    turning a missing PyYAML into a collection error instead of the clean,
    named failure :func:`_yaml` raises.
    """
    problems = jobs_missing_setup_python(workflow.name, _parse(workflow))

    assert not problems, "\n".join(problems)


def test_no_exemption_is_stale():
    """An exemption naming a job that no longer exists is a hole waiting for
    a job of that name to come back."""
    live = set()
    for path in workflow_files():
        for job_name, _job in _jobs_of(path.name, _parse(path)):
            live.add((path.name, job_name))

    stale = sorted(key for key in JOBS_EXEMPT_FROM_SETUP_PYTHON if key not in live)

    assert not stale, (
        "JOBS_EXEMPT_FROM_SETUP_PYTHON names job(s) that do not exist: "
        + ", ".join(f"{name}::{job}" for name, job in stale)
        + ". Remove them; a stale exemption silently pre-approves the next "
        "job that happens to take the same name."
    )


# ---------------------------------------------------------------------------
# The exemption machinery is empty in this repository, so prove it works.
# ---------------------------------------------------------------------------

_SYNTHETIC = {
    "jobs": {
        "no-python": {"steps": [{"name": "Say hi", "run": "echo hi"}]},
        "with-python": {
            "steps": [
                {
                    "uses": "actions/setup-python@" + "0" * 40,
                    "with": {"python-version-file": VERSION_FILE_NAME},
                }
            ]
        },
    }
}


def test_a_job_without_setup_python_is_reported():
    problems = jobs_missing_setup_python("synthetic.yml", _SYNTHETIC, {})

    assert len(problems) == 1, problems
    assert "synthetic.yml::no-python" in problems[0]


def test_an_exemption_silences_exactly_the_job_it_names():
    exempt = {("synthetic.yml", "no-python"): "test fixture: runs no Python"}

    assert jobs_missing_setup_python("synthetic.yml", _SYNTHETIC, exempt) == []


def test_an_exemption_does_not_cover_a_different_job():
    exempt = {("other.yml", "no-python"): "wrong file"}
    problems = jobs_missing_setup_python("synthetic.yml", _SYNTHETIC, exempt)

    assert len(problems) == 1, problems
    assert "synthetic.yml::no-python" in problems[0]


def test_an_exemption_on_a_job_that_sets_up_python_is_contradictory():
    exempt = {("synthetic.yml", "with-python"): "claims it cannot run Python"}
    problems = jobs_missing_setup_python("synthetic.yml", _SYNTHETIC, exempt)

    assert len(problems) == 2, problems
    assert any("contradict" in p or "says otherwise" in p for p in problems)


def test_a_uses_only_job_is_reported_and_the_advice_is_actionable():
    document = {"jobs": {"call": {"uses": "./.github/workflows/other.yml"}}}
    problems = jobs_missing_setup_python("caller.yml", document, {})

    assert len(problems) == 1, problems
    # The advice must not be the one that does not work.
    assert "does NOT resolve it" in problems[0]
    assert "JOBS_EXEMPT_FROM_SETUP_PYTHON" in problems[0]


def test_a_conditional_setup_python_step_does_not_satisfy_a_job():
    document = {
        "jobs": {
            "maybe": {
                "steps": [
                    {
                        "if": "runner.os == 'macOS'",
                        "uses": "actions/setup-python@" + "0" * 40,
                        "with": {"python-version-file": VERSION_FILE_NAME},
                    }
                ]
            }
        }
    }
    problems = jobs_missing_setup_python("cond.yml", document, {})

    assert len(problems) == 1, problems
    assert "'if:'" in problems[0]


# ---------------------------------------------------------------------------
# The guard is only worth anything if it has something to guard.
# ---------------------------------------------------------------------------


def test_there_are_workflows_to_check():
    assert workflow_files(), f"no workflow files under {WORKFLOW_DIR}"


def test_at_least_one_setup_python_step_exists():
    """Redundant with the per-job assertion above while every job is an
    ordinary one, and kept because it stops being redundant the moment an
    exemption is added."""
    total = sum(len(setup_python_steps(p)) for p in workflow_files())

    assert total, (
        "no actions/setup-python step found in any workflow; either the "
        "workflows stopped setting up Python or this guard stopped finding "
        "them, and both mean it is no longer checking anything"
    )


# ---------------------------------------------------------------------------
# Assertions 2 and 3: how each setup-python step is written.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_no_setup_python_step_states_a_version_inline(workflow):
    """The whole point: a version stated here is a version that can drift."""
    for where, step, _ref in setup_python_steps(workflow):
        with_block = step.get("with")
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
    for where, step, _ref in setup_python_steps(workflow):
        with_block = step.get("with")
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


def test_every_setup_python_step_is_pinned_to_one_agreed_sha():
    """The design rests on one behaviour of one version of this action.

    With ``python-version-file`` named, a *missing* file makes setup-python
    throw instead of silently falling back to the runner's Python. That is
    what makes assertion 1 worth anything, and it is a property of the
    action's source at a particular commit -- not of the name ``v5``, which
    GitHub documents as a tag it may move at any time. A moved tag would
    change the behaviour this file depends on without changing a byte of this
    repository.

    All five must agree, for the same reason the Python version lives in one
    file: two pins are two things that can drift apart.
    """
    refs = {}
    for path in workflow_files():
        for where, _step, ref in setup_python_steps(path):
            refs[where] = ref

    assert refs, "no setup-python step found to check the pin of"

    unpinned = sorted(w for w, ref in refs.items() if not COMMIT_SHA.match(ref))
    assert not unpinned, (
        "setup-python must be pinned to a full 40-character commit SHA, with "
        "the version in a trailing comment. These are not: "
        + ", ".join(f"{w} -> {refs[w]!r}" for w in unpinned)
        + ". A tag like 'v5' is mutable by GitHub's own documentation, so "
        "the throw-on-missing-file behaviour this guard relies on could "
        "change without any commit here."
    )

    distinct = sorted(set(refs.values()))
    assert len(distinct) == 1, (
        "setup-python is pinned to more than one SHA "
        f"({', '.join(distinct)}); they can drift apart, which is the same "
        "defect as two workflows stating two Python versions. Pin all of "
        "them to one reviewed commit."
    )


# ---------------------------------------------------------------------------
# Assertion 4: no shell block resolves against a literal version.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_no_run_block_passes_a_literal_python_version(workflow):
    """``uv pip compile --python-version`` chooses the interpreter uv resolves
    *for*, so a literal there is a second source of truth whose divergence
    never announces itself: a bump of ``.python-version`` would leave the
    dependency set resolved for the old Python and installed on the new one.

    Both occurrences in ``test-macos.yml`` matter -- the flag uv acts on and
    the copy inside ``--custom-compile-command`` that is written verbatim into
    the lock header. The shell expands both before uv sees either, so the
    generated lock stays byte-identical.
    """
    document = _parse(workflow)

    for job_name, job in _jobs_of(workflow.name, document):
        for index, step in _steps_of(workflow.name, job_name, job):
            run = step.get("run")
            if not isinstance(run, str):
                continue

            where = _where(workflow.name, job_name, index, step)
            literals = [
                value
                for value in UV_PYTHON_VERSION_FLAG.findall(run)
                if VERSION_TOKEN.match(value.strip("'\""))
            ]
            assert not literals, (
                f"{where} passes a literal Python version to "
                "--python-version: " + ", ".join(repr(v) for v in literals)
                + f". Read {VERSION_FILE_NAME} in the shell instead, so the "
                "flag cannot disagree with the interpreter the job installed."
            )

            if UV_PYTHON_VERSION_FLAG.search(run):
                assert VERSION_FILE_NAME in run, (
                    f"{where} uses --python-version but never mentions "
                    f"{VERSION_FILE_NAME}, so whatever it passes is not "
                    "derived from the one file that states the version."
                )


# ---------------------------------------------------------------------------
# Assertion 5: the local-development plane agrees with CI.
# ---------------------------------------------------------------------------


def conda_python_pin():
    """The Python version ``environment.yml`` pins, or fail saying why not."""
    assert CONDA_ENV_FILE.is_file(), f"{CONDA_ENV_FILE.name} is missing"

    document = _parse(CONDA_ENV_FILE)
    dependencies = document.get("dependencies")
    assert isinstance(dependencies, list) and dependencies, (
        f"{CONDA_ENV_FILE.name} has no 'dependencies' list; unrecognised shape"
    )

    # conda puts pip-only requirements in a nested mapping; a python pin
    # hiding in there would be just as authoritative, so look in both.
    entries = []
    for entry in dependencies:
        if isinstance(entry, str):
            entries.append(entry)
        elif isinstance(entry, dict):
            for nested in entry.values():
                if isinstance(nested, list):
                    entries.extend(n for n in nested if isinstance(n, str))

    pins = [e for e in entries if re.split(r"[=<>!~\s]", e.strip(), 1)[0] == "python"]

    assert len(pins) == 1, (
        f"{CONDA_ENV_FILE.name} names Python {len(pins)} times ({pins!r}); "
        "it must pin it exactly once, or it is ambiguous which one a conda "
        "user gets"
    )

    match = re.fullmatch(r"python\s*={1,2}\s*(\d+(?:\.\d+)*)", pins[0].strip())
    assert match, (
        f"{CONDA_ENV_FILE.name} states {pins[0]!r}, which this guard cannot "
        f"compare with {VERSION_FILE_NAME}. It must be an exact pin, e.g. "
        "'python=3.11'; a range would let a conda user land on an "
        "interpreter no CI job ever tests."
    )
    return match.group(1)


def test_the_conda_environment_pins_the_same_python():
    """``environment.yml`` builds the interpreter contributors actually run.

    It pinned 3.10 while the app shipped and CI tested 3.11 -- the same defect
    as the original, relocated to the local-development plane, and the reason
    a contributor's own machine could redden a test that is green in CI.
    """
    stated = stated_version_text().strip()
    pinned = conda_python_pin()

    assert pinned == stated, (
        f"{CONDA_ENV_FILE.name} pins Python {pinned}, but "
        f"{VERSION_FILE_NAME} states {stated}. Contributors following the "
        "README would develop and test on an interpreter the shipped app "
        "never uses, which is exactly the divergence this PR removes from CI."
    )


# ---------------------------------------------------------------------------
# Assertion 6: the file all of them point at.
# ---------------------------------------------------------------------------


def test_the_version_file_exists():
    assert stated_version_text() is not None


def test_the_version_file_holds_exactly_one_version():
    """One version, one line, no comments.

    pyenv reads every line of this file as a version name, so a second line or
    a trailing comment is not a note -- it is a second source of truth.
    """
    raw = stated_version_text()
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
