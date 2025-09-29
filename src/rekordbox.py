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
            # handle file:// and file://localhost
            if parsed.netloc and parsed.netloc != "localhost":
                # Rare case: remote file host; mount specifics may vary
                path_local = "/" + parsed.netloc + unquote(parsed.path)
            else:
                path_local = unquote(parsed.path)

        rows.append({
            "track_id": t.get("TrackID") or t.get("TrackID", ""),
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

    # Stable ID if XML TrackID missing
    if "track_id" not in df or df["track_id"].isna().any() or (df["track_id"] == "").any():
        df["track_id"] = df["path"]

    return df


