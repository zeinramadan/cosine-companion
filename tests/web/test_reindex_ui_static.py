"""Static contracts that the DOM shim cannot observe: copy, CSS and boot wiring."""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess

from web import host


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "src/web/static/index.html"
APP_CSS = ROOT / "src/web/static/css/app.css"
MAIN_JS = ROOT / "src/web/static/js/main.js"
JS = ROOT / "src/web/static/js"
GUIDANCE_DRIVER = ROOT / "tests/web/js/library_guidance_driver.mjs"
JS_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\w])//[^\n]*", re.S)


def _js(path):
    """JavaScript with comments replaced by separating whitespace."""
    return JS_COMMENT.sub(
        lambda match: " " + "\n" * match.group().count("\n"),
        path.read_text(encoding="utf-8"),
    )


class _ButtonLabels(HTMLParser):
    """Visible button labels keyed by stable HTML attributes."""

    def __init__(self):
        super().__init__()
        self.labels = {}
        self._button = None
        self._hidden = []
        self._text = []
        self.navigation = set()
        self.sections = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "button":
            assert self._button is None, "index.html contains nested buttons"
            self._button = attributes
            self._hidden = [False]
            self._text = []
        elif self._button is not None:
            self._hidden.append(
                self._hidden[-1] or attributes.get("aria-hidden") == "true"
            )

        if tag == "button" and "data-destination" in attributes:
            destination = attributes["data-destination"]
            assert destination not in self.navigation, (
                f"duplicate destination navigation control: {destination}"
            )
            self.navigation.add(destination)

        classes = set(attributes.get("class", "").split())
        identity = attributes.get("id", "")
        if tag == "section" and "view" in classes and identity.startswith("view-"):
            destination = identity.removeprefix("view-")
            assert destination not in self.sections, (
                f"duplicate destination view section: {destination}"
            )
            self.sections.add(destination)

    def handle_data(self, data):
        if self._button is not None and not self._hidden[-1]:
            self._text.append(data)

    def handle_endtag(self, tag):
        if self._button is None:
            return
        if tag == "button":
            label = " ".join("".join(self._text).split())
            if "id" in self._button:
                self.labels[("id", self._button["id"])] = label
            if "data-destination" in self._button:
                self.labels[
                    ("destination", self._button["data-destination"])
                ] = label
            self._button = None
            self._hidden = []
            self._text = []
        else:
            self._hidden.pop()


def _button_labels():
    parser = _ButtonLabels()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    parser.close()
    return parser.labels


def _mounted_component_modules():
    """``component module -> called exports`` derived from ``main.js``."""
    body = _js(MAIN_JS)
    component_targets = set()
    for statement in re.findall(
        r"(?ms)^\s*import\b.*?;[ \t]*(?:\n|$)", body
    ):
        targets = re.findall(r"['\"]([^'\"]+)['\"]", statement)
        assert len(targets) == 1, f"could not read main.js import: {statement.strip()}"
        if targets[0].startswith("./components/"):
            component_targets.add(targets[0])

    assert component_targets, "main.js imports no components"

    parsed_targets = set()
    mounted = {}
    for names, target in re.findall(
        r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", body
    ):
        if target not in component_targets:
            continue
        parsed_targets.add(target)
        module = (JS / target).resolve()
        assert module.is_relative_to(JS / "components"), (
            f"component imported outside components/: {target}"
        )
        assert module.is_file(), f"component does not exist: {target}"

        for name in names.split(","):
            binding = re.fullmatch(
                r"\s*([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?\s*",
                name,
            )
            assert binding is not None, f"could not read {target} import: {name!r}"
            exported, local = binding.group(1), binding.group(2) or binding.group(1)
            if re.search(rf"\b{re.escape(local)}\s*\(", body):
                mounted.setdefault(module, set()).add(exported)

    assert parsed_targets == component_targets, (
        "main.js has a component import the structural reader cannot follow: "
        f"all={sorted(component_targets)}, parsed={sorted(parsed_targets)}"
    )
    assert mounted, "main.js calls no imported component; the call reader stopped matching"
    return mounted


