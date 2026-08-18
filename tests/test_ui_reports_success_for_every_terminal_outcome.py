"""CHARACTERISATION. The Tkinter UI reports SUCCESS for all three terminal
indexing outcomes, including the one the service calls a failure.

Why this file exists
--------------------
``index_library`` used to ``return`` bare ``None`` from both of its empty
outcomes. It now returns a status dict, and ``IndexResult`` exposes the
``no_embeddings`` case as ``failed is True``
(``services/indexing_service.py``). A reviewer read that as a silent bug fix
smuggled into a strict-behaviour-preservation PR.

It is not one, and this file is the proof: the new distinction is **additive API
surface that no current caller reads**. Every call site discards the return
value entirely --

* ``ui/reindex_window.py:173``  ``service.run(...)``    - no assignment
* ``ui/onboarding.py:389``     ``service.run(...)``     - no assignment
* ``cosine_companion.py:50``   ``index_library(...)``   - no assignment

-- so what the user observes is unchanged: all three outcomes still queue
``('complete', True)`` and the line ``\\n✅ Indexing completed successfully!``.

The service-level tests in ``tests/services/test_indexing_service.py`` pin the
NEW distinction. These tests pin the OBSERVABLE behaviour, which is what the
preservation contract is actually about. If PR 3 wants the UI to surface the
failure, PR 3 must change these tests deliberately -- they are the tripwire.

The load-bearing case is ``no_embeddings``: new tracks were found and not one of
them could be embedded. The service calls that a FAILURE; the Tkinter UI still
tells the user it succeeded. That is the current behaviour and it is pinned
below exactly as it is, bug and all.
"""

import queue
import types

import pytest

pytest.importorskip("tkinter", reason="headless build of Python without Tk")

import ui.onboarding as onboarding_module  # noqa: E402
import ui.reindex_window as reindex_module  # noqa: E402
from services.indexing_service import (  # noqa: E402
    STATUS_INDEXED,
    STATUS_NO_EMBEDDINGS,
    STATUS_UP_TO_DATE,
    IndexResult,
)

SUCCESS_LINE = "\n✅ Indexing completed successfully!"


# The three terminal outcomes of a run that does not raise, as IndexingService
# reports them. Cancellation is the fourth outcome and raises KeyboardInterrupt
# instead of returning; it is pinned separately in test_indexing_service.py.
TERMINAL_OUTCOMES = [
    pytest.param(
        IndexResult(status=STATUS_INDEXED, total_tracks_indexed=5, new_tracks_added=5,
                    new_tracks_found=5),
        id="indexed",
    ),
    pytest.param(
        IndexResult(status=STATUS_UP_TO_DATE, new_tracks_found=0),
        id="up_to_date",
    ),
    pytest.param(
        # service.failed is True for this one. The UI must still say success.
        IndexResult(status=STATUS_NO_EMBEDDINGS, new_tracks_found=3, new_tracks_added=0),
        id="no_embeddings",
    ),
]


class RecordingService:
    """Stands in for IndexingService, returning a canned terminal outcome.

    Also records the call so we can assert the UI passed a progress callback and
    never inspected what came back.
    """

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, settings):  # used in place of the IndexingService class
        return self

    def run(self, xml_path, **kwargs):
        self.calls.append((xml_path, kwargs))
        return self.result


def _install(monkeypatch, result):
    """Patch the IndexingService that both windows import inside run_indexing."""
    import services

    service = RecordingService(result)
    monkeypatch.setattr(services, "IndexingService", service)
    return service


def _drain(q):
    """Every ('kind', payload) message the window queued, in order."""
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _reindex_stub():
    """The attributes ReindexWindow.run_indexing reads off ``self``.

    Called unbound, so no Tk root, no display and no window is created.
    ``cancel_requested`` is a plain False here: this file is about the
    non-cancelled outcomes.
    """
    import threading

    return types.SimpleNamespace(
        message_queue=queue.Queue(),
        xml_path="/tmp/library.xml",
        force_full=False,
        cancel_event=threading.Event(),
        cancel_requested=False,
    )


def _onboarding_stub():
    """The attributes OnboardingWindow.run_indexing reads off ``self``."""
    return types.SimpleNamespace(
        message_queue=queue.Queue(),
        xml_path="/tmp/library.xml",
    )


# ---------------------------------------------------------------------------
# ReindexWindow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("result", TERMINAL_OUTCOMES)
def test_reindex_window_reports_success_for_every_terminal_outcome(monkeypatch, result):
    """CURRENT BEHAVIOUR. indexed / up_to_date / no_embeddings are
    indistinguishable to the user: identical queue traffic, identical log line."""
    _install(monkeypatch, result)
    stub = _reindex_stub()

    reindex_module.ReindexWindow.run_indexing(stub)

    assert _drain(stub.message_queue) == [
        ('complete', True),
        ('log', SUCCESS_LINE),
    ]


@pytest.mark.parametrize("result", TERMINAL_OUTCOMES)
def test_reindex_window_never_surfaces_the_failure_distinction(monkeypatch, result):
    """No queued message mentions the status, and none reports a failure -
    not even for the outcome whose IndexResult.failed is True."""
    _install(monkeypatch, result)
    stub = _reindex_stub()

    reindex_module.ReindexWindow.run_indexing(stub)
    messages = _drain(stub.message_queue)

    assert ('complete', False) not in messages
    assert not any(kind == 'cancelled' for kind, _ in messages)
    logs = " ".join(payload for kind, payload in messages if kind == 'log')
    for leak in (result.status, "failed", "no_embeddings", "up to date", "up_to_date"):
        assert leak not in logs, f"UI leaked {leak!r}; it never did on main"


