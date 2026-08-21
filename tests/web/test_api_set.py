"""``POST /api/set`` - the Set Creator destination's one endpoint.

**Where the expected values come from.** Not from calling the thing under test.
``tests/services/golden/set_builder_fixture.json`` holds committed, ordered
``SetTrack`` sequences for four anchor configurations over the twelve-track
fixture library, and ``tests/services/test_golden_values_actually_fail.py``
already proves those goldens discriminate. So this file asserts the endpoint's
JSON against literals a human wrote down, which is the only way an assertion
here can fail when the endpoint starts building a different set. An earlier
draft compared the response with ``SetBuilder(...).build(...)`` and would have
passed for any set whatsoever, including an empty one - the exact tautology
``tests/services/test_set_builder.py`` was rewritten to remove.

The library is the TWELVE-track fixture, not ``web_library``. The web fixture
adds two rows (``webtest_support.WEB_EXTRA_TRACKS``), and two extra candidates
change which track wins a slot, so the goldens would not apply to it. The two
extra rows exist for BPM/UTF-8 sanitisation, and a ``SetTrack`` carries neither
a BPM nor a path.

Nothing here reads ``data/``: every library is written under ``tmp_path``.
"""

import json

import pytest

from fixture_library import load_golden, write_fixture_library
from services.library_session import LibrarySession
from services.settings_store import SettingsStore
from web.api import MAX_SET_TRACKS, CocoApi
from web.server import CocoServer
from webtest_support import client_for

GOLDEN = load_golden("set_builder_fixture")

#: The golden cases this endpoint can actually ask for. ``unfillable`` is
#: excluded because it is defined by an ``exclude`` list, and ``POST /api/set``
#: has no exclusion parameter: the Set Creator tab calls
#: ``self.set_builder.build(self.anchor_tracks, total_tracks)`` with two
#: arguments (set_creator_tab.py:113-116), so exposing a third would be surface
#: no catalogued control can reach. The placeholder rows that case exists to
#: produce are reached here the way inventory workflow 41 (:1508) reaches them
#: instead - by asking for a set longer than the library can fill.
GOLDEN_CASES = sorted(name for name in GOLDEN if not GOLDEN[name].get("exclude"))


def test_the_excluded_golden_case_is_excluded_for_the_stated_reason():
    """Guard the guard. If the filter above silently matched everything, or
    nothing, the parametrised tests would quietly change what they cover."""
    skipped = sorted(name for name in GOLDEN if GOLDEN[name].get("exclude"))

    assert skipped == ["unfillable"]
    assert GOLDEN_CASES == ["anchor_first", "single_anchor_mid", "two_anchors"]


@pytest.fixture
def fixture_data_dir(tmp_path):
    """The twelve committed tracks the goldens were captured against."""
    return write_fixture_library(tmp_path / "data", audio_dir=tmp_path / "audio")


@pytest.fixture
def fixture_library(fixture_data_dir):
    return LibrarySession.load(fixture_data_dir)


@pytest.fixture
def api(fixture_library, tmp_path):
    return CocoApi(fixture_library, SettingsStore(tmp_path / "settings.json"))


def generate(api, anchors, total_tracks):
    """POST a set request through ``handle``, as the server would."""
    return api.handle(
        "POST", "/api/set", {}, {"anchors": anchors, "total_tracks": total_tracks}
    )


def run_golden(api, name):
    case = GOLDEN[name]
    return generate(api, case["anchors"], case["total"]), case


# ---------------------------------------------------------------------------
# The generated set, against committed golden sequences
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", GOLDEN_CASES)
def test_the_endpoint_returns_the_golden_sequence(api, name):
    (status, body), case = run_golden(api, name)

    assert status == 200
    got = body["tracks"]
    expected = case["tracks"]

    assert [t["track_id"] for t in got] == [e["track_id"] for e in expected]
    assert [t["position"] for t in got] == [e["position"] for e in expected]
    assert [t["is_anchor"] for t in got] == [e["is_anchor"] for e in expected]
    assert [t["artist"] for t in got] == [e["artist"] for e in expected]
    assert [t["title"] for t in got] == [e["title"] for e in expected]
    for track, expect in zip(got, expected):
        assert track["score"] == pytest.approx(expect["score"], abs=1e-6)


