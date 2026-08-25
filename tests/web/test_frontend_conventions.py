"""The frontend's design constraints, mechanised.

There is no automated test of the rendered UI in this PR - introducing a
browser-automation dependency to test a handful of hand-written files is not
worth the packaging risk, and the visual pass is done by hand in Safari. But
several of the constraints are not visual at all: "tokens first", "no
hard-coded hex", "respect prefers-reduced-motion", "real focus rings", "4.5:1
contrast" are each easy to claim, easy to skip, and readable in the source.

HOW TO READ A GREEN RUN OF THIS FILE. What these assertions run over is an
APPROXIMATION of the source, derived from it by regex - stripped text, matched
patterns, brace-counted regions - together with an AST of this file itself.
Nothing here runs a browser, resolves a cascade or lays anything out. So a
green run is EVIDENCE that the source says what these patterns look for. It is
not proof of what the page does. Where a check's approximation is known to
part company with the browser, the note above `stylesheets()` records it - and
that note declares its list of holes NON-EXHAUSTIVE, which is meant literally:
a hole absent from it is unlisted, not closed.

It cannot tell you whether the result looks good.
"""

import ast
import colorsys
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent.parent / "src" / "web" / "static"
CSS = STATIC / "css"
JS = STATIC / "js"

TOKENS_CSS = CSS / "tokens.css"
APP_CSS = CSS / "app.css"
INDEX_HTML = STATIC / "index.html"

COMMENT = re.compile(r"/\*.*?\*/", re.S)
JS_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\w])//[^\n]*", re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _without(pattern, text):
    r"""`text` with every `pattern` match replaced by a SPACE, not deleted.

    A COMMENT SEPARATES TOKENS. CSS's tokenizer consumes a comment and emits
    nothing, so `posi/**/tion` is two identifiers - `posi` and `tion` - and

        .exportv__progress { posi/**/tion: sticky; bottom: calc(...); }

    is an INVALID declaration that a browser drops. The block returns to
    normal flow and the Stop button scrolls out of reach. Deleting the comment
    instead of separating with it produced `position: sticky` here, so the
    guard read a declaration that does not exist - the same defect as reading
    a commented-out one as live, in the opposite direction, and green when it
    was found. `sti/**/cky` and `var(--space/**/-6)` were the same.

    So the substitution is a space, which is what a comment IS to a tokenizer,
    and the newlines the comment spanned are kept after it so the line numbers
    in a refusal still point at the right line.

    Not a refusal, unlike most of this round: this is not a construct the file
    declines to model, it is a stripper that was wrong about what a comment
    does. `calc(1px/**/+2px)` types as two adjacent operands both ways, and
    `.a/**/b` is a rule the browser drops and this file now merely fails to
    match - the safe direction.
    """
    return pattern.sub(
        lambda match: " " + "\n" * match.group().count("\n"), text
    )


def without_js_comments(text):
    return _without(JS_COMMENT, text)


def without_html_comments(text):
    return _without(HTML_COMMENT, text)


HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
COLOUR_FUNCTION = re.compile(r"\b(?:rgba?|hsla?|lab|lch|oklch|color)\s*\(")


def read(path):
    return path.read_text(encoding="utf-8")


def without_comments(text):
    return _without(COMMENT, text)


class _CannotModel(AssertionError):
    """The source uses syntax whose meaning this file cannot compute.

Four rounds on this file have now established the same thing four
    times: a guard that MIS-READS a construct is worse than one that refuses
    it, because the mis-read is silent and the refusal is not. A maintainer
    whose CSS is refused gets a failure that names the construct, and either
    rewrites one declaration or teaches the reader the construct. A maintainer
    whose CSS is mis-read gets a dead accessibility feature and a green suite -
    which is what happened with `!important` and with a semicolon inside a
    string, and what this class exists to stop happening a third time.

    What each refusal can name differs, and is worth knowing before relying on
    one: the six raised from `_splittable` are handed a `where` and compute a
    line, and name both. `_rule` is handed a `where` and names it, with the
    rule's selector text, but has no line. `_declaration`, `_custom_properties`
    and `_important_declaration` are handed neither and name the property and
    its value only.

    It subclasses AssertionError so pytest reports it as a failing check
    rather than an error in the tests, which is what it is: the stylesheet
    does not meet a constraint this file imposes.
    """


#: A quote opens a CSS string, and a string can contain ANYTHING - `;`, `}`,
#: `{`, a whole fake ruleset.
_QUOTE = re.compile(r"""["']""")

#: CSS WHITESPACE IS FIVE CHARACTERS: space, tab, line feed, form feed and
#: carriage return. Python's `\s` is a much larger set on a `str` - it also
#: matches U+000B, U+001C-U+001F, U+0085, U+00A0, U+3000 and every other
#: Unicode space - and the declaration-boundary patterns here are built out of
#: `\s*`: `_DECLARATION_BOUNDARY`, the `\s*:\s*` in `_declarations_of`,
#: `_CUSTOM_DECLARATION`, `_ANY_DECLARATION` and `_MIXED_CASE_PROPERTY`. So
#:
#:     .exportv__progress {<U+00A0>position: sticky; ... }
#:
#: reads here as a declaration and does not exist in the browser: an
#: identifier cannot start with U+00A0, so the declaration is invalid, it is
#: dropped, the initial `auto` applies and the block scrolls out of reach.
#: Five different characters did that, silently, with the guard green.
#:
#: The pattern is the AGREED SET, written as a character class rather than as
#: a list of the ways to disagree - the disagreements are a Unicode table and
#: the agreement is four control characters and printable ASCII. It also
#: forecloses everything else non-ASCII does to a text comparison at the same
#: time: a homoglyph class name, a zero-width joiner inside a selector, an
#: RTL override. None of those is enumerable and none of them survives this.
#:
#: Comments are stripped before this runs, so the `§`, `·`, `–` and emoji in
#: the two sheets' prose are unaffected; what is left has to be ASCII.
_ALIEN_CHARACTER = re.compile(r"[^\t\n\f\r\x20-\x7e]")

#: An UNTERMINATED comment runs to the end of the stylesheet in CSS, and
#: matches nothing at all in `COMMENT`, whose `.*?\*/` needs a terminator. So
#:
#:     /* a browser ignores everything from here { }
#:     .exportv__progress { position: sticky; ... }
#:
#: leaves the rule live for this file and commented out for the browser. The
#: `{ }` is what makes it work: it resets the rule splitter so the selector
#: after it comes out clean. Without the brace pair the leftover comment text
#: lands in the selector and the rule is reported unevaluated, which is why
#: this looked safe.
#:
#: Anything left of a comment delimiter after stripping means the stripper and
#: the browser disagree about where the source ends, so it is refused.
_COMMENT_REMNANT = re.compile(r"/\*|\*/")

#: The at-rules these stylesheets are allowed to use, which is the same thing
#: as the at-rules this file models.
#:
#: `@media` it models by treating everything inside one as CONDITIONAL - see
#: `_rule`, which will not merge a nested rule, and
#: `test_reduced_motion_is_respected_at_the_token_level`, which reads INTO one
#: block deliberately and bounds itself to it. `@keyframes` it models the same
#: way: its `from`/`to` rules are nested, so they are never read as page rules,
#: and their durations are enumerated for a ceiling rather than resolved.
#:
#: EVERYTHING ELSE IS REFUSED, and the two that matter are why:
#:
#:   * `@import` pulls in a stylesheet this file never opens. Every rule in it
#:     is invisible here, so `.setc__status { position: static }` in the
#:     imported sheet undoes the checked one with the guard green.
#:   * `@layer` reorders the cascade wholesale. A rule in a later layer beats
#:     an earlier layer's rule regardless of order or specificity, which is
#:     the same "precedence this file cannot compute" that `!important` is.
#:
#: `@font-face`, `@property`, `@page`, `@container`, `@supports` and the rest
#: are refused too, not because they are dangerous but because refusing what
#: is not modelled is the rule. Adding one is one line here plus whatever
#: modelling it needs.
_AT_RULE = re.compile(r"@([\w-]+)")
MODELLED_AT_RULES = ("media", "keyframes")

#: A backslash in CSS starts an IDENTIFIER ESCAPE, and an escape means one
#: element can be selected by names that share no characters.
#: `.exportv\_\_progress` and `.\65 xportv__progress` are both the class
#: `exportv__progress`; `_mentions` and the selector-list comparison in `_rule`
#: see three different strings. So a later
#:
#:     .exportv\_\_progress { position: static; }
#:
#: undoes the checked rule and is invisible here - found by probing for it
#: after the seventh, and green when it was found.
#:
#: Unescaping is not the fix. It needs the escape grammar, the whitespace rule
#: that terminates a hex escape, and the surrogate rules - which is the same
#: "parse it properly" answer that has now failed at every layer of this file.
#: A backslash is refused, and these sheets contain none.
_ESCAPE = re.compile(r"\\")

#: A property NAME in CSS is ASCII case-insensitive: `POSITION: static` and
#: `position: static` are the same declaration to a browser, and the NAME
#: lookups here are case-sensitive - `_declarations_of` interpolates
#: `re.escape(name)` into a pattern compiled with no flags, and so do
#: `_CUSTOM_DECLARATION` and `_ANY_DECLARATION`. So a later
#: `.exportv__progress { POSITION: static; }` beat the checked rule while
#: `_declaration("position", ...)` never saw it - found alongside the escape
#: above, and green.
#:
#: Case-folding is NOT the fix, and this is the one place where "just handle
#: it" is actively wrong rather than merely risky: a CUSTOM property name is
#: case-SENSITIVE, so `--Motion-Fast` and `--motion-fast` are different
#: properties. Folding with `re.I` would make the boundary lookup answer for
#: the wrong one - a new instance of the exact defect the boundary exists to
#: fix. Folding only non-custom names means telling them apart, which is more
#: modelling and more room to be wrong.
#:
#: So a property name that is not already lowercase is refused. It costs
#: nothing, and the measurement is stated with its method because the number
#: this line carried before ("69") was the count at nesting depth 0 while the
#: refusal scans the sheet at every depth. Counted as the distinct non-custom
#: names `_ANY_DECLARATION` finds in the blocks `_rules` emits for app.css and
#: tokens.css: 74 at any depth, of which 69 are in top-level rules. All 74 are
#: lowercase. `css()` runs `_splittable` on
#: every sheet it reads, so a mixed-case name appearing in either one raises
#: `_CannotModel` out of the first `css(APP_CSS)` or `css(TOKENS_CSS)` that
#: touches it. Nobody writes `POSITION:` by accident.
#: The `(?!--)` is the case-sensitivity of custom properties, from the other
#: side: `--Motion-Fast` is a DIFFERENT property from `--motion-fast`, not a
#: mis-spelling of it, so refusing it would be a false red. A vendor prefix
#: (`-WebKit-transform`) is a single dash and is folded like any other
#: property name, so it is refused.
_MIXED_CASE_PROPERTY = re.compile(r"(?:\A|[{};])\s*(?!--)([a-zA-Z-]*[A-Z][a-zA-Z-]*)\s*:")


def _splittable(text, where=None):
    r"""`text`, or a refusal if this file cannot split it into declarations.

    THE SECOND CLOSED-FORM REFUSAL IN THIS FILE, and it is the same shape as
    the first. Every declaration lookup here ends in a `[^;{}]` value or a
    `([^{}]+)\{([^{}]*)\}` rule split, and both of those read the CHARACTERS
    `;`, `{` and `}` as structure. Inside a CSS string they are not structure,
    they are content:

        .exportv__progress {
          content: "x; position: sticky; bottom: calc(var(--space-6) * -1);";
        }

    splits into three declarations that say the block is stuck to the bottom
    of the scrollport, and the rule can be emptied of every real sticky
    declaration with the guard still green. That was reported, live, in round
    6. `content: "{}"` is worse: it hides a whole rule from the rule splitter,
    so a later rule redeclaring `position` becomes invisible.

    The fix is NOT to split correctly. A correct splitter needs the string
    grammar, the escape grammar and the url() token, and every previous round
    that answered an evasion by handling it better left the next spelling
    open. The refusal is one line: if the region contains a quote at all, this
    file does not know where its declarations begin, and says so.

    IT IS NOT COMPLETE, which is what this used to claim. The url() token in
    that list is unquoted and unmodelled, so
    `background-image: url(data:x;position:sticky;bottom:0;);` does exactly
    what the string above does, with no quote for this to catch - evasion 1 in
    the boundary note above `stylesheets()`. Refusing a quote closes the
    spelling it names, not the class.

    What it costs, said plainly: `content: "→"` and `font-family: "Inter"` are
    legitimate CSS that these stylesheets may no longer contain. That is the
    trade, taken deliberately - see the note in tokens.css, where the font
    stacks are written as identifier sequences for exactly this reason.

    AND THE SAME REFUSAL, five more times, for five more things a browser
    reads differently from a regex. Each was found by probing for it after the
    two above were reported, each was green when it was found, and each is one
    line to refuse and a grammar to parse:

      * `MODELLED_AT_RULES` - an `@import` is a stylesheet this file never
        opens and a `@layer` is a cascade it cannot rank;
      * `_ESCAPE` - `.exportv\_\_progress` is the same class as
        `.exportv__progress` and shares almost no characters with it;
      * `_MIXED_CASE_PROPERTY` - `POSITION` is the same property as `position`;
      * `_ALIEN_CHARACTER` - Python's `\s` matches characters CSS does not
        treat as whitespace, so a U+00A0 makes a declaration that is live here
        and invalid there;
      * `_COMMENT_REMNANT` - an unterminated comment ends the sheet for the
        browser and ends nothing for `COMMENT`.
    """
    unmodelled = [
        (match.group(1), text.count("\n", 0, match.start()) + 1)
        for match in _AT_RULE.finditer(text)
        if match.group(1).lower() not in MODELLED_AT_RULES
    ]
    if unmodelled:
        name, line = unmodelled[0]
        raise _CannotModel(
            f"{where or 'this CSS'} uses `@{name}` (line {line}), which this file "
            f"does not model. `@import` hides a whole stylesheet from it and "
            f"`@layer` reorders the cascade underneath it, so neither can be read "
            f"past - and an at-rule it has never been taught is in the same "
            f"position. Add it to MODELLED_AT_RULES with the handling it needs."
        )

    alien = _ALIEN_CHARACTER.search(text)
    if alien is not None:
        line = text.count("\n", 0, alien.start()) + 1
        raise _CannotModel(
            f"{where or 'this CSS'} contains U+{ord(alien.group()):04X} (line "
            f"{line}), which is not a character CSS and this file agree about. "
            f"CSS whitespace is five characters and Python's `\\s` matches many "
            f"more, so a U+00A0 before a property name reads as a declaration "
            f"here and is invalid - dropped - in the browser. Outside comments "
            f"these stylesheets are ASCII."
        )

    remnant = _COMMENT_REMNANT.search(text)
    if remnant is not None:
        line = text.count("\n", 0, remnant.start()) + 1
        raise _CannotModel(
            f"{where or 'this CSS'} still contains `{remnant.group()}` on line "
            f"{line} after `COMMENT` was applied to it. `COMMENT` needs a `/*` "
            f"and a `*/` to match, so a delimiter left over means one of the "
            f"pair is missing. Close the comment, or delete the stray "
            f"delimiter."
        )

    escape = _ESCAPE.search(text)
    if escape is not None:
        line = text.count("\n", 0, escape.start()) + 1
        raise _CannotModel(
            f"{where or 'this CSS'} contains an identifier escape (line {line}). "
            f"`.exportv\\_\\_progress` is the same class as `.exportv__progress` "
            f"and shares barely a character with it, so a rule spelled that way "
            f"undoes a checked one invisibly. This file compares selectors as "
            f"text and will not guess at the escape grammar: write the name "
            f"unescaped, or teach `_splittable` to unescape."
        )

    mixed = _MIXED_CASE_PROPERTY.search(text)
    if mixed is not None:
        line = text.count("\n", 0, mixed.start()) + 1
        raise _CannotModel(
            f"{where or 'this CSS'} declares `{mixed.group(1)}` (line {line}), and "
            f"a CSS property name is ASCII case-insensitive - so that is the same "
            f"declaration as `{mixed.group(1).lower()}`, which every lookup here "
            f"matches case-sensitively and would miss. Folding is not the answer: "
            f"a CUSTOM property name IS case-sensitive, so folding would make "
            f"`--Motion-Fast` answer for `--motion-fast`. Write it lowercase."
        )

    quote = _QUOTE.search(text)
    if quote is not None:
        line = text.count("\n", 0, quote.start()) + 1
        excerpt = " ".join(text[max(0, quote.start() - 60) : quote.start() + 60].split())
        raise _CannotModel(
            f"{where or 'this CSS'} contains a string ({quote.group()} on line "
            f"{line}: ...{excerpt}...). A string can hold a `;`, a `{{` or a "
            f"`}}`, so this file cannot say where the declarations in it begin "
            f"or end, and it will not guess. Rewrite the value without quotes "
            f"- an unquoted identifier sequence is usually the same thing - or "
            f"teach `_splittable` the string grammar."
        )
    return text


#: How each kind of source is made to look the way a browser sees it. Keyed by
#: suffix, so the reader is chosen by what the FILE IS rather than by how its
#: path happened to be spelled at the call site.
STRIPPERS = {
    ".css": without_comments,
    ".js": without_js_comments,
    ".html": without_html_comments,
}


def source(path):
    """`path` as the browser sees it, whatever kind of source it is.

    The reader for a path that is not known until run time - a glob result, a
    loop variable, an import target resolved from another file. There is no
    default: a suffix with no stripper is an ASSERTION, not a quiet raw read,
    because a reader that passes through what it does not recognise is the
    defect this file has now been wrong about three times over.
    """
    strip = STRIPPERS.get(path.suffix)
    assert strip is not None, (
        f"{path.name} is a kind of source this file has no reader for - add one "
        f"to STRIPPERS rather than reading it raw"
    )
    return strip(read(path))


def css(path):
    """A stylesheet as the BROWSER sees it: comments gone, once, here.

    THE READER THE CSS CHECKS IN THIS FILE ARE WRITTEN TO CALL. What looks for
    the ones that do not is
    `test_no_source_file_is_read_without_its_comments_being_stripped`, which
    runs `_reads` over THIS FILE's own AST and reports a listed `READ_PRIMITIVES`
    name spelled - as a `Name` or an `Attribute` - outside a registered reader.
    That is two literal node shapes, not a proof: the boundary note above
    `stylesheets()` gives the scan's limits, and its evasion 4 is a real raw
    read that the scan does not report. So read this as "the reader, plus a
    scan for the spellings that skip it", not as "every read goes through
    here". That is not tidiness. A commented-out declaration is
    not a declaration - the browser has no such custom property, no such font
    size and no such media block - and a regex reading one as live is a guard
    describing a stylesheet that does not exist. It was wrong in both
    directions at once here: `--ink-secondary` declared ONLY inside a comment
    counted as defined, so a token every component uses could go undefined
    with the suite green; the whole `prefers-reduced-motion` block could be
    commented out with the suite green; and a commented-out font size, a
    commented-out `:root` and a commented-out colour override each produced a
    RED for something the browser never sees.

    Three separate corrections were what let the fourth, fifth and sixth sites
    survive, so there is one correction and it lives at the reader.

    AND THE SAME ARGUMENT, FOR STRINGS. A sheet containing a quote is refused
    here rather than handed on to be split wrongly - see `_splittable`. A
    sheet obtained THROUGH THIS FUNCTION has passed those refusals by the time
    a consumer sees it; the splitters check again for the synthetic sheets the
    tests build by hand, which are passed in as strings and do not come
    through here.
    """
    assert path.suffix == ".css", f"{path.name} is not a stylesheet"
    return _splittable(source(path), path.name)


def js(path):
    """The same, for scripts. A `setProperty('--x')` inside a comment defines
    nothing, and a hex inside one styles nothing - and a `hue: (position - 1)
    * 30` inside one computes nothing, which is the read of `format.js` that
    was still raw when round 5 opened."""
    assert path.suffix == ".js", f"{path.name} is not a script"
    return source(path)


def html(path):
    """And for the markup. `<!-- <main> -->` is not a landmark, a commented-out
    `data-destination` is not a nav item, and a commented-out placeholder
    eyebrow is not a placeholder - all three are claims this file makes about
    index.html by grepping it."""
    assert path.suffix == ".html", f"{path.name} is not markup"
    return source(path)


# ---------------------------------------------------------------------------
# One anchored lookup, for every name this file reads out of a stylesheet
# ---------------------------------------------------------------------------

#: Where a declaration is allowed to BEGIN: the start of the text, or straight
#: after the `{` that opened its block, the `;` that ended the one before it,
#: or the `}` that closed the previous block. Nothing else in CSS is a
#: declaration boundary.
#:
#: Every name lookup in this file used to be a bare `re.search(name)`, which
#: finds the name ANYWHERE - including in the middle of a longer name that
#: declares something else entirely. Three review rounds each found that same
#: defect in a NEW consumer:
#:
#:   * `--not--motion-fast: 1ms` answered a lookup for `--motion-fast`, so both
#:     motion tokens could be renamed out of the reduced-motion block, leaving
#:     the real ones at 110 ms and 170 ms with every test in this file green -
#:     an accessibility guard reporting a preference it does not honour;
#:   * `--not--text-xs: 1px` answered a lookup for `--text-xs`, so a token
#:     resolved to a value the browser never gives it;
#:   * `-webkit-animation-duration` answers one for `animation-duration`, and
#:     `background-position: sticky` one for `position: sticky`.
#:
#: The decoys cannot be enumerated - `--x--motion-fast`, `--another--motion-fast`
#: and so on are unbounded, and a list of them is what the last two rounds
#: patched. The BOUNDARY is finite. So it is written once, here, and the four
#: name patterns interpolate it rather than re-spelling it: `_declarations_of`,
#: `_CUSTOM_DECLARATION`, `_ANY_DECLARATION` and - with its own copy of the
#: same alternation - `_MIXED_CASE_PROPERTY`. The looser matches this file also
#: makes are not name lookups and do not come through here; the boundary note
#: above `stylesheets()` has a list of them that says it is non-exhaustive.
#:
#: Both ends are anchored: the boundary before the name, and the `:` that has
#: to follow it, which is what stops `--motion` matching `--motion-fast`.
_DECLARATION_BOUNDARY = r"(?:\A|[{};])\s*"

#: A declaration value runs to the `;` that ends it or the `}` that ends its
#: block, whichever comes first.
_DECLARATION_VALUE = r"([^;{}]+)"


#: The `!important` flag, which CSS allows to be spaced and cased freely. It
#: is a WELL-DEFINED TOKEN, which is why refusing it is closed-form: there is
#: no need to decide what it means, only to notice that it is there.
_IMPORTANT = re.compile(r"!\s*important\s*$", re.I)


