r"""`format.parseIntegerStrictly` against the function it claims to reproduce.

Why this file exists
--------------------
Inventory :501 and :962 both hang a dialog off a bare ``int()`` raising
ValueError, so "is this an integer" is a question CPython answers and the
frontend has to give the same answer. The helper's docstring said so from the
start; its implementation was ``/^[+-]?\\d+$/``, which is JavaScript's answer.
The two disagree on real input:

* ``int("1_0")`` is 10 and the regex refused it;
* ``int()`` accepts every Unicode decimal digit, and the regex accepted only
  ``0-9`` - so an Arabic keyboard's ten was "not a valid number for total
  tracks" in the browser and a 10-track set in Tkinter.

A hand-written table of cases would have missed both, because both are things
you have to already know to write down. So the oracle here is ``int()`` itself,
run over a corpus derived from ``int()`` itself: **every Unicode decimal digit
there is**, and **every character it strips from the ends of its argument**. If
JavaScript and Python disagree about any code point, or about any of the grammar
around it, this fails and names the input.

ONE DIRECTION IS NOT ENOUGH, AND THE FIRST VERSION OF THIS FILE ONLY HAD ONE
---------------------------------------------------------------------------
The corpus above is derived from ``unicodedata``, so it can only ever contain
digits PYTHON knows. That shows every Python digit is accepted and can never
show that JavaScript's extras are refused - and the helper delegated to
``\p{Nd}``, which resolves against the Unicode tables of whichever runtime
evaluates it. Those version independently from CPython's:

    CPython 3.11        unicodedata 14.0    660 Nd code points
    node 20.20 / ICU 78 Unicode 17.0        770 Nd code points

so 110 code points - Kawi, Nag Mundari, Kirat Rai and nine other blocks - were
digits to the browser and ``ValueError`` to ``int()``. A Kawi ten parsed as 10
in the field and raised in Python. Both ``Total Tracks`` (:501) and the anchor
``Position`` control (:962) reach it, so both accepted a value the Tkinter tab
refuses with a dialog.

``format.js`` now carries CPython's table instead of delegating, and this file
checks it in BOTH directions: every code point the helper accepts is one this
interpreter calls ``Nd`` with the same value, and every code point THIS NODE
calls ``Nd`` and the table does not is refused - alone and inside a number.

WHICH CPYTHON. THIS IS THE PART ROUND 3 GOT WRONG
-------------------------------------------------
A compiled-in table is exactly one Unicode version, so "CPython's table" is an
incomplete sentence until it names an interpreter. Round 3 generated it from
the one that runs the TESTS and the app ships on a different one:

    .github/workflows/test-macos.yml    python 3.10  ->  unicodedata 13.0.0
    .github/workflows/build-*.yml       python 3.11  ->  unicodedata 14.0.0

Measured on real interpreters, not read off a changelog:

    3.10.18   13.0.0   650 Nd   int("\U00016AC1\U00016AC0")  ValueError
    3.11.14   14.0.0   660 Nd   int("\U00016AC1\U00016AC0")  == 10

So the shipped parser refused ten Tangsa code points that the ``int()`` frozen
into the same bundle reads as digits: round 3 closed 120 false acceptances by
opening ten false REFUSALS, in the configuration users actually run. Its
``test_the_table_is_pinned_to_the_test_interpreter_not_the_build_one`` went
green BECAUSE the two disagreed, which is a test asserting a defect. Both are
gone. The table is generated from the interpreter every ``build-*`` workflow
freezes, and the module exports ``PYTHON_UNICODE_VERSION`` saying which.

THE PROPERTY THAT BLOCKS SHIPPING, AND WHY NOTHING BRIDGES IT ANY MORE
----------------------------------------------------------------------
*The shipped parser must not disagree with the shipped interpreter, in
membership OR in value.* The oracle for that sentence is the shipped
interpreter, and there is exactly one way to consult it: run the suite on it.

Rounds 3 and 4 both tried the other way. CI set up 3.10 and the app ships 3.11,
so this file carried a MEASURED record of the difference - ten Tangsa code
points - and excused the parser for accepting them. Round 3's defect was that
the record excused their ABSENCE too, so a table that dropped them while still
declaring Unicode 14.0.0 passed a green 3.10 suite. Round 4 closed that half,
and the same defect came straight back one dimension over: the record pinned
WHICH code points and never their VALUES, and ``unicodedata.decimal`` cannot be
asked about a character this build has never heard of. Splitting the Tangsa run
in two -

    [0x16ac0, 0x16ac9]  ->  [0x16ac0, 0x16ac0], [0x16ac1, 0x16ac9]

- leaves membership identical, makes ``parseIntegerStrictly`` answer 0 for the
Tangsa ten the shipped ``int()`` answers 10 for, and passed all eleven tests on
3.10. Measured in this worktree, not argued.

That is not two bugs. It is one shape, twice: every fix added another recorded
fact about an interpreter that is not present, and each such fact is
unverifiable on exactly the interpreter where it is load-bearing. A third
dimension was already queued - the extras never entered the multi-character
grammar corpus, because a corpus derived from THIS ``unicodedata`` cannot
contain them - and a fourth would have followed it.

So the record is gone and nothing replaces it. The comparison is exact, in one
code path, on every interpreter:

* every digit the running interpreter calls decimal is accepted with the same
  VALUE, and nothing else is accepted at all;
* and where the running interpreter is not the one the table declares, this
  file FAILS rather than certify what it cannot see.

That second line is the whole design. A 3.10 run does not get a green suite and
an allowance; it gets one named failure saying parity with the shipped
interpreter was not proved here and naming the interpreter that proves it. An
interpreter that cannot see the property does not get to certify it - which is
also why there is no ``pytest.skip`` and no ``if os.environ["CI"]`` here. A
skip exits zero, and an environment sniff is the same fail-open shape the
workflow reader below had to be made strict to remove.

The cost is real and it is the smaller half: until
``.github/workflows/test-macos.yml`` names the interpreter the builds freeze,
this one test is red on CI and on any developer's 3.10. That red IS the
mismatch. Aligning the two makes every run a total proof and requires no change
here.

The other half of the property fails separately and so is checked separately:
that the table is DECLARED for the interpreter every build workflow freezes -
``test_the_digit_table_targets_the_interpreter_the_app_ships_on``, with the
reader under it pinned by
``test_the_shipped_version_is_read_from_the_build_workflows`` and
``test_every_workflow_names_exactly_one_python_the_reader_understands``.

WHAT IT DOES NOT CHECK
----------------------
Magnitude. Python's integers are unbounded and JavaScript's arrive as a
float64, so the corpus stops well inside ``Number.MAX_SAFE_INTEGER``. That
limit is documented on the helper and is fifteen orders of magnitude past
``MAX_SET_TRACKS``; it is a real difference and it is not one this can close.

Nor does it check any interpreter that neither runs the suite nor is named by a
build workflow. A table generated for 3.11 says nothing about what 3.13 would
do, and this file does not pretend otherwise: moving a build workflow to an
unmeasured Python fails with an instruction to measure it.
"""