@pytest.mark.parametrize("name", GOLDEN_CASES)
def test_the_two_computed_strings_survive_serialisation(api, name):
    """``display_name`` and ``icon`` are ``@property``, so ``asdict`` drops them.

    Without ``_set_track`` adding them back the response would carry artist and
    title and nothing else, and the frontend would have to reimplement the
    four-branch resolution order in ``recommendations/models.py:18-30``. These
    are the two fields the rendered row of inventory :479 is built from.
    """
    (_status, body), case = run_golden(api, name)

    assert [t["display_name"] for t in body["tracks"]] == [
        e["display_name"] for e in case["tracks"]
    ]
    assert [t["icon"] for t in body["tracks"]] == [e["icon"] for e in case["tracks"]]


def test_the_golden_cases_exercise_both_icons(api):
    """Guard the guard. If every golden row were an anchor, or none were, the
    icon assertion above would hold for a response that always sent one glyph."""
    icons = set()
    for name in GOLDEN_CASES:
        (_status, body), _case = run_golden(api, name)
        icons.update(track["icon"] for track in body["tracks"])

    assert icons == {"\U0001f512", "\U0001f916"}


def test_an_unfillable_slot_arrives_with_the_fields_the_row_is_built_from(api):
    """Inventory :490-495, reached as workflow 41 (:1508) reaches it: a set
    longer than the twelve-track library can fill. The placeholder is
    artist-only with an EMPTY title, which is what makes ``display_name``
    append ``– (Unknown Title)``. Score is 0.0, and inventory :487 shows no
    suffix for a score that is not > 0."""
    status, body = generate(api, {"1": "f01"}, 20)

    assert status == 200
    assert len(body["tracks"]) == 20
    placeholders = [t for t in body["tracks"] if t["track_id"].startswith("empty_")]
    assert len(placeholders) == 8, "twelve tracks, so eight of the twenty are empty"
    for slot in placeholders:
        assert slot["artist"] == "No suitable track found"
        assert slot["title"] == ""
        assert slot["score"] == 0.0
        assert slot["is_anchor"] is False
        assert slot["display_name"] == "No suitable track found – (Unknown Title)"
        assert not slot["display_name"].endswith("– ")


def test_the_response_is_serialisable_with_no_nan_or_numpy_left_in_it(api):
    """``allow_nan=False`` is the check the frontend's ``JSON.parse`` performs
    for us; a numpy float would not survive ``json.dumps`` at all."""
    (_status, body), _case = run_golden(api, "two_anchors")

    text = json.dumps(body, allow_nan=False)

    assert json.loads(text) == body
    for track in body["tracks"]:
        assert type(track["score"]) is float
        assert type(track["position"]) is int
        assert type(track["is_anchor"]) is bool


# ---------------------------------------------------------------------------
# What the service decides, and what this layer decides
# ---------------------------------------------------------------------------


def test_no_anchors_comes_back_as_the_services_own_message(api):
    """Not re-worded here. Inventory :506-508 renders whatever the ValueError
    said into the ``Generation Error`` dialog, so the message has to travel."""
    status, body = generate(api, {}, 5)

    assert status == 400
    assert body["error"]["code"] == "set_generation_failed"
    assert body["error"]["message"] == "At least one anchor track is required"


def test_an_anchor_past_the_end_is_the_generation_error_inventory_names(api):
    """Inventory :506-508 - this is NOT one of the three pre-checks at :501-503;
    it reaches the builder and comes back as a generation failure."""
    status, body = generate(api, {"9": "f01"}, 4)

    assert status == 400
    assert body["error"]["code"] == "set_generation_failed"
    assert body["error"]["message"] == "Anchor track position exceeds total tracks"


def test_a_length_equal_to_the_anchor_count_is_allowed(api):
    """Inventory :505 - the dialog says *greater than* but the check is ``<``,
    so ``total == len(anchors)`` generates. Preserved, not tidied."""
    status, body = generate(api, {"1": "f01", "2": "f06"}, 2)

    assert status == 200
    assert [t["track_id"] for t in body["tracks"]] == ["f01", "f06"]
    assert all(t["is_anchor"] for t in body["tracks"])


def test_the_same_track_anchored_twice_loses_the_second_anchor_and_its_slot(api):
    """CURRENT BEHAVIOUR, and a gap in the inventory rather than a rule from it.

    Inventory :967 says "The same track may be anchored at several positions",
    which is true of the DIALOG - §2.12 has no such check - and says nothing
    about what generation then does. It does this:
    ``generate_set`` places BOTH anchors, then its final de-duplication pass
    (set_generator.py:176-187) keeps only the first occurrence of any repeated
    id. The dropped one takes its whole SLOT with it, because the pass filters
    the assembled list rather than refilling the position. So a 5-track request
    comes back with FOUR tracks whose positions read 1, 2, 3, 5 - a visible gap
    in the rendered rows - plus a warning on stdout that no UI shows.

    Asserted, not fixed: this endpoint is an adapter and the behaviour is the
    service's. Reported in the PR description.
    """
    status, body = generate(api, {"1": "f01", "4": "f01"}, 5)

    assert status == 200
    assert len(body["tracks"]) == 4, "the duplicate anchor is dropped, not replaced"
    assert [t["position"] for t in body["tracks"]] == [1, 2, 3, 5]
    anchors = [t for t in body["tracks"] if t["is_anchor"]]
    assert [t["position"] for t in anchors] == [1]


