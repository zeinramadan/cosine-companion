"""The library, browse, search and track-detail endpoints.

Tested through ``CocoApi.handle`` directly rather than over HTTP: the server's
own suite already pins transport, auth and serialisation, and going through a
socket here would only make these slower without testing anything the API
decides. What each case asserts is the *contract* - the status code and the
body shape - because the frontend is written against exactly that.

Every library in this file is synthetic and lives under ``tmp_path``. The
maintainer's real ``data/`` directory is never read.
"""

import json

import pytest

from webtest_support import (
    NAN_BPM_TRACK_ID,
    NON_ASCII_TRACK_ID,
    WEB_LIBRARY_TRACK_COUNT,
)

from web.api import (
    DEFAULT_BROWSE_LIMIT,
    DEFAULT_SEARCH_LIMIT,
    MAX_BROWSE_LIMIT,
    MAX_SEARCH_LIMIT,
    CocoApi,
    _int_param,
)


@pytest.fixture
def api(web_library, settings):
    return CocoApi(web_library, settings)


@pytest.fixture
def empty_api(empty_library, settings):
    return CocoApi(empty_library, settings)


class OversizedLibrary:
    """A library with more rows than any cap in the API, built in memory.

    It exists because a cap cannot be pinned by a fixture smaller than the cap.
    Nothing is written to disk and nothing under ``data/`` is read: ``_browse``
    only reads ``meta_ix`` and ``track_count``, and ``_search`` only calls
    ``search_tracks``, so those four members are the whole surface the two
    endpoints under test touch.

    ``search_tracks`` records the limit it was handed, which is the resolved
    value the API decided - the thing the clamp actually controls.
    """

    def __init__(self, rows):
        import pandas as pd

        self.meta_ix = pd.DataFrame(
            {
                "artist": [f"Artist {index:04d}" for index in range(rows)],
                "title": [f"Title {index:04d}" for index in range(rows)],
            },
            index=pd.Index([f"t{index:04d}" for index in range(rows)], name="track_id"),
        )
        self.track_count = rows
        self.is_empty = False
        self.data_dir = "/nonexistent"
        self.search_calls = []

    def search_tracks(self, query, limit):
        self.search_calls.append({"query": query, "limit": limit})
        return [
            {
                "track_id": f"t{index:04d}",
                "artist": f"Artist {index:04d}",
                "title": f"Title {index:04d}",
                "display_name": f"Artist {index:04d} – Title {index:04d}",
            }
            for index in range(limit)
        ]


#: Comfortably past MAX_BROWSE_LIMIT (500), the largest cap in the API.
OVERSIZED_ROWS = 600


@pytest.fixture
def big_api(settings):
    library = OversizedLibrary(OVERSIZED_ROWS)
    return CocoApi(library, settings), library


def call(api, path, **params):
    """Invoke a route the way the server does, with list-valued query params."""
    query = {name: [str(value)] for name, value in params.items()}
    return api.handle("GET", path, query)


def assert_serialisable(body):
    """The whole point of the sanitiser: the body must be real JSON.

    ``allow_nan=False`` is what the server uses, so a NaN slipping through
    fails here rather than in WKWebView's JSON.parse.
    """
    round_tripped = json.loads(json.dumps(body, allow_nan=False, ensure_ascii=False))
    assert round_tripped == body
    return round_tripped


# -- /api/health -----------------------------------------------------------


def test_health_reports_the_app_and_the_api_version(api):
    status, body = call(api, "/api/health")

    assert status == 200
    assert body == {"ok": True, "app": "cosine-companion", "api_version": 1}
    assert_serialisable(body)


def test_health_does_not_need_a_loaded_library(empty_api):
    """It is the endpoint the frontend uses to decide the backend is alive; it
    must not depend on the thing that might be broken."""
    status, body = call(empty_api, "/api/health")

    assert status == 200
    assert body["ok"] is True


# -- /api/library ----------------------------------------------------------


