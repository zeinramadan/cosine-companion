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

#: Methods this server answers, in the order the ``Allow`` header lists them.
ALLOWED_METHODS = "GET, HEAD"

#: Methods answered by running another method's handler. HEAD is *defined* as
#: GET without the content (RFC 9110 §9.3.2), so the GET path is what has to
#: produce its status, its headers and its Content-Length; ``_Handler._send``
#: is where the content alone is dropped. Written as a mapping rather than an
#: ``if`` so that "which methods stand in for which" is one readable fact.
SAFE_ALIASES = {"HEAD": "GET"}

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

    # -- the one entry point -----------------------------------------------

    def __getattr__(self, name: str):
        """Route *every* HTTP method into ``_dispatch``.

        There is deliberately no ``do_GET`` / ``do_POST`` / ... on this class,
        and that absence is the security property.
        ``BaseHTTPRequestHandler.handle_one_request`` resolves a request by
        looking up ``'do_' + self.command`` with ``hasattr`` and, when that
        lookup fails, answering 501 with an HTML page **before any code of
        ours runs**. With per-verb methods the token check is therefore one
        branch among six, and every verb nobody thought to define - HEAD,
        TRACE, or a string that is not a verb at all - skips it. Nothing was
        exposed by that, because 501 is an error page, but the contract in this
        module's docstring says every ``/api/`` request needs a token and
        returns JSON, and that was false; worse, the next ``do_HEAD`` added for
        static files would have been a real bypass with no test failing.

        Making this lookup succeed for every name gives ``_dispatch`` sole
        custody of the auth-and-routing decision. Chosen over overriding
        ``handle_one_request``, which would mean carrying a copy of the ~30
        stdlib lines that read the request line, enforce its length limit, call
        ``parse_request`` and answer ``Expect: 100-continue`` - a fork that rots
        silently across Python versions. This intercepts exactly the one
        attribute lookup the stdlib performs and leaves the rest of it alone.

        Pinned by tests/web/test_server_auth.py::
        test_no_verb_gets_its_own_handler_method and the parameterised
        method tests beside it.
        """
        # Only method names. Everything else must still raise, or a typo
        # anywhere in this class becomes a silent no-op returning a callable.
        if name.startswith("do_") and len(name) > len("do_"):
            method = name[len("do_") :]
            return lambda: self._dispatch(method)
        raise AttributeError(name)

    # -- routing -----------------------------------------------------------

    def _dispatch(self, method: str) -> None:
        try:
            # Before anything else, including the token: a request addressed to
            # a name this server does not answer to was not meant for it. See
            # CocoServer.allowed_host_names for why this is worth having when
            # the token is already the real control.
            if not self.coco.accepts_host(self.headers.get("Host")):
                self._send_json(
                    403,
                    error_body(
                        "forbidden",
                        "This server does not answer to that host name.",
                    ),
                )
                return

            split = urlsplit(self.path)
            path = unquote(split.path)
            query = parse_qs(split.query, keep_blank_values=True)

            # HEAD is routed as GET. RFC 9110 §9.3.2 defines a HEAD response as
            # the one GET would have produced with the content removed, and
            # §8.6 requires the Content-Length to keep describing that removed
            # content - so answering HEAD with its own 405 would satisfy
            # neither. Aliasing here, after the Host check and before the two
            # servers, means HEAD reaches _serve_api's token check by exactly
            # the same route GET does; nothing about auth is special-cased.
            routed = SAFE_ALIASES.get(method, method)

            if path == API_PREFIX or path.startswith(API_PREFIX + "/"):
                self._serve_api(routed, path, query)
            else:
                self._serve_static(routed, path)
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
                extra_headers={"Allow": ALLOWED_METHODS},
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
                extra_headers={"Allow": ALLOWED_METHODS},
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

    def send_error(self, code, message=None, explain=None) -> None:
        """Answer the stdlib's own transport errors in JSON as well.

        ``parse_request`` still rejects a malformed request line, an over-long
        request URI and an unsupported HTTP version before any routing happens,
        and the base implementation answers those with an HTML page. That is
        the last place an HTML body could leave this server, and the frontend
        reads every non-2xx body as JSON, so these are translated rather than
        left as the one exception.

        The JSON is only half of it: most of these are raised while
        ``request_version`` still holds the sentinel that suppresses response
        framing entirely, so the translated body needed a status line in front
        of it before it was a response at all. ``_ensure_framable`` is what
        supplies that, on the shared path rather than here.
        """
        try:
            shortmsg = self.responses[code][0]
        except (KeyError, TypeError):  # pragma: no cover - unlisted status
            shortmsg = "Error"

        slug = "internal" if int(code) >= 500 else "bad_request"
        self._send_json(
            int(code),
            error_body(slug, str(message or shortmsg)),
            extra_headers={"Connection": "close"},
        )
        # These are all unrecoverable framing errors; the stdlib closes too.
        self.close_connection = True

    def _ensure_framable(self) -> None:
        """Guarantee this response gets a status line, headers and a blank line.

        ``BaseHTTPRequestHandler`` suppresses all three whenever
        ``request_version`` is the ``HTTP/0.9`` sentinel - ``send_response_only``,
        ``send_header`` and ``end_headers`` each open with the same
        ``if self.request_version != 'HTTP/0.9'``. That is how the base class
        speaks 0.9, which has no response framing at all.

        The trap is that ``parse_request`` installs that sentinel *before* it
        reads anything and only replaces it once it has a version it accepts.
        Every request line it rejects on the way there - a one-word line,
        ``HTTP/9.9``, ``HTTP/2.0`` - is therefore answered while the sentinel is
        still in place, and what went on the wire was a naked JSON body with no
        ``HTTP/1.1`` line in front of it. A real client does not read that as
        our 400: ``http.client`` raises ``BadStatusLine`` and never sees the
        status or the body. (The 414 escaped this only because
        ``handle_one_request`` blanks ``request_version`` rather than leaving
        the sentinel, which is a difference of one line in the stdlib and not
        something to rely on.)

        This is inherited behaviour, not something the ``send_error`` override
        introduced - the same request lines got an unframed HTML page before
        it. What the override did was make the module docstring's promise
        louder than what was delivered.

        Normalising here rather than inside ``send_error`` puts it on the one
        path every response takes, so a future error route cannot miss it, and
        it is safe unconditionally because there is no HTTP/0.9 client to
        confuse: a 0.9 request carries no headers, so it cannot carry ``Host``,
        and ``_dispatch`` refuses it 403 either way. Framing that refusal makes
        it legible instead of leaving a bare body on the socket.

        Note what this deliberately does **not** do: it does not authorise
        anything. These failures happen before a header has been parsed, so
        there is no API request here to protect - only a request line this
        server could not read, which it must be able to say so about.

        Pinned by the raw-socket cases in tests/web/test_server_auth.py, which
        use sockets rather than ``http.client`` precisely because
        ``http.client`` is forgiving enough to hand an unframed body back as a
        response.
        """
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.1"

    def _send(self, status: int, payload: bytes, content_type: str, extra_headers=None):
        self._ensure_framable()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # The app is served from disk beside the interpreter that reads it;
        # a cached stale asset is pure cost with no benefit.
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        # The only difference between a HEAD response and its GET, and the
        # last moment at which it can be made. _dispatch already routed this
        # request as GET, so the status, the Content-Type and the
        # Content-Length above are the GET's - which is what RFC 9110 §9.3.2
        # and §8.6 require - and all that is left is to not write the content.
        #
        # Writing it anyway does NOT show up as a stray body: the client stops
        # reading on the method's semantics, so it reports no body either way.
        # It shows up one response later, on a keep-alive connection, when the
        # bytes still in the socket are read as the start of the NEXT response.
        # That is why the test for this reuses its connection.
        if self.command != "HEAD":
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
        return f"{self.display_url}/?key={self._token}"

    @property
    def display_url(self) -> str:
        """The same URL with the token removed, for anything a human reads.

        ``url`` is what the webview is pointed at and it has to carry the
        token. Printing that to stdout writes a live credential into terminal
        scrollback, shell history files and any log the launcher is piped
        into, where it outlives the process that could still use it.
        """
        return f"http://{self._host}:{self.port}"

    #: Extra names, beyond the bound address, that mean "this machine".
    LOOPBACK_ALIASES = ("localhost",)

    @property
    def allowed_host_names(self) -> frozenset:
        """The host names this server will answer to, lower-cased.

        Defence in depth, and deliberately labelled as such. A page on another
        origin can point a name it controls at 127.0.0.1 - DNS rebinding - and
        make a browser send requests here. The *token* is what stops those
        reading anything, because the attacker's script cannot read it out of a
        cross-origin response; this only closes the door one step earlier.

        The reason it earns its place anyway is that it makes the answer
        explicit. It is derived from the bound address, so pointing ``host`` at
        a LAN interface to reach the UI from a phone widens this in one place
        and on purpose, rather than leaving "which names work" as something
        nobody decided.
        """
        return frozenset({self._host.lower(), *self.LOOPBACK_ALIASES})

    def accepts_host(self, header: Optional[str]) -> bool:
        """Whether a ``Host`` header names this server.

        An absent header is refused rather than waved through: HTTP/1.1
        requires one, and treating "absent" as "fine" would make the check
        skippable by anything that can open a socket - which is precisely the
        caller it exists for.
        """
        if not header:
            return False

        candidate = header.strip()
        if candidate.startswith("["):  # an IPv6 literal: [::1] or [::1]:8000
            name, _, rest = candidate.partition("]")
            name = name[1:]
            port = rest[1:] if rest.startswith(":") else ""
        else:
            name, separator, port = candidate.partition(":")
            if not separator:
                port = ""

        # A name with no port is accepted; a name with the WRONG port is not,
        # because that request was addressed to a different server.
        if port and port != str(self.port):
            return False
        return name.lower() in self.allowed_host_names

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
