"""The /api/jobs surface: starting, watching, cancelling, and the results.

One route starts work here: ``POST /api/jobs/export``. The re-index route was
cut from this PR on review and ``web.api``'s DEFERRED note says why, so the
indexing doubles that used to live in this file are gone with it.

The export service is a double. The real one takes ~6.8 minutes over the full
collection, so running it here would make this file unrunnable rather than
slow. Two things keep the double honest:

* ``test_the_double_matches_the_real_export_service_signature`` binds the
  arguments this API really passes against the **real** service's signature
  with ``inspect``, so a double that drifts is a failure here rather than a
  500 in production;
* ``tests/web/test_jobs_real_export.py`` runs the whole machinery against the
  real ``ExportService`` over the fixture library.

Every double blocks on a ``threading.Event`` with a bounded wait. Nothing
spins and nothing sleeps hoping.
"""

import inspect
import threading

import pytest

from services.export_service import ExportResult, ExportService
from web.api import COMBINED_EXPORT_FILENAME, CocoApi
from web.jobs import CANCELLED, FAILED, RUNNING, SUCCEEDED

WAIT = 5.0


class FakeExportService:
    """Records its call, holds it open until released, returns a fixed result.

    Doubles as the FACTORY ``CocoApi`` is given: ``__call__`` takes the
    library the API pinned for this request and returns this double, so a
    test can read ``libraries`` and see which view the run was handed. The
    idiom is the one ``tests/test_ui_reports_success_for_every_terminal_
    outcome.py`` already uses to stand in for a service class.
    """

    def __init__(self, result=None, raises=None):
        self.calls = []
        #: One entry per accepted export: the library the factory was
        #: called with. A ``_PinnedLibrary``, not the session.
        self.libraries = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.result = result or ExportResult(
            total_tracks=2,
            successful=2,
            failed=0,
            total_recommendations=20,
            playlists_created=2,
        )
        self.raises = raises
        self.progress = None
        self.cancel = None

    def __call__(self, library):
        self.libraries.append(library)
        return self

    def _run(self, name, track_ids, target, per_track, progress, cancel):
        self.calls.append(
            {
                "name": name,
                "track_ids": list(track_ids),
                "target": target,
                "recommendations_per_track": per_track,
            }
        )
        self.progress = progress
        self.cancel = cancel
        self.entered.set()
        assert self.release.wait(timeout=WAIT), "the export double was never released"
        if self.raises is not None:
            raise self.raises
        return self.result

    def export_per_seed(
        self, track_ids, out_dir, recommendations_per_track, progress=None, cancel=None
    ):
        return self._run(
            "per_seed", track_ids, out_dir, recommendations_per_track, progress, cancel
        )

    def export_combined(
        self, track_ids, out_path, recommendations_per_track, progress=None, cancel=None
    ):
        return self._run(
            "combined", track_ids, out_path, recommendations_per_track, progress, cancel
        )


@pytest.fixture
def exports():
    return FakeExportService()


@pytest.fixture
def api(web_library, settings, exports):
    return CocoApi(web_library, settings, export_service_factory=exports)


# -- helpers ---------------------------------------------------------------


def start_export(api, **body):
    payload = {"out_dir": "/tmp/coco-out", "track_ids": "f01\nf02"}
    payload.update(body)
    payload = {key: value for key, value in payload.items() if value is not _ABSENT}
    return api.handle("POST", "/api/jobs/export", {}, payload)


_ABSENT = object()


def read_job(api, job_id):
    status, body = api.handle("GET", f"/api/jobs/{job_id}", {})
    assert status == 200, body
    return body["job"]


def settle(api, double, job_id):
    """Release a held double and wait for the job to reach a terminal state."""
    double.release.set()
    job = api.jobs.get(job_id)
    assert job is not None
    job.thread.join(timeout=WAIT)
    assert not job.thread.is_alive(), "the job worker did not finish"
    return read_job(api, job_id)


# -- the doubles are the real shape ---------------------------------------


