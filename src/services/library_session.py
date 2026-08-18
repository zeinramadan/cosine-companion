#!/usr/bin/env python3
"""LibrarySession - the single source of truth for the indexed library.

Takes over the six loose attributes ``App`` used to hold and mutate from tab
mixins (``meta``, ``meta_ix``, ``emb_ix``, ``idx``, ``V``, ``ids``;
``ui/app.py:46``), plus the deletion logic that lived in
``ui/library_tab.py:213-273``.

The logic here was **moved**, not rewritten. In particular these quirks are
preserved deliberately and are pinned by tests
(``tests/services/test_library_session.py``):

* Deleting every track leaves ``index`` as ``None`` and ``vectors`` as a 0-d
  empty array, and ``index.npy`` is **not** rewritten - so it keeps the old
  vectors beside an empty ``ids.json`` (inventory defect #3).
* The four data files are rewritten in sequence with no temp-file-and-rename
  and no rollback, so a failure partway through leaves them mutually
  inconsistent (inventory defect #2, spec 3.2).
* ``search_tracks`` exposes ``recommendations.search.search_tracks`` - the
  implementation the two selector dialogs call - and therefore returns ``[]``
  for a blank query (inventory defect #9). The regex variant in
  ``pick_current`` and the album/key variant in ``filter_library`` are
  documented in the inventory and deliberately NOT unified here.

This module must never import tkinter or any UI module.
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from config import DATA
from core.deleted_tracks import add_deleted_tracks_with_metadata
from core.index_builder import NumpyCosIndex
from core.loader import index_file_paths, load_all
from recommendations.search import search_tracks


class LibrarySession:
    """Owns the loaded library: metadata, embeddings, vectors and the index."""

    def __init__(self, data_dir: Optional[Path] = None):
        """Create an unloaded session bound to ``data_dir`` (default: config DATA)."""
        self.data_dir = Path(data_dir) if data_dir is not None else DATA
        self._meta: Optional[pd.DataFrame] = None
        self._meta_ix: Optional[pd.DataFrame] = None
        self._emb_ix: Optional[pd.DataFrame] = None
        self._index: Optional[NumpyCosIndex] = None
        self._vectors: Optional[np.ndarray] = None
        self._ids: Optional[List[str]] = None

    @classmethod
    def load(cls, data_dir: Optional[Path] = None) -> "LibrarySession":
        """Load a library from ``data_dir`` and return the session holding it."""
        session = cls(data_dir)
        session.reload()
        return session

    def reload(self) -> None:
        """Re-read all four data files from disk, replacing the in-memory state."""
        (
            self._meta,
            self._meta_ix,
            self._emb_ix,
            self._index,
            self._vectors,
            self._ids,
        ) = load_all(self.data_dir)

    # -- read accessors ----------------------------------------------------

    @property
    def meta(self) -> pd.DataFrame:
        """Full metadata, one row per track, with track_id as a column."""
        return self._meta

    @property
    def meta_ix(self) -> pd.DataFrame:
        """Metadata indexed by track_id."""
        return self._meta_ix

    @property
    def emb_ix(self) -> pd.DataFrame:
        """Embeddings indexed by track_id."""
        return self._emb_ix

    @property
    def index(self) -> Optional[NumpyCosIndex]:
        """The exact cosine index, or ``None`` once every track is deleted."""
        return self._index

    @property
    def vectors(self) -> np.ndarray:
        """The raw vector matrix (``V`` in the old App)."""
        return self._vectors

    @property
    def ids(self) -> List[str]:
        """Track IDs in index row order."""
        return self._ids

    @property
    def track_count(self) -> int:
        """Number of tracks in the metadata table."""
        return 0 if self._meta_ix is None else len(self._meta_ix)

    @property
    def is_empty(self) -> bool:
        """True when there is no usable index - the old ``idx is None`` condition."""
        return self._index is None

    def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Return one track's metadata as a dict, or ``None`` if it is unknown."""
        if self._meta_ix is None or track_id not in self._meta_ix.index:
            return None
        row = self._meta_ix.loc[track_id]
        track = row.to_dict()
        track["track_id"] = track_id
        return track

    def search_tracks(self, query: str, limit: int = 20) -> List[Dict[str, str]]:
        """Search artist/title, delegating to the implementation the UI dialogs use."""
        return search_tracks(query, self._meta_ix, limit=limit)

    # -- mutation ----------------------------------------------------------

    def delete_tracks(self, track_ids: Iterable[str]) -> int:
        """Remove tracks from the library and persist the four data files.

        Moved verbatim from ``ui/library_tab.py:213-273``, including its
        non-atomic write sequence and its empty-collection handling. Returns the
        number of metadata rows removed, which the Library tab uses to decide
        which status message to show.
        """
        track_ids_to_delete = set(track_ids)

        # Record these tracks as deleted with their metadata so we can display
        # them later. The Library tab used to hand over the dicts it had already
        # built from meta_ix; looking them up here yields the same values, and
        # an unknown id falls back to the same "Unknown" defaults.
        add_deleted_tracks_with_metadata(
            [self._deleted_track_record(tid) for tid in track_ids_to_delete]
        )

        # Update metadata
        original_meta_count = len(self._meta_ix)
        self._meta_ix = self._meta_ix[~self._meta_ix.index.isin(track_ids_to_delete)]

        # Update embeddings
        self._emb_ix = self._emb_ix[~self._emb_ix.index.isin(track_ids_to_delete)]

        # Update cosine index and vectors: rebuild without the deleted tracks
        remaining_track_ids = []
        remaining_vectors = []

        for i, track_id in enumerate(self._ids):
            if track_id not in track_ids_to_delete:
                remaining_track_ids.append(track_id)
                remaining_vectors.append(self._vectors[i])

        if remaining_vectors:
            self._vectors = np.vstack(remaining_vectors)
            self._ids = remaining_track_ids

            self._index = NumpyCosIndex(self._vectors.shape[1])
            for tid, v in zip(self._ids, self._vectors):
                self._index.add(tid, v)
        else:
            # No tracks remaining
            self._vectors = np.array([])
            self._ids = []
            self._index = None

        self._meta = self._meta_ix.reset_index()
        self._persist()

        return original_meta_count - len(self._meta_ix)

    def _deleted_track_record(self, track_id: str) -> Dict[str, str]:
        track = self.get_track(track_id)
        if track is None:
            # add_deleted_tracks_with_metadata applies its own "Unknown"
            # defaults for absent keys.
            return {"track_id": track_id}
        return {
            "track_id": track_id,
            "artist": track.get("artist", ""),
            "title": track.get("title", ""),
        }

    def _persist(self) -> None:
        """Write the four data files, in the original order and without atomicity."""
        meta_pq, emb_pq, idx_npy, ids_json = index_file_paths(self.data_dir)

        # Convert meta_ix back to a regular DataFrame for saving
        self._meta_ix.reset_index().to_parquet(meta_pq, index=False)

        # Convert emb_ix back to a regular DataFrame for saving
        self._emb_ix.reset_index().to_parquet(emb_pq, index=False)

        # Save vectors and IDs
        if len(self._vectors) > 0:
            np.save(idx_npy, self._vectors)
        with open(ids_json, "w") as f:
            json.dump(self._ids, f)
