"""Static contracts that the DOM shim cannot observe: copy, CSS and boot wiring."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "src/web/static/index.html"
APP_CSS = ROOT / "src/web/static/css/app.css"
MAIN_JS = ROOT / "src/web/static/js/main.js"


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

    assert "mountSettings({ refreshLibrary: refreshLibrarySummary });" in body
    assert ".library()" in body
    assert "store.setState({ library, libraryError: null });" in body
    assert "return false;" in body
