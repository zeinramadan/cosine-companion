#!/usr/bin/env python3
"""Track search functionality."""

from typing import List, Dict

import pandas as pd


def search_tracks(query: str, meta_ix: pd.DataFrame, limit: int = 20) -> List[Dict[str, str]]:
    """
    Search for tracks by artist or title.
    
    Args:
        query: Search query
        meta_ix: Metadata index DataFrame
        limit: Maximum results to return
        
    Returns:
        List of track dictionaries with track_id, artist, title, and display_name
    """
    if not query.strip():
        return []
    
    query_lower = query.lower()
    results = []
    
    for track_id, row in meta_ix.iterrows():
        artist = str(row.get("artist", "")).lower()
        title = str(row.get("title", "")).lower()
        
        if (query_lower in artist or 
            query_lower in title or
            query_lower in f"{artist} {title}"):
            results.append({
                "track_id": track_id,
                "artist": row.get("artist", ""),
                "title": row.get("title", ""),
                "display_name": f"{row.get('artist', '')} – {row.get('title', '')}"
            })
            
            if len(results) >= limit:
                break
    
    return results
