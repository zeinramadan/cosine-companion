"""Where the frontend lives, in development and inside a frozen bundle.

This is the single most likely way the web UI passes every test locally and
then ships a blank window: PyInstaller puts ``--add-data`` payloads somewhere
other than the source tree, and under PyInstaller 6.x onedir on macOS that
somewhere is ``Contents/Frameworks``, not ``Contents/Resources``
(spec §4.3). ``sys._MEIPASS`` is the only supported way to find them, so the
resolution order is pinned here rather than discovered after a build.
"""

import sys

import pytest

from web import assets


def test_the_development_static_directory_is_the_one_next_to_the_module():
    """Unfrozen, the assets sit beside ``assets.py`` in the source tree."""
    resolved = assets.static_dir()

    assert resolved.is_dir()
    assert resolved == (assets.MODULE_DIR / "static").resolve()
    assert (resolved / "index.html").is_file()


def test_a_frozen_build_resolves_through_meipass(tmp_path, monkeypatch):
    """Frozen, ``sys._MEIPASS/web/static`` wins over the source tree."""
    bundled = tmp_path / "web" / "static"
    bundled.mkdir(parents=True)
    (bundled / "index.html").write_text("<!doctype html>", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert assets.static_dir() == bundled.resolve()


def test_a_frozen_build_whose_payload_is_missing_says_where_it_looked(
    tmp_path, monkeypatch
):
    """A blank window is a terrible diagnostic. The error names both candidates.

    ``_MEIPASS`` points at an empty directory here, and the development
    fallback is redirected to a directory that does not exist either, so
    neither candidate resolves.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(assets, "MODULE_DIR", tmp_path / "absent")

    with pytest.raises(FileNotFoundError) as caught:
        assets.static_dir()

    message = str(caught.value)
    assert str(tmp_path / "web" / "static") in message
    assert str(tmp_path / "absent" / "static") in message


def test_an_unfrozen_interpreter_ignores_a_stray_meipass(tmp_path, monkeypatch):
    """``sys.frozen`` is the switch; ``_MEIPASS`` alone must not divert us.

    ``config/paths.py`` treats a bare ``_MEIPASS`` as frozen too, so the two
    modules disagree deliberately: here a stray attribute in a developer's
    session must not send asset resolution into a temp directory.
    """
    bundled = tmp_path / "web" / "static"
    bundled.mkdir(parents=True)
    (bundled / "index.html").write_text("<!doctype html>", encoding="utf-8")

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert assets.static_dir() == (assets.MODULE_DIR / "static").resolve()


def test_the_index_page_is_the_advertised_entry_point():
    """``server.py`` serves ``/`` from this file; ``host.py`` opens that URL."""
    assert (assets.static_dir() / "index.html").read_text(encoding="utf-8").strip()
