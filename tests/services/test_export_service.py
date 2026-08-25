"""Characterisation tests for ExportService.

**What changed and why.** These tests used to diff the service's output against
``recommendations.playlist_exporter``'s two functions. That was meaningful only
while the service carried its own copy of the export loops - and carrying that
copy was the defect. Now the service *orchestrates* those functions, so diffing
against them would compare a thing with itself. The expectations therefore come
from ``golden/export_fixture.json``: committed playlist filenames and committed
ordered track ids, from which the exact bytes are reconstructed.

The legacy comparison survives where it still means something: as a check that
driving the pure exporter directly and driving it through the service produce
the same files, which is what proves the service adds no behaviour of its own.

Known defects are pinned as CURRENT behaviour: tracks whose audio file is
missing are silently skipped, and combined mode reports no playlists_created
key (which is why the tab raises KeyError and shows no completion dialog -
inventory defect #10).
"""

import threading
from pathlib import Path

import pytest

from fixture_library import GOLDEN_SEEDS, load_golden
from recommendations.playlist_exporter import (
    export_recommendations_as_playlists,
    export_single_playlist,
    playlist_filename,
)
from services.export_service import ExportResult, ExportService

GOLDEN = load_golden("export_fixture")

REAL_SEEDS = ["64638770", "24614611", "36999061"]


@pytest.fixture
def service(fixture_library):
    return ExportService(fixture_library)


@pytest.fixture
def real_service(real_library):
    return ExportService(real_library)


def m3u_bytes(library, track_ids):
    """The exact file create_m3u_playlist writes for these ids, from meta."""
    lines = ["#EXTM3U"]
    for track_id in track_ids:
        track = library.meta_ix.loc[track_id]
        path_local = track["path_local"]
        if not path_local or not Path(path_local).exists():
            continue  # silently skipped, exactly as the writer does
        lines.append(f"#EXTINF:-1,{track['artist']} - {track['title']}")
        lines.append(path_local)
    return ("\n".join(lines) + "\n").encode("utf-8")


def tree(directory):
    return {p.name: p.read_bytes() for p in sorted(Path(directory).glob("*.m3u"))}


# --------------------------------------------------------------------------
# Golden: exact filenames and exact bytes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("per_track", sorted(GOLDEN["per_seed"], key=int))
def test_per_seed_output_matches_the_golden_files(fixture_library, service, tmp_path, per_track):
    expected = GOLDEN["per_seed"][per_track]
    out = tmp_path / f"out{per_track}"

    result = service.export_per_seed(GOLDEN_SEEDS, str(out), int(per_track))

    written = tree(out)
    assert sorted(written) == sorted(expected), "playlist filenames drifted"
    for filename, track_ids in expected.items():
        assert written[filename] == m3u_bytes(fixture_library, track_ids), filename
    assert result.playlists_created == len(expected)


@pytest.mark.parametrize("per_track", sorted(GOLDEN["combined"], key=int))
def test_combined_output_matches_the_golden_file(fixture_library, service, tmp_path, per_track):
    expected_ids = GOLDEN["combined"][per_track]
    out = tmp_path / f"combined{per_track}.m3u"

    result = service.export_combined(GOLDEN_SEEDS, str(out), int(per_track))

    assert out.read_bytes() == m3u_bytes(fixture_library, expected_ids)
    assert result.total_recommendations == len(expected_ids)


def test_the_golden_export_is_not_empty():
    """Guard the guard: an empty golden would make the assertions vacuous."""
    assert GOLDEN["per_seed"]["2"]
    assert all(ids for ids in GOLDEN["per_seed"]["2"].values())
    assert GOLDEN["combined"]["2"]


# --------------------------------------------------------------------------
# The service adds no behaviour of its own
# --------------------------------------------------------------------------


