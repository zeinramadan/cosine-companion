"""The ``<PLAYLISTS>`` parse, against hand-written fixtures and the real export.

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
Every one of them is a literal. The fixture expectations in
``tests/services/playlist_fixtures.py`` were read off the XML literal beside
them by hand; the real-export expectations below were measured with a
standalone lxml script that does not import ``processing.playlist_parser`` at
all. Nothing here computes an expected value by calling the thing under test.

THE REAL-EXPORT CASE SKIPS, IT DOES NOT FAIL
--------------------------------------------
``data/`` is gitignored, so on CI the export is simply not there. It is guarded
the same way ``tests/services/golden/`` guards the real-library tests: absent
means skip with a stated reason, and a DIFFERENT file at the same path also
means skip, naming both digests - the numbers below describe one specific
export and asserting them against another one would be a failure that says
nothing about the code.
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "services"))

from playlist_fixtures import (  # noqa: E402
    DUPLICATE_PATH_XML,
    ENTRIES_MISMATCH_XML,
    FIXTURE_FOLDER_PATHS,
    FIXTURE_MEMBERSHIP_COUNT,
    FIXTURE_PLAYLISTS,
    NO_PLAYLISTS_XML,
    write_fixture_xml,
)

from processing.playlist_parser import (  # noqa: E402
    ROOT_NODE_NAME,
    mint_folder_id,
    mint_playlist_id,
    parse_playlists,
)


@pytest.fixture
def fixture_xml(tmp_path):
    return write_fixture_xml(tmp_path / "fixture.xml")


@pytest.fixture
def parsed(fixture_xml):
    return parse_playlists(fixture_xml)


# ---------------------------------------------------------------------------
# The fixture export
# ---------------------------------------------------------------------------


def test_every_playlist_is_found_in_document_order(parsed):
    found = tuple(
        (playlist.folder_path, playlist.name, playlist.entries, playlist.track_ids)
        for playlist in parsed.playlists
    )

    assert found == FIXTURE_PLAYLISTS


def test_the_root_segment_never_reaches_a_path(parsed):
    """It is Rekordbox's container, not a folder anybody made."""
    for playlist in parsed.playlists:
        assert ROOT_NODE_NAME not in playlist.folder_path

    for path in parsed.folder_paths:
        assert ROOT_NODE_NAME not in path


def test_a_top_level_playlist_has_an_empty_folder_path(parsed):
    """Not ``('ROOT',)`` and not ``('',)`` - genuinely nothing above it."""
    top = next(p for p in parsed.playlists if p.name == "top level")

    assert top.folder_path == ()
    assert top.parent_id == ""


def test_the_folder_paths_are_the_five_folders_root_excluded(parsed):
    assert parsed.folder_paths == FIXTURE_FOLDER_PATHS


def test_nesting_five_segments_deep_is_parsed_whole(parsed):
    """One deeper than the real export, so a hard-coded depth of 4 fails here."""
    deep = next(p for p in parsed.playlists if p.name == "five deep")

    assert deep.folder_path == ("Alpha", "Collections/Hauls", "deep", "deeper")
    assert deep.full_path == (
        "Alpha",
        "Collections/Hauls",
        "deep",
        "deeper",
        "five deep",
    )
    assert len(deep.full_path) == 5


def test_a_folder_name_containing_a_slash_stays_one_segment(parsed):
    """``Collections/Hauls`` is ONE folder. This is the whole reason
    ``folder_path`` is a list: joined with ' / ' it would be indistinguishable
    from two folders called ``Collections`` and ``Hauls``."""
    deep = next(p for p in parsed.playlists if p.name == "five deep")

    assert deep.folder_path[1] == "Collections/Hauls"
    assert "Collections" not in deep.folder_path
    assert "Hauls" not in deep.folder_path


def test_two_playlists_sharing_a_leaf_name_are_two_distinct_playlists(parsed):
    """36 leaf names are duplicated in the real export. The leaf name is not
    an identity; the full path is."""
    shared = [p for p in parsed.playlists if p.name == "shared name"]

    assert len(shared) == 2
    assert {p.folder_path for p in shared} == {("Alpha",), ("Beta",)}
    assert shared[0].playlist_id != shared[1].playlist_id
    assert shared[0].parent_id != shared[1].parent_id


def test_an_empty_playlist_is_recorded_with_no_members(parsed):
    """Unreachable with the real export (0 empty playlists) and reachable here."""
    empty = next(p for p in parsed.playlists if p.name == "empty")

    assert empty.entries == 0
    assert empty.track_ids == ()


def test_a_path_keyed_playlist_is_catalogued_without_its_membership(parsed):
    """``KeyType="1"`` means the keys are file locations, not TrackIDs.

    Recording them as if they were TrackIDs would put rows in the membership
    table that can never match a track. The playlist itself is still listed.
    """
    by_path = next(p for p in parsed.playlists if p.name == "by path")

    assert by_path.key_type == "1"
    assert by_path.track_ids == ()
    assert parsed.unsupported_key_type == ((("Beta", "by path"), "1", 1),)


