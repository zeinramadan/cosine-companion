"""The job routes over a real socket: auth, verbs, and the JSON on the wire.

``tests/web/test_api_jobs.py`` drives ``CocoApi.handle`` directly, which never
touches the server. These are the properties that only exist once a request
has been through ``_dispatch``: the token check, the Host check, HEAD, an
undefined verb, and whether the document survives ``json.dumps`` at all.

The point of the auth cases is PR #14: the job endpoints are state-changing
and must go through the **same** choke point as everything else. "No new door"
is not provable by reading the route table - ``__getattr__`` routes verbs
nobody defined, so the test has to send them.
"""

import json
import threading

import pytest

from services.export_service import ExportResult
from web.api import CocoApi
from web.jobs import SUCCEEDED
from web.server import API_ALLOWED_METHODS, CocoServer

WAIT = 5.0

#: Every job route this PR ships. The auth cases below are parameterised over
#: this so a route added later without a token check is a failure rather than
#: an omission. ``POST /api/jobs/reindex`` is deliberately absent - it was cut
#: on review; see ``web.api``'s DEFERRED note.
JOB_ROUTES = [
    ("GET", "/api/jobs"),
    ("GET", "/api/jobs/anything"),
    ("POST", "/api/jobs/export"),
    ("POST", "/api/jobs/anything/cancel"),
]