import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parent / "js" / "parse_integer_driver.mjs"
SURVEY_DRIVER = Path(__file__).resolve().parent / "js" / "unicode_digits_driver.mjs"
WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

#: Same floor as the behavioural suites: `node --test` and ESM top-level await.
MINIMUM_NODE_MAJOR = 18

#: ``unicodedata.unidata_version`` for each CPython minor this project is built
#: or tested with. MEASURED, one real interpreter at a time - never read off a
#: changelog, because mis-stating exactly this mapping is the defect this
#: section exists to stop. A minor that is not here is a hard failure with an
#: instruction to measure it, not a guess put in its place.
MEASURED_UNICODE_VERSION = {
    "3.10": "13.0.0",  # measured: CPython 3.10.18, 650 Nd code points
    "3.11": "14.0.0",  # measured: CPython 3.11.14, 660 Nd code points
}




def _node():
    return shutil.which("node")


def _node_major(executable):
    finished = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=30
    )
    return int(finished.stdout.strip().lstrip("v").split(".")[0])


def _characters_int_strips():
    """Every code point ``int()`` ignores at the ends of its argument.

    DERIVED, not listed. The digits below already came from ``unicodedata``,
    while the whitespace was a hand-written tuple - so the half of this
    function that cannot be guessed was being checked against a guess.

    ``int()`` does not use ``str.isspace()``, which is the guess a reader would
    make: ``"\x1c".isspace()`` is True and ``int("\x1c10")`` raises. Prefix AND
    suffix both have to parse to ten, which is what separates whitespace from
    the two other things that parse as a prefix - a sign (``int("10+")``
    raises) and a digit (``int("100")`` is a hundred).
    """
    stripped = []
    for code in range(sys.maxunicode + 1):
        character = chr(code)
        try:
            if int(character + "10") == 10 and int("10" + character) == 10:
                stripped.append(character)
        except ValueError:
            pass
    return stripped


