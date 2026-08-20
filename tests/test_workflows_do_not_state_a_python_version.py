"""Guard: every ordinary CI job contains an unconditional
``actions/setup-python`` step configured from ``.python-version``, and no
workflow states a version of its own inline.

WHAT THIS DOES **NOT** ESTABLISH -- stated here, first, next to the claim,
because the sentence that used to open this file claimed the opposite. It said
"every CI job takes its Python from ``.python-version``" and "nothing can
disagree". Both were false, and a reviewer showed it in three lines: inserting,
AFTER a perfectly valid setup-python step,

    - name: Replace the configured interpreter
      run: uv python install 3.12 --default

left every test in this file green.

What is asserted is that the step is PRESENT, UNCONDITIONAL, and CONFIGURED
FROM THE FILE -- ``test_every_job_sets_up_python_from_the_version_file`` and
``test_every_setup_python_step_points_at_the_version_file``. Which interpreter
the job *subsequently uses* is not asserted here by anything, and the gap is
not narrow. A later ``run:`` step can replace the configured interpreter
outright (``uv python install --default``, ``pyenv global``, a
``$GITHUB_PATH`` prepend, ``conda activate``), and an *earlier* ``run:`` step
never sees it at all, because this file checks that the setup step exists and
not where in the list it sits. Every one of those is ordinary shell behaviour
on a runner; reading it would take exactly the interpret-the-workflow
apparatus that shipped four confident wrong answers before being deleted, and
that apparatus is not coming back. The same list appears once more, in full,
under KNOWN BLIND SPOTS.

What this file does buy, and the whole of it: the *declared* second sources of
truth are gone. One file states the version; every workflow points at that
file instead of restating it (assertions 1-3); ``environment.yml`` restates it
in one fixed spelling and is checked to equal it (assertion 5). Two workflows
cannot disagree about a version that neither of them states -- which is the
defect described next, and is the one thing here that is actually mechanised.

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
else points at it -- no more than that, and see the second paragraph above for
what that leaves uncovered.

WHAT THIS FILE ASSERTS
----------------------
1. Every *ordinary* job -- a job with a ``steps:`` list -- in every workflow
   contains an unconditional setup-python step reading ``.python-version``.
   There is no exemption table and no way to opt a job out.
2. No setup-python step states a version inline.
3. Every setup-python step is pinned to a full commit SHA, and all of them to
   the *same* one.
4. No ``run:`` block hands a literal version to ``--python-version`` (uv
   resolves against that flag, so a literal there is a second source of truth
   that only shows up as a wrong resolution).
5. ``environment.yml`` pins conda to the same version, in the single
   spelling ``python=<that version>`` and no other.
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
conditionally-run setup-python step, or a missing ``.python-version`` is a
FAILURE -- never a skip, never a pass by default.
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
Deliberate, and the reason the opening paragraph says what it says. Each is a
way a job could run a Python other than the one its setup-python step
installed, and each was left undetected on purpose: detecting them is the
"teach it one more Actions shape" treadmill that produced four wrong answers.
They are listed so the next reader does not have to rediscover them.

* ``container:`` jobs -- the image's interpreter, not the runner's.
* Composite actions -- a ``uses:`` step whose own action.yml sets up Python.
* ``uv python install 3.12 --default`` inside a ``run:`` block -- this is the
  one a reviewer used, and it is the reason the guarantee at the top of this
  file is worded the way it is. ``pyenv global``, ``conda activate`` and
  ``conda create`` are the same hole with different spellings.
* Manual ``PATH`` manipulation, including ``$GITHUB_PATH`` writes.
* Step *order*: a ``run:`` step placed before the setup-python step in the
  same job runs on the runner's default Python. Presence is asserted here;
  position is not.

None of the above has an instance in this repository as this is written --
``grep -n "container:|GITHUB_PATH|uv python|pyenv|conda activate|conda create"``
over ``.github/workflows/*.yml`` returns nothing, and the only ``uses:`` steps
are checkout, setup-python, cache, upload-artifact and ``setup-uv`` (given
``version:`` alone, so it installs no interpreter). That is an observation
about today, not an invariant: NOTHING RE-RUNS THAT GREP. It is not a test,
this file does not make it one, and a commit adding any of them goes green.
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
# There is no escape hatch, deliberately.
# ---------------------------------------------------------------------------
#
# An earlier revision of this file carried JOBS_EXEMPT_FROM_SETUP_PYTHON: a
# table mapping ``(workflow file, job name)`` to a written reason, letting a
# named job opt out of assertion 1. It was empty, and it is gone, because a
# reviewer used it to recreate the exact defect this file exists to prevent.
# Deleting build-macos.yml's setup-python step and adding
#
#     ("build-macos.yml", "build-macos"):
#         "artifact-packaging job; it does not select a Python interpreter"
#
# left the whole suite green while that job went on running
# ``python -m pip install``, ``python -c`` and ``python build_app.py`` on
# whatever interpreter the runner image happened to carry.
#
# The two checks that were supposed to hold an entry to its claim tested the
# entry's SHAPE and not its claim. "The named job still exists" and "the named
# job has no setup-python step" are both things a hole satisfies by
# construction -- they are, in fact, the definition of the hole. Nothing
# compared the words "does not select a Python interpreter" against a job that
# demonstrably does.
#
# So there is no table, and adding one back is not a two-line change. A job
# that genuinely cannot set up Python fails here, loudly, until someone builds
# the exemption AND the enforcement that tests its claim in the same commit,
# where a reviewer sees both. An escape hatch that exists is one a later commit
# can walk through without argument; one that does not exist has to be built
# first, in the open.


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

    A job with no ``steps:`` yields nothing. That is not a pass: such a job is
    reported by :func:`jobs_missing_setup_python`, which sees every job
    whether or not it has steps. Keeping that decision in one place is what
    stops a ``uses:``-only job from being silently skipped by every
    step-shape check below.
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


def jobs_missing_setup_python(name, document):
    """Every job in one workflow that does not set up Python.

    Returns a list of problem descriptions; empty means every job in this
    workflow is accounted for. Shapes this guard cannot read raise from the
    helpers above instead -- there is no third answer, and in particular no
    path that returns ``[]`` because a job was never looked at, and no
    argument a caller can pass to make a job stop being looked at.
    """
    problems = []

    for job_name, job in _jobs_of(name, document):
        setups = setup_python_steps_in_job(name, job_name, job)

        if "steps" not in job:
            problems.append(
                f"{name}::{job_name} has no 'steps' (uses="
                f"{job.get('uses')!r}). This guard reads steps, so it cannot "
                "see which Python a called workflow sets up, and it will not "
                "report a green it did not verify. Resolve it by inlining an "
                "unconditional setup-python step into this job. Pointing this "
                "guard's glob at the called workflow does NOT resolve it: "
                "that covers the callee's own jobs, while this caller still "
                "has no steps and still fails here. There is no exemption "
                "table to add it to -- see the note above on why not."
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
                "the setup-python step unconditional."
            )
            continue

        if not runnable:
            problems.append(
                f"{name}::{job_name} has {len(job['steps'])} step(s) and no "
                "actions/setup-python step. Every ordinary job must take its "
                f"interpreter from {VERSION_FILE_NAME}; without one, any "
                "Python this job runs is whatever the runner image happens "
                "to preinstall, which is the original defect arriving "
                "quietly. Add an unconditional setup-python step with "
                f"python-version-file: {VERSION_FILE_NAME}."
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


# ---------------------------------------------------------------------------
# Every branch of assertion 1 that this repository does not currently exercise.
# ---------------------------------------------------------------------------
#
# Every job here sets up Python correctly, so on this repository's own
# workflows :func:`jobs_missing_setup_python` returns ``[]`` down its happy
# path and never reaches the code that reports a problem. A reporting path
# that nothing exercises is a reporting path that can be broken without
# anything going red -- which is how the deleted-step defect survived the
# revision before last. These synthetic documents drive the three ways a job
# can fail assertion 1 through the real function, not a copy of it.

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
    """The blocker branch: a job with steps and no setup-python step.

    _SYNTHETIC also holds a correct job, so this pins that the function
    reports the offending job and not merely "something was wrong".
    """
    problems = jobs_missing_setup_python("synthetic.yml", _SYNTHETIC)

    assert len(problems) == 1, problems
    assert "synthetic.yml::no-python" in problems[0]


def test_a_uses_only_job_is_reported_and_the_advice_is_actionable():
    document = {"jobs": {"call": {"uses": "./.github/workflows/other.yml"}}}
    problems = jobs_missing_setup_python("caller.yml", document)

    assert len(problems) == 1, problems
    # The advice must not be the one that does not work.
    assert "does NOT resolve it" in problems[0]
    # ...and it must name the one that does.
    assert "inlining an unconditional setup-python step" in problems[0]


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
    problems = jobs_missing_setup_python("cond.yml", document)

    assert len(problems) == 1, problems
    assert "'if:'" in problems[0]


# ---------------------------------------------------------------------------
# The guard is only worth anything if it has something to guard.
# ---------------------------------------------------------------------------


def test_there_are_workflows_to_check():
    assert workflow_files(), f"no workflow files under {WORKFLOW_DIR}"


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


# A conda spec is ``[channel[/subdir]::]name[version[=build]]``. Only the
# leading package name is parsed here -- the version syntax after it is never
# interpreted, because interpreting it is what went wrong. conda package names
# are drawn from ``[A-Za-z0-9_.-]``, so the name is the leading run of those,
# and the first character outside the class ends it whatever it is (``=``,
# ``>``, ``<``, ``!``, ``~``, ``|``, ``,`` or a space).
CONDA_PACKAGE_NAME = re.compile(r"[A-Za-z0-9_.\-]+")


def _conda_package_name(spec):
    """The package a top-level conda dependency names, or ``None``.

    The channel prefix is stripped before the name is read, so
    ``conda-forge::python=3.12`` is recognised as a python pin. It was not,
    and that was half of a wrong pass: the pin conda would actually honour
    went unseen while a decoy elsewhere in the file was read as authoritative.
    """
    _channel, _sep, rest = spec.strip().rpartition("::")
    match = CONDA_PACKAGE_NAME.match(rest)
    return match.group(0).lower() if match else None


def python_entries_in(dependencies):
    """Every TOP-LEVEL conda dependency that names the python package.

    Top-level only. conda's ``pip:`` block is a nested mapping, and nothing
    inside it is a conda package spec, so nothing inside it can be the pin
    conda honours -- pip cannot install an interpreter for the environment it
    is running in. The previous revision flattened the nested lists into the
    same bucket as the real dependencies, so

        - conda-forge::python=3.12        # what conda actually installs
        - pip:
            - python==3.11                # read as authoritative

    passed: the decoy matched the expected version and the real pin was not
    recognised as python at all. Nested entries are not consulted here, not
    even to reject them; a pin that moves into one leaves zero top-level
    python entries, which fails below as "names Python 0 time(s)".
    """
    top_level = []
    for index, entry in enumerate(dependencies):
        if isinstance(entry, str):
            top_level.append(entry)
        elif isinstance(entry, dict):
            continue  # the pip: block; see the docstring
        else:
            raise AssertionError(
                f"{CONDA_ENV_FILE.name} dependency {index} is a "
                f"{type(entry).__name__} ({entry!r}); this guard reads conda "
                "dependencies as strings and does not recognise this shape, "
                "so it fails rather than passing over it"
            )

    return [e for e in top_level if _conda_package_name(e) == "python"]


def conda_python_entries():
    """:func:`python_entries_in` applied to the real ``environment.yml``."""
    assert CONDA_ENV_FILE.is_file(), f"{CONDA_ENV_FILE.name} is missing"

    document = _parse(CONDA_ENV_FILE)
    dependencies = document.get("dependencies")
    assert isinstance(dependencies, list) and dependencies, (
        f"{CONDA_ENV_FILE.name} has no 'dependencies' list; unrecognised shape"
    )
    return python_entries_in(dependencies)


def conda_python_pin(expected, entries):
    """Assert ``entries`` pins python in the ONE accepted form.

    Returns the accepted spec; every other input raises. ``entries`` is passed
    in rather than read here -- the same shape as
    :func:`jobs_missing_setup_python` taking a parsed document -- because
    otherwise the comparison below is reachable only through the real
    ``environment.yml``, which is correct, so loosening it would redden
    nothing. That is not hypothetical: relaxing this to a substring search
    left the entire suite green.

    EXACTLY ONE STRING PASSES: ``python=<the version in .python-version>``,
    with nothing before it and nothing after it. Not ``python 3.11``, not
    ``python>=3.11,<3.12``, not ``python=3.11.*``, not ``python=3.11=h1234_0``,
    not ``conda-forge::python=3.11``, not a bare ``python``. Those are all
    legal conda, and several of them would even install the right interpreter.
    They fail anyway.

    That is the point, and it is the fourth attempt at this function. The three
    before it tried to UNDERSTAND conda's version syntax -- match a pin, allow
    a wildcard, tolerate a build string -- and each was confidently wrong about
    a shape nobody had thought to enumerate. A parser that decides what a spec
    MEANS has to be right about every spec that exists. A parser that compares
    against one literal has to be right about one. So this does not implement
    MatchSpec, or any part of it: it identifies which entries are about python
    (name only, channel stripped), demands there be exactly one, and compares
    that one to a fixed string.

    The cost is that a correct-but-differently-spelled pin fails and someone
    has to rewrite it in the accepted form. The failure message says so. That
    is a minute of annoyance in exchange for the property that no spec this
    guard has not seen can pass it.
    """
    accepted = f"python={expected}"
    pins = [e for e in entries if _conda_package_name(e) == "python"]

    assert len(pins) == 1, (
        f"{CONDA_ENV_FILE.name} names Python {len(pins)} time(s) at the top "
        f"level of 'dependencies' ({pins!r}); it must name it exactly once. "
        f"Write it as '{accepted}'. Zero means the pin is missing, was "
        "commented out, or moved under 'pip:' where conda does not honour it; "
        "more than one means it is ambiguous which one a conda user gets."
    )

    assert pins[0].strip() == accepted, (
        f"{CONDA_ENV_FILE.name} pins Python as {pins[0].strip()!r}. The only "
        f"form this guard accepts is exactly {accepted!r} -- no channel "
        "prefix, no build string, no wildcard, no range, no spaces. This is "
        "deliberately narrower than conda's own grammar: three earlier "
        "revisions tried to interpret that grammar and each passed a spec it "
        "had misread. Only one string passes now, so a spelling this guard "
        "has never seen cannot slip through as a version it never checked. "
        f"If the pin is correct but written differently, rewrite it as "
        f"{accepted!r}; if the version itself differs from "
        f"{VERSION_FILE_NAME}, that is the divergence this guard is for."
    )
    return pins[0].strip()


def test_the_conda_environment_pins_the_same_python():
    """``environment.yml`` builds the interpreter contributors actually run.

    It pinned 3.10 while the app shipped and CI tested 3.11 -- the same defect
    as the original, relocated to the local-development plane, and the reason
    a contributor's own machine could redden a test that is green in CI.
    """
    stated = stated_version_text().strip()

    # Every way this can fail raises inside, naming the file, the spec it
    # found and the one spec it accepts. There is no returned value left to
    # compare: "is it the right version" and "is it a shape this guard
    # actually understood" are the same question here, which is what stops a
    # misread spec from being compared against the right number and passing.
    conda_python_pin(stated, conda_python_entries())


# The two branches that were wrong, driven through the real helpers.
#
# environment.yml is correct, so on this repository python_entries_in() only
# ever sees one plain top-level string and never reaches either branch. Both
# were wrong for four rounds without anything going red, which is what an
# unexercised branch buys you. These call the real functions -- not a copy of
# their logic -- with the documents that defeated the previous revision.


def test_a_pip_block_is_not_read_as_a_conda_python_pin():
    """The decoy half of the reviewer's mutation, in isolation."""
    dependencies = ["numpy>=1.20.0", {"pip": ["python==3.11", "essentia-tensorflow"]}]

    assert python_entries_in(dependencies) == []