def test_library_reports_the_real_track_count(api, web_data_dir, settings):
    status, body = call(api, "/api/library")

    assert status == 200
    assert body["track_count"] == WEB_LIBRARY_TRACK_COUNT
    assert body["is_empty"] is False
    assert body["data_dir"] == str(web_data_dir)
    assert body["xml_path"] == settings.xml_path
    assert_serialisable(body)


def test_library_reports_an_unloaded_library_as_empty(empty_api):
    status, body = call(empty_api, "/api/library")

    assert status == 200
    assert body["track_count"] == 0
    assert body["is_empty"] is True


def test_library_reports_a_null_xml_path_when_none_is_configured(web_library, tmp_path):
    from services.settings_store import SettingsStore

    api = CocoApi(web_library, SettingsStore(tmp_path / "absent.json"))

    status, body = call(api, "/api/library")

    assert status == 200
    assert body["xml_path"] is None
    assert_serialisable(body)


# -- /api/tracks -----------------------------------------------------------


def test_tracks_returns_the_first_page_and_the_full_total(api):
    status, body = call(api, "/api/tracks", limit=3)

    assert status == 200
    assert len(body["tracks"]) == 3
    assert body["total"] == WEB_LIBRARY_TRACK_COUNT
    assert_serialisable(body)


def test_tracks_defaults_to_fifty(api):
    """The palette's empty state shows this page, so the default is a contract
    with the frontend, not an implementation detail."""
    _, body = call(api, "/api/tracks")

    assert len(body["tracks"]) == min(50, WEB_LIBRARY_TRACK_COUNT)


def test_tracks_clamps_an_absurd_limit_rather_than_serialising_the_library(big_api):
    """The cap has to BITE, which the fourteen-track fixture cannot make it do.

    This asserted ``len(tracks) == min(500, WEB_LIBRARY_TRACK_COUNT)``, i.e.
    ``== 14``. Raising MAX_BROWSE_LIMIT to 9999 left that green, because with
    fourteen rows in the library ``min(9999, 14)`` and ``min(500, 14)`` are the
    same number - the assertion was about the fixture, not about the cap. A
    library larger than the cap is what makes it an assertion about the cap.
    """
    api, library = big_api

    _, body = call(api, "/api/tracks", limit=9999)

    # The literal as well as the constant. Comparing the result only against
    # the constant is circular: raising the constant raises both sides of the
    # comparison. These numbers are contract values the frontend is written
    # against, so pinning them is the point rather than a duplication.
    assert MAX_BROWSE_LIMIT == 500
    assert library.track_count > MAX_BROWSE_LIMIT, "the fixture cannot bind the cap"
    assert len(body["tracks"]) == 500
    assert body["total"] == library.track_count


def test_the_browse_cap_is_the_documented_number(big_api):
    """One row below and one row above, so an off-by-one in the clamp shows."""
    api, _ = big_api

    _, under = call(api, "/api/tracks", limit=MAX_BROWSE_LIMIT - 1)
    _, at = call(api, "/api/tracks", limit=MAX_BROWSE_LIMIT)
    _, over = call(api, "/api/tracks", limit=MAX_BROWSE_LIMIT + 1)

    assert len(under["tracks"]) == MAX_BROWSE_LIMIT - 1
    assert len(at["tracks"]) == MAX_BROWSE_LIMIT
    assert len(over["tracks"]) == MAX_BROWSE_LIMIT


def test_tracks_come_back_in_meta_ix_order(api, web_library):
    _, body = call(api, "/api/tracks", limit=5)

    assert [track["track_id"] for track in body["tracks"]] == list(
        web_library.meta_ix.index[:5]
    )


def test_a_track_summary_has_exactly_the_four_advertised_fields(api):
    _, body = call(api, "/api/tracks", limit=1)

    assert set(body["tracks"][0]) == {"track_id", "artist", "title", "display_name"}


def test_the_display_name_uses_an_en_dash_like_every_other_surface(api):
    """U+2013, not a hyphen. §3.1 of the inventory: everything user-facing in a
    list uses the en dash, and search_tracks already builds it that way."""
    _, body = call(api, "/api/tracks", limit=1)
    summary = body["tracks"][0]

    assert summary["display_name"] == f"{summary['artist']} – {summary['title']}"
    assert " – " in summary["display_name"]


