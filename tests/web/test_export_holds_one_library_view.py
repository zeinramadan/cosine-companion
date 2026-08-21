"""One library view, from the moment a request is accepted to the last seed.

``POST /api/jobs/export`` answers a question - "how many seeds, and are they
all real?" - and then a worker thread answers it again, minutes later, by
exporting them. Between those two moments the library can change:
``POST /api/library/tracks/delete`` publishes a whole new generation, and
nothing about a 202 stops it.

The request and the worker therefore have to be looking at the SAME
generation, or the 202 was about a library that no longer exists. That is not
a hypothetical: with the acceptance reading ``LibrarySession.snapshot()`` and
``ExportService`` independently reading it again at the top of the run, a
delete landing in between made the request accept two seeds, return
``total: 2``, and the job finish ``succeeded`` with ``successful: 1`` and
``failed: 1``. The user was told two playlists were coming and got one, with
no error anywhere.

WHY A PIN AND NOT A LOCK
------------------------
PR #19 put ``LibrarySession.snapshot()`` and ``delete_tracks`` under one
``RLock``, so a capture is wholly before or wholly after a deletion's
publication and the captured objects are never mutated in place - deletion
rebinds. That is the whole of what is needed here: capture ONCE, at
acceptance, and hand that capture to the run. Holding a lock across a
6.8-minute export would be the other way to make the two agree, and it would
make Delete unusable for the length of an export.

So ``CocoApi`` builds the export service over a view pinned to the accepted
snapshot, and ``ExportService``'s own ``self.library.snapshot()`` returns it.
No fifth pattern, no service change: the service already asks a library for
one snapshot per run, and it is handed a library that has one.

Every gate here is a ``threading.Event`` with a bounded wait. The export is
the real ``ExportService`` over the committed fourteen-track fixture library,
writing real ``.m3u`` files, so what is asserted is what a user would find in
the directory they chose.
"""

import threading

import pytest

from recommendations.playlist_exporter import playlist_filename
from services.export_service import ExportService
from web.api import CocoApi
from web.jobs import SUCCEEDED

#: Every blocking wait is bounded by this, so a wedge fails rather than hangs.
WAIT = 30.0

#: Two fixture seeds with real audio files on disk, so the exporter writes a
#: playlist for each rather than silently skipping it. ``VICTIM`` is the one
#: deleted inside the window.
KEEPER = "f01"
VICTIM = "f02"
SEEDS = f"{KEEPER}\n{VICTIM}"


class GatedExportService:
    """The REAL ``ExportService``, held at its door until the test releases it.

    The gate is *outside* ``export_per_seed``, so it parks the worker before
    the service takes its own library capture. That is the exact window this
    file is about - after the request was accepted, before the run began - and
    it is the only place a test can stand in it.

    ``on_progress`` runs inside the export loop instead, which is the *other*
    window: after the capture, between seeds.

    ``__call__`` is the factory ``CocoApi`` invokes once per accepted export,
    with the pinned view. The real service is built over whatever it is
    handed - the point of the file being that what it is handed is the
    request's own snapshot rather than the live session.
    """

    def __init__(self, on_progress=None):
        self.library = None
        self._service = None
        self._on_progress = on_progress
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, library):
        self.library = library
        self._service = ExportService(library)
        return self

    def _wrap(self, progress):
        if self._on_progress is None:
            return progress

        def report(current, total, message):
            progress(current, total, message)
            self._on_progress(current, total, message)

        return report

    def export_per_seed(
        self, track_ids, out_dir, recommendations_per_track, progress=None, cancel=None
    ):
        self.entered.set()
        assert self.release.wait(timeout=WAIT), "the export was never released"
        return self._service.export_per_seed(
            track_ids,
            out_dir,
            recommendations_per_track,
            progress=self._wrap(progress),
            cancel=cancel,
        )

    def export_combined(self, *args, **kwargs):  # pragma: no cover - unused here
        raise AssertionError("combined mode is not exercised in this file")


def start_export(api, out_dir, track_ids=SEEDS):
    return api.handle(
        "POST",
        "/api/jobs/export",
        {},
        {"out_dir": str(out_dir), "track_ids": track_ids},
    )


def settle(api, job_id):
    job = api.jobs.get(job_id)
    assert job is not None
    job.thread.join(timeout=WAIT)
    assert not job.thread.is_alive(), "the export job did not finish"
    status, body = api.handle("GET", f"/api/jobs/{job_id}", {})
    assert status == 200, body
    return body["job"]


def expected_filename(library, track_id):
    """The name the exporter gives this seed's playlist."""
    row = library.meta_ix.loc[track_id]
    return playlist_filename(row.get("artist", ""), row.get("title", ""))


@pytest.fixture
def victim_filename(web_library):
    """Captured BEFORE any delete - afterwards the row is gone."""
    return expected_filename(web_library, VICTIM)


