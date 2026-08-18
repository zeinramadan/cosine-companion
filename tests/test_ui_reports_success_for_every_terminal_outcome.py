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

``test_no_ui_module_can_reach_the_index_result`` is the static backstop for that
"every call site discards it" claim. It is an AST **reachability** check, not a
pattern match: it flags a producer call whose parent node is anything other than
``ast.Expr``. Its limits are stated in its own docstring and demonstrated by
``test_the_backstop_catches_the_construct_the_old_version_missed``, which runs
the same analyser over fifteen synthetic shapes - including ``if
service.run(...):``, which matters because the new status dict is TRUTHY where
the old return was ``None`` and falsey.

Cancellation is also pinned here, in the section near the bottom. The inventory
used to claim reindex_window's two cancellation lines were dead code; they are
not (inventory Sec 2.13 timings B and C, defects #16 and #17), and those tests
are what stops that claim coming back.

The service-level tests in ``tests/services/test_indexing_service.py`` pin the
NEW distinction. These tests pin the OBSERVABLE behaviour, which is what the
preservation contract is actually about. If PR 3 wants the UI to surface the
failure, PR 3 must change these tests deliberately -- they are the tripwire.

The load-bearing case is ``no_embeddings``: new tracks were found and not one of
them could be embedded. The service calls that a FAILURE; the Tkinter UI still
tells the user it succeeded. That is the current behaviour and it is pinned
below exactly as it is, bug and all.
"""

import ast
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
# reports them, WITH cancel_requested False.
#
# Cancellation is not a fourth outcome of the pipeline: it is a different
# interleaving over these same three. When the pipeline observes the flag at a
# per-track checkpoint it raises KeyboardInterrupt and returns nothing (timing A,
# pinned in test_indexing_service.py); when it does not, the run returns one of
# the three below and reindex_window takes its cancel branch instead (timing B,
# inventory defect #17, pinned at the bottom of this file).
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

    def __init__(self, result, raises=None):
        self.result = result
        self.raises = raises
        self.calls = []

    def __call__(self, settings):  # used in place of the IndexingService class
        return self

    def run(self, xml_path, **kwargs):
        self.calls.append((xml_path, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.result


def _install(monkeypatch, result, raises=None):
    """Patch the IndexingService that both windows import inside run_indexing."""
    import services

    service = RecordingService(result, raises=raises)
    monkeypatch.setattr(services, "IndexingService", service)
    return service


def _drain(q):
    """Every ('kind', payload) message the window queued, in order."""
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _reindex_stub(cancel_requested=False):
    """The attributes ReindexWindow.run_indexing reads off ``self``.

    Called unbound, so no Tk root, no display and no window is created.
    ``cancel_requested`` defaults to False - most of this file is about the
    non-cancelled outcomes. The two timing-B/C tests at the bottom pass True,
    which is the state a user's Cancel click leaves behind.
    """
    import threading

    return types.SimpleNamespace(
        message_queue=queue.Queue(),
        xml_path="/tmp/library.xml",
        force_full=False,
        cancel_event=threading.Event(),
        cancel_requested=cancel_requested,
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
    strict subset of ReindexWindow's - and just as blind to the status.

    The service-was-called assertion is load-bearing: without it this test would
    still pass if onboarding stopped invoking indexing altogether and just queued
    the hard-coded success pair.
    """
    service = _install(monkeypatch, result)
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)

    assert len(service.calls) == 1, "onboarding did not invoke the indexing service"
    assert _drain(stub.message_queue) == [
        ('complete', True),
        ('log', SUCCESS_LINE),
    ]


@pytest.mark.parametrize("result", TERMINAL_OUTCOMES)
def test_onboarding_never_surfaces_the_failure_distinction(monkeypatch, result):
    service = _install(monkeypatch, result)
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)
    messages = _drain(stub.message_queue)

    assert len(service.calls) == 1, "onboarding did not invoke the indexing service"
    assert ('complete', False) not in messages
    logs = " ".join(payload for kind, payload in messages if kind == 'log')
    for leak in (result.status, "failed", "no_embeddings"):
        assert leak not in logs


def test_onboarding_discards_the_index_result(monkeypatch):
    class Exploding:
        def __getattribute__(self, name):
            raise AssertionError(f"onboarding read IndexResult.{name}")

    service = _install(monkeypatch, Exploding())
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)

    assert len(service.calls) == 1, "onboarding did not invoke the indexing service"
    assert _drain(stub.message_queue) == [('complete', True), ('log', SUCCESS_LINE)]