def _unicode_decimal_digits():
    """Every code point Python calls a decimal digit, as characters.

    Derived from `unicodedata`, not from a list: a list would pin the Unicode
    version this was written against, and the point of the check is that the two
    runtimes agree about whatever set they each have.
    """
    return [
        chr(code)
        for code in range(sys.maxunicode + 1)
        if unicodedata.category(chr(code)) == "Nd"
    ]


def _corpus(node_only_digits=()):
    """Inputs where the two languages could plausibly disagree, plus the ones
    where they obviously do not.

    ``node_only_digits`` is the half a Python-derived corpus cannot produce:
    characters THIS node calls a decimal digit and this interpreter does not.
    Empty when called without them, which is what the size guard below uses.
    """
    cases = [
        # The plain ones, and the JavaScript-flavoured answers Python refuses.
        "10",
        "0",
        "007",
        "-2",
        "+3",
        "10.0",
        "3.9",
        "0x10",
        "1e3",
        "3 apples",
        "",
        "   ",
        "-",
        "+",
        "nan",
        "Infinity",
        # Underscores: single, between digits, and every way of getting that
        # wrong. `int("1_0")` is 10; the other four raise.
        "1_0",
        "1_0_0",
        "_10",
        "10_",
        "1__0",
        "+1_0",
        "-1_0",
        "+_10",
        "_",
        "1_",
    ]

    # Surrounding whitespace: every character `int()` strips, derived from
    # `int()`, plus four it does NOT strip that a reader would expect it to.
    # U+FEFF is stripped by `String.prototype.trim()` and U+0085 is not, which
    # is the pair that separates the two languages; U+180E and U+200B look like
    # spaces and are not; U+001C is `str.isspace()` and is not `int()`.
    for space in _characters_int_strips() + ["\ufeff", "\u180e", "\u200b", "\x1c"]:
        cases += [f"{space}10", f"10{space}", f"{space}10{space}"]

    digits = _unicode_decimal_digits()
    # Every decimal digit on its own: the value of each one, in every script.
    cases += digits
    # And each block's zero paired with the digit after it, which catches a
    # right answer reached by the wrong route (a lookup that happens to work for
    # single characters but not for place value).
    zeros = [d for d in digits if unicodedata.decimal(d) == 0]
    for zero in zeros:
        cases.append(chr(ord(zero) + 1) + chr(ord(zero) + 2))
        # And "ten" written in that script, which is what a keyboard laid out
        # for it produces when someone types a set length.
        cases.append(chr(ord(zero) + 1) + zero)
    # Scripts mixed inside one number, which `int()` allows.
    if len(zeros) > 3:
        cases.append(chr(ord(zeros[1]) + 1) + "0")
        cases.append("1" + chr(ord(zeros[2]) + 2))

    # THE OTHER DIRECTION. Digits this node knows and this interpreter does not:
    # on their own, as a "ten" in their own script, and mixed into an ASCII
    # number - because the grammar could refuse a lone one and still let it
    # through beside a digit it does accept.
    for digit in node_only_digits:
        cases += [digit, digit + digit, digit + "0", "1" + digit]

    return cases


def _python_answer(text):
    """`int(text)` as a string, or None where it raises - the driver's shape."""
    try:
        return str(int(text))
    except ValueError:
        return None


def _run_node(executable, script, payload=None, timeout=180):
    """Run one driver and return its stdout, reaping it in every path."""
    process = subprocess.Popen(
        [executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(script.parent),
    )
    try:
        out, err = process.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
        pytest.fail(f"{script.name} did not finish within {timeout} s:\n{err}")
    finally:
        # Belt to the braces of `communicate`, which has already reaped in every
        # path above. A `kill` on an exited process is a no-op, and one on a
        # process left behind by an exception higher up is the whole point.
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)

    assert process.returncode == 0, f"{script.name} failed:\n{out}\n{err}"
    return out


def _require_node():
    executable = _node()
    if executable is None:
        pytest.skip(
            "node is not on PATH, so parseIntegerStrictly was not compared "
            "against int() at all"
        )
    if _node_major(executable) < MINIMUM_NODE_MAJOR:
        pytest.skip(
            f"node >= {MINIMUM_NODE_MAJOR} is needed to run the driver as ESM; "
            "parseIntegerStrictly was not compared against int()"
        )
    return executable


@pytest.fixture(scope="module")
def digit_survey():
    """Which code points the helper accepts, and which ones THIS node calls Nd.

    Behaviour, not internals: `accepted` comes from calling the exported
    function on every code point, so a rule that read the shipped table and then
    used something else would still be caught.
    """
    executable = _require_node()
    survey = json.loads(_run_node(executable, SURVEY_DRIVER))
    return {
        "accepted": {code: value for code, value in survey["accepted"]},
        "node_nd": set(survey["nodeNd"]),
        # The Unicode version the shipped table DECLARES. Read from the module's
        # export, so a table regenerated without moving the declaration - or a
        # declaration moved without regenerating the table - is still caught.
        "unicode_version": survey["unicodeVersion"],
    }


