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


def _parse_tracks(tmp_path: Path, tracks: list[str]) -> pd.DataFrame:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        "<DJ_PLAYLISTS><COLLECTION>"
        + "".join(tracks)
        + "</COLLECTION></DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    return read_rekordbox_xml(str(xml_path))


def _legacy_track_id_column(xml_path: Path) -> pd.Series:
    """Return track IDs using the parser behavior from main at a9e7886."""
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
    return frame["track_id"]


def test_all_track_ids_are_preserved_exactly(tmp_path: Path) -> None:
    frame = _parse_tracks(
        tmp_path,
        [
            '<TRACK TrackID="00017" Location="file:///Music/one.mp3"/>',
            '<TRACK TrackID="9007199254740993" Location="file:///Music/two.mp3"/>',
        ],
    )

    assert frame["track_id"].tolist() == ["00017", "9007199254740993"]


def test_one_missing_track_id_only_changes_that_row(tmp_path: Path) -> None:
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
    "tracks",
    [
        [
            '<TRACK TrackID="file:///Music/fallback.mp3" '
            'Location="file:///Music/existing.mp3"/>',
            '<TRACK Location="file:///Music/fallback.mp3"/>',
        ],
        [
            '<TRACK Location="file:///Music/duplicate.mp3"/>',
            '<TRACK TrackID="" Location="file:///Music/duplicate.mp3"/>',
        ],
    ],
    ids=["fallback-collides-with-track-id", "fallback-paths-collide"],
)
def test_duplicate_final_track_ids_raise_clear_error(
    tmp_path: Path, tracks: list[str]
) -> None:
    with pytest.raises(ValueError, match="Duplicate track_id values.*file://"):
        _parse_tracks(tmp_path, tracks)


def test_row_without_resolvable_local_path_is_dropped(tmp_path: Path) -> None:
    frame = _parse_tracks(
        tmp_path,
        [
            '<TRACK TrackID="drop-me" Location="https://example.com/remote.mp3"/>',
            '<TRACK TrackID="keep-me" Location="file:///Music/local.mp3"/>',
        ],
    )

    assert frame.index.tolist() == [1]
    assert frame["track_id"].tolist() == ["keep-me"]


def test_real_xml_track_ids_match_legacy_parser_output() -> None:
    xml_path = Path(__file__).parents[1] / "data" / "09102025.xml"
    if not xml_path.exists():
        pytest.skip("private real-library XML export is not present")

    actual = read_rekordbox_xml(str(xml_path))["track_id"]
    expected = _legacy_track_id_column(xml_path)

    pd.testing.assert_series_equal(actual, expected)
