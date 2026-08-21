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

import dataclasses
import math
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from services.explore_session import ExploreSession
from services.export_service import ExportService
from services.playlist_service import IMPORT_COMMAND, PlaylistService
from services.set_builder import SetBuilder
from services.settings_store import XML_PATH_KEY

from web.jobs import JobInProgress, JobRegistry, WorkOutcome


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

# Filesystem limits differ, but a path longer than this is not useful on any
# platform the desktop app supports and can raise from a later UI callback.
MAX_XML_PATH_CHARACTERS = 4096

#: The one long operation this PR ships, as a ``JobSnapshot.kind`` value.
#: The re-index is deferred; see ``CocoApi``'s DEFERRED note.
JOB_KIND_EXPORT = "export"

#: Export writes one playlist per seed into a directory, or every seed's
#: recommendations into one de-duplicated file. Same names the service uses.
EXPORT_MODE_PER_SEED = "per_seed"
EXPORT_MODE_COMBINED = "combined"
EXPORT_MODES = (EXPORT_MODE_PER_SEED, EXPORT_MODE_COMBINED)

#: Combined mode's filename inside the chosen directory. The literal is
#: ``ui/playlist_export_tab.py:407``'s, so both front ends write and overwrite
#: the same file rather than leaving two differently-named exports behind.
#: (``export_service.COMBINED_PLAYLIST_NAME`` is a different string: the
#: playlist's *display name* written inside the M3U.)
COMBINED_EXPORT_FILENAME = "Cosine_Recommendations.m3u"

#: The Tkinter combo offers 10-50 (``playlist_export_tab.py:141``). The API is
#: not going to enforce a combo box's list, but it does refuse zero - which
#: would run the whole export and write empty playlists - and a value large
#: enough to be a typo rather than a request.
MIN_RECOMMENDATIONS_PER_TRACK = 1
MAX_RECOMMENDATIONS_PER_TRACK = 100
DEFAULT_RECOMMENDATIONS_PER_TRACK = 10

#: Accepted fields in the export-start body. Unknown fields are refused rather
#: than ignored, matching ``_update_settings`` and ``_delete_library_tracks``:
#: a misspelled ``out_dir`` must not silently start a seven-minute export into
#: the wrong place.
EXPORT_BODY_FIELDS = frozenset(
    {"mode", "out_dir", "recommendations_per_track", "track_ids"}
)

#: The longest set ``POST /api/set`` will build. The Tkinter tab has no upper
#: bound at all (inventory :501-503 lists three validations and this is not one
#: of them), so typing 100000 into ``Total Tracks`` freezes that window for as
#: long as it takes. Generation is ~2.3 ms per slot on the 1,532-track library,
#: so 500 is ~1.2 s - long enough to be useful, short enough that a loopback
#: request cannot be turned into a stall. Over the cap is REFUSED rather than
#: clamped: a silently shortened set is not the set that was asked for.
MAX_SET_TRACKS = 500

#: The two fields ``POST /api/set`` accepts, named once so the parser and its
#: error messages cannot disagree about them.
SET_ANCHORS_KEY = "anchors"
SET_TOTAL_TRACKS_KEY = "total_tracks"


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


def unknown_job(job_id: str) -> ApiError:
    """404 rather than 410 for a job that has been evicted.

    ``JobRegistry`` remembers a bounded number of finished jobs, so an id can
    stop resolving. The caller cannot act on the difference between "never
    existed" and "forgotten" - both mean *there is nothing here to poll* - and
    a 410 would invite a UI to distinguish two states it cannot verify.
    """
    return ApiError(404, "unknown_job", f"No job with id {job_id!r}.")


