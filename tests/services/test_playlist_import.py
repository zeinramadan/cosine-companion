"""Persisting the playlist tables: the two parquet files and the provenance.

Everything here runs against ``tmp_path``. The real ``data/`` directory is
never read and never written, and one test asserts exactly that by listing the
four index files before and after an import.

Expected values are literals worked out from
``playlist_fixtures.FIXTURE_XML``, or - for the real export - measured with a
standalone lxml script. Nothing calls ``import_playlists`` to decide what
``import_playlists`` should have produced.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from playlist_fixtures import (
    FIXTURE_MEMBERSHIP_COUNT,
    FIXTURE_PLAYLISTS,
    FIXTURE_RESOLVED,
    FIXTURE_TRACK_IDS,
    FIXTURE_UNRESOLVED,
    NO_PLAYLISTS_XML,
    write_fixture_xml,
)

from core.playlist_store import (
    MEMBERSHIP_FILENAME,
    PLAYLIST_COLUMNS,
    PLAYLISTS_FILENAME,
    PROVENANCE_FILENAME,
    PROVENANCE_SCHEMA,
    playlist_file_paths,
    read_provenance,
)
from services.playlist_import import import_playlists, playlist_tables_exist

#: The four files this PR must never write. Named here rather than imported so
#: a rename in the source cannot quietly shrink the check.
INDEX_FILES = ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json")

FIXED_CLOCK = datetime(2026, 8, 19, 14, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def xml(tmp_path):
    return write_fixture_xml(tmp_path / "export.xml")


@pytest.fixture
def data_dir(tmp_path):
    """A data directory holding a meta.parquet with the fixture's four tracks."""
    target = tmp_path / "data"
    target.mkdir()
    pd.DataFrame({"track_id": list(FIXTURE_TRACK_IDS)}).to_parquet(
        target / "meta.parquet", index=False
    )
    return target


@pytest.fixture
def summary(xml, data_dir):
    return import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------


def test_the_three_files_are_written_where_they_are_expected(summary, data_dir):
    assert (data_dir / PLAYLISTS_FILENAME).is_file()
    assert (data_dir / MEMBERSHIP_FILENAME).is_file()
    assert (data_dir / PROVENANCE_FILENAME).is_file()
    assert playlist_tables_exist(data_dir)


def test_the_playlist_table_has_exactly_the_five_specified_columns(summary, data_dir):
    """Spec §6.2 names five. A sixth would be a schema change nobody agreed to."""
    playlists = pd.read_parquet(data_dir / PLAYLISTS_FILENAME)

    assert list(playlists.columns) == PLAYLIST_COLUMNS
    assert PLAYLIST_COLUMNS == [
        "playlist_id",
        "name",
        "folder_path",
        "parent_id",
        "entries",
    ]


def test_the_membership_table_has_exactly_the_two_specified_columns(summary, data_dir):
    membership = pd.read_parquet(data_dir / MEMBERSHIP_FILENAME)

    assert list(membership.columns) == ["track_id", "playlist_id"]


def test_the_rows_are_the_fixtures_seven_playlists_in_document_order(
    summary, data_dir
):
    playlists = pd.read_parquet(data_dir / PLAYLISTS_FILENAME)

    found = [
        (tuple(row.folder_path), row.name, int(row.entries))
        for row in playlists.itertuples(index=False)
    ]
    assert found == [
        (folder_path, name, entries)
        for folder_path, name, entries, _ in FIXTURE_PLAYLISTS
    ]


def test_folder_path_round_trips_as_a_list_of_segments(summary, data_dir):
    """Written as LIST<STRING>, read back as segments. A pre-joined string is
    unrecoverable: ``Collections/Hauls`` is one folder whose name has a slash."""
    playlists = pd.read_parquet(data_dir / PLAYLISTS_FILENAME)
    deep = playlists[playlists["name"] == "five deep"].iloc[0]

    assert list(deep["folder_path"]) == [
        "Alpha",
        "Collections/Hauls",
        "deep",
        "deeper",
    ]


def test_every_membership_pair_is_persisted_including_the_unresolvable_one(
    summary, data_dir
):
    """Filtering at import time would mean a later reindex could never pick the
    missing entries up without somebody remembering to re-import."""
    membership = pd.read_parquet(data_dir / MEMBERSHIP_FILENAME)

    assert len(membership) == FIXTURE_MEMBERSHIP_COUNT == 7
    assert "t999" in set(membership["track_id"])


# ---------------------------------------------------------------------------
# dtypes: the join is exact-string
# ---------------------------------------------------------------------------


