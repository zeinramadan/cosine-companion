from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
import pytest
from lxml import etree


# Import the parser without executing processing/__init__.py, which imports the
# optional Essentia runtime that is intentionally absent from the unit-test job.
XML_PARSER_PATH = Path(__file__).parents[1] / "src" / "processing" / "xml_parser.py"
SPEC = spec_from_file_location("xml_parser", XML_PARSER_PATH)
assert SPEC is not None and SPEC.loader is not None
XML_PARSER = module_from_spec(SPEC)
SPEC.loader.exec_module(XML_PARSER)
read_rekordbox_xml = XML_PARSER.read_rekordbox_xml
ANONYMIZED_XML_PATH = Path(__file__).parent / "fixtures" / "collection.xml"


def _parse_tracks(tmp_path: Path, tracks: list[str]) -> pd.DataFrame:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        "<DJ_PLAYLISTS><COLLECTION>"
        + "".join(tracks)
        + "</COLLECTION></DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    return read_rekordbox_xml(str(xml_path))


# Frozen copy of main@a9e7886. Never edit this to make a test pass — a diff here
# means the parser changed and the compatibility expectation needs review.
def _legacy_read_rekordbox_xml(xml_path: Path) -> pd.DataFrame:
    """Return the complete DataFrame produced by the parser at main@a9e7886."""
    root = etree.parse(str(xml_path)).getroot()
    rows = []

    for track in root.xpath("//COLLECTION/TRACK"):
        location = track.get("Location") or ""
        parsed = urlparse(location)
        path_local = ""
        if parsed.scheme == "file":
            path_with_fragment = parsed.path + (
                "#" + parsed.fragment if parsed.fragment else ""
            )
            if parsed.netloc and parsed.netloc != "localhost":
                path_local = "/" + parsed.netloc + unquote(path_with_fragment)
            else:
                path_local = unquote(path_with_fragment)

        rows.append(
            {
                "track_id": track.get("TrackID") or track.get("TrackID", ""),
                "path": location,
                "artist": track.get("Artist") or "",
                "title": track.get("Name") or "",
                "album": track.get("Album") or "",
                "bpm": float(
                    track.get("AverageBpm") or track.get("Tempo") or 0
                )
                or None,
                "key": track.get("Tonality") or "",
                "path_local": path_local,
            }
        )

    frame = pd.DataFrame(rows)
    frame = frame[frame["path_local"].astype(str).str.len() > 0].copy()
    if (
        "track_id" not in frame
        or frame["track_id"].isna().any()
        or (frame["track_id"] == "").any()
    ):
        frame["track_id"] = frame["path"]
    return frame


def test_all_track_ids_are_preserved_exactly(tmp_path: Path) -> None:
    frame = _parse_tracks(
        tmp_path,
        [
            '<TRACK TrackID="00017" Location="file:///Music/one.mp3"/>',
            '<TRACK TrackID="9007199254740993" Location="file:///Music/two.mp3"/>',
        ],
    )

    assert frame["track_id"].tolist() == ["00017", "9007199254740993"]


def test_track_id_zero_is_preserved(tmp_path: Path) -> None:
    frame = _parse_tracks(
        tmp_path,
        [
            '<TRACK TrackID="0" Location="file:///Music/zero.mp3"/>',
            '<TRACK TrackID="1" Location="file:///Music/one.mp3"/>',
        ],
    )

    assert frame["track_id"].tolist() == ["0", "1"]


def test_one_missing_track_id_only_changes_that_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fallback_path = "file:///Music/missing.mp3"
    frame = _parse_tracks(
        tmp_path,
        [
            '<TRACK TrackID="101" Location="file:///Music/one.mp3"/>',
            f'<TRACK Location="{fallback_path}"/>',
            '<TRACK TrackID="103" Location="file:///Music/three.mp3"/>',
        ],
    )

    assert frame["track_id"].tolist() == ["101", fallback_path, "103"]
    assert capsys.readouterr().out == (
        "1 track(s) had no Rekordbox TrackID; using file path as identity\n"
    )


def test_all_missing_track_ids_fall_back_to_their_own_paths(tmp_path: Path) -> None:
    paths = ["file:///Music/one.mp3", "file:///Music/two.mp3"]
    frame = _parse_tracks(
        tmp_path,
        [f'<TRACK Location="{path}"/>' for path in paths],
    )

    assert frame["track_id"].tolist() == paths


def test_empty_and_absent_track_ids_both_fall_back(tmp_path: Path) -> None:
    empty_path = "file:///Music/empty.mp3"
    absent_path = "file:///Music/absent.mp3"
    frame = _parse_tracks(
        tmp_path,
        [
            f'<TRACK TrackID="" Location="{empty_path}"/>',
            f'<TRACK Location="{absent_path}"/>',
        ],
    )

    assert frame["track_id"].tolist() == [empty_path, absent_path]


