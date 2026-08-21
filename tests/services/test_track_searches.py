"""Exact characterisation of all THREE track searches.

The plan named two; there are three, and none is used by more than one kind of
caller. They must not be unified in this PR, so each is pinned separately:

| | **A** `recommendations/search.py` | **B** `pick_current` | **C** `filter_library` |
|---|---|---|---|
| Callers | `AddAnchorDialog`, `TrackSelectorDialog` | Explore `Set Current Track` | Library search box |
| Exposed by | `LibrarySession.search_tracks` | nothing | nothing |
| Blank query | `[]` | everything | everything |
| Match | literal substring | **regex** (`str.contains`) | literal substring |
| Fields | artist, title, `"{artist} {title}"` | artist, title | artist, title, **album**, **key** |
| Limit | caller's `limit` | `.head(50)` | none |
| Order | parquet | parquet | **artist/title** |

B and C live inside Tkinter mixin methods that cannot be called without a
running Tk, so the tests below re-state their expressions - and then assert that
the re-statement still matches the source, so the mirror cannot rot silently.
An earlier version of these tests modelled B with ``.head(100)`` when the UI
uses ``.head(50)``; that is the kind of drift the source check now catches.
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from recommendations.search import search_tracks

UI = Path(__file__).resolve().parents[2] / "src" / "ui"

# ---------------------------------------------------------------------------
# The mirrors, copied from the two UI call sites
# ---------------------------------------------------------------------------

PICK_CURRENT_SOURCE = '''
    meta = self.library.meta
    m = meta[(meta["artist"].str.lower().str.contains(q, na=False)) | (meta["title"].str.lower().str.contains(q, na=False))].head(50)
'''

FILTER_LIBRARY_SOURCE = '''
    self.filtered_library_tracks = [
        track for track in self.library_tracks
        if (query in track["artist"].lower() or
            query in track["title"].lower() or
            query in track["album"].lower() or
            query in track["key"].lower())
    ]
'''


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def search_b(meta, query):
    """Implementation B, mirroring recommendations_tab.pick_current."""
    q = query.lower()
    return meta[
        (meta["artist"].str.lower().str.contains(q, na=False))
        | (meta["title"].str.lower().str.contains(q, na=False))
    ].head(50)


def regex_error_type(meta):
    """What THIS pandas raises when ``str.contains`` is handed a bad regex.

    Measured, not named. pandas 2 evaluates the expression with Python's
    ``re`` and raises ``re.error``; pandas 3 stores the column as arrow-backed
    ``str`` and the same call raises ``pyarrow.lib.ArrowInvalid``. The two
    share no base class below ``Exception``, and widening the assertion to
    ``pytest.raises(Exception)`` would let a typo in the test pass as readily
    as the behaviour it is meant to pin - so the type is taken from the same
    expression, on the same frame, at the moment of the test.

    Guard the guard: if ``str.contains`` ever stops raising and starts
    returning an empty result, the test below would pass for the wrong reason
    - so a probe that does NOT raise is an error here, not a shrug.
    """
    try:
        meta["artist"].str.lower().str.contains("(", na=False)
    except Exception as exc:  # noqa: BLE001 - the type IS the measurement
        return type(exc)
    raise AssertionError(
        "str.contains accepted an unbalanced '(' instead of raising. B no "
        "longer propagates a regex error, which is a change in what the "
        "Explore 'Set Current Track' prompt does with bad input, not a "
        "change in what this test should assert."
    )


def library_rows(meta_ix):
    """What library_tab.refresh_library builds, in the order it builds it."""
    rows = [
        {
            "track_id": track_id,
            "artist": row.get("artist", ""),
            "title": row.get("title", ""),
            "album": row.get("album", ""),
            "key": row.get("key", ""),
        }
        for track_id, row in meta_ix.iterrows()
    ]
    rows.sort(key=lambda x: (x["artist"].lower(), x["title"].lower()))
    return rows


def search_c(rows, query):
    """Implementation C, mirroring library_tab.filter_library."""
    query = query.lower()
    if not query:
        return list(rows)
    return [
        track for track in rows
        if (query in track["artist"].lower() or
            query in track["title"].lower() or
            query in track["album"].lower() or
            query in track["key"].lower())
    ]


# ---------------------------------------------------------------------------
# The mirrors must still match the source
# ---------------------------------------------------------------------------


def test_implementation_b_mirror_matches_the_ui_source():
    source = squash((UI / "recommendations_tab.py").read_text(encoding="utf-8"))

    assert squash(PICK_CURRENT_SOURCE) in source
    assert ".head(50)" in source and ".head(100)" not in source


def test_implementation_c_mirror_matches_the_ui_source():
    source = squash((UI / "library_tab.py").read_text(encoding="utf-8"))

    assert squash(FILTER_LIBRARY_SOURCE) in source


def test_the_library_row_builder_mirror_matches_the_ui_source():
    source = squash((UI / "library_tab.py").read_text(encoding="utf-8"))

    assert squash('self.library_tracks.sort(key=lambda x: (x["artist"].lower(), x["title"].lower()))') in source


# ---------------------------------------------------------------------------
# A - recommendations/search.py, the one LibrarySession exposes
# ---------------------------------------------------------------------------


def ids_a(library, query, limit=20):
    return [r["track_id"] for r in library.search_tracks(query, limit=limit)]


def test_a_matches_the_implementation_the_ui_dialogs_call(fixture_library):
    """AddAnchorDialog and TrackSelectorDialog both call
    recommendations.search.search_tracks; LibrarySession exposes THAT one."""
    for query in ["a", "de", "s.", "no such artist anywhere"]:
        assert fixture_library.search_tracks(query, limit=20) == search_tracks(
            query, fixture_library.meta_ix, limit=20
        )


def test_a_returns_exactly_these_ids(fixture_library):
    assert ids_a(fixture_library, "a", limit=100) == [
        "f01", "f02", "f03", "f04", "f05", "f07", "f09", "f11", "f12"
    ]
    assert ids_a(fixture_library, "de", limit=100) == ["f02", "f05", "f11", "f12"]
    assert ids_a(fixture_library, "xerrox", limit=100) == ["f01"]
    assert ids_a(fixture_library, "ROTOR", limit=100) == ["f09"]  # case-insensitive
    assert ids_a(fixture_library, "no such thing", limit=100) == []


def test_a_returns_nothing_for_a_blank_or_whitespace_query(fixture_library):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. This is why AddAnchorDialog and
    TrackSelectorDialog both open showing an EMPTY list despite their
    '# Initialize with all tracks' intent. Inventory defect #9."""
    assert fixture_library.search_tracks("", limit=100) == []
    assert fixture_library.search_tracks("   ", limit=100) == []
    assert fixture_library.search_tracks("\t\n", limit=100) == []