@pytest.fixture(scope="module")
def python_decimal_digits():
    """``{code point: value}`` for every Nd character THIS interpreter has."""
    return {
        code: unicodedata.decimal(chr(code))
        for code in range(sys.maxunicode + 1)
        if unicodedata.category(chr(code)) == "Nd"
    }


@pytest.fixture(scope="module")
def node_digits_the_helper_refuses(digit_survey):
    """Characters node calls a decimal digit and the shipped table does not.

    Derived from the helper's own accepted set rather than from this
    interpreter's ``Nd``, because those are not the same question when the suite
    runs on an interpreter older than the one the table targets: there the table
    holds digits this ``int()`` refuses, and feeding those into a corpus that
    expects ``int()`` to agree would fail for a reason that is not a parser
    defect. ``test_the_helper_accepts_exactly_the_shipped_interpreters_digits``
    is where that mismatch is failed, once, by name.

    Every member is still one THIS ``int()`` refuses - the table holds at least
    this interpreter's digits, so subtracting it subtracts at least as much -
    which is what keeps the comparison against ``int()`` in
    ``test_every_answer_is_the_answer_int_gives`` honest.
    """
    return [chr(code) for code in sorted(digit_survey["node_nd"] - set(digit_survey["accepted"]))]


@pytest.fixture(scope="module")
def javascript_answers(node_digits_the_helper_refuses):
    """The shipped helper's answer for every corpus entry, via node."""
    executable = _require_node()

    corpus = _corpus(node_digits_the_helper_refuses)
    answers = json.loads(_run_node(executable, DRIVER, json.dumps(corpus)))
    assert len(answers) == len(corpus), (
        f"the driver answered {len(answers)} of {len(corpus)} inputs"
    )
    return dict(zip(corpus, answers))


def test_the_corpus_is_the_size_it_claims_to_be():
    """Guard the guard. If `unicodedata` stopped yielding digits the comparison
    below would pass over almost nothing and still be green."""
    digits = _unicode_decimal_digits()

    assert len(digits) > 600, f"only {len(digits)} decimal digits found"
    assert "0" in digits and "\u0660" in digits, "the ASCII or Arabic-Indic block is missing"
    assert len(_corpus()) > 700

    # And the other derived half. A loop that yielded nothing would leave the
    # whitespace rule unchecked while the file still read as thorough.
    stripped = _characters_int_strips()
    assert len(stripped) > 20, f"only {len(stripped)} stripped characters found"
    assert "\u0085" in stripped, "U+0085 is stripped by int(); the derivation missed it"
    assert "\ufeff" not in stripped, "U+FEFF is not stripped by int()"
    assert "\x1c" not in stripped, (
        "int() does not strip U+001C, so the derivation has picked up "
        "str.isspace() rather than int()"
    )
    assert "0" not in stripped and "+" not in stripped, (
        "a digit or a sign was mistaken for whitespace"
    )


def test_every_answer_is_the_answer_int_gives(javascript_answers):
    """The comparison itself, over the whole corpus at once.

    Reported as a list rather than one case at a time: a change to the parsing
    rule breaks a whole class of input, and seeing the class is what says which
    rule moved.
    """
    disagreements = [
        (text, _python_answer(text), javascript_answers[text])
        for text in javascript_answers
        if _python_answer(text) != javascript_answers[text]
    ]

    assert disagreements == [], "\n".join(
        f"  {text!r}: int() -> {expected}, parseIntegerStrictly -> {actual}"
        for text, expected, actual in disagreements[:40]
    )


def test_the_two_characters_that_separate_int_from_javascript_trim(javascript_answers):
    """Named on their own, because they are the reason this file exists rather
    than a shorter hand-written one, and a corpus edit could drop them silently.

    U+0085 NEXT LINE: `int()` strips it, `String.prototype.trim()` does not.
    U+FEFF: `trim()` strips it, `int()` does not.
    """
    assert javascript_answers["\u008510"] == "10", "U+0085 has to be stripped, as int() does"
    assert javascript_answers["\ufeff10"] is None, "U+FEFF must not be stripped; int() keeps it"


