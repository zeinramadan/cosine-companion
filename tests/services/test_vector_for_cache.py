"""``vector_for`` serves precomputed vectors; these pin what that must not change.

``recommendations.engine.vector_for`` no longer rebuilds one vector out of pandas
per call - it normalises the whole embeddings frame once and serves rows from it.
That is a pure performance change, so the thing worth testing is that nothing
about the *result* moved.

**Why the reference implementation below is a copy-paste and not an import.**
``REFERENCE_vector_for`` is the verbatim pre-cache body of ``vector_for`` from
c5bf32e. If it imported ``engine._normalise`` or ``engine._vector_from_frame``
instead, a mutation to the shared normalisation would move the expectation and
the assertion together and every test here would still pass - the tautology
``tests/services/golden/README.md`` was written about. Held separately, it stays
an independent oracle.

Equality is asserted **bit-for-bit** (``np.array_equal`` over float32, and a
sha256 of the raw bytes), not within a tolerance. A tolerance would let a
reordered computation through, and a reordering that flips which candidate wins
a transition is a behaviour change, not noise.
"""

import hashlib

import numpy as np
import pandas as pd
import pytest

from recommendations.engine import vector_for


def REFERENCE_vector_for(track_id, emb_ix):
    """The body of ``vector_for`` exactly as it stood before the cache landed."""
    if track_id not in emb_ix.index:
        return None
    row = emb_ix.loc[track_id]
    vcols = [c for c in emb_ix.columns if c.startswith("v")]
    v = row[vcols].to_numpy().astype("float32")
    v = v / (np.linalg.norm(v) + 1e-9)
    return v


