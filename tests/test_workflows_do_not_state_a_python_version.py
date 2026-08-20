"""Guard: ``.python-version`` is compared against the places listed under
WHAT THIS FILE ASSERTS below -- the ``with:`` inputs of each setup-python
step, the conda pin in ``environment.yml``, and the run blocks pinned verbatim
here. Those comparisons are the enforced set; other things in this repository
can choose an interpreter without being compared to anything, and they are
named under WHAT THIS FILE DOES **NOT** ESTABLISH and on
:data:`UV_RESOLUTION_MARKERS`. Nor is ``.python-version`` the one file that
states the version: ``environment.yml`` restates it, which is why assertion 5
exists to compare the two rather than to forbid the second statement.

WHAT THIS FILE READS -- two kinds of thing, and deliberately nothing else:
PARSED REPOSITORY CONFIGURATION (PyYAML's view of the workflows and of
``environment.yml``, the raw bytes of ``.python-version``), and EXACT LITERAL
TEXT compared for equality.

That restriction was arrived at by measurement. Every earlier revision carried
a hand-rolled parser -- of Actions YAML shapes, of shell words, of conda's
version grammar, of this file's own prose -- and each shipped a confident wrong
answer on a shape nobody had enumerated. Five consecutive review rounds each
produced a mutation that broke the property while the suite stayed green, and
each was closed by teaching the parser one more shape, which is what produced
the next one. A parser that decides what a construct MEANS has to be right
about every construct that exists; a comparison against one literal has to be
right about one. So the parsers are gone rather than improved.

WHAT THIS FILE ASSERTS
----------------------
1. Every *ordinary* job -- one with a ``steps:`` list -- in every workflow has
   an unconditional ``actions/setup-python`` step at the root of that list.
   There is no exemption table and no way to opt a job out.
2. No setup-python step states a version inline.
3. Every setup-python step is pinned to the exact reviewed commit SHA of
   ``actions/setup-python``, spelled out below.
4. Every ``run:`` block that names uv's resolution target matches, byte for
   byte, a reviewed copy kept here. Not "contains no literal version": the
   text is pinned whole, so any edit to it reddens with a diff.
5. ``environment.yml`` has exactly one top-level dependency whose leading
   package name is ``python``, spelled ``python=<the version in
   .python-version>``.
6. ``.python-version`` holds one bare ASCII version token and one newline,
   byte for byte.

WHAT THIS FILE DOES **NOT** ESTABLISH
-------------------------------------
Stated first, because the sentence that used to open this file claimed the
opposite -- "every CI job takes its Python from ``.python-version``",
"nothing can disagree" -- and a reviewer disproved it in three lines by
adding ``run: uv python install 3.12 --default`` after a valid setup-python
step.

**This file does not determine which Python anything uses.** It asserts that
the setup-python step is PRESENT, UNCONDITIONAL and CONFIGURED FROM THE FILE.
Which interpreter a job subsequently runs is asserted by nothing here, and the
gap is not narrow: ``container:`` jobs run the image's interpreter; a
composite action's own action.yml may set up Python; ``uv python install
--default``, ``pyenv global``, ``conda activate`` and ``$GITHUB_PATH`` writes
all replace it from a ``run:`` block; and step ORDER is not checked, so a
``run:`` step placed before the setup step runs on the runner's default
Python. None of those has an instance in this repository as this is written --
an observation about today, not an invariant. NOTHING RE-RUNS THAT CHECK, and
a commit adding any of them goes green.

Assertion 4 is pinned text rather than an understanding of the shell, so its
scope is the blocks it collects and no further; the collection rule and what
falls outside it are on :data:`UV_RESOLUTION_MARKERS`. Assertion 5 is a claim
about entries whose leading package name is ``python`` and about nothing else
-- it does NOT establish that ``environment.yml`` carries no other Python
constraint; see :func:`conda_python_pin`.

WHAT IT DOES BUY
----------------
``.python-version`` is the SOURCE -- not the only file that states the version,
which is a different and false claim, contradicted by ``environment.yml``. What
is ruled out is an UNCHECKED second statement of the version, not a second
statement.

The defect is measured, not remembered. ``build-macos.yml`` has stated 3.11
since 2025-10-05; there was no test workflow at all until 2026-08-18, when
``test-macos.yml`` was created stating 3.10 (47d8152) and corrected two days
later (8c1c0be) -- the divergence arrived in the same commit as the CI that was
supposed to notice it, and surfaced only because a compiled-in Unicode digit
table generated from the *test* interpreter disagreed with the *shipped* one.
``environment.yml`` is where it ran long: ``python=3.10`` from 2026-01-02
(ab5be5b) while the app shipped 3.11 that entire time -- seven and a half
months in which a contributor's conda environment was a different interpreter
from the one anything was verified on, and nothing compared the two.

FAIL-CLOSED
-----------
An unparseable workflow, a job or step shape this file does not recognise, a
setup-python step with no ``with:`` block, a ``uses:``-only job, a
conditionally-run setup-python step, a missing ``.python-version`` or a
missing PyYAML is a FAILURE -- never a skip, never a pass by default. A
skipped guard reads identically to a passing one.

Assertions 1-3 are keyed on the *parsed step*, never on a substring.
``test-macos.yml`` contains the text ``python-version`` in places that are not
setup-python inputs -- the ``uv pip compile`` flag, and the
``--custom-compile-command`` string that records it -- so a text search
reddens on a completely correct tree, and a check that cries wolf gets
weakened or deleted, which is the mechanism that produced this whole defect
family.
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
# name ``v5``, which GitHub documents as a tag it may move at any time. A
# pattern would accept any forty hex characters, so a fork's SHA -- or a later
# upstream commit nobody here has read -- passes it. Equality makes the upgrade
# a two-file diff a reviewer sees. That is the intended cost.
SETUP_PYTHON_SHA = "a26af69be951a213d495a4c3e4e4022e16d87065"

# Inputs that state a version inline. setup-python takes ``python-version``;
# the other spellings never reach it, but a step carrying one is a shape this
# guard does not understand, so it fails rather than guessing. Compared through
# :func:`runner_input_name`, which is what makes each entry stand for every
# casing of itself -- and which keeps these three DISTINCT, because the runner
# folds case and spaces and nothing else.
INLINE_VERSION_KEYS = ("python-version", "python_version", "pythonVersion")

# The one input a setup-python step here is allowed to configure the version
# with. Also compared through :func:`runner_input_name`.
VERSION_FILE_INPUT = "python-version-file"

# Deliberately permissive about *form* (3.11, 3.11.9, 3.13) and strict about
# there being exactly one token. Judging the value is not this file's job.
#
# ASCII DIGITS SPELLED OUT, NEVER ``\d``. Python's ``\d`` matches every
# character in Unicode category Nd, so it matched ``٣.١١`` -- ARABIC-INDIC
# THREE, ONE, ONE. With that in ``.python-version`` and ``python=٣.١١`` in
# ``environment.yml`` the whole repository suite stayed green, both mutations
# proved applied by sha256. actions/setup-python's version handling is
# JavaScript, where ``\d`` is ASCII-only with or without the ``u`` flag, so
# ``pythonVersionToSemantic`` passes the string through untouched and semver
# receives it raw -- MEASURED on semver 6.3.1 and 7.7.4: ``coerce("٣.١١")`` is
# null, ``validRange("٣.١١")`` is null, ``satisfies("3.11.9", "٣.١١")`` is
# false. No release in the manifest matches and ``useCpythonVersion`` reaches
# its ``was not found`` throw. A guard that accepts a version its own consumers
# cannot parse is not checking the thing its name says.
#
# ANCHORED ``\A``/``\Z``, NOT ``^``/``$``: ``$`` also matches immediately
# before a trailing newline, so ``^\d+(?:\.\d+)*$`` accepted ``"3.11\n"`` as a
# bare token -- measured. The caller strips before it gets here, so nothing
# reaches it with one today; that is the argument for closing it now rather
# than after a caller stops stripping.
VERSION_TOKEN = re.compile(r"\A[0-9]+(?:\.[0-9]+)*\Z")

# A conda spec is ``[channel[/subdir]::]name[version[=build]]``. Only the
# leading package name is read -- the version syntax after it is never
# interpreted, because interpreting it is what went wrong three times. conda
# package names are drawn from ``[A-Za-z0-9_.-]``, so the name is the leading
# run of those and the first character outside the class ends it, whatever it
# is (``=``, ``>``, ``<``, ``!``, ``~``, ``|``, ``,`` or a space).
CONDA_PACKAGE_NAME = re.compile(r"[A-Za-z0-9_.\-]+")


# There is no escape hatch, deliberately. An earlier revision carried
# JOBS_EXEMPT_FROM_SETUP_PYTHON, a table mapping ``(workflow, job)`` to a
# written reason. It was empty, and it is gone, because a reviewer used it to
# recreate the exact defect this file prevents: deleting build-macos.yml's
# setup-python step and adding an entry reading "artifact-packaging job; it does
# not select a Python interpreter" left the whole suite green. The two checks
# meant to hold an entry to its claim tested the entry's SHAPE and not its claim
# -- "the named job still exists" and "the named job has no setup-python step"
# are both things a hole satisfies by construction. So there is no table, and
# adding one back is not a two-line change.


def _yaml():
    """Import PyYAML, or fail loudly and by name.

    PyYAML is not declared: it arrives as a transitive of essentia-tensorflow,
    which CI installs from ``requirements-macos-arm64-py311.lock`` with
    ``--require-hashes``. That makes it exactly the kind of dependency a
    ``pytest.importorskip`` would quietly turn into a green run. So: never
    skip.
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