def _declarations_of(name, text):
    """Every value `name` is declared with in `text`, in document order."""
    return [
        value.strip()
        for value in re.findall(
            rf"{_DECLARATION_BOUNDARY}{re.escape(name)}\s*:\s*{_DECLARATION_VALUE}",
            _splittable(text),
        )
    ]


def _declaration(name, text):
    """The value `name` is DECLARED with in `text`, or None if it is not.

    `text` is expected to have come through `css()` already. `_custom_property`
    is the single exception and strips for itself, because it is handed a sheet
    as a STRING by callers that cannot be made to strip first.

    WHAT THIS RETURNS IS THE LAST TEXT MATCHING THE NAME-PLUS-COLON PATTERN,
    which is narrower than the cascade in two separate ways.

    FIRST, SPECIFICITY. `re.search` returned the FIRST match, so a rule that
    declared `bottom` twice, or two rules merged by `_rule`, was read off the
    declaration the browser discards - taking the last fixes that. It does not
    make this the cascade, and this docstring used to say it did. Between
    rules of different specificity, order is not what decides:

        .setc .setc__status { position: static; }   /* written first  */
        .setc__status       { position: sticky; }   /* written second */

    computes `static`, because 0-2-0 beats 0-1-0 whatever the order, and this
    function returns `sticky`.

    SECOND, VALIDITY - and it applies even inside ONE block, where specificity
    cannot differ. CSS drops a declaration whose value is not valid for its
    property AT PARSE TIME, so the winner is the last VALID declaration, not
    the last one written. This function takes the last one written:

        _declaration("position", "position: sticky; position: nonsense;")

    returns `'nonsense'`; a browser discards the second declaration and
    computes `sticky`. Measured, not reasoned.

    IT CANNOT TELL THE DIFFERENCE. Deciding validity needs a grammar per
    property, and there is none here: the one validity test in this file is
    `_type_of`, which types a LENGTH and is called on the `bottom` value by
    `assert_sticks_to_the_bottom` and on `var()` chains by the token checks.
    Every other name resolved through here is returned as written. So read
    this as "the last declaration of the name in this text", and take the gap
    between that and "the declaration that applies" as unmeasured for any name
    `_type_of` does not see.

    THE TWO SHIPPED CALLERS ARE GUARDED ONE LAYER UP, not by this function.
    `_rule` merges only rules whose selector is an exact top-level entry, and
    walks the blocks `_rules` emits, putting any OTHER block whose selector
    text names the selector and declares one of the properties being checked
    into its `unevaluated` list;
    `test_the_set_creator_status_line_cannot_be_scrolled_out_of_reach` and
    `test_the_export_progress_block_cannot_be_scrolled_out_of_reach` both
    assert `unevaluated == []`. Adding the `.setc .setc__status` rule above to
    app.css turns the first one RED with
    `[('.setc .setc__status', ['position'])]`, and the `.exportv` equivalent
    turns the second one red the same way - both measured, not reasoned.

    WHAT THAT DOES NOT COVER: a rule that reaches the element without naming
    the class. `.exportv > div { position: static; }` is not a mention, so it
    is neither merged nor reported, and the guard stays green - measured too.
    Which rules match an element is a selector engine and a document, and this
    file has neither.

    AND `!important` BREAKS THAT, so it is REFUSED rather than modelled. An
    earlier `.setc__status { position: static !important; }` beats a later
    `position: sticky` in the browser, and last-wins reads the sticky one: the
    status line is in normal flow and this file reports it stuck. That was
    live and green in round 6.

    Modelling it properly means the whole cascade - origin, layer, importance,
    specificity, order - and this file has no selector engine and no document.
    Noticing the flag needs one regex. So a name whose declarations include an
    important one is not resolved at all: `_important_declaration` is the
    other half, for the one place in these sheets where `!important` is the
    POINT rather than an accident.
    """
    declared = _declarations_of(name, text)
    if not declared:
        return None
    important = [value for value in declared if _IMPORTANT.search(value)]
    if important:
        raise _CannotModel(
            f"`{name}` is declared `!important` here ({important[-1]!r}), and this "
            f"file resolves a name by taking the LAST declaration - which an "
            f"EARLIER `!important` one beats in the browser. It has no cascade, so "
            f"it will not guess: drop the flag, or read the name with "
            f"`_important_declaration`, which requires it."
        )
    return declared[-1]


def _important_declaration(name, text):
    """The value of `name` where EVERY declaration of it carries `!important`.

    The other half of the refusal above, and deliberately just as strict in
    its own direction. A region where some declarations of a name are
    important and some are not is exactly the cascade this file cannot
    compute, so it is refused from here too rather than resolved by the same
    last-wins rule that `!important` invalidates.

    The reduced-motion block is where the flag is the point:
    `animation-duration: 1ms` without it loses to a component that declares
    its own duration, so the preference would be honoured by the tokens and
    ignored by everything that does not use them.
    """
    declared = _declarations_of(name, text)
    if not declared:
        return None
    ordinary = [value for value in declared if not _IMPORTANT.search(value)]
    if ordinary:
        raise _CannotModel(
            f"`{name}` is declared both with and without `!important` here "
            f"({ordinary[-1]!r} is not flagged), so which one applies is the "
            f"cascade, which this file does not have. Flag them all, or none."
        )
    return _IMPORTANT.sub("", declared[-1]).strip()


def _declares(name, value_pattern, text):
    """Whether `text` declares `name` with a value matching `value_pattern`.

    The pattern is matched against the VALUE, so `^` in it means the start of
    the value rather than the start of a line - `_declares("position",
    r"^sticky\b", ...)` is "position IS sticky", not "sticky appears
    somewhere near a colon".
    """
    declared = _declaration(name, text)
    return declared is not None and re.search(value_pattern, declared) is not None


def _declares_important(name, value_pattern, text):
    """`_declares`, for a name whose declarations all have to be flagged."""
    declared = _important_declaration(name, text)
    return declared is not None and re.search(value_pattern, declared) is not None


_CUSTOM_DECLARATION = re.compile(
    rf"{_DECLARATION_BOUNDARY}(--[a-zA-Z0-9-]+)\s*:\s*{_DECLARATION_VALUE}"
)


def _custom_properties(text):
    """`{name: value}` for every custom property DECLARED in `text`.

    The same anchoring as `_declaration`, from the other side: the dict is
    keyed by the WHOLE name, so `--not--text-xs` is its own key and can never
    answer for `--text-xs`. The LAST declaration in the text wins, and that is
    not the cascade - it is the same gap `_declaration` sets out. This walks
    the whole string it is handed, so a `--motion-fast` inside the
    reduced-motion block and a `--motion-fast` at `:root` land in one dict and
    the later TEXT position decides, while in a browser the applicable rule
    does. The validity half of that gap bites less here, because a custom
    property's value is a token stream accepted at parse time and resolved
    where it is used - but what this returns is still "the last declaration of
    the name in this text", not "the value the element gets".

    And the same two refusals, for the same reason: "later wins" is not the
    cascade when an earlier declaration is flagged, and a sheet with a string
    in it cannot be split into declarations at all.
    """
    declared = {}
    for match in _CUSTOM_DECLARATION.finditer(_splittable(text)):
        value = match.group(2).strip()
        if _IMPORTANT.search(value):
            raise _CannotModel(
                f"`{match.group(1)}` is declared `!important` ({value!r}). This "
                f"dict is built later-wins, which an earlier flagged declaration "
                f"beats in the browser, so it is not built at all."
            )
        declared[match.group(1)] = value
    return declared


def _block_body(match, text):
    """The body between the `{` that `match` ends on and its matching `}`.

    Brace-balanced, so a nested rule does not end the block early - and so a
    block ENDS. Reading "everything from here to the end of the file" is the
    region-shaped version of the same defect the boundary above fixes: a
    declaration written AFTER the `@media` block would answer a lookup meant
    to be scoped inside it.
    """
    opening = match.end() - 1
    assert text[opening] == "{", "the pattern must end on the opening brace"
    depth = 0
    for position in range(opening, len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : position]
    return None


# A `position: sticky` block is only stuck in the block direction if its offset
# RESOLVES TO A LENGTH. `auto` - the initial value, and what every one of the
# CSS-wide keywords falls back to here - leaves no constraint at all, so the
# element stays in normal flow and scrolls away exactly as if the rule had been
# deleted. So does a syntactically invalid value: the declaration is dropped and
# the initial value applies. A guard that only asks whether `bottom:` appears
# cannot tell any of those from a working offset.
#
# This set is a MESSAGE, not a check, and is deliberately not asserted against
# separately: an identifier is rejected by `_Typer.unit` whether or not it is
# listed here, because no bare identifier types as a length. Naming the common
# ones only buys a failure that says WHICH mistake was made. A second assert
# over this set would look like a guard and catch nothing the first did not.
STICKY_KEYWORDS = {
    "auto",
    "inherit",
    "initial",
    "unset",
    "revert",
    "revert-layer",
    "normal",
    "none",
}

LENGTH_UNIT = r"(?:px|rem|em|ex|ch|vh|vw|vmin|vmax|%)"
NUMBER = r"(?:\d+\.?\d*|\.\d+)"
ZERO = re.compile(rf"^[+-]?{NUMBER}$")

# Operands, brackets and operators of a CSS maths expression. ORDER MATTERS
# twice over. A signed dimension has to win over a signed number, and both over
# a bare `+`/`-`, so that `calc(1px -1px)` tokenises as two operands in a row -
# which is what CSS does with it, and why CSS drops it. And `--space-6` has to
# win over the `-` operator, which is why the identifier alternative sits above
# it and why a bare identifier must start with a letter: otherwise the leading
# `-` of every custom property parses as a subtraction.
_VALUE_TOKEN = re.compile(
    rf"""
      (?P<ws>\s+)
    | (?P<open>calc\(|var\(|\()
    | (?P<close>\))
    | (?P<comma>,)
    | (?P<dimension>[+-]?{NUMBER}{LENGTH_UNIT})
    | (?P<number>[+-]?{NUMBER})
    | (?P<ident>--[\w-]+|[a-zA-Z_][\w-]*)
    | (?P<operator>[*/+-])
    """,
    re.VERBOSE | re.IGNORECASE,
)


class _NotALength(Exception):
    """The value does not type as a length, with the reason CSS would drop it."""


def _custom_property(name, tokens):
    """The declared value of `name` in tokens.css, or raise saying it is absent.

    Two boundaries, and both were wrong here in turn.

    COMMENTS are stripped first, because this takes a sheet as a string and
    cannot know whether its caller stripped: a commented-out declaration is not
    a declaration, the browser sees an undefined custom property, the whole
    `bottom` is invalid at computed-value time and the block returns to normal
    flow.

    The NAME is then resolved at a declaration boundary rather than anywhere in
    the text. Unanchored, `--not--text-xs: 1px` answered a lookup for
    `--text-xs` and `text-xs` answered one for `--text-xs`; the second was
    patched at the call site last round, which left the lookup itself still
    wrong for every other spelling.
    """
    declared = _declaration(name, without_comments(tokens))
    if declared is None:
        raise _NotALength(f"uses {name}, which tokens.css does not declare")
    return declared


def _tokenise(value):
    tokens = []
    position = 0
    while position < len(value):
        match = _VALUE_TOKEN.match(value, position)
        if not match:
            raise _NotALength(f"contains `{value[position:]}`, which is not CSS the parser accepts")
        position = match.end()
        kind = match.lastgroup
        if kind != "ws":
            tokens.append((kind, match.group(), match.start()))
        elif tokens:
            tokens[-1] = tokens[-1] + ("space-after",)
    return tokens


class _Typer:
    """CSS's maths type algebra, as much of it as `bottom` can be written with.

    `number` and `length` are the only types that reach here; a percentage is
    folded into `length` because `bottom` takes a `<length-percentage>` and
    resolves one against the containing block either way.

    Anything this does not recognise - `min()`, `env()`, `attr()`, a bare
    identifier - raises rather than passing. That direction is deliberate: an
    unrecognised value can only ever produce a loud false RED, whereas letting
    one through is precisely the hole this replaced.
    """

    def __init__(self, tokens, custom_properties, depth, inside_maths):
        self.tokens = tokens
        self.custom_properties = custom_properties
        self.depth = depth
        # Unitless zero is a length in a property VALUE and a plain number
        # inside `calc()` - `bottom: 0` is valid and `bottom: calc(0)` is not.
        # That is the only thing this flag decides.
        self.inside_maths = inside_maths
        self.at = 0

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self):
        token = self.peek()
        if token is None:
            raise _NotALength("ends in the middle of an expression")
        self.at += 1
        return token

    def sum(self):
        """`a + b` and `a - b`: CSS requires BOTH operands to be the same type."""
        left = self.product()
        while True:
            token = self.peek()
            if token is None or token[0] != "operator" or token[1] not in "+-":
                return left
            # `calc(1px+1px)` and `calc(1px -1px)` are both invalid CSS: the
            # additive operators must be surrounded by whitespace, which is why
            # the tokeniser records what followed each token.
            if "space-after" not in token or "space-after" not in self.tokens[self.at - 1]:
                raise _NotALength(
                    f"has `{token[1]}` without whitespace on both sides, which CSS does not parse"
                )
            self.take()
            right = self.product()
            if left != right:
                raise _NotALength(f"adds a {left} to a {right}, which has no type")
        return left

    def product(self):
        """`a * b` needs one side to be a number; `a / b` needs the divisor to be."""
        left = self.unit()
        while True:
            token = self.peek()
            if token is None or token[0] != "operator" or token[1] not in "*/":
                return left
            operator = self.take()[1]
            right = self.unit()
            if operator == "*":
                if left == "number":
                    left = right
                elif right != "number":
                    raise _NotALength("multiplies a length by a length, which has no type")
            else:
                if right != "number":
                    raise _NotALength(f"divides by a {right}, which CSS does not allow")
        return left

    def unit(self):
        kind, text, *_ = self.take()
        if kind == "dimension":
            return "length"
        if kind == "number":
            if not self.inside_maths and ZERO.match(text) and float(text) == 0:
                return "length"
            return "number"
        if kind == "open" and text.lower() in ("calc(", "("):
            # The restore on the third line is DEAD under this grammar, and is
            # kept as state hygiene rather than as a rule. `outer` is False only
            # when a group is opened from the bare entry in `_type_of`, and that
            # entry consumes exactly one operand and then demands the tokens be
            # finished - so nothing ever reads `inside_maths` again after the
            # restore runs. Every other way in has already set it True. Deleting
            # the restore leaves this file green and no value was found that
            # tells the two apart, which is stated here rather than answered
            # with a test that would only be pinning a fiction.
            outer, self.inside_maths = self.inside_maths, True
            inner = self.sum()
            self.inside_maths = outer
            closing = self.take()
            if closing[0] != "close":
                raise _NotALength(f"has `{closing[1]}` where a `)` belongs")
            return inner
        if kind == "open" and text.lower() == "var(":
            return self.variable()
        if kind == "ident" and text.lower() in STICKY_KEYWORDS:
            raise _NotALength(f"is the keyword `{text}`, which is not a length at all")
        raise _NotALength(f"has `{text}` where a number or a length belongs")

    def variable(self):
        name = self.take()
        if name[0] != "ident" or not name[1].startswith("--"):
            raise _NotALength(f"has `var({name[1]}`, which names no custom property")
        # A fallback is SKIPPED rather than typed. tokens.css is meant to be the
        # one place the offset comes from, so a `var(--x, 0px)` whose `--x` is
        # undeclared stays red here even though a browser would accept it -
        # stricter than CSS, and only ever in the loud direction.
        depth = 1
        while depth:
            token = self.peek()
            if token is None:
                raise _NotALength(f"leaves `var({name[1]}` unclosed")
            if token[0] == "close":
                depth -= 1
            elif token[0] == "open":
                depth += 1
            self.take()
        # A custom property is a token stream substituted where it is used, so
        # it is bare exactly when the `var()` referencing it is.
        return _type_of(
            _custom_property(name[1], self.custom_properties),
            self.custom_properties,
            self.depth + 1,
            bare=not self.inside_maths,
        )


def _type_of(value, custom_properties, depth=0, bare=True):
    """`length`, `number`, or raise `_NotALength` saying why CSS would drop it.

    `bare` says the value sits directly in the property rather than inside a
    maths expression. CSS has no arithmetic outside `calc()`, so a bare value is
    a SINGLE operand - `bottom: 1px + 1px` is as invalid as `bottom: nonsense`.
    """
    if depth > 8:
        raise _NotALength("nests custom properties more than eight deep")
    typer = _Typer(_tokenise(value), custom_properties, depth, inside_maths=not bare)
    result = typer.unit() if bare else typer.sum()
    if typer.peek() is not None:
        raise _NotALength(
            f"has `{typer.peek()[1]}` after the value, and CSS has no arithmetic "
            f"outside calc()"
        )
    return result


def assert_sticks_to_the_bottom(rule_name, declarations):
    """Assert `declarations` really pins its block to the bottom of the scrollport.

    Checks the VALUE, not the presence of the property, and TYPES it rather
    than pattern-matching it: the offset is run through CSS's maths type
    algebra, following every custom property back to `tokens.css`, and the
    expression has to come out a length. That is what distinguishes the shipped
    `calc(var(--space-6) * -1)` from `calc(5)` - both are `calc(...)`, but the
    second types as a NUMBER, so a browser drops the declaration and the
    initial `auto` applies, putting the element back in normal flow.

    WHAT THIS ESTABLISHES, exactly: the declared value is a length under CSS's
    type algebra, with every `var()` in it declared in `tokens.css` and itself a
    length. Nothing more. It does not lay anything out, does not know the
    stacking or scrollport the rule lands in, and cannot tell a useful offset
    from a silly one - where the block actually lands was measured by hand in a
    real browser and recorded in the PR description. Values written with syntax
    this does not model - `min()`, `clamp()`, `env()`, and a trailing
    `!important` - are REJECTED, not passed: erring loud costs a maintainer one
    obvious failure, and erring quiet is what let `calc(5)` through.
    """
    # Anchored, through `_declares` to `_declaration` and its boundary:
    # `background-position` CONTAINS `position`, and a rule declaring
    # `background-position: sticky` is not positioned at all.
    assert _declares("position", r"^sticky\b", declarations), (
        f"{rule_name} is back in the normal flow: {declarations}"
    )

    # Anchored for the reason `test_a_rule_with_no_bottom_offset_is_not_read_off_
    # a_neighbouring_property` records: `padding-bottom` is not `bottom`.
    value = _declaration("bottom", declarations)
    assert value is not None, (
        f"{rule_name} has no bottom offset, so it never sticks: {declarations}"
    )

    try:
        resolved = _type_of(value, css(TOKENS_CSS))
    except _NotALength as why:
        raise AssertionError(
            f"{rule_name} has `bottom: {value}`, which {why} - so the declaration is "
            f"dropped, the initial `auto` applies, and the block scrolls out of reach"
        ) from None

    assert resolved == "length", (
        f"{rule_name} has `bottom: {value}`, which types as a {resolved} rather than a "
        f"length - CSS drops the declaration and the initial `auto` applies, so the "
        f"block returns to normal flow and scrolls out of reach"
    )


def _mentions(selector, entry):
    """Whether one selector in a rule's list names `selector` at all.

    At a name boundary: `.setc__status-line` is a DIFFERENT class and not a
    mention, while `.never-used.setc__status`, `.setc .setc__status` and
    `.setc__status[hidden]` each name it.
    """
    return re.search(rf"{re.escape(selector)}(?![\w-])", entry) is not None


#: Any declaration in a list, as (property, value). Read by
#: `_important_properties`, which is what names the offending properties in
#: `_rule`'s refusal and what
#: `test_the_shipped_sheets_declare_nothing_important_the_guard_resolves`
#: asserts on. The name lookups themselves do not come through here; they stay
#: anchored per name.
_ANY_DECLARATION = re.compile(
    rf"{_DECLARATION_BOUNDARY}(--[a-zA-Z0-9-]+|[a-zA-Z-]+)\s*:\s*{_DECLARATION_VALUE}"
)


def _important_properties(declarations):
    """The names in `declarations` that carry `!important`, in order."""
    return [
        match.group(1)
        for match in _ANY_DECLARATION.finditer(_splittable(declarations))
        if _IMPORTANT.search(match.group(2).strip())
    ]


def _rule(body, selector, properties, where="this stylesheet"):
    r"""(declarations, rules this cannot evaluate) for exactly `selector`.

    THE FIFTH PLACE THIS FILE MATCHED A NAME AS A SUBSTRING. The three rules
    it guards were found with `re.search(rf"\.{name}\s*\{{([^}}]*)\}}")`, and
    a selector is not a substring any more than a declaration is:

      * `.never-used.setc__status { position: sticky; bottom: -2rem; }`
        satisfied that search while applying only to an element carrying both
        classes - so the status line a user sees is in normal flow and the
        guard reports it stuck;
      * so did `.setc .setc__status`, which needs an ancestor;
      * and `re.search` is the FIRST match, so a second
        `.setc__status { position: static; }` further down the sheet undid the
        first one invisibly. The cascade is not "the first rule wins".

    So this iterates the blocks `_rules` emits, in document order, and merges
    a block into `applies` when `selector` is one whole comma-split entry of
    its selector text AND its depth is 0. What `_rules` does not emit is not
    iterated - evasion 2 in the boundary note above `stylesheets()` is a rule
    that is not emitted under its own selector at all.

    THE TOP-LEVEL PART IS THE SEVENTH INSTANCE OF THE SAME DEFECT, found while
    looking for one. A rule inside an at-rule is conditional, and this file
    cannot evaluate the condition - it has no viewport, no media, no UA and no
    layer order. Reading a nested rule as though it were unconditional meant
    the whole shipped rule could be wrapped in

        @media (min-width: 99999px) { .exportv__progress { ... } }

    and the guard reported the block stuck while it applied to nobody: the
    Stop button back below the fold, `2 passed`. `@media print`, `@supports
    (not (all: x))` and a losing `@layer` are the same move.

    A nested rule is therefore never merged. If it names the selector and
    declares something being checked it is handed back as UNEVALUATED, which
    is the channel that already exists for exactly this - "whether this
    applies needs a selector engine and a document, which this does not have".
    If the only rule for the selector was nested, `applies` comes back empty
    and the caller says the rule is gone, which is what a rule matching no
    viewport is.

    `properties` is what the caller is about to assert on. Any OTHER emitted
    block whose selector text names this selector and declares one of them is
    handed back rather than ignored: whether it applies needs a selector
    engine and a document, which this does not have, and passing over what it
    cannot evaluate is the defect rather than the fix. Blocks that name the
    selector and declare none of them
    - `.exportv__progress[hidden] { display: none; }` - change no answer here
    and are not reported.
    """
    applies, unevaluated = [], []
    for selector_text, declarations, depth in _rules(body):
        entries = [entry.strip() for entry in selector_text.split(",")]
        names = selector in entries or any(_mentions(selector, entry) for entry in entries)
        if names:
            flagged = _important_properties(declarations)
            if flagged:
                raise _CannotModel(
                    f"{where}: the rule `{' '.join(selector_text.split())}` "
                    f"names `{selector}` and `_important_properties` found "
                    f"{', '.join(flagged)} carrying `!important` in its "
                    f"declarations. `_declaration` resolves a name by taking the "
                    f"last declaration of it, which is not how `!important` is "
                    f"ranked, so this file will not read past it. Drop the flag, "
                    f"or read the name with `_important_declaration`, which "
                    f"requires it."
                )
        if selector in entries and depth == 0:
            applies.append(" ".join(declarations.split()))
        elif names:
            clashing = sorted(
                name for name in properties if _declaration(name, declarations) is not None
            )
            if clashing:
                where_nested = "" if depth == 0 else f" (nested {depth} deep)"
                unevaluated.append(
                    (" ".join(selector_text.split()) + where_nested, clashing)
                )
    return "; ".join(applies), unevaluated


