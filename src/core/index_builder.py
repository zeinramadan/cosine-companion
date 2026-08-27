#!/usr/bin/env python3
"""Exact NumPy cosine-similarity index."""

from typing import List, Optional, Tuple

import numpy as np


class NumpyCosIndex:
    """Brute-force cosine search over a float32 matrix."""

    def __init__(self, dim: int):
        """Initialize an empty index for vectors with ``dim`` components."""
        if dim <= 0:
            raise ValueError(f"Vector dimension must be positive, got {dim}")
        self.dim = dim
        self.ids: List[str] = []
        self._rows: List[np.ndarray] = []
        self._matrix: Optional[np.ndarray] = None

    @property
    def matrix(self) -> np.ndarray:
        """Materialize and cache the current rows as one float32 matrix."""
        if self._matrix is None:
            self._matrix = (
                np.vstack(self._rows)
                if self._rows
                else np.empty((0, self.dim), dtype=np.float32)
            )
        return self._matrix

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
        self._rows.append(v)
        self._matrix = None
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

        # NumPy 2.2.6 with Apple Accelerate raised divide, overflow, and invalid
        # here on the measured finite 1,532 x 2,560 float32 library even though
        # every score was finite and bitwise unchanged by this local suppression;
        # the same data and NumPy version were silent with the tested OpenBLAS
        # build. Ignore only those measured flags, then validate the result.
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            scores = self.matrix @ v
        if not np.isfinite(scores).all():
            raise RuntimeError(
                "Recommendation index is corrupt: similarity search produced "
                "non-finite scores. Rebuild the library index in Settings, then "
                "try again."
            )
        ranked_indices = np.argsort(-scores, kind="stable")[:count]
        return [(self.ids[i], float(scores[i])) for i in ranked_indices]
