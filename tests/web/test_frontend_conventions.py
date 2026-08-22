"""The frontend's design constraints, mechanised.

There is no automated test of the rendered UI in this PR - introducing a
browser-automation dependency to test a handful of hand-written files is not
worth the packaging risk, and the visual pass is done by hand in Safari. But
several of the constraints are not visual at all: "tokens first", "no
hard-coded hex", "respect prefers-reduced-motion", "real focus rings", "4.5:1
contrast" are each easy to claim, easy to skip, and completely checkable from
the source.

So they are checked here. What this file cannot tell you is whether the result
looks good; what it can tell you is that the system underneath it is real.
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


def without_js_comments(text):
    return JS_COMMENT.sub("", text)


def without_html_comments(text):
    return HTML_COMMENT.sub("", text)


HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
COLOUR_FUNCTION = re.compile(r"\b(?:rgba?|hsla?|lab|lch|oklch|color)\s*\(")


def read(path):
    return path.read_text(encoding="utf-8")


def without_comments(text):
    return COMMENT.sub("", text)


class _CannotModel(AssertionError):
    """The source uses syntax whose meaning this file cannot compute.

    Raised, never swallowed, and never narrowed into a special case. Four
    rounds on this file have now established the same thing four times: a
    guard that MIS-READS a construct is worse than one that refuses it,
    because the mis-read is silent and the refusal is not. A maintainer who
    writes CSS this file turns down gets an obvious failure naming the file,
    the construct and the line, and either rewrites one declaration or teaches
    the reader the construct. A maintainer whose CSS is mis-read gets a dead
    accessibility feature and a green suite - which is what happened with
    `!important` and with a semicolon inside a string, and what this class
    exists to stop happening a third time.

    It subclasses AssertionError so pytest reports it as a failing check
    rather than an error in the tests, which is what it is: the stylesheet
    does not meet a constraint this file imposes.
    """


#: A quote opens a CSS string, and a string can contain ANYTHING - `;`, `}`,
#: `{`, a whole fake ruleset.
_QUOTE = re.compile(r"""["']""")


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
    open. Refusing is complete in one line: if the region contains a quote at
    all, this file does not know where its declarations begin, and says so.

    What it costs, said plainly: `content: "→"` and `font-family: "Inter"` are
    legitimate CSS that these stylesheets may no longer contain. That is the
    trade, taken deliberately - see the note in tokens.css, where the font
    stacks are written as identifier sequences for exactly this reason.
    """
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

    Every CSS read in this file goes through this, and
    `test_no_source_file_is_read_without_its_comments_being_stripped` fails if
    a new one does not. That is not tidiness. A commented-out declaration is
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
    here rather than handed on to be split wrongly - see `_splittable`. This
    is the reader, so no real stylesheet reaches a consumer without passing
    it; the splitters check again for the synthetic sheets the tests build by
    hand, which never come through here.
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
#: patched. The BOUNDARY is finite. So the boundary is what is checked, once,
#: here, and every consumer goes through it.
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

    THE LAST DECLARATION WINS, which is the cascade - `re.search` returns the
    first, so a rule that declared `bottom` twice, or two rules merged by
    `_rule`, was read off the declaration the browser discards.

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

    Its one caller is the reduced-motion block, where the flag is the point:
    `animation-duration: 1ms` without it loses to any component that declares
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
    answer for `--text-xs`. Later declarations win, which is the cascade.

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
    # Anchored, like every other name lookup in this file: `background-position`
    # CONTAINS `position`, and a rule declaring `background-position: sticky`
    # is not positioned at all.
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


#: Any declaration in a list, as (property, value). Only used to NAME what is
#: wrong in a refusal - the lookups themselves stay anchored per name.
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

    So a rule counts when `selector` is one whole entry in its selector LIST,
    and EVERY such rule is merged in document order.

    `properties` is what the caller is about to assert on. Any OTHER rule that
    names this selector and declares one of them is handed back rather than
    ignored: whether it applies needs a selector engine and a document, which
    this does not have, and passing over what it cannot evaluate is the defect
    rather than the fix. Rules that name the selector and declare none of them
    - `.exportv__progress[hidden] { display: none; }` - change no answer here
    and are not reported.
    """
    applies, unevaluated = [], []
    for selector_text, declarations in _rules(body):
        entries = [entry.strip() for entry in selector_text.split(",")]
        names = selector in entries or any(_mentions(selector, entry) for entry in entries)
        if names:
            flagged = _important_properties(declarations)
            if flagged:
                raise _CannotModel(
                    f"{where}: `{' '.join(selector_text.split())}` declares "
                    f"{', '.join(flagged)} `!important`. Every rule here is merged "
                    f"in document order and read last-wins, and an `!important` "
                    f"declaration beats a later ordinary one - an EARLIER "
                    f"`{selector} {{ position: static !important; }}` leaves the "
                    f"block in normal flow with this file reporting it stuck. "
                    f"Modelling that means the cascade; this file has no selector "
                    f"engine and no document, so it refuses instead."
                )
        if selector in entries:
            applies.append(" ".join(declarations.split()))
        elif names:
            clashing = sorted(
                name for name in properties if _declaration(name, declarations) is not None
            )
            if clashing:
                unevaluated.append((" ".join(selector_text.split()), clashing))
    return "; ".join(applies), unevaluated


