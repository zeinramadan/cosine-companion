"""The re-index job route, including its two data-loss boundaries.

Fast lifecycle tests use blocking service doubles with bounded waits. The
refresh regression uses the real API, IndexingService, pipeline persistence,
LibrarySession publication, and delete path; only the audio embedder is a
deterministic eight-value fake, so the test neither imports Essentia nor skips
when TensorFlow is absent.
"""

import inspect
import threading
from urllib.parse import quote

import numpy as np
import pytest

from services.export_service import ExportResult
from services.indexing_service import (
    STATUS_INDEXED,
    STATUS_NO_EMBEDDINGS,
    IndexResult,
    IndexingService,
    ProgressEvent,
)
from services.library_session import LibrarySession
from services.settings_store import SettingsStore
from web.api import CocoApi
from web.jobs import CANCELLED, RUNNING, SUCCEEDED


WAIT = 5.0


class FakeIndexingService:
    """Factory and held service with the real constructor/run shapes."""

    def __init__(self, result=None, raises=None):
        self.result = result or IndexResult(
            status=STATUS_INDEXED,
            total_tracks_indexed=15,
            new_tracks_added=1,
            new_tracks_found=1,
        )
        self.raises = raises
        self.constructions = []
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.progress = None
        self.cancel = None

    def __call__(self, settings, data_dir, library=None):
        self.constructions.append(
            {"settings": settings, "data_dir": data_dir, "library": library}
        )
        return self

    def run(
        self, xml_path, force_full=False, progress=None, cancel=None, sample_size=None
    ):
        self.calls.append({"xml_path": xml_path, "force_full": force_full})
        self.progress = progress
        self.cancel = cancel
        self.entered.set()
        assert self.release.wait(timeout=WAIT), "the indexing double was not released"
        if self.raises is not None:
            raise self.raises
        return self.result


class FakeExportService:
    """The held export half of the cross-kind exclusion tests."""

    def __init__(self):
        self.libraries = []
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, library):
        self.libraries.append(library)
        return self

    def export_per_seed(
        self, track_ids, out_dir, recommendations_per_track, progress=None, cancel=None
    ):
        self.calls.append(list(track_ids))
        self.entered.set()
        assert self.release.wait(timeout=WAIT), "the export double was not released"
        return ExportResult(
            total_tracks=len(track_ids),
            successful=len(track_ids),
            failed=0,
            total_recommendations=len(track_ids) * recommendations_per_track,
            playlists_created=len(track_ids),
            cancelled=cancel is not None and cancel.is_set(),
        )

    def export_combined(self, *args, **kwargs):  # pragma: no cover - not needed here
        raise AssertionError("the cross-kind tests use per-seed export")


@pytest.fixture
def indexing():
    return FakeIndexingService()


@pytest.fixture
def exports():
    return FakeExportService()


@pytest.fixture
def api(web_library, settings, indexing, exports):
    return CocoApi(
        web_library,
        settings,
        export_service_factory=exports,
        indexing_service_factory=indexing,
    )


def start_reindex(api, body=None):
    return api.handle("POST", "/api/jobs/reindex", {}, body)


def start_export(api):
    return api.handle(
        "POST",
        "/api/jobs/export",
        {},
        {"out_dir": "/tmp/coco-reindex-exclusion", "track_ids": "f01"},
    )


def read_job(api, job_id):
    status, body = api.handle("GET", f"/api/jobs/{job_id}", {})
    assert status == 200
    return body["job"]


def settle(api, double, job_id):
    double.release.set()
    job = api.jobs.get(job_id)
    assert job is not None
    job.thread.join(timeout=WAIT)
    assert not job.thread.is_alive(), "the job worker did not finish"
    return read_job(api, job_id)


def test_literal_reindex_route_precedes_job_lookup_and_returns_202(api, indexing):
    """Before this route existed, POST matched ``{job_id}`` and returned 405."""
    literal = next(
        index
        for index, (verb, pattern, _handler) in enumerate(CocoApi.ROUTES)
        if verb == "POST" and pattern.pattern == r"^/api/jobs/reindex$"
    )
    job_lookup = next(
        index
        for index, (verb, pattern, _handler) in enumerate(CocoApi.ROUTES)
        if verb == "GET" and "(?P<job_id>" in pattern.pattern
        and not pattern.pattern.endswith("/cancel$")
    )
    assert literal < job_lookup

    status, body = start_reindex(api, {})

    assert status == 202
    assert body["job"]["kind"] == "reindex"
    assert body["job"]["state"] == RUNNING
    assert indexing.entered.wait(timeout=WAIT)
    settle(api, indexing, body["job"]["id"])


