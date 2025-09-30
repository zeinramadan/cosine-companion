#!/usr/bin/env python3
"""Track transition scoring for smooth DJ sets."""

from typing import Optional

import numpy as np
import pandas as pd

from recommendations.engine import vector_for


def calculate_transition_score(
    from_track_id: str, 
    to_track_id: str, 
    next_track_id: Optional[str],
    emb_ix: pd.DataFrame
) -> float:
    """
    Calculate how well tracks transition together.
    
    Considers both the direct transition from source to candidate,
    and if a next track is known, also factors in forward compatibility.
    
    Args:
        from_track_id: Source track ID
        to_track_id: Candidate track ID  
        next_track_id: Next track ID (if known)
        emb_ix: Embeddings index DataFrame
        
    Returns:
        Transition score (0.0 to 1.0)
    """
    # Get embedding vectors
    from_vec = vector_for(from_track_id, emb_ix)
    to_vec = vector_for(to_track_id, emb_ix)
    
    if from_vec is None or to_vec is None:
        return 0.0
    
    # Base cosine similarity
    cosine_score = float(np.dot(from_vec, to_vec))
    
    # Forward compatibility if next track is known
    if next_track_id:
        next_vec = vector_for(next_track_id, emb_ix)
        if next_vec is not None:
            forward_score = float(np.dot(to_vec, next_vec))
            # Weight: 80% current transition + 20% forward compatibility
            return 0.8 * cosine_score + 0.2 * forward_score
    
    # If no next track, use only cosine similarity
    return cosine_score
