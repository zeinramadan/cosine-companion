"""Audio processing and indexing pipeline."""

from processing.embeddings import DiscogsEffnetEmbedder
from processing.xml_parser import read_rekordbox_xml
from processing.pipeline import index_library

__all__ = [
    'DiscogsEffnetEmbedder',
    'read_rekordbox_xml',
    'index_library',
]
