"""Characterisation tests for IndexingService.

This is the one place in PR 2 where a MECHANISM changes. Progress used to be
reported by replacing the process-global sys.stdout with a queue writer from a
worker thread (reindex_window.py:164-194, onboarding.py:400-416). It is now a
structured callback. The plan sanctions exactly this change, and the constraint
is that the UI must display the same information as before - so every one of the
37 print sites reachable during indexing (processing/pipeline.py, core/loader.py,
core/deleted_tracks.py) emits an event carrying the IDENTICAL string.

Essentia is never loaded here: the embedder is mocked. A real indexing pass over
real audio is a separate manual check, recorded in the PR description.
"""

import os
import sys
import threading
from urllib.parse import quote

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lxml", reason="processing.xml_parser needs lxml to read the fixture XML")

import core.deleted_tracks as deleted_tracks_module  # noqa: E402
import core.loader as loader_module  # noqa: E402
import core.persistence as persistence_module  # noqa: E402
import processing.pipeline as pipeline_module  # noqa: E402
from services.indexing_service import (  # noqa: E402
    STATUS_INDEXED,
    STATUS_NO_EMBEDDINGS,
    STATUS_UP_TO_DATE,
    IndexingService,
    IndexResult,
    ProgressEvent,
)
from services.settings_store import SettingsStore  # noqa: E402

DIM = 8

SEPARATOR = "=" * 50


class FakeEmbedder:
    """Stands in for DiscogsEffnetEmbedder. Never touches Essentia."""

    instances = 0

    def __init__(self, *args, **kwargs):
        FakeEmbedder.instances += 1
        self.embedded = []

    def embed_file(self, path_local):
        self.embedded.append(path_local)
        # Match the FILE NAME, not the path: pytest's tmp directory for
        # test_missing_and_broken_files_are_reported is itself called
        # "test_missing_and_broken_files_0".
        if os.path.basename(path_local).startswith("broken"):
            return None  # the decode-failure path
        vector = np.zeros(DIM, dtype="float32")
        vector[len(self.embedded) % DIM] = 1.0
        return vector


def _write_xml(path, tracks):
    entries = "".join(
        f'<TRACK TrackID="{tid}" Name="{name}" Artist="{artist}" '
        f'AverageBpm="128.00" Tonality="8A" Album="" '
        f'Location="file://localhost{quote(str(loc))}"/>'
        for tid, name, artist, loc in tracks
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="{len(tracks)}">'
        f"{entries}</COLLECTION></DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def indexing(tmp_path, monkeypatch):
    """An isolated data directory, a fixture XML and a mocked embedder."""
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
    monkeypatch.setattr(deleted_tracks_module, "DELETED_TRACKS_JSON", data / "deleted.json")
    monkeypatch.setattr(pipeline_module, "DiscogsEffnetEmbedder", FakeEmbedder)
    monkeypatch.setattr(pipeline_module, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))

    tracks = []
    for i in range(1, 6):
        f = audio / f"track{i}.mp3"
        f.write_bytes(b"\x00")
        tracks.append((str(1000 + i), f"Title {i}", f"Artist {i}", f))
    xml = _write_xml(tmp_path / "library.xml", tracks)

    service = IndexingService(SettingsStore(data / "settings.json"))
    return service, xml, data, audio


def collect(service, xml, **kw):
    events = []
    result = service.run(str(xml), progress=events.append, **kw)
    return result, events


# --------------------------------------------------------------------------
# Structured progress replaces the stdout swap
# --------------------------------------------------------------------------


def test_run_never_writes_to_stdout(indexing, capsys):
    """The whole point of the mechanism change. reindex_window used to swap
    sys.stdout process-wide from a worker thread to capture these lines."""
    service, xml, _, _ = indexing

    service.run(str(xml), progress=lambda e: None)

    captured = capsys.readouterr()
    assert captured.out == ""


def test_run_does_not_replace_sys_stdout(indexing):
    service, xml, _, _ = indexing
    before = sys.stdout

    service.run(str(xml), progress=lambda e: None)

    assert sys.stdout is before


def test_emits_progress_events(indexing):
    service, xml, _, _ = indexing

    _, events = collect(service, xml)

    assert events
    assert all(isinstance(e, ProgressEvent) for e in events)
    assert all(isinstance(e.phase, str) and isinstance(e.message, str) for e in events)


