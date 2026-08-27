"""Serving the front end: what is reachable, and what must not be.

Hand-rolled static serving is where path traversal lives. ``http.server``'s own
``SimpleHTTPRequestHandler`` sanitises paths for you; this server does not use
it, because it has to route ``/api/`` first and because ``SimpleHTTPRequest
Handler`` serves the process's working directory rather than a fixed root. That
trade buys routing control and owes a containment check, which is the bulk of
this file.

The static shell is served **without** a token on purpose: the page has to load
before it can read ``?key=`` out of its own URL. Everything it can reach that
way is HTML, CSS and JS that ships in the repository. The library is behind the
API, and the API is behind the token.
"""

import socket
from pathlib import Path

import pytest

from webtest_support import StubApi, client_for

from web.server import CocoServer

STATIC = Path(__file__).resolve().parents[2] / "src/web/static"


# -- the assets that ship --------------------------------------------------


def test_the_root_path_serves_the_index_page(client):
    response = client.get("/")

    assert response.status == 200
    assert response.content_type == "text/html; charset=utf-8"
    assert "<" in response.text


def test_the_index_page_is_also_reachable_by_name(client):
    assert client.get("/index.html").status == 200


def test_the_stylesheet_is_served_as_css(client):
    response = client.get("/css/app.css")

    assert response.status == 200
    assert response.content_type == "text/css; charset=utf-8"


def test_the_design_tokens_are_served_as_css(client):
    response = client.get("/css/tokens.css")

    assert response.status == 200
    assert response.content_type == "text/css; charset=utf-8"


def test_the_entry_module_is_served_as_javascript(client):
    """WKWebView refuses a module whose MIME type is not a JavaScript one, and
    the console error names neither the file nor the reason."""
    response = client.get("/js/main.js")

    assert response.status == 200
    assert response.content_type == "text/javascript; charset=utf-8"


def test_static_assets_need_no_token(client):
    """The page cannot present a token before it has loaded and read one."""
    for path in ("/", "/index.html", "/css/app.css", "/js/main.js"):
        assert client.get(path).status == 200, path


def test_a_token_on_a_static_request_is_simply_ignored(client, server):
    assert client.get("/css/app.css", token=server.token).status == 200
    assert client.get("/css/app.css", token="rubbish").status == 200


def test_a_missing_asset_is_a_404(client):
    response = client.get("/js/does-not-exist.js")

    assert response.status == 404
    assert response.error_code == "not_found"


def test_a_directory_is_not_listed(client):
    """An index of the asset tree is not a vulnerability, but it is not a
    feature either, and http.server's directory listing is one line away."""
    response = client.get("/css/")

    assert response.status == 404


def test_the_body_length_matches_the_declared_content_length(client):
    response = client.get("/index.html")

    assert int(response.headers["Content-Length"]) == len(response.body)


def test_static_responses_are_not_cached(client):
    """The assets sit on disk beside the interpreter reading them; a stale
    cached module is pure cost, and it makes `--debug` iteration confusing."""
    assert "no-store" in client.get("/index.html").headers["Cache-Control"]


def test_every_tkinter_reference_in_static_assets_is_source_commentary():
    """Enumerate every occurrence; historical design notes may remain."""
    occurrences = []
    user_visible = []
    for path in sorted(STATIC.rglob("*")):
        if path.suffix not in {".css", ".html", ".js"}:
            continue
        block_comment_end = None
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            comment_columns = set()
            column = 0
            while column < len(line):
                if block_comment_end is not None:
                    comment_columns.add(column)
                    if line.startswith(block_comment_end, column):
                        comment_columns.update(
                            range(column, column + len(block_comment_end))
                        )
                        column += len(block_comment_end)
                        block_comment_end = None
                    else:
                        column += 1
                elif line.startswith("/*", column):
                    block_comment_end = "*/"
                elif line.startswith("<!--", column):
                    block_comment_end = "-->"
                elif line.startswith("//", column):
                    comment_columns.update(range(column, len(line)))
                    break
                else:
                    column += 1

            column = line.find("Tkinter")
            while column >= 0:
                item = (str(path.relative_to(STATIC)), line_number, line.strip())
                occurrences.append(item)
                if column not in comment_columns:
                    user_visible.append(item)
                column = line.find("Tkinter", column + 1)

    assert occurrences, "the historical references this test classifies disappeared"
    assert user_visible == []


# -- path traversal --------------------------------------------------------

TRAVERSALS = [
    "/../../etc/passwd",
    "/%2e%2e/%2e%2e/etc/passwd",
    "/..%2f..%2fetc/passwd",
    "/css/../../../../etc/passwd",
    "/css/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
    "/./../../etc/passwd",
    "/....//....//etc/passwd",
]


@pytest.mark.parametrize("path", TRAVERSALS)
def test_a_traversal_never_returns_a_file_outside_the_static_directory(client, path):
    response = client.get(path)

    assert response.status in (403, 404), f"{path} returned {response.status}"
    assert b"root:" not in response.body


SOURCE_ESCAPES = [
    # Reachable relative to src/web/static/ if containment is not enforced:
    # the module that resolves the static directory, and a service module.
    "/../assets.py",
    "/../server.py",
    "/../../services/library_session.py",
    "/../../config/paths.py",
]


@pytest.mark.parametrize("path", SOURCE_ESCAPES)
def test_a_traversal_cannot_read_the_application_source(client, path):
    """More realistic than /etc/passwd: these files certainly exist, at a known
    depth above the static root, so a missing containment check leaks them
    rather than merely 404ing on an absent target."""
    response = client.get(path)

    assert response.status in (403, 404), f"{path} returned {response.status}"
    assert b"import" not in response.body


def test_a_symlink_pointing_out_of_the_static_directory_is_refused(tmp_path):
    """Containment must be checked after resolution, not before: a link inside
    the root whose target is outside it passes any purely textual check."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html>", encoding="utf-8")

    secret = tmp_path / "secret.txt"
    secret.write_text("PRIVATE", encoding="utf-8")
    (static / "escape.txt").symlink_to(secret)

    running = CocoServer(StubApi(), static)
    running.start()
    try:
        response = client_for(running).get("/escape.txt")
    finally:
        running.stop()

    assert response.status in (403, 404)
    assert b"PRIVATE" not in response.body


def test_a_request_line_with_a_raw_absolute_path_is_refused(server):
    """http.client will not send this, so it is written by hand on a socket."""
    connection = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        connection.sendall(b"GET //etc/passwd HTTP/1.1\r\nHost: localhost\r\n\r\n")
        raw = connection.recv(4096)
    finally:
        connection.close()

    assert b" 200 " not in raw.split(b"\r\n")[0]
    assert b"root:" not in raw