def test_api_constructs_the_guarded_service_over_its_live_library(
    api, indexing, web_library, settings
):
    status, body = start_reindex(api, {})
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)

    assert indexing.constructions == [
        {
            "settings": settings,
            "data_dir": web_library.data_dir,
            "library": web_library,
        }
    ]
    settle(api, indexing, body["job"]["id"])


def test_indexing_service_guard_raises_on_a_deliberate_directory_mismatch(
    web_library, settings, tmp_path
):
    wrong_library = tmp_path / "different-library"

    with pytest.raises(ValueError, match="must match LibrarySession.data_dir"):
        IndexingService(settings, data_dir=wrong_library, library=web_library)


def test_the_double_calls_bind_the_real_constructor_and_run_signatures(
    api, indexing
):
    status, body = start_reindex(api, {"force_full": True})
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)

    construction = indexing.constructions[0]
    inspect.signature(IndexingService.__init__).bind(
        IndexingService,
        construction["settings"],
        data_dir=construction["data_dir"],
        library=construction["library"],
    )
    call = indexing.calls[0]
    inspect.signature(IndexingService.run).bind(
        IndexingService,
        call["xml_path"],
        force_full=call["force_full"],
        progress=indexing.progress,
        cancel=indexing.cancel,
    )
    settle(api, indexing, body["job"]["id"])


@pytest.mark.parametrize(
    "force_full, expected_mode, expected_message",
    [
        (False, "incremental", "Checking for new tracks"),
        (True, "full", "Full re-index"),
    ],
)
def test_force_full_is_explicit_in_the_call_and_terminal_wire_result(
    api, indexing, settings, force_full, expected_mode, expected_message
):
    status, body = start_reindex(api, {"force_full": force_full})
    assert status == 202
    assert body["job"]["progress"]["message"] == expected_message
    assert indexing.entered.wait(timeout=WAIT)
    assert indexing.calls == [
        {"xml_path": settings.xml_path, "force_full": force_full}
    ]

    job = settle(api, indexing, body["job"]["id"])

    assert job["result"]["force_full"] is force_full
    assert job["result"]["requested_mode"] == expected_mode


def test_a_null_body_requests_incremental_mode(api, indexing):
    status, body = start_reindex(api, None)
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)
    assert indexing.calls[0]["force_full"] is False
    settle(api, indexing, body["job"]["id"])


@pytest.mark.parametrize(
    "body",
    [
        {"force_full": "yes"},
        {"force_full": 1},
        {"force_full": None},
        {"full": True},
        [],
    ],
)
def test_bad_reindex_bodies_are_refused_before_construction(api, indexing, body):
    status, response = start_reindex(api, body)

    assert status == 400
    assert response["error"]["code"] == "bad_request"
    assert indexing.constructions == []
    assert api.jobs.all() == ()


def test_no_configured_xml_is_409_before_service_construction(
    web_library, tmp_path, indexing
):
    settings = SettingsStore(tmp_path / "unset-settings.json")
    api = CocoApi(
        web_library, settings, indexing_service_factory=indexing
    )

    status, response = start_reindex(api, {})

    assert status == 409
    assert response["error"]["code"] == "no_xml_path"
    assert indexing.constructions == []
    assert api.jobs.all() == ()


def test_indexing_progress_is_narrowed_to_the_job_record(api, indexing):
    status, body = start_reindex(api, {})
    job_id = body["job"]["id"]
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)

    indexing.progress(
        ProgressEvent(phase="embed", current=7, total=15, message="[7/15]")
    )

    assert read_job(api, job_id)["progress"] == {
        "current": 7,
        "total": 15,
        "message": "[7/15]",
    }
    settle(api, indexing, job_id)


def test_no_embeddings_is_a_completed_job_with_the_failure_outcome(web_library, settings):
    indexing = FakeIndexingService(
        result=IndexResult(
            status=STATUS_NO_EMBEDDINGS,
            new_tracks_found=3,
        )
    )
    api = CocoApi(
        web_library, settings, indexing_service_factory=indexing
    )

    status, body = start_reindex(api, {})
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)
    job = settle(api, indexing, body["job"]["id"])

    assert job["state"] == SUCCEEDED
    assert job["result"]["status"] == STATUS_NO_EMBEDDINGS
    assert job["result"]["failed"] is True
    assert job["result"]["up_to_date"] is False
    assert job["result"]["new_tracks_found"] == 3


def test_observed_cancel_reports_cancelled_with_no_partial_result(
    web_library, settings
):
    indexing = FakeIndexingService(raises=KeyboardInterrupt("cancel checkpoint"))
    api = CocoApi(
        web_library, settings, indexing_service_factory=indexing
    )
    status, body = start_reindex(api, {"force_full": True})
    job_id = body["job"]["id"]
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)

    cancel_status, cancelled = api.handle(
        "POST", f"/api/jobs/{job_id}/cancel", {}, {}
    )
    assert cancel_status == 200
    assert cancelled["job"]["cancel_requested"] is True
    job = settle(api, indexing, job_id)

    assert job["state"] == CANCELLED
    assert job["result"] is None
    assert job["error"] is None