def _destination_components():
    """``destination -> mounted component`` derived from HTML and main.js."""
    catalog = _ButtonLabels()
    catalog.feed(INDEX.read_text(encoding="utf-8"))
    catalog.close()

    assert catalog.navigation, "index.html declares no destination controls"
    assert catalog.navigation == catalog.sections, (
        "destination controls and view sections disagree: "
        f"controls={sorted(catalog.navigation)}, sections={sorted(catalog.sections)}"
    )

    components = {}
    for module, called_exports in _mounted_component_modules().items():
        body = _js(module)
        roots = set(
            re.findall(
                r"document\.getElementById\(\s*['\"]view-([a-z-]+)['\"]\s*\)",
                body,
            )
        )
        roots.intersection_update(catalog.navigation)
        if not roots:
            continue
        assert len(roots) == 1, (
            f"{module.name} names multiple destination roots: {sorted(roots)}"
        )
        destination = roots.pop()
        assert destination not in components, (
            f"multiple mounted components claim view-{destination}: "
            f"{components[destination].name}, {module.name}"
        )
        exported = [
            mount
            for mount in called_exports
            if re.search(rf"\bexport\s+function\s+{re.escape(mount)}\s*\(", body)
        ]
        assert exported, (
            f"{module.name} names view-{destination} but exports none of "
            f"{sorted(called_exports)}"
        )
        components[destination] = module

    assert set(components) == catalog.navigation, (
        "shipped destinations and mounted destination components disagree: "
        f"destinations={sorted(catalog.navigation)}, components={sorted(components)}"
    )
    return components


LOAD_ERROR_BRANCH = re.compile(
    r"(?m)^[ \t]*if\s*\(\s*state\.library\s*&&\s*"
    r"state\.library\.load_error\s*\)\s*\{\s*$"
)


def test_every_destination_renders_the_saved_index_error_instead_of_an_empty_state():
    r"""No destination may turn an unloaded broken index into zero tracks.

    THE DESTINATION SET IS STRUCTURAL, NOT A FIVE-FILE LIST. ``HTMLParser``
    reads every shipped ``data-destination`` control and matching ``view-*``
    section. ``main.js`` then supplies the mounted component modules, and the
    module's own ``document.getElementById('view-*')`` lookup ties it back to
    the destination identity. A sixth destination therefore joins this check
    without this test changing; a nav/view/module mismatch fails separately.

    THE CLAIM IS DELIBERATELY A SOURCE CONVENTION. For each derived module this
    requires the exact uncommented branch used by Explore and Set Creator,
    the shared error title, and the backend message as the state-block body.
    It does not execute JavaScript or prove control flow. A template literal
    could contain an imitation branch, and a semantically equivalent optional
    chain or destructuring read is refused until this reader is taught that
    spelling. The five runtime component tests establish what today's branches
    render; this structural half makes a new destination opt into that same
    idiom instead of silently inheriting the tracks endpoint's empty list.
    """
    offenders = {}
    for destination, module in sorted(_destination_components().items()):
        body = _js(module)
        missing = []
        if not LOAD_ERROR_BRANCH.search(body):
            missing.append("if (state.library && state.library.load_error)")
        if "title: 'Library index needs rebuilding'" not in body:
            missing.append("the shared error title")
        if "body: state.library.load_error.message" not in body:
            missing.append("the backend message body")
        if missing:
            offenders[destination] = {"module": module.name, "missing": missing}

    assert offenders == {}, f"destinations can render a false empty state: {offenders}"


LIBRARY_TRACK_COUNT = re.compile(r"\btrack_count\b")
LIBRARY_LOAD_ERROR = re.compile(r"\bload_error\b")


