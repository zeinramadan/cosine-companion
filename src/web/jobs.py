#!/usr/bin/env python3
"""Background jobs: run one long operation off the request that asked for it.

Two operations cannot be answered inside an HTTP request. A full-collection
export is measured at **≈ 6.8 minutes** and a re-index at **≈ 11.5 minutes**
(docs/UI_FEATURE_INVENTORY.md:637 and §2.13). Both need three things the
request/response shape cannot give them: progress while they run, a cancel the
user can press, and survival of the request that started them.

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

#: ``(current, total, message)`` - what ``ExportService`` already calls its
#: ``progress`` argument with. ``IndexingService`` emits a richer
#: ``ProgressEvent``; ``web.api`` narrows it to this on the way through.
ProgressReporter = Callable[[int, int, str], None]


@dataclass(frozen=True)
class WorkOutcome:
    """What a job's callable returns: whether it stopped early, and its result.

    ``cancelled`` is separate from raising, because the two services disagree
    and neither is wrong. ``ExportService`` returns an ``ExportResult`` with
    ``cancelled=True`` and real counts; ``IndexingService`` raises
    ``KeyboardInterrupt`` from the pipeline's checkpoint and produces no result
    at all. ``Job._run`` accepts both and lands them in the same terminal state.
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
        """Publish the terminal snapshot. Called once, by the worker."""
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

        ``KeyboardInterrupt`` is caught first and read as a cancellation, not
        as a failure. In a worker thread it has one source - the indexing
        pipeline raises it at its per-track checkpoint when ``cancel`` is set
        (``IndexingService.run``'s docstring). CPython delivers a real Ctrl-C
        to the main thread only, so there is no other interpretation available
        here.
        """
        try:
            outcome = work(self.report_progress, self._cancel)
        except KeyboardInterrupt:
            self._finish(CANCELLED)
        except BaseException as error:  # noqa: BLE001 - see the docstring
            traceback.print_exc(file=sys.stderr)
            self._finish(FAILED, error=_describe(error))
        else:
            self._finish(
                CANCELLED if outcome.cancelled else SUCCEEDED,
                result=outcome.result,
            )


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
    """
    text = f"{type(error).__name__}: {error}".strip()
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

        The worker thread is started inside the lock as well. It does not need
        the registry lock to run - progress and completion take the *job's*
        publication lock - so there is no deadlock, and there is no window in
        which a job is registered as running with nothing running it.
        """
        with self._lock:
            for job in self._jobs.values():
                snapshot = job.snapshot()
                if not snapshot.terminal:
                    raise JobInProgress(snapshot)

            job = Job(
                job_id=self._id_factory(),
                kind=kind,
                total=total,
                message=message,
                clock=self._clock,
            )
            # Built privately, published by one rebind: a reader mid-start sees
            # either the old mapping or the whole new one.
            kept = dict(self._pruned())
            kept[job.job_id] = job
            self._jobs = MappingProxyType(kept)
            job.start(work)
            return job

    def _pruned(self) -> Mapping[str, Job]:
        """The jobs worth keeping. Caller holds ``self._lock``.

        Terminal jobs are dropped oldest-first once there are more than
        ``max_remembered``; a non-terminal job is never dropped, because the
        one-at-a-time check above is what reads it.
        """
        jobs = self._jobs
        finished = []
        live = {}
        for job_id, job in jobs.items():
            snapshot = job.snapshot()
            if snapshot.terminal:
                finished.append((snapshot.finished_at or snapshot.started_at, job_id))
            else:
                live[job_id] = job

        # Oldest first, so the tail is the newest and the head is what goes.
        # ``job_id`` breaks ties, which an injected constant clock produces.
        finished.sort()
        # One slot is left free for the job about to be added.
        keep = max(self._max_remembered - 1, 0)
        newest_kept = finished[len(finished) - keep :] if keep else []
        for _, job_id in newest_kept:
            live[job_id] = jobs[job_id]
        return live
