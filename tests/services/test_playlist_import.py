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
import re
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
    MEMBERSHIP_STEM,
    PLAYLIST_COLUMNS,
    PLAYLISTS_STEM,
    PROVENANCE_FILENAME,
    PROVENANCE_SCHEMA,
    committed_table_paths,
    playlist_manifest_path,
    read_playlist_tables,
    read_provenance,
)
from services.playlist_import import import_playlists, playlist_tables_exist
from services.playlist_service import PlaylistService

#: The four files this PR must never write. Named here rather than imported so
#: a rename in the source cannot quietly shrink the check.
INDEX_FILES = ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json")

FIXED_CLOCK = datetime(2026, 8, 19, 14, 30, 0, tzinfo=timezone.utc)


def playlists_pq(data_dir):
    """The committed playlist table, found the only supported way.

    A table's filename carries the generation that wrote it, so nothing outside
    the store can construct one - which is the point: the manifest is the
    pointer, and a test that guessed a filename would be checking a file no
    reader would ever open.
    """
    paths = committed_table_paths(data_dir)
    assert paths is not None, "no committed generation in this data directory"
    return paths[0]


def membership_pq(data_dir):
    paths = committed_table_paths(data_dir)
    assert paths is not None, "no committed generation in this data directory"
    return paths[1]


def reseal(data_dir):
    """Rewrite the manifest's digests to match whatever its tables hold now.

    Needed by every test that DAMAGES a table on purpose. The manifest records
    the digest of the bytes it was committed for, so an edited table is refused
    by that guard alone - which would leave the guard the test is actually
    about (the column check, the parse) never running, and the test passing for
    the wrong reason. Resealing puts the edited table inside a generation that
    is consistent with its own manifest, which is the only way to reach the
    deeper guards.
    """
    manifest = playlist_manifest_path(data_dir)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["playlists_sha256"] = hashlib.sha256(
        playlists_pq(data_dir).read_bytes()
    ).hexdigest()
    raw["membership_sha256"] = hashlib.sha256(
        membership_pq(data_dir).read_bytes()
    ).hexdigest()
    manifest.write_text(json.dumps(raw), encoding="utf-8")


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


@pytest.fixture
def parquet_string_dtype(tmp_path):
    """The dtype THIS pandas gives a string column read back from parquet.

    Measured rather than named. pandas 2 answers ``object`` and pandas 3
    answers ``str``; writing either literal into the assertions below would
    pin the version of pandas instead of the shape of the data, and the tests
    would go red on an upgrade that changed nothing about the tables. What has
    to hold on every version is that ``track_id`` comes back as *the string
    dtype*, whatever this pandas calls it, and never as an inferred ``int64``.

    Guard the guard: a probe that stopped yielding ``str`` values would make
    every assertion built on it vacuous, so that is checked here rather than
    assumed.
    """
    probe = tmp_path / "dtype-probe.parquet"
    pd.DataFrame({"probe": ["a", "b"]}).to_parquet(probe, index=False)
    column = pd.read_parquet(probe)["probe"]

    assert all(isinstance(value, str) for value in column), (
        "the probe column is not holding Python str, so it does not describe "
        "the dtype the track_id assertions are about"
    )
    return column.dtype


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------


def test_the_manifest_names_two_tables_that_are_on_disk_beside_it(summary, data_dir):
    """The manifest is the fixed name; the tables are whatever it says."""
    assert playlist_manifest_path(data_dir).is_file()
    assert playlists_pq(data_dir).is_file()
    assert membership_pq(data_dir).is_file()
    assert playlist_tables_exist(data_dir)


def test_the_table_names_carry_a_generation_nobody_else_will_choose(summary, data_dir):
    """``playlists.<32 hex>.parquet``. The generation is what makes a committed
    table immutable in practice: a second import mints a different one, so it
    can never write over a table a reader in another process is holding."""
    playlists, membership = committed_table_paths(data_dir)

    assert re.fullmatch(rf"{PLAYLISTS_STEM}\.[0-9a-f]{{32}}\.parquet", playlists.name)
    assert re.fullmatch(rf"{MEMBERSHIP_STEM}\.[0-9a-f]{{32}}\.parquet", membership.name)
    # One generation per import, shared by both of its tables.
    assert playlists.name.split(".")[1] == membership.name.split(".")[1]


def test_the_playlist_table_has_exactly_the_five_specified_columns(summary, data_dir):
    """Spec §6.2 names five. A sixth would be a schema change nobody agreed to."""
    playlists = pd.read_parquet(playlists_pq(data_dir))

    assert list(playlists.columns) == PLAYLIST_COLUMNS
    assert PLAYLIST_COLUMNS == [
        "playlist_id",
        "name",
        "folder_path",
        "parent_id",
        "entries",
    ]


