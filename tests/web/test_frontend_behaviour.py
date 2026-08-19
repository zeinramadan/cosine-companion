"""Run the frontend's behavioural tests, which are JavaScript, under pytest.

WHY THERE IS JAVASCRIPT IN THIS SUITE
-------------------------------------
Two of the defects this PR shipped with were pure sequencing:

* ``← Back`` re-sorted the restored list with the CURRENT sort, so the history
  entry came back with the right tracks in the wrong order; and
* the palette's debounce invalidated on request start rather than on keystroke,
  leaving a window in which a response for ``a`` repainted the list while the
  input read ``ab``.

Neither is visible in the source, and neither can be reached from Python. An
ordering defect is only settled by running the ordering, so these tests import
the modules that actually ship - no reimplementation - and run them under
``node --test``, which is node's own runner and therefore not a new dependency
to install. The DOM they run against is a ~200-line shim in
``tests/web/js/dom_shim.mjs`` whose limits are documented at the top of that
file: it can tell you what a module DID, not what a user SAW. The visual pass
is still done by hand in WKWebView.

If node is not on PATH these tests skip. That is a real gap and it is named
rather than hidden: the skip reason says which behaviours went unchecked.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent / "js"

#: ``node --test`` arrived in 18, and the suites use top-level await in ESM.
MINIMUM_NODE_MAJOR = 18


def _node():
    """The node binary, or None."""
    return shutil.which("node")


def _node_major(executable):
    reported = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=30
    ).stdout.strip()
    return int(reported.lstrip("v").split(".")[0])


def _suites():
    return sorted(JS_TESTS.glob("*.test.mjs"))


def test_the_javascript_suites_are_discoverable():
    """A rename that orphans a suite must fail loudly rather than silently
    reducing the suite to nothing."""
    names = {path.name for path in _suites()}

    assert names >= {
        "drawer_playlists.test.mjs",
        "explore_copy.test.mjs",
        "explore_history.test.mjs",
        "format.test.mjs",
        "globals.test.mjs",
        "palette_modality.test.mjs",
        "palette_sequencing.test.mjs",
        "settings.test.mjs",
    }, f"a behavioural suite disappeared: {sorted(names)}"


@pytest.mark.parametrize("suite", _suites(), ids=lambda path: path.stem)
def test_frontend_behaviour(suite):
    executable = _node()
    if executable is None:
        pytest.skip(
            "node is not on PATH, so the frontend behaviour suites did not run: "
            f"{suite.name}"
        )
    if _node_major(executable) < MINIMUM_NODE_MAJOR:
        pytest.skip(
            f"node >= {MINIMUM_NODE_MAJOR} is needed for `node --test`; "
            f"{suite.name} did not run"
        )

    finished = subprocess.run(
        [executable, "--test", "--test-reporter=tap", str(suite)],
        capture_output=True,
        text=True,
        cwd=str(suite.parent),
        timeout=300,
    )

    assert finished.returncode == 0, (
        f"{suite.name} failed:\n{finished.stdout}\n{finished.stderr}"
    )
    # A suite that runs zero tests exits 0. That has to be a failure here, or a
    # broken import silently becomes a green run.
    assert "# fail 0" in finished.stdout, finished.stdout
    assert not any(
        line.strip() == "# pass 0" for line in finished.stdout.splitlines()
    ), f"{suite.name} ran no tests:\n{finished.stdout}"


def test_the_dom_shim_is_documented_as_a_shim():
    """It is a test double, not a browser. A future reader must not mistake a
    green run here for evidence that the rendered UI was checked."""
    body = (JS_TESTS / "dom_shim.mjs").read_text(encoding="utf-8")

    assert "It is not a browser and it is not jsdom" in body
    assert "WKWebView" in body


#: Suites whose subject is the harness rather than the frontend, listed one by
#: one. `globals.test.mjs` tests that the shim can install itself over a
#: runtime-owned global - which is a property of the shim, not of any shipped
#: module. Enumerating the exemption means a behavioural suite cannot join it
#: by quietly dropping its import.
HARNESS_SUITES = {"globals.test.mjs"}


def test_no_javascript_suite_reimplements_what_it_tests():
    """Each suite must import from src/web/static/js. A suite that defines its
    own copy of the logic is a tautology, and this PR has been bitten by
    exactly that before."""
    for suite in _suites():
        if suite.name in HARNESS_SUITES:
            continue
        body = suite.read_text(encoding="utf-8")
        assert "src/web/static/js/" in body, f"{suite.name} imports no shipped module"


def test_the_harness_exemption_names_files_that_exist():
    """A dead exemption is an exemption nobody notices growing."""
    present = {path.name for path in _suites()}

    assert HARNESS_SUITES <= present, f"stale exemptions: {sorted(HARNESS_SUITES - present)}"
    assert len(HARNESS_SUITES) < len(present), "every suite is exempt, so the rule is vacuous"
