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

HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
COLOUR_FUNCTION = re.compile(r"\b(?:rgba?|hsla?|lab|lch|oklch|color)\s*\(")


def read(path):
    return path.read_text(encoding="utf-8")


def without_comments(text):
    return COMMENT.sub("", text)


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

    Comments are stripped first. A commented-out declaration is not a
    declaration - the browser sees an undefined custom property, the whole
    `bottom` is invalid at computed-value time and the block returns to normal
    flow - and reading it as one would be this guard's own bug back again.
    """
    declared = re.search(rf"{re.escape(name)}\s*:\s*([^;}}]+)", without_comments(tokens))
    if not declared:
        raise _NotALength(f"uses {name}, which tokens.css does not declare")
    return declared.group(1).strip()


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
    assert re.search(r"position\s*:\s*sticky", declarations), (
        f"{rule_name} is back in the normal flow: {declarations}"
    )

    match = re.search(r"(?:^|;)\s*bottom\s*:\s*([^;}]+)", declarations)
    assert match, f"{rule_name} has no bottom offset, so it never sticks: {declarations}"
    value = match.group(1).strip()

    try:
        resolved = _type_of(value, read(TOKENS_CSS))
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


def stylesheets():
    return sorted(CSS.glob("*.css"))


def scripts():
    return sorted(JS.rglob("*.js"))


# ---------------------------------------------------------------------------
# Tokens first
# ---------------------------------------------------------------------------


def test_there_is_a_token_file_and_it_is_where_the_colours_live():
    assert TOKENS_CSS.is_file()
    assert HEX_COLOUR.search(without_comments(read(TOKENS_CSS))), (
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
        body = without_comments(read(sheet))
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
        body = read(script)
        found = HEX_COLOUR.findall(body)
        if found:
            offenders[str(script.relative_to(JS))] = sorted(set(found))

    assert offenders == {}, f"literal colours in JavaScript: {offenders}"


def test_every_custom_property_used_is_actually_defined():
    """A typo in a var() name is silent: the declaration is simply dropped and
    the element inherits, which usually still looks plausible."""
    defined = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", read(TOKENS_CSS), re.M))
    # Properties the components set on an element at runtime.
    for script in scripts():
        defined.update(re.findall(r"setProperty\(\s*['\"](--[a-z0-9-]+)", read(script)))

    used = set()
    for sheet in stylesheets():
        used.update(re.findall(r"var\(\s*(--[a-z0-9-]+)", without_comments(read(sheet))))

    assert defined, "no custom properties found; the regex stopped matching"
    assert used - defined == set(), f"undefined custom properties: {sorted(used - defined)}"


def test_the_type_scale_has_at_most_six_sizes():
    """More than six and the hierarchy stops being a hierarchy."""
    sizes = re.findall(r"^\s*(--text-[a-z0-9]+)\s*:", read(TOKENS_CSS), re.M)

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


def _milliseconds(value):
    """The single duration in a declaration value, in ms, or None."""
    match = DURATION.search(value)
    if match is None:
        return None
    number, unit = match.groups()
    return float(number) * (1000 if unit == "s" else 1)


def _rules(text):
    """(selector, declarations) for every innermost block in ``text``."""
    return re.findall(r"([^{}]+)\{([^{}]*)\}", without_comments(text))


def _declared_durations():
    """(milliseconds, declaration) for every duration in every stylesheet."""
    found = []
    for sheet in stylesheets():
        for _selector, declarations in _rules(read(sheet)):
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
    body = read(TOKENS_CSS)

    assert "@media (prefers-reduced-motion: reduce)" in body
    reduced = body[body.index("@media (prefers-reduced-motion: reduce)") :]

    for name in (
        "--motion-base",
        "--motion-fast",
        "animation-duration",
        "transition-duration",
    ):
        match = re.search(rf"{re.escape(name)}\s*:\s*([^;]+);", reduced)
        assert match, f"{name} is not overridden under prefers-reduced-motion"

        milliseconds = _milliseconds(match.group(1))
        assert milliseconds is not None, (
            f"{name} is overridden with {match.group(1)!r}, which is not a duration"
        )
        assert milliseconds <= REDUCED_MOTION_CEILING_MS, (
            f"{name} is still {milliseconds:g} ms under prefers-reduced-motion"
        )

    # A 1 ms animation that still repeats forever is still motion.
    assert re.search(r"animation-iteration-count\s*:\s*1\b", reduced), (
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
    body = without_comments(read(APP_CSS))

    assert ":focus-visible" in body
    assert "--focus-ring" in body

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
    body = without_comments(read(APP_CSS))
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", body)

    for selector, declarations in blocks:
        if re.search(r"outline\s*:\s*none", declarations):
            replaced = "box-shadow" in declarations or ":focus-visible" in selector
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
    return dict(
        re.findall(r"^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);", read(TOKENS_CSS), re.M)
    )


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
    match = re.search(
        r"hsl\(\s*var\(--camelot-hue[^)]*\)\s+([\d.]+)%\s+([\d.]+)%\s*\)", tokens[name]
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
    body = read(JS / "format.js")

    assert "(position - 1) * 30" in body


# ---------------------------------------------------------------------------
# The page itself
# ---------------------------------------------------------------------------


def test_the_page_has_no_inline_styles():
    """An inline style is a colour or a spacing value outside the system, and
    it beats every stylesheet rule that would have corrected it."""
    assert not re.search(r'\sstyle\s*=\s*"', read(INDEX_HTML))


def test_nothing_is_loaded_from_another_origin():
    """The app runs from a loopback server against a local library, and a frozen
    build has no guarantee of a network at all. A CDN font or script would make
    the UI depend on one."""
    offenders = []
    for path in [INDEX_HTML] + stylesheets() + scripts():
        for match in re.finditer(r"""(?:https?:)?//[^\s'")]+""", read(path)):
            if match.group(0).startswith("//"):
                continue  # a `// comment` in JavaScript
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
    body = read(INDEX_HTML)

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
    body = read(INDEX_HTML)

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
    body = read(INDEX_HTML)
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
    body = read(INDEX_HTML)

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
    body = read(INDEX_HTML)
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
    body = read(INDEX_HTML)
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
    assert 'class="nav__soon"' not in read(INDEX_HTML)


