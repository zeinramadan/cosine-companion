"""The job machinery: lifecycle, the one-at-a-time rule, and the shared state.

Nothing here runs a real export. ``web.jobs`` deliberately knows nothing about
exports, so a job is a callable, and every callable in this file returns in
microseconds or blocks on an ``Event`` with a bounded timeout. There is no
sleep-until-hopefully and no spin: a worker that is supposed to be stuck waits
on a pipe-equivalent (``Event.wait``) and is released by the test.
"""

import io
import sys
import threading
import time

import pytest

from web.jobs import (
    CANCELLED,
    FAILED,
    MAX_ERROR_CHARACTERS,
    RUNNING,
    SUCCEEDED,
    Job,
    JobInProgress,
    JobRegistry,
    WorkOutcome,
)

#: Every blocking wait in this file is bounded by this. A test that would hang
#: fails instead, and it fails in the assertion that names what it was waiting
#: for rather than in pytest's collection timeout.
WAIT = 5.0


class Gate:
    """A work function that blocks until the test releases it.

    ``entered`` is set once the worker is inside the callable, so a test can
    know the thread is really running before it asserts on ``running`` state.
    ``release`` is what lets it return. Both are ``threading.Event``s, so a
    blocked worker consumes no CPU.
    """

    def __init__(self, result=None, raises=None, cancelled=None):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.result = {} if result is None else result
        self.raises = raises
        #: None means "report cancelled if the event was set", which is what
        #: ExportService does. True/False force the answer.
        self._cancelled = cancelled
        self.saw_cancel_set = None
        self.reporter = None

    def __call__(self, report, cancel):
        self.reporter = report
        self.entered.set()
        if not self.release.wait(timeout=WAIT):  # pragma: no cover - a hang
            raise AssertionError("the work gate was never released")
        self.saw_cancel_set = cancel.is_set()
        if self.raises is not None:
            raise self.raises
        cancelled = cancel.is_set() if self._cancelled is None else self._cancelled
        return WorkOutcome(cancelled=cancelled, result=self.result)


def finish(job, gate):
    """Release the worker and wait for the job to reach a terminal state."""
    gate.release.set()
    assert job.thread is not None
    job.thread.join(timeout=WAIT)
    assert not job.thread.is_alive(), "the worker thread did not finish"
    return job.snapshot()


def start_and_enter(registry, kind="export", gate=None, **kwargs):
    """Start a gated job and wait until the worker is really inside it."""
    gate = Gate() if gate is None else gate
    job = registry.start(kind, gate, **kwargs)
    assert gate.entered.wait(timeout=WAIT), "the worker never started"
    return job, gate


@pytest.fixture
def registry():
    return JobRegistry()


# -- lifecycle -------------------------------------------------------------


def test_a_started_job_is_running_and_carries_what_it_was_started_with(registry):
    job, gate = start_and_enter(registry, "export", total=1532, message="Exporting")

    snapshot = job.snapshot()
    assert snapshot.state == RUNNING
    assert snapshot.kind == "export"
    assert snapshot.total == 1532
    assert snapshot.message == "Exporting"
    assert snapshot.current == 0
    assert snapshot.finished_at is None
    assert snapshot.result is None
    assert snapshot.error is None
    assert snapshot.terminal is False

    finish(job, gate)


def test_progress_the_worker_reports_is_visible_to_a_reader(registry):
    job, gate = start_and_enter(registry, total=3)

    gate.reporter(2, 3, "Aphex Twin - Xtal")

    snapshot = job.snapshot()
    assert (snapshot.current, snapshot.total, snapshot.message) == (
        2,
        3,
        "Aphex Twin - Xtal",
    )
    assert snapshot.state == RUNNING

    finish(job, gate)


def test_a_completed_job_publishes_its_result_and_a_finish_time(registry):
    gate = Gate(result={"playlists_created": 12})
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.state == SUCCEEDED
    assert snapshot.terminal is True
    assert dict(snapshot.result) == {"playlists_created": 12}
    assert snapshot.finished_at is not None
    assert snapshot.finished_at >= snapshot.started_at
    assert snapshot.error is None


