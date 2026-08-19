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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from playlist_fixtures import (
    FIXTURE_REVERSE_INDEX,
    FIXTURE_XML,
    FIXTURE_TRACK_IDS,
    write_fixture_xml,
)

from core.playlist_store import (
    PROVENANCE_FILENAME,
    REAP_GRACE_SECONDS,
    STAGING_SUFFIX,
    committed_table_paths,
    playlist_manifest_path,
    read_provenance,
    reap_superseded_generations,
)
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


@pytest.fixture
def xml_bytes(imported):
    return imported[1].read_bytes()


# ---------------------------------------------------------------------------
# The reverse index
# ---------------------------------------------------------------------------


def full_paths(refs):
    return tuple(ref.full_path for ref in refs)


def playlists_pq(data_dir):
    """The committed playlist table, found the only supported way: through the
    manifest, which is the sole thing that knows what the tables are called."""
    paths = committed_table_paths(data_dir)
    assert paths is not None, "no committed generation in this data directory"
    return paths[0]


def membership_pq(data_dir):
    paths = committed_table_paths(data_dir)
    assert paths is not None, "no committed generation in this data directory"
    return paths[1]


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
    playlists = pd.read_parquet(playlists_pq(service.data_dir))
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
    playlists_pq(data_dir).unlink()

    assert PlaylistService(data_dir).playlists_for("t1") is None


def test_a_corrupt_playlist_table_reads_as_not_imported(imported):
    data_dir, _ = imported
    playlists_pq(data_dir).write_bytes(b"not a parquet file")

    service = PlaylistService(data_dir)
    assert service.imported is False
    assert service.playlists_for("t1") is None


def test_a_missing_provenance_record_reads_as_not_imported(imported):
    """Both tables present with no record of where they came from is a state
    the writer cannot produce, and one whose provenance line would be a lie."""
    data_dir, _ = imported
    playlist_manifest_path(data_dir).unlink()

    assert PlaylistService(data_dir).playlists_for("t1") is None


def test_a_membership_row_naming_an_unknown_playlist_is_skipped(imported, xml_bytes):
    """A dangling row inside an OTHERWISE CONSISTENT generation is stepped over.

    Committed through the real writer rather than by editing the parquet file
    underneath the manifest. Editing it is now a different test entirely - the
    manifest records the digests of the tables it was committed for, so a table
    that has been altered since is a mixed generation and the whole import
    reads as absent (see the mixed-generation tests below). That is the right
    answer for an edited file and the wrong one for the branch this test is
    about, which is the reader stepping over one bad row in a generation that
    is otherwise its own.
    """
    from core.playlist_store import write_playlist_tables
    from processing.playlist_parser import parse_playlists_bytes

    data_dir, _ = imported
    parsed = parse_playlists_bytes(xml_bytes)
    write_playlist_tables(
        data_dir,
        parsed.playlists,
        [*parsed.membership, ("t1", "nope")],
        read_provenance(data_dir),
    )

    assert full_paths(PlaylistService(data_dir).playlists_for("t1")) == (
        ("top level",),
        ("Alpha", "shared name"),
    )


# ---------------------------------------------------------------------------
# Every unusable state is an ANSWER, never an exception
# ---------------------------------------------------------------------------


