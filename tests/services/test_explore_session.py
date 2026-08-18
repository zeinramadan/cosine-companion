"""Characterisation tests for ExploreSession.

The ranking policy was duplicated in three places before this service existed:
recommendations_tab.py:236-247, playlist_exporter.py:101-116 and
playlist_exporter.py:185-202. All three ran

    recommend_for(seed, meta_ix, emb_ix, idx, topk=500, final_top=200)
    recs.sort(key=lambda x: x["cosine"], reverse=True)

and then truncated by a caller-supplied count. Diffed over 60 seeds x 3
truncation counts before refactoring: 0 ordering mismatches, 0 value
mismatches. They are behaviourally IDENTICAL; only the truncation count
differs, and that is a parameter, not policy. Recorded in the PR description.

These tests assert the exact ordered output of that policy against the real
1,307-track library, so a change in either step is caught.
"""

import pytest

from config import DATA
from recommendations.engine import recommend_for
from services.explore_session import ExploreSession, Recommendation
from services.library_session import LibrarySession

SEED = "64638770"  # Boris S. - Compression


@pytest.fixture(scope="module")
def library():
    return LibrarySession.load(DATA)


@pytest.fixture(scope="module")
def explore(library):
    return ExploreSession(library)


def _current_ui_policy(library, seed, topk, final_top):
    """The exact code the Explore tab ran before this service existed."""
    recs = recommend_for(
        seed, library.meta_ix, library.emb_ix, library.index,
        topk=topk, final_top=final_top,
    )
    recs.sort(key=lambda x: x["cosine"], reverse=True)
    return recs


# --------------------------------------------------------------------------
# The policy itself
# --------------------------------------------------------------------------


def test_matches_the_current_ui_policy_exactly(library, explore):
    """The Explore tab's configuration: topk=500, final_top=200."""
    expected = _current_ui_policy(library, SEED, 500, 200)

    got = explore.recommend(SEED, topk=500, final_top=200)

    assert [r.track_id for r in got] == [e["track_id"] for e in expected]
    assert [r.cosine for r in got] == [e["cosine"] for e in expected]
    assert [r.score for r in got] == [e["score"] for e in expected]


def test_matches_the_current_ui_policy_across_many_seeds(library, explore):
    import random

    random.seed(20260818)
    for seed in random.sample(library.ids, 15):
        expected = _current_ui_policy(library, seed, 500, 200)
        got = explore.recommend(seed, topk=500, final_top=200)
        assert [r.track_id for r in got] == [e["track_id"] for e in expected], seed


def test_results_are_ordered_by_cosine_descending(explore):
    got = explore.recommend(SEED, topk=500, final_top=200)

    cosines = [r.cosine for r in got]
    assert cosines == sorted(cosines, reverse=True)


def test_membership_is_chosen_by_score_even_though_order_is_by_cosine(library, explore):
    """The two steps compose into something that is neither pure-score nor
    pure-cosine ranking. Measured over 40 seeds: the top-200 differs from a pure
    cosine ranking of the same 500 candidates in 40/40 seeds."""
    policy = explore.recommend(SEED, topk=500, final_top=200)
    pure_cosine = sorted(
        recommend_for(SEED, library.meta_ix, library.emb_ix, library.index,
                      topk=500, final_top=500),
        key=lambda x: x["cosine"], reverse=True,
    )[:200]

    assert [r.track_id for r in policy] != [e["track_id"] for e in pure_cosine]


def test_final_top_truncates(explore):
    full = explore.recommend(SEED, topk=500, final_top=200)

    for n in (1, 15, 25, 50):
        truncated = explore.recommend(SEED, topk=500, final_top=n)
        assert len(truncated) == n
        # Truncation happens BEFORE the cosine re-sort, so a smaller final_top
        # is not simply a prefix of the larger one.
        assert all(isinstance(r, Recommendation) for r in truncated)
    assert len(full) == 200


def test_the_seed_track_is_never_recommended(library, explore):
    import random

    random.seed(11)
    for seed in random.sample(library.ids, 10):
        assert seed not in [r.track_id for r in explore.recommend(seed, topk=100, final_top=50)]