def test_a_non_ascii_ten_is_a_ten(javascript_answers):
    """The case that made this a defect rather than a curiosity: an Arabic
    keyboard's digits, refused by the old ASCII-only rule."""
    assert javascript_answers["\u0661\u0660"] == "10"
    assert javascript_answers["\uff11\uff10"] == "10"
    assert javascript_answers["\u0967\u0966"] == "10"


# ---------------------------------------------------------------------------
# The other direction: digits JavaScript knows and this Python does not
# ---------------------------------------------------------------------------


def test_the_helper_accepts_exactly_the_shipped_interpreters_digits(
    digit_survey, python_decimal_digits
):
    r"""THE SHIP-BLOCKING PROPERTY: parser == shipped interpreter, with VALUES.

    Exact parity in both directions over every code point there is. No
    allowance, no measured record of an interpreter that is not here, no branch
    on which interpreter is running - one comparison, and where it cannot be
    made this fails instead of narrowing what it claims.

    Three ways to fail, named separately because they mean different things: an
    unexpected acceptance is `\p{Nd}` delegation or a table generated from the
    wrong interpreter; one this Python accepts and the helper does not is the
    table falling behind; and a disagreement about a VALUE is `decimalValue`
    finding the wrong start for a run.

    WHY THE INTERPRETER CHECK SITS IN THE MIDDLE OF IT. The first two failures
    are askable of any interpreter: every digit it knows must be accepted, with
    its value. The third - that NOTHING ELSE is accepted - is only askable of
    the interpreter the table was generated from, because a table legitimately
    holding digits an older `int()` refuses is indistinguishable, from that
    older interpreter, from a table holding digits nobody's `int()` accepts.

    Rounds 3 and 4 both shipped a defect through that gap, so the gap is closed
    by refusing to certify rather than by describing the gap more precisely.
    See the module docstring: the record that used to sit here pinned
    membership and then, one round later, still not values, and a table whose
    Tangsa run was split in two answered 0 for a Tangsa ten and passed all
    eleven tests on 3.10.

    Red on a 3.10 run, deliberately, and that red says so in one line rather
    than looking like a parser defect.
    """
    accepted = digit_survey["accepted"]

    only_python = sorted(set(python_decimal_digits) - set(accepted))
    wrong_value = sorted(
        code
        for code in set(accepted) & set(python_decimal_digits)
        if accepted[code] != python_decimal_digits[code]
    )

    assert only_python == [], (
        "int() accepts "
        + ", ".join(f"U+{code:04X}" for code in only_python[:20])
        + f" ({len(only_python)} code points) and parseIntegerStrictly refuses "
        f"them. PYTHON_DECIMAL_RUNS is behind this interpreter "
        f"(unicodedata {unicodedata.unidata_version}); regenerate it on the "
        "interpreter the build workflows freeze, with\n"
        "  python -c \"import sys,unicodedata; "
        "print([c for c in range(sys.maxunicode+1) "
        "if unicodedata.category(chr(c))=='Nd'])\""
    )
    assert wrong_value == [], (
        "the two disagree about the VALUE of "
        + ", ".join(f"U+{code:04X}" for code in wrong_value[:20])
        + " - decimalValue found the wrong start for a run"
    )

    declared = digit_survey["unicode_version"]
    assert unicodedata.unidata_version == declared, (
        f"this suite is running CPython "
        f"{sys.version_info[0]}.{sys.version_info[1]} (unicodedata "
        f"{unicodedata.unidata_version}) and format.js declares its digit table "
        f"to be Unicode {declared}, which is what the interpreter every "
        "build-*.yml freezes reports. Parity with the SHIPPED interpreter is "
        "the property that blocks shipping, and this interpreter cannot check "
        "it: the code points the two versions differ by are ones it has never "
        "heard of, so it can see neither their membership nor their values.\n"
        "\n"
        "There is deliberately no allowance for this any more. One lived here "
        "for two rounds and shipped a defect through a green suite each time - "
        "first by excusing the extras' ABSENCE, then by pinning which code "
        "points they are and never their VALUES.\n"
        "\n"
        "Run the suite on the interpreter the app ships on. "
        ".github/workflows/test-macos.yml naming that interpreter is what makes "
        "this green on CI, and nothing in this file has to change when it does."
    )

    unexpected = sorted(set(accepted) - set(python_decimal_digits))
    assert unexpected == [], (
        "parseIntegerStrictly accepts "
        + ", ".join(f"U+{code:04X}" for code in unexpected[:20])
        + f" ({len(unexpected)} code points) that this int() refuses, and this "
        f"IS the interpreter the table declares itself generated from "
        f"(Unicode {declared}). Either the digit class is resolving against the "
        "JavaScript runtime's Unicode tables instead of PYTHON_DECIMAL_RUNS, or "
        "the table was generated from an interpreter that is not the one "
        "PYTHON_UNICODE_VERSION names."
    )