def test_a_treats_the_query_literally(fixture_library):
    """'.' is a literal here and a regex metacharacter in B."""
    assert ids_a(fixture_library, "s.", limit=100) == ["f08"]


def test_a_does_not_search_album_or_key(fixture_library):
    assert ids_a(fixture_library, "solens", limit=100) == []   # an album
    assert ids_a(fixture_library, "8a", limit=100) == []       # a key


def test_a_matches_the_joined_artist_and_title(fixture_library):
    """The third clause: 'huerco s. plucked' spans both fields."""
    assert ids_a(fixture_library, "huerco s. plucked", limit=100) == ["f08"]


def test_a_honours_the_limit_by_breaking_early(fixture_library):
    assert ids_a(fixture_library, "a", limit=3) == ["f01", "f02", "f03"]
    assert len(fixture_library.search_tracks("a")) == 9  # fewer than the default 20


def test_a_defaults_to_a_limit_of_twenty(fixture_library):
    import inspect

    assert inspect.signature(search_tracks).parameters["limit"].default == 20
    assert inspect.signature(type(fixture_library).search_tracks).parameters["limit"].default == 20


def test_a_result_shape_and_en_dash(fixture_library):
    result = fixture_library.search_tracks("xerrox", limit=20)[0]

    assert set(result) == {"track_id", "artist", "title", "display_name"}
    assert result["display_name"] == "Alva Noto – Xerrox"


