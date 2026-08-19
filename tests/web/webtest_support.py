"""Helpers shared by the web tests: an HTTP client, a stub API, a fixture library.

Kept out of ``conftest.py`` so tests can import them directly. ``tests/web`` is
deliberately not a package (an ``__init__.py`` here would make pytest import
these modules as ``web.*`` and shadow ``src/web/``), so this module is reached
through the directory pytest puts on ``sys.path``.
"""

import http.client
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services"))

from fixture_library import FIXTURE_TRACKS, write_fixture_library  # noqa: E402


class Response:
    """One HTTP response, decoded lazily."""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def text(self):
        return self.body.decode("utf-8")

    @property
    def json(self):
        return json.loads(self.text)

    @property
    def content_type(self):
        return self.headers.get("Content-Type", "")

    @property
    def error_code(self):
        """The API's machine-readable error slug, for status-plus-code asserts."""
        return self.json["error"]["code"]


class Client:
    """A one-shot HTTP client over the loopback port the server bound.

    ``requests`` is not installed in CI and is not being added for a handful of
    assertions; ``http.client`` is in the standard library and it sends the
    request line verbatim, which is what the path-traversal tests need.
    """

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def request(self, method, path, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request(method, path, headers=headers or {})
            raw = connection.getresponse()
            return Response(raw.status, dict(raw.getheaders()), raw.read())
        finally:
            connection.close()

    def get(self, path, token=None):
        """GET ``path``, sending ``token`` in the header when one is given."""
        headers = {"X-Coco-Token": token} if token is not None else {}
        return self.request("GET", path, headers)


class StubApi:
    """Stands in for CocoApi while the server itself is under test.

    The server owns routing, auth and static serving; giving it the real API
    would couple its tests to library behaviour it does not implement. The
    protocol is fixed here and the real API implements it unchanged:
    ``handle(method, path, query) -> (status, body)``.
    """

    def __init__(self, response=None, raises=None):
        self.calls = []
        self.response = response if response is not None else (200, {"stub": True})
        self.raises = raises

    def handle(self, method, path, query):
        self.calls.append((method, path, query))
        if self.raises is not None:
            raise self.raises
        return self.response


def client_for(server):
    """A client pointed at a started server."""
    return Client("127.0.0.1", server.port)


# -- library fixtures ------------------------------------------------------
#
# The twelve committed tracks from tests/services/fixture_library.py are reused
# rather than reinvented: they are already explicit literals whose keys and
# BPMs are spread across every compatibility class the scorer distinguishes.
# What the API needs on top is a NaN BPM and a non-ASCII artist, added here as
# two extra rows.

WEB_EXTRA_TRACKS = [
    # A missing BPM. json.dumps renders float('nan') as the bare literal NaN,
    # which is not valid JSON and makes JSON.parse throw in WKWebView, so this
    # row is what proves the sanitiser runs.
    ("w01", "Nyege Nyege", "Tape Head", "Sounds", None, "4A", [4, 4, 0, 0, 1, 1, 0, 0]),
    # Non-ASCII, so a UTF-8 round trip over the wire is asserted rather than
    # assumed.
    ("w02", "Björk", "Jóga", "Homogenic", 96.0, "6B", [0, 3, 3, 1, 0, 0, 4, 2]),
]

#: The row with no BPM, and the row whose artist is not ASCII.
NAN_BPM_TRACK_ID = "w01"
NON_ASCII_TRACK_ID = "w02"

WEB_LIBRARY_TRACK_COUNT = len(FIXTURE_TRACKS) + len(WEB_EXTRA_TRACKS)


def write_web_fixture_library(data_dir, audio_dir=None):
    """The twelve committed tracks plus the two the API layer needs.

    Everything is written under ``data_dir``, which every caller roots at
    ``tmp_path``. The real ``data/`` directory is never read or written.
    """
    import numpy as np
    import pandas as pd

    data_dir = write_fixture_library(data_dir, audio_dir=audio_dir)

    meta = pd.read_parquet(data_dir / "meta.parquet")
    emb = pd.read_parquet(data_dir / "embeddings.parquet")
    vectors = np.load(data_dir / "index.npy")
    ids = json.loads((data_dir / "ids.json").read_text(encoding="utf-8"))

    extra_meta = []
    extra_vectors = []
    for track_id, artist, title, album, bpm, key, vector in WEB_EXTRA_TRACKS:
        extra_meta.append(
            {
                "track_id": track_id,
                "path": f"file://localhost/nonexistent/{track_id}.mp3",
                "artist": artist,
                "title": title,
                "album": album,
                "bpm": float("nan") if bpm is None else bpm,
                "key": key,
                "path_local": f"/nonexistent/{track_id}.mp3",
            }
        )
        extra_vectors.append(vector)

    extra_vectors = np.array(extra_vectors, dtype="float32")
    meta = pd.concat([meta, pd.DataFrame(extra_meta)], ignore_index=True)
    extra_emb = pd.concat(
        [
            pd.DataFrame({"track_id": [row[0] for row in WEB_EXTRA_TRACKS]}),
            pd.DataFrame(
                extra_vectors, columns=[f"v{i}" for i in range(vectors.shape[1])]
            ),
        ],
        axis=1,
    )
    emb = pd.concat([emb, extra_emb], ignore_index=True)
    vectors = np.vstack([vectors, extra_vectors])
    ids = ids + [row[0] for row in WEB_EXTRA_TRACKS]

    meta.to_parquet(data_dir / "meta.parquet", index=False)
    emb.to_parquet(data_dir / "embeddings.parquet", index=False)
    np.save(data_dir / "index.npy", vectors)
    (data_dir / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    return data_dir
