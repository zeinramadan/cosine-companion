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

import hashlib
import json
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
from services.library_session import LibrarySession  # noqa: E402
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

    monkeypatch.setattr(
        deleted_tracks_module,
        "DELETED_TRACKS_JSON",
        data / "deleted_tracks.json",
    )
    monkeypatch.setattr(pipeline_module, "DiscogsEffnetEmbedder", FakeEmbedder)
    monkeypatch.setattr(pipeline_module, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))

    tracks = []
    for i in range(1, 6):
        f = audio / f"track{i}.mp3"
        f.write_bytes(b"\x00")
        tracks.append((str(1000 + i), f"Title {i}", f"Artist {i}", f))
    xml = _write_xml(tmp_path / "library.xml", tracks)

    service = IndexingService(
        SettingsStore(data / "settings.json"), data_dir=data
    )
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


def data_saved_line(data_dir):
    return f"   • Data saved to: {data_dir}/"


def test_a_first_run_emits_exactly_this_ordered_event_list(indexing):
    """THE COMPLETE, ORDERED timeline - not a subset.

    This test used to assert `"..." in messages` for a dozen strings, which
    passes even if messages are lost, reordered or duplicated: the log pane is a
    transcript, and a transcript with the right lines in the wrong order is
    wrong. Every event, in order, with its phase and its current/total.
    """
    service, xml, data, _ = indexing

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
        ("complete", 0, 0, data_saved_line(data)),
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


class CountingEvent(threading.Event):
    """A REAL ``threading.Event`` that also counts how many times it is read.

    ``IndexingService`` passes ``cancel.is_set`` to the pipeline, so every
    ``cancel_check()`` the pipeline performs lands in this counter, and nothing
    else does.

    It is deliberately a real Event rather than a scripted double. A double
    whose ``is_set()`` starts returning True after the Nth read can be pointed
    at a run that never performs an Nth read - in which case the flag is False
    at every moment the pipeline is running, the "late cancel" it claims to
    model is an ordinary uncancelled run, and the test's own trailing
    ``is_set()`` call manufactures the state it then asserts. With a real Event
    the only way the flag becomes True is for something to call ``set()``, so a
    test has to actually cause the state it claims to observe.
    """

    def __init__(self):
        super().__init__()
        self.reads = 0

    def is_set(self):
        self.reads += 1
        return super().is_set()


