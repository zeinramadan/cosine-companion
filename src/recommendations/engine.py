#!/usr/bin/env python3
"""Track recommendation engine and similarity search."""

from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd

from config import DEFAULT_TOPK, DEFAULT_FINAL_TOP
from core.index_builder import NumpyCosIndex
from recommendations.scoring import key_compat, bpm_compat, final_score


def vector_for(track_id: str, emb_ix: pd.DataFrame) -> Optional[np.ndarray]:
    """
    Get normalized embedding vector for a track.
    
    Args:
        track_id: Track ID to look up
        emb_ix: Embeddings DataFrame indexed by track_id
        
    Returns:
        Normalized embedding vector or None if not found
    """
    if track_id not in emb_ix.index:
        return None
    row = emb_ix.loc[track_id]
    vcols = [c for c in emb_ix.columns if c.startswith("v")]
    v = row[vcols].to_numpy().astype("float32")
    v = v / (np.linalg.norm(v) + 1e-9)
    return v


def recommend_for(
    track_id: str,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx: NumpyCosIndex,
    topk: int = DEFAULT_TOPK,
    final_top: int = DEFAULT_FINAL_TOP,
) -> List[Dict[str, Any]]:
    """
    Generate track recommendations based on similarity and compatibility.
    
    Args:
        track_id: Source track ID
        meta_ix: Metadata DataFrame indexed by track_id
        emb_ix: Embeddings DataFrame indexed by track_id
        idx: Exact cosine index for similarity search
        topk: Number of cosine-similarity candidates to retrieve
        final_top: Number of final recommendations to return
        
    Returns:
        List of recommendation dictionaries with track info and scores
    """
    v = vector_for(track_id, emb_ix)
    if v is None:
        return []
    src = meta_ix.loc[track_id]
    nbrs = idx.search(v, k=topk + 1)

    out: List[Dict[str, Any]] = []
    for tid, cos in nbrs:
        if tid == track_id:
            continue
        m = meta_ix.loc[tid]
        ks = key_compat(src.get("key"), m.get("key"))
        bs = bpm_compat(src.get("bpm"), m.get("bpm"))
        score = final_score(cos, ks, bs)
        out.append({
            "track_id": tid,
            "artist": m.get("artist", ""),
            "title": m.get("title", ""),
            "bpm": m.get("bpm", None),
            "key": m.get("key", ""),
            "score": score,
            "cosine": cos,
            "key_score": ks,
            "bpm_score": bs,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:final_top]
