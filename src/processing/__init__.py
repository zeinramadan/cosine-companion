"""Audio processing and indexing pipeline.

``DiscogsEffnetEmbedder`` is re-exported **lazily**. Importing it executes
``import essentia.standard``, which loads TensorFlow - roughly 483 MB and
several seconds - and that must not happen merely because something imported
this package. Only an actual indexing run needs the embedder, so the import is
deferred to first attribute access (PEP 562).

``from processing import DiscogsEffnetEmbedder`` still works and still returns
the same class; it just pays the cost at that moment rather than at package
import. See tests/test_services_are_lightweight.py.
"""

from processing.xml_parser import read_rekordbox_xml
from processing.pipeline import index_library

__all__ = [
    'DiscogsEffnetEmbedder',
    'read_rekordbox_xml',
    'index_library',
]


def __getattr__(name):
    if name == 'DiscogsEffnetEmbedder':
        from processing.embeddings import DiscogsEffnetEmbedder

        return DiscogsEffnetEmbedder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
