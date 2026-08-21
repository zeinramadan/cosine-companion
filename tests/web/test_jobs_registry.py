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

import web.jobs as jobs_module
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


def read_from_another_thread(read):
    """Run ``read`` on its own thread and return what it saw, bounded.

    Used where the claim under test is about what a READER sees. Job and
    registry readers take no lock at all, so the answer a reader would get
    is the answer this gets - and running it on a real second thread is
    what makes that a demonstration rather than an assertion about the
    writer's own view.
    """
    seen = []
    reader = threading.Thread(
        target=lambda: seen.append(read()), name="coco-test-reader", daemon=True
    )
    reader.start()
    reader.join(timeout=WAIT)
    assert not reader.is_alive(), "the reader thread did not return"
    return seen[0]


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


class ExplodingJob(Job):
    """A ``Job`` whose FIRST ``start`` raises, as ``Thread.start`` really can.

    ``threading.Thread.start`` raises ``RuntimeError("can't start new
    thread")`` when the process cannot create another one. Modelled here
    rather than by exhausting the machine's threads, which would be a test
    that hurts the machine it runs on and is not reliably reproducible.

    Only the first call explodes, so the same registry can be asked to start a
    real job afterwards - which is the half that matters.
    """

    explode = True

    def start(self, work):
        if type(self).explode:
            type(self).explode = False
            raise RuntimeError("can't start new thread")
        super().start(work)


def test_a_job_whose_thread_cannot_start_leaves_no_record_behind(
    registry, monkeypatch
):
    """A job that never ran must not hold the slot every later job needs.

    The registry published the job into ``_jobs`` and started its thread
    afterwards. When the start raised, the publication had already happened -
    so a ``running`` record with nothing running it stayed registered for the
    life of the process and every later start was refused with
    ``JobInProgress``. One resource-exhaustion moment disabled exports until
    the app was restarted.

    Starting first and publishing second makes that impossible rather than
    unlikely: there is nothing to roll back, because nothing was published.
    """
    monkeypatch.setattr(ExplodingJob, "explode", True)
    monkeypatch.setattr(jobs_module, "Job", ExplodingJob)

    with pytest.raises(RuntimeError):
        registry.start("export", Gate())

    assert registry.all() == (), "a job that never started was remembered"
    assert registry.running() is None

    # And the registry is usable: the next start is not refused by a ghost.
    job, gate = start_and_enter(registry, "export")
    assert job.snapshot().state == RUNNING
    finish(job, gate)


def test_no_reader_can_find_a_job_before_its_worker_exists(registry, monkeypatch):
    """``JobRegistry.start``'s no-window claim, checked by a real reader.

    Readers - ``get``, ``all``, ``running`` - take no registry lock; that is
    deliberate and it is what makes a poll cheap. It also means the lock the
    writer holds buys nothing here: whatever is in ``_jobs`` is visible the
    instant it is rebound. So publishing the job and then starting its thread
    left a window in which a reader could find a ``running`` job whose
    ``thread`` was ``None`` - the window the docstring said did not exist.

    The reader runs at the one instant the two orders differ: inside
    ``Job.start``, before the thread is created. Either the job is not
    findable yet, or it is findable and already has a thread. Nothing else is
    an acceptable answer.
    """
    seen = []

    class WatchedJob(Job):
        def start(self, work):
            found = read_from_another_thread(lambda: registry.get(self.job_id))
            seen.append((found, None if found is None else found.thread))
            super().start(work)

    monkeypatch.setattr(jobs_module, "Job", WatchedJob)

    job, gate = start_and_enter(registry, "export")
    finish(job, gate)

    assert len(seen) == 1
    found, thread = seen[0]
    assert found is None or thread is not None, (
        "a reader found a running job whose worker did not exist yet"
    )
    # ...and once the start has returned, both halves are true together.
    assert registry.get(job.job_id) is job
    assert job.thread is not None


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


# -- nothing may escape: the guards themselves ------------------------------
#
# Every test below drives a failure that an ``except Exception`` does NOT
# catch and an ``except BaseException`` does, or a call that the guard above
# it does not cover at all. An ordinary exception cannot tell those apart, so
# an ordinary exception cannot pin them - which is why the whole suite stayed
# green while each of these guards was narrowed or removed.