def test_onboarding_still_passes_the_xml_path_and_progress_through(monkeypatch):
    """The mirror of test_reindex_window_still_passes_progress_and_cancel_through.

    Onboarding calls `service.run(self.xml_path, force_full=False,
    progress=on_progress)` (onboarding.py:389) and passes NO cancel - it has
    never offered cancellation. Pinned so "onboarding has no cancel path" stops
    being a prose claim.
    """
    service = _install(monkeypatch, TERMINAL_OUTCOMES[0].values[0])
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)

    (xml_path, kwargs), = service.calls
    assert xml_path == "/tmp/library.xml"
    assert kwargs["force_full"] is False
    assert callable(kwargs["progress"])
    assert "cancel" not in kwargs


def test_onboarding_progress_callback_queues_one_log_line_per_event(monkeypatch):
    """And the callback it passes is the real thing, not an inert lambda."""
    from services.indexing_service import ProgressEvent

    service = _install(monkeypatch, TERMINAL_OUTCOMES[0].values[0])
    stub = _onboarding_stub()

    onboarding_module.OnboardingWindow.run_indexing(stub)

    (_, kwargs), = service.calls
    kwargs["progress"](ProgressEvent(phase="embed", current=1, total=5, message="hello"))

    assert ('log', "hello") in _drain(stub.message_queue)


# ---------------------------------------------------------------------------
# Cancellation timings B and C (inventory Sec 2.13, defects #16 and #17)
# ---------------------------------------------------------------------------
#
# The inventory used to claim, universally, that reindex_window's own two
# cancellation lines are dead code. They are not. Both are reachable, because
# `cancel_check` is read in exactly ONE place - pipeline.py:182, at the top of
# each per-track loop iteration - so a flag first set after the last checkpoint
# is never observed and the pipeline returns normally instead of raising.
#
# These tests drive run_indexing with the state such an interleaving leaves
# behind: cancel_requested True and a service that RETURNS (B) or raises an
# ordinary Exception (C). Neither test asserts a wall-clock race; both are
# deterministic.


@pytest.mark.parametrize("result", TERMINAL_OUTCOMES)
def test_a_late_cancel_appends_the_cancelled_by_user_line(monkeypatch, result):
    """TIMING B. CURRENT BEHAVIOUR, NOT A BUG FIX.

    The pipeline never saw the flag, so service.run returns. reindex_window's
    `if self.cancel_requested:` (reindex_window.py:180) is True, and it queues
    ('cancelled', True) plus the line the inventory used to call dead. The
    success line is NOT queued - it is the else of the same branch.

    On the `indexed` outcome this is the user-visible half of defect #17: the
    data files were written and the window still reports a cancellation.
    """
    service = _install(monkeypatch, result)
    stub = _reindex_stub(cancel_requested=True)

    reindex_module.ReindexWindow.run_indexing(stub)

    assert len(service.calls) == 1, "the window did not invoke the indexing service"
    assert _drain(stub.message_queue) == [
        ('cancelled', True),
        ('log', "\n⚠️ Indexing cancelled by user"),
    ]


def test_a_late_cancel_does_not_queue_the_success_line(monkeypatch):
    """Stated separately because it is what workflow 34d checks by absence."""
    _install(monkeypatch, TERMINAL_OUTCOMES[0].values[0])
    stub = _reindex_stub(cancel_requested=True)

    reindex_module.ReindexWindow.run_indexing(stub)

    messages = _drain(stub.message_queue)
    assert ('complete', True) not in messages
    assert SUCCESS_LINE not in [payload for kind, payload in messages if kind == 'log']


def test_a_cancel_plus_an_unrelated_error_appends_the_other_cancelled_line(monkeypatch):
    """TIMING C. The `except Exception` cancellation branch
    (reindex_window.py:187-189) is not dead either.

    It needs an ordinary Exception - e.g. an OSError during the merge or the
    four-file write - to arrive while cancel_requested is already True. Rarer
    than A or B, because it needs two events, but reachable, so the inventory
    must not claim otherwise.
    """
    _install(monkeypatch, None, raises=OSError("disk full during save_all"))
    stub = _reindex_stub(cancel_requested=True)

    reindex_module.ReindexWindow.run_indexing(stub)

    assert _drain(stub.message_queue) == [
        ('cancelled', True),
        ('log', "\n⚠️ Indexing cancelled"),
    ]


def test_an_error_without_a_cancel_still_reports_the_error(monkeypatch):
    """The control for the test above: same exception, cancel_requested False."""
    _install(monkeypatch, None, raises=OSError("disk full during save_all"))
    stub = _reindex_stub(cancel_requested=False)

    reindex_module.ReindexWindow.run_indexing(stub)

    messages = _drain(stub.message_queue)
    assert messages[0] == ('complete', False)
    assert messages[1][1].startswith("\n❌ Error during indexing: disk full")
    assert len(messages) == 3  # the traceback is queued as a third line