def test_an_anchor_the_library_does_not_have_is_left_to_the_service(api):
    """CURRENT BEHAVIOUR, pinned rather than improved.

    ``generate_set`` places an anchor only ``if track_id in meta_ix.index``
    (set_generator.py:55), so an unknown id is silently dropped and the slot is
    filled by a generated pick instead. The endpoint does not add a 404 of its
    own: this module is an adapter, and inventing a rule here would mean two
    different answers to "what is an unknown anchor" depending on which caller
    asked.

    This used to add "and it cannot be reached from the web UI, where anchors
    come from search results". That was true when there was only one
    destination. The sibling Library destination adds a reachable DELETE, so an
    anchor chosen from a search result can be gone by the time Generate Set is
    pressed - see the next test, which reaches this same path through a real
    delete rather than an id nothing ever had.
    """
    status, body = generate(api, {"1": "no-such-track"}, 3)

    assert status == 200
    assert len(body["tracks"]) == 3
    assert body["tracks"][0]["track_id"] != "no-such-track"
    assert body["tracks"][0]["is_anchor"] is False


@pytest.fixture
def isolated_deleted_tracks(tmp_path, monkeypatch):
    """Point ``deleted_tracks.json`` at ``tmp_path`` so ``data/`` is untouched.

    Same patch as ``tests/services/conftest.py:83``, kept local: this is the
    only test in this file that mutates a library, and a shared fixture in
    ``tests/web/conftest.py`` would be a hunk in a file the sibling
    destination's PR is also editing.
    """
    import core.deleted_tracks as deleted_tracks_module

    target = tmp_path / "deleted_tracks.json"
    monkeypatch.setattr(deleted_tracks_module, "DELETED_TRACKS_JSON", target)
    return target


def test_an_anchor_deleted_after_it_was_chosen_takes_the_same_path(
    api, fixture_library, isolated_deleted_tracks
):
    """The cross-destination case, reached the way a user reaches it.

    The Set Creator caches an anchor's artist and title when the anchor is
    chosen, so its row outlives a delete on the Library destination - inventory
    §6.6 declares that, and the row is the visible half. This is the invisible
    half: what the ENDPOINT then does with an anchor whose track the library no
    longer has. The answer is the one above, and it is asserted here against a
    track that genuinely existed and genuinely went away, because "an id nothing
    ever had" and "an id that was deleted" are the same path only as long as
    ``delete_tracks`` really does remove the row from ``meta_ix``.
    """
    anchored = "f01"
    assert anchored in fixture_library.meta_ix.index

    removed = fixture_library.delete_tracks([anchored])

    assert removed == 1
    assert anchored not in fixture_library.meta_ix.index
    assert anchored not in fixture_library.ids

    status, body = generate(api, {"1": anchored}, 3)

    # No error, no 404, and the slot is filled by an ordinary generated pick.
    assert status == 200
    assert len(body["tracks"]) == 3
    assert body["tracks"][0]["track_id"] != anchored
    assert body["tracks"][0]["is_anchor"] is False
    assert anchored not in [track["track_id"] for track in body["tracks"]], (
        "the deleted track came back in the generated set"
    )
    assert [track["is_anchor"] for track in body["tracks"]] == [False, False, False], (
        "the set claims an anchor the request's only anchor could not supply"
    )