class _UnnameableMeta(type):
    """A metaclass that raises while resolving a class's ``__name__``.

    ``type(error).__name__`` reads like a plain attribute access and is not
    one. A metaclass may define ``__name__`` as a data descriptor, and a data
    descriptor on the metaclass wins over ``type``'s own slot - so the one
    expression ``_describe`` falls back to when the message is unavailable is
    itself user code, and it can raise for the same reason the message did.
    """

    @property
    def __name__(cls):
        raise RuntimeError("this exception's type cannot be named")


class UnnameableError(Exception, metaclass=_UnnameableMeta):
    """An exception whose type name cannot be read at all."""


class _ExitingNameMeta(type):
    """The same, raising a ``BaseException`` instead of an ``Exception``."""

    @property
    def __name__(cls):
        raise SystemExit("naming this exception's type exits the interpreter")


class ExitingNameError(Exception, metaclass=_ExitingNameMeta):
    """An exception whose type name raises a ``SystemExit`` when read."""


class ExitingMessageError(Exception):
    """An exception whose ``__str__`` raises a ``BaseException``.

    ``UnprintableError`` above raises an ordinary ``RuntimeError`` from the
    same call, and that is the difference this class exists for: an
    ``except Exception`` catches one and not the other.
    """

    def __str__(self):
        raise SystemExit("describing this exception exits the interpreter")


def assert_the_slot_is_free(registry, unhandled):
    """The wedge, asserted directly: a later job can still be started.

    Every failure below has the same consequence if it escapes - the job stays
    ``running`` for the life of the process and the one-at-a-time rule refuses
    every later start with ``JobInProgress`` naming a job that is not
    executing. Asserting the terminal state proves the caller was told;
    asserting this proves the registry is usable, which is what the user
    actually loses. ``unhandled`` empty says the worker also left by the front
    door rather than dying on the way out.
    """
    assert unhandled == [], (
        "the worker died on its way out of _run; the thread was torn down by "
        "threading.excepthook rather than returning"
    )
    assert registry.running() is None
    next_job, next_gate = start_and_enter(registry, "export")
    finish(next_job, next_gate)


def test_a_failure_whose_TYPE_CANNOT_BE_NAMED_still_publishes_the_failure(
    registry, monkeypatch, capsys
):
    """``_describe``'s last resort may not repeat the call that just failed.

    The fallback for "the message raised" was ``type(error).__name__`` - the
    very expression the attempt above it had just evaluated. An exception
    whose metaclass raises while resolving ``__name__`` therefore makes BOTH
    attempts raise, and the second one is not inside anything: it escapes
    ``_describe``, escapes the handler in ``_run`` that was building the
    terminal snapshot, and kills the worker with the job still ``running``.
    That is the wedge ``_run``'s docstring forbids in capitals, reached
    through the function whose own docstring claimed to be total.

    The failure here is an ordinary ``RuntimeError``, so this test says
    nothing about the WIDTH of any guard - only that the last resort must
    call nothing. Deleting the inner guard, or replacing the constant with
    any expression that can raise, turns this red.
    """
    unhandled = []
    monkeypatch.setattr(threading, "excepthook", unhandled.append)

    gate = Gate(raises=UnnameableError())
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.terminal is True
    assert snapshot.state == FAILED
    assert snapshot.error == jobs_module.UNDESCRIBABLE_ERROR
    assert_the_slot_is_free(registry, unhandled)
    capsys.readouterr()


def test_a_failure_whose_MESSAGE_raises_a_BaseException_still_publishes(
    registry, monkeypatch, capsys
):
    """``_describe``'s guard must be ``BaseException``, not ``Exception``.

    ``test_a_failure_that_cannot_DESCRIBE_itself_still_publishes_the_failure``
    drives the same call with an ordinary ``RuntimeError``, and an ordinary
    ``RuntimeError`` is caught by either guard - so that test stays green with
    the guard narrowed to ``except Exception``, and the whole suite did. A
    ``SystemExit`` out of ``__str__`` is the discriminator: narrowed, it
    escapes ``_describe`` mid-argument, so ``_finish`` is never called and the
    job stays ``running`` for the life of the process.

    Red here therefore means exactly "the guard around the message is wide
    enough to hold a ``BaseException``", because a ``BaseException`` from that
    call is the only thing this test changes.

    The type name still survives, which is the point of having a fallback at
    all rather than giving up on the description.
    """
    unhandled = []
    monkeypatch.setattr(threading, "excepthook", unhandled.append)

    gate = Gate(raises=ExitingMessageError())
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.terminal is True
    assert snapshot.state == FAILED
    assert snapshot.error == "ExitingMessageError"
    assert_the_slot_is_free(registry, unhandled)
    capsys.readouterr()