def test_tracks_on_an_unloaded_library_is_an_empty_page_not_a_crash(empty_api):
    status, body = call(empty_api, "/api/tracks")

    assert status == 200
    assert body == {"tracks": [], "total": 0}


@pytest.mark.parametrize("limit", ["abc", "1.5", "", "3x"])
def test_a_non_integer_limit_is_a_bad_request(api, limit):
    status, body = call(api, "/api/tracks", limit=limit)

    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_a_negative_limit_is_a_bad_request(api):
    status, body = call(api, "/api/tracks", limit=-1)

    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_a_zero_limit_is_an_empty_page_not_an_error(api):
    status, body = call(api, "/api/tracks", limit=0)

    assert status == 200
    assert body["tracks"] == []
    assert body["total"] == WEB_LIBRARY_TRACK_COUNT


# -- /api/tracks/search ----------------------------------------------------


def test_search_finds_a_track_by_artist(api):
    status, body = call(api, "/api/tracks/search", q="blawan")

    assert status == 200
    assert body["query"] == "blawan"
    assert [result["track_id"] for result in body["results"]] == ["f02"]
    assert body["results"][0]["display_name"] == "Blawan – Why They Hide"
    assert_serialisable(body)


def test_search_finds_a_track_by_title(api):
    _, body = call(api, "/api/tracks/search", q="the bells")

    assert [result["track_id"] for result in body["results"]] == ["f10"]


def test_search_round_trips_a_non_ascii_artist(api):
    _, body = call(api, "/api/tracks/search", q="björk")

    assert [result["track_id"] for result in body["results"]] == [NON_ASCII_TRACK_ID]
    assert body["results"][0]["artist"] == "Björk"
    assert body["results"][0]["display_name"] == "Björk – Jóga"
    assert_serialisable(body)


def test_search_with_no_query_is_a_bad_request(api):
    """The palette shows /api/tracks for an empty box instead. Returning [] here
    would make "no query" and "no matches" indistinguishable to the frontend."""
    status, body = call(api, "/api/tracks/search")

    assert status == 400
    assert body["error"]["code"] == "bad_request"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_search_with_a_blank_query_is_a_bad_request(api, blank):
    status, body = call(api, "/api/tracks/search", q=blank)

    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_search_honours_its_limit(api):
    _, body = call(api, "/api/tracks/search", q="a", limit=2)

    assert len(body["results"]) == 2


def test_search_clamps_its_limit_to_a_hundred(big_api):
    """The RESOLVED limit is asserted, not the length of what came back.

    ``len(results) <= 100`` was true of the fourteen-track fixture whatever the
    cap was, so raising MAX_SEARCH_LIMIT to 9999 left it green. What the API
    actually decides is the number it hands to ``search_tracks``, so that is
    what is recorded and asserted here.
    """
    api, library = big_api

    _, body = call(api, "/api/tracks/search", q="a", limit=9999)

    # The literal, not the constant: `limit=9999` resolving to MAX_SEARCH_LIMIT
    # is trivially true when MAX_SEARCH_LIMIT is itself 9999.
    assert MAX_SEARCH_LIMIT == 100
    assert library.search_calls == [{"query": "a", "limit": 100}]
    assert len(body["results"]) == 100


def test_search_passes_a_limit_under_the_cap_through_unchanged(big_api):
    api, library = big_api

    call(api, "/api/tracks/search", q="a", limit=7)

    assert library.search_calls == [{"query": "a", "limit": 7}]


def test_the_search_default_is_the_documented_number(big_api):
    api, library = big_api

    call(api, "/api/tracks/search", q="a")

    assert DEFAULT_SEARCH_LIMIT == 20
    assert library.search_calls == [{"query": "a", "limit": 20}]


