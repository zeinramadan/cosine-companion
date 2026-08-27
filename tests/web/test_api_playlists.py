"""``track.playlists`` and ``track.playlist_source`` on the detail endpoint.

Filling the field the drawer already fetches rather than adding a route: see
``CocoApi._detail``. That decision is what these tests pin, along with the
three-way ``null`` / ``[]`` / list contract the drawer branches on.

Every library here is synthetic and under ``tmp_path``. The real ``data/``
directory is never read - which is also why the playlist tables are written
into the same ``tmp_path`` the library lives in, through the real importer.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services"))

from playlist_fixtures import (  # noqa: E402
    write_fixture_xml,
    write_schema_2_layout,
)

from services.playlist_import import import_playlists  # noqa: E402
from services.playlist_service import IMPORT_COMMAND, PlaylistService  # noqa: E402
from web.api import CocoApi  # noqa: E402

FIXED_CLOCK = datetime(2026, 8, 19, 14, 30, 0, tzinfo=timezone.utc)

#: Three of the twelve committed fixture tracks, re-used as playlist members so
#: the ids in the export match ids the library really has.
MEMBER_ONE = "f01"
MEMBER_TWO = "f02"
NON_MEMBER = "f03"

#: A hand-written export whose members are real fixture-library track ids and
#: whose folder names include one containing a slash.
PLAYLIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="0"></COLLECTION>
  <PLAYLISTS>
    <NODE Type="0" Name="ROOT" Count="1">
      <NODE Type="1" Name="top level" Entries="1" KeyType="0">
        <TRACK Key="f01"/>
      </NODE>
      <NODE Type="0" Name="Mischief" Count="1">
        <NODE Type="0" Name="Collections/Hauls" Count="1">
          <NODE Type="1" Name="hard 1hr" Entries="2" KeyType="0">
            <TRACK Key="f01"/>
            <TRACK Key="f02"/>
          </NODE>
        </NODE>
      </NODE>
    </NODE>
  </PLAYLISTS>
</DJ_PLAYLISTS>
"""


def call(api, path, query=None):
    return api.handle("GET", path, query or {})


@pytest.fixture
def export(web_data_dir):
    """The export written INSIDE the library's own tmp directory."""
    return write_fixture_xml(web_data_dir / "export.xml", PLAYLIST_XML)


@pytest.fixture
def api_without_playlists(web_library, settings):
    """No import has happened. The default service finds no tables."""
    return CocoApi(web_library, settings)


@pytest.fixture
def api_with_playlists(web_library, settings, web_data_dir, export):
    import_playlists(export, data_dir=web_data_dir, now=FIXED_CLOCK)
    return CocoApi(web_library, settings, playlists=PlaylistService(web_data_dir))


# ---------------------------------------------------------------------------
# null vs [] vs a list
# ---------------------------------------------------------------------------


def test_no_import_yet_leaves_playlists_null(api_without_playlists):
    """The state PR 3a shipped, and it must keep meaning "not imported"."""
    _, body = call(api_without_playlists, f"/api/tracks/{MEMBER_ONE}")

    assert body["track"]["playlists"] is None
    assert body["track"]["playlist_source"] is None


def test_an_imported_track_gets_its_playlists(api_with_playlists):
    _, body = call(api_with_playlists, f"/api/tracks/{MEMBER_ONE}")

    assert body["track"]["playlists"] == [
        {
            "playlist_id": body["track"]["playlists"][0]["playlist_id"],
            "name": "top level",
            "folder_path": [],
            "entries": 1,
        },
        {
            "playlist_id": body["track"]["playlists"][1]["playlist_id"],
            "name": "hard 1hr",
            "folder_path": ["Mischief", "Collections/Hauls"],
            "entries": 2,
        },
    ]


def test_a_schema_2_install_shows_the_import_call_to_action_not_an_error(
    web_library, settings, web_data_dir, export
):
    """MIGRATION, as the user experiences it on the first run after upgrading.

    An install from before the generation-scoped layout has two flat tables and
    a manifest that does not name them, which this build reads as "nothing
    imported" - it cannot check bytes against a record that never said which
    bytes it meant. The question that matters is what that looks like in the
    drawer, and the answer has to be the import call-to-action rather than an
    error: ``playlists: null`` is the field ``renderPlaylists`` branches on to
    show "No Rekordbox playlists have been imported yet" and the command block.

    So: a 200, with the same two nulls the never-imported state produces. One
    re-import - the command that screen is already showing - restores them.

    ONE API, ACROSS THE IMPORT
    --------------------------
    The repaired request is made against the SAME ``CocoApi`` as the broken
    one, because that is the only version of this that means anything:
    ``web/host.py:123`` builds one and the window holds it until it closes. An
    earlier version of this test built a second API afterwards, which is a
    restarted app - and a restarted app was exactly what the user was being
    made to do.
    """
    write_schema_2_layout(web_data_dir, export)
    api = CocoApi(web_library, settings, playlists=PlaylistService(web_data_dir))

    status, body = call(api, f"/api/tracks/{MEMBER_ONE}")

    assert status == 200
    assert body["track"]["playlists"] is None
    assert body["track"]["playlist_source"] is None

    import_playlists(export, data_dir=web_data_dir, now=FIXED_CLOCK)

    _, repaired = call(api, f"/api/tracks/{MEMBER_ONE}")
    assert [entry["name"] for entry in repaired["track"]["playlists"]] == [
        "top level",
        "hard 1hr",
    ]
    assert repaired["track"]["playlist_source"]["source_name"] == export.name


