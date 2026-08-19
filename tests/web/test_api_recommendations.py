"""The recommendations endpoint.

This is the one endpoint with real behaviour behind it, and the behaviour is
not this layer's to invent: the ranking policy lives in
``recommendations/ranking.py`` and is pinned by committed golden values in the
services suite. What is asserted here is that the API calls it with the right
arguments and does not reorder, re-rank or re-truncate what comes back.

The candidate-pool configuration - ``topk=500, final_top=200`` - is the Explore
tab's, confirmed at docs/UI_FEATURE_INVENTORY.md:1378 and :370. It is *not*
``ExploreSession``'s own default, which is ``config.defaults`` DEFAULT_TOPK=200
/ DEFAULT_FINAL_TOP=15, so relying on the signature default would silently give
the web UI a different result set from the Tkinter one.
"""

import pytest

from services.explore_session import Recommendation

from webtest_support import NAN_BPM_TRACK_ID

from web.api import (
    EXPLORE_FINAL_TOP,
    EXPLORE_TOPK,
    MAX_RECOMMENDATION_LIMIT,
    CocoApi,
)

RECOMMENDATION_FIELDS = {
    "track_id",
    "artist",
    "title",
    "bpm",
    "key",
    "path_local",
    "cosine",
    "score",
    "key_score",
    "bpm_score",
}

SEED = "f01"


@pytest.fixture
def api(web_library, settings):
    return CocoApi(web_library, settings)


@pytest.fixture
def empty_api(empty_library, settings):
    return CocoApi(empty_library, settings)


def call(api, path, **params):
    query = {name: [str(value)] for name, value in params.items()}
    return api.handle("GET", path, query)


def recommendations(api, track_id=SEED, **params):
    status, body = call(api, f"/api/tracks/{track_id}/recommendations", **params)
    assert status == 200, body
    return body


class RecordingExplore:
    """Wraps a real ExploreSession and records how it was called."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def recommend(self, track_id, topk=None, final_top=None):
        self.calls.append({"track_id": track_id, "topk": topk, "final_top": final_top})
        return self.inner.recommend(track_id, topk=topk, final_top=final_top)


@pytest.fixture
def recording_api(web_library, settings):
    from services.explore_session import ExploreSession

    explore = RecordingExplore(ExploreSession(web_library))
    return CocoApi(web_library, settings, explore=explore), explore


# -- happy path ------------------------------------------------------------


def test_a_seed_returns_ranked_recommendations(api):
    body = recommendations(api)

    assert body["recommendations"], "the fixture library has thirteen other tracks"
    assert set(body["recommendations"][0]) == RECOMMENDATION_FIELDS


def test_the_response_carries_the_seed_as_a_full_track_detail(api):
    body = recommendations(api)

    assert body["seed"]["track_id"] == SEED
    assert body["seed"]["artist"] == "Alva Noto"
    assert body["seed"]["playlists"] is None


def test_the_seed_is_not_among_its_own_recommendations(api):
    body = recommendations(api)

    assert SEED not in [rec["track_id"] for rec in body["recommendations"]]


def test_the_body_is_real_json(api):
    import json

    body = recommendations(api)

    assert json.loads(json.dumps(body, allow_nan=False, ensure_ascii=False)) == body


def test_a_recommendation_with_no_bpm_reports_null(api):
    """w01 has a NaN bpm, and it is a candidate for every seed."""
    body = recommendations(api, limit=MAX_RECOMMENDATION_LIMIT)

    without_bpm = [
        rec for rec in body["recommendations"] if rec["track_id"] == NAN_BPM_TRACK_ID
    ]
    assert without_bpm, "w01 should be a candidate in a fourteen-track library"
    assert without_bpm[0]["bpm"] is None


def test_every_score_is_a_plain_number(api):
    """They come out of numpy, and np.float32 is not JSON-serialisable at all
    while np.float64 NaN serialises to an invalid literal."""
    for rec in recommendations(api)["recommendations"]:
        for field in ("cosine", "score", "key_score", "bpm_score"):
            assert isinstance(rec[field], float), (field, type(rec[field]))


# -- the arguments the service is called with ------------------------------


def test_the_explore_tab_configuration_is_used_by_default(recording_api):
    """topk=500, final_top=200 - inventory :1378. ExploreSession's own defaults
    are 200/15 and would quietly give a different result set."""
    api, explore = recording_api

    recommendations(api)

    assert explore.calls == [
        {"track_id": SEED, "topk": EXPLORE_TOPK, "final_top": EXPLORE_FINAL_TOP}
    ]
    assert (EXPLORE_TOPK, EXPLORE_FINAL_TOP) == (500, 200)


def test_topk_and_final_top_are_forwarded_when_given(recording_api):
    api, explore = recording_api

    recommendations(api, topk=40, final_top=7)

    assert explore.calls == [{"track_id": SEED, "topk": 40, "final_top": 7}]


def test_limit_truncates_after_ranking_and_is_never_passed_as_final_top(recording_api):
    """final_top decides *membership* by weighted score; the caller's limit
    truncates the cosine-ordered result. Confusing them changes which tracks
    come back, not merely how many (inventory §3.3)."""
    api, explore = recording_api

    body = recommendations(api, limit=2)

    assert len(body["recommendations"]) == 2
    assert explore.calls == [
        {"track_id": SEED, "topk": EXPLORE_TOPK, "final_top": EXPLORE_FINAL_TOP}
    ]


# -- ordering --------------------------------------------------------------


def test_the_order_is_exactly_what_the_service_returned(api, web_library):
    """No re-sorting in the API. The policy composes a score-decided membership
    with a cosine-decided order, and re-sorting either would change results
    that committed golden values pin."""
    from services.explore_session import ExploreSession

    expected = ExploreSession(web_library).recommend(
        SEED, topk=EXPLORE_TOPK, final_top=EXPLORE_FINAL_TOP
    )

    body = recommendations(api, limit=MAX_RECOMMENDATION_LIMIT)

    assert [rec["track_id"] for rec in body["recommendations"]] == [
        rec.track_id for rec in expected
    ]


def test_a_truncated_response_is_the_prefix_of_the_untruncated_one(api):
    full = recommendations(api, limit=MAX_RECOMMENDATION_LIMIT)["recommendations"]

    truncated = recommendations(api, limit=3)["recommendations"]

    assert [rec["track_id"] for rec in truncated] == [
        rec["track_id"] for rec in full[:3]
    ]


def test_the_values_match_the_service_field_for_field(api, web_library):
    from services.explore_session import ExploreSession

    expected = ExploreSession(web_library).recommend(
        SEED, topk=EXPLORE_TOPK, final_top=EXPLORE_FINAL_TOP
    )[0]

    first = recommendations(api)["recommendations"][0]

    assert first["track_id"] == expected.track_id
    assert first["artist"] == expected.artist
    assert first["title"] == expected.title
    assert first["key"] == expected.key
    assert first["path_local"] == expected.path_local
    assert first["cosine"] == pytest.approx(expected.cosine)
    assert first["score"] == pytest.approx(expected.score)


# -- limits ----------------------------------------------------------------


def test_the_default_limit_is_fifty(recording_api, api):
    """The Tkinter Explore tab's Top-N default (inventory :1377, :337)."""
    body = recommendations(api)

    assert len(body["recommendations"]) == min(50, 13)