def test_a_published_result_cannot_be_mutated_by_a_reader(registry):
    """``result`` is a MappingProxyType, so "never changes" is enforced.

    Two request threads read the same terminal snapshot. If one could write
    into the result mapping the other would see the write, which is the whole
    property ``_Generation.by_track`` wraps its mapping for.
    """
    gate = Gate(result={"successful": 3})
    job, _ = start_and_enter(registry, gate=gate)
    snapshot = finish(job, gate)

    with pytest.raises(TypeError):
        snapshot.result["successful"] = 99

    assert snapshot.result["successful"] == 3


def test_the_registry_finds_a_job_by_id_and_lists_it(registry):
    job, gate = start_and_enter(registry)

    assert registry.get(job.job_id) is job
    assert registry.get("nothing-like-this") is None
    assert [found.job_id for found in registry.all()] == [job.job_id]

    finish(job, gate)


def test_all_returns_newest_first(registry):
    first, gate = start_and_enter(registry)
    finish(first, gate)
    second, gate2 = start_and_enter(registry)
    finish(second, gate2)

    assert [job.job_id for job in registry.all()] == [second.job_id, first.job_id]


# -- one job at a time -----------------------------------------------------


def test_a_second_job_is_refused_while_one_is_running(registry):
    job, gate = start_and_enter(registry, "export")

    with pytest.raises(JobInProgress) as raised:
        registry.start("reindex", Gate())

    # The refusal names the job holding the slot: a bare "busy" leaves the
    # caller with nothing to offer the user.
    assert raised.value.running.job_id == job.job_id
    assert raised.value.running.kind == "export"

    finish(job, gate)


def test_a_refused_start_leaves_the_running_job_untouched(registry):
    job, gate = start_and_enter(registry, "export", total=7)
    before = job.snapshot()

    with pytest.raises(JobInProgress):
        registry.start("reindex", Gate())

    assert job.snapshot() == before
    assert [found.job_id for found in registry.all()] == [job.job_id]

    finish(job, gate)


def test_a_second_job_starts_once_the_first_has_finished(registry):
    first, gate = start_and_enter(registry)
    finish(first, gate)

    second, gate2 = start_and_enter(registry, "reindex")
    assert second.snapshot().state == RUNNING
    finish(second, gate2)


def test_only_one_of_many_simultaneous_starts_wins(registry):
    """The check and the insert are one atomic region, not two steps.

    Sixteen threads are held at a barrier and released together. The id
    factory blocks briefly, which puts a real, deterministic window between
    "nothing is running" and "mine is registered" - the window a split
    check-then-insert leaves open. With one lock around both, exactly one
    thread gets through and fifteen see ``JobInProgress``.
    """
    slow_ids = _SlowIds(delay=0.05)
    registry = JobRegistry(id_factory=slow_ids)

    threads_count = 16
    barrier = threading.Barrier(threads_count)
    started = []
    refused = []
    lock = threading.Lock()
    gates = [Gate() for _ in range(threads_count)]

    def attempt(index):
        barrier.wait(timeout=WAIT)
        try:
            job = registry.start("export", gates[index])
        except JobInProgress:
            with lock:
                refused.append(index)
        else:
            with lock:
                started.append(job)

    threads = [
        threading.Thread(target=attempt, args=(index,), daemon=True)
        for index in range(threads_count)
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=WAIT)
            assert not thread.is_alive(), "a starting thread did not return"
    finally:
        for gate in gates:
            gate.release.set()

    assert len(started) == 1, f"{len(started)} jobs started concurrently"
    assert len(refused) == threads_count - 1
    # And the registry agrees: the one that won is the only one recorded.
    assert [job.job_id for job in registry.all()] == [started[0].job_id]

    for job in started:
        job.thread.join(timeout=WAIT)


class _SlowIds:
    """An id factory that takes measurable time, widening the start window."""

    def __init__(self, delay):
        self.delay = delay
        self.issued = 0

    def __call__(self):
        self.issued += 1
        time.sleep(self.delay)
        return f"job-{self.issued}"


def test_running_reports_the_job_holding_the_slot(registry):
    assert registry.running() is None

    job, gate = start_and_enter(registry, "reindex")
    running = registry.running()
    assert running is not None
    assert running.job_id == job.job_id

    finish(job, gate)
    assert registry.running() is None


# -- cancellation ----------------------------------------------------------


