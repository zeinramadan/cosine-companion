#!/usr/bin/env python3
"""Management of manually deleted tracks to prevent re-indexing."""

import json
from typing import Set, Dict, List
from pathlib import Path

from config import DELETED_TRACKS_JSON


def _report(progress, phase, message):
    """Print, or hand the same string to a structured progress callback."""
    if progress is None:
        print(message)
    else:
        progress(phase, 0, 0, message)


def load_deleted_tracks(progress=None, path=None) -> Set[str]:
    """
    Load the set of track IDs that have been manually deleted.
    
    Returns:
        Set of deleted track IDs
    """
    data = load_deleted_tracks_with_info(progress=progress, path=path)
    return set(data.keys())


def load_deleted_tracks_with_info(progress=None, path=None) -> Dict[str, Dict[str, str]]:
    """
    Load deleted tracks with their metadata.
    
    Returns:
        Dict mapping track_id to {artist, title}
    """
    target = Path(path) if path is not None else DELETED_TRACKS_JSON
    if not target.exists():
        return {}
    
    try:
        with open(target, 'r') as f:
            data = json.load(f)
            
            # Handle old format (list of track IDs)
            if isinstance(data, list):
                # Convert old format to new format
                return {track_id: {"artist": "Unknown", "title": track_id} for track_id in data}
            
            # New format (dict with metadata)
            return data
    except Exception as e:
        _report(progress, "deleted", f"Warning: Could not load deleted tracks list ({e})")
        return {}


def save_deleted_tracks_with_info(
    deleted_tracks: Dict[str, Dict[str, str]], path=None
) -> None:
    """
    Save deleted tracks with their metadata to disk.
    
    Args:
        deleted_tracks: Dict mapping track_id to {artist, title}
    """
    try:
        target = Path(path) if path is not None else DELETED_TRACKS_JSON
        with open(target, 'w') as f:
            json.dump(deleted_tracks, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save deleted tracks list ({e})")


def save_deleted_tracks(deleted_ids: Set[str], path=None) -> None:
    """
    Save the set of deleted track IDs to disk (without metadata).
    Used when clearing tracks.
    
    Args:
        deleted_ids: Set of track IDs that have been deleted
    """
    # Convert to dict format
    deleted_tracks = {track_id: {"artist": "Unknown", "title": track_id} for track_id in deleted_ids}
    save_deleted_tracks_with_info(deleted_tracks, path=path)


def add_deleted_tracks_with_metadata(
    tracks_info: List[Dict[str, str]], path=None
) -> None:
    """
    Add tracks to the deleted list with their metadata.
    
    Args:
        tracks_info: List of dicts with keys: track_id, artist, title
    """
    existing_deleted = load_deleted_tracks_with_info(path=path)
    
    for track in tracks_info:
        track_id = track["track_id"]
        existing_deleted[track_id] = {
            "artist": track.get("artist", "Unknown"),
            "title": track.get("title", "Unknown")
        }
    
    save_deleted_tracks_with_info(existing_deleted, path=path)


def remove_from_deleted_tracks(track_ids: Set[str], path=None) -> None:
    """
    Remove track IDs from the deleted tracks list (if user wants to re-add them).
    
    Args:
        track_ids: Set of track IDs to remove from deleted list
        path: Explicit deleted-tracks file for the library being restored
    """
    existing_deleted = load_deleted_tracks_with_info(path=path)
    
    for track_id in track_ids:
        existing_deleted.pop(track_id, None)
    
    save_deleted_tracks_with_info(existing_deleted, path=path)


def filter_deleted_tracks(
    df, track_id_column: str = 'track_id', progress=None, path=None
):
    """
    Filter out tracks that have been manually deleted by the user.
    
    Args:
        df: DataFrame with track data
        track_id_column: Name of the column containing track IDs
        progress: Optional callable(phase, current, total, message)
        path: Explicit deleted-tracks file for the library being indexed

    Returns:
        Filtered DataFrame without deleted tracks
    """
    deleted_ids = load_deleted_tracks(progress=progress, path=path)
    
    if not deleted_ids:
        return df
    
    original_count = len(df)
    filtered_df = df[~df[track_id_column].isin(deleted_ids)]
    filtered_count = original_count - len(filtered_df)
    
    if filtered_count > 0:
        _report(progress, "deleted", f"   Filtered out {filtered_count} previously deleted tracks")
    
    return filtered_df