def test_the_membership_table_has_exactly_the_two_specified_columns(summary, data_dir):
    membership = pd.read_parquet(membership_pq(data_dir))

    assert list(membership.columns) == ["track_id", "playlist_id"]


def test_the_rows_are_the_fixtures_seven_playlists_in_document_order(
    summary, data_dir
):
    playlists = pd.read_parquet(playlists_pq(data_dir))

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
    playlists = pd.read_parquet(playlists_pq(data_dir))
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
    membership = pd.read_parquet(membership_pq(data_dir))

    assert len(membership) == FIXTURE_MEMBERSHIP_COUNT == 7
    assert "t999" in set(membership["track_id"])


# ---------------------------------------------------------------------------
# dtypes: the join is exact-string
# ---------------------------------------------------------------------------


def test_membership_track_id_is_the_same_dtype_as_meta_parquets(
    summary, data_dir, parquet_string_dtype
):
    """The whole feature is worthless if these drift. Rekordbox TrackIDs look
    like integers - ``192072736`` - so any inference step would happily make
    one column int64 and the other object, and the join would match nothing
    while raising nothing.

    The dtype is compared against ``parquet_string_dtype`` - what this pandas
    calls a string column off parquet - rather than the literal ``object``.
    On pandas 2 that IS ``object`` and this assertion is unchanged; on pandas
    3 the same column reads back as ``str``. Neither is a change to the data,
    and pinning the older spelling would have this file fail an upgrade while
    the join it protects was still exact."""
    membership = pd.read_parquet(membership_pq(data_dir))
    meta = pd.read_parquet(data_dir / "meta.parquet")

    # They must not drift APART, and neither may be a number.
    assert membership["track_id"].dtype == meta["track_id"].dtype
    assert membership["track_id"].dtype == parquet_string_dtype
    assert all(isinstance(value, str) for value in membership["track_id"])
    assert all(isinstance(value, str) for value in meta["track_id"])


def test_numeric_looking_track_ids_survive_as_strings(tmp_path, parquet_string_dtype):
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

    membership = pd.read_parquet(membership_pq(data_dir))
    assert membership["track_id"].dtype == parquet_string_dtype
    assert "192072736" in set(membership["track_id"])
    assert 192072736 not in set(membership["track_id"])


def test_playlist_ids_join_the_two_tables(summary, data_dir, parquet_string_dtype):
    """The join itself, stated as the join rate rather than as a dtype.

    A dtype equality is a proxy for "these two tables still join"; the merge
    below is that property directly, and it is the one that has to survive a
    pandas upgrade. The dtypes are still asserted underneath it, because a
    mismatch is how the join would fail *silently* - matching nothing and
    raising nothing - which is the failure this pair exists to rule out."""
    playlists = pd.read_parquet(playlists_pq(data_dir))
    membership = pd.read_parquet(membership_pq(data_dir))

    # Every membership row finds its playlist: a 100% join rate.
    joined = membership.merge(playlists, on="playlist_id", how="inner")
    assert len(joined) == len(membership) == FIXTURE_MEMBERSHIP_COUNT

    assert set(membership["playlist_id"]) <= set(playlists["playlist_id"])
    assert membership["playlist_id"].dtype == playlists["playlist_id"].dtype
    assert membership["playlist_id"].dtype == parquet_string_dtype


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
    raw = json.loads(playlist_manifest_path(data_dir).read_text(encoding="utf-8"))

    assert raw["schema_version"] == 3
    assert set(raw) == {
        "source_xml",
        "source_sha256",
        "source_bytes",
        "source_mtime",
        "imported_at",
        "playlist_count",
        "membership_count",
        "playlists_file",
        "membership_file",
        "playlists_sha256",
        "membership_sha256",
        "schema_version",
    }


def test_the_manifest_names_its_two_tables_and_records_their_digests(summary, data_dir):
    """The commit record IS the pointer: two basenames and two digests.

    Recomputed here with hashlib against the files on disk, not read back out
    of the writer. The pair is what lets a reader check the bytes it has just
    read against the generation it decided to read, with no second look at a
    path something else may have changed in between.
    """
    raw = json.loads(playlist_manifest_path(data_dir).read_text(encoding="utf-8"))

    assert raw["playlists_file"] == playlists_pq(data_dir).name
    assert raw["membership_file"] == membership_pq(data_dir).name
    # Basenames, never paths: a data directory has to survive being moved, and
    # a manifest must not be able to point outside the directory it is in.
    assert "/" not in raw["playlists_file"] and "/" not in raw["membership_file"]
    assert raw["playlists_sha256"] == hashlib.sha256(
        playlists_pq(data_dir).read_bytes()
    ).hexdigest()
    assert raw["membership_sha256"] == hashlib.sha256(
        membership_pq(data_dir).read_bytes()
    ).hexdigest()


