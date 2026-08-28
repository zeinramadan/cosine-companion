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
GUIDANCE_DRIVER = ROOT / "tests/web/js/library_guidance_driver.mjs"


class _ButtonLabels(HTMLParser):
    """Visible button labels keyed by stable HTML attributes."""

    def __init__(self):
        super().__init__()
        self.labels = {}
        self._button = None
        self._hidden = []
        self._text = []

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
