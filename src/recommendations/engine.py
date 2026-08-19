#!/usr/bin/env python3
"""Track recommendation engine and similarity search."""

from typing import Dict, List, Any, Optional

import numpy as np
import pandas as pd

from config import DEFAULT_TOPK, DEFAULT_FINAL_TOP
from core.index_builder import NumpyCosIndex
from recommendations.scoring import key_compat, bpm_compat, final_score


def _vector_columns(emb_ix: pd.DataFrame) -> List[str]:
    """The embedding columns, in frame order - the original ``startswith("v")``."""
    return [c for c in emb_ix.columns if c.startswith("v")]


def _normalise(v: np.ndarray) -> np.ndarray:
    """L2-normalise exactly as ``vector_for`` always has, epsilon included.

    Kept as one expression used by both the per-row path and the cache build so
    the two cannot drift: whatever rounding this performs, both perform.
    """
    return v / (np.linalg.norm(v) + 1e-9)


def _vector_from_frame(track_id: str, emb_ix: pd.DataFrame) -> np.ndarray:
    """Derive one normalised vector straight from pandas.

    This is the original body of ``vector_for``, unchanged. It is still the
    definition of the result - ``_NormalisedVectors`` precomputes what it would
    return - and it is still the live code path for any frame the cache cannot
    be built for.
    """
    row = emb_ix.loc[track_id]
    vcols = _vector_columns(emb_ix)
    v = row[vcols].to_numpy().astype("float32")
    return _normalise(v)


class _NormalisedVectors:
    """Every row of one embeddings frame, normalised once, keyed by track_id.

    ``vector_for`` used to redo the same pandas work on every call: a ``.loc``
    row lookup, a rebuild of the vector-column name list (2,560 names filtered
    out of 2,561 columns, i.e. 3.9M ``str.startswith`` calls per generated set),
    a ``to_numpy().astype(float32)`` and an L2 normalise. Generating a 30-track
    set from the 1,532-track library called it 1,508 times for just 286 distinct
    tracks, and that per-call work was ~90% of the run.

    Bit-exactness is by construction rather than by argument. The column list is
    the same list, the float32 row handed to the normaliser is the same fresh
    contiguous buffer ``to_numpy().astype("float32")`` produced, and the
    arithmetic is the shared ``_normalise``. The matrix the cosine index holds is
    deliberately NOT reused: ``NumpyCosIndex.add`` divides by ``norm`` while this
    divides by ``norm + 1e-9``, and although the epsilon happens to vanish in
    float32 at these norms, "happens to" is not a guarantee to build on.
    """

    __slots__ = ("frame", "positions", "matrix")

    def __init__(
        self,
        frame: pd.DataFrame,
        positions: Optional[Dict[Any, int]],
        matrix: Optional[np.ndarray],
    ):
        self.frame = frame
        self.positions = positions
        self.matrix = matrix

    @property
    def usable(self) -> bool:
        """False for a frame that must keep using the per-row path."""
        return self.positions is not None


def _build_normalised_vectors(emb_ix: pd.DataFrame) -> _NormalisedVectors:
    """Normalise every row of ``emb_ix`` once, or mark the frame uncacheable.

    A frame with a duplicate track_id or a duplicate embedding column makes
    ``.loc``/``row[vcols]`` return something other than one vector per id, and
    ``load_all`` rejects duplicate ids outright. Rather than guess at what those
    shapes should mean, such a frame - and any frame whose block simply cannot be
    built - falls back to ``_vector_from_frame``, which is the code that ran
    before this cache existed.
    """
    unusable = _NormalisedVectors(emb_ix, None, None)

    try:
        if emb_ix.index.has_duplicates:
            return unusable
        vcols = _vector_columns(emb_ix)
        if len(set(vcols)) != len(vcols):
            return unusable

        block = emb_ix[vcols].to_numpy()
        matrix = np.empty(block.shape, dtype="float32")
        for i in range(block.shape[0]):
            # ``astype`` copies, so each row reaches ``_normalise`` as the same
            # kind of fresh contiguous float32 buffer the old ``.to_numpy()
            # .astype("float32")`` handed it.
            matrix[i] = _normalise(block[i].astype("float32"))
    except Exception:
        return unusable

    positions = {track_id: i for i, track_id in enumerate(emb_ix.index)}
    return _NormalisedVectors(emb_ix, positions, matrix)


# Frames are matched by identity against a strong reference, so a recycled id()
# can never produce a false hit. Two slots because a session holds one
# embeddings frame at a time and ``LibrarySession.delete_tracks`` rebinds to a
# new one; the second slot only keeps tests that interleave two libraries from
# rebuilding on every call. Rebound as a whole new tuple, never mutated in
# place, so a concurrent reader always sees one consistent generation.
_CACHE_SLOTS = 2
_normalised_cache: tuple = ()


def _normalised_vectors(emb_ix: pd.DataFrame) -> _NormalisedVectors:
    """The precomputed table for ``emb_ix``, building it on first sight."""
    global _normalised_cache

    for entry in _normalised_cache:
        if entry.frame is emb_ix:
            return entry

    entry = _build_normalised_vectors(emb_ix)
    _normalised_cache = (entry,) + _normalised_cache[: _CACHE_SLOTS - 1]
    return entry


def vector_for(track_id: str, emb_ix: pd.DataFrame) -> Optional[np.ndarray]:
    """
    Get normalized embedding vector for a track.

    Args:
        track_id: Track ID to look up
        emb_ix: Embeddings DataFrame indexed by track_id

    Returns:
        Normalized embedding vector or None if not found

    The vector is served from ``_NormalisedVectors``, which normalises the whole
    frame once instead of rebuilding one vector out of pandas per call. The
    returned array is a fresh writable copy, as it has always been, so callers
    may not reach through it into the cache.
    """
    table = _normalised_vectors(emb_ix)
    if not table.usable:
        if track_id not in emb_ix.index:
            return None
        return _vector_from_frame(track_id, emb_ix)

    position = table.positions.get(track_id)
    if position is None:
        return None
    return table.matrix[position].copy()


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