def test_every_digit_node_knows_and_the_table_refuses_is_refused_everywhere(
    digit_survey, node_digits_the_helper_refuses, javascript_answers
):
    """The reverse corpus: the GRAMMAR half, and the guard that sizes it.

    ``node_digits_the_helper_refuses`` went into ``_corpus`` alone, doubled,
    and mixed with an ASCII digit on both sides, so this covers the grammar and
    not only the character class - a rule that refused a lone Kawi zero and
    still let one through beside a ``1`` would fail here and pass the character
    -class test above. Each of them is also one THIS ``int()`` refuses, so the
    comparison is still against CPython and not merely against the helper's own
    opinion of itself.

    The character class is owned by
    ``test_the_helper_accepts_exactly_the_shipped_interpreters_digits`` exactly;
    this does not restate it. What this adds is the four positions.
    """
    assert digit_survey["node_nd"] >= set(digit_survey["accepted"]), (
        "this node calls fewer code points Nd than the shipped table holds, "
        "which the reverse corpus assumes is impossible"
    )
    assert len(node_digits_the_helper_refuses) > 50, (
        f"only {len(node_digits_the_helper_refuses)} code points this node "
        "calls a decimal digit and the table refuses, so this checks almost "
        "nothing. Either node and the shipped CPython have converged on one "
        "Unicode version - in which case say so here and retire the guard - or "
        "the helper has gone back to asking the runtime what a digit is, which "
        "would make these two sets identical by construction."
    )

    disagreements = [
        (text, _python_answer(text), javascript_answers[text])
        for digit in node_digits_the_helper_refuses
        for text in (digit, digit + digit, digit + "0", "1" + digit)
        if _python_answer(text) != javascript_answers[text]
    ]

    assert disagreements == [], (
        f"{len(node_digits_the_helper_refuses)} code points this node calls a "
        "decimal digit and the shipped table does not; "
        + "\n".join(
            f"  {text!r}: int() -> {expected}, parseIntegerStrictly -> {actual}"
            for text, expected, actual in disagreements[:20]
        )
    )

    print(
        f"\nchecked {len(node_digits_the_helper_refuses)} node digits the table "
        f"refuses (node Nd {len(digit_survey['node_nd'])}, "
        f"table {len(digit_survey['accepted'])})"
    )


# ---------------------------------------------------------------------------
# WHICH interpreter the table is for. The check above compares the parser with
# the interpreter that RUNS it; on its own that says nothing about the one the
# app SHIPS on, and round 3 shipped a table generated from the wrong one.
# ---------------------------------------------------------------------------

def _workflow_python_versions():
    """``{workflow file name: [python-version, ...]}`` for every workflow."""
    versions = {}
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        found = re.findall(
            r"""python-version:\s*['"]?([0-9.]+)['"]?""", workflow.read_text()
        )
        if found:
            versions[workflow.name] = sorted(set(found))
    return versions


def _shipped_python_version(versions):
    """The one CPython minor every ``build-*`` workflow sets up.

    The BUILD workflows, not the test one: what a user runs is what PyInstaller
    froze, and `parseIntegerStrictly` has to answer as THAT interpreter's
    ``int()`` answers. Insisting the builds agree with each other is part of the
    check - three platforms on two Pythons would make "the shipped interpreter"
    an ambiguous phrase, and the table can only be generated from one.
    """
    build = sorted(
        {
            version
            for name, found in versions.items()
            if name.startswith("build-")
            for version in found
        }
    )
    assert build, f"no build-* workflow sets a python-version; found {versions}"
    assert len(build) == 1, (
        f"the build workflows no longer agree on one interpreter: {build}. "
        "PYTHON_DECIMAL_RUNS can only be generated from one of them, so "
        "'the shipped interpreter' has to name exactly one version."
    )
    return build[0]