def test_a_channel_prefixed_python_is_recognised_as_python():
    """The unseen-real-pin half. Before this, the entry conda would actually
    honour was not recognised as a python entry at all, so the count came out
    at zero-plus-a-decoy instead of one."""
    assert _conda_package_name("conda-forge::python=3.12") == "python"
    assert python_entries_in(["conda-forge::python=3.12"]) == ["conda-forge::python=3.12"]


def test_a_package_merely_starting_with_python_is_not_the_python_pin():
    """The false positive that would get this deleted: real conda environments
    carry python-dateutil, pythonocc-core and friends."""
    dependencies = ["python-dateutil>=2.8", "pythonocc-core", "python.app"]

    assert python_entries_in(dependencies) == []


def test_both_halves_of_the_reviewer_mutation_together_leave_one_wrong_pin():
    """End to end on the exact document that passed: one recognised entry,
    and it is the one conda honours -- so the comparison below it is made
    against 3.12 and fails, instead of being made against the decoy's 3.11."""
    dependencies = ["conda-forge::python=3.12", {"pip": ["python==3.11"]}]

    assert python_entries_in(dependencies) == ["conda-forge::python=3.12"]


# Every spec below names python and several install the right interpreter.
# Exactly one of them passes. This is the property the whole rewrite rests on,
# and it needs its own test: environment.yml is spelled correctly, so the
# comparison is never reached with anything else, and relaxing it to a
# substring search left the suite green.