def stated_version_text(path=VERSION_FILE):
    """The raw contents of the AUTHORITATIVE SOURCE for the version.

    Not "the one file that states the version": ``environment.yml`` states it
    too, and assertion 5 exists precisely because it does. This is the file the
    others are checked against. Every reader goes through here so that a
    missing file fails by name rather than as a bare FileNotFoundError.

    DECODED FROM BYTES, not ``read_text``, and that is not a style choice.
    ``read_text`` opens in text mode, so universal-newline translation turns a
    CRLF file into ``"3.11\\n"`` before any caller sees it, and
    :func:`one_version_token` compares this string byte for byte. Measured:
    with ``read_text``, ``3.11\\r\\n`` on disk passed. It reddens now. pyenv
    would read the version name as ``3.11\\r``; setup-python trims the ``\\r``
    away. Two consumers, two answers, from one file.

    ``path`` is an argument only so that behaviour is reachable with a file
    this repository does not have. Reading the fixed path alone, switching
    back to ``read_text`` reddened nothing -- measured -- because the real
    file is LF and the two agree on it.
    """
    assert path.is_file(), (
        f"{VERSION_FILE_NAME} is missing. Every workflow points at it, so "
        "every job would fail -- but this guard says so first, and by name."
    )
    return path.read_bytes().decode("utf-8")


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
    reported by :func:`jobs_missing_setup_python`, which sees every job whether
    or not it has steps. Keeping that decision in one place is what stops a
    ``uses:``-only job from being silently skipped by every step-shape check
    below.
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


# ---------------------------------------------------------------------------
# Comparing a name the way the thing that consumes it compares it.
# ---------------------------------------------------------------------------
#
# Every comparison in this file is against a fixed ASCII literal, so the only
# question a comparison can get wrong is WHICH SPELLINGS THE CONSUMER TREATS AS
# EQUAL TO THAT LITERAL. Python's ``==`` and ``in`` are case sensitive. Neither
# of the two consumers below is, and this file shipped a green mutant for each:
# ``Python-Version: "3.12"`` added to a correct setup-python step left the whole
# guard at 79 passed, and a second step spelled ``uses: Actions/Setup-Python``
# is not a setup-python step to any check here.
#
# These are the two fixes of the species that has worked twice on this file --
# make the comparison equivalent to the real consumer's -- as opposed to
# enumerating another spelling, which has failed six times.


def runner_input_name(key):
    """The single input name a ``with:`` key reaches the action under.

    THE MIRRORED NORMALISATION IS ``replace(' ', '_')`` THEN UPPERCASE, and it
    is read off both ends of the wire rather than guessed:

    * actions/runner ``src/Runner.Worker/Handlers/Handler.cs`` L185 writes each
      step input into the action's environment as
      ``$"INPUT_{pair.Key?.Replace(' ', '_').ToUpperInvariant()}"``;
    * the ``getInput`` BUNDLED INTO THE PINNED ACTION ITSELF --
      ``dist/setup/index.js`` at :data:`SETUP_PYTHON_SHA`, L6034 -- reads
      ``process.env[`INPUT_${name.replace(/ /g, '_').toUpperCase()}`]``;
    * actions/runner's ``src/Sdk/WorkflowParser/workflow-v1.0.json`` says the
      same thing in prose on the ``step-with`` definition -- "The variable
      created converts input names to uppercase letters and replaces spaces
      with ``_``".

    Two earlier stages agree with it and are subsumed by it: the runner stores
    step inputs in a ``Dictionary<String, String>(StringComparer.
    OrdinalIgnoreCase)`` (``WorkflowTemplateConverter.ConvertToStepInputs``,
    L805) and checks input names against the action manifest through
    ``HashSet<string>(StringComparer.OrdinalIgnoreCase)`` (``ActionRunner.cs``
    L187 and L198) -- so a cased spelling is a VALID declared input of
    setup-python and does not even draw the "Unexpected input(s)" warning.

    That is the whole rule. There is NO trimming, so a padded key stays a
    different input; no other separator is folded, so ``python_version`` and
    ``python-version`` stay two inputs -- which is why
    :data:`INLINE_VERSION_KEYS` still lists both and still fails rather than
    guessing about either.

    Python's ``str.upper`` is Unicode FULL case mapping and
    ``ToUpperInvariant`` is the simple one; where the two differ Python folds
    MORE spellings together, never fewer. Against an ASCII literal that can
    only over-report, which is the direction this file errs in everywhere else.
    """
    return key.replace(" ", "_").upper()