def test_the_drawer_follows_a_RE_import_without_the_app_being_restarted(
    web_library, settings, web_data_dir, export
):
    """The staleness prompt's whole point, at the endpoint the drawer calls.

    ``playlist_source.stale`` goes true when the export changes, and the block
    it drives names ``import-playlists``. Running that command has to change
    what the NEXT request returns from the API already running - otherwise the
    drawer is telling the user to do something it cannot observe, and the
    prompt stays up over data that is no longer stale.
    """
    import_playlists(export, data_dir=web_data_dir, now=FIXED_CLOCK)
    api = CocoApi(web_library, settings, playlists=PlaylistService(web_data_dir))

    _, before = call(api, f"/api/tracks/{MEMBER_ONE}")
    assert before["track"]["playlist_source"]["stale"] is False
    assert [entry["name"] for entry in before["track"]["playlists"]] == [
        "top level",
        "hard 1hr",
    ]

    export.write_text(
        PLAYLIST_XML.replace('Name="top level"', 'Name="renamed top"'),
        encoding="utf-8",
    )

    _, stale = call(api, f"/api/tracks/{MEMBER_ONE}")
    assert stale["track"]["playlist_source"]["stale"] is True
    assert IMPORT_COMMAND in stale["track"]["playlist_source"]["reason"]

    import_playlists(export, data_dir=web_data_dir, now=FIXED_CLOCK)

    _, after = call(api, f"/api/tracks/{MEMBER_ONE}")
    assert after["track"]["playlist_source"]["stale"] is False
    assert [entry["name"] for entry in after["track"]["playlists"]] == [
        "renamed top",
        "hard 1hr",
    ]


def test_a_track_in_no_playlist_gets_an_empty_list_not_null(api_with_playlists):
    """The distinction the drawer renders as two different screens. Reachable
    with real data too - 8 of the 1,532 indexed tracks are in nothing - but
    covered here by fixture, which is the only way to cover it on CI."""
    _, body = call(api_with_playlists, f"/api/tracks/{NON_MEMBER}")

    assert body["track"]["playlists"] == []
    assert body["track"]["playlists"] is not None


def test_folder_path_reaches_the_client_as_a_list_of_segments(api_with_playlists):
    """``Collections/Hauls`` is ONE segment. Joined server-side the drawer
    could not tell it from two folders."""
    _, body = call(api_with_playlists, f"/api/tracks/{MEMBER_TWO}")

    assert body["track"]["playlists"][0]["folder_path"] == [
        "Mischief",
        "Collections/Hauls",
    ]


def test_the_payload_is_json_serialisable_with_nan_rejected(api_with_playlists):
    """The server dumps with ``allow_nan=False``; a numpy type or a NaN that
    escaped the sanitiser is a 500 rather than invalid JSON on the wire."""
    _, body = call(api_with_playlists, f"/api/tracks/{MEMBER_ONE}")

    round_tripped = json.loads(json.dumps(body, allow_nan=False))
    assert round_tripped["track"]["playlists"][1]["entries"] == 2


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_the_provenance_names_the_file_and_the_import_time(api_with_playlists):
    _, body = call(api_with_playlists, f"/api/tracks/{MEMBER_ONE}")
    source = body["track"]["playlist_source"]

    assert source["source_name"] == "export.xml"
    assert source["imported_at"] == "2026-08-19T14:30:00+00:00"
    assert source["playlist_count"] == 2
    assert source["entry_count"] == 3
    assert source["stale"] is False
    assert source["source_missing"] is False
    assert source["import_command"] == IMPORT_COMMAND


def test_the_absolute_xml_path_never_leaves_the_server(api_with_playlists, export):
    """A basename plus a date is the whole of spec §6.4's example. The full
    path would put a home directory into every screenshot of the drawer."""
    _, body = call(api_with_playlists, f"/api/tracks/{MEMBER_ONE}")

    payload = json.dumps(body)
    assert str(export) not in payload
    assert str(export.parent) not in payload
    assert "export.xml" in payload