def test_cancel_sets_the_event_the_worker_reads(registry):
    job, gate = start_and_enter(registry)

    snapshot = job.request_cancel()
    assert snapshot.cancel_requested is True
    assert job.cancel_event.is_set() is True

    finish(job, gate)
    # The worker really observed it, rather than the flag merely being set on
    # the record a reader sees.
    assert gate.saw_cancel_set is True


def test_a_cancelled_worker_lands_in_the_cancelled_state_with_its_partial_result(
    registry,
):
    """Cancel keeps what the run produced. See ``api._export_result_document``.

    ``ExportService`` returns an ``ExportResult`` with ``cancelled=True`` and
    real counts rather than raising, and the job must carry those counts into
    the terminal record - that is what lets a UI say what is on disk.
    """
    gate = Gate(result={"playlists_created": 47, "total_tracks": 1532})
    job, _ = start_and_enter(registry, gate=gate)

    job.request_cancel()
    snapshot = finish(job, gate)

    assert snapshot.state == CANCELLED
    assert dict(snapshot.result) == {"playlists_created": 47, "total_tracks": 1532}
    assert snapshot.cancel_requested is True


def test_a_worker_raising_keyboardinterrupt_is_cancelled_not_failed(registry):
    """``IndexingService.run`` raises KeyboardInterrupt at a cancel checkpoint.

    Reported as a failure it would put a red error in front of a user who
    pressed Stop, and it would carry a traceback message with no meaning.
    """
    gate = Gate(raises=KeyboardInterrupt())
    job, _ = start_and_enter(registry, "reindex", gate=gate)

    job.request_cancel()
    snapshot = finish(job, gate)

    assert snapshot.state == CANCELLED
    assert snapshot.error is None
    assert snapshot.result is None


def test_cancelling_a_finished_job_does_not_disturb_it(registry):
    job, gate = start_and_enter(registry)
    finished = finish(job, gate)

    after = job.request_cancel()

    assert after.state == finished.state == SUCCEEDED
    assert after.cancel_requested is False, (
        "a cancel that was never delivered must not be reported as requested"
    )
    assert after.finished_at == finished.finished_at


def test_a_cancel_that_arrives_too_late_is_visible_beside_the_success(registry):
    """The shape of inventory defect #17, and it is reported rather than hidden.

    ``cancelled=False`` from the work function models a run whose cancel the
    pipeline never observed: it completed for real. The job says so - and the
    terminal snapshot still carries ``cancel_requested``, so "the user pressed
    Stop and it finished anyway" is legible instead of invisible.
    """
    gate = Gate(cancelled=False, result={"status": "indexed"})
    job, _ = start_and_enter(registry, "reindex", gate=gate)

    job.request_cancel()
    snapshot = finish(job, gate)

    assert snapshot.state == SUCCEEDED
    assert snapshot.cancel_requested is True


def test_cancel_is_idempotent(registry):
    job, gate = start_and_enter(registry)

    first = job.request_cancel()
    second = job.request_cancel()

    assert first.cancel_requested is second.cancel_requested is True
    assert first.started_at == second.started_at
    finish(job, gate)


# -- failure ---------------------------------------------------------------


def test_a_worker_that_raises_lands_the_job_in_failed_with_the_message(
    registry, capsys
):
    gate = Gate(raises=PermissionError(13, "Permission denied", "/Volumes/ro/out"))
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.state == FAILED
    assert snapshot.result is None
    assert "PermissionError" in snapshot.error
    assert "Permission denied" in snapshot.error
    # The traceback goes to the developer's stderr, the message to the client.
    assert "PermissionError" in capsys.readouterr().err


def test_a_worker_that_raises_systemexit_still_reaches_a_terminal_state(registry):
    """Nothing may escape the worker.

    ``SystemExit`` is a ``BaseException``: raised in a worker thread it ends
    the thread silently. Left uncaught, the job would stay ``running`` for the
    life of the process - and because only one job runs at a time, every later
    job would be refused by a job that is not executing. That is why ``_run``
    catches ``BaseException`` rather than ``Exception``.
    """
    gate = Gate(raises=SystemExit(2))
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.terminal is True
    assert snapshot.state == FAILED
    # And the registry is usable again, which is the property that matters.
    next_job, next_gate = start_and_enter(registry, "reindex")
    finish(next_job, next_gate)