def reseal(data_dir):
    """Rewrite the manifest so its table digests match whatever is on disk now.

    Needed by every test below that damages a TABLE. The manifest records the
    digests of the two tables it was committed for, so a damaged table is a
    mixed generation and is refused by that guard alone - which would leave the
    guard the test is actually about (the parquet read, the column check, the
    index build) never running, and the test passing for the wrong reason.

    Resealing puts the damaged table inside a generation that is consistent
    with its own manifest, which is the only way to ask what the deeper guards
    do. It is exactly the state a future schema change - or PR 3b - produces:
    files that were committed together and that this build cannot read.
    """
    path = playlist_manifest_path(data_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["playlists_sha256"] = hashlib.sha256(
        playlists_pq(data_dir).read_bytes()
    ).hexdigest()
    raw["membership_sha256"] = hashlib.sha256(
        membership_pq(data_dir).read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(raw), encoding="utf-8")


def _no_manifest(data_dir):
    playlist_manifest_path(data_dir).unlink()


def _corrupt_manifest(data_dir):
    playlist_manifest_path(data_dir).write_text("{not json", encoding="utf-8")


def _unknown_schema(data_dir):
    path = playlist_manifest_path(data_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["schema_version"] = 99
    path.write_text(json.dumps(raw), encoding="utf-8")


def _truncated_table(data_dir):
    path = playlists_pq(data_dir)
    path.write_bytes(path.read_bytes()[:120])
    reseal(data_dir)


def _renamed_playlist_columns(data_dir):
    """A VALID parquet whose columns are not the ones this build reads.

    THE BLOCKER. This used to reach ``_build_refs`` and raise AttributeError
    out of ``row.playlist_id``, which is a 500 on ``GET /api/tracks/{id}`` -
    the request the drawer makes for everything, so a schema change did not
    merely lose playlists, it broke track detail outright.
    """
    frame = pd.read_parquet(playlists_pq(data_dir)).rename(
        columns={"playlist_id": "id", "entries": "entry_count"}
    )
    frame.to_parquet(playlists_pq(data_dir), index=False)
    reseal(data_dir)


def _renamed_membership_columns(data_dir):
    frame = pd.read_parquet(membership_pq(data_dir)).rename(
        columns={"track_id": "track", "playlist_id": "playlist"}
    )
    frame.to_parquet(membership_pq(data_dir), index=False)
    reseal(data_dir)


def _unusable_values_in_the_right_columns(data_dir):
    """The columns are all present and hold something no reader can use."""
    frame = pd.read_parquet(playlists_pq(data_dir))
    frame["entries"] = "not a number"
    frame.to_parquet(playlists_pq(data_dir), index=False)
    reseal(data_dir)


UNUSABLE_STATES = [
    ("missing manifest", _no_manifest),
    ("corrupt manifest", _corrupt_manifest),
    ("unknown schema_version", _unknown_schema),
    ("truncated parquet bytes", _truncated_table),
    ("valid parquet, renamed playlist columns", _renamed_playlist_columns),
    ("valid parquet, renamed membership columns", _renamed_membership_columns),
    ("right columns, unusable values", _unusable_values_in_the_right_columns),
]


@pytest.mark.parametrize(
    "damage", [pytest.param(fn, id=label) for label, fn in UNUSABLE_STATES]
)
def test_every_unusable_state_degrades_to_not_imported_rather_than_raising(
    imported, damage
):
    """One list, one assertion: none of these may reach the caller as an error.

    ``lookup`` is what ``CocoApi._detail`` calls on every drawer open, so an
    exception escaping here is a 500 on the endpoint that carries the whole of
    track detail - not a missing playlist section, a missing drawer.
    """
    data_dir, _ = imported
    damage(data_dir)

    service = PlaylistService(data_dir)
    result = service.lookup("t1")

    assert result.imported is False
    assert result.playlists is None
    assert result.provenance is None
    assert service.playlists_for("t1") is None
    assert service.track_count == 0


def test_a_schema_that_merely_ADDS_a_column_is_still_read(imported):
    """Degrading is for what cannot be read, not for anything unfamiliar.

    The column check is a subset test on purpose: a later schema that adds a
    column should not cost this build the playlists it can still understand.
    """
    data_dir, _ = imported
    frame = pd.read_parquet(playlists_pq(data_dir))
    frame["colour"] = "chartreuse"
    frame.to_parquet(playlists_pq(data_dir), index=False)
    reseal(data_dir)

    assert full_paths(PlaylistService(data_dir).playlists_for("t1")) == (
        ("top level",),
        ("Alpha", "shared name"),
    )


# ---------------------------------------------------------------------------
# An interrupted import cannot be reported as imported - and no longer costs
# the user the import that was already there
# ---------------------------------------------------------------------------


class _RecordingOs:
    """The real ``os``, except that ``replace`` is counted and can be refused.

    ``allow=0`` stands in for a process that died before its commit; the
    recorded destinations are how a test says WHICH files a commit replaces,
    which is the property the whole layout rests on.
    """

    def __init__(self, allow):
        self._allow = allow
        self.replaced = []

    def __getattr__(self, name):
        return getattr(os, name)

    def replace(self, src, dst):
        if len(self.replaced) >= self._allow:
            raise _Interrupted(f"killed before os.replace #{len(self.replaced) + 1}")
        self.replaced.append(Path(dst))
        return os.replace(src, dst)


class _Interrupted(RuntimeError):
    pass


def _import_generation_b(data_dir, xml, monkeypatch, allow):
    """Rename one playlist and re-import, allowing ``allow`` commit steps.

    Renaming mints a NEW playlist_id, so a table from B beside a table from A
    would leave dangling membership rows and silently drop that playlist from
    every track that was in it - which is what would make a blended generation
    visible at all rather than merely theoretical.

    Returns the ``_RecordingOs``, so a caller can ask what was replaced.
    """
    import core.playlist_store as store

    xml.write_text(
        FIXTURE_XML.replace('Name="top level"', 'Name="renamed top"'),
        encoding="utf-8",
    )
    recorder = _RecordingOs(allow)
    monkeypatch.setattr(store, "os", recorder)
    if allow:
        import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    else:
        with pytest.raises(_Interrupted):
            import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    monkeypatch.undo()
    return recorder


def test_the_commit_replaces_the_manifest_AND_NOTHING_ELSE(imported, monkeypatch):
    """The property the whole layout rests on, asserted as one number.

    An import writes its two tables under names it claimed for itself, so they
    are invisible until something points at them; the only file it replaces is
    the manifest, and ``os.replace`` is atomic per file on one filesystem. One
    replace means the commit is one step, and a step cannot be half done.

    The previous design replaced three files in a fixed order and could only
    promise that a reader would DETECT the states in between. There are now no
    states in between.
    """
    data_dir, xml = imported

    recorder = _import_generation_b(data_dir, xml, monkeypatch, allow=3)

    assert [path.name for path in recorder.replaced] == [PROVENANCE_FILENAME]


def test_an_import_killed_before_it_commits_leaves_THE_PREVIOUS_ONE_INTACT(
    imported, monkeypatch
):
    """And this is what the single replace buys the user.

    The previous design's honest cost was that an interrupted import lost the
    import before it too: it had already overwritten one of the two tables, and
    nothing could tell which half of the pair was old. Here it never touched
    them, so the answer is not "nothing imported" - it is the generation that
    was already there, whole, still readable, still with its own provenance.
    """
    data_dir, xml = imported
    before = playlists_pq(data_dir).read_bytes()

    _import_generation_b(data_dir, xml, monkeypatch, allow=0)

    service = PlaylistService(data_dir)
    assert service.imported is True
    assert full_paths(service.playlists_for("t1")) == (
        ("top level",),
        ("Alpha", "shared name"),
    )
    assert service.provenance.source_name == "export.xml"
    assert playlists_pq(data_dir).read_bytes() == before


def test_an_import_interrupted_AT_ITS_COMMIT_leaves_only_inert_debris(
    imported, monkeypatch
):
    """The deliberate cost of never undoing a commit that may have happened.

    Cleanup used to cover the ``os.replace`` itself, and an exception surfacing
    there deleted the two tables the manifest had just started naming. It could
    not do otherwise: it had no way to know whether the rename had landed, and
    it guessed "no". This guesses the other way, and only ``OSError`` - which
    ``rename`` raises only when it changed nothing - is treated as proof.

    So an interrupt at the commit is no longer tidy, and it is no longer
    destructive either. What it leaves is exactly what a ``SIGKILL`` at the
    same instant leaves, because a ``SIGKILL`` runs no handler at all: two
    table files and a staged manifest that no pointer names. Nothing reads
    them, and the reaper takes them.
    """
    data_dir, xml = imported
    before = {path.name for path in data_dir.iterdir()}

    _import_generation_b(data_dir, xml, monkeypatch, allow=0)

    # The import that was already there is untouched and still the one on disk.
    service = PlaylistService(data_dir)
    assert service.provenance.source_name == "export.xml"
    assert full_paths(service.playlists_for("t1")) == (
        ("top level",),
        ("Alpha", "shared name"),
    )

    # What is left over is named by nothing.
    debris = {path.name for path in data_dir.iterdir()} - before
    assert debris, "the interrupted import did claim its names, or nothing is proved"
    assert debris.isdisjoint(
        {service.provenance.playlists_file, service.provenance.membership_file}
    )

    # ...and it is the reaper's, once it is nobody's in-flight work.
    for path in data_dir.iterdir():
        stamp = os.stat(path).st_mtime - (REAP_GRACE_SECONDS + 60)
        os.utime(path, (stamp, stamp))
    reap_superseded_generations(data_dir)

    assert {path.name for path in data_dir.iterdir()} == before
    assert sorted(p.name for p in data_dir.glob("*" + STAGING_SUFFIX)) == []
    assert PlaylistService(data_dir).provenance.source_name == "export.xml"


def test_a_write_that_fails_partway_still_cleans_up_after_itself(
    imported, monkeypatch
):
    """The debris case the previous design missed.

    It appended each staged path to its cleanup list AFTER the write returned,
    so a write that created a partial file and then raised left that file
    behind - the ``finally`` had never heard of it. Every path is now
    registered before anything is written to it, so the cleanup covers a write
    that dies in the middle as well as one that never started.
    """
    import core.playlist_store as store

    data_dir, xml = imported
    before = sorted(path.name for path in data_dir.iterdir())
    real_to_parquet = pd.DataFrame.to_parquet

    def dies_partway(frame, path, *args, **kwargs):
        Path(path).write_bytes(b"PAR1 half a file and then")
        raise _Interrupted("the disk filled up mid-write")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", dies_partway)
    with pytest.raises(_Interrupted):
        import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
    monkeypatch.undo()
    assert real_to_parquet is pd.DataFrame.to_parquet

    assert sorted(path.name for path in data_dir.iterdir()) == before


def test_re_running_the_import_commits_the_new_generation(imported, monkeypatch):
    """What the drawer tells the user to run has to work after a failed one."""
    data_dir, xml = imported
    _import_generation_b(data_dir, xml, monkeypatch, allow=0)

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert full_paths(PlaylistService(data_dir).playlists_for("t1")) == (
        ("renamed top",),
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
    before = playlists_pq(data_dir).read_bytes()

    service = PlaylistService(data_dir)
    assert service.staleness().stale is True
    service.lookup("t1")

    assert playlists_pq(data_dir).read_bytes() == before
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
