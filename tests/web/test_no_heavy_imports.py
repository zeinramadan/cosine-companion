"""Guard: importing the web API layer must not load a GUI toolkit or Essentia.

``src/web/server.py`` and ``src/web/api.py`` are the halves of the web layer
that CI exercises. The CI job installs numpy/pandas/pyarrow/lxml/pytest and
pywebview - it has no Essentia, no TensorFlow, and the runner is headless. If
either module reached ``webview`` or ``tkinter`` at import time the API tests
could not be collected at all, and the 483 MB TensorFlow stack would be paid
for on every server boot.

Only ``src/web/host.py`` may import ``webview``; that is the module that owns
the macOS main thread and it is deliberately excluded here.

This mirrors tests/test_services_are_lightweight.py: the check runs in a
**subprocess** and inspects ``sys.modules`` rather than the source text. A grep
would pass while a transitive import three packages away still loaded the
offender - which is exactly the failure this file exists to catch. It does not
require any of the forbidden packages to be installed: it asserts they were
never *reached*, which holds either way.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
WEB_DIR = SRC / "web"

# webview and tkinter are GUI toolkits the API layer must stay free of so it can
# run headless; essentia is the 483 MB offender and tensorflow is what it loads.
FORBIDDEN_ROOTS = ("webview", "tkinter", "essentia", "tensorflow")

# host.py is the one module allowed to import webview - it is the pywebview
# host. Everything else under src/web/ is checked.
HEADLESS_MODULES = ("web", "web.assets", "web.server", "web.api", "web.jobs")


def _loaded_forbidden_after(import_statements):
    """Import in a subprocess; return the forbidden modules that got loaded."""
    program = (
        "import sys\n"
        + import_statements
        + "\nloaded = sorted(\n"
        "    m for m in sys.modules\n"
        f"    if m.split('.')[0] in {FORBIDDEN_ROOTS!r}\n"
        ")\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(SRC),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return [m for m in result.stdout.strip().split(",") if m]


def test_the_guard_has_modules_to_guard():
    """An empty web directory would make every check below vacuous."""
    assert WEB_DIR.is_dir(), f"{WEB_DIR} does not exist"
    assert (WEB_DIR / "server.py").is_file()
    assert (WEB_DIR / "api.py").is_file()
    assert (WEB_DIR / "jobs.py").is_file()


@pytest.mark.parametrize("module", HEADLESS_MODULES)
def test_importing_one_web_module_loads_no_gui_toolkit(module):
    """Per module, so a failure names the offender instead of the package."""
    assert _loaded_forbidden_after(f"import {module}\n") == []


def test_importing_the_server_and_the_api_together_loads_no_gui_toolkit():
    """The combination the server process actually performs."""
    assert _loaded_forbidden_after("import web.server, web.api\n") == []


def test_the_web_package_itself_imports_nothing_heavy():
    """``import web`` must not eagerly pull server/api/host in behind it.

    ``src/web/__init__.py`` is a package marker. If it grows re-exports it will
    drag ``host`` - and therefore ``webview`` - into every importer.
    """
    program = (
        "import sys\n"
        "import web\n"
        "eager = sorted(m for m in sys.modules if m.startswith('web.'))\n"
        "print(','.join(eager))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(SRC),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", (
        f"importing web eagerly loaded submodules: {result.stdout.strip()}"
    )


def test_only_host_may_import_webview():
    """Pin the exemption itself, so it cannot quietly widen.

    A source-text check is the right tool here: the point is which FILE is
    allowed to name ``webview``, not what gets loaded at runtime.
    """
    offenders = [
        path.name
        for path in sorted(WEB_DIR.glob("*.py"))
        if path.name != "host.py" and "import webview" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"modules other than host.py import webview: {offenders}"