class UnprintableError(Exception):
    """An exception whose own ``__str__`` raises.

    Exotic, but ``work`` is an arbitrary callable and an exception class is
    ordinary user code: nothing stops one of these arriving. It is here
    because the job record's ``error`` is built by calling ``str()`` on
    whatever was raised, and that call is not guaranteed to return.
    """

    def __str__(self):
        raise RuntimeError("this exception cannot describe itself")


class WatchingStderr(io.StringIO):
    """A stderr that records what the job looked like as it was written to."""

    def __init__(self):
        super().__init__()
        self.job = None
        self.terminal_at_first_write = None

    def write(self, text):
        if self.job is not None and self.terminal_at_first_write is None:
            self.terminal_at_first_write = self.job.snapshot().terminal
        return super().write(text)


def test_a_worker_whose_failure_cannot_be_REPORTED_still_publishes_the_failure(
    registry, monkeypatch
):
    """Reporting a failure must not be able to prevent publishing it.

    ``Job._run`` writes the traceback to ``sys.stderr`` for the developer.
    With stderr closed - which is the state of a frozen windowed build with no
    console attached - that write raises ``ValueError`` from inside the very
    handler whose job is to land the job somewhere terminal. Ordinary work
    raising an ordinary ``ValueError`` then left the worker thread dead with
    the job still ``running``, and because only one job runs at a time every
    later start was refused with ``JobInProgress`` naming a job that was not
    executing. That is exactly the disaster ``_run``'s own docstring forbids
    in capitals.

    A real closed file rather than a mock: ``io.StringIO`` after ``close()``
    raises the same ``ValueError`` a closed stream does, from the same call.

    ``threading.excepthook`` is watched as well as the job record, and the two
    assertions are separate properties. The record says the CALLER was told;
    an empty excepthook list says the worker also left by the front door
    rather than dying on the way out - which is what stops the same closed
    stream turning every job failure into interpreter-level noise.
    """
    broken = io.StringIO()
    broken.close()
    monkeypatch.setattr(sys, "stderr", broken)
    unhandled = []
    monkeypatch.setattr(threading, "excepthook", unhandled.append)

    gate = Gate(raises=ValueError("ordinary work went wrong"))
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.terminal is True
    assert snapshot.state == FAILED
    assert "ValueError" in snapshot.error
    assert "ordinary work went wrong" in snapshot.error
    assert unhandled == [], (
        "the worker died on its way out; the failure reached the record but "
        "the thread did not finish cleanly"
    )
    # The property that matters: the slot is free again.
    assert registry.running() is None
    next_job, next_gate = start_and_enter(registry, "export")
    finish(next_job, next_gate)


def test_the_terminal_snapshot_is_published_before_the_traceback_is_written(
    registry, monkeypatch
):
    """The order, pinned on its own, so it is not left resting on the guard.

    Swallowing the reporting error is enough to keep a failure from wedging
    the registry, so the ordering would survive being reversed with every
    other test green. It is worth having anyway, and therefore worth
    pinning: publication is not downstream of reporting, it is upstream of
    it. The instrumented stream reads the job at the instant the first byte
    of the traceback is written, which is the only instant at which the two
    orders differ.
    """
    watcher = WatchingStderr()
    monkeypatch.setattr(sys, "stderr", watcher)

    gate = Gate(raises=ValueError("ordinary work went wrong"))
    job, _ = start_and_enter(registry, gate=gate)
    watcher.job = job

    snapshot = finish(job, gate)

    assert snapshot.state == FAILED
    assert watcher.terminal_at_first_write is True, (
        "the traceback was written while the job was still running: a reader "
        "polling at that moment sees a job nobody is running any more"
    )
    # ...and the traceback really was written, so this is not vacuous.
    assert "ordinary work went wrong" in watcher.getvalue()


def test_a_failure_that_cannot_DESCRIBE_itself_still_publishes_the_failure(
    registry, capsys
):
    """The same wedge, one step earlier, and not in the reported finding.

    The terminal snapshot carries ``f"{type(error).__name__}: {error}"``, and
    the ``{error}`` half is a call into the exception's own ``__str__``. If
    that raises, the publication never happens and the registry is wedged for
    the life of the process in exactly the way above - a different door into
    the same room. The type name is still true and still useful, so it is
    what survives.
    """
    gate = Gate(raises=UnprintableError())
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.terminal is True
    assert snapshot.state == FAILED
    assert snapshot.error == "UnprintableError"
    assert registry.running() is None
    next_job, next_gate = start_and_enter(registry, "export")
    finish(next_job, next_gate)
    capsys.readouterr()


