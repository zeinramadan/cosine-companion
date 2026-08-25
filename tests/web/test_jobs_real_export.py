"""The job machinery driving the REAL ``ExportService``, writing real files.

Everything else in this area uses a double, because the real export is
measured at ~6.8 minutes over the full collection. That is a limit on the
*size* of the library, not on the realness of the service - so this file runs
the genuine ``ExportService``, over the committed fourteen-track fixture
library, and asserts against ``.m3u`` files that really exist on disk.

**No skip.** ``tests/services`` has a ``real_library`` fixture that skips when
``data/`` is absent, and ``tests/web/conftest.py`` deliberately has no
equivalent - an API test that only runs on one machine cannot gate a merge,
and a skipping test reads exactly like a passing one. Everything here runs
everywhere, from a clean checkout, with no library present.

The full-size counterpart is ``tests/manual/web_jobs_real_export.py``, which
drives the same code over a real 1,532-track library. It is not collected by
pytest and it is not a gate; it exists so the claim "this works at real size"
has something behind it.
"""

import threading

import pytest

from recommendations import playlist_exporter
from recommendations.playlist_exporter import playlist_filename
from services.export_service import ExportService
from web.jobs import CANCELLED, SUCCEEDED, JobRegistry, WorkOutcome

#: Three of the twelve committed tracks that have real (empty) audio files on
#: disk, so the exporter does not silently skip them.
SEEDS = ["f01", "f06", "f10"]

RECOMMENDATIONS_PER_TRACK = 5

#: A real export of three fixture seeds is milliseconds. This bound exists so a
#: wedge fails the test instead of hanging the run.
WAIT = 30.0


@pytest.fixture
def service(web_library):
    return ExportService(web_library)


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "playlists"


def expected_filename(library, track_id):
    """The name ``export_recommendations_as_playlists`` gives this seed's file."""
    row = library.meta_ix.loc[track_id]
    return playlist_filename(row.get("artist", ""), row.get("title", ""))


def export_work(service, seeds, out_dir, on_progress=None):
    """A job callable that runs the real per-seed export."""

    def work(report, cancel):
        def progress(current, total, message):
            report(current, total, message)
            if on_progress is not None:
                on_progress(current, total, message)

        result = service.export_per_seed(
            seeds,
            str(out_dir),
            RECOMMENDATIONS_PER_TRACK,
            progress=progress,
            cancel=cancel,
        )
        return WorkOutcome(
            cancelled=result.cancelled,
            result={
                "successful": result.successful,
                "failed": result.failed,
                "playlists_created": result.playlists_created,
                "total_tracks": result.total_tracks,
                "cancelled": result.cancelled,
            },
        )

    return work


def run_to_completion(job):
    assert job.thread is not None
    job.thread.join(timeout=WAIT)
    assert not job.thread.is_alive(), "the real export job did not finish"
    return job.snapshot()


def test_a_real_export_runs_as_a_job_and_writes_real_playlists(
    service, web_library, out_dir
):
    """The whole machinery, end to end, against the service that ships."""
    registry = JobRegistry()

    job = registry.start(
        "export", export_work(service, SEEDS, out_dir), total=len(SEEDS)
    )
    snapshot = run_to_completion(job)

    assert snapshot.state == SUCCEEDED
    assert snapshot.error is None
    assert dict(snapshot.result) == {
        "successful": 3,
        "failed": 0,
        "playlists_created": 3,
        "total_tracks": 3,
        "cancelled": False,
    }

    written = sorted(path.name for path in out_dir.glob("*.m3u"))
    assert written == sorted(expected_filename(web_library, seed) for seed in SEEDS)

    # Real content, not empty files: the exporter's own header plus one line
    # per recommendation whose audio exists on disk.
    body = (out_dir / written[0]).read_text(encoding="utf-8")
    assert body.startswith("#EXTM3U")
    assert len(body.strip().splitlines()) > 1


