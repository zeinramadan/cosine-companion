#!/usr/bin/env python3
"""ExportService - M3U playlist writing.

**Orchestration, not reimplementation.** The two export loops live where they
always did, in ``recommendations.playlist_exporter``; this service captures a
library snapshot, supplies the progress and cancellation plumbing, calls them
and adapts their stats dict into an ``ExportResult``. An earlier draft copied
both loops - the ranking, the statistics, the cancellation points, the filename
sanitisation and the error handling - and delegated only the final M3U write,
which left the originals in the source but unreachable and consolidated the
ranking policy in the service instead of at its source. That is undone: the
policy is in ``recommendations.ranking`` and the loops have exactly one
implementation each.

**One snapshot per run.** ``export_per_seed`` and ``export_combined`` call
``LibrarySession.snapshot()`` once at entry and pass that single view all the
way through ranking and writing. The first draft read ``self.library``'s live
properties per seed, during recommendation conversion, and again while writing,
so a concurrent deletion could switch snapshots mid-export - even between the
three arguments of one ``recommend_for`` call. The legacy worker captured
``meta_ix``/``emb_ix``/``idx`` once at export start, and so does this.

This does not repair the export/delete race (inventory defect #1); a delete
during an export still leaves the run finishing against a stale view, with no
warning. It restores the legacy failure mode instead of a worse one.

Preserved quirks, each pinned by a test:

* Tracks whose ``path_local`` is empty or does not exist on disk are silently
  skipped - not written, not counted, no warning (46 of the real library's
  1,307 tracks are in this state).
* Combined mode reports **no** ``playlists_created`` key, which is why
  ``export_complete`` raises ``KeyError`` and shows no completion dialog
  (inventory defect #10). ``ExportResult.as_legacy_stats()`` reproduces the
  exact per-mode dict shape so that defect survives the extraction.
* Combined mode does not create its output directory.

Signature notes. The plan's sketch omitted ``recommendations_per_track``, which
the tab supplies from a combo box; it is a required argument here. The sketch
also listed ``ExploreSession`` as a collaborator, because at the time the
ranking policy was to live there; now that it lives in the pure layer the
service needs only the library, so that parameter is gone. The ``cancel``
parameter is plumbing for PR 3 - the Tkinter tab has no cancel control and
passes ``None``, so it changes nothing user-visible today.

This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from recommendations.playlist_exporter import (
    export_recommendations_as_playlists,
    export_single_playlist,
)

ProgressCallback = Callable[[int, int, str], None]

COMBINED_PLAYLIST_NAME = "Cosine Recommendations"


@dataclass
class ExportResult:
    """Outcome of an export run."""

    total_tracks: int
    successful: int = 0
    failed: int = 0
    total_recommendations: int = 0
    playlists_created: Optional[int] = None  # None in combined mode
    cancelled: bool = False

    @classmethod
    def from_stats(cls, stats: Dict[str, Any], cancelled: bool = False) -> "ExportResult":
        """Adapt an exporter's stats dict. A missing key stays missing."""
        return cls(
            total_tracks=stats["total_tracks"],
            successful=stats["successful"],
            failed=stats["failed"],
            total_recommendations=stats["total_recommendations"],
            playlists_created=stats.get("playlists_created"),
            cancelled=cancelled,
        )

    def as_legacy_stats(self) -> Dict[str, Any]:
        """Reproduce the exact stats dict the tab consumes, per mode.

        ``playlists_created`` is omitted in combined mode, preserving the
        ``KeyError`` in ``export_complete`` (inventory defect #10).
        """
        stats: Dict[str, Any] = {
            "total_tracks": self.total_tracks,
            "successful": self.successful,
            "failed": self.failed,
        }
        if self.playlists_created is not None:
            stats["playlists_created"] = self.playlists_created
        stats["total_recommendations"] = self.total_recommendations
        return stats


def _cancel_check(cancel):
    return cancel.is_set if cancel is not None else None


def _was_cancelled(cancel) -> bool:
    """Whether the run stopped early.

    Read from the event rather than returned by the exporters, so their stats
    dict keeps the exact shape the Tkinter tab consumes.
    """
    return cancel is not None and cancel.is_set()


class ExportService:
    """Writes recommendation playlists as .m3u files."""

    def __init__(self, library):
        """Bind to a LibrarySession. Snapshots are taken per export, not here."""
        self.library = library

    def export_per_seed(
        self,
        track_ids: List[str],
        out_dir: str,
        recommendations_per_track: int,
        progress: Optional[ProgressCallback] = None,
        cancel=None,
    ) -> ExportResult:
        """Write one playlist per seed track into ``out_dir``."""
        library = self.library.snapshot()

        stats = export_recommendations_as_playlists(
            track_ids,
            out_dir,
            recommendations_per_track,
            library.meta_ix,
            library.emb_ix,
            library.index,
            progress_callback=progress,
            cancel_check=_cancel_check(cancel),
        )

        return ExportResult.from_stats(stats, cancelled=_was_cancelled(cancel))

    def export_combined(
        self,
        track_ids: List[str],
        out_path: str,
        recommendations_per_track: int,
        progress: Optional[ProgressCallback] = None,
        cancel=None,
    ) -> ExportResult:
        """Write every seed's recommendations into one de-duplicated playlist."""
        library = self.library.snapshot()

        stats = export_single_playlist(
            track_ids,
            out_path,
            COMBINED_PLAYLIST_NAME,
            library.meta_ix,
            library.emb_ix,
            library.index,
            recommendations_per_track,
            progress_callback=progress,
            cancel_check=_cancel_check(cancel),
        )

        return ExportResult.from_stats(stats, cancelled=_was_cancelled(cancel))