def test_membership_track_id_is_the_same_dtype_as_meta_parquets(summary, data_dir):
    """The whole feature is worthless if these drift. Rekordbox TrackIDs look
    like integers - ``192072736`` - so any inference step would happily make
    one column int64 and the other object, and the join would match nothing
    while raising nothing."""
    membership = pd.read_parquet(data_dir / MEMBERSHIP_FILENAME)
    meta = pd.read_parquet(data_dir / "meta.parquet")

    assert membership["track_id"].dtype == meta["track_id"].dtype == object
    assert all(isinstance(value, str) for value in membership["track_id"])
    assert all(isinstance(value, str) for value in meta["track_id"])


def test_numeric_looking_track_ids_survive_as_strings(tmp_path):
    """The fixture ids are ``t1``..``t4``, which cannot be inferred as numbers.
    The REAL ones can, so the case is covered explicitly."""
    numeric = (
        write_fixture_xml(tmp_path / "numeric.xml").read_text(encoding="utf-8")
        .replace('"t1"', '"192072736"')
        .replace('Key="t2"', 'Key="148105274"')
    )
    xml = write_fixture_xml(tmp_path / "numeric.xml", numeric)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    membership = pd.read_parquet(data_dir / MEMBERSHIP_FILENAME)
    assert membership["track_id"].dtype == object
    assert "192072736" in set(membership["track_id"])
    assert 192072736 not in set(membership["track_id"])


def test_playlist_ids_join_the_two_tables(summary, data_dir):
    playlists = pd.read_parquet(data_dir / PLAYLISTS_FILENAME)
    membership = pd.read_parquet(data_dir / MEMBERSHIP_FILENAME)

    assert set(membership["playlist_id"]) <= set(playlists["playlist_id"])
    assert membership["playlist_id"].dtype == playlists["playlist_id"].dtype == object


# ---------------------------------------------------------------------------
# Provenance and staleness
# ---------------------------------------------------------------------------


def test_the_provenance_record_is_what_was_imported(summary, data_dir, xml):
    provenance = read_provenance(data_dir)

    assert provenance is not None
    assert provenance.schema_version == PROVENANCE_SCHEMA
    assert provenance.source_xml == str(Path(xml).resolve())
    assert provenance.source_name == "export.xml"
    assert provenance.imported_at == "2026-08-19T14:30:00+00:00"
    assert provenance.playlist_count == 7
    assert provenance.membership_count == FIXTURE_MEMBERSHIP_COUNT


def test_the_recorded_digest_is_the_files_own_sha256(summary, xml, data_dir):
    """Computed here with hashlib, not read back out of the writer."""
    expected = hashlib.sha256(Path(xml).read_bytes()).hexdigest()

    assert read_provenance(data_dir).source_sha256 == expected


def test_the_recorded_size_and_mtime_are_the_files_own(summary, xml, data_dir):
    stat = Path(xml).stat()
    provenance = read_provenance(data_dir)

    assert provenance.source_bytes == stat.st_size
    assert provenance.source_mtime == pytest.approx(stat.st_mtime)


def test_the_provenance_json_is_readable_by_a_human(summary, data_dir):
    """It is the one file in this feature somebody may have to read by hand."""
    raw = json.loads((data_dir / PROVENANCE_FILENAME).read_text(encoding="utf-8"))

    assert raw["schema_version"] == 1
    assert set(raw) == {
        "source_xml",
        "source_sha256",
        "source_bytes",
        "source_mtime",
        "imported_at",
        "playlist_count",
        "membership_count",
        "schema_version",
    }


def test_a_provenance_record_from_a_future_schema_reads_as_absent(summary, data_dir):
    """Misreading a record written by a newer version is worse than not
    reading it: the drawer's "nothing imported" state is at least true."""
    path = data_dir / PROVENANCE_FILENAME
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["schema_version"] = PROVENANCE_SCHEMA + 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert read_provenance(data_dir) is None


def test_a_corrupt_provenance_record_reads_as_absent(summary, data_dir):
    (data_dir / PROVENANCE_FILENAME).write_text("{not json", encoding="utf-8")

    assert read_provenance(data_dir) is None


# ---------------------------------------------------------------------------
# Determinism: re-importing an unchanged file is a no-op
# ---------------------------------------------------------------------------


def test_re_importing_an_unchanged_file_rewrites_identical_tables(xml, data_dir):
    first = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    playlists_bytes = (data_dir / PLAYLISTS_FILENAME).read_bytes()
    membership_bytes = (data_dir / MEMBERSHIP_FILENAME).read_bytes()

    second = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert (data_dir / PLAYLISTS_FILENAME).read_bytes() == playlists_bytes
    assert (data_dir / MEMBERSHIP_FILENAME).read_bytes() == membership_bytes
    assert first.provenance.source_sha256 == second.provenance.source_sha256