#: What `assert_sticks_to_the_bottom` and its callers read off a rule, so that
#: another rule redeclaring one of them cannot go unnoticed.
STICKY_PROPERTIES = ("position", "bottom", "background")


# WHAT IS STILL MATCHED LOOSELY IN THIS FILE, and why. Every CSS name and every
# CSS selector now goes through `_declaration`, `_custom_properties` or `_rule`,
# and every read of a source file through `css()`, `js()`, `html()` or
# `source()`. What is left is written down here rather than discovered in
# round six:
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
#     the behavioural test that establishes what the module DOES.
#   * `body.split('data-destination="export"')[1].split("</button>")[0]` takes
#     a region between two substrings rather than parsing the markup.


def stylesheets():
    return sorted(CSS.glob("*.css"))


def scripts():
    return sorted(JS.rglob("*.js"))


# ---------------------------------------------------------------------------
# Tokens first
# ---------------------------------------------------------------------------


THIS_FILE = Path(__file__).resolve()

#: The four readers that make a source file look the way a browser sees it,
#: plus `read`, which is the only thing in this file that touches the
#: filesystem. Inside their definitions a raw read is what they ARE; anywhere
#: else it is the defect below.
#:
#: This is a closed set of five functions at the top of one file, not an open
#: set of spellings. A sixth reader added without registering it here does not
#: slip through - the `read` in its body is reported, loudly, as an
#: unclassified raw read.
READER_DEFINITIONS = ("read", "source", "css", "js", "html")

#: Names that get bytes off disk. `read` is this file's own; `open` is the
#: builtin.
RAW_READ_NAMES = ("read", "open")

#: ...and the same thing reached as an attribute, which is how `pathlib`,
#: `io`, `codecs` and `builtins` all spell it.
RAW_READ_ATTRIBUTES = ("read_text", "read_bytes", "read", "open")

#: Calls that hand back stripped source. A call to one of these is fine
#: wherever it appears and whatever path it is given.
STRIPPING_READERS = ("source", "css", "js", "html")


def _reads(tree):
    """Every read of a source file in `tree`, as (stripped, raw).

    STRUCTURAL, and deliberately the other way round from the scan it
    replaces. That one recognised five variable NAMES - `TOKENS_CSS`,
    `APP_CSS`, `sheet`, `script`, `current` - and passed everything else in
    silence, so `read(JS / "format.js")`, `read(JS / "modal.js")`,
    `read(JS / "components" / "drawer.js")` and `read(INDEX_HTML)` were all
    invisible to it. The space of ways to spell a path is unbounded, so a list
    of spellings always loses; PR #24 spent six rounds proving that.

    So the path is not classified at all. The READER is. Every way of getting
    bytes off disk is a violation unless it is `read(THIS_FILE)` - this file's
    own source, which is what is being parsed here - or sits inside one of the
    five reader definitions. A composed path, a path bound to a new name, an
    alias of `read`, a bare `Path.read_text()`, an `open()` and a new
    raw-reading helper are all reported for the same reason and without the
    scan needing to understand any of them.

    Nothing is skipped for being unrecognised. A reference to `read` that is
    not a direct call - an alias, a dict entry, an argument passed to
    something else - is reported as such, because the scan cannot follow it
    and a scan that silently passes what it cannot follow is the bug, not the
    fix.
    """
    stripped, raw = [], []

    def report(node, what):
        raw.append(f"line {node.lineno}: {what}")

    def visit(node, in_reader):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            in_reader = in_reader or node.name in READER_DEFINITIONS

        if isinstance(node, ast.Call):
            call = node.func
            if isinstance(call, ast.Name) and call.id in STRIPPING_READERS:
                if not in_reader:
                    stripped.append(f"line {node.lineno}: {ast.unparse(node)}")
            elif isinstance(call, ast.Name) and call.id == "read":
                if not in_reader and not _reads_this_file(node):
                    report(node, f"{ast.unparse(node)} - raw, use a stripping reader")
                for child in node.args + node.keywords:
                    visit(child, in_reader)
                return
            elif isinstance(call, ast.Attribute) and call.attr in RAW_READ_ATTRIBUTES:
                if not in_reader:
                    report(node, f"{ast.unparse(node)} - raw, use a stripping reader")

        if isinstance(node, ast.Name) and node.id in RAW_READ_NAMES and not in_reader:
            report(node, f"`{node.id}` is referenced outside a direct call, so this "
                         f"scan cannot say what it reads")

        for child in ast.iter_child_nodes(node):
            visit(child, in_reader)

    visit(tree, False)
    return stripped, raw


