#!/usr/bin/env python3
"""Data persistence functions for saving and merging indexed data."""

from pathlib import Path
import re
from typing import Tuple, Optional, List

import numpy as np
import pandas as pd

from core.index_store import write_index_generation


VECTOR_COLUMN_PATTERN = re.compile(r"^v\d+$")


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
    data_dir: Path,
    meta_df: pd.DataFrame,
    embeddings_df: pd.DataFrame,
    vectors: np.ndarray,
    track_ids: List[str]
) -> None:
    """
    Save all index data to disk.
    
    Args:
        data_dir: Directory that owns this index generation
        meta_df: Metadata DataFrame
        embeddings_df: Embeddings DataFrame
        vectors: Vector array
        track_ids: List of track IDs
    """
    _validate_row_alignment(meta_df, embeddings_df, vectors, track_ids)

    # CLI indexing and web deletion are separate processes that can overlap.
    # Both must use the same immutable-generation commit; otherwise indexing's
    # old flat rewrite could unlink a deletion manifest that committed midway
    # through it. The configured flat paths are refreshed as compatibility
    # hard links by write_index_generation, but the manifest is authoritative.
    write_index_generation(
        Path(data_dir),
        meta_df,
        embeddings_df,
        vectors,
        track_ids,
    )


def _validate_row_alignment(
    meta_df: pd.DataFrame,
    embeddings_df: pd.DataFrame,
    vectors: np.ndarray,
    track_ids: List[str],
) -> None:
    """Refuse a generation whose four row-indexed values do not agree.

    Search scores are the raw rows of ``index.npy`` and row ``i`` is identified
    solely by ``ids.json[i]``.  The parquet tables therefore have to carry the
    same IDs in the same order, and the vector columns must be the matrix that
    is being committed rather than merely a matrix of the same shape.
    """
    ids = list(track_ids)
    if vectors.ndim != 2:
        raise ValueError(f"index vectors must be 2D; got shape {vectors.shape}")

    row_counts = {
        "meta.parquet": len(meta_df),
        "embeddings.parquet": len(embeddings_df),
        "index.npy": vectors.shape[0],
        "ids.json": len(ids),
    }
    if len(set(row_counts.values())) != 1:
        raise ValueError(f"index row counts do not match: {row_counts}")

    if len(set(ids)) != len(ids):
        raise ValueError("ids.json contains duplicate track IDs")

    for name, frame in (
        ("meta.parquet", meta_df),
        ("embeddings.parquet", embeddings_df),
    ):
        if "track_id" not in frame.columns:
            raise ValueError(f"{name} is missing the track_id column")
        frame_ids = frame["track_id"].tolist()
        if frame_ids != ids:
            raise ValueError(
                f"{name} track_id rows are not aligned with ids.json"
            )

    vector_columns = [
        column
        for column in embeddings_df.columns
        if isinstance(column, str) and VECTOR_COLUMN_PATTERN.fullmatch(column)
    ]
    if len(vector_columns) != vectors.shape[1]:
        raise ValueError(
            "embeddings.parquet vector dimension does not match index.npy"
        )
    embedded_vectors = embeddings_df[vector_columns].to_numpy(dtype="float32")
    if not np.array_equal(embedded_vectors, vectors.astype("float32"), equal_nan=True):
        raise ValueError(
            "embeddings.parquet vector rows are not aligned with index.npy"
        )
