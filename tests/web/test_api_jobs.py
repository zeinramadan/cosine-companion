"""The /api/jobs surface: starting, watching, cancelling, and the results.

Every service here is a double. The real ones take ~6.8 and ~11.5 minutes, so
running either would make this file unrunnable rather than slow. Two things
keep the doubles honest:

* ``test_the_double_matches_the_real_export_service_signature`` and its
  indexing twin bind the arguments this API really passes against the **real**
  service's signature with ``inspect``, so a double that drifts is a failure
  here rather than a 500 in production;
* ``tests/web/test_jobs_real_export.py`` runs the whole machinery against the
  real ``ExportService`` over the fixture library.

Every double blocks on a ``threading.Event`` with a bounded wait. Nothing
spins and nothing sleeps hoping.
"""

import inspect
import threading

import pytest

from services.export_service import ExportResult, ExportService
from services.indexing_service import (
    STATUS_INDEXED,
    STATUS_NO_EMBEDDINGS,
    STATUS_UP_TO_DATE,
    IndexResult,
    IndexingService,
    ProgressEvent,
)
from web.api import COMBINED_EXPORT_FILENAME, CocoApi
from web.jobs import CANCELLED, FAILED, RUNNING, SUCCEEDED

WAIT = 5.0


class FakeExportService:
    """Records its call, holds it open until released, returns a fixed result."""

    def __init__(self, result=None, raises=None):
        self.calls = []
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


class FakeIndexingService:
    """The same, for ``IndexingService.run``."""

    def __init__(self, result=None, raises=None):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.result = result or IndexResult(
            status=STATUS_INDEXED, total_tracks_indexed=14, new_tracks_added=2
        )
        self.raises = raises
        self.progress = None
        self.cancel = None

    def run(
        self, xml_path, force_full=False, progress=None, cancel=None, sample_size=None
    ):
        self.calls.append({"xml_path": xml_path, "force_full": force_full})
        self.progress = progress
        self.cancel = cancel
        self.entered.set()
        assert self.release.wait(timeout=WAIT), "the indexing double was never released"
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.fixture
def exports():
    return FakeExportService()


@pytest.fixture
def indexing():
    return FakeIndexingService()


@pytest.fixture
def api(web_library, settings, exports, indexing):
    return CocoApi(
        web_library, settings, export_service=exports, indexing_service=indexing
    )


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


def test_the_double_matches_the_real_indexing_service_signature(api, indexing):
    api.handle("POST", "/api/jobs/reindex", {}, {})
    assert indexing.entered.wait(timeout=WAIT)
    call = indexing.calls[0]

    inspect.signature(IndexingService.run).bind(
        IndexingService,
        call["xml_path"],
        force_full=call["force_full"],
        progress=indexing.progress,
        cancel=indexing.cancel,
    )

    settle(api, indexing, api.jobs.all()[0].job_id)


# -- starting --------------------------------------------------------------


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


def test_starting_a_reindex_passes_the_configured_xml_path(api, indexing, settings):
    status, body = api.handle("POST", "/api/jobs/reindex", {}, {"force_full": True})

    assert status == 202
    assert body["job"]["kind"] == "reindex"
    assert body["job"]["progress"]["message"] == "Full re-index"
    assert indexing.entered.wait(timeout=WAIT)
    assert indexing.calls == [
        {"xml_path": settings.get("xml_path"), "force_full": True}
    ]

    settle(api, indexing, body["job"]["id"])


# -- watching --------------------------------------------------------------


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


def test_indexing_progress_events_are_narrowed_to_the_job_record(api, indexing):
    """``ProgressEvent`` carries a phase; the job record carries three fields.

    The phase is dropped here rather than widening every job for one producer.
    ``total`` travels untouched, including the 0 the pipeline sends outside the
    embedding phase, which a UI reads as indeterminate.
    """
    status, body = api.handle("POST", "/api/jobs/reindex", {}, {})
    job_id = body["job"]["id"]
    assert indexing.entered.wait(timeout=WAIT)

    indexing.progress(ProgressEvent(phase="parse", current=0, total=0, message="Parsing"))
    assert read_job(api, job_id)["progress"] == {
        "current": 0,
        "total": 0,
        "message": "Parsing",
    }

    indexing.progress(
        ProgressEvent(phase="embed", current=137, total=1307, message="[137/1307]")
    )
    assert read_job(api, job_id)["progress"] == {
        "current": 137,
        "total": 1307,
        "message": "[137/1307]",
    }

    settle(api, indexing, job_id)


def test_the_job_list_carries_every_remembered_job(api, exports, indexing):
    status, body = start_export(api)
    export_id = body["job"]["id"]
    settle(api, exports, export_id)

    status, body = api.handle("POST", "/api/jobs/reindex", {}, {})
    reindex_id = body["job"]["id"]

    status, listing = api.handle("GET", "/api/jobs", {})
    assert status == 200
    assert [job["id"] for job in listing["jobs"]] == [reindex_id, export_id]
    assert [job["kind"] for job in listing["jobs"]] == ["reindex", "export"]

    settle(api, indexing, reindex_id)


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
    api = CocoApi(api.library, api.settings, export_service=exports)
    status, body = start_export(api, mode="combined", out_dir="/tmp/here")
    job = settle(api, exports, body["job"]["id"])

    assert "playlists_created" in job["result"]
    assert job["result"]["playlists_created"] is None
    assert job["result"]["output"] == f"/tmp/here/{COMBINED_EXPORT_FILENAME}"


