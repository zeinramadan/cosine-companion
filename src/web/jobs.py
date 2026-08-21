#!/usr/bin/env python3
"""Background jobs: run one long operation off the request that asked for it.

Two operations cannot be answered inside an HTTP request. A full-collection
export is measured at **≈ 6.8 minutes** and a re-index at **≈ 11.5 minutes**
(docs/UI_FEATURE_INVENTORY.md:637 and §2.13). Both need three things the
request/response shape cannot give them: progress while they run, a cancel the
user can press, and survival of the request that started them.

**One of the two ships here.** ``POST /api/jobs/export`` is in this PR; the
re-index route is not, and ``web.api``'s DEFERRED note - above ``_start`` -
says exactly why. This module is unchanged by that: it is the machinery for
both, and the parts that exist for indexing's shape rather than export's are
marked where they are and exercised directly by
tests/web/test_jobs_registry.py rather than through a route.

This module is the machinery only. It knows nothing about exports, indexes,
playlists or M3U files - a *job* here is an opaque callable plus the state
needed to watch it. ``web.api`` supplies the callables. That split is what
lets the tests below drive the whole lifecycle against a fake that returns in
microseconds, rather than against a 6.8-minute export.

WHY POLLING, AND NOT SERVER-SENT EVENTS
---------------------------------------
Nothing in this module holds a connection open. A caller reads
``GET /api/jobs/{id}`` as often as it likes and every read is an ordinary
JSON response through the one path ``server._send`` already owns. That was a
decision, and it was made against measurements rather than taste.

``server.py`` has exactly one response-emitting function, and three separate
correctness properties live in its last few lines: ``_ensure_framable``
supplies a status line for requests parsed before ``request_version`` was
trusted, ``Content-Length`` frames the body, and ``if self.command != "HEAD"``
is the *only* place a HEAD response drops its content. A streaming response
cannot use it: ``_send`` takes complete ``payload: bytes`` and sends
``Content-Length: len(payload)``. So SSE means a second emission path, and a
spike against this very server (a naive ``text/event-stream`` route added to
``_serve_api``) showed what that second path costs:

* ``HEAD /api/events`` streamed **48 bytes of ``data:`` frames** to a HEAD
  request. ``HEAD /api/health``, through ``_send``, sent 0. A body on HEAD is
  the exact defect class PR #14 closed when it moved every verb through
  ``__getattr__`` into one choke point.
* The streamed response carried **neither ``Content-Length`` nor
  ``Transfer-Encoding``**, so on HTTP/1.1 it is framed only by connection
  close (RFC 9112 §6.3) - and the handler never closes. A keep-alive probe
  read the event frames and then the *next* response's status line glued onto
  the end of them, which is the desynchronisation ``_read_json_body``'s
  ``close_connection`` handling and ``_ensure_framable`` both exist to prevent.
* ``CocoServer.stop()`` returned in 51 ms but left the streaming handler
  thread running against a closed server.

Every one of those is fixable - by reimplementing HEAD elision, framing and
chunked encoding in the new path. That is the "no new door" constraint failing
on its own terms: the value of one choke point is that there is one.

Against that, what polling costs a single local user: one small JSON GET per
interval on a loopback socket, on a job whose progress advances a few times a
second. Sub-second staleness on a seven-minute operation is not perceptible,
a poll re-attaches after a page reload with no replay logic, and a cancel is
already a POST on the same path. Polling is not the compromise here; it is the
cheaper answer to the question actually being asked.

HOW THE SHARED STATE IS KEPT SAFE
---------------------------------
Job state is read by request threads (``ThreadingHTTPServer`` gives each
request its own) and written by the worker thread. This codebase has paid for
that mistake four times, so the shape is copied rather than invented:
``PlaylistService._Generation`` and ``LibrarySession``'s four-file generation
both **build privately and publish by rebinding one immutable reference**, and
so does ``Job``.

* Everything observable about a job is one frozen ``JobSnapshot``. There is no
  such thing as a half-updated job, because a snapshot is never updated - it is
  replaced.
* Writers serialise on ``Job._publish_lock`` because there are two of them (the
  worker reporting progress and finishing, a request thread requesting a
  cancel) and each does a read-modify-write. Readers take **no** lock: one
  attribute read yields the whole answer.
* ``JobSnapshot.result`` is a ``MappingProxyType`` for the same reason
  ``_Generation.by_track`` is - so "never changes" is enforced rather than
  promised while other threads are still reading it.

The rule ``PlaylistService.lookup`` was rewritten for applies here too: a
reader takes **one** snapshot at the top of its call and answers every part of
the question from that one reference. ``api._job_document`` is written that
way, and ``JobRegistry`` hands back ``Job`` objects rather than fields so
there is nothing else for a caller to re-read.

ONE JOB AT A TIME
-----------------
``JobRegistry.start`` refuses to start a second job while one is running, and
the refusal is a check-and-insert inside a single lock rather than a check
followed by an insert. The reasons are in ``JobRegistry.start``'s docstring;
the enforcement is ``JobInProgress``, which ``web.api`` turns into a 409
naming the job already running.
"""

