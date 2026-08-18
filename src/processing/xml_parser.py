#!/usr/bin/env python3
"""Rekordbox XML parsing functionality.

Produces a DataFrame with at least: track_id, path, artist, title, album, bpm, key, path_local
"""

import pandas as pd
from lxml import etree
from urllib.parse import urlparse, unquote


def read_rekordbox_xml(xml_path: str, progress=None) -> pd.DataFrame:
    """
    Parse Rekordbox XML export and extract track metadata.

    Args:
        xml_path: Path to the Rekordbox XML export file
        progress: Optional callable(phase, current, total, message). When given,
            warnings are reported through it instead of being printed.

    Returns:
        DataFrame with columns: track_id, path, artist, title, album, bpm, key, path_local
    """
    def report(phase, message, current=0, total=0):
        if progress is None:
            print(message)
        else:
            progress(phase, current, total, message)

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
        fallback_count = int(missing_track_id.sum())
        report(
            "read_xml",
            f"{fallback_count} track(s) had no Rekordbox TrackID; "
            "using file path as identity"
        )
        df.loc[missing_track_id, "track_id"] = df.loc[missing_track_id, "path"]

    # This guard also rejects duplicate TrackIDs that main tolerated; duplicate
    # primary keys break set_index in loader.py. It runs before the pipeline's
    # remove_simple_duplicates() call, so repeated imports of the same file with
    # no TrackID fail here instead of being deduplicated later by path_local.
    duplicate_track_id = df["track_id"].duplicated(keep=False)
    if duplicate_track_id.any():
        duplicate_rows = df.loc[duplicate_track_id, ["track_id", "path"]]
        duplicate_id_count = duplicate_rows["track_id"].nunique(dropna=False)
        duplicate_id_label = "value" if duplicate_id_count == 1 else "values"
        examples = "; ".join(
            f"{track_id!r} -> {path!r}"
            for track_id, path in duplicate_rows.head(5).itertuples(index=False)
        )
        raise ValueError(
            f"Rekordbox XML {str(xml_path)!r} contains {len(duplicate_rows)} "
            f"tracks across {duplicate_id_count} duplicated track_id "
            f"{duplicate_id_label}. "
            "Affected track_id -> path pairs (up to 5): "
            f"{examples}. Ensure each retained track has a unique Rekordbox "
            "TrackID or file Location before indexing."
        )

    return df
