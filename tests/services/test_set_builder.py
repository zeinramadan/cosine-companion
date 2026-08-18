"""Characterisation tests for SetBuilder.

SetBuilder wraps recommendations.set_generator.generate_set, which the Set
Creator tab called directly. The plan sketched
``.build(seed_track_id, length, **params)`` but also said to "mirror the current
set_generator signature exactly; read it before designing" - and generate_set
takes {position: track_id} anchors, not a single seed, and returns SetTrack
objects carrying position / is_anchor / icon / display_name that a
Recommendation cannot express. The mirroring instruction wins, because it is the
behaviour-preserving reading. Recorded in the PR description.

Assertions run against the real 1,307-track library; generate_set is
deterministic given its inputs.
"""

import pytest

from config import DATA
from recommendations.models import SetTrack
from recommendations.set_generator import generate_set
from services.library_session import LibrarySession
from services.set_builder import SetBuilder

ANCHOR = "64638770"   # Boris S. - Compression
ANCHOR_2 = "24614611"  # Lars Huismann - Superfunk 1


@pytest.fixture(scope="module")
def library():
    return LibrarySession.load(DATA)


@pytest.fixture(scope="module")
def builder(library):
    return SetBuilder(library)


def _current_ui_path(library, anchors, total, exclude=None):
    """The exact call the Set Creator tab made before this service existed."""
    return generate_set(
        anchors, total, library.meta_ix, library.emb_ix, library.index,
        exclude_tracks=exclude,
    )


def test_matches_the_current_ui_path_exactly(library, builder):
    expected = _current_ui_path(library, {3: ANCHOR}, 6)

    got = builder.build({3: ANCHOR}, 6)

    assert [t.track_id for t in got] == [t.track_id for t in expected]
    assert [t.position for t in got] == [t.position for t in expected]
    assert [t.score for t in got] == [t.score for t in expected]
    assert [t.is_anchor for t in got] == [t.is_anchor for t in expected]


def test_matches_the_current_ui_path_with_several_anchors(library, builder):
    anchors = {1: ANCHOR, 5: ANCHOR_2}
    expected = _current_ui_path(library, anchors, 8)

    got = builder.build(anchors, 8)

    assert [(t.position, t.track_id, t.score) for t in got] == [
        (t.position, t.track_id, t.score) for t in expected
    ]


def test_returns_set_tracks_not_recommendations(builder):
    got = builder.build({1: ANCHOR}, 4)

    assert all(isinstance(t, SetTrack) for t in got)


def test_produces_the_requested_length(builder):
    for length in (1, 4, 10):
        assert len(builder.build({1: ANCHOR}, length)) == length


def test_anchors_land_on_their_positions_and_are_marked(builder):
    got = builder.build({2: ANCHOR, 4: ANCHOR_2}, 5)

    by_position = {t.position: t for t in got}
    assert by_position[2].track_id == ANCHOR
    assert by_position[4].track_id == ANCHOR_2
    assert by_position[2].is_anchor and by_position[4].is_anchor
    assert by_position[2].score == 1.0
    assert not by_position[1].is_anchor


def test_no_track_is_used_twice(builder):
    got = builder.build({1: ANCHOR}, 20)

    ids = [t.track_id for t in got if not t.track_id.startswith("empty_")]
    assert len(ids) == len(set(ids))


def test_generated_tracks_carry_the_transition_score(library, builder):
    """0.8 * cos(prev -> candidate) + 0.2 * cos(candidate -> next), from
    recommendations.transitions.calculate_transition_score.

    The forward context is the next ALREADY-PLACED track, not the track that
    eventually lands in the next slot: slots are filled left to right, so when
    position 2 is chosen, position 3 is still empty and the anchor at position 4
    supplies the forward term. Pinned because it is easy to assume otherwise.
    """
    from recommendations.transitions import calculate_transition_score

    got = builder.build({1: ANCHOR, 4: ANCHOR_2}, 4)

    second = next(t for t in got if t.position == 2)
    third = next(t for t in got if t.position == 3)
    assert second.score == pytest.approx(
        calculate_transition_score(ANCHOR, second.track_id, ANCHOR_2, library.emb_ix)
    )
    # ...and position 3 then looks back at 2 and forward to the anchor at 4.
    assert third.score == pytest.approx(
        calculate_transition_score(second.track_id, third.track_id, ANCHOR_2, library.emb_ix)
    )