def test_service_and_direct_call_produce_identical_files(fixture_library, service, tmp_path):
    """Not a tautology: it is what makes 'orchestrates, does not reimplement'
    checkable. The service must be a pass-through plus a snapshot."""
    direct = tmp_path / "direct"
    through_service = tmp_path / "service"

    direct_stats = export_recommendations_as_playlists(
        GOLDEN_SEEDS, str(direct), 5,
        fixture_library.meta_ix, fixture_library.emb_ix, fixture_library.index,
    )
    result = service.export_per_seed(GOLDEN_SEEDS, str(through_service), 5)

    assert tree(through_service) == tree(direct)
    assert result.as_legacy_stats() == direct_stats


def test_service_and_direct_call_produce_identical_combined_files(fixture_library, service, tmp_path):
    direct = tmp_path / "direct.m3u"
    through_service = tmp_path / "service.m3u"

    direct_stats = export_single_playlist(
        GOLDEN_SEEDS, str(direct), "Cosine Recommendations",
        fixture_library.meta_ix, fixture_library.emb_ix, fixture_library.index, 5,
    )
    result = service.export_combined(GOLDEN_SEEDS, str(through_service), 5)

    assert through_service.read_bytes() == direct.read_bytes()
    assert result.as_legacy_stats() == direct_stats


def _spy_on_both_loops(monkeypatch):
    """Replace BOTH exporter loops with recorders. Returns the call log.

    Each records under its own name, so a service method that called the WRONG
    loop, or BOTH loops, or neither, is visible in the log rather than silently
    passing.

    What the call log alone canNOT show is a service that calls the right loop
    AND ALSO does inlined work of its own - the log would still read
    ``["per_seed"]``. That gap is covered separately, by
    test_neither_export_mode_writes_anything_itself (no bytes reach disk when
    the loops are stubbed out) and
    test_neither_export_mode_ranks_or_writes_playlists_itself (the service never
    calls the ranking policy or the M3U writer directly).
    """
    import services.export_service as module

    calls = []

    def per_seed(*a, **k):
        calls.append(("per_seed", a, k))
        return {"total_tracks": 1, "successful": 1, "failed": 0,
                "playlists_created": 1, "total_recommendations": 3}

    def combined(*a, **k):
        calls.append(("combined", a, k))
        # No playlists_created key: combined mode's shape (defect #10).
        return {"total_tracks": 1, "successful": 1, "failed": 0,
                "total_recommendations": 3}

    monkeypatch.setattr(module, "export_recommendations_as_playlists", per_seed)
    monkeypatch.setattr(module, "export_single_playlist", combined)
    return calls


def test_export_per_seed_calls_the_per_seed_loop_exactly_once_and_not_the_other(
    service, fixture_library, tmp_path, monkeypatch
):
    """The loops live in recommendations.playlist_exporter; export_per_seed
    calls the per-seed one exactly once and never touches the combined one.

    Named for what it proves. It does NOT prove the absence of extra inlined
    work in the service - the two tests at the end of this section do that."""
    calls = _spy_on_both_loops(monkeypatch)

    result = service.export_per_seed(["f01"], str(tmp_path / "o"), 3)

    assert [c[0] for c in calls] == ["per_seed"]
    assert result.playlists_created == 1


def test_export_combined_calls_the_combined_loop_exactly_once_and_not_the_other(
    service, fixture_library, tmp_path, monkeypatch
):
    """The other half of the pair above, which used to go uncovered: the test
    claimed both loops but only ever spied on the per-seed exporter."""
    calls = _spy_on_both_loops(monkeypatch)

    result = service.export_combined(["f01"], str(tmp_path / "o.m3u"), 3)

    assert [c[0] for c in calls] == ["combined"]
    # Combined mode carries no playlists_created, and the service must not
    # invent one (defect #10 survives the extraction).
    assert result.playlists_created is None
    assert "playlists_created" not in result.as_legacy_stats()


def test_neither_export_mode_calls_the_other_loop(service, tmp_path, monkeypatch):
    """Stated once, over both modes: exactly one loop call per export, and it is
    the one belonging to that mode."""
    calls = _spy_on_both_loops(monkeypatch)

    service.export_per_seed(["f01"], str(tmp_path / "o"), 3)
    service.export_combined(["f01"], str(tmp_path / "o.m3u"), 3)

    assert [c[0] for c in calls] == ["per_seed", "combined"]