def test_the_double_matches_the_real_export_service_signature(api, exports):
    """The API's call must bind against the REAL service, not only the double.

    A double is free to accept anything, so on its own it proves nothing about
    production. ``inspect.signature(...).bind`` on the real, unbound method is
    what makes the contract real without spending 6.8 minutes on it.
    """
    status, body = start_export(api, mode="per_seed")
    assert status == 202
    assert exports.entered.wait(timeout=WAIT)
    call = exports.calls[0]

    for method in (ExportService.export_per_seed, ExportService.export_combined):
        inspect.signature(method).bind(
            ExportService,
            call["track_ids"],
            call["target"],
            call["recommendations_per_track"],
            progress=exports.progress,
            cancel=exports.cancel,
        )

    settle(api, exports, body["job"]["id"])


def test_starting_an_export_returns_202_and_a_running_job(api, exports):
    status, body = start_export(api)

    assert status == 202, "202: accepted and not finished; 200 would say it is done"
    job = body["job"]
    assert job["state"] == RUNNING
    assert job["kind"] == "export"
    assert job["progress"] == {"current": 0, "total": 2, "message": "Exporting 2 tracks"}
    assert job["result"] is None
    assert job["error"] is None
    assert job["cancel_requested"] is False
    assert job["finished_at"] is None

    settle(api, exports, job["id"])


def test_the_export_service_is_called_with_the_requested_seeds_and_target(
    api, exports
):
    status, body = start_export(
        api, out_dir="/tmp/here", track_ids="f03\nf01", recommendations_per_track=25
    )
    assert status == 202
    assert exports.entered.wait(timeout=WAIT)

    assert exports.calls == [
        {
            "name": "per_seed",
            # Order is the caller's, not a set's: inventory defect #13 is that
            # the Tkinter tab exports in arbitrary order.
            "track_ids": ["f03", "f01"],
            "target": "/tmp/here",
            "recommendations_per_track": 25,
        }
    ]
    settle(api, exports, body["job"]["id"])


def test_combined_mode_writes_one_named_file_inside_the_chosen_directory(
    api, exports
):
    status, body = start_export(api, mode="combined", out_dir="/tmp/here")
    assert status == 202
    assert exports.entered.wait(timeout=WAIT)

    call = exports.calls[0]
    assert call["name"] == "combined"
    assert call["target"] == f"/tmp/here/{COMBINED_EXPORT_FILENAME}"

    settle(api, exports, body["job"]["id"])


def test_omitting_track_ids_exports_the_whole_library(api, exports):
    """The 6.8-minute case, and the one that does not fit in a 16 KiB body."""
    status, body = start_export(api, track_ids=_ABSENT)
    assert status == 202
    assert exports.entered.wait(timeout=WAIT)

    assert len(exports.calls[0]["track_ids"]) == 14
    assert body["job"]["progress"]["total"] == 14

    settle(api, exports, body["job"]["id"])


def test_the_default_recommendation_count_is_passed_when_none_is_given(api, exports):
    status, body = start_export(api)
    assert status == 202
    assert exports.entered.wait(timeout=WAIT)

    assert exports.calls[0]["recommendations_per_track"] == 10

    settle(api, exports, body["job"]["id"])


