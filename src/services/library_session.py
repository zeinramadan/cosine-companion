#!/usr/bin/env python3
"""LibrarySession - the single source of truth for the indexed library.

Takes over the six loose attributes ``App`` used to hold and mutate from tab
mixins (``meta``, ``meta_ix``, ``emb_ix``, ``idx``, ``V``, ``ids``;
``ui/app.py:46``), plus the deletion logic that lived in
``ui/library_tab.py:213-273``.

The web Library destination is the point where the characterised deletion
defects are retired:

* all four files are written as an immutable generation and published by one
  atomically replaced manifest;
* deleting the final track writes a real ``(0, dimension)`` matrix, so restart
  preserves an empty, consistent library; and
* ``meta`` is published with the other rebuilt objects, so every consumer sees
  the deletion immediately.

Every in-memory object is still rebound rather than mutated.  A running export
that already captured ``snapshot()`` therefore finishes against its start-of-
run generation, while a later export captures the newly published one.

The following search quirk remains deliberately preserved and pinned by tests
(``tests/services/test_library_session.py``):

* ``search_tracks`` exposes ``recommendations.search.search_tracks`` - the
  implementation the two selector dialogs call - and therefore returns ``[]``
  for a blank query (inventory defect #9). The regex variant in
  ``pick_current`` and the album/key variant in ``filter_library`` are
  documented in the inventory and deliberately NOT unified here.
This module must never depend on a UI toolkit; see
tests/test_services_are_ui_free.py, which enforces that with an AST walk.
"""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from config import DATA
from core.deleted_tracks import add_deleted_tracks_with_metadata
from core.index_builder import NumpyCosIndex
from core.index_store import write_index_generation
from core.loader import load_all
from recommendations.search import search_tracks


@dataclass(frozen=True)
class LibrarySnapshot:
    """One consistent view of the library, captured at a single instant.

    A long-running reader - the playlist export, which takes ~6.8 minutes over
    the full collection - must not re-read the session's properties as it goes.
    ``delete_tracks`` **rebinds** ``meta_ix``, ``emb_ix``, ``index``, ``vectors``
    and ``ids`` to new objects, so a reader that re-reads them mid-run can find
    itself ranking against one index and writing against another. Capturing them
    once, here, is what the Tkinter export worker always did by passing them as
    arguments at the start of the run.

    This is NOT a fix for the export/delete race (inventory defect #1): the
    export still finishes against a snapshot that a concurrent delete has made
    stale, exactly as before. It restores parity - one capture point per run -
    rather than the per-seed re-reading the first draft of the service
    introduced.
    """

    meta: Optional[pd.DataFrame]
    meta_ix: Optional[pd.DataFrame]
    emb_ix: Optional[pd.DataFrame]
    index: Optional[NumpyCosIndex]
    vectors: Optional[np.ndarray]
    ids: Optional[List[str]]


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
        self._lock = threading.RLock()

    @classmethod
    def load(cls, data_dir: Optional[Path] = None) -> "LibrarySession":
        """Load a library from ``data_dir`` and return the session holding it."""
        session = cls(data_dir)
        session.reload()
        return session

    def reload(self) -> None:
        """Re-read all four data files from disk, replacing the in-memory state."""
        loaded = load_all(self.data_dir)
        with self._lock:
            (
                self._meta,
                self._meta_ix,
                self._emb_ix,
                self._index,
                self._vectors,
                self._ids,
            ) = loaded

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

    def snapshot(self) -> LibrarySnapshot:
        """Capture the current library objects for the duration of one operation.

        Deletion holds the same lock while publishing all six new references,
        so this capture is wholly before or wholly after that publication.
        Objects from the old generation remain alive for readers that already
        captured them; deletion never mutates those objects in place.
        """
        with self._lock:
            return LibrarySnapshot(
                meta=self._meta,
                meta_ix=self._meta_ix,
                emb_ix=self._emb_ix,
                index=self._index,
                vectors=self._vectors,
                ids=self._ids,
            )

    def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Return one track's metadata as a dict, or ``None`` if it is unknown."""
        with self._lock:
            meta_ix = self._meta_ix
        if meta_ix is None or track_id not in meta_ix.index:
            return None
        row = meta_ix.loc[track_id]
        track = row.to_dict()
        track["track_id"] = track_id
        return track

    def search_tracks(self, query: str, limit: int = 20) -> List[Dict[str, str]]:
        """Search artist/title, delegating to the implementation the UI dialogs use."""
        with self._lock:
            return search_tracks(query, self._meta_ix, limit=limit)

    # -- mutation ----------------------------------------------------------

    def delete_tracks(self, track_ids: Iterable[str]) -> int:
        """Remove tracks from the library and persist the four data files.

        The replacement generation is built privately, persisted, and only
        then published to readers. Returns the number of metadata rows removed,
        which the Library tab uses to decide which status message to show.
        """
        track_ids_to_delete = set(track_ids)
        if not track_ids_to_delete:
            return 0

        with self._lock:
            original_meta_count = len(self._meta_ix)
            new_meta_ix = self._meta_ix[
                ~self._meta_ix.index.isin(track_ids_to_delete)
            ]
            deleted_count = original_meta_count - len(new_meta_ix)
            if deleted_count == 0:
                return 0

            records = [
                self._deleted_track_record(track_id)
                for track_id in track_ids_to_delete
                if track_id in self._meta_ix.index
            ]
            new_emb_ix = self._emb_ix[
                ~self._emb_ix.index.isin(track_ids_to_delete)
            ]

            remaining_positions = [
                position
                for position, track_id in enumerate(self._ids)
                if track_id not in track_ids_to_delete
            ]
            new_ids = [self._ids[position] for position in remaining_positions]
            if remaining_positions:
                new_vectors = self._vectors[remaining_positions].copy()
                new_index = NumpyCosIndex(new_vectors.shape[1])
                for track_id, vector in zip(new_ids, new_vectors):
                    new_index.add(track_id, vector)
            else:
                dimension = self._vectors.shape[1]
                new_vectors = np.empty((0, dimension), dtype=self._vectors.dtype)
                new_index = None

            new_meta = new_meta_ix.reset_index()
            new_embeddings = new_emb_ix.reset_index()

            # Preserve the DeletedTracksDialog contract, but bind it to this
            # session's data directory. A fixture session must never write the
            # configured application library's deleted_tracks.json.
            add_deleted_tracks_with_metadata(
                records, path=self.data_dir / "deleted_tracks.json"
            )
            self._persist(new_meta, new_embeddings, new_vectors, new_ids)

            # One short publication region. snapshot() takes this same lock,
            # so an export begins wholly before or wholly after these rebinds.
            self._meta = new_meta
            self._meta_ix = new_meta_ix
            self._emb_ix = new_emb_ix
            self._vectors = new_vectors
            self._ids = new_ids
            self._index = new_index
            return deleted_count

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

    def _persist(self, meta, embeddings, vectors, ids) -> None:
        """Commit one immutable four-file generation behind one pointer."""
        write_index_generation(self.data_dir, meta, embeddings, vectors, ids)