def test_a_cancel_first_observed_after_the_last_checkpoint_does_not_stop_the_run(
    indexing, monkeypatch
):
    """TIMING B, inventory defect #17. CURRENT BEHAVIOUR, NOT A BUG FIX.

    The flag is set DURING the run, at the single interleaving defect #17 is
    about: after the LAST track's checkpoint and before that track's embed
    returns. That is a user clicking Cancel while the final track is being
    embedded.

    The progress callback supplies that interleaving deterministically - no
    threads, no sleeps, no wall-clock race. Each per-track iteration runs, in
    source order:

        pipeline.py:182   if cancel_check and cancel_check():   <- the checkpoint
        pipeline.py:188   pl = str(row.get("path_local", ""))
        pipeline.py:189   report("embed", "   [  5/  5] ...")   <- fires progress
        pipeline.py:198   vector = embedder.embed_file(pl)

    so calling ``cancel.set()`` from the report on track 5 lands strictly
    between track 5's checkpoint and track 5's embed. The assertions below PIN
    that placement instead of assuming it: at the moment of ``set()`` the
    pipeline has performed 5 checkpoint reads (all of them) and 4 embeds (not
    yet track 5's).

    ``cancel_check`` is read in exactly one place, at the TOP of each
    iteration, and track 5 is the last iteration - so the pipeline never looks
    again. It does not raise ``KeyboardInterrupt``, it does not emit
    "⚠️ Cancellation detected, stopping...", it finishes embedding track 5,
    and it writes all four data files.

    reindex_window then evaluates `if self.cancel_requested:` - True - and
    appends "⚠️ Indexing cancelled by user". The UI half of that is pinned in
    tests/test_ui_reports_success_for_every_terminal_outcome.py.
    """
    service, xml, data, _ = indexing
    embeds = []

    class RecordingEmbedder(FakeEmbedder):
        """FakeEmbedder that also records WHEN each embed happened, so the test
        can prove the flag was set before the final embed rather than assert it."""

        def embed_file(self, path_local):
            embeds.append(path_local)
            return super().embed_file(path_local)

    monkeypatch.setattr(pipeline_module, "DiscogsEffnetEmbedder", RecordingEmbedder)

    cancel = CountingEvent()
    events = []
    set_at = []

    def progress(event):
        events.append(event)
        # The per-track embed line for the LAST track. The closing
        # "✨ Generated ..." summary is also phase "embed" at current == 5, so
        # match on the "   [  i/  N] " prefix the way the rest of this file does.
        if event.phase == "embed" and event.current == 5 and event.message.startswith("   ["):
            cancel.set()
            set_at.append((cancel.reads, len(embeds)))

    try:
        result = service.run(str(xml), progress=progress, cancel=cancel)
    except KeyboardInterrupt:  # pragma: no cover - only on a behaviour change
        pytest.fail(
            "the pipeline OBSERVED the late cancel and raised KeyboardInterrupt. "
            "Defect #17 says it does not: a cancellation checkpoint now runs "
            "somewhere after the top of the last per-track iteration."
        )

    # The RUN set the flag - this test did not - and it set it after the fifth
    # (final) checkpoint and before the fifth embed. That is timing B exactly.
    assert set_at == [(5, 4)], (
        "the flag was not set at the timing-B interleaving. Expected "
        "(checkpoint reads, completed embeds) == (5, 4) at set(); got "
        f"{set_at}"
    )

    # The pipeline never consulted the token again, so it ran the rest of the
    # job - the final embed, the merge, the four-file write - with the
    # cancellation flag standing at True the whole time.
    reads_during_run = cancel.reads  # captured before this test reads it itself
    assert reads_during_run == 5, (
        f"expected 5 in-run reads (one per track); got {reads_during_run}. "
        "A checkpoint after the last one would have caught this cancel"
    )
    assert len(embeds) == 5, "track 5 was not embedded after the flag went up"

    assert cancel.is_set() is True  # still set; nothing cleared it
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

    This pins only the NUMBER of reads, not their location. The location is
    pinned by the test above, which sets a real flag between the last
    checkpoint and the last embed.
    """
    service, xml, _, _ = indexing
    cancel = CountingEvent()  # never set: nothing in this test calls set()

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
    try:
        result = service.run(str(xml), progress=events.append, cancel=already_set)
    except KeyboardInterrupt:  # pragma: no cover - only on a behaviour change
        pytest.fail(
            "the up-to-date path OBSERVED the cancel and raised KeyboardInterrupt. "
            "Workflow 34f says it does not: a cancellation checkpoint now runs on "
            "the len(new_tracks) == 0 return path."
        )

    assert result.status == STATUS_UP_TO_DATE
    assert "⚠️ Cancellation detected, stopping..." not in [e.message for e in events]
    assert "✅ No new tracks to process! Your index is up to date." in [
        e.message for e in events
    ]

def test_a_late_cancel_on_the_no_embeddings_path_is_never_observed(indexing, tmp_path):
    """TIMING B via STATUS_NO_EMBEDDINGS (inventory §2.13, §4 #17).
    CURRENT BEHAVIOUR, NOT A BUG FIX.

    Three tracks whose files are all missing. The per-track loop DOES run here -
    every track is iterated and every track reports "File not found" - so this
    path performs one checkpoint per track, exactly like the STATUS_INDEXED
    path. What it never performs is a checkpoint AFTER the last iteration:
    ``pipeline.py:219-221`` reports "❌ No new embeddings generated." and
    returns without reading ``cancel_check`` again.

    So the reachable timing-B interleaving on this path is a flag first set
    after the LAST track's checkpoint - not "at any moment of the run", which
    would be caught by a later track's checkpoint. The progress callback
    supplies that interleaving deterministically, with no threads and no
    sleeps. Each per-track iteration runs, in source order:

        pipeline.py:182   if cancel_check and cancel_check():   <- the checkpoint
        pipeline.py:189   report("embed", "   [  3/3] C - Gone")
        pipeline.py:193   if not pl or not os.path.exists(pl):
        pipeline.py:194   report("embed", "      ⚠️  File not found: ...")  <- fires
        pipeline.py:197   continue

    so calling ``cancel.set()`` from the THIRD "File not found" report lands
    after every checkpoint this run will ever perform. The assertions below PIN
    that placement rather than assume it: at the moment of ``set()`` the
    pipeline has performed 3 checkpoint reads - one per track, all of them -
    and has reported all 3 misses.

    The pipeline never looks again. It does not raise ``KeyboardInterrupt``, it
    does not emit "⚠️ Cancellation detected, stopping...", it emits its
    "❌ No new embeddings generated." line AFTER the flag went up, and it
    returns ``STATUS_NO_EMBEDDINGS``. No data files are written on this path.

    reindex_window then evaluates `if self.cancel_requested:` - True - and
    appends "⚠️ Indexing cancelled by user" over a run that failed rather than
    one that was cancelled. The UI half of that is pinned in
    tests/test_ui_reports_success_for_every_terminal_outcome.py.
    """
    service, _, data, audio = indexing
    xml = _write_xml(tmp_path / "allbad.xml", [
        ("3001", "Gone", "A", audio / "missing1.mp3"),
        ("3002", "Gone", "B", audio / "missing2.mp3"),
        ("3003", "Gone", "C", audio / "missing3.mp3"),
    ])

    cancel = CountingEvent()
    events = []
    misses = []
    set_at = []
    set_index = []

    def progress(event):
        events.append(event)
        # The per-track miss line for each track. Matching the message prefix
        # the way the rest of this file does; the closing "complete" line is a
        # different phase and does not collide with it.
        if event.message.startswith("      ⚠️  File not found:"):
            misses.append(event.message)
            if len(misses) == 3:  # the LAST track's miss
                cancel.set()
                set_at.append((cancel.reads, len(misses)))
                set_index.append(len(events))

    try:
        result = service.run(str(xml), progress=progress, cancel=cancel)
    except KeyboardInterrupt:  # pragma: no cover - only on a behaviour change
        pytest.fail(
            "the no-embeddings path OBSERVED the late cancel and raised "
            "KeyboardInterrupt. Defect #17 says it does not: a cancellation "
            "checkpoint now runs after the top of the last per-track iteration "
            "- most likely on the STATUS_NO_EMBEDDINGS return path itself."
        )

    # The RUN set the flag - this test did not - and it set it after the third
    # (final) checkpoint. That is timing B on this path exactly.
    assert set_at == [(3, 3)], (
        "the flag was not set at the timing-B interleaving. Expected "
        "(checkpoint reads, misses reported) == (3, 3) at set(); got "
        f"{set_at}"
    )

    # The pipeline never consulted the token again, so it ran the rest of the
    # job - the empty-vector test, the "complete" report and the return - with
    # the cancellation flag standing at True the whole time.
    reads_during_run = cancel.reads  # captured before this test reads it itself
    assert reads_during_run == 3, (
        f"expected 3 in-run reads (one per track); got {reads_during_run}. "
        "A checkpoint after the last one would have caught this cancel"
    )

    assert cancel.is_set() is True  # still set; nothing cleared it
    assert result.status == STATUS_NO_EMBEDDINGS
    assert result.failed is True
    assert result.up_to_date is False
    assert result.new_tracks_found == 3
    assert result.new_tracks_added == 0

    messages = [e.message for e in events]
    assert "⚠️ Cancellation detected, stopping..." not in messages

    # The run carried on PAST the moment the flag went up: its terminal line was
    # emitted after set(), which is what "the cancel was never observed" means
    # here. Asserting the ordering rather than an absolute index, so an
    # unrelated event elsewhere in the pipeline does not move this goalpost.
    complete_line = "❌ No new embeddings generated. Check audio paths/codecs."
    assert complete_line in messages
    assert messages.index(complete_line) >= set_index[0], (
        "the terminal line was emitted before the flag was set, so this run "
        "never modelled a late cancel at all"
    )

    # Nothing is persisted on this path, cancelled or not.
    for name in ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json"):
        assert not (data / name).exists(), f"{name} was written on the no-embeddings path"



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


def test_an_explicit_data_directory_is_the_only_index_write_target(
    indexing, tmp_path, monkeypatch
):
    """The regression: X receives the generation and the default stays exact.

    The four module constants are redirected to a scratch "default" so this
    test also fails against the former implicit persistence path without ever
    putting the maintainer's real library at risk.
    """
    service, xml, target, _ = indexing
    wrong_default = tmp_path / "default"
    wrong_default.mkdir()
    for name in ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json"):
        (wrong_default / name).write_bytes(f"sentinel:{name}".encode())

    monkeypatch.setattr(loader_module, "META_PQ", wrong_default / "meta.parquet")
    monkeypatch.setattr(loader_module, "EMB_PQ", wrong_default / "embeddings.parquet")
    monkeypatch.setattr(
        persistence_module, "META_PQ", wrong_default / "meta.parquet", raising=False
    )
    monkeypatch.setattr(
        persistence_module,
        "EMB_PQ",
        wrong_default / "embeddings.parquet",
        raising=False,
    )
    monkeypatch.setattr(
        persistence_module, "IDX_NPY", wrong_default / "index.npy", raising=False
    )
    monkeypatch.setattr(
        persistence_module, "IDS_JSON", wrong_default / "ids.json", raising=False
    )
    monkeypatch.setattr(
        deleted_tracks_module,
        "DELETED_TRACKS_JSON",
        wrong_default / "deleted_tracks.json",
    )
    service.settings = SettingsStore(wrong_default / "settings.json")

    def fingerprint(directory):
        return {
            path.name: (
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in sorted(directory.iterdir())
            if path.is_file()
        }

    default_before = fingerprint(wrong_default)
    result = service.run(str(xml), force_full=True, progress=lambda event: None)

    assert result.status == STATUS_INDEXED
    assert LibrarySession.load(target).ids == [
        "1001",
        "1002",
        "1003",
        "1004",
        "1005",
    ]
    assert fingerprint(wrong_default) == default_before


def test_the_four_persisted_values_share_one_row_mapping(indexing, tmp_path):
    """A failed embed is absent everywhere; every remaining row maps exactly."""
    service, _, data, audio = indexing
    broken = audio / "broken-row.mp3"
    broken.write_bytes(b"\x00")
    xml = _write_xml(
        tmp_path / "partial.xml",
        [
            ("left", "Left", "A", audio / "track1.mp3"),
            ("failed", "Failed", "B", broken),
            ("right", "Right", "C", audio / "track2.mp3"),
        ],
    )

    service.run(str(xml), force_full=True, progress=lambda event: None)

    meta = pd.read_parquet(data / "meta.parquet")
    embeddings = pd.read_parquet(data / "embeddings.parquet")
    ids = json.loads((data / "ids.json").read_text(encoding="utf-8"))
    matrix = np.load(data / "index.npy")
    vector_columns = [f"v{index}" for index in range(matrix.shape[1])]

    assert meta["track_id"].tolist() == ids == ["left", "right"]
    assert embeddings["track_id"].tolist() == ids
    np.testing.assert_array_equal(
        embeddings[vector_columns].to_numpy(dtype="float32"), matrix
    )


def test_a_committed_index_refreshes_before_a_later_delete(indexing, tmp_path):
    """A delete after reindex starts from the new six-track snapshot, not five."""
    first_service, xml, data, audio = indexing
    first_service.run(str(xml), progress=lambda event: None)
    library = LibrarySession.load(data)
    assert library.track_count == 5

    added = audio / "track6.mp3"
    added.write_bytes(b"\x00")
    tracks = [
        (str(1000 + index), f"Title {index}", f"Artist {index}", audio / f"track{index}.mp3")
        for index in range(1, 7)
    ]
    expanded_xml = _write_xml(tmp_path / "expanded.xml", tracks)
    service = IndexingService(
        first_service.settings, data_dir=data, library=library
    )

    result = service.run(str(expanded_xml), progress=lambda event: None)

    assert result.status == STATUS_INDEXED
    assert library.track_count == 6
    assert library.ids[-1] == "1006"

    assert library.delete_tracks(["1001"]) == 1
    reloaded = LibrarySession.load(data)
    assert reloaded.track_count == 5
    assert "1006" in reloaded.ids


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

    service, xml, _, _ = indexing
    index_library(str(xml), data_dir=service.data_dir)

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
