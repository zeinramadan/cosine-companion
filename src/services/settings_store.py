#!/usr/bin/env python3
"""Settings persistence, extracted from the Tkinter UI.

Replaces the hand-rolled settings.json I/O previously repeated at seven sites
across ``ui/onboarding.py``, ``ui/app.py`` and ``ui/settings_window.py``.

Behaviour is preserved exactly, including the two quirks:

* A **missing** file reads as an empty document. Every original site guarded on
  ``Path.exists()`` and took a "not configured" branch.
* A **corrupt** file raises ``json.JSONDecodeError``. No original site wrapped
  ``json.load`` in a ``try``, so the error propagated - out of
  ``needs_onboarding()`` that crashes startup before any window is shown. That
  is a known defect (spec 3.2); it is characterised here, not fixed.

``set()`` merges into the existing document (matching
``SettingsWindow.change_xml_path``) while ``replace()`` overwrites it wholesale
(matching ``OnboardingWindow.save_settings``). Both are kept so each call site
retains its exact semantics.

This module must never import tkinter or any UI module.
"""

import json
from pathlib import Path
from typing import Any, Dict, Union

XML_PATH_KEY = "xml_path"
FIRST_RUN_COMPLETE_KEY = "first_run_complete"


class SettingsStore:
    """Read/write access to the application's settings.json document."""

    def __init__(self, path: Union[str, Path]):
        """Bind the store to ``path``. The file need not exist yet."""
        self.path = Path(path)

    def all(self) -> Dict[str, Any]:
        """Return the whole document, or ``{}`` when the file does not exist.

        Raises ``json.JSONDecodeError`` for an unparseable file, as the original
        call sites did.
        """
        if not self.path.exists():
            return {}
        with open(self.path, "r") as f:
            return json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """Return ``key``'s value, or ``default`` when it is absent."""
        return self.all().get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Merge ``key`` into the document and persist immediately."""
        settings = self.all()
        settings[key] = value
        self._write(settings)

    def replace(self, settings: Dict[str, Any]) -> None:
        """Overwrite the whole document and persist immediately."""
        self._write(dict(settings))

    @property
    def xml_path(self) -> Any:
        """The configured Rekordbox XML path, or ``None``. The only key in use."""
        return self.get(XML_PATH_KEY)

    def _write(self, settings: Dict[str, Any]) -> None:
        with open(self.path, "w") as f:
            json.dump(settings, f, indent=2)
