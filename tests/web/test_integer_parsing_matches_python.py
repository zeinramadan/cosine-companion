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
workflow reader below was deleted for being.

The cost is real and it is the smaller half: until
``.github/workflows/test-macos.yml`` names the interpreter the builds freeze,
this one test is red on CI and on any developer's 3.10. That red IS the
mismatch. Aligning the two makes every run a total proof and requires no change
here.

The other half of the property fails separately and so is checked separately:
that the table is DECLARED for the interpreter every build workflow freezes -
``test_the_digit_table_targets_the_interpreter_the_app_ships_on``. What that
reads the workflows WITH is PyYAML, after three hand-written YAML subsets in
a row answered the question confidently and wrongly; the shapes that defeated
them are pinned by
``test_the_shipped_version_is_read_from_the_build_workflows`` and
``test_every_workflow_names_exactly_one_python_this_file_can_resolve``.

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
#
# THE WORKFLOWS ARE PARSED BY PyYAML. They used to be read by a hand-written
# YAML subset, and it was CONFIDENTLY WRONG three rounds running - each round
# fixed by teaching it one more shape, and each fix followed by a shape nobody
# had thought of:
#
#   round 5  a regex over raw text: a heredoc line inside `run: |` was read as
#            a setting, and a key not first on its line was invisible
#   round 6  flow mappings and block scalars taught to it
#   round 7  `with: {"python\x2dversion": "3.10"}` - an escaped `-` in a
#            double-quoted key, which YAML decodes to `python-version` and the
#            raw bytes do not contain - above a `run: |2-` block, a valid
#            header spelling (indicator 2, chomping `-`) that the reader's
#            `[|>][+-]?[0-9]?` did not accept, so it never cut the block and
#            read the shell script under it instead. yaml.safe_load says that
#            build uses 3.10. The reader said 3.11, and eleven tests passed.
#
# Round 6's argument that collecting everything can only produce false
# AMBIGUITY was wrong: it produces false CERTAINTY, in both directions. And a
# hand-written YAML subset is a GENERATOR of that defect rather than a thing
# with a finite number of bugs in it, because YAML's shapes are unbounded.
#
# So the subset is gone and nothing here parses YAML any more. PyYAML does, and
# `yaml.safe_load` is the same oracle that convicted each of the three readers.
#
# WHERE PyYAML COMES FROM, because this is the one fact worth knowing before
# trusting the arrangement: it is not declared anywhere in this repository. It
# reaches CI as a dependency of `essentia-tensorflow`, through
# `requirements-macos-arm64-py311.lock` (`pyyaml==6.0.3  # via
# essentia-tensorflow`), which `.github/workflows/test-macos.yml` installs with
# `--require-hashes`. That is a real thread to hang this on and it could be cut
# - trimming the 483 MB TensorFlow stack out of the test job would take PyYAML
# with it. It is hung on anyway because the failure is LOUD: `_yaml()` raises,
# the tests below fail and name the lock. There is deliberately no skip. A skip
# exits zero, and this project has had seven green suites that measured
# nothing. If that thread is ever cut, declare PyYAML directly rather than
# going back to reading YAML with regexes.
# ---------------------------------------------------------------------------

#: Both spellings of the extension GitHub Actions runs. Globbing only ``*.yml``
#: was one of the old reader's fail-open modes: renaming a build workflow to
#: ``.yaml`` changes nothing about what CI does and used to remove the workflow
#: from view entirely, leaving the surviving builds to answer in its place.
WORKFLOW_SUFFIXES = (".yml", ".yaml")

#: The name of the workflow that runs this suite. A literal, and checked to
#: exist rather than looked up with ``.get`` - a rename that silently stopped
#: the check applying is the same fail-open shape as the rest of this section.
TEST_WORKFLOW = "test-macos.yml"