@pytest.mark.parametrize(
    ("tracks", "expected_track_id", "expected_paths"),
    [
        (
            [
                '<TRACK TrackID="file:///Music/fallback.mp3" '
                'Location="file:///Music/existing.mp3"/>',
                '<TRACK Location="file:///Music/fallback.mp3"/>',
            ],
            "file:///Music/fallback.mp3",
            ["file:///Music/existing.mp3", "file:///Music/fallback.mp3"],
        ),
        (
            [
                '<TRACK Location="file:///Music/duplicate.mp3"/>',
                '<TRACK TrackID="" Location="file:///Music/duplicate.mp3"/>',
            ],
            "file:///Music/duplicate.mp3",
            ["file:///Music/duplicate.mp3", "file:///Music/duplicate.mp3"],
        ),
        (
            [
                '<TRACK TrackID="5" Location="file:///Music/first.mp3"/>',
                '<TRACK TrackID="5" Location="file:///Music/second.mp3"/>',
            ],
            "5",
            ["file:///Music/first.mp3", "file:///Music/second.mp3"],
        ),
    ],
    ids=[
        "fallback-collides-with-track-id",
        "fallback-paths-collide",
        "real-track-ids-collide",
    ],
)
def test_duplicate_final_track_ids_raise_clear_error(
    tmp_path: Path,
    tracks: list[str],
    expected_track_id: str,
    expected_paths: list[str],
) -> None:
    with pytest.raises(ValueError) as exc_info:
        _parse_tracks(tmp_path, tracks)

    message = str(exc_info.value)
    assert str(tmp_path / "rekordbox.xml") in message
    assert "contains 2 tracks across 1 duplicated track_id value" in message
    assert "Affected track_id -> path pairs (up to 5)" in message
    assert repr(expected_track_id) in message
    for expected_path in expected_paths:
        assert repr(expected_path) in message
    assert "Ensure each retained track has a unique Rekordbox TrackID" in message
    assert "after applying per-row path fallbacks" not in message


def test_duplicate_error_reports_total_beyond_five_examples(tmp_path: Path) -> None:
    tracks = [
        f'<TRACK TrackID="5" Location="file:///Music/duplicate-{index}.mp3"/>'
        for index in range(6)
    ]

    with pytest.raises(ValueError) as exc_info:
        _parse_tracks(tmp_path, tracks)

    message = str(exc_info.value)
    assert "contains 6 tracks across 1 duplicated track_id value" in message
    for index in range(5):
        assert f"file:///Music/duplicate-{index}.mp3" in message
    assert "file:///Music/duplicate-5.mp3" not in message


def test_dropped_row_cannot_trigger_track_id_collision(tmp_path: Path) -> None:
    frame = _parse_tracks(
        tmp_path,
        [
            '<TRACK TrackID="same-id" Location="https://example.com/remote.mp3"/>',
            '<TRACK TrackID="same-id" Location="file:///Music/local.mp3"/>',
        ],
    )

    assert frame.index.tolist() == [1]
    assert frame["track_id"].tolist() == ["same-id"]


def test_anonymized_fixture_decoding_and_mixed_id_behavior(
    capsys: pytest.CaptureFixture[str],
) -> None:
    frame = read_rekordbox_xml(str(ANONYMIZED_XML_PATH))

    assert len(frame) == 16
    assert frame.loc[frame["title"] == "Neon Harbor", "path_local"].item() == (
        "/Users/example/Music/Aster Vale/Neon Harbor.mp3"
    )
    assert frame.loc[frame["title"] == "Satellite Bloom", "path_local"].item() == (
        "/Users/example/Music/Lumen Field/Satellite Bloom.aiff"
    )
    assert frame.loc[frame["title"] == "Break Point", "path_local"].item() == (
        "/Users/example/Music/SignalGarden/Break#Point.wav"
    )
    missing_id_row = frame.loc[frame["title"] == "Unknown Signal"].iloc[0]
    assert missing_id_row["track_id"] == missing_id_row["path"]
    assert "Offline Entry" not in frame["title"].tolist()
    assert capsys.readouterr().out == (
        "1 track(s) had no Rekordbox TrackID; using file path as identity\n"
    )


def test_anonymized_fixture_routes_fallback_warning_to_progress(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = []

    read_rekordbox_xml(
        str(ANONYMIZED_XML_PATH),
        progress=lambda phase, current, total, message: events.append(
            (phase, current, total, message)
        ),
    )

    assert events == [
        (
            "read_xml",
            0,
            0,
            "1 track(s) had no Rekordbox TrackID; using file path as identity",
        )
    ]
    assert capsys.readouterr().out == ""


def test_anonymized_all_id_fixture_matches_frozen_legacy(
    tmp_path: Path,
) -> None:
    tree = etree.parse(str(ANONYMIZED_XML_PATH))
    missing_id_tracks = tree.xpath(
        '//COLLECTION/TRACK[not(@TrackID) or @TrackID=""]'
    )
    assert len(missing_id_tracks) == 1
    for track in missing_id_tracks:
        track.getparent().remove(track)
    all_id_xml_path = tmp_path / "collection-all-ids.xml"
    tree.write(str(all_id_xml_path), encoding="UTF-8", xml_declaration=True)

    actual = read_rekordbox_xml(str(all_id_xml_path))
    expected = _legacy_read_rekordbox_xml(all_id_xml_path)

    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_private_real_xml_matches_frozen_legacy_parser_output() -> None:
    xml_path = Path(__file__).parents[1] / "data" / "09102025.xml"
    if not xml_path.exists():
        pytest.skip("private real-library XML export is not present")

    actual = read_rekordbox_xml(str(xml_path))
    expected = _legacy_read_rekordbox_xml(xml_path)

    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
