import numpy as np
import pytest

from core.index_builder import NumpyCosIndex


def _naive_cosine(vector: np.ndarray, query: np.ndarray) -> float:
    vector = vector.astype("float32")
    query = query.astype("float32")
    vector_norm = np.linalg.norm(vector)
    query_norm = np.linalg.norm(query)
    if vector_norm > 0:
        vector = vector / vector_norm
    if query_norm > 0:
        query = query / query_norm
    return float(np.dot(vector, query))


def test_search_matches_naive_python_cosine_loop() -> None:
    rng = np.random.default_rng(20260818)
    vectors = rng.normal(size=(24, 17))
    query = rng.normal(size=17)
    ids = [f"track-{i}" for i in range(len(vectors))]

    index = NumpyCosIndex(dim=17)
    for track_id, vector in zip(ids, vectors):
        index.add(track_id, vector)

    expected = sorted(
        ((track_id, _naive_cosine(vector, query)) for track_id, vector in zip(ids, vectors)),
        key=lambda item: item[1],
        reverse=True,
    )
    actual = index.search(query, k=len(vectors))

    assert [track_id for track_id, _ in actual] == [
        track_id for track_id, _ in expected
    ]
    np.testing.assert_allclose(
        [score for _, score in actual],
        [score for _, score in expected],
        rtol=1e-6,
        atol=1e-6,
    )


def test_search_returns_scores_in_descending_order() -> None:
    index = NumpyCosIndex(dim=2)
    index.add("opposite", np.array([-1.0, 0.0]))
    index.add("orthogonal", np.array([0.0, 1.0]))
    index.add("same", np.array([1.0, 0.0]))

    results = index.search(np.array([1.0, 0.0]), k=3)

    assert [track_id for track_id, _ in results] == ["same", "orthogonal", "opposite"]
    assert [score for _, score in results] == pytest.approx([1.0, 0.0, -1.0])


def test_search_clamps_k_greater_than_collection_size() -> None:
    index = NumpyCosIndex(dim=2)
    index.add("a", np.array([1.0, 0.0]))
    index.add("b", np.array([0.0, 1.0]))

    results = index.search(np.array([1.0, 0.0]), k=50)

    assert len(results) == 2
    assert {track_id for track_id, _ in results} == {"a", "b"}


def test_search_with_k_equal_to_collection_size() -> None:
    index = NumpyCosIndex(dim=2)
    index.add("a", np.array([1.0, 0.0]))
    index.add("b", np.array([0.0, 1.0]))
    index.add("c", np.array([-1.0, 0.0]))

    results = index.search(np.array([1.0, 0.0]), k=3)

    assert [track_id for track_id, _ in results] == ["a", "b", "c"]


def test_search_empty_index_returns_empty_list() -> None:
    index = NumpyCosIndex(dim=3)

    assert index.search(np.array([1.0, 2.0, 3.0]), k=10) == []


def test_zero_vectors_are_not_divided_by_zero() -> None:
    index = NumpyCosIndex(dim=3)
    index.add("zero", np.zeros(3))
    index.add("nonzero", np.array([1.0, 0.0, 0.0]))

    zero_query_results = index.search(np.zeros(3), k=2)
    nonzero_query_results = index.search(np.array([1.0, 0.0, 0.0]), k=2)

    assert len(zero_query_results) == 2
    assert all(score == pytest.approx(0.0) for _, score in zero_query_results)
    assert dict(nonzero_query_results)["zero"] == pytest.approx(0.0)
    assert np.isfinite(index.matrix).all()


def test_self_match_scores_approximately_one() -> None:
    vector = np.array([2.5, -4.0, 1.25, 8.0])
    index = NumpyCosIndex(dim=4)
    index.add("self", vector)

    result = index.search(vector, k=1)

    assert result == [("self", pytest.approx(1.0, abs=1e-6))]


def test_add_then_search_round_trips_track_ids() -> None:
    index = NumpyCosIndex(dim=3)
    expected_ids = ["alpha", "bravo", "charlie"]
    for track_id, vector in zip(expected_ids, np.eye(3)):
        index.add(track_id, vector)

    results = index.search(np.array([0.9, 0.3, 0.1]), k=3)

    assert index.ids == expected_ids
    assert [track_id for track_id, _ in results] == expected_ids
    assert index.matrix.dtype == np.float32
