"""The pipeline's playlist refresh, pinned at each of its three call sites.

WHY THIS FILE EXISTS
--------------------
``processing.pipeline.index_library`` calls ``refresh_playlists`` at every
terminal outcome, so a normal reindex keeps the playlist tables current without
the user running a second command. Nothing tested that. Deleting all three
calls left the entire suite - 782 tests at the time of writing, including all
35 in ``test_indexing_service.py`` - green.

It was invisible for a reason worth writing down: every XML those tests build
has a ``<COLLECTION>`` and NO ``<PLAYLISTS>`` element, so the refresh they do
run imports nothing, writes three near-empty files nobody looks at, and is
indistinguishable from not running. The fixtures here carry real playlists,
which is the whole difference.

ONE TEST PER CALL SITE, AND EACH ONE ISOLATES ITS OWN
-----------------------------------------------------
Each test deletes the three playlist files immediately before the run it is
about, so only that run can put them back. Removing any single call turns
exactly one test red rather than all three - which is what makes this a test of
the integration rather than of the importer, and what stops a partial deletion
hiding behind the other two.

Essentia is never loaded: the embedder is mocked, exactly as in
``test_indexing_service.py``.
"""

import os
import sys
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pytest

pytest.importorskip("lxml", reason="the pipeline needs lxml to read the fixture XML")

import core.deleted_tracks as deleted_tracks_module  # noqa: E402
import core.loader as loader_module  # noqa: E402
import core.persistence as persistence_module  # noqa: E402
import processing.pipeline as pipeline_module  # noqa: E402
from core.playlist_store import (  # noqa: E402
    MEMBERSHIP_FILENAME,
    PLAYLISTS_FILENAME,
    PROVENANCE_FILENAME,
)
from services.indexing_service import (  # noqa: E402
    STATUS_INDEXED,
    STATUS_NO_EMBEDDINGS,
    STATUS_UP_TO_DATE,
    IndexingService,
)
from services.playlist_service import PlaylistService  # noqa: E402
from services.settings_store import SettingsStore  # noqa: E402

DIM = 8

#: Two tracks, and three playlists in two folders wrapped in the ROOT container
#: Rekordbox always emits. Worked out by hand and asserted as a literal below:
#: ``2001`` is in "warmup" and in "peak", ``2002`` is in "peak" only, and
#: "empty shelf" holds nobody.
TRACK_IDS = ("2001", "2002")

EXPECTED_PLAYLISTS = {
    "2001": ((("Sets",), "warmup"), (("Sets", "Late"), "peak")),
    "2002": ((("Sets", "Late"), "peak"),),
}


class FakeEmbedder:
    """Stands in for DiscogsEffnetEmbedder. Never touches Essentia."""

    def __init__(self, *args, **kwargs):
        self.embedded = []

    def embed_file(self, path_local):
        self.embedded.append(path_local)
        if not os.path.exists(path_local):
            return None
        vector = np.zeros(DIM, dtype="float32")
        vector[len(self.embedded) % DIM] = 1.0
        return vector


