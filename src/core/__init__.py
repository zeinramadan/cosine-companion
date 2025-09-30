"""Core data management and indexing functionality."""

from core.loader import load_all, load_existing_data, find_new_tracks
from core.persistence import save_index_data, merge_embeddings
from core.index_builder import FaissCosIndex, build_faiss_index
from core.duplicates import remove_simple_duplicates

__all__ = [
    'load_all',
    'load_existing_data',
    'save_index_data',
    'merge_embeddings',
    'FaissCosIndex',
    'build_faiss_index',
    'remove_simple_duplicates',
    'find_new_tracks',
]