def test_a_dropped_anchor_and_a_duplicate_anchor_are_different_response_shapes(
    api, fixture_library, isolated_deleted_tracks
):
    """THE PREMISE THE FRONTEND'S STALE-ROW RULE STANDS ON.

    Round 2 declined to touch a stale anchor row, on the stated grounds that a
    deleted anchor and :967's duplicate anchor "produce the identical shape - a
    requested position with no anchor on it, for a track the library still has -
    so a frontend rule keyed on that shape would remove the wrong row". That is
    false, and this is the probe that says so, run against the same service the
    endpoint calls rather than against a description of it.

    The two differ in two independent ways:

    * the DUPLICATE loses the position entirely, because the de-duplication pass
      filters the assembled list (``set_generator.py:176-187``), so the response
      is SHORT and the requested position is ABSENT;
    * the DELETED anchor is dropped before placement (``set_generator.py:55``)
      and an ordinary pick fills the slot, so the response is FULL LENGTH and
      the requested position is PRESENT with ``is_anchor`` false.

    And the duplicated id is still anchored at its surviving position, where a
    deleted id is anchored nowhere - which is the signal ``set-creator.js``
    actually keys on, because it is the one that cannot be confused by a set
    that is short for some other reason.

    This test exists so that a service change which collapsed the two shapes
    would fail HERE, next to the behaviour, rather than silently making the
    frontend mark the wrong row.
    """
    duplicate_status, duplicate = generate(api, {"1": "f01", "4": "f01"}, 5)

    assert duplicate_status == 200
    assert [t["position"] for t in duplicate["tracks"]] == [1, 2, 3, 5]
    assert 4 not in [t["position"] for t in duplicate["tracks"]], (
        "the duplicate's lost position is present, so it is no longer "
        "distinguishable from a deleted anchor by position"
    )
    assert "f01" in [t["track_id"] for t in duplicate["tracks"] if t["is_anchor"]], (
        "the surviving occurrence is not anchored, so the second signal is gone"
    )

    # The same request shape, with one anchor whose track genuinely went away.
    assert fixture_library.delete_tracks(["f06"]) == 1
    deleted_status, deleted = generate(api, {"1": "f06", "4": "f01"}, 5)

    assert deleted_status == 200
    assert [t["position"] for t in deleted["tracks"]] == [1, 2, 3, 4, 5], (
        "the deleted anchor's slot was not refilled, so the response now looks "
        "like the duplicate case"
    )
    dropped_slot = next(t for t in deleted["tracks"] if t["position"] == 1)
    assert dropped_slot["track_id"] != "f06"
    assert dropped_slot["is_anchor"] is False
    assert "f06" not in [t["track_id"] for t in deleted["tracks"] if t["is_anchor"]]

    # The live anchor in the same request is untouched, which is what stops the
    # frontend marking every row whenever any one of them is dropped.
    surviving = next(t for t in deleted["tracks"] if t["position"] == 4)
    assert surviving["track_id"] == "f01"
    assert surviving["is_anchor"] is True


def test_an_empty_library_is_a_409_before_anything_else_is_looked_at(tmp_path):
    """Same ordering and same code as ``_recommendations``: a library with no
    index cannot answer, and saying so beats blaming the anchors. The body here
    is also malformed, so a 400 would prove the 409 came second."""
    api = CocoApi(
        LibrarySession(tmp_path / "empty-data"),
        SettingsStore(tmp_path / "settings.json"),
    )

    status, body = api.handle("POST", "/api/set", {}, {"nonsense": True})

    assert status == 409
    assert body["error"]["code"] == "empty_library"


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "anchors",
        {},
        {"anchors": {"1": "f01"}},
        {"total_tracks": 4},
        {"anchors": {"1": "f01"}, "total_tracks": 4, "extra": 1},
    ],
    ids=[
        "null",
        "list",
        "string",
        "empty-object",
        "no-total",
        "no-anchors-field",
        "unknown-field",
    ],
)
def test_a_body_of_the_wrong_shape_is_a_400(api, body):
    status, payload = api.handle("POST", "/api/set", {}, body)

    assert status == 400
    assert payload["error"]["code"] == "bad_request"


@pytest.mark.parametrize(
    "anchors",
    [
        {"0": "f01"},
        {"-1": "f01"},
        {"one": "f01"},
        {"1.5": "f01"},
        {"1": ""},
        {"1": 17},
        {"1": None},
    ],
    ids=["zero", "negative", "word", "fractional", "blank-id", "int-id", "null-id"],
)
def test_an_anchor_that_is_not_a_position_and_an_id_is_a_400(api, anchors):
    status, body = generate(api, anchors, 5)

    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_position_zero_would_otherwise_land_on_the_last_slot(api):
    """WHY position < 1 is refused rather than passed through.

    ``generate_set`` assigns ``set_slots[position - 1]``, so ``0`` is Python's
    index ``-1``: the anchor silently becomes the LAST track of the set. That is
    not a rule this layer invented - inventory :963 is the dialog enforcing the
    same one - but the derivation is worth keeping beside the refusal.
    """
    refused, _body = generate(api, {"0": "f01"}, 4)
    assert refused == 400

    from recommendations.set_generator import generate_set

    library = api.library
    placed = generate_set(
        {0: "f01"}, 4, library.meta_ix, library.emb_ix, library.index
    )

    assert placed[-1].track_id == "f01"
    assert placed[-1].is_anchor is True
    assert placed[-1].position == 0


