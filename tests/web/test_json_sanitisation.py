"""Everything the services hand back has to survive json.dumps. Most of it does not.

``LibrarySession.get_track`` builds its dict from a pandas row, so the values
are ``numpy.float64``, ``numpy.int64`` and - for a track with no BPM -
``float('nan')``. ``json.dumps`` refuses the numpy scalars outright, and it
serialises NaN as the bare literal ``NaN``, which is **not valid JSON**:
``JSON.parse`` in WKWebView throws on it, and the failure surfaces in the
frontend as a blank list rather than as an error naming the field.

So every value that leaves the API goes through ``_jsonable`` first, and the
server serialises with ``allow_nan=False`` as a second line of defence.
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

from web.api import _jsonable


def dumps(value):
    """Serialise exactly as the server does - NaN and Infinity are errors."""
    return json.dumps(value, allow_nan=False)


# -- the values that break json.dumps --------------------------------------


def test_json_really_does_reject_the_values_this_helper_exists_for():
    """Guard the guard. If json.dumps stopped caring, _jsonable would be dead
    weight and these tests would pass whatever it did.

    Which numpy scalars it rejects is not uniform, and the exception is the
    dangerous one: ``np.float64`` **is** a subclass of ``float``, so it
    serialises silently - and so does a ``np.float64`` NaN, straight out to the
    invalid literal ``NaN``. That is precisely the value a track with no BPM
    has, coming out of a float64 parquet column. The types that raise are the
    safe failures; the type that does not raise is the bug.
    """
    for rejected in (np.float32(0.5), np.int64(3), np.int32(-7), np.bool_(True)):
        with pytest.raises(TypeError):
            dumps(rejected)

    with pytest.raises(ValueError):
        dumps(float("nan"))

    # The silent one: a float64 NaN is accepted by a default json.dumps and
    # emitted as a literal that JSON.parse refuses.
    assert isinstance(np.float64(1.5), float)
    assert json.dumps(np.float64("nan")) == "NaN"
    assert json.dumps(float("nan")) == "NaN"


@pytest.mark.parametrize(
    "value, expected",
    [
        (np.float64(1.5), 1.5),
        (np.float32(0.5), 0.5),
        (np.int64(3), 3),
        (np.int32(-7), -7),
        (np.bool_(True), True),
        (np.str_("x"), "x"),
    ],
)
def test_a_numpy_scalar_becomes_the_python_scalar(value, expected):
    converted = _jsonable(value)

    assert converted == expected
    assert type(converted) in (float, int, bool, str)
    assert dumps(converted) is not None


@pytest.mark.parametrize(
    "missing",
    [
        float("nan"),
        np.float64("nan"),
        None,
        pd.NaT,
        pd.NA,
        # numpy has its own not-a-time, and it is NOT pd.NaT. `pd.NaT is
        # np.datetime64("NaT")` is False, so the identity test above never saw
        # these two and each failed differently:
        #   np.datetime64("NaT")  fell through to str() and serialised as the
        #                         four-character string "NaT", which the
        #                         frontend renders as a date;
        #   np.timedelta64("NaT") is an np.signedinteger SUBCLASS, so it was
        #                         caught by the integer branch, where int()
        #                         raises TypeError and takes the endpoint down
        #                         with a 500.
        np.datetime64("NaT"),
        np.timedelta64("NaT"),
    ],
)
def test_every_flavour_of_missing_becomes_null(missing):
    assert _jsonable(missing) is None
    assert dumps(_jsonable(missing)) == "null"


@pytest.mark.parametrize(
    "value, expected",
    [
        (np.datetime64("2020-01-02T03:04:05"), "2020-01-02T03:04:05"),
        (np.datetime64("2020-01-02"), "2020-01-02"),
        (np.timedelta64(5, "D"), "5 days"),
        (np.timedelta64(90, "s"), "90 seconds"),
    ],
)
def test_a_real_numpy_temporal_scalar_survives_as_text(value, expected):
    """The non-NaT half of the same hole.

    ``np.timedelta64(5, "D")`` raised TypeError too - not only the NaT one -
    because the integer branch caught every timedelta64 and ``int()`` on one
    returns a ``datetime.timedelta``. Text rather than a number because the
    unit is part of the value and a bare integer would silently drop it.
    """
    converted = _jsonable(value)

    assert converted == expected
    assert dumps(converted)


def test_a_frame_of_dates_round_trips_through_the_sanitiser():
    """The realistic route in: a metadata column pandas has typed as
    datetime64, holding a gap. Reading a row out of one yields the numpy
    scalars above, not the pandas ones."""
    frame = pd.DataFrame({"added": pd.to_datetime(["2020-01-02", None])})
    values = frame["added"].to_numpy()

    assert dumps(_jsonable(list(values))) == '["2020-01-02T00:00:00.000000000", null]'


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), np.float64("inf")])
def test_a_non_finite_number_becomes_null_rather_than_invalid_json(value):
    """json.dumps writes Infinity, which JSON.parse rejects for the same reason
    it rejects NaN."""
    assert _jsonable(value) is None


def test_a_real_number_is_not_mistaken_for_missing():
    for value in (0.0, -0.0, 0, False, ""):
        assert _jsonable(value) is not None or value is None, value

    assert _jsonable(0.0) == 0.0
    assert _jsonable(0) == 0
    assert _jsonable(False) is False
    assert _jsonable("") == ""


# -- containers ------------------------------------------------------------


def test_a_dict_is_sanitised_all_the_way_down():
    converted = _jsonable(
        {
            "bpm": np.float64("nan"),
            "nested": {"cosine": np.float32(0.25), "ids": np.array([1, 2])},
            "rows": [np.int64(1), float("nan")],
        }
    )

    assert converted == {
        "bpm": None,
        "nested": {"cosine": 0.25, "ids": [1, 2]},
        "rows": [1, None],
    }
    assert dumps(converted)


def test_a_numpy_array_becomes_a_list():
    assert _jsonable(np.array([1.5, 2.5], dtype="float32")) == [1.5, 2.5]


def test_a_tuple_becomes_a_list_because_json_has_no_tuples():
    assert _jsonable((1, np.float64(2.0))) == [1, 2.0]


def test_a_dict_key_that_is_not_a_string_is_stringified():
    """Parquet column names are strings, but a row index need not be, and
    json.dumps silently coerces int keys while refusing numpy ones."""
    assert _jsonable({np.int64(3): "x"}) == {"3": "x"}


# -- pandas-shaped values --------------------------------------------------


def test_a_pandas_row_survives_the_round_trip():
    frame = pd.DataFrame(
        [{"track_id": "t1", "artist": "Björk", "bpm": float("nan"), "key": "4A"}]
    ).set_index("track_id")
    row = frame.loc["t1"].to_dict()

    converted = _jsonable(row)

    assert converted == {"artist": "Björk", "bpm": None, "key": "4A"}
    assert json.loads(dumps(converted))["artist"] == "Björk"


def test_a_timestamp_becomes_an_iso_string():
    converted = _jsonable(pd.Timestamp("2026-08-19T10:30:00"))

    assert converted == "2026-08-19T10:30:00"


def test_an_unexpected_object_degrades_to_its_string_form():
    """A 500 because some future column holds an object json cannot name is a
    worse outcome than a stringified value. The fallback is deliberate and is
    the last branch, so nothing above it is reached by accident."""

    class Opaque:
        def __str__(self):
            return "opaque"

    assert _jsonable(Opaque()) == "opaque"


def test_a_path_becomes_its_string_form():
    from pathlib import Path

    assert _jsonable(Path("/tmp/x.mp3")) == "/tmp/x.mp3"


def test_bytes_become_text():
    assert _jsonable("café".encode("utf-8")) == "café"


def test_the_helper_does_not_mutate_what_it_is_given():
    """get_track's dict is built from the live library; sanitising in place
    would corrupt it for every later reader."""
    original = {"bpm": float("nan")}

    _jsonable(original)

    assert math.isnan(original["bpm"])