import secrets
import sys
import threading
import time
import traceback
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Tuple

#: A job is in exactly one of these. ``running`` is the only non-terminal one.
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL_STATES = frozenset({SUCCEEDED, FAILED, CANCELLED})

#: How many finished jobs a registry keeps so a reloaded page can still read a
#: result it missed. Running jobs are never evicted. Eight is arbitrary but
#: bounded, which is the property that matters: a window left open for a day
#: must not accumulate job records without limit.
MAX_REMEMBERED_JOBS = 8

#: An error message longer than this is truncated before it is stored. A
#: pandas or numpy exception can carry a repr of an entire frame, and the job
#: record is read by a UI that has to render it.
MAX_ERROR_CHARACTERS = 500

#: What ``_describe`` returns for an exception that can be neither printed nor
#: named. A literal, because it is the LAST resort: anything computed here
#: could raise in turn, and there is nothing after it left to catch that.
UNDESCRIBABLE_ERROR = "an error that cannot be described"

#: ``(current, total, message)`` - what ``ExportService`` already calls its
#: ``progress`` argument with, and the only producer wired up in this PR.
#: ``IndexingService`` emits a richer ``ProgressEvent`` with a phase; the
#: deferred re-index caller will narrow it to these three on the way
#: through rather than widening every job record for one producer.
ProgressReporter = Callable[[int, int, str], None]


@dataclass(frozen=True)
class WorkOutcome:
    """What a job's callable returns: whether it stopped early, and its result.

    ``cancelled`` is separate from raising, because the two services disagree
    and neither is wrong. ``ExportService`` returns an ``ExportResult`` with
    ``cancelled=True`` and real counts; ``IndexingService`` raises
    ``KeyboardInterrupt`` from the pipeline's checkpoint and produces no result
    at all. ``Job._run`` accepts both and lands them in the same terminal
    state. Only the first is reached through a route in this PR - the
    re-index is deferred, see ``web.api``'s DEFERRED note - and the second
    is exercised directly by tests/web/test_jobs_registry.py, which is the
    machinery's own reachable path: ``work`` is an arbitrary callable.
    """

    cancelled: bool
    result: Mapping[str, Any]


@dataclass(frozen=True)
class JobSnapshot:
    """One whole answer about one job, captured together.

    Frozen and published by a single rebind - see the module docstring. Every
    field a caller can observe is here, so a reader that holds one of these
    cannot compose an answer from two generations.
    """

    job_id: str
    kind: str
    state: str
    current: int
    total: int
    message: str
    started_at: float
    finished_at: Optional[float]
    #: True once a cancel has been *delivered* to the worker's event. It stays
    #: true in the terminal snapshot, which is what makes the "cancelled too
    #: late to matter" case legible rather than invisible: a job can finish
    #: ``succeeded`` with ``cancel_requested`` true, and that is precisely
    #: inventory defect #17 (a cancel set after the pipeline's last checkpoint
    #: is never observed and the run completes).
    cancel_requested: bool
    result: Optional[Mapping[str, Any]]
    error: Optional[str]

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