def test_the_set_creator_status_line_cannot_be_scrolled_out_of_reach():
    """Inventory :244 and :1293 - the Tk status bar is packed ``side="bottom"``
    "so a short window cannot hide it". That is a property of the control, not
    of Tk's geometry manager, and it has to survive the port.

    Left in the normal flow the line sat under the generated rows, so with a
    500-row set the message announcing the set was off screen. This is a
    SOURCE-TEXT check - it cannot lay anything out - and the behavioural half
    was done by hand against real Chrome and recorded in the PR description.
    """
    body = without_comments(read(APP_CSS))
    match = re.search(r"\.setc__status\s*\{([^}]*)\}", body)

    assert match, "the Set Creator status rule is gone"
    declarations = " ".join(match.group(1).split())
    # By value - `bottom: auto` passed the presence check this used to make,
    # and means the status line scrolls away. Same claim, same guard as the
    # Export progress block below.
    assert_sticks_to_the_bottom("the Set Creator status line", declarations)
    # Opaque, or the rows scroll THROUGH the text rather than under it.
    assert re.search(r"background\s*:\s*var\(--surface", declarations), declarations


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
    body = without_comments(read(APP_CSS))
    match = re.search(r"\.exportv__progress\s*\{([^}]*)\}", body)

    assert match, "the Export progress rule is gone"
    declarations = " ".join(match.group(1).split())

    assert_sticks_to_the_bottom("the progress block", declarations)
    # Opaque, or the rows scrolling under it read through it.
    assert re.search(r"background\s*:\s*var\(--surface", declarations), (
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
# each was re-run to a red. Two branches survive with no discriminating input at
# all and are documented AS such at their sites rather than papered over: the
# `inside_maths` save/restore in `_Typer.unit`, and the `STICKY_KEYWORDS`
# special case.
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
    body = read(INDEX_HTML)

    assert 'id="modal-layer"' in body
    assert 'getElementById(LAYER_ID)' in read(JS / "modal.js")
    assert "const LAYER_ID = 'modal-layer';" in read(JS / "modal.js")


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
    body = read(JS / "components" / "drawer.js")

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
JS_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\w])//[^\n]*", re.S)

HTML_SINK = re.compile(r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b")


def without_js_comments(text):
    return JS_COMMENT.sub("", text)


def test_the_comment_stripper_still_strips_something():
    """Guard the guard: a stripper that removed everything, or nothing, would
    make the check below vacuous in one direction or noisy in the other."""
    stripped = without_js_comments(read(JS / "components" / "drawer.js"))

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
        found = HTML_SINK.findall(without_js_comments(read(script)))
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
    body = read(INDEX_HTML)

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
        for target in re.findall(r"from\s+'([^']+)'", read(current)):
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
    body = without_js_comments(read(JS / "main.js"))

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
    body = without_comments(read(APP_CSS))
    match = re.search(r"\.message-box__message\s*\{([^}]*)\}", body)

    assert match, "the message-box body rule is gone"
    assert re.search(r"white-space\s*:\s*pre-line\b", match.group(1)), (
        f"the message box collapses its newlines: {' '.join(match.group(1).split())}"
    )


def test_no_screen_renders_the_services_playlist_counter():
    """`playlists_created` is not a count of files, and the web UI must not read it.

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
    satisfies a check that the field is unused.

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
        body = without_comments(read(script))
        body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
        if "playlists_created" in body:
            offenders[script.name] = [
                line.strip() for line in body.splitlines() if "playlists_created" in line
            ]

    assert offenders == {}, (
        f"the service's playlist counter is being rendered again: {offenders}"
    )


def test_the_entry_module_is_loaded_as_a_module():
    """`type="module"` is what makes the import graph above work at all."""
    assert '<script type="module" src="/js/main.js"></script>' in read(INDEX_HTML)


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
    body = read(TOKENS_CSS)
    root_block = body[body.index(":root {") : body.index("\n}", body.index(":root {"))]

    leaked = [name for name in ("--camelot-bg", "--camelot-fg", "--camelot-edge")
              if f"{name}:" in root_block]

    assert leaked == [], (
        f"{leaked} are declared inside :root, so var(--camelot-hue) resolves "
        "against :root and every pill gets the fallback hue"
    )
    assert ".pill {" in body, "the camelot properties must be declared on .pill"
