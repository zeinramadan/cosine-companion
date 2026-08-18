"""Proof that the golden values are discriminating.

A golden file is only worth having if it fails when behaviour drifts. The tests
it replaced looked convincing and asserted nothing - they computed their
"expected" value by calling the code under test. To make sure the replacements
are not quietly toothless in some other way, this file perturbs the engine four
ways and asserts that the golden comparisons **fail**.

Each perturbation is a plausible refactor, not a random mutation:

1. re-weighting the score (someone "tunes" the recommender)
2. dropping the cosine re-sort (someone "simplifies" the two-step policy)
3. moving the truncation to after the re-sort (someone "cleans up" the ordering)
4. re-weighting the transition score (someone "improves" set flow)

Every one is reverted by ``monkeypatch`` at the end of its test.
"""

import pytest

from fixture_library import GOLDEN_SEEDS, load_golden
from services.explore_session import ExploreSession
from services.set_builder import SetBuilder
from test_explore_session import assert_matches_golden as assert_explore_golden
from test_set_builder import assert_matches_golden as assert_set_golden
from test_set_builder import run_case

EXPLORE_GOLDEN = load_golden("explore_fixture")
SET_GOLDEN = load_golden("set_builder_fixture")

SEED = GOLDEN_SEEDS[0]


def check_explore_golden(library, seed=SEED):
    got = ExploreSession(library).recommend(seed, topk=500, final_top=200)
    assert_explore_golden(got, EXPLORE_GOLDEN["seeds"][seed])


def check_truncation_golden(library, n="5"):
    got = ExploreSession(library).recommend(SEED, topk=500, final_top=int(n))
    assert [r.track_id for r in got] == EXPLORE_GOLDEN["truncations"][n]


def check_set_golden(library, name="two_anchors"):
    assert_set_golden(run_case(SetBuilder(library), SET_GOLDEN[name]), SET_GOLDEN[name])


# --------------------------------------------------------------------------
# Baseline: unperturbed, the goldens pass
# --------------------------------------------------------------------------


def test_the_goldens_pass_when_nothing_is_perturbed(fixture_library):
    check_explore_golden(fixture_library)
    check_truncation_golden(fixture_library)
    check_set_golden(fixture_library)


# --------------------------------------------------------------------------
# Perturbations
# --------------------------------------------------------------------------


def test_reweighting_the_score_breaks_the_explore_goldens(fixture_library, monkeypatch):
    """0.7/0.2/0.1 -> 0.5/0.3/0.2."""
    import recommendations.engine as engine

    monkeypatch.setattr(
        engine, "final_score",
        lambda cosine, key_score, bpm_score, weights=None:
            0.5 * cosine + 0.3 * key_score + 0.2 * bpm_score,
    )

    with pytest.raises(AssertionError):
        check_explore_golden(fixture_library)


def test_dropping_the_cosine_resort_breaks_the_explore_goldens(fixture_library, monkeypatch):
    """The policy's second step removed - results left in weighted-score order.
    A test that only checked lengths and types would not notice."""
    import services.explore_session as module
    from recommendations.engine import recommend_for

    def unsorted_policy(track_id, meta_ix, emb_ix, idx, topk, final_top, limit=None):
        recs = recommend_for(track_id, meta_ix, emb_ix, idx, topk=topk, final_top=final_top)
        return recs if limit is None else recs[:limit]

    monkeypatch.setattr(module, "ranked_recommendations", unsorted_policy)

    with pytest.raises(AssertionError):
        check_explore_golden(fixture_library)


def test_truncating_after_the_resort_breaks_the_truncation_goldens(fixture_library, monkeypatch):
    """final_top applied AFTER the cosine sort instead of before it. The set of
    surviving tracks changes while the LENGTH stays identical - precisely the
    drift the old length-only assertion could not catch."""
    import services.explore_session as module
    from recommendations.engine import recommend_for

    def late_truncation(track_id, meta_ix, emb_ix, idx, topk, final_top, limit=None):
        recs = recommend_for(track_id, meta_ix, emb_ix, idx, topk=topk, final_top=topk)
        recs.sort(key=lambda x: x["cosine"], reverse=True)
        recs = recs[:final_top]
        return recs if limit is None else recs[:limit]

    monkeypatch.setattr(module, "ranked_recommendations", late_truncation)

    # The length is unchanged...
    assert len(ExploreSession(fixture_library).recommend(SEED, topk=500, final_top=5)) == 5
    # ...and the golden still catches it.
    with pytest.raises(AssertionError):
        check_truncation_golden(fixture_library)


def test_reweighting_the_transition_score_breaks_the_set_goldens(fixture_library, monkeypatch):
    """0.8/0.2 -> 0.5/0.5."""
    import numpy as np

    import recommendations.set_generator as sg
    from recommendations.engine import vector_for

    def half_and_half(from_track_id, to_track_id, next_track_id, emb_ix):
        from_vec = vector_for(from_track_id, emb_ix)
        to_vec = vector_for(to_track_id, emb_ix)
        if from_vec is None or to_vec is None:
            return 0.0
        cosine = float(np.dot(from_vec, to_vec))
        if next_track_id:
            next_vec = vector_for(next_track_id, emb_ix)
            if next_vec is not None:
                return 0.5 * cosine + 0.5 * float(np.dot(to_vec, next_vec))
        return cosine

    monkeypatch.setattr(sg, "calculate_transition_score", half_and_half)

    with pytest.raises(AssertionError):
        check_set_golden(fixture_library)


def test_changing_the_per_hop_candidate_pool_breaks_the_set_goldens(fixture_library, monkeypatch):
    """topk=100/final_top=50 -> topk=10/final_top=3."""
    import recommendations.set_generator as sg

    real = sg.recommend_for
    monkeypatch.setattr(
        sg, "recommend_for",
        lambda track_id, meta_ix, emb_ix, idx, topk, final_top: real(
            track_id, meta_ix, emb_ix, idx, topk=10, final_top=3
        ),
    )

    with pytest.raises(AssertionError):
        check_set_golden(fixture_library)


def test_breaking_the_filename_sanitiser_breaks_the_export_goldens(fixture_library, tmp_path, monkeypatch):
    """Keeping '/' and ':' would change every playlist filename."""
    import recommendations.playlist_exporter as exporter

    monkeypatch.setattr(exporter, "sanitise_filename_part", lambda value: value.strip().upper())

    from services.export_service import ExportService

    out = tmp_path / "out"
    ExportService(fixture_library).export_per_seed(GOLDEN_SEEDS, str(out), 2)

    written = sorted(p.name for p in out.glob("*.m3u"))
    assert written != sorted(load_golden("export_fixture")["per_seed"]["2"])


def test_the_perturbations_are_undone(fixture_library):
    """monkeypatch reverts everything; this fails loudly if one leaked."""
    check_explore_golden(fixture_library)
    check_truncation_golden(fixture_library)
    check_set_golden(fixture_library)
