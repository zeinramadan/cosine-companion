"""Hand-written Rekordbox XML fixtures for the playlist tests.

Every expected value in the tests that use these is worked out BY HAND from
the literal below and written as a literal of its own. Nothing here calls the
parser, the store or the service to decide what the answer should be: a test
whose oracle is the function under test proves only that the function is
deterministic.

``FIXTURE_XML`` is one document covering, deliberately, every structural case
the plan names:

* a ``ROOT`` container to be stripped;
* a playlist at the top level, with no folder at all;
* nesting FIVE display segments deep - four folders plus the leaf - which is
  one deeper than the real export, so a hard-coded depth of 4 would fail here;
* a folder whose NAME contains a forward slash (``Collections/Hauls``, the
  real one), which is why folder paths are lists and not joined strings;
* two playlists sharing a leaf name under different parents;
* an empty playlist (none exist in the real export; fixture-only);
* a playlist with ``KeyType="1"``, whose keys are file paths, not TrackIDs;
* a ``<TRACK Key>`` naming an id that is not in the collection.
"""

from textwrap import dedent

#: The four collection tracks. ``t999`` is deliberately NOT among them.
FIXTURE_TRACK_IDS = ("t1", "t2", "t3", "t4")
FIXTURE_UNKNOWN_TRACK_ID = "t999"

FIXTURE_XML = dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <DJ_PLAYLISTS Version="1.0.0">
      <COLLECTION Entries="4">
        <TRACK TrackID="t1" Name="One" Artist="A" AverageBpm="128.00" Tonality="8A" Album="" Location="file://localhost/music/one.mp3"/>
        <TRACK TrackID="t2" Name="Two" Artist="B" AverageBpm="126.00" Tonality="9A" Album="" Location="file://localhost/music/two.mp3"/>
        <TRACK TrackID="t3" Name="Three" Artist="C" AverageBpm="130.00" Tonality="7A" Album="" Location="file://localhost/music/three.mp3"/>
        <TRACK TrackID="t4" Name="Four" Artist="D" AverageBpm="124.00" Tonality="6A" Album="" Location="file://localhost/music/four.mp3"/>
      </COLLECTION>
      <PLAYLISTS>
        <NODE Type="0" Name="ROOT" Count="3">
          <NODE Type="1" Name="top level" Entries="2" KeyType="0">
            <TRACK Key="t1"/>
            <TRACK Key="t2"/>
          </NODE>
          <NODE Type="0" Name="Alpha" Count="2">
            <NODE Type="1" Name="shared name" Entries="1" KeyType="0">
              <TRACK Key="t1"/>
            </NODE>
            <NODE Type="0" Name="Collections/Hauls" Count="1">
              <NODE Type="0" Name="deep" Count="1">
                <NODE Type="0" Name="deeper" Count="1">
                  <NODE Type="1" Name="five deep" Entries="1" KeyType="0">
                    <TRACK Key="t3"/>
                  </NODE>
                </NODE>
              </NODE>
            </NODE>
          </NODE>
          <NODE Type="0" Name="Beta" Count="4">
            <NODE Type="1" Name="shared name" Entries="1" KeyType="0">
              <TRACK Key="t2"/>
            </NODE>
            <NODE Type="1" Name="empty" Entries="0" KeyType="0"/>
            <NODE Type="1" Name="by path" Entries="1" KeyType="1">
              <TRACK Key="/music/one.mp3"/>
            </NODE>
            <NODE Type="1" Name="dangling" Entries="2" KeyType="0">
              <TRACK Key="t4"/>
              <TRACK Key="t999"/>
            </NODE>
          </NODE>
        </NODE>
      </PLAYLISTS>
    </DJ_PLAYLISTS>
    """
)

#: Read off the literal above, in document order:
#: ``(folder_path, name, entries, recorded track ids)``.
FIXTURE_PLAYLISTS = (
    ((), "top level", 2, ("t1", "t2")),
    (("Alpha",), "shared name", 1, ("t1",)),
    (("Alpha", "Collections/Hauls", "deep", "deeper"), "five deep", 1, ("t3",)),
    (("Beta",), "shared name", 1, ("t2",)),
    (("Beta",), "empty", 0, ()),
    # KeyType="1": catalogued, but its one path key is not recorded.
    (("Beta",), "by path", 1, ()),
    (("Beta",), "dangling", 2, ("t4", "t999")),
)

#: Folder paths, ``ROOT`` stripped, in document order.
FIXTURE_FOLDER_PATHS = (
    ("Alpha",),
    ("Alpha", "Collections/Hauls"),
    ("Alpha", "Collections/Hauls", "deep"),
    ("Alpha", "Collections/Hauls", "deep", "deeper"),
    ("Beta",),
)

#: 2 + 1 + 1 + 1 + 0 + 0 + 2, counted off the tuple above.
FIXTURE_MEMBERSHIP_COUNT = 7

#: Of those seven, only the one naming ``t999`` fails to resolve.
FIXTURE_RESOLVED = 6
FIXTURE_UNRESOLVED = 1

#: track_id -> the full paths it belongs to, in document order. Written out
#: rather than derived, because this IS the reverse index under test.
FIXTURE_REVERSE_INDEX = {
    "t1": (("top level",), ("Alpha", "shared name")),
    "t2": (("top level",), ("Beta", "shared name")),
    "t3": (("Alpha", "Collections/Hauls", "deep", "deeper", "five deep"),),
    "t4": (("Beta", "dangling"),),
    "t999": (("Beta", "dangling"),),
}


def write_fixture_xml(path, text=FIXTURE_XML):
    """Write a fixture export to ``path`` and return it."""
    path.write_text(text, encoding="utf-8")
    return path


#: Two playlists with the SAME name under the SAME parent. Rekordbox does not
#: normally produce this, which is exactly why the id scheme has to survive it:
#: without the occurrence ordinal both rows would mint the same id and the
#: second would silently overwrite the first.
DUPLICATE_PATH_XML = dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <DJ_PLAYLISTS Version="1.0.0">
      <COLLECTION Entries="0"></COLLECTION>
      <PLAYLISTS>
        <NODE Type="0" Name="ROOT" Count="1">
          <NODE Type="0" Name="Folder" Count="2">
            <NODE Type="1" Name="twin" Entries="1" KeyType="0"><TRACK Key="t1"/></NODE>
            <NODE Type="1" Name="twin" Entries="1" KeyType="0"><TRACK Key="t2"/></NODE>
          </NODE>
        </NODE>
      </PLAYLISTS>
    </DJ_PLAYLISTS>
    """
)

#: ``Entries="9"`` against three real ``<TRACK>`` children. The real export has
#: zero such mismatches, so this state is only reachable by fixture.
ENTRIES_MISMATCH_XML = dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <DJ_PLAYLISTS Version="1.0.0">
      <COLLECTION Entries="0"></COLLECTION>
      <PLAYLISTS>
        <NODE Type="0" Name="ROOT" Count="1">
          <NODE Type="1" Name="lying" Entries="9" KeyType="0">
            <TRACK Key="t1"/><TRACK Key="t2"/><TRACK Key="t3"/>
          </NODE>
        </NODE>
      </PLAYLISTS>
    </DJ_PLAYLISTS>
    """
)

#: A valid export with no ``<PLAYLISTS>`` element at all - which is what every
#: XML the indexing tests write looks like.
NO_PLAYLISTS_XML = dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <DJ_PLAYLISTS Version="1.0.0">
      <COLLECTION Entries="0"></COLLECTION>
    </DJ_PLAYLISTS>
    """
)