def test_the_shipped_version_is_read_from_the_build_workflows(tmp_path, monkeypatch):
    """The reader under the test below, on workflows written here.

    Without this, ``test_the_digit_table_targets_the_interpreter_the_app_ships_on``
    proves only that the declaration equals SOME value that happens to be
    "3.11"'s Unicode version - a hardcoded constant would satisfy it just as
    well. The honest way to show it reads `.github/workflows/build-*.yml` is to
    point it at workflows this test wrote, which
    `.github/workflows/` itself cannot be used for: the parallel PR that aligns
    the test interpreter with the build one owns those files.

    Three things, because they are three ways for the reader to be wrong: the
    BUILD workflows are what it reads, `test-macos.yml` is not allowed to
    influence the answer, and builds that disagree with each other are a failure
    rather than a silent pick.
    """
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "test-macos.yml").write_text('        python-version: "3.10"\n')
    (workflows / "build-macos.yml").write_text("        python-version: '3.12'\n")
    (workflows / "build-windows.yml").write_text("        python-version: '3.12'\n")
    monkeypatch.setattr(
        sys.modules[__name__], "WORKFLOWS", workflows, raising=True
    )

    versions = _workflow_python_versions()
    assert versions == {
        "build-macos.yml": ["3.12"],
        "build-windows.yml": ["3.12"],
        "test-macos.yml": ["3.10"],
    }, f"the workflow reader did not read what was written: {versions}"

    assert _shipped_python_version(versions) == "3.12", (
        "the shipped version was not taken from the build workflows; "
        "3.10 is what test-macos.yml says and it must not reach the answer"
    )

    (workflows / "build-macos-intel.yml").write_text("        python-version: '3.13'\n")
    with pytest.raises(AssertionError, match="no longer agree on one interpreter"):
        _shipped_python_version(_workflow_python_versions())


def test_the_digit_table_targets_the_interpreter_the_app_ships_on(digit_survey):
    """THE SHIP-BLOCKING PROPERTY, half one: the table is FOR the built Python.

    ``test_the_helper_accepts_exactly_the_shipped_interpreters_digits``
    compares the parser against whichever interpreter runs the suite. That is
    only worth something if the table was generated from the interpreter the
    app is SHIPPED on, and in round 3 it was not: the table came from 3.10
    (Unicode 13.0, 650 digits) and every ``build-*`` workflow freezes 3.11
    (Unicode 14.0, 660). A user on a shipped build could type a Tangsa ten,
    whose ``int()`` in that same bundle returns 10, and be told it was not a
    valid number for total tracks.

    The version is read from the module's EXPORT through node, not grepped out
    of the source, so it is the declaration the shipped code actually carries.

    Red when: the builds move to a Python whose Unicode version differs from
    the table's declaration, or the declaration is edited to a version the
    builds do not use. Either way the table needs regenerating from the new
    interpreter, and the message says which one to run.
    """
    shipped = _shipped_python_version(_workflow_python_versions())

    assert shipped in MEASURED_UNICODE_VERSION, (
        f"the app is built on CPython {shipped}, whose unicodedata version has "
        "not been measured here. Run\n"
        "  pythonX.Y -c \"import unicodedata; print(unicodedata.unidata_version)\"\n"
        "on that exact interpreter, add the row to MEASURED_UNICODE_VERSION, "
        "and regenerate PYTHON_DECIMAL_RUNS from it. Do not read the version "
        "off a changelog - that is how round 3 shipped the wrong table."
    )
    expected = MEASURED_UNICODE_VERSION[shipped]

    assert digit_survey["unicode_version"] == expected, (
        f"format.js declares its digit table to be Unicode "
        f"{digit_survey['unicode_version']}, and the app is built on CPython "
        f"{shipped}, whose unicodedata is {expected}. The shipped parser and "
        "the shipped interpreter would disagree about which characters are "
        "digits. Regenerate the table with\n"
        "  python -c \"import sys,unicodedata; print([c for c in "
        "range(sys.maxunicode+1) if unicodedata.category(chr(c))=='Nd'])\"\n"
        f"on CPython {shipped}, and update PYTHON_UNICODE_VERSION."
    )


def test_the_measured_unicode_versions_are_right_about_this_interpreter():
    """The mapping above is hand-maintained, so it is checked where it can be.

    Only one row is checkable per run - the row for the interpreter running
    this test - but every interpreter the project uses runs the suite sooner or
    later, so every row is reachable. A row that was wrong about the running
    interpreter would make
    ``test_the_digit_table_targets_the_interpreter_the_app_ships_on`` demand the
    wrong table, which is round 3's defect wearing a different hat.

    A minor that is not in the map is skipped rather than failed: running the
    suite on an interpreter the project does not build or test on is a
    developer's business, not a defect, and the test above is what refuses an
    unmeasured BUILD version.
    """
    running = "%d.%d" % sys.version_info[:2]
    if running not in MEASURED_UNICODE_VERSION:
        pytest.skip(
            f"CPython {running} is not a version this project builds or tests "
            f"on ({sorted(MEASURED_UNICODE_VERSION)}), so it pins no row"
        )

    assert MEASURED_UNICODE_VERSION[running] == unicodedata.unidata_version, (
        f"MEASURED_UNICODE_VERSION says CPython {running} has unicodedata "
        f"{MEASURED_UNICODE_VERSION[running]}, and this CPython {running} "
        f"reports {unicodedata.unidata_version}. The map is wrong; measure it "
        "again on each interpreter rather than editing it to taste."
    )


