"""The frontend switch, including the frozen branch that runs before Typer."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import typer

import cosine_companion as entrypoint


ENTRYPOINT = Path(__file__).resolve().parents[1] / "src" / "cosine_companion.py"


FROZEN_PROBE = r"""
import json
import os
import runpy
import sys
import types

events = []

web_package = types.ModuleType("web")
web_package.__path__ = []
web_host = types.ModuleType("web.host")

def run_web_ui(*, data_dir=None, debug=False):
    events.append(["web", data_dir, debug])
    if os.environ.get("WEB_FAILURE"):
        raise RuntimeError(os.environ["WEB_FAILURE"])

web_host.run_web_ui = run_web_ui
sys.modules["web"] = web_package
sys.modules["web.host"] = web_host

classic_ui = types.ModuleType("ui")

def run_ui():
    events.append(["tk"])
    if os.environ.get("TK_FAILURE"):
        raise RuntimeError(os.environ["TK_FAILURE"])

classic_ui.run_ui = run_ui
sys.modules["ui"] = classic_ui

messagebox = types.SimpleNamespace(
    showwarning=lambda title, message: events.append(["warning", title, message]),
    showerror=lambda title, message: events.append(["error", title, message]),
)
tkinter = types.ModuleType("tkinter")
tkinter.messagebox = messagebox
sys.modules["tkinter"] = tkinter

sys.frozen = True
sys.platform = "darwin"
sys.argv = json.loads(os.environ["FROZEN_ARGV"])
# This is the relevant PyInstaller --windowed condition: there is no terminal
# on which a printed explanation can be relied upon.
sys.stderr = None

try:
    runpy.run_path(os.environ["ENTRYPOINT"], run_name="__main__")
except SystemExit as stopped:
    events.append(["exit", stopped.code])
except BaseException as error:
    events.append(["raised", type(error).__name__, str(error)])

print(json.dumps(events))
"""


def _run_frozen(argv, *, web_failure=None, tk_failure=None):
    environment = os.environ.copy()
    environment.update(
        {
            "ENTRYPOINT": str(ENTRYPOINT),
            "FROZEN_ARGV": json.dumps(argv),
        }
    )
    if web_failure is not None:
        environment["WEB_FAILURE"] = web_failure
    if tk_failure is not None:
        environment["TK_FAILURE"] = tk_failure

    result = subprocess.run(
        [sys.executable, "-c", FROZEN_PROBE],
        cwd=str(ENTRYPOINT.parent),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "argv",
    [
        ["Cosine Companion"],
        ["Cosine Companion", "-psn_0_12345"],
    ],
)
def test_frozen_finder_launch_uses_the_web_frontend(argv):
    """Both Finder argument shapes execute the real pre-Typer early branch."""
    assert _run_frozen(argv) == [["web", None, False], ["exit", 0]]


def test_frozen_web_failure_warns_before_opening_the_classic_fallback():
    events = _run_frozen(["Cosine Companion"], web_failure="WKWebView unavailable")

    assert [event[0] for event in events] == ["web", "warning", "tk", "exit"]
    assert "WKWebView unavailable" in events[1][2]
    assert "classic interface instead" in events[1][2]


def test_web_system_exit_opens_the_classic_fallback(monkeypatch, capsys):
    """A dependency's sys.exit is a startup failure, not a user cancellation."""
    calls = []

    def stop_web(**options):
        calls.append(("web", options))
        raise SystemExit("webview stopped during startup")

    monkeypatch.setattr(entrypoint, "_run_web_frontend", stop_web)
    monkeypatch.setattr(
        entrypoint,
        "_run_tk_frontend",
        lambda: calls.append(("tk", {})),
    )
    monkeypatch.setattr(entrypoint, "_is_frozen_gui_launch", lambda: False)

    entrypoint._run_default_frontend(debug=True, data_dir="/tmp/library")

    assert calls == [
        ("web", {"debug": True, "data_dir": "/tmp/library"}),
        ("tk", {}),
    ]
    assert "SystemExit: webview stopped during startup" in capsys.readouterr().err


def test_keyboard_interrupt_propagates_without_opening_the_classic_fallback(
    monkeypatch,
):
    """Ctrl-C means quit even though a library-originated SystemExit falls back."""
    calls = []

    def interrupt_web(**options):
        calls.append(("web", options))
        raise KeyboardInterrupt

    monkeypatch.setattr(entrypoint, "_run_web_frontend", interrupt_web)
    monkeypatch.setattr(
        entrypoint,
        "_run_tk_frontend",
        lambda: calls.append(("tk", {})),
    )

    with pytest.raises(KeyboardInterrupt):
        entrypoint._run_default_frontend(debug=False, data_dir=None)

    assert calls == [("web", {"debug": False, "data_dir": None})]