def test_the_ids_do_not_move_when_the_file_is_re_imported(xml, data_dir):
    """Re-import must be a no-op, which is what "stable and deterministic for
    the same XML" buys. A positional id would renumber every row."""
    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    before = pd.read_parquet(data_dir / PLAYLISTS_FILENAME)["playlist_id"].tolist()

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    after = pd.read_parquet(data_dir / PLAYLISTS_FILENAME)["playlist_id"].tolist()

    assert before == after
    assert len(set(before)) == 7


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------


def test_the_summary_counts_the_fixtures_entries(summary):
    assert summary.playlists == 7
    assert summary.folders == 5
    assert summary.entries_total == FIXTURE_MEMBERSHIP_COUNT == 7
    assert summary.entries_resolved == FIXTURE_RESOLVED == 6
    assert summary.entries_unresolved == FIXTURE_UNRESOLVED == 1
    assert summary.indexed_tracks == 4
    assert summary.tracks_with_playlists == 4
    assert summary.path_keyed_playlists == 1
    assert summary.entries_attribute_mismatches == 0


def test_the_summary_names_the_unresolvable_entries_rather_than_hiding_them(summary):
    """Spec §6.5: reported, not an error. Silently dropping them would make
    playlist counts quietly wrong."""
    lines = summary.lines()

    assert any(
        "1 entries reference tracks not in your library - reindex to include them"
        in line
        for line in lines
    ), lines


def test_the_summary_names_the_path_keyed_playlist(summary):
    assert any("KeyType=1" in line for line in summary.lines())


def test_an_import_with_nothing_unresolvable_says_nothing_about_it(tmp_path):
    """The line is a report of a real condition, not decoration."""
    xml = write_fixture_xml(tmp_path / "clean.xml")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    pd.DataFrame({"track_id": list(FIXTURE_TRACK_IDS) + ["t999"]}).to_parquet(
        data_dir / "meta.parquet", index=False
    )

    summary = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert summary.entries_unresolved == 0
    assert not any("reindex to include them" in line for line in summary.lines())


def test_importing_before_any_index_exists_counts_everything_as_unresolvable(
    tmp_path, xml
):
    """"Imported playlists before indexing" is a real order of operations and
    it must produce a summary, not a crash."""
    data_dir = tmp_path / "empty-data"
    data_dir.mkdir()

    summary = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert summary.indexed_tracks == 0
    assert summary.entries_resolved == 0
    assert summary.entries_unresolved == FIXTURE_MEMBERSHIP_COUNT


def test_an_export_with_no_playlists_element_imports_to_nothing(tmp_path):
    """This is the shape every XML the indexing tests write has, and the
    pipeline calls the import on all of them."""
    xml = write_fixture_xml(tmp_path / "bare.xml", NO_PLAYLISTS_XML)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    summary = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert summary.playlists == 0
    assert summary.entries_total == 0
    assert pd.read_parquet(data_dir / PLAYLISTS_FILENAME).empty
    assert list(pd.read_parquet(data_dir / MEMBERSHIP_FILENAME).columns) == [
        "track_id",
        "playlist_id",
    ]


# ---------------------------------------------------------------------------
# What must NOT be written
# ---------------------------------------------------------------------------


def test_the_import_never_writes_any_of_the_four_index_files(xml, tmp_path):
    """Plan §2.3. ``meta.parquet`` is rewritten wholesale in two other places,
    which is precisely why membership is two separate tables."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in INDEX_FILES:
        (data_dir / name).write_bytes(b"sentinel")
    before = {name: (data_dir / name).read_bytes() for name in INDEX_FILES}

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    after = {name: (data_dir / name).read_bytes() for name in INDEX_FILES}
    assert after == before
    assert all(value == b"sentinel" for value in after.values())


def test_the_import_creates_only_the_three_playlist_files(xml, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert sorted(path.name for path in data_dir.iterdir()) == sorted(
        [PLAYLISTS_FILENAME, MEMBERSHIP_FILENAME, PROVENANCE_FILENAME]
    )


def test_the_import_creates_the_data_directory_if_it_is_absent(xml, tmp_path):
    data_dir = tmp_path / "not-yet"

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert playlist_tables_exist(data_dir)


def test_playlist_file_paths_are_beside_the_index_files(tmp_path):
    playlists, membership, provenance = playlist_file_paths(tmp_path)

    assert playlists == tmp_path / "playlists.parquet"
    assert membership == tmp_path / "playlist_membership.parquet"
    assert provenance == tmp_path / "playlist_import.json"
