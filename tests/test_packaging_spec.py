"""Contracts for the PyInstaller package shape.

These tests inspect the spec rather than importing it: importing a spec starts
PyInstaller collection against the current interpreter, which is both slow and
incapable of proving what the declarative package recipe says.
"""

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = PROJECT_ROOT / "cosine-companion.spec"


def _recipe():
    return SPEC.read_text(encoding="utf-8")


def _call(name):
    calls = [
        node
        for node in ast.walk(ast.parse(_recipe()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]
    assert len(calls) == 1, f"expected one {name} call, found {len(calls)}"
    return calls[0]


def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    return None


def test_the_frozen_package_ships_the_web_frontend_at_its_runtime_path():
    """The server resolves ``sys._MEIPASS/web/static/index.html`` frozen."""
    recipe = _recipe()

    assert "(str(project_root / 'src' / 'web' / 'static'), 'web/static')" in recipe


def test_macos_is_an_onedir_bundle_not_a_self_extracting_onefile():
    exe = _call("EXE")
    collect = _call("COLLECT")
    bundle = _call("BUNDLE")

    exe_keywords = {keyword.arg: keyword.value for keyword in exe.keywords}
    assert ast.literal_eval(exe_keywords["exclude_binaries"]) is True
    assert "a.binaries" not in {_dotted_name(arg) for arg in exe.args}
    assert "a.zipfiles" not in {_dotted_name(arg) for arg in exe.args}
    assert "a.datas" not in {_dotted_name(arg) for arg in exe.args}

    assert [_dotted_name(arg) for arg in collect.args[:4]] == [
        "exe",
        "a.binaries",
        "a.zipfiles",
        "a.datas",
    ]
    assert _dotted_name(bundle.args[0]) == "coll"
