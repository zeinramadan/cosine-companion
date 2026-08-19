#!/usr/bin/env python3
"""The loopback HTTP server: binding, token auth, routing, static files.

No domain logic lives here. The server knows three things - how to bind
loopback on an ephemeral port, how to decide whether a caller may use the API,
and how to hand a request to something that does know: any object with

    handle(method: str, path: str, query: dict[str, list[str]]) -> (int, dict)

``web.api.CocoApi`` is that object in production; the server's own tests use a
stub, which is the point of keeping the protocol this narrow.

**Why there is a token at all.** Binding 127.0.0.1 keeps the LAN out but not
other processes running as this user, and the API can read the whole music
library. A per-process ``secrets.token_urlsafe(32)`` is what closes that, and
it is required on *every* ``/api/`` request including ``/api/health`` - an
unauthenticated endpoint is an unauthenticated endpoint. Static assets are
served without it so the page can bootstrap and read ``?key=`` out of its own
URL; the API is the thing being protected, not the HTML shell.
"""

import hmac
import json
import secrets
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

#: Requests whose path starts here are API requests and need a token.
API_PREFIX = "/api"

TOKEN_HEADER = "X-Coco-Token"
TOKEN_QUERY_PARAM = "key"

#: Explicit rather than ``mimetypes.guess_type``: the system MIME database
#: varies between machines and a ``.js`` served as ``text/plain`` is refused by
#: WKWebView's module loader with an error that names neither the file nor the
#: reason.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"

JSON_CONTENT_TYPE = "application/json; charset=utf-8"

INDEX_FILE = "index.html"

#: ``serve_forever`` polls for the shutdown flag on this interval, so it also
#: bounds how long ``stop()`` blocks. The stdlib default of 0.5 s is a tenth of
#: a second of dead time at window close and half a second per server in the
#: tests, which construct one per case. Twenty idle wakeups a second on a
#: loopback socket costs nothing measurable.
SHUTDOWN_POLL_SECONDS = 0.05


def error_body(code: str, message: str) -> Dict[str, Any]:
    """The one error shape the whole API uses."""
    return {"error": {"code": code, "message": message}}