def _reads_this_file(call):
    """`read(THIS_FILE)` exactly, and nothing that merely resembles it."""
    return (
        len(call.args) == 1
        and not call.keywords
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "THIS_FILE"
    )


def test_no_source_file_is_read_without_its_comments_being_stripped():
    """The single rule the readers exist to enforce, checked on THIS file's AST.

    Not a style point. Six separate regexes in here read tokens.css and app.css
    raw, and every one of them was wrong about the browser:

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

    Two of those were reported and four were found by looking for the rest,
    which is the reason this test exists at all rather than a sixth correction:
    correcting the sites one at a time is what left four of them standing.

    AND THE SCAN ITSELF WAS THE SEVENTH. It recognised five variable names, so
    it never saw `read(JS / "format.js")` two hundred lines below it -
    commenting out `hue: (position - 1) * 30,` and substituting `hue: 0,` left
    every Camelot pill at hue zero with 129 Python and 168 JS tests green.
    Enumerating the spellings of a path is the same losing game as enumerating
    the decoys a substring lookup accepts, so it is not played: `_reads` walks
    the AST and reports every reader that is not a stripping one, whatever it
    is handed.
    """
    stripped, raw = _reads(ast.parse(read(THIS_FILE)))

    assert raw == [], "source read without stripping comments:\n  " + "\n  ".join(raw)
    # ...and not vacuously. If every call site went away, or the scan stopped
    # recognising them, `raw == []` would pass with nothing being checked. This
    # is the floor, and unlike the `count("css(") >= 6` it replaces it is a
    # property of the scan rather than a tally of a substring.
    assert stripped, (
        "the AST scan found no stripping reader called anywhere in this file; "
        "it has stopped seeing reads rather than found none to report"
    )


#: Every way of reading a source file that the scan this replaces could not
#: see. `read(JS / "format.js")` is not hypothetical - it was live in this file
#: when round 5 opened, and it is what let the Camelot hue be commented out
#: with 129 Python and 168 JS tests green. The rest are the same read spelled
#: differently, which is the point: the spellings are unbounded, so the scan
#: classifies the READER and never the path.
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
]

#: ...and the forms that are fine, or the check above is satisfied by a scan
#: that reports everything.
PERMITTED_READS = [
    ("a stylesheet", 'def test_x():\n    body = css(TOKENS_CSS)\n'),
    ("a script", 'def test_x():\n    body = js(JS / "format.js")\n'),
    ("markup", 'def test_x():\n    body = html(INDEX_HTML)\n'),
    ("a path only known at run time", 'def test_x():\n'
                                      '    for path in stylesheets():\n'
                                      '        body = source(path)\n'),
    ("this file's own source", 'def test_x():\n    body = read(THIS_FILE)\n'),
]


@pytest.mark.parametrize("what,snippet", EVASIONS, ids=[name for name, _ in EVASIONS])
def test_the_self_scan_reports_a_read_however_it_is_spelled(what, snippet):
    """A rule nobody has seen fail is a rule nobody has seen work.

    `test_no_source_file_is_read_without_its_comments_being_stripped` asserts
    an EMPTY list, and an empty list is what a scan that has stopped matching
    also produces. These are the inputs that tell the two apart, and every one
    of them passed the enumerated scan this replaces.
    """
    _stripped, raw = _reads(ast.parse(snippet))

    assert raw, f"{what} was not reported at all"


@pytest.mark.parametrize(
    "what,snippet", PERMITTED_READS, ids=[name for name, _ in PERMITTED_READS]
)
def test_the_self_scan_leaves_a_stripping_reader_alone(what, snippet):
    """The other direction. A scan that reported everything would pass the
    check above while making the readers unusable, and someone would delete
    it."""
    stripped, raw = _reads(ast.parse(snippet))

    assert raw == [], f"{what} was reported as a raw read: {raw}"
    # `read(THIS_FILE)` is permitted and is not a stripped read; everything
    # else here has to be COUNTED, or the floor in
    # `test_no_source_file_is_read_without_its_comments_being_stripped` is a
    # list the scan simply never fills.
    if "read(THIS_FILE)" not in snippet:
        assert stripped, f"{what} was not counted as a stripped read"