def test_real_progress_reaches_the_job_record(service, out_dir):
    """The service's own callback, not a simulated one, moves the snapshot."""
    registry = JobRegistry()
    seen = []

    job = registry.start(
        "export",
        export_work(service, SEEDS, out_dir, on_progress=lambda c, t, m: seen.append(c)),
        total=len(SEEDS),
    )
    snapshot = run_to_completion(job)

    assert seen == [1, 2, 3], "the real exporter reports once per seed, in order"
    assert snapshot.current == 3
    assert snapshot.total == 3
    # The message is the seed's own display name, straight from the exporter.
    assert " - " in snapshot.message


def test_cancelling_a_real_export_keeps_the_playlists_it_already_wrote(
    service, web_library, out_dir
):
    """The partial-results decision, proved against the real exporter.

    ``export_recommendations_as_playlists`` checks ``cancel_check`` at the
    **top** of its loop and reports progress just after, so blocking inside
    the progress callback for seed 2 puts the cancel between seed 2's write
    and seed 3's check. The run therefore stops with exactly two files on
    disk, and this asserts that both of them are still there and complete.

    Deleting them was the alternative, and it is the wrong one: these are
    whole, importable playlists in a directory the *user* chose, and a Stop
    button that erases files from it is a destructive act. Indexing's opposite
    answer - discard everything (inventory defect #4) - is right for indexing
    because a partial set of embeddings is not a usable index. Different
    artefacts, different answers.

    Deterministic, not timing-dependent: the worker blocks on an ``Event``
    until this test releases it.
    """
    registry = JobRegistry()
    reached_second_seed = threading.Event()
    may_continue = threading.Event()

    def on_progress(current, total, message):
        if current == 2:
            reached_second_seed.set()
            assert may_continue.wait(timeout=WAIT), "the export was never released"

    job = registry.start(
        "export",
        export_work(service, SEEDS, out_dir, on_progress=on_progress),
        total=len(SEEDS),
    )

    assert reached_second_seed.wait(timeout=WAIT), "the export never reached seed 2"
    job.request_cancel()
    may_continue.set()

    snapshot = run_to_completion(job)

    assert snapshot.state == CANCELLED
    assert snapshot.cancel_requested is True

    # Two seeds were written; the third was never started.
    written = sorted(path.name for path in out_dir.glob("*.m3u"))
    assert written == sorted(
        expected_filename(web_library, seed) for seed in SEEDS[:2]
    )
    assert expected_filename(web_library, SEEDS[2]) not in written

    # And each surviving file is a whole playlist, not a truncated write.
    for name in written:
        body = (out_dir / name).read_text(encoding="utf-8")
        assert body.startswith("#EXTM3U")
        assert body.endswith("\n")

    # The record says what is on disk, which is the half this PR owns.
    assert dict(snapshot.result) == {
        "successful": 2,
        "failed": 0,
        "playlists_created": 2,
        "total_tracks": 3,
        "cancelled": True,
    }


def test_a_real_export_into_an_unwritable_directory_fails_with_its_reason(
    service, tmp_path
):
    """A real OSError from the real service becomes a legible job failure.

    Not a 500 and not a silent stall: the job lands ``failed`` carrying the
    exception's own message, which for an export is almost always about the
    directory the user chose.
    """
    blocked = tmp_path / "blocked"
    blocked.write_text("I am a file, not a directory", encoding="utf-8")
    registry = JobRegistry()

    job = registry.start(
        "export", export_work(service, SEEDS, blocked / "out"), total=len(SEEDS)
    )
    snapshot = run_to_completion(job)

    assert snapshot.state == "failed"
    assert snapshot.result is None
    assert snapshot.error
    assert "Error" in snapshot.error or "error" in snapshot.error.lower()