class _Handler(BaseHTTPRequestHandler):
    """One request. Reads its server's ``coco`` attribute for everything."""

    protocol_version = "HTTP/1.1"
    server_version = "CosineCompanion"
    sys_version = ""

    # -- plumbing ----------------------------------------------------------

    def log_message(self, format, *args):  # noqa: A002 - base class signature
        """Silence the default stderr access log.

        Frozen, the app has no console; unfrozen, a line per asset drowns the
        indexing output that the same terminal is showing.
        """

    @property
    def coco(self) -> "CocoServer":
        return self.server.coco

    # -- verbs -------------------------------------------------------------

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    # -- routing -----------------------------------------------------------

    def _dispatch(self, method: str) -> None:
        try:
            split = urlsplit(self.path)
            path = unquote(split.path)
            query = parse_qs(split.query, keep_blank_values=True)

            if path == API_PREFIX or path.startswith(API_PREFIX + "/"):
                self._serve_api(method, path, query)
            else:
                self._serve_static(method, path)
        except Exception:  # pragma: no cover - defensive
            traceback.print_exc(file=sys.stderr)
            self._send_json(500, error_body("internal", "The server failed to respond."))

    def _serve_api(self, method: str, path: str, query: Dict[str, List[str]]) -> None:
        if not self.coco.authorises(self._presented_token(query)):
            self._send_json(
                401, error_body("unauthorized", "A valid API token is required.")
            )
            return

        # Transport, not an argument. Leaving it in would surface it in error
        # messages built from the query.
        query.pop(TOKEN_QUERY_PARAM, None)

        if method != "GET":
            self._send_json(
                405,
                error_body("method_not_allowed", f"{method} is not supported."),
                extra_headers={"Allow": "GET"},
            )
            return

        try:
            status, body = self.coco.api.handle(method, path, query)
        except Exception:
            # The traceback goes to the developer, never to the client: an
            # exception message can carry a filesystem path or a track title.
            traceback.print_exc(file=sys.stderr)
            self._send_json(
                500, error_body("internal", "The request could not be completed.")
            )
            return

        self._send_json(status, body)

    def _presented_token(self, query: Dict[str, List[str]]) -> Optional[str]:
        """The token the caller offered, header first.

        Exactly one is consulted. Falling back to the query parameter when a
        header is present but wrong would let a caller present one valid and
        one invalid credential and be let in.
        """
        header = self.headers.get(TOKEN_HEADER)
        if header is not None:
            return header
        values = query.get(TOKEN_QUERY_PARAM) or []
        return values[0] if values else None

    def _serve_static(self, method: str, path: str) -> None:
        if method != "GET":
            self._send_json(
                405,
                error_body("method_not_allowed", f"{method} is not supported."),
                extra_headers={"Allow": "GET"},
            )
            return

        target = self._resolve_static(path)
        if target is None:
            self._send_json(404, error_body("not_found", f"No asset at {path!r}."))
            return

        payload = target.read_bytes()
        self._send(
            200,
            payload,
            CONTENT_TYPES.get(target.suffix.lower(), DEFAULT_CONTENT_TYPE),
        )

    def _resolve_static(self, path: str) -> Optional[Path]:
        """Map a URL path to a file inside the static directory, or nothing.

        The containment check is the reason this method exists. ``path`` has
        already been percent-decoded, so ``/%2e%2e/%2e%2e/etc/passwd`` and
        ``/../../etc/passwd`` arrive here identically, and joining either onto
        the static root produces a path outside it. Resolution has to happen
        **before** the check, not after, or a symlink inside the root pointing
        out of it passes - a purely textual check never sees the target.

        Pinned by tests/web/test_static_assets.py: the source-escape cases
        (``/../server.py``, ``/../../services/library_session.py``) were
        verified to really return 200 with file contents before this check
        existed, so they are a live guard rather than a hopeful one.
        """
        relative = path.lstrip("/")
        if relative == "" or relative.endswith("/"):
            relative += INDEX_FILE

        root = self.coco.static_dir
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            return None
        if not candidate.is_file():
            return None
        return candidate

    # -- responses ---------------------------------------------------------

    def _send_json(self, status: int, body: Dict[str, Any], extra_headers=None) -> None:
        try:
            # allow_nan=False turns a NaN that escaped the API's sanitiser into
            # a 500 here rather than into the bare literal `NaN` on the wire,
            # which is not valid JSON and makes JSON.parse throw in WKWebView.
            payload = json.dumps(body, allow_nan=False, ensure_ascii=False)
        except (ValueError, TypeError):
            traceback.print_exc(file=sys.stderr)
            status = 500
            payload = json.dumps(
                error_body("internal", "The response could not be serialised.")
            )

        self._send(status, payload.encode("utf-8"), JSON_CONTENT_TYPE, extra_headers)

    def _send(self, status: int, payload: bytes, content_type: str, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # The app is served from disk beside the interpreter that reads it;
        # a cached stale asset is pure cost with no benefit.
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


class _ThreadingServer(ThreadingHTTPServer):
    """``daemon_threads`` so a hung request cannot outlive the window."""

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """Stay quiet when the client simply went away.

        A webview that navigates or closes mid-response leaves the server
        writing into a socket nobody is reading, and socketserver's default is
        to dump a traceback per occurrence. That is normal client behaviour,
        not a fault. Anything else is still reported - swallowing every error
        here would hide real handler bugs.
        """
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class CocoServer:
    """A loopback HTTP server for one application process."""

    def __init__(self, api, static_dir, host: str = "127.0.0.1", port: int = 0):
        """Bind nothing yet; generate this process's token.

        Args:
            api: any object implementing
                ``handle(method, path, query) -> (status, body)``.
            static_dir: the directory holding ``index.html``.
            host: loopback. Not a parameter anyone should change - it exists so
                the binding can be asserted rather than assumed.
            port: 0 for an ephemeral port, which is the only value used.
        """
        self._api = api
        self._static_dir = Path(static_dir).resolve()
        self._host = host
        self._requested_port = port
        self._token = secrets.token_urlsafe(32)
        self._httpd: Optional[_ThreadingServer] = None
        self._thread: Optional[threading.Thread] = None
        self._bound: Optional[Tuple[str, int]] = None

    # -- read accessors ----------------------------------------------------

    @property
    def api(self):
        return self._api

    @property
    def static_dir(self) -> Path:
        return self._static_dir

    @property
    def token(self) -> str:
        return self._token

    @property
    def socket_address(self) -> Tuple[str, int]:
        """The address really bound, read back from the socket."""
        if self._bound is None:
            raise RuntimeError("the server has not been started")
        return self._bound

    @property
    def port(self) -> int:
        return self.socket_address[1]

    @property
    def url(self) -> str:
        """The page URL, carrying the token so the frontend can pick it up."""
        return f"http://{self._host}:{self.port}/?key={self._token}"

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._thread

    # -- lifecycle ---------------------------------------------------------

    def authorises(self, candidate: Optional[str]) -> bool:
        """Whether ``candidate`` is this process's token.

        ``hmac.compare_digest`` rather than a plain comparison: a string
        comparison short-circuits at the first differing byte, which hands a
        local attacker who can retry a prefix oracle. Pinned by
        tests/web/test_server_auth.py::test_the_token_check_is_constant_time.
        """
        if not candidate:
            return False
        return hmac.compare_digest(candidate, self._token)

    def start(self) -> None:
        """Bind, then serve in a daemon thread. Returns once the port is known."""
        if self._httpd is not None:
            raise RuntimeError("the server is already started")

        self._httpd = _ThreadingServer((self._host, self._requested_port), _Handler)
        self._httpd.coco = self
        self._bound = self._httpd.socket.getsockname()[:2]

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            args=(SHUTDOWN_POLL_SECONDS,),
            name="cosine-companion-http",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port. Safe to call more than once."""
        if self._httpd is None:
            return

        httpd, self._httpd = self._httpd, None
        httpd.shutdown()
        httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
