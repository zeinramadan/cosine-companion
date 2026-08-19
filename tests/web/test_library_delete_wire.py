"""Security and framing of the real Library mutation over loopback HTTP."""

import json

import pytest

from web.api import CocoApi
from web.server import MAX_REQUEST_BODY_BYTES, CocoServer
from webtest_support import client_for


@pytest.fixture
def running_library_api(web_library, settings, static_dir):
    running = CocoServer(CocoApi(web_library, settings), static_dir)
    running.start()
    try:
        yield running
    finally:
        running.stop()


def test_an_unauthenticated_delete_is_rejected_before_its_body_is_used(
    running_library_api, web_library
):
    response = client_for(running_library_api).post(
        "/api/library/tracks/delete",
        b'{"track_ids":"f02"}',
    )

    assert response.status == 401
    assert response.error_code == "unauthorized"
    assert response.content_type == "application/json; charset=utf-8"
    assert web_library.get_track("f02") is not None


def test_a_delete_with_the_wrong_content_type_is_a_framed_415(
    running_library_api, web_library
):
    response = client_for(running_library_api).post(
        "/api/library/tracks/delete",
        b'{"track_ids":"f02"}',
        token=running_library_api.token,
        content_type="text/plain",
    )

    assert response.status == 415
    assert response.error_code == "unsupported_media_type"
    assert response.content_type == "application/json; charset=utf-8"
    assert web_library.get_track("f02") is not None


def test_an_oversized_delete_body_is_a_framed_413_without_a_mutation(
    running_library_api, web_library
):
    body = b'{' + b'"track_ids":"' + b'x' * MAX_REQUEST_BODY_BYTES + b'"}'
    assert len(body) > MAX_REQUEST_BODY_BYTES

    response = client_for(running_library_api).post(
        "/api/library/tracks/delete",
        body,
        token=running_library_api.token,
    )

    assert response.status == 413
    assert response.error_code == "payload_too_large"
    assert response.content_type == "application/json; charset=utf-8"
    assert web_library.track_count == 14


def test_a_valid_authenticated_delete_mutates_once_over_the_wire(
    running_library_api, web_library
):
    response = client_for(running_library_api).post(
        "/api/library/tracks/delete",
        json.dumps({"track_ids": "f02\nf05"}).encode("utf-8"),
        token=running_library_api.token,
    )

    assert response.status == 200
    assert response.json["deleted"] == 2
    assert response.json["library"] == {"track_count": 12, "is_empty": False}
    assert web_library.get_track("f02") is None
    assert web_library.get_track("f05") is None