@pytest.mark.parametrize(
    "default, maximum",
    [
        (DEFAULT_BROWSE_LIMIT, MAX_BROWSE_LIMIT),
        (DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT),
    ],
)
def test_the_clamp_itself_clamps(default, maximum):
    """The parser under the endpoints, on its own, at the boundary."""
    assert _int_param({}, "limit", default, maximum) == default
    assert _int_param({"limit": ["0"]}, "limit", default, maximum) == 0
    assert _int_param({"limit": [str(maximum - 1)]}, "limit", default, maximum) == maximum - 1
    assert _int_param({"limit": [str(maximum)]}, "limit", default, maximum) == maximum
    assert _int_param({"limit": [str(maximum + 1)]}, "limit", default, maximum) == maximum
    assert _int_param({"limit": ["999999"]}, "limit", default, maximum) == maximum


def test_search_with_no_matches_is_an_empty_list_not_a_404(api):
    status, body = call(api, "/api/tracks/search", q="zzzznotatrack")

    assert status == 200
    assert body["results"] == []


def test_search_on_an_unloaded_library_returns_nothing_rather_than_crashing(empty_api):
    """meta_ix is None there, and recommendations.search iterates it directly."""
    status, body = call(empty_api, "/api/tracks/search", q="anything")

    assert status == 200
    assert body == {"results": [], "query": "anything"}


# -- /api/tracks/{track_id} ------------------------------------------------


def test_a_known_track_returns_its_metadata(api):
    status, body = call(api, "/api/tracks/f01")

    assert status == 200
    track = body["track"]
    assert track["track_id"] == "f01"
    assert track["artist"] == "Alva Noto"
    assert track["title"] == "Xerrox"
    assert track["album"] == "Xerrox Vol 1"
    assert track["bpm"] == 128.0
    assert track["key"] == "8A"
    assert_serialisable(body)


def test_a_track_with_no_bpm_reports_null_rather_than_NaN(api):
    """The case the sanitiser exists for. json.dumps would write the literal
    NaN here, and JSON.parse in WKWebView throws on it."""
    status, body = call(api, f"/api/tracks/{NAN_BPM_TRACK_ID}")

    assert status == 200
    assert body["track"]["bpm"] is None
    assert_serialisable(body)


def test_a_non_ascii_track_survives_the_round_trip(api):
    _, body = call(api, f"/api/tracks/{NON_ASCII_TRACK_ID}")

    assert body["track"]["artist"] == "Björk"
    assert body["track"]["title"] == "Jóga"
    assert_serialisable(body)


def test_an_unknown_track_is_a_404(api):
    status, body = call(api, "/api/tracks/nope")

    assert status == 404
    assert body["error"]["code"] == "unknown_track"


def test_an_unknown_track_on_an_unloaded_library_is_also_a_404(empty_api):
    status, body = call(empty_api, "/api/tracks/f01")

    assert status == 404
    assert body["error"]["code"] == "unknown_track"


def test_track_detail_reserves_a_playlists_field_without_inventing_data(api):
    """PR 4 fills this in from the Rekordbox XML. Until then it is explicitly
    null - not absent, so the drawer can tell "not implemented yet" from "this
    track is in no playlists", and not fabricated."""
    _, body = call(api, "/api/tracks/f01")

    assert "playlists" in body["track"]
    assert body["track"]["playlists"] is None


def test_track_detail_carries_the_local_path_for_the_drawer(api):
    _, body = call(api, "/api/tracks/f01")

    assert body["track"]["path_local"].endswith("f01.mp3")


# -- routing ---------------------------------------------------------------


def test_an_unknown_route_is_a_404(api):
    status, body = call(api, "/api/nonsense")

    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_the_search_route_wins_over_the_track_id_route(api):
    """/api/tracks/search must not be read as the track whose id is 'search'."""
    status, body = call(api, "/api/tracks/search", q="blawan")

    assert status == 200
    assert "results" in body


def test_a_non_get_method_is_refused_by_the_api_too(api):
    """The server already blocks it, but the API is a separately reachable
    object and host.py is not the only possible caller."""
    status, body = api.handle("POST", "/api/library", {})

    assert status == 405
    assert body["error"]["code"] == "method_not_allowed"


def test_a_repeated_query_parameter_takes_the_first_value(api):
    status, body = api.handle("GET", "/api/tracks", {"limit": ["2", "7"]})

    assert status == 200
    assert len(body["tracks"]) == 2
