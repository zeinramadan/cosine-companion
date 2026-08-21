"""Contracts for the PyInstaller package shape.

These tests inspect the spec rather than importing it: importing a spec starts
PyInstaller collection against the current interpreter, which is both slow and
incapable of proving what the declarative package recipe says.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = PROJECT_ROOT / "cosine-companion.spec"


def test_the_frozen_package_ships_the_web_frontend_at_its_runtime_path():
    """The server resolves ``sys._MEIPASS/web/static/index.html`` frozen."""
    recipe = SPEC.read_text(encoding="utf-8")

    assert "(str(project_root / 'src' / 'web' / 'static'), 'web/static')" in recipe
