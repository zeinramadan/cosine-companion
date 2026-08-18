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
"""

from dataclasses import dataclass
from typing import Callable, Optional

from processing.pipeline import index_library


@dataclass
class ProgressEvent:
    """One unit of indexing progress."""

    phase: str
    current: int
    total: int
    message: str


@dataclass
class IndexResult:
    """Outcome of an indexing run."""

    total_tracks_indexed: int = 0
    new_tracks_added: int = 0
    up_to_date: bool = False


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

        if summary is None:
            # Nothing new to process, or nothing embeddable.
            return IndexResult(up_to_date=True)

        return IndexResult(
            total_tracks_indexed=summary["total_tracks_indexed"],
            new_tracks_added=summary["new_tracks_added"],
        )