def test_defaults_match_the_config_constants(explore):
    from config import DEFAULT_FINAL_TOP

    assert len(explore.recommend(SEED)) == DEFAULT_FINAL_TOP == 15


def test_unknown_track_returns_nothing(explore):
    assert explore.recommend("no-such-track-id") == []


# --------------------------------------------------------------------------
# The Recommendation payload
# --------------------------------------------------------------------------


def test_recommendation_carries_every_field_the_ui_renders(explore):
    r = explore.recommend(SEED, topk=500, final_top=1)[0]

    assert isinstance(r.track_id, str)
    assert isinstance(r.artist, str) and isinstance(r.title, str)
    assert isinstance(r.key, str)
    assert isinstance(r.cosine, float) and isinstance(r.score, float)
    assert r.bpm is not None


def test_recommendation_carries_path_local_which_recommend_for_omits(library, explore):
    """recommend_for returns no path_local; the exporter re-reads it from
    meta_ix. Carrying it here means ExportService does not have to."""
    r = explore.recommend(SEED, topk=500, final_top=1)[0]

    assert r.path_local == library.get_track(r.track_id)["path_local"]
    assert "path_local" not in recommend_for(
        SEED, library.meta_ix, library.emb_ix, library.index, topk=10, final_top=1
    )[0]


def test_recommendation_keeps_the_component_scores(library, explore):
    expected = _current_ui_policy(library, SEED, 500, 200)[0]
    r = explore.recommend(SEED, topk=500, final_top=200)[0]

    assert r.key_score == expected["key_score"]
    assert r.bpm_score == expected["bpm_score"]


def test_recommendation_field_values_match_the_dicts_they_replace(library, explore):
    expected = _current_ui_policy(library, SEED, 500, 200)
    got = explore.recommend(SEED, topk=500, final_top=200)

    for r, e in zip(got, expected):
        assert r.artist == e["artist"]
        assert r.title == e["title"]
        assert r.key == e["key"]
        assert (r.bpm == e["bpm"]) or (r.bpm != r.bpm and e["bpm"] != e["bpm"])  # NaN
        assert r.cosine == e["cosine"]
        assert r.score == e["score"]


def test_rendered_explore_line_is_unchanged(library, explore):
    """The exact string format from recommendations_tab.update_listbox."""
    expected = _current_ui_policy(library, SEED, 500, 200)[0]
    old = (
        f"{expected['artist']} – {expected['title']}   "
        f"[Key {expected['key'] or '?'}  BPM {expected['bpm'] or '?'}  "
        f"Cos {float(expected['cosine']) * 100.0:.1f}%  "
        f"Score {max(0.0, min(1.0, float(expected['score']))) * 100.0:.1f}%]"
    )

    r = explore.recommend(SEED, topk=500, final_top=200)[0]
    new = (
        f"{r.artist} – {r.title}   "
        f"[Key {r.key or '?'}  BPM {r.bpm or '?'}  "
        f"Cos {float(r.cosine) * 100.0:.1f}%  "
        f"Score {max(0.0, min(1.0, float(r.score))) * 100.0:.1f}%]"
    )

    assert new == old
    assert new.startswith("Kessell – ") or " – " in new


def test_recommendations_are_independent_objects_per_call(explore):
    """The Explore tab copies the list into its history and re-sorts in place."""
    first = explore.recommend(SEED, topk=100, final_top=5)
    second = explore.recommend(SEED, topk=100, final_top=5)

    assert first is not second
    assert first[0] is not second[0]
    assert [r.track_id for r in first] == [r.track_id for r in second]


def test_recommendation_is_mutable_so_the_tab_can_sort_in_place(explore):
    """sort_suggestions sorts self.current_recommendations in place."""
    recs = explore.recommend(SEED, topk=100, final_top=10)

    recs.sort(key=lambda x: str(x.key))

    assert [r.key for r in recs] == sorted(str(r.key) for r in recs)


def test_reads_the_library_live_rather_than_snapshotting_it(library, explore):
    """The session must see index rebuilds (e.g. after a delete), because the
    Explore tab holds one ExploreSession for the lifetime of the window."""
    assert explore.library is library
    assert explore.recommend(SEED, topk=10, final_top=3)
