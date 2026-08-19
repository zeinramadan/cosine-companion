"""Characterisation tests for SetBuilder, pinned to committed golden sequences.

**Why golden values.** The first version of this file built its "expected" set
by calling ``generate_set`` - the function ``SetBuilder.build`` wraps. Every
assertion was ``f(x) == f(x)``, so it would have passed unchanged if the
transition scoring, the candidate pool or the anchor placement changed. That is
a tautology, and this PR exists to be a baseline.

The expectations now come from ``golden/set_builder_*.json``: for fixed anchors,
the exact ordered ``SetTrack`` sequence, including position, is_anchor, score,
artist, title, the rendered ``display_name`` and the icon.
``test_golden_values_actually_fail.py`` proves these goldens are discriminating.

SetBuilder wraps ``recommendations.set_generator.generate_set``, which the Set
Creator tab called directly. The plan sketched ``.build(seed_track_id, length,
**params)`` but also said to "mirror the current set_generator signature
exactly; read it before designing" - and generate_set takes {position:
track_id} anchors, not a single seed, and returns SetTrack objects carrying
position / is_anchor / icon / display_name that a Recommendation cannot
express. The mirroring instruction wins, because it is the behaviour-preserving
reading. Recorded in the PR description.
"""

import pytest

from fixture_library import load_golden
from recommendations.models import SetTrack
from services.set_builder import SetBuilder

FLOAT_TOLERANCE = 1e-6

ANCHOR = "f01"
ANCHOR_2 = "f06"

REAL_ANCHOR = "64638770"   # Boris S. - Compression
REAL_ANCHOR_2 = "24614611"  # Lars Huismann - Superfunk 1

GOLDEN = load_golden("set_builder_fixture")
GOLDEN_REAL = load_golden("set_builder_real")


@pytest.fixture
def builder(fixture_library):
    return SetBuilder(fixture_library)


@pytest.fixture
def real_builder(real_library):
    return SetBuilder(real_library)


def assert_matches_golden(got, case):
    expected = case["tracks"]

    assert [t.track_id for t in got] == [e["track_id"] for e in expected]
    assert [t.position for t in got] == [e["position"] for e in expected]
    assert [t.is_anchor for t in got] == [e["is_anchor"] for e in expected]
    assert [t.artist for t in got] == [e["artist"] for e in expected]
    assert [t.title for t in got] == [e["title"] for e in expected]
    assert [t.display_name for t in got] == [e["display_name"] for e in expected]
    assert [t.icon for t in got] == [e["icon"] for e in expected]

    for t, e in zip(got, expected):
        assert t.score == pytest.approx(e["score"], abs=FLOAT_TOLERANCE), t.track_id


def run_case(builder, case):
    anchors = {int(k): v for k, v in case["anchors"].items()}
    return builder.build(anchors, case["total"], exclude_tracks=case.get("exclude"))


# --------------------------------------------------------------------------
# Golden: exact generated sequences
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_generated_set_matches_the_golden_sequence(builder, name):
    case = GOLDEN[name]

    got = run_case(builder, case)

    assert_matches_golden(got, case)
    assert len(got) == case["total"]


@pytest.mark.parametrize("name", sorted(GOLDEN_REAL))
def test_generated_set_matches_the_golden_sequence_on_the_real_library(real_builder, name):
    case = GOLDEN_REAL[name]

    got = run_case(real_builder, case)

    assert_matches_golden(got, case)


def test_the_golden_sets_are_not_all_anchors(builder):
    """Guard the guard: a golden file of nothing but anchors would pin the
    placement and none of the generation."""
    generated = [t for t in run_case(builder, GOLDEN["two_anchors"]) if not t.is_anchor]

    assert len(generated) >= 5


# --------------------------------------------------------------------------
# The rendered row, from the golden display names
# --------------------------------------------------------------------------


def test_rendered_set_line_matches_the_golden_strings(builder):
    """The exact string format from set_creator_tab.update_set_listbox."""
    case = GOLDEN["single_anchor_mid"]
    got = run_case(builder, case)

    lines = []
    for track in got:
        score_text = ""
        if not track.is_anchor and track.score > 0:
            score_text = f" ({track.score:.0%} match)"
        lines.append(f"[{track.position:2d}] {track.icon} {track.display_name}{score_text}")

    expected = []
    for e in case["tracks"]:
        score_text = ""
        if not e["is_anchor"] and e["score"] > 0:
            score_text = f" ({e['score']:.0%} match)"
        expected.append(f"[{e['position']:2d}] {e['icon']} {e['display_name']}{score_text}")

    assert lines == expected
    assert lines[2].startswith("[ 3] 🔒 Alva Noto – Xerrox")
    assert lines[0].startswith("[ 1] 🤖 ")
    assert "match)" in lines[0]