#: What `assert_sticks_to_the_bottom` and its callers read off a rule, so that
#: another rule redeclaring one of them cannot go unnoticed.
STICKY_PROPERTIES = ("position", "bottom", "background")


# WHAT A GREEN RUN OF THIS FILE MEANS, WRITTEN AS WHAT EACH CHECK LITERALLY
# LOOKS FOR AND IN WHAT LITERAL FORM. This paragraph used to open with a
# universal - "every read of a source file goes through `css()`, `js()`,
# `html()` or `source()`" - and evasion 4, twenty lines below, is a read that
# does not. A sentence quantifying over reads, scripts, rules or tests has been
# falsified by one constructed counterexample in every round this file has had.
# This reads a regex-derived approximation of the source; it cannot carry a
# universal, so it no longer states one.
#
# THE BOUNDARY, AND IT IS MEASURED RATHER THAN ARGUED. Rounds 3, 4, 5 and 6
# each closed this class of hole and each was followed by a new spelling of it.
# Round 7 is this paragraph instead of a seventh regex, because a guard that
# overstates itself is how the previous four happened.
#
# What this file establishes are properties of ITS OWN REGEX-DERIVED
# REPRESENTATION of the source, and nothing beyond them:
#
#   * PYTHON READS: `_reads` walks THIS FILE's AST and, outside a registered
#     reader, reports a `Name` spelling one of `READ_PRIMITIVES` or
#     `INDIRECTION_NAMES`, an `Attribute` spelling one of `READ_PRIMITIVES`,
#     and any dunder `Attribute`;
#     `test_this_file_imports_nothing_that_can_reach_a_reader`
#     reads `Import`/`ImportFrom` nodes against `PERMITTED_IMPORTS`. A read spelled
#     as none of those is not reported - evasion 4 is one, in this file's own
#     suite.
#   * JAVASCRIPT: `_STYLE_MENTION` finds the five words of
#     `INLINE_STYLE_PRIMITIVES` at word boundaries in `js()` output, line by
#     line, with a per-LINE exemption for a custom-property write.
#   * CSS SELECTORS: `_rule` compares `selector` as EXACT TEXT against the
#     comma-split entries of each block `_rules` EMITS, and merges those at
#     depth 0. What `_rules` does not emit is invisible here, and a rule whose
#     block contains native nesting is not emitted under its own selector at
#     all: `_rules(".exportv__progress { position: static !important; & { color:
#     red; } }")` returns one entry, selector text `position: static
#     !important; &`, depth 1 - `.exportv__progress` appears nowhere in the
#     result. Measured.
#   * CSS NAMES: `_declaration`, `_declarations_of`, `_custom_properties` and
#     `_important_declaration` search `_splittable` text for the LITERAL name
#     followed by `:` at a declaration boundary, over semicolon-split
#     fragments.
#
# It does NOT establish: browser CSS tokenization or cascade, native CSS
# nesting, whether a stylesheet is loaded by index.html at all, complete
# JavaScript comment removal, all CSSOM writes, or all Python filesystem reads.
#
# SEVEN THINGS THAT WALK STRAIGHT THROUGH IT, each CONSTRUCTED AND RUN rather
# than imagined, each leaving all 272 tests in this file green. They are
# deliberately NOT closed: closing the holes that came before them is what
# produced these, and the statement above is the answer instead of a seventh
# round.
#
# THIS LIST IS NON-EXHAUSTIVE. It is declared non-exhaustive here, in those
# words, because twice now absence from it has been read as coverage. It is a
# record of holes that were constructed and run, not a survey of the holes that
# exist, and it is not maintained as exhaustive. A hole that is not on it is
# UNLISTED, not closed, and the next one found is an addition to this list
# rather than a defect in it. The same goes for the two lists that follow -
# what is REFUSED, and what is matched LOOSELY.
#
#   1. AN UNQUOTED `url()` TOKEN IS NOT MODELLED. `_splittable` refuses a
#      QUOTE, which catches `content: "x; position: sticky; ..."` - but a url
#      token needs no quotes:
#
#          .exportv__progress {
#            background-image: url(data:x;position:sticky;bottom:0;);
#          }
#
#      A `;` inside that token is not a declaration boundary to a browser and
#      is one to every lookup here, so `_declaration` reads `position: sticky`
#      and `bottom: 0` out of a rule that declares NEITHER and
#      `assert_sticks_to_the_bottom` passes. Chrome 151 computes `position:
#      static; bottom: auto` - the block returns to normal flow and the Stop
#      button scrolls out of reach, which is the exact defect the rule exists
#      to prevent.
#
#   2. NATIVE CSS NESTING IS NOT MODELLED, and it falsifies what this comment
#      used to claim about `!important`:
#
#          .exportv__progress { & { position: static !important; } }
#
#      `_rules` reports the inner block with the selector `&`, which does not
#      MENTION `.exportv__progress`, so `_rule` never reaches
#      `_important_properties`; the outer wrapper matches no `_rules` pattern
#      at all and disappears. Chrome computes `static`.
#
#      NAMING THE TARGET IN THE OUTER SELECTOR DOES NOT HELP, and this is the
#      correction to what the sentence here said last round - "a rule whose
#      selector LIST names the selector as text", which sounds like it covers
#      the case below and does not:
#
#          .exportv__progress { position: static !important; & { color: red; } }
#
#      The target is named, and the important declaration is written directly
#      in that rule's own block rather than behind a nested selector. `_rules`
#      still returns ONE entry for it - selector text `position: static
#      !important; &`, body `color: red;`, depth 1 - because the outer `{` is
#      followed by another `{` before any `}`, so the outer rule cannot match
#      `([^{}]+)\{([^{}]*)\}` and its selector is consumed as part of the
#      inner one's. Nothing carrying `.exportv__progress` reaches
#      `_important_properties`. Appended to app.css: 272 passed.
#
#      SO THE REFUSAL'S ACTUAL SCOPE is rules that `_rules` SUCCESSFULLY
#      EMITS, and whose EMITTED selector text names the target. A rule
#      `_rules` does not emit under its own selector is outside it, however
#      the source is written.
#
#   3. `JS_COMMENT` DOES NOT REMOVE EVERY JAVASCRIPT COMMENT. Its
#      `(?<![:\w])//` keeps `https://` out of the match and also declines a
#      `//` that follows a WORD character - which JavaScript starts a comment
#      on regardless:
#
#          hue: position// (position - 1) * 30
#          ,
#
#      The module parses and loads, and `js()` hands its consumers BOTH the
#      commented-out formula the browser never runs AND whatever the live code
#      says. Put into `format.js` beside a live `hue: 0`, every substring
#      grep below still finds the formula in text that is a comment.
#
#   4. THE INVERTED READ SCAN IS BOUNDED BY ITS OWN TWO LISTS. It reports a
#      listed primitive and an `import` node; an ALREADY-PERMITTED namespace
#      that hands back a module is neither:
#
#          pytest.importorskip("io").FileIO(path).readall()
#
#      `pytest` is in `PERMITTED_IMPORTS`, there is no `import` AST node, and
#      `importorskip`, `FileIO` and `readall` are in no list here. That line
#      really does read the file raw; `_reads` returns nothing for it.
#
#   5. THE INLINE-CSS SCAN IS A WORD SEARCH, so a name that is never SPELLED
#      is never found:
#
#          progress['st' + 'yle']['position'] = 'static';
#
#      added to the real Export component leaves all 272 green. The primitives
#      are five WORDS, not five concepts, and a computed property name reaches
#      the same object without writing any of them.
#
#   6. NOTHING CHECKS THAT index.html LOADS app.css. Deleting the one line
#      `<link rel="stylesheet" href="/css/app.css">` leaves the WHOLE suite
#      green - 1398 passed, both sticky guards included. So every claim the CSS
#      checks make can be a claim about a stylesheet the browser never fetches.
#
#   7. PROPERTY RESETS, SHORTHANDS AND ALIASES ARE NOT MODELLED. The sticky
#      lookups search for the LITERAL names in `STICKY_PROPERTIES` -
#      `position`, `bottom`, `background` - each followed by `:`. A rule that
#      changes those computed values while spelling none of the three names is
#      merged into `applies` and moves no assertion:
#
#          .exportv__progress { all: initial; }
#
#      appended to app.css as a TOP-LEVEL rule: `_rule` merges it (exact
#      selector, depth 0), `unevaluated` comes back `[]`, and the whole file is
#      272 passed. `_declaration("position", ...)` still reads the shipped
#      `sticky` and `_declaration("bottom", ...)` the shipped
#      `calc(var(--space-6) * -1)`, because `all` is neither name. A browser
#      resets position to `static`, bottom to `auto` and the background to
#      transparent - the Stop button back below the fold and the rows scrolling
#      through the text. `.exportv__progress { inset: auto; }` (bottom via the
#      shorthand) and `.exportv__progress { background-color: transparent; }`
#      (a longhand `background` does not match, because the next character is
#      `-` and not `:`) were appended and run the same way: 272 passed each.
#
# REFUSED rather than modelled, each because reading it wrongly is silent and
# refusing it is not, and each pinned by a table of its own:
#
#   * `!important` in a declaration this file RESOLVES - `_declaration` and
#     `_custom_properties` refuse it in the text they are handed, and `_rule`
#     refuses it in a rule that `_rules` EMITS and whose EMITTED selector text
#     names the selector. Precedence needs the cascade. `_important_declaration`
#     reads the reduced-motion block, where the flag is the point, and refuses
#     an UNFLAGGED declaration in turn. Evasion 2 is the syntax it does not
#     reach - including a rule that names the target and declares the flag in
#     its own block, which `_rules` does not emit under that selector at all;
#   * a QUOTE anywhere in a sheet - a string can hold `;`, `{` or `}`. Evasion
#     1 is the unquoted token that does the same thing;
#   * an AT-RULE outside `@media` and `@keyframes` - `@import` hides a whole
#     stylesheet and `@layer` reorders the cascade;
#   * a rule NESTED inside an at-rule, which is conditional, and whose
#     condition this file cannot evaluate;
#   * a BACKSLASH - an identifier escape makes one class two strings;
#   * a MIXED-CASE property name - CSS folds it and `_declarations_of` does
#     not;
#   * any CHARACTER outside `\t\n\f\r` and printable ASCII - Python's `\s`
#     is a bigger set than CSS whitespace, and a homoglyph is not a comparison
#     this file can win;
#   * a COMMENT DELIMITER surviving the stripper - an unterminated comment ends
#     the sheet for the browser and ends nothing for `COMMENT`;
#   * a READ PRIMITIVE outside a registered module-level reader, and any import
#     outside `PERMITTED_IMPORTS`. Evasion 4 is the reach it does not cover.
#
# What is still matched loosely, written down here rather than discovered in a
# later round:
#
#   * ABSENCE checks - `HEX_COLOUR`, `COLOUR_FUNCTION`, `HTML_SINK`,
#     `"playlists_created" in body`, `'class="nav__soon"'`. Over-matching is
#     the safe direction for these: a loose pattern makes them fail loudly,
#     never pass quietly.
#   * `":focus-visible" in body` is an existence check and `:not(:focus-visible)`
#     satisfies it. The ring's VALUE is asserted from the token, and
#     `test_focus_is_never_removed_without_being_replaced` is the guard that
#     does the work.
#   * `--focus-ring` is checked for a non-zero `px`/`rem`/`em` ANYWHERE in its
#     value, not specifically in the thickness position of the box-shadow.
#   * `test_nothing_is_loaded_from_another_origin` skips a match beginning
#     `//`, so a protocol-relative `//cdn.example.com/x.js` is not reported.
#     Named at that site.
#   * `_destination_sections` requires `class="view"` exactly, so a section
#     that gains a second class becomes invisible to it - a false green rather
#     than a false red, and the reason the tests around it assert BOTH that
#     nothing is unbuilt and that the derivation still tells the two apart.
#   * The `.js` greps - `"track.playlists" in body`, `"folder_path"`,
#     `"(position - 1) * 30"`, `getElementById(LAYER_ID)` - are substring
#     presence checks on stripped source. Each says so at its site and names
#     the behavioural test that establishes what the module DOES. Evasion 3 is
#     the "stripped" part failing.
#   * `body.split('data-destination="export"')[1].split("</button>")[0]` takes
#     a region between two substrings rather than parsing the markup.
#   * The refusals are over CSS SOURCE TEXT, so what they establish is what the
#     stylesheet says.
#     `test_no_script_puts_css_on_the_page_outside_the_stylesheet` reports the
#     five words of `INLINE_STYLE_PRIMITIVES` in stripped script source, line
#     by line; evasion 5 is a write to `.style` that spells none of them, and
#     the two sticky tests still cannot lay anything out. Where those blocks
#     actually land was measured by hand
#     in a real browser and is recorded in the PR description.
#   * A stylesheet in `src/web/static/css/` that no `<link>` in index.html
#     loads is still read by the sheet-wide checks, and NOTHING HERE NOTICES
#     THE MISSING `<link>` - evasion 6. That is not "more is checked, not
#     less", which is what this said before it was measured: it is a guard
#     describing a stylesheet the browser may never load.
#     `test_nothing_is_loaded_from_another_origin` bounds where the links that
#     ARE in the markup point; it says nothing about whether the sheets that
#     are checked are linked at all.


def stylesheets():
    return sorted(CSS.glob("*.css"))


def scripts():
    return sorted(JS.rglob("*.js"))


# ---------------------------------------------------------------------------
# Tokens first
# ---------------------------------------------------------------------------


THIS_FILE = Path(__file__).resolve()


def own_source():
    """This file's own text, raw, for the AST scan below to parse.

    A REGISTERED READER rather than an exemption. The scan used to special-case
    `read(THIS_FILE)` at the call site - one shape, matched exactly - and the
    lesson of every round on this file is that a named door in a rule beats a
    hole in it. There is nothing to strip here: this is Python, parsed as
    Python, not source a browser ever sees.
    """
    return read(THIS_FILE)

#: The readers that make a source file look the way a browser sees it, plus
#: `read`, whose body is `path.read_text(encoding="utf-8")`, plus
#: `own_source`, which is how this file gets its own text to parse. Inside
#: their definitions a raw read is what they ARE; anywhere else it is the
#: defect below.
#:
#: This is a closed set of six functions at the top of one file, not an open
#: set of spellings. A read primitive written in the body of a function whose
#: name is not in this tuple is reported as an unclassified raw read - the
#: "read(THIS_FILE) somewhere else" and "a new helper that reads raw" rows of
#: `EVASIONS`. Only a MODULE-LEVEL `def` counts:
#: a `def css(path)`
#: written inside a test body is not this file's stylesheet reader, it is a
#: local function that happens to share its name, and treating it as one is
#: how a raw read hid inside a reader's name in round 6.
READER_DEFINITIONS = ("read", "own_source", "source", "css", "js", "html")

#: The spellings `_reads` reports as a `Name` or as an `Attribute` outside a
#: registered reader - see the `READ_PRIMITIVES` branches in `_reads`. This is
#: the inversion round 6 forced, and the direction matters more than the
#: contents.
#:
#: The scan this replaces classified the SHAPE of a call - "a call to `read`",
#: "a call whose function is an attribute named `read_text`" - and every round
#: found a new shape it did not model. `UNSTRIPPED = Path.read_text` is not a
#: call at all, so nothing about a call site could catch it;
#: `linecache.getlines` is a call to an attribute nobody had listed. Shapes are
#: unbounded. There is no finite list of them, and PR #24 and this one have
#: between them spent nine rounds proving it.
#:
#: A spelling, unlike a call shape, is there to be matched wherever it sits:
#: `UNSTRIPPED = Path.read_text` is reported at the ATTRIBUTE, before there is
#: a call to have a shape at all. What this list does NOT do is enumerate the
#: ways bytes reach Python. Evasion 4 in the boundary note above
#: `stylesheets()` reads a file through `readall`, which is on no list here.
#:
#: Refused as a NAME or as an ATTRIBUTE, wherever either appears: assigned,
#: called, passed, put in a dict, defaulted into a signature, or merely
#: mentioned. Not "reported unless the scan can follow it" - REPORTED.
READ_PRIMITIVES = (
    # builtins, io, codecs, gzip, tokenize, os and pathlib all spell it `open`
    "open",
    "fdopen",
    # this file's own reader, and every file object
    "read",
    "readline",
    "readlines",
    "readinto",
    # pathlib, importlib.resources
    "read_text",
    "read_bytes",
    "read_binary",
    # linecache - the one round 6 reported - and its singular
    "getline",
    "getlines",
    # pkgutil, inspect
    "get_data",
    "getsource",
    "getsourcelines",
    "findsource",
    # mmap, numpy
    "mmap",
    "loadtxt",
    "genfromtxt",
    "fromfile",
)

#: Names that do not read a file themselves but hand out something that can,
#: so a scan reading source text cannot say what happens next. Refused as
#: NAMES only: `re.compile` is an attribute and is fine, a bare `compile(...)`
#: is the builtin and is not.
#:
#: This set is what makes the one above hold. Every read primitive except the
#: builtin `open` and the methods on a `Path` needs an IMPORT to reach, and
#: `test_this_file_imports_nothing_that_can_reach_a_reader` closes that door;
#: these are the builtins that get to a module or an attribute without one.
INDIRECTION_NAMES = (
    "__import__",
    "__builtins__",
    "eval",
    "exec",
    "compile",
    "getattr",
    "globals",
    "locals",
    "vars",
    "input",
)

#: Calls that hand back stripped source. A call to one of these is fine
#: wherever it appears and whatever path it is given.
STRIPPING_READERS = ("source", "css", "js", "html")

#: What this file is allowed to import, at any depth:
#: `test_this_file_imports_nothing_that_can_reach_a_reader` walks the `Import`
#: and `ImportFrom` nodes of this file and reports any whose top-level name is
#: not in this tuple.
#:
#: `linecache`, `io`, `codecs`, `os`, `subprocess`, `fileinput`, `pkgutil`,
#: `inspect`, `mmap` and `importlib` are each a way to read a file that no
#: list of call shapes would have caught, and each is reported by that test.
#: `pytest` is not: it is on this list, and
#: `pytest.importorskip("io").FileIO(path).readall()` reaches a raw read
#: through it with no import node to report - evasion 4 in the boundary note
#: above `stylesheets()`.
PERMITTED_IMPORTS = ("ast", "colorsys", "re", "pathlib", "pytest")


def _reads(tree):
    """The source reads this scan FINDS in `tree`, as (stripped, raw).

    Not every read in `tree`: what it reports is a `Name` or an `Attribute`
    whose spelling is in `READ_PRIMITIVES` or `INDIRECTION_NAMES`, plus any
    dunder attribute, each outside a registered reader. A read spelled as none
    of those is not in the result - evasion 4 in the boundary note above
    `stylesheets()` is one, constructed and run.

    STRUCTURAL, and INVERTED - it looks for read primitives rather than for
    call shapes. `READ_PRIMITIVES` says why that swap is the whole point.

    Three rules, and each was a hole in round 6 before it was a rule:

      * a primitive is refused wherever it is SPELLED, as a Name or as an
        Attribute, whether or not it is being called. `UNSTRIPPED =
        Path.read_text` then `UNSTRIPPED(APP_CSS, encoding="utf-8")` was a
        real raw read that passed in silence, because neither line is a call
        shape the old scan modelled;
      * only a MODULE-LEVEL `def` whose name is registered is a reader. A
        nested `def css(path): return path.read_text()` inside a test used to
        turn its whole enclosing body into reader territory just by being
        named `css`;
      * a function's DECORATORS, ARGUMENT DEFAULTS and ANNOTATIONS are
        evaluated where the `def` is written, not where its body runs, so they
        are visited OUTSIDE the reader. `def css(path, _raw=APP_CSS.read_text())`
        is a raw read at module scope wearing a reader's name.

    A lambda is never a reader: it has no name to register, so its body is
    read in whatever context the lambda itself appears in.

    There is no exemption for this file's own source. `own_source` is a
    REGISTERED READER, so its raw read has a name instead of a special case,
    and `read(THIS_FILE)` written anywhere else is reported like any other
    primitive - the "read(THIS_FILE) somewhere else" row of `EVASIONS`.
    """
    readers = {
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in READER_DEFINITIONS
    }
    stripped, raw = [], []

    def report(node, what):
        raw.append(f"line {node.lineno}: {what}")

    def visit(node, in_reader):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Written here, evaluated here: outside the body, and so outside
            # the reader even when the `def` is one.
            for decorator in node.decorator_list:
                visit(decorator, in_reader)
            visit(node.args, in_reader)
            if node.returns is not None:
                visit(node.returns, in_reader)
            for statement in node.body:
                visit(statement, in_reader or node in readers)
            return

        if isinstance(node, ast.Lambda):
            visit(node.args, in_reader)
            visit(node.body, in_reader)
            return

        if not in_reader:
            if isinstance(node, ast.Name):
                if node.id in READ_PRIMITIVES:
                    report(node, f"`{node.id}` gets bytes off disk, outside any reader")
                elif node.id in INDIRECTION_NAMES:
                    report(node, f"`{node.id}` reaches code this scan cannot read")
            elif isinstance(node, ast.Attribute):
                if node.attr in READ_PRIMITIVES:
                    report(node, f"`.{node.attr}` gets bytes off disk, outside any reader")
                elif node.attr.startswith("__") and node.attr.endswith("__"):
                    # `().__class__.__base__.__subclasses__()` walks to every
                    # object in the process and `f.__globals__` to every module
                    # a function can see. A SYNTACTIC class rather than a list,
                    # so there is nothing to enumerate - and this file uses no
                    # dunder attribute at all, so it costs nothing to refuse.
                    report(node, f"`.{node.attr}` reaches objects this scan cannot read")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in STRIPPING_READERS
            ):
                stripped.append(f"line {node.lineno}: {ast.unparse(node)}")

        for child in ast.iter_child_nodes(node):
            visit(child, in_reader)

    visit(tree, False)
    return stripped, raw


