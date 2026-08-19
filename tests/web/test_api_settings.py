"""The one mutating destination: read and write the Rekordbox XML path.

Every store in this file lives under ``tmp_path``. The web API is deliberately
not a generic editor for settings.json: ``first_run_complete`` controls
onboarding, so the Settings destination may neither read nor write it.
"""

import json

import pytest

from services.settings_store import SettingsStore
from web.api import CocoApi
from web.server import CocoServer
from webtest_support import client_for


class EmptyLibrary:
    """Settings routes do not need a loaded library or any data files."""

    is_empty = True
    track_count = 0
    data_dir = "/nonexistent"
    meta_ix = None


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
def settings_api(settings_path):
    return CocoApi(EmptyLibrary(), SettingsStore(settings_path))


def test_get_settings_reports_an_unset_path_without_creating_a_file(
    settings_api, settings_path
):
    status, body = settings_api.handle("GET", "/api/settings", {})

    assert status == 200
    assert body == {"settings": {"xml_path": None}}
    assert not settings_path.exists()


def test_get_settings_exposes_only_the_user_editable_field(settings_path):
    settings_path.write_text(
        json.dumps(
            {
                "xml_path": "/old/collection.xml",
                "first_run_complete": True,
            }
        ),
        encoding="utf-8",
    )
    api = CocoApi(EmptyLibrary(), SettingsStore(settings_path))

    status, body = api.handle("GET", "/api/settings", {})

    assert status == 200
    assert body == {"settings": {"xml_path": "/old/collection.xml"}}
    assert "first_run_complete" not in json.dumps(body)


def test_post_settings_persists_immediately_and_preserves_onboarding(settings_path):
    settings_path.write_text(
        json.dumps(
            {
                "xml_path": "/old/collection.xml",
                "first_run_complete": True,
            }
        ),
        encoding="utf-8",
    )
    api = CocoApi(EmptyLibrary(), SettingsStore(settings_path))

    status, body = api.handle(
        "POST",
        "/api/settings",
        {},
        {"xml_path": "/new/collection.xml"},
    )

    assert status == 200
    assert body == {"settings": {"xml_path": "/new/collection.xml"}}
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "xml_path": "/new/collection.xml",
        "first_run_complete": True,
    }


def test_the_running_server_and_real_api_persist_the_same_post(
    settings_path, static_dir
):
    api = CocoApi(EmptyLibrary(), SettingsStore(settings_path))
    running = CocoServer(api, static_dir)
    running.start()
    try:
        response = client_for(running).post(
            "/api/settings",
            b'{"xml_path":"/wire/collection.xml"}',
            token=running.token,
        )
    finally:
        running.stop()

    assert response.status == 200
    assert response.json == {"settings": {"xml_path": "/wire/collection.xml"}}
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "xml_path": "/wire/collection.xml"
    }


def test_post_settings_does_not_require_the_chosen_file_to_exist(
    settings_api, settings_path
):
    """Matches SettingsWindow.change_xml_path rather than inventing validation."""
    chosen = "/a/path/that/does/not/exist/collection.xml"

    status, body = settings_api.handle(
        "POST", "/api/settings", {}, {"xml_path": chosen}
    )

    assert status == 200
    assert body["settings"]["xml_path"] == chosen
    assert json.loads(settings_path.read_text(encoding="utf-8"))["xml_path"] == chosen


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "not an object",
        {},
        {"first_run_complete": True},
        {"xml_path": "/ok.xml", "first_run_complete": False},
        {"xml_path": "/ok.xml", "unexpected": True},
    ],
)
def test_post_settings_accepts_exactly_the_xml_path_field(
    settings_api, settings_path, body
):
    status, response = settings_api.handle("POST", "/api/settings", {}, body)

    assert status == 400
    assert response["error"]["code"] == "bad_request"
    assert not settings_path.exists()


@pytest.mark.parametrize("xml_path", [None, True, 7, "", "   ", "\t"])
def test_xml_path_must_be_a_non_blank_string(settings_api, settings_path, xml_path):
    status, body = settings_api.handle(
        "POST", "/api/settings", {}, {"xml_path": xml_path}
    )

    assert status == 400
    assert body["error"]["code"] == "bad_request"
    assert not settings_path.exists()


def test_a_method_other_than_get_or_post_is_refused(settings_api):
    status, body = settings_api.handle("PATCH", "/api/settings", {})

    assert status == 405
    assert body["error"]["code"] == "method_not_allowed"