def github_action_path(action_path):
    """An ``owner/repo[/subpath]`` reference, folded the way GitHub resolves it.

    MEASURED, not read, because this resolution is GitHub's rather than the
    runner's: on 2026-08-21 ``gh api repos/Actions/Setup-Python`` and
    ``gh api repos/ACTIONS/SETUP-PYTHON`` both answered
    ``"full_name": "actions/setup-python"``. So ``uses: Actions/Setup-Python@``
    runs this action, and a segment comparison that is case sensitive does not
    see it: a SECOND step spelled that way, carrying an inline version, is not
    a setup-python step to assertions 2 or 3, while assertion 1 stays satisfied
    by the correctly spelled first one.

    ``str.lower`` rather than :func:`runner_input_name`, because this is a
    different consumer with a different rule -- there are no spaces in a
    repository name and no uppercase in the literals compared against. GitHub
    draws owner and repository names from ASCII, so nothing here turns on
    Python's Unicode case mapping.

    The ``@ref`` is deliberately NOT folded. Assertion 3 compares it to one
    reviewed commit for equality, so an unexpected casing reddens; folding it
    would only widen what passes.
    """
    return action_path.lower()


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
    positive that gets this guard deleted. A fork or mirror of setup-python, on
    the other hand, is a hole -- so it fails as unrecognised rather than being
    skipped silently.

    The length check finishes what the segment comparison starts. Comparing the
    first two segments establishes a PREFIX, not an identity:
    ``actions/setup-python/not-the-root-action@<sha>`` shares the prefix and is
    a different action, because GitHub resolves a sub-path ``uses:`` to that
    directory's own action.yml, which this guard has never read. Under the
    prefix comparison it was accepted as the real thing for four rounds and the
    whole suite stayed green.

    Both comparisons are made on :func:`github_action_path`, so they are as
    case blind as GitHub's own repository lookup. Case sensitively,
    ``Actions/Setup-Python`` was neither the action nor a look-alike worth
    failing on -- it fell out of both branches and returned False.
    """
    if resolved is None:
        return False

    action_path, _ref = resolved
    segments = tuple(github_action_path(action_path).split("/"))
    if segments[:2] == SETUP_PYTHON:
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


def step_inputs(where, step):
    """``{input name: (key as written, value)}`` for one step's ``with:``.

    Keyed by :func:`runner_input_name`, so every lookup made on the result asks
    the question the action asks rather than the question Python's ``in`` asks.

    A COLLISION FAILS rather than resolving to one of the two, and both kinds
    of collision are real:

    * two keys differing only in case never run at all -- the template reader
      gathers mapping keys into ``HashSet<String>(StringComparer.
      OrdinalIgnoreCase)`` and reports ``ValueAlreadyDefined``
      (actions/runner ``TemplateReader.cs``, both ``HandleMappingWith*``
      paths), so the workflow is rejected before a job starts;
    * two keys differing by a space against an underscore are NOT duplicates
      to that reader and DO collide at ``Handler.cs`` L185, where the input
      the dictionary happens to yield last is the one the action sees. Which
      one that is, this file will not guess.

    A NON-STRING KEY FAILS for the same reason. The runner stringifies one
    (``TemplateReader`` rebuilds a non-string scalar key with
    ``nextKeyScalar.ToString()``), but .NET and PyYAML do not agree on what
    ``on:`` or ``3.11:`` becomes, and a guess here is a guess about which input
    the action received.
    """
    with_block = step.get("with")
    assert isinstance(with_block, dict), (
        f"{where} has no 'with:' mapping, so it cannot be pointing at "
        f"{VERSION_FILE_NAME}"
    )

    inputs = {}
    for key, value in with_block.items():
        assert isinstance(key, str), (
            f"{where} has a non-string 'with:' key ({key!r}); this guard "
            "compares input names as text and cannot say what the runner "
            "would call this one, so it fails rather than passing over it"
        )

        name = runner_input_name(key)
        assert name not in inputs, (
            f"{where} writes both {inputs[name][0]!r} and {key!r} in one "
            f"'with:' block. They are the single input {name!r} to the "
            "runner, so at most one of the two values reaches the action and "
            "this guard will not guess which. Delete the one that is not "
            "intended."
        )
        inputs[name] = (key, value)

    return inputs


def inline_version_inputs(where, inputs):
    """Assert no input of this step states a version inline; return them.

    ``inputs`` is passed in rather than taken from a step for the reason
    argued on :func:`conda_python_pin`: every setup-python step in this
    repository is correct, so the rejecting branch below is reachable only
    through mutated configuration. Not hypothetical -- replacing the whole
    assertion with the tautology ``assert stated is not None`` left this guard
    at 79 passed, sha256 617261a1 -> 4ccad9a8, measured 2026-08-21.
    """
    wanted = [runner_input_name(key) for key in INLINE_VERSION_KEYS]
    stated = [inputs[name] for name in wanted if name in inputs]

    assert not stated, (
        f"{where} states a Python version inline: "
        + ", ".join(f"{key}: {value!r}" for key, value in stated)
        + f". Every workflow must read {VERSION_FILE_NAME} instead, so "
        "that no two setup-python steps can disagree about the "
        "interpreter they install. Spelling the key differently does not "
        "help: the runner folds case and spaces before the action reads it, "
        "so 'Python-Version' and 'python-version' are one input."
    )
    return stated


def version_file_input(where, inputs):
    """Assert this step points ``python-version-file`` at the version file.

    ``inputs`` is passed in for the same reason as on
    :func:`inline_version_inputs`; both rejecting branches here were reachable
    only through the real workflows, which are correct.
    """
    name = runner_input_name(VERSION_FILE_INPUT)

    assert name in inputs, (
        f"{where} does not set {VERSION_FILE_INPUT}. Omitting it makes "
        "setup-python fall back to the runner's default Python with only "
        "a warning, which is the original defect arriving quietly."
    )

    _key, target = inputs[name]
    assert isinstance(target, str) and target.strip() == VERSION_FILE_NAME, (
        f"{where} points {VERSION_FILE_INPUT} at {target!r}; it must be "
        f"exactly {VERSION_FILE_NAME}, or there is more than one file "
        "claiming to hold the version"
    )
    return target


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


# The shape checks the helpers above make, driven with documents this
# repository does not have. Each is reachable only through a malformed
# workflow, so each was a rejecting branch that could be deleted outright with
# nothing going red -- the same unexercised-branch hole this file has now found
# in itself six times. The point of them is fail-closed: an unreadable shape
# must be a failure and never a quiet pass.


def test_a_workflow_with_no_jobs_mapping_is_reported():
    with pytest.raises(AssertionError, match="unrecognised workflow shape"):
        list(_jobs_of("w.yml", {"on": "push"}))


def test_a_job_that_is_not_a_mapping_is_reported():
    with pytest.raises(AssertionError, match="not a mapping; unrecognised job"):
        list(_jobs_of("w.yml", {"jobs": {"j": ["not", "a", "mapping"]}}))


def test_steps_that_are_not_a_list_are_reported():
    with pytest.raises(AssertionError, match="'steps' is not a list"):
        list(_steps_of("w.yml", "j", {"steps": {"uses": "actions/checkout@v4"}}))


def test_a_step_that_is_not_a_mapping_is_reported():
    with pytest.raises(AssertionError, match="is not a mapping"):
        list(_steps_of("w.yml", "j", {"steps": ["echo hi"]}))


def test_a_job_with_no_steps_key_yields_no_steps_rather_than_failing():
    """The one shape :func:`_steps_of` passes over, pinned as a MISS so that it
    is a stated decision. It is safe only because
    :func:`jobs_missing_setup_python` sees the job anyway, which the next test
    up the file is about."""
    assert list(_steps_of("w.yml", "j", {"uses": "./.github/workflows/o.yml"})) == []


@pytest.mark.parametrize("uses", [["actions/checkout@v4"], 3.11, "", "   "])
def test_a_uses_this_guard_cannot_read_is_reported(uses):
    with pytest.raises(AssertionError, match="non-string 'uses'"):
        _uses_ref("w::j step 0", {"uses": uses})


def test_a_run_step_has_no_uses_reference():
    assert _uses_ref("w::j step 0", {"run": "echo hi"}) is None


def test_an_unparseable_workflow_is_reported(tmp_path):
    broken = tmp_path / "broken.yml"
    broken.write_text("jobs: [unclosed\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="is not parseable YAML"):
        _parse(broken)


def test_a_workflow_that_is_not_a_mapping_is_reported(tmp_path):
    scalar = tmp_path / "scalar.yml"
    scalar.write_text("just a string\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="did not parse to a mapping"):
        _parse(scalar)


# ---------------------------------------------------------------------------
# Assertion 1: every job accounts for itself.
# ---------------------------------------------------------------------------


def jobs_missing_setup_python(name, document):
    """Every job in one workflow that does not set up Python.

    Returns a list of problem descriptions; empty means every job in this
    workflow is accounted for. Shapes this guard cannot read raise from the
    helpers above instead -- there is no third answer, no path that returns
    ``[]`` because a job was never looked at, and no argument a caller can pass
    to make a job stop being looked at.
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

    Per **job**, not per repository, and that distinction is the whole point. A
    previous revision asserted only "at least one setup-python step exists
    somewhere" plus "every step it finds is correct". Deleting the entire
    ``Set up Python`` step from ``build-macos.yml`` left valid YAML, left the
    repository-wide existence assertion satisfied by the other workflows, and
    left both per-workflow loops iterating an empty list -- the whole suite
    stayed green while that job ran ``pip install --require-hashes``,
    ``python -c`` and ``python build_app.py`` on whatever interpreter the
    runner image carried. A guard that proves a property only about the steps
    it *finds* proves nothing about the steps that are gone.

    Parametrised over the file rather than the job so that collection stays a
    glob. Parametrising per job would mean parsing YAML at collection time,
    turning a missing PyYAML into a collection error instead of the clean,
    named failure :func:`_yaml` raises.
    """
    problems = jobs_missing_setup_python(workflow.name, _parse(workflow))

    assert not problems, "\n".join(problems)


# Every branch of assertion 1 that this repository does not exercise. Its own
# jobs are all correct, so :func:`jobs_missing_setup_python` returns ``[]`` down
# its happy path and never reaches the code that reports a problem. A reporting
# path that nothing exercises can be broken without anything going red -- which
# is how the deleted-step defect survived a revision. These synthetic documents
# drive the three ways a job can fail assertion 1 through the real function.

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
    """_SYNTHETIC also holds a correct job, so this pins that the function
    reports the offending job and not merely "something was wrong"."""
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


def test_there_are_workflows_to_check():
    """The guard is only worth anything if it has something to guard."""
    assert workflow_files(), f"no workflow files under {WORKFLOW_DIR}"


# ---------------------------------------------------------------------------
# Assertions 2 and 3: how each setup-python step is written.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_no_setup_python_step_states_a_version_inline(workflow):
    """The whole point: a version stated here is a version that can drift.

    The comparison lives in :func:`inline_version_inputs` so that it is
    reachable with a document this repository does not have; see that
    function's docstring for the tautology that gutted it while this test
    stayed green.
    """
    for where, step, _ref in setup_python_steps(workflow):
        inline_version_inputs(where, step_inputs(where, step))


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_every_setup_python_step_points_at_the_version_file(workflow):
    """Uniform and unambiguous: one input, one target, no alternatives.

    ``python-version-file`` rather than omitting the input, although
    setup-python does read ``.python-version`` when nothing is supplied. The
    two differ when the file is gone: omission logs a warning and falls back to
    whatever Python the runner preinstalled, while a stated file that does not
    exist throws. Fail-closed, and it names its source in the workflow.

    ON THE ``.strip()`` BELOW -- the rule is STRIP WHERE THE CONSUMER STRIPS,
    and it is the reason :func:`conda_python_pin` does the opposite.
    setup-python reads this input as ``core.getInput('python-version-file')``
    with no options, and at the pinned commit the bundled toolkit's
    ``getInput`` ends ``return val.trim()`` unless
    ``options.trimWhitespace === false`` is passed, which setup-python does not
    pass. The action sees the trimmed string, so a padded value here is
    genuinely equivalent. That argument is also not load-bearing: if the trim
    ever went away, setup-python reaches ``fs.existsSync(versionFile)`` and
    THROWS. A padded value cannot become a silent fall-back to the runner's
    Python in either world.
    """
    for where, step, _ref in setup_python_steps(workflow):
        version_file_input(where, step_inputs(where, step))


def unpinned_setup_python_steps(refs):
    """Assert every ``{where: ref}`` is the reviewed commit; return them.

    ``refs`` is passed in for the reason argued on :func:`conda_python_pin`:
    every step in this repository is pinned correctly, so the comparison below
    was reachable only through the real workflows and could be replaced by
    ``ref != ref`` -- a constant False -- without anything going red.
    """
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
    return refs


def test_every_setup_python_step_is_pinned_to_the_reviewed_sha():
    """One reviewed commit, compared for equality; see :data:`SETUP_PYTHON_SHA`.

    All of them must equal that constant and therefore each other, for the same
    reason the Python version has one authoritative source: two pins are two
    things that can drift apart.
    """
    refs = {}
    for path in workflow_files():
        for where, _step, ref in setup_python_steps(path):
            refs[where] = ref

    unpinned_setup_python_steps(refs)


# Which strings are, and are not, the action this guard is about. Every step in
# this repository is spelled correctly, so :func:`_is_setup_python` only ever
# sees the root action here and never reaches the branches that decide anything.


def test_the_root_action_is_recognised():
    assert _is_setup_python("w::j step 0", ("actions/setup-python", "0" * 40)) is True


def test_a_sub_path_under_setup_python_is_not_the_root_action():
    """The reviewer's mutation, in isolation: a sub-path shares two segments
    with the real action and is a different action."""
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


def test_a_cased_action_reference_is_the_same_action():
    """GitHub resolves the repository case blind -- MEASURED against the API,
    see :func:`github_action_path`.

    Case sensitively, ``Actions/Setup-Python`` fell out of both branches and
    returned False: not the action, and not a look-alike worth failing on. So a
    SECOND step spelled that way, carrying an inline version beside a correctly
    spelled first step, was checked by nothing -- assertion 1 was satisfied by
    the first step and assertions 2 and 3 never saw the second.
    """
    assert _is_setup_python("w::j step 0", ("Actions/Setup-Python", "0" * 40)) is True
    assert _is_setup_python("w::j step 0", ("ACTIONS/SETUP-PYTHON", "0" * 40)) is True

    with pytest.raises(AssertionError, match="sub-path"):
        _is_setup_python("w::j step 0", ("Actions/Setup-Python/Sub", "0" * 40))

    with pytest.raises(AssertionError, match="looks like setup-python"):
        _is_setup_python("w::j step 0", ("Someone-Else/Setup-Python", "0" * 40))


# Every branch of assertions 2 and 3 that this repository does not exercise.
# Its own setup-python steps are correct, so both comparisons were reachable
# only through the real workflows: replacing the inline-version rejection with
# the tautology ``assert stated is not None`` left this guard at 79 passed,
# sha256 617261a1 -> 4ccad9a8, measured 2026-08-21.

_WHERE = "w.yml::j step 0"

# Spellings the runner delivers as one of INLINE_VERSION_KEYS and Python's
# ``in`` did not. Rows, not a rule: the rule is :func:`runner_input_name`, and
# each row is checked below to be a consequence of it rather than a new case.
CASED_INLINE_VERSION_KEYS = [
    "Python-Version",
    "PYTHON-VERSION",
    "pYtHoN-vErSiOn",
    "Python_Version",
    "python version",
    "PythonVersion",
]


@pytest.mark.parametrize("key", CASED_INLINE_VERSION_KEYS)
def test_a_cased_inline_version_input_is_refused(key):
    """The reviewer's green mutant, driven through the real comparison.

    ``Python-Version: "3.12"`` added to build-macos.yml's correct
    setup-python step left all 79 tests passing (sha256 e65d779e -> 3f0422c4,
    the parsed step genuinely carrying both that and python-version-file).
    setup-python reads ``python-version`` FIRST and gives it precedence over
    ``python-version-file`` -- ``resolveVersionInput`` at
    :data:`SETUP_PYTHON_SHA` warns and uses ``python-version`` when both are
    supplied -- so the build resolved 3.12 while this guard certified 3.11.

    Each row is checked to BE the thing it is here for before it is used,
    because a row refused for an unrelated reason passes this test while
    pinning nothing: it must NOT be one of :data:`INLINE_VERSION_KEYS`
    verbatim, or the comparison this replaced already refused it; and it must
    normalise to one of them, or refusing it is this guard inventing a rule
    instead of mirroring one. Those two together are exactly "green before,
    red now".
    """
    refused = {runner_input_name(k) for k in INLINE_VERSION_KEYS}

    assert key not in INLINE_VERSION_KEYS, (
        f"{key!r} is in INLINE_VERSION_KEYS verbatim, so the case-sensitive "
        "``in`` this replaced refused it too and the row pins nothing"
    )
    assert runner_input_name(key) in refused, (
        f"{key!r} does not reach the action as any of {INLINE_VERSION_KEYS}, "
        "so refusing it would be a rule this guard invented rather than one it "
        "mirrors"
    )

    step = {"with": {key: "3.12", VERSION_FILE_INPUT: VERSION_FILE_NAME}}

    with pytest.raises(AssertionError, match="states a Python version inline"):
        inline_version_inputs(_WHERE, step_inputs(_WHERE, step))


@pytest.mark.parametrize("key", INLINE_VERSION_KEYS)
def test_each_inline_version_spelling_is_refused(key):
    """The plain spellings, so the parametrised rows above are measured against
    a comparison that is doing something."""
    with pytest.raises(AssertionError, match="states a Python version inline"):
        inline_version_inputs(_WHERE, step_inputs(_WHERE, {"with": {key: "3.12"}}))


def test_a_cased_version_file_input_still_points_at_the_version_file():
    """The mirror image, and the half that keeps the fold honest: folding must
    not only ADD failures.

    ``Python-Version-File`` reaches setup-python as python-version-file, so a
    step spelled that way IS configured from the file and must pass. Under the
    case-sensitive lookup it failed as "does not set python-version-file" -- a
    guard crying wolf at a workflow that works, which is the mechanism that
    gets a guard weakened or deleted.
    """
    step = {"with": {"Python-Version-File": VERSION_FILE_NAME}}

    assert version_file_input(_WHERE, step_inputs(_WHERE, step)) == VERSION_FILE_NAME


def test_two_with_keys_that_are_one_input_to_the_runner_are_reported():
    """Both kinds of collision, and neither is a document to read a version
    out of: the case-only pair never runs at all (the template reader rejects
    the duplicate case blind), and the space-against-underscore pair DOES run,
    with one of the two values discarded at ``Handler.cs`` L185."""
    with pytest.raises(AssertionError, match="single input"):
        step_inputs(_WHERE, {"with": {VERSION_FILE_INPUT: VERSION_FILE_NAME,
                                      "PYTHON-VERSION-FILE": "/etc/elsewhere"}})

    with pytest.raises(AssertionError, match="single input"):
        step_inputs(_WHERE, {"with": {"python_version": "3.11",
                                      "python version": "3.12"}})


def test_a_non_string_with_key_is_reported():
    """PyYAML resolves a bare ``on:`` key to ``True``; the runner would call it
    "true". Rather than model that disagreement, this fails."""
    with pytest.raises(AssertionError, match="non-string 'with:' key"):
        step_inputs(_WHERE, {"with": {True: "3.12"}})


def test_a_step_with_no_with_block_is_reported():
    with pytest.raises(AssertionError, match="no 'with:' mapping"):
        step_inputs(_WHERE, {"uses": f"actions/setup-python@{SETUP_PYTHON_SHA}"})


def test_a_step_that_sets_no_version_file_input_is_reported():
    with pytest.raises(AssertionError, match="does not set python-version-file"):
        version_file_input(_WHERE, step_inputs(_WHERE, {"with": {"cache": "pip"}}))


def test_a_version_file_input_pointing_elsewhere_is_reported():
    step = {"with": {VERSION_FILE_INPUT: "some-other-file"}}

    with pytest.raises(AssertionError, match="points python-version-file at"):
        version_file_input(_WHERE, step_inputs(_WHERE, step))


def test_a_correctly_configured_step_passes_both_checks():
    """The other half: these must not be checks that refuse everything."""
    inputs = step_inputs(_WHERE, {"with": {VERSION_FILE_INPUT: VERSION_FILE_NAME,
                                           "cache": "pip"}})

    assert inline_version_inputs(_WHERE, inputs) == []
    assert version_file_input(_WHERE, inputs) == VERSION_FILE_NAME


def test_a_step_pinned_to_anything_but_the_reviewed_commit_is_reported():
    with pytest.raises(AssertionError, match="must be pinned to exactly"):
        unpinned_setup_python_steps({_WHERE: "v5"})


def test_no_setup_python_step_to_check_the_pin_of_is_reported():
    with pytest.raises(AssertionError, match="no setup-python step found"):
        unpinned_setup_python_steps({})


def test_correctly_pinned_steps_pass():
    refs = {_WHERE: SETUP_PYTHON_SHA}

    assert unpinned_setup_python_steps(refs) == refs


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
# gaining a marker that flips between 3.11 and 3.12 changes it, without a commit
# here. A backstop that happens to be inert today is not a backstop.
#
# WHAT USED TO BE HERE. Five revisions read the shell text looking for a bare
# version token next to the flag. It carried five admitted blind spots and a
# reviewer found another in each of the last rounds -- an interior-quoted flag
# name (``--pyth"on-version"=3.12``, which the shell glues back together before
# uv sees it), a fragment-assembled flag, a value from a job-level ``env:``, a
# variable assigned a literal two lines above the call. Every one of those is
# simply "the text differs" to a comparison against fixed text.
#
# The cost is real and is the point: a legitimate change to this command -- a
# new flag, a moved --exclude-newer date -- reddens this test and someone pastes
# the new text in. Each of those edits changes what uv resolves against or what
# the lock records, and none should land without a reviewer looking at it.

# A run block is collected -- and therefore has to match a reviewed copy -- when
# it contains any of these as a contiguous run of characters.
#
# This is SELECTION, not parsing: nothing here decides what the shell would do
# with the text, only which blocks are subject to the comparison. Three markers
# rather than one because each is a way a block can name uv's resolution target.
#
# A block that selects an interpreter without any of them is NOT collected and
# NOT covered. Deciding otherwise in general means interpreting the shell.
# Named, because an unnamed limit reads as coverage: a STEP-level ``env:``
# (collection reads ``run:`` and nothing else), a job-level or workflow-level
# ``env:``, ``requires-python`` in pyproject.toml, ``uv python install``, and a
# flag spelled so the characters never appear contiguously. The first of those
# was MEASURED on 2026-08-21 rather than reasoned about: a second step carrying
# ``env: {UV_PYTHON: "3.12"}`` beside ``run: u"v" p"ip" c"ompile" ...`` -- which
# the shell glues back into a real ``uv pip compile`` call -- was added to
# build-macos.yml, and this guard stayed green. It still does. Collecting
# ``env:`` too would close that one member and leave the rest of the list, which
# is the shape-by-shape widening that produced five of this file's revisions.
UV_RESOLUTION_MARKERS = ("uv pip compile", "--python-version", "UV_PYTHON")

# The reviewed text of every collected block, keyed by where it lives. A raw
# string, so the shell's line continuations are the characters they look like.
# Compared with ``==`` against the scalar PyYAML hands back.
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


def uv_resolution_problems(collected):
    """Compare a collected mapping against the reviewed copies kept here.

    ``collected`` is passed in rather than gathered here for the reason argued
    on :func:`conda_python_pin`: this repository's one such block is correct,
    so every reporting branch below is unreachable through the real workflows
    and loosening any of them would redden nothing. Relaxing the ``==`` to a
    substring test is the obvious way to gut this check, and on the real files
    alone it is invisible.

    Both directions matter. A collected block with no reviewed copy is a NEW
    place uv's target is chosen. A reviewed key with nothing collected means
    the step was deleted, renamed out of its job, or had every marker removed
    -- which is what a mutation moving the target elsewhere looks like from
    here.
    """
    problems = []

    for key in sorted(set(collected) - set(REVIEWED_UV_RESOLUTION_BLOCKS)):
        problems.append(
            f"{key[0]}::{key[1]} names uv's resolution target and has no "
            "reviewed copy in this file. uv resolves the dependency set FOR "
            "whatever it selects, and the lock-drift gate does not catch a "
            "wrong selection (the recompile at 3.12 is byte-identical today; "
            "see the note above). Read the block, then add it to "
            "REVIEWED_UV_RESOLUTION_BLOCKS verbatim."
        )

    for key in sorted(set(REVIEWED_UV_RESOLUTION_BLOCKS) - set(collected)):
        problems.append(
            f"no run block was collected for {key[0]}::{key[1]}, which this "
            "file has a reviewed copy of. The step was deleted, moved to "
            "another job, or no longer contains any of "
            f"{UV_RESOLUTION_MARKERS}. If uv's resolution target moved, the "
            "new block has to be reviewed and pinned here; if it is genuinely "
            "gone, delete the entry."
        )

    for key, reviewed in sorted(REVIEWED_UV_RESOLUTION_BLOCKS.items()):
        if key in collected and collected[key] != reviewed:
            problems.append(
                f"{key[0]}::{key[1]} run block differs from the reviewed copy "
                "in this file.\n--- reviewed ---\n"
                f"{reviewed}--- in the workflow ---\n{collected[key]}"
                "--- end ---\nThis block chooses the interpreter uv resolves "
                "the dependency set FOR, and the lock-drift gate does not "
                "catch a wrong choice. If the change is intended, read it and "
                "paste the new text into REVIEWED_UV_RESOLUTION_BLOCKS in the "
                "same commit."
            )

    return problems


def test_every_uv_resolution_block_matches_its_reviewed_text():
    """The blocks that choose what uv resolves against are pinned verbatim.

    Not "no literal version appears next to the flag" -- that claim needed a
    shell-text parser, and a reviewer defeated the parser in each of the last
    five rounds. This compares fixed text with ``==``: a literal version, a
    re-quoted flag, a variable assigned a literal, a moved ``--exclude-newer``
    and a deleted flag are all simply "the text differs".
    """
    collected = {}
    for path in workflow_files():
        collected.update(uv_resolution_blocks(path.name, _parse(path)))

    assert not uv_resolution_problems(collected), "\n".join(
        uv_resolution_problems(collected)
    )


# The branches of assertion 4 that this repository does not exercise: its own
# workflows are correct, so both functions above only ever walk their happy
# path, and every reporting branch was unreachable from the real files.


def test_an_unreviewed_block_is_reported():
    """A NEW place uv's resolution target is chosen."""
    problems = uv_resolution_problems({("other.yml", "j"): "uv pip compile x.in"})

    assert len(problems) == 2, problems  # unreviewed, plus the real one missing
    assert "other.yml::j" in problems[0]
    assert "no reviewed copy" in problems[0]


