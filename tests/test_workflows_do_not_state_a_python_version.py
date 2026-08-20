"""Guard: one file states the Python version, and everything that selects an
interpreter is checked against it.

WHAT THIS FILE READS
--------------------
Two kinds of thing, and deliberately nothing else:

* PARSED REPOSITORY CONFIGURATION -- PyYAML's view of the workflows and of
  ``environment.yml``, and the raw bytes of ``.python-version``.
* EXACT LITERAL TEXT -- a fixed string compared for equality.

That restriction is the whole design, and it was arrived at by measurement
rather than taste. Every earlier revision of this file carried a hand-rolled
parser -- of Actions YAML shapes, of shell words, of conda's version grammar,
of this file's own prose -- and every one of them shipped a confident wrong
answer on a shape nobody had enumerated. Five consecutive review rounds each
produced a mutation that broke the property while the whole suite stayed
green, and each was closed by teaching the parser one more shape, which is
what produced the next one. A parser that decides what a construct MEANS has
to be right about every construct that exists. A comparison against one
literal has to be right about one.

So the parsers are gone rather than improved. Nothing here interprets shell
text, and nothing here reads this file's own comments or docstrings.

WHAT THIS FILE ASSERTS
----------------------
1. Every *ordinary* job -- a job with a ``steps:`` list -- in every workflow
   contains an unconditional ``actions/setup-python`` step at the root of that
   list. There is no exemption table and no way to opt a job out.
2. No setup-python step states a version inline.
3. Every setup-python step is pinned to the exact reviewed commit SHA of
   ``actions/setup-python``, spelled out in this file.
4. Every ``run:`` block that mentions uv's resolution target matches, byte for
   byte, a reviewed copy kept here. Not "contains no literal version" -- the
   text is pinned whole, so any edit to it reddens with a diff.
5. ``environment.yml`` has exactly one top-level dependency whose package name
   is ``python``, and it is spelled ``python=<the version in
   .python-version>``.
6. ``.python-version`` holds exactly one bare ASCII version token and one
   newline, byte for byte.

WHAT THIS FILE DOES **NOT** ESTABLISH
-------------------------------------
Stated here, first, because the sentence that used to open this file claimed
the opposite -- "every CI job takes its Python from ``.python-version``" and
"nothing can disagree" -- and a reviewer disproved it in three lines by adding
``run: uv python install 3.12 --default`` after a perfectly valid
setup-python step.

**This file does not determine which Python anything uses.** It asserts that
the setup-python step is PRESENT, UNCONDITIONAL and CONFIGURED FROM THE FILE.
Which interpreter a job subsequently runs is not asserted by anything here,
and the gap is not narrow:

* ``container:`` jobs -- the image's interpreter, not the runner's.
* Composite actions -- a ``uses:`` step whose own action.yml sets up Python.
* ``uv python install 3.12 --default``, ``pyenv global``, ``conda activate``,
  ``conda create`` in a ``run:`` block.
* Manual ``PATH`` manipulation, including ``$GITHUB_PATH`` writes.
* Step *order*: a ``run:`` step placed before the setup-python step runs on
  the runner's default Python. Presence is asserted; position is not.

None of the above has an instance in this repository as this is written. That
is an observation about today, not an invariant: NOTHING RE-RUNS THAT CHECK,
this file does not make it one, and a commit adding any of them goes green.

Assertion 4 is pinned text and not an understanding of the shell, so its scope
is the blocks it collects and no further. A block is collected when it
contains ``uv pip compile``, ``--python-version`` or ``UV_PYTHON`` as a
contiguous run of characters. A resolution target chosen some other way -- a
job-level or workflow-level ``env:``, ``requires-python`` in pyproject.toml,
a flag spelled so those characters never appear contiguously -- is not
collected and not covered. Deciding that in general means interpreting the
shell, which is the apparatus that shipped four wrong answers here.

Assertion 5 is a claim about entries whose leading package name is ``python``,
and about nothing else. It does NOT establish that ``environment.yml``
contains no other Python constraint. A direct package URL, a local ``.conda``
path, or any other spelling conda honours whose leading name is not ``python``
is invisible to it -- a reviewer demonstrated exactly that, adding a
``https://conda.anaconda.org/.../python-3.12.3-...conda`` entry beside
``python=3.11`` and leaving the suite green. Making the broader claim true
requires conda's own ``MatchSpec``, which is not a test dependency, so the
claim is narrowed instead of the check being taught one more spelling.

WHAT IT DOES BUY
----------------
The *declared* second sources of truth are gone. ``.python-version`` is the
SOURCE -- not the only file that states the version, which is a different and
false claim, contradicted by ``environment.yml``. Every setup-python step
points at the source instead of restating it (assertions 1-3); the one
``run:`` block that selects a resolution target is pinned verbatim
(assertion 4); ``environment.yml`` restates the version in one fixed spelling
and is compared against the source character for character (assertion 5).
What is ruled out is an UNCHECKED second statement of the version, not a
second statement.

The defect this exists to prevent is measured, not remembered.
``build-macos.yml`` has stated 3.11 since 2025-10-05. There was no test
workflow at all until 2026-08-18, when ``test-macos.yml`` was created stating
3.10 (47d8152) -- the day this repository got its first tests. It was
corrected to 3.11 two days later (8c1c0be). CI and the build disagreed for
two days, and the divergence arrived in the same commit as the CI that was
supposed to notice it. It surfaced only because a compiled-in Unicode digit
table generated from the *test* interpreter disagreed with the *shipped* one.

``environment.yml`` is where the same defect ran long. It pinned
``python=3.10`` from 2026-01-02 (ab5be5b) while the app shipped 3.11 that
entire time -- seven and a half months in which a contributor's conda
environment was a different interpreter from the one anything was verified
on, and nothing compared the two. This PR is the commit that changes it.

FAIL-CLOSED
-----------
An unparseable workflow, a job or step shape this file does not recognise, a
setup-python step with no ``with:`` block, a ``uses:``-only job, a
conditionally-run setup-python step, a missing ``.python-version`` or a
missing PyYAML is a FAILURE -- never a skip, never a pass by default. A
skipped guard reads identically to a passing one, and this project has been
bitten by that repeatedly.

Assertions 1-3 are keyed on the *parsed step*, never on a substring.
``test-macos.yml`` contains the text ``python-version`` in places that are not
setup-python inputs -- the ``uv pip compile`` flag and the
``--custom-compile-command`` string that records it. A text search for a
setup-python input reddens on a completely correct tree, and a check that
cries wolf gets weakened or deleted, which is the mechanism that produced this
whole defect family.
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

# The one commit of that action this repository runs, compared for EQUALITY
# rather than matched against a 40-hex pattern.
#
# The design rests on one behaviour of one version: with ``python-version-file``
# named, a MISSING file makes setup-python throw instead of falling back to the
# runner's Python. That is a property of the source at this commit, not of the
# name ``v5``, which GitHub documents as a tag it may move at any time.
#
# A pattern would accept any forty hex characters, so swapping in a fork's SHA
# -- or a later upstream commit whose behaviour nobody here has read -- passes
# it. An equality comparison means the upgrade is a two-file diff a reviewer
# sees. That is the intended cost.
SETUP_PYTHON_SHA = "a26af69be951a213d495a4c3e4e4022e16d87065"

# Inputs that state a version inline. setup-python takes ``python-version``;
# the other spellings never reach it, but a step carrying one is a shape this
# guard does not understand, so it fails rather than guessing.
INLINE_VERSION_KEYS = ("python-version", "python_version", "pythonVersion")

# Deliberately permissive about *form* (3.11, 3.11.9, 3.13) and strict about
# there being exactly one token. Judging the value is not this file's job.
#
# ASCII DIGITS SPELLED OUT, NEVER ``\d``. Python's ``\d`` matches every
# character in Unicode category Nd, so it matched ``٣.١١`` -- ARABIC-INDIC
# THREE, ONE, ONE. With that in ``.python-version`` and ``python=٣.١١`` in
# ``environment.yml`` the whole repository suite stayed green, both mutations
# proved applied by sha256. It is not a version anything downstream can use.
# actions/setup-python's version handling is JavaScript, where ``\d`` is
# ASCII-only with or without the ``u`` flag, so ``pythonVersionToSemantic``
# passes the string through untouched and semver receives it raw -- MEASURED on
# semver 6.3.1 and 7.7.4: ``coerce("٣.١١")`` is null, ``validRange("٣.١١")`` is
# null, and ``satisfies("3.11.9", "٣.١١")`` is false, so no release in the
# manifest matches and ``useCpythonVersion`` reaches its ``was not found``
# throw. A guard that accepts a version its own consumers cannot parse is not
# checking the thing its name says.
#
# ANCHORED ``\A``/``\Z``, NOT ``^``/``$``. ``$`` also matches immediately
# before a trailing newline, so ``^\d+(?:\.\d+)*$`` accepted ``"3.11\n"`` as a
# bare token -- measured. The caller strips before it gets here, so nothing
# reaches it with one today; that is the argument for closing it now rather
# than after a caller stops stripping.
VERSION_TOKEN = re.compile(r"\A[0-9]+(?:\.[0-9]+)*\Z")

# A conda spec is ``[channel[/subdir]::]name[version[=build]]``. Only the
# leading package name is read here -- the version syntax after it is never
# interpreted, because interpreting it is what went wrong three times. conda
# package names are drawn from ``[A-Za-z0-9_.-]``, so the name is the leading
# run of those, and the first character outside the class ends it whatever it
# is (``=``, ``>``, ``<``, ``!``, ``~``, ``|``, ``,`` or a space).
CONDA_PACKAGE_NAME = re.compile(r"[A-Za-z0-9_.\-]+")


# ---------------------------------------------------------------------------
# There is no escape hatch, deliberately.
# ---------------------------------------------------------------------------
#
# An earlier revision carried JOBS_EXEMPT_FROM_SETUP_PYTHON: a table mapping
# ``(workflow file, job name)`` to a written reason, letting a named job opt
# out of assertion 1. It was empty, and it is gone, because a reviewer used it
# to recreate the exact defect this file exists to prevent. Deleting
# build-macos.yml's setup-python step and adding
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
# construction -- they are, in fact, the definition of the hole.
#
# So there is no table, and adding one back is not a two-line change. A job
# that genuinely cannot set up Python fails here, loudly, until someone builds
# the exemption AND the enforcement that tests its claim in the same commit,
# where a reviewer sees both.


def _yaml():
    """Import PyYAML, or fail loudly and by name.

    PyYAML is not declared: it arrives as a transitive of
    essentia-tensorflow, which CI installs from
    ``requirements-macos-arm64-py311.lock`` with ``--require-hashes``. That
    makes it exactly the kind of dependency a ``pytest.importorskip`` would
    quietly turn into a green run. A skipped guard reads identically to a
    passing one. So: never skip.
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
    """The raw contents of the AUTHORITATIVE SOURCE for the version.

    Not "the one file that states the version": ``environment.yml`` states it
    too, and assertion 5 exists precisely because it does. This is the file
    the others are checked against.

    Every reader goes through here so that a missing file fails by name,
    rather than one caller reporting a bare FileNotFoundError that says
    nothing about what the file is for.

    DECODED FROM BYTES, not ``read_text``, and that is not a style choice.
    ``read_text`` opens in text mode, so Python's universal-newline
    translation turns a CRLF file into ``"3.11\\n"`` before any caller sees
    it. :func:`test_the_version_file_holds_exactly_one_version` compares this
    string against the one accepted content byte for byte; through
    ``read_text`` that comparison cannot see a CRLF file at all. Measured:
    with ``read_text``, ``3.11\\r\\n`` on disk passed. It reddens now. pyenv
    would read the version name as ``3.11\\r``; setup-python trims the ``\\r``
    away. Two consumers, two answers, from one file.
    """
    assert VERSION_FILE.is_file(), (
        f"{VERSION_FILE_NAME} is missing. Every workflow points at it, so "
        "every job would fail -- but this guard says so first, and by name."
    )
    return VERSION_FILE.read_bytes().decode("utf-8")


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
        # Comparing the first two segments establishes a PREFIX, not an
        # identity, and the two are not the same claim.
        # ``actions/setup-python/not-the-root-action@<sha>`` shares the prefix
        # and is a different action: GitHub resolves a sub-path ``uses:`` to
        # that directory's own action.yml, which this guard has never read and
        # which need not consult .python-version at all. Under the prefix
        # comparison it was accepted as the real thing and the whole suite
        # stayed green. So the prefix is where the match STARTS and the length
        # is what finishes it.
        assert len(segments) == 2, (
            f"{where} uses {action_path!r}, a sub-path under the "
            f"{'/'.join(SETUP_PYTHON)} repository rather than the root "
            "action. GitHub runs that directory's own action.yml, which this "
            f"guard has not read and which need not read {VERSION_FILE_NAME}. "
            f"Use exactly {'/'.join(SETUP_PYTHON)}@{SETUP_PYTHON_SHA}."
        )
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

    Per **job**, not per repository, and that distinction is the whole point.
    A previous revision asserted only "at least one setup-python step exists
    somewhere" plus "every step it finds is correct". Deleting the entire
    ``Set up Python`` step from ``build-macos.yml`` left valid YAML, left the
    repository-wide existence assertion satisfied by the other workflows, and
    left both per-workflow loops iterating an empty list -- the whole suite
    stayed green while that job went on to run ``pip install
    --require-hashes``, ``python -c`` and ``python build_app.py`` on whatever
    interpreter the runner image happened to carry. A guard that proves a
    property only about the steps it *finds* proves nothing about the steps
    that are gone.
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
                    "uses": f"actions/setup-python@{SETUP_PYTHON_SHA}",
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
                        "uses": f"actions/setup-python@{SETUP_PYTHON_SHA}",
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
            "that no two setup-python steps can disagree about the "
            "interpreter they install."
        )


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_every_setup_python_step_points_at_the_version_file(workflow):
    """Uniform and unambiguous: one input, one target, no alternatives.

    ``python-version-file`` rather than omitting the input, although
    setup-python does read ``.python-version`` when nothing is supplied. The
    two differ when the file is gone: omission logs a warning and falls back
    to whatever Python the runner preinstalled, while a stated file that does
    not exist throws. Fail-closed, and it names its source in the workflow.

    ON THE ``.strip()`` BELOW -- the rule is STRIP WHERE THE CONSUMER STRIPS.
    Comparing a stripped copy is exactly the shape that was a defect for the
    conda pin, where a padded ``" python=3.11 "`` passed a guard claiming that
    one string and only one string passes, while conda rejects the spec
    outright. It is correct here, and the difference is the consumer, not the
    style. setup-python reads this input as
    ``core.getInput('python-version-file')`` with no options, and at the
    commit this repository pins the bundled toolkit's ``getInput`` ends
    ``return val.trim()`` unless ``options.trimWhitespace === false`` is
    passed, which setup-python does not pass. The action sees the trimmed
    string, so a padded value here is genuinely equivalent. conda is the
    opposite: it takes the spec verbatim, which is why
    :func:`conda_python_pin` compares the raw scalar.

    That argument is also not load-bearing, which is the point of demanding
    this input at all. If the trim ever went away, setup-python reaches
    ``fs.existsSync(versionFile)`` and THROWS "The specified python version
    file at: ... doesn't exist". A padded value cannot become a silent
    fall-back to the runner's Python in either world.
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


def test_every_setup_python_step_is_pinned_to_the_reviewed_sha():
    """One reviewed commit, compared for equality. See :data:`SETUP_PYTHON_SHA`.

    All of them must agree with that constant and therefore with each other,
    for the same reason the Python version has one authoritative source: two
    pins are two things that can drift apart.
    """
    refs = {}
    for path in workflow_files():
        for where, _step, ref in setup_python_steps(path):
            refs[where] = ref

    assert refs, "no setup-python step found to check the pin of"

    wrong = sorted(w for w, ref in refs.items() if ref != SETUP_PYTHON_SHA)
    assert not wrong, (
        f"setup-python must be pinned to exactly {SETUP_PYTHON_SHA} -- the "
        "reviewed commit, with the version in a trailing comment. These are "
        "not: " + ", ".join(f"{w} -> {refs[w]!r}" for w in wrong)
        + ". A tag like 'v5' is mutable by GitHub's own documentation, and "
        "any other SHA is a commit whose throw-on-missing-file behaviour "
        "nobody here has read. To upgrade, change SETUP_PYTHON_SHA and the "
        "workflows in the same commit, so a reviewer sees both."
    )


# Which strings are, and are not, the action this guard is about.
#
# Every step in this repository is spelled correctly, so :func:`_is_setup_python`
# only ever sees the root action here and never reaches the branches that
# decide anything. One of those branches compared a PREFIX and called it an
# identity, and it was wrong for four rounds with nothing going red.


def test_the_root_action_is_recognised():
    assert _is_setup_python("w::j step 0", ("actions/setup-python", "0" * 40)) is True


def test_a_sub_path_under_setup_python_is_not_the_root_action():
    """The reviewer's mutation, in isolation.

    ``actions/setup-python/not-the-root-action@<sha>`` shares two segments
    with the real action and is a different action: GitHub runs that
    directory's own action.yml. The prefix comparison accepted it as the real
    thing and the whole suite stayed green.
    """
    with pytest.raises(AssertionError, match="sub-path"):
        _is_setup_python(
            "w::j step 0", ("actions/setup-python/not-the-root-action", "0" * 40)
        )


def test_a_fork_or_mirror_of_setup_python_is_not_silently_skipped():
    with pytest.raises(AssertionError, match="looks like setup-python"):
        _is_setup_python("w::j step 0", ("someone-else/setup-python", "0" * 40))


def test_an_unrelated_action_is_not_setup_python():
    """The false positive that would get this deleted: setup-uv also takes a
    ``python-version`` input."""
    assert _is_setup_python("w::j step 0", ("astral-sh/setup-uv", "v7")) is False
    assert _is_setup_python("w::j step 0", None) is False


# ---------------------------------------------------------------------------
# Assertion 4: uv's resolution target, pinned as text rather than parsed.
# ---------------------------------------------------------------------------
#
# ``uv pip compile --python-version`` chooses the interpreter uv RESOLVES for,
# so a literal there is a second source of truth: bumping .python-version alone
# would leave the dependency set resolved for the old interpreter and installed
# on the new one.
#
# THE STRUCTURAL BACKSTOP FOR THIS DOES NOT EXIST -- MEASURED. The strongest
# argument for having no check here at all is that test-macos.yml already
# recompiles the lock and runs ``git diff --exit-code``, so a wrong
# --python-version would resolve a different dependency set and the committed
# lock would stop matching. That was measured on 2026-08-20 rather than
# believed: the job's own command was re-run with the flag set to 3.12, output
# to a temporary path, and the result was BYTE-IDENTICAL to the committed lock
# (both sha256 5845ce4030f7a487ea8fb00d15a245d27703d59f70f1fdfe878e7fd316213278).
# The resolved body does not depend on the flag at all for today's dependency
# set; only the header comment does, and only because --custom-compile-command
# echoes the value verbatim. So the drift gate accepts the mutation, exits 0,
# and CI is green with the dependency set resolved for the wrong interpreter.
# That invariance is an accident of today's dependency set -- one dependency
# gaining a marker that flips between 3.11 and 3.12 changes it, in either
# direction, without a commit here. A backstop that happens to be inert today
# is not a backstop, so something has to check this.
#
# WHAT USED TO BE HERE, AND WHY IT IS GONE. Five revisions read the shell text
# looking for a bare version token next to the flag: split on whitespace,
# unquote each word, unquote each half of a word glued with ``=``. It carried
# five admitted blind spots and a reviewer found a sixth in each of the last
# five rounds -- an interior-quoted flag name (``--pyth"on-version"=3.12``, which
# the shell glues back together before uv sees it), a fragment-assembled flag,
# a value arriving from a job-level ``env:``, a variable assigned a literal two
# lines above the call. Every one of those is invisible to a comparison against
# fixed text only if the text still matches, and it does not: the block is
# pinned WHOLE, so any edit to any of it reddens with a diff.
#
# The cost is real and is the point: a legitimate change to this command --
# a new flag, a moved --exclude-newer date -- reddens this test and someone
# pastes the new text in. Every one of those edits changes what uv resolves
# against or what the lock records, and none of them should land without a
# reviewer looking at the resolution target.
#
# What it does NOT cover is written next to the collection markers below.

# A run block is collected -- and therefore has to match a reviewed copy --
# when it contains any of these as a contiguous run of characters.
#
# This is SELECTION, not parsing: nothing here decides what the shell would do
# with the text, only which blocks are subject to the comparison. Three
# markers rather than one because each is a way a block can name uv's
# resolution target, and a block naming it any of those ways should not be
# able to appear without review.
#
# A block that selects an interpreter without any of them -- a job-level or
# workflow-level ``env:``, ``requires-python`` in pyproject.toml, ``uv python
# install``, a flag spelled so the characters never appear contiguously -- is
# NOT collected and NOT covered. Deciding that in general means interpreting
# the shell, which is the apparatus that shipped four confident wrong answers
# in earlier rounds of this PR.
UV_RESOLUTION_MARKERS = ("uv pip compile", "--python-version", "UV_PYTHON")

# The reviewed text of every collected block, keyed by where it lives.
#
# A raw string, so the shell's line continuations are the characters they look
# like. Compared with ``==`` against the scalar PyYAML hands back.
_LOCK_COMPILE_RUN = r'''PYTHON_VERSION="$(cat .python-version)"
uv pip compile \
  --python-version "$PYTHON_VERSION" \
  --python-platform aarch64-apple-darwin \
  --prerelease explicit \
  --exclude-newer 2026-08-20 \
  --build-constraint build-constraints.txt \
  --generate-hashes \
  --custom-compile-command "MACOSX_DEPLOYMENT_TARGET=15.2 uv pip compile --python-version $PYTHON_VERSION --python-platform aarch64-apple-darwin --prerelease explicit --exclude-newer 2026-08-20 --build-constraint build-constraints.txt --generate-hashes requirements-macos-arm64-py311.in -o requirements-macos-arm64-py311.lock" \
  requirements-macos-arm64-py311.in \
  -o requirements-macos-arm64-py311.lock
git diff --exit-code -- requirements-macos-arm64-py311.lock
'''

REVIEWED_UV_RESOLUTION_BLOCKS = {
    ("test-macos.yml", "pytest"): _LOCK_COMPILE_RUN,
}


def uv_resolution_blocks(name, document):
    """``{(workflow, job): run}`` for every collected block in one document.

    Collection is the substring test described on
    :data:`UV_RESOLUTION_MARKERS` and nothing more.

    Keyed by ``(workflow, job)`` and not by step index or step name, so that
    renaming a step or inserting an unrelated one before it does not redden
    this. Two collected blocks in one job would collide, and that is reported
    rather than silently keeping the last one.
    """
    found = {}
    for job_name, job in _jobs_of(name, document):
        for index, step in _steps_of(name, job_name, job):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            if not any(marker in run for marker in UV_RESOLUTION_MARKERS):
                continue

            key = (name, job_name)
            assert key not in found, (
                f"{name}::{job_name} has more than one run block naming uv's "
                "resolution target; this guard pins one reviewed block per "
                f"job and cannot tell which of them is which. The second is "
                f"at step {index}. Put them in separate jobs, or fold them "
                "into one block and update the reviewed copy."
            )
            found[key] = run
    return found


def test_every_uv_resolution_block_matches_its_reviewed_text():
    """The blocks that choose what uv resolves against are pinned verbatim.

    Not "no literal version appears next to the flag" -- that claim needed a
    shell-text parser, and a reviewer defeated the parser in each of the last
    five rounds. This compares fixed text with ``==``: a literal version, a
    re-quoted flag, a variable assigned a literal, a moved ``--exclude-newer``
    and a deleted flag are all simply "the text differs".

    Both directions matter. A collected block that is not in the reviewed
    mapping is a NEW place uv's target is chosen. A reviewed key with no
    collected block means the step was deleted, renamed out of its job, or had
    every marker removed -- which is what a mutation that moves the target
    somewhere else looks like from here.
    """
    found = {}
    for path in workflow_files():
        found.update(uv_resolution_blocks(path.name, _parse(path)))

    unreviewed = sorted(set(found) - set(REVIEWED_UV_RESOLUTION_BLOCKS))
    assert not unreviewed, (
        "these run blocks name uv's resolution target and have no reviewed "
        f"copy in this file: {unreviewed}. uv resolves the dependency set FOR "
        "whatever they select, and the lock-drift gate does not catch a wrong "
        "selection (the recompile at 3.12 is byte-identical today; see the "
        "note above). Read the block, then add it to "
        "REVIEWED_UV_RESOLUTION_BLOCKS verbatim."
    )

    missing = sorted(set(REVIEWED_UV_RESOLUTION_BLOCKS) - set(found))
    assert not missing, (
        f"no run block was collected for {missing}, which this file has a "
        "reviewed copy of. The step was deleted, moved to another job, or no "
        "longer contains any of "
        f"{UV_RESOLUTION_MARKERS}. If uv's resolution target moved, the new "
        "block has to be reviewed and pinned here; if it is genuinely gone, "
        "delete the entry."
    )

    for key, reviewed in sorted(REVIEWED_UV_RESOLUTION_BLOCKS.items()):
        assert found[key] == reviewed, (
            f"{key[0]}::{key[1]} run block differs from the reviewed copy in "
            "this file.\n--- reviewed ---\n"
            f"{reviewed}--- in the workflow ---\n{found[key]}"
            "--- end ---\nThis block chooses the interpreter uv resolves the "
            "dependency set FOR, and the lock-drift gate does not catch a "
            "wrong choice. If the change is intended, read it and paste the "
            "new text into REVIEWED_UV_RESOLUTION_BLOCKS in the same commit."
        )


# The branches of assertion 4 that this repository does not exercise. Its own
# workflows are correct, so the comparison above only ever walks its happy
# path, and every reporting branch below was unreachable from the real files.


def test_a_run_block_naming_no_marker_is_not_collected():
    document = {"jobs": {"j": {"steps": [{"run": "python -m pytest -q"}]}}}

    assert uv_resolution_blocks("w.yml", document) == {}


def test_a_run_block_naming_a_marker_is_collected():
    document = {"jobs": {"j": {"steps": [{"run": "uv pip compile reqs.in"}]}}}

    assert uv_resolution_blocks("w.yml", document) == {
        ("w.yml", "j"): "uv pip compile reqs.in"
    }


def test_an_environment_variable_spelling_is_collected_too():
    """``UV_PYTHON`` selects uv's interpreter without naming the flag, so a
    block setting it is collected and has to be reviewed like any other."""
    document = {"jobs": {"j": {"steps": [{"run": "UV_PYTHON=3.12 uv sync"}]}}}

    assert set(uv_resolution_blocks("w.yml", document)) == {("w.yml", "j")}


def test_two_collected_blocks_in_one_job_are_reported():
    document = {
        "jobs": {
            "j": {
                "steps": [
                    {"run": "uv pip compile a.in"},
                    {"run": "uv pip compile b.in"},
                ]
            }
        }
    }
    with pytest.raises(AssertionError, match="more than one run block"):
        uv_resolution_blocks("w.yml", document)


def test_the_reviewed_text_is_compared_exactly():
    """A one-character edit is a different string. That is the entire check,
    and it is stated here so that a future revision cannot quietly relax the
    comparison to a substring test without something going red."""
    mutated = _LOCK_COMPILE_RUN.replace('"$PYTHON_VERSION"', "3.12")

    assert mutated != _LOCK_COMPILE_RUN
    assert mutated not in REVIEWED_UV_RESOLUTION_BLOCKS.values()


# ---------------------------------------------------------------------------
# Assertion 5: the local-development plane agrees with CI.
# ---------------------------------------------------------------------------


def _conda_package_name(spec):
    """The package a top-level conda dependency names, or ``None``.

    The channel prefix is stripped before the name is read, so
    ``conda-forge::python=3.12`` is recognised as a python pin. It was not,
    and that was half of a wrong pass: the pin conda would actually honour
    went unseen while a decoy elsewhere in the file was read as authoritative.

    An entry whose leading name is not a package name -- a direct package
    URL, a local path -- reports whatever leading run of name characters it
    happens to start with (``https``, for a URL). It is therefore not counted
    as a python entry, and a Python constraint spelled that way is invisible
    to assertion 5. That is stated in the module docstring as a limit of the
    claim rather than patched here: recognising it in general is conda's own
    ``MatchSpec``, which is not a test dependency.
    """
    _channel, _sep, rest = spec.strip().rpartition("::")
    match = CONDA_PACKAGE_NAME.match(rest)
    return match.group(0).lower() if match else None


def python_entries_in(dependencies):
    """Every TOP-LEVEL conda dependency whose package name is ``python``.

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
    in rather than read here because otherwise the comparison below is
    reachable only through the real ``environment.yml``, which is correct, so
    loosening it would redden nothing. That is not hypothetical: relaxing this
    to a substring search left the entire suite green.

    EXACTLY ONE STRING PASSES: ``python=<the version in .python-version>``,
    with nothing before it and nothing after it. Not ``python 3.11``, not
    ``python>=3.11,<3.12``, not ``python=3.11.*``, not ``python=3.11=h1234_0``,
    not ``conda-forge::python=3.11``, not a bare ``python``. Those are all
    legal conda, and several of them would even install the right interpreter.
    They fail anyway.

    That is the point, and it is the fourth attempt at this function. The three
    before it tried to UNDERSTAND conda's version syntax -- match a pin, allow
    a wildcard, tolerate a build string -- and each was confidently wrong about
    a shape nobody had thought to enumerate. So this does not implement
    ``MatchSpec``, or any part of it: it identifies which entries are about
    python (leading name only, channel stripped), demands there be exactly
    one, and compares that one to a fixed string.

    THE SCOPE OF THE COUNT, stated because a reviewer's mutation turned on it:
    "exactly one" counts entries whose LEADING PACKAGE NAME is ``python``. An
    entry that constrains Python without being spelled that way -- a direct
    ``https://.../python-3.12.3-...conda`` URL, a local path -- is not counted
    and does not fail here. Adding such an entry beside ``python=3.11`` leaves
    this green, and was measured doing so. This is not the claim that
    ``environment.yml`` has no other Python constraint; it is the claim that
    it has exactly one *named* one and that it reads ``python=<version>``.

    The comparison is against the RAW scalar. It used to ``.strip()`` first,
    and ``- " python=3.11 "`` -- valid YAML -- therefore passed, while conda
    refuses that spec outright: measured on conda 23.1.0, ``MatchSpec`` raises
    ``InvalidMatchSpec: no package name found in ' python=3.11 '``. A guard
    that accepts exactly one literal has to compare the literal.
    Identification (:func:`_conda_package_name`) still strips, on purpose, so
    a padded pin is FOUND and reported as wrongly spelled rather than counted
    as absent.
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

    assert pins[0] == accepted, (
        f"{CONDA_ENV_FILE.name} pins Python as {pins[0]!r}. The only "
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
    return pins[0]


def test_the_conda_environment_pins_the_same_python():
    """``environment.yml`` builds the interpreter contributors actually run.

    It pinned 3.10 from 2026-01-02 (ab5be5b) while the app shipped 3.11 the
    whole time -- seven and a half months, against the two days CI and the
    build disagreed. Same defect as the original, relocated to the
    local-development plane, running far longer because no plane compared
    them, and the reason a contributor's own machine could redden a test that
    is green in CI.
    """
    stated = stated_version_text().strip()

    # Every way this can fail raises inside, naming the file, the spec it
    # found and the one spec it accepts. There is no returned value left to
    # compare: "is it the right version" and "is it a shape this guard
    # actually understood" are the same question here, which is what stops a
    # misread spec from being compared against the right number and passing.
    conda_python_pin(stated, conda_python_entries())


# The branches that were wrong, driven through the real helpers.
#
# environment.yml is correct, so on this repository python_entries_in() only
# ever sees plain top-level strings and never reaches either branch. Both were
# wrong for four rounds without anything going red, which is what an
# unexercised branch buys you.


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


def test_a_direct_package_url_is_not_counted_as_a_python_entry():
    """The limit of assertion 5, pinned as a MISS so it is a stated decision
    and not a surprise.

    A reviewer added this line beside ``python=3.11`` in the real
    ``environment.yml``, giving it two Python dependencies at two versions,
    and the suite stayed green. The leading run of package-name characters is
    ``https``, so the entry is not a python entry to this file and the count
    stays at one. Recognising it in general is ``MatchSpec``. The module
    docstring states the narrowed claim; this pins the boundary executably, so
    a later change that starts seeing such entries reddens here and whoever
    made it updates the claim in the same commit.
    """
    url = (
        "https://conda.anaconda.org/conda-forge/osx-arm64/"
        "python-3.12.3-h4a7b5fc_0_cpython.conda"
    )

    assert _conda_package_name(url) == "https"
    assert python_entries_in(["python=3.11", url]) == ["python=3.11"]


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
    # Quoted in YAML so the scalar carries the padding: `- " python=3.11 "` is
    # valid YAML, and the comparison used to .strip() before comparing, so it
    # passed. What conda does with these four was MEASURED (conda 23.1.0,
    # conda.models.match_spec.MatchSpec) rather than assumed, because they do
    # not behave alike:
    #
    #   ' python=3.11 '   InvalidMatchSpec: no package name found in ...
    #   ' python=3.11'    InvalidMatchSpec: no package name found in ...
    #   'python=3.11 '    ACCEPTED, parsed as python=3.11
    #   '\tpython=3.11'   parsed WITHOUT error into a spec whose package name
    #                     is "\tpython" -- no channel has that, so it fails
    #                     later, at solve time, as a package-not-found
    #
    # So only leading whitespace is the outright rejection; trailing is
    # harmless to conda and a tab is worse than a rejection, because it fails
    # somewhere else entirely. All four are refused here anyway, and that is
    # the case for a guard that accepts one literal instead of modelling the
    # grammar: it did not need to know which of these conda tolerates.
    #
    # Identification still strips, so each is reported as a wrongly-spelled
    # pin rather than as no pin at all; the comparison does not.
    " python=3.11 ",            # surrounding whitespace -- conda rejects
    " python=3.11",             # leading only -- conda rejects
    "python=3.11 ",             # trailing only -- conda ACCEPTS; refused here
    "\tpython=3.11",            # a tab -- conda parses it into a package
                                # named "\tpython" that does not exist
]


