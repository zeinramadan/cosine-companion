#!/usr/bin/env python3
"""FAISS index management for similarity search."""

from typing import List, Tuple

import numpy as np
import faiss


class FaissCosIndex:
    """
    FAISS-based cosine similarity index using HNSW (Hierarchical Navigable Small World).

    Provides efficient approximate nearest neighbor search for high-dimensional vectors.
    """

    def __init__(self, dim: int):
        """Initialize the FAISS index with inner-product metric (cosine on normalized vectors)."""
        # Use inner product metric; we normalize all vectors beforehand
        self.index = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
        self.index.hnsw.efSearch = 64
        self.index.hnsw.efConstruction = 200
        self.ids: List[str] = []

    def add(self, track_id: str, v: np.ndarray):
        """Add a normalized vector to the index (will normalize defensively)."""
        v = v.astype("float32")
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        self.index.add(v[np.newaxis, :])
        self.ids.append(track_id)

    def search(self, v: np.ndarray, k: int = 50) -> List[Tuple[str, float]]:
        """Search for k nearest neighbors.

        Returns list of (track_id, similarity_score).
        """
        # Ensure query vector is normalized
        v = v.astype("float32")
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        D, I = self.index.search(v[np.newaxis, :], k)
        out = []
        for j, i in enumerate(I[0]):
            if i == -1:
                continue
            out.append((self.ids[i], float(D[0, j])))
        return out


def build_faiss_index(vectors: np.ndarray, track_ids: List[str]) -> FaissCosIndex:
    """
    Build a FAISS index from vectors and track IDs.
    
    Args:
        vectors: Array of embedding vectors (N x D)
        track_ids: List of track IDs corresponding to vectors
        
    Returns:
        Built FaissCosIndex ready for search
    """
    if len(vectors) == 0:
        raise ValueError("Cannot build index from empty vectors")
    
    if len(vectors) != len(track_ids):
        raise ValueError(f"Vector count ({len(vectors)}) must match track ID count ({len(track_ids)})")
    
    idx = FaissCosIndex(vectors.shape[1])
    for tid, v in zip(track_ids, vectors):
        idx.add(tid, v)
    
    return idx
