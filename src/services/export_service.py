#!/usr/bin/env python3
"""ExportService - M3U playlist writing.

Replaces the two entry points ``ui/playlist_export_tab.py`` called directly,
``recommendations.playlist_exporter.export_recommendations_as_playlists`` and
``export_single_playlist``. Those functions are deliberately LEFT IN PLACE and
untouched: they are no longer reachable from the UI, but
``tests/services/test_export_service.py`` diffs this service's output against
them byte-for-byte, which makes them a permanent regression oracle.

Ranking comes from ExploreSession, so the policy exists once rather than three
times. File writing still delegates to
``recommendations.playlist_exporter.create_m3u_playlist``, so the M3U bytes are
produced by exactly the same code as before.

Preserved quirks, each pinned by a test:

* Tracks whose ``path_local`` is empty or does not exist on disk are silently
  skipped - not written, not counted, no warning (46 of the real library's
  1,307 tracks are in this state).
* Combined mode reports **no** ``playlists_created`` key, which is why
  ``export_complete`` raises ``KeyError`` and shows no completion dialog
  (inventory defect #10). ``ExportResult.as_legacy_stats()`` reproduces the
  exact per-mode dict shape so that defect survives the extraction.
* Combined mode does not create its output directory.

Signature note: the plan's sketch omitted ``recommendations_per_track``, which
the tab supplies from a combo box; it is a required argument here. The
``cancel`` parameter is plumbing for PR 3 - the Tkinter tab has no cancel
control and passes ``None``, so it changes nothing user-visible today.

This module must never import tkinter or any UI module.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from recommendations.playlist_exporter import create_m3u_playlist

ProgressCallback = Callable[[int, int, str], None]

TOPK = 500
FINAL_TOP = 200


@dataclass
class ExportResult:
    """Outcome of an export run."""

    total_tracks: int
    successful: int = 0
    failed: int = 0
    total_recommendations: int = 0
    playlists_created: Optional[int] = None  # None in combined mode
    cancelled: bool = False

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


class ExportService:
    """Writes recommendation playlists as .m3u files."""

    def __init__(self, library, explore):
        """Bind to a LibrarySession and the ExploreSession that ranks for it."""
        self.library = library
        self.explore = explore

    def export_per_seed(
        self,
        track_ids: List[str],
        out_dir: str,
        recommendations_per_track: int,
        progress: Optional[ProgressCallback] = None,
        cancel=None,
    ) -> ExportResult:
        """Write one playlist per seed track into ``out_dir``."""
        output_path = Path(out_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        result = ExportResult(total_tracks=len(track_ids), playlists_created=0)

        for i, track_id in enumerate(track_ids, 1):
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                break

            track = self.library.get_track(track_id)
            if track is None:
                result.failed += 1
                continue

            artist = track.get("artist", "Unknown Artist")
            title = track.get("title", "Unknown Title")

            if progress:
                progress(i, len(track_ids), f"{artist} - {title}")

            recommendations = self._recommend(track_id, recommendations_per_track)
            if not recommendations:
                result.failed += 1
                continue

            playlist_path = output_path / self._playlist_filename(artist, title)
            rec_track_ids = [rec.track_id for rec in recommendations]

            try:
                create_m3u_playlist(rec_track_ids, str(playlist_path), self.library.meta_ix)
                result.successful += 1
                result.playlists_created += 1
                result.total_recommendations += len(rec_track_ids)
            except Exception as e:
                print(f"Failed to create playlist for {artist} - {title}: {e}")
                result.failed += 1

        return result

    def export_combined(
        self,
        track_ids: List[str],
        out_path: str,
        recommendations_per_track: int,
        progress: Optional[ProgressCallback] = None,
        cancel=None,
    ) -> ExportResult:
        """Write every seed's recommendations into one de-duplicated playlist."""
        result = ExportResult(total_tracks=len(track_ids))
        all_recommendations: List[str] = []
        seen_tracks = set()

        for i, track_id in enumerate(track_ids, 1):
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                break

            track = self.library.get_track(track_id)
            if track is None:
                result.failed += 1
                continue

            if progress:
                progress(
                    i,
                    len(track_ids),
                    f"{track.get('artist', 'Unknown Artist')} - {track.get('title', 'Unknown Title')}",
                )

            recommendations = self._recommend(track_id, recommendations_per_track)
            if not recommendations:
                result.failed += 1
                continue

            result.successful += 1

            for rec in recommendations:
                if rec.track_id not in seen_tracks:
                    all_recommendations.append(rec.track_id)
                    seen_tracks.add(rec.track_id)

        # The legacy function wrote nothing at all when it collected no ids, and
        # never created the output directory.
        if all_recommendations:
            create_m3u_playlist(all_recommendations, out_path, self.library.meta_ix)
            result.total_recommendations = len(all_recommendations)

        return result

    def _recommend(self, track_id: str, per_track: int):
        """Rank with the shared policy, then truncate to the user's count."""
        return self.explore.recommend(track_id, topk=TOPK, final_top=FINAL_TOP)[:per_track]

    @staticmethod
    def _playlist_filename(artist: str, title: str) -> str:
        """{safe_artist} - {safe_title}.m3u, truncated to 204 characters."""
        safe_artist = "".join(c for c in artist if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{safe_artist} - {safe_title}.m3u"

        # Limit filename length
        if len(filename) > 200:
            filename = filename[:200] + ".m3u"
        return filename
