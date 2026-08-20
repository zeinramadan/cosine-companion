"""Guard: every ordinary CI job contains an unconditional
``actions/setup-python`` step configured from ``.python-version``, and no
``actions/setup-python`` step states a version of its own inline.

The scope of that second clause -- SETUP-PYTHON STEPS, not workflows -- is
load-bearing, and it is narrower than it was. This sentence used to read "no
workflow states a version of its own inline", which measurement contradicts:
``uv python install 3.12 --default`` inside a ``run:`` block is a version
stated inline in a workflow, it is admitted green two paragraphs below, and
the old wording claimed it away. Workflows may state versions inline in
``run:`` text. What this file reads out of that text is one LEXICAL
ARRANGEMENT -- a bare version token in the word immediately adjacent to the
characters ``--python-version`` (assertion 4) -- and nothing else.

That is deliberately weaker than "a literal handed to uv", which is what this
sentence used to say, and the difference is measurable. A block may hand uv a
literal without ever placing one next to the flag:

    PYTHON_VERSION="$(cat .python-version)"
    ACTING_PYTHON_VERSION=3.12
    uv pip compile --python-version "$ACTING_PYTHON_VERSION" ...

uv resolves for 3.12. The word next to the flag is a variable, so assertion 4
sees nothing; the block mentions ``.python-version``, so the second check is
satisfied too; and the lock the mutant produces is byte-identical, so the
drift gate accepts it. Measured, not reasoned: applied to the real
``test-macos.yml``, every test in this file passed. Reading that block
correctly means knowing what ``ACTING_PYTHON_VERSION`` holds, which is the
shell-interpretation treadmill that cost this PR family four wrong answers,
so it is pinned as a miss rather than fixed --
:func:`test_a_variable_assigned_a_literal_in_the_same_block_is_not_seen`.

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
truth are gone. One file is the SOURCE of the version -- not the only file
that states it, which is a different and false claim, contradicted twenty
lines below by ``environment.yml`` and by this file's own assertion 5. Every
workflow points at the source instead of restating it (assertions 1-3);
``environment.yml`` restates it in one fixed spelling and is checked to equal
it (assertion 5). Two workflows cannot disagree about a version that neither
of them states -- which is the defect described next, and is the one thing
here that is actually mechanised. They can still disagree about a version
either of them states in ``run:`` text; see KNOWN BLIND SPOTS.

The defect this exists to prevent is measured, not remembered, and the
measurement is sharper than the "for months" framing this paragraph used to
carry. ``build-macos.yml`` has stated 3.11 since 2025-10-05. There was no
test workflow at all until 2026-08-18, when ``test-macos.yml`` was created
stating 3.10 (47d8152) -- the day this repository got its first tests. It was
corrected to 3.11 two days later (8c1c0be). So CI and the build disagreed for
TWO DAYS, and that is the stronger fact rather than the weaker one: the
divergence arrived in the same commit as the CI that was supposed to notice
it, and nothing noticed. It surfaced only because a compiled-in Unicode digit
table generated from the *test* interpreter disagreed with the *shipped* one.

``environment.yml`` is where the same defect ran long. It has pinned
``python=3.10`` since 2026-01-02 (ab5be5b) while the app shipped 3.11 that
entire time -- seven and a half months in which a contributor's conda
environment was a different interpreter from the one anything was verified
on, and nothing compared the two. This PR is the commit that changes it.

All three agree as of this commit -- ``.python-version``, the workflows that
point at it, and ``environment.yml``. So both bugs are dormant. Neither was
PREVENTED, though, and that is the difference this file is about: each of
those files independently stated its own version, and no check compared any
two of them.

Four earlier rounds tried to *detect* divergence by working out which Python
each workflow uses. Every one shipped a confident wrong answer on a
counterexample (flow mappings, escaped keys, block-scalar decoys,
``python-version-file``), and every fix was "teach it one more Actions shape".
That apparatus is gone. **This file does not determine which Python anything
uses.**

What it asserts is narrower than "exactly one file states a version and
everything else points at it", because that sentence -- which is what this
paragraph used to say -- is contradicted by a file in this repository.
``environment.yml`` restates the version literally, as ``python=3.11``, and it
has to: conda takes a literal in the spec and cannot be pointed at
``.python-version``. Two files state the version.

The accurate shape is ONE SOURCE AND ONE CHECKED RESTATEMENT.
``.python-version`` is the source. Every setup-python step points at it rather
than restating it (assertions 1-3). ``environment.yml`` restates it, in one
fixed spelling, and assertion 5 compares that restatement against the source
character for character -- so it cannot drift without reddening, which is the
property the deleted absolute was reaching for. What is ruled out is an
UNCHECKED second statement of the version, not a second statement. See the
second paragraph above for what all of this leaves uncovered.

WHAT THIS FILE ASSERTS
----------------------
1. Every *ordinary* job -- a job with a ``steps:`` list -- in every workflow
   contains an unconditional setup-python step reading ``.python-version``.
   There is no exemption table and no way to opt a job out.
2. No setup-python step states a version inline.
3. Every setup-python step is pinned to a full commit SHA, and all of them to
   the *same* one.
4. No ``run:`` block places a bare version token in the word IMMEDIATELY
   ADJACENT to ``--python-version`` -- the next whitespace-separated word, or
   the value glued on with ``=``, with surrounding quotes taken off the flag
   half and the value half independently, so ``"--python-version"=3.12`` reads
   the same as ``--python-version 3.12`` -- and any block
   containing that flag also mentions ``.python-version``. That is the whole
   invariant, and it is a statement about characters, not about what uv
   receives: a literal that reaches uv through a variable, a fragment-built
   flag, or a job-level ``env:`` satisfies it. uv resolves the dependency set
   FOR that flag, so a literal there is a second source of truth that only
   shows up as a wrong resolution -- this catches the shape someone writes by
   hand, not the shape someone writes to get past it. It is the one assertion
   here that reads shell text rather than parsed structure, it is much the
   weakest of the six, and the lock-drift gate in ``test-macos.yml`` does NOT
   back it up -- a recompile at 3.12 was measured byte-identical to the
   committed lock. Both the measurement and the shapes this assertion cannot
   see are recorded on :func:`uv_python_version_problems`, next to the code.
   That list has 5 entries, of which 3 have an executable test pinning the miss
   and 2 are documented only. This sentence used to say "each has an executable
   test pinning it green", which was false, and which the comment sitting above
   those pins in this same file already contradicted -- two sentences each
   plausible alone and impossible together, which is a shape no sweep for
   unsupported absolutes can see, because neither is unsupported on its own.
   Neither number is remembered now:
   :func:`test_the_blind_spot_accounting_is_checked_not_remembered` counts the
   entries in the code and renders both sentences from that count. It then
   looks for each rendered sentence AT THE SITE THAT IS SUPPOSED TO CARRY IT
   -- this numbered item, read off the module's own ``__doc__``, and the
   comment block located directly above ``PINNED_BLIND_SPOTS`` -- rather than
   in the file's text as a whole. Searching the whole text was itself a
   decoy-shaped check: a copy of either sentence in any comment, docstring or
   string literal anywhere in these 1600 lines satisfied it while both real
   sites said the opposite number, measured green.
5. ``environment.yml`` pins conda to the same version, in the single
   spelling ``python=<that version>`` and no other.
6. ``.python-version`` holds exactly one bare version token AND NOTHING
   ELSE: its content must equal that token plus one newline, byte for byte.
   That is stricter than either consumer requires, deliberately; the argument
   is at :func:`test_the_version_file_holds_exactly_one_version`.

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

Assertions 1-3 are keyed on the *parsed step*, never on a substring.
``test-macos.yml`` contains the text ``python-version`` in places that are not
setup-python inputs (the ``uv pip compile`` flag and the
``--custom-compile-command`` string that records it). A text search for a
setup-python input reddens on a completely correct tree, and a check that
cries wolf gets weakened or deleted -- which is the mechanism that produced
this whole defect family. Parsing also means the shapes that defeated rounds 5
and 6 need no special handling at all: ``python-version:``,
``"python-version":`` and ``{python-version: "3.10"}`` are the same dict key
once PyYAML is done.

Assertion 4 is the exception, and it is an exception because its subject is
different: a ``run:`` block is a shell command, and PyYAML parses it to one
opaque string. There is no structure under it to key on. So that assertion
reads text -- deliberately as a SUBSTRING and word adjacency, never as a
grammar. It does not decide what the shell will do; it reports which
characters sit next to which. The distinction matters because the previous
attempt did model the shell, badly: it required a separator immediately after
the flag name, so ``"--python-version" 3.12`` -- which the shell unquotes and
hands straight to uv -- matched nothing and passed.

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

import ast
import io
import re
import tokenize
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
#
# ASCII DIGITS SPELLED OUT, NEVER ``\d``. Python's ``\d`` matches every
# character in Unicode category Nd, so it matched ``٣.١١`` -- ARABIC-INDIC THREE,
# ONE, ONE. With that in ``.python-version`` and ``python=٣.١١`` in
# ``environment.yml`` the entire repository suite was green: 971 passed, 25
# skipped, both mutations proved applied by sha256. It is not a version
# anything downstream can use. actions/setup-python's version handling is
# JavaScript, where ``\d`` is ASCII-only with or without the ``u`` flag, so
# ``pythonVersionToSemantic`` passes the string through untouched and semver
# receives it raw -- MEASURED on semver 6.3.1 and 7.7.4:
# ``coerce("٣.١١")`` is null, ``validRange("٣.١١")`` is null, and
# ``satisfies("3.11.9", "٣.١١")`` is false, so no release in the manifest
# matches and ``useCpythonVersion`` reaches its ``was not found`` throw. A
# guard that accepts a version its own consumers cannot parse is not checking
# the thing its name says. Refused by :func:`one_version_token`, pinned by
# :func:`test_a_version_written_in_non_ascii_digits_is_refused`.
#
# ANCHORED ``\A``/``\Z``, NOT ``^``/``$``. ``$`` also matches immediately
# before a trailing newline, so ``^\d+(?:\.\d+)*$`` accepted ``"3.11\n"`` as
# a bare token -- measured. Both callers strip before they get here, so
# nothing reaches it with one today; that is the argument for closing it now
# rather than after a caller stops stripping.
VERSION_TOKEN = re.compile(r"\A[0-9]+(?:\.[0-9]+)*\Z")

# A full-length git commit SHA, which is the only ref that cannot move.
# ``\A``/``\Z`` for the reason given above: under ``^...$`` a ref of forty hex
# characters followed by a newline matched. ``_uses_ref`` strips the ref, so
# nothing reaches this with one today.
COMMIT_SHA = re.compile(r"\A[0-9a-f]{40}\Z")

# The flag as PLAIN TEXT, matched with ``in``. It was a regex --
# ``--python-version[=\s]+(\S+)`` -- which required a space or an ``=``
# immediately after the flag name and therefore missed
# ``"--python-version" 3.12``: the shell strips those quotes and uv receives
# the literal, while the regex saw a ``"`` where it demanded a separator and
# matched nothing at all. Re-quoting the flag AT ITS ENDS cannot dodge a
# substring, because ``"--python-version"`` still contains the characters.
# Re-quoting it in the MIDDLE does dodge it, and this said otherwise:
# ``--pyth"on-version"`` is a different run of characters, and the shell glues
# it back together before uv sees it. MEASURED in zsh and bash --
# ``set -- uv pip compile --pyth"on-version"=3.12 reqs.in`` gives argv
# ``<--python-version=3.12>`` in both, while ``in`` finds nothing. That miss is
# deliberate and pinned; see
# :func:`test_a_quote_inside_the_flag_name_is_not_seen`. See
# :func:`uv_python_version_problems` for what is done with this constant and
# for what it still cannot see.
UV_PYTHON_VERSION_FLAG = "--python-version"


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
    """The raw contents of the AUTHORITATIVE SOURCE for the version.

    Not "the one file that states the version", which is what this line used
    to say: ``environment.yml`` states it too, as ``python=3.11``, and
    assertion 5 exists precisely because it does. This is the file the others
    are checked against.

    Every reader goes through here so that a missing file fails by name in
    all of them, rather than one of them reporting a bare FileNotFoundError
    traceback that says nothing about what the file is for.

    DECODED FROM BYTES, not ``read_text``, and that is not a style choice.
    ``read_text`` opens in text mode, so Python's universal-newline
    translation turns a CRLF file into ``"3.11\n"`` before any caller sees
    it. :func:`test_the_version_file_holds_exactly_one_version` compares this
    string against the one accepted content byte for byte; through
    ``read_text`` that comparison cannot see a CRLF file at all, and a claim
    about bytes that is checked against a translated copy is exactly the
    species of overclaim this file keeps finding in itself. Measured: with
    ``read_text``, ``3.11\r\n`` on disk passed. It reddens now. pyenv would
    read the version name as ``3.11\r``; setup-python trims the ``\r`` away.
    Two consumers, two answers, from one file.
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
            f"Use exactly {'/'.join(SETUP_PYTHON)}@<40-character sha>."
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
            "that no two setup-python steps can disagree about the "
            "interpreter they install. (Workflows can still disagree in "
            "'run:' text -- 'uv python install 3.12 --default' is an admitted "
            "blind spot; see KNOWN BLIND SPOTS at the top of this file.)"
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
    commit this repository pins -- a26af69be951a213d495a4c3e4e4022e16d87065 --
    the bundled toolkit's ``getInput`` ends ``return val.trim()`` unless
    ``options.trimWhitespace === false`` is passed, which setup-python does
    not pass. The action sees the trimmed string, so a padded value here is
    genuinely equivalent. conda is the opposite: it takes the spec verbatim,
    which is why :func:`conda_python_pin` compares the raw scalar.

    That argument is also not load-bearing, which is the point of assertion 2
    demanding this input at all. If the trim ever went away, setup-python
    reaches ``fs.existsSync(versionFile)`` and THROWS "The specified python
    version file at: ... doesn't exist". A padded value cannot become a silent
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