class JobInProgress(Exception):
    """Raised by ``JobRegistry.start`` when a job is already running.

    Carries the running job's snapshot so the caller can name it. A bare
    "busy" would leave the user with a button that does nothing and no way to
    find out which operation is holding the lock.
    """

    def __init__(self, running: JobSnapshot):
        super().__init__(f"the {running.kind} job {running.job_id} is still running")
        self.running = running


def _new_job_id() -> str:
    """A per-process job id.

    Random rather than a counter on purpose. Ids live only as long as the
    process, so a UI still polling ``/api/jobs/j1`` across an app restart would
    be handed a *different* job under a reused id; a random id 404s instead,
    which is the true answer. Not a security property - every job route is
    already behind the server's token.
    """
    return secrets.token_urlsafe(9)


class Job:
    """One background operation and everything observable about it."""

    def __init__(
        self,
        job_id: str,
        kind: str,
        total: int = 0,
        message: str = "",
        clock: Callable[[], float] = time.time,
    ):
        self.job_id = job_id
        self.kind = kind
        self._clock = clock
        self._cancel = threading.Event()
        #: Serialises the two writers. Readers never take it; see the module
        #: docstring. Held only across a ``replace`` and one rebind.
        self._publish_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        #: The one reference. Rebound, never mutated.
        self._state = JobSnapshot(
            job_id=job_id,
            kind=kind,
            state=RUNNING,
            current=0,
            total=total,
            message=message,
            started_at=clock(),
            finished_at=None,
            cancel_requested=False,
            result=None,
            error=None,
        )

    # -- reading -----------------------------------------------------------

    def snapshot(self) -> JobSnapshot:
        """The whole job, in one lock-free read.

        Callers must take this **once** and read every field from the returned
        object. Re-reading ``job.snapshot()`` per field is the bug
        ``PlaylistService.lookup`` was rewritten to make impossible.
        """
        return self._state

    @property
    def cancel_event(self) -> threading.Event:
        """The event both services duck-type as ``cancel`` via ``.is_set()``."""
        return self._cancel

    # -- writing -----------------------------------------------------------

    def _publish(self, **changes) -> JobSnapshot:
        """Replace the snapshot under the writer lock. Returns the new one."""
        with self._publish_lock:
            self._state = replace(self._state, **changes)
            return self._state

    def report_progress(self, current: int, total: int, message: str) -> None:
        """The ``progress`` callback both services are handed.

        A report that arrives after the job is terminal is dropped rather than
        resurrecting it. Neither service does that today - both call progress
        synchronously from the thread that later returns - but a terminal state
        that can be walked back is not a terminal state.
        """
        with self._publish_lock:
            if self._state.terminal:
                return
            self._state = replace(
                self._state,
                current=int(current),
                total=int(total),
                message=str(message),
            )

    def request_cancel(self) -> JobSnapshot:
        """Ask the worker to stop. Idempotent; safe after the job has finished.

        The event is set **before** ``cancel_requested`` is published, and both
        happen under the lock that ``_finish`` also takes. That ordering is
        what makes the flag honest in both directions:

        * a snapshot with ``cancel_requested`` true means the worker's event
          really is set, never that it is about to be;
        * a job that finishes first stays finished - the terminal state is not
          overwritten - and the cancel is reported as not delivered.
        """
        with self._publish_lock:
            if self._state.terminal:
                return self._state
            self._cancel.set()
            self._state = replace(self._state, cancel_requested=True)
            return self._state

    def _finish(
        self,
        state: str,
        result: Optional[Mapping[str, Any]] = None,
        error: Optional[str] = None,
    ) -> JobSnapshot:
        """Publish the terminal snapshot. Called once, by the worker.

        KNOWN LIMIT, DELIBERATELY NOT CLOSED HERE. Every call to this sits
        OUTSIDE ``_run``'s outer guard - two in its handlers, one in its
        ``else``, and a ``try`` covers neither. So a ``clock`` that raises on
        this line escapes ``_run`` with nothing published at all: a clock
        that returns once for ``started_at`` and raises for ``finished_at``
        leaves the job ``running`` for good, one ``threading.excepthook``
        call, and every later job refused with ``JobInProgress`` - exactly
        the wedge the ordering above is built to prevent, reached from the
        one call the ordering does not cover. It stays open because of its
        precondition, not because it is harmless: ``JobRegistry`` is
        constructed with ``time.time``, so getting here needs a test seam
        that fails on purpose or an environmental failure of that shape.
        Closing it means publishing without asking a clock, or guarding the
        publication itself - a change to behaviour, and so its own change.
        """
        return self._publish(
            state=state,
            finished_at=self._clock(),
            result=None if result is None else MappingProxyType(dict(result)),
            error=error,
        )

    # -- running -----------------------------------------------------------

    def start(self, work: Callable[[ProgressReporter, threading.Event], WorkOutcome]):
        """Run ``work`` on a daemon thread.

        ``daemon=True`` for the reason ``server._ThreadingServer`` gives for
        its own: a job that hangs must not keep the window's process alive
        after the window is gone.
        """
        self._thread = threading.Thread(
            target=self._run,
            args=(work,),
            name=f"coco-job-{self.job_id}",
            daemon=True,
        )
        self._thread.start()

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._thread

    def _run(self, work) -> None:
        """Run the work and land the job in exactly one terminal state.

        NOTHING MAY ESCAPE THIS FUNCTION. A worker that dies without
        publishing leaves the job ``running`` for the life of the process, and
        because only one job runs at a time that wedges every later job behind
        a job that is not executing. That is why the second handler catches
        ``BaseException`` and not ``Exception``: a ``SystemExit`` raised in a
        worker thread otherwise ends the thread silently, which is exactly the
        wedge described.

        And it is why nothing between entering that handler and publishing may
        raise. Two things there could, and a review found the first of them
        doing it: ``traceback.print_exc(file=sys.stderr)`` ran BEFORE the
        publication and raises ``ValueError`` on a closed stderr, so ordinary
        work raising an ordinary ``ValueError`` produced the wedge above; and
        ``_describe`` calls the exception's own ``__str__``, which is user
        code. Reporting a failure now happens after it is published and cannot
        prevent it (``_report_traceback``), and describing one always returns
        (``_describe``).

        THE WIDTH OF EVERY GUARD ON THIS PATH IS PART OF THE PROPERTY rather
        than a matter of taste, and it is the part that kept slipping.
        ``_describe`` and ``_report_traceback`` each swallow ``BaseException``
        for this function's own reason, and each was measured surviving the
        whole suite green when narrowed to ``Exception``: an ordinary
        exception is caught by either, so an ordinary exception cannot tell
        them apart and cannot pin one. The tests that separate them drive a
        ``SystemExit`` out of ``__str__``, out of ``type(...).__name__``, and
        out of ``sys.stderr.write``.

        AND THE SUCCESS PATH READS USER CODE TOO. ``outcome.cancelled`` and
        ``outcome.result`` are attributes of whatever ``work`` returned, which
        is exactly as unconstrained as ``work``; they were read in the
        ``else:`` below, and the ``else:`` of a ``try`` is not covered by its
        handlers. A callable that forgot to ``return`` therefore wedged the
        registry with an ``AttributeError`` while nominally succeeding, which
        is the least expected door into this room. Both reads are inside the
        ``try`` now.

        ``KeyboardInterrupt`` is caught first and read as a cancellation, not
        as a failure. In a worker thread it has one source - the indexing
        pipeline raises it at its per-track checkpoint when ``cancel`` is set
        (``IndexingService.run``'s docstring). CPython delivers a real Ctrl-C
        to the main thread only, so there is no other interpretation available
        here. The re-index route that would deliver it is deferred out of this
        PR (see ``web.api``'s DEFERRED note); the branch is not defensive
        padding for that reason - ``work`` is any callable, and
        tests/web/test_jobs_registry.py raises it through the real ``start``
        path, so deleting the branch turns that test red.
        """
        try:
            outcome = work(self.report_progress, self._cancel)
            # READ HERE, INSIDE THE GUARD, AND NOT IN THE ``else`` BELOW.
            # Whatever ``work`` returned is user code as much as its body
            # was: ``cancelled`` may be a property that raises, ``result`` a
            # mapping whose ``keys()`` raises under ``_finish``'s ``dict()``,
            # and a callable that falls off its end returns ``None``, whose
            # ``.cancelled`` raises ``AttributeError``. The ``else`` of a
            # ``try`` is NOT covered by its handlers, so read there any of
            # those escaped ``_run`` and wedged the registry from the
            # SUCCESS path. The ``else`` now publishes values already plain.
            state = CANCELLED if outcome.cancelled else SUCCEEDED
            result = None if outcome.result is None else dict(outcome.result)
        except KeyboardInterrupt:
            self._finish(CANCELLED)
        except BaseException as error:  # noqa: BLE001 - see the docstring
            # PUBLICATION FIRST, REPORTING SECOND, and the order is the
            # whole point. The traceback used to be written here, before
            # the terminal snapshot - and ``print_exc`` raises when stderr
            # is closed, which is the state of a frozen windowed build with
            # no console. Ordinary work raising an ordinary ValueError then
            # killed the worker with the job still ``running``, wedging
            # every later job behind it. Telling the developer about a
            # failure must not be able to stop the caller being told.
            self._finish(FAILED, error=_describe(error))
            _report_traceback()
        else:
            self._finish(state, result=result)


