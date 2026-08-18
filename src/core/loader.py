#!/usr/bin/env python3
"""Data loading functions for metadata, embeddings, and index."""

import json
import re
from typing import Tuple, Optional, List

import numpy as np
import pandas as pd

from config import META_PQ, EMB_PQ, IDX_NPY, IDS_JSON
from core.index_builder import NumpyCosIndex


VECTOR_COLUMN_PATTERN = re.compile(r"^v\d+$")


def load_existing_data() -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Load existing metadata and embeddings if they exist.
    
    Returns:
        Tuple of (existing_meta_df, existing_embeddings_df) or (None, None) if no data exists
    """
    if not META_PQ.exists() or not EMB_PQ.exists():
        return None, None
    
    try:
        existing_meta = pd.read_parquet(META_PQ)
        existing_emb = pd.read_parquet(EMB_PQ)
        print(f"Found existing data: {len(existing_meta)} tracks already indexed")
        return existing_meta, existing_emb
    except Exception as e:
        print(f"Warning: Could not load existing data ({e}), starting fresh")
        return None, None


def _validate_index_data(V: np.ndarray, ids: List[str], emb: pd.DataFrame) -> None:
    """Validate the persisted row and dimension mappings before indexing."""
    if V.ndim != 2:
        raise ValueError(f"index.npy must contain a 2D matrix; got shape {V.shape}")
    if len(ids) != V.shape[0]:
        raise ValueError(
            f"ids.json contains {len(ids)} track IDs but index.npy has "
            f"{V.shape[0]} vector rows"
        )

    duplicate_ids = pd.Index(ids)[pd.Index(ids).duplicated()].unique().tolist()
    if duplicate_ids:
        raise ValueError(f"ids.json contains duplicate track IDs: {duplicate_ids[:5]}")

    if "track_id" not in emb.columns:
        raise ValueError("embeddings.parquet is missing the track_id column")
    duplicate_embedding_ids = emb.loc[
        emb["track_id"].duplicated(), "track_id"
    ].unique().tolist()
    if duplicate_embedding_ids:
        raise ValueError(
            "embeddings.parquet contains duplicate track IDs: "
            f"{duplicate_embedding_ids[:5]}"
        )

    vector_columns = [
        column
        for column in emb.columns
        if isinstance(column, str) and VECTOR_COLUMN_PATTERN.fullmatch(column)
    ]
    if len(vector_columns) != V.shape[1]:
        raise ValueError(
            f"index.npy vector dimension is {V.shape[1]} but "
            f"embeddings.parquet has {len(vector_columns)} vector columns"
        )

    indexed_ids = set(ids)
    embedding_ids = set(emb["track_id"])
    if indexed_ids != embedding_ids:
        missing = list(indexed_ids - embedding_ids)[:5]
        extra = list(embedding_ids - indexed_ids)[:5]
        raise ValueError(
            "ids.json and embeddings.parquet track IDs do not match "
            f"(missing embeddings: {missing}; unindexed embeddings: {extra})"
        )


def load_all() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, NumpyCosIndex, np.ndarray, List[str]]:
    """
    Load all indexed data: metadata, embeddings, vectors, and cosine index.
    
    Returns:
        Tuple of (meta, meta_ix, emb_ix, idx, V, ids) where:
        - meta: Full metadata DataFrame
        - meta_ix: Metadata indexed by track_id
        - emb_ix: Embeddings indexed by track_id
        - idx: Built exact cosine index
        - V: Vector array
        - ids: List of track IDs
    """
    meta = pd.read_parquet(META_PQ)
    emb = pd.read_parquet(EMB_PQ)
    V = np.load(IDX_NPY)
    with open(IDS_JSON, encoding="utf-8") as f:
        ids = json.load(f)

    _validate_index_data(V, ids, emb)

    idx = NumpyCosIndex(V.shape[1])
    for tid, v in zip(ids, V):
        idx.add(tid, v)

    meta_ix = meta.set_index("track_id")
    emb_ix = emb.set_index("track_id")
    return meta, meta_ix, emb_ix, idx, V, ids


def find_new_tracks(current_meta: pd.DataFrame, existing_meta: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    Find tracks that need to be processed (new or changed).
    
    Args:
        current_meta: Current metadata from XML
        existing_meta: Previously processed metadata
        
    Returns:
        DataFrame of tracks that need processing
    """
    if existing_meta is None:
        return current_meta
    
    # Find tracks not in existing data
    existing_ids = set(existing_meta['track_id'].values)
    new_tracks = current_meta[~current_meta['track_id'].isin(existing_ids)]
    
    print(f"Found {len(new_tracks)} new tracks to process")
    return new_tracks