def test_a_reviewed_block_that_vanished_is_reported():
    """The step was deleted, or the target moved somewhere not collected."""
    problems = uv_resolution_problems({})

    assert len(problems) == 1, problems
    assert "no run block was collected" in problems[0]


@pytest.mark.parametrize(
    "edit",
    [
        ('"$PYTHON_VERSION"', "3.12"),                    # the naive literal
        ("--python-version", '"--python-version"'),       # the round-6 mutant
        ("--python-version", '--pyth"on-version"'),       # the round-7 mutant
        ("--exclude-newer 2026-08-20", "--exclude-newer 2027-01-01"),
        ("git diff --exit-code", "git diff"),             # the drift gate itself
        ("", "export UV_PYTHON=3.12\n"),                  # APPENDED, not replaced
    ],
    ids=["literal", "quoted-flag", "interior-quote", "exclude-newer",
         "drift-gate", "appended"],
)
def test_a_one_character_edit_to_a_reviewed_block_is_reported(edit):
    """Every shape the deleted shell parser missed is simply "the text differs".

    The middle two are the mutations that walked past that parser in rounds 6
    and 7 -- a quote at the end of the flag name, and a quote in the MIDDLE of
    it, which the shell glues back together before uv sees it. Neither needs
    understanding here.

    The last row APPENDS rather than replaces, and it is here because relaxing
    the comparison to ``reviewed in collected[key]`` survived every replacing
    row -- a modified copy does not contain the original either way. Only an
    addition tells the two apart, and an addition is how a second resolution
    target arrives beside a correct one.
    """
    key = ("test-macos.yml", "pytest")
    mutated = _LOCK_COMPILE_RUN.replace(*edit, 1)
    assert mutated != _LOCK_COMPILE_RUN, "this row edits nothing and pins nothing"

    problems = uv_resolution_problems({key: mutated})

    assert len(problems) == 1, problems
    assert "differs from the reviewed copy" in problems[0]


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