def test_every_mounted_track_count_consumer_also_consults_load_error():
    """A mounted surface may not treat an unloadable index as zero tracks.

    The surface set is derived from component imports that ``main.js`` actually
    calls. The guarded class is then derived by the canonical library-summary
    field it consumes, ``track_count``; a newly mounted count surface joins
    without adding its filename here. Requiring the sibling ``load_error``
    field is deliberately spelling-flexible so destructuring, optional chaining
    and other legitimate local refactors remain possible.

    This is a source convention, not data-flow analysis: it cannot prove that
    the two reads influence the same output, and it does not cover a count
    fetched from another endpoint or represented by a future field. The real
    sidebar module's three-state behavioural test proves today's control flow.
    """
    consumers = {}
    offenders = {}
    for module in sorted(_mounted_component_modules()):
        body = _js(module)
        if not LIBRARY_TRACK_COUNT.search(body):
            continue
        consumers[module.name] = module
        if not LIBRARY_LOAD_ERROR.search(body):
            offenders[module.name] = "reads track_count without load_error"

    assert consumers, "no mounted track_count consumer; the structural reader stopped matching"
    assert offenders == {}, f"mounted count surfaces can render a false zero: {offenders}"


def _first_run_guidance():
    executable = shutil.which("node")
    assert executable is not None, "node is required to inspect shipped JS guidance"
    finished = subprocess.run(
        [executable, str(GUIDANCE_DRIVER)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout)["firstRunGuidance"]


def test_guidance_names_the_shipped_labels_of_its_recovery_controls():
    """Labels come from index.html; the test duplicates only stable identities."""
    labels = _button_labels()
    settings = labels[("destination", "settings")]

    expected_by_guidance = {
        _first_run_guidance(): [settings, labels[("id", "reindex-incremental")]],
        host._INDEX_REBUILD_ROUTE: [settings, labels[("id", "reindex-full")]],
    }
    for guidance, expected_labels in expected_by_guidance.items():
        for label in expected_labels:
            assert label in guidance, (
                f"guidance names no shipped {label!r} recovery control: {guidance!r}"
            )


def test_settings_explains_how_to_create_the_rekordbox_xml():
    body = INDEX.read_text(encoding="utf-8")

    assert "File → Export Collection in XML format" in body
    assert "exported file's full path below" in body


def test_both_reindex_tradeoffs_are_visible_before_their_buttons():
    body = INDEX.read_text(encoding="utf-8")

    incremental_copy = "Embed only tracks that are not in the index yet. Usually finishes in seconds."
    incremental_button = 'id="reindex-incremental"'
    full_copy = "roughly 75 minutes for\n                    1,532 tracks. Requires confirmation."
    full_button = 'id="reindex-full"'

    assert incremental_copy in body
    assert body.index(incremental_copy) < body.index(incremental_button)
    assert full_copy in body
    assert body.index(full_copy) < body.index(full_button)
    assert 'class="button button--danger" id="reindex-full"' in body


def test_reindex_stop_remains_visible_at_a_resolvable_sticky_offset():
    sheet = APP_CSS.read_text(encoding="utf-8")
    match = re.search(r"\.settings__reindex-progress\s*\{(?P<body>.*?)\}", sheet, re.S)

    assert match, "the reindex progress rule is missing"
    declarations = match.group("body")
    assert re.search(r"\bposition\s*:\s*sticky\s*;", declarations)
    assert re.search(
        r"\bbottom\s*:\s*calc\(var\(--space-6\)\s*\*\s*-1\)\s*;",
        declarations,
    )
    assert re.search(r"\bbackground\s*:\s*var\(--surface-2\)\s*;", declarations)
    assert ".settings__reindex-progress[hidden]" in sheet


def test_the_production_boot_wires_reindex_success_to_the_shared_library_summary():
    body = MAIN_JS.read_text(encoding="utf-8")

    assert "mountSettings({ store, refreshLibrary: refreshLibrarySummary });" in body
    assert ".library()" in body
    assert "store.setState({ library, libraryError: null });" in body
    assert "return false;" in body