def test_neither_export_mode_writes_anything_itself(service, tmp_path, monkeypatch):
    """The anti-inlining check the call-log spies cannot make.

    With both loops stubbed out to write nothing, an ExportService that only
    orchestrates leaves the filesystem untouched. A service that had grown its
    own inlined copy of the loop - ranking, filename sanitisation and the M3U
    write - would put bytes on disk here even though the call log still read
    ["per_seed"] or ["combined"].
    """
    _spy_on_both_loops(monkeypatch)
    out_dir = tmp_path / "per_seed_out"
    out_dir.mkdir()
    combined = tmp_path / "combined_out.m3u"

    service.export_per_seed(["f01", "f02"], str(out_dir), 3)
    service.export_combined(["f01", "f02"], str(combined), 3)

    assert list(out_dir.iterdir()) == [], "export_per_seed wrote files of its own"
    assert not combined.exists(), "export_combined wrote a file of its own"


def test_export_service_imports_only_the_two_loops_from_the_export_layer():
    """The static half of the anti-inlining check, and the sound one.

    An inlined loop has to get its pieces from somewhere. The only sources are
    ``recommendations.ranking`` (the single ranking policy, defect #12) and
    ``recommendations.playlist_exporter`` (the loops and the M3U writer). So
    pin the whole import surface: services/export_service.py may import EXACTLY
    the two loop functions from ``recommendations.*``, and nothing else - not
    ``ranked_recommendations``, not ``create_m3u_playlist``, not
    ``sanitise_filename_part``, not ``NumpyCosIndex``.

    A monkeypatch cannot do this job: the service would use a ``from X import
    y`` binding in its own namespace, which patching X does not intercept. The
    import surface can only be checked statically.
    """
    import ast
    from pathlib import Path

    import services.export_service as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            ("recommendations", "core", "processing")
        ):
            imported.setdefault(node.module, set()).update(a.name for a in node.names)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(("recommendations", "core", "processing")):
                    imported.setdefault(alias.name, set()).add("<module>")

    assert imported == {
        "recommendations.playlist_exporter": {
            "export_recommendations_as_playlists",
            "export_single_playlist",
        }
    }, (
        "ExportService's import surface changed. Anything beyond the two loops "
        f"is the raw material for an inlined copy: {imported}"
    )


def test_real_library_export_matches_a_direct_call(real_library, real_service, tmp_path):
    direct = tmp_path / "direct"
    through_service = tmp_path / "service"

    export_recommendations_as_playlists(
        REAL_SEEDS, str(direct), 10,
        real_library.meta_ix, real_library.emb_ix, real_library.index,
    )
    service_result = real_service.export_per_seed(REAL_SEEDS, str(through_service), 10)

    assert tree(through_service) == tree(direct)
    assert tree(through_service), "nothing was written"
    assert service_result.playlists_created == 3


# --------------------------------------------------------------------------
# The export/delete race: one snapshot per run
# --------------------------------------------------------------------------


DOOMED = "f07"  # belongs to a LATER seed's playlist than the pause point


def pristine_bytes(tmp_path, track_ids):
    """The undisturbed export bytes, built from a second, untouched library."""
    from fixture_library import write_fixture_library
    from services.library_session import LibrarySession

    pristine = write_fixture_library(tmp_path / "pristine", audio_dir=tmp_path / "audio")
    return m3u_bytes(LibrarySession.load(pristine), track_ids)


def delete_at_first_seed(library, track_id=DOOMED):
    """A progress callback that deletes ``track_id`` after the first seed."""
    def progress(current, total, name):
        if current == 1:
            library.delete_tracks([track_id])
    return progress