@pytest.mark.parametrize(
    "total", ["4", 4.0, None, True, False, [4]],
    ids=["string", "float", "null", "true", "false", "list"],
)
def test_a_total_that_is_not_an_integer_is_a_400(api, total):
    status, body = generate(api, {"1": "f01"}, total)

    assert status == 400
    assert body["error"]["code"] == "bad_request"
    assert "total_tracks" in body["error"]["message"]


def test_a_set_longer_than_the_cap_is_refused_rather_than_quietly_shortened(api):
    """A clamp would answer with a set that is not the one that was asked for,
    and the caller could not tell. The message names the cap."""
    status, body = generate(api, {"1": "f01"}, MAX_SET_TRACKS + 1)

    assert status == 400
    assert body["error"]["code"] == "bad_request"
    assert str(MAX_SET_TRACKS) in body["error"]["message"]


def test_the_cap_itself_is_accepted(api):
    """Guard the guard: an off-by-one that refused the cap would still pass the
    test above. The twelve-track library fills the rest with placeholders, which
    is the point - the cap is about work done, not about tracks available."""
    status, body = generate(api, {"1": "f01"}, MAX_SET_TRACKS)

    assert status == 200
    assert len(body["tracks"]) == MAX_SET_TRACKS


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_the_route_exists_and_is_a_post(api):
    routes = [(verb, pattern.pattern) for verb, pattern, _ in CocoApi.ROUTES]

    assert ("POST", r"^/api/set$") in routes
    assert [route for route in routes if route[1] == r"^/api/set$"] == [
        ("POST", r"^/api/set$")
    ]


def test_a_get_on_the_set_route_is_a_405_not_a_404(api):
    status, body = api.handle("GET", "/api/set", {})

    assert status == 405
    assert body["error"]["code"] == "method_not_allowed"


def test_the_builder_is_handed_the_parsed_anchors_and_nothing_else(
    fixture_library, tmp_path
):
    """The positions must arrive as INTEGER keys. JSON gives string keys, and
    ``set_slots[position - 1]`` on a string raises TypeError, so the conversion
    is load-bearing rather than cosmetic."""
    seen = []

    class RecordingBuilder:
        def build(self, anchor_tracks, total_tracks, exclude_tracks=None):
            seen.append((anchor_tracks, total_tracks, exclude_tracks))
            return []

    api = CocoApi(
        fixture_library,
        SettingsStore(tmp_path / "settings.json"),
        sets=RecordingBuilder(),
    )

    api.handle(
        "POST", "/api/set", {}, {"anchors": {"3": "f01", "7": "f06"}, "total_tracks": 9}
    )

    assert seen == [({3: "f01", 7: "f06"}, 9, None)]


def test_the_default_builder_is_bound_to_the_libraries_own_data(fixture_library, tmp_path):
    """Constructed, not injected, in production - and over the SAME session, so
    an index rebuild is seen without rebuilding the API."""
    from services.set_builder import SetBuilder

    api = CocoApi(fixture_library, SettingsStore(tmp_path / "settings.json"))

    assert isinstance(api.sets, SetBuilder)
    assert api.sets.library is fixture_library


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------


def test_the_running_server_serves_a_real_set_over_http(
    fixture_library, tmp_path, static_dir
):
    """Everything above calls ``handle`` directly. This one goes through the
    socket, the token check, the POST body limits and ``json.dumps``, because a
    handler that works and a route that is unreachable look identical from
    inside."""
    case = GOLDEN["two_anchors"]
    api = CocoApi(fixture_library, SettingsStore(tmp_path / "settings.json"))
    running = CocoServer(api, static_dir)
    running.start()
    try:
        response = client_for(running).post(
            "/api/set",
            json.dumps(
                {"anchors": case["anchors"], "total_tracks": case["total"]}
            ).encode("utf-8"),
            token=running.token,
        )
    finally:
        running.stop()

    assert response.status == 200
    assert [t["track_id"] for t in response.json["tracks"]] == [
        e["track_id"] for e in case["tracks"]
    ]
    assert [t["display_name"] for t in response.json["tracks"]] == [
        e["display_name"] for e in case["tracks"]
    ]


def test_the_set_endpoint_needs_the_token_like_every_other_api_path(
    fixture_library, tmp_path, static_dir
):
    api = CocoApi(fixture_library, SettingsStore(tmp_path / "settings.json"))
    running = CocoServer(api, static_dir)
    running.start()
    try:
        response = client_for(running).post(
            "/api/set", b'{"anchors":{"1":"f01"},"total_tracks":3}'
        )
    finally:
        running.stop()

    assert response.status == 401