# ---------------------------------------------------------------------------
# Assertion 5: the local-development plane agrees with CI.
# ---------------------------------------------------------------------------


def _conda_package_name(spec):
    """The package a top-level conda dependency names, or ``None``.

    The channel prefix is stripped before the name is read, so
    ``conda-forge::python=3.12`` is recognised as a python pin. It was not, and
    that was half of a wrong pass: the pin conda would actually honour went
    unseen while a decoy elsewhere in the file was read as authoritative.

    An entry whose leading text is not a package name -- a direct package URL,
    a local path -- reports whatever leading run of name characters it starts
    with (``https``, for a URL), so it is not counted as a python entry. That
    is a limit of assertion 5's claim, stated on :func:`conda_python_pin` and
    pinned by
    :func:`test_a_direct_package_url_is_not_counted_as_a_python_entry`.
    """
    _channel, _sep, rest = spec.strip().rpartition("::")
    match = CONDA_PACKAGE_NAME.match(rest)
    return match.group(0).lower() if match else None


def python_entries_in(dependencies):
    """Every TOP-LEVEL conda dependency whose package name is ``python``.

    Top-level only. conda's ``pip:`` block is a nested mapping, and nothing
    inside it is a conda package spec, so nothing inside it can be the pin conda
    honours -- pip cannot install an interpreter for the environment it is
    running in. The previous revision flattened the nested lists into the same
    bucket as the real dependencies, so a ``conda-forge::python=3.12`` pin
    alongside a ``pip:`` entry of ``python==3.11`` passed: the decoy matched the
    expected version and the real pin was not recognised as python at all.
    Nested entries are not consulted here, not even to reject them; a pin that
    moves into one leaves zero top-level python entries, which fails below as
    "names Python 0 time(s)".
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

    return python_entries_in(
        conda_dependencies(CONDA_ENV_FILE.name, _parse(CONDA_ENV_FILE))
    )


def conda_dependencies(name, document):
    """The top-level ``dependencies`` list, or fail naming the file.

    Split out of :func:`conda_python_entries` so the shape check is reachable
    with a document this repository does not have; ``environment.yml`` is
    correct, so ``assert True`` here reddened nothing.
    """
    dependencies = document.get("dependencies")
    assert isinstance(dependencies, list) and dependencies, (
        f"{name} has no 'dependencies' list; unrecognised shape"
    )
    return dependencies


def conda_python_pin(expected, entries):
    """Assert ``entries`` pins python in the ONE accepted form.

    Returns the accepted spec; every other input raises. ``entries`` is passed
    in rather than read here because otherwise the comparison below is reachable
    only through the real ``environment.yml``, which is correct, so loosening it
    would redden nothing -- not hypothetical: relaxing this to a substring
    search left the entire suite green.

    EXACTLY ONE STRING PASSES: ``python=<the version in .python-version>``, with
    nothing before it and nothing after it. Every other spelling in
    :data:`REJECTED_PYTHON_SPECS` is legal conda and several would install the
    right interpreter; they fail anyway. This is the fourth attempt at this
    function, and the three before it tried to UNDERSTAND conda's version
    syntax, each confidently wrong about a shape nobody had enumerated. So it
    implements no part of ``MatchSpec``: it identifies which entries are about
    python (leading name only, channel stripped), demands exactly one, and
    compares that one to a fixed string.

    THE SCOPE OF THE COUNT, stated because a reviewer's mutation turned on it:
    "exactly one" counts entries whose LEADING PACKAGE NAME is ``python``. An
    entry that constrains Python without being spelled that way -- a direct
    ``https://.../python-3.12.3-...conda`` URL, a local path -- is not counted
    and does not fail here; adding one beside ``python=3.11`` leaves this green,
    and was measured doing so. This is NOT the claim that ``environment.yml``
    carries no other Python constraint. It is the claim that it carries exactly
    one *named* one and that it reads ``python=<version>``. The broader claim
    needs conda's own ``MatchSpec``, which is not a test dependency.

    The comparison is against the RAW scalar. It used to ``.strip()`` first, and
    ``- " python=3.11 "`` -- valid YAML -- therefore passed, while conda refuses
    that spec outright: measured on conda 23.1.0, ``MatchSpec`` raises
    ``InvalidMatchSpec: no package name found in ' python=3.11 '``. A guard that
    accepts exactly one literal has to compare the literal. Identification
    (:func:`_conda_package_name`) still strips, on purpose, so a padded pin is
    FOUND and reported as wrongly spelled rather than counted as absent.
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

    Every way this can fail raises inside :func:`conda_python_pin`, naming the
    file, the spec it found and the one spec it accepts. There is no returned
    value left to compare: "is it the right version" and "is it a shape this
    guard actually understood" are the same question here, which is what stops
    a misread spec from being compared against the right number and passing.
    """
    conda_python_pin(stated_version_text().strip(), conda_python_entries())


# The branches that were wrong, driven through the real helpers. environment.yml
# is correct, so python_entries_in() only ever sees plain top-level strings here
# and never reaches either branch -- both were wrong for four rounds without
# anything going red, which is what an unexercised branch buys you.


def test_a_pip_block_is_not_read_as_a_conda_python_pin():
    """The decoy half of the reviewer's mutation, in isolation."""
    dependencies = ["numpy>=1.20.0", {"pip": ["python==3.11", "essentia-tensorflow"]}]

    assert python_entries_in(dependencies) == []