def test_export_uses_one_library_snapshot_for_the_whole_run(
    fixture_library, service, tmp_path, isolated_deleted_tracks
):
    """DETERMINISTIC INTERLEAVING. The export is paused at its first seed, a
    track that a LATER seed recommends is deleted, and the export resumes.

    The legacy Tkinter worker passed meta_ix / emb_ix / idx as arguments at
    export start, so the whole run finished against the pre-delete view. The
    first draft of this service re-read the live session per seed, during
    recommendation conversion and again while writing, so a delete could switch
    views mid-export - even between the three arguments of one recommend_for
    call. This pins the legacy behaviour: the deleted track still appears.
    """
    assert DOOMED in GOLDEN["per_seed"]["2"]["Function - Voiceprint.m3u"]
    assert DOOMED not in GOLDEN["per_seed"]["2"]["Alva Noto - Xerrox.m3u"]
    out = tmp_path / "out"
    seen = []

    def progress(current, total, name):
        seen.append(current)
        if current == 1:
            fixture_library.delete_tracks([DOOMED])

    service.export_per_seed(GOLDEN_SEEDS, str(out), 2, progress=progress)

    # The delete really landed on the session...
    assert DOOMED not in fixture_library.meta_ix.index
    assert DOOMED not in fixture_library.ids
    # ...and the export nonetheless finished against the view it started with.
    assert seen == [1, 2, 3]
    written = tree(out)
    assert sorted(written) == sorted(GOLDEN["per_seed"]["2"])
    assert written["Function - Voiceprint.m3u"] == pristine_bytes(
        tmp_path, GOLDEN["per_seed"]["2"]["Function - Voiceprint.m3u"]
    )
    assert f"{DOOMED}.mp3" in written["Function - Voiceprint.m3u"].decode()


def test_the_same_interleaving_matches_the_legacy_exporter(tmp_path, isolated_deleted_tracks):
    """Same interleaving, two runs on two identical libraries: one straight
    through the pure exporter with its arguments captured up front, the way the
    Tkinter worker captured them, and one through the service. They must agree.
    """
    from fixture_library import write_fixture_library
    from services.library_session import LibrarySession

    legacy_lib = LibrarySession.load(
        write_fixture_library(tmp_path / "legacy-data", audio_dir=tmp_path / "audio")
    )
    service_lib = LibrarySession.load(
        write_fixture_library(tmp_path / "service-data", audio_dir=tmp_path / "audio")
    )
    legacy_dir, service_dir = tmp_path / "legacy", tmp_path / "service"

    # Legacy shape: evaluate the three arguments once, then delete midway.
    export_recommendations_as_playlists(
        GOLDEN_SEEDS, str(legacy_dir), 2,
        legacy_lib.meta_ix, legacy_lib.emb_ix, legacy_lib.index,
        progress_callback=delete_at_first_seed(legacy_lib),
    )
    ExportService(service_lib).export_per_seed(
        GOLDEN_SEEDS, str(service_dir), 2, progress=delete_at_first_seed(service_lib)
    )

    assert tree(service_dir) == tree(legacy_dir)
    assert DOOMED not in legacy_lib.ids and DOOMED not in service_lib.ids
    assert f"{DOOMED}.mp3" in tree(legacy_dir)["Function - Voiceprint.m3u"].decode()


def test_a_live_reading_export_would_have_produced_something_different(
    fixture_library, tmp_path, isolated_deleted_tracks
):
    """Proves the two tests above are not vacuous: had the export re-read the
    library after the delete, the later seed's playlist WOULD have changed."""
    from recommendations.ranking import ranked_recommendations

    def rank():
        return [
            r["track_id"]
            for r in ranked_recommendations(
                "f06", fixture_library.meta_ix, fixture_library.emb_ix,
                fixture_library.index, topk=500, final_top=200, limit=2,
            )
        ]

    before = rank()
    fixture_library.delete_tracks([DOOMED])
    after = rank()

    assert before != after
    assert DOOMED in before
    assert DOOMED not in after


def test_snapshot_survives_a_delete(fixture_library, isolated_deleted_tracks):
    snapshot = fixture_library.snapshot()

    fixture_library.delete_tracks([DOOMED])

    assert DOOMED in snapshot.meta_ix.index
    assert DOOMED in snapshot.index.ids
    assert snapshot.index is not fixture_library.index
    assert snapshot.meta_ix is not fixture_library.meta_ix