def test_a_manifest_without_the_table_digests_reads_as_absent(summary, data_dir):
    """A schema-2 record that cannot be checked is not a record worth trusting.

    The two digest keys are read with ``raw[...]`` and not ``raw.get(...)`` on
    purpose: a manifest missing them - hand-edited, or written by something
    that only knew the older shape - would otherwise compare its empty default
    against a real digest, fail, and be reported as a mixed generation. Absent
    is the honest answer, and it is the same one the drawer already renders.
    """
    path = playlist_manifest_path(data_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["membership_sha256"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert read_provenance(data_dir) is None


def test_a_manifest_that_does_not_name_its_tables_reads_as_absent(summary, data_dir):
    """The same rule applied to the two keys schema 3 adds: a record that does
    not say which files it committed cannot be checked against anything, and an
    uncheckable record is not usable."""
    path = playlist_manifest_path(data_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["playlists_file"]
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
    frame = pd.read_parquet(playlists_pq(data_dir)).rename(
        columns={"playlist_id": "id"}
    )
    frame.to_parquet(playlists_pq(data_dir), index=False)
    reseal(data_dir)

    assert read_playlist_tables(data_dir, read_provenance(data_dir)) is None


def test_read_playlist_tables_accepts_a_table_that_has_gained_a_column(
    summary, data_dir
):
    """Subset, not equality: an added column is not a reason to refuse."""
    frame = pd.read_parquet(membership_pq(data_dir))
    frame["added_later"] = 1
    frame.to_parquet(membership_pq(data_dir), index=False)
    reseal(data_dir)

    tables = read_playlist_tables(data_dir, read_provenance(data_dir))

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
    names = set(pd.read_parquet(playlists_pq(data_dir))["name"])
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
    path = playlist_manifest_path(data_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["schema_version"] = PROVENANCE_SCHEMA + 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert read_provenance(data_dir) is None


def test_a_corrupt_provenance_record_reads_as_absent(summary, data_dir):
    (playlist_manifest_path(data_dir)).write_text("{not json", encoding="utf-8")

    assert read_provenance(data_dir) is None


# ---------------------------------------------------------------------------
# Determinism: re-importing an unchanged file is a no-op
# ---------------------------------------------------------------------------


def test_re_importing_an_unchanged_file_writes_identical_tables(xml, data_dir):
    """Same bytes, new names. The CONTENT is deterministic - which is what
    "stable for the same XML" means - while the names cannot repeat, because no
    import ever writes a name another import chose."""
    first = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    first_playlists = playlists_pq(data_dir)
    playlists_bytes = first_playlists.read_bytes()
    membership_bytes = membership_pq(data_dir).read_bytes()

    second = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert playlists_pq(data_dir).read_bytes() == playlists_bytes
    assert membership_pq(data_dir).read_bytes() == membership_bytes
    assert playlists_pq(data_dir) != first_playlists
    assert first.provenance.source_sha256 == second.provenance.source_sha256


def test_the_ids_do_not_move_when_the_file_is_re_imported(xml, data_dir):
    """Re-import must be a no-op, which is what "stable and deterministic for
    the same XML" buys. A positional id would renumber every row."""
    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    before = pd.read_parquet(playlists_pq(data_dir))["playlist_id"].tolist()

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    after = pd.read_parquet(playlists_pq(data_dir))["playlist_id"].tolist()

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
    assert pd.read_parquet(playlists_pq(data_dir)).empty
    assert list(pd.read_parquet(membership_pq(data_dir)).columns) == [
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


def test_the_import_creates_only_the_manifest_and_its_own_two_tables(xml, tmp_path):
    """One import, three files, and no staging debris left beside them."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert sorted(path.name for path in data_dir.iterdir()) == sorted(
        [
            PROVENANCE_FILENAME,
            playlists_pq(data_dir).name,
            membership_pq(data_dir).name,
        ]
    )


def test_the_import_creates_the_data_directory_if_it_is_absent(xml, tmp_path):
    data_dir = tmp_path / "not-yet"

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert playlist_tables_exist(data_dir)


def test_the_manifest_is_beside_the_index_files(tmp_path):
    assert playlist_manifest_path(tmp_path) == tmp_path / "playlist_import.json"


def test_there_are_no_table_paths_before_anything_is_committed(tmp_path):
    """The tables have no fixed names, so "where are they" is a question only
    the manifest can answer - and before an import there is no answer."""
    assert committed_table_paths(tmp_path) is None
    assert not playlist_tables_exist(tmp_path)