def test_unfillable_slots_render_the_unknown_title_suffix(builder):
    """CURRENT BEHAVIOUR. When no candidate survives filtering the slot gets
    artist='No suitable track found', an EMPTY title and track_id='empty_{n}' -
    and SetTrack.display_name (models.py:23) then appends '– (Unknown Title)'
    because the title is falsy. The inventory used to claim a bare trailing en
    dash; it does not render that way."""
    got = run_case(builder, GOLDEN["unfillable"])

    placeholders = [t for t in got if t.track_id.startswith("empty_")]
    assert len(placeholders) == 3
    assert placeholders[0].artist == "No suitable track found"
    assert placeholders[0].title == ""
    assert placeholders[0].score == 0.0
    assert placeholders[0].display_name == "No suitable track found – (Unknown Title)"
    assert not placeholders[0].display_name.endswith("– ")


# --------------------------------------------------------------------------
# Structure and validation
# --------------------------------------------------------------------------


def test_returns_set_tracks_not_recommendations(builder):
    assert all(isinstance(t, SetTrack) for t in builder.build({1: ANCHOR}, 4))


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
    got = builder.build({1: ANCHOR}, 12)

    ids = [t.track_id for t in got if not t.track_id.startswith("empty_")]
    assert len(ids) == len(set(ids))


def test_generated_tracks_carry_the_transition_score(fixture_library, builder):
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
        calculate_transition_score(ANCHOR, second.track_id, ANCHOR_2, fixture_library.emb_ix)
    )
    # ...and position 3 then looks back at 2 and forward to the anchor at 4.
    assert third.score == pytest.approx(
        calculate_transition_score(second.track_id, third.track_id, ANCHOR_2, fixture_library.emb_ix)
    )


def test_transition_scoring_weights_are_eighty_twenty(fixture_library):
    """Pins the weighting itself, independent of any particular set."""
    import numpy as np
    from recommendations.engine import vector_for
    from recommendations.transitions import calculate_transition_score

    a, b, c = fixture_library.ids[0], fixture_library.ids[1], fixture_library.ids[2]
    va, vb, vc = (vector_for(t, fixture_library.emb_ix) for t in (a, b, c))

    assert calculate_transition_score(a, b, c, fixture_library.emb_ix) == pytest.approx(
        0.8 * float(np.dot(va, vb)) + 0.2 * float(np.dot(vb, vc))
    )
    # With no next track it is the plain cosine.
    assert calculate_transition_score(a, b, None, fixture_library.emb_ix) == pytest.approx(
        float(np.dot(va, vb))
    )


def test_per_hop_candidate_pool_is_topk_100_final_top_50(builder, monkeypatch):
    """set_generator.py requests topk=100, final_top=50 for every hop."""
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


def test_reads_the_library_live(fixture_library, builder):
    assert builder.library is fixture_library


# --------------------------------------------------------------------------
# How the build CAPTURES the library - which is not the same as the race
#
# These three tests pin the capture ROUTE: ``build`` goes through
# ``snapshot()`` and never touches the public properties. They do NOT pin the
# build/delete race, and one of them used to be named as though it did. The
# race is still open inside ``snapshot()`` - see inventory §6.6, which records
# it with both of its reproduced outcomes - and closing it means atomic publish
# inside ``LibrarySession``, which is a separate PR.
# --------------------------------------------------------------------------


#: In the generated set for ``{1: ANCHOR}, 5`` (position 4), so removing it from
#: the index mid-build changes the answer rather than being invisible.
DOOMED = "f05"


def _delete_when_meta_ix_is_read(library, monkeypatch, track_id=DOOMED):
    """Make the FIRST read of the PUBLIC ``meta_ix`` property delete ``track_id``.

    WHAT THIS CAN AND CANNOT OBSERVE. It is a probe on the public getter, and
    ``snapshot()`` reads the private ``self._meta_ix`` - so against a build that
    captures a snapshot this getter is never called and the delete never fires.
    That makes the harness a detector of the CAPTURE ROUTE, and nothing more.

    It is not a race harness. To observe the race you have to inject into the
    private reads ``snapshot()`` actually performs, or into ``delete_tracks``'
    own rebind sequence; both were done by hand and both show the window is
    still open (inventory §6.6). Nothing in this file does that, deliberately:
    the fix belongs to ``LibrarySession`` and to another PR.

    Returns the list that records whether the getter fired.
    """
    fired = []
    getter = type(library).meta_ix.fget

    def deleting(self):
        value = getter(self)
        if not fired:
            fired.append(track_id)
            # After the value is captured, so this is the half-applied read and
            # not simply a pre-emptive delete.
            self.delete_tracks([track_id])
        return value

    monkeypatch.setattr(type(library), "meta_ix", property(deleting))
    return fired


