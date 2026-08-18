"""Characterisation tests for ExploreSession, pinned to committed golden values.

**Why golden values.** The first version of this file computed its "expected"
result by calling ``recommend_for`` and re-sorting - the very two steps
``ExploreSession`` performs. Every assertion was therefore of the form
``f(x) == f(x)``: it would have passed unchanged if the ordering flipped, if the
scoring weights moved, or if the truncation point shifted. That is a tautology,
not a baseline, and a baseline is the entire purpose of this PR.

So the expectations now come from ``golden/explore_*.json``, committed files
that the test never regenerates. If the engine's behaviour drifts, these fail.
``test_golden_values_actually_fail.py`` proves they do.

**Exactness.** Track-id order is compared exactly. Floats are compared to
``abs=1e-6``: regenerating on two different NumPy builds gives identical
ordering but float32 values differing by up to 1.8e-7 (one ulp of the ``float32``
matmul in ``core/index_builder.py``). 1e-6 is ~30x that noise and four orders of
magnitude tighter than any behavioural change. See ``golden/README.md``.

Both libraries are exercised: the twelve committed fixture tracks (everywhere,
including CI) and the real 1,307-track library (skipped when ``data/`` is
absent, which is always the case on CI because it is gitignored).
"""

import pytest

from fixture_library import GOLDEN_SEEDS, load_golden
from services.explore_session import ExploreSession, Recommendation

FLOAT_TOLERANCE = 1e-6

REAL_SEED = "64638770"  # Boris S. - Compression

GOLDEN = load_golden("explore_fixture")
GOLDEN_REAL = load_golden("explore_real")


@pytest.fixture
def explore(fixture_library):
    return ExploreSession(fixture_library)


@pytest.fixture
def real_explore(real_library):
    return ExploreSession(real_library)


def assert_matches_golden(got, expected_rows):
    """Ids exactly; floats to FLOAT_TOLERANCE; artist/title/key exactly."""
    assert [r.track_id for r in got] == [e["track_id"] for e in expected_rows]

    for r, e in zip(got, expected_rows):
        assert r.artist == e["artist"], r.track_id
        assert r.title == e["title"], r.track_id
        assert r.key == e["key"], r.track_id
        assert r.bpm == pytest.approx(e["bpm"], abs=FLOAT_TOLERANCE), r.track_id
        assert r.cosine == pytest.approx(e["cosine"], abs=FLOAT_TOLERANCE), r.track_id
        assert r.score == pytest.approx(e["score"], abs=FLOAT_TOLERANCE), r.track_id
        assert r.key_score == pytest.approx(e["key_score"], abs=FLOAT_TOLERANCE), r.track_id
        assert r.bpm_score == pytest.approx(e["bpm_score"], abs=FLOAT_TOLERANCE), r.track_id


# --------------------------------------------------------------------------
# Golden: the exact ranked output
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", GOLDEN_SEEDS)
def test_ranked_output_matches_the_golden_values(explore, seed):
    """The Explore tab's configuration: topk=500, final_top=200."""
    got = explore.recommend(seed, topk=500, final_top=200)

    assert_matches_golden(got, GOLDEN["seeds"][seed])
    assert got, "golden file recorded an empty ranking"


@pytest.mark.parametrize("seed", sorted(GOLDEN_REAL["seeds"]))
def test_ranked_output_matches_the_golden_values_on_the_real_library(real_explore, seed):
    expected = GOLDEN_REAL["seeds"][seed]

    got = real_explore.recommend(seed, topk=500, final_top=200)

    assert [r.track_id for r in got] == expected["order"]
    assert len(got) == 200
    assert_matches_golden(got[: len(expected["head"])], expected["head"])


def test_the_golden_real_library_is_the_one_we_captured(real_library):
    assert real_library.track_count == GOLDEN_REAL["track_count"] == 1307