def test_transition_scoring_weights_are_eighty_twenty(library):
    """Pins the weighting itself, independent of any particular set."""
    import numpy as np
    from recommendations.engine import vector_for
    from recommendations.transitions import calculate_transition_score

    a, b, c = library.ids[0], library.ids[1], library.ids[2]
    va, vb, vc = (vector_for(t, library.emb_ix) for t in (a, b, c))

    assert calculate_transition_score(a, b, c, library.emb_ix) == pytest.approx(
        0.8 * float(np.dot(va, vb)) + 0.2 * float(np.dot(vb, vc))
    )
    # With no next track it is the plain cosine.
    assert calculate_transition_score(a, b, None, library.emb_ix) == pytest.approx(
        float(np.dot(va, vb))
    )


def test_per_hop_candidate_pool_is_topk_100_final_top_50(library, builder, monkeypatch):
    """set_generator.py:90-106 requests topk=100, final_top=50 for every hop."""
    import recommendations.set_generator as sg

    calls = []
    real = sg.recommend_for

    def spy(track_id, meta_ix, emb_ix, idx, topk, final_top):
        calls.append((topk, final_top))
        return real(track_id, meta_ix, emb_ix, idx, topk=topk, final_top=final_top)

    monkeypatch.setattr(sg, "recommend_for", spy)

    builder.build({1: ANCHOR}, 5)

    assert calls, "no candidate lookups happened"
    assert set(calls) == {(100, 50)}


def test_excluded_tracks_are_not_used(builder):
    baseline = builder.build({1: ANCHOR}, 5)
    banned = [t.track_id for t in baseline if not t.is_anchor][:2]

    got = builder.build({1: ANCHOR}, 5, exclude_tracks=banned)

    assert not set(banned) & {t.track_id for t in got}


def test_requires_at_least_one_anchor(builder):
    with pytest.raises(ValueError, match="At least one anchor track is required"):
        builder.build({}, 5)


def test_rejects_an_anchor_beyond_the_set_length(builder):
    """The Set Creator tab does not pre-validate this; the ValueError surfaces
    in its 'Generation Error' dialog. Current behaviour."""
    with pytest.raises(ValueError, match="Anchor track position exceeds total tracks"):
        builder.build({9: ANCHOR}, 5)


def test_unfillable_slots_become_placeholders(library):
    """CURRENT BEHAVIOUR. When no candidate survives filtering, the slot is
    filled with artist='No suitable track found' and track_id='empty_{n}',
    which the tab renders and its clipboard export then skips."""
    small = LibrarySession.load(DATA)
    builder = SetBuilder(small)
    everything = [t for t in small.ids if t != ANCHOR]

    got = builder.build({1: ANCHOR}, 3, exclude_tracks=everything)

    placeholders = [t for t in got if t.track_id.startswith("empty_")]
    assert len(placeholders) == 2
    assert placeholders[0].artist == "No suitable track found"
    assert placeholders[0].title == ""
    assert placeholders[0].score == 0.0
    assert placeholders[0].display_name == "No suitable track found – (Unknown Title)"


def test_rendered_set_line_is_unchanged(builder):
    """The exact string format from set_creator_tab.update_set_listbox."""
    got = builder.build({3: ANCHOR}, 4)

    lines = []
    for track in got:
        score_text = ""
        if not track.is_anchor and track.score > 0:
            score_text = f" ({track.score:.0%} match)"
        lines.append(f"[{track.position:2d}] {track.icon} {track.display_name}{score_text}")

    assert lines[2].startswith("[ 3] 🔒 ")
    assert lines[0].startswith("[ 1] 🤖 ")
    assert "match)" in lines[0]
    assert " – " in lines[0]


def test_reads_the_library_live(library, builder):
    assert builder.library is library
