#!/usr/bin/env python3
"""The JSON API: a thin adapter over the services layer.

No business logic lives here. Every endpoint translates a query string into a
service call and the result into JSON, and the two hard parts of doing that are
both about honesty of representation rather than about behaviour:

**Sanitising.** ``LibrarySession.get_track`` builds its dict from a pandas row
and ``ExploreSession.recommend`` returns dataclasses whose numbers come out of
numpy. ``json.dumps`` cannot serialise ``numpy.float64`` at all, and it
serialises ``float('nan')`` - which is what a track with no BPM has - as the
bare literal ``NaN``. That is not valid JSON, ``JSON.parse`` in WKWebView
throws on it, and the frontend sees an empty list rather than an error naming
the field. ``_jsonable`` is the single funnel every outgoing value passes
through.

**Status codes.** They are part of the contract and the frontend branches on
them, so each one is chosen deliberately rather than falling out of an
exception: an unknown seed is 404, a library with no index is 409, a
non-integer parameter is 400 rather than a 500 traceback.

This module must not import a UI toolkit or Essentia; see
tests/web/test_no_heavy_imports.py.
"""

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from services.explore_session import ExploreSession

API_VERSION = 1
APP_NAME = "cosine-companion"

#: The separator every user-facing list in the app uses: U+2013, not a hyphen
#: (inventory §3.1). ``recommendations.search.search_tracks`` already builds its
#: display names this way; browse has to match it or the palette's two states
#: would render differently.
EN_DASH = "–"

DEFAULT_BROWSE_LIMIT = 50
MAX_BROWSE_LIMIT = 500

DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100

#: The Explore tab's candidate-pool configuration, confirmed against
#: docs/UI_FEATURE_INVENTORY.md:1378 ("Explore computation | topk=500,
#: final_top=200") and :370. These are NOT ExploreSession's own defaults, which
#: come from config.defaults (DEFAULT_TOPK=200, DEFAULT_FINAL_TOP=15) and are
#: the CLI/library values - so both are passed explicitly on every call.
EXPLORE_TOPK = 500
EXPLORE_FINAL_TOP = 200

DEFAULT_RECOMMENDATION_LIMIT = 50
MAX_RECOMMENDATION_LIMIT = 200


class ApiError(Exception):
    """An error with a status code and a machine-readable slug.

    Raised by parameter parsing and route handlers so every failure path builds
    the same body shape rather than each one assembling its own.
    """

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def as_response(self) -> Tuple[int, Dict[str, Any]]:
        return self.status, {"error": {"code": self.code, "message": self.message}}


def bad_request(message: str) -> ApiError:
    return ApiError(400, "bad_request", message)


def unknown_track(track_id: str) -> ApiError:
    return ApiError(404, "unknown_track", f"No track with id {track_id!r}.")


def not_found(path: str) -> ApiError:
    return ApiError(404, "not_found", f"No endpoint at {path!r}.")


def empty_library() -> ApiError:
    return ApiError(
        409,
        "empty_library",
        "The library has no index. Index a Rekordbox collection first.",
    )