# --------------------------------------------------------------------------
# Golden: truncation. final_top truncates BEFORE the cosine re-sort, the
# exporter's limit AFTER it, so the two produce different sets - which is
# exactly what a length-and-type assertion could never have caught.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("n", sorted(GOLDEN["truncations"], key=int))
def test_final_top_truncation_matches_the_golden_ids(explore, n):
    expected = GOLDEN["truncations"][n]

    got = explore.recommend(GOLDEN_SEEDS[0], topk=500, final_top=int(n))

    assert [r.track_id for r in got] == expected
    assert len(got) == int(n) == len(expected)
    assert all(isinstance(r, Recommendation) for r in got)


def test_a_smaller_final_top_is_not_a_prefix_of_a_larger_one(explore):
    """Because the weighted score picks the members and cosine orders them,
    shrinking final_top changes *which* tracks survive, not just how many.
    Pinned as an explicit golden fact, from the same committed file."""
    five = GOLDEN["truncations"]["5"]
    eleven = GOLDEN["truncations"]["11"]

    assert five != eleven[:5]
    assert [r.track_id for r in explore.recommend(GOLDEN_SEEDS[0], topk=500, final_top=5)] == five


@pytest.mark.parametrize("n", sorted(GOLDEN_REAL["truncations"], key=int))
def test_real_library_truncation_matches_the_golden_ids(real_explore, n):
    got = real_explore.recommend(REAL_SEED, topk=500, final_top=int(n))

    assert [r.track_id for r in got] == GOLDEN_REAL["truncations"][n]
    assert len(got) == int(n)


def test_real_library_smaller_final_top_is_not_a_prefix(real_explore):
    twentyfive = GOLDEN_REAL["truncations"]["25"]
    two_hundred = GOLDEN_REAL["truncations"]["200"]

    assert twentyfive != two_hundred[:25]
    assert [r.track_id for r in real_explore.recommend(REAL_SEED, topk=500, final_top=25)] == twentyfive


# --------------------------------------------------------------------------
# The policy's shape
# --------------------------------------------------------------------------


def test_results_are_ordered_by_cosine_descending(explore):
    cosines = [r.cosine for r in explore.recommend(GOLDEN_SEEDS[0], topk=500, final_top=200)]

    assert cosines == sorted(cosines, reverse=True)


def test_membership_is_chosen_by_score_even_though_order_is_by_cosine(explore, fixture_library):
    """The two steps compose into something that is neither pure-score nor
    pure-cosine ranking, and the golden file records the difference."""
    from recommendations.ranking import ranked_recommendations

    policy = GOLDEN["truncations"]["5"]
    pure_cosine = [
        r["track_id"]
        for r in sorted(
            ranked_recommendations(
                GOLDEN_SEEDS[0], fixture_library.meta_ix, fixture_library.emb_ix,
                fixture_library.index, topk=500, final_top=11,
            ),
            key=lambda x: x["cosine"], reverse=True,
        )
    ][:5]

    assert policy != pure_cosine


def test_the_seed_track_is_never_recommended(explore):
    for seed, _artist, *_ in [(t, None) for t in GOLDEN_SEEDS]:
        assert seed not in [r.track_id for r in explore.recommend(seed, topk=100, final_top=50)]


def test_defaults_match_the_config_constants(real_explore):
    from config import DEFAULT_FINAL_TOP

    assert len(real_explore.recommend(REAL_SEED)) == DEFAULT_FINAL_TOP == 15


def test_unknown_track_returns_nothing(explore):
    assert explore.recommend("no-such-track-id") == []


def test_explore_delegates_to_the_shared_ranking_policy(explore, monkeypatch):
    """The policy must live in recommendations.ranking, not be re-implemented
    here - that is what lets both playlist exporters share it."""
    import services.explore_session as module

    calls = []
    real = module.ranked_recommendations

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "ranked_recommendations", spy)
    explore.recommend(GOLDEN_SEEDS[0], topk=500, final_top=200)

    assert calls == [{"topk": 500, "final_top": 200}]


# --------------------------------------------------------------------------
# The Recommendation payload
# --------------------------------------------------------------------------


