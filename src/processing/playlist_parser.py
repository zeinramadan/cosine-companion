#!/usr/bin/env python3
"""The ``<PLAYLISTS>`` half of a Rekordbox XML export.

``xml_parser.read_rekordbox_xml`` reads ``//COLLECTION/TRACK`` and discards
everything else. This module reads the other half - the folder/playlist tree
and the track membership inside it - and is deliberately a separate module
rather than an addition to ``xml_parser``: the collection parse feeds the
index, its output is load-bearing, and nothing here may perturb it.

WHAT THE XML LOOKS LIKE, MEASURED
---------------------------------
Measured on ``data/library_export_190826.xml`` (2026-08-19, 141 playlists) with
a standalone lxml script, not with this parser:

* ``<NODE Type="0">`` is a folder (attrs ``Type``, ``Name``, ``Count``);
  ``<NODE Type="1">`` is a playlist (attrs ``Type``, ``Name``, ``Entries``,
  ``KeyType``). Membership is ``<TRACK Key="..."/>`` children.
* 141 playlists, and 14 ``Type="0"`` nodes IN TOTAL - one of which is the
  container literally named ``ROOT``, leaving 13 folders the user made. (The
  plan and spec both say "14 folders, plus a single root node", i.e. 15; the
  export has 14 including ROOT. Corrected here against the measurement.)
* ``KeyType`` is ``"0"`` on all 141: membership is by TrackID, never by path.
* 4,669 membership entries; 0 empty playlists; the ``Entries`` attribute
  matches the child count on every one of the 141.
* Deepest playlist is 5 segments including ``ROOT`` - 4 once it is stripped.
* 36 leaf names are duplicated across 72 playlists; all 141 FULL paths are
  unique.

THREE CONSEQUENCES, EACH OF WHICH IS A DECISION HERE
----------------------------------------------------
1. **``ROOT`` is stripped.** It is Rekordbox's container, not a folder anybody
   made, and it carries no information. It must never reach the UI. Stripped
   here, at the parse, so no consumer has to remember to.
2. **``folder_path`` is a LIST of segments, never a joined string.** Two folder
   names in this very export contain a forward slash - ``Collections/Hauls``
   and ``08/2026`` - so ``" / "`` is ambiguous as a separator and joining at
   the parse would lose the distinction irrecoverably. The UI joins; the data
   does not.
3. **The walk is genuinely recursive.** Depth 4 exists today and nothing stops
   Rekordbox going deeper, so no depth is hard-coded.

WHAT IS NOT RESOLVED HERE
-------------------------
A ``Key`` is copied out verbatim. Whether it names a track CoCo has indexed is
a question about ``meta.parquet``, not about this file, and answering it here
would make the parse depend on the library. ``services.playlist_import`` does
that resolution and reports the count.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree

#: Rekordbox's own container node. Present exactly once, as the only child of
#: ``<PLAYLISTS>``, and stripped from every path.
ROOT_NODE_NAME = "ROOT"

FOLDER_TYPE = "0"
PLAYLIST_TYPE = "1"

#: The only ``KeyType`` whose ``<TRACK Key>`` is a Rekordbox TrackID. ``"1"``
#: means the key is a file location instead, which cannot be resolved without
#: the collection; such a playlist is catalogued but contributes no membership.
KEY_TYPE_TRACK_ID = "0"

#: Length of a minted ``playlist_id``, in hex characters.
PLAYLIST_ID_HEX_LENGTH = 16


def mint_playlist_id(folder_path, name: str, occurrence: int = 0) -> str:
    """A stable, deterministic id for the playlist at ``folder_path`` / ``name``.

    Rekordbox does not give playlists an id of their own, so one has to be
    minted, and the requirement is that re-importing an unchanged file is a
    no-op - which rules out anything positional, anything derived from
    ``id()``, and Python's own ``hash()`` (salted per process since 3.3).

    What is hashed is the canonical JSON encoding of the full path - the folder
    segments, then the leaf name - plus an occurrence ordinal. blake2b at
    ``digest_size=8`` gives 16 hex characters, which is short enough to read in
    a parquet column and far past what 141 rows need.

    The ordinal is what makes this total rather than merely usually-unique. All
    141 full paths in the real export are distinct, so every ordinal is 0
    today; two playlists with the same name under the same parent would
    otherwise mint the same id and silently merge into one. ``parse_playlists``
    assigns the ordinal in document order and raises if a digest still
    collides.

    Deliberately NOT derived from the name alone: 36 leaf names are duplicated.
    """
    canonical = json.dumps(
        [*folder_path, name, occurrence], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.blake2b(
        canonical.encode("utf-8"), digest_size=PLAYLIST_ID_HEX_LENGTH // 2
    ).hexdigest()


@dataclass(frozen=True)
class ParsedPlaylist:
    """One ``<NODE Type="1">``, with its position in the folder tree."""

    playlist_id: str
    name: str
    #: Folder segments from the outermost inwards, ``ROOT`` already removed.
    #: Empty for a playlist sitting at the top level.
    folder_path: Tuple[str, ...]
    #: The minted id of the parent FOLDER path, or ``""`` at the top level.
    #:
    #: A grouping key derived from ``folder_path``, not a foreign key into the
    #: playlist table: folders are not rows here, because §6.2 of the spec
    #: gives ``playlists.parquet`` one row per playlist and browsing by folder
    #: is explicitly out of scope for this PR. Two playlists share a
    #: ``parent_id`` exactly when they share a ``folder_path``.
    parent_id: str
    #: The ``Entries`` attribute. Verified against the real child count on all
    #: 141 real playlists, and re-derived rather than trusted when the two
    #: disagree - see ``entries_attribute_mismatch``.
    entries: int
    #: ``KeyType`` verbatim. ``"0"`` on all 141 real playlists.
    key_type: str
    #: Every ``<TRACK Key>`` child, in document order, unresolved. Empty when
    #: ``key_type`` is not ``"0"``.
    track_ids: Tuple[str, ...] = ()

    @property
    def full_path(self) -> Tuple[str, ...]:
        return (*self.folder_path, self.name)


@dataclass(frozen=True)
class ParsedPlaylists:
    """Everything the ``<PLAYLISTS>`` element says, and nothing derived from it."""

    playlists: Tuple[ParsedPlaylist, ...] = ()
    #: Folder paths encountered, ``ROOT`` stripped, in document order. Reported
    #: rather than persisted; nothing downstream needs a folder row.
    folder_paths: Tuple[Tuple[str, ...], ...] = ()
    #: Playlists whose ``Entries`` attribute disagreed with the child count,
    #: as ``(full_path, attribute, actual)``. Zero on the real export.
    entries_attribute_mismatch: Tuple[Tuple[Tuple[str, ...], int, int], ...] = ()
    #: Playlists whose ``KeyType`` is not ``"0"``: catalogued, but their
    #: membership cannot be resolved to a TrackID and is not recorded.
    unsupported_key_type: Tuple[Tuple[Tuple[str, ...], str, int], ...] = ()

    @property
    def membership(self) -> List[Tuple[str, str]]:
        """``(track_id, playlist_id)`` for every recorded entry, in document order."""
        return [
            (track_id, playlist.playlist_id)
            for playlist in self.playlists
            for track_id in playlist.track_ids
        ]

    @property
    def membership_count(self) -> int:
        return sum(len(playlist.track_ids) for playlist in self.playlists)


def parse_playlists(xml_path) -> ParsedPlaylists:
    """Read the folder/playlist tree out of a Rekordbox XML export.

    An export with no ``<PLAYLISTS>`` element at all yields an empty result
    rather than an error: that is a Rekordbox export with nothing in it, not a
    corrupt file, and the caller's summary says "0 playlists" either way.
    """
    return parse_playlists_bytes(Path(xml_path).read_bytes())


def parse_playlists_bytes(data: bytes) -> ParsedPlaylists:
    """The same parse, over a buffer that has already been read from a file.

    ``services.playlist_import`` hashes the export and parses it, and those two
    have to be the same bytes: reading twice let a re-export land in between,
    after which the manifest recorded the digest of a file the tables were not
    built from and the staleness check reported "fresh" for data that did not
    match. So the importer reads once and passes the buffer here.

    BYTES, NOT ``str``. lxml refuses a ``str`` carrying an encoding
    declaration, and every Rekordbox export opens with one. The declaration is
    also how the document's encoding is known, so decoding first and re-encoding
    would be guessing at something the file already states.
    """
    return parse_playlists_element(etree.fromstring(data).find("PLAYLISTS"))


def parse_playlists_element(playlists_element) -> ParsedPlaylists:
    """The parse itself, over an already-located ``<PLAYLISTS>`` element.

    Split out so a test can drive it from a hand-built tree, and so
    ``parse_playlists`` stays a two-line file adapter.
    """
    if playlists_element is None:
        return ParsedPlaylists()

    playlists: List[ParsedPlaylist] = []
    folder_paths: List[Tuple[str, ...]] = []
    mismatches: List[Tuple[Tuple[str, ...], int, int]] = []
    unsupported: List[Tuple[Tuple[str, ...], str, int]] = []
    #: How many playlists already carry each full path, so the second one gets
    #: ordinal 1 rather than the first one's id.
    seen_paths: Dict[Tuple[str, ...], int] = {}
    minted: Dict[str, Tuple[str, ...]] = {}

    def walk(node, path: Tuple[str, ...]) -> None:
        for child in node:
            if child.tag != "NODE":
                continue

            node_type = child.get("Type")
            name = child.get("Name") or ""

            if node_type == FOLDER_TYPE:
                # ROOT is Rekordbox's container. Skipping the SEGMENT rather
                # than the node is what strips it: its children still recurse,
                # they simply do not inherit its name.
                if not path and name == ROOT_NODE_NAME:
                    walk(child, path)
                    continue
                folder_paths.append((*path, name))
                walk(child, (*path, name))
                continue

            if node_type != PLAYLIST_TYPE:
                # Neither a folder nor a playlist. No such node exists in any
                # export seen; ignoring it beats guessing what it meant.
                continue

            key_type = child.get("KeyType") or ""
            keys = tuple(
                (track.get("Key") or "")
                for track in child.findall("TRACK")
            )
            full_path = (*path, name)

            declared = child.get("Entries")
            try:
                entries = int(declared)
            except (TypeError, ValueError):
                entries = len(keys)
            if entries != len(keys):
                # The attribute is trustworthy on the real export (0 mismatches
                # in 141), but "trustworthy" is a measurement, not a guarantee.
                # The child count is the thing that is actually there.
                mismatches.append((full_path, entries, len(keys)))
                entries = len(keys)

            if key_type != KEY_TYPE_TRACK_ID:
                # A path-keyed playlist. It is real and it is catalogued, but
                # its Key values are file locations, and resolving those to
                # TrackIDs is a job for the collection parse. Recording them as
                # if they were TrackIDs would put entries in the membership
                # table that can never match a track.
                unsupported.append((full_path, key_type, len(keys)))
                keys = ()

            occurrence = seen_paths.get(full_path, 0)
            seen_paths[full_path] = occurrence + 1
            playlist_id = mint_playlist_id(path, name, occurrence)
            if playlist_id in minted:
                raise ValueError(
                    f"minted playlist_id {playlist_id!r} collides between "
                    f"{minted[playlist_id]!r} and {full_path!r}"
                )
            minted[playlist_id] = full_path

            playlists.append(
                ParsedPlaylist(
                    playlist_id=playlist_id,
                    name=name,
                    folder_path=path,
                    parent_id=mint_folder_id(path),
                    entries=entries,
                    key_type=key_type,
                    track_ids=keys,
                )
            )

    walk(playlists_element, ())

    return ParsedPlaylists(
        playlists=tuple(playlists),
        folder_paths=tuple(folder_paths),
        entries_attribute_mismatch=tuple(mismatches),
        unsupported_key_type=tuple(unsupported),
    )


def mint_folder_id(folder_path) -> str:
    """The grouping id for a folder path, or ``""`` at the top level.

    Same digest scheme as ``mint_playlist_id`` so the two are readable side by
    side, with the last segment playing the role of the leaf name. A top-level
    playlist has no parent folder and gets the empty string rather than the
    digest of an empty path, so "no parent" is distinguishable at a glance.
    """
    folder_path = tuple(folder_path)
    if not folder_path:
        return ""
    return mint_playlist_id(folder_path[:-1], folder_path[-1], 0)