#: (suffix, source, what the browser is left with). The three strippers are
#: each guarded on their own further down; this is the TABLE, which is what
#: decides which of them a given file gets. Pointing `.js` at the CSS stripper
#: leaves every `//` comment standing - the exact defect that let the Camelot
#: hue be commented out - and pointing `.html` at it leaves every `<!-- -->`.
#: Both survived with this file green until this table existed, because
#: index.html carries no comment and drawer.js's header is a `/* */` one.
READER_DISPATCH = [
    (".css", "/* gone */\n//kept", "\n//kept"),
    (".js", "/* gone */\n// gone\nkept", "\n\nkept"),
    (".html", "<!-- gone -->/* kept */", "/* kept */"),
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
    """The three suffix asserts, which nothing in the tree can reach.

    Every path this file reads ends in `.css`, `.js` or `.html`, so no call
    exercises the wrong-reader case and all three asserts survived deletion
    with the suite green. They are worth having - `css()` on a script strips
    `/* */` and leaves every `//` comment standing, which is the reader being
    wrong about the browser in the direction this whole file exists to stop -
    so they are pinned here rather than left as decoration.
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
    Every consumer in this file resolves names through `_declaration` and
    `_custom_properties`, so this pins all of them at once.
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

    `_splittable` is called from the reader and from all three splitters, so
    this asserts on all four: a consumer that reached around one of them would
    be the sixth place this file has been wrong about the same thing.
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
    through `_important_declaration`, which requires it. So: every rule the
    sticky guard reads is unflagged, and the reduced-motion block is flagged.
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
    assert without_html_comments("<main><!-- <aside> --></main>") == "<main></main>"
    assert without_html_comments("<!--\n<main>\n-->") == "", "a multi-line comment survived"
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
    """(selector, declarations) for every innermost block in ``text``.

    Takes text that has ALREADY been through `css()`. Stripping again here
    would be a second place the rule lives, which is the shape of the bug this
    replaced.

    Refuses a string, because `{` and `}` inside one are content rather than
    structure: `.x { content: "{}" }` splits into a rule whose selector is
    `content: "` and whose body is empty, and the real `.x` rule vanishes from
    the result entirely."""
    return re.findall(r"([^{}]+)\{([^{}]*)\}", _splittable(text))


def _declared_durations():
    """(milliseconds, declaration) for every duration in every stylesheet."""
    found = []
    for sheet in stylesheets():
        for _selector, declarations in _rules(css(sheet)):
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
    """Overriding the duration TOKENS means every transition in the app obeys
    the preference without any component opting in individually.

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

    # The two TOKENS, which every component reads through `var()`. Ordinary
    # declarations: nothing else declares them inside this block, so last-wins
    # is the cascade and `_declaration` resolves them.
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

    ``--focus-ring: none`` satisfies every name-presence check in this file
    while removing the focus indicator from the whole application, which is the
    exact outcome the check is here to prevent.
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
    """Every custom property tokens.css declares, keyed by its WHOLE name.

    Through the same anchored reader as every other lookup here, so a token
    can only ever be read off the declaration that carries its exact name -
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
    it beats every stylesheet rule that would have corrected it."""
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
# THIS LIST IS NOW EXHAUSTIVE BY CONSTRUCTION rather than by inspection, and it
# had to be: it was assembled a rule at a time, and twice a rule was found
# missing after the list had been called complete - the length-times-length one,
# then the closing-token one, which accepted `bottom: calc(1px,`. Guessing at
# what is uncovered does not converge. So every raise, every branch and every
# assert in `_tokenise`, `_Typer`, `_type_of` and `assert_sticks_to_the_bottom`
# was disabled ONE AT A TIME and this file re-run against the mutant, which
# turned up EIGHT more survivors past the one that was reported: the closing
# token, the `var()` name check, the unclosed-`var(` check, the bareness of a
# substituted value, the recursion limit, the `position: sticky` assert, the
# missing-`bottom` assert, and the `(?:^|;)` anchor that stops `padding-bottom`
# being read as `bottom`. Each is covered below or in a test underneath, and
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

    Two separate holes met here. The `(?:^|;)` anchor is what stops the search
    matching the tail of `padding-bottom`, and without it this declaration
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
    presence would be asserting that the feature was not built. It is the ONLY
    pre-existing test this PR changes.

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
    the strings that would carry an injection. Every component builds nodes and
    sets textContent; one innerHTML anywhere defeats that for all of them.

    Checked across every script rather than only the drawer, because the
    property is "this frontend does not do that", not "this file does not".
    Comments are stripped first, so the drawer is allowed to SAY it does not
    write innerHTML in the same file that must not write it.
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
    half of the same claim, and it is the stronger one: it fails for ANY new
    reader of the field, in any component, before anyone has to think of a
    string to assert against. Comments are stripped first - the reasoning above
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
    for selector, declarations in _rules(body):
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