def sha_of(vectors):
    h = hashlib.sha256()
    for v in vectors:
        h.update(np.ascontiguousarray(v, dtype=np.float32).tobytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# The whole library, bit for bit
# ---------------------------------------------------------------------------


def test_every_vector_is_bit_identical_to_the_pre_cache_implementation(fixture_library):
    emb_ix = fixture_library.emb_ix

    for track_id in fixture_library.ids:
        got = vector_for(track_id, emb_ix)
        expected = REFERENCE_vector_for(track_id, emb_ix)
        assert got.dtype == expected.dtype == np.float32
        assert np.array_equal(got, expected), (
            f"{track_id}: max abs deviation "
            f"{np.abs(got.astype(np.float64) - expected.astype(np.float64)).max():.3e}"
        )


def test_the_whole_library_hashes_to_the_pre_cache_bytes(fixture_library):
    """One digest over every vector: catches a single flipped bit anywhere."""
    emb_ix = fixture_library.emb_ix
    ids = fixture_library.ids

    assert sha_of(vector_for(t, emb_ix) for t in ids) == sha_of(
        REFERENCE_vector_for(t, emb_ix) for t in ids
    )


def test_every_real_library_vector_is_bit_identical(real_library):
    """The same proof on the maintainer's own library. Skips when data/ is absent."""
    emb_ix = real_library.emb_ix

    assert sha_of(vector_for(t, emb_ix) for t in real_library.ids) == sha_of(
        REFERENCE_vector_for(t, emb_ix) for t in real_library.ids
    )


# ---------------------------------------------------------------------------
# The properties a cache is most likely to break
# ---------------------------------------------------------------------------


def test_the_vector_is_normalised(fixture_library):
    """Serving the raw stored row instead of the normalised one is the obvious
    shortcut, and the fixture vectors are small integers with norms far from 1,
    so it would show up here immediately."""
    for track_id in fixture_library.ids:
        v = vector_for(track_id, fixture_library.emb_ix)
        assert np.linalg.norm(v.astype(np.float64)) == pytest.approx(1.0, abs=1e-6)


def test_each_track_gets_its_own_row(fixture_library):
    """An off-by-one in the id->row mapping still returns a plausible, normalised
    vector, so identity has to be pinned against the raw stored values rather
    than against 'some vector came back'."""
    emb_ix = fixture_library.emb_ix
    vcols = [c for c in emb_ix.columns if c.startswith("v")]

    for track_id in fixture_library.ids:
        raw = emb_ix.loc[track_id, vcols].to_numpy().astype("float32")
        got = vector_for(track_id, emb_ix)
        # Same direction as this track's own raw row, and no other track's.
        assert float(np.dot(got, raw / np.linalg.norm(raw))) == pytest.approx(1.0, abs=1e-6)


def test_an_unknown_track_id_returns_none(fixture_library):
    assert vector_for("no-such-track", fixture_library.emb_ix) is None


def test_the_caller_gets_an_independent_writable_array(fixture_library):
    """A cache that hands out views into its own matrix lets one caller corrupt
    every later lookup. ``vector_for`` always returned a fresh array; it still
    must."""
    emb_ix = fixture_library.emb_ix
    track_id = fixture_library.ids[0]

    first = vector_for(track_id, emb_ix)
    assert first.flags.writeable
    before = first.copy()

    first[:] = 999.0
    second = vector_for(track_id, emb_ix)

    assert np.array_equal(second, before), "a mutated result leaked back into the cache"
    assert second is not first


def test_two_libraries_do_not_share_vectors(fixture_library, tmp_path):
    """The cache is keyed on the frame, not on the track_id. Two frames that use
    the same ids must each return their own values."""
    emb_ix = fixture_library.emb_ix
    other = emb_ix * 0.0
    other.iloc[:, 0] = 1.0

    from_original = vector_for(fixture_library.ids[0], emb_ix)
    from_other = vector_for(fixture_library.ids[0], other)

    assert np.array_equal(from_other, REFERENCE_vector_for(fixture_library.ids[0], other))
    assert not np.array_equal(from_other, from_original)
    # ...and going back to the first frame still gives the first frame's answer.
    assert np.array_equal(vector_for(fixture_library.ids[0], emb_ix), from_original)


def test_a_rebound_frame_is_not_served_from_the_old_one(fixture_library, isolated_deleted_tracks):
    """``LibrarySession.delete_tracks`` rebinds ``emb_ix`` to a new frame. The
    surviving tracks must come from the new frame, and the deleted one must be
    gone rather than lingering in a stale table."""
    keep, drop = fixture_library.ids[0], fixture_library.ids[1]
    before = vector_for(keep, fixture_library.emb_ix)

    fixture_library.delete_tracks([drop])

    assert vector_for(drop, fixture_library.emb_ix) is None
    assert np.array_equal(vector_for(keep, fixture_library.emb_ix), before)


def test_a_frame_with_duplicate_track_ids_behaves_as_before(fixture_library):
    """``load_all`` rejects duplicate ids, so this shape only reaches the engine
    from hand-built frames. It must not be silently reinterpreted by the cache:
    whatever the original per-row code did, that is what still happens."""
    emb_ix = fixture_library.emb_ix
    duplicated = pd.concat([emb_ix, emb_ix.iloc[[0]]])
    track_id = fixture_library.ids[0]

    got = vector_for(track_id, duplicated)
    expected = REFERENCE_vector_for(track_id, duplicated)

    assert np.array_equal(np.asarray(got), np.asarray(expected))
    assert vector_for("no-such-track", duplicated) is None


# ---------------------------------------------------------------------------
# The scores built on top of the vectors
# ---------------------------------------------------------------------------


def test_transition_scores_are_bit_identical_to_the_pre_cache_values(fixture_library):
    """``calculate_transition_score`` is 0.8/0.2 over two dot products of these
    vectors; a change of one ulp in a vector can flip which candidate wins a hop,
    so this compares exactly rather than approximately."""
    from recommendations.transitions import calculate_transition_score

    emb_ix = fixture_library.emb_ix
    ids = fixture_library.ids

    for i, a in enumerate(ids):
        b = ids[(i + 1) % len(ids)]
        c = ids[(i + 5) % len(ids)]
        va, vb, vc = (REFERENCE_vector_for(t, emb_ix) for t in (a, b, c))

        assert calculate_transition_score(a, b, c, emb_ix) == (
            0.8 * float(np.dot(va, vb)) + 0.2 * float(np.dot(vb, vc))
        )
        assert calculate_transition_score(a, b, None, emb_ix) == float(np.dot(va, vb))


def test_a_missing_track_still_scores_zero(fixture_library):
    from recommendations.transitions import calculate_transition_score

    emb_ix = fixture_library.emb_ix
    a, b = fixture_library.ids[0], fixture_library.ids[1]

    assert calculate_transition_score("nope", b, None, emb_ix) == 0.0
    assert calculate_transition_score(a, "nope", None, emb_ix) == 0.0
    # An unknown *next* track drops the forward term rather than zeroing.
    assert calculate_transition_score(a, b, "nope", emb_ix) == calculate_transition_score(
        a, b, None, emb_ix
    )
