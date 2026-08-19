"""Guard: nothing under src/services/ may import a UI toolkit.

This is the whole point of the services layer - a single stray import defeats
it, and the front end stops being replaceable. Enforced two ways:

1. A static AST walk over every module. Parsing, not grepping: a grep matches
   the word "tkinter" in comments and docstrings and would fail on this very
   file. ast.walk also descends into function bodies, which matters because the
   UI's own style is function-local imports.
2. A subprocess import of the whole package asserting tkinter never reaches
   sys.modules, which catches *transitive* pull-in (e.g. via utils.icon) that
   the AST walk cannot see.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SERVICES_DIR = Path(__file__).resolve().parent.parent / "src" / "services"

FORBIDDEN_ROOTS = {"tkinter", "ui", "src.ui"}


def _service_modules():
    return sorted(SERVICES_DIR.rglob("*.py"))


def _imported_module_names(tree):
    """Yield every module name an import statement in ``tree`` refers to."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, which cannot reach a UI package
            # from inside src/services/.
            if node.level == 0 and node.module:
                yield node.module


def _forbidden_import(module_name):
    """Return the forbidden root ``module_name`` belongs to, or None."""
    parts = module_name.split(".")
    for root in FORBIDDEN_ROOTS:
        root_parts = root.split(".")
        if parts[: len(root_parts)] == root_parts:
            return root
    return None


def test_services_directory_exists_and_has_modules():
    """Guard the guard: an empty directory would make every check vacuous."""
    assert SERVICES_DIR.is_dir()
    assert _service_modules(), f"no modules found under {SERVICES_DIR}"


@pytest.mark.parametrize(
    "module_path", _service_modules(), ids=lambda p: p.name
)
def test_service_module_imports_no_ui(module_path):
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    offenders = [
        (name, _forbidden_import(name))
        for name in _imported_module_names(tree)
        if _forbidden_import(name)
    ]

    assert not offenders, (
        f"{module_path.relative_to(SERVICES_DIR.parent.parent)} imports "
        + ", ".join(f"{name!r} (forbidden root {root!r})" for name, root in offenders)
    )


def test_importing_services_never_loads_tkinter():
    """Catches transitive UI imports the AST walk cannot see."""
    src = SERVICES_DIR.parent
    modules = [f"services.{p.stem}" for p in _service_modules() if p.stem != "__init__"]
    program = (
        "import sys\n"
        "import services\n"
        + "".join(f"import {m}\n" for m in modules)
        + "loaded = sorted(m for m in sys.modules if m.split('.')[0] in "
        "('tkinter', 'ui'))\n"
        "print(','.join(loaded))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(src),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", (
        f"importing src/services pulled in UI modules: {result.stdout.strip()}"
    )
