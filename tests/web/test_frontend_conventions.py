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
    """Settings is the one addition; the three placeholders stay explicit."""
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


def test_the_derived_placeholder_check_can_still_see_a_placeholder():
    """Guard the guard: if every destination were built, the loop above would
    pass over an empty list and stop distinguishing anything."""
    unbuilt = [
        name
        for name, markup in _destination_sections(read(INDEX_HTML))
        if 'class="placeholder"' in markup
    ]

    assert unbuilt, "no placeholders left; retire this check rather than keeping a vacuous one"


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
