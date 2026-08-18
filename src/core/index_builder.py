#!/usr/bin/env python3
"""Exact NumPy cosine-similarity index."""

from typing import List, Tuple

import numpy as np


class NumpyCosIndex:
    """Brute-force cosine search over a float32 matrix."""

    def __init__(self, dim: int):
        """Initialize an empty index for vectors with ``dim`` components."""
        if dim <= 0:
            raise ValueError(f"Vector dimension must be positive, got {dim}")
        self.dim = dim
        self.matrix = np.empty((0, dim), dtype=np.float32)
        self.ids: List[str] = []

    def add(self, track_id: str, v: np.ndarray) -> None:
        """Normalize and append a vector and its positional track ID."""
        v = v.astype("float32")
        if v.shape != (self.dim,):
            raise ValueError(
                f"Vector for track {track_id!r} has shape {v.shape}; "
                f"expected ({self.dim},)"
            )
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        self.matrix = np.concatenate((self.matrix, v[np.newaxis, :]), axis=0)
        self.ids.append(track_id)

    def search(self, v: np.ndarray, k: int = 50) -> List[Tuple[str, float]]:
        """Return up to ``k`` track IDs in descending exact-cosine order."""
        count = min(k, len(self.ids))
        if count <= 0:
            return []

        v = v.astype("float32")
        if v.shape != (self.dim,):
            raise ValueError(f"Query vector has shape {v.shape}; expected ({self.dim},)")
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm

        scores = self.matrix @ v
        candidate_indices = np.argpartition(scores, len(scores) - count)[-count:]
        order = np.argsort(-scores[candidate_indices], kind="stable")
        ranked_indices = candidate_indices[order]
        return [(self.ids[i], float(scores[i])) for i in ranked_indices]
