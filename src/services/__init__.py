"""Headless service layer for Cosine Companion.

Every module in this package is UI-free by construction: nothing here may import
tkinter or any module under ``src/ui/``. ``tests/test_services_are_ui_free.py``
enforces that with an AST walk.

Services *orchestrate*. The pure layers - ``src/core/``, ``src/processing/`` and
``src/recommendations/`` - are called, never reimplemented.
"""

from services.explore_session import ExploreSession, Recommendation
from services.export_service import ExportResult, ExportService
from services.indexing_service import (
    STATUS_INDEXED,
    STATUS_NO_EMBEDDINGS,
    STATUS_UP_TO_DATE,
    IndexingService,
    IndexResult,
    ProgressEvent,
)
from services.library_session import LibrarySession, LibrarySnapshot
from services.playlist_import import PlaylistImportSummary, import_playlists
from services.playlist_service import (
    IMPORT_COMMAND,
    PlaylistLookup,
    PlaylistRef,
    PlaylistService,
    StalenessVerdict,
)
from services.set_builder import SetBuilder
from services.settings_store import SettingsStore

__all__ = [
    'IMPORT_COMMAND',
    'STATUS_INDEXED',
    'STATUS_NO_EMBEDDINGS',
    'STATUS_UP_TO_DATE',
    'ExploreSession',
    'ExportResult',
    'ExportService',
    'IndexResult',
    'IndexingService',
    'LibrarySession',
    'LibrarySnapshot',
    'PlaylistImportSummary',
    'PlaylistLookup',
    'PlaylistRef',
    'PlaylistService',
    'ProgressEvent',
    'Recommendation',
    'SetBuilder',
    'SettingsStore',
    'StalenessVerdict',
    'import_playlists',
]