def test_the_suite_and_the_build_agree_on_one_interpreter_or_say_they_do_not():
    """THE SHIP-BLOCKING PROPERTY, half two: is this run's evidence complete?

    Parity is proved against the interpreter that RUNS the suite. When that is
    the interpreter the app SHIPS on, the two halves compose and the proof is
    total: parser == running == shipped. When it is not, the comparison is
    still made and still real, but ten code points at the top of the table are
    ones this interpreter cannot be asked about, so their VALUES go unchecked.

    This test does not fail on the mismatch - it is not a defect for a
    developer to run the suite on the interpreter they happen to have, and
    failing here would make the branch unrunnable outside CI. It REPORTS it, in
    the one place a reader is looking at the parity evidence, so a partial run
    cannot be read as a total one. `.github/workflows/test-macos.yml` moving to
    the build's interpreter is what turns this from partial to total, and
    nothing here has to change when it does.
    """
    versions = _workflow_python_versions()
    shipped = _shipped_python_version(versions)
    tested = versions.get("test-macos.yml")
    running = "%d.%d" % sys.version_info[:2]

    assert tested, f"test-macos.yml sets no python-version; found {versions}"
    assert len(tested) == 1, f"test-macos.yml sets several Pythons: {tested}"

    if running == shipped:
        print(
            f"\nTOTAL: this run is on CPython {running}, the interpreter the "
            "app ships on, so parity is proved against the shipped int()"
        )
    else:
        print(
            f"\nPARTIAL: this run is on CPython {running} and the app ships on "
            f"{shipped}. Every digit THIS interpreter knows is checked in both "
            "directions; the digits only the shipped interpreter knows are "
            "checked for membership and not for value. CI sets up "
            f"{tested[0]}; aligning it with {shipped} makes this run total."
        )


def test_no_digit_this_runtime_knows_sits_just_below_a_run_the_helper_accepts(
    digit_survey,
):
    """THE PREMISE THAT MADE THE OLD WALK-BACK SAFE, pinned so its expiry shows.

    ``decimalValue`` used to find the start of a digit's run by walking back
    over the RUNTIME's ``\\p{Nd}``; it now finds it in ``PYTHON_DECIMAL_RUNS``.
    That change cannot be caught by any behavioural test on this node, and this
    test exists to say so rather than to hide it: restoring the walk-back leaves
    every suite green, because on node 20 the two agree about the value of all
    650 accepted code points.

    They agree only because of an accident of layout - no code point node calls
    a decimal digit sits immediately below the start of a run the helper
    accepts, so the walk can never leave its own run. The commit that removed
    the walk called that luck rather than design. This is the luck, written
    down: if a future runtime learns a digit block that abuts one of these runs,
    the walk-back would start returning a wrong VALUE for an ordinary digit, and
    this goes red on the day that becomes possible instead of on the day someone
    reintroduces the walk.

    What it does NOT pin: the current implementation. A rule that read the table
    and then computed the offset some other way passes here and fails
    ``test_the_helper_accepts_exactly_the_shipped_interpreters_digits``, which
    is the test that owns values.
    """
    accepted = set(digit_survey["accepted"])
    assert accepted, "the survey accepted nothing, so this checks no boundaries"

    # Derived from what the helper ACCEPTS, not from a copy of the table: the
    # walk-back walks over contiguous digits, so the boundary that matters is
    # the edge of a maximal contiguous accepted block.
    starts = sorted(code for code in accepted if code - 1 not in accepted)

    assert len(starts) > 50, (
        f"only {len(starts)} run starts derived from {len(accepted)} accepted "
        "code points; the survey has collapsed and this boundary check would "
        "pass over almost nothing"
    )
    assert 0x0030 in starts, "the ASCII run start is missing from the derivation"

    abutting = [code for code in starts if code > 0 and code - 1 in digit_survey["node_nd"]]

    assert abutting == [], (
        "this runtime calls "
        + ", ".join(f"U+{code - 1:04X}" for code in abutting[:20])
        + " a decimal digit, and it sits immediately below the accepted run "
        "starting at "
        + ", ".join(f"U+{code:04X}" for code in abutting[:20])
        + ". Walking back over the runtime's \\p{Nd} to find a run start would "
        "now leave the run and return a wrong place value, so the table lookup "
        "in decimalValue is load-bearing rather than merely tidier."
    )