def test_embed_events_carry_real_current_and_total(indexing):
    """The pipeline has always known i/N; it just never reported it, which is
    why the progress bar is indeterminate (spec 3.2). The service now supplies
    it; making the bar determinate is PR 3 work."""
    service, xml, _, _ = indexing

    _, events = collect(service, xml)

    per_track = [e for e in events if e.phase == "embed" and e.message.startswith("   [")]
    assert [e.current for e in per_track] == [1, 2, 3, 4, 5]
    assert all(e.total == 5 for e in per_track)
    # The closing summary is also an embed-phase event, at current == total.
    summary = [e for e in events if e.message.startswith("✨")]
    assert (summary[0].phase, summary[0].current, summary[0].total) == ("embed", 5, 5)


def test_non_embed_events_report_zero_progress(indexing):
    service, xml, _, _ = indexing

    _, events = collect(service, xml)

    for e in events:
        if e.phase != "embed":
            assert (e.current, e.total) == (0, 0), e


def test_phases_appear_in_pipeline_order(indexing):
    service, xml, _, _ = indexing

    _, events = collect(service, xml)

    order = []
    for e in events:
        if not order or order[-1] != e.phase:
            order.append(e.phase)
    assert order == ["start", "read_xml", "duplicates", "deleted", "plan",
                     "embed", "merge", "complete"], order


# --------------------------------------------------------------------------
# The UI must display the same information as before
# --------------------------------------------------------------------------


def timeline(events):
    """The complete ordered event list: (phase, current, total, message)."""
    return [(e.phase, e.current, e.total, e.message) for e in events]


def data_saved_line():
    from config import DATA

    return f"   • Data saved to: {DATA}/"


def test_a_first_run_emits_exactly_this_ordered_event_list(indexing):
    """THE COMPLETE, ORDERED timeline - not a subset.

    This test used to assert `"..." in messages` for a dozen strings, which
    passes even if messages are lost, reordered or duplicated: the log pane is a
    transcript, and a transcript with the right lines in the wrong order is
    wrong. Every event, in order, with its phase and its current/total.
    """
    service, xml, _, _ = indexing

    _, events = collect(service, xml)

    assert timeline(events) == [
        ("start", 0, 0, "🎵 Cosine Companion - Incremental Indexing"),
        ("start", 0, 0, SEPARATOR),
        ("read_xml", 0, 0, "📖 Reading Rekordbox XML..."),
        ("read_xml", 0, 0, "   Found 5 tracks in XML"),
        ("duplicates", 0, 0, "🔍 Checking for duplicate tracks..."),
        ("duplicates", 0, 0, "   No duplicates found"),
        ("deleted", 0, 0, "🔍 Checking for previously deleted tracks..."),
        # "Found N new tracks to process" is absent on a first run: find_new_tracks
        # returns early WITHOUT reporting when there is no existing data.
        ("plan", 0, 0, "🎯 Processing 5 new tracks..."),
        ("embed", 1, 5, "   [  1/5] Artist 1 - Title 1"),
        ("embed", 2, 5, "   [  2/5] Artist 2 - Title 2"),
        ("embed", 3, 5, "   [  3/5] Artist 3 - Title 3"),
        ("embed", 4, 5, "   [  4/5] Artist 4 - Title 4"),
        ("embed", 5, 5, "   [  5/5] Artist 5 - Title 5"),
        ("embed", 5, 5, "✨ Generated 5 new embeddings"),
        ("merge", 0, 0, "🔄 Merging with existing data..."),
        ("complete", 0, 0, SEPARATOR),
        ("complete", 0, 0, "✅ Indexing complete!"),
        ("complete", 0, 0, "   • Total tracks indexed: 5"),
        ("complete", 0, 0, "   • New tracks added: 5"),
        ("complete", 0, 0, data_saved_line()),
        ("complete", 0, 0, "🚀 Ready to use! Run 'python cosine_companion.py ui' to start the application."),
    ]


def test_an_up_to_date_run_emits_exactly_this_ordered_event_list(indexing):
    service, xml, _, _ = indexing
    service.run(str(xml), progress=lambda e: None)  # first pass creates data

    _, events = collect(service, xml)

    assert timeline(events) == [
        ("start", 0, 0, "🎵 Cosine Companion - Incremental Indexing"),
        ("start", 0, 0, SEPARATOR),
        ("start", 0, 0, "Found existing data: 5 tracks already indexed"),
        ("read_xml", 0, 0, "📖 Reading Rekordbox XML..."),
        ("read_xml", 0, 0, "   Found 5 tracks in XML"),
        ("duplicates", 0, 0, "🔍 Checking for duplicate tracks..."),
        ("duplicates", 0, 0, "   No duplicates found"),
        ("deleted", 0, 0, "🔍 Checking for previously deleted tracks..."),
        ("plan", 0, 0, "Found 0 new tracks to process"),
        ("complete", 0, 0, "✅ No new tracks to process! Your index is up to date."),
    ]