def job_in_progress(running) -> ApiError:
    """409 for the second job, naming the first.

    Conflict, not rate limiting: 429 would tell a caller to retry after a
    delay, and the honest instruction is "cancel or wait for that job". The
    running job's id is in the message so the UI can offer exactly that.
    """
    return ApiError(
        409,
        "job_in_progress",
        f"A {running.kind} job ({running.job_id}) is already running. "
        "Wait for it to finish or cancel it first.",
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

    # numpy's temporal scalars, and they have to be tested BEFORE the numeric
    # branches below. Neither is covered by the identity test above, because
    # ``pd.NaT is np.datetime64("NaT")`` is False - they are different objects
    # that mean the same thing. Reading a row out of a datetime64 column is how
    # they get here, and each failed differently:
    #
    #   np.datetime64("NaT")  reached the final str() fallback and serialised
    #                         as the four-character string "NaT", which the
    #                         frontend renders as if it were a date;
    #   np.timedelta64(...)   is a SUBCLASS of np.signedinteger, so the integer
    #                         branch below caught every one of them - and
    #                         ``int()`` on a timedelta64 returns a
    #                         datetime.timedelta, raising TypeError. That took
    #                         the endpoint down with a 500 for a real value,
    #                         not only for a missing one.
    #
    # Text rather than a number for the non-missing case: a timedelta64 carries
    # its unit, and an integer would drop it silently. datetime64's str() is
    # already ISO 8601, which is what the pd.Timestamp branch produces too.
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return None if np.isnat(value) else str(value)

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
# Job documents
# ---------------------------------------------------------------------------


def _job_document(snapshot) -> Dict[str, Any]:
    """One job, as JSON, from ONE ``JobSnapshot``.

    Takes the snapshot as an argument rather than a ``Job`` so the "one read,
    answer everything from it" rule is enforced by the signature: there is no
    ``job`` in scope here to re-read a field from. That is the bug
    ``PlaylistService.lookup`` was rewritten for, and job state changes far
    more often than a playlist manifest does.

    ``dict(snapshot.result)`` is not cosmetic. ``JobSnapshot.result`` is a
    ``MappingProxyType`` so a published generation cannot be mutated by a
    reader, and a ``MappingProxyType`` is **not** a ``dict`` subclass: it
    misses ``_jsonable``'s dict branch and would fall through to the final
    ``str()`` fallback, putting a Python repr on the wire where the frontend
    expects an object. Pinned by
    tests/web/test_api_jobs_wire.py::test_a_job_result_arrives_as_a_json_object.
    """
    return {
        "id": snapshot.job_id,
        "kind": snapshot.kind,
        "state": snapshot.state,
        "progress": {
            "current": snapshot.current,
            "total": snapshot.total,
            "message": snapshot.message,
        },
        "cancel_requested": snapshot.cancel_requested,
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
        "result": None if snapshot.result is None else dict(snapshot.result),
        "error": snapshot.error,
    }


def _export_result_document(result, mode: str, output: str) -> Dict[str, Any]:
    """An ``ExportResult`` as JSON, including what a cancel left behind.

    WHAT CANCELLING A HALF-FINISHED EXPORT LEAVES ON DISK
    ----------------------------------------------------
    It leaves it. That is a decision, and it is the opposite of indexing's -
    a cancelled index run discards every embedding it computed (inventory
    defect #4) - because the two produce different kinds of artefact:

    * Per-seed mode writes one complete ``.m3u`` per seed as it goes, and
      ``export_recommendations_as_playlists`` breaks at the *top* of its loop,
      before a write. So every file on disk when a cancel lands is a whole,
      importable playlist. Deleting them would mean the job layer removing
      files from a directory the **user** chose and may keep their own files
      in - a destructive act performed by a Stop button. No.
    * Combined mode accumulates in memory and writes one file *after* the
      loop, cancel or not (``playlist_exporter.py:266-269``), so a cancelled
      combined export still produces a playlist - a shorter one. That is the
      service's behaviour and this PR does not change services; what it can do
      is stop it being a surprise.

    So the honest part is the reporting, and that is what this document is
    for: ``cancelled`` beside the real counts and the path written to, so a UI
    can say "cancelled - 47 of 1,532 playlists written to ~/Desktop/..."
    rather than "cancelled" and nothing. A partial result the user is told
    about is a result; the same files with no accounting are what feels like
    corruption.

    ``playlists_created`` is explicitly ``None`` in combined mode rather than
    absent. ``ExportResult.as_legacy_stats`` *omits* the key there, which is
    what makes the Tkinter tab raise ``KeyError`` and show no completion
    dialog (inventory defect #10) - a defect of that **caller**, preserved at
    the service boundary. Reproducing the missing key on a new JSON surface
    would recreate the defect for a consumer that never had it; an explicit
    null says the same thing without arming the trap.
    """
    return {
        "mode": mode,
        "output": output,
        "total_tracks": result.total_tracks,
        "successful": result.successful,
        "failed": result.failed,
        "total_recommendations": result.total_recommendations,
        "playlists_created": result.playlists_created,
        "cancelled": result.cancelled,
    }


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
# JSON-body field parsing
# ---------------------------------------------------------------------------
#
# The query-string helpers above take ``dict[str, list[str]]`` and every value
# is text. A JSON body carries real types, so these are separate rather than
# overloaded - conflating them is how ``recommendations_per_track: "10"``
# starts being accepted by one endpoint and not another.


def _body_fields(body: Any, allowed: frozenset) -> Dict[str, Any]:
    """Validate a JSON object body and return it.

    Unknown fields are refused, matching ``_update_settings`` and
    ``_delete_library_tracks``. Silently ignoring them means a caller that
    misspells ``out_dir`` starts an export into the *default* location and
    finds out when it finishes.

    ``None`` is accepted as an empty object so a caller with nothing to say
    can POST the literal ``null`` rather than being required to know that
    ``{}`` is the spelling.
    """
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad_request("The JSON body must be an object.")
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise bad_request(
            f"Unknown field(s): {', '.join(repr(name) for name in unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
    return body


def _path_field(fields: Dict[str, Any], name: str) -> str:
    """A required, non-blank, length-capped filesystem path from a body.

    The same ceiling ``_update_settings`` puts on the XML path, for the same
    reason: longer than this is not useful on any supported platform and can
    raise from somewhere far away from the request that carried it.
    """
    value = fields.get(name)
    if not isinstance(value, str) or not value.strip():
        raise bad_request(f"{name} must be a non-blank string.")
    value = value.strip()
    if len(value) > MAX_XML_PATH_CHARACTERS:
        raise bad_request(
            f"{name} must not exceed {MAX_XML_PATH_CHARACTERS} characters."
        )
    return value


def _int_field(
    fields: Dict[str, Any], name: str, default: int, minimum: int, maximum: int
) -> int:
    """A bounded integer from a body. Out of range is a 400, not a clamp.

    Deliberately unlike ``_int_param``, which clamps a too-large ``limit``
    because "as many as you have" is a sensible reading of it. There is no
    such reading here: ``recommendations_per_track: 100000`` is a typo, and
    silently exporting 100 instead would hide it behind a seven-minute run.

    ``bool`` is rejected explicitly - it is an ``int`` subclass in Python, so
    ``True`` would otherwise be accepted and mean 1.
    """
    if name not in fields:
        return default
    value = fields[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request(f"{name} must be an integer, got {value!r}.")
    if not minimum <= value <= maximum:
        raise bad_request(
            f"{name} must be between {minimum} and {maximum}, got {value}."
        )
    return value


# ---------------------------------------------------------------------------
# Set requests
# ---------------------------------------------------------------------------


def _set_track(track) -> Dict[str, Any]:
    """One ``SetTrack`` as JSON, carrying its two computed strings.

    ``display_name`` and ``icon`` are ``@property``, so ``dataclasses.asdict``
    does not see them and the wire format would lose both. They are sent rather
    than recomputed in JavaScript on purpose: ``display_name`` has a four-branch
    resolution order ending in ``Track #{track_id}`` for an all-digit id
    (``recommendations/models.py:18-30``, inventory :484-486), and a second copy
    of it in the frontend is a second thing to keep in step with the first. The
    unfillable-slot row inventory :490-495 describes is produced entirely by
    that property, from an artist and an empty title.
    """
    detail = dataclasses.asdict(track)
    detail["display_name"] = track.display_name
    detail["icon"] = track.icon
    return detail


def _set_anchors(raw: Any) -> Dict[int, str]:
    """``{"3": "f01"}`` from JSON into ``{3: "f01"}``.

    JSON object keys are strings, so the positions arrive as text and have to
    be converted before ``generate_set`` indexes with them.

    A position below 1 is refused. ``generate_set`` does not check it - it
    assigns ``set_slots[position - 1]``, so 0 writes to the LAST slot and -1 to
    the one before it, silently putting the anchor somewhere nobody asked for.
    Inventory :963 states the rule the dialog enforces ("Position must be 1 or
    greater"), and this is the same rule at the layer that can be reached
    without the dialog.
    """
    if not isinstance(raw, dict):
        raise bad_request(f"{SET_ANCHORS_KEY} must be an object of position -> track id.")

    anchors: Dict[int, str] = {}
    for key, track_id in raw.items():
        try:
            position = int(str(key))
        except (TypeError, ValueError):
            raise bad_request(
                f"{SET_ANCHORS_KEY} keys must be integer positions, got {key!r}."
            ) from None
        if position < 1:
            raise bad_request(
                f"{SET_ANCHORS_KEY} positions must be 1 or greater, got {position}."
            )
        if not isinstance(track_id, str) or not track_id:
            raise bad_request(
                f"{SET_ANCHORS_KEY}[{key!r}] must be a non-empty track id."
            )
        anchors[position] = track_id
    return anchors


def _set_total_tracks(raw: Any) -> int:
    """The requested length, refused rather than clamped when it is over the cap.

    ``isinstance(True, int)`` is True in Python, so booleans are excluded
    explicitly: ``total_tracks: true`` would otherwise mean a one-track set.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise bad_request(f"{SET_TOTAL_TRACKS_KEY} must be an integer, got {raw!r}.")
    if raw > MAX_SET_TRACKS:
        raise bad_request(
            f"{SET_TOTAL_TRACKS_KEY} must not exceed {MAX_SET_TRACKS}, got {raw}."
        )
    return raw


def _set_request(body: Any) -> Tuple[Dict[int, str], int]:
    """Both fields of a set request, or a 400 naming what is wrong.

    Exactly these two keys, as ``_update_settings`` requires exactly its one:
    an unrecognised field is far more likely to be a caller that thinks it is
    configuring something than a field to ignore.
    """
    expected = {SET_ANCHORS_KEY, SET_TOTAL_TRACKS_KEY}
    if not isinstance(body, dict) or set(body) != expected:
        raise bad_request(
            "The JSON body must contain exactly two fields: "
            f"{SET_ANCHORS_KEY} and {SET_TOTAL_TRACKS_KEY}."
        )

    return _set_anchors(body[SET_ANCHORS_KEY]), _set_total_tracks(
        body[SET_TOTAL_TRACKS_KEY]
    )


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


class CocoApi:
    """Routes JSON requests onto the services layer."""

    def __init__(
        self,
        library,
        settings,
        explore=None,
        playlists=None,
        sets=None,
        jobs=None,
        export_service=None,
    ):
        """Bind to a library and a settings store.

        Args:
            library: a ``LibrarySession``.
            settings: a ``SettingsStore``.
            explore: an ``ExploreSession``; built from ``library`` when absent,
                which is all the default construction ever is. Injectable so a
                test can watch the arguments it is called with.
            playlists: a ``PlaylistService``. Built over the library's own data
                directory when absent, so the playlist tables are looked for
                beside the index they describe rather than in the configured
                directory - a library opened with ``--data-dir`` must not read
                another directory's playlists. Constructing one touches no
                disk; a library object with no ``data_dir`` (the in-memory
                doubles two tests use for the browse and search caps) falls
                back to the configured directory, which is where a real
                deployment's is anyway.
            sets: a ``SetBuilder``. Built over ``library`` when absent, which
                is all the default construction ever is - the builder holds a
                reference and reads ``meta_ix``/``emb_ix``/``index`` live, so
                one built here follows an index rebuild. Injectable for the
                same reason ``explore`` is: so a test can watch the anchors and
                the length it is actually handed.
            jobs: a ``web.jobs.JobRegistry``. One per API, holding the
                long-running work; built here when absent. Injectable so a
                test can supply a fake clock and deterministic ids.
            export_service: an ``ExportService``. Built over ``library`` when
                absent. Injectable because the real one takes ~6.8 minutes
                over the full collection, which no test may spend.
        """
        self.library = library
        self.settings = settings
        self.explore = explore if explore is not None else ExploreSession(library)
        self.playlists = (
            playlists
            if playlists is not None
            else PlaylistService(getattr(library, "data_dir", None))
        )
        self.sets = sets if sets is not None else SetBuilder(library)

        self.jobs = jobs if jobs is not None else JobRegistry()
        # Cheap to construct and holds no state between runs - it snapshots
        # the library per export. Building it here rather than per request
        # keeps the request path free of construction that could raise.
        self.export_service = (
            export_service if export_service is not None else ExportService(library)
        )

        self._settings_write_lock = threading.Lock()
        self._library_write_lock = threading.Lock()

    # -- routing -----------------------------------------------------------
    #
    # An ordered list of (method, pattern, handler name). No routing library:
    # the table is short. Two ordering constraints: /api/tracks/search is
    # matched before /api/tracks/{track_id}, and the literal /api/jobs/export
    # is matched before /api/jobs/{job_id}. A list expresses that better than
    # a dependency would. Deliberately no count in this comment: the
    # destinations still to be built each add rows, so a number here is a
    # merge conflict and a wrong fact the moment one of them lands.

    ROUTES = [
        ("GET", re.compile(r"^/api/health$"), "_health"),
        ("GET", re.compile(r"^/api/library$"), "_library"),
        ("GET", re.compile(r"^/api/library/tracks$"), "_library_tracks"),
        (
            "POST",
            re.compile(r"^/api/library/tracks/delete$"),
            "_delete_library_tracks",
        ),
        # Jobs. The literal POST route is listed before the ``{job_id}``
        # ones so ``/api/jobs/export`` is a route and not a job called
        # "export"; ``handle`` matches in order.
        ("GET", re.compile(r"^/api/jobs$"), "_jobs"),
        ("POST", re.compile(r"^/api/jobs/export$"), "_start_export"),
        (
            "POST",
            re.compile(r"^/api/jobs/(?P<job_id>[^/]+)/cancel$"),
            "_cancel_job",
        ),
        ("GET", re.compile(r"^/api/jobs/(?P<job_id>[^/]+)$"), "_job"),
        ("GET", re.compile(r"^/api/settings$"), "_settings"),
        ("POST", re.compile(r"^/api/settings$"), "_update_settings"),
        ("POST", re.compile(r"^/api/set$"), "_generate_set"),
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
        self,
        method: str,
        path: str,
        query: Dict[str, List[str]],
        body: Any = None,
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
                arguments = match.groupdict()
                if method == "POST":
                    arguments["body"] = body
                return getattr(self, handler_name)(query, **arguments)
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

    def _library_tracks(self, query):
        """Every row the Library destination filters and sorts in the browser."""
        snapshot = self.library.snapshot()
        if snapshot.meta_ix is None:
            return 200, {"tracks": [], "total": 0}

        tracks = []
        for track_id, row in snapshot.meta_ix.iterrows():
            tracks.append(
                {
                    "track_id": str(track_id),
                    "artist": row.get("artist", ""),
                    "title": row.get("title", ""),
                    "album": row.get("album", ""),
                    "key": row.get("key", ""),
                    "bpm": row.get("bpm", ""),
                    "path_local": row.get("path_local", ""),
                }
            )
        return 200, _jsonable({"tracks": tracks, "total": len(tracks)})

    def _delete_library_tracks(self, query, body):
        """Delete one selection through LibrarySession's atomic mutation.

        IDs are newline-delimited inside one JSON string. The real collection's
        full 1,532-ID selection is 14.7 KiB in that representation and therefore
        still fits the server's fixed 16 KiB request-body ceiling; a JSON array
        of the same IDs does not.
        """
        if not isinstance(body, dict) or set(body) != {"track_ids"}:
            raise bad_request(
                "The JSON body must contain exactly one field: track_ids."
            )

        encoded_ids = body["track_ids"]
        if not isinstance(encoded_ids, str) or not encoded_ids:
            raise bad_request("track_ids must be a non-empty newline-delimited string.")
        track_ids = encoded_ids.split("\n")
        if any(not track_id for track_id in track_ids):
            raise bad_request("track_ids must not contain blank track IDs.")
        if len(set(track_ids)) != len(track_ids):
            raise bad_request("track_ids must not contain duplicates.")

        # Serialise validation with the mutation so two simultaneous requests
        # cannot both validate one ID and let the second silently delete zero.
        with self._library_write_lock:
            for track_id in track_ids:
                if self.library.get_track(track_id) is None:
                    raise unknown_track(track_id)
            deleted = self.library.delete_tracks(track_ids)
            return 200, _jsonable(
                {
                    "deleted": deleted,
                    "track_ids": track_ids,
                    "library": {
                        "track_count": self.library.track_count,
                        "is_empty": self.library.is_empty,
                    },
                }
            )

    def _settings(self, query):
        return 200, self._settings_document()

    def _update_settings(self, query, body):
        """Persist the one value the existing Settings window can change.

        ``first_run_complete`` is a real setting, but it controls whether the
        onboarding flow runs and is not a user-editable preference. Keeping it
        out of both response and request prevents this small endpoint from
        becoming a generic settings-file editor.
        """
        if not isinstance(body, dict) or set(body) != {XML_PATH_KEY}:
            raise bad_request(
                f"The JSON body must contain exactly one field: {XML_PATH_KEY}."
            )

        xml_path = body[XML_PATH_KEY]
        if not isinstance(xml_path, str) or not xml_path.strip():
            raise bad_request(f"{XML_PATH_KEY} must be a non-blank string.")
        xml_path = xml_path.strip()
        if len(xml_path) > MAX_XML_PATH_CHARACTERS:
            raise bad_request(
                f"{XML_PATH_KEY} must not exceed {MAX_XML_PATH_CHARACTERS} characters."
            )

        # SettingsStore.set is deliberately the merge operation: changing the
        # XML path must preserve first_run_complete, as the Tkinter window does.
        # The chosen path is not checked for existence there, so it is not
        # checked here either.
        with self._settings_write_lock:
            self.settings.set(XML_PATH_KEY, xml_path)
            return 200, self._settings_document()

    def _settings_document(self):
        return {
            "settings": {
                XML_PATH_KEY: _jsonable(self.settings.get(XML_PATH_KEY)),
            }
        }

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

    def _recommendations(self, query, track_id):
        """Ranked recommendations for a seed track.

        Emptiness is checked before the seed is looked up. Both errors are true
        of a library with no index, and the 409 is the more informative one -
        it says why nothing can be recommended rather than blaming the id. It
        is also the only ordering under which the 409 is reachable at all:
        ``LibrarySession.delete_tracks`` empties ``meta_ix`` along with the
        index, so there is no such thing as a known track id in a library that
        has none.
        """
        if self.library.is_empty:
            raise empty_library()

        seed = self._detail(track_id)

        topk = _int_param(query, "topk", EXPLORE_TOPK)
        final_top = _int_param(query, "final_top", EXPLORE_FINAL_TOP)
        limit = _int_param(
            query,
            "limit",
            DEFAULT_RECOMMENDATION_LIMIT,
            MAX_RECOMMENDATION_LIMIT,
        )

        ranked = self.explore.recommend(track_id, topk=topk, final_top=final_top)

        # Truncation happens HERE, after ranking, and `limit` is never passed
        # as final_top. final_top decides the *membership* of the result by
        # weighted score; the order is then by raw cosine (inventory §3.3).
        # Confusing the two changes which tracks come back, not merely how many.
        return 200, {
            "seed": seed,
            "recommendations": [
                _jsonable(dataclasses.asdict(rec)) for rec in ranked[:limit]
            ],
        }

    # -- jobs --------------------------------------------------------------

    def _jobs(self, query):
        """Every remembered job, newest first.

        The endpoint a page uses on load: a reload during a seven-minute
        export must be able to find the export again, and it does not know the
        id it was given before the reload.
        """
        return 200, _jsonable(
            {"jobs": [_job_document(job.snapshot()) for job in self.jobs.all()]}
        )

    def _job(self, query, job_id):
        """One job. The endpoint a UI polls; see ``web.jobs`` on why polling."""
        job = self.jobs.get(job_id)
        if job is None:
            raise unknown_job(job_id)
        return 200, _jsonable({"job": _job_document(job.snapshot())})

    def _cancel_job(self, query, job_id, body):
        """Ask a job to stop, and answer with its state *after* the request.

        200 rather than 409 for a job that has already finished. Pressing Stop
        as a run completes is a race the user cannot avoid, and an error there
        would be an error about nothing. The returned document is unambiguous
        either way: ``cancel_requested`` is true only if the signal really was
        delivered, and ``state`` says what the job actually did.

        The body must be empty. A cancel takes no arguments, and accepting
        fields nobody reads is how an endpoint acquires ones somebody does.
        """
        if body not in (None, {}):
            raise bad_request("The cancel request takes no fields.")

        job = self.jobs.get(job_id)
        if job is None:
            raise unknown_job(job_id)
        # ONE call: request_cancel returns the snapshot it published, so the
        # response describes the state this request produced rather than
        # whatever a second read would have found.
        return 200, _jsonable({"job": _job_document(job.request_cancel())})

    def _start_export(self, query, body):
        """Start an export job. 202, or 409 if a job is already running.

        The whole request is validated - the mode, the directory, the count
        and every track id - **before** the job starts, so a mistyped field is
        a 400 the caller sees now rather than a job that fails seven minutes
        later. Track ids are resolved against ONE ``library.snapshot()``, the
        same capture discipline ``ExportService`` uses internally.
        """
        fields = _body_fields(body, EXPORT_BODY_FIELDS)

        mode = fields.get("mode", EXPORT_MODE_PER_SEED)
        if mode not in EXPORT_MODES:
            raise bad_request(
                f"mode must be one of {', '.join(EXPORT_MODES)}, got {mode!r}."
            )

        out_dir = _path_field(fields, "out_dir")
        per_track = _int_field(
            fields,
            "recommendations_per_track",
            DEFAULT_RECOMMENDATIONS_PER_TRACK,
            MIN_RECOMMENDATIONS_PER_TRACK,
            MAX_RECOMMENDATIONS_PER_TRACK,
        )
        track_ids = self._export_track_ids(fields)

        if mode == EXPORT_MODE_COMBINED:
            # The directory is not created for combined mode - the exporter
            # never has (``export_service`` module docstring, "Combined mode
            # does not create its output directory"), and this PR changes no
            # service. A missing directory surfaces as a failed job carrying
            # the OSError's own message rather than as a silent no-op.
            output = str(Path(out_dir) / COMBINED_EXPORT_FILENAME)
        else:
            output = out_dir

        service = self.export_service

        def work(report, cancel):
            if mode == EXPORT_MODE_COMBINED:
                result = service.export_combined(
                    track_ids, output, per_track, progress=report, cancel=cancel
                )
            else:
                result = service.export_per_seed(
                    track_ids, output, per_track, progress=report, cancel=cancel
                )
            return WorkOutcome(
                cancelled=result.cancelled,
                result=_export_result_document(result, mode, output),
            )

        return self._start(
            JOB_KIND_EXPORT,
            work,
            total=len(track_ids),
            message=f"Exporting {len(track_ids)} tracks",
        )

    # DEFERRED: POST /api/jobs/reindex was here, and it is not in this PR.
    #
    # It was cut on review, not postponed for want of time. The endpoint had a
    # demonstrated data-loss path with two independent halves, and only the
    # second of them can be fixed inside src/web/.
    #
    # (a) IT CAN REWRITE A LIBRARY THE REQUEST NEVER NAMED.
    #     ``web.host.build_api(data_dir)`` binds the LibrarySession, the
    #     SettingsStore and the PlaylistService to ``data_dir``, so
    #     ``ui-web --data-dir X`` really does open X. The indexing pipeline
    #     does not take part in that: ``IndexingService.__init__`` takes only a
    #     settings store (services/indexing_service.py:155) and
    #     ``IndexingService.run(xml_path, force_full, progress, cancel,
    #     sample_size)`` has no data-directory parameter at all (:159).
    #     ``index_library`` loads through ``load_existing_data`` and persists
    #     through ``save_index_data`` (processing/pipeline.py:193, :337), and
    #     ``core.persistence`` writes to ``config.META_PQ`` / ``EMB_PQ`` /
    #     ``IDX_NPY`` / ``IDS_JSON`` - four module constants derived once from
    #     the global ``config.DATA`` (config/paths.py:33, :43-47).
    #
    #     So a force re-index started from a window opened on X reads X's
    #     configured XML and overwrites the DEFAULT library's four files with
    #     it. On this machine the default library is the maintainer's real
    #     1,532-track index. That is the data loss, and no amount of care in
    #     this file prevents it: the write target is decided at import time,
    #     three layers down, by a module constant.
    #
    # (b) EVEN ON THE DEFAULT DIRECTORY, THE API KEEPS THE STALE LIBRARY.
    #     A re-index rewrites the four files on disk, and nothing here calls
    #     ``LibrarySession.reload`` (services/library_session.py:99) afterwards
    #     - so the API goes on serving the generation it loaded at startup.
    #     Modelled over the fourteen-track fixture with a signature-correct run
    #     committing a real fifteen-track generation: the job reported success
    #     with 15, ``GET /api/library`` still said 14, and a subsequent
    #     ``POST /api/library/tracks/delete`` wrote its replacement generation
    #     from that stale 14-track snapshot - replacing the 15-track generation
    #     on disk with a 13-track one and losing the newly indexed track.
    #
    # (b) alone is an omission and one line fixes it. (a) is an architectural
    # mismatch between a process-global data directory and a per-session one,
    # and closing it means changing src/services/ and src/processing/ - which
    # this PR must not do, and which deserves its own PR and its own review.
    # Adding the reload without that would leave a reachable route that
    # rewrites the wrong library, so the route is gone instead.
    #
    # What is NOT deferred: the generic job machinery in ``web.jobs`` stays,
    # including the ``KeyboardInterrupt``-as-cancellation handling that exists
    # for the indexing pipeline's checkpoint. It is exercised directly by
    # tests/web/test_jobs_registry.py, and it is what the re-index will be
    # built on once its data directory is its own.

    def _start(self, kind, work, total=0, message=""):
        """Register a job, or turn the one-at-a-time refusal into a 409."""
        try:
            job = self.jobs.start(kind, work, total=total, message=message)
        except JobInProgress as conflict:
            raise job_in_progress(conflict.running) from None
        # 202: the response describes work that has been accepted and is not
        # finished. A 200 would say the export is done.
        return 202, _jsonable({"job": _job_document(job.snapshot())})

    def _export_track_ids(self, fields) -> List[str]:
        """The seeds to export, validated against one library snapshot.

        ``track_ids`` absent means the whole library, which is both the
        measured 6.8-minute case and the one that does not fit on the wire:
        the full 1,532-id selection is 14.7 KiB newline-delimited (see
        ``_delete_library_tracks``) against a fixed 16 KiB request-body
        ceiling, leaving under 2 KiB for the directory path and everything
        else. Omitting the field removes that cliff for the common case
        instead of engineering around it.

        Ids are checked for membership up front. The exporter counts an
        unknown id as ``failed`` and carries on, which on a seven-minute run
        means the caller learns about a typo at the end; a 404 now is the same
        verdict, earlier, and matches ``_delete_library_tracks``.
        """
        # ONE capture. Re-reading ``self.library.meta_ix`` per check would let
        # a concurrent delete land between the membership test and the count.
        snapshot = self.library.snapshot()
        known = snapshot.meta_ix

        raw = fields.get("track_ids")
        if raw is None:
            if known is None or len(known.index) == 0:
                raise empty_library()
            return [str(track_id) for track_id in known.index]

        if not isinstance(raw, str) or not raw:
            raise bad_request(
                "track_ids must be a non-empty newline-delimited string."
            )
        track_ids = raw.split("\n")
        if any(not track_id for track_id in track_ids):
            raise bad_request("track_ids must not contain blank track IDs.")
        if len(set(track_ids)) != len(track_ids):
            raise bad_request("track_ids must not contain duplicates.")

        if known is None:
            raise empty_library()
        membership = {str(track_id) for track_id in known.index}
        for track_id in track_ids:
            if track_id not in membership:
                raise unknown_track(track_id)
        return track_ids

    def _generate_set(self, query, body):
        """Build a DJ set around ``{position: track_id}`` anchors.

        POST, and the body is the reason. The request is an anchor MAP plus a
        length; a query string can carry that only by inventing an encoding for
        a mapping, and the one place this app already encodes structure - the
        settings write - does it as JSON in a body. Nothing is stored: the set
        is computed and returned, and the client owns it from there. That is
        why there is no ``GET /api/set/{id}`` to go with this.

        No progress stream and no cancellation, deliberately. Generation is
        ~2.3 ms per slot on the 1,532-track library - 0.064 s for the 30-track
        set inventory :511-512 recorded at 2.76 s before the transition-vector
        work - so the whole ``MAX_SET_TRACKS`` ceiling is about 1.2 s. Building
        a progress channel for that would cost more than the wait it reports.

        Emptiness is checked first, for the reason ``_recommendations`` gives:
        a library with no index cannot answer this, and the 409 says why rather
        than blaming the anchors.

        Validation of the REQUEST is here; validation of the USER'S INPUT is
        not. Inventory :501-503 lists three checks the Tkinter tab makes before
        it calls the builder - a non-integer length, no anchors, a length below
        the anchor count - and each raises a named dialog. Those belong to the
        control that owns the entry field, so the web Set Creator makes them in
        the same order with the same strings (``set-creator.js``). What this
        method refuses is a request no control could have produced: a body of
        the wrong shape, a position that is not a positive integer, a length
        over the cap. Everything the builder itself rejects - no anchors, an
        anchor past the end - is left to the builder so there is exactly one
        implementation of it, and comes back as ``set_generation_failed``
        carrying the service's own message.
        """
        if self.library.is_empty:
            raise empty_library()

        anchors, total_tracks = _set_request(body)

        try:
            tracks = self.sets.build(anchors, total_tracks)
        except ValueError as error:
            # The two the service raises are "At least one anchor track is
            # required" and "Anchor track position exceeds total tracks"
            # (set_generator.py:41-44). Inventory :506-508 sends the second one
            # to the "Generation Error" dialog as "Failed to generate set:
            # {error}", so the message travels rather than being replaced.
            raise ApiError(400, "set_generation_failed", str(error)) from None

        return 200, _jsonable({"tracks": [_set_track(track) for track in tracks]})

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
        """One track's metadata, sanitised, with its playlist membership.

        Filling the field the drawer already fetches, rather than adding a
        ``GET /api/tracks/{id}/playlists`` route. The drawer opens with exactly
        one request today and a second one would buy nothing: the lookup is a
        dict hit against a reverse index built once at first use, so it costs
        less than the round trip would. It also keeps ``ROUTES`` untouched,
        which matters while ``feat/web-write-surface`` is editing that list.
        """
        track = self.library.get_track(track_id)
        if track is None:
            raise unknown_track(track_id)

        detail = _jsonable(track)
        # Still explicitly null when nothing has been imported - the drawer
        # tells "no playlist data" from "this track is in no playlists", and
        # the two are different screens. An empty LIST is the second one.
        #
        # ONE call, not three. ``PlaylistService`` re-reads the manifest on
        # every access so that the app follows an import run in a terminal, so
        # separate calls for the rows, the provenance and the staleness verdict
        # are separate chances to be told about different generations - and the
        # drawer would render the mixture as one import. ``lookup`` checks the
        # pointer once and answers every part of the question from what it
        # found.
        answer = self.playlists.lookup(track_id)
        detail["playlists"] = self._playlists(answer)
        detail["playlist_source"] = self._playlist_source(answer)
        return detail

    @staticmethod
    def _playlists(answer) -> Optional[List[Dict[str, Any]]]:
        """This track's playlists, or ``None`` when none have been imported.

        ``folder_path`` goes over the wire as a LIST OF SEGMENTS and is joined
        by the drawer. Two folder names in the real export contain a forward
        slash, so joining here would hand the UI a string it cannot take apart.
        """
        found = answer.playlists
        if found is None:
            return None
        return [
            {
                "playlist_id": playlist.playlist_id,
                "name": playlist.name,
                "folder_path": list(playlist.folder_path),
                "entries": playlist.entries,
            }
            for playlist in found
        ]

    @staticmethod
    def _playlist_source(answer) -> Optional[Dict[str, Any]]:
        """Provenance and the staleness verdict, or ``None`` before any import.

        The absolute ``source_xml`` is deliberately NOT sent. Spec §6.4's own
        example is "from ``242.xml``, imported 12 Aug", which the basename and
        the timestamp answer completely; the full path would put a home
        directory into every screenshot of the drawer and buys the UI nothing.
        ``import_command`` travels with it so the call to action names the same
        command the service does, rather than the frontend keeping its own copy
        of a string that can drift.
        """
        provenance = answer.provenance
        if provenance is None:
            return None

        verdict = answer.staleness
        return _jsonable(
            {
                "source_name": provenance.source_name,
                "imported_at": provenance.imported_at,
                "playlist_count": provenance.playlist_count,
                "entry_count": provenance.membership_count,
                "stale": verdict.stale,
                "source_missing": verdict.source_missing,
                "reason": verdict.reason,
                "import_command": IMPORT_COMMAND,
            }
        )
