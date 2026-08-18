#!/usr/bin/env python3
"""IndexingService - the indexing pipeline with structured progress events.

This is the ONE place in PR 2 where a mechanism changes, and the plan sanctions
it explicitly. Progress used to be reported by replacing the process-global
``sys.stdout`` with a queue writer from a worker thread
(``ui/reindex_window.py:164-194`` and ``ui/onboarding.py:400-416``). It is now a
structured callback.

The constraint attached to that permission is that the UI must display the same
information as before, so every one of the 37 print sites reachable during
indexing - across ``processing/pipeline.py``, ``core/loader.py`` and
``core/deleted_tracks.py`` - emits an event carrying the IDENTICAL string, in
the same order. The CLI is untouched: with no callback those functions still
print exactly as they did.

Two behaviours are preserved rather than improved:

* Cancellation raises ``KeyboardInterrupt``. That derives from
  ``BaseException``, so ``reindex_window``'s ``except Exception`` does not catch
  it: the worker thread dies unhandled, no completion message is queued, and the
  "Indexing cancelled by user" log line is never appended. The window still
  shows the cancelled state because the Cancel button set the flag. Subtle, and
  pinned by a test.
* A cancelled run discards every embedding computed so far (spec 3.2).

``ProgressEvent`` carries real ``current``/``total`` for the embedding phase -
the pipeline always knew ``i/N`` and simply never reported it. Making the
progress bar determinate with it is PR 3 work.

This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.

It must also never pull Essentia in at import time. ``processing.pipeline`` is
imported inside :meth:`IndexingService.run`, not at module scope, because
``processing/__init__.py`` re-exports ``DiscogsEffnetEmbedder`` and that module
does ``import essentia.standard``. A module-level import here would drag a
483 MB TensorFlow dependency into every consumer of the service layer - even
``services.settings_store``, a 72-line JSON reader - and would break both the
CI job (which installs only numpy/pandas/pyarrow/pytest) and PR 3's web server.
``tests/test_services_are_lightweight.py`` enforces that.
"""

from dataclasses import dataclass
from typing import Callable, Optional

# Mirrored from processing.pipeline so that importing this module stays free of
# Essentia. They are asserted equal to the pipeline's own constants by
# tests/services/test_indexing_service.py.
STATUS_INDEXED = "indexed"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_NO_EMBEDDINGS = "no_embeddings"


@dataclass
class ProgressEvent:
    """One unit of indexing progress."""

    phase: str
    current: int
    total: int
    message: str


@dataclass
class IndexResult:
    """Outcome of an indexing run.

    ``status`` distinguishes the pipeline's three terminal outcomes. The two
    empty ones used to be indistinguishable - both returned ``None`` from
    ``index_library`` and both surfaced here as ``up_to_date=True`` - so a run in
    which new tracks existed and *not one of them could be embedded* reported
    itself as a success. PR 3 consumes this API; it must be able to tell them
    apart.

    * ``indexed`` - work was done. ``total_tracks_indexed`` and
      ``new_tracks_added`` are meaningful.
    * ``up_to_date`` - no new tracks were found. Nothing to do; a success.
    * ``no_embeddings`` - ``new_tracks_found`` tracks were found and every one
      of them failed to embed (missing file, unsupported codec). A FAILURE.

    A cancelled run raises ``KeyboardInterrupt`` and produces no result at all.
    """

    status: str
    total_tracks_indexed: int = 0
    new_tracks_added: int = 0
    new_tracks_found: int = 0

    @property
    def up_to_date(self) -> bool:
        """True only for a genuinely up-to-date index, never for a failed run."""
        return self.status == STATUS_UP_TO_DATE

    @property
    def failed(self) -> bool:
        """True when new tracks were found and none of them could be embedded."""
        return self.status == STATUS_NO_EMBEDDINGS


ProgressCallback = Callable[[ProgressEvent], None]


class IndexingService:
    """Runs the indexing pipeline and reports progress as structured events."""

    def __init__(self, settings):
        """Bind to a SettingsStore, which holds the configured XML path."""
        self.settings = settings

    def run(
        self,
        xml_path: str,
        force_full: bool = False,
        progress: Optional[ProgressCallback] = None,
        cancel=None,
        sample_size: Optional[int] = None,
    ) -> IndexResult:
        """Index ``xml_path``, emitting a ProgressEvent for every pipeline message.

        Raises ``KeyboardInterrupt`` when ``cancel`` is set, exactly as the
        pipeline always has.
        """
        # Imported here, not at module scope: processing/__init__.py re-exports
        # DiscogsEffnetEmbedder, which does `import essentia.standard`. See the
        # module docstring - a top-level import makes every service, including
        # settings_store, require a 483 MB TensorFlow install.
        from processing.pipeline import index_library

        callback = None
        if progress is not None:
            def callback(phase, current, total, message):
                progress(ProgressEvent(phase=phase, current=current,
                                       total=total, message=message))

        summary = index_library(
            xml_path,
            force_full=force_full,
            sample_size=sample_size,
            cancel_check=(cancel.is_set if cancel is not None else None),
            progress=callback,
        )

        return IndexResult(
            status=summary["status"],
            total_tracks_indexed=summary.get("total_tracks_indexed", 0),
            new_tracks_added=summary.get("new_tracks_added", 0),
            new_tracks_found=summary.get("new_tracks_found", 0),
        )