def test_frozen_double_failure_uses_a_native_fatal_dialog():
    events = _run_frozen(
        ["Cosine Companion"],
        web_failure="loopback bind failed",
        tk_failure="Tk failed",
    )

    assert [event[0] for event in events] == [
        "web",
        "warning",
        "tk",
        "error",
        "raised",
    ]
    assert "loopback bind failed" in events[3][2]
    assert "Tk failed" in events[3][2]


def test_tk_system_exit_reports_both_failures_then_propagates(monkeypatch):
    """A frozen launch must explain a Tk sys.exit before preserving its exit."""
    dialogs = []

    def fail_web(**options):
        raise RuntimeError("loopback bind failed")

    def stop_tk():
        raise SystemExit(9)

    monkeypatch.setattr(entrypoint, "_run_web_frontend", fail_web)
    monkeypatch.setattr(entrypoint, "_run_tk_frontend", stop_tk)
    monkeypatch.setattr(entrypoint, "_is_frozen_gui_launch", lambda: True)
    monkeypatch.setattr(
        entrypoint,
        "_native_launch_dialog",
        lambda title, message, **options: dialogs.append((title, message, options)),
    )

    with pytest.raises(SystemExit) as stopped:
        entrypoint._run_default_frontend()

    assert stopped.value.code == 9
    assert len(dialogs) == 2
    title, message, options = dialogs[-1]
    assert title == "Cosine Companion could not start"
    assert "RuntimeError: loopback bind failed" in message
    assert "SystemExit: 9" in message
    assert options == {"error": True}


def test_a_broken_tk_dialog_uses_the_macos_native_fallback(monkeypatch):
    calls = []

    broken_messagebox = type(
        "BrokenMessagebox",
        (),
        {
            "showwarning": staticmethod(
                lambda *args: (_ for _ in ()).throw(RuntimeError("Tcl failed"))
            ),
            "showerror": staticmethod(
                lambda *args: (_ for _ in ()).throw(RuntimeError("Tcl failed"))
            ),
        },
    )
    tkinter = type("Tkinter", (), {"messagebox": broken_messagebox})
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setattr(entrypoint.sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **options: calls.append((command, options)),
    )

    entrypoint._native_launch_dialog("Could not start", "Both UIs failed", error=True)

    assert len(calls) == 1
    command, options = calls[0]
    assert command[0:2] == ["/usr/bin/osascript", "-e"]
    assert "as critical" in command[2]
    assert command[3:] == ["Could not start", "Both UIs failed"]
    assert options["check"] is True


def test_ui_command_uses_the_web_default_and_ui_tk_is_direct(monkeypatch):
    calls = []
    monkeypatch.setattr(
        entrypoint,
        "_run_default_frontend",
        lambda **options: calls.append(("default", options)),
    )
    monkeypatch.setattr(
        entrypoint,
        "_run_tk_frontend",
        lambda: calls.append(("tk", {})),
    )
    monkeypatch.setattr(
        entrypoint,
        "_run_web_frontend",
        lambda **options: calls.append(("web", options)),
    )

    entrypoint.ui(debug=True, data_dir="/tmp/library")
    entrypoint.ui_tk()

    assert entrypoint.DEFAULT_FRONTEND == entrypoint.WEB_FRONTEND
    assert calls == [
        ("default", {"debug": True, "data_dir": "/tmp/library"}),
        ("tk", {}),
    ]


def test_ui_web_remains_a_strict_web_only_alias(monkeypatch, capsys):
    calls = []

    def fail_web(**options):
        calls.append(("web", options))
        raise OSError("cannot bind loopback")

    monkeypatch.setattr(entrypoint, "_run_web_frontend", fail_web)
    monkeypatch.setattr(
        entrypoint,
        "_run_tk_frontend",
        lambda: calls.append(("tk", {})),
    )

    with pytest.raises(typer.Exit) as stopped:
        entrypoint.ui_web(debug=False, data_dir=None)

    assert stopped.value.exit_code == 1
    assert calls == [("web", {"debug": False, "data_dir": None})]
    assert "cannot bind loopback" in capsys.readouterr().err


def test_ui_web_turns_system_exit_into_a_clean_cli_error(monkeypatch, capsys):
    def stop_web(**options):
        raise SystemExit("webview stopped during startup")

    monkeypatch.setattr(entrypoint, "_run_web_frontend", stop_web)

    with pytest.raises(typer.Exit) as stopped:
        entrypoint.ui_web(debug=False, data_dir=None)

    assert stopped.value.exit_code == 1
    assert "SystemExit: webview stopped during startup" in capsys.readouterr().err