def test_reindex_window_discards_the_index_result(monkeypatch):
    """The return value is not read at all. Returning an object that raises on
    ANY attribute access changes nothing - which is what makes `status` and
    `failed` additive rather than a behaviour change."""

    class Exploding:
        def __getattribute__(self, name):
            raise AssertionError(f"reindex_window read IndexResult.{name}")

    _install(monkeypatch, Exploding())
    stub = _reindex_stub()

    reindex_module.ReindexWindow.run_indexing(stub)

    assert _drain(stub.message_queue) == [('complete', True), ('log', SUCCESS_LINE)]


def test_reindex_window_still_passes_progress_and_cancel_through(monkeypatch):
    """The success path above must not be an artefact of a broken call."""
    service = _install(monkeypatch, TERMINAL_OUTCOMES[0].values[0])
    stub = _reindex_stub()

    reindex_module.ReindexWindow.run_indexing(stub)

    (xml_path, kwargs), = service.calls
    assert xml_path == "/tmp/library.xml"
    assert kwargs["cancel"] is stub.cancel_event
    assert kwargs["force_full"] is False
    assert callable(kwargs["progress"])


# ---------------------------------------------------------------------------
# OnboardingWindow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("result", TERMINAL_OUTCOMES)
def test_onboarding_reports_success_for_every_terminal_outcome(monkeypatch, result):
    """CURRENT BEHAVIOUR. Onboarding has no cancel path, so its worker is a
    strict subset of ReindexWindow's - and just as blind to the status."""
    _install(monkeypatch, result)
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)

    assert _drain(stub.message_queue) == [
        ('complete', True),
        ('log', SUCCESS_LINE),
    ]


@pytest.mark.parametrize("result", TERMINAL_OUTCOMES)
def test_onboarding_never_surfaces_the_failure_distinction(monkeypatch, result):
    _install(monkeypatch, result)
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)
    messages = _drain(stub.message_queue)

    assert ('complete', False) not in messages
    logs = " ".join(payload for kind, payload in messages if kind == 'log')
    for leak in (result.status, "failed", "no_embeddings"):
        assert leak not in logs


def test_onboarding_discards_the_index_result(monkeypatch):
    class Exploding:
        def __getattribute__(self, name):
            raise AssertionError(f"onboarding read IndexResult.{name}")

    _install(monkeypatch, Exploding())
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)

    assert _drain(stub.message_queue) == [('complete', True), ('log', SUCCESS_LINE)]


# ---------------------------------------------------------------------------
# The whole point, stated once
# ---------------------------------------------------------------------------


def test_the_worst_case_still_reads_as_success_to_the_user(monkeypatch):
    """New tracks were found and NOT ONE could be embedded. The service says
    failed; both windows say '✅ Indexing completed successfully!'.

    This is the exact case the reviewer worried had been silently fixed. It has
    not been: the user still sees a success. Pinned here so that if PR 3 ever
    changes it, it changes it on purpose."""
    disaster = IndexResult(status=STATUS_NO_EMBEDDINGS, new_tracks_found=1307,
                           new_tracks_added=0)
    assert disaster.failed is True
    assert disaster.up_to_date is False

    _install(monkeypatch, disaster)
    reindex = _reindex_stub()
    reindex_module.ReindexWindow.run_indexing(reindex)

    _install(monkeypatch, disaster)
    onboarding = _onboarding_stub()
    onboarding_module.OnboardingWindow.run_indexing(onboarding)

    expected = [('complete', True), ('log', SUCCESS_LINE)]
    assert _drain(reindex.message_queue) == expected
    assert _drain(onboarding.message_queue) == expected


def test_no_ui_module_can_reach_the_index_result():
    """Static backstop for the claim in this file's docstring.

    Soundness: a UI module can only read ``IndexResult`` if it first obtains a
    reference to one, and the only sources are ``service.run(...)`` and
    ``index_library(...)``. So it is enough to prove that no call site captures,
    returns, or immediately dereferences either. (Matching attribute names
    directly would be unsound in the other direction - ``.status`` is the Tk
    status-hint Label on ``App``, ``LibraryTab`` and three other widgets.)

    ``.failed`` / ``.up_to_date`` are checked by name as well, because those two
    names appear nowhere else in the UI and would be the natural way to consume
    the distinction.
    """
    import ast
    from pathlib import Path

    ui_dir = Path(reindex_module.__file__).parent
    entrypoint = ui_dir.parent / "cosine_companion.py"
    PRODUCERS = {"run", "index_library"}
    RESULT_ONLY_ATTRS = {"failed", "up_to_date"}

    def called_name(node):
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)

    offenders = []
    for path in sorted(ui_dir.glob("*.py")) + [entrypoint]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            where = f"{path.name}:{getattr(node, 'lineno', '?')}"

            # 1. the result is captured in a name
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                if called_name(node.value) in PRODUCERS:
                    offenders.append(f"{where} captures {called_name(node.value)}()")

            # 2. the result is handed onward
            if isinstance(node, ast.Return) and called_name(node.value) in PRODUCERS:
                offenders.append(f"{where} returns {called_name(node.value)}()")

            # 3. the result is dereferenced in place, e.g. service.run(...).failed
            if isinstance(node, (ast.Attribute, ast.Subscript)):
                if called_name(node.value) in PRODUCERS:
                    offenders.append(f"{where} dereferences {called_name(node.value)}()")

            # 4. the two names that could only mean IndexResult
            if isinstance(node, ast.Attribute) and node.attr in RESULT_ONLY_ATTRS:
                offenders.append(f"{where} reads .{node.attr}")

    assert offenders == [], (
        "A UI module can now reach the additive IndexResult API, so the "
        "characterisation above no longer describes 'nobody looks': "
        + ", ".join(offenders)
    )
