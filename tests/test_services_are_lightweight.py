"""Guard: importing anything under src/services/ must not load Essentia.

The service layer's whole value is that a headless caller can use it. If
importing a service drags in ``essentia.standard`` then the layer requires a
483 MB TensorFlow install to read a JSON settings file, the CI job (which
installs only numpy/pandas/pyarrow/pytest) cannot even *collect* the suite, and
PR 3's web server pays TensorFlow's import cost at boot.

This is exactly what happened: ``services/__init__.py`` imported
``IndexingService``, which imported ``processing.pipeline`` at module scope,
which pulled in ``processing/__init__.py`` -> ``processing.embeddings`` ->
``import essentia.standard``. Seven test files failed to collect.

The check runs in a **subprocess** and inspects ``sys.modules``, not the source
text. A grep would pass while a transitive import three packages away still
loaded Essentia - that is precisely the failure this file exists to catch. It
does not require Essentia to be installed: it asserts the module was never
*reached*, which holds whether or not it could have been imported.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
SERVICES_DIR = SRC / "services"

# Essentia is the direct offender; TensorFlow is what Essentia loads and the
# reason the cost matters. numpy/pandas/pyarrow are expected and permitted.
FORBIDDEN_ROOTS = ("essentia", "tensorflow")


def _service_modules():
    return sorted(SERVICES_DIR.rglob("*.py"))


def _module_names():
    return [f"services.{p.stem}" for p in _service_modules() if p.stem != "__init__"]


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
    """An empty services directory would make every check below vacuous."""
    assert _module_names(), f"no modules found under {SERVICES_DIR}"


def test_importing_the_services_package_never_loads_essentia():
    assert _loaded_forbidden_after("import services\n") == []


@pytest.mark.parametrize("module", _module_names())
def test_importing_one_service_never_loads_essentia(module):
    """Per module, so a failure names the offender instead of the package."""
    assert _loaded_forbidden_after(f"import {module}\n") == []


def test_importing_every_service_together_never_loads_essentia():
    statements = "import services\n" + "".join(f"import {m}\n" for m in _module_names())

    assert _loaded_forbidden_after(statements) == []


def test_the_settings_reader_is_importable_on_its_own():
    """services.settings_store is 72 lines of json.load. It must not need a
    483 MB dependency, and it must not need the rest of the package either."""
    result = subprocess.run(
        [sys.executable, "-c", "import services.settings_store as s; print(s.XML_PATH_KEY)"],
        cwd=str(SRC),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "xml_path"


def requires_lxml():
    """processing.pipeline imports processing.xml_parser, which needs lxml.

    lxml is a real dependency of parsing a Rekordbox XML - unlike Essentia, it
    is small and CI installs it - but a bare numpy/pandas/pyarrow/pytest
    environment does not have it, and these three checks are about Essentia,
    not about lxml. Skip rather than fail there.
    """
    pytest.importorskip("lxml", reason="processing.xml_parser needs lxml")


def test_importing_the_indexing_pipeline_never_loads_essentia():
    """The pipeline constructs the embedder only when there is work to do, so
    importing it - which is what IndexingService.run() does, and what the
    indexing characterisation tests do - must not cost a TensorFlow load."""
    requires_lxml()

    assert _loaded_forbidden_after("import processing.pipeline\n") == []
    assert _loaded_forbidden_after("import processing\n") == []


def test_the_embedder_is_still_reachable_from_the_pipeline():
    """Lazy must mean deferred, not dropped: the module attribute that the
    tests and tests/manual/real_indexing.py patch has to remain the seam."""
    requires_lxml()

    program = (
        "import sys, types\n"
        "fake = types.ModuleType('essentia')\n"
        "fake.standard = types.ModuleType('essentia.standard')\n"
        "sys.modules['essentia'] = fake\n"
        "sys.modules['essentia.standard'] = fake.standard\n"
        "import processing.pipeline as p\n"
        "assert p.DiscogsEffnetEmbedder is None, 'imported eagerly'\n"
        "assert p._load_embedder().__name__ == 'DiscogsEffnetEmbedder'\n"
        "assert p.DiscogsEffnetEmbedder is not None, 'not cached'\n"
        "import processing\n"
        "assert processing.DiscogsEffnetEmbedder.__name__ == 'DiscogsEffnetEmbedder'\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(SRC),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_importing_the_tkinter_app_never_loads_essentia():
    """On main, `import ui.app` worked without Essentia. This branch must not
    break that invariant - the desktop app only needs the embedder when the
    user actually starts an indexing run."""
    pytest.importorskip("tkinter", reason="headless build of Python without Tk")

    assert _loaded_forbidden_after("import ui.app\n") == []


def test_the_indexing_service_still_reaches_the_pipeline_when_it_runs():
    """The laziness must be an import-time deferral, not a dropped dependency:
    IndexingService.run() has to end up calling processing.pipeline."""
    requires_lxml()

    program = (
        "import sys\n"
        "import types\n"
        "\n"
        "# Stand in for the Essentia-backed module before anything imports it.\n"
        "fake = types.ModuleType('essentia')\n"
        "fake.standard = types.ModuleType('essentia.standard')\n"
        "sys.modules['essentia'] = fake\n"
        "sys.modules['essentia.standard'] = fake.standard\n"
        "\n"
        "from services.indexing_service import IndexingService\n"
        "assert 'processing.pipeline' not in sys.modules, 'imported too early'\n"
        "\n"
        "import processing.pipeline as pipeline\n"
        "calls = []\n"
        "pipeline.index_library = lambda *a, **k: calls.append((a, k)) or "
        "{'status': 'up_to_date', 'new_tracks_found': 0}\n"
        "result = IndexingService(None).run('/nope.xml')\n"
        "assert calls, 'run() never called index_library'\n"
        "print(result.status)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(SRC),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "up_to_date"