def write_xml_with_playlists(path, tracks):
    """A Rekordbox export carrying BOTH halves: a collection and playlists."""
    entries = "".join(
        f'<TRACK TrackID="{tid}" Name="{name}" Artist="{artist}" '
        f'AverageBpm="128.00" Tonality="8A" Album="" '
        f'Location="file://localhost{quote(str(loc))}"/>'
        for tid, name, artist, loc in tracks
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="{len(tracks)}">'
        f"{entries}</COLLECTION>"
        '<PLAYLISTS><NODE Type="0" Name="ROOT" Count="1">'
        '<NODE Type="0" Name="Sets" Count="2">'
        '<NODE Type="1" Name="warmup" Entries="1" KeyType="0">'
        '<TRACK Key="2001"/></NODE>'
        '<NODE Type="0" Name="Late" Count="2">'
        '<NODE Type="1" Name="peak" Entries="2" KeyType="0">'
        '<TRACK Key="2001"/><TRACK Key="2002"/></NODE>'
        '<NODE Type="1" Name="empty shelf" Entries="0" KeyType="0"/>'
        "</NODE></NODE></NODE></PLAYLISTS>"
        "</DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def indexing(tmp_path, monkeypatch):
    """An isolated data directory, an export WITH playlists, a mocked embedder.

    The monkeypatched attributes are the ones ``test_indexing_service.py``
    patches, for the same reason: these tests must never read or write the
    maintainer's real library, and ``refresh_playlists`` derives its data
    directory from ``persistence.META_PQ`` precisely so that patching it is
    enough.
    """
    data = tmp_path / "data"
    data.mkdir()
    audio = tmp_path / "audio"
    audio.mkdir()

    monkeypatch.setattr(loader_module, "META_PQ", data / "meta.parquet")
    monkeypatch.setattr(loader_module, "EMB_PQ", data / "embeddings.parquet")
    monkeypatch.setattr(persistence_module, "META_PQ", data / "meta.parquet")
    monkeypatch.setattr(persistence_module, "EMB_PQ", data / "embeddings.parquet")
    monkeypatch.setattr(persistence_module, "IDX_NPY", data / "index.npy")
    monkeypatch.setattr(persistence_module, "IDS_JSON", data / "ids.json")
    monkeypatch.setattr(
        deleted_tracks_module, "DELETED_TRACKS_JSON", data / "deleted.json"
    )
    monkeypatch.setattr(pipeline_module, "DiscogsEffnetEmbedder", FakeEmbedder)
    monkeypatch.setattr(
        pipeline_module, "time", type("T", (), {"sleep": staticmethod(lambda s: None)})
    )

    tracks = []
    for index, track_id in enumerate(TRACK_IDS, start=1):
        audio_file = audio / f"track{index}.mp3"
        audio_file.write_bytes(b"\x00")
        tracks.append((track_id, f"Title {index}", f"Artist {index}", audio_file))
    xml = write_xml_with_playlists(tmp_path / "library.xml", tracks)

    service = IndexingService(SettingsStore(data / "settings.json"))
    return service, xml, data, audio


def clear_playlist_files(data):
    """Remove the three files, so only the NEXT run can put them back."""
    for name in (PLAYLISTS_FILENAME, MEMBERSHIP_FILENAME, PROVENANCE_FILENAME):
        path = data / name
        if path.exists():
            path.unlink()
    assert not any(
        (data / name).exists()
        for name in (PLAYLISTS_FILENAME, MEMBERSHIP_FILENAME, PROVENANCE_FILENAME)
    )


def assert_playlists_were_imported(data, xml):
    """All three files present, holding the playlists written by hand above."""
    for name in (PLAYLISTS_FILENAME, MEMBERSHIP_FILENAME, PROVENANCE_FILENAME):
        assert (data / name).is_file(), f"{name} was not written beside meta.parquet"

    service = PlaylistService(data)
    assert service.imported is True
    assert service.provenance.source_xml == str(Path(xml).resolve())

    for track_id, expected in EXPECTED_PLAYLISTS.items():
        found = service.playlists_for(track_id)
        assert found is not None, track_id
        assert tuple((ref.folder_path, ref.name) for ref in found) == expected


def run(service, xml):
    return service.run(str(xml), progress=lambda event: None)


def test_the_indexed_outcome_refreshes_playlists(indexing):
    """pipeline.py: the refresh after ``save_index_data``."""
    service, xml, data, _ = indexing
    clear_playlist_files(data)

    result = run(service, xml)

    assert result.status == STATUS_INDEXED
    assert_playlists_were_imported(data, xml)


def test_the_up_to_date_outcome_refreshes_playlists(indexing):
    """pipeline.py: the refresh on the "no new tracks" path.

    The files are cleared BETWEEN the two runs, so the first run's refresh
    cannot stand in for the second one's.
    """
    service, xml, data, _ = indexing
    assert run(service, xml).status == STATUS_INDEXED
    clear_playlist_files(data)

    result = run(service, xml)

    assert result.status == STATUS_UP_TO_DATE
    assert_playlists_were_imported(data, xml)


def test_the_no_embeddings_outcome_refreshes_playlists(indexing, tmp_path):
    """pipeline.py: the refresh on the "nothing could be embedded" path.

    A run that indexes nothing still tells the truth about playlists - and this
    is the outcome where a user is most likely to open the drawer looking for
    an explanation.
    """
    service, _, data, audio = indexing
    xml = write_xml_with_playlists(
        tmp_path / "allbad.xml",
        [(track_id, "Gone", "X", audio / f"missing-{track_id}.mp3")
         for track_id in TRACK_IDS],
    )
    clear_playlist_files(data)

    result = run(service, xml)

    assert result.status == STATUS_NO_EMBEDDINGS
    assert not (data / "meta.parquet").exists()
    assert_playlists_were_imported(data, xml)


def test_a_playlist_import_failure_never_fails_the_run(indexing, monkeypatch):
    """The refresh is best-effort by design: the four index files are already
    written by the time it runs, and a malformed <PLAYLISTS> element is not a
    reason to tell the user an 11-minute embed did not happen."""
    service, xml, data, _ = indexing

    def explode(*args, **kwargs):
        raise RuntimeError("malformed export")

    import services.playlist_import as playlist_import

    monkeypatch.setattr(playlist_import, "import_playlists", explode)

    events = []
    result = service.run(str(xml), progress=events.append)

    assert result.status == STATUS_INDEXED
    assert (data / "meta.parquet").is_file()
    assert any("Could not import playlists" in event.message for event in events)