def test_every_setup_python_step_is_pinned_to_one_agreed_sha():
    """The design rests on one behaviour of one version of this action.

    With ``python-version-file`` named, a *missing* file makes setup-python
    throw instead of silently falling back to the runner's Python. That is
    what makes assertion 1 worth anything, and it is a property of the
    action's source at a particular commit -- not of the name ``v5``, which
    GitHub documents as a tag it may move at any time. A moved tag would
    change the behaviour this file depends on without changing a byte of this
    repository.

    All five must agree, for the same reason the Python version has one
    authoritative source: two pins are two things that can drift apart.
    ("Lives in one file" is what this said, and it is the same overclaim
    corrected elsewhere in this file -- environment.yml states the version
    too. One SOURCE; restatements get checked against it.)
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
# Assertion 4: no shell block resolves against a literal version.
# ---------------------------------------------------------------------------


def _unquote(text):
    """``text`` with ``'`` and ``"`` characters removed FROM ITS TWO ENDS.

    Not a shell unquoter, and it must never become one: it deletes quote
    characters at the ends of a piece of text and looks at nothing else.
    Interior quotes survive, which is exactly why ``--pyth"on-version"=3.12``
    stays invisible to this file -- recorded as such in the blind-spot list
    on :func:`uv_python_version_problems`.

    It exists as a named function because the same normalisation has to be
    applied in two places that are easy to get out of step: to each
    whitespace-separated word, and to each half of a word glued together with
    ``=``. Applying it in only the first place is what let
    ``"--python-version"=3.12`` past this guard until round 6.
    """
    return text.strip("'\"")


def _shell_words(run):
    """``run`` split on whitespace, each word stripped of surrounding quotes.

    This is NOT a shell parser and must never become one. It does not know
    about expansion, comments, escapes, line continuations, heredocs or word
    splitting; it splits on whitespace and hands each piece to
    :func:`_unquote`. Four rounds of this PR family died trying to work out
    what a construct would MEAN at runtime. This decides nothing about
    meaning: it reports which characters sit next to which.
    """
    return [_unquote(word) for word in run.split()]


def literal_python_versions_passed_to_uv(run):
    """Every bare version literal sitting where uv reads ``--python-version``.

    Both spellings: ``--python-version 3.12`` (the value is the next word) and
    ``--python-version=3.12`` (the value is glued on). Quotes AT THE ENDS of
    either half change nothing, because those come off first -- which is the
    whole repair, since ``"--python-version" 3.12`` is exactly the shape that
    walked past the previous regex.

    ONLY AT THE ENDS. This said "quoting either the flag or the value changes
    nothing", and that sentence is false: ``--pyth"on-version"=3.12`` carries
    a quote in the middle of the flag NAME, and the shell hands uv
    ``--python-version=3.12`` all the same -- measured in zsh and bash, argv
    ``<--python-version=3.12>`` in both, and this function returns ``[]``.
    :func:`_unquote` takes quotes off the two ends of a word and off the two
    ends of each half of a glued word, and off nothing else, so the characters
    it compares are simply not the flag. That miss is bullet 1 of the
    blind-spot list on :func:`uv_python_version_problems`; it is pinned twice,
    at that function's level by
    :func:`test_a_flag_assembled_from_fragments_is_not_seen` and at this one's
    by :func:`test_a_quote_inside_the_flag_name_is_not_seen`.

    Making the sentence true instead of narrowing it was considered and
    rejected on measurement. Deleting EVERY quote character from a word buys
    the interior-quote catch and costs two false positives, on the one check
    in this file whose design note says a false positive is what gets a check
    weakened or deleted. Measured in zsh and bash:
    ``--python-version \"3.12\"`` hands uv ``<"3.12">``, quotes included,
    which uv rejects -- and the repair would report it as a literal; and
    ``"--pyth'on-version"=3.12`` hands uv ``<--pyth'on-version=3.12>``, which
    is not this flag at all -- and the repair would report that too. Getting
    all three right is a shell unquoter, which is the apparatus that shipped
    four confident wrong answers in earlier rounds of this PR.

    BOTH HALVES OF A GLUED WORD ARE UNQUOTED, not just the value, and that is
    the round-6 repair. ``"--python-version"=3.12`` is one shell word; the
    shell hands uv ``--python-version=3.12`` (verified, not reasoned:
    ``zsh -c 'set -- "--python-version"=3.12; printf "<%s>" "$1"'`` prints
    ``<--python-version=3.12>``). Splitting on whitespace and unquoting the
    WORD leaves ``--python-version"=3.12``, because the trailing character is
    a digit and the quote sits in the middle. Partitioning on ``=`` then gives
    a flag half of ``--python-version"``, which is not equal to the flag, so
    the literal was missed while the docstring claimed quotes were stripped
    either way. Unquoting each half after the partition costs no understanding
    of the shell whatsoever -- it decides nothing about what the shell will do,
    it normalises characters before a comparison this function already makes,
    the same species of change as dropping a ``.strip()`` that hid a padded
    conda spec.

    A word that is not a bare version token is not judged. ``"$PYTHON_VERSION"``
    strips to ``$PYTHON_VERSION``, which :data:`VERSION_TOKEN` does not match,
    so it is left alone -- this function never tries to work out what a
    variable holds.

    :data:`VERSION_TOKEN` is ASCII digits only, which narrows this function
    too: ``--python-version ٣.١٢`` is no longer reported. That is not a new
    blind spot and it is deliberately NOT in the list below, because the list
    is ways a block can hand uv a version it will USE. uv parses this flag as
    a PEP 440 version and will not accept a non-ASCII digit, so such a block
    fails the step outright rather than resolving quietly for the wrong
    interpreter. The narrowing drops a false positive, not a catch. Pinned by
    :func:`test_a_non_ascii_digit_next_to_the_flag_is_not_reported_as_a_literal`.
    """
    literals = []
    words = _shell_words(run)

    for index, word in enumerate(words):
        flag, glued, value = word.partition("=")
        if _unquote(flag) != UV_PYTHON_VERSION_FLAG:
            continue

        if not glued:
            value = words[index + 1] if index + 1 < len(words) else ""

        value = _unquote(value)
        if VERSION_TOKEN.match(value):
            literals.append(value)

    return literals


def uv_python_version_problems(where, run):
    """The two LEXICAL problems this guard reads out of one ``run:`` block.

    Not "every way this block can hand uv a wrong version" -- that is what
    this line used to claim, and a reviewer's mutant disproved it (see the
    variable-indirection entry below). These are the two things checked, and
    they are the whole of it:

    1. a bare version token in the word immediately adjacent to
       ``--python-version``;
    2. the flag appearing in a block that never names ``.python-version``.

    Returns a list of problem descriptions. EMPTY MEANS NEITHER OF THOSE TWO
    FIRED -- it does not mean the block resolves for the version in the file,
    and the blind-spot list below is the list of ways it can be empty and
    wrong.

    THE STRUCTURAL BACKSTOP FOR THIS ASSERTION DOES NOT EXIST -- MEASURED
    --------------------------------------------------------------------
    The strongest argument for deleting this check is that ``test-macos.yml``
    already recompiles the lock and runs ``git diff --exit-code``, so a wrong
    ``--python-version`` would resolve a different dependency set and the
    committed lock would stop matching -- a real recompile catching it with no
    text matching anywhere. That argument was measured on 2026-08-20 rather
    than believed. The job's own command was run with the flag set to 3.12,
    output to a temporary path, and the committed lock never used as a target:

        MACOSX_DEPLOYMENT_TARGET=15.2 uv pip compile --python-version 3.12 \
          --python-platform aarch64-apple-darwin --prerelease explicit \
          --exclude-newer 2026-08-20 --build-constraint build-constraints.txt \
          --generate-hashes requirements-macos-arm64-py311.in -o <temp>

    The result was BYTE-IDENTICAL to the committed lock. Both are sha256
    5845ce4030f7a487ea8fb00d15a245d27703d59f70f1fdfe878e7fd316213278. The
    resolved body does not depend on the flag at all for this dependency set;
    only the header comment does, and only because
    ``--custom-compile-command`` echoes the value verbatim. So the mutation
    that matters -- the ACTING flag becomes a literal while
    ``--custom-compile-command`` still expands ``$PYTHON_VERSION`` -- produces
    a lock the drift gate accepts, ``git diff --exit-code`` exits 0, and CI is
    green with the dependency set resolved for the wrong interpreter.

    That invariance is an accident of today's dependency set, not a property
    of the design: it holds because nothing currently resolved carries a
    marker that flips between 3.11 and 3.12. One dependency gaining one would
    change it, in either direction, without a commit here. A backstop that
    happens to be inert today is not a backstop, so this check stays.

    WHAT IT STILL CANNOT SEE -- here, next to the claim
    ---------------------------------------------------
    * The flag spelled so the characters ``--python-version`` never appear
      as one contiguous run: ``F=--python; uv pip compile ${F}-version 3.12``,
      and equally ``--pyth"on-version"=3.12``, which the shell glues back
      together but which carries a quote in the MIDDLE of the flag name --
      :func:`_unquote` takes quotes off the two ends of a word and off the two
      halves of a glued word, and off nothing else. Neither check below
      triggers on either, because neither is looking for a concept: both are
      looking for that literal run of characters, and the early return in this
      function never even gets past ``UV_PYTHON_VERSION_FLAG not in run``.
    * A value that arrives from outside this block: a job-level or
      workflow-level ``env:``, a ``$GITHUB_ENV`` write in an earlier step, or
      an input to a reusable workflow. The word here is ``"$SOMETHING"``,
      which is not a version token, and the block may well mention
      ``.python-version`` for an unrelated reason and satisfy the second
      check too.
    * A value assigned a literal INSIDE THIS SAME BLOCK, a few words away::

          PYTHON_VERSION="$(cat .python-version)"
          ACTING_PYTHON_VERSION=3.12
          uv pip compile --python-version "$ACTING_PYTHON_VERSION" ...

      This is the sharpest of the misses, because everything that would make
      a reader trust the block is present and honest-looking: the file IS
      read, the flag IS derived from a variable, and ``.python-version`` IS
      mentioned. uv resolves for 3.12. Applied to ``test-macos.yml`` this was
      measured green -- every test in this file passed, mutation proved
      applied by sha and reverted byte-identical -- and the recompiled lock
      was byte-identical too, so the drift gate accepted it as well. Closing it means
      tracking assignments, which is a shell interpreter; the deliberate
      choice is to miss it and say so. Pinned by
      :func:`test_a_variable_assigned_a_literal_in_the_same_block_is_not_seen`.
    * A value glued together by the shell -- ``--python-version 3"."12`` --
      strips to ``3"."12``, which is not a version token.
    * Any OTHER flag that selects a resolution target: ``uv pip compile -p``
      / ``--python``, the ``UV_PYTHON`` environment variable,
      ``requires-python`` in pyproject.toml. Only this one flag is read.
      Adding the others is not obviously wrong, but ``--python`` is a prefix
      of both ``--python-version`` and ``--python-platform``, so it cannot be
      matched as a substring without firing on the correct line, and that is
      the false positive that gets a check deleted.
    """
    problems = []

    if UV_PYTHON_VERSION_FLAG not in run:
        return problems

    literals = literal_python_versions_passed_to_uv(run)
    if literals:
        problems.append(
            f"{where} passes a literal Python version to "
            f"{UV_PYTHON_VERSION_FLAG}: "
            + ", ".join(repr(v) for v in literals)
            + f". uv resolves the dependency set FOR that version, so a "
            "literal here is a second source of truth that never announces "
            "itself -- and the lock-drift gate does not catch it either (the "
            "recompile at 3.12 is byte-identical today; see this function's "
            f"docstring). Read {VERSION_FILE_NAME} in the shell and pass the "
            "result instead."
        )

    if VERSION_FILE_NAME not in run:
        problems.append(
            f"{where} uses {UV_PYTHON_VERSION_FLAG} but never mentions "
            f"{VERSION_FILE_NAME}, so whatever it passes is not derived from "
            "the authoritative source for the version. Set it from "
            f'\'PYTHON_VERSION="$(cat {VERSION_FILE_NAME})"\' in the same '
            "block."
        )

    return problems


@pytest.mark.parametrize("workflow", workflow_files(), ids=lambda p: p.name)
def test_no_run_block_puts_a_literal_version_next_to_the_uv_flag(workflow):
    """``uv pip compile --python-version`` chooses the interpreter uv resolves
    *for*, so a literal there is a second source of truth whose divergence
    never announces itself: a bump of ``.python-version`` would leave the
    dependency set resolved for the old Python and installed on the new one.

    The name is deliberately about ADJACENCY and not about "passing a
    literal". It used to be ``test_no_run_block_passes_a_literal_python_version``
    and that name was a claim the function does not make: a block can pass uv
    a literal through a variable assigned two lines above and this test stays
    green. See :func:`uv_python_version_problems` for the measured list.

    Both occurrences in ``test-macos.yml`` matter -- the flag uv acts on and
    the copy inside ``--custom-compile-command`` that is written verbatim into
    the lock header. The shell expands both before uv sees either, so the
    generated lock stays byte-identical.
    """
    document = _parse(workflow)
    problems = []

    for job_name, job in _jobs_of(workflow.name, document):
        for index, step in _steps_of(workflow.name, job_name, job):
            run = step.get("run")
            if not isinstance(run, str):
                continue

            where = _where(workflow.name, job_name, index, step)
            problems.extend(uv_python_version_problems(where, run))

    assert not problems, "\n".join(problems)


# The branches of assertion 4, driven through the real functions.
#
# test-macos.yml is written correctly, so on this repository
# :func:`uv_python_version_problems` only ever walks its happy path. Every
# reporting branch below was unreachable from the real workflows, and the
# quoting shape in the parametrised test walked straight past the regex that
# used to live here.

_DERIVED_RUN = (
    'PYTHON_VERSION="$(cat .python-version)"\n'
    'uv pip compile --python-version "$PYTHON_VERSION" reqs.in -o reqs.lock\n'
)


def test_the_shape_test_macos_actually_uses_is_accepted():
    """Not a check that rejects everything: the real derived spelling passes."""
    assert uv_python_version_problems("w::j step 0", _DERIVED_RUN) == []


def test_a_run_block_that_never_mentions_the_flag_is_left_alone():
    assert uv_python_version_problems("w::j step 0", "python -m pytest -q") == []


@pytest.mark.parametrize(
    "fragment",
    [
        "--python-version 3.12",
        '--python-version "3.12"',
        "--python-version '3.12'",
        '"--python-version" 3.12',          # the reviewer's mutation
        "'--python-version' 3.12",
        '"--python-version" "3.12"',
        "--python-version=3.12",
        '"--python-version=3.12"',
        '"--python-version"=3.12',        # the round-6 reviewer mutation
        '"--python-version"="3.12"',
        "'--python-version'=3.12",
        '--python-version="3.12"',
        '--python-version\t3.12',
        "--python-version  3.12",
    ],
    ids=lambda f: f.replace(" ", "_"),
)
def test_a_literal_is_found_however_the_ends_of_the_word_are_quoted(fragment):
    """The repair for the third green mutant.

    The name used to be ``..._however_the_shell_quotes_it``, which claimed
    every quoting the shell accepts and is not what any row below tests.
    ``--pyth"on-version"=3.12`` is a quoting the shell accepts, it is glued
    back into this exact flag before uv sees it, and it returns ``[]``. Every
    row here quotes only the ENDS of the word, or the ends of one half of a
    word glued with ``=``, and that is what the name says now. The boundary
    itself is the test directly below.

    The previous regex demanded a space or ``=`` immediately after the flag
    name, so a quote character there hid the literal completely. Quotes come
    off the ENDS of the words first now, which costs no understanding of the
    shell: the literal is either the next word or glued on with ``=``.

    The four glued-and-quoted rows were added in round 6, when a reviewer
    showed that ``"--python-version"=3.12`` -- which this file's own
    assertion 4 described as covered -- returned ``[]``. A quote between the
    flag and the ``=`` survived splitting on whitespace, so the flag half of
    the partition still carried it. Both halves are unquoted now.
    """
    assert literal_python_versions_passed_to_uv(
        f"uv pip compile {fragment} reqs.in"
    ) == ["3.12"]


@pytest.mark.parametrize(
    "fragment",
    [
        '--pyth"on-version"=3.12',
        '--pyth"on-version" 3.12',
        '--python-ver"sion"=3.12',
    ],
    ids=lambda f: f.replace(" ", "_"),
)
def test_a_quote_inside_the_flag_name_is_not_seen(fragment):
    """The boundary of the test above, pinned as a MISS rather than fixed.

    The shell glues each of these back into this exact flag -- MEASURED, zsh
    and bash agree: argv is ``<--python-version=3.12>`` or
    ``<--python-version> <3.12>``. This function returns ``[]`` for all three,
    and :func:`uv_python_version_problems` returns no problems at all for
    them, because its ``UV_PYTHON_VERSION_FLAG not in run`` early return fires
    first: the characters never appear as one contiguous run, so the
    mentions-the-version-file check does not run either.

    This is bullet 1 of the blind-spot list, which
    :data:`PINNED_BLIND_SPOTS` already declares pinned by
    :func:`test_a_flag_assembled_from_fragments_is_not_seen`. It is restated
    here, at the level of the function whose docstring made the false claim
    and beside the rows that claim bounds. It is deliberately NOT a second
    entry in that tuple: the tuple is one name per bullet, and adding a name
    without adding a bullet is the arithmetic
    :func:`test_the_blind_spot_accounting_is_checked_not_remembered` exists to
    keep honest.

    Only the flag NAME is interior-quoted here. A quote interior to the VALUE
    -- ``--python-version 3".12"`` -- is a different bullet, number 4, which
    :data:`DOCUMENTED_ONLY_BLIND_SPOTS` declares documented only. Asserting
    that one executably would make that declaration false while the totals
    still added up, which is exactly the shape round 6 found.
    """
    assert literal_python_versions_passed_to_uv(
        f"uv pip compile {fragment} reqs.in"
    ) == []


def test_the_quoted_flag_mutation_is_reported_and_names_the_literal():
    run = 'PYTHON_VERSION="$(cat .python-version)"\nuv pip compile "--python-version" 3.12 reqs.in'
    problems = uv_python_version_problems("w::j step 0", run)

    assert len(problems) == 1, problems
    assert "'3.12'" in problems[0]


def test_a_flag_that_never_references_the_version_file_is_reported():
    problems = uv_python_version_problems(
        "w::j step 0", 'uv pip compile --python-version "$SOMETHING" reqs.in'
    )

    assert len(problems) == 1, problems
    assert VERSION_FILE_NAME in problems[0]


def test_a_variable_is_never_resolved_to_a_literal():
    """This function does not try to work out what a variable holds, and this
    pins that it does not start: ``$PYTHON_VERSION`` is not a version token."""
    assert literal_python_versions_passed_to_uv(_DERIVED_RUN) == []


# 3 of the 5 blind-spot entries in :func:`uv_python_version_problems` are
# PINNED AS MISSES below, in the order they appear there; the other 2 are
# documented only. They are pinned, not fixed, and kept here as executable
# statements so the prose cannot quietly drift from the code. If a later
# change makes any of them visible, that test reddens and whoever made the
# change corrects the list, assertion 4's wording and the module docstring in
# the same commit.
#
# The asymmetry is not an oversight to be tidied away. The two documented-only
# entries -- a value glued together by the shell, and any OTHER flag that
# selects a resolution target -- are facts about which characters the check
# looks at, provable by reading the five lines of
# :func:`literal_python_versions_passed_to_uv`, whereas the three below each
# turn on a construct a reader could plausibly believe is handled.
#
# The two tuples below exist because the module docstring said "each has an
# executable test pinning it green" while this comment said two of them were
# not pinned. Both sentences are rendered from these tuples now, and
# :func:`test_the_blind_spot_accounting_is_checked_not_remembered` fails if
# either stops matching.

PINNED_BLIND_SPOTS = (
    "test_a_flag_assembled_from_fragments_is_not_seen",
    "test_a_value_arriving_from_outside_the_block_is_not_seen",
    "test_a_variable_assigned_a_literal_in_the_same_block_is_not_seen",
)

DOCUMENTED_ONLY_BLIND_SPOTS = (
    "A value glued together by the shell",
    "Any OTHER flag that selects a resolution target",
)


def _flatten(text):
    """``text`` as a single line: strip each line, drop the empty ones, join.

    The sentences checked below are wrapped prose. Where the wrapper happened
    to break a line is not the thing being pinned, so it is normalised away
    before the comparison rather than being written into it.
    """
    return " ".join(
        part for part in (line.strip() for line in text.splitlines()) if part
    )


def _docstring_section(doc, heading):
    """The body lines of one underlined section of ``doc``.

    A section is a line followed by a rule of ``-`` characters, and it runs
    until the next such line. Scoping to a section is what stops a ``* ``
    bullet added to some OTHER part of the same docstring from being counted
    as a blind-spot entry -- which would let a bullet be deleted from the list
    and re-added elsewhere with the total, and therefore this whole check,
    unchanged.
    """
    lines = doc.splitlines()

    def underlined(index):
        below = lines[index + 1].strip() if index + 1 < len(lines) else ""
        return len(below) >= 3 and set(below) == {"-"}

    headings = [index for index in range(len(lines)) if underlined(index)]
    for position, index in enumerate(headings):
        if lines[index].strip().startswith(heading):
            end = (
                headings[position + 1]
                if position + 1 < len(headings)
                else len(lines)
            )
            return lines[index + 2 : end]

    raise AssertionError(
        f"the docstring being read has no {heading!r} section. It was renamed "
        "or removed, which stops everything counted out of it from meaning "
        "anything, so this fails rather than counting zero."
    )


def _numbered_item(doc, number):
    """One numbered item of the WHAT THIS FILE ASSERTS list, as one line.

    The item is delimited by the next ``N. `` at the same level, so the
    sentence checked against it cannot be satisfied by a copy sitting in a
    different assertion's paragraph.
    """
    collected = []
    for line in _docstring_section(doc, "WHAT THIS FILE ASSERTS"):
        stripped = line.strip()
        if collected and re.match(r"\A[0-9]+\. ", stripped):
            break
        if collected or stripped.startswith(f"{number}. "):
            collected.append(line)

    assert collected, (
        f"there is no item {number} in the WHAT THIS FILE ASSERTS list. The "
        "sentence this test renders has nowhere to live, so it fails rather "
        "than looking for it somewhere else."
    )
    return _flatten("\n".join(collected))


def _comment_block_above(name):
    """The ``#`` comment block directly above the assignment to ``name``.

    LOCATED, not searched for. The statement is found through :mod:`ast` and
    the comments through :mod:`tokenize` -- column 0 only, so a trailing
    comment on a line of code is not part of a block -- and the block is the
    contiguous run of them immediately above it, blank lines between the two
    allowed. Nothing else in the file can answer for this comment.
    """
    source = Path(__file__).read_text(encoding="utf-8")

    target = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            target = node
            break

    assert target is not None, (
        f"there is no top-level assignment to {name} in this module, so the "
        "comment that is supposed to sit above it cannot be located. A "
        "renamed target stops this check finding anything, which must fail "
        "rather than pass."
    )

    own_line = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and token.start[1] == 0:
            own_line[token.start[0]] = token.string.removeprefix("#").strip()

    lines = source.splitlines()
    row = target.lineno - 1
    while row >= 1 and not lines[row - 1].strip():
        row -= 1

    block = []
    while row in own_line:
        block.append(own_line[row])
        row -= 1
    block.reverse()

    assert block, (
        f"there is no comment block directly above the assignment to {name}. "
        "The sentence this test renders is supposed to be there; if the "
        "comment moved, the sentence moved with it and this check no longer "
        "knows where to look."
    )
    return " ".join(part for part in block if part)


def test_the_blind_spot_accounting_is_checked_not_remembered():
    """The pinned/documented split is derived from the code, not recalled.

    Round 6 found the module docstring claiming every blind spot had an
    executable pin and the comment above these tests saying two did not.
    Each sentence was plausible on its own; they were 900 lines apart and
    jointly impossible. Counting absolutes one at a time cannot catch that,
    because neither sentence is an unsupported absolute -- it is the PAIR
    that is wrong.

    So both sentences are now rendered from the same two tuples and the same
    count taken off :func:`uv_python_version_problems`. They cannot disagree
    with each other, and neither can disagree with the number of entries in
    the list they describe.

    EACH SENTENCE IS LOOKED FOR AT ITS OWN SITE, which is the round-7 repair.
    Both were looked for in the whole file, flattened -- and a check that
    accepts the words ANYWHERE accepts a decoy. Measured: with both real sites
    edited to say "5 of 5 ... 0 documented only" and both true sentences
    pasted into an unrelated comment block 460 lines away, this file was
    green, 79 passed. So sentence one is read out of assertion 4's numbered
    item in ``__doc__`` and sentence two out of the comment block located
    above :data:`PINNED_BLIND_SPOTS`, and a copy anywhere else answers for
    neither.

    WHAT THIS DOES NOT CATCH, said here rather than discovered later: moving
    an entry from one tuple to the other without touching the code it
    describes. The totals still add up, the sentences still render the same
    way, and this test still passes. It pins the ARITHMETIC and the names,
    not the claim that a given bullet is the one a given test pins.
    """
    entries = [
        line
        for line in _docstring_section(
            uv_python_version_problems.__doc__, "WHAT IT STILL CANNOT SEE"
        )
        if line.strip().startswith("* ")
    ]
    pinned = len(PINNED_BLIND_SPOTS)
    documented = len(DOCUMENTED_ONLY_BLIND_SPOTS)

    assert len(entries) == pinned + documented, (
        f"the blind-spot list in uv_python_version_problems has "
        f"{len(entries)} entries, but {pinned} are declared pinned and "
        f"{documented} documented-only. Whoever added or removed a bullet "
        "updates PINNED_BLIND_SPOTS or DOCUMENTED_ONLY_BLIND_SPOTS and the "
        "two sentences that quote them."
    )

    for name in PINNED_BLIND_SPOTS:
        assert callable(globals().get(name)), (
            f"PINNED_BLIND_SPOTS names {name!r}, which is not a function in "
            "this module. A pin that was renamed or deleted stops pinning "
            "anything, silently, which is the whole failure this guards."
        )

    for phrase in DOCUMENTED_ONLY_BLIND_SPOTS:
        assert phrase in uv_python_version_problems.__doc__, (
            f"DOCUMENTED_ONLY_BLIND_SPOTS names {phrase!r}, which no longer "
            "appears in the blind-spot list it is supposed to be describing."
        )

    total = len(entries)
    sited = (
        (
            f"That list has {total} entries, of which {pinned} have an executable "
            f"test pinning the miss and {documented} are documented only.",
            _numbered_item(__doc__, 4),
            "assertion 4 in this module's docstring",
        ),
        (
            f"{pinned} of the {total} blind-spot entries in "
            f":func:`uv_python_version_problems` are PINNED AS MISSES below",
            _comment_block_above("PINNED_BLIND_SPOTS"),
            "the comment block directly above PINNED_BLIND_SPOTS",
        ),
    )
    for sentence, site, where in sited:
        assert sentence in site, (
            f"{where} no longer contains, verbatim, {sentence!r}. It reads: "
            f"{site!r}. The module docstring and the comment above the pins "
            "both state the split; they contradicted each other before this "
            "test existed, so they are rendered from the same numbers now -- "
            "and each is checked WHERE IT LIVES, because a copy of the "
            "sentence somewhere else in this file is not this site saying it."
        )


def test_a_flag_assembled_from_fragments_is_not_seen():
    """Blind spot 1: the characters never appear as one contiguous run.

    Two spellings, because round 6's repair to :func:`_unquote` made the
    boundary worth stating: quotes come off the two ends of a word and off
    the two halves of a glued word. A quote in the MIDDLE of the flag name is
    still a different run of characters, so it is still invisible -- for the
    same reason ``${F}-version`` is.
    """
    fragments = "F=--python\nuv pip compile ${F}-version 3.12 reqs.in"
    interior_quote = 'uv pip compile --pyth"on-version"=3.12 reqs.in'

    assert uv_python_version_problems("w::j step 0", fragments) == []
    assert uv_python_version_problems("w::j step 0", interior_quote) == []


def test_a_value_arriving_from_outside_the_block_is_not_seen():
    run = (
        'echo "resolving for $PYTHON_VERSION"  # a job-level env: sets this,\n'
        "# and nothing here compares it against .python-version\n"
        'uv pip compile --python-version "$PYTHON_VERSION" reqs.in'
    )

    assert uv_python_version_problems("w::j step 0", run) == []


def test_a_variable_assigned_a_literal_in_the_same_block_is_not_seen():
    """The reviewer's round-5 mutant, pinned as a MISS.

    Every signal a reader would use to trust this block is present: the file
    is read, the flag takes a variable rather than a literal, and
    ``.python-version`` appears. uv still resolves for 3.12, because the
    variable next to the flag is a DIFFERENT one, assigned a literal two
    lines up. Applied to the real ``test-macos.yml`` this was measured green
    -- the whole file passed -- and the lock it produces is byte-identical,
    so the drift gate does not catch it either.

    Seeing it requires tracking what an assignment put in a variable -- a
    shell interpreter, which is exactly the apparatus that shipped four
    confident wrong answers in earlier rounds of this PR. So it is admitted,
    here, executably. If a later change makes this visible, this test reddens
    and whoever made the change updates assertion 4's wording, the blind-spot
    list in :func:`uv_python_version_problems`, and the module docstring in
    the same commit -- which is the entire point of pinning it.
    """
    run = (
        'PYTHON_VERSION="$(cat .python-version)"\n'
        "ACTING_PYTHON_VERSION=3.12\n"
        'uv pip compile --python-version "$ACTING_PYTHON_VERSION" reqs.in'
    )

    assert uv_python_version_problems("w::j step 0", run) == []


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

    The comparison is against the RAW scalar. It used to ``.strip()`` first,
    and ``- " python=3.11 "`` -- valid YAML -- therefore passed, while conda
    refuses that spec outright: measured on conda 23.1.0, ``MatchSpec``
    raises ``InvalidMatchSpec: no package name found in ' python=3.11 '``. A
    guard that accepts exactly one literal has to compare the literal. Identification (:func:`_conda_package_name`) still strips, on
    purpose, so a padded pin is FOUND and reported as wrongly spelled rather
    than counted as absent. Other ``.strip()`` calls in this file are correct
    because their consumer strips too; the rule and the evidence are in
    :func:`test_every_setup_python_step_points_at_the_version_file`.
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

    It has pinned 3.10 since 2026-01-02 (ab5be5b) while the app shipped 3.11
    the whole time -- seven and a half months, against the two days CI and the
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
    # grammar: it did not need to know which of these conda tolerates. A
    # revision that tried to be exactly as strict as conda would have had to
    # get all four right, and the three before this one got fewer than that.
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
    argued at length on :func:`conda_python_pin`: this repository's
    ``.python-version`` is correct, so every rejecting branch below is
    unreachable through the real file and loosening any of them reddens
    nothing. That is not hypothetical for this particular check. With
    :data:`VERSION_TOKEN` written as ``\d`` it accepted a version spelled in
    ARABIC-INDIC digits, and the only test that could have caught it was this
    one, reading a file that does not contain them.
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
    r"""The reviewer's second green mutant, driven through the real check.

    ``.python-version`` holding ``٣.١١`` and ``environment.yml`` holding
    ``python=٣.١١`` left the WHOLE REPOSITORY suite green -- 971 passed, 25
    skipped, both mutations proved applied by sha256 and reverted
    byte-identical. Every character above is Unicode category Nd, which is
    what Python's ``\d`` means and is not what any consumer of this file
    means. The mixed rows matter too: ``coerce("3.١١")`` is not null, it is
    ``3.0.0``, so that spelling does not even fail honestly.

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
    matches immediately before one. Both callers strip first, so nothing
    reached it that way; it is anchored ``\A``/``\Z`` now regardless."""
    assert VERSION_TOKEN.match("3.11")
    assert not VERSION_TOKEN.match("3.11\n")
    assert not COMMIT_SHA.match("0" * 40 + "\n")


def test_a_non_ascii_digit_next_to_the_flag_is_not_reported_as_a_literal():
    """The one place the ASCII narrowing REMOVES a report, pinned so it is a
    decision and not a surprise. uv parses ``--python-version`` as a PEP 440
    version and refuses a non-ASCII digit, so this shape fails the step rather
    than resolving quietly for another interpreter -- which is why it is not
    in the blind-spot list."""
    assert literal_python_versions_passed_to_uv(
        "uv pip compile --python-version ٣.١٢ reqs.in"
    ) == []


def test_the_version_file_exists():
    assert stated_version_text() is not None


def test_the_version_file_holds_exactly_one_version():
    """One version, one line -- and as of round 6 the test means it literally.

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

    The two assertions live on :func:`one_version_token` so that they can be
    driven with content this repository's file does not have; see there.

    THIS IS STRICTER THAN EITHER CONSUMER, and that is a deliberate departure
    from the rule argued at length in
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
    measured -- that claim would be the same unsupported absolute this file
    keeps finding in itself. The trade does not need it. Being wrong about an
    editor costs one red test whose message names the expected bytes, which is
    a one-line correction; the alternative cost a test whose name said one
    line while it accepted three. That gap is what a reviewer found, so it is
    closed by making the check match the name rather than by softening the
    name.
    """
    one_version_token(stated_version_text())