def test_a_full_reindex_emits_exactly_this_ordered_event_list(indexing):
    service, xml, _, _ = indexing
    service.run(str(xml), progress=lambda e: None)

    _, events = collect(service, xml, force_full=True)

    assert timeline(events)[:4] == [
        ("start", 0, 0, "🎵 Cosine Companion - Full Reindex"),
        ("start", 0, 0, SEPARATOR),
        # No "Found existing data" line: force_full skips load_existing_data.
        ("start", 0, 0, "🔄 Force full reindex requested - ignoring existing data"),
        ("read_xml", 0, 0, "📖 Reading Rekordbox XML..."),
    ]
    assert timeline(events)[-1] == (
        "complete", 0, 0,
        "🚀 Ready to use! Run 'python cosine_companion.py ui' to start the application.",
    )
    assert ("embed", 5, 5, "✨ Generated 5 new embeddings") in timeline(events)


def test_a_run_where_nothing_can_be_embedded_emits_exactly_this_list(indexing, tmp_path):
    service, _, _, audio = indexing
    missing = audio / "gone.mp3"  # never created
    xml = _write_xml(tmp_path / "allbad.xml", [("3001", "Gone", "C", missing)])

    _, events = collect(service, xml)

    assert timeline(events) == [
        ("start", 0, 0, "🎵 Cosine Companion - Incremental Indexing"),
        ("start", 0, 0, SEPARATOR),
        ("read_xml", 0, 0, "📖 Reading Rekordbox XML..."),
        ("read_xml", 0, 0, "   Found 1 tracks in XML"),
        ("duplicates", 0, 0, "🔍 Checking for duplicate tracks..."),
        ("duplicates", 0, 0, "   No duplicates found"),
        ("deleted", 0, 0, "🔍 Checking for previously deleted tracks..."),
        ("plan", 0, 0, "🎯 Processing 1 new tracks..."),
        ("embed", 1, 1, "   [  1/1] C - Gone"),
        ("embed", 1, 1, f"      ⚠️  File not found: {missing}"),
        ("complete", 0, 0, "❌ No new embeddings generated. Check audio paths/codecs."),
    ]


def test_no_message_is_lost_reordered_or_duplicated(indexing):
    """What the subset assertion could not see: the ordered list above would
    still contain every expected string if two of them swapped places."""
    service, xml, _, _ = indexing

    _, events = collect(service, xml)
    messages = [e.message for e in events]

    assert len(messages) == len(set(messages)) + 1  # only SEPARATOR repeats
    assert messages.count(SEPARATOR) == 2
    assert messages.index("🎯 Processing 5 new tracks...") < messages.index(
        "   [  1/5] Artist 1 - Title 1"
    )


def test_per_track_message_keeps_its_exact_padding_and_hyphen(indexing):
    service, xml, _, _ = indexing

    _, events = collect(service, xml)

    embed = [e for e in events if e.phase == "embed" and e.message.startswith("   [")]
    assert embed[0].message == "   [  1/5] Artist 1 - Title 1"
    assert embed[4].message == "   [  5/5] Artist 5 - Title 5"


def test_no_blank_messages_are_emitted(indexing):
    """The QueueWriter dropped blank lines, so the pipeline's bare print() never
    reached the log pane. Preserved."""
    service, xml, _, _ = indexing

    _, events = collect(service, xml)

    assert all(e.message.strip() for e in events)


def test_full_reindex_announces_itself(indexing):
    service, xml, _, _ = indexing

    _, events = collect(service, xml, force_full=True)
    messages = [e.message for e in events]

    assert messages[0] == "🎵 Cosine Companion - Full Reindex"
    assert "🔄 Force full reindex requested - ignoring existing data" in messages


def test_messages_from_core_modules_are_forwarded_too(indexing):
    """load_existing_data, find_new_tracks and filter_deleted_tracks all print,
    and all of it used to reach the log pane through the stdout swap."""
    service, xml, data, _ = indexing
    service.run(str(xml), progress=lambda e: None)  # first pass creates data

    _, events = collect(service, xml)
    messages = [e.message for e in events]

    assert "Found existing data: 5 tracks already indexed" in messages  # core.loader
    assert "Found 0 new tracks to process" in messages                  # core.loader
    assert "✅ No new tracks to process! Your index is up to date." in messages