def test_no_source_file_is_read_without_its_comments_being_stripped():
    """The single rule the readers exist to enforce, checked on THIS file's AST.

    Not a style point. These regexes in here read tokens.css and app.css raw,
    and each was wrong about the browser:

      * a `--ink-secondary` that exists ONLY inside a comment counted as
        DEFINED, so the one token every component uses could be commented out
        and this whole file stayed green while the page lost its secondary
        text colour;
      * the entire `@media (prefers-reduced-motion: reduce)` block could be
        commented out and stayed green - the exact failure its own docstring
        calls "worse than none, because it reads like a check";
      * a commented-out seventh font size counted against the six-size ceiling;
      * a commented-out `--ink-secondary` override SHADOWED the live one in the
        contrast fixture, so the ratios were computed from a colour the browser
        never sees;
      * a commented-out `:root {` block was read as the real one and reported a
        camelot leak that does not exist.

    Two of those were reported and the rest were found by looking for more,
    which is the reason this test exists at all rather than one more
    correction: correcting the sites one at a time is what left the rest
    standing.

    AND THE SCAN ITSELF WAS ONE. It recognised five variable names, so
    it never saw `read(JS / "format.js")` two hundred lines below it -
    commenting out `hue: (position - 1) * 30,` and substituting `hue: 0,` left
    every Camelot pill at hue zero with 129 Python and 168 JS tests green.
    Enumerating the spellings of a path is the same losing game as enumerating
    the decoys a substring lookup accepts, so it is not played.

    AND THE SCAN THAT REPLACED IT WAS ANOTHER, which is why it now runs the
    other way round. Classifying CALL SHAPES is the same losing game one level
    up: `UNSTRIPPED = Path.read_text` is not a call, a nested `def css` wore a
    reader's name, and `linecache.getlines` was a shape nobody had listed. All
    three were green in round 6. `_reads` classifies the READ PRIMITIVE
    instead - as a Name or an Attribute, called or not, anywhere in the file.
    What it reports is bounded by what it looks for; a read spelled as none of
    those is not reported, and evasion 4 in the boundary note above
    `stylesheets()` is one - `_reads` returns `([], [])` for it, measured.
    """
    stripped, raw = _reads(ast.parse(own_source()))

    assert raw == [], "source read without stripping comments:\n  " + "\n  ".join(raw)
    # ...and not vacuously. If every call site went away, or the scan stopped
    # recognising them, `raw == []` would pass with nothing being checked. This
    # is the floor, and unlike the `count("css(") >= 6` it replaces it is a
    # property of the scan rather than a tally of a substring.
    assert stripped, (
        "the AST scan found no stripping reader called anywhere in this file; "
        "it has stopped seeing reads rather than found none to report"
    )


def test_this_file_imports_nothing_that_can_reach_a_reader():
    """The narrowing under `READ_PRIMITIVES`, checked rather than asserted in
    a comment.

    Python has many ways to read a file and no list of them is complete on its
    own - `subprocess.run(["cat", path])`, `ctypes`, an extension module. Most
    of those have to be IMPORTED first, and this test reports an import of
    anything outside `PERMITTED_IMPORTS`. It does NOT establish that what is
    left in scope cannot read a file: `pytest` is permitted, and evasion 4 in
    the boundary note above `stylesheets()` reaches a raw read through it.

    The half that is easy to forget: an `import linecache` at the top of a test
    function is three words, and it puts a read primitive in scope that nothing
    else here would have to notice. `linecache.getlines` is in the primitive
    list as well - belt and braces, and because it is the one round 6 actually
    reported.

    Checked at any depth, because `import` inside a function body is still an
    import.
    """
    imported = []
    for node in ast.walk(ast.parse(own_source())):
        if isinstance(node, ast.Import):
            imported.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A relative import has no module name; it is still an import of
            # something this list does not cover, so it is reported as one.
            imported.append((node.module or ".", node.lineno))

    outside = [
        f"line {line}: {name}"
        for name, line in imported
        if name.split(".")[0] not in PERMITTED_IMPORTS
    ]
    assert outside == [], (
        "this file imports something PERMITTED_IMPORTS does not cover:\n  "
        + "\n  ".join(outside)
        + "\nEvery such module is a way to read a file that `_reads` would have "
          "to enumerate call by call. Add it here only with the primitives it "
          "brings added to READ_PRIMITIVES beside it."
    )
    # ...and not vacuously: an empty import list would pass the check above
    # while meaning the parse found nothing.
    assert len(imported) >= len(PERMITTED_IMPORTS), (
        f"only {len(imported)} imports found; the scan has stopped seeing them"
    )