def test_a_delete_between_acceptance_and_execution_does_not_change_the_export(
    web_library, settings, tmp_path, victim_filename
):
    """The defect, and the window it lives in, end to end.

    The request is accepted while ``f02`` exists. The worker is held at the
    service's door, ``f02`` is really deleted through ``LibrarySession`` - a
    whole replacement generation, published under the lock, written to disk -
    and only then is the worker released.

    Re-reading the library there, the run finds fourteen tracks minus one,
    counts the seed it was accepted with as ``failed`` and writes one playlist
    for a 202 that promised two. Pinned to the accepted snapshot, it writes
    both, because both is what was accepted.
    """
    exports = GatedExportService()
    api = CocoApi(web_library, settings, export_service_factory=exports)
    out_dir = tmp_path / "playlists"

    status, body = start_export(api, out_dir)
    assert status == 202
    assert body["job"]["progress"]["total"] == 2, "the request accepted two seeds"
    # The view the run was built over is the one the request accepted, and
    # it still holds the seed that is about to be deleted.
    accepted = exports.library.snapshot()
    assert VICTIM in accepted.meta_ix.index
    job_id = body["job"]["id"]

    assert exports.entered.wait(timeout=WAIT), "the worker never reached the service"
    assert web_library.delete_tracks([VICTIM]) == 1, "the window is real"
    assert web_library.get_track(VICTIM) is None
    # The capture is unaffected: deletion REBINDS, it does not edit the
    # objects a reader already holds. That is what makes pinning safe.
    assert VICTIM in accepted.meta_ix.index
    exports.release.set()

    job = settle(api, job_id)

    assert job["state"] == SUCCEEDED
    assert job["result"]["total_tracks"] == 2
    assert job["result"]["successful"] == 2, (
        "the run must export what the request accepted, not what survived it"
    )
    assert job["result"]["failed"] == 0

    # The half a count cannot show: the deleted seed's playlist is really on
    # disk, in the directory the user chose, with real content in it.
    written = sorted(path.name for path in out_dir.glob("*.m3u"))
    assert victim_filename in written
    body = (out_dir / victim_filename).read_text(encoding="utf-8")
    assert body.startswith("#EXTM3U")
    assert len(body.strip().splitlines()) > 1


def test_a_delete_during_the_run_does_not_change_it_either(
    web_library, settings, tmp_path, victim_filename
):
    """The other window, and it must not regress.

    This one was already correct: ``ExportService`` captures once at entry, so
    a delete after that capture leaves ``meta_ix``, ``emb_ix`` and ``index``
    on the generation the run started with. Pinning the capture earlier must
    not move the capture point *later* or make it per-seed - the failure mode
    a review found in the first draft of the services layer, which re-read the
    live properties for every seed.

    The delete lands while the worker is inside the loop, blocked in the
    progress callback for seed one, with seed two still to write.
    """
    reached_first_seed = threading.Event()
    may_continue = threading.Event()

    def on_progress(current, total, message):
        if current == 1:
            reached_first_seed.set()
            assert may_continue.wait(timeout=WAIT), "the export was never released"

    exports = GatedExportService(on_progress=on_progress)
    api = CocoApi(web_library, settings, export_service_factory=exports)
    out_dir = tmp_path / "playlists"

    status, body = start_export(api, out_dir)
    assert status == 202
    job_id = body["job"]["id"]

    assert exports.entered.wait(timeout=WAIT)
    exports.release.set()

    assert reached_first_seed.wait(timeout=WAIT), "the export never reached seed 1"
    assert web_library.delete_tracks([VICTIM]) == 1
    may_continue.set()

    job = settle(api, job_id)

    assert job["state"] == SUCCEEDED
    assert job["result"]["successful"] == 2
    assert job["result"]["failed"] == 0
    assert victim_filename in sorted(path.name for path in out_dir.glob("*.m3u"))


class CountingLibrary:
    """The real session, counting the captures taken through it.

    Everything except ``snapshot`` is forwarded untouched, so the API, the
    explore session and the set builder all see the session they would
    normally get.
    """

    def __init__(self, library):
        self._library = library
        self.snapshots = 0

    def snapshot(self):
        self.snapshots += 1
        return self._library.snapshot()

    def __getattr__(self, name):
        return getattr(self._library, name)


def test_one_accepted_export_takes_exactly_one_capture(
    web_library, settings, tmp_path
):
    """Not "a capture per phase" - ONE, shared.

    The two tests above prove the request's view and the run's view agree.
    They agree because there is only one view, and that is worth pinning
    separately: two captures taken microseconds apart at acceptance would
    still satisfy those tests every time, and would still be two generations
    answering one question - the shape ``PlaylistService.lookup`` was
    rewritten to remove, and the shape a review found in the first draft of
    ``ExportService``.

    Counted through the library rather than asserted about the source, so
    what is checked is the calls that really happen.
    """
    counting = CountingLibrary(web_library)
    exports = GatedExportService()
    api = CocoApi(counting, settings, export_service_factory=exports)

    status, body = start_export(api, tmp_path / "playlists")
    assert status == 202
    assert exports.entered.wait(timeout=WAIT)
    exports.release.set()

    job = settle(api, body["job"]["id"])
    assert job["state"] == SUCCEEDED
    assert job["result"]["successful"] == 2

    assert counting.snapshots == 1, (
        f"the accepted export took {counting.snapshots} captures; one capture "
        "has to answer the request AND run the export, or the two can differ"
    )