def test_deleted_track_filtering_is_reported(indexing):
    service, xml, data, _ = indexing
    from core.deleted_tracks import add_deleted_tracks_with_metadata

    add_deleted_tracks_with_metadata([{"track_id": "1001", "artist": "A", "title": "T"}])

    _, events = collect(service, xml)

    assert "   Filtered out 1 previously deleted tracks" in [e.message for e in events]


def test_missing_and_broken_files_are_reported(indexing, tmp_path):
    service, _, _, audio = indexing
    good = audio / "track1.mp3"
    broken = audio / "broken.mp3"
    broken.write_bytes(b"\x00")
    missing = audio / "gone.mp3"  # never created
    xml = _write_xml(tmp_path / "mixed.xml", [
        ("2001", "Good", "A", good),
        ("2002", "Broken", "B", broken),
        ("2003", "Gone", "C", missing),
    ])

    _, events = collect(service, xml)
    messages = [e.message for e in events]

    assert f"      ⚠️  File not found: {missing}" in messages
    assert (f"      ⚠️  Failed to process audio file "
            f"(unsupported codec or decode error): {broken}") in messages
    assert "✨ Generated 1 new embeddings" in messages


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------


def test_cancel_stops_the_run(indexing):
    service, xml, _, _ = indexing
    cancel = threading.Event()
    events = []

    def progress(event):
        events.append(event)
        if event.phase == "embed" and event.current == 2:
            cancel.set()

    with pytest.raises(KeyboardInterrupt, match="User cancelled indexing"):
        service.run(str(xml), progress=progress, cancel=cancel)

    assert "⚠️ Cancellation detected, stopping..." in [e.message for e in events]
    assert max(e.current for e in events if e.phase == "embed") < 5


def test_cancel_raises_keyboardinterrupt_which_is_not_an_exception(indexing):
    """CURRENT BEHAVIOUR, NOT A BUG FIX, and subtle enough to pin.

    TIMING A of inventory Sec 2.13: the flag is set while a per-track checkpoint
    still lies ahead. KeyboardInterrupt derives from BaseException, so
    reindex_window's `except Exception` does NOT catch it. The worker thread
    dies with an unhandled exception, neither a 'cancelled' nor a 'complete'
    message is queued, and the "⚠️ Indexing cancelled by user" log line is not
    appended. The window still shows the cancelled state, because
    cancel_indexing() set the flag that check_indexing_status reads. Changing
    this would alter what the user sees. Spec 3.2 / inventory defect #4.

    This is NOT universal. See
    test_a_cancel_first_observed_after_the_last_checkpoint_does_not_stop_the_run
    for timing B, where no KeyboardInterrupt is raised at all."""
    service, xml, _, _ = indexing
    cancel = threading.Event()
    cancel.set()

    assert not issubclass(KeyboardInterrupt, Exception)
    with pytest.raises(KeyboardInterrupt):
        service.run(str(xml), progress=lambda e: None, cancel=cancel)