def test_a_returns_results_in_parquet_order(fixture_library):
    assert ids_a(fixture_library, "a", limit=100) == [
        t for t in list(fixture_library.meta["track_id"].values)
        if t in ids_a(fixture_library, "a", limit=100)
    ]


# ---------------------------------------------------------------------------
# B - pick_current, the regex one
# ---------------------------------------------------------------------------


def ids_b(library, query):
    return list(search_b(library.meta, query)["track_id"].values)


def test_b_returns_exactly_these_ids(fixture_library):
    assert ids_b(fixture_library, "a") == [
        "f01", "f02", "f03", "f04", "f05", "f07", "f09", "f11", "f12"
    ]
    assert ids_b(fixture_library, "xerrox") == ["f01"]
    assert ids_b(fixture_library, "ROTOR") == ["f09"]
    assert ids_b(fixture_library, "no such thing") == []


def test_b_reads_the_query_as_a_regular_expression(fixture_library):
    """THE divergence from A: '.' matches any character. A returns one row for
    's.', B returns three."""
    assert ids_b(fixture_library, "s.") == ["f07", "f08", "f09"]
    assert ids_a(fixture_library, "s.", limit=100) == ["f08"]


def test_b_propagates_a_regex_error_out_of_the_tk_callback(fixture_library):
    """An unbalanced '(' raises, rather than returning an empty result.
    pick_current does not catch it, so it surfaces as a Tk traceback. Current
    behaviour, and still current under pandas 3 - only the CLASS moved.

    pandas 2 raises ``re.error`` from Python's engine; pandas 3 evaluates the
    same expression through pyarrow and raises ``ArrowInvalid``. The user-
    visible behaviour is identical either way (an uncaught exception out of
    the Tk callback), so the class is measured rather than written down. What
    is pinned is that B propagates at all: wrap the expression in a
    try/except returning an empty frame and this test fails."""
    with pytest.raises(regex_error_type(fixture_library.meta)):
        ids_b(fixture_library, "(")


def test_b_returns_everything_for_a_blank_query(fixture_library):
    """pick_current never actually reaches this - askstring returning '' is
    caught by `if not query: return` first - but the expression itself matches
    every row, which is the opposite of A."""
    assert ids_b(fixture_library, "") == list(fixture_library.meta["track_id"].values)


def test_b_does_not_strip_whitespace(fixture_library):
    assert ids_b(fixture_library, "   ") == []
    assert ids_b(fixture_library, " ") == [
        t["track_id"] for t in library_rows(fixture_library.meta_ix)
        if " " in t["artist"].lower() or " " in t["title"].lower()
    ]


def test_b_does_not_search_album_or_key(fixture_library):
    assert ids_b(fixture_library, "solens") == []
    assert ids_b(fixture_library, "8a") == []


def test_b_caps_at_fifty_rows_not_one_hundred(real_library):
    """The cap the earlier test got wrong. Needs more than 50 matches, so it
    runs against the real library."""
    assert len(search_b(real_library.meta, "a")) == 50
    assert len(search_b(real_library.meta, "e")) == 50


def test_b_returns_a_dataframe_slice_not_dicts(fixture_library):
    m = search_b(fixture_library.meta, "a")

    assert isinstance(m, pd.DataFrame)
    assert list(m[["artist", "title", "track_id"]].columns) == ["artist", "title", "track_id"]


# ---------------------------------------------------------------------------
# C - filter_library, the album/key one
# ---------------------------------------------------------------------------


def ids_c(library, query):
    return [t["track_id"] for t in search_c(library_rows(library.meta_ix), query)]


def test_c_returns_exactly_these_ids(fixture_library):
    assert ids_c(fixture_library, "a") == [
        "f01", "f02", "f03", "f04", "f05", "f06", "f07", "f09", "f10", "f11", "f12"
    ]
    assert ids_c(fixture_library, "xerrox") == ["f01"]
    assert ids_c(fixture_library, "ROTOR") == ["f09"]
    assert ids_c(fixture_library, "no such thing") == []