@pytest.fixture
def write_fails_after_the_header(monkeypatch):
    """Make the real writer raise mid-file, the way a full disk does.

    Nothing here fakes the FILE. ``create_m3u_playlist`` opens the real
    destination in mode ``'w'`` and writes ``#EXTM3U`` before it looks at a
    single track, so the truncated ``.m3u`` this leaves behind is the shipped
    writer's own doing, on a real path, through a real handle. The one thing
    injected is the ``OSError`` itself - on a real machine it arrives as ENOSPC
    or EIO partway through a write, which is not something a test can arrange
    honestly.

    ``playlist_exporter`` calls the builtin ``open`` exactly once, so shadowing
    it as a module global reaches that call and nothing else in the process.
    """
    real_open = open

    def exploding_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        real_write = handle.write

        def write(text):
            if text.startswith("#EXTINF"):
                raise OSError(28, "No space left on device")
            return real_write(text)

        handle.write = write
        return handle

    monkeypatch.setattr(playlist_exporter, "open", exploding_open, raising=False)


def test_a_failed_write_leaves_a_partial_playlist_behind(
    service, web_library, out_dir, write_fails_after_the_header
):
    """``successful == 0`` does NOT mean the directory is empty.

    Round-3 blocker, and the premise the stopped dialog's zero branch rests on.
    That branch read "so this run left nothing in {dir}" whenever ``successful``
    was zero, reasoning that no write call had returned. The reasoning does not
    reach the conclusion: ``create_m3u_playlist`` opens the destination with
    mode ``'w'`` and writes the header BEFORE it iterates, so a raise partway
    through leaves a truncated file on disk, and
    ``export_recommendations_as_playlists`` catches it and increments only
    ``failed``. Nothing about the leftover reaches the wire, so the screen has
    no way to know about it and cannot claim its absence.

    The whole sequence, end to end through the real service: seed 1's write
    raises after the header, the stop lands before seed 2, the record comes
    back with every count at zero - and there is a file in the directory.

    IF THIS TEST GOES RED because the writer was made atomic - a temporary path
    and a rename - that is the signal that ``cancelledMessage``'s zero branch
    may go back to claiming the absence. Change the copy deliberately at that
    point; do not delete this test to make the red go away.
    """
    registry = JobRegistry()
    reached_first_seed = threading.Event()
    may_continue = threading.Event()

    def on_progress(current, total, message):
        # Progress for seed N is reported BEFORE seed N's write and AFTER the
        # cancel check at the top of its iteration, so releasing here lets
        # seed 1's write run and fail, and puts the stop at the top of seed 2.
        if current == 1:
            reached_first_seed.set()
            assert may_continue.wait(timeout=WAIT), "the export was never released"

    job = registry.start(
        "export",
        export_work(service, SEEDS, out_dir, on_progress=on_progress),
        total=len(SEEDS),
    )

    assert reached_first_seed.wait(timeout=WAIT), "the export never reached seed 1"
    job.request_cancel()
    may_continue.set()

    snapshot = run_to_completion(job)

    # `successful` and `playlists_created` are zero and `failed` is 1. There is
    # no field in this record that could tell a dialog a file exists.
    assert snapshot.state == CANCELLED
    assert dict(snapshot.result) == {
        "successful": 0,
        "failed": 1,
        "playlists_created": 0,
        "total_tracks": 3,
        "cancelled": True,
    }

    # And yet.
    written = sorted(path.name for path in out_dir.glob("*.m3u"))
    assert written == [expected_filename(web_library, SEEDS[0])], (
        "the failed write left no file, so the exporter is atomic now - see this "
        "test's docstring before changing the cancelled-export copy"
    )

    # Truncated, not empty and not whole: the header reached disk and not one
    # track line did. This is the file the old copy promised was not there.
    body = (out_dir / written[0]).read_text(encoding="utf-8")
    assert body.startswith("#EXTM3U")
    assert len(body.strip().splitlines()) == 1, (
        f"expected a header and nothing else, got {body!r}"
    )
