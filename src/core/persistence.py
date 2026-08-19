#!/usr/bin/env python3
"""Data persistence functions for saving and merging indexed data."""

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Tuple, Optional, List

import numpy as np
import pandas as pd

from config import META_PQ, EMB_PQ, IDX_NPY, IDS_JSON
from core.index_store import retire_index_manifest


def _replace_file(path, writer) -> None:
    """Write one flat compatibility file through a fsync'd same-dir temp."""
    path = Path(path)
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        existing_mode = None

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=path.suffix,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        writer(temporary)
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    # Each flat file is replaced rather than opened in place. After Library
    # deletion these paths are hard-link compatibility mirrors of the current
    # immutable generation; truncating one would corrupt that generation while
    # its manifest was still live.
    _replace_file(META_PQ, lambda path: meta_df.to_parquet(path, index=False))
    _replace_file(EMB_PQ, lambda path: embeddings_df.to_parquet(path, index=False))
    _replace_file(IDX_NPY, lambda path: np.save(path, vectors))

    def write_ids(path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(track_ids, handle)

    _replace_file(IDS_JSON, write_ids)

    # Library deletion publishes immutable files behind one manifest pointer.
    # Keep that pointer live while these four flat files are being rewritten;
    # removing it only after the final close makes this completed flat set the
    # next visible generation. A failed indexing run therefore leaves the
    # preceding deletion generation readable instead of exposing a mixed set.
    retire_index_manifest(META_PQ.parent)