REJECTED_PYTHON_SPECS = [
    "python 3.11",              # space-separated, legal conda
    "python>=3.11,<3.12",       # range
    "python=3.11.*",            # wildcard
    "python=3.11=h1234_0",      # build string
    "python",                   # bare
    "python==3.11",             # pip spelling
    "python =3.11",             # space before the operator
    "conda-forge::python=3.11", # right version, channel prefix
    "python=3.12",              # right FORM, wrong version -- the divergence
    "python=3.1",               # a prefix of the right version
    "python=3.11.9",            # more precise than the stated version
]


@pytest.mark.parametrize("spec", REJECTED_PYTHON_SPECS)
def test_only_the_exactly_accepted_spec_passes(spec):
    with pytest.raises(AssertionError):
        conda_python_pin("3.11", [spec])


def test_the_accepted_spec_passes():
    """The other half: this must not be a check that rejects everything."""
    assert conda_python_pin("3.11", ["python=3.11"]) == "python=3.11"


def test_the_accepted_spec_tracks_the_stated_version():
    """`accepted` is built from the argument, not hard-coded, so a bump of
    .python-version moves what passes rather than needing an edit here."""
    assert conda_python_pin("3.13", ["python=3.13"]) == "python=3.13"
    with pytest.raises(AssertionError):
        conda_python_pin("3.13", ["python=3.11"])


def test_no_python_entry_at_all_fails():
    with pytest.raises(AssertionError, match="0 time"):
        conda_python_pin("3.11", ["numpy>=1.20.0", "pip"])


def test_two_python_entries_fail_even_when_one_is_correct():
    with pytest.raises(AssertionError, match="2 time"):
        conda_python_pin("3.11", ["python=3.11", "conda-forge::python=3.12"])


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