@pytest.mark.parametrize("spec", REJECTED_PYTHON_SPECS)
def test_only_the_exactly_accepted_spec_passes(spec):
    with pytest.raises(AssertionError):
        conda_python_pin("3.11", [spec])


def test_a_quoted_padded_pin_is_identified_and_then_rejected():
    """The asymmetry this rests on, stated as a test.

    Identification is tolerant so that a badly spelled pin is still FOUND --
    otherwise a padded entry would count as zero python entries and the
    failure would read "names Python 0 time(s)", pointing at a missing pin
    rather than at the one that is right there. The comparison is exact,
    because the accepted string is the one conda accepts.
    """
    assert python_entries_in([" python=3.11 "]) == [" python=3.11 "]

    with pytest.raises(AssertionError, match="pins Python as"):
        conda_python_pin("3.11", [" python=3.11 "])


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


def one_version_token(raw):
    r"""Assert ``raw`` is one bare version token and one newline; return it.

    ``raw`` is passed in rather than read from disk here, for the reason
    argued on :func:`conda_python_pin`: this repository's ``.python-version``
    is correct, so every rejecting branch below is unreachable through the
    real file and loosening any of them reddens nothing. That is not
    hypothetical for this particular check. With :data:`VERSION_TOKEN` written
    as ``\d`` it accepted a version spelled in ARABIC-INDIC digits, and the
    only test that could have caught it was this one, reading a file that does
    not contain them.
    """
    version = raw.strip()

    assert VERSION_TOKEN.match(version), (
        f"{VERSION_FILE_NAME} holds {raw!r}, which trims to {version!r} -- not "
        "a bare version token. A second line, a comment or any other extra "
        "text is not a note: pyenv would read every line here as a version "
        "name while setup-python reads the whole trimmed file as ONE version "
        "string, so the two consumers would not even agree on what this file "
        "says. Digits must be ASCII: setup-python hands this string to semver, "
        "whose parse is ASCII-only, and a version it cannot coerce is a "
        "version no release in the manifest matches."
    )

    assert raw == f"{version}\n", (
        f"{VERSION_FILE_NAME} holds {raw!r}; the one accepted content is "
        f"{version + chr(10)!r} -- the version token and a single newline, "
        "nothing before it and nothing after it. Both consumers trim, so this "
        "is stricter than either requires; see "
        ":func:`test_the_version_file_holds_exactly_one_version` for why that "
        "is the right trade for this particular file."
    )
    return version