def _report_traceback() -> None:
    """Put the failure's traceback in front of a developer, or give up quietly.

    Called AFTER the terminal snapshot is published, and its own failure is
    swallowed, because there is by definition nowhere left to write one: the
    thing that failed IS the writing. ``sys.exc_info()`` is still the
    worker's exception here - the handler this is called from has not
    exited - so ``print_exc`` prints what it always did, and
    ``test_a_worker_that_raises_lands_the_job_in_failed_with_the_message``
    still reads it off stderr.

    ``BaseException`` rather than ``Exception``, for ``_run``'s own reason:
    the point is that NOTHING gets past this line, and a stream object is
    free to raise whatever it likes.
    """
    try:
        traceback.print_exc(file=sys.stderr)
    except BaseException:  # noqa: BLE001 - see the docstring
        pass


def _describe(error: BaseException) -> str:
    """The message a job failure shows the user, truncated.

    Deliberately more informative than ``server._serve_api``'s generic 500,
    and the difference is reasoned rather than accidental. That 500 hides an
    exception because a traceback from a *read* can leak a filesystem path or
    a track title into a response the caller never asked about. A job failure
    is the opposite situation: the user chose the output directory, the
    failure is almost always about it ("Permission denied",
    "No such file or directory"), and an opaque message makes a seven-minute
    export failure undiagnosable. The traceback still goes to stderr for the
    developer; only the type and the message go to the client, over the same
    token-authenticated loopback socket every other response uses.

    TOTAL - AND THE CONSTRUCTION IS THE BODY BELOW, NOT THIS SENTENCE. It is
    called while building the terminal snapshot, so it must return for every
    argument or the job never lands. An earlier version claimed exactly that
    here while its fallback re-evaluated, unguarded, the expression that had
    just raised, which is the difference between a property and a note saying
    there is one. Three things make it true now: every call that can raise is
    inside a guard; a handler may repeat the call it is handling, but only
    under a guard of its own, so the repeats are a short finite chain and not
    a way out; and the innermost handler calls nothing at all - it binds a
    constant. That middle clause is worded that way because it has to be: the
    fallback below does re-read ``type(error).__name__``, so when that read is
    what raised, it is attempted a second time and a descriptor that raises
    every time raises there too. What changed is not that the repeat went
    away but that it landed in a guard. Each branch binds a
    ``str`` - ``f"..."`` and ``str()`` return one or raise - so the truncation
    below cannot raise either.
    """
    # ``{error}`` calls the exception's own ``__str__``, which is ordinary
    # user code and can raise. Losing the message is a poor outcome; losing
    # the terminal snapshot this string is being built for is the wedge
    # ``_run``'s docstring forbids, so the type name is what survives.
    try:
        text = f"{type(error).__name__}: {error}".strip()
    except BaseException:  # noqa: BLE001 - see above
        # THE FALLBACK DOES REPEAT THE CALL THAT JUST FAILED, AND MAY ONLY
        # DO SO UNDER A GUARD OF ITS OWN WITH A CONSTANT BEHIND IT.
        # ``type(error).__name__`` reads like a plain attribute access and is
        # not one: a metaclass may define ``__name__`` as a data descriptor,
        # and a data descriptor on the metaclass wins over ``type``'s own
        # slot. An exception whose metaclass raises there made the attempt
        # above raise, and this line reads the name a second time - so a
        # descriptor that raises every time raises here too. Before the guard
        # below existed, that second raise went out of a function that had
        # just promised to return, into the handler building the terminal
        # snapshot, and the job never landed. The repeat is deliberate: the
        # type name is the only thing left worth salvaging, and the only way
        # to avoid re-reading it is to give it up. So it is attempted under
        # its own guard, and what follows it calls nothing: it is a constant.
        try:
            text = str(type(error).__name__)
        except BaseException:  # noqa: BLE001 - see above
            text = UNDESCRIBABLE_ERROR
    if len(text) > MAX_ERROR_CHARACTERS:
        text = text[: MAX_ERROR_CHARACTERS - 1] + "…"
    return text


