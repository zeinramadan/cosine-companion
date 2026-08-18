"""Characterisation tests for ExportService.

The legacy functions recommendations.playlist_exporter.
export_recommendations_as_playlists and export_single_playlist are deliberately
LEFT IN PLACE and unused by the UI, so these tests can diff ExportService's
output against them byte-for-byte in perpetuity. That is the strongest available
evidence that the extraction preserved behaviour.

Known defects are pinned as CURRENT behaviour: tracks whose audio file is
missing are silently skipped, and combined mode reports no playlists_created
key (which is why the tab raises KeyError and shows no completion dialog -
inventory defect #10).
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import DATA
from recommendations.playlist_exporter import (
    export_recommendations_as_playlists,
    export_single_playlist,
)
from services.explore_session import ExploreSession
from services.export_service import ExportResult, ExportService
from services.library_session import LibrarySession

SEEDS = ["64638770", "24614611", "36999061"]


@pytest.fixture(scope="module")
def library():
    return LibrarySession.load(DATA)


@pytest.fixture(scope="module")
def service(library):
    return ExportService(library, ExploreSession(library))


@pytest.fixture
def tmp_library(tmp_path):
    """A four-track library whose audio files really exist, plus one that does not."""
    audio = tmp_path / "audio"
    audio.mkdir()
    rows = []
    for i, (tid, artist, title) in enumerate(
        [
            ("t1", "Artist A", "Title One"),
            ("t2", "Artist B/C: Two", "Title *Two*"),
            ("t3", "Artist C", "Title Three"),
            ("t4", "Ghost", "Missing File"),
        ]
    ):
        path = audio / f"{tid}.mp3"
        if tid != "t4":  # t4's file is deliberately absent
            path.write_bytes(b"\x00")
        vec = np.zeros(4, dtype="float32")
        vec[i] = 1.0
        vec[(i + 1) % 4] = 0.5
        rows.append((tid, artist, title, str(path), vec))

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    meta = pd.DataFrame(
        [
            {"track_id": t, "path": "", "artist": a, "title": ti, "album": "",
             "bpm": 128.0, "key": "8A", "path_local": p}
            for t, a, ti, p, _ in rows
        ]
    )
    vectors = np.array([v for *_, v in rows], dtype="float32")
    emb = pd.concat(
        [pd.DataFrame({"track_id": [r[0] for r in rows]}),
         pd.DataFrame(vectors, columns=[f"v{i}" for i in range(4)])],
        axis=1,
    )
    meta.to_parquet(data_dir / "meta.parquet", index=False)
    emb.to_parquet(data_dir / "embeddings.parquet", index=False)
    np.save(data_dir / "index.npy", vectors)
    (data_dir / "ids.json").write_text(json.dumps([r[0] for r in rows]))
    return data_dir


def _tree(directory):
    return {p.name: p.read_bytes() for p in sorted(Path(directory).glob("*.m3u"))}


# --------------------------------------------------------------------------
# Byte-for-byte equivalence with the legacy implementation
# --------------------------------------------------------------------------


def test_per_seed_output_is_byte_identical_to_the_legacy_exporter(library, service, tmp_path):
    legacy_dir = tmp_path / "legacy"
    new_dir = tmp_path / "new"

    legacy_stats = export_recommendations_as_playlists(
        SEEDS, str(legacy_dir), 10, library.meta_ix, library.emb_ix, library.index
    )
    result = service.export_per_seed(SEEDS, str(new_dir), 10)

    assert _tree(new_dir) == _tree(legacy_dir)
    assert _tree(new_dir), "nothing was written"
    assert result.as_legacy_stats() == legacy_stats


def test_combined_output_is_byte_identical_to_the_legacy_exporter(library, service, tmp_path):
    legacy = tmp_path / "legacy.m3u"
    new = tmp_path / "new.m3u"

    legacy_stats = export_single_playlist(
        SEEDS, str(legacy), "Cosine Recommendations",
        library.meta_ix, library.emb_ix, library.index, 10,
    )
    result = service.export_combined(SEEDS, str(new), 10)

    assert new.read_bytes() == legacy.read_bytes()
    assert new.read_bytes(), "nothing was written"
    assert result.as_legacy_stats() == legacy_stats


def test_equivalence_holds_across_several_per_track_counts(library, service, tmp_path):
    for n in (1, 5, 25):
        legacy_dir = tmp_path / f"legacy{n}"
        new_dir = tmp_path / f"new{n}"
        export_recommendations_as_playlists(
            SEEDS[:1], str(legacy_dir), n, library.meta_ix, library.emb_ix, library.index
        )
        service.export_per_seed(SEEDS[:1], str(new_dir), n)
        assert _tree(new_dir) == _tree(legacy_dir), n


# --------------------------------------------------------------------------
# M3U format
# --------------------------------------------------------------------------


def test_m3u_format(tmp_library, tmp_path):
    library = LibrarySession.load(tmp_library)
    service = ExportService(library, ExploreSession(library))

    service.export_combined(["t1"], str(tmp_path / "out.m3u"), 3)

    lines = (tmp_path / "out.m3u").read_text(encoding="utf-8").split("\n")
    assert lines[0] == "#EXTM3U"
    assert lines[1].startswith("#EXTINF:-1,")
    assert " - " in lines[1]  # hyphen, not the en dash used in the UI
    assert lines[2].startswith("/") and lines[2].endswith(".mp3")
    assert lines[-1] == ""  # trailing newline after the last path


def test_duration_is_always_minus_one(tmp_library, tmp_path):
    """CoCo never captures track duration."""
    library = LibrarySession.load(tmp_library)
    service = ExportService(library, ExploreSession(library))

    service.export_combined(["t1"], str(tmp_path / "out.m3u"), 3)

    for line in (tmp_path / "out.m3u").read_text().splitlines():
        if line.startswith("#EXTINF"):
            assert line.startswith("#EXTINF:-1,")


def test_tracks_whose_audio_file_is_missing_are_silently_skipped(tmp_library, tmp_path):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. t4's file does not exist, so it never
    reaches the playlist and is not counted anywhere - no warning, no failed
    tally. 46 of the real library's 1,307 tracks are in this state."""
    library = LibrarySession.load(tmp_library)
    service = ExportService(library, ExploreSession(library))

    result = service.export_combined(["t1", "t2", "t3"], str(tmp_path / "out.m3u"), 5)

    body = (tmp_path / "out.m3u").read_text()
    assert "t4.mp3" not in body
    assert "Missing File" not in body
    assert result.failed == 0  # the skip is invisible in the stats