#: What this file is prepared to UNDERSTAND as a version: a bare CPython minor
#: or patch, as a STRING. Everything else - ``${{ env.BUILD_PYTHON }}``, a
#: matrix expression, a YAML list, a range - is a real setting this file cannot
#: resolve, and is refused rather than skipped. Separating "understood" from
#: "found" is the point: the round-3 reader had only "found", so a value it
#: could not read was indistinguishable from a workflow that set nothing, and
#: both were dropped in silence.
#:
#: A STRING, and that word is load-bearing now that YAML does the reading.
#: Unquoted ``python-version: 3.10`` is a YAML FLOAT: it parses to 3.1, reaches
#: setup-python as ``3.1``, and is the best-known way to build on a Python
#: nobody meant. A float is not a string, so it is refused with its own name.
_UNDERSTOOD_VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def _yaml():
    """PyYAML, or a LOUD failure. Never a skip.

    A skip exits zero and reads exactly like a pass in every summary line and
    every CI badge. The whole of this section is about not letting "could not
    check" look like "checked", so the one dependency it has fails the same way
    everything else here fails: by name, with the fix in the message.
    """
    try:
        import yaml
    except ImportError as exception:  # pragma: no cover - see the message
        raise AssertionError(
            "PyYAML is not importable, and this file reads .github/workflows "
            "with it rather than with a regex - three hand-written readers "
            "were confidently wrong about which Python the app is built on "
            "before it did. This is a FAILURE and not a skip on purpose: a "
            "skip exits zero and looks like a pass.\n"
            "\n"
            "CI gets PyYAML from requirements-macos-arm64-py311.lock "
            "(pyyaml==6.0.3, via essentia-tensorflow), which test-macos.yml "
            "installs with --require-hashes. Locally: python -m pip install "
            "pyyaml==6.0.3. If the lock no longer carries it, declare it "
            "directly - do not go back to parsing YAML by hand."
        ) from exception
    return yaml


def _workflow_files():
    """Every workflow file on disk, ``{name: path}``.

    THE FILESYSTEM IS THE ROLL CALL, not the set of files that happened to
    match a pattern. That distinction is half of this section's fix: the check
    below can only demand an answer from a build workflow it knows exists, and
    it can only know one exists by listing the directory.
    """
    return {
        path.name: path
        for path in sorted(WORKFLOWS.iterdir())
        if path.is_file() and path.suffix in WORKFLOW_SUFFIXES
    }


