"""Headless service layer for Cosine Companion.

Every module in this package is UI-free by construction: nothing here may import
tkinter or any module under ``src/ui/``. ``tests/test_services_are_ui_free.py``
enforces that with an AST walk.

Services *orchestrate*. The pure layers - ``src/core/``, ``src/processing/`` and
``src/recommendations/`` - are called, never reimplemented.
"""

from services.explore_session import ExploreSession, Recommendation
from services.export_service import ExportResult, ExportService
from services.library_session import LibrarySession
from services.set_builder import SetBuilder
from services.settings_store import SettingsStore

__all__ = [
    'ExploreSession',
    'ExportResult',
    'ExportService',
    'LibrarySession',
    'Recommendation',
    'SetBuilder',
    'SettingsStore',
]