def test_combined_export_also_snapshots(
    fixture_library, service, tmp_path, isolated_deleted_tracks
):
    out = tmp_path / "combined.m3u"

    service.export_combined(
        GOLDEN_SEEDS, str(out), 2, progress=delete_at_first_seed(fixture_library)
    )

    assert out.read_bytes() == pristine_bytes(tmp_path, GOLDEN["combined"]["2"])
    assert DOOMED not in fixture_library.ids


@pytest.mark.parametrize("mode", ["per_seed", "combined"])
def test_the_service_takes_exactly_one_snapshot_per_export(
    fixture_library, tmp_path, monkeypatch, mode
):
    """One capture point per run - not one per seed, which is what made the
    race materially worse than the legacy worker's.

    Both modes are covered: this used to count calls for per-seed only, so
    export_combined could have re-read the live library per seed unnoticed."""
    real = fixture_library.snapshot
    calls = []
    monkeypatch.setattr(
        fixture_library, "snapshot", lambda: calls.append(1) or real()
    )

    service = ExportService(fixture_library)
    if mode == "per_seed":
        service.export_per_seed(GOLDEN_SEEDS, str(tmp_path / "o"), 2)
    else:
        service.export_combined(GOLDEN_SEEDS, str(tmp_path / "o.m3u"), 2)

    assert len(calls) == 1


# --------------------------------------------------------------------------
# M3U format
# --------------------------------------------------------------------------


def test_m3u_format(fixture_library, service, tmp_path):
    service.export_combined(["f01"], str(tmp_path / "out.m3u"), 3)

    lines = (tmp_path / "out.m3u").read_text(encoding="utf-8").split("\n")
    assert lines[0] == "#EXTM3U"
    assert lines[1].startswith("#EXTINF:-1,")
    assert " - " in lines[1]  # hyphen, not the en dash used in the UI
    assert lines[2].startswith("/") and lines[2].endswith(".mp3")
    assert lines[-1] == ""  # trailing newline after the last path


def test_duration_is_always_minus_one(service, tmp_path):
    """CoCo never captures track duration."""
    service.export_combined(["f01"], str(tmp_path / "out.m3u"), 3)

    for line in (tmp_path / "out.m3u").read_text().splitlines():
        if line.startswith("#EXTINF"):
            assert line.startswith("#EXTINF:-1,")


def test_tracks_whose_audio_file_is_missing_are_silently_skipped(tmp_path):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. A track whose file does not exist never
    reaches the playlist and is not counted anywhere - no warning, no failed
    tally. 46 of the real library's 1,307 tracks are in this state."""
    from fixture_library import write_fixture_library
    from services.library_session import LibrarySession

    data = write_fixture_library(
        tmp_path / "data", audio_dir=tmp_path / "audio", missing=("f02",)
    )
    library = LibrarySession.load(data)
    service = ExportService(library)

    result = service.export_combined(["f01"], str(tmp_path / "out.m3u"), 5)

    body = (tmp_path / "out.m3u").read_text()
    assert "f02.mp3" not in body
    assert "Why They Hide" not in body
    assert result.failed == 0  # the skip is invisible in the stats
    assert result.total_recommendations == 5  # ...and it is still counted here


def test_filename_scheme_and_sanitisation():
    """{safe_artist} - {safe_title}.m3u, keeping only alphanumerics, space,
    hyphen and underscore. Exercises the production helper directly."""
    assert playlist_filename("Artist A", "Title One") == "Artist A - Title One.m3u"
    assert playlist_filename("Artist B/C: Two", "Title *Two*") == "Artist BC Two - Title Two.m3u"
    assert playlist_filename("  padded  ", "  title  ") == "padded - title.m3u"
    assert playlist_filename("", "") == " - .m3u"