def test_a_failure_whose_TYPE_NAME_raises_a_BaseException_still_publishes(
    registry, monkeypatch, capsys
):
    """The fallback's own guard must be ``BaseException`` too.

    The last resort is reached only when naming the type raised, and the two
    tests above reach it with an ordinary exception. This one reaches it with
    a ``SystemExit``: the metaclass raises it, so the first attempt raises it,
    so the fallback raises it. Narrow the inner guard to ``except Exception``
    and that second ``SystemExit`` escapes exactly as the unguarded fallback
    did before it existed - the same wedge, one line further down.

    Without this test the inner guard added for
    ``test_a_failure_whose_TYPE_CANNOT_BE_NAMED_...`` would be a fresh
    ``except BaseException`` that nothing in the suite could tell from
    ``except Exception``, which is the defect this whole change is about.
    """
    unhandled = []
    monkeypatch.setattr(threading, "excepthook", unhandled.append)

    gate = Gate(raises=ExitingNameError())
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.terminal is True
    assert snapshot.state == FAILED
    assert snapshot.error == jobs_module.UNDESCRIBABLE_ERROR
    assert_the_slot_is_free(registry, unhandled)
    capsys.readouterr()


class ExitingStderr(io.StringIO):
    """A stderr whose ``write`` raises a ``BaseException``.

    The closed ``io.StringIO`` above raises ``ValueError``; this raises
    ``SystemExit`` from the same call, for the same reason as
    ``ExitingMessageError``. A stream is an arbitrary object - a GUI console
    pane, a pipe wrapper, a logging shim - and nothing constrains what its
    ``write`` may raise.
    """

    def write(self, text):
        raise SystemExit("writing to this stream exits the interpreter")


def test_a_stderr_that_raises_a_BaseException_does_not_kill_the_worker(
    registry, monkeypatch
):
    """``_report_traceback``'s guard must be ``BaseException`` too.

    THE TERMINAL STATE IS NOT THE DISCRIMINATOR HERE, and that is worth being
    explicit about. Reporting happens after publication, so the job lands
    ``failed`` whether or not this escape is caught - the assertion that
    separates the two guards is the empty ``unhandled`` list. Narrowed to
    ``except Exception``, the ``SystemExit`` from ``write`` escapes
    ``_report_traceback``, escapes ``_run`` as its last statement, and the
    worker is torn down by ``threading.excepthook`` instead of returning.

    That the record survives the escape is the useful half of the finding:
    publishing-first and guarding-the-report are two independent protections,
    not one property written twice. Each is pinned separately, here and in
    ``test_a_worker_whose_failure_cannot_be_REPORTED_still_publishes_the_failure``,
    and neither test would notice the other's guard being removed.
    """
    monkeypatch.setattr(sys, "stderr", ExitingStderr())
    unhandled = []
    monkeypatch.setattr(threading, "excepthook", unhandled.append)

    gate = Gate(raises=ValueError("ordinary work went wrong"))
    job, _ = start_and_enter(registry, gate=gate)

    snapshot = finish(job, gate)

    assert snapshot.terminal is True
    assert snapshot.state == FAILED
    assert "ordinary work went wrong" in snapshot.error
    assert_the_slot_is_free(registry, unhandled)


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


class WatchedCancelEvent(threading.Event):
    """A job's cancel event with a real reader parked at the instant of delivery.

    ``set()`` is the only moment the two writes ``request_cancel`` makes can
    be told apart from outside: the flag's publication is a plain attribute
    rebind with no hook of its own. Running a reader here answers the question
    the ordering exists for - what does somebody polling see, at the one
    instant the two orders differ?

    No deadlock: ``request_cancel`` holds the job's publication lock while
    this runs, and readers take no lock at all.
    """

    def __init__(self, job):
        super().__init__()
        self._job = job
        self.reader_saw = None
        self.reads = 0

    def set(self):
        job = self._job
        self.reads += 1
        self.reader_saw = read_from_another_thread(
            lambda: (job.snapshot().cancel_requested, job.cancel_event.is_set())
        )
        super().set()