def test_recommendation_carries_every_field_the_ui_renders(explore):
    r = explore.recommend(GOLDEN_SEEDS[0], topk=500, final_top=1)[0]

    assert isinstance(r.track_id, str)
    assert isinstance(r.artist, str) and isinstance(r.title, str)
    assert isinstance(r.key, str)
    assert isinstance(r.cosine, float) and isinstance(r.score, float)
    assert r.bpm is not None


def test_recommendation_carries_path_local_which_recommend_for_omits(explore, fixture_library):
    """recommend_for returns no path_local; the exporter re-reads it from
    meta_ix. Carrying it here means the Explore tab does not have to."""
    from recommendations.engine import recommend_for

    r = explore.recommend(GOLDEN_SEEDS[0], topk=500, final_top=1)[0]

    assert r.path_local == fixture_library.get_track(r.track_id)["path_local"]
    assert "path_local" not in recommend_for(
        GOLDEN_SEEDS[0], fixture_library.meta_ix, fixture_library.emb_ix,
        fixture_library.index, topk=10, final_top=1,
    )[0]


def test_rendered_explore_line_matches_the_golden_string(explore):
    """The exact string recommendations_tab.update_listbox builds, for the
    top golden row. Hard-coded, so a formatting change fails here."""
    expected = GOLDEN["seeds"]["f01"][0]
    r = explore.recommend("f01", topk=500, final_top=200)[0]

    line = (
        f"{r.artist} – {r.title}   "
        f"[Key {r.key or '?'}  BPM {r.bpm or '?'}  "
        f"Cos {float(r.cosine) * 100.0:.1f}%  "
        f"Score {max(0.0, min(1.0, float(r.score))) * 100.0:.1f}%]"
    )

    assert line == "Blawan – Why They Hide   [Key 9A  BPM 130.0  Cos 96.7%  Score 93.7%]"
    assert expected["track_id"] == "f02"


def test_rendered_explore_line_is_unchanged_on_the_real_library(real_explore):
    head = GOLDEN_REAL["seeds"][REAL_SEED]["head"][0]
    r = real_explore.recommend(REAL_SEED, topk=500, final_top=200)[0]

    line = (
        f"{r.artist} – {r.title}   "
        f"[Key {r.key or '?'}  BPM {r.bpm or '?'}  "
        f"Cos {float(r.cosine) * 100.0:.1f}%  "
        f"Score {max(0.0, min(1.0, float(r.score))) * 100.0:.1f}%]"
    )

    assert line == (
        f"{head['artist']} – {head['title']}   "
        f"[Key {head['key']}  BPM {head['bpm']}  "
        f"Cos {head['cosine'] * 100.0:.1f}%  "
        f"Score {max(0.0, min(1.0, head['score'])) * 100.0:.1f}%]"
    )
    assert " – " in line


def test_recommendations_are_independent_objects_per_call(explore):
    """The Explore tab copies the list into its history and re-sorts in place."""
    first = explore.recommend(GOLDEN_SEEDS[0], topk=100, final_top=5)
    second = explore.recommend(GOLDEN_SEEDS[0], topk=100, final_top=5)

    assert first is not second
    assert first[0] is not second[0]
    assert [r.track_id for r in first] == [r.track_id for r in second]


def test_recommendation_is_mutable_so_the_tab_can_sort_in_place(explore):
    """sort_suggestions sorts self.current_recommendations in place."""
    recs = explore.recommend(GOLDEN_SEEDS[0], topk=100, final_top=10)

    recs.sort(key=lambda x: str(x.key))

    assert [r.key for r in recs] == sorted(str(r.key) for r in recs)


def test_reads_the_library_live_rather_than_snapshotting_it(explore, fixture_library):
    """The Explore tab holds one ExploreSession for the window's lifetime, so
    it must see an index rebuild. Note the deliberate contrast with
    ExportService, which snapshots for the duration of one export."""
    assert explore.library is fixture_library
    assert explore.recommend(GOLDEN_SEEDS[0], topk=10, final_top=3)
