#!/usr/bin/env python3
"""DJ set generation with anchor tracks."""

from typing import Dict, List, Optional

import pandas as pd

from recommendations.models import SetTrack
from recommendations.engine import recommend_for
from recommendations.transitions import calculate_transition_score


def generate_set(
    anchor_tracks: Dict[int, str],
    total_tracks: int,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx,
    exclude_tracks: Optional[List[str]] = None
) -> List[SetTrack]:
    """
    Generate a complete DJ set with anchor tracks at specified positions.
    
    This algorithm fills empty slots between and around anchor tracks by:
    1. Using context from adjacent tracks (previous/next)
    2. Scoring candidates based on transition quality
    3. Preventing duplicate track selection
    
    Args:
        anchor_tracks: {position: track_id} mapping (1-indexed)
        total_tracks: Total desired tracks in set
        meta_ix: Metadata index DataFrame
        emb_ix: Embeddings index DataFrame  
        idx: FAISS index for similarity search
        exclude_tracks: Track IDs to exclude from recommendations
        
    Returns:
        List of SetTrack objects representing the complete set
    """
    if not anchor_tracks:
        raise ValueError("At least one anchor track is required")
    
    if max(anchor_tracks.keys()) > total_tracks:
        raise ValueError("Anchor track position exceeds total tracks")
    
    exclude_set = set(exclude_tracks or [])
    exclude_set.update(anchor_tracks.values())  # Don't recommend anchor tracks
    
    # Initialize set structure
    set_slots: List[Optional[SetTrack]] = [None] * total_tracks
    
    # Place anchor tracks
    for position, track_id in anchor_tracks.items():
        if track_id in meta_ix.index:
            row = meta_ix.loc[track_id]
            set_slots[position - 1] = SetTrack(
                track_id=track_id,
                position=position,
                is_anchor=True,
                score=1.0,
                artist=row.get("artist", ""),
                title=row.get("title", "")
            )
    
    # Fill empty slots sequentially
    for i in range(total_tracks):
        if set_slots[i] is not None:
            continue  # Already filled (anchor track)
        
        # Determine context for recommendations
        prev_track = None
        next_track = None
        
        # Find previous track
        for j in range(i - 1, -1, -1):
            if set_slots[j] is not None:
                prev_track = set_slots[j].track_id
                break
        
        # Find next track
        for j in range(i + 1, total_tracks):
            if set_slots[j] is not None:
                next_track = set_slots[j].track_id
                break
        
        # Get recommendations based on context
        if prev_track:
            # Get candidates similar to previous track
            candidates = recommend_for(
                prev_track, meta_ix, emb_ix, idx, 
                topk=100, final_top=50
            )
        elif next_track:
            # If no previous track, get candidates similar to next track
            candidates = recommend_for(
                next_track, meta_ix, emb_ix, idx,
                topk=100, final_top=50
            )
        else:
            # Fallback: use first anchor track if no context
            first_anchor = list(anchor_tracks.values())[0]
            candidates = recommend_for(
                first_anchor, meta_ix, emb_ix, idx,
                topk=100, final_top=50
            )
        
        # Filter out excluded tracks and already used tracks
        used_tracks = {track.track_id for track in set_slots if track is not None}
        all_excluded = exclude_set.union(used_tracks)  # Combine both exclusion sets
        filtered_candidates = [
            c for c in candidates 
            if c["track_id"] not in all_excluded
        ]
        
        if not filtered_candidates:
            # If no candidates, create placeholder
            set_slots[i] = SetTrack(
                track_id=f"empty_{i+1}",
                position=i + 1,
                is_anchor=False,
                score=0.0,
                artist="No suitable track found",
                title=""
            )
            continue
        
        # Score candidates based on transition quality
        best_candidate = None
        best_score = -1.0
        
        for candidate in filtered_candidates[:20]:  # Limit to top 20 for performance
            track_id = candidate["track_id"]
            
            if prev_track:
                score = calculate_transition_score(
                    prev_track, track_id, next_track, emb_ix
                )
            else:
                # No previous track, just use cosine similarity to next
                score = candidate.get("cosine", 0.0)
            
            if score > best_score:
                best_score = score
                best_candidate = candidate
        
        # Add best candidate to set
        if best_candidate:
            track_id = best_candidate["track_id"]
            
            # Get artist and title, with fallback to meta_ix if not in candidate
            artist = best_candidate.get("artist", "")
            title = best_candidate.get("title", "")
            
            # Fallback: get from meta_ix if not available in candidate
            if (not artist or not title) and track_id in meta_ix.index:
                row = meta_ix.loc[track_id]
                artist = artist or row.get("artist", "")
                title = title or row.get("title", "")
            
            set_slots[i] = SetTrack(
                track_id=track_id,
                position=i + 1,
                is_anchor=False,
                score=best_score,
                artist=artist,
                title=title
            )
            # Add to exclude set to prevent reuse
            exclude_set.add(track_id)
    
    # Final validation: ensure no duplicates
    final_set = [track for track in set_slots if track is not None]
    track_ids = [track.track_id for track in final_set]
    
    # Check for duplicates (excluding placeholder tracks)
    real_tracks = [tid for tid in track_ids if not tid.startswith("empty_")]
    if len(real_tracks) != len(set(real_tracks)):
        print("⚠️  Warning: Duplicate tracks detected in generated set")
        # Remove duplicates, keeping first occurrence
        seen = set()
        unique_set = []
        for track in final_set:
            if track.track_id not in seen or track.track_id.startswith("empty_"):
                seen.add(track.track_id)
                unique_set.append(track)
        final_set = unique_set
    
    return final_set