def test_a_channel_prefixed_python_is_recognised_as_python():
    """The unseen-real-pin half: before this, the entry conda would actually
    honour was not recognised as a python entry at all, so the count came out
    at zero-plus-a-decoy instead of one."""
    assert _conda_package_name("conda-forge::python=3.12") == "python"
    assert python_entries_in(["conda-forge::python=3.12"]) == ["conda-forge::python=3.12"]


def test_a_conda_dependency_this_guard_cannot_read_is_reported():
    """A nested list, a number: not a spec string and not the ``pip:`` mapping.
    Reachable only through an environment.yml this repository does not have."""
    with pytest.raises(AssertionError, match="does not recognise this shape"):
        python_entries_in(["python=3.11", ["nested", "list"]])

    with pytest.raises(AssertionError, match="does not recognise this shape"):
        python_entries_in([3.11])


@pytest.mark.parametrize(
    "document",
    [{"name": "coco"}, {"dependencies": []}, {"dependencies": "python=3.11"}],
    ids=["absent", "empty", "not-a-list"],
)
def test_a_conda_document_with_no_dependencies_list_is_reported(document):
    with pytest.raises(AssertionError, match="no 'dependencies' list"):
        conda_dependencies("environment.yml", document)


def test_a_package_merely_starting_with_python_is_not_the_python_pin():
    """The false positive that would get this deleted: real conda environments
    carry python-dateutil, pythonocc-core and friends."""
    dependencies = ["python-dateutil>=2.8", "pythonocc-core", "python.app"]

    assert python_entries_in(dependencies) == []


