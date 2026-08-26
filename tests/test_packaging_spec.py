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


def _unconditional_list_items(node):
    if isinstance(node, ast.List):
        return node.elts
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (
            _unconditional_list_items(node.left)
            + _unconditional_list_items(node.right)
        )
    return []


def test_the_frozen_package_ships_the_web_frontend_at_its_runtime_path():
    """The server resolves ``sys._MEIPASS/web/static/index.html`` frozen."""
    analysis = _call("Analysis")
    analysis_keywords = {
        keyword.arg: keyword.value for keyword in analysis.keywords
    }
    datas = _unconditional_list_items(analysis_keywords["datas"])
    expected = ast.parse(
        "(str(project_root / 'src' / 'web' / 'static'), 'web/static')",
        mode="eval",
    ).body

    assert ast.dump(expected) in {ast.dump(item) for item in datas}


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


def test_macos_minimum_matches_the_locked_binary_floor():
    bundle = _call("BUNDLE")
    bundle_keywords = {keyword.arg: keyword.value for keyword in bundle.keywords}
    info_plist = ast.literal_eval(bundle_keywords["info_plist"])

    assert info_plist["LSMinimumSystemVersion"] == "15.2"


def _hidden_imports():
    """Every module name the spec names outright in ``hiddenimports``.

    The literal entries only. The ``+ collect_submodules(...)`` tails are
    resolved against whatever the build machine has installed, so what they
    contribute is a property of that machine and not of this recipe.
    """
    analysis = _call("Analysis")
    analysis_keywords = {
        keyword.arg: keyword.value for keyword in analysis.keywords
    }
    return {
        item.value
        for item in _unconditional_list_items(analysis_keywords["hiddenimports"])
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }


def test_the_frozen_package_declares_the_web_ui_it_has_to_import():
    """``ui-web`` is reached by a function-body import inside a try/except.

    PyInstaller's modulegraph does follow that edge today, so a build can be
    green while nothing in the recipe says the bundle carries a second front
    end - and the next refactor of that import site takes the web UI with it
    silently.

    ``webview`` is spelled as the IMPORT name on purpose: the distribution is
    ``pywebview`` (requirements.txt), and a hiddenimports entry saying
    ``pywebview`` collects nothing while looking exactly like coverage.
    """
    declared = _hidden_imports()

    required = {
        "webview",
        "webview.platforms.cocoa",
        "web",
        "web.assets",
        "web.host",
        "web.api",
        "web.server",
        "web.jobs",
    }
    missing = required - declared
    assert not missing, "the spec does not declare " + ", ".join(sorted(missing))

    assert "pywebview" not in declared, (
        "'pywebview' is the distribution name; the importable module is "
        "'webview'. PyInstaller resolves hiddenimports as import names, so "
        "this entry would collect nothing and only warn."
    )


def test_the_frozen_package_still_declares_the_tkinter_front_end():
    """Tkinter is still what a no-argument frozen launch opens.

    ``cosine_companion.py`` short-circuits to ``ui.run_ui`` before Typer when
    frozen with no arguments, so shipping the web UI must not cost the default
    one. Nothing else in this file mentions ``ui`` or ``tkinter``, which is how
    they could be dropped in a teardown PR without a single test going red.
    """
    declared = _hidden_imports()

    required = {"ui", "ui.app", "tkinter", "PIL.ImageTk"}
    missing = required - declared
    assert not missing, "the spec does not declare " + ", ".join(sorted(missing))
