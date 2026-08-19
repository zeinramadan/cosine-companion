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
    FIXTURE_XML,
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
    read_playlist_tables,
    read_provenance,
)
from services.playlist_import import import_playlists, playlist_tables_exist
from services.playlist_service import PlaylistService

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

    assert raw["schema_version"] == 2
    assert set(raw) == {
        "source_xml",
        "source_sha256",
        "source_bytes",
        "source_mtime",
        "imported_at",
        "playlist_count",
        "membership_count",
        "playlists_sha256",
        "membership_sha256",
        "schema_version",
    }


def test_the_manifest_records_the_digests_of_the_tables_beside_it(summary, data_dir):
    """The commit record names its own two tables.

    Recomputed here with hashlib against the files on disk, not read back out
    of the writer. This pair is what makes a mixed generation - one table from
    an interrupted import beside another from the one before it - detectable
    rather than merely unlikely.
    """
    raw = json.loads((data_dir / PROVENANCE_FILENAME).read_text(encoding="utf-8"))

    assert raw["playlists_sha256"] == hashlib.sha256(
        (data_dir / PLAYLISTS_FILENAME).read_bytes()
    ).hexdigest()
    assert raw["membership_sha256"] == hashlib.sha256(
        (data_dir / MEMBERSHIP_FILENAME).read_bytes()
    ).hexdigest()


def test_a_manifest_without_the_table_digests_reads_as_absent(summary, data_dir):
    """A schema-2 record that cannot be checked is not a record worth trusting.

    The two digest keys are read with ``raw[...]`` and not ``raw.get(...)`` on
    purpose: a manifest missing them - hand-edited, or written by something
    that only knew the older shape - would otherwise compare its empty default
    against a real digest, fail, and be reported as a mixed generation. Absent
    is the honest answer, and it is the same one the drawer already renders.
    """
    path = data_dir / PROVENANCE_FILENAME
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["membership_sha256"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert read_provenance(data_dir) is None


def test_read_playlist_tables_refuses_a_table_missing_a_column_it_reads(
    summary, data_dir
):
    """The column check, on its own, at the level it lives at.

    ``PlaylistService.reload`` also has a broad handler around the index build,
    so a service-level test alone would still pass with this check deleted -
    the handler would simply catch the AttributeError instead. Testing the
    guard where it is means both layers have to stay.
    """
    frame = pd.read_parquet(data_dir / PLAYLISTS_FILENAME).rename(
        columns={"playlist_id": "id"}
    )
    frame.to_parquet(data_dir / PLAYLISTS_FILENAME, index=False)

    assert read_playlist_tables(data_dir) is None


def test_read_playlist_tables_accepts_a_table_that_has_gained_a_column(
    summary, data_dir
):
    """Subset, not equality: an added column is not a reason to refuse."""
    frame = pd.read_parquet(data_dir / MEMBERSHIP_FILENAME)
    frame["added_later"] = 1
    frame.to_parquet(data_dir / MEMBERSHIP_FILENAME, index=False)

    tables = read_playlist_tables(data_dir)

    assert tables is not None
    assert len(tables[1]) == FIXTURE_MEMBERSHIP_COUNT


def test_the_recorded_digest_describes_the_bytes_THAT_WERE_PARSED(tmp_path, monkeypatch):
    """A re-export landing mid-import cannot make the manifest describe a file
    the tables were not built from.

    The import used to read the export twice - once to parse it, once to hash
    it - and Rekordbox rewrites that file every time the user re-exports. A
    rewrite between the two reads left the tables holding version A and the
    manifest holding the digest of version B, after which
    ``PlaylistService.staleness`` reported **fresh** for data that did not
    match the file. A false "stale" costs a re-import; a false "fresh" is the
    drawer confidently showing playlists that no longer exist, which is the one
    failure this manifest exists to rule out.

    The fix is to read once and hash and parse the same buffer, so the wrapper
    below - which lets the re-export land at the widest point the window could
    ever be, the instant of the parse - changes nothing about what is recorded.
    """
    import processing.playlist_parser as parser

    xml = write_fixture_xml(tmp_path / "export.xml")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    renamed = FIXTURE_XML.replace('Name="top level"', 'Name="renamed top"')
    assert renamed != FIXTURE_XML

    original = parser.parse_playlists_bytes

    def parse_then_let_a_re_export_land(data):
        parsed = original(data)
        xml.write_text(renamed, encoding="utf-8")
        return parsed

    monkeypatch.setattr(
        parser, "parse_playlists_bytes", parse_then_let_a_re_export_land
    )
    summary = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    # The tables hold the version that was parsed...
    names = set(pd.read_parquet(data_dir / PLAYLISTS_FILENAME)["name"])
    assert "top level" in names
    assert "renamed top" not in names

    # ...and the manifest holds the digest of THAT version, computed here from
    # the literal rather than read back out of the writer.
    parsed_digest = hashlib.sha256(FIXTURE_XML.encode("utf-8")).hexdigest()
    assert summary.provenance.source_sha256 == parsed_digest
    assert read_provenance(data_dir).source_sha256 == parsed_digest

    # Which is what makes the verdict on the file now on disk the true one.
    assert parsed_digest != hashlib.sha256(xml.read_bytes()).hexdigest()
    assert PlaylistService(data_dir).staleness().stale is True


def test_the_recorded_size_is_the_length_of_the_buffer_that_was_parsed(
    tmp_path, monkeypatch
):
    """Same window, checked on the byte count rather than the digest.

    ``source_bytes`` used to come from a second ``stat``, so a file that grew
    after the parse was recorded at its new length beside its old contents.
    """
    import processing.playlist_parser as parser

    xml = write_fixture_xml(tmp_path / "export.xml")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    padded = FIXTURE_XML + "<!-- a much longer file arrives -->\n" * 50
    original = parser.parse_playlists_bytes

    def parse_then_let_a_bigger_export_land(data):
        parsed = original(data)
        xml.write_text(padded, encoding="utf-8")
        return parsed

    monkeypatch.setattr(
        parser, "parse_playlists_bytes", parse_then_let_a_bigger_export_land
    )
    summary = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert summary.provenance.source_bytes == len(FIXTURE_XML.encode("utf-8"))
    assert summary.provenance.source_bytes != xml.stat().st_size


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