def test_a_direct_package_url_is_not_counted_as_a_python_entry():
    """The limit of assertion 5, pinned as a MISS so it is a stated decision
    and not a surprise.

    A reviewer added this line beside ``python=3.11`` in the real
    ``environment.yml``, giving it two Python dependencies at two versions, and
    the suite stayed green. The leading run of package-name characters is
    ``https``, so the entry is not a python entry to this file and the count
    stays at one. A later change that starts seeing such entries reddens here,
    and whoever makes it updates the narrowed claim on
    :func:`conda_python_pin` in the same commit.
    """
    url = (
        "https://conda.anaconda.org/conda-forge/osx-arm64/"
        "python-3.12.3-h4a7b5fc_0_cpython.conda"
    )

    assert _conda_package_name(url) == "https"
    assert python_entries_in(["python=3.11", url]) == ["python=3.11"]


def test_both_halves_of_the_reviewer_mutation_together_leave_one_wrong_pin():
    """End to end on the exact document that passed: one recognised entry, and
    it is the one conda honours -- so the comparison is made against 3.12 and
    fails, instead of being made against the decoy's 3.11."""
    dependencies = ["conda-forge::python=3.12", {"pip": ["python==3.11"]}]

    assert python_entries_in(dependencies) == ["conda-forge::python=3.12"]