# Every one of these is a version to Python's ``\d`` and to nothing else in
# the chain. The name of each character is spelled out because the glyphs are
# the entire point and are not readable at a glance in a diff.
NON_ASCII_DIGIT_VERSIONS = [
    ("٣.١١", "ARABIC-INDIC"),
    ("۳.۱۱", "EXTENDED-ARABIC-INDIC"),
    ("３.１１", "FULLWIDTH"),
    ("𝟹.𝟷𝟷", "MATHEMATICAL-MONOSPACE"),
    ("3.١١", "ASCII-major-ARABIC-INDIC-minor"),
    ("٣.11", "ARABIC-INDIC-major-ASCII-minor"),
]


@pytest.mark.parametrize("version,script", NON_ASCII_DIGIT_VERSIONS)
def test_a_version_written_in_non_ascii_digits_is_refused(version, script):
    r"""The reviewer's green mutant, driven through the real check.

    ``.python-version`` holding ``٣.١١`` and ``environment.yml`` holding
    ``python=٣.١١`` left the WHOLE REPOSITORY suite green, both mutations
    proved applied by sha256 and reverted byte-identical. Every character
    above is Unicode category Nd, which is what Python's ``\d`` means and is
    not what any consumer of this file means. The mixed rows matter too:
    ``coerce("3.١١")`` is not null, it is ``3.0.0``, so that spelling does not
    even fail honestly.

    Each row is checked to BE the thing it is here to be before it is used,
    because a row that is refused for some unrelated reason -- a stray letter,
    a typo -- passes this test while pinning nothing at all, and it passes
    silently. So: the row must be a version to the ``\d`` this replaced, and
    must not be ASCII. Those two together are exactly "green before, red now".
    """
    assert re.match(r"\A\d+(?:\.\d+)*\Z", version), (
        f"the {script} row is not a version even to the Unicode-aware ``\\d`` "
        "this fix replaced, so it would have been refused before the fix too "
        "and pins nothing"
    )
    assert not version.isascii(), (
        f"the {script} row is written in ASCII, so it is not the thing this "
        "test is named for"
    )

    with pytest.raises(AssertionError, match="not a bare version token"):
        one_version_token(f"{version}\n")


