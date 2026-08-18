#!/usr/bin/env python3
"""M3U playlist export functionality for recommendations."""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd

from recommendations.engine import recommend_for
from core.index_builder import NumpyCosIndex


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
    progress_callback: Optional[callable] = None
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
    
    for i, track_id in enumerate(track_ids, 1):
        if track_id not in meta_ix.index:
            stats['failed'] += 1
            continue
        
        track = meta_ix.loc[track_id]
        artist = track.get('artist', 'Unknown Artist')
        title = track.get('title', 'Unknown Title')
        
        # Update progress
        if progress_callback:
            progress_callback(i, len(track_ids), f"{artist} - {title}")
        
        # Generate recommendations - get more candidates than needed so we can sort by cosine
        # and still have the top N by cosine (not by combined score)
        recommendations = recommend_for(
            track_id,
            meta_ix,
            emb_ix,
            idx,
            topk=500,  # Get many cosine-similarity candidates
            final_top=200  # Get top 200 by combined score
        )
        
        if not recommendations:
            stats['failed'] += 1
            continue
        
        # Sort by cosine similarity (pure audio similarity) and take top N
        recommendations.sort(key=lambda x: x['cosine'], reverse=True)
        recommendations = recommendations[:recommendations_per_track]
        
        # Create safe filename
        safe_artist = "".join(c for c in artist if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{safe_artist} - {safe_title}.m3u"
        
        # Limit filename length
        if len(filename) > 200:
            filename = filename[:200] + ".m3u"
        
        playlist_path = output_path / filename
        
        # Extract track IDs from recommendations
        rec_track_ids = [rec['track_id'] for rec in recommendations]
        
        # Create playlist
        try:
            create_m3u_playlist(rec_track_ids, str(playlist_path), meta_ix)
            stats['successful'] += 1
            stats['playlists_created'] += 1
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
    recommendations_per_track: int
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
        
    Returns:
        Dictionary with export statistics
    """
    all_recommendations = []
    seen_tracks = set()
    
    stats = {
        'total_tracks': len(track_ids),
        'successful': 0,
        'failed': 0,
        'total_recommendations': 0
    }
    
    for track_id in track_ids:
        if track_id not in meta_ix.index:
            stats['failed'] += 1
            continue
        
        # Generate recommendations - get more candidates than needed so we can sort by cosine
        recommendations = recommend_for(
            track_id,
            meta_ix,
            emb_ix,
            idx,
            topk=500,  # Get many cosine-similarity candidates
            final_top=200  # Get top 200 by combined score
        )
        
        if not recommendations:
            stats['failed'] += 1
            continue
        
        stats['successful'] += 1
        
        # Sort by cosine similarity (pure audio similarity) and take top N
        recommendations.sort(key=lambda x: x['cosine'], reverse=True)
        recommendations = recommendations[:recommendations_per_track]
        
        # Add unique recommendations
        for rec in recommendations:
            rec_id = rec['track_id']
            if rec_id not in seen_tracks:
                all_recommendations.append(rec_id)
                seen_tracks.add(rec_id)
    
    # Create single playlist with all recommendations
    if all_recommendations:
        create_m3u_playlist(all_recommendations, output_path, meta_ix)
        stats['total_recommendations'] = len(all_recommendations)
    
    return stats
