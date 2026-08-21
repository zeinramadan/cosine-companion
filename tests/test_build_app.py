"""The build wrapper must package with the interpreter it validates."""

import sys
from types import SimpleNamespace

import build_app


def test_pyinstaller_runs_from_the_current_interpreter(monkeypatch):
    commands = []

    def completed(command):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(build_app.subprocess, "run", completed)
    monkeypatch.setattr(build_app.platform, "system", lambda: "Darwin")

    build_app.build_with_pyinstaller()

    assert commands == [
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "cosine-companion.spec",
        ]
    ]