def test_an_ascii_version_still_passes():
    """The other half: this must not be a check that refuses everything."""
    assert one_version_token("3.11\n") == "3.11"
    assert one_version_token("3.11.9\n") == "3.11.9"
    assert one_version_token("3\n") == "3"


def test_a_trailing_newline_is_not_itself_part_of_a_version_token():
    r"""``^...$`` matched a token with a newline glued on, because ``$`` also
    matches immediately before one. The caller strips first, so nothing
    reached it that way; it is anchored ``\A``/``\Z`` now regardless."""
    assert VERSION_TOKEN.match("3.11")
    assert not VERSION_TOKEN.match("3.11\n")


def test_the_version_file_holds_exactly_one_version():
    """One version, one line -- and the test means it literally.

    It did not. It filtered blank lines out before counting them, so
    ``"\n3.11\n\n"`` -- three physical lines -- passed a check whose name and
    whose first docstring line both said one line. A reviewer found it by
    reading the claim against the assertion. The whole file content is
    compared now, so exactly one byte string is accepted: the version token
    and one newline.

    pyenv reads every line of this file as a version name, so a second line or
    a trailing comment is not a note -- it is a second source of truth.

    The two consumers disagree about the file in a way that makes "exactly one
    line" the only spelling both accept. setup-python does not read it line by
    line at all: at the pinned commit ``getVersionInputFromPlainFile`` is
    ``fs.readFileSync(versionFile, 'utf8').trim()`` returning ``[version]`` --
    the WHOLE file, trimmed, as ONE version string. A second line does not
    become a second candidate there; it becomes the single nonsense version
    ``"3.11\n3.12"``. pyenv, meanwhile, would read two. Neither is what anyone
    meant, and both are refused here.

    THIS IS STRICTER THAN EITHER CONSUMER, and that is a deliberate departure
    from the rule argued in
    :func:`test_every_setup_python_step_points_at_the_version_file` -- STRIP
    WHERE THE CONSUMER STRIPS. Both consumers trim, so both would accept
    ``" 3.11 "`` and ``"\n3.11\n\n"``; this refuses them anyway. The
    difference is what is being judged. There, it is a value a human typed
    into a workflow, where refusing a spelling the consumer accepts is a check
    crying wolf -- and a check that cries wolf gets weakened or deleted, which
    is the mechanism that produced this whole defect family. Here it is a file
    with one job and one correct content, and what that content is is not a
    matter of taste: ``echo 3.11 > .python-version`` produces it and this
    repository's file already is it, byte for byte. Whether some editor
    somewhere would write it differently is NOT claimed here and was not
    measured. Being wrong about an editor costs one red test whose message
    names the expected bytes, which is a one-line correction; the alternative
    cost a test whose name said one line while it accepted three.
    """
    one_version_token(stated_version_text())