def test_the_import_check_reports_a_module_that_could_read_a_file():
    """A rule nobody has seen fail is a rule nobody has seen work."""
    for module in ("linecache", "io", "os", "subprocess", "importlib.resources"):
        found = [
            alias.name
            for node in ast.walk(ast.parse(f"import {module}\n"))
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert found, module
        assert found[0].split(".")[0] not in PERMITTED_IMPORTS, (
            f"{module} is treated as permitted, so the check above allows it"
        )


#: Ways of reading a source file that a scan classifying CALL SHAPES could
#: not see. A hand-written list, not a survey.
#: `read(JS / "format.js")` is not hypothetical - it was live in
#: this file when round 5 opened, and it is what let the Camelot hue be
#: commented out with 129 Python and 168 JS tests green. The rest are the same
#: read spelled differently, which is the point: the spellings are unbounded,
#: so the scan classifies the READ PRIMITIVE and never the path or the call.
#:
#: THE FOUR ROWS UNDER THE "reported in round 6" COMMENT are that round's
#: report, and all four were green against the shape-classifying scan this
#: replaces. Rows were appended after them, so they are not the last four.
EVASIONS = [
    ("a composed path", 'def test_x():\n    body = read(JS / "components" / "drawer.js")\n'),
    ("a path bound to a new name", 'FORMAT_JS = JS / "format.js"\n'
                                   'def test_x():\n    body = read(FORMAT_JS)\n'),
    ("a path built out of strings", 'def test_x():\n'
                                    '    body = read(Path(str(JS) + "/format.js"))\n'),
    ("an alias of the raw reader", 'raw = read\ndef test_x():\n    body = raw(TOKENS_CSS)\n'),
    ("the raw reader in a table", 'READERS = {"raw": read}\n'
                                  'def test_x():\n    READERS["raw"](TOKENS_CSS)\n'),
    ("the raw reader passed on", 'def test_x():\n    body = "".join(map(read, scripts()))\n'),
    ("a bare Path.read_text", 'def test_x():\n    body = (JS / "format.js").read_text()\n'),
    ("read_bytes", 'def test_x():\n    body = (CSS / "app.css").read_bytes()\n'),
    ("open()", 'def test_x():\n    body = open(INDEX_HTML).read()\n'),
    ("io.open()", 'def test_x():\n    body = io.open(INDEX_HTML).read()\n'),
    ("a new helper that reads raw", 'def slurp(path):\n    return path.read_text()\n'
                                    'def test_x():\n    slurp(TOKENS_CSS)\n'),
    ("read(THIS_FILE) somewhere else", 'def test_x():\n    body = read(THIS_FILE)\n'),
    # -- reported in round 6, every one of them silent before this ---------
    ("an UNBOUND method aliased", 'UNSTRIPPED = Path.read_text\n'
                                  'def test_x():\n'
                                  '    body = UNSTRIPPED(APP_CSS, encoding="utf-8")\n'),
    ("an imported linecache.getlines", 'import linecache\ndef test_x():\n'
                                       '    body = "".join(linecache.getlines(str(APP_CSS)))\n'),
    ("a nested function named css", 'def test_x():\n'
                                    '    def css(path):\n'
                                    '        return path.read_text()\n'
                                    '    body = css(APP_CSS)\n'),
    ("a raw default on a function named css", 'def css(path, _raw=APP_CSS.read_text()):\n'
                                              '    return _raw\n'),
    # -- and the same three tricks the four above are instances of ---------
    ("a nested function named read", 'def test_x():\n'
                                     '    def read(path):\n'
                                     '        return path.read_bytes()\n'
                                     '    read(APP_CSS)\n'),
    ("a reader defined inside a class", 'class Reader:\n'
                                        '    def css(self, path):\n'
                                        '        return path.read_text()\n'),
    ("a raw annotation on a reader", 'def css(path) -> type(APP_CSS.read_text()):\n'
                                     '    return source(path)\n'),
    ("a raw decorator on a reader", '@pytest.mark.skipif(not APP_CSS.read_text(), reason="x")\n'
                                    'def css(path):\n    return source(path)\n'),
    ("a lambda that reads raw", 'css_of = lambda path: path.read_text()\n'),
    ("getattr around the primitive", 'def test_x():\n'
                                     '    body = getattr(APP_CSS, "read_" + "text")()\n'),
    ("a dunder walk to the builtins", 'def test_x():\n'
                                      '    ns = type(APP_CSS).__init__.__globals__\n'),
    ("pkgutil.get_data", 'import pkgutil\ndef test_x():\n'
                         '    body = pkgutil.get_data("web", "static/css/app.css")\n'),
    ("a file object left open", 'def test_x():\n'
                                '    handle = open(APP_CSS)\n    body = handle.readlines()\n'),
]

#: ...and the forms that are fine, or the check above is satisfied by a scan
#: that reports everything.
#:
#: The third column says whether the row should also register on the STRIPPED
#: side, which is the floor under
#: `test_no_source_file_is_read_without_its_comments_being_stripped`. It is a
#: column rather than an `if "read(THIS_FILE)" not in snippet` at the call
#: site: that test used to decide by looking for a substring of the snippet,
#: which is the same loose match this whole file exists to stamp out, and it
#: silently exempted any row that happened to contain those characters.
COUNTS = True
NO_STRIPPING_READER_CALLED = False

PERMITTED_READS = [
    ("a stylesheet", 'def test_x():\n    body = css(TOKENS_CSS)\n', COUNTS),
    ("a script", 'def test_x():\n    body = js(JS / "format.js")\n', COUNTS),
    ("markup", 'def test_x():\n    body = html(INDEX_HTML)\n', COUNTS),
    ("a path only known at run time", 'def test_x():\n'
                                      '    for path in stylesheets():\n'
                                      '        body = source(path)\n', COUNTS),
    # A REGISTERED READER, not an exemption - the module-level `def` is what
    # makes the raw read inside it legitimate, and it is the same `def` a
    # reviewer reads when asking which functions may touch the filesystem.
    ("this file's own source, through its reader",
     'def own_source():\n    return read(THIS_FILE)\n'
     'def test_x():\n    body = own_source()\n', NO_STRIPPING_READER_CALLED),
    ("a registered reader doing its job",
     'def read(path):\n    return path.read_text(encoding="utf-8")\n'
     'def source(path):\n    return STRIPPERS[path.suffix](read(path))\n',
     NO_STRIPPING_READER_CALLED),
    # `re.compile` is an attribute, and the builtin `compile` is a name. The
    # scan has to tell them apart or fourteen live call sites in this file
    # become violations.
    ("re.compile", 'PATTERN = re.compile(r"x")\n', NO_STRIPPING_READER_CALLED),
]


@pytest.mark.parametrize("what,snippet", EVASIONS, ids=[name for name, _ in EVASIONS])
def test_the_self_scan_reports_a_read_however_it_is_spelled(what, snippet):
    """A rule nobody has seen fail is a rule nobody has seen work.

    `test_no_source_file_is_read_without_its_comments_being_stripped` asserts
    an EMPTY list, and an empty list is what a scan that has stopped matching
    also produces. These are the inputs that tell the two apart. The four rows
    under the "reported in round 6" comment were green against the
    shape-classifying scan this replaces.
    """
    _stripped, raw = _reads(ast.parse(snippet))

    assert raw, f"{what} was not reported at all"


@pytest.mark.parametrize(
    "what,snippet,counts", PERMITTED_READS, ids=[name for name, _, _ in PERMITTED_READS]
)
def test_the_self_scan_leaves_a_stripping_reader_alone(what, snippet, counts):
    """The other direction. A scan that reported everything would pass the
    check above while making the readers unusable, and someone would delete
    it."""
    stripped, raw = _reads(ast.parse(snippet))

    assert raw == [], f"{what} was reported as a raw read: {raw}"
    # ...and the rows that call one have to be COUNTED, or the floor in
    # `test_no_source_file_is_read_without_its_comments_being_stripped` is a
    # list the scan simply never fills.
    assert bool(stripped) == counts, (
        f"{what}: expected stripping-reader calls={counts}, got {stripped}"
    )


#: (suffix, source, what the browser is left with). The three strippers are
#: each guarded on their own further down; this is the TABLE, which is what
#: decides which of them a given file gets. Pointing `.js` at the CSS stripper
#: leaves every `//` comment standing - the exact defect that let the Camelot
#: hue be commented out - and pointing `.html` at it leaves every `<!-- -->`.
#: Both survived with this file green until this table existed, because
#: index.html carries no comment and drawer.js's header is a `/* */` one.
#: The comment becomes a SPACE rather than nothing - see `_without`, and
#: `test_a_comment_separates_the_tokens_it_sits_between` for why the
#: difference is a live sticky rule rather than tidiness.
READER_DISPATCH = [
    (".css", "/* gone */\n//kept", " \n//kept"),
    (".js", "/* gone */\n// gone\nkept", " \n \nkept"),
    (".html", "<!-- gone -->/* kept */", " /* kept */"),
]


@pytest.mark.parametrize("suffix,before,after", READER_DISPATCH)
def test_each_kind_of_source_gets_the_stripper_for_its_own_comment_syntax(
    suffix, before, after
):
    assert STRIPPERS[suffix](before) == after


def test_the_script_reader_strips_both_comment_forms():
    """Guard the guard, against a real script rather than a synthetic string.

    `test_the_comment_stripper_still_strips_something` reads drawer.js, whose
    header is a `/* */` comment - so the CSS stripper satisfies it, and
    mapping `.js` to the CSS stripper left this file green. A `//` comment has
    to be shown gone from a file that has one.
    """
    stripped = js(JS / "format.js")

    assert "Decimal digits are laid out in blocks" not in stripped, (
        "a `//` comment survived js()"
    )
    assert "Rendering helpers shared by the palette" not in stripped, (
        "a `/* */` comment survived js()"
    )
    assert "export function camelot" in stripped, "the reader ate the code"


def test_a_reader_is_chosen_by_what_the_file_is():
    """The three suffix asserts, called with the suffix each one refuses.

    `css()`, `js()` and `html()` each open with an `assert path.suffix == ...`,
    and this is what calls them with the wrong one. Before it existed all three
    asserts survived deletion with the suite green. They are worth having -
    `css()` on a script strips `/* */` and leaves a `//` comment standing,
    which is the reader being wrong about the browser in the direction this
    whole file exists to stop - so they are pinned here rather than left as
    decoration.
    """
    with pytest.raises(AssertionError, match="not a stylesheet"):
        css(JS / "format.js")
    with pytest.raises(AssertionError, match="not a script"):
        js(TOKENS_CSS)
    with pytest.raises(AssertionError, match="not markup"):
        html(TOKENS_CSS)

    # And `source()` has no default. A suffix with no stripper is an assertion,
    # not a quiet raw read - unreachable from the tree as it stands, and the
    # moment an `.svg` or a `.json` is read it is the difference between a
    # loud failure and a silent one.
    with pytest.raises(AssertionError, match="no reader for"):
        source(STATIC / "nothing.svg")


def test_the_self_scan_counts_only_the_call_sites_it_is_a_floor_under():
    """The non-vacuity floor is about the CALL SITES, not the readers' own
    bodies - `css`, `js` and `html` each call `source(path)` inside themselves,
    and those three survive the deletion of every test in this file."""
    _stripped, raw = _reads(ast.parse('def css(path):\n    return source(path)\n'))

    assert raw == []
    assert _stripped == [], "the readers' own bodies are counted as call sites"


def test_the_stylesheet_reader_really_does_strip():
    """Guard the guard, the twin of the JS one further down. A reader that
    stripped everything would make every check above vacuous, and one that
    stripped nothing is the bug this replaced."""
    stripped = css(TOKENS_CSS)

    assert "/*" not in stripped and "*/" not in stripped, "comments survived the reader"
    assert "--ink-secondary" in _custom_properties(stripped), "the reader ate the declarations"
    assert ":root" in stripped, "the reader ate the selectors"


#: A name and a sheet that CONTAINS that name without declaring it. Every row
#: is a real false-green or the same shape as one: unanchored, each of these
#: lookups resolved from the decoy and reported a value the browser never
#: computes.
#:
#: The rows are examples, not the guard. What the guard checks is the
#: declaration BOUNDARY, which is finite; the decoys are not, and enumerating
#: them is exactly what the last two rounds did.
DECOY_DECLARATIONS = [
    # Reported twice, and the reason this exists. Renaming both motion tokens
    # inside the reduced-motion block satisfied the override check while
    # leaving the real ones at 110 ms and 170 ms.
    ("--motion-fast", ":root { --not--motion-fast: 1ms; }"),
    ("--motion-base", ":root { --another--motion-base: 1ms; }"),
    # The lookup `var()` resolution goes through.
    ("--text-xs", ":root { --not--text-xs: 1px; }"),
    # The suffix that was patched at the CALL SITE last round, which left the
    # lookup itself wrong for every other spelling of the same trick.
    ("--text-xs", ":root { text-xs: 1px; }"),
    # Ordinary properties, not custom ones. A vendor prefix is this shape and
    # is CSS people really write.
    ("animation-duration", "* { -webkit-animation-duration: 1ms; }"),
    ("transition-duration", "* { -moz-transition-duration: 1ms; }"),
    ("position", ".x { background-position: sticky; }"),
    ("bottom", ".x { padding-bottom: 1px; }"),
    ("outline", ".x { outline-color: none; }"),
    # A name that is a PREFIX of a declared one. The `:` that has to follow the
    # name is what rejects this, which is why the anchoring is at both ends.
    ("--motion", ":root { --motion-fast: 1ms; }"),
    ("background", ".x { background-image: var(--surface-1); }"),
    # A declaration boundary is a brace or a semicolon, not any whitespace: a
    # value can run over a line break, and the tail of one is not a new
    # declaration.
    ("--fast", ":root { --font-sans:\n    --fast: 1ms; }"),
    # A `--name:` inside a VALUE declares nothing. Deleting the boundary from
    # `_custom_properties` left this file green until this row existed: the
    # name pattern is greedy, so `--not--text-xs` is captured whole either way
    # and none of the rows above can tell the two apart there.
    #
    # This row used to be `.x { content: "--decoy: 1px"; }` and asserted that
    # the lookup returned None. It is written without the string now, because
    # a string is no longer something this file reads carefully - it is
    # something it REFUSES, and the quoted spelling is pinned as a refusal in
    # `UNSPLITTABLE_SHEETS` instead. Same claim, without asking a lookup to be
    # right about text it has declared it cannot parse.
    ("--decoy", ".x { --outer: var(--decoy: 1px); }"),
]


@pytest.mark.parametrize("name,sheet", DECOY_DECLARATIONS)
def test_a_longer_name_that_contains_a_real_one_declares_something_else(name, sheet):
    """The single defect three review rounds each found in a new consumer.

    A lookup that finds its name ANYWHERE in the text is answered by any
    longer name that happens to contain it - so a token can be renamed out of
    existence, or shadowed by a decoy, with every check that reads it green.

    The NAME lookups here go through `_declaration` and `_custom_properties`,
    which is why this pins the boundary once instead of once per call site.
    The looser matches this file also makes - the substring greps and absence
    patterns listed in the boundary note above `stylesheets()` - do not come
    through either function and are not pinned by this.
    """
    assert _declaration(name, sheet) is None, (
        f"{name} was read out of {sheet!r}, which declares no such property"
    )
    assert not _declares(name, r".", sheet)
    assert name not in _custom_properties(sheet)


#: Sheets this file REFUSES to split, because a quote in them means it cannot
#: say where a declaration begins. Every row is CSS a browser reads perfectly
#: well and this file will not: that is the trade, and it is pinned here so
#: nobody can quietly reintroduce splitting-by-guess.
#:
#: The first row is the evasion as it was reported - with the real sticky
#: declarations deleted, the string alone satisfied every check the sticky
#: guard makes, and the block scrolled out of reach with `1 passed`.
UNSPLITTABLE_SHEETS = [
    ("the reported evasion", ".exportv__progress {\n"
                             '  content: "x; position: sticky; bottom: '
                             'calc(var(--space-6) * -1); background: var(--surface);";\n}'),
    ("a brace inside a string", '.x { content: "{}" } .setc__status { position: static; }'),
    ("a single-quoted string", ".x { content: 'a; b'; }"),
    ("a quoted font name", ':root { --font-sans: "SF Pro Text", sans-serif; }'),
    ("a quoted attribute selector", '.x[data-y="z"] { position: sticky; }'),
    ("a bare quote", '.x { content: "; }'),
]


@pytest.mark.parametrize(
    "what,sheet", UNSPLITTABLE_SHEETS, ids=[name for name, _ in UNSPLITTABLE_SHEETS]
)
def test_a_stylesheet_with_a_string_in_it_is_refused_rather_than_split(what, sheet):
    """Every entry point, not just the one the evasion came in through.

    `_splittable` is called from `css`, `_declarations_of`,
    `_custom_properties`, `_important_properties` and `_rules`. The five
    entry points below reach it through those: a consumer that reached around
    one of them would be the sixth place this file has been wrong about the
    same thing.
    """
    for name, call in (
        ("_declaration", lambda: _declaration("position", sheet)),
        ("_declares", lambda: _declares("position", r"^sticky", sheet)),
        ("_custom_properties", lambda: _custom_properties(sheet)),
        ("_rules", lambda: _rules(sheet)),
        ("_rule", lambda: _rule(sheet, ".exportv__progress", STICKY_PROPERTIES)),
    ):
        with pytest.raises(_CannotModel) as refusal:
            call()
        assert "string" in str(refusal.value), (
            f"{name} refused {what} without saying why: {refusal.value}"
        )


def test_the_stylesheet_reader_refuses_a_string_too(tmp_path):
    """The reader is the entry point every real sheet comes through, so the
    refusal has to be there and not only in the splitters underneath it.

    Through a real file rather than a string, because the reader is what is
    being tested and its argument is a path. In `tmp_path`, not by rewriting a
    shipped sheet: a test that edits `src/` leaves the tree broken if it is
    interrupted, and the point of this file is not to need that.
    """
    sheet = tmp_path / "app.css"
    sheet.write_text('/* fine */\n.x { content: "a; b"; }\n', encoding="utf-8")

    with pytest.raises(_CannotModel) as refusal:
        css(sheet)

    assert "app.css" in str(refusal.value), (
        f"the refusal does not name the file: {refusal.value}"
    )


def test_the_shipped_stylesheets_are_ones_this_file_can_actually_split():
    """...and the other direction, or every check above is vacuous.

    A refusal that fires on the real sheets would be found in seconds. A
    refusal that fires on NOTHING - because `_splittable` stopped looking -
    would not, and every string evasion would be open again with this file
    green. So the shipped sheets are read here, through the reader, and the
    absence of a quote in them is the thing asserted.
    """
    assert stylesheets(), "no stylesheets found at all"
    for sheet in stylesheets():
        body = css(sheet)
        assert _QUOTE.search(body) is None, f"{sheet.name} carries a string"
        assert _rules(body), f"{sheet.name} split into no rules"


#: A rule that only applies under a condition this file cannot evaluate. THIS
#: IS THE SEVENTH INSTANCE, found by looking for one against the six fixed
#: above, and it was green: the whole shipped `.exportv__progress` rule could
#: be wrapped in a media query matching no real viewport, and the guard
#: reported the block stuck with the Stop button back below the fold.
#:
#: Each row is the rule the guard checks, moved somewhere it does not apply.
CONDITIONAL_RULES = [
    ("a viewport nothing has",
     "@media (min-width: 99999px) {\n"
     "  .exportv__progress { position: sticky; bottom: 0; background: var(--surface-2); }\n}"),
    ("print only",
     "@media print {\n"
     "  .exportv__progress { position: sticky; bottom: 0; background: var(--surface-2); }\n}"),
    ("a feature query that fails",
     "@supports (not (all: initial)) {\n"
     "  .exportv__progress { position: sticky; bottom: 0; }\n}"),
    ("a keyframe step",
     "@keyframes drift {\n"
     "  to { position: sticky; bottom: 0; }\n"
     "  from { position: sticky; bottom: 0; }\n}"),
]


@pytest.mark.parametrize(
    "what,sheet", CONDITIONAL_RULES, ids=[name for name, _ in CONDITIONAL_RULES]
)
def test_a_rule_inside_an_at_rule_is_not_read_as_though_it_always_applied(what, sheet):
    """A nested rule is conditional, and this file cannot evaluate conditions.

    `@supports` and `@keyframes` are refused one step earlier, at the reader,
    because they are not in MODELLED_AT_RULES - so both spellings are checked
    here: either the sheet is turned down, or the rule is not merged. What must
    NOT happen is the third thing, which is what happened: the rule read as if
    it were written at the top of the sheet.
    """
    try:
        declarations, _unevaluated = _rule(sheet, ".exportv__progress", STICKY_PROPERTIES)
    except _CannotModel:
        return
    assert declarations == "", (
        f"{what} was merged as though it applied unconditionally: {declarations}"
    )


def test_a_nested_rule_that_clashes_is_handed_back_rather_than_dropped():
    """Not merged is not the same as not mentioned.

    A nested rule redeclaring a checked property is exactly what the
    `unevaluated` channel is for: this file cannot say whether it applies, and
    saying nothing is the defect rather than the fix. So the real rule stays
    checked AND the conditional one is reported.
    """
    sheet = (".exportv__progress { position: sticky; bottom: 0; }\n"
             "@media (min-width: 99999px) {\n"
             "  .exportv__progress { position: static; }\n}")

    declarations, unevaluated = _rule(sheet, ".exportv__progress", STICKY_PROPERTIES)

    assert _declares("position", r"^sticky\b", declarations), declarations
    assert unevaluated, "the conditional rule was dropped in silence"
    assert "nested" in unevaluated[0][0], unevaluated
    assert unevaluated[0][1] == ["position"], unevaluated


def test_a_top_level_rule_is_still_read_when_the_sheet_has_a_media_block():
    """...and the other direction, or the check above is satisfied by a reader
    that stopped merging anything at all. tokens.css really does carry an
    `@media` block, so "nested" has to mean nested rather than "after the
    first at-rule in the file"."""
    sheet = ("@media (prefers-reduced-motion: reduce) {\n"
             "  :root { --motion-fast: 1ms; }\n}\n"
             ".exportv__progress { position: sticky; bottom: 0; }")

    declarations, unevaluated = _rule(sheet, ".exportv__progress", STICKY_PROPERTIES)

    assert _declares("position", r"^sticky\b", declarations), declarations
    assert unevaluated == [], unevaluated


#: Two more spellings a browser reads as the checked rule and this file does
#: not, both found by probing after the seventh was fixed, both green when
#: they were found. They are the same defect as the `!important` and the
#: string: a construct with a definite meaning that the regexes underneath
#: this file quietly give a different one.
DIFFERENTLY_SPELLED_RULES = [
    ("an escaped class name",
     ".exportv__progress { position: sticky; bottom: 0; }\n"
     ".exportv\\_\\_progress { position: static; }"),
    ("a hex-escaped first character",
     ".exportv__progress { position: sticky; bottom: 0; }\n"
     ".\\65 xportv__progress { position: static; }"),
    ("an uppercase property name",
     ".exportv__progress { position: sticky; bottom: 0; }\n"
     ".exportv__progress { POSITION: static; }"),
    ("a capitalised property name",
     ".exportv__progress { position: sticky; bottom: 0; }\n"
     ".exportv__progress { Bottom: auto; }"),
    ("an uppercase name on the checked rule itself",
     ".exportv__progress { POSITION: sticky; BOTTOM: 0; }"),
]


@pytest.mark.parametrize(
    "what,sheet", DIFFERENTLY_SPELLED_RULES,
    ids=[name for name, _ in DIFFERENTLY_SPELLED_RULES],
)
def test_a_rule_spelled_differently_from_the_one_checked_is_refused(what, sheet):
    """A browser reads these as the checked rule. This file reads them as
    something else, and until it refused them it read them as nothing at all -
    which is worse, because a rule it cannot see cannot undo one it can."""
    with pytest.raises(_CannotModel):
        _rule(sheet, ".exportv__progress", STICKY_PROPERTIES, where="app.css")


def test_the_shipped_sheets_are_spelled_the_way_this_file_reads_them():
    """The floor under both refusals, and the reason they are shippable at
    all: `_ESCAPE` and `_MIXED_CASE_PROPERTY` find nothing in either shipped
    sheet, so refusing costs the maintainer nothing today."""
    assert stylesheets(), "no stylesheets found at all"
    for sheet in stylesheets():
        body = css(sheet)
        assert _ESCAPE.search(body) is None, f"{sheet.name} escapes an identifier"
        assert _MIXED_CASE_PROPERTY.search(body) is None, f"{sheet.name} has a mixed-case property"
        # ...and the patterns still match something, or the two asserts above
        # are satisfied by a regex that stopped working.
    assert _ESCAPE.search(r".a\_b { x: 1px; }") is not None
    assert _MIXED_CASE_PROPERTY.search(".a { POSITION: static; }") is not None
    assert _MIXED_CASE_PROPERTY.search(".a { -WebKit-transform: none; }") is not None
    # A custom property is case-SENSITIVE, so `--Motion-Fast` is a different
    # property rather than a mis-spelling, and refusing it would be a false
    # red. This assert is why the pattern carries a `(?!--)`; without it the
    # refusal turns down legitimate CSS, which is the one way a loud guard
    # gets deleted rather than fixed.
    assert _MIXED_CASE_PROPERTY.search(":root { --Motion-Fast: 1ms; }") is None


#: Where a comment sits INSIDE a token. A comment is consumed by the CSS
#: tokenizer and emits nothing, so `posi/**/tion` is two identifiers and the
#: declaration is invalid - a browser drops it, the initial value applies and
#: the block returns to normal flow. Deleting the comment produced
#: `position: sticky` here, which is a declaration that does not exist.
#:
#: Found by probing after the reported evasions, and green: the shipped sticky
#: rule could be made invalid to a browser and unchanged to this file by four
#: characters.
COMMENTS_INSIDE_TOKENS = [
    ("in the property name",
     ".exportv__progress { posi/**/tion: sticky; bottom: 0; }"),
    ("in the value keyword",
     ".exportv__progress { position: sti/**/cky; bottom: 0; }"),
    ("in a custom property name",
     ".exportv__progress { position: sticky; bottom: calc(var(--space/**/-6) * -1); }"),
]


@pytest.mark.parametrize(
    "what,sheet", COMMENTS_INSIDE_TOKENS, ids=[name for name, _ in COMMENTS_INSIDE_TOKENS]
)
def test_a_comment_separates_the_tokens_it_sits_between(what, sheet):
    """The declaration must not come back live, by any route.

    This is the one correction in this round that is NOT a refusal, because it
    is not a construct the file declines to model - it is a stripper that was
    wrong about what a comment does. The right behaviour is a space, which is
    what a comment is to a tokenizer, and it lands at the reader where the
    other comment rule already lives.
    """
    declarations, _unevaluated = _rule(
        without_comments(sheet), ".exportv__progress", STICKY_PROPERTIES, where="app.css"
    )
    with pytest.raises(AssertionError):
        assert_sticks_to_the_bottom("the progress block", declarations)


def test_the_stripper_keeps_the_lines_a_comment_spanned():
    """...so a refusal's line number still points at the right line. A
    multi-line comment replaced by one space would shift everything after it
    up, and every message in `_splittable` names a line."""
    text = without_comments("a\n/* two\nlines */\nb")

    assert text.count("\n") == 3, text
    assert text.splitlines()[-1] == "b", text


def test_the_stripper_still_removes_the_comment_itself():
    """The other direction, or the space substitution is satisfied by a
    stripper that stopped stripping."""
    assert without_comments("/* gone */") == " "
    assert "gone" not in without_comments(".a { /* gone */ color: red; }")
    assert "color: red" in without_comments(".a { /* gone */ color: red; }")


#: Sheets a browser and this file's regexes read differently because of a
#: single CHARACTER. Both rows below were found by probing after the two
#: reported evasions were fixed, and both were green.
DISAGREEING_CHARACTERS = [
    # CSS whitespace is space, tab, LF, FF and CR. Python's `\s` is much
    # larger, and every anchored lookup here is built out of `\s*`, so each of
    # these reads as a declaration and is invalid - dropped - in the browser.
    ("a no-break space", "\u00a0"),
    ("an ideographic space", "\u3000"),
    ("a vertical tab", "\u000b"),
    ("a next-line control", "\u0085"),
    ("a file separator control", "\u001c"),
    # Not whitespace at all, but the same class of defect: a text comparison
    # that a character makes wrong.
    ("a zero-width space", "\u200b"),
]


@pytest.mark.parametrize(
    "what,character", DISAGREEING_CHARACTERS,
    ids=[name for name, _ in DISAGREEING_CHARACTERS],
)
def test_a_character_css_and_this_file_disagree_about_is_refused(what, character):
    sheet = (".exportv__progress {" + character + "position: sticky;"
             + character + "bottom: 0; }")
    with pytest.raises(_CannotModel) as refusal:
        _rule(sheet, ".exportv__progress", STICKY_PROPERTIES, where="app.css")
    assert "U+" in str(refusal.value), refusal.value


UNTERMINATED_COMMENTS = [
    # The brace pair is what makes this one work: it resets the rule splitter
    # so the selector after it comes out clean. Without it the leftover comment
    # text lands in the selector and the rule is merely unevaluated, which is
    # why the plain spelling looked safe.
    ("with a brace pair to reset the splitter",
     "/* a browser ignores everything from here { }\n"
     ".exportv__progress { position: sticky; bottom: 0; }"),
    ("plain",
     "/* a browser ignores everything from here\n"
     ".exportv__progress { position: sticky; bottom: 0; }"),
    ("a stray closer",
     ".a { color: red; } */\n.exportv__progress { position: sticky; bottom: 0; }"),
]


@pytest.mark.parametrize(
    "what,sheet", UNTERMINATED_COMMENTS, ids=[name for name, _ in UNTERMINATED_COMMENTS]
)
def test_a_comment_the_stripper_could_not_close_is_refused(what, sheet):
    """Each sheet goes through `without_comments` and then `_rule`, which has
    to raise `_CannotModel` naming a comment. `COMMENT` needs a `/*` and a `*/`
    to match, so each of these leaves a delimiter behind for
    `_COMMENT_REMNANT` to find - the first two are missing the `*/`, the third
    the `/*`. What the browser does with the three differs; the note above
    `_COMMENT_REMNANT` works one of them through."""
    with pytest.raises(_CannotModel) as refusal:
        _rule(without_comments(sheet), ".exportv__progress", STICKY_PROPERTIES,
              where="app.css")
    assert "comment" in str(refusal.value).lower(), refusal.value


def test_the_shipped_sheets_are_ascii_with_every_comment_closed():
    """The floor under both refusals above.

    The `§`, `·`, `–` and emoji in these sheets' prose are all inside
    comments, which are stripped before any of this runs - so the refusal
    costs the maintainer nothing today. What `_ALIEN_CHARACTER` matches is the
    complement of tab, line feed, form feed, carriage return and printable
    ASCII; a homoglyph drawn from printable ASCII is not in that set.
    """
    assert stylesheets(), "no stylesheets found at all"
    for sheet in stylesheets():
        body = css(sheet)
        assert _ALIEN_CHARACTER.search(body) is None, f"{sheet.name} is not ASCII"
        assert _COMMENT_REMNANT.search(body) is None, f"{sheet.name} has an open comment"
    # ...and both patterns still match something.
    assert _ALIEN_CHARACTER.search(".a { \u00a0color: red; }") is not None
    assert _COMMENT_REMNANT.search(".a { } /* open") is not None
    # Comments themselves may say whatever they like: the reader strips them
    # first, and asserting otherwise would make this a prose rule.
    assert _ALIEN_CHARACTER.search(without_comments("/* \u00a7 2.6 - \u2013 */\n.a { b: c; }")) is None


#: At-rules the reader turns down, and what each of them would otherwise hide.
UNMODELLED_AT_RULES = [
    ("an imported stylesheet", '@import url(other.css);\n.x { position: sticky; }'),
    ("a cascade layer", "@layer base, app;\n.x { position: sticky; }"),
    ("a layer block", "@layer app { .x { position: sticky; } }"),
    ("a feature query", "@supports (position: sticky) { .x { position: sticky; } }"),
    ("a container query", "@container (min-width: 1px) { .x { position: sticky; } }"),
    ("a font face", "@font-face { font-family: X; src: url(x.woff2); }"),
]


@pytest.mark.parametrize(
    "what,sheet", UNMODELLED_AT_RULES, ids=[name for name, _ in UNMODELLED_AT_RULES]
)
def test_an_at_rule_this_file_does_not_model_is_refused(what, sheet):
    with pytest.raises(_CannotModel) as refusal:
        _splittable(sheet, "app.css")
    assert "@" in str(refusal.value), refusal.value


def test_the_at_rules_the_sheets_actually_use_are_modelled():
    """The floor. A refusal that turned down `@media` would be found at once;
    one that turns down NOTHING would not, and `@import` would be open again
    with this file green."""
    assert stylesheets(), "no stylesheets found at all"
    used = set()
    for sheet in stylesheets():
        used.update(match.group(1).lower() for match in _AT_RULE.finditer(css(sheet)))
    assert used, "no at-rule found in any stylesheet; the pattern stopped matching"
    assert used <= set(MODELLED_AT_RULES), f"a shipped sheet uses {used - set(MODELLED_AT_RULES)}"


#: Declarations this file REFUSES to resolve, because `!important` is not the
#: cascade it implements. The first row is the evasion as it was reported: an
#: EARLIER static rule with the flag on it beat the later sticky one in the
#: browser while `_rule` merged them and last-wins read the sticky one.
REFUSED_DECLARATIONS = [
    ("an earlier flagged rule", "position",
     ".setc__status { position: static !important; }\n"
     ".setc__status { position: sticky; bottom: 0; }"),
    ("a flagged declaration on its own", "position",
     ".setc__status { position: sticky !important; bottom: 0; }"),
    ("spaced and capitalised", "position",
     ".setc__status { position: static ! IMPORTANT; }\n"
     ".setc__status { position: sticky; }"),
    ("a flagged offset", "bottom",
     ".x { bottom: 0 !important; }"),
]


@pytest.mark.parametrize(
    "what,name,sheet", REFUSED_DECLARATIONS,
    ids=[name for name, _, _ in REFUSED_DECLARATIONS],
)
def test_an_important_declaration_is_refused_rather_than_ranked(what, name, sheet):
    with pytest.raises(_CannotModel) as refusal:
        _declaration(name, sheet)
    assert "important" in str(refusal.value).lower(), refusal.value


def test_the_rule_reader_names_the_file_the_selector_and_the_property():
    """The refusal has to be actionable, or a maintainer deletes it.

    Naming only "something is !important" makes someone grep a 1700-line
    stylesheet. The three things they need are which file, which rule and
    which property, and `_rule` knows all three at the point it gives up.
    """
    sheet = (".setc__status { position: static !important; }\n"
             ".setc__status { position: sticky; bottom: 0; }")

    with pytest.raises(_CannotModel) as refusal:
        _rule(sheet, ".setc__status", STICKY_PROPERTIES, where="app.css")

    message = str(refusal.value)
    assert "app.css" in message, message
    assert ".setc__status" in message, message
    assert "position" in message, message


def test_a_flagged_rule_that_only_mentions_the_selector_is_refused_too():
    """`.never-used.setc__status { position: static !important; }` does not
    apply to the status line on its own - but whether it does needs a selector
    engine, and the `unevaluated` path exists precisely because this file has
    none. Handing it back as "unevaluated" would be fine; reading past it
    because the flag made it unresolvable would not."""
    sheet = (".never-used.setc__status { position: static !important; }\n"
             ".setc__status { position: sticky; bottom: 0; }")

    with pytest.raises(_CannotModel):
        _rule(sheet, ".setc__status", STICKY_PROPERTIES, where="app.css")


def test_an_important_declaration_is_read_where_the_flag_is_the_point():
    """...and the refusal is not simply "never look at `!important`".

    `_important_declaration` is the other half. It reads a flagged declaration
    and refuses an UNFLAGGED one, which is the same claim from the other side:
    what it cannot do is rank the two against each other.
    """
    flagged = "* { animation-duration: 1ms !important; }"
    assert _important_declaration("animation-duration", flagged) == "1ms"
    assert _declares_important("animation-duration", r"^1ms$", flagged)

    with pytest.raises(_CannotModel):
        _important_declaration("animation-duration", "* { animation-duration: 1ms; }")

    mixed = ("* { animation-duration: 1ms !important; }\n"
             ".x { animation-duration: 700ms; }")
    with pytest.raises(_CannotModel):
        _important_declaration("animation-duration", mixed)


def test_the_shipped_sheets_declare_nothing_important_the_guard_resolves():
    """The floor under the refusals above.

    They are only worth having if the real sheets pass them, and the one place
    these stylesheets DO use `!important` - the reduced-motion block - is read
    through `_important_declaration`, which requires it.

    STATED AS WHAT IS ASSERTED: `_important_properties` finds nothing in the
    merged declaration text `_rule` returns for `.setc__status` and for
    `.exportv__progress`, and finds exactly the four listed names in the
    reduced-motion block of tokens.css. That is a claim about those two merged
    strings and that one block - not about the sheet. A rule `_rules` does not
    emit under one of those two selectors contributes nothing to either
    string and is not read here; evasion 2 above is the shape that does it.
    """
    body = css(APP_CSS)
    for selector in (".setc__status", ".exportv__progress"):
        declarations, _unevaluated = _rule(body, selector, STICKY_PROPERTIES,
                                           where=APP_CSS.name)
        assert declarations, f"{selector} is gone"
        assert _important_properties(declarations) == [], (
            f"{selector} declares something !important: {declarations}"
        )

    reduced = _block_body(REDUCED_MOTION_QUERY.search(css(TOKENS_CSS)), css(TOKENS_CSS))
    assert _important_properties(reduced) == [
        "animation-duration",
        "animation-iteration-count",
        "transition-duration",
        "scroll-behavior",
    ], "the reduced-motion block no longer flags what it overrides"


#: The other direction, or the check above is satisfied by a lookup that never
#: finds anything. Spacing, the end of a block, the start of the text and a
#: missing final semicolon are all real CSS.
REAL_DECLARATIONS = [
    ("--motion-fast", ":root { --motion-fast: 1ms; }", "1ms"),
    ("--motion-fast", ":root{--motion-fast:1ms}", "1ms"),
    ("--text-xs", ":root { --a: 1px; --text-xs: 0.6875rem; }", "0.6875rem"),
    ("--text-xs", ":root { --not--text-xs: 1px; --text-xs: 0.6875rem; }", "0.6875rem"),
    # `!important` is no longer resolved by `_declaration` at all - it is
    # refused, and `REFUSED_DECLARATIONS` below is where that is pinned. What
    # stays here is the reduced-motion block's shape read the other way, by
    # the function that REQUIRES the flag.
    ("animation-duration", "* { animation-duration: 1ms; }", "1ms"),
    ("position", "position: sticky; bottom: 0;", "sticky"),
    ("bottom", "position: sticky; bottom: calc(var(--space-6) * -1);",
     "calc(var(--space-6) * -1)"),
    ("bottom", "bottom: 0", "0"),
    ("--motion-fast", "@media (prefers-reduced-motion: reduce) {\n"
                      "  :root { --motion-fast: 1ms; }\n}", "1ms"),
    # The cascade. `re.search` returns the FIRST declaration, and the browser
    # keeps the last.
    ("bottom", "bottom: 1px; bottom: 2px;", "2px"),
    ("position", ".x { position: sticky; } .x { position: static; }", "static"),
]


@pytest.mark.parametrize("name,sheet,expected", REAL_DECLARATIONS)
def test_the_anchored_lookup_still_finds_a_real_declaration(name, sheet, expected):
    assert _declaration(name, sheet) == expected


def test_a_var_is_never_resolved_from_a_longer_name_that_ends_in_it():
    """`_custom_property` end to end, which is where the offset checker reads.

    The call-site patch this replaces asked whether the name began with `--`.
    That rejected `var(text-xs)` and nothing else: `--not--text-xs` begins with
    `--` and still is not `--text-xs`.
    """
    with pytest.raises(_NotALength) as raised:
        _type_of("var(--text-xs)", ":root { --not--text-xs: 1px; }")
    assert "does not declare" in str(raised.value)

    assert _type_of("var(--text-xs)", ":root { --not--text-xs: 2px; --text-xs: 1px; }") == "length"


def test_no_token_name_ends_in_another_token_name():
    """A NAMING rule on the stylesheets, and only that.

    What makes the lookups above safe is the anchoring, not this: with it in
    place a decoy declaration is inert. This is the other half of the same
    claim, and it is about the SOURCE rather than about the reader - a name
    that ends in another declared name makes the sheet ambiguous to every
    consumer that is not a full CSS parser, which is this file, every grep a
    maintainer runs, and anyone reading it.

    It is the assertion that goes red if `--not--text-xs: 1px` is added beside
    `--text-xs`. It does NOT establish that any consumer reads the right
    declaration - `test_a_longer_name_that_contains_a_real_one_declares_
    something_else` is what establishes that - and it would not notice a decoy
    whose name merely contains a real one somewhere other than at its end.
    """
    declared = set()
    for sheet in stylesheets():
        declared.update(_custom_properties(css(sheet)))

    assert declared, "no custom properties found; the reader stopped matching"

    ambiguous = sorted(
        (longer, shorter)
        for longer in declared
        for shorter in declared
        if longer != shorter and longer.endswith(shorter)
    )
    assert ambiguous == [], (
        f"these names end in another declared name: {ambiguous} - a lookup for "
        f"the shorter one can be answered by the longer one's declaration"
    )


#: Rules that NAME `.setc__status` without applying to a bare one. Each
#: satisfied the `re.search(r"\.setc__status\s*\{...")` these replace.
SELECTOR_DECOYS = [
    ("a compound selector", ".never-used.setc__status { position: sticky; bottom: -2rem; }"),
    ("a descendant selector", ".setc .setc__status { position: sticky; bottom: -2rem; }"),
    ("an attribute selector", ".setc__status[hidden] { position: sticky; bottom: -2rem; }"),
    ("a pseudo-class", ".setc__status:hover { position: sticky; bottom: -2rem; }"),
    ("a child of it", ".setc__status > b { position: sticky; bottom: -2rem; }"),
]


@pytest.mark.parametrize("what,sheet", SELECTOR_DECOYS, ids=[n for n, _ in SELECTOR_DECOYS])
def test_a_rule_that_only_names_a_selector_is_not_that_rule(what, sheet):
    """The same defect as the declaration boundary, one level up.

    None of these apply to an element that merely carries the class, so a
    guard reading them as its rule reports a status line stuck to the bottom
    of a scrollport it is in fact scrolling out of.
    """
    declarations, unevaluated = _rule(sheet, ".setc__status", STICKY_PROPERTIES)

    assert declarations == "", f"{what} was read as the rule for .setc__status"
    # ...and reported rather than passed over, because whether it applies to
    # the element in front of the user is not something this can decide.
    assert unevaluated, f"{what} was ignored instead of reported"


def test_a_class_whose_name_merely_starts_the_same_is_a_different_class():
    """The other direction: `.setc__status-line` is not `.setc__status`, and
    reporting it would make the guard fail on legitimate CSS."""
    declarations, unevaluated = _rule(
        ".setc__status-line { position: static; }", ".setc__status", STICKY_PROPERTIES
    )

    assert declarations == ""
    assert unevaluated == []


def test_a_rule_that_names_the_selector_and_changes_nothing_is_not_reported():
    """`.exportv__progress[hidden] { display: none; }` ships in app.css and
    redeclares none of what the sticky check reads."""
    _declarations, unevaluated = _rule(
        ".x[hidden] { display: none; }", ".x", STICKY_PROPERTIES
    )

    assert unevaluated == []


def test_every_rule_for_a_selector_is_read_and_the_last_one_wins():
    """The cascade, which `re.search` cannot see: it returns the FIRST rule, so
    a later one undoing it was invisible.

    Both halves matter. A second rule that undoes the offset has to be caught,
    and a second rule that SUPPLIES it has to count - reading only the first
    would be a false red on a perfectly ordinary two-rule sheet.
    """
    undone = (
        ".setc__status { position: sticky; bottom: -2rem; }\n"
        ".setc__status { position: static; }\n"
    )
    declarations, unevaluated = _rule(undone, ".setc__status", STICKY_PROPERTIES)

    assert unevaluated == []
    assert _declaration("position", declarations) == "static", (
        "the later rule was not read, so a rule that undoes the offset is invisible"
    )
    with pytest.raises(AssertionError) as raised:
        assert_sticks_to_the_bottom("the status line", declarations)
    assert "back in the normal flow" in str(raised.value)

    supplied = (
        ".setc__status { position: sticky; }\n"
        ".a, .setc__status { bottom: calc(var(--space-6) * -1); }\n"
    )
    declarations, _unevaluated = _rule(supplied, ".setc__status", STICKY_PROPERTIES)

    assert_sticks_to_the_bottom("the status line", declarations)


def test_a_block_ends_where_its_braces_end():
    """The region-shaped half of the same defect, on the one input the real
    sheet cannot supply.

    The reduced-motion check used to read `body[body.index(query):]` - every
    byte from the query to the end of the file - so a token declared AFTER the
    block, applying unconditionally, satisfied a check scoped inside it. In
    tokens.css that block happens to be last, so the shipped sheet cannot tell
    a bounded read from an unbounded one and every mutation of the bound
    stayed green until this test existed.
    """
    sheet = (
        "@media (prefers-reduced-motion: reduce) {\n"
        "  :root { --motion-fast: 1ms; }\n"
        "}\n"
        ":root { --motion-base: 170ms; }\n"
    )
    query = REDUCED_MOTION_QUERY.search(sheet)
    assert query

    reduced = _block_body(query, sheet)

    assert _declaration("--motion-fast", reduced) == "1ms"
    assert _declaration("--motion-base", reduced) is None, (
        "a declaration written after the block was read as though it were inside it"
    )


def test_a_media_query_that_only_begins_like_the_preference_is_not_it():
    """`@media (prefers-reduced-motion: reduce) and (min-width: 99999px)`
    CONTAINS the text this used to look for and applies to nobody, so the query
    is matched up to the brace that opens its block."""
    assert REDUCED_MOTION_QUERY.search("@media (prefers-reduced-motion: reduce) {}")
    assert REDUCED_MOTION_QUERY.search("@media(prefers-reduced-motion:reduce){}")
    assert not REDUCED_MOTION_QUERY.search(
        "@media (prefers-reduced-motion: reduce) and (min-width: 99999px) {}"
    )
    assert not REDUCED_MOTION_QUERY.search("@media (prefers-reduced-motion: no-preference) {}")


def test_the_markup_reader_really_does_strip():
    """Guard the guard, the third of three. index.html carries no comment
    today, so nothing else in this file would notice a stripper that removed
    everything or nothing - which is exactly the state the CSS reader was in
    before six regexes were found to be wrong about the browser."""
    # A SPACE, not nothing - see `_without`. In markup the difference is
    # cosmetic; in CSS it is the difference between a declaration the browser
    # applies and one it drops, and there is one stripper rule rather than
    # three so that cannot be true in one reader and false in another.
    assert without_html_comments("<main><!-- <aside> --></main>") == "<main> </main>"
    # Whitespace and the newlines it spanned, not the empty string - the
    # substitution keeps line numbers true; see
    # `test_the_stripper_keeps_the_lines_a_comment_spanned`.
    assert without_html_comments("<!--\n<main>\n-->").strip() == "", (
        "a multi-line comment survived"
    )
    assert "<main>" not in without_html_comments("<!--\n<main>\n-->")
    assert without_html_comments("<main>x</main>") == "<main>x</main>", "the stripper ate the markup"

    stripped = html(INDEX_HTML)

    assert "<!--" not in stripped and "-->" not in stripped, "comments survived the reader"
    assert "<main" in stripped, "the reader ate the markup"


def test_a_commented_out_custom_property_is_not_a_declaration():
    """The other boundary. `_type_of` takes a sheet as a STRING and cannot know
    whether its caller stripped it, so it strips at that edge too - and the
    lookup there is unanchored `re.search`, so a commented declaration matches
    on one line as readily as on its own. Both edges are load-bearing and both
    are pinned; what was wrong before was the six unguarded readers between
    them, not the number of edges.
    """
    with pytest.raises(_NotALength) as raised:
        _type_of("var(--parked)", ":root { /* --parked: 1px; */ }")
    assert "tokens.css does not declare" in str(raised.value)

    assert _type_of("var(--parked)", ":root { --parked: 1px; }") == "length"


def test_there_is_a_token_file_and_it_is_where_the_colours_live():
    assert TOKENS_CSS.is_file()
    assert HEX_COLOUR.search(css(TOKENS_CSS)), (
        "tokens.css defines no colour at all, which makes every check below vacuous"
    )


def test_no_stylesheet_other_than_tokens_contains_a_literal_colour():
    """The whole point of a token layer is that the palette lives in one file.

    A single hex in a component stylesheet is not a nit - it is a colour that
    will not move when the palette does, and it is invisible in review.
    """
    offenders = {}
    for sheet in stylesheets():
        if sheet == TOKENS_CSS:
            continue
        body = css(sheet)
        found = HEX_COLOUR.findall(body) + [
            match.group(0) for match in COLOUR_FUNCTION.finditer(body)
        ]
        if found:
            offenders[sheet.name] = sorted(set(found))

    assert offenders == {}, f"literal colours outside tokens.css: {offenders}"


def test_no_script_sets_a_literal_colour():
    """Styling from JS is the other way the token layer leaks."""
    offenders = {}
    for script in scripts():
        body = js(script)
        found = HEX_COLOUR.findall(body)
        if found:
            offenders[str(script.relative_to(JS))] = sorted(set(found))

    assert offenders == {}, f"literal colours in JavaScript: {offenders}"


def test_every_custom_property_used_is_actually_defined():
    """A typo in a var() name is silent: the declaration is simply dropped and
    the element inherits, which usually still looks plausible."""
    defined = set(_custom_properties(css(TOKENS_CSS)))
    # Properties the components set on an element at runtime.
    for script in scripts():
        defined.update(re.findall(r"setProperty\(\s*['\"](--[a-z0-9-]+)", js(script)))

    used = set()
    for sheet in stylesheets():
        used.update(re.findall(r"var\(\s*(--[a-z0-9-]+)", css(sheet)))

    assert defined, "no custom properties found; the regex stopped matching"
    assert used - defined == set(), f"undefined custom properties: {sorted(used - defined)}"


def test_the_type_scale_has_at_most_six_sizes():
    """More than six and the hierarchy stops being a hierarchy."""
    sizes = sorted(
        name for name in _custom_properties(css(TOKENS_CSS)) if name.startswith("--text-")
    )

    assert 1 <= len(sizes) <= 6, f"{len(sizes)} font sizes: {sizes}"


# ---------------------------------------------------------------------------
# Motion and focus
# ---------------------------------------------------------------------------


DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|s)\b")