def test_long_filenames_are_truncated_to_204_characters():
    """CURRENT BEHAVIOUR: filename[:200] + '.m3u' yields a 204-character name,
    cut mid-title.

    This used to re-implement the formula in the test body and never call the
    production code at all, so it would have passed with the helper broken. It
    now exercises the real helper - and doing so disproved the claim it used to
    carry. A "doubled .m3u" is **impossible**: the sanitiser keeps only
    alphanumerics, space, hyphen and underscore, so the only dot in the name is
    the extension the function appends, and when the name exceeds 200
    characters that extension sits beyond the cut. The inventory said otherwise
    and has been corrected.
    """
    name = playlist_filename("A" * 150, "B" * 150)

    assert len(name) == 204
    assert name == "A" * 150 + " - " + "B" * 47 + ".m3u"
    assert name.count(".m3u") == 1
    assert not name.endswith(".m3u.m3u")


def test_a_doubled_extension_is_unreachable():
    """Because sanitisation drops '.', no truncated name can end in '.m3u'."""
    for artist, title in [
        ("A" * 210, "whatever.m3u"),
        ("x" * 196, "m3u tail that is long enough to force the cut" * 5),
        ("." * 300, "." * 300),
    ]:
        name = playlist_filename(artist, title)
        assert name.count(".m3u") == 1, name


def test_a_filename_at_the_limit_is_left_alone():
    """The boundary the truncation branch turns on: >200, not >=200."""
    artist, title = "A" * 98, "B" * 95
    name = playlist_filename(artist, title)

    assert len(name) == 200
    assert not name.endswith(".m3u.m3u")


def test_filenames_are_generated_by_the_helper_the_exporter_uses(fixture_library, service, tmp_path):
    service.export_per_seed(["f01"], str(tmp_path / "out"), 2)

    track = fixture_library.meta_ix.loc["f01"]
    expected = playlist_filename(track["artist"], track["title"])
    assert [p.name for p in (tmp_path / "out").glob("*.m3u")] == [expected]


def test_colliding_seed_names_create_distinct_valid_playlists(
    fixture_library, service, tmp_path
):
    """A successful seed must own a distinct file, while unrelated names stay put.

    The smallest track id in a collision group retains the legacy filename;
    every other member is disambiguated regardless of seed iteration order, so
    unrelated exports do not churn names.
    """
    for track_id in ("f01", "f06"):
        fixture_library.meta_ix.loc[track_id, "artist"] = "Collision Artist"
        fixture_library.meta_ix.loc[track_id, "title"] = "Same Title"

    out = tmp_path / "out"
    result = service.export_per_seed(["f01", "f06", "f10"], str(out), 2)
    written = tree(out)

    assert result.successful == 3  # seeds processed successfully
    assert result.playlists_created == len(written) == 3  # actual output files
    assert "Collision Artist - Same Title.m3u" in written
    assert "Collision Artist - Same Title [ID f06].m3u" in written
    assert "Jeff Mills - The Bells.m3u" in written  # non-collider is unchanged
    assert all(body.startswith(b"#EXTM3U\n") for body in written.values())
    assert all(len(body.splitlines()) == 5 for body in written.values())


def test_blank_artist_keeps_the_legacy_leading_separator():
    """Blank artists are cosmetic, not collisions; do not rename 69 real files."""
    assert playlist_filename("", "01 Justyn Nell - Visions MST") == (
        " - 01 Justyn Nell - Visions MST.m3u"
    )


def test_reexport_reuses_the_same_disambiguated_names(
    fixture_library, service, tmp_path
):
    """An existing export folder must not accumulate a new suffix per run."""
    for track_id in ("f01", "f06"):
        fixture_library.meta_ix.loc[track_id, "artist"] = "Collision Artist"
        fixture_library.meta_ix.loc[track_id, "title"] = "Same Title"

    out = tmp_path / "out"
    first = service.export_per_seed(["f01", "f06"], str(out), 2)
    first_names = sorted(tree(out))
    second = service.export_per_seed(["f01", "f06"], str(out), 2)

    assert sorted(tree(out)) == first_names == [
        "Collision Artist - Same Title [ID f06].m3u",
        "Collision Artist - Same Title.m3u",
    ]
    assert first.playlists_created == second.playlists_created == 2