class OversizedExplore:
    """An ExploreSession that returns more recommendations than the cap.

    The fixture library has fourteen tracks, so ``recommend`` can never return
    more than thirteen and ``len(recommendations) <= 200`` was true whatever
    the cap was - raising MAX_RECOMMENDATION_LIMIT to 9999 left the clamp test
    green. Only a ranked list longer than the cap can make the cap bite, and
    the ranking is not what is under test here: the API's own truncation is.
    """

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def recommend(self, track_id, topk=None, final_top=None):
        self.calls.append({"track_id": track_id, "topk": topk, "final_top": final_top})
        return [
            Recommendation(
                track_id=f"r{index:04d}",
                artist=f"Artist {index:04d}",
                title=f"Title {index:04d}",
                bpm=120.0 + index,
                key="8A",
                path_local=f"/nonexistent/{index}.mp3",
                cosine=1.0 - index / self.rows,
                score=1.0 - index / self.rows,
                key_score=1.0,
                bpm_score=1.0,
            )
            for index in range(self.rows)
        ]


#: Comfortably past MAX_RECOMMENDATION_LIMIT (200).
OVERSIZED_ROWS = 500


@pytest.fixture
def oversized_api(web_library, settings):
    """The real library (so the seed lookup is real) with a ranking stub."""
    explore = OversizedExplore(OVERSIZED_ROWS)
    return CocoApi(web_library, settings, explore=explore), explore


