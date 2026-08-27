"""The web-only launcher, including the frozen branch before Typer imports."""

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
import typer

import cosine_companion as entrypoint


ENTRYPOINT = Path(__file__).resolve().parents[1] / "src" / "cosine_companion.py"


FROZEN_PROBE = r"""
import json
import os
import runpy
import subprocess
import sys
import types

events = []

web_package = types.ModuleType("web")
web_package.__path__ = []
web_host = types.ModuleType("web.host")

def run_web_ui(*, data_dir=None, debug=False):
    events.append(["web", str(data_dir) if data_dir is not None else None, debug])
    if os.environ.get("WEB_FAILURE"):
        raise RuntimeError(os.environ["WEB_FAILURE"])

web_host.run_web_ui = run_web_ui
sys.modules["web"] = web_package
sys.modules["web.host"] = web_host

def native_dialog(command, **options):
    events.append(["dialog", command[3], command[4], command[2]])

subprocess.run = native_dialog

sys.frozen = True
sys.platform = "darwin"
sys.argv = json.loads(os.environ["FROZEN_ARGV"])
# A PyInstaller --windowed launch has no terminal for the diagnostic.
sys.stderr = None

try:
    runpy.run_path(os.environ["ENTRYPOINT"], run_name="__main__")
except SystemExit as stopped:
    events.append(["exit", stopped.code])
except BaseException as error:
    events.append(["raised", type(error).__name__, str(error)])

print(json.dumps(events))
"""


def _run_frozen(argv, *, web_failure=None, data_dir=None):
    environment = os.environ.copy()
    environment.update(
        {
            "ENTRYPOINT": str(ENTRYPOINT),
            "FROZEN_ARGV": json.dumps(argv),
        }
    )
    if web_failure is not None:
        environment["WEB_FAILURE"] = web_failure
    if data_dir is not None:
        environment["COSINE_COMPANION_DATA_DIR"] = data_dir
    else:
        environment.pop("COSINE_COMPANION_DATA_DIR", None)

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


def test_frozen_web_failure_shows_native_error_before_nonzero_exit():
    events = _run_frozen(
        ["Cosine Companion"], web_failure="WKWebView unavailable"
    )

    assert [event[0] for event in events] == ["web", "dialog", "exit"]
    assert events[-1] == ["exit", 1]
    assert events[1][1] == "Cosine Companion could not start"
    assert "WKWebView unavailable" in events[1][2]
    assert "as critical" in events[1][3]


def test_frozen_finder_launch_can_use_an_isolated_data_directory():
    """Release smoke tests need not read or write the user's live library."""
    assert _run_frozen(
        ["Cosine Companion"], data_dir="/tmp/cosine-release-smoke"
    ) == [
        ["web", "/tmp/cosine-release-smoke", False],
        ["exit", 0],
    ]


def test_web_system_exit_is_reported_then_propagates(monkeypatch, capsys):
    """A dependency's sys.exit is a startup failure, not a close request."""
    calls = []

    def stop_web(**options):
        calls.append(options)
        raise SystemExit("webview stopped during startup")

    monkeypatch.setattr(entrypoint, "_run_web_frontend", stop_web)
    monkeypatch.setattr(entrypoint, "_is_frozen_gui_launch", lambda: False)

    with pytest.raises(SystemExit, match="webview stopped during startup"):
        entrypoint._run_default_frontend(debug=True, data_dir="/tmp/library")

    assert calls == [{"debug": True, "data_dir": "/tmp/library"}]
    assert "SystemExit: webview stopped during startup" in capsys.readouterr().err


def test_keyboard_interrupt_propagates_without_becoming_a_startup_error(
    monkeypatch,
    capsys,
):
    """Ctrl-C remains an explicit request to quit."""
    calls = []
    dialogs = []

    def interrupt_web(**options):
        calls.append(options)
        raise KeyboardInterrupt

    monkeypatch.setattr(entrypoint, "_run_web_frontend", interrupt_web)
    monkeypatch.setattr(entrypoint, "_is_frozen_gui_launch", lambda: True)
    monkeypatch.setattr(
        entrypoint,
        "_native_launch_dialog",
        lambda *arguments: dialogs.append(arguments),
    )

    with pytest.raises(KeyboardInterrupt):
        entrypoint._run_default_frontend(debug=False, data_dir=None)

    assert calls == [{"debug": False, "data_dir": None}]
    assert capsys.readouterr().err == ""
    assert dialogs == []


def test_macos_native_error_uses_osascript_without_a_gui_toolkit(monkeypatch):
    calls = []
    monkeypatch.setattr(entrypoint.sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **options: calls.append((command, options)),
    )

    entrypoint._native_launch_dialog("Could not start", "Web UI failed")

    assert len(calls) == 1
    command, options = calls[0]
    assert command[0:2] == ["/usr/bin/osascript", "-e"]
    assert "as critical" in command[2]
    assert command[3:] == ["Could not start", "Web UI failed"]
    assert options["check"] is True
    assert options["timeout"] == 30


def test_windows_native_error_uses_message_box(monkeypatch):
    calls = []
    fake_user32 = types.SimpleNamespace(
        MessageBoxW=lambda *arguments: calls.append(arguments)
    )
    monkeypatch.setattr(entrypoint.sys, "platform", "win32")
    monkeypatch.setattr(
        __import__("ctypes"),
        "windll",
        types.SimpleNamespace(user32=fake_user32),
        raising=False,
    )

    entrypoint._native_launch_dialog("Could not start", "Web UI failed")

    assert calls == [(None, "Web UI failed", "Could not start", 0x10)]


def test_ui_command_runs_the_web_frontend(monkeypatch):
    calls = []
    monkeypatch.setattr(
        entrypoint,
        "_run_default_frontend",
        lambda **options: calls.append(options),
    )

    entrypoint.ui(debug=True, data_dir="/tmp/library")

    assert calls == [{"debug": True, "data_dir": "/tmp/library"}]


@pytest.mark.parametrize("command", [entrypoint.ui, entrypoint.ui_web])
def test_both_ui_commands_turn_startup_failure_into_a_clean_cli_error(
    monkeypatch, capsys, command
):
    def fail_web(**options):
        raise OSError("cannot bind loopback")

    monkeypatch.setattr(entrypoint, "_run_web_frontend", fail_web)

    with pytest.raises(typer.Exit) as stopped:
        command(debug=False, data_dir=None)

    assert stopped.value.exit_code == 1
    assert "OSError: cannot bind loopback" in capsys.readouterr().err


def test_ui_turns_system_exit_into_a_clean_cli_error(monkeypatch, capsys):
    def stop_web(**options):
        raise SystemExit("webview stopped during startup")

    monkeypatch.setattr(entrypoint, "_run_web_frontend", stop_web)

    with pytest.raises(typer.Exit) as stopped:
        entrypoint.ui(debug=False, data_dir=None)

    assert stopped.value.exit_code == 1
    assert "SystemExit: webview stopped during startup" in capsys.readouterr().err


def test_missing_pywebview_error_includes_install_hint(monkeypatch, capsys):
    def missing_webview(**options):
        raise ImportError("No module named webview")

    monkeypatch.setattr(entrypoint, "_run_web_frontend", missing_webview)

    with pytest.raises(typer.Exit):
        entrypoint.ui(debug=False, data_dir=None)

    assert "pip install pywebview" in capsys.readouterr().err
