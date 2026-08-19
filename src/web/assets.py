#!/usr/bin/env python3
"""Locating the static front end, in a source checkout and in a frozen bundle.

The frontend has no build step, so "the assets" is literally the ``static/``
directory next to this file. Under PyInstaller that directory is copied into
the bundle by an ``--add-data`` entry and has to be found through
``sys._MEIPASS`` instead: on macOS with PyInstaller 6.x onedir the payload
lands in ``Contents/Frameworks``, *not* ``Contents/Resources``, so hard-coding
a bundle-relative path is how this breaks (spec §4.3).

Resolution order, pinned by tests/web/test_assets.py:

1. ``sys._MEIPASS / "web" / "static"`` when ``sys.frozen`` is set;
2. ``<this directory> / "static"``.

The switch is ``sys.frozen``, not the presence of ``_MEIPASS``. ``config/paths``
accepts either, because it is choosing a *writable* directory and erring
towards the user's Application Support folder is harmless. Here the cost of a
false positive is a blank window, so the stricter signal is used.
"""

import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent

STATIC_DIR_NAME = "static"

#: The file whose presence proves a candidate directory really holds the UI.
ENTRY_POINT = "index.html"


def _candidates():
    """Every directory that could hold the front end, best first."""
    found = []
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        found.append(Path(meipass) / "web" / STATIC_DIR_NAME)
    found.append(MODULE_DIR / STATIC_DIR_NAME)
    return found


def static_dir() -> Path:
    """Return the directory containing ``index.html``.

    Raises:
        FileNotFoundError: naming every directory that was tried. A blank
            window is an unreadable diagnostic; the paths are the diagnosis.
    """
    tried = _candidates()
    for candidate in tried:
        if (candidate / ENTRY_POINT).is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "the web front end is missing: no "
        f"{ENTRY_POINT} found in any of "
        + ", ".join(str(path) for path in tried)
    )