def test_collision_names_are_independent_of_seed_iteration_order(
    fixture_library, service, tmp_path
):
    """Reversed and shuffled seeds must reuse one deterministic name set."""
    import random

    for track_id in ("f01", "f06"):
        fixture_library.meta_ix.loc[track_id, "artist"] = "Collision Artist"
        fixture_library.meta_ix.loc[track_id, "title"] = "Same Title"

    forward = ["f01", "f06", "f10", "f02"]
    reversed_order = list(reversed(forward))
    shuffled = forward.copy()
    random.Random(7).shuffle(shuffled)
    assert shuffled not in (forward, reversed_order)

    expected_names = sorted([
        "Collision Artist - Same Title [ID f06].m3u",
        "Collision Artist - Same Title.m3u",
    ] + [
        playlist_filename(
            fixture_library.meta_ix.loc[track_id, "artist"],
            fixture_library.meta_ix.loc[track_id, "title"],
        )
        for track_id in ("f10", "f02")
    ])
    out = tmp_path / "out"

    for order in (forward, reversed_order, shuffled):
        result = service.export_per_seed(order, str(out), 2)
        assert sorted(tree(out)) == expected_names
        assert result.playlists_created == len(expected_names)


def test_collision_key_uses_full_case_folding():
    """Unicode full case-folding pairs must share one reservation key.

    These non-ASCII pairs distinguish full case folding from ``lower()``;
    ASCII-only case variants cannot pin that filesystem-safety property.
    """
    from recommendations.playlist_exporter import _filename_collision_key

    assert _filename_collision_key("Artist - Title.m3u") == (
        _filename_collision_key("artist - title.M3U")
    )
    assert _filename_collision_key("Straße.m3u") == (
        _filename_collision_key("Strasse.m3u")
    )
    assert _filename_collision_key("ﬁ.m3u") == _filename_collision_key("fi.m3u")
    assert _filename_collision_key("K.m3u") == _filename_collision_key("k.m3u")


def test_collision_key_normalises_canonically_equivalent_unicode():
    """Composed and decomposed Å must share one reservation key."""
    from recommendations.playlist_exporter import _filename_collision_key

    assert _filename_collision_key("A\N{COMBINING RING ABOVE}.m3u") == (
        _filename_collision_key("\N{LATIN CAPITAL LETTER A WITH RING ABOVE}.m3u")
    )


def test_long_collision_suffix_retains_the_complete_track_id():
    """The discriminator is appended after cutting room for it."""
    from recommendations.playlist_exporter import _filename_with_track_id

    legacy_name = playlist_filename("A" * 200, "B" * 200)
    disambiguated = _filename_with_track_id(legacy_name, "f06", 1)

    assert len(disambiguated) == len(legacy_name) == 204
    assert disambiguated.endswith(" [ID f06].m3u")


def test_failed_write_does_not_reserve_its_filename(
    fixture_library, service, tmp_path, monkeypatch
):
    """A retry of the same seed reuses the name that the failed write never owned."""
    from recommendations import playlist_exporter

    real_create = playlist_exporter.create_m3u_playlist
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected write failure")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(playlist_exporter, "create_m3u_playlist", fail_once)
    out = tmp_path / "out"
    result = service.export_per_seed(["f01", "f01"], str(out), 2)

    track = fixture_library.meta_ix.loc["f01"]
    expected_name = playlist_filename(track["artist"], track["title"])
    assert sorted(tree(out)) == [expected_name]
    assert result.successful == result.failed == result.playlists_created == 1


def test_output_directory_is_created_for_per_seed(service, tmp_path):
    target = tmp_path / "does" / "not" / "exist"

    service.export_per_seed(["f01"], str(target), 3)

    assert target.is_dir() and list(target.glob("*.m3u"))


def test_combined_does_not_create_its_output_directory(service, tmp_path):
    """CURRENT BEHAVIOUR: export_single_playlist never made the directory, so a
    missing one raises into the tab's 'Export Error' dialog."""
    with pytest.raises(FileNotFoundError):
        service.export_combined(["f01"], str(tmp_path / "nope" / "out.m3u"), 3)


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------