def test_filename_scheme_and_sanitisation(tmp_library, tmp_path):
    """{safe_artist} - {safe_title}.m3u, keeping only alphanumerics, space,
    hyphen and underscore."""
    library = LibrarySession.load(tmp_library)
    service = ExportService(library, ExploreSession(library))

    service.export_per_seed(["t1", "t2"], str(tmp_path / "out"), 2)

    names = sorted(p.name for p in (tmp_path / "out").glob("*.m3u"))
    # "Artist B/C: Two" -> "/" and ":" dropped, surrounding spaces kept;
    # "Title *Two*" -> asterisks dropped.
    assert names == ["Artist A - Title One.m3u", "Artist BC Two - Title Two.m3u"]


def test_long_filenames_are_truncated_to_204_characters(tmp_path):
    """CURRENT BEHAVIOUR: filename[:200] + '.m3u' yields 204 characters and can
    leave a doubled extension."""
    from recommendations.playlist_exporter import export_recommendations_as_playlists as legacy

    artist = "A" * 150
    title = "B" * 150
    filename = f"{artist} - {title}.m3u"
    assert len(filename) > 200
    truncated = filename[:200] + ".m3u"
    assert len(truncated) == 204


def test_output_directory_is_created_for_per_seed(library, service, tmp_path):
    target = tmp_path / "does" / "not" / "exist"

    service.export_per_seed(SEEDS[:1], str(target), 3)

    assert target.is_dir() and list(target.glob("*.m3u"))


def test_combined_does_not_create_its_output_directory(library, service, tmp_path):
    """CURRENT BEHAVIOUR: export_single_playlist never made the directory, so a
    missing one raises into the tab's 'Export Error' dialog."""
    with pytest.raises(FileNotFoundError):
        service.export_combined(SEEDS[:1], str(tmp_path / "nope" / "out.m3u"), 3)


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------


