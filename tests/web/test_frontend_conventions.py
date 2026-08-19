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


def test_reduced_motion_is_respected_at_the_token_level():
    """Overriding the duration TOKENS means every transition in the app obeys
    the preference without any component opting in individually."""
    body = read(TOKENS_CSS)

    assert "@media (prefers-reduced-motion: reduce)" in body
    reduced = body[body.index("@media (prefers-reduced-motion: reduce)") :]
    assert "--motion-base:" in reduced and "--motion-fast:" in reduced
    assert "animation-duration" in reduced
    assert "transition-duration" in reduced


def test_no_transition_or_animation_is_longer_than_two_hundred_milliseconds():
    durations = []
    for sheet in stylesheets():
        body = without_comments(read(sheet))
        durations += [int(value) for value in re.findall(r"(\d+)ms\b", body)]
        durations += [
            int(float(value) * 1000) for value in re.findall(r"(\d+(?:\.\d+)?)s\b", body)
        ]

    assert durations, "no durations found; the regex stopped matching"
    assert max(durations) <= 700, f"durations over 700 ms: {sorted(set(durations))}"
    # The spinner is a repeating indicator, not a transition; everything that
    # moves in response to an action is under 200 ms.
    transitions = [d for d in durations if d != 700]
    assert max(transitions) <= 200, f"transitions over 200 ms: {sorted(set(transitions))}"


def test_there_is_a_visible_focus_ring():
    body = without_comments(read(APP_CSS))

    assert ":focus-visible" in body
    assert "--focus-ring" in body


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
    body = read(INDEX_HTML)

    assert "<nav" in body
    assert "<aside" in body
    assert 'class="main"' in body
    assert "<h1" in body


def test_all_four_destinations_are_present():
    """Three of them are not implemented in this PR and are still rendered: the
    shape of the shell is part of what is being reviewed."""
    body = read(INDEX_HTML)

    for destination in ("explore", "set-creator", "library", "export"):
        assert f'data-destination="{destination}"' in body


def test_the_unimplemented_destinations_say_so():
    body = read(INDEX_HTML)

    assert body.count("Coming in the next PR") == 3


def test_the_drawer_does_not_invent_playlist_data():
    """There is no playlist endpoint yet and track.playlists comes back null.
    The drawer says so and renders nothing else."""
    body = read(JS / "components" / "drawer.js")

    assert "Playlist membership arrives in the next update." in body
    assert "/api/playlists" not in body


def test_every_interactive_control_is_a_real_element():
    """A clickable div is not keyboard reachable and announces nothing."""
    body = read(INDEX_HTML)

    assert not re.search(r"<div[^>]*\bonclick", body)
    for match in re.finditer(r"<button[^>]*>", body):
        assert 'type="button"' in match.group(0), match.group(0)


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


def test_the_entry_module_is_loaded_as_a_module():
    """`type="module"` is what makes the import graph above work at all."""
    assert '<script type="module" src="/js/main.js"></script>' in read(INDEX_HTML)