class WatchableJob(Job):
    """A ``Job`` whose cancel event is a ``WatchedCancelEvent``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cancel = WatchedCancelEvent(self)


class RecordingJob(Job):
    """Records every snapshot this job publishes, in order.

    Publication IS a rebind of ``_state`` - the module docstring's whole
    design - so ``__setattr__`` sees every generation the job ever had,
    starting with the one built in ``__init__``. That is strictly more than a
    poller can see: a poller samples, this misses nothing.
    """

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "published", [])
        super().__init__(*args, **kwargs)

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "_state":
            self.published.append(value)


def test_a_cancel_flag_is_never_published_before_the_event_is_delivered():
    """``cancel_requested`` true must MEAN the worker's event is set.

    Both writes happen under the publication lock, and that is not enough:
    readers take no lock, so between the two writes a reader sees whichever
    has landed. With the flag published first there is a window in which the
    record says a cancel was delivered and the worker's event is still unset -
    a UI showing "Stopping..." for a run that has been told nothing.

    The other order leaves the opposite window, and it is the honest one: the
    event set with the flag not yet published means the worker may stop
    slightly before the record admits it, which understates rather than
    invents. That asymmetry is what ``request_cancel``'s docstring promises,
    and it is what is checked here.

    No worker: this is ``Job``'s own machinery, so a bare job is the whole
    subject and there is no thread to schedule around.
    """
    job = WatchableJob("j1", "export")

    snapshot = job.request_cancel()

    assert snapshot.cancel_requested is True
    assert job.cancel_event.is_set() is True

    assert job.cancel_event.reads == 1, "the reader must have run exactly once"
    flag, delivered = job.cancel_event.reader_saw
    assert delivered is False, (
        "the reader did not run inside set(); the check below would be vacuous"
    )
    assert flag is False, (
        "at the instant the cancel reached the worker's event the record "
        "already claimed it had - so a reader in that window saw "
        "cancel_requested=True for a cancel nothing had been told about"
    )


def test_a_job_publishes_exactly_one_terminal_snapshot_and_it_is_whole(
    registry, monkeypatch
):
    """One read answers everything - including the last read.

    ``PlaylistService.lookup`` had this bug: an answer assembled from two
    generations. A terminal state published in two steps is the same shape.
    A poller landing between them reads ``state=succeeded`` and
    ``terminal=True`` beside ``finished_at=None`` and ``result=None`` - a job
    that has finished, has no finish time and produced nothing - and every one
    of those fields is on the wire in ``api._job_document``.

    Checked against EVERY generation the job ever published rather than
    against a poll that happened to land in the window. A poller samples; this
    misses nothing, so the property does not depend on timing to be observed.
    """
    monkeypatch.setattr(jobs_module, "Job", RecordingJob)

    gate = Gate(result={"playlists_created": 12})
    job, _ = start_and_enter(registry, gate=gate, total=2)
    gate.reporter(1, 2, "halfway")

    snapshot = finish(job, gate)
    assert snapshot.state == SUCCEEDED

    published = list(job.published)
    assert len(published) >= 3, "running, a progress report, and the finish"

    terminal = [state for state in published if state.terminal]
    assert len(terminal) == 1, (
        f"{len(terminal)} terminal snapshots were published; a terminal state "
        "reached in two steps has an observable half-finished generation"
    )

    for state in published:
        if state.terminal:
            assert state.finished_at is not None, (
                "a finished job with no finish time was published"
            )
            assert state.result is not None, (
                "a succeeded job with no result was published"
            )
        else:
            assert state.finished_at is None
            assert state.result is None
            assert state.error is None


def test_all_returns_newest_first_when_the_timestamps_tie():
    """Registration order is reversed BEFORE the sort, and ties prove it.

    ``list.sort`` is stable, so with equal ``started_at`` the sort preserves
    whatever order it was given - registration order, oldest first, which is
    exactly backwards. Reversing first makes the tie fall the right way.

    Equal timestamps are not contrived. An injected constant clock produces
    them, and so does a coarse real one: two jobs started inside the same tick
    of ``time.time`` on a machine whose clock is not fine-grained tie in
    production too.

    ``test_all_returns_newest_first`` cannot see this - it uses the real
    clock, so the timestamps differ and the sort alone answers correctly.
    """
    registry = JobRegistry(clock=lambda: 1.0)

    first, gate = start_and_enter(registry)
    finish(first, gate)
    second, second_gate = start_and_enter(registry)
    finish(second, second_gate)

    assert first.snapshot().started_at == second.snapshot().started_at == 1.0

    assert [job.job_id for job in registry.all()] == [second.job_id, first.job_id], (
        "with equal timestamps the listing fell back to registration order, "
        "which is oldest first"
    )


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