def test_a_key_naming_an_unknown_track_is_kept_verbatim(parsed):
    """Resolution is not this module's job. The parse records what the file
    says; ``services.playlist_import`` counts what does not resolve."""
    dangling = next(p for p in parsed.playlists if p.name == "dangling")

    assert dangling.track_ids == ("t4", "t999")


def test_membership_pairs_are_track_id_then_playlist_id(parsed):
    top = next(p for p in parsed.playlists if p.name == "top level")

    assert parsed.membership[:2] == [
        ("t1", top.playlist_id),
        ("t2", top.playlist_id),
    ]
    assert parsed.membership_count == FIXTURE_MEMBERSHIP_COUNT
    assert len(parsed.membership) == FIXTURE_MEMBERSHIP_COUNT


def test_an_export_with_no_playlists_element_parses_to_nothing(tmp_path):
    """Every XML the indexing tests write looks like this."""
    parsed = parse_playlists(write_fixture_xml(tmp_path / "bare.xml", NO_PLAYLISTS_XML))

    assert parsed.playlists == ()
    assert parsed.folder_paths == ()
    assert parsed.membership == []


def test_a_declared_entries_count_that_disagrees_loses_to_the_contents(tmp_path):
    """``Entries="9"`` over three children. The real export has 0 mismatches,
    so the attribute is trustworthy - but trustworthy is a measurement, and the
    children are the thing that is actually there."""
    parsed = parse_playlists(
        write_fixture_xml(tmp_path / "lying.xml", ENTRIES_MISMATCH_XML)
    )

    lying = parsed.playlists[0]
    assert lying.entries == 3
    assert parsed.entries_attribute_mismatch == ((("lying",), 9, 3),)


# ---------------------------------------------------------------------------
# Minted ids
# ---------------------------------------------------------------------------


def test_a_minted_id_is_the_same_every_run_and_every_process():
    """The literals are the point: Python's own ``hash()`` is salted per
    process, so a scheme built on it would re-mint every id on every run and
    make re-importing an unchanged file rewrite every row.

    These four digests were computed from the SPECIFICATION in
    ``mint_playlist_id``'s docstring - blake2b, digest_size 8, over
    ``json.dumps([*folder_path, name, occurrence], ensure_ascii=False,
    separators=(",", ":"))`` - by a throwaway script that does not import the
    module. Pinning them here is what makes the scheme a contract rather than
    whatever the implementation happens to do this week.
    """
    assert mint_playlist_id(("Alpha", "Beta"), "gamma") == "90ebf4be34c9ff80"
    assert mint_playlist_id((), "gamma") == "aef76700c2cb6399"
    assert mint_folder_id(("Alpha", "Beta")) == "bae88d88787b7bb5"
    assert mint_folder_id(()) == ""

    # 16 hex characters, which is what PLAYLIST_ID_HEX_LENGTH promises.
    assert len(mint_playlist_id((), "gamma")) == 16


def test_the_id_depends_on_the_whole_path_not_the_leaf_name():
    assert mint_playlist_id(("Alpha",), "x") != mint_playlist_id(("Beta",), "x")
    assert mint_playlist_id(("A/B",), "x") != mint_playlist_id(("A", "B"), "x")


def test_the_parent_id_of_a_playlist_is_its_folder_paths_own_id(parsed):
    deep = next(p for p in parsed.playlists if p.name == "five deep")

    assert deep.parent_id == mint_folder_id(
        ("Alpha", "Collections/Hauls", "deep", "deeper")
    )


def test_two_playlists_with_an_identical_full_path_still_get_distinct_ids(tmp_path):
    """Without the occurrence ordinal these two would mint the same id and the
    second would silently replace the first in every downstream dict."""
    parsed = parse_playlists(
        write_fixture_xml(tmp_path / "twins.xml", DUPLICATE_PATH_XML)
    )

    first, second = parsed.playlists
    assert first.full_path == second.full_path == ("Folder", "twin")
    assert first.playlist_id != second.playlist_id
    assert first.playlist_id == mint_playlist_id(("Folder",), "twin", 0)
    assert second.playlist_id == mint_playlist_id(("Folder",), "twin", 1)


def test_re_parsing_the_same_file_mints_the_same_ids(fixture_xml):
    """Determinism is the requirement re-import-is-a-no-op rests on."""
    first = [p.playlist_id for p in parse_playlists(fixture_xml).playlists]
    second = [p.playlist_id for p in parse_playlists(fixture_xml).playlists]

    assert first == second
    assert len(set(first)) == len(first)


# ---------------------------------------------------------------------------
# The real export
# ---------------------------------------------------------------------------

#: The one export these numbers describe. Measured on 2026-08-19.
REAL_EXPORT_NAME = "library_export_190826.xml"
REAL_EXPORT_SHA256 = (
    "6f868f1851a39559be672042d0a2ac560baf96e2d48d4f8d2bb9ffdcc98ac2e6"
)
REAL_EXPORT_BYTES = 1496376

