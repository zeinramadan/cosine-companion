"""The inventory is checked against ITSELF, not only against the source.

Why this file exists
--------------------
docs/UI_FEATURE_INVENTORY.md is the acceptance contract for PR 3. A false claim
in it is not a documentation nit: PR 3 is reviewed against this document, so a
false claim becomes a regression that PASSES review.

Round 3 wrote falsifiers for 98 absence / universal / exclusivity claims, each
testing the claim against the CODE. Two defects still got through, and neither
was findable that way:

1. "reindex_window's own two cancellation lines are dead code" was falsified by
   an INTERLEAVING - a cancel flag first set after the pipeline's last checkpoint
   - which no static search over the source can surface. (Now inventory defect
   #17, pinned in tests/services/test_indexing_service.py and
   tests/test_ui_reports_success_for_every_terminal_outcome.py.)
2. The scrollbar table said "three of the nine listboxes" and then enumerated
   EIGHT, and its no-scrollbar row claimed content was "unreachable" while
   another section of the same document said the same widgets scroll with the
   mouse wheel. That is an arithmetic mismatch plus an internal contradiction -
   both entirely inside the document.

So the document needs a check whose subject is the document. That is this file.

WHAT IT VERIFIES
----------------
* every source citation names a real file and a line NUMBER that exists in it;
* every internal cross-reference (section, defect number, test name) resolves;
* the defect table is numbered 1..n without gaps;
* the listbox and print-site counts are re-derived from the source rather than
  trusted, and no stated count contradicts its own enumeration;
* a short, explicit list of claims already found false cannot reappear verbatim;
* absolute claims ("never", "dead code", "none of ... are written") must carry a
  justification TOKEN - a test citation, the word "pinned", or a `file.py:N`
  derivation - in the same block.

WHAT IT DOES NOT VERIFY
-----------------------
Read this before treating a green run as evidence that a claim is true.

* It does not check that a citation SUPPORTS the sentence it is attached to.
  Both the citation check and the justification check test for presence: does
  the file exist, is the line number within it, is a token there. Neither ever
  reads the cited line. Any real line number in any real file satisfies both.
* There is NO general contradiction detector, and none is attempted - a
  semantic checker over English prose is not achievable here. The two
  contradiction checks below are hand-written for two specific known pairs
  (scrolling; the refuted-claim list). A new claim that contradicts a distant
  section passes.
* It cannot settle an ORDERING claim at all. Those are refuted by an
  interleaving, which is not present in the text in any form.

The concrete demonstration, from the round-5 review: rewriting the timing-B
paragraph of Sec 2.13 to claim the OPPOSITE of what it claims - "if the run
reached STATUS_INDEXED, none of the four data files are written
(pipeline.py:182)" - passed every check in this file. The citation resolved
(that is all the citation check verifies), the required headings and the
"**IS appended**" marker were still present, and although workflow 34e still
said all four files ARE written, nothing here compares the two. Round 5 added
"none"/"no ... are" to the absolute vocabulary, which closes the narrower half
of that hole; the citation-relevance half is not closable here.

So: this file stops drift, stale references and arithmetic slips. It does not
stop a determined false claim, and it is not a substitute for reading the cited
line. Ordering claims are settled instead by the deterministic timing tests in
tests/services/test_indexing_service.py and
tests/test_ui_reports_success_for_every_terminal_outcome.py, each of which has
been verified to FAIL when the behaviour it pins is changed. The manual pass is
recorded in the PR description.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = ROOT / "docs" / "UI_FEATURE_INVENTORY.md"
UI_DIR = ROOT / "src" / "ui"


@pytest.fixture(scope="module")
def doc():
    return DOC_PATH.read_text(encoding="utf-8")


def _blocks(text):
    """The document as blank-line-separated blocks, table rows split out.

    A table row is its own claim; a paragraph is one claim group. This is the
    unit an "absolute claim needs a justification nearby" check reasons over.
    """
    out = []
    for block in re.split(r"\n\s*\n", text):
        if block.lstrip().startswith("|"):
            out.extend(line for line in block.split("\n") if line.strip())
        else:
            out.append(block)
    return out


# ---------------------------------------------------------------------------
# 1. Citations resolve
# ---------------------------------------------------------------------------

CITATION = re.compile(r"`([A-Za-z0-9_./]+\.py):(\d+)(?:-(\d+))?`")

# Citations deliberately pointing at code as it was on `main`, before the
# service extraction moved it. The document marks every one of them by writing
# "on `main`" immediately after the citation, and that marker is what exempts
# them from the line-count check.
HISTORICAL = re.compile(r"`[A-Za-z0-9_./]+\.py:\d+(?:-\d+)?` on `main`")


def _python_files():
    return [p for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))]


def test_every_source_citation_resolves_to_a_line_that_exists(doc):
    """`file.py:N` and `file.py:N-M` must name a real file with at least M lines.

    Catches the commonest silent drift: code moves, the inventory keeps the old
    coordinates, and a reviewer following the citation lands somewhere else.
    """
    files = _python_files()
    stripped = HISTORICAL.sub("", doc)

    problems = []
    checked = 0
    for match in CITATION.finditer(stripped):
        name, lo, hi = match.group(1), int(match.group(2)), match.group(3)
        hi = int(hi) if hi else lo
        candidates = [p for p in files if str(p).endswith("/" + name) or p.name == name]
        candidates = [p for p in candidates if str(p.relative_to(ROOT)).endswith(name)]
        if len(candidates) != 1:
            problems.append(f"`{name}:{lo}` -> {'no' if not candidates else 'ambiguous'} match")
            continue
        checked += 1
        n_lines = len(candidates[0].read_text(encoding="utf-8").splitlines())
        if hi > n_lines:
            problems.append(
                f"`{name}:{match.group(2)}"
                f"{'-' + match.group(3) if match.group(3) else ''}` "
                f"but {candidates[0].relative_to(ROOT)} has only {n_lines} lines"
            )

    assert checked >= 40, f"only {checked} citations checked; the regex stopped matching"
    assert problems == [], "stale source citations in the inventory: " + "; ".join(problems)


def test_every_section_reference_resolves_to_a_heading(doc):
    """`§2.13` must be a heading in this document. `spec §3.2` refers to the
    separate spec document and is excluded."""
    headings = set(re.findall(r"^#+\s+(\d+(?:\.\d+)*)\.?\s", doc, re.M))
    assert len(headings) > 20, f"heading scan found only {headings}"

    refs = set(re.findall(r"(?<!spec )§(\d+(?:\.\d+)*)", doc))
    assert refs, "no section references found; the regex stopped matching"
    dangling = sorted(r for r in refs if r not in headings)
    assert dangling == [], f"§ references with no such heading: {dangling}"


def _defect_numbers(doc):
    """The `#` column of the §4 defect table."""
    start = doc.index("## 4. Known defects")
    end = doc.index("## 5. Workflow checklist")
    return {int(m) for m in re.findall(r"^\|\s*(\d+)\s*\|", doc[start:end], re.M)}


def test_every_defect_reference_resolves_to_a_defect_row(doc):
    """`§4 #17`, `defect #17`, `defects #1, #3` must name rows that exist."""
    numbers = _defect_numbers(doc)
    assert numbers, "no defect rows found"

    refs = set()
    for pattern in (r"§4 #(\d+)", r"[Dd]efects? #(\d+)", r"§4 #\d+(?:, ?#(\d+))+"):
        refs.update(int(m) for m in re.findall(pattern, doc) if m)
    # "§2.13, §4 #16, #17" - the trailing bare "#17" belongs to the same list.
    for tail in re.findall(r"§4 #\d+((?:, ?#\d+)+)", doc):
        refs.update(int(m) for m in re.findall(r"#(\d+)", tail))

    assert refs, "no defect references found; the regex stopped matching"
    dangling = sorted(r for r in refs if r not in numbers)
    assert dangling == [], f"defect references with no such row: {dangling}"


def test_the_defect_table_is_numbered_without_gaps(doc):
    numbers = sorted(_defect_numbers(doc))
    assert numbers == list(range(1, len(numbers) + 1)), f"defect numbering is not 1..n: {numbers}"


def test_every_cited_test_exists(doc):
    """`tests/x.py::test_y` must name a test that is really there.

    The inventory uses these citations as evidence that a claim is pinned. A
    citation to a test that was renamed or deleted is evidence of nothing.
    """
    refs = set(re.findall(r"(tests/[A-Za-z0-9_/]+\.py)::(\w+)", doc))
    assert refs, "no test citations found; the regex stopped matching"

    missing = []
    for rel, name in sorted(refs):
        path = ROOT / rel
        if not path.exists():
            missing.append(f"{rel} does not exist")
        elif f"def {name}(" not in path.read_text(encoding="utf-8"):
            missing.append(f"{rel} has no {name}")
    assert missing == [], "; ".join(missing)


def test_abbreviated_test_citations_name_a_real_test(doc):
    """Rows written `…::test_name` inherit the file from the row above it; check
    the test name exists somewhere under tests/."""
    names = set(re.findall(r"`…::(\w+)`", doc))
    if not names:
        pytest.skip("no abbreviated citations in the document")
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").rglob("*.py"))
    missing = sorted(n for n in names if f"def {n}(" not in corpus)
    assert missing == [], f"abbreviated citations naming no test: {missing}"


# ---------------------------------------------------------------------------
# 2. Counts are re-derived from the source, not trusted
# ---------------------------------------------------------------------------

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}


def _listbox_ground_truth():
    """Every `tk.Listbox(...)` in src/ui, and whether its frame has a Scrollbar.

    Returns ``(with_scrollbar, without_scrollbar)`` as lists of "file.py:line".

    A listbox counts as having a scrollbar widget when its own construction
    passes `yscrollcommand=` - that is the only wiring in this codebase, and it
    is what makes a scrollbar visible and draggable. `library_tab` sets it in a
    following `.config()` call instead, which is handled by also accepting a
    `yscrollcommand` assignment naming the same attribute.
    """
    with_sb, without_sb = [], []
    for path in sorted(UI_DIR.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            if "Listbox(" not in line:
                continue
            # The constructor call may span several lines; take until the
            # brackets balance, then look a few lines further for a .config().
            chunk = "\n".join(lines[i - 1:i + 12])
            wired = "yscrollcommand" in chunk
            (with_sb if wired else without_sb).append(f"{path.name}:{i}")
    return with_sb, without_sb


def test_the_listbox_table_matches_an_actual_enumeration_of_the_source(doc):
    """The exact defect an independent review caught: the prose said "three of
    the nine" and the table listed eight, because SimplePicker was missing.

    Both halves are re-derived here. The table must have one row per listbox
    that really exists in src/ui, with the right scrollbar verdict, and the
    sentence above it must state the same totals.
    """
    with_sb, without_sb = _listbox_ground_truth()
    total = len(with_sb) + len(without_sb)

    # a) The sentence's numbers.
    sentence = re.search(
        r"(\w+) of the app's \*\*(\w+)\*\* listboxes\s*\n?\s*have a scrollbar widget and (\w+) do not",
        doc,
    )
    assert sentence, "the listbox count sentence is gone or was reworded; update this test with it"
    stated_with, stated_total, stated_without = (
        WORD_NUMBERS[w.lower()] if w.lower() in WORD_NUMBERS else int(w)
        for w in sentence.groups()
    )
    assert stated_total == total, f"document says {stated_total} listboxes, source has {total}"
    assert stated_with == len(with_sb), (
        f"document says {stated_with} have a scrollbar, source has {len(with_sb)}: {with_sb}"
    )
    assert stated_without == len(without_sb), (
        f"document says {stated_without} have none, source has {len(without_sb)}: {without_sb}"
    )
    assert stated_with + stated_without == stated_total, (
        "the sentence's own arithmetic does not add up"
    )

    # b) The table's rows, one per listbox, each with the right verdict.
    rows = re.findall(
        r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*`([a-z_]+\.py):(\d+)`\s*\|\s*\*\*(yes|no)\*\*[^|]*\|",
        doc, re.M,
    )
    assert len(rows) == total, (
        f"the table enumerates {len(rows)} listboxes but src/ui has {total}. "
        f"with scrollbar: {with_sb}; without: {without_sb}"
    )
    assert [int(n) for n, *_ in rows] == list(range(1, total + 1)), "table rows are misnumbered"

    tabled_with = {f"{f}:{n}" for _, _, f, n, verdict in rows if verdict == "yes"}
    tabled_without = {f"{f}:{n}" for _, _, f, n, verdict in rows if verdict == "no"}
    assert tabled_with == set(with_sb), (
        f"table's scrollbar column disagrees with the source. "
        f"table says yes for {sorted(tabled_with)}, source says {sorted(with_sb)}"
    )
    assert tabled_without == set(without_sb), (
        f"table says no for {sorted(tabled_without)}, source says {sorted(without_sb)}"
    )


def test_no_stated_count_contradicts_its_own_arithmetic(doc):
    """General form of the defect above: "N of the M ... and K do not" must
    satisfy N + K == M wherever the document says it."""
    bad = []
    for match in re.finditer(
        r"\b(\w+) of the (?:app's )?\**(\w+)\**\s+(\w[\w\s`.]*?)\s+"
        r"(?:have|has|are|scroll)[^.]*?\band (\w+) (?:do not|does not|don't)",
        doc,
    ):
        try:
            n, m, k = (WORD_NUMBERS.get(g.lower(), None) for g in
                       (match.group(1), match.group(2), match.group(4)))
        except Exception:  # pragma: no cover - defensive
            continue
        if None in (n, m, k):
            continue
        if n + k != m:
            bad.append(f"{match.group(0)[:90]!r}: {n} + {k} != {m}")
    assert bad == [], "; ".join(bad)


# ---------------------------------------------------------------------------
# 3. Claims found false must not come back
# ---------------------------------------------------------------------------

# Each entry: (regex, why it is false). These are the exact wordings an
# independent review refuted. A rewrite that reintroduces the claim in these
# words fails here.
REFUTED = [
    (
        r"content past the visible height is unreachable",
        "Tk's default Listbox class bindings include <MouseWheel>; a missing "
        "scrollbar widget removes the affordance, not the reachability. "
        "src/ui never rebinds or unbinds them.",
    ),
    (
        r"cancellation lines are dead code",
        "Both are reachable. cancel_check is read only at pipeline.py:182, so a "
        "flag first set after the last checkpoint is never observed and "
        "reindex_window takes its cancel branch. Inventory defect #17.",
    ),
    (
        r".{0,60}\bdoubled\b.{0,180}",  # a window, so the exemption words are visible
        "sanitise_filename_part drops '.', so the only dot is the extension, "
        "and it cannot survive a [:200] slice that only runs when the name is "
        "longer than 200 characters.",
        ("impossible", "cannot", "never", "previously claimed"),
    ),
    (
        r"the only listbox in the app with a working scrollbar",
        "Three listboxes have a scrollbar widget: library_tab, "
        "DeletedTracksDialog and TrackSelectorDialog.",
    ),
    (
        r"the only key in use",
        "first_run_complete is written at onboarding.py:587 and read at "
        "onboarding.py:613.",
    ),
]


def test_no_refuted_claim_has_returned(doc):
    """A refuted claim is not a typo to fix once; it is a sentence that keeps
    getting rewritten back in because it sounds right. Each entry above is the
    exact wording an independent review knocked down.

    An optional third element lists words that mark the sentence as the
    CORRECTION rather than the claim - so "a doubled `.m3u` is impossible" is
    allowed while "can leave a doubled extension" is not.
    """
    found = []
    for entry in REFUTED:
        pattern, why = entry[0], entry[1]
        exempt = entry[2] if len(entry) > 2 else ()
        for match in re.finditer(pattern, doc, re.I | re.S):
            text = match.group(0)
            if any(word.lower() in text.lower() for word in exempt):
                continue
            line = doc[:match.start()].count("\n") + 1
            found.append(f"line {line}: {text.strip()!r} - {why}")
    assert found == [], "\n".join(found)


def test_the_source_comments_that_repeated_refuted_claims_stay_corrected():
    """The same false statements also lived in code comments. Both were
    corrected; this stops either drifting back independently of the document."""
    settings_store = (ROOT / "src/services/settings_store.py").read_text(encoding="utf-8")
    assert "the only key in use" not in settings_store.lower()
    assert "first_run_complete" in settings_store

    exporter = (ROOT / "src/recommendations/playlist_exporter.py").read_text(encoding="utf-8")
    assert "can leave a doubled" not in exporter.lower()
    assert "impossible" in exporter.lower()


def test_the_document_does_not_contradict_itself_about_scrolling(doc):
    """The internal contradiction that made the round-3 correction wrong.

    §2.4 has always said the Explore list has "no scrollbar widget (mouse-wheel
    scrolling only)". Any section claiming a missing scrollbar makes content
    unreachable contradicts it. Both statements are about the same widget class,
    so at most one of them can be true - and the mouse-wheel one is.
    """
    assert "mouse-wheel scrolling only" in doc, (
        "the mouse-wheel statement in §2.4 was removed; it is the counterexample "
        "that refutes the 'unreachable' claim"
    )
    for match in re.finditer(r"[^.\n]*unreachable[^.\n]*", doc):
        sentence = match.group(0)
        assert "does not make content unreachable" in sentence or "not" in sentence.lower(), (
            f"unqualified unreachability claim: {sentence.strip()!r}"
        )


# ---------------------------------------------------------------------------
# 4. Absolute claims must carry a justification
# ---------------------------------------------------------------------------

ABSOLUTE = re.compile(
    r"\b(dead code"
    r"|never (?:appended|reached|runs?|fires?|happens?|shown|called|written|observed)"
    r"|unreachable|impossible|cannot happen|is never|are never|can never"
    # Added in round 5. A reviewer defeated this guard with "none of the four
    # data files are written" - and the vocabulary above did not recognise that
    # as an absolute claim at ALL. Negation by "none"/"no X are"/"nothing is" is
    # exactly as absolute as "never", and was a cheap miss.
    r"|none of\b"
    r"|no [a-z ]{0,30}?(?:are|is) "
    r"(?:written|appended|queued|emitted|shown|rendered|reached|called|observed|created|set)"
    r"|nothing is (?:written|appended|queued|emitted|shown|reached|called|observed))\b",
    re.I,
)

# A block satisfies the requirement if it cites a test, says it is pinned, or
# derives the claim in place (a file:line citation, or an explicit refutation of
# a previous claim).
# NOTE the `[a-z_/]+` in the derivation branch: the document cites both bare
# filenames (`pipeline.py:182`) and path-qualified ones
# (`processing/pipeline.py:182`), and both are equally good as a derivation.
JUSTIFIED = re.compile(
    r"(tests/[A-Za-z0-9_/]+\.py|`…::|[Pp]inned|`[a-z_/]+\.py:\d+|contrary to what|"
    r"class bindings|re-derived)",
)


def _plain(block):
    """A block with markdown emphasis markers removed.

    ABSOLUTE reasons about WORDS, and this document bolds them constantly. Row
    34b writes "**no** data files are written", where the `**` sits between
    "no" and the space the pattern needs, so the claim slipped past the
    vocabulary purely because of its formatting. Strip the markers first.
    """
    return re.sub(r"[*_]{1,3}", "", block)


def test_every_absolute_claim_carries_a_justification_in_its_own_block(doc):
    """The lesson of defect #17, mechanised as far as it goes.

    An existential claim ("string X is at line N") is settled by one grep. An
    absolute one ("never", "dead code", "none of ... are written") can only be
    settled by argument, and it is exactly the kind that survives review by
    being plausible. So every block making one must show its working in the
    same block: a test citation, the word "pinned", or a derivation.

    THE LIMIT, stated so nobody relies on more than this delivers. The check is
    for the PRESENCE of a justification token, not its relevance. A `file.py:N`
    citation satisfies it as long as line N exists in that file - the citation
    check never reads the cited line, and this check never reads it either. So
    a false claim that carries a real-but-irrelevant line number passes both.
    That is how a reviewer defeated this file in round 5, and it is not fixable
    by widening either regex; it needs a human reading the cited line.

    This does not make the claims TRUE. It makes an UNSUPPORTED one visible.
    """
    unjustified = []
    for block in _blocks(doc):
        if ABSOLUTE.search(_plain(block)) and not JUSTIFIED.search(block):
            unjustified.append(" ".join(block.split())[:160])
    assert unjustified == [], (
        "absolute claims with no test citation or derivation in the same block:\n  "
        + "\n  ".join(unjustified)
    )


def test_the_absolute_vocabulary_recognises_the_claims_that_have_defeated_it(doc):
    """A vocabulary that cannot SEE a claim cannot ask it to justify itself.

    In round 5 a reviewer rewrote the timing-B paragraph to say "none of the
    four data files are written" and every check here passed. Two things were
    wrong, and only one of them is fixable: "none"/"no X are"/"nothing is" were
    absent from the vocabulary (fixed, and pinned below), and the block still
    carried a real `pipeline.py` citation, which is all a justification token
    has to be (not fixable here - see the docstring above).

    This test exists so the vocabulary cannot silently narrow back. It reasons
    over phrases, not over the document, so it keeps working when the document
    is rewritten.
    """
    recognised = (
        "none of the four data files are written",
        "no data files are written",
        "no playlist is written for it",
        "nothing is written",
        "the branch is dead code",
        "the line is never appended",
        "this is unreachable",
    )
    for phrase in recognised:
        assert ABSOLUTE.search(phrase), f"absolute claim NOT recognised: {phrase!r}"

    # ... and formatting must not hide one. Row 34b writes "**no** data files
    # are written", where the emphasis markers sit exactly where the pattern
    # expects a space.
    for phrase in recognised:
        emphasised = phrase.replace(" ", "** **", 1)
        assert ABSOLUTE.search(_plain(emphasised)), (
            f"absolute claim hidden by markdown emphasis: {emphasised!r}")

    # ... and it must not fire on the ordinary positive statements the document
    # is mostly made of, or every block would need a justification token.
    ignored = (
        "all four data files are written",
        "the log pane shows two cancellation lines",
        "the window reports a cancellation",
        "a piano roll is drawn for each note",
    )
    for phrase in ignored:
        assert not ABSOLUTE.search(phrase), f"false positive on: {phrase!r}"


def test_the_cancellation_section_describes_both_timings(doc):
    """Defect #17 in the document's own words. If a future edit collapses this
    back to a single universal statement, the acceptance contract for PR 3 is
    wrong again in exactly the way it was wrong before.
    """
    start = doc.index("### 2.13")
    end = doc.index("## 3. Cross-cutting rules")
    section = doc[start:end]

    for required in (
        "Two cancellation timings",
        "Timing A",
        "Timing B",
        "Timing C",
        "⚠️ Indexing cancelled by user",
        "processing/pipeline.py:182",
    ):
        assert required in section, f"§2.13 no longer mentions {required!r}"

    assert "**IS appended**" in section, (
        "§2.13 must state that ⚠️ Indexing cancelled by user IS appended under "
        "timing B; the previous version claimed it never was"
    )


def test_the_workflow_checklist_covers_both_cancellation_timings(doc):
    """34a/34b describe timing A. PR 3 is checked against this table, so timing
    B needs rows of its own or the race is untested by the manual pass."""
    start = doc.index("## 5. Workflow checklist")
    rows = {m.group(1): m.group(0) for m in
            re.finditer(r"^\|\s*(3[0-9][a-f]?)\s*\|.*$", doc[start:], re.M)}

    assert "34a" in rows and "timing A" in rows["34a"]
    assert "34b" in rows and "timing A" in rows["34b"]
    late = [k for k, v in rows.items() if "timing B" in v]
    assert len(late) >= 2, f"only {late} cover timing B; the late-cancel race needs its own rows"