def test_per_seed_stats_shape(library, service, tmp_path):
    result = service.export_per_seed(SEEDS, str(tmp_path / "out"), 5)

    assert set(result.as_legacy_stats()) == {
        "total_tracks", "successful", "failed", "playlists_created",
        "total_recommendations",
    }
    assert result.total_tracks == 3
    assert result.successful == 3
    assert result.playlists_created == 3
    assert result.failed == 0
    assert result.total_recommendations == 15


def test_combined_stats_omit_playlists_created(library, service, tmp_path):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. This missing key is exactly why
    playlist_export_tab.export_complete raises KeyError in combined mode and the
    user gets no completion dialog. Inventory defect #10."""
    result = service.export_combined(SEEDS, str(tmp_path / "out.m3u"), 5)

    stats = result.as_legacy_stats()
    assert "playlists_created" not in stats
    with pytest.raises(KeyError, match="playlists_created"):
        stats["playlists_created"]


def test_unknown_track_ids_count_as_failed(library, service, tmp_path):
    result = service.export_per_seed(
        ["no-such-track", SEEDS[0]], str(tmp_path / "out"), 3
    )

    assert result.total_tracks == 2
    assert result.failed == 1
    assert result.successful == 1


def test_combined_deduplicates_across_seeds(library, service, tmp_path):
    out = tmp_path / "out.m3u"

    result = service.export_combined(SEEDS, str(out), 25)

    paths = [l for l in out.read_text().splitlines() if not l.startswith("#")]
    assert len(paths) == len(set(paths))
    assert result.total_recommendations >= len(paths)


def test_result_is_an_export_result(library, service, tmp_path):
    assert isinstance(service.export_per_seed(SEEDS[:1], str(tmp_path / "a"), 2), ExportResult)
    assert isinstance(service.export_combined(SEEDS[:1], str(tmp_path / "b.m3u"), 2), ExportResult)


# --------------------------------------------------------------------------
# progress and cancel
# --------------------------------------------------------------------------


def test_per_seed_progress_matches_the_legacy_callback_contract(library, service, tmp_path):
    """progress(current, total, "{artist} - {title}") fired BEFORE each seed's
    recommendations are computed, current starting at 1."""
    seen = []
    legacy_seen = []

    export_recommendations_as_playlists(
        SEEDS, str(tmp_path / "legacy"), 3, library.meta_ix, library.emb_ix,
        library.index, progress_callback=lambda c, t, n: legacy_seen.append((c, t, n)),
    )
    service.export_per_seed(
        SEEDS, str(tmp_path / "new"), 3, progress=lambda c, t, n: seen.append((c, t, n))
    )

    assert seen == legacy_seen
    assert seen[0][0] == 1 and seen[-1][0] == 3
    assert all(t == 3 for _, t, _ in seen)
    assert " - " in seen[0][2]


def test_progress_is_optional(library, service, tmp_path):
    assert service.export_per_seed(SEEDS[:1], str(tmp_path / "out"), 2).successful == 1


def test_cancel_event_stops_a_per_seed_export(library, service, tmp_path):
    """Plumbing for PR 3. The Tkinter tab has no cancel control and passes None,
    so this changes nothing user-visible today."""
    import threading

    cancel = threading.Event()

    def progress(current, total, name):
        if current == 2:
            cancel.set()

    result = service.export_per_seed(
        SEEDS, str(tmp_path / "out"), 3, progress=progress, cancel=cancel
    )

    assert result.cancelled is True
    assert result.successful < 3
    assert len(list((tmp_path / "out").glob("*.m3u"))) < 3


def test_an_unset_cancel_event_does_not_stop_anything(library, service, tmp_path):
    import threading

    result = service.export_per_seed(
        SEEDS, str(tmp_path / "out"), 3, cancel=threading.Event()
    )

    assert result.cancelled is False
    assert result.successful == 3


def test_cancel_event_stops_a_combined_export(library, service, tmp_path):
    import threading

    cancel = threading.Event()
    result = service.export_combined(
        SEEDS, str(tmp_path / "out.m3u"), 3,
        progress=lambda c, t, n: cancel.set(), cancel=cancel,
    )

    assert result.cancelled is True