def test_a_keyboardinterrupt_propagates_and_queues_nothing(monkeypatch):
    """TIMING A, at the window boundary rather than the service boundary.

    KeyboardInterrupt is a BaseException, so `except Exception` does not catch
    it: it leaves run_indexing, the daemon thread dies with a traceback on
    stderr, and the queue stays empty. This is what makes timings A and B differ
    in the log pane at all.
    """
    _install(monkeypatch, None, raises=KeyboardInterrupt("User cancelled indexing"))
    stub = _reindex_stub(cancel_requested=True)

    with pytest.raises(KeyboardInterrupt):
        reindex_module.ReindexWindow.run_indexing(stub)

    assert _drain(stub.message_queue) == []


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


PRODUCERS = {"run", "index_library"}


def _analyse(source, filename):
    """Parent-linked AST walk. Returns ``(sites, offenders, aliases)``.

    A *site* is ``(filename, lineno, name, parent_node_class_name)`` for every
    ``service.run(...)`` / ``index_library(...)`` call found.

    A producer call's result is discarded **iff** the call node's direct parent
    is an ``ast.Expr`` - that is the only Python construct that evaluates an
    expression and throws the value away. Every other parent (Assign, AnnAssign,
    AugAssign, NamedExpr, Return, Yield, If, While, Attribute, Subscript, Call
    as an argument, BoolOp, Compare, JoinedStr, comprehension, With, Assert, ...)
    keeps the value reachable, and lands in *offenders*. That is what makes this
    a reachability check rather than the earlier hand-listed pattern match,
    which knew only four shapes and could not see ``if service.run(...):``.

    *aliases* holds the ways a producer could be reached under a name this walk
    would not recognise: a bare (uncalled) reference that binds the function
    elsewhere, and ``getattr(x, "run")``.
    """
    tree = ast.parse(source)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    sites, offenders, aliases = [], [], []
    for node in ast.walk(tree):
        where = f"{filename}:{getattr(node, 'lineno', '?')}"

        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in PRODUCERS:
                parent = parents.get(node)
                sites.append((filename, node.lineno, name, type(parent).__name__))
                if not isinstance(parent, ast.Expr):
                    offenders.append(
                        f"{where}: {name}() result is reachable - parent is "
                        f"{type(parent).__name__}, not Expr"
                    )
            if isinstance(func, ast.Name) and func.id == "getattr":
                for arg in node.args[1:2]:
                    if isinstance(arg, ast.Constant) and arg.value in PRODUCERS:
                        aliases.append(f"{where}: dynamic getattr(..., {arg.value!r})")

        # A producer referenced WITHOUT calling it: `f = service.run` binds the
        # function, and a later `f()` is invisible to the check above.
        if isinstance(node, ast.Attribute) and node.attr in PRODUCERS:
            parent = parents.get(node)
            if not (isinstance(parent, ast.Call) and parent.func is node):
                aliases.append(f"{where}: bare reference to .{node.attr}")
        if isinstance(node, ast.Name) and node.id == "index_library":
            parent = parents.get(node)
            if not (isinstance(parent, ast.Call) and parent.func is node):
                if not isinstance(parent, (ast.ImportFrom, ast.alias)):
                    aliases.append(f"{where}: bare reference to index_library")

    return sites, offenders, aliases


def _ui_sources():
    """``src/ui/*.py`` plus the ``src/cosine_companion.py`` entrypoint."""
    from pathlib import Path

    ui_dir = Path(reindex_module.__file__).parent
    for path in sorted(ui_dir.glob("*.py")) + [ui_dir.parent / "cosine_companion.py"]:
        yield path.name, path.read_text(encoding="utf-8")


