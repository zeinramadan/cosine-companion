#!/usr/bin/env python3
"""M3U playlist export functionality for recommendations.

These two exporters are the single implementation of the export loops.
``services.ExportService`` orchestrates them - it captures a library snapshot,
supplies the progress and cancellation plumbing and adapts the returned stats
dict into an ``ExportResult`` - but it does not reimplement them, and neither
function has a private copy of the ranking policy any more: both call
``recommendations.ranking.ranked_recommendations``.

``progress_callback`` and ``cancel_check`` are optional and default to ``None``,
which is what every pre-existing caller passes implicitly, so their behaviour is
unchanged.
"""

import os
import unicodedata
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
import pandas as pd

from core.index_builder import NumpyCosIndex
from recommendations.ranking import (
    RANKING_FINAL_TOP,
    RANKING_TOPK,
    ranked_recommendations,
)

# filename[:200] + ".m3u" yields a 204-CHARACTER name, cut mid-title. The legacy
# formula is preserved for ordinary names; collisions are handled at export time
# so a non-colliding seed keeps exactly the filename it had before.
#
# A DOUBLED ".m3u" is impossible, contrary to what this comment used to claim:
# sanitise_filename_part keeps only alphanumerics, space, hyphen and underscore,
# so the sole "." in the name is the extension itself - and it can only survive
# the [:200] slice if the name was already <= 200 characters, in which case the
# truncation branch never runs.
MAX_FILENAME_LENGTH = 200


def sanitise_filename_part(value: str) -> str:
    """Keep only alphanumerics, space, hyphen and underscore; strip the ends."""
    return "".join(c for c in value if c.isalnum() or c in (' ', '-', '_')).strip()


def playlist_filename(artist: str, title: str) -> str:
    """Return the legacy per-seed filename: ``{artist} - {title}.m3u``."""
    filename = f"{sanitise_filename_part(artist)} - {sanitise_filename_part(title)}.m3u"

    # Limit filename length
    if len(filename) > MAX_FILENAME_LENGTH:
        filename = filename[:MAX_FILENAME_LENGTH] + ".m3u"
    return filename


def _filename_collision_key(filename: str) -> str:
    """Return the key used to reserve a filename during one export run.

    APFS commonly compares names case-insensitively and normalises Unicode.
    Using the same conservative comparison here prevents two distinct strings
    from selecting one filesystem entry on those volumes.
    """
    return unicodedata.normalize('NFC', filename).casefold()


def _filename_with_track_id(filename: str, track_id: str, attempt: int) -> str:
    """Add a bounded discriminator while retaining the legacy length ceiling."""
    safe_track_id = sanitise_filename_part(str(track_id))[:64] or "unknown"
    marker = f" [ID {safe_track_id}]"
    if attempt > 1:
        marker = f" [ID {safe_track_id}-{attempt}]"

    extension = ".m3u"
    stem = filename[:-len(extension)] if filename.endswith(extension) else filename
    stem = stem[:max(0, MAX_FILENAME_LENGTH - len(marker))]
    return f"{stem}{marker}{extension}"


def _unique_playlist_path(
    output_path: Path,
    filename: str,
    track_id: str,
    reserved_filename_keys: Set[str],
) -> Path:
    """Choose this seed's path without changing a free legacy filename."""
    candidate = filename
    attempt = 1
    while _filename_collision_key(candidate) in reserved_filename_keys:
        candidate = _filename_with_track_id(filename, track_id, attempt)
        attempt += 1
    return output_path / candidate


