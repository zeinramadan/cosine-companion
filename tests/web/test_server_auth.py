"""The loopback server: what it binds to, and who it will talk to.

The threat model is small but real: any other process running as this user can
open a connection to 127.0.0.1. A per-process token is what stops it reading
the library. That makes these assertions security assertions, not plumbing
ones, so each rule is pinned individually rather than through one happy path.
"""

import hmac
import inspect
import socket

import pytest

from webtest_support import StubApi, client_for

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


def test_the_token_check_is_constant_time():
    """A source check, because timing safety is not observable from outside.

    ``==`` on a string short-circuits at the first differing byte, which leaks
    a prefix oracle to a local attacker who can retry. ``hmac.compare_digest``
    is the fix and it has to actually be the thing that runs.
    """
    source = inspect.getsource(CocoServer.authorises)

    assert "hmac.compare_digest" in source
    assert "==" not in source, f"non-constant-time comparison in authorises:\n{source}"
    assert hmac.compare_digest is not None


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