def test_a_reindex_result_carries_the_outcome_the_tkinter_windows_hide(api):
    """``no_embeddings`` reads as success in both Tk windows. Not here.

    The job's own ``state`` is still ``succeeded`` - the run completed and did
    not raise - but ``status`` and ``failed`` travel in the result, which is
    what lets a later UI render the distinction deliberately.
    """
    indexing = FakeIndexingService(
        result=IndexResult(
            status=STATUS_NO_EMBEDDINGS, new_tracks_found=1307, new_tracks_added=0
        )
    )
    api = CocoApi(api.library, api.settings, indexing_service=indexing)
    status, body = api.handle("POST", "/api/jobs/reindex", {}, {})
    job = settle(api, indexing, body["job"]["id"])

    assert job["state"] == SUCCEEDED
    assert job["result"]["status"] == STATUS_NO_EMBEDDINGS
    assert job["result"]["failed"] is True
    assert job["result"]["up_to_date"] is False
    assert job["result"]["new_tracks_found"] == 1307


def test_an_up_to_date_reindex_is_reported_as_such(api):
    indexing = FakeIndexingService(result=IndexResult(status=STATUS_UP_TO_DATE))
    api = CocoApi(api.library, api.settings, indexing_service=indexing)
    status, body = api.handle("POST", "/api/jobs/reindex", {}, {})
    job = settle(api, indexing, body["job"]["id"])

    assert job["result"]["status"] == STATUS_UP_TO_DATE
    assert job["result"]["up_to_date"] is True
    assert job["result"]["failed"] is False


def test_a_service_that_raises_lands_the_job_in_failed_with_the_message(api):
    exports = FakeExportService(
        raises=FileNotFoundError(2, "No such file or directory", "/nope/out.m3u")
    )
    api = CocoApi(api.library, api.settings, export_service=exports)
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
    api = CocoApi(api.library, api.settings, export_service=exports)
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


def test_a_cancelled_reindex_reports_no_result_at_all(api):
    """Indexing's opposite answer, and it is the pipeline's, not this PR's.

    ``IndexingService.run`` raises ``KeyboardInterrupt`` at the checkpoint and
    every embedding computed so far is discarded (inventory defect #4). There
    is no partial result to report, and inventing one would claim work exists
    that does not.
    """
    indexing = FakeIndexingService(raises=KeyboardInterrupt())
    api = CocoApi(api.library, api.settings, indexing_service=indexing)
    status, body = api.handle("POST", "/api/jobs/reindex", {}, {})
    job_id = body["job"]["id"]
    assert indexing.entered.wait(timeout=WAIT)
    api.handle("POST", f"/api/jobs/{job_id}/cancel", {}, {})

    job = settle(api, indexing, job_id)

    assert job["state"] == CANCELLED
    assert job["result"] is None
    assert job["error"] is None


def test_a_cancel_the_pipeline_never_observed_is_reported_beside_the_success(api):
    """Inventory defect #17, made visible instead of guessed at."""
    indexing = FakeIndexingService(
        result=IndexResult(status=STATUS_INDEXED, total_tracks_indexed=1307)
    )
    api = CocoApi(api.library, api.settings, indexing_service=indexing)
    status, body = api.handle("POST", "/api/jobs/reindex", {}, {})
    job_id = body["job"]["id"]
    assert indexing.entered.wait(timeout=WAIT)
    api.handle("POST", f"/api/jobs/{job_id}/cancel", {}, {})

    job = settle(api, indexing, job_id)

    assert job["state"] == SUCCEEDED
    assert job["cancel_requested"] is True
    assert job["result"]["status"] == STATUS_INDEXED


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


def test_a_second_job_is_409_naming_the_one_already_running(api, exports, indexing):
    status, body = start_export(api)
    running_id = body["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)

    status, refused = api.handle("POST", "/api/jobs/reindex", {}, {})

    assert status == 409
    assert refused["error"]["code"] == "job_in_progress"
    assert running_id in refused["error"]["message"]
    assert "export" in refused["error"]["message"]
    # The refused job never reached the service.
    assert indexing.calls == []
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


def test_a_job_can_start_once_the_previous_one_has_finished(api, exports, indexing):
    status, body = start_export(api)
    settle(api, exports, body["job"]["id"])

    status, body = api.handle("POST", "/api/jobs/reindex", {}, {})

    assert status == 202
    settle(api, indexing, body["job"]["id"])


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
    api = CocoApi(empty_library, settings, export_service=exports)

    status, response = api.handle("POST", "/api/jobs/export", {}, {"out_dir": "/tmp/x"})

    assert status == 409
    assert response["error"]["code"] == "empty_library"
    assert exports.calls == []


def test_a_reindex_with_no_configured_xml_is_409_no_xml_path(
    web_library, tmp_path, indexing
):
    from services.settings_store import SettingsStore

    blank = SettingsStore(tmp_path / "blank.json")
    api = CocoApi(web_library, blank, indexing_service=indexing)

    status, response = api.handle("POST", "/api/jobs/reindex", {}, {})

    assert status == 409
    assert response["error"]["code"] == "no_xml_path"
    assert indexing.calls == []


@pytest.mark.parametrize(
    "body", [{"force_full": "yes"}, {"force_full": 1}, {"full": True}]
)
def test_a_bad_reindex_request_is_refused(api, indexing, body):
    status, response = api.handle("POST", "/api/jobs/reindex", {}, body)

    assert status == 400
    assert response["error"]["code"] == "bad_request"
    assert indexing.calls == []


def test_a_null_body_is_an_empty_object(api, indexing):
    """A caller with nothing to say may POST ``null`` rather than ``{}``."""
    status, body = api.handle("POST", "/api/jobs/reindex", {}, None)

    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)
    assert indexing.calls[0]["force_full"] is False

    settle(api, indexing, body["job"]["id"])
