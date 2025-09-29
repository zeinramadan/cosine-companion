#!/usr/bin/env python3
"""Track recommendation logic and data management."""

import json
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import pandas as pd

from config import META_PQ, EMB_PQ, IDX_NPY, IDS_JSON, DEFAULT_TOPK, DEFAULT_FINAL_TOP
from indexing import FaissCosIndex
from scoring import key_compat, bpm_compat, final_score


def load_all() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, FaissCosIndex, np.ndarray, List[str]]:
    meta = pd.read_parquet(META_PQ)
    emb = pd.read_parquet(EMB_PQ)
    V = np.load(IDX_NPY)
    with open(IDS_JSON) as f:
        ids = json.load(f)

    idx = FaissCosIndex(V.shape[1])
    for tid, v in zip(ids, V):
        idx.add(tid, v)

    meta_ix = meta.set_index("track_id")
    emb_ix = emb.set_index("track_id")
    return meta, meta_ix, emb_ix, idx, V, ids


def vector_for(track_id: str, emb_ix: pd.DataFrame) -> Optional[np.ndarray]:
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
    idx: FaissCosIndex,
    topk: int = DEFAULT_TOPK,
    final_top: int = DEFAULT_FINAL_TOP,
) -> List[Dict[str, Any]]:
    v = vector_for(track_id, emb_ix)
    if v is None:
        return []
    src = meta_ix.loc[track_id]
    nbrs = idx.search(v, k=topk + 1)

    out: List[Dict[str, Any]] = []
    for tid, _ in nbrs:
        if tid == track_id:
            continue
        m = meta_ix.loc[tid]
        # Recompute cosine from stored embeddings to avoid any index-metric discrepancies
        v2 = vector_for(tid, emb_ix)
        if v2 is None:
            continue
        cos = float(np.dot(v, v2))
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