#: Under the preference, motion is meant to be gone, not merely brisk.
REDUCED_MOTION_CEILING_MS = 10

#: A repeating indicator is a rate, not a delay anyone waits out. This bounds
#: it anyway, so "exempt" does not mean "unbounded".
REPEATING_CEILING_MS = 1000

#: The whole query, up to and including the brace that opens its block. Not a
#: substring of it: `@media (prefers-reduced-motion: reduce) and (min-width:
#: 99999px)` CONTAINS the text this used to look for, and applies to nobody.
REDUCED_MOTION_QUERY = re.compile(
    r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{"
)


def _milliseconds(value):
    """The single duration in a declaration value, in ms, or None."""
    match = DURATION.search(value)
    if match is None:
        return None
    number, unit = match.groups()
    return float(number) * (1000 if unit == "s" else 1)


def _rules(text):
    r"""(selector, declarations, depth) for each `([^{}]+)\{([^{}]*)\}` match
    in ``text``, left to right and non-overlapping.

    `[^{}]+` cannot cross a brace, so what precedes an inner `{` is what
    comes back as the selector: `_rules(".a { .b { x } }")` returns
    `[(' .b ', ' x ', 1)]` and `.a` appears nowhere in the result - measured.
    Evasion 2 in the boundary note above `stylesheets()` works a
    shipped-shaped case of that through.

    Takes text that has ALREADY been through `css()`. Stripping again here
    would be a second place the rule lives, which is the shape of the bug this
    replaced.

    Refuses a string, because `{` and `}` inside one are content rather than
    structure: `.x { content: "{}" }` splits into a rule whose selector is
    `content: "` and whose body is empty, and the real `.x` rule vanishes from
    the result entirely.

    DEPTH is how many blocks are still open where the rule begins - 0 for a
    rule written at the top of the sheet, 1 for one inside an `@media`, an
    `@supports`, a `@layer` or a `@keyframes`. It is reported rather than
    discarded because a rule's at-rule context decides WHETHER IT APPLIES, and
    a reader that drops it says `@media (min-width: 99999px) { .exportv__progress
    { position: sticky; } }` and `.exportv__progress { position: sticky; }`
    are the same rule. They are not: the first applies to nobody.
    """
    found = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", _splittable(text)):
        opening = match.start(2) - 1
        depth = text.count("{", 0, opening) - text.count("}", 0, opening)
        found.append((match.group(1), match.group(2), depth))
    return found


def _declared_durations():
    """(milliseconds, declaration) for each `DURATION` match in each
    semicolon-split fragment of each block `_rules` emits, for each sheet
    `stylesheets()` returns."""
    found = []
    for sheet in stylesheets():
        for _selector, declarations, _depth in _rules(css(sheet)):
            for declaration in declarations.split(";"):
                for number, unit in DURATION.findall(declaration):
                    found.append(
                        (
                            float(number) * (1000 if unit == "s" else 1),
                            " ".join(declaration.split()),
                        )
                    )
    return found


def test_reduced_motion_is_respected_at_the_token_level():
    """The duration TOKENS are overridden inside the preference block, so a
    component that reads them through `var()` gets the reduced value without
    opting in individually. Whether a given component reads them is not
    something this test looks at.

    The VALUES are asserted, not the presence of the property names. Checking
    only that the words appeared let the whole block be kept while the numbers
    inside it were raised back to their normal durations - a guard that passes
    for a stylesheet which does not reduce motion at all is worse than none,
    because it reads like a check.
    """
    body = css(TOKENS_CSS)

    query = REDUCED_MOTION_QUERY.search(body)
    assert query, "tokens.css has no `@media (prefers-reduced-motion: reduce)` block"
    # BOUNDED to the block. This used to be `body[body.index(query):]`, which
    # runs to the end of the file, so a `--motion-fast` declared AFTER the
    # media block - outside it, applying always - satisfied the override check.
    reduced = _block_body(query, body)
    assert reduced is not None, "the prefers-reduced-motion block is never closed"

    # The two TOKENS, read through `var()` wherever a component uses them.
    # Ordinary declarations: `_declarations_of` returns a single value for each
    # inside this block, so there is no last-wins choice to make and
    # `_declaration` resolves them.
    #
    # ANCHORED. Unanchored, renaming these two to `--not--motion-fast` and
    # `--not--motion-base` satisfied this loop while leaving the real ones at
    # 110 ms and 170 ms - the whole application ignoring the preference with
    # this file green.
    #
    # ...and the two PROPERTIES, which are the backstop for anything that does
    # not read the tokens, and which are read with `_important_declaration`
    # because the flag on them is load-bearing rather than incidental: without
    # it a component declaring its own `animation-duration` wins on
    # specificity and the preference is ignored for exactly the animations
    # most likely to have one. Asserting that they ARE flagged is a claim this
    # test did not make before - `_declaration` used to hand back
    # `"1ms !important"` and `_milliseconds` read the 1 out of it, so the flag
    # could be deleted with this test green.
    for name, resolve in (
        ("--motion-base", _declaration),
        ("--motion-fast", _declaration),
        ("animation-duration", _important_declaration),
        ("transition-duration", _important_declaration),
    ):
        declared = resolve(name, reduced)
        assert declared is not None, f"{name} is not overridden under prefers-reduced-motion"

        milliseconds = _milliseconds(declared)
        assert milliseconds is not None, (
            f"{name} is overridden with {declared!r}, which is not a duration"
        )
        assert milliseconds <= REDUCED_MOTION_CEILING_MS, (
            f"{name} is still {milliseconds:g} ms under prefers-reduced-motion"
        )

    # A 1 ms animation that still repeats forever is still motion. Flagged for
    # the same reason as the durations beside it.
    assert _declares_important("animation-iteration-count", r"^1\b", reduced), (
        "repeating animations are not stopped under prefers-reduced-motion"
    )


def test_no_transition_or_animation_is_longer_than_two_hundred_milliseconds():
    """The exemption is keyed on what the declaration IS, not on its value.

    This used to exempt every duration equal to 700 ms, on the grounds that the
    spinner is 700 ms. That meant setting an interaction token to 700 ms passed
    the check - the guard exempted a number rather than a kind of thing. The
    distinction that actually matters is whether the animation repeats: a
    repeating indicator is a rate, and anything that runs ONCE in response to
    an action is a delay the user sits through.
    """
    found = _declared_durations()
    assert found, "no durations found; the regex stopped matching"

    repeating = [row for row in found if "infinite" in row[1]]
    once = [row for row in found if "infinite" not in row[1]]

    assert repeating, (
        "no repeating animation is declared, so the exemption below is vacuous "
        "and this test would silently stop distinguishing anything"
    )
    assert once, "no one-shot durations found; the regex stopped matching"

    worst_repeating = max(repeating)
    assert worst_repeating[0] <= REPEATING_CEILING_MS, (
        f"repeating animation over {REPEATING_CEILING_MS} ms: {worst_repeating[1]}"
    )

    worst_once = max(once)
    assert worst_once[0] <= 200, f"transition over 200 ms: {worst_once[1]}"


def test_there_is_a_visible_focus_ring(tokens):
    """The token has to BE a ring, not merely exist.

    ``--focus-ring: none`` is a declaration, so a check that asks only whether
    the name is declared is satisfied by it - and what it declares draws
    nothing. So the VALUE is what is asserted: no `none`, a non-zero
    `px`/`rem`/`em` somewhere in it, and a colour.
    """
    body = css(APP_CSS)

    assert ":focus-visible" in body
    # `var(--focus-ring)`, not `--focus-ring`: the bare name is satisfied by
    # `--not--focus-ring` and by a token that is declared and never used.
    assert "var(--focus-ring)" in body, "app.css never uses the focus ring token"

    ring = " ".join(tokens["--focus-ring"].split())

    assert "none" not in ring, f"--focus-ring draws nothing: {ring!r}"
    assert re.search(r"\b[1-9]\d*(?:\.\d+)?(?:px|rem|em)\b", ring), (
        f"--focus-ring has no non-zero thickness: {ring!r}"
    )
    assert "var(--" in ring or HEX_COLOUR.search(ring), (
        f"--focus-ring names no colour: {ring!r}"
    )


def test_focus_is_never_removed_without_being_replaced():
    """`outline: none` with nothing in its place is the single commonest way a
    keyboard user is locked out of an interface."""
    body = css(APP_CSS)
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", body)

    for selector, declarations in blocks:
        if _declares("outline", r"^none\b", declarations):
            replaced = (
                _declaration("box-shadow", declarations) is not None
                or ":focus-visible" in selector
            )
            assert replaced, f"outline removed with no replacement in: {selector.strip()}"


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------


def _channel(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(rgb):
    red, green, blue = (_channel(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first, second):
    a, b = _luminance(first), _luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _from_hex(value):
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(component * 2 for component in value)
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _from_hsl(hue, saturation, lightness):
    return colorsys.hls_to_rgb(hue / 360.0, lightness / 100.0, saturation / 100.0)


@pytest.fixture(scope="module")
def tokens():
    """`_custom_properties(css(TOKENS_CSS))`, keyed by the WHOLE name.

    Anchored at a declaration boundary, so a token is read off the declaration
    that carries its exact name -
    and so a declaration that is not at the start of a line is not invisible.
    """
    return _custom_properties(css(TOKENS_CSS))


TEXT_ON_SURFACE = [
    (foreground, surface)
    for foreground in ("--ink-primary", "--ink-secondary", "--ink-tertiary")
    for surface in (
        "--surface-0",
        "--surface-1",
        "--surface-2",
        "--surface-3",
        "--surface-4",
    )
]


@pytest.mark.parametrize("foreground, surface", TEXT_ON_SURFACE)
def test_body_text_clears_the_contrast_floor(tokens, foreground, surface):
    ratio = _contrast(_from_hex(tokens[foreground]), _from_hex(tokens[surface]))

    assert ratio >= 4.5, f"{foreground} on {surface} is {ratio:.2f}:1"


@pytest.mark.parametrize("accent", ["--accent", "--accent-2", "--danger"])
@pytest.mark.parametrize("surface", ["--surface-1", "--surface-2", "--surface-3"])
def test_accent_text_clears_the_contrast_floor(tokens, accent, surface):
    ratio = _contrast(_from_hex(tokens[accent]), _from_hex(tokens[surface]))

    assert ratio >= 4.5, f"{accent} on {surface} is {ratio:.2f}:1"


def test_the_primary_button_label_clears_the_contrast_floor(tokens):
    ratio = _contrast(
        _from_hex(tokens["--ink-on-accent"]), _from_hex(tokens["--accent-strong"])
    )

    assert ratio >= 4.5, f"{ratio:.2f}:1"


def _hsl_token(tokens, name):
    """Parse `hsl(var(--camelot-hue, Xdeg) S% L%)` into (saturation, lightness)."""
    # `var(--camelot-hue` and then ANYTHING up to a `)` also matches
    # `var(--camelot-hue-somewhere-else, 220deg)`, which is a different custom
    # property and not the one format.js sets. The name has to end where a
    # custom-property name can end: at the fallback comma, or at the `)`.
    match = re.search(
        r"hsl\(\s*var\(\s*--camelot-hue\s*(?:,[^()]*)?\)\s+([\d.]+)%\s+([\d.]+)%\s*\)",
        tokens[name],
    )
    assert match, f"{name} is no longer an hsl() built on --camelot-hue: {tokens[name]}"
    return float(match.group(1)), float(match.group(2))


@pytest.mark.parametrize("position", range(1, 13))
@pytest.mark.parametrize("mode", ["minor", "major"])
def test_every_camelot_pill_is_readable(tokens, position, mode):
    """All twenty-four wheel positions, not a sampled few.

    Hue is a SECOND signal on these pills - the text is always drawn - but a
    pill whose own label is unreadable is worse than no colour at all.
    """
    hue = (position - 1) * 30
    background = "--camelot-bg" if mode == "minor" else "--camelot-bg-major"
    foreground = "--camelot-fg" if mode == "minor" else "--camelot-fg-major"

    ratio = _contrast(
        _from_hsl(hue, *_hsl_token(tokens, foreground)),
        _from_hsl(hue, *_hsl_token(tokens, background)),
    )

    assert ratio >= 4.5, f"Camelot {position}{'B' if mode == 'major' else 'A'}: {ratio:.2f}:1"


def test_harmonic_neighbours_are_adjacent_in_hue(tokens):
    """The reason the pills are coloured at all: hue = (n-1)*30 walks the wheel,
    so 7A and 8A sit next to each other in colour as well as in number."""
    body = js(JS / "format.js")

    assert "(position - 1) * 30" in body


# ---------------------------------------------------------------------------
# The page itself
# ---------------------------------------------------------------------------


def test_the_page_has_no_inline_styles():
    """An inline style is a colour or a spacing value outside the system, and
    it outranks any ordinary rule in the sheet that would have corrected it.

    A grep for a `style="` attribute in stripped markup. Its JavaScript
    counterpart is `test_no_script_puts_css_on_the_page_outside_the_stylesheet`,
    which carries the limits of the word search it runs."""
    assert not re.search(r'\sstyle\s*=\s*"', html(INDEX_HTML))


def test_nothing_is_loaded_from_another_origin():
    """The app runs from a loopback server against a local library, and a frozen
    build has no guarantee of a network at all. A CDN font or script would make
    the UI depend on one."""
    offenders = []
    for path in [INDEX_HTML] + stylesheets() + scripts():
        # `source()`, because the kind of file is not known until the loop
        # runs. A CDN URL inside a comment loads nothing, so reading these raw
        # was a false RED waiting to happen.
        for match in re.finditer(r"""(?:https?:)?//[^\s'")]+""", source(path)):
            if match.group(0).startswith("//"):
                # Still skipped, and this is the one thing here that is looser
                # than it looks: a protocol-relative `//cdn.example.com/x.js`
                # IS an external origin and is not reported. The JS stripper
                # eats one written in a string anyway, so tightening this would
                # be a claim about CSS and markup only. Named rather than
                # quietly relied on.
                continue
            offenders.append(f"{path.name}: {match.group(0)}")

    assert offenders == [], f"external origins referenced: {offenders}"


def test_the_shell_uses_real_landmarks():
    """A landmark is an ELEMENT, not a class name.

    This asserted ``class="main"``, which a ``<div>`` satisfies - so the guard
    endorsed the very thing the plan (step 2: "semantic landmarks (<nav>,
    <main>, <aside>)") asks for and the markup did not do. ``<main>`` is what
    "skip to main content" and every screen reader's landmark rotor navigate
    by; a div with a class is not in that list at all.
    """
    body = html(INDEX_HTML)

    assert re.search(r"<nav\b", body)
    assert re.search(r"<aside\b", body)
    assert re.search(r"<main\b", body), "the content region is not a <main> landmark"
    assert "</main>" in body
    assert re.search(r"<h1\b", body)

    # Exactly one, or "the main landmark" stops being a thing you can name.
    assert len(re.findall(r"<main\b", body)) == 1


def test_all_five_destinations_are_present():
    """Every catalogued destination has a nav item, built or not.

    This asserted a count of what is still a placeholder, and that number is
    wrong the moment any destination lands - the Library and Set Creator
    branches each edited it, from opposite sides, in the same merge. Which
    destinations are still placeholders is DERIVED from the markup by
    ``test_the_unimplemented_destinations_say_so``; this one only asks that
    none of the five disappeared.
    """
    body = html(INDEX_HTML)

    for destination in ("explore", "set-creator", "library", "export", "settings"):
        assert f'data-destination="{destination}"' in body


#: The eyebrow every not-yet-built destination carries.
PLACEHOLDER_EYEBROW = "Coming in the next PR"


def _destination_sections(body):
    """``(name, markup)`` for every ``<section class="view" id="view-...">``."""
    return re.findall(
        r'<section class="view" id="view-([a-z-]+)"[^>]*>(.*?)</section>', body, re.S
    )


def test_the_unimplemented_destinations_say_so():
    """DERIVED, not counted.

    This asserted ``== 3``. That number is wrong the moment any destination
    lands, so every such PR has to edit this one line - and two of them are in
    flight at once, which makes it a guaranteed conflict in a file neither PR is
    really changing. Worse, resolving that conflict by picking a number is
    exactly the edit that could silently drop a placeholder nobody has built.

    So the count comes from the markup: whatever still renders a placeholder
    must say it is coming, and nothing else may claim to.
    """
    body = html(INDEX_HTML)
    sections = _destination_sections(body)
    assert sections, "no destination sections found; the regex stopped matching"

    unbuilt = [name for name, markup in sections if 'class="placeholder"' in markup]

    assert body.count(PLACEHOLDER_EYEBROW) == len(unbuilt), (
        f"{len(unbuilt)} destinations still render a placeholder ({unbuilt}) but "
        f'"{PLACEHOLDER_EYEBROW}" appears {body.count(PLACEHOLDER_EYEBROW)} times'
    )
    for name, markup in sections:
        if name in unbuilt:
            assert PLACEHOLDER_EYEBROW in markup, f"{name} has a silent placeholder"
        else:
            assert PLACEHOLDER_EYEBROW not in markup, (
                f"{name} is built but still says it is coming"
            )


def test_the_derived_placeholder_check_still_discriminates():
    """RETIRED AND REPLACED, which is what its predecessor asked for.

    That test read::

        assert unbuilt, "no placeholders left; retire this check rather than
                         keeping a vacuous one"

    and it was right to. It existed because ``test_the_unimplemented_destinations_say_so``
    loops over the unbuilt list, and an empty list makes a loop pass over
    nothing; while any destination was still a placeholder, asserting that at
    least one existed kept that loop honest. Export was the last of the five,
    so on this branch the list is empty by construction and the old assertion
    can only fail. Keeping it would mean re-adding a placeholder to satisfy a
    test, which is the tail wagging the dog.

    What replaces it has to be falsifiable in the state the file is actually
    in, so it checks the two halves separately:

    * against the SHIPPED markup, that nothing is unbuilt and the eyebrow
      appears nowhere - so re-adding a placeholder, or leaving a stray
      "Coming in the next PR" behind after building a destination, fails here;
    * against a SYNTHETIC page, that the derivation still tells a placeholder
      section from a built one - so a regex that stopped matching, or a marker
      that was renamed, fails here rather than turning the check above into a
      pair of assertions about an empty list.

    The second half is the part the old test was really protecting: not that a
    placeholder exists, but that one would be SEEN.
    """
    body = html(INDEX_HTML)

    unbuilt = [
        name for name, markup in _destination_sections(body) if 'class="placeholder"' in markup
    ]
    assert unbuilt == [], f"a destination went back to being a placeholder: {unbuilt}"
    assert body.count(PLACEHOLDER_EYEBROW) == 0, (
        f'"{PLACEHOLDER_EYEBROW}" is still in the markup with nothing unbuilt'
    )

    sample = (
        '<section class="view" id="view-built" hidden aria-label="Built">'
        "<div class=\"real\"></div></section>"
        '<section class="view" id="view-unbuilt" hidden aria-label="Unbuilt">'
        f'<div class="placeholder"><p class="placeholder__eyebrow">{PLACEHOLDER_EYEBROW}</p>'
        "</div></section>"
    )
    found = _destination_sections(sample)

    assert [name for name, _ in found] == ["built", "unbuilt"], (
        f"the destination-section regex stopped matching: {found}"
    )
    assert [
        name for name, markup in found if 'class="placeholder"' in markup
    ] == ["unbuilt"], "the placeholder marker is no longer recognised"


def test_the_set_creator_destination_is_no_longer_a_placeholder():
    """The claim this PR makes about index.html, on its own so that landing it
    does not edit a line another destination's PR is also editing."""
    body = html(INDEX_HTML)
    sections = dict(_destination_sections(body))

    assert "set-creator" in sections, "the Set Creator section was renamed or removed"
    assert 'class="placeholder"' not in sections["set-creator"]
    assert 'data-destination="set-creator"' in body
    assert '<span class="nav__soon">Soon</span>' not in body.split(
        'data-destination="set-creator"'
    )[1].split("</button>")[0], "the Set Creator nav item still says Soon"


def test_the_export_destination_is_no_longer_a_placeholder():
    """The claim this PR makes about index.html, on its own hunk for the reason
    the Set Creator's version of it gives: landing a destination must not edit a
    line another destination's PR is also editing."""
    body = html(INDEX_HTML)
    sections = dict(_destination_sections(body))

    assert "export" in sections, "the Export section was renamed or removed"
    assert 'class="placeholder"' not in sections["export"]
    assert 'data-destination="export"' in body
    assert '<span class="nav__soon">Soon</span>' not in body.split(
        'data-destination="export"'
    )[1].split("</button>")[0], "the Export nav item still says Soon"


def test_nothing_says_soon_now_that_every_destination_is_built():
    """`.nav__soon` was the badge on an unbuilt destination. Export was the last
    one wearing it, so a nav item carrying it now is a claim about a destination
    that does not exist."""
    assert 'class="nav__soon"' not in html(INDEX_HTML)


def test_the_set_creator_status_line_cannot_be_scrolled_out_of_reach():
    """Inventory :244 and :1293 - the Tk status bar is packed ``side="bottom"``
    "so a short window cannot hide it". That is a property of the control, not
    of Tk's geometry manager, and it has to survive the port.

    Left in the normal flow the line sat under the generated rows, so with a
    500-row set the message announcing the set was off screen. This is a
    SOURCE-TEXT check - it cannot lay anything out - and the behavioural half
    was done by hand against real Chrome and recorded in the PR description.
    """
    body = css(APP_CSS)
    declarations, unevaluated = _rule(body, ".setc__status", STICKY_PROPERTIES, where=APP_CSS.name)

    assert declarations, "the Set Creator status rule is gone"
    assert unevaluated == [], (
        f"another rule naming .setc__status redeclares what this checks: {unevaluated}"
    )
    # By value - `bottom: auto` passed the presence check this used to make,
    # and means the status line scrolls away. Same claim, same guard as the
    # Export progress block below.
    assert_sticks_to_the_bottom("the Set Creator status line", declarations)
    # Opaque, or the rows scroll THROUGH the text rather than under it.
    assert _declares("background", r"^var\(\s*--surface", declarations), declarations


#: THE PRIMITIVES, not the write shapes. `style` covers the `style` property,
#: the `style` ATTRIBUTE and a `<style>` element; `cssText` is the bulk write;
#: `insertRule`/`deleteRule`/`adoptedStyleSheets` are the CSSOM.
#:
#: THIS USED TO SAY "there is no way round them". IT IS FALSE, and it was
#: falsified by running one:
#:
#:     progress['st' + 'yle']['position'] = 'static';
#:
#: put into the real Export component, all 272 tests green. These are five
#: WORDS, matched by `_STYLE_MENTION` in stripped source, and a computed
#: property name reaches the same object without spelling any of them.
#:
#: WHAT THE CHECK BELOW LITERALLY DOES, which is the only thing it can be
#: relied on for: it reads each file under `JS` through `js()`, splits the
#: result into LINES, and reports a line on which `_STYLE_MENTION` finds one
#: of the five words at a word boundary - UNLESS the word found is `style` and
#: `_CUSTOM_PROPERTY_WRITE` also matches SOMEWHERE ON THAT SAME LINE.
#:
#: THE EXEMPTION IS TESTED PER LINE, NOT PER MENTION, and that is a hole with
#: a measured shape rather than a suspicion:
#:
#:     progress.style.position = 'static'; progress.style.setProperty('--progress', '0%');
#:
#: `_STYLE_MENTION` finds `style` twice on that line and
#: `_CUSTOM_PROPERTY_WRITE.search(line)` is true, so BOTH mentions take the
#: `continue` - including the plain write that beats the sheet. Measured on
#: this line, not reasoned about: two mentions, one custom-property match, no
#: offence recorded.
#:
#: So this is not a statement about what scripts do. It is a statement about
#: which lines this loop appends to `offences`, and evasion 5 in the boundary
#: note above `stylesheets()` carries the rest.
#:
#: WRITTEN THIS WAY BECAUSE THE FIRST VERSION OF THIS CHECK WAS THE DEFECT
#: THIS WHOLE ROUND IS ABOUT. It matched `.style.<name> =`,
#: `.style.setProperty('<name>')`, `.cssText =` and `setAttribute('style')` -
#: four shapes - and `el.style['position'] = 'static'`,
#: `Object.assign(el.style, {position: 'static'})`, `const s = el.style; s.position = ...`,
#: `setProperty('bot' + 'tom', ...)`, an injected `<style>` element,
#: `adoptedStyleSheets` and `insertRule` all walked through it. Seven
#: spellings walking through a check written to close a hole. The shapes are
#: unbounded; the words are five.
INLINE_STYLE_PRIMITIVES = ("style", "cssText", "insertRule", "deleteRule",
                           "adoptedStyleSheets")

#: The one permitted use, and it is a syntactic class rather than a named file
#: or a named property: `setProperty` of a CUSTOM property. `--camelot-hue`,
#: `--progress` and `--score` are per-element VALUES that the stylesheet then
#: consumes - `.progress__fill { width: var(--progress, 0%); }` - so the
#: DECLARATION still lives in app.css, which is what the checks above read.
_STYLE_MENTION = re.compile(r"\b(" + "|".join(INLINE_STYLE_PRIMITIVES) + r")\b")
_CUSTOM_PROPERTY_WRITE = re.compile(
    r"\.style\.setProperty\(\s*(['\"])--[\w-]+\1\s*,"
)


def test_no_script_puts_css_on_the_page_outside_the_stylesheet():
    """The boundary of the two sticky checks, closed rather than assumed.

    `test_the_set_creator_status_line_...` and
    `test_the_export_progress_block_...` read app.css and conclude those two
    blocks are stuck to the bottom of the scrollport. That conclusion holds
    only while the STYLESHEET is where their geometry is written. One line -

        progress.style.position = 'static';

    - outranks any ordinary rule in the sheet, and no amount of care about the
    CSS would notice: an inline style is not CSS source text and the sticky
    guards read CSS source text.

    WHAT THIS SEARCHES FOR, IN WHAT LITERAL FORM. For each file `scripts()`
    returns, it takes `js(script)`, splits it on newlines, and appends a line
    to `offences` when `_STYLE_MENTION` - the five names of
    `INLINE_STYLE_PRIMITIVES` in a word-boundary alternation - finds a match
    on it; a match is skipped when its word is `style` and
    `_CUSTOM_PROPERTY_WRITE` - a dotted `style.setProperty(` whose first
    argument is a quoted name beginning with two hyphens - also matches
    somewhere on THE SAME LINE. Both patterns are written out in full
    immediately above. FLAT, and searching for words rather than for a list of
    write shapes, because the shapes are unbounded and the first version of
    this check missed seven spellings that are written out above
    `INLINE_STYLE_PRIMITIVES`.

    WHAT THAT IS NOT is "no script reaches the cascade", which is what this
    docstring used to say. `progress['st' + 'yle']['position'] = 'static';`
    reaches it and mentions nothing - see evasion 5 in the boundary note above
    `stylesheets()`. Nor is it "no script mentions the five words outside a
    custom-property write": the exemption is decided per LINE, so the plain
    write in

        progress.style.position = 'static'; progress.style.setProperty('--progress', '0%');

    is skipped along with the permitted one, measured. The word list is a
    floor under the shapes, not a proof about the language.

    What it costs, stated: `clipboard.js` styled its off-screen scratch
    textarea inline and now uses a `.clipboard-scratch` class; `format.js`
    wrote `fill.style.width` and now sets `--score`, which app.css consumes
    exactly as it already consumed `--progress`. Both are the same rendering.
    A component that genuinely needs to compute a length now writes a custom
    property, which is one line and leaves the declaration in the sheet.
    """
    offences = []
    for script in scripts():
        body = js(script)
        for line_number, line in enumerate(body.splitlines(), start=1):
            for match in _STYLE_MENTION.finditer(line):
                if match.group(1) == "style" and _CUSTOM_PROPERTY_WRITE.search(line):
                    continue
                offences.append(f"{script.name}:{line_number}: {' '.join(line.split())}")
                break

    assert offences == [], (
        "`_STYLE_MENTION` matched a name from INLINE_STYLE_PRIMITIVES on these "
        "lines of stripped script source. A match is skipped only when the word "
        "it matched is `style` AND `_CUSTOM_PROPERTY_WRITE` matches that same "
        "line, which did not happen here:\n  "
        + "\n  ".join(offences)
        + "\nPut the declaration in app.css, or write a custom property with "
          "`style.setProperty('--name', ...)`, which `_CUSTOM_PROPERTY_WRITE` "
          "exempts."
    )


#: Eleven spellings of the same act. The first is the only one the
#: shape-matching version of this check caught.
INLINE_STYLE_ROUTES = [
    ("the obvious one", "el.style.position = 'static';"),
    ("bracket access", "el.style['position'] = 'static';"),
    ("bracket access, computed", "el.style['posi' + 'tion'] = 'static';"),
    ("Object.assign onto style", "Object.assign(el.style, { position: 'static' });"),
    ("an alias of style", "const s = el.style;"),
    ("setProperty with a built name", "el.style.setProperty('bot' + 'tom', 'auto');"),
    ("a style attribute", "el.setAttribute('style', 'position: static');"),
    ("cssText", "el.cssText = 'position: static';"),
    ("an injected style element", "document.createElement('style');"),
    ("adoptedStyleSheets", "document.adoptedStyleSheets = [sheet];"),
    ("insertRule", "sheet.insertRule('.exportv__progress{position:static}');"),
]


@pytest.mark.parametrize(
    "what,line", INLINE_STYLE_ROUTES, ids=[name for name, _ in INLINE_STYLE_ROUTES]
)
def test_every_route_in_this_list_is_reported(what, line):
    """A rule nobody has seen fail is a rule nobody has seen work, and this
    one has been wrong once already.

    RENAMED FROM `test_every_route_to_the_cascade_is_reported`, which claimed
    an exhaustiveness this has never had. It reads a hand-written list of
    eleven lines and checks each is matched; a route absent from the list is
    not a route it says anything about, and

        progress['st' + 'yle']['position'] = 'static';

    is one - it reaches `.style` without spelling `style`, it went into the
    real Export component, and all 272 tests here stayed green. That is
    evasion 5 in the boundary note above `stylesheets()`.

    The list is still worth having, and the shape of the honest claim is: the
    eleven spellings below are reported and the first was the only one the
    shape-matching version caught. It is a floor under `_STYLE_MENTION`, not a
    census of the language.
    """
    assert _STYLE_MENTION.search(line), f"{what} is not reported"
    assert not (
        _STYLE_MENTION.search(line).group(1) == "style"
        and _CUSTOM_PROPERTY_WRITE.search(line)
    ), f"{what} was treated as a custom-property write"


#: ...and the writes that are fine, or the check above is one a maintainer
#: deletes rather than obeys. All three are live in the shipped scripts.
CUSTOM_PROPERTY_WRITES = [
    "element.style.setProperty('--camelot-hue', `${parsed.hue}deg`);",
    "progressFill.style.setProperty('--progress', `${percent.toFixed(1)}%`);",
    "fill.style.setProperty('--score', `${(clamped * 100).toFixed(1)}%`);",
]


@pytest.mark.parametrize("line", CUSTOM_PROPERTY_WRITES)
def test_setting_a_custom_property_is_left_alone(line):
    assert _CUSTOM_PROPERTY_WRITE.search(line), line


def test_the_stylesheet_declares_what_those_custom_properties_feed():
    """The other half of permitting them: a custom property is only "the
    declaration still lives in app.css" if app.css actually consumes it."""
    sheet = css(APP_CSS)
    for name in ("--progress", "--score"):
        assert re.search(rf"var\(\s*{re.escape(name)}\b", sheet), (
            f"{name} is set by a script and read by no rule in app.css"
        )


def test_the_export_progress_block_cannot_be_scrolled_out_of_reach():
    """The same claim as the Set Creator status line, for the control that
    needs it most.

    §2.6's progress block holds the only Stop button in the application, and
    the window opens at 1280x840 (``web/host.py:34-36``). The three numbered
    sections and the action button fill that on their own, so in the normal
    flow the block appeared BELOW the fold at the moment an export started -
    measured in headless Chrome at 1280x980, a taller window than the app
    opens with, where the block began at y=985 against a viewport ending at
    980. A progress bar nobody can see is not a progress bar, and a Stop
    button nobody can reach is worse.

    A SOURCE-TEXT check - it cannot lay anything out - and the behavioural half
    was done by hand against a real browser and recorded in the PR description.

    THE OFFSET IS CHECKED BY VALUE, not by presence. This test used to ask only
    whether a `bottom:` declaration existed, and `bottom: auto` satisfies that
    while meaning the exact opposite: Chrome computes `auto`, the block leaves
    the sticky constraint behind, and the Stop button renders offscreen - which
    is the defect the rule was written to fix. A guard a wrong value satisfies
    is worse than no guard, because it reads as coverage.
    """
    body = css(APP_CSS)
    declarations, unevaluated = _rule(body, ".exportv__progress", STICKY_PROPERTIES, where=APP_CSS.name)

    assert declarations, "the Export progress rule is gone"
    assert unevaluated == [], (
        f"another rule naming .exportv__progress redeclares what this checks: {unevaluated}"
    )

    assert_sticks_to_the_bottom("the progress block", declarations)
    # Opaque, or the rows scrolling under it read through it.
    assert _declares("background", r"^var\(\s*--surface", declarations), (
        f"the progress block is transparent: {declarations}"
    )


# Offsets a browser really does resolve to a length, and offsets it drops. The
# two lists are the guard's actual claim, written out: the tests above only ever
# run it against the ONE value app.css currently ships, so every rule in the
# type algebra that the shipped value does not exercise would otherwise be
# unpinned. Gutting the length-times-length rule, for instance, left the whole
# file green until this table existed.
#
# HOW THIS LIST WAS ASSEMBLED, since calling it complete is what went wrong
# twice: it was built a rule at a time, and twice a rule was found missing
# AFTER the list had been called complete - the length-times-length one, then
# the closing-token one, which accepted `bottom: calc(1px,`. Guessing at what
# is uncovered does not converge, so guessing was replaced by a procedure: each
# raise, branch and assert in `_tokenise`, `_Typer`, `_type_of` and
# `assert_sticks_to_the_bottom` was disabled ONE AT A TIME and this file re-run
# against the mutant. That turned up EIGHT survivors past the one that was
# reported: the closing
# token, the `var()` name check, the unclosed-`var(` check, the bareness of a
# substituted value, the recursion limit, the `position: sticky` assert, the
# missing-`bottom` assert, and the `_DECLARATION_BOUNDARY` anchor that stops
# `padding-bottom` being read as `bottom`.
# Each is covered below or in a test underneath, and
# each was re-run to a red. ONE branch survives with no discriminating input at
# all and is documented AS such at its site rather than papered over: the
# `inside_maths` save/restore in `_Typer.unit`.
#
# This used to say two, and named the `STICKY_KEYWORDS` special case as the
# second. That was wrong. The branch is reachable and it is pinned - deleting
# it turns `test_a_css_wide_keyword_is_rejected_as_a_keyword_and_named` red,
# because what it uniquely produces is the DIAGNOSIS and the diagnosis is what
# that test asserts. What is true of it is narrower and is said where it
# belongs: it changes no accept-or-reject verdict, so no row of the table below
# can tell it apart.
OFFSETS_THAT_RESOLVE = [
    "calc(var(--space-6) * -1)",  # what both sticky rules actually ship
    "0",  # unitless zero IS a length in a property value
    "0px",
    "-0.5rem",
    "4%",  # `bottom` takes a length-percentage
    "calc(0px - var(--space-6))",
    "calc(var(--space-6) / 2)",
    "calc((var(--space-6) + 4px) * -1)",
    "calc(-1 * var(--space-6))",  # number on the left of the multiply
    # A `var()` FALLBACK, which is the only reason the tokeniser has a `comma`
    # token at all. Without that token `_tokenise` raises on the comma before
    # `_Typer.variable` ever gets to skip the fallback, so this value - which a
    # browser resolves perfectly well - would be a false red. Deleting the
    # comma token left every other row here green.
    "calc(var(--space-6, 0px) * -1)",
]

OFFSETS_A_BROWSER_DROPS = [
    "auto",  # the initial value: no bottom constraint at all
    "inherit",
    "initial",
    "unset",
    "revert",
    "5",  # a bare non-zero number is not a length
    "calc(5)",  # a calc that types as a NUMBER, which `bottom` will not take
    "calc(0)",  # zero is a plain number once it is inside calc()
    "calc(var(--space-6) + 1)",  # length plus number: no type
    "calc(var(--space-6) * var(--space-6))",  # length times length: no type
    "calc(var(--space-6) / var(--space-6))",  # division by a length
    "calc(1px+1px)",  # `+` needs whitespace on both sides or CSS drops it
    "calc(1px -1px)",  # tokenises as two operands, exactly as CSS reads it
    # The two that the whitespace rule alone rejects. Without them the rule is
    # dead code: the signed-dimension tokens above are already caught by the
    # parser reading them as two operands in a row, so deleting the whitespace
    # check left the suite green until these were listed.
    "calc(1px -var(--space-6))",  # space before the `-` but not after
    "calc(var(--space-6)- 1px)",  # space after the `-` but not before
    "1px + 1px",  # arithmetic outside calc() is not a thing
    "calc(var(--nope) * -1)",  # a custom property tokens.css does not declare
    "var(--nope)",
    "var(--ink-primary)",  # declared, but a colour rather than a length
    "min(var(--space-6), 0px)",  # syntax the checker does not model
    "calc(var(--space-6) * -1",  # unclosed
    # A `calc()` that ends on something that is not `)`. The closing token was
    # read and thrown away without being checked, so this typed as a plain
    # `length` and the guard passed a value a browser cannot parse. `calc(1px
    # 2px)` does NOT catch it - two operands in a row are rejected by the
    # grammar before the closing check is reached - which is why the rule
    # stayed unpinned through two rounds of this table.
    "calc(1px,",
    # `var()` takes a CUSTOM PROPERTY name, so an ordinary identifier is
    # invalid CSS and the browser drops the declaration. Worse than merely
    # unpinned: `_custom_property` matches `name` anywhere in tokens.css, and
    # `text-xs` is a suffix of the real `--text-xs`, so with the name check
    # disabled this resolved to `0.6875rem` and PASSED.
    "var(text-xs)",
    # An unclosed `var(`. Rejected for the same reason as the unclosed `calc(`
    # above - erring loud on syntax this does not model - and unpinned until
    # now because the unclosed `calc(` is caught one frame earlier, by the
    # tokens running out mid-expression.
    "var(--space-6",
    # A bare identifier that is not one of the keywords named above. Without it
    # the catch-all in `_Typer.unit` is dead: every other identifier here is
    # either a listed keyword or followed by a `(`, and both are rejected
    # somewhere else, so replacing the catch-all with `return "length"` left the
    # suite green.
    "fit-content",
    # Text the tokeniser cannot read at all. Same story: making `_tokenise`
    # silently skip what it does not recognise stayed green until this was here.
    '"0px"',
    "",  # no value at all
]


@pytest.mark.parametrize("offset", OFFSETS_THAT_RESOLVE)
def test_the_sticky_guard_accepts_every_offset_that_really_resolves(offset):
    """A guard that rejects working CSS is a guard someone will delete."""
    assert_sticks_to_the_bottom("a rule", f"position: sticky; bottom: {offset};")


@pytest.mark.parametrize("offset", OFFSETS_A_BROWSER_DROPS)
def test_the_sticky_guard_rejects_every_offset_a_browser_would_drop(offset):
    """Each of these leaves the element at `bottom: auto` in a real browser.

    The failure has to NAME the offset it rejected. `pytest.raises` on its own
    would be satisfied by the helper raising for any reason at all - including
    a typo in the helper itself - which is the same shape of hole as a guard
    that matches a pattern instead of establishing a property.
    """
    with pytest.raises(AssertionError) as raised:
        assert_sticks_to_the_bottom("a rule", f"position: sticky; bottom: {offset};")
    assert offset in str(raised.value) or "no bottom offset" in str(raised.value)


# `_type_of` reads its custom properties out of the real tokens.css, so two of
# its rules cannot be reached from the offset table above however it is written:
# they need a custom property whose VALUE has a particular shape, and tokens.css
# happens to contain no such token. Feeding the function a synthetic sheet is
# not a weaker test - it is the same function at the same interface, with the
# one input the table cannot vary.
SUBSTITUTED_VALUES = [
    # A custom property is a token stream substituted where it is USED, so its
    # bareness is the bareness of the `var()` referencing it. Inside `calc()` a
    # unitless zero is a plain NUMBER, so this whole expression is a number and
    # a browser drops `bottom`. Substituting it as though it were bare types
    # the zero as a length and the expression comes out a length, which is the
    # guard passing a declaration that does not apply.
    ("calc(var(--zero) * -1)", ":root { --zero: 0; }", "number"),
    # The same rule from the other side. CSS has no arithmetic outside
    # `calc()`, so `1px + 1px` is invalid as a bare property value and valid
    # once substituted inside one. Typing this one as bare rejects a value a
    # browser resolves - the false-red direction of the same bug.
    ("calc(var(--sum))", ":root { --sum: 1px + 1px; }", "length"),
    # Eight levels of indirection resolve; the ninth is where the limit sits.
    ("var(--d0)", ":root {" + "".join(f"--d{i}: var(--d{i + 1});" for i in range(7)) + "--d7: 1px; }", "length"),
]


@pytest.mark.parametrize("value,sheet,expected", SUBSTITUTED_VALUES)
def test_a_substituted_custom_property_is_typed_where_it_is_used(value, sheet, expected):
    assert _type_of(value, sheet) == expected


def test_a_cycle_between_custom_properties_is_rejected_rather_than_crashing():
    """`--a: var(--b); --b: var(--a)` is a sheet someone can really write.

    Without the depth limit this is unbounded recursion, and what a maintainer
    sees is a RecursionError out of a conventions test with no indication that
    their stylesheet is what caused it. The limit is not reachable through the
    real tokens.css - nothing in it nests anywhere near eight deep - so nothing
    in the offset table can pin it, and removing it left this file green.
    """
    with pytest.raises(_NotALength) as raised:
        _type_of("var(--a)", ":root { --a: var(--b); --b: var(--a); }")
    assert "eight deep" in str(raised.value)


def test_a_css_wide_keyword_is_rejected_as_a_keyword_and_named():
    """`auto` and its siblings are the mistake this guard exists to catch.

    The keyword branch is INERT for accept-or-reject purposes - the catch-all
    in `_Typer.unit` rejects a bare identifier anyway, which is why deleting
    `STICKY_KEYWORDS` entirely leaves the offset table green. What it uniquely
    produces is the DIAGNOSIS, and the diagnosis is the whole value of the
    branch: `auto` is not a typo, it is the initial value, and a maintainer who
    is told "is the keyword `auto`, which is not a length at all" knows they
    have written a no-op, where "has `auto` where a number or a length belongs"
    reads like a parser complaint. So the message is what gets pinned; there is
    nothing else about the branch to pin.
    """
    for keyword in sorted(STICKY_KEYWORDS):
        with pytest.raises(AssertionError) as raised:
            assert_sticks_to_the_bottom("a rule", f"position: sticky; bottom: {keyword};")
        assert f"is the keyword `{keyword}`, which is not a length at all" in str(raised.value), (
            f"`{keyword}` was rejected, but not as the CSS-wide keyword it is"
        )


def test_the_sticky_guard_checks_the_position_too_and_not_only_the_offset():
    """An offset on a statically positioned block does nothing at all.

    Every row of the offset table ships `position: sticky` in the declarations
    it builds, so none of them can tell whether the guard looks at it - and
    deleting that assert left this file green.
    """
    with pytest.raises(AssertionError) as raised:
        assert_sticks_to_the_bottom("a rule", "bottom: calc(var(--space-6) * -1);")
    assert "back in the normal flow" in str(raised.value)


def test_a_rule_with_no_bottom_offset_is_not_read_off_a_neighbouring_property():
    """`padding-bottom` is not `bottom`, and a sticky block with only a padding
    is not stuck to anything.

    Two separate holes met here. The `_DECLARATION_BOUNDARY` anchor is what
    stops the search matching the tail of `padding-bottom`, and without it this
    declaration
    resolved to a length and PASSED. And the missing-offset assert underneath
    it was unreachable from the table: the empty-string row does not reach it,
    because the whitespace in the pattern backtracks and the capture matches
    the single space before the `;`,
    so it is `_type_of` that rejects that row rather than this assert.
    """
    with pytest.raises(AssertionError) as raised:
        assert_sticks_to_the_bottom("a rule", "position: sticky; padding-bottom: 1px;")
    assert "no bottom offset" in str(raised.value)


def test_the_modal_layer_the_dialogs_mount_into_exists():
    """`modal.js` looks this up by id; a rename would leave every dialog
    building nodes into nothing and failing silently at the moment a user
    presses `+ Add Anchor`."""
    body = html(INDEX_HTML)

    assert 'id="modal-layer"' in body
    assert 'getElementById(LAYER_ID)' in js(JS / "modal.js")
    assert "const LAYER_ID = 'modal-layer';" in js(JS / "modal.js")


def test_the_drawer_renders_playlists_from_the_field_it_is_given():
    """REPLACES test_the_drawer_does_not_invent_playlist_data (PR 3a).

    That test pinned the placeholder - "Playlist membership arrives in the next
    update." - which was the honest thing to assert while `track.playlists`
    came back null and there was nothing to render. This PR is the next update:
    the field is populated, so the placeholder is gone and a test asserting its
    presence would be asserting that the feature was not built.

    What replaces it keeps the two properties the original was protecting -
    the drawer invents nothing, and it does not reach for an endpoint that does
    not exist - and adds the ones that matter now.

    THIS IS A SOURCE-TEXT CHECK, AND ONLY A SOURCE-TEXT CHECK
    ---------------------------------------------------------
    Everything below greps drawer.js. That is worth having - it is where the
    convention tests live and it reads as documentation of the decision - but
    it does not establish what the drawer DOES. A drawer that builds the path
    at runtime (``'/api/pl' + 'aylists'``) passes every assertion here.

    The behavioural half is
    ``tests/web/js/drawer_playlists.test.mjs`` -> "no playlist state makes the
    drawer call any endpoint but track detail", which mounts the real module
    and reads back every request it makes across all five playlist states. That
    mutant turns those red and leaves this one green, which is the whole reason
    both exist.
    """
    body = js(JS / "components" / "drawer.js")

    # Still no endpoint, as a matter of source text: the field rides on the
    # track detail the drawer already fetches, so no route was added. That it
    # is not CALLED is pinned in the JS suite named above, not here.
    assert "/api/playlists" not in body
    assert "Playlist membership arrives in the next update." not in body

    # The three-way contract. `null` is not `[]`.
    assert "track.playlists" in body
    assert "Array.isArray(playlists)" in body

    # The full path, not the leaf name: 36 leaf names are duplicated.
    assert "folder_path" in body

    # Nothing is invented client-side: the only strings the drawer supplies are
    # its own copy and the command to run.
    assert "import-playlists" in body


#: `/* ... */` and `// ...`, so a rule about what the CODE does is not tripped
#: by a comment saying the code does not do it - which is exactly what
#: drawer.js's header says about innerHTML.
HTML_SINK = re.compile(r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b")


def test_the_comment_stripper_still_strips_something():
    """Guard the guard: a stripper that removed everything, or nothing, would
    make the check below vacuous in one direction or noisy in the other."""
    stripped = js(JS / "components" / "drawer.js")

    assert "innerHTML" not in stripped, "the drawer's own header is not being stripped"
    assert "export function mountDrawer" in stripped, "the stripper ate the code"
    assert "playlist__segment" in stripped, "the stripper ate the code"


def test_no_component_ever_writes_html_as_a_string():
    """Playlist names are user data from an external file, and they are exactly
    the strings that would carry an injection, so the components build nodes
    and set textContent instead.

    WHAT THIS SEARCHES FOR: `HTML_SINK.findall(js(script))` for each file
    `scripts()` returns - four literal names in a word-boundary alternation,
    `innerHTML`, `outerHTML`, `insertAdjacentHTML` and `document.write`, in
    stripped source. A LIST, not a class of behaviour, and the same limit as
    evasion 5 applies to it: `node['inner' + 'HTML'] = name` spells none of
    the four. A sink that is not on the list is not looked for at all, and
    three that are not on it are `DOMParser.parseFromString`,
    `Element.setHTML` and the fragment builder on `Range`. Adding one to the
    list is the change; reading a green run as "no component writes HTML as a
    string" is not supported.

    Run over every file `scripts()` returns rather than only the drawer,
    because the property being aimed at is "this frontend does not do that",
    not "this file does not". Comments are stripped first, so the drawer is
    allowed to SAY it does not write innerHTML in the same file that must not
    write it.
    """
    offenders = {}
    for script in scripts():
        found = HTML_SINK.findall(js(script))
        if found:
            offenders[str(script.relative_to(JS))] = sorted(set(found))

    assert offenders == {}, f"HTML written as a string: {offenders}"


def test_the_html_sink_check_would_catch_a_real_assignment():
    """A rule nobody has seen fail is a rule nobody has seen work."""
    assert HTML_SINK.search("node.innerHTML = name;")
    assert HTML_SINK.search("node.insertAdjacentHTML('beforeend', name);")
    assert not HTML_SINK.search("node.textContent = name;")


def test_every_interactive_control_is_a_real_element():
    """A clickable div is not keyboard reachable and announces nothing."""
    body = html(INDEX_HTML)

    assert not re.search(r"<div[^>]*\bonclick", body)
    for match in re.finditer(r"<button[^>]*>", body):
        assert re.search(r'type="(?:button|submit)"', match.group(0)), match.group(0)


def test_every_script_file_is_reachable_from_the_entry_module():
    """A no-build frontend has no bundler to tell you a file is orphaned."""
    reachable = set()
    queue = [JS / "main.js"]

    while queue:
        current = queue.pop()
        if current in reachable or not current.is_file():
            continue
        reachable.add(current)
        # Stripped: a commented-out `import` makes an orphaned module look
        # reachable, which is the one thing this test exists to notice.
        for target in re.findall(r"from\s+'([^']+)'", js(current)):
            queue.append((current.parent / target).resolve())

    orphans = sorted(str(path.relative_to(JS)) for path in set(scripts()) - reachable)
    assert orphans == [], f"scripts nothing imports: {orphans}"


def test_every_mount_function_the_entry_module_imports_is_also_called():
    """An import with no call mounts nothing, and nothing else notices.

    ``test_every_script_file_is_reachable_from_the_entry_module`` catches a
    module nothing imports. It cannot catch the other half: a destination whose
    module is imported and whose ``mount*`` is never invoked is reachable,
    orphan-free, and completely absent from the running page. Losing the call
    is a one-line deletion in a file every destination branch edits.

    COMMENTS COME OFF FIRST. Searching the raw source made this pass for a
    ``// mountExport({ store });`` - the commented-out call matched the very
    pattern meant to prove the live one was there. Found by mutation, and it
    is the same hole ``test_no_component_ever_writes_html_as_a_string`` strips
    comments to avoid.
    """
    body = js(JS / "main.js")

    imported = set()
    for names in re.findall(r"import\s*\{([^}]*)\}\s*from", body):
        imported.update(
            name.strip() for name in names.split(",") if name.strip().startswith("mount")
        )

    assert imported, "main.js imports no mount function; the regex stopped matching"

    uncalled = sorted(name for name in imported if not re.search(rf"\b{name}\s*\(", body))
    assert uncalled == [], f"imported but never called: {uncalled}"


def test_the_message_box_keeps_the_newlines_its_bodies_are_written_with():
    """§2.6's two longest strings are catalogued WITH their line breaks.

    `Confirm Export` (:603-611) is four lines and `Export Complete` (:620-634)
    is seven lines of accounting - "Playlists created", "Successful", "Total
    recommendations", "Failed", then the location and the Rekordbox
    instructions. (The shipped per-seed body is six of those seven: it drops
    the "Playlists created" line, which claims a file count nothing on the wire
    can supply - see `completionMessage` and the test below. Combined mode
    keeps it, and either way the line breaks are the point here.) Under CSS's
    default `white-space: normal` every one of those newlines is collapsed to a
    space and the dialog renders one run-on paragraph, which is not the message
    that was catalogued.

    A source-text check, and it is honest about being one: it cannot lay
    anything out. The rendered result was checked by hand and recorded in the
    PR description.
    """
    body = css(APP_CSS)
    declarations, unevaluated = _rule(body, ".message-box__message", ("white-space",), where=APP_CSS.name)

    assert declarations, "the message-box body rule is gone"
    assert unevaluated == [], (
        f"another rule naming .message-box__message redeclares white-space: {unevaluated}"
    )
    assert _declares("white-space", r"^pre-line\b", declarations), (
        f"the message box collapses its newlines: {declarations}"
    )


def test_no_screen_renders_the_services_playlist_counter():
    r"""`playlists_created` is not a count of files, and the web UI must not read it.

    `playlist_exporter.py:171-173` increments it beside `successful` inside one
    `try`, so in per-seed mode the two are the same number; what it counts is
    write calls that did not raise. `playlist_filename(artist, title)` decides
    where each write lands and its own docstring says two seeds that sanitise
    to the same name "overwrite each other silently", so N writes leave N files
    only if the N names are distinct. On the real collection they are not - the
    service reports 1532 and the directory holds 1529 - and a dialog that
    prints the counter states a number the filesystem contradicts.

    The behavioural tests probe the two dialogs with a counter no real run
    could produce and assert it never reaches the user. This is the structural
    half of the same claim, and it catches a case they cannot: a new reader of
    the field in a component nobody thought to write an assertion against.
    What it actually does is `"playlists_created" in js(script)` for each file
    `scripts()` returns - a SUBSTRING presence check on stripped source, so a
    reader that never spells the field, `stats["playlists_" + "created"]`,
    is not found. Comments are stripped first - the reasoning above
    is written out in `export.js`, and prose about a field must not be what
    satisfies a check that the field is unused. Once, by `js()`: this stripped
    `^\s*//` a second time on its own, which was inert (deleting it left this
    file green) and was a second place the rule lived, which is the shape of
    the bug the single reader replaced.

    The field stays on the wire, and should: `web/api.py` sends what the
    service returned, faithfully, and a client that wants it is not this one.
    """
    scanned = scripts()
    # Guard the guard. This asserts a property of a SET, and an empty set has
    # every property: a glob that stopped matching would make it pass while
    # checking nothing. So the unit the claim is actually about has to be in
    # the set before the absence means anything.
    assert scanned, "scripts() found no modules; the glob stopped matching"
    assert any(script.name == "export.js" for script in scanned), (
        f"the Export screen is not among the scanned modules: {[s.name for s in scanned]}"
    )

    offenders = {}
    for script in scanned:
        body = js(script)
        if "playlists_created" in body:
            offenders[script.name] = [
                line.strip() for line in body.splitlines() if "playlists_created" in line
            ]

    assert offenders == {}, (
        f"the service's playlist counter is being rendered again: {offenders}"
    )


def test_the_entry_module_is_loaded_as_a_module():
    """`type="module"` is what makes the import graph above work at all."""
    assert '<script type="module" src="/js/main.js"></script>' in html(INDEX_HTML)


def test_the_camelot_colours_are_declared_on_the_pill_not_on_the_root():
    """The bug this pins was invisible in every static check and looked fine.

    Custom-property substitution happens where a property is DECLARED, not
    where it is used. `--camelot-bg: hsl(var(--camelot-hue, 220deg) …)`
    declared inside `:root` is substituted against :root's `--camelot-hue` -
    which is never set, so the fallback wins - and the already-resolved colour
    inherits down to every pill. The per-element hue format.js sets is simply
    ignored. Every pill in the list rendered at the same 222°, while the A/B
    lightness difference still worked and made the result look intentional. It
    was caught by sampling pixels out of a screenshot, not by any assertion.
    """
    body = css(TOKENS_CSS)
    camelot = ("--camelot-bg", "--camelot-fg", "--camelot-edge")

    # WHERE each one is declared, taken from the rules rather than from a slice
    # of the file. The slice was `body[body.index(":root {") : body.index("\n}")]`,
    # which ends at the first line-start `}` in the file and cannot see a
    # second `:root` at all - and `f"{name}:" in root_block` is the unanchored
    # match this file has now been wrong about three times: `--x--camelot-bg:`
    # satisfies it.
    sites = {}
    for selector, declarations, _depth in _rules(body):
        for name in _custom_properties(declarations):
            if name in camelot:
                sites.setdefault(name, []).append(" ".join(selector.split()))

    missing = [name for name in camelot if name not in sites]
    assert missing == [], f"{missing} are not declared anywhere in tokens.css"

    leaked = {
        name: where
        for name, where in sites.items()
        if any(".pill" not in selector for selector in where)
    }
    assert leaked == {}, (
        f"{sorted(leaked)} are declared outside .pill ({leaked}), so "
        "var(--camelot-hue) resolves where they are DECLARED - against a rule "
        "that never carries a hue - and every pill gets the fallback"
    )