def test_c_searches_album_and_key_which_neither_other_does(fixture_library):
    assert ids_c(fixture_library, "solens") == ["f11"]          # album
    assert ids_c(fixture_library, "8a") == ["f01", "f04", "f07", "f12"]  # key
    assert ids_a(fixture_library, "solens", limit=100) == []
    assert ids_b(fixture_library, "solens") == []


def test_c_shows_everything_for_a_blank_query(fixture_library):
    """The opposite of A, and the reason the Library tab opens populated while
    the two selector dialogs open empty."""
    assert ids_c(fixture_library, "") == [t["track_id"] for t in library_rows(fixture_library.meta_ix)]
    assert len(ids_c(fixture_library, "")) == 12


def test_c_does_not_strip_whitespace(fixture_library):
    """A lone space matches only rows containing a space; it is NOT treated as
    an empty query."""
    got = ids_c(fixture_library, " ")

    assert got != ids_c(fixture_library, "")
    # Every row whose artist, title, album OR key contains a space - which the
    # album field makes most of them. f05 and f06 have a space in none.
    assert got == ["f01", "f02", "f03", "f04", "f07", "f08", "f09", "f10", "f11", "f12"]
    assert "f05" not in got and "f06" not in got


def test_c_treats_the_query_literally(fixture_library):
    assert ids_c(fixture_library, "s.") == ["f08"]
    assert ids_c(fixture_library, "(") == []  # no regex, so no error


def test_c_has_no_limit(real_library):
    """A returns at most `limit`, B at most 50, C returns everything."""
    rows = library_rows(real_library.meta_ix)

    assert len(search_c(rows, "a")) > 50


def test_c_orders_by_artist_then_title_not_parquet_order(tmp_path):
    """C reads a list that refresh_library pre-sorted by (artist, title). The
    fixture library happens to be stored alphabetically, so this uses a small
    library written deliberately OUT of that order."""
    data = tmp_path / "data"
    data.mkdir()
    rows = [
        ("s1", "Zoe", "beta", "Album Z", "1A"),
        ("s2", "adam", "gamma", "Album A", "2A"),
        ("s3", "Zoe", "Alpha", "Album Z", "3A"),
        ("s4", "Mia", "delta", "Album M", "4A"),
    ]
    meta = pd.DataFrame([
        {"track_id": t, "path": "", "artist": a, "title": ti, "album": al,
         "bpm": 128.0, "key": k, "path_local": f"/tmp/{t}.mp3"}
        for t, a, ti, al, k in rows
    ])
    vectors = np.eye(4, dtype="float32")
    emb = pd.concat(
        [pd.DataFrame({"track_id": [r[0] for r in rows]}),
         pd.DataFrame(vectors, columns=[f"v{i}" for i in range(4)])],
        axis=1,
    )
    meta.to_parquet(data / "meta.parquet", index=False)
    emb.to_parquet(data / "embeddings.parquet", index=False)
    np.save(data / "index.npy", vectors)
    (data / "ids.json").write_text(json.dumps([r[0] for r in rows]))

    from services.library_session import LibrarySession

    library = LibrarySession.load(data)

    # Case-insensitive artist sort, then title: adam, Mia, Zoe/Alpha, Zoe/beta.
    assert ids_c(library, "") == ["s2", "s4", "s3", "s1"]
    assert list(library.meta["track_id"].values) == ["s1", "s2", "s3", "s4"]
    # A and B keep parquet order for the same query.
    assert ids_b(library, "a") == ["s1", "s2", "s3", "s4"]


# ---------------------------------------------------------------------------
# The three disagree, and that is the point
# ---------------------------------------------------------------------------


def test_the_three_implementations_disagree(fixture_library):
    assert ids_a(fixture_library, "") == []
    assert ids_b(fixture_library, "") != []
    assert ids_c(fixture_library, "") != []

    assert ids_a(fixture_library, "s.") != ids_b(fixture_library, "s.")
    assert ids_a(fixture_library, "8a") != ids_c(fixture_library, "8a")


def test_library_session_exposes_a_and_only_a(fixture_library):
    import inspect

    from services import library_session

    assert library_session.search_tracks is search_tracks
    source = inspect.getsource(type(fixture_library).search_tracks)
    assert "search_tracks(query, self._meta_ix, limit=limit)" in source
