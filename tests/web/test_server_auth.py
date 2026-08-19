"""The loopback server: what it binds to, and who it will talk to.

The threat model is small but real: any other process running as this user can
open a connection to 127.0.0.1. A per-process token is what stops it reading
the library. That makes these assertions security assertions, not plumbing
ones, so each rule is pinned individually rather than through one happy path.
"""

import hmac
import http.client
import inspect
import json
import socket

import pytest

from webtest_support import StubApi, client_for

import web.server as server_module
from web.server import CocoServer


# -- binding ---------------------------------------------------------------


def test_the_server_binds_loopback_and_nothing_else(server):
    """0.0.0.0 would put the library on the LAN. The bound host is asserted,
    not the constructor default, so a later refactor cannot widen it quietly."""
    host, port = server.socket_address

    assert host == "127.0.0.1"
    assert port == server.port
    assert server.port != 0, "an ephemeral port must be resolved once bound"


def test_the_url_carries_the_token_so_the_page_can_bootstrap(server):
    assert server.url == f"http://127.0.0.1:{server.port}/?key={server.token}"


def test_the_port_is_unknown_until_the_server_is_started(stub_api, static_dir):
    """Reading .port early would silently return the placeholder 0 and send
    host.py to the wrong URL."""
    not_started = CocoServer(stub_api, static_dir)

    with pytest.raises(RuntimeError):
        not_started.port


def test_stopping_the_server_releases_the_port(stub_api, static_dir):
    running = CocoServer(stub_api, static_dir)
    running.start()
    port = running.port
    running.stop()

    with pytest.raises((ConnectionRefusedError, socket.timeout, OSError)):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


def test_stopping_twice_is_harmless(stub_api, static_dir):
    """host.py stops the server in a finally block after webview.start()
    returns; a double stop on an error path must not raise over the real
    failure."""
    running = CocoServer(stub_api, static_dir)
    running.start()
    running.stop()
    running.stop()


def test_the_serving_thread_is_a_daemon_and_does_not_outlive_stop(stub_api, static_dir):
    """webview.start() owns the main thread. A non-daemon serving thread would
    keep the process alive after the window closes."""
    running = CocoServer(stub_api, static_dir)
    running.start()

    assert running.thread.daemon is True
    assert running.thread.is_alive()

    running.stop()

    assert not running.thread.is_alive()


# -- tokens ----------------------------------------------------------------


def test_each_server_generates_its_own_token(stub_api, static_dir):
    tokens = {CocoServer(stub_api, static_dir).token for _ in range(5)}

    assert len(tokens) == 5


def test_the_token_is_long_enough_to_be_worth_having(server):
    """secrets.token_urlsafe(32) is 32 bytes of entropy, ~43 characters."""
    assert len(server.token) >= 32


def test_the_token_check_accepts_only_the_real_token(server):
    assert server.authorises(server.token) is True
    assert server.authorises(None) is False
    assert server.authorises("") is False
    assert server.authorises(server.token + "x") is False
    assert server.authorises(server.token[:-1]) is False
    assert server.authorises(server.token.upper()) is False


#: Wrong candidates that must each be decided by compare_digest and not by
#: something cheaper. The empty string is deliberately absent: `authorises`
#: refuses it before comparing anything, and a candidate's *emptiness* is not
#: secret - "did the caller send a token at all" leaks nothing about its value.
WRONG_TOKENS = {
    "longer": lambda token: token + "xxxxx",
    "shorter": lambda token: token[:5],
    "one_short": lambda token: token[:-1],
    "differs_at_the_first_byte": lambda token: "~" + token[1:],
    "differs_at_the_last_byte": lambda token: token[:-1] + "~",
    "case_flipped": lambda token: token.upper(),
}