#: Measured with a standalone lxml script, not with the parser under test.
#: NOTE two corrections to the plan and the spec, both re-measured:
#:   * "14 folders PLUS a root node" (i.e. 15) is wrong - the export has 14
#:     ``Type="0"`` nodes IN TOTAL, one of which is ROOT, so 13 real folders;
#:   * the spec's max depth of "4 display segments" is confirmed: 3 folder
#:     levels plus the leaf.
REAL_PLAYLISTS = 141
REAL_FOLDERS = 13
REAL_MEMBERSHIP = 4669
REAL_DUPLICATE_LEAF_NAMES = 36
REAL_MAX_FOLDER_DEPTH = 3
REAL_TOP_LEVEL_PLAYLISTS = 6
REAL_DEEPEST_FOLDER = ("Mischief", "Collections/Hauls", "biscuit (funk)")
REAL_SLASHED_FOLDERS = {("Mischief", "08/2026"), ("Mischief", "Collections/Hauls")}


def real_export_path():
    from config import DATA

    return Path(DATA) / REAL_EXPORT_NAME


@pytest.fixture(scope="module")
def real_export():
    """The 2026-08-19 export, or an actionable skip."""
    path = real_export_path()
    if not path.is_file():
        pytest.skip(
            f"the real Rekordbox export is not present at {path}: data/ is "
            "gitignored, so this assertion only runs on a developer machine "
            "with the export in place. The hand-written fixture cases above "
            "guard the parser everywhere, including CI."
        )

    found = hashlib.sha256(path.read_bytes()).hexdigest()
    if found != REAL_EXPORT_SHA256:
        pytest.skip(
            f"{path} is not the export these numbers were measured against. "
            f"Expected sha256 {REAL_EXPORT_SHA256}, found {found}. Re-measure "
            "and update REAL_* in this file if the export was deliberately "
            "replaced; the fixture cases above are unaffected."
        )
    return path


@pytest.fixture(scope="module")
def real_parsed(real_export):
    return parse_playlists(real_export)


def test_the_real_export_is_the_size_it_was_measured_at(real_export):
    assert real_export.stat().st_size == REAL_EXPORT_BYTES


def test_the_real_export_yields_the_measured_counts(real_parsed):
    assert len(real_parsed.playlists) == REAL_PLAYLISTS
    assert len(real_parsed.folder_paths) == REAL_FOLDERS
    assert real_parsed.membership_count == REAL_MEMBERSHIP


def test_the_real_export_has_no_entries_attribute_mismatch(real_parsed):
    assert real_parsed.entries_attribute_mismatch == ()


def test_every_real_playlist_is_keyed_by_track_id(real_parsed):
    """All 141 are ``KeyType="0"``, so path-keyed membership is fixture-only."""
    assert real_parsed.unsupported_key_type == ()
    assert {p.key_type for p in real_parsed.playlists} == {"0"}


def test_no_real_playlist_is_empty(real_parsed):
    assert [p.name for p in real_parsed.playlists if not p.track_ids] == []


def test_the_real_export_nests_four_display_segments_deep(real_parsed):
    depths = {len(p.folder_path) for p in real_parsed.playlists}

    assert max(depths) == REAL_MAX_FOLDER_DEPTH
    assert min(depths) == 0  # six playlists sit at the top level
    deepest = {p.folder_path for p in real_parsed.playlists if len(p.folder_path) == 3}
    assert deepest == {REAL_DEEPEST_FOLDER}


def test_the_real_export_has_six_top_level_playlists(real_parsed):
    top = [p for p in real_parsed.playlists if not p.folder_path]

    assert len(top) == REAL_TOP_LEVEL_PLAYLISTS
    assert all(p.parent_id == "" for p in top)


def test_two_real_folder_names_contain_a_forward_slash(real_parsed):
    """The measurement the list-of-segments decision rests on. The plan names
    ``Collections/Hauls``; there is a second, ``08/2026``."""
    slashed = {path for path in real_parsed.folder_paths if "/" in path[-1]}

    assert slashed == REAL_SLASHED_FOLDERS


def test_thirty_six_real_leaf_names_are_duplicated(real_parsed):
    """Which is why the drawer renders the full path and not the name."""
    from collections import Counter

    counts = Counter(p.name for p in real_parsed.playlists)
    duplicated = {name for name, count in counts.items() if count > 1}

    assert len(duplicated) == REAL_DUPLICATE_LEAF_NAMES


def test_every_real_full_path_is_unique(real_parsed):
    paths = [p.full_path for p in real_parsed.playlists]

    assert len(set(paths)) == len(paths) == REAL_PLAYLISTS


def test_no_real_playlist_id_collides(real_parsed):
    ids = [p.playlist_id for p in real_parsed.playlists]

    assert len(set(ids)) == REAL_PLAYLISTS
