#!/usr/bin/env python3
"""Data persistence functions for saving and merging indexed data."""

import json
from typing import Tuple, Optional, List

import numpy as np
import pandas as pd

from config import META_PQ, EMB_PQ, IDX_NPY, IDS_JSON


def merge_embeddings(
    existing_emb: Optional[pd.DataFrame], 
    new_emb_df: pd.DataFrame, 
    new_track_ids: List[str], 
    new_vectors: np.ndarray
) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
    """
    Merge existing embeddings with new ones.
    
    Args:
        existing_emb: Existing embeddings DataFrame
        new_emb_df: New embeddings DataFrame  
        new_track_ids: List of new track IDs
        new_vectors: Array of new vectors
        
    Returns:
        Tuple of (combined_embeddings_df, combined_vectors, combined_track_ids)
    """
    if existing_emb is None:
        return new_emb_df, new_vectors, new_track_ids
    
    # Combine DataFrames
    combined_emb = pd.concat([existing_emb, new_emb_df], ignore_index=True)
    
    # Reconstruct vectors from existing embeddings
    existing_vcols = [c for c in existing_emb.columns if c.startswith("v")]
    existing_vectors = existing_emb[existing_vcols].values.astype("float32")
    existing_track_ids = existing_emb['track_id'].tolist()
    
    # Combine vectors and track IDs
    if len(new_vectors) > 0:
        combined_vectors = np.vstack([existing_vectors, new_vectors])
    else:
        combined_vectors = existing_vectors
    
    combined_track_ids = existing_track_ids + new_track_ids
    
    return combined_emb, combined_vectors, combined_track_ids


def save_index_data(
    meta_df: pd.DataFrame,
    embeddings_df: pd.DataFrame,
    vectors: np.ndarray,
    track_ids: List[str]
) -> None:
    """
    Save all index data to disk.
    
    Args:
        meta_df: Metadata DataFrame
        embeddings_df: Embeddings DataFrame
        vectors: Vector array
        track_ids: List of track IDs
    """
    # Save metadata
    meta_df.to_parquet(META_PQ, index=False)
    
    # Save embeddings
    embeddings_df.to_parquet(EMB_PQ, index=False)
    
    # Save vectors
    np.save(IDX_NPY, vectors)
    
    # Save track IDs
    with open(IDS_JSON, "w") as f:
        json.dump(track_ids, f)