def test_per_seed_stats_shape(service, tmp_path):
    result = service.export_per_seed(GOLDEN_SEEDS, str(tmp_path / "out"), 5)

    assert set(result.as_legacy_stats()) == {
        "total_tracks", "successful", "failed", "playlists_created",
        "total_recommendations",
    }
    assert result.total_tracks == 3
    assert result.successful == 3
    assert result.playlists_created == 3
    assert result.failed == 0
    assert result.total_recommendations == 15


def test_combined_stats_omit_playlists_created(service, tmp_path):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. This missing key is exactly why
    playlist_export_tab.export_complete raises KeyError in combined mode and the
    user gets no completion dialog. Inventory defect #10."""
    result = service.export_combined(GOLDEN_SEEDS, str(tmp_path / "out.m3u"), 5)

    stats = result.as_legacy_stats()
    assert "playlists_created" not in stats
    with pytest.raises(KeyError, match="playlists_created"):
        stats["playlists_created"]


def test_unknown_track_ids_count_as_failed(service, tmp_path):
    result = service.export_per_seed(["no-such-track", "f01"], str(tmp_path / "out"), 3)

    assert result.total_tracks == 2
    assert result.failed == 1
    assert result.successful == 1


def test_combined_deduplicates_across_seeds(service, tmp_path):
    out = tmp_path / "out.m3u"

    result = service.export_combined(GOLDEN_SEEDS, str(out), 5)

    paths = [l for l in out.read_text().splitlines() if not l.startswith("#")]
    assert len(paths) == len(set(paths))
    assert result.total_recommendations >= len(paths)


def test_result_is_an_export_result(service, tmp_path):
    assert isinstance(service.export_per_seed(["f01"], str(tmp_path / "a"), 2), ExportResult)
    assert isinstance(service.export_combined(["f01"], str(tmp_path / "b.m3u"), 2), ExportResult)


# --------------------------------------------------------------------------
# progress and cancel
# --------------------------------------------------------------------------


def test_per_seed_progress_matches_the_legacy_callback_contract(fixture_library, service, tmp_path):
    """progress(current, total, "{artist} - {title}") fired BEFORE each seed's
    recommendations are computed, current starting at 1."""
    seen = []

    service.export_per_seed(
        GOLDEN_SEEDS, str(tmp_path / "new"), 3, progress=lambda c, t, n: seen.append((c, t, n))
    )

    assert seen == [
        (1, 3, "Alva Noto - Xerrox"),
        (2, 3, "Function - Voiceprint"),
        (3, 3, "Jeff Mills - The Bells"),
    ]


def test_progress_is_optional(service, tmp_path):
    assert service.export_per_seed(["f01"], str(tmp_path / "out"), 2).successful == 1


def test_cancel_event_stops_a_per_seed_export(service, tmp_path):
    """Plumbing for PR 3. The Tkinter tab has no cancel control and passes None,
    so this changes nothing user-visible today."""
    cancel = threading.Event()

    def progress(current, total, name):
        if current == 2:
            cancel.set()

    result = service.export_per_seed(
        GOLDEN_SEEDS, str(tmp_path / "out"), 3, progress=progress, cancel=cancel
    )

    assert result.cancelled is True
    assert result.successful < 3
    assert len(list((tmp_path / "out").glob("*.m3u"))) < 3


def test_an_unset_cancel_event_does_not_stop_anything(service, tmp_path):
    result = service.export_per_seed(
        GOLDEN_SEEDS, str(tmp_path / "out"), 3, cancel=threading.Event()
    )

    assert result.cancelled is False
    assert result.successful == 3


def test_cancel_event_stops_a_combined_export(service, tmp_path):
    cancel = threading.Event()

    result = service.export_combined(
        GOLDEN_SEEDS, str(tmp_path / "out.m3u"), 3,
        progress=lambda c, t, n: cancel.set(), cancel=cancel,
    )

    assert result.cancelled is True