class JobRegistry:
    """The jobs this process knows about, and the one-at-a-time rule."""

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = _new_job_id,
        max_remembered: int = MAX_REMEMBERED_JOBS,
    ):
        """Hold no jobs. Injectable clock and id factory so tests are exact."""
        self._clock = clock
        self._id_factory = id_factory
        self._max_remembered = max_remembered
        self._lock = threading.Lock()
        #: One immutable mapping, rebound on every change. Readers take one
        #: reference; see the module docstring.
        self._jobs: Mapping[str, Job] = MappingProxyType({})

    # -- reading -----------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        """The job with this id, or ``None``. One read, no lock."""
        return self._jobs.get(job_id)

    def all(self) -> Tuple[Job, ...]:
        """Every remembered job, newest first. One read, no lock.

        Registration order is reversed *before* the sort so that jobs sharing a
        timestamp - which an injected constant clock produces, and a coarse
        real one can too - still come back most-recently-started first rather
        than in whatever order a stable sort left them.
        """
        newest_first = list(reversed(list(self._jobs.values())))
        newest_first.sort(key=lambda job: job.snapshot().started_at, reverse=True)
        return tuple(newest_first)

    def running(self) -> Optional[JobSnapshot]:
        """The running job's snapshot, or ``None``. One read per job."""
        for job in self._jobs.values():
            snapshot = job.snapshot()
            if not snapshot.terminal:
                return snapshot
        return None

    # -- writing -----------------------------------------------------------

    def start(
        self,
        kind: str,
        work: Callable[[ProgressReporter, threading.Event], WorkOutcome],
        total: int = 0,
        message: str = "",
    ) -> Job:
        """Start ``work`` as a job, or raise ``JobInProgress``.

        ONE AT A TIME, AND WHY
        ----------------------
        Both operations this exists for write into the same data directory and
        saturate the same machine. A re-index rewrites the index generation
        that an export is reading; ``LibrarySession``'s snapshot semantics mean
        the export would then finish against a view of the library that no
        longer exists, silently (inventory defect #1's residue). Two exports
        into one output directory interleave their writes. And two CPU-bound
        runs on a laptop do not finish sooner than two sequential ones - they
        finish later, both of them. There is no case where a second concurrent
        job is what the user wanted.

        ENFORCED, NOT ASSUMED
        ---------------------
        The check and the insert are inside **one** acquisition of
        ``self._lock``. Split into "is anything running?" then "register mine",
        two request threads arriving together both see nothing running and both
        start - which is the non-atomic shape this codebase has already paid
        for four times. Each candidate job is read with a single
        ``snapshot()``, so the decision is made against one generation per job
        rather than a field at a time.

        The worker thread is started inside the lock as well, and **before**
        the registry is rebound. It does not need the registry lock to run -
        progress and completion take the *job's* publication lock - so there
        is no deadlock. Starting before publishing is what makes the claim
        'no job is registered as running with nothing running it' true: a
        reader either does not find the job at all or finds one that already
        has a thread, and a start that raises publishes nothing to roll back.
        Pinned by ``test_no_reader_can_find_a_job_before_its_worker_exists``
        and ``test_a_job_whose_thread_cannot_start_leaves_no_record_behind``,
        which reads the registry from a real second thread at the one instant
        the two orders differ.
        """
        with self._lock:
            # ONE pass, and ONE snapshot per job, feeding BOTH decisions this
            # block makes - whether to refuse, and what to keep. Reading each
            # job twice would be two generations answering one question, which
            # is the shape ``PlaylistService.lookup`` was rewritten to remove.
            finished = []
            for job_id, existing in self._jobs.items():
                snapshot = existing.snapshot()
                if not snapshot.terminal:
                    raise JobInProgress(snapshot)
                finished.append((snapshot.finished_at or snapshot.started_at, job_id))

            # Only reachable once every remembered job is terminal, because the
            # loop above returns rather than falls through otherwise. That is
            # what makes "a running job is never evicted" a property of the
            # structure rather than a defensive branch nothing can reach - an
            # earlier draft had the branch, and a mutation that deleted it left
            # every test green.
            #
            # Oldest first, so the head is what goes. ``job_id`` breaks ties,
            # which an injected constant clock produces.
            finished.sort()
            keep = max(self._max_remembered - 1, 0)  # one slot for the new job
            newest = finished[len(finished) - keep :] if keep else []
            # Built privately, published by one rebind: a reader mid-start sees
            # either the old mapping or the whole new one.
            kept = {job_id: self._jobs[job_id] for _, job_id in newest}

            job = Job(
                job_id=self._id_factory(),
                kind=kind,
                total=total,
                message=message,
                clock=self._clock,
            )
            kept[job.job_id] = job

            # STARTED FIRST, PUBLISHED SECOND. Readers take no registry
            # lock - that is what makes a poll cheap - so the lock held
            # here buys nothing against them: whatever is in ``_jobs`` is
            # visible the instant it is rebound. Published first, a reader
            # could find a ``running`` job whose ``thread`` was still
            # ``None``, and a ``Thread.start`` that raised (which it does
            # when the process is out of threads) left that record
            # registered for good, refusing every later job.
            #
            # This order needs no rollback, which is the point: if the
            # start raises, nothing was published and the registry is
            # exactly as it was. The worker cannot notice the difference -
            # it touches only the job's own publication lock, never the
            # registry - so it may finish before it is registered and the
            # record it publishes is still the whole truth about it.
            job.start(work)
            self._jobs = MappingProxyType(kept)
            return job
