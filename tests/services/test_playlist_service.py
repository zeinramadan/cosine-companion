"""PlaylistService: the reverse index, the four degraded states, staleness.

The fixture expectations come from ``playlist_fixtures.FIXTURE_REVERSE_INDEX``,
which is written out by hand from the XML literal beside it - the reverse index
is the thing under test, so deriving the expectation from the parse would prove
nothing.

The real-library case is guarded like ``tests/services/golden/``: the export
and the index are both gitignored, so absent means skip, and a different export
at the same path also means skip rather than fail.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from playlist_fixtures import (
    FIXTURE_REVERSE_INDEX,
    FIXTURE_TRACK_IDS,
    write_fixture_xml,
)

from core.playlist_store import PLAYLISTS_FILENAME, PROVENANCE_FILENAME
from services.playlist_import import import_playlists
from services.playlist_service import (
    IMPORT_COMMAND,
    PlaylistRef,
    PlaylistService,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXED_CLOCK = datetime(2026, 8, 19, 14, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def imported(tmp_path):
    """A data directory with the fixture export imported into it."""
    xml = write_fixture_xml(tmp_path / "export.xml")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    pd.DataFrame({"track_id": list(FIXTURE_TRACK_IDS)}).to_parquet(
        data_dir / "meta.parquet", index=False
    )
    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    return data_dir, xml


@pytest.fixture
def service(imported):
    return PlaylistService(imported[0])


# ---------------------------------------------------------------------------
# The reverse index
# ---------------------------------------------------------------------------


def full_paths(refs):
    return tuple(ref.full_path for ref in refs)


@pytest.mark.parametrize("track_id", sorted(FIXTURE_REVERSE_INDEX))
def test_every_tracks_playlists_are_the_hand_written_ones(service, track_id):
    """One case per track, so a failure names the track rather than the dict."""
    assert full_paths(service.playlists_for(track_id)) == FIXTURE_REVERSE_INDEX[
        track_id
    ]


def test_a_track_in_two_playlists_gets_both_in_document_order(service):
    """``t1`` is in ``top level`` and in ``Alpha / shared name``, in that order
    in the file. Export order, not alphabetical: sorting by name would put the
    two ``shared name`` playlists in unrelated places."""
    assert full_paths(service.playlists_for("t1")) == (
        ("top level",),
        ("Alpha", "shared name"),
    )


def test_the_two_playlists_sharing_a_leaf_name_are_told_apart_by_path(service):
    """This is the whole reason ``folder_path`` reaches the drawer."""
    first = service.playlists_for("t1")[1]
    second = service.playlists_for("t2")[1]

    assert first.name == second.name == "shared name"
    assert first.folder_path == ("Alpha",)
    assert second.folder_path == ("Beta",)
    assert first.playlist_id != second.playlist_id


def test_a_folder_name_with_a_slash_arrives_as_one_segment(service):
    ref = service.playlists_for("t3")[0]

    assert ref.folder_path == ("Alpha", "Collections/Hauls", "deep", "deeper")
    assert ref.name == "five deep"


def test_a_playlist_ref_carries_its_total_entry_count(service):
    """The size from the export, not how many of its tracks are indexed."""
    top = service.playlists_for("t1")[0]

    assert top == PlaylistRef(
        playlist_id=top.playlist_id, name="top level", folder_path=(), entries=2
    )


def test_an_indexed_track_in_no_playlist_gets_an_empty_tuple(service):
    """NOT ``None``: the tables exist, this track is simply in nothing.

    Reachable with real data - 8 of the 1,532 indexed tracks are in zero
    playlists - and reachable here without one.
    """
    assert service.playlists_for("t-not-in-any") == ()
    assert service.playlists_for("t-not-in-any") is not None


def test_an_unresolvable_entry_is_still_in_the_index(service):
    """``t999`` is not in the collection. Its membership is recorded anyway, so
    a later reindex that adds the track picks it up without a re-import."""
    assert full_paths(service.playlists_for("t999")) == (("Beta", "dangling"),)


def test_the_path_keyed_playlist_contributes_no_membership(service):
    """It is catalogued in the table, but nothing can be a member of it."""
    playlists = pd.read_parquet(Path(service.data_dir) / PLAYLISTS_FILENAME)
    assert "by path" in set(playlists["name"])

    every_ref = {
        ref.name
        for track_id in FIXTURE_REVERSE_INDEX
        for ref in service.playlists_for(track_id)
    }
    assert "by path" not in every_ref


def test_the_index_covers_every_track_the_membership_names(service):
    assert service.track_count == len(FIXTURE_REVERSE_INDEX) == 5


def test_the_lookup_result_is_a_dataclass_not_a_dict(service):
    """The other six services return dataclasses; so does this one."""
    lookup = service.lookup("t1")

    assert lookup.imported is True
    assert lookup.count == 2
    assert full_paths(lookup.playlists) == FIXTURE_REVERSE_INDEX["t1"]
    assert lookup.provenance.source_name == "export.xml"
    assert lookup.staleness.stale is False
    assert not isinstance(lookup, dict)


# ---------------------------------------------------------------------------
# The four degraded states
# ---------------------------------------------------------------------------


def test_nothing_imported_yet_reads_as_none_not_as_empty(tmp_path):
    """The distinction the drawer renders as two different screens."""
    service = PlaylistService(tmp_path / "never-imported")

    assert service.imported is False
    assert service.playlists_for("t1") is None
    assert service.provenance is None
    assert service.lookup("t1").imported is False


def test_a_data_directory_that_does_not_exist_is_not_an_error(tmp_path):
    service = PlaylistService(tmp_path / "no" / "such" / "place")

    assert service.playlists_for("anything") is None


def test_construction_reads_nothing(tmp_path):
    """Building the API on a machine with no library must be free."""
    service = PlaylistService(tmp_path / "data")

    assert service._loaded is False


def test_a_membership_table_with_no_playlist_table_reads_as_not_imported(imported):
    data_dir, _ = imported
    (data_dir / PLAYLISTS_FILENAME).unlink()

    assert PlaylistService(data_dir).playlists_for("t1") is None


def test_a_corrupt_playlist_table_reads_as_not_imported(imported):
    data_dir, _ = imported
    (data_dir / PLAYLISTS_FILENAME).write_bytes(b"not a parquet file")

    service = PlaylistService(data_dir)
    assert service.imported is False
    assert service.playlists_for("t1") is None


def test_a_missing_provenance_record_reads_as_not_imported(imported):
    """Both tables present with no record of where they came from is a state
    the writer cannot produce, and one whose provenance line would be a lie."""
    data_dir, _ = imported
    (data_dir / PROVENANCE_FILENAME).unlink()

    assert PlaylistService(data_dir).playlists_for("t1") is None


def test_a_membership_row_naming_an_unknown_playlist_is_skipped(imported):
    """Hand-edited or half-written files, not something the writer produces."""
    from core.playlist_store import MEMBERSHIP_FILENAME

    data_dir, _ = imported
    membership = pd.read_parquet(data_dir / MEMBERSHIP_FILENAME)
    membership.loc[len(membership)] = {"track_id": "t1", "playlist_id": "nope"}
    membership.to_parquet(data_dir / MEMBERSHIP_FILENAME, index=False)

    assert full_paths(PlaylistService(data_dir).playlists_for("t1")) == (
        ("top level",),
        ("Alpha", "shared name"),
    )


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def test_an_unchanged_source_is_not_stale(service):
    verdict = service.staleness()

    assert verdict.stale is False
    assert verdict.source_missing is False
    assert verdict.reason == ""


def test_a_changed_source_is_stale_and_names_the_command(imported):
    data_dir, xml = imported
    xml.write_text(
        xml.read_text(encoding="utf-8").replace("top level", "renamed"),
        encoding="utf-8",
    )

    verdict = PlaylistService(data_dir).staleness()

    assert verdict.stale is True
    assert verdict.source_missing is False
    assert "export.xml" in verdict.reason
    assert IMPORT_COMMAND in verdict.reason


def test_a_same_size_edit_that_preserves_mtime_is_still_detected(imported):
    """The reason the check is a digest and not mtime-and-size.

    ``Alpha`` and ``Zebra`` are both five letters, so renaming the folder
    leaves the byte count identical, and the mtime is restored afterwards to
    the nanosecond. An mtime-and-size check calls this file fresh. It is not,
    and a drawer confidently listing a folder that no longer exists is the
    failure this feature is meant to prevent.
    """
    import os

    data_dir, xml = imported
    before = xml.stat()
    original = xml.read_text(encoding="utf-8")
    changed = original.replace("Alpha", "Zebra")
    assert changed != original, "the edit did not apply"
    assert len(changed.encode()) == len(original.encode()), "the edit changed the size"

    xml.write_text(changed, encoding="utf-8")
    os.utime(xml, ns=(before.st_atime_ns, before.st_mtime_ns))

    after = xml.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns

    assert PlaylistService(data_dir).staleness().stale is True


def test_a_source_that_has_been_deleted_is_reported_not_crashed(imported):
    """Spec §6.5: show provenance plus a note; do not crash."""
    data_dir, xml = imported
    xml.unlink()

    service = PlaylistService(data_dir)
    verdict = service.staleness()

    assert verdict.source_missing is True
    assert verdict.stale is False
    assert "export.xml" in verdict.reason
    # The playlists themselves are still answerable.
    assert service.playlists_for("t1") is not None
    assert service.provenance.source_name == "export.xml"


def test_staleness_before_any_import_is_silent(tmp_path):
    verdict = PlaylistService(tmp_path / "nothing").staleness()

    assert verdict == type(verdict)()
    assert verdict.reason == ""


def test_the_service_never_imports_on_its_own(imported):
    """Spec §6.4: prompt, never auto-import. A stale verdict must leave the
    tables exactly as they were."""
    data_dir, xml = imported
    xml.write_text(
        xml.read_text(encoding="utf-8").replace("top level", "renamed"),
        encoding="utf-8",
    )
    before = (data_dir / PLAYLISTS_FILENAME).read_bytes()

    service = PlaylistService(data_dir)
    assert service.staleness().stale is True
    service.lookup("t1")

    assert (data_dir / PLAYLISTS_FILENAME).read_bytes() == before
    assert full_paths(service.playlists_for("t1"))[0] == ("top level",)


def test_reload_picks_up_a_fresh_import(imported):
    data_dir, xml = imported
    service = PlaylistService(data_dir)
    assert service.playlists_for("t1") is not None

    xml.write_text(
        xml.read_text(encoding="utf-8").replace('Name="top level"', 'Name="renamed"'),
        encoding="utf-8",
    )
    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    service.reload()

    assert full_paths(service.playlists_for("t1"))[0] == ("renamed",)


# ---------------------------------------------------------------------------
# The real library
# ---------------------------------------------------------------------------

REAL_EXPORT_NAME = "library_export_190826.xml"
REAL_EXPORT_SHA256 = (
    "6f868f1851a39559be672042d0a2ac560baf96e2d48d4f8d2bb9ffdcc98ac2e6"
)

#: Measured with a standalone lxml + pandas script against
#: ``data/meta.parquet``'s 1,532 track ids. NOT the plan's 514 / 11.01%: that
#: was measured when the library held 1,307 tracks and is superseded.
REAL_INDEXED_TRACKS = 1532
REAL_MEMBERSHIP = 4669
REAL_RESOLVED = 4516
REAL_UNRESOLVED = 153
REAL_TRACKS_WITH_PLAYLISTS = 1524
REAL_TRACKS_WITHOUT_PLAYLISTS = 8

#: ``Fireground - Never Sleep``, the track with the most playlists.
REAL_BUSIEST_TRACK_ID = "192072736"
REAL_BUSIEST_COUNT = 21
#: Its 21 full paths, in the export's document order. Note the two
#: ``Hardgroove + Minimal Grooves`` entries under DIFFERENT parents: rendering
#: leaf names alone would show this track two identical rows.
REAL_BUSIEST_PATHS = (
    ("Cosine Companion", "never sleep"),
    ("timo&co", "biscuit (funk)", "Hardgroove + Minimal Grooves"),
    ("timo&co", "biscuit (funk)", "candidate"),
    ("timo&co", "biscuit (funk)", "peak tribal/hardgroove crate"),
    ("timo&co", "biscuit (funk)", "funk to minimal grooves"),
    ("timo&co", "biscuit (funk)", "biscuit techno crate"),
    ("timo&co", "biscuit (funk)", "biscuit techno draft"),
    ("timo&co", "biscuit (funk)", "funktech 1"),
    ("timo&co", "melodic tracks"),
    ("favorite tracks",),
    ("Mischief", "08/2026", "Peak"),
    ("Mischief", "08/2026", "Crate"),
    ("Mischief", "Blocks", "jazzy /melodic/techno"),
    ("Mischief", "Blocks", "never sleep"),
    ("Mischief", "Collections/Hauls", "biscuit (funk)", "Hardgroove + Minimal Grooves"),
    ("Mischief", "Collections/Hauls", "biscuit (funk)", "candidate"),
    ("Mischief", "Collections/Hauls", "biscuit (funk)", "peak tribal/hardgroove crate"),
    ("Mischief", "Collections/Hauls", "biscuit (funk)", "funk to minimal grooves"),
    ("Mischief", "Collections/Hauls", "biscuit (funk)", "biscuit techno crate"),
    ("Mischief", "Collections/Hauls", "biscuit (funk)", "biscuit techno draft"),
    ("Mischief", "Collections/Hauls", "biscuit (funk)", "funktech 1"),
)

#: The eight indexed tracks in zero playlists, sorted. Their existence
#: falsifies spec §6.5's "every one of the indexed tracks is in at least one
#: playlist", which was true of the 1,307-track library.
REAL_TRACKS_IN_NO_PLAYLIST = (
    "13213231",
    "149296216",
    "220974589",
    "249497337",
    "252962046",
    "263627393",
    "31589091",
    "69965747",
)


@pytest.fixture(scope="module")
def real_import(tmp_path_factory):
    """The real export imported into a TEMPORARY directory.

    Never into ``data/``: these tests must not write to the maintainer's
    library. ``meta.parquet`` is COPIED in so the resolution counts are against
    the real 1,532 tracks.
    """
    from config import DATA

    export = Path(DATA) / REAL_EXPORT_NAME
    meta = Path(DATA) / "meta.parquet"
    if not export.is_file() or not meta.is_file():
        pytest.skip(
            f"the real export ({export}) or the real meta.parquet ({meta}) is "
            "not present: data/ is gitignored, so these assertions only run on "
            "a developer machine with both. The fixture cases above guard the "
            "service everywhere, including CI."
        )

    found = hashlib.sha256(export.read_bytes()).hexdigest()
    if found != REAL_EXPORT_SHA256:
        pytest.skip(
            f"{export} is not the export these numbers were measured against. "
            f"Expected sha256 {REAL_EXPORT_SHA256}, found {found}. Re-measure "
            "and update the REAL_* values in this file if it was deliberately "
            "replaced."
        )

    indexed = set(pd.read_parquet(meta, columns=["track_id"])["track_id"].astype(str))
    if len(indexed) != REAL_INDEXED_TRACKS:
        pytest.skip(
            f"the real library holds {len(indexed)} tracks, not the "
            f"{REAL_INDEXED_TRACKS} these resolution counts were measured "
            "against. Reindexing changes them; re-measure before asserting."
        )

    data_dir = tmp_path_factory.mktemp("real-playlists")
    import shutil

    shutil.copy(meta, data_dir / "meta.parquet")
    summary = import_playlists(export, data_dir=data_dir, now=FIXED_CLOCK)
    return PlaylistService(data_dir), summary, indexed


def test_the_real_export_resolves_the_measured_number_of_entries(real_import):
    _, summary, _ = real_import

    assert summary.entries_total == REAL_MEMBERSHIP
    assert summary.entries_resolved == REAL_RESOLVED
    assert summary.entries_unresolved == REAL_UNRESOLVED
    assert summary.indexed_tracks == REAL_INDEXED_TRACKS
    assert summary.tracks_with_playlists == REAL_TRACKS_WITH_PLAYLISTS
    assert round(summary.unresolved_percent, 2) == 3.28


def test_the_busiest_real_track_gets_all_twenty_one_of_its_playlists(real_import):
    """``Fireground - Never Sleep``. The drawer has to render this gracefully."""
    service, _, _ = real_import

    found = service.playlists_for(REAL_BUSIEST_TRACK_ID)

    assert len(found) == REAL_BUSIEST_COUNT
    assert full_paths(found) == REAL_BUSIEST_PATHS


def test_the_busiest_real_track_has_two_playlists_with_the_same_leaf_name(real_import):
    """Rendered as leaf names, two of its 21 rows would read identically."""
    service, _, _ = real_import

    names = [ref.name for ref in service.playlists_for(REAL_BUSIEST_TRACK_ID)]

    assert names.count("Hardgroove + Minimal Grooves") == 2
    paths = full_paths(service.playlists_for(REAL_BUSIEST_TRACK_ID))
    assert len(set(paths)) == REAL_BUSIEST_COUNT


def test_eight_real_indexed_tracks_are_in_no_playlist_at_all(real_import):
    """Falsifies spec §6.5's claim that the empty state is unreachable with
    real data. It was true of the 1,307-track library and is not true now."""
    service, _, indexed = real_import

    without = tuple(
        sorted(
            track_id
            for track_id in indexed
            if service.playlists_for(track_id) == ()
        )
    )

    assert without == REAL_TRACKS_IN_NO_PLAYLIST
    assert len(without) == REAL_TRACKS_WITHOUT_PLAYLISTS


def test_every_real_indexed_track_gets_an_answer(real_import):
    """1,532 lookups, none of which may be ``None`` once an import exists."""
    service, _, indexed = real_import

    assert all(service.playlists_for(track_id) is not None for track_id in indexed)
    assert (
        sum(len(service.playlists_for(track_id)) for track_id in indexed)
        == REAL_RESOLVED
    )


def test_the_real_import_is_not_stale_against_its_own_source(real_import):
    service, _, _ = real_import

    assert service.staleness().stale is False
    assert service.provenance.source_name == REAL_EXPORT_NAME
