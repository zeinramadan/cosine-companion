#!/usr/bin/env python3
"""Rekordbox XML parsing functionality.

Produces a DataFrame with at least: track_id, path, artist, title, album, bpm, key, path_local
"""

import pandas as pd
from lxml import etree
from urllib.parse import urlparse, unquote


def read_rekordbox_xml(xml_path: str) -> pd.DataFrame:
    """
    Parse Rekordbox XML export and extract track metadata.

    Args:
        xml_path: Path to the Rekordbox XML export file

    Returns:
        DataFrame with columns: track_id, path, artist, title, album, bpm, key, path_local
    """
    tree = etree.parse(xml_path)
    root = tree.getroot()
    rows = []

    for t in root.xpath("//COLLECTION/TRACK"):
        loc = t.get("Location") or ""
        parsed = urlparse(loc)
        path_local = ""
        if parsed.scheme == "file":
            # Preserve literal '#' characters that may appear in filenames.
            # urlparse treats '#' as a fragment separator, so we need to stitch
            # it back into the path for correct local filesystem resolution.
            path_with_fragment = parsed.path + ("#" + parsed.fragment if parsed.fragment else "")

            # handle file:// and file://localhost
            if parsed.netloc and parsed.netloc != "localhost":
                # Rare case: remote file host; mount specifics may vary
                path_local = "/" + parsed.netloc + unquote(path_with_fragment)
            else:
                path_local = unquote(path_with_fragment)

        rows.append({
            "track_id": t.get("TrackID") or "",
            "path": loc,
            "artist": t.get("Artist") or "",
            "title": t.get("Name") or "",
            "album": t.get("Album") or "",
            "bpm": float(t.get("AverageBpm") or t.get("Tempo") or 0) or None,
            "key": t.get("Tonality") or "",
            "path_local": path_local,
        })

    df = pd.DataFrame(rows)

    # Keep only rows with a resolved local path
    df = df[df["path_local"].astype(str).str.len() > 0].copy()

    # Fall back only for the individual tracks that have no Rekordbox TrackID.
    # A path-derived ID is not stable if the file moves, and the row's identity
    # will change if Rekordbox later assigns a real TrackID. This is preferable to
    # replacing the valid TrackIDs for the rest of the library.
    missing_track_id = df["track_id"].isna() | (df["track_id"] == "")
    if missing_track_id.any():
        df.loc[missing_track_id, "track_id"] = df.loc[missing_track_id, "path"]

    duplicate_track_id = df["track_id"].duplicated(keep=False)
    if duplicate_track_id.any():
        duplicates = df.loc[duplicate_track_id, "track_id"].unique().tolist()
        raise ValueError(
            "Duplicate track_id values after applying per-row path fallbacks: "
            f"{duplicates[:5]}"
        )

    return df