def create_m3u_playlist(
    track_ids: List[str],
    output_path: str,
    meta_ix: pd.DataFrame,
    include_extended: bool = True
) -> None:
    """
    Create an M3U playlist file from a list of track IDs.

    Args:
        track_ids: List of track IDs to include in the playlist
        output_path: Path where the .m3u file should be saved
        meta_ix: Metadata DataFrame indexed by track_id
        include_extended: If True, uses extended M3U format with metadata
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        if include_extended:
            f.write("#EXTM3U\n")

        for track_id in track_ids:
            if track_id not in meta_ix.index:
                continue

            track = meta_ix.loc[track_id]
            path_local = track.get('path_local', '')

            if not path_local or not os.path.exists(path_local):
                continue

            if include_extended:
                artist = track.get('artist', 'Unknown Artist')
                title = track.get('title', 'Unknown Title')
                # Duration in seconds - we don't have this, so use -1
                f.write(f"#EXTINF:-1,{artist} - {title}\n")

            f.write(f"{path_local}\n")


def export_recommendations_as_playlists(
    track_ids: List[str],
    output_dir: str,
    recommendations_per_track: int,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx: NumpyCosIndex,
    progress_callback: Optional[callable] = None,
    cancel_check: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Export recommendation playlists for selected tracks.

    Args:
        track_ids: List of track IDs to generate recommendations for
        output_dir: Directory where playlist files will be saved
        recommendations_per_track: Number of recommendations per track
        meta_ix: Metadata DataFrame indexed by track_id
        emb_ix: Embeddings DataFrame indexed by track_id
        idx: Exact cosine index for similarity search
        progress_callback: Optional callback function(current, total, track_name)
        cancel_check: Optional callable returning True to stop between seeds

    Returns:
        Dictionary with export statistics
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    stats = {
        'total_tracks': len(track_ids),
        'successful': 0,
        'failed': 0,
        'playlists_created': 0,
        'total_recommendations': 0
    }
    written_filename_keys: Set[str] = set()

    for i, track_id in enumerate(track_ids, 1):
        if cancel_check is not None and cancel_check():
            break

        if track_id not in meta_ix.index:
            stats['failed'] += 1
            continue

        track = meta_ix.loc[track_id]
        artist = track.get('artist', 'Unknown Artist')
        title = track.get('title', 'Unknown Title')

        # Update progress
        if progress_callback:
            progress_callback(i, len(track_ids), f"{artist} - {title}")

        # Rank with the shared policy, then truncate to the user's count.
        recommendations = ranked_recommendations(
            track_id,
            meta_ix,
            emb_ix,
            idx,
            topk=RANKING_TOPK,
            final_top=RANKING_FINAL_TOP,
            limit=recommendations_per_track,
        )

        if not recommendations:
            stats['failed'] += 1
            continue

        playlist_path = _unique_playlist_path(
            output_path,
            playlist_filename(artist, title),
            track_id,
            written_filename_keys,
        )

        # Extract track IDs from recommendations
        rec_track_ids = [rec['track_id'] for rec in recommendations]

        # Create playlist
        try:
            create_m3u_playlist(rec_track_ids, str(playlist_path), meta_ix)
            stats['successful'] += 1
            written_filename_keys.add(_filename_collision_key(playlist_path.name))
            stats['playlists_created'] = len(written_filename_keys)
            stats['total_recommendations'] += len(rec_track_ids)
        except Exception as e:
            print(f"Failed to create playlist for {artist} - {title}: {e}")
            stats['failed'] += 1

    return stats


def export_single_playlist(
    track_ids: List[str],
    output_path: str,
    playlist_name: str,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx: NumpyCosIndex,
    recommendations_per_track: int,
    progress_callback: Optional[callable] = None,
    cancel_check: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Export all recommendations into a single combined playlist.

    Args:
        track_ids: List of track IDs to generate recommendations for
        output_path: Path where the playlist file will be saved
        playlist_name: Name for the playlist
        meta_ix: Metadata DataFrame indexed by track_id
        emb_ix: Embeddings DataFrame indexed by track_id
        idx: Exact cosine index for similarity search
        recommendations_per_track: Number of recommendations per track
        progress_callback: Optional callback function(current, total, track_name)
        cancel_check: Optional callable returning True to stop between seeds

    Returns:
        Dictionary with export statistics. Note the deliberate absence of a
        ``playlists_created`` key: that is what makes the Tkinter tab raise
        KeyError and show no completion dialog (inventory defect #10).
    """
    all_recommendations = []
    seen_tracks = set()

    stats = {
        'total_tracks': len(track_ids),
        'successful': 0,
        'failed': 0,
        'total_recommendations': 0
    }

    for i, track_id in enumerate(track_ids, 1):
        if cancel_check is not None and cancel_check():
            break

        if track_id not in meta_ix.index:
            stats['failed'] += 1
            continue

        if progress_callback:
            track = meta_ix.loc[track_id]
            progress_callback(
                i,
                len(track_ids),
                f"{track.get('artist', 'Unknown Artist')} - {track.get('title', 'Unknown Title')}",
            )

        # Rank with the shared policy, then truncate to the user's count.
        recommendations = ranked_recommendations(
            track_id,
            meta_ix,
            emb_ix,
            idx,
            topk=RANKING_TOPK,
            final_top=RANKING_FINAL_TOP,
            limit=recommendations_per_track,
        )

        if not recommendations:
            stats['failed'] += 1
            continue

        stats['successful'] += 1

        # Add unique recommendations
        for rec in recommendations:
            rec_id = rec['track_id']
            if rec_id not in seen_tracks:
                all_recommendations.append(rec_id)
                seen_tracks.add(rec_id)

    # Create single playlist with all recommendations. The legacy function wrote
    # nothing at all when it collected no ids, and never created the directory.
    if all_recommendations:
        create_m3u_playlist(all_recommendations, output_path, meta_ix)
        stats['total_recommendations'] = len(all_recommendations)

    return stats