# ---------------------------------------------------------------------------
# JSON sanitisation
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Return ``value`` as something ``json.dumps(..., allow_nan=False)`` accepts.

    Missing data of every flavour - ``None``, ``NaN``, ``NaT``, ``pd.NA`` - maps
    to ``None``, and so do the non-finite floats, because ``Infinity`` is
    rejected by ``JSON.parse`` for the same reason ``NaN`` is. numpy scalars
    become their Python equivalents; arrays, tuples, dicts and lists are walked.

    The final branch stringifies anything unrecognised. That is deliberate and
    it is last: a future metadata column holding an object nobody anticipated
    should degrade to text, not take the endpoint down with a 500.

    Never mutates its argument - ``get_track``'s dict is built from the live
    library and later readers see the original values.
    """
    if value is None:
        return None

    # pandas' missing-value singletons. pd.isna is not used as the first test
    # because it is elementwise over arrays and returns an array, not a bool.
    if value is pd.NaT or value is pd.NA:
        return None

    if isinstance(value, (bool, np.bool_)):
        return bool(value)

    if isinstance(value, (int, np.integer)):
        return int(value)

    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None

    if isinstance(value, (str, np.str_)):
        return str(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]

    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    return str(value)


# ---------------------------------------------------------------------------
# Query-parameter parsing
# ---------------------------------------------------------------------------


def _first(query: Dict[str, List[str]], name: str) -> Optional[str]:
    """The first value for ``name``, or ``None``.

    First rather than last, matching how every mainstream server reads a
    repeated parameter, so a duplicated ``?limit=`` is not silently the other
    one.
    """
    values = query.get(name) or []
    return values[0] if values else None


def _int_param(
    query: Dict[str, List[str]], name: str, default: int, maximum: Optional[int] = None
) -> int:
    """Read an integer parameter, clamping above and refusing nonsense.

    A value over ``maximum`` is clamped rather than rejected: it is a request
    for "as many as you have" and answering it is more useful than a 400. A
    non-integer or a negative value is a caller bug and gets a 400 - never a
    500 traceback.
    """
    raw = _first(query, name)
    if raw is None:
        return default

    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        raise bad_request(f"{name} must be an integer, got {raw!r}.") from None

    if parsed < 0:
        raise bad_request(f"{name} must not be negative, got {parsed}.")

    if maximum is not None:
        return min(parsed, maximum)
    return parsed


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


class CocoApi:
    """Routes JSON requests onto the services layer."""

    def __init__(self, library, settings, explore=None):
        """Bind to a library and a settings store.

        Args:
            library: a ``LibrarySession``.
            settings: a ``SettingsStore``.
            explore: an ``ExploreSession``; built from ``library`` when absent,
                which is all the default construction ever is. Injectable so a
                test can watch the arguments it is called with.
        """
        self.library = library
        self.settings = settings
        self.explore = explore if explore is not None else ExploreSession(library)

    # -- routing -----------------------------------------------------------
    #
    # An ordered list of (method, pattern, handler name). No routing library:
    # there are six routes and the only ordering constraint is that
    # /api/tracks/search is matched before /api/tracks/{track_id}, which a list
    # expresses better than a dependency would.

    ROUTES = [
        ("GET", re.compile(r"^/api/health$"), "_health"),
        ("GET", re.compile(r"^/api/library$"), "_library"),
        ("GET", re.compile(r"^/api/tracks$"), "_browse"),
        ("GET", re.compile(r"^/api/tracks/search$"), "_search"),
        (
            "GET",
            re.compile(r"^/api/tracks/(?P<track_id>[^/]+)/recommendations$"),
            "_recommendations",
        ),
        ("GET", re.compile(r"^/api/tracks/(?P<track_id>[^/]+)$"), "_track"),
    ]

    def handle(
        self, method: str, path: str, query: Dict[str, List[str]]
    ) -> Tuple[int, Dict[str, Any]]:
        """Dispatch one request. Never raises; every failure is a status code."""
        matched_path = False
        for verb, pattern, handler_name in self.ROUTES:
            match = pattern.match(path)
            if match is None:
                continue
            matched_path = True
            if verb != method:
                continue
            try:
                return getattr(self, handler_name)(query, **match.groupdict())
            except ApiError as error:
                return error.as_response()

        if matched_path:
            return ApiError(
                405, "method_not_allowed", f"{method} is not supported."
            ).as_response()
        return not_found(path).as_response()

    # -- endpoints ---------------------------------------------------------

    def _health(self, query):
        """Liveness. Deliberately independent of whether a library loaded."""
        return 200, {"ok": True, "app": APP_NAME, "api_version": API_VERSION}

    def _library(self, query):
        return 200, _jsonable(
            {
                "track_count": self.library.track_count,
                "is_empty": self.library.is_empty,
                "data_dir": str(self.library.data_dir),
                "xml_path": self.settings.xml_path,
            }
        )

    def _browse(self, query):
        """The first page of the library, for the palette's empty state.

        The Tkinter selector dialogs show nothing at all until you type
        (inventory defect #9). That defect is characterised against the
        *service* and the service is unchanged; this endpoint is the new
        surface's answer to the same question, and it does not go through
        ``search_tracks``.
        """
        limit = _int_param(query, "limit", DEFAULT_BROWSE_LIMIT, MAX_BROWSE_LIMIT)
        meta_ix = self.library.meta_ix

        if meta_ix is None:
            return 200, {"tracks": [], "total": 0}

        tracks = [
            self._summary(track_id, row)
            for track_id, row in meta_ix.head(limit).iterrows()
        ]
        return 200, _jsonable({"tracks": tracks, "total": self.library.track_count})

    def _search(self, query):
        raw = _first(query, "q")
        if raw is None or not raw.strip():
            raise bad_request("q is required and must not be blank.")

        limit = _int_param(query, "limit", DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT)

        if self.library.meta_ix is None:
            return 200, {"results": [], "query": raw}

        results = self.library.search_tracks(raw, limit=limit)
        return 200, _jsonable({"results": results, "query": raw})

    def _track(self, query, track_id):
        return 200, {"track": self._detail(track_id)}

    # -- helpers -----------------------------------------------------------

    def _summary(self, track_id, row) -> Dict[str, Any]:
        """The shape ``search_tracks`` returns, built from a browse row.

        Kept identical on purpose: the palette renders one list from two
        endpoints and must not need to know which one it is showing.
        """
        artist = row.get("artist", "")
        title = row.get("title", "")
        return {
            "track_id": track_id,
            "artist": artist,
            "title": title,
            "display_name": f"{artist} {EN_DASH} {title}",
        }

    def _detail(self, track_id: str) -> Dict[str, Any]:
        """One track's metadata, sanitised, with the PR 4 field reserved."""
        track = self.library.get_track(track_id)
        if track is None:
            raise unknown_track(track_id)

        detail = _jsonable(track)
        # Explicitly null rather than absent, so the drawer can distinguish
        # "not implemented yet" from "this track is in no playlists". PR 4
        # fills it in from the Rekordbox XML; nothing here invents it.
        detail["playlists"] = None
        return detail