def test_the_builder_takes_exactly_one_snapshot_per_build(fixture_library):
    """The capture point, counted. ``ExportService`` pins the same thing for the
    same reason (``test_export_service.py:439``)."""
    real = fixture_library.snapshot
    calls = []
    fixture_library.snapshot = lambda: calls.append(1) or real()

    SetBuilder(fixture_library).build({1: ANCHOR}, 5)

    assert len(calls) == 1, (
        "build reads meta_ix / emb_ix / index as separate properties instead of "
        "capturing one LibrarySnapshot"
    )


def test_the_build_never_reads_the_public_meta_ix_property(
    fixture_library, monkeypatch, isolated_deleted_tracks
):
    """The capture route, from the other side: ``build`` reaches the library
    ONLY through ``snapshot()``.

    ``test_the_builder_takes_exactly_one_snapshot_per_build`` counts the
    captures; this one shows there is no second route alongside them. A build
    that called ``snapshot()`` and ALSO read ``self.library.meta_ix`` would pass
    the counter and fail here.

    WHAT IT DOES NOT PIN, SAID PLAINLY. This test was called
    ``test_a_delete_between_the_property_reads_cannot_be_observed_half_applied``
    and its assertion message said a concurrent delete had been prevented.
    Both were false. The delete is fired from a getter the code under test never
    calls, so the interleaving never occurs - and a harness that cannot make the
    bad thing happen cannot show that it was prevented. ``fired == []`` says
    "the getter was not used", not "the race was won".

    The race is still there, in ``snapshot()``'s own six unlocked reads. Two
    outcomes were reproduced by hand and are recorded in inventory §6.6:
    ``KeyError: 'f05'`` for one half-applied capture, and a silently different
    set for the inverse. Reverting ``build`` to three property reads turns this
    test red, which is exactly and only the discrimination it has.
    """
    undisturbed = [t.track_id for t in SetBuilder(fixture_library).build({1: ANCHOR}, 5)]
    assert DOOMED in undisturbed, "the doomed track is not in the set, so its loss is invisible"

    fired = _delete_when_meta_ix_is_read(fixture_library, monkeypatch)
    got = [t.track_id for t in SetBuilder(fixture_library).build({1: ANCHOR}, 5)]

    assert fired == [], (
        "build read the public meta_ix property, so it is not capturing the "
        "library through snapshot() alone. This says nothing about the "
        "build/delete race, which snapshot() does not close."
    )
    assert got == undisturbed
    assert DOOMED in fixture_library.ids, "the doomed track was deleted after all"


def test_the_interleaving_harness_can_actually_change_the_answer(
    fixture_library, monkeypatch, isolated_deleted_tracks
):
    """Guard the guard - for the capture-route claim, not for the race.

    ``fired == []`` above is only worth something if the harness is live and if
    the route it detects actually matters. Here the three properties are read
    the way ``build`` used to read them, the getter fires, and the answer moves.
    So the test above distinguishes two REAL capture routes rather than two
    spellings of the same one.

    Note what this does NOT license. That the property route can produce a
    different set does not mean the snapshot route cannot; it can, because
    ``snapshot()`` reads the same objects one after another. This is a contrast
    between two routes, not evidence that one of them is safe.
    """
    from recommendations.set_generator import generate_set

    undisturbed = [t.track_id for t in SetBuilder(fixture_library).build({1: ANCHOR}, 5)]
    fired = _delete_when_meta_ix_is_read(fixture_library, monkeypatch)

    # The three separate reads, in the order build() used.
    half_applied = generate_set(
        {1: ANCHOR}, 5, fixture_library.meta_ix, fixture_library.emb_ix, fixture_library.index
    )

    assert fired == [DOOMED], "the harness never fired"
    assert [t.track_id for t in half_applied] != undisturbed, (
        "reading the three properties around a delete produced the same set, so "
        "the capture-route test above cannot distinguish anything"
    )