def test_a_changed_export_reaches_the_client_as_stale(
    web_library, settings, web_data_dir, export
):
    import_playlists(export, data_dir=web_data_dir, now=FIXED_CLOCK)
    export.write_text(
        export.read_text(encoding="utf-8").replace("hard 1hr", "renamed"),
        encoding="utf-8",
    )
    api = CocoApi(web_library, settings, playlists=PlaylistService(web_data_dir))

    _, body = call(api, f"/api/tracks/{MEMBER_ONE}")
    source = body["track"]["playlist_source"]

    assert source["stale"] is True
    assert source["source_missing"] is False
    assert IMPORT_COMMAND in source["reason"]
    # The playlists themselves still come back: the prompt is a prompt.
    assert len(body["track"]["playlists"]) == 2


def test_a_deleted_export_reaches_the_client_without_a_crash(
    web_library, settings, web_data_dir, export
):
    """Spec §6.5: provenance plus a note, never a traceback."""
    import_playlists(export, data_dir=web_data_dir, now=FIXED_CLOCK)
    export.unlink()
    api = CocoApi(web_library, settings, playlists=PlaylistService(web_data_dir))

    status, body = call(api, f"/api/tracks/{MEMBER_ONE}")
    source = body["track"]["playlist_source"]

    assert status == 200
    assert source["source_missing"] is True
    assert source["stale"] is False
    assert "export.xml" in source["reason"]
    assert len(body["track"]["playlists"]) == 2


# ---------------------------------------------------------------------------
# What must keep working
# ---------------------------------------------------------------------------


def test_health_does_not_depend_on_playlist_data(api_without_playlists):
    """Liveness must not need a library, let alone a playlist import."""
    status, body = call(api_without_playlists, "/api/health")

    assert status == 200
    assert body["ok"] is True


def test_the_playlist_FEATURE_added_no_route_of_its_own(api_without_playlists):
    """The field is filled on the detail response the drawer already fetches.

    THIS ASSERTS ONE FEATURE'S CLAIM, NOT THE WHOLE ROUTE TABLE
    -----------------------------------------------------------
    It has twice been written as an exact-list pin of every route the API has,
    and it has twice failed for a reason that had nothing to do with playlists:
    once counting "the same six", once listing all eight after ``/api/settings``
    arrived with the web write surface (#16). Both times the failure was a
    merge, not a defect, and the next one is already scheduled - Library,
    Set-Creator, Export and reindex routes are PR 3b's.

    A pin on the global table cannot say "this feature added nothing"; it says
    "nobody added anything", which is a different and much broader claim that
    this test is the wrong place to make. So what is asserted is the claim
    itself: no route mentions playlists, and the route the drawer actually
    fetches - the one the field rides on - is still there.
    """
    routes = [(verb, pattern.pattern) for verb, pattern, _ in CocoApi.ROUTES]

    assert [route for route in routes if "playlist" in route[1]] == []
    assert ("GET", r"^/api/tracks/(?P<track_id>[^/]+)$") in routes, (
        "the playlist field rides on the track-detail route; if that has moved, "
        "the feature has a delivery problem this test should not pass over"
    )


def test_there_is_no_playlists_endpoint(api_with_playlists):
    status, body = call(api_with_playlists, "/api/playlists")

    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_an_unknown_track_is_still_a_404_when_playlists_are_imported(
    api_with_playlists,
):
    status, body = call(api_with_playlists, "/api/tracks/nope")

    assert status == 404
    assert body["error"]["code"] == "unknown_track"


def test_the_recommendation_seed_carries_playlists_too(api_with_playlists):
    """``_detail`` builds the seed, so the field arrives there as well. Not a
    separate code path; asserted so it cannot become one."""
    _, body = call(api_with_playlists, f"/api/tracks/{MEMBER_ONE}/recommendations")

    assert len(body["seed"]["playlists"]) == 2
    assert body["seed"]["playlist_source"]["source_name"] == "export.xml"


def test_the_default_service_looks_beside_the_library_not_in_the_configured_dir(
    web_library, settings, web_data_dir, export
):
    """A library opened with ``--data-dir`` must not read another directory's
    playlists. Constructing ``CocoApi`` with no service must find the tables
    that were written beside THIS library."""
    import_playlists(export, data_dir=web_data_dir, now=FIXED_CLOCK)

    api = CocoApi(web_library, settings)

    assert api.playlists.data_dir == Path(web_data_dir)
    _, body = call(api, f"/api/tracks/{MEMBER_ONE}")
    assert len(body["track"]["playlists"]) == 2