# Every spec below names python and several install the right interpreter.
# Exactly one of them passes. This needs its own test: environment.yml is
# spelled correctly, so the comparison is never reached with anything else, and
# relaxing it to a substring search left the suite green.
#
# What conda does with the last four was MEASURED (conda 23.1.0,
# conda.models.match_spec.MatchSpec) rather than assumed, because they do not
# behave alike: ' python=3.11 ' and ' python=3.11' raise InvalidMatchSpec;
# 'python=3.11 ' is ACCEPTED and parsed as python=3.11; '\tpython=3.11' parses
# WITHOUT error into a spec whose package name is "\tpython", which no channel
# has, so it fails at solve time as a package-not-found. All four are refused
# here anyway, and that is the case for accepting one literal instead of
# modelling the grammar: it did not need to know which conda tolerates.

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
    " python=3.11 ",            # surrounding whitespace -- conda rejects
    " python=3.11",             # leading only -- conda rejects
    "python=3.11 ",             # trailing only -- conda ACCEPTS; refused here
    "\tpython=3.11",            # a tab -- a package named "\tpython"
]


@pytest.mark.parametrize("spec", REJECTED_PYTHON_SPECS)
def test_only_the_exactly_accepted_spec_passes(spec):
    with pytest.raises(AssertionError):
        conda_python_pin("3.11", [spec])


def test_a_quoted_padded_pin_is_identified_and_then_rejected():
    """The asymmetry this rests on, stated as a test.

    Identification is tolerant so that a badly spelled pin is still FOUND --
    otherwise a padded entry would count as zero python entries and the failure
    would read "names Python 0 time(s)", pointing at a missing pin rather than
    at the one that is right there. The comparison is exact, because the
    accepted string is the one conda accepts.
    """
    assert python_entries_in([" python=3.11 "]) == [" python=3.11 "]

    with pytest.raises(AssertionError, match="pins Python as"):
        conda_python_pin("3.11", [" python=3.11 "])


def test_the_accepted_spec_passes():
    """The other half: this must not be a check that rejects everything."""
    assert conda_python_pin("3.11", ["python=3.11"]) == "python=3.11"


def test_the_accepted_spec_tracks_the_stated_version():
    """``accepted`` is built from the argument, not hard-coded, so a bump of
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

    ``raw`` is passed in rather than read from disk here, for the reason argued
    on :func:`conda_python_pin`: this repository's ``.python-version`` is
    correct, so every rejecting branch below is unreachable through the real
    file and loosening any of them reddens nothing. Not hypothetical for this
    check -- with :data:`VERSION_TOKEN` written as ``\d`` it accepted a version
    spelled in ARABIC-INDIC digits, and the only test that could have caught it
    was this one, reading a file that does not contain them.

    THE BYTE COMPARISON IS STRICTER THAN EITHER CONSUMER, deliberately, and a
    departure from the STRIP WHERE THE CONSUMER STRIPS rule argued on
    :func:`test_every_setup_python_step_points_at_the_version_file`. There, the
    subject is a value a human typed into a workflow, where refusing a spelling
    the consumer accepts is a check crying wolf. Here it is a file with one job
    and one correct content, which is not a matter of taste: ``echo 3.11 >
    .python-version`` produces it and this repository's file already is it,
    byte for byte.

    The consumers also disagree about it in a way that makes exactly one line
    the only spelling both accept. setup-python does not read it line by line:
    at the pinned commit ``getVersionInputFromPlainFile`` is
    ``fs.readFileSync(versionFile, 'utf8').trim()`` returning ``[version]`` --
    the WHOLE file, trimmed, as ONE version string, so a second line becomes the
    single nonsense version ``"3.11\n3.12"``. pyenv would read two. The
    predecessor of this check filtered blank lines out before counting them, so
    ``"\n3.11\n\n"`` -- three physical lines -- passed a check whose name said
    one line; the whole content is compared now.
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
        "is stricter than either requires; see this function's docstring for "
        "why that is the right trade for this particular file."
    )
    return version


# Every one of these is a version to Python's ``\d`` and to nothing else in the
# chain. The name of each character is spelled out because the glyphs are the
# entire point and are not readable at a glance in a diff.
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
    proved applied by sha256 and reverted byte-identical. The mixed rows matter
    too: ``coerce("3.١١")`` is not null, it is ``3.0.0``, so that spelling does
    not even fail honestly.

    Each row is checked to BE the thing it is here to be before it is used,
    because a row refused for some unrelated reason -- a stray letter, a typo --
    passes this test while pinning nothing at all, silently. So: the row must be
    a version to the ``\d`` this replaced, and must not be ASCII. Those two
    together are exactly "green before, red now".
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


@pytest.mark.parametrize(
    "raw",
    [
        "3.11",           # no trailing newline at all
        "3.11\n\n",       # a blank second line
        "\n3.11\n",       # a blank first line
        " 3.11 \n",       # padded
        "3.11\r\n",       # CRLF -- pyenv reads the name as '3.11\r'
        "\t3.11\n",       # a leading tab
    ],
    ids=["no-newline", "blank-second-line", "blank-first-line", "padded",
         "crlf", "leading-tab"],
)
def test_a_content_that_only_trims_to_a_version_is_refused(raw):
    """The second assertion of :func:`one_version_token`, driven on its own.

    Every row here TRIMS to ``3.11``, so the first assertion accepts all of
    them and only the byte comparison refuses them. Without this, relaxing
    that comparison to ``raw.strip() == version`` reddens nothing -- measured:
    the whole file stayed green under exactly that edit, which is the same
    unexercised-branch hole this file has now found in itself four times.

    Both consumers would accept several of these. The argument for refusing
    them anyway is on :func:`one_version_token`.
    """
    assert VERSION_TOKEN.match(raw.strip()), (
        f"the {raw!r} row does not trim to a version token, so it would be "
        "refused by the first assertion too and pins nothing"
    )

    with pytest.raises(AssertionError, match="the one accepted content is"):
        one_version_token(raw)


def test_an_ascii_version_still_passes():
    """The other half: this must not be a check that refuses everything."""
    assert one_version_token("3.11\n") == "3.11"
    assert one_version_token("3.11.9\n") == "3.11.9"
    assert one_version_token("3\n") == "3"


def test_a_trailing_newline_is_not_itself_part_of_a_version_token():
    r"""``^...$`` matched a token with a newline glued on, because ``$`` also
    matches immediately before one. The caller strips first, so nothing reached
    it that way; it is anchored ``\A``/``\Z`` now regardless."""
    assert VERSION_TOKEN.match("3.11")
    assert not VERSION_TOKEN.match("3.11\n")


def test_a_missing_version_file_is_reported_by_name(tmp_path):
    """:func:`stated_version_text` exists so this fails by name rather than as
    a bare FileNotFoundError, and that branch is unreachable through the real
    file -- which is there."""
    with pytest.raises(AssertionError, match="is missing"):
        stated_version_text(tmp_path / VERSION_FILE_NAME)


def test_the_version_file_is_read_as_raw_bytes(tmp_path):
    """No universal-newline translation between the disk and the comparison.

    Written as a file rather than asserted about the reader's source, because
    what matters is the bytes that come back. A CRLF file must arrive with its
    carriage return intact; under ``read_text`` it arrives as ``"3.11\\n"``
    and :func:`one_version_token` cannot tell it from a correct file.
    """
    crlf = tmp_path / VERSION_FILE_NAME
    crlf.write_bytes(b"3.11\r\n")

    assert stated_version_text(crlf) == "3.11\r\n"

    with pytest.raises(AssertionError, match="the one accepted content is"):
        one_version_token(stated_version_text(crlf))


def test_the_version_file_holds_exactly_one_version():
    """The real file, through the real check. The argument for comparing whole
    bytes rather than a trimmed copy is on :func:`one_version_token`, and the
    argument for decoding them ourselves is on :func:`stated_version_text`."""
    one_version_token(stated_version_text())