class HeldExportService:
    """A stand-in export that blocks until released. Never spins."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cancel = None

    def __call__(self, library):
        """The factory call ``CocoApi`` makes per accepted export."""
        return self

    def export_per_seed(
        self, track_ids, out_dir, recommendations_per_track, progress=None, cancel=None
    ):
        self.cancel = cancel
        self.entered.set()
        assert self.release.wait(timeout=WAIT), "the export double was never released"
        return ExportResult(
            total_tracks=len(track_ids),
            successful=len(track_ids),
            failed=0,
            total_recommendations=len(track_ids) * 10,
            playlists_created=len(track_ids),
            cancelled=cancel is not None and cancel.is_set(),
        )

    def export_combined(self, *args, **kwargs):  # pragma: no cover - unused here
        raise AssertionError("combined mode is not exercised on the wire")


@pytest.fixture
def exports():
    return HeldExportService()


@pytest.fixture
def job_server(web_library, settings, exports, static_dir):
    api = CocoApi(web_library, settings, export_service_factory=exports)
    running = CocoServer(api, static_dir)
    running.start()
    try:
        yield running
    finally:
        running.stop()


@pytest.fixture
def job_client(job_server):
    from webtest_support import Client

    return Client("127.0.0.1", job_server.port)


def post_json(client, path, payload, token):
    return client.post(path, json.dumps(payload).encode("utf-8"), token=token)


def settle(job_server, exports, job_id):
    exports.release.set()
    job = job_server.api.jobs.get(job_id)
    assert job is not None
    job.thread.join(timeout=WAIT)
    assert not job.thread.is_alive()


# -- the same door as everything else --------------------------------------


@pytest.mark.parametrize("method, path", JOB_ROUTES)
def test_a_job_route_without_a_token_is_401(job_client, method, path):
    response = job_client.request(method, path, {"Content-Type": "application/json"})

    assert response.status == 401
    assert response.error_code == "unauthorized"


@pytest.mark.parametrize("method, path", JOB_ROUTES)
def test_a_job_route_with_the_wrong_token_is_401(job_client, method, path):
    response = job_client.request(
        method,
        path,
        {"X-Coco-Token": "not-the-token", "Content-Type": "application/json"},
    )

    assert response.status == 401
    assert response.error_code == "unauthorized"


@pytest.mark.parametrize("method, path", JOB_ROUTES)
def test_a_job_route_with_no_host_header_is_403(job_client, job_server, method, path):
    response = job_client.request(
        method,
        path,
        {"X-Coco-Token": job_server.token, "Content-Type": "application/json"},
        host_header=False,
    )

    assert response.status == 403
    assert response.error_code == "forbidden"


@pytest.mark.parametrize("verb", ["PUT", "DELETE", "PATCH", "TRACE", "FROBNICATE"])
def test_an_undefined_verb_on_a_job_route_behaves_like_every_other_route(
    job_client, job_server, verb
):
    """PR #14's property, re-proved on the new routes.

    There is no ``do_PUT``; ``_Handler.__getattr__`` is what makes the lookup
    succeed so ``_dispatch`` - and therefore the token check - owns the
    decision. An unauthenticated probe must get 401, not the stdlib's 501 HTML
    page, and an authenticated one must get a JSON 405 with an Allow header.
    """
    unauthenticated = job_client.request(verb, "/api/jobs")
    assert unauthenticated.status == 401
    assert unauthenticated.error_code == "unauthorized"
    assert "json" in unauthenticated.content_type

    authenticated = job_client.request(
        verb, "/api/jobs", {"X-Coco-Token": job_server.token}
    )
    assert authenticated.status == 405
    assert authenticated.error_code == "method_not_allowed"
    assert authenticated.headers.get("Allow") == API_ALLOWED_METHODS


def test_head_on_a_job_route_is_the_get_with_no_body(job_client, job_server):
    """RFC 9110 §9.3.2: a HEAD response is the GET's, content removed.

    ``_dispatch`` aliases HEAD to GET before the two servers, so this reaches
    the token check by exactly the same route, and ``_send`` drops the content
    at the last moment while keeping the GET's Content-Length. That is the
    property a streaming progress endpoint could not have kept - see
    ``web.jobs``'s module docstring.
    """
    getted = job_client.get("/api/jobs", token=job_server.token)
    headed = job_client.request(
        "HEAD", "/api/jobs", {"X-Coco-Token": job_server.token}
    )

    assert headed.status == getted.status == 200
    assert headed.headers["Content-Length"] == getted.headers["Content-Length"]
    assert headed.headers["Content-Type"] == getted.headers["Content-Type"]
    assert headed.body == b""
    assert getted.body != b""


def test_head_on_a_job_route_leaves_the_connection_usable(job_server):
    """The bytes a HEAD wrongly wrote would show up on the NEXT response.

    Reuses one keep-alive connection, which is the only way this is
    observable: a client stops reading a HEAD response on the method's
    semantics, so a stray body is silent until it is parsed as the start of
    the following response.
    """
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", job_server.port, timeout=WAIT)
    try:
        headers = {"X-Coco-Token": job_server.token}
        connection.request("HEAD", "/api/jobs", headers=headers)
        connection.getresponse().read()

        connection.request("GET", "/api/jobs", headers=headers)
        second = connection.getresponse()
        payload = second.read()
    finally:
        connection.close()

    assert second.status == 200
    assert json.loads(payload.decode("utf-8"))["jobs"] == []


def test_a_job_start_still_requires_a_json_content_type(job_client, job_server):
    response = job_client.post(
        "/api/jobs/export",
        b'{"out_dir": "/tmp/x"}',
        token=job_server.token,
        content_type="text/plain",
    )

    assert response.status == 415
    assert response.error_code == "unsupported_media_type"
    assert job_server.api.jobs.all() == ()


def test_a_job_start_with_a_malformed_body_is_400(job_client, job_server):
    response = job_client.post(
        "/api/jobs/export", b"{not json", token=job_server.token
    )

    assert response.status == 400
    assert job_server.api.jobs.all() == ()


# -- the document on the wire ---------------------------------------------


def test_the_whole_lifecycle_over_http(job_client, job_server, exports, tmp_path):
    """Start, poll, cancel, read the terminal record - all through the socket."""
    token = job_server.token
    out_dir = str(tmp_path / "playlists")

    started = post_json(
        job_client,
        "/api/jobs/export",
        {"out_dir": out_dir, "track_ids": "f01\nf02\nf03"},
        token,
    )
    assert started.status == 202
    job_id = started.json["job"]["id"]
    assert started.json["job"]["state"] == "running"
    assert exports.entered.wait(timeout=WAIT)

    polled = job_client.get(f"/api/jobs/{job_id}", token=token)
    assert polled.status == 200
    assert polled.json["job"]["id"] == job_id
    assert polled.json["job"]["progress"]["total"] == 3

    listed = job_client.get("/api/jobs", token=token)
    assert [job["id"] for job in listed.json["jobs"]] == [job_id]

    cancelled = post_json(job_client, f"/api/jobs/{job_id}/cancel", {}, token)
    assert cancelled.status == 200
    assert cancelled.json["job"]["cancel_requested"] is True
    assert exports.cancel.is_set() is True

    settle(job_server, exports, job_id)

    final = job_client.get(f"/api/jobs/{job_id}", token=token)
    assert final.json["job"]["state"] == "cancelled"
    assert final.json["job"]["result"]["cancelled"] is True
    assert final.json["job"]["result"]["output"] == out_dir


def test_a_job_result_arrives_as_a_json_object(job_client, job_server, exports):
    """``JobSnapshot.result`` is a MappingProxyType, which is not a ``dict``.

    ``_jsonable``'s dict branch is an ``isinstance(value, dict)`` test, and a
    ``MappingProxyType`` fails it - it would fall through to the final
    ``str()`` fallback and put ``"mappingproxy({'mode': ...})"`` on the wire as
    a string. That is invisible in a unit test that reads ``result["mode"]``
    off a live object, and obvious here.
    """
    token = job_server.token
    started = post_json(
        job_client, "/api/jobs/export", {"out_dir": "/tmp/x", "track_ids": "f01"}, token
    )
    job_id = started.json["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)
    settle(job_server, exports, job_id)

    result = job_client.get(f"/api/jobs/{job_id}", token=token).json["job"]["result"]

    assert isinstance(result, dict), f"result came back as {type(result).__name__}"
    assert result["mode"] == "per_seed"
    assert result["successful"] == 1


def test_the_second_job_is_a_409_on_the_wire(job_client, job_server, exports):
    token = job_server.token
    started = post_json(
        job_client, "/api/jobs/export", {"out_dir": "/tmp/x", "track_ids": "f01"}, token
    )
    job_id = started.json["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)

    refused = post_json(
        job_client,
        "/api/jobs/export",
        {"out_dir": "/tmp/y", "track_ids": "f02"},
        token,
    )

    assert refused.status == 409
    assert refused.error_code == "job_in_progress"
    assert job_id in refused.json["error"]["message"]

    settle(job_server, exports, job_id)


def test_getting_a_job_start_route_is_a_404_not_a_crash(job_client, job_server):
    """``GET /api/jobs/export`` falls through to the ``{job_id}`` route.

    Which is the honest answer: there is no job called "export". Pinned so the
    route ordering that produces it is not changed by accident.
    """
    response = job_client.get("/api/jobs/export", token=job_server.token)

    assert response.status == 404
    assert response.error_code == "unknown_job"


def test_a_get_on_the_cancel_route_is_405(job_client, job_server):
    response = job_client.get("/api/jobs/whatever/cancel", token=job_server.token)

    assert response.status == 405
    assert response.headers.get("Allow") == API_ALLOWED_METHODS


def test_every_job_document_survives_strict_json(job_client, job_server, exports):
    """``server._send_json`` uses ``allow_nan=False``; a NaN would be a 500."""
    token = job_server.token
    started = post_json(
        job_client, "/api/jobs/export", {"out_dir": "/tmp/x", "track_ids": "f01"}, token
    )
    job_id = started.json["job"]["id"]
    assert exports.entered.wait(timeout=WAIT)
    settle(job_server, exports, job_id)

    for path in ("/api/jobs", f"/api/jobs/{job_id}"):
        response = job_client.get(path, token=token)
        assert response.status == 200
        json.dumps(response.json, allow_nan=False)

    assert (
        job_client.get(f"/api/jobs/{job_id}", token=token).json["job"]["state"]
        == SUCCEEDED
    )