def test_the_limit_is_clamped_to_two_hundred(oversized_api):
    """200 is the most the Tkinter Top-N combobox offers (inventory :337)."""
    api, explore = oversized_api

    body = recommendations(api, limit=99999)

    # The literal as well as the constant: `limit=99999` resolving to
    # MAX_RECOMMENDATION_LIMIT is trivially true when that constant is 99999.
    # 200 is the largest value the Tkinter Top-N combobox offers (:337), so it
    # is a contract number rather than an implementation detail.
    assert MAX_RECOMMENDATION_LIMIT == 200
    assert OVERSIZED_ROWS > MAX_RECOMMENDATION_LIMIT, "the stub cannot bind the cap"
    assert len(body["recommendations"]) == 200
    # And it is the API doing the truncating, not the ranking: the session was
    # still asked for the full Explore pool.
    assert explore.calls == [
        {"track_id": SEED, "topk": EXPLORE_TOPK, "final_top": EXPLORE_FINAL_TOP}
    ]


def test_the_recommendation_cap_is_the_documented_number(oversized_api):
    """One below, at, and one above, so an off-by-one in the clamp shows."""
    api, _ = oversized_api

    under = recommendations(api, limit=MAX_RECOMMENDATION_LIMIT - 1)
    at = recommendations(api, limit=MAX_RECOMMENDATION_LIMIT)
    over = recommendations(api, limit=MAX_RECOMMENDATION_LIMIT + 1)

    assert len(under["recommendations"]) == MAX_RECOMMENDATION_LIMIT - 1
    assert len(at["recommendations"]) == MAX_RECOMMENDATION_LIMIT
    assert len(over["recommendations"]) == MAX_RECOMMENDATION_LIMIT


def test_the_truncation_keeps_the_head_of_the_ranking(oversized_api):
    """Clamping must take the FIRST n, not a slice from anywhere else: the
    order is by raw cosine and the head is the answer (§3.3)."""
    api, _ = oversized_api

    body = recommendations(api, limit=3)

    assert [rec["track_id"] for rec in body["recommendations"]] == [
        "r0000",
        "r0001",
        "r0002",
    ]


def test_a_zero_limit_returns_the_seed_and_no_recommendations(api):
    body = recommendations(api, limit=0)

    assert body["recommendations"] == []
    assert body["seed"]["track_id"] == SEED


# -- errors ----------------------------------------------------------------


def test_an_unknown_seed_is_a_404(api):
    status, body = call(api, "/api/tracks/nope/recommendations")

    assert status == 404
    assert body["error"]["code"] == "unknown_track"


def test_a_library_with_no_index_is_a_409(empty_api):
    """409 rather than 500 or an empty list: nothing can be recommended without
    an index, and the frontend needs to tell that apart from "no matches" so it
    can say so.

    Note the precedence: emptiness is checked BEFORE the seed is looked up.
    That is deliberate and it is not the order the plan's contract implied. The
    plan describes "a valid track in an empty library", but that state is not
    reachable through the services - LibrarySession.delete_tracks empties
    meta_ix along with the index, so a library with no index has no known track
    ids either. Checking emptiness first is the only ordering that makes the
    409 observable at all.
    """
    status, body = call(empty_api, f"/api/tracks/{SEED}/recommendations")

    assert status == 409
    assert body["error"]["code"] == "empty_library"


def test_the_409_takes_precedence_over_the_404(empty_api):
    """Both are true of an unloaded library; the more informative one wins."""
    status, body = call(empty_api, "/api/tracks/definitely-not-a-track/recommendations")

    assert status == 409
    assert body["error"]["code"] == "empty_library"


@pytest.mark.parametrize("name", ["topk", "final_top", "limit"])
def test_a_non_integer_parameter_is_a_400_not_a_traceback(api, name):
    status, body = call(api, f"/api/tracks/{SEED}/recommendations", **{name: "abc"})

    assert status == 400
    assert body["error"]["code"] == "bad_request"
    assert name in body["error"]["message"]


@pytest.mark.parametrize("name", ["topk", "final_top", "limit"])
def test_a_negative_parameter_is_a_400(api, name):
    status, body = call(api, f"/api/tracks/{SEED}/recommendations", **{name: -5})

    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_a_seed_that_exists_in_metadata_but_has_no_vector_is_not_a_crash(
    web_library, settings
):
    """recommend_for returns [] when vector_for finds nothing, rather than
    raising. An empty list with a 200 is the honest answer - the track is real,
    it just has no neighbours to offer."""
    import pandas as pd

    web_library._meta_ix = pd.concat(
        [
            web_library.meta_ix,
            pd.DataFrame(
                [{"track_id": "ghost", "artist": "A", "title": "B", "bpm": 120.0,
                  "key": "8A", "album": "", "path": "", "path_local": ""}]
            ).set_index("track_id"),
        ]
    )
    api = CocoApi(web_library, settings)

    status, body = call(api, "/api/tracks/ghost/recommendations")

    assert status == 200
    assert body["recommendations"] == []
    assert body["seed"]["track_id"] == "ghost"