@pytest.mark.parametrize("name", sorted(WRONG_TOKENS))
def test_every_wrong_token_is_decided_by_compare_digest(server, monkeypatch, name):
    """Constant time, asserted by what RUNS rather than by what the source says.

    The source check this replaces asserted that "hmac.compare_digest" appeared
    in ``authorises`` and that "==" did not. Both survive the mutation that
    matters:

        if len(candidate) != len(self._token):
            return False          # <- returns before compare_digest is reached
        return hmac.compare_digest(candidate, self._token)

    That reintroduces a length oracle, and a first-byte version of it
    reintroduces the prefix oracle outright, while the old assertions stayed
    green. Recording the call is what distinguishes "compare_digest is
    mentioned" from "compare_digest is what decided this".
    """
    candidate = WRONG_TOKENS[name](server.token)
    assert candidate != server.token, "this case does not test a WRONG token"

    calls = []
    real = hmac.compare_digest

    def recording(left, right):
        calls.append((left, right))
        return real(left, right)

    monkeypatch.setattr(server_module.hmac, "compare_digest", recording)

    assert server.authorises(candidate) is False
    assert calls, (
        f"a {name.replace('_', ' ')} candidate was rejected without reaching "
        "compare_digest, which is a timing oracle"
    )


def test_the_right_token_is_decided_by_compare_digest_too(server, monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(
        server_module.hmac,
        "compare_digest",
        lambda left, right: (calls.append(1), real(left, right))[1],
    )

    assert server.authorises(server.token) is True
    assert calls


def test_an_absent_token_is_refused_without_comparing_anything(server, monkeypatch):
    """The one short-circuit that is correct, pinned so it stays deliberate."""
    calls = []
    monkeypatch.setattr(
        server_module.hmac, "compare_digest", lambda *a: calls.append(1) or False
    )

    assert server.authorises(None) is False
    assert server.authorises("") is False
    assert calls == []


def test_the_token_check_still_names_compare_digest(server):
    """Kept alongside the behavioural tests, and worth exactly what it says:
    that the intent is written down where the next reader will see it."""
    source = inspect.getsource(CocoServer.authorises)

    assert "hmac.compare_digest" in source


# -- the API is what is protected ------------------------------------------


API_PATHS = [
    "/api/health",
    "/api/library",
    "/api/tracks",
    "/api/tracks/search?q=x",
    "/api/tracks/f01",
    "/api/tracks/f01/recommendations",
]


@pytest.mark.parametrize("path", API_PATHS)
def test_an_api_request_with_no_token_is_rejected(client, stub_api, path):
    """Including /api/health. There is no unauthenticated endpoint."""
    response = client.get(path)

    assert response.status == 401
    assert response.error_code == "unauthorized"
    assert stub_api.calls == [], "the API ran before the token was checked"


@pytest.mark.parametrize("path", API_PATHS)
def test_an_api_request_with_the_wrong_token_is_rejected(client, stub_api, server, path):
    response = client.get(path, token=server.token + "-nope")

    assert response.status == 401
    assert response.error_code == "unauthorized"
    assert stub_api.calls == []


def test_the_token_is_accepted_from_the_header(client, server, stub_api):
    response = client.get("/api/health", token=server.token)

    assert response.status == 200
    assert response.json == {"stub": True}
    assert stub_api.calls == [("GET", "/api/health", {})]


def test_the_token_is_accepted_from_the_key_query_parameter(client, server, stub_api):
    """The page is opened at /?key=... so the very first request carries it in
    the URL; the frontend then moves it to the header."""
    response = client.get(f"/api/health?key={server.token}")

    assert response.status == 200
    assert stub_api.calls == [("GET", "/api/health", {})]


def test_the_key_parameter_is_not_forwarded_to_the_api(client, server, stub_api):
    """It is transport, not an argument. Leaking it into query handling would
    make it turn up in error messages and logs."""
    client.get(f"/api/tracks?limit=3&key={server.token}")

    assert stub_api.calls == [("GET", "/api/tracks", {"limit": ["3"]})]


def test_a_bad_header_token_is_not_rescued_by_a_good_query_token(client, server, stub_api):
    """Whichever the caller supplies must be right; presenting one valid and
    one invalid credential is not authentication."""
    response = client.request(
        "GET",
        f"/api/health?key={server.token}",
        headers={"X-Coco-Token": "wrong"},
    )

    assert response.status == 401
    assert stub_api.calls == []


def test_the_query_string_reaches_the_api_as_lists_of_values(client, server, stub_api):
    client.get(f"/api/tracks/search?q=bl%C3%A5&limit=5&limit=7&key={server.token}")

    assert stub_api.calls == [
        ("GET", "/api/tracks/search", {"q": ["blå"], "limit": ["5", "7"]})
    ]


def test_a_blank_query_value_is_preserved_rather_than_dropped(client, server, stub_api):
    """``?q=`` must reach the API as an empty string, not as an absent key, or
    the API cannot tell "searched for nothing" from "did not search"."""
    client.get(f"/api/tracks/search?q=&key={server.token}")

    assert stub_api.calls == [("GET", "/api/tracks/search", {"q": [""]})]


# -- transport-level responses ---------------------------------------------


def test_api_responses_are_utf8_json(client, server):
    response = client.get("/api/health", token=server.token)

    assert response.content_type == "application/json; charset=utf-8"


def test_an_exception_inside_the_api_becomes_a_500_not_a_dropped_connection(static_dir):
    """A traceback out of handle() must not take the connection down with it -
    the frontend would see a network error and could not report anything
    useful."""
    running = CocoServer(StubApi(raises=RuntimeError("boom")), static_dir)
    running.start()
    try:
        response = client_for(running).get("/api/health", token=running.token)
    finally:
        running.stop()

    assert response.status == 500
    assert response.error_code == "internal"


def test_a_500_body_does_not_leak_the_exception_text(static_dir):
    """The message is for a user, not a stack trace addressed to nobody."""
    running = CocoServer(StubApi(raises=RuntimeError("secret/path/detail")), static_dir)
    running.start()
    try:
        response = client_for(running).get("/api/health", token=running.token)
    finally:
        running.stop()

    assert "secret/path/detail" not in response.text


def test_an_unknown_method_on_an_api_path_is_refused(client, server, stub_api):
    response = client.request(
        "DELETE", "/api/library", headers={"X-Coco-Token": server.token}
    )

    assert response.status in (400, 404, 405)
    assert response.status != 500


# -- the auth choke point --------------------------------------------------
#
# The bug these pin: the handler used to define do_GET/do_POST/do_PUT/do_PATCH/
# do_DELETE/do_OPTIONS, each calling _dispatch, which is where the token is
# checked. Any verb WITHOUT a do_X method never reached _dispatch at all -
# BaseHTTPRequestHandler.handle_one_request looks the method up with hasattr
# and answers 501 with an HTML error page before a line of our code runs. No
# data was exposed by that, but it broke the contract this module's docstring
# states ("required on *every* /api/ request") and it left auth sitting in six
# per-verb methods, so the next person to add do_HEAD for static files would
# have opened a real bypass with no test failing.
#
# Verified against a running server before the fix:
#   GET  /api/health no token -> 401 application/json
#   HEAD /api/health no token -> 501 text/html      <- never reached auth
#   TRACE / FOO      no token -> 501 text/html

#: Defined verbs, undefined verbs, and one that is not a verb at all.
EVERY_METHOD = [
    "GET",
    "HEAD",
    "OPTIONS",
    "TRACE",
    "PATCH",
    "DELETE",
    "POST",
    "PUT",
    "FROB",
]

#: HEAD responses carry the headers of the GET they stand in for and no body
#: (RFC 9110 §9.3.2), so the status and the Content-Type are what can be
#: asserted for it. Every other verb is asserted on its body as well.
BODYLESS = {"HEAD"}

#: The methods this server actually answers. HEAD is here because it is
#: *implemented* - routed as the GET it stands in for (server.py SAFE_ALIASES)
#: - and not because it is tolerated; the HEAD/GET parity tests below are what
#: hold that. Everything outside this set is a 405 naming these two in Allow.
SUPPORTED_METHODS = ("GET", "HEAD")


def test_no_verb_gets_its_own_handler_method():
    """The architectural pin, not a behavioural one.

    A per-verb ``do_X`` is a second entry point, and the token check only
    protects the entry points that route through ``_dispatch``. Deleting them
    all is what makes ``_dispatch`` a choke point rather than the busiest of
    several doors, so a reintroduced ``do_HEAD`` fails here even if it happens
    to call ``_dispatch`` itself.
    """
    from web.server import _Handler

    own = sorted(name for name in vars(_Handler) if name.startswith("do_"))

    assert own == [], f"per-verb handlers reintroduce a bypass route: {own}"


@pytest.mark.parametrize("method", EVERY_METHOD)
def test_no_method_whatsoever_reaches_the_api_without_a_token(client, stub_api, method):
    """Every method, defined or not, is answered by the token check in JSON."""
    response = client.request(method, "/api/library")

    assert response.status == 401
    assert response.content_type == "application/json; charset=utf-8"
    assert stub_api.calls == [], "the API ran before the token was checked"
    if method not in BODYLESS:
        assert response.error_code == "unauthorized"


@pytest.mark.parametrize(
    "method", [m for m in EVERY_METHOD if m not in SUPPORTED_METHODS]
)
def test_an_authenticated_unsupported_method_is_a_json_405(
    client, server, stub_api, method
):
    """Past the token, an unsupported verb is a 405 with the API's error shape -
    never the stdlib's HTML 501 page.

    ``Allow`` has to name every method that *is* supported, so it is asserted
    here rather than left to drift: adding HEAD to the routing without adding
    it to ``Allow`` would be a 405 that lies about the alternative.
    """
    response = client.request(
        method, "/api/library", headers={"X-Coco-Token": server.token}
    )

    assert response.status == 405
    assert response.content_type == "application/json; charset=utf-8"
    assert response.headers["Allow"] == "GET, HEAD"
    assert stub_api.calls == [], "an unsupported method must not reach the API"
    if method not in BODYLESS:
        assert response.error_code == "method_not_allowed"


@pytest.mark.parametrize("method", EVERY_METHOD)
def test_no_method_whatsoever_is_answered_with_html(client, server, method):
    """The frontend parses every non-2xx body as JSON. An HTML error page from
    the stdlib is a body it cannot read, on a path it did not expect."""
    response = client.request(
        method, "/api/nothing-here", headers={"X-Coco-Token": server.token}
    )

    assert "text/html" not in response.content_type
    assert response.content_type == "application/json; charset=utf-8"


# -- HEAD -------------------------------------------------------------------
#
# HEAD is answered by running the GET and dropping the content, which is what
# RFC 9110 §9.3.2 and §8.6 require: the same status, the same headers, and a
# Content-Length that still describes the content that was removed.
#
# Before this round the code did only the second half. `_send` elided the body
# correctly, but routing sent HEAD down the unsupported-method branch, so
# measured against a running server:
#
#   HEAD /api/health -> 405, Content-Length 78   GET -> 200, Content-Length 12
#   HEAD /           -> 405, Content-Length 78   GET -> 200, Content-Length 4907
#
# A HEAD whose status and length disagree with its GET is the one thing HEAD is
# for - asking about a resource without fetching it - so the parity below is
# the assertion, not the absence of a body.

#: An API path and a static path, each in a success and a failure state. The
#: failure states matter as much: a 401 or a 404 is still a response a HEAD
#: must be able to describe.
HEAD_PARITY_CASES = [
    ("/api/health", True),
    ("/api/health", False),
    ("/", False),
    ("/no-such-asset.css", False),
]


@pytest.mark.parametrize(
    "path,with_token",
    HEAD_PARITY_CASES,
    ids=lambda value: value if isinstance(value, str) else f"token={value}",
)
def test_head_returns_what_get_returns_minus_the_content(
    client, server, path, with_token
):
    """Status and Content-Length identical to the GET; body empty."""
    headers = {"X-Coco-Token": server.token} if with_token else {}

    fetched = client.request("GET", path, headers=dict(headers))
    described = client.request("HEAD", path, headers=dict(headers))

    assert described.status == fetched.status
    assert described.content_type == fetched.content_type
    assert described.headers["Content-Length"] == fetched.headers["Content-Length"]
    assert described.body == b""
    # Without this the parity above would also hold for two empty responses.
    assert int(fetched.headers["Content-Length"]) == len(fetched.body) > 0


def test_a_head_response_leaves_the_connection_synchronised(server):
    """The load-bearing form of "a HEAD response carries no body".

    Asserting ``response.body == b""`` on a fresh connection CANNOT FAIL, and
    the earlier version of this test did exactly that. ``http.client`` decides
    there is no body from the METHOD (``HTTPResponse.begin`` sets
    ``self.length = 0`` when ``_method == "HEAD"``), never from the socket, so
    it reports ``b""`` whether or not the server wrote one - and a one-shot
    client then closes the connection and throws the stray bytes away. Making
    ``_send`` write the payload for HEAD too was applied to ``server.py`` and
    the old assertion stayed green.

    What a stray body actually does is desynchronise the connection: the
    leftover bytes are read as the start of the NEXT response. So this pipelines
    HEAD and GET down ONE socket and asserts on the bytes between them.

    Raw socket rather than ``http.client``, and not only for the usual reason.
    ``http.client`` builds a fresh ``BufferedReader`` per response, so whether
    it notices stray bytes depends on whether they had already been read into
    the previous reader's 8 KB buffer - which depends on TCP segmentation. A
    test that catches the mutation only when the segments land a certain way is
    a flaky test, not a load-bearing one. Reading the socket directly makes the
    assertion deterministic: whatever follows the HEAD headers must be the next
    status line.

    ``/`` is the HEAD target on purpose - index.html is several KB, so under
    the mutation the desynchronisation is unmissable rather than marginal.
    """
    authority = f"127.0.0.1:{server.port}".encode()
    exchange = raw_exchange(
        server.port,
        b"HEAD / HTTP/1.1\r\nHost: " + authority + b"\r\n\r\n"
        b"GET /api/health HTTP/1.1\r\nHost: " + authority + b"\r\n"
        b"Connection: close\r\n\r\n",
    )

    described, separator, following = exchange.partition(b"\r\n\r\n")

    assert separator, f"the HEAD response has no header block: {exchange[:120]!r}"
    assert described.startswith(b"HTTP/1.1 200 "), described[:120]
    assert b"Content-Length: 0\r\n" not in described, (
        "the Content-Length must describe the content a GET would have sent"
    )
    assert following.startswith(b"HTTP/1.1 401 "), (
        "the HEAD response left content on the connection, so the next response "
        f"starts mid-stream: {following[:80]!r}"
    )
    assert json.loads(following.partition(b"\r\n\r\n")[2])["error"]["code"] == (
        "unauthorized"
    )


# -- request lines the stdlib rejects before any code of ours runs ----------
#
# Over RAW SOCKETS, and that is the point. ``http.client`` will not emit a
# malformed request line in the first place, and it is forgiving enough to hand
# back a body that never had a status line in front of it.
#
# What these pin is that a response IS one. ``BaseHTTPRequestHandler``
# suppresses the status line, every header AND the blank line ending them while
# ``request_version`` holds the ``HTTP/0.9`` sentinel, and ``parse_request``
# installs that sentinel before it reads anything - so every request line it
# rejects was answered with a naked body. Measured on this branch before the
# fix, and on main@c5bf32e which has no ``send_error`` override at all:
#
#   request line       main@c5bf32e            this branch, pre-fix
#   HELLO              unframed HTML page      unframed JSON body
#   GET / HTTP/9.9     unframed HTML page      unframed JSON body
#   GET / HTTP/2.0     unframed HTML page      unframed JSON body
#
# So the defect is inherited stdlib behaviour rather than something the
# override introduced; what the override added was a claim that it was fixed.
# ``_ensure_framable`` is what makes the claim true.
#
# Note what is NOT asserted: a token. These failures happen before a single
# header has been parsed, so there is no API request here to protect - only a
# request line the server could not read, which it must be able to say so
# about. Answering them without a token is correct.

#: label -> (bytes on the wire, the status that must come back)
MALFORMED_REQUEST_LINES = {
    "one_word": (b"HELLO\r\n\r\n", 400),
    "invalid_version": (b"GET / HTTP/9.9\r\nHost: 127.0.0.1\r\n\r\n", 505),
    "http_2": (b"GET / HTTP/2.0\r\nHost: 127.0.0.1\r\n\r\n", 505),
}


def raw_exchange(port, request_bytes, limit=1 << 20):
    """Send bytes and read the reply to EOF, using nothing but a socket."""
    connection = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        connection.sendall(request_bytes)
        connection.shutdown(socket.SHUT_WR)
        received = b""
        while len(received) < limit:
            chunk = connection.recv(65536)
            if not chunk:
                break
            received += chunk
        return received
    finally:
        connection.close()


@pytest.mark.parametrize("case", sorted(MALFORMED_REQUEST_LINES))
def test_a_rejected_request_line_still_gets_a_framed_json_response(server, case):
    """A JSON body is not a response until something frames it.

    Without the status line a real client never sees the status or the body:
    ``http.client`` raises ``BadStatusLine`` on the first line it reads.
    """
    request_bytes, expected_status = MALFORMED_REQUEST_LINES[case]

    received = raw_exchange(server.port, request_bytes)

    assert received.startswith(b"HTTP/1.1 "), (
        "no status line, so a client reads this as BadStatusLine rather than as "
        f"our {expected_status}: {received[:160]!r}"
    )
    head, separator, body = received.partition(b"\r\n\r\n")
    assert separator, f"no blank line ending the headers: {received[:160]!r}"
    assert head.split(b"\r\n")[0] == (
        f"HTTP/1.1 {expected_status} ".encode()
        + http.client.responses[expected_status].encode()
    )
    assert b"Content-Type: application/json; charset=utf-8\r\n" in head, head
    assert json.loads(body)["error"]["code"], body


def test_an_over_long_request_line_is_answered_in_json(server):
    """The one stdlib transport error that was already framed, kept separate
    because the reason it was framed is a one-line accident.

    ``handle_one_request`` blanks ``request_version`` before answering 414,
    rather than leaving the ``HTTP/0.9`` sentinel that ``parse_request`` leaves,
    so the base class did not suppress this one. That is the whole difference
    between this case and the three above, and it is not a difference to build
    on - which is why ``_ensure_framable`` sits on the shared path.

    ``http.client`` is enough here precisely because the framing works:
    ``getresponse()`` would raise ``BadStatusLine`` if it did not.
    """
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        connection.putrequest("GET", "/" + "a" * 70000, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"127.0.0.1:{server.port}")
        connection.endheaders()
        raw = connection.getresponse()
        body = raw.read()
        content_type = raw.getheader("Content-Type")
        status = raw.status
    finally:
        connection.close()

    assert status == 414
    assert content_type == "application/json; charset=utf-8"
    assert json.loads(body)["error"]["code"]


# -- who the server answers to ---------------------------------------------
#
# Defence in depth, and deliberately not more than that. A page on another
# origin can point a name it controls at 127.0.0.1 (DNS rebinding) and make the
# browser send requests here; the TOKEN is what stops those reading anything,
# because the attacker cannot read it out of a cross-origin response. Checking
# Host closes the door a step earlier and - the reason it is worth having at
# all - makes the set of names this server answers to a decision somebody made
# rather than an accident. Before this, `Host: evil.example` returned 200.


def test_a_request_addressed_to_another_name_is_refused(client, server, stub_api):
    response = client.request(
        "GET",
        "/api/health",
        headers={"Host": "evil.example", "X-Coco-Token": server.token},
    )

    assert response.status == 403
    assert response.error_code == "forbidden"
    assert stub_api.calls == [], "the API ran for a request addressed elsewhere"


def test_the_host_check_covers_static_assets_too(client, server):
    """The shell is not secret, but a rebound origin that can load the page can
    read whatever the page reads. One rule for the whole server."""
    response = client.request("GET", "/", headers={"Host": "evil.example"})

    assert response.status == 403
    assert response.content_type == "application/json; charset=utf-8"


@pytest.mark.parametrize("suffix", ["", ":{port}"])
@pytest.mark.parametrize("name", ["127.0.0.1", "localhost", "LOCALHOST"])
def test_the_names_this_server_answers_to(client, server, name, suffix):
    """The bound address and ``localhost``, with or without the port."""
    response = client.request(
        "GET",
        "/api/health",
        headers={
            "Host": name + suffix.format(port=server.port),
            "X-Coco-Token": server.token,
        },
    )

    assert response.status == 200


def test_the_right_name_on_the_wrong_port_is_refused(client, server):
    response = client.request(
        "GET",
        "/api/health",
        headers={"Host": "127.0.0.1:1", "X-Coco-Token": server.token},
    )

    assert response.status == 403


def test_a_missing_host_header_is_refused(client, server):
    """HTTP/1.1 requires one. Treating "absent" as "fine" would make the check
    trivially skippable by anything that can open a socket."""
    response = client.request(
        "GET",
        "/api/health",
        headers={"X-Coco-Token": server.token},
        host_header=False,
    )

    assert response.status == 403


def test_the_allowed_names_follow_the_bound_address(stub_api, static_dir):
    """The reason this is a derived set and not a constant: binding elsewhere
    to reach the UI from a phone must widen this, deliberately, in one place.
    The token still gates every /api/ read at that point."""
    elsewhere = CocoServer(stub_api, static_dir, host="0.0.0.0")

    assert "0.0.0.0" in elsewhere.allowed_host_names
    assert "localhost" in elsewhere.allowed_host_names
