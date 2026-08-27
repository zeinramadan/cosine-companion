"""Contract for the one track search exposed by the service layer."""

from recommendations.search import search_tracks


def ids(library, query, limit=20):
    return [row["track_id"] for row in library.search_tracks(query, limit=limit)]


def test_service_matches_the_shared_search_implementation(fixture_library):
    for query in ["a", "de", "s.", "no such artist anywhere"]:
        assert fixture_library.search_tracks(query, limit=20) == search_tracks(
            query, fixture_library.meta_ix, limit=20
        )


def test_search_returns_exactly_these_ids(fixture_library):
    assert ids(fixture_library, "a", limit=100) == [
        "f01",
        "f02",
        "f03",
        "f04",
        "f05",
        "f07",
        "f09",
        "f11",
        "f12",
    ]
    assert ids(fixture_library, "de", limit=100) == ["f02", "f05", "f11", "f12"]
    assert ids(fixture_library, "xerrox", limit=100) == ["f01"]
    assert ids(fixture_library, "ROTOR", limit=100) == ["f09"]
    assert ids(fixture_library, "no such thing", limit=100) == []


def test_search_returns_nothing_for_blank_or_whitespace(fixture_library):
    assert fixture_library.search_tracks("", limit=100) == []
    assert fixture_library.search_tracks("   ", limit=100) == []
    assert fixture_library.search_tracks("\t\n", limit=100) == []


def test_search_treats_the_query_literally(fixture_library):
    assert ids(fixture_library, "s.", limit=100) == ["f08"]


def test_search_does_not_search_album_or_key(fixture_library):
    assert ids(fixture_library, "solens", limit=100) == []
    assert ids(fixture_library, "8a", limit=100) == []


def test_search_matches_joined_artist_and_title(fixture_library):
    assert ids(fixture_library, "huerco s. plucked", limit=100) == ["f08"]


def test_search_honours_the_limit(fixture_library):
    assert ids(fixture_library, "a", limit=3) == ["f01", "f02", "f03"]
    assert len(fixture_library.search_tracks("a")) == 9


def test_search_defaults_to_twenty(fixture_library):
    import inspect

    assert inspect.signature(search_tracks).parameters["limit"].default == 20
    assert (
        inspect.signature(type(fixture_library).search_tracks)
        .parameters["limit"]
        .default
        == 20
    )


def test_search_result_shape_and_en_dash(fixture_library):
    result = fixture_library.search_tracks("xerrox", limit=20)[0]

    assert set(result) == {"track_id", "artist", "title", "display_name"}
    assert result["display_name"] == "Alva Noto – Xerrox"


def test_search_preserves_parquet_order(fixture_library):
    found = ids(fixture_library, "a", limit=100)
    assert found == [
        track_id
        for track_id in list(fixture_library.meta["track_id"].values)
        if track_id in found
    ]


def test_library_session_exposes_the_shared_search(fixture_library):
    import inspect

    from services import library_session

    assert library_session.search_tracks is search_tracks
    source = inspect.getsource(type(fixture_library).search_tracks)
    assert "search_tracks(query, self._meta_ix, limit=limit)" in source