def _python_version_settings(node):
    """Every value set for a ``python-version`` KEY anywhere in one document.

    A key, in the parsed document - not a line, and not an occurrence of the
    text. That is the whole difference between this and the three readers it
    replaces, and it decides both directions at once:

    * ``with: {"python\\x2dversion": "3.10"}`` IS this key. PyYAML decoded the
      escape; nothing here had to know that ``\\x2d`` is a hyphen.
    * a heredoc line inside ``run: |``, a ``python-version`` inside a quoted
      string, and ``uv pip compile --python-version 3.11`` in a shell command
      are all part of one STRING value. A string is not a mapping, so none of
      them is reached. Nothing here had to know what a block scalar is, which
      is what the ``|2-`` in round 7 turned on.
    """
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "python-version":
                found.append(value)
            found.extend(_python_version_settings(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_python_version_settings(item))
    return found


def _workflow_python_versions():
    """``{workflow name: [value, ...]}`` for every workflow file there is.

    AS PARSED, in document order, and never filtered. A workflow that sets
    nothing gets an empty list rather than vanishing, and a value this file
    cannot resolve is carried through to be refused by name rather than
    dropped. Both of those used to disappear here, which is how the reader
    failed open: change one build to ``python-version: ${{ env.BUILD_PYTHON }}``
    while another keeps a literal 3.11, and the surviving workflow quietly
    became the answer for both.
    """
    yaml = _yaml()
    versions = {}
    for name, path in _workflow_files().items():
        try:
            documents = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError as exception:
            raise AssertionError(
                f"{name} is not valid YAML, so GitHub Actions cannot be "
                f"running it either: {exception}"
            ) from exception
        versions[name] = [
            value
            for document in documents
            for value in _python_version_settings(document)
        ]
    return versions


def _understood_version(value):
    """The CPython version one parsed setting states, or None for "cannot tell".

    None is not "there is none" - it is "this file does not understand this",
    and every caller has to turn that into a failure rather than a skip.
    """
    if not isinstance(value, str) or not _UNDERSTOOD_VERSION.match(value):
        return None
    return value


def _describe(value):
    """One unresolvable value, with the TYPE YAML gave it.

    The type is the message for the commonest real mistake: ``3.11`` without
    quotes is a float, and printing it back as ``3.11`` would hide exactly the
    thing that went wrong.
    """
    return f"{value!r} ({type(value).__name__})"


def _the_one_python_it_sets(name, values):
    """The single CPython version one workflow sets, or a loud failure.

    Three failures rather than one silence, because they need different fixes:
    the workflow sets nothing, it sets something unreadable, or it sets several.
    """
    assert values, (
        f"{name} sets no python-version at all, and this file's answer depends "
        "on it. Either it lost the `- uses: actions/setup-python` step, or the "
        "step now takes its version from somewhere this file does not look."
    )
    unreadable = [value for value in values if _understood_version(value) is None]
    assert unreadable == [], (
        f"{name} sets python-version to "
        + ", ".join(_describe(value) for value in unreadable)
        + ", which is not a literal CPython version. It will not be guessed at "
        "and it will not be skipped: skipping is what let one build workflow's "
        "literal answer for another's expression.\n"
        "\n"
        "If the type above is `float`, the version is unquoted, and that is a "
        "real defect rather than a formatting one - YAML reads `3.10` as the "
        "number 3.1 and setup-python is handed `3.1`. Quote it.\n"
        "\n"
        "Otherwise either give the workflow a literal version, or teach "
        "_understood_version to resolve this form and pin the new form in "
        "test_the_shipped_version_is_read_from_the_build_workflows."
    )
    understood = sorted({_understood_version(value) for value in values})
    assert len(understood) == 1, (
        f"{name} sets several Pythons ({understood}), so it does not name one "
        "interpreter. A matrix here would make 'the interpreter this workflow "
        "uses' an ambiguous phrase."
    )
    return understood[0]


def _shipped_python_version(versions):
    """The one CPython minor every ``build-*`` workflow sets up.

    The BUILD workflows, not the test one: what a user runs is what PyInstaller
    froze, and `parseIntegerStrictly` has to answer as THAT interpreter's
    ``int()`` answers. Insisting the builds agree with each other is part of the
    check - three platforms on two Pythons would make "the shipped interpreter"
    an ambiguous phrase, and the table can only be generated from one.

    EVERY build workflow has to answer, and the roll call is the directory
    listing. A build that could not be read used to be absent from ``versions``
    and therefore absent from this set, which made every other build an
    effective fallback for it.
    """
    build = sorted(name for name in versions if name.startswith("build-"))
    assert build, f"no build-* workflow was found at all; read {sorted(versions)}"

    per_workflow = {name: _the_one_python_it_sets(name, versions[name]) for name in build}
    distinct = sorted(set(per_workflow.values()))
    assert len(distinct) == 1, (
        f"the build workflows no longer agree on one interpreter: {per_workflow}. "
        "PYTHON_DECIMAL_RUNS can only be generated from one of them, so "
        "'the shipped interpreter' has to name exactly one version."
    )
    return distinct[0]


def test_the_shipped_version_is_read_from_the_build_workflows(tmp_path, monkeypatch):
    """The reader under the test below, on workflows this test writes.

    Without this, ``test_the_digit_table_targets_the_interpreter_the_app_ships_on``
    proves only that the declaration equals SOME value that happens to be
    "3.11"'s Unicode version - a hardcoded constant would satisfy it just as
    well. The honest way to show it reads `.github/workflows/build-*` is to
    point it at workflows written here, which `.github/workflows/` itself
    cannot be used for: a test that mutated the real files would have to put
    them back, and a killed run would leave the repository holding the mutation.

    THE FAIL-OPEN MODES ARE THE POINT, and every one of them below was a GREEN
    eleven-test suite at the time. Three of them are the shapes that convicted
    three successive hand-written readers, and they are here to stay red on the
    day someone decides parsing YAML by hand was fine after all.
    """
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    monkeypatch.setattr(sys.modules[__name__], "WORKFLOWS", workflows, raising=True)

    def build_says(text):
        (workflows / "build-macos.yml").write_text(text)
        return _workflow_python_versions()

    (workflows / "test-macos.yml").write_text('        python-version: "3.10"\n')
    (workflows / "build-macos.yml").write_text("        python-version: '3.12'\n")
    # `.yaml`, because GitHub Actions runs it and the old glob did not see it.
    (workflows / "build-windows.yaml").write_text(
        "# python-version: '3.9'   <- a comment, and not a setting\n"
        "python-version: '3.12'    # quoted, with a trailing comment\n"
    )
    versions = _workflow_python_versions()
    assert versions == {
        "build-macos.yml": ["3.12"],
        "build-windows.yaml": ["3.12"],
        "test-macos.yml": ["3.10"],
    }, f"the workflows were not read as written: {versions}"

    assert _shipped_python_version(versions) == "3.12", (
        "the shipped version was not taken from the build workflows; "
        "3.10 is what test-macos.yml says and it must not reach the answer"
    )

    # A build that disagrees with the others is a failure, not a silent pick.
    (workflows / "build-macos-intel.yml").write_text("        python-version: '3.13'\n")
    with pytest.raises(AssertionError, match="no longer agree on one interpreter"):
        _shipped_python_version(_workflow_python_versions())
    (workflows / "build-macos-intel.yml").unlink()

    # THE FAIL-OPEN CASE ITSELF: one build in a form that cannot be resolved,
    # while another still carries a literal. The old reader answered "3.12"
    # here, from the surviving workflow, and said nothing.
    with pytest.raises(AssertionError, match="not a literal CPython version"):
        _shipped_python_version(build_says("        python-version: ${{ env.BUILD_PYTHON }}\n"))

    # And a build that sets no python-version at all, which the old reader also
    # let the surviving workflow answer for.
    with pytest.raises(AssertionError, match="sets no python-version at all"):
        _shipped_python_version(build_says("        cache: pip\n"))

    # A matrix inside one workflow is ambiguous in the same way two workflows
    # disagreeing are, and is refused for the same reason.
    with pytest.raises(AssertionError, match="sets several Pythons"):
        _shipped_python_version(
            build_says(
                "strategy:\n"
                "  matrix:\n"
                "    include:\n"
                "      - python-version: '3.12'\n"
                "      - python-version: '3.13'\n"
            )
        )

    # AN UNQUOTED VERSION IS A YAML FLOAT, not a version. `3.10` parses to the
    # number 3.1 and setup-python is handed `3.1`. The old text reader called
    # this a perfectly good "3.10", which is the one place reading the raw
    # bytes was not merely blind but actively wrong about the value.
    with pytest.raises(AssertionError, match=r"not a literal CPython version"):
        _shipped_python_version(build_says("        python-version: 3.10\n"))
    assert build_says("        python-version: 3.10\n")["build-macos.yml"] == [3.1], (
        "unquoted 3.10 is the YAML float 3.1; if this ever reads as '3.10' "
        "then something is reading the file's text again"
    )

    # ROUND 5. A `run: |` block holds a shell script, and a heredoc inside it
    # can put `python-version:` at the start of its own line. That text
    # configures nothing. It is a STRING here, and strings are not walked.
    assert build_says(
        "      with:\n"
        "        python-version: '3.12'\n"
        "      run: |\n"
        "        cat <<'EOF' > note.txt\n"
        "        python-version: 3.10\n"
        "        EOF\n"
    )["build-macos.yml"] == ["3.12"], "block scalar text was read as a setting"

    # ROUND 5'S OTHER HALF, and round 6's probe: FLOW MAPPING STYLE. The key is
    # mid-line, so a reader anchored to the start of a line could not see it at
    # all - and INVISIBLE is worse than unreadable, because an unreadable value
    # still says a version is set here while an invisible one leaves the other
    # builds to answer in this one's place.
    assert build_says("      with: {python-version: '3.10', cache: pip}\n")[
        "build-macos.yml"
    ] == ["3.10"], "the flow-mapping form of the setting was not read"
    with pytest.raises(AssertionError, match="no longer agree on one interpreter"):
        _shipped_python_version(_workflow_python_versions())

    # ROUND 5'S TWO HALVES TOGETHER, which is what made it a defect rather than
    # an ambiguity: the real setting invisible AND a shell script answering in
    # its place, with nothing left for the reader to notice.
    assert build_says(
        "      with: {python-version: '3.10'}\n"
        "      run: |\n"
        "        cat <<'EOF' > note.txt\n"
        "        python-version: 3.12\n"
        "        EOF\n"
    )["build-macos.yml"] == ["3.10"], "the one real setting was not the answer"

    # ROUND 7, THE DEFECT THIS PARSER REPLACES. `python\x2dversion` is an
    # escaped `-` in a double-quoted key: YAML decodes it to `python-version`
    # and the raw bytes contain no such string, so the old reader never saw the
    # real 3.10 setting. `|2-` is a VALID block scalar header - indentation
    # indicator 2, chomping `-` - that its `[|>][+-]?[0-9]?` did not accept, so
    # it never cut the block and read the script underneath instead. Reproduced
    # on the real build-macos.yml: yaml.safe_load said 3.10, the reader said
    # 3.11, and all eleven tests passed.
    assert build_says(
        '    - uses: actions/setup-python@v5\n'
        '      with: {"python\\x2dversion": "3.10"}\n'
        "    - run: |2-\n"
        "        python-version: 3.11\n"
    )["build-macos.yml"] == ["3.10"], (
        "the escaped-key setting was not read, or the block scalar under a "
        "`|2-` header was"
    )
    with pytest.raises(AssertionError, match="no longer agree on one interpreter"):
        _shipped_python_version(_workflow_python_versions())

    # AND THE SAME KEY WITH A DECOY PLANTED TO MIRROR ANOTHER FILE'S LINE. This
    # is the arrangement a text comparison of the two files cannot see, and the
    # reason this parses instead of comparing: `python-version` appears in the
    # file exactly once as text, spelling 3.11, and the build uses 3.10.
    assert build_says(
        '    - uses: actions/setup-python@v5\n'
        '      with: {"python\\x2dversion": "3.10"}\n'
        "    - run: |2-\n"
        '        python-version: "3.11"\n'
    )["build-macos.yml"] == ["3.10"], "a mirrored decoy answered for the real setting"

    # A FALSE SETTING INSIDE A QUOTED STRING. The old flow-mapping regex read
    # `{python-version: 3.11}` out of the middle of a string value and reported
    # it as a setting this workflow makes. It configures nothing.
    assert build_says(
        "      with:\n"
        "        python-version: '3.10'\n"
        '      env: {NOTE: "{python-version: 3.11}"}\n'
    )["build-macos.yml"] == ["3.10"], "a quoted string was read as a setting"

    # AND A SHELL COMMAND THAT NAMES A PYTHON VERSION IS NOT A SETTING EITHER.
    # test-macos.yml really does run `uv pip compile --python-version 3.11`, so
    # this is not hypothetical: a check that counted mentions rather than
    # parsing keys would refuse the repository as it actually stands.
    assert build_says(
        "      with:\n"
        "        python-version: '3.11'\n"
        "      run: |\n"
        "        uv pip compile --python-version 3.11 -o out.lock\n"
    )["build-macos.yml"] == ["3.11"], "a --python-version flag was read as a setting"

    # A WORKFLOW THAT IS NOT VALID YAML is a failure naming the file, because
    # GitHub Actions is not running it either.
    with pytest.raises(AssertionError, match="is not valid YAML"):
        build_says("      with: {python-version: '3.11'\n")

    # A RENAME MUST NOT QUIETLY STOP THE CHECK APPLYING. TEST_WORKFLOW is a
    # literal, and a literal that no longer names a file used to mean the check
    # simply had nothing to say about the workflow that runs this suite.
    build_says("        python-version: '3.11'\n")
    (workflows / "test-macos.yml").rename(workflows / "test-macos-renamed.yml")
    with pytest.raises(AssertionError, match="is not among the workflow files"):
        _the_interpreters_the_answer_depends_on(_workflow_python_versions())
    (workflows / "test-macos-renamed.yml").rename(workflows / "test-macos.yml")

    # AND NEITHER MAY THE BUILDS ALL VANISH, which would leave the roll call
    # with nothing to call and the answer resting on the test workflow alone.
    for name in ("build-macos.yml", "build-windows.yaml"):
        (workflows / name).unlink()
    with pytest.raises(AssertionError, match="no build-. workflow was found"):
        _the_interpreters_the_answer_depends_on(_workflow_python_versions())

    # THE DEPENDENCY FAILS LOUDLY AND NEVER SKIPS. `_yaml()` is the one import
    # this section has, and if it ever stops resolving the tests here have to
    # go RED rather than green-with-a-skip - this project has had seven green
    # suites that measured nothing, and a skip is how each of them read.
    monkeypatch.setitem(sys.modules, "yaml", None)
    try:
        _workflow_python_versions()
    except AssertionError as failure:
        assert "PyYAML is not importable" in str(failure), failure
    except BaseException as other:  # pytest.skip raises BaseException, not Exception
        raise AssertionError(
            f"an unimportable PyYAML raised {type(other).__name__} rather than "
            "an AssertionError. `pytest.raises(AssertionError)` would not have "
            "caught pytest's Skipped either, and the run would have been "
            "reported as a skip - which is the one outcome this must never "
            "have, because a skip exits zero and reads as a pass."
        ) from other
    else:
        raise AssertionError(
            "an unimportable PyYAML did not fail at all, so this section would "
            "certify the shipped interpreter without reading a workflow"
        )


def _the_interpreters_the_answer_depends_on(versions):
    """``{name: version}`` for every workflow this file's answer rests on.

    Split out from the test below so the synthetic test can drive it over
    workflows it writes - the roll call is only worth having if something
    proves it refuses a missing file, and `.github/workflows/` cannot be used
    to prove that.
    """
    assert versions, f"no workflow files were found under {WORKFLOWS}"

    # `TEST_WORKFLOW` is asserted to EXIST rather than looked up with `.get`,
    # because a rename that quietly stopped the check applying is the same
    # fail-open shape as the rest of this section.
    assert TEST_WORKFLOW in versions, (
        f"{TEST_WORKFLOW} is not among the workflow files ({sorted(versions)}). "
        "If the workflow that runs this suite was renamed, TEST_WORKFLOW has to "
        "be renamed with it - otherwise this check silently stops applying."
    )
    depends_on = sorted(
        name for name in versions if name.startswith("build-") or name == TEST_WORKFLOW
    )
    named = {name: _the_one_python_it_sets(name, versions[name]) for name in depends_on}

    assert sum(1 for name in named if name.startswith("build-")) >= 1, (
        f"no build-* workflow was found among {sorted(versions)}"
    )
    return named


def test_every_workflow_names_exactly_one_python_this_file_can_resolve():
    """The parser against the REAL `.github/workflows`, which the test above
    cannot use because it writes its own.

    The test above proves the fail-open shapes are REFUSED. This proves the
    repository does not currently contain one - that every workflow whose
    answer this file depends on names exactly one CPython that resolves, and
    that no workflow anywhere sets a python-version that does not. A check that
    is strict about files nobody looked at is a check whose strictness is
    theoretical.

    This also carries the one thing worth keeping from the reporting test that
    round 4 deleted: that `test-macos.yml` names exactly one interpreter. That
    check was real; the test around it was not, because its two branches both
    printed and neither could fail.
    """
    versions = _workflow_python_versions()
    named = _the_interpreters_the_answer_depends_on(versions)

    # And nowhere else may a python-version be set in a form this cannot read.
    # A workflow with no python-version is fine - not every workflow needs one -
    # but one that sets an unresolvable value would be a form this file would
    # have to be taught before it appeared in a build.
    unreadable = sorted(
        (name, _describe(value))
        for name, values in versions.items()
        for value in values
        if _understood_version(value) is None
    )
    assert unreadable == [], (
        "these workflows set a python-version this file cannot resolve: "
        + ", ".join(f"{name} -> {shown}" for name, shown in unreadable)
        + ". Teach _understood_version the form and pin it in "
        "test_the_shipped_version_is_read_from_the_build_workflows, so that a "
        "build workflow adopting it later cannot be read as setting nothing."
    )

    print(f"\nworkflow interpreters: {named}")


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