def test_cancel_discards_every_embedding_computed_so_far(indexing):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. A cancelled run keeps nothing; the
    6.8-minute full run loses everything. Keeping partial work is PR 3 work
    (spec 5.4)."""
    service, xml, data, _ = indexing
    cancel = threading.Event()

    def progress(event):
        if event.phase == "embed" and event.current == 3:
            cancel.set()

    with pytest.raises(KeyboardInterrupt):
        service.run(str(xml), progress=progress, cancel=cancel)

    assert not (data / "meta.parquet").exists()
    assert not (data / "index.npy").exists()


def test_an_unset_cancel_event_does_not_stop_anything(indexing):
    service, xml, data, _ = indexing

    result = service.run(str(xml), progress=lambda e: None, cancel=threading.Event())

    assert result.new_tracks_added == 5
    assert (data / "meta.parquet").exists()


class LateCancel:
    """A cancel token that reports False for the first ``n`` reads, True after.

    ``IndexingService`` passes ``cancel.is_set`` to the pipeline, so this stands
    in for a ``threading.Event`` whose flag is first set at a chosen point in the
    checkpoint sequence. With ``n`` equal to the number of tracks, every one of
    the loop's checkpoints reads False and the flag "becomes set" only after the
    loop is over - which is exactly the interleaving a real user produces by
    clicking Cancel during the last track's embed or during the merge/write.
    """

    def __init__(self, n):
        self.n = n
        self.reads = 0

    def is_set(self):
        self.reads += 1
        return self.reads > self.n


def test_a_cancel_first_observed_after_the_last_checkpoint_does_not_stop_the_run(indexing):
    """TIMING B, inventory defect #17. CURRENT BEHAVIOUR, NOT A BUG FIX.

    cancel_check is read in exactly one place - pipeline.py:182, at the top of
    each per-track loop iteration. The fixture has 5 tracks, so there are exactly
    5 checkpoints. A flag that only becomes set on the 6th read is never observed
    by the pipeline: no KeyboardInterrupt, no "⚠️ Cancellation detected,
    stopping..." line, and the run persists all four data files.

    reindex_window then evaluates `if self.cancel_requested:` - True - and
    appends "⚠️ Indexing cancelled by user". The UI half of that is pinned in
    tests/test_ui_reports_success_for_every_terminal_outcome.py.
    """
    service, xml, data, _ = indexing
    cancel = LateCancel(n=5)
    events = []

    result = service.run(str(xml), progress=events.append, cancel=cancel)

    # The pipeline consulted the token once per track and then stopped asking.
    assert cancel.reads == 5
    assert cancel.is_set() is True, "the token is set by now; the pipeline just never re-reads it"

    assert result.status == STATUS_INDEXED
    assert result.new_tracks_added == 5
    assert "⚠️ Cancellation detected, stopping..." not in [e.message for e in events]

    # ... and the data WAS written, contradicting "a cancelled run leaves nothing".
    for name in ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json"):
        assert (data / name).exists(), f"{name} missing; timing B must persist"


def test_the_pipeline_reads_the_cancel_token_once_per_track_and_nowhere_else(indexing):
    """The load-bearing fact behind defect #17, stated directly.

    If a future edit adds a second cancel checkpoint - in the merge, in the
    persist, anywhere - this read count changes and the timing-B analysis in
    inventory Sec 2.13 stops being true. That is a behaviour change and it must
    be deliberate, so it fails here first.
    """
    service, xml, _, _ = indexing
    cancel = LateCancel(n=10 ** 6)  # never sets

    service.run(str(xml), progress=lambda e: None, cancel=cancel)

    assert cancel.reads == 5, (
        "expected exactly one cancel_check per track (5 tracks, 5 reads); "
        f"got {cancel.reads}. A checkpoint was added or removed"
    )


def test_a_cancel_during_an_up_to_date_run_is_never_observed(indexing):
    """TIMING B via STATUS_UP_TO_DATE (inventory workflow 34f).

    When there are no new tracks the pipeline returns at pipeline.py:169-170,
    before the loop. There is no checkpoint at all, so a cancel set at ANY moment
    of such a run - even before it starts - is ignored, and the run reports
    up_to_date. No data files are written on this path.
    """
    service, xml, _, _ = indexing
    first = service.run(str(xml), progress=lambda e: None)
    assert first.status == STATUS_INDEXED

    # Re-run against the same XML with an ALREADY-SET cancel event. There are no
    # new tracks, so the loop never runs and the flag is never read.
    already_set = threading.Event()
    already_set.set()
    events = []
    result = service.run(str(xml), progress=events.append, cancel=already_set)

    assert result.status == STATUS_UP_TO_DATE
    assert "⚠️ Cancellation detected, stopping..." not in [e.message for e in events]
    assert "✅ No new tracks to process! Your index is up to date." in [
        e.message for e in events
    ]


# --------------------------------------------------------------------------
# Result and persistence
# --------------------------------------------------------------------------


def test_returns_an_index_result(indexing):
    service, xml, _, _ = indexing

    result = service.run(str(xml), progress=lambda e: None)

    assert isinstance(result, IndexResult)
    assert result.status == STATUS_INDEXED
    assert result.total_tracks_indexed == 5
    assert result.new_tracks_added == 5
    assert result.new_tracks_found == 5
    assert result.up_to_date is False
    assert result.failed is False


def test_second_run_finds_nothing_new(indexing):
    service, xml, _, _ = indexing
    service.run(str(xml), progress=lambda e: None)

    result = service.run(str(xml), progress=lambda e: None)

    assert result.new_tracks_added == 0


# --------------------------------------------------------------------------
# The two empty outcomes are DIFFERENT
#
# Both used to return a bare None from index_library and surface as
# up_to_date=True, so a run in which new tracks existed and not one of them
# could be embedded reported itself as a success. PR 3 consumes this API.
# --------------------------------------------------------------------------


def test_an_up_to_date_run_says_up_to_date(indexing):
    service, xml, _, _ = indexing
    service.run(str(xml), progress=lambda e: None)

    result = service.run(str(xml), progress=lambda e: None)

    assert result.status == STATUS_UP_TO_DATE
    assert result.up_to_date is True
    assert result.failed is False
    assert result.new_tracks_found == 0
    assert result.new_tracks_added == 0


def test_a_run_where_nothing_could_be_embedded_is_not_up_to_date(indexing, tmp_path):
    """Three tracks, every file missing. The index gained nothing and the user
    needs to know - this is a failure, not an up-to-date index."""
    service, _, data, audio = indexing
    xml = _write_xml(tmp_path / "allbad.xml", [
        ("3001", "Gone", "A", audio / "missing1.mp3"),
        ("3002", "Gone", "B", audio / "missing2.mp3"),
        ("3003", "Gone", "C", audio / "missing3.mp3"),
    ])

    result = service.run(str(xml), progress=lambda e: None)

    assert result.status == STATUS_NO_EMBEDDINGS
    assert result.up_to_date is False
    assert result.failed is True
    assert result.new_tracks_found == 3
    assert result.new_tracks_added == 0
    assert not (data / "meta.parquet").exists()


def test_the_two_empty_outcomes_are_distinguishable(indexing, tmp_path):
    """The regression itself: these two runs must not compare equal."""
    service, xml, _, audio = indexing
    service.run(str(xml), progress=lambda e: None)

    up_to_date = service.run(str(xml), progress=lambda e: None)
    nothing_embeddable = service.run(
        str(_write_xml(tmp_path / "bad.xml", [("4001", "Gone", "A", audio / "nope.mp3")])),
        progress=lambda e: None,
    )

    assert up_to_date.status != nothing_embeddable.status
    assert up_to_date.up_to_date and not nothing_embeddable.up_to_date
    assert nothing_embeddable.failed and not up_to_date.failed
    assert up_to_date != nothing_embeddable


def test_the_service_statuses_match_the_pipelines(indexing):
    """The service mirrors the constants rather than importing them, so that
    importing it stays free of Essentia. They must not drift apart."""
    import processing.pipeline as pipeline

    assert STATUS_INDEXED == pipeline.STATUS_INDEXED
    assert STATUS_UP_TO_DATE == pipeline.STATUS_UP_TO_DATE
    assert STATUS_NO_EMBEDDINGS == pipeline.STATUS_NO_EMBEDDINGS
    assert len({STATUS_INDEXED, STATUS_UP_TO_DATE, STATUS_NO_EMBEDDINGS}) == 3


def test_writes_the_four_data_files(indexing):
    service, xml, data, _ = indexing

    service.run(str(xml), progress=lambda e: None)

    for name in ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json"):
        assert (data / name).exists(), name
    assert len(pd.read_parquet(data / "meta.parquet")) == 5
    assert np.load(data / "index.npy").shape == (5, DIM)


def test_the_embedder_is_only_constructed_when_there_is_work(indexing):
    service, xml, _, _ = indexing
    service.run(str(xml), progress=lambda e: None)
    before = FakeEmbedder.instances

    service.run(str(xml), progress=lambda e: None)

    assert FakeEmbedder.instances == before


# --------------------------------------------------------------------------
# The CLI keeps printing
# --------------------------------------------------------------------------


def test_pipeline_still_prints_when_no_callback_is_given(indexing, capsys):
    """python cosine_companion.py index <xml> must be unchanged."""
    from processing.pipeline import index_library

    _, xml, _, _ = indexing
    index_library(str(xml))

    out = capsys.readouterr().out
    assert "🎵 Cosine Companion - Incremental Indexing" in out
    assert "   [  1/5] Artist 1 - Title 1" in out
    assert "✅ Indexing complete!" in out
    assert out.endswith(
        "🚀 Ready to use! Run 'python cosine_companion.py ui' to start the application.\n"
    )


def test_settings_store_is_available_to_the_service(indexing):
    service, _, data, _ = indexing

    service.settings.set("xml_path", "/tmp/library.xml")

    assert service.settings.xml_path == "/tmp/library.xml"
