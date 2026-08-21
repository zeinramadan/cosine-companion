"""The Add Anchor dialog's row format, checked against BOTH implementations.

Why this file exists
--------------------
Inventory :954 said the dialog's rows render ``{artist} – {title}``, and this
branch's dialog does not: it drops a blank field along with the separator, the
way the ⌘K palette and the Explore rows already do. That is a deliberate
divergence and §6.6 now declares it, with a specimen table saying exactly what
each implementation produces for three tracks.

A declared divergence is only worth the paper if both halves of it are true.
``tests/web/js/anchor_dialog.test.mjs`` reads the table's "this dialog's row"
column and drives the shipped module against it, so the WEB half cannot drift
from the declaration without the suite going red.

This file does the other half. The table's claim about *Tkinter* is a claim
about ``recommendations.search.search_tracks`` - the implementation the Tk
dialog inserts verbatim (``ui/dialogs.py:90``) - and nothing was checking it.
An inventory table that says "Tk does X" and is never run against Tk is exactly
the kind of claim that has blocked PRs on this project, so the Tk column is
re-derived here from the shipped function rather than trusted.

What it does NOT do: it does not run Tkinter. ``search_tracks`` builds the
string and the dialog inserts it unchanged, so the string is settled here; that
the listbox then shows it is a Tk fact, recorded in §2.12 and checked by hand.
"""

import re
from pathlib import Path

import pandas as pd
import pytest

from recommendations.search import search_tracks

ROOT = Path(__file__).resolve().parent.parent.parent
INVENTORY = ROOT / "docs" / "UI_FEATURE_INVENTORY.md"

SPECIMEN_HEADER = (
    "| artist | title | Tk's row (`recommendations/search.py:38`) | this dialog's row |"
)


def _unquote(cell: str) -> str:
    """A table cell as its value: backticks stripped, the spaces they quote kept.

    The leading space in ``` ` – Skee Mask - Reviver` ``` is the divergence.
    Stripping it here would quietly turn the specimen into the thing it is
    contrasted with.
    """
    text = cell.strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        return text[1:-1]
    return text


def specimen_rows():
    """§6.6's specimen table as ``{artist, title, tk, web}`` dicts."""
    body = INVENTORY.read_text(encoding="utf-8")
    start = body.find(SPECIMEN_HEADER)
    assert start != -1, (
        "the §6.6 specimen table for the Add Anchor dialog rows is gone or was "
        "reworded; it is the declaration this file and anchor_dialog.test.mjs "
        "both check against"
    )

    rows = []
    # The header line, then the |---| separator under it.
    for line in body[start:].splitlines()[2:]:
        if not line.startswith("|"):
            break
        cells = [_unquote(cell) for cell in line.split("|")[1:-1]]
        assert len(cells) == 4, f"the specimen table row has {len(cells)} cells: {line}"
        rows.append(dict(zip(("artist", "title", "tk", "web"), cells)))

    assert len(rows) >= 3, f"the specimen table has only {len(rows)} rows"
    return rows


SPECIMENS = specimen_rows()


def _meta_ix(artist: str, title: str) -> pd.DataFrame:
    """A one-row ``meta_ix``, shaped as ``search_tracks`` reads it."""
    return pd.DataFrame(
        {"artist": [artist], "title": [title]}, index=pd.Index(["t1"], name="track_id")
    )


def _query_for(artist: str, title: str) -> str:
    """A query that matches this row. One of the two fields is always blank in
    the specimens, so the query comes from whichever one is not."""
    word = re.split(r"\s+", (artist or title).strip())[0]
    assert word, "a specimen with neither field would match nothing"
    return word.lower()


@pytest.mark.parametrize(
    "specimen", SPECIMENS, ids=lambda s: f"artist={s['artist']!r},title={s['title']!r}"
)
def test_the_tk_column_is_what_search_tracks_actually_builds(specimen):
    """The table's Tk column, re-derived from the shipped implementation A."""
    results = search_tracks(
        _query_for(specimen["artist"], specimen["title"]),
        _meta_ix(specimen["artist"], specimen["title"]),
        limit=50,
    )

    assert len(results) == 1, "the specimen did not match its own query"
    assert results[0]["display_name"] == specimen["tk"], (
        "§6.6's specimen table says Tk renders "
        f"{specimen['tk']!r} for artist={specimen['artist']!r} "
        f"title={specimen['title']!r}, and search_tracks builds "
        f"{results[0]['display_name']!r}"
    )


def test_the_table_declares_a_divergence_rather_than_parity():
    """Guard the guard. If the two columns ever agreed on every row, both this
    file and the JavaScript suite would still pass while declaring nothing, and
    the divergence entry would have quietly become a parity claim."""
    differing = [row for row in SPECIMENS if row["tk"] != row["web"]]

    assert differing, (
        "no specimen row distinguishes the two implementations; either the "
        "divergence was undone - in which case §6.6's entry has to go too - or "
        "the table stopped saying anything"
    )


def test_a_blank_artist_is_one_of_the_declared_cases():
    """The case the divergence exists for, and the one the library actually
    contains: 69 of its 1,532 tracks carry an artist of ``''``."""
    blank = [row for row in SPECIMENS if row["artist"] == ""]

    assert blank, "the specimen table no longer carries a blank-artist row"
    assert blank[0]["tk"].startswith(" –"), (
        f"Tk's row for a blank artist opens with the dangling separator; the "
        f"table says {blank[0]['tk']!r}"
    )
    assert not blank[0]["web"].startswith(" "), (
        f"the dialog's row for a blank artist drops it; the table says "
        f"{blank[0]['web']!r}"
    )