def test_no_ui_module_can_reach_the_index_result():
    """AST reachability backstop for the claim in this file's docstring.

    Soundness argument. A UI module can only read ``IndexResult`` if it first
    obtains a reference to one, and within this codebase the only sources are
    ``service.run(...)`` and ``index_library(...)``. A call's value is discarded
    exactly when its parent node is an ``ast.Expr``; any other parent keeps it
    reachable. So checking the parent of every producer call decides the
    question, rather than pattern-matching a hand-picked list of shapes.

    (Matching the attribute names *of the result* would be unsound in the other
    direction - ``.status`` is the Tk status-hint Label on ``App``,
    ``LibraryTab`` and three other widgets. ``.failed`` / ``.up_to_date`` appear
    nowhere else in the UI, so those two are still checked by name below.)

    What this CANNOT see, stated so the claim is not larger than the check:

    * a producer reached through a name this walk cannot resolve - a method
      called via ``getattr`` with a computed string, ``exec``/``eval``, or a
      callable stored in a dict. ``getattr`` with a *literal* producer name IS
      flagged, and so is any bare (uncalled) reference to ``.run`` /
      ``index_library``, which is how an alias would have to start.
    * name collisions in the safe direction: any method called ``run`` counts as
      a producer here, which can only produce false alarms, never silence.
    * it is a static check of ``src/ui/*.py`` plus ``src/cosine_companion.py``.
      A UI module importing a helper from outside that set, which itself reads
      the result, is out of scope.

    It also asserts the producers were actually FOUND. Without that, deleting
    every call site - or renaming ``run`` - would make this test pass vacuously,
    which is the failure mode a "no offenders" assertion invites.
    """
    sites, offenders, aliases = [], [], []
    for name, source in _ui_sources():
        s_, o_, a_ = _analyse(source, name)
        sites += s_
        offenders += o_
        aliases += a_

    # Non-vacuity: the three known call sites must all be present.
    found = {(f, name) for f, _, name, _ in sites}
    for expected in (("reindex_window.py", "run"),
                     ("onboarding.py", "run"),
                     ("cosine_companion.py", "index_library")):
        assert expected in found, (
            f"no {expected[1]}() call found in {expected[0]}; this test would "
            "otherwise pass by finding nothing to check"
        )

    assert offenders == [], (
        "A UI module can now reach the additive IndexResult API, so the "
        "characterisation above no longer describes 'nobody looks': "
        + ", ".join(offenders)
    )
    assert aliases == [], (
        "A producer is referenced without being called, so the parent check "
        "above no longer sees every call: " + ", ".join(aliases)
    )

    # The two names that could only mean IndexResult.
    RESULT_ONLY_ATTRS = {"failed", "up_to_date"}
    reads = []
    for name, source in _ui_sources():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute) and node.attr in RESULT_ONLY_ATTRS:
                reads.append(f"{name}:{node.lineno} reads .{node.attr}")
    assert reads == [], "; ".join(reads)


def test_the_backstop_catches_the_construct_the_old_version_missed():
    """The new status dict is TRUTHY where the old return was None and falsey.

    So `if service.run(...):` anywhere in the UI would have flipped behaviour,
    and the previous hand-listed backstop - assignment, return, immediate
    dereference - could not see it. This runs the REAL analyser (`_analyse`, the
    same function the test above uses) over synthetic modules, so the claim is
    demonstrated rather than asserted.
    """
    def offenders_in(body):
        indented = body.replace("\n", "\n    ")
        return _analyse(f"def f(service, x, y):\n    {indented}\n", "synthetic.py")[1]

    # Discarded - the current, characterised shape. No offender.
    assert offenders_in("service.run(x)") == []

    # Every one of these keeps the result reachable. The first three are the
    # shapes the old backstop looked for; the rest are what it could not see.
    for body in (
        "r = service.run(x)",                       # assign
        "return service.run(x)",                    # return
        "service.run(x).failed",                    # immediate dereference
        "if service.run(x):\n    pass",             # <-- the truthiness flip
        "while service.run(x):\n    pass",
        "log(service.run(x))",                      # passed into another call
        "assert service.run(x)",
        "[service.run(i) for i in y]",
        "ok = service.run(x) or fallback()",
        "print(f'{service.run(x)}')",
        "with service.run(x) as r:\n    pass",
        "r: object = service.run(x)",
        "if (r := service.run(x)):\n    pass",
        "return [service.run(x)]",
        "d = {'k': service.run(x)}",
    ):
        assert offenders_in(body), f"backstop missed: {body!r}"


def test_the_backstop_flags_aliasing_and_dynamic_dispatch():
    """The two escape hatches named in the docstring above are not silent."""
    assert _analyse("f = service.run\nf(x)\n", "synthetic.py")[2]
    assert _analyse("getattr(service, 'run')(x)\n", "synthetic.py")[2]
    assert _analyse("g = index_library\ng(x)\n", "synthetic.py")[2]
    # ...and a plain discarded call is not mistaken for one.
    assert _analyse("service.run(x)\n", "synthetic.py")[2] == []


def test_the_backstop_fails_when_there_is_nothing_to_check():
    """The zero-producer case. A file with no producer call yields no sites, so
    the non-vacuity assertion in the real test has something to bite on."""
    sites, offenders, aliases = _analyse("print('hello')\n", "synthetic.py")
    assert sites == [] and offenders == [] and aliases == []