def test_progress_from_the_service_is_visible_to_a_poller(api, exports):
    status, body = start_export(api)
    job_id = body["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)

    exports.progress(1, 2, "Blawan - Why They Hide")

    assert read_job(api, job_id)["progress"] == {
        "current": 1,
        "total": 2,
        "message": "Blawan - Why They Hide",
    }
    settle(api, exports, job_id)


def test_the_job_list_carries_every_remembered_job(api, exports):
    """A finished job is still listed, beside the one running now."""
    status, body = start_export(api)
    first_id = body["job"]["id"]
    settle(api, exports, first_id)

    exports.release.clear()
    exports.entered.clear()
    status, body = start_export(api, out_dir="/tmp/second")
    assert status == 202
    second_id = body["job"]["id"]

    status, listing = api.handle("GET", "/api/jobs", {})
    assert status == 200
    assert [job["id"] for job in listing["jobs"]] == [second_id, first_id]
    assert [job["state"] for job in listing["jobs"]] == [RUNNING, SUCCEEDED]

    settle(api, exports, second_id)


def test_an_unknown_job_is_404_unknown_job(api):
    status, body = api.handle("GET", "/api/jobs/nope", {})

    assert status == 404
    assert body["error"]["code"] == "unknown_job"
    assert "nope" in body["error"]["message"]


# -- results ---------------------------------------------------------------


def test_a_finished_export_reports_the_counts_and_where_it_wrote(api, exports):
    status, body = start_export(api, out_dir="/tmp/here")
    job = settle(api, exports, body["job"]["id"])

    assert job["state"] == SUCCEEDED
    assert job["result"] == {
        "mode": "per_seed",
        "output": "/tmp/here",
        "total_tracks": 2,
        "successful": 2,
        "failed": 0,
        "total_recommendations": 20,
        "playlists_created": 2,
        "cancelled": False,
    }
    assert job["finished_at"] is not None


def test_combined_mode_reports_playlists_created_as_an_explicit_null(api):
    """Not an absent key. ``as_legacy_stats`` omits it, and that omission is
    what makes the Tkinter tab raise ``KeyError`` and show no completion
    dialog (inventory defect #10) - a defect of that caller, preserved at the
    service boundary. A JSON consumer that never had the defect must not
    inherit it from a missing field."""
    exports = FakeExportService(
        result=ExportResult(
            total_tracks=2,
            successful=2,
            failed=0,
            total_recommendations=17,
            playlists_created=None,
        )
    )
    api = CocoApi(api.library, api.settings, export_service_factory=exports)
    status, body = start_export(api, mode="combined", out_dir="/tmp/here")
    job = settle(api, exports, body["job"]["id"])

    assert "playlists_created" in job["result"]
    assert job["result"]["playlists_created"] is None
    assert job["result"]["output"] == f"/tmp/here/{COMBINED_EXPORT_FILENAME}"


def test_a_service_that_raises_lands_the_job_in_failed_with_the_message(api):
    exports = FakeExportService(
        raises=FileNotFoundError(2, "No such file or directory", "/nope/out.m3u")
    )
    api = CocoApi(api.library, api.settings, export_service_factory=exports)
    status, body = start_export(api, mode="combined", out_dir="/nope")
    job = settle(api, exports, body["job"]["id"])

    assert job["state"] == FAILED
    assert job["result"] is None
    assert "FileNotFoundError" in job["error"]
    assert "No such file or directory" in job["error"]


# -- cancelling ------------------------------------------------------------


def test_cancelling_sets_the_event_the_service_is_holding(api, exports):
    status, body = start_export(api)
    job_id = body["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)
    assert exports.cancel.is_set() is False

    status, cancelled = api.handle("POST", f"/api/jobs/{job_id}/cancel", {}, {})

    assert status == 200
    assert cancelled["job"]["cancel_requested"] is True
    assert exports.cancel.is_set() is True, (
        "the cancel must reach the object the service is reading, not only the record"
    )
    settle(api, exports, job_id)


def test_a_cancelled_export_keeps_and_reports_what_it_wrote(api):
    """The user-visible half of the partial-results decision.

    ``ExportService`` returns real counts beside ``cancelled=True`` - the M3U
    files already on disk are complete and stay there. The terminal record has
    to carry those counts and the directory, or a UI can only say "cancelled"
    about a directory that is not empty.
    """
    exports = FakeExportService(
        result=ExportResult(
            total_tracks=1532,
            successful=47,
            failed=0,
            total_recommendations=470,
            playlists_created=47,
            cancelled=True,
        )
    )
    api = CocoApi(api.library, api.settings, export_service_factory=exports)
    status, body = start_export(api, out_dir="/tmp/here")
    job_id = body["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)
    api.handle("POST", f"/api/jobs/{job_id}/cancel", {}, {})

    job = settle(api, exports, job_id)

    assert job["state"] == CANCELLED
    assert job["result"]["cancelled"] is True
    assert job["result"]["playlists_created"] == 47
    assert job["result"]["total_tracks"] == 1532
    assert job["result"]["output"] == "/tmp/here"


def test_a_cancel_the_service_never_observed_is_reported_beside_the_success(api):
    """Inventory defect #17's shape, made visible instead of guessed at.

    A service that returns ``cancelled=False`` after a cancel was requested
    is saying the run completed for real - the signal arrived too late to
    change anything. Reporting that as ``cancelled`` would claim work was
    discarded that was in fact kept, so the state stays ``succeeded`` and
    ``cancel_requested`` carries the other half of the story.
    """
    exports = FakeExportService(
        result=ExportResult(
            total_tracks=2,
            successful=2,
            failed=0,
            total_recommendations=20,
            playlists_created=2,
            cancelled=False,
        )
    )
    api = CocoApi(api.library, api.settings, export_service_factory=exports)
    status, body = start_export(api)
    job_id = body["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)
    api.handle("POST", f"/api/jobs/{job_id}/cancel", {}, {})

    job = settle(api, exports, job_id)

    assert job["state"] == SUCCEEDED
    assert job["cancel_requested"] is True
    assert job["result"]["successful"] == 2


def test_cancelling_a_finished_job_is_200_and_says_what_it_did(api, exports):
    status, body = start_export(api)
    job_id = body["job"]["id"]
    settle(api, exports, job_id)

    status, cancelled = api.handle("POST", f"/api/jobs/{job_id}/cancel", {}, {})

    assert status == 200, "pressing Stop as a run completes is not an error"
    assert cancelled["job"]["state"] == SUCCEEDED
    assert cancelled["job"]["cancel_requested"] is False


def test_cancelling_an_unknown_job_is_404(api):
    status, body = api.handle("POST", "/api/jobs/nope/cancel", {}, {})

    assert status == 404
    assert body["error"]["code"] == "unknown_job"


def test_a_cancel_body_with_fields_is_refused(api):
    status, body = api.handle("POST", "/api/jobs/whatever/cancel", {}, {"force": True})

    assert status == 400
    assert body["error"]["code"] == "bad_request"


# -- one at a time ---------------------------------------------------------


def test_a_second_job_is_409_naming_the_one_already_running(api, exports):
    status, body = start_export(api)
    running_id = body["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)

    status, refused = start_export(api, out_dir="/tmp/elsewhere")

    assert status == 409
    assert refused["error"]["code"] == "job_in_progress"
    assert running_id in refused["error"]["message"]
    assert "export" in refused["error"]["message"]
    # The refused job never reached the service.
    assert len(exports.calls) == 1
    # ...and the running one is untouched.
    assert read_job(api, running_id)["state"] == RUNNING

    settle(api, exports, running_id)


def test_a_second_export_is_refused_too(api, exports):
    status, body = start_export(api)
    job_id = body["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)

    status, refused = start_export(api, out_dir="/tmp/elsewhere")

    assert status == 409
    assert len(exports.calls) == 1, "the second export must not reach the service"

    settle(api, exports, job_id)


def test_a_job_can_start_once_the_previous_one_has_finished(api, exports):
    status, body = start_export(api)
    settle(api, exports, body["job"]["id"])

    exports.release.clear()
    exports.entered.clear()
    status, body = start_export(api, out_dir="/tmp/second")

    assert status == 202
    settle(api, exports, body["job"]["id"])


# -- request validation ----------------------------------------------------


@pytest.mark.parametrize(
    "body, code",
    [
        ({"out_dir": "/tmp/x", "mode": "sideways"}, "bad_request"),
        ({"out_dir": ""}, "bad_request"),
        ({"out_dir": "   "}, "bad_request"),
        ({}, "bad_request"),
        ({"out_dir": 7}, "bad_request"),
        ({"out_dir": "/tmp/x", "out_directory": "/tmp/y"}, "bad_request"),
        ({"out_dir": "/tmp/x", "recommendations_per_track": 0}, "bad_request"),
        ({"out_dir": "/tmp/x", "recommendations_per_track": 101}, "bad_request"),
        ({"out_dir": "/tmp/x", "recommendations_per_track": "10"}, "bad_request"),
        ({"out_dir": "/tmp/x", "recommendations_per_track": True}, "bad_request"),
        ({"out_dir": "/tmp/x", "track_ids": ""}, "bad_request"),
        ({"out_dir": "/tmp/x", "track_ids": "f01\n"}, "bad_request"),
        ({"out_dir": "/tmp/x", "track_ids": "f01\nf01"}, "bad_request"),
        ({"out_dir": "/tmp/x", "track_ids": ["f01"]}, "bad_request"),
        ({"out_dir": "/tmp/x", "track_ids": "f01\nnope"}, "unknown_track"),
    ],
)
def test_a_bad_export_request_is_refused_before_any_job_starts(
    api, exports, body, code
):
    status, response = api.handle("POST", "/api/jobs/export", {}, body)

    assert status in (400, 404)
    assert response["error"]["code"] == code
    assert exports.calls == []
    assert api.jobs.all() == ()


def test_an_over_long_output_path_is_refused(api, exports):
    status, response = api.handle(
        "POST", "/api/jobs/export", {}, {"out_dir": "/" + "x" * 5000}
    )

    assert status == 400
    assert "4096" in response["error"]["message"]
    assert api.jobs.all() == ()


def test_a_non_object_export_body_is_refused(api):
    status, response = api.handle("POST", "/api/jobs/export", {}, ["f01"])

    assert status == 400
    assert response["error"]["code"] == "bad_request"


def test_exporting_a_library_with_no_index_is_409_empty_library(
    empty_library, settings, exports
):
    api = CocoApi(empty_library, settings, export_service_factory=exports)

    status, response = api.handle("POST", "/api/jobs/export", {}, {"out_dir": "/tmp/x"})

    assert status == 409
    assert response["error"]["code"] == "empty_library"
    assert exports.calls == []


def test_a_null_body_is_an_empty_object(api, exports):
    """A caller with nothing to say may POST ``null`` rather than ``{}``.

    Export needs an ``out_dir``, so neither spelling can start a job - and
    that is what makes the two comparable. The refusal has to be the one
    ``{}`` earns, about the MISSING FIELD, rather than the one an
    unrecognised body earns ("The JSON body must be an object"). Read as
    a non-object, ``null`` would be refused for the wrong reason and a
    caller would go looking for a malformed request it never sent.
    """
    from_null = api.handle("POST", "/api/jobs/export", {}, None)
    from_empty = api.handle("POST", "/api/jobs/export", {}, {})

    assert from_null == from_empty
    assert from_null[0] == 400
    assert "out_dir" in from_null[1]["error"]["message"]
    assert exports.calls == []
    assert api.jobs.all() == ()


# -- what this PR does NOT ship -------------------------------------------


def test_there_is_no_reindex_route_in_this_pr(api, exports):
    """The cut route stays cut until its data directory is its own.

    ``POST /api/jobs/reindex`` was removed on review, and ``web.api``'s
    DEFERRED note carries both reasons in full. The short version is that
    ``IndexingService.run`` has no data-directory parameter and the pipeline
    persists through ``config.DATA``, so a re-index started from a window
    opened with ``--data-dir X`` overwrites the DEFAULT library's four files.

    Pinned here rather than left to the route table's own shape, because the
    two ways it could come back look nothing alike from the outside: a row
    restored in ``ROUTES`` and a handler restored on ``CocoApi``. Both are
    checked, and so is what a caller gets today.
    """
    assert not hasattr(CocoApi, "_start_reindex")
    assert [
        (verb, pattern.pattern)
        for verb, pattern, _ in CocoApi.ROUTES
        if "reindex" in pattern.pattern
    ] == []

    status, response = api.handle("POST", "/api/jobs/reindex", {}, {})

    # 405, not 404, and the route table is why: ``/api/jobs/reindex`` still
    # matches the ``GET /api/jobs/{job_id}`` pattern, so ``handle`` finds the
    # PATH and refuses the VERB. That is the same answer POSTing to any other
    # job id gets, which is the point - "reindex" is not a special word here
    # any more.
    assert status == 405
    assert response["error"]["code"] == "method_not_allowed"
    assert api.handle("POST", "/api/jobs/anything-else", {}, {}) == (status, response)
    assert exports.calls == []
    assert api.jobs.all() == ()