def test_reindex_result_cannot_be_published_as_cancelled_after_last_checkpoint(
    api, indexing
):
    status, body = start_reindex(api, {"force_full": True})
    job_id = body["job"]["id"]
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)

    api.handle("POST", f"/api/jobs/{job_id}/cancel", {}, {})
    job = settle(api, indexing, job_id)

    # A returned IndexResult is the only result-bearing reindex path. Even with
    # a pending stop, api.py hardcodes that WorkOutcome to cancelled=False; the
    # cancelled path is the KeyboardInterrupt path tested immediately above.
    assert not (job["state"] == CANCELLED and job["result"] is not None)
    assert job["state"] == SUCCEEDED
    assert job["cancel_requested"] is True
    assert job["result"]["status"] == STATUS_INDEXED
    assert job["result"]["requested_mode"] == "full"


def test_reindex_is_refused_while_an_export_is_running(api, exports, indexing):
    status, body = start_export(api)
    export_id = body["job"]["id"]
    assert status == 202
    assert exports.entered.wait(timeout=WAIT)

    status, refused = start_reindex(api, {})

    assert status == 409
    assert refused["error"]["code"] == "job_in_progress"
    assert export_id in refused["error"]["message"]
    assert "export" in refused["error"]["message"]
    assert indexing.calls == []
    settle(api, exports, export_id)


def test_export_is_refused_while_a_reindex_is_running(api, exports, indexing):
    status, body = start_reindex(api, {})
    reindex_id = body["job"]["id"]
    assert status == 202
    assert indexing.entered.wait(timeout=WAIT)

    status, refused = start_export(api)

    assert status == 409
    assert refused["error"]["code"] == "job_in_progress"
    assert reindex_id in refused["error"]["message"]
    assert "reindex" in refused["error"]["message"]
    assert exports.calls == []
    settle(api, indexing, reindex_id)


def _write_one_track_xml(path, track_id, audio_path):
    location = "file://localhost" + quote(str(audio_path))
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<DJ_PLAYLISTS Version="1.0.0">'
        '<COLLECTION Entries="1">'
        f'<TRACK TrackID="{track_id}" Name="New Track" Artist="New Artist" '
        'AverageBpm="125.00" Tonality="7A" Album="New Album" '
        f'Location="{location}"/>'
        '</COLLECTION>'
        '<PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/></PLAYLISTS>'
        '</DJ_PLAYLISTS>',
        encoding="utf-8",
    )


def test_success_republishes_the_api_session_before_a_delete(
    web_library, web_data_dir, settings, tmp_path, monkeypatch
):
    """The exact stale-snapshot loss: N→N+1, API read, then API delete."""
    import processing.pipeline as pipeline

    class EightValueEmbedder:
        def embed_file(self, path_local):
            assert path_local == str(audio)
            return np.array([1.0, 0.5, 0.25, 0.125, 0.0, 0.0, 0.0, 0.0])

    monkeypatch.setattr(pipeline, "DiscogsEffnetEmbedder", EightValueEmbedder)
    audio = tmp_path / "new-track.mp3"
    audio.write_bytes(b"fixture audio")
    new_id = "new-after-api-reindex"
    xml = tmp_path / "expanded-library.xml"
    _write_one_track_xml(xml, new_id, audio)
    settings.set("xml_path", str(xml))

    api = CocoApi(web_library, settings)
    before_status, before = api.handle("GET", "/api/library", {})
    assert before_status == 200
    original_count = before["track_count"]

    status, started = start_reindex(api, {"force_full": False})
    assert status == 202
    job_id = started["job"]["id"]
    job = api.jobs.get(job_id)
    assert job is not None
    job.thread.join(timeout=WAIT)
    assert not job.thread.is_alive(), "the real re-index job did not finish"
    terminal = read_job(api, job_id)
    assert terminal["state"] == SUCCEEDED, terminal
    assert terminal["result"]["total_tracks_indexed"] == original_count + 1

    after_status, after = api.handle("GET", "/api/library", {})
    assert after_status == 200
    assert after["track_count"] == original_count + 1
    assert web_library.get_track(new_id) is not None

    delete_status, deleted = api.handle(
        "POST",
        "/api/library/tracks/delete",
        {},
        {"track_ids": "f01"},
    )
    assert delete_status == 200
    assert deleted["library"]["track_count"] == original_count
    assert web_library.get_track(new_id) is not None

    reloaded = LibrarySession.load(web_data_dir)
    assert reloaded.track_count == original_count
    assert new_id in reloaded.ids
    assert reloaded.get_track(new_id) is not None