def test_a_long_error_message_is_truncated(registry):
    gate = Gate(raises=ValueError("x" * (MAX_ERROR_CHARACTERS * 3)))
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert len(snapshot.error) == MAX_ERROR_CHARACTERS
    assert snapshot.error.endswith("…")


def test_progress_reported_after_the_job_finished_is_ignored(registry):
    """A terminal state that can be walked back is not a terminal state."""
    gate = Gate(result={"successful": 1})
    job, _ = start_and_enter(registry, gate=gate)
    snapshot = finish(job, gate)

    job.report_progress(999, 999, "impossible")

    after = job.snapshot()
    assert after.state == snapshot.state == SUCCEEDED
    assert (after.current, after.message) == (snapshot.current, snapshot.message)
    assert after.message != "impossible"


# -- retention -------------------------------------------------------------


def test_finished_jobs_are_evicted_oldest_first(registry):
    """Bounded, so a window left open for a day does not grow without limit."""
    ticks = iter(range(1000))
    registry = JobRegistry(clock=lambda: float(next(ticks)), max_remembered=3)

    ids = []
    for _ in range(5):
        job, gate = start_and_enter(registry)
        ids.append(job.job_id)
        finish(job, gate)

    remembered = [job.job_id for job in registry.all()]
    assert len(remembered) == 3
    assert remembered == list(reversed(ids[-3:]))
    for evicted in ids[:-3]:
        assert registry.get(evicted) is None


def test_a_running_job_survives_any_number_of_refused_starts(registry):
    """The running job stays findable however many starts pile up behind it.

    Note what this does NOT pin, because a mutation proved it: retention can
    never evict a running job, but that is structural rather than guarded -
    ``JobRegistry.start`` raises before it reaches the eviction, so eviction
    only ever runs when every remembered job is terminal. An earlier draft had
    a "skip non-terminal jobs" branch inside the pruning instead, and deleting
    that branch left every test green because nothing could reach it. The
    branch is gone; this test covers the reachable half - that a refused start
    leaves the registry, the running job and the retention untouched.
    """
    ticks = iter(range(1000))
    registry = JobRegistry(clock=lambda: float(next(ticks)), max_remembered=2)

    for _ in range(4):
        job, gate = start_and_enter(registry)
        finish(job, gate)
    remembered_before = [job.job_id for job in registry.all()]

    live, live_gate = start_and_enter(registry, "reindex")
    for _ in range(4):
        with pytest.raises(JobInProgress):
            registry.start("export", Gate())

    assert registry.get(live.job_id) is live
    assert registry.running().job_id == live.job_id
    # The refused starts evicted nothing: retention is not reached at all.
    assert [job.job_id for job in registry.all()][1:] == remembered_before[:1]
    finish(live, live_gate)


# -- the snapshot discipline ----------------------------------------------


def test_a_snapshot_is_a_whole_answer_that_later_writes_do_not_edit(registry):
    """One read answers everything, and keeps answering it.

    A reader that took a snapshot before a progress report must still see the
    values it took. Held as live attributes on the job, it would see the new
    ``current`` beside the old ``message`` - the mixed read
    ``PlaylistService.lookup`` was rewritten to make impossible.
    """
    job, gate = start_and_enter(registry, total=3)
    gate.reporter(1, 3, "first")

    taken = job.snapshot()

    gate.reporter(2, 3, "second")
    job.request_cancel()

    assert (taken.current, taken.message) == (1, "first")
    assert taken.cancel_requested is False
    assert taken.state == RUNNING
    # ...while the live job really has moved on.
    assert job.snapshot().current == 2

    finish(job, gate)


def test_a_job_is_frozen_state_not_mutable_attributes():
    """``JobSnapshot`` is frozen: publication is a rebind, never an edit."""
    job = Job("j1", "export")
    snapshot = job.snapshot()

    with pytest.raises(Exception):
        snapshot.state = SUCCEEDED

    assert job.snapshot().state == RUNNING
