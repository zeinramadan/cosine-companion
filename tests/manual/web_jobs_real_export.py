#!/usr/bin/env python3
"""The job machinery over the REAL library, through the real HTTP server.

Not collected by pytest. ``tests/web/test_jobs_real_export.py`` runs the same
code against the committed fourteen-track fixture and gates every merge; this
runs it at real size - a 1,500-track library, the real ``ExportService``, the
real ``CocoServer`` and an HTTP client - so the claim "this works at real
size" has something behind it.

READ ONLY. The library is opened with ``LibrarySession.load`` and never
mutated; the export writes into a temporary directory that is removed at the
end. Every content file under ``data/`` is fingerprinted (size, mtime,
sha256) before and after, and a difference is a failure, not a warning. See
``fingerprint`` for the one file that is checked separately and why.

    PYTHONPATH=src python tests/manual/web_jobs_real_export.py
    PYTHONPATH=src python tests/manual/web_jobs_real_export.py --seeds 5

What it checks, in order:

1. a full-library export starts, is refused a second time (409), reports real
   progress, and is cancelled part-way;
2. the playlists written before the cancel are still on disk and complete,
   and the job's terminal record's counts match what is really there;
3. a small export runs to completion and its record matches the directory;
4. the poll endpoint's cost is measured, because "polling is cheap enough"
   was an argument and arguments should be checkable;
5. every content file under ``data/`` is byte-identical to what it was
   before (the index lock file excepted, and explained, in ``fingerprint``).
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

from core.index_store import INDEX_LOCK_FILENAME  # noqa: E402
from services.export_service import ExportService  # noqa: E402
from services.library_session import LibrarySession  # noqa: E402
from services.settings_store import SettingsStore  # noqa: E402
from web import assets  # noqa: E402
from web.api import CocoApi  # noqa: E402
from web.server import CocoServer  # noqa: E402

WAIT = 600.0
RECOMMENDATIONS_PER_TRACK = 10

failures = []


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    if not condition:
        failures.append(label)
    print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
    return condition


def fingerprint(directory):
    """Size, mtime and sha256 of every content file under ``directory``.

    ``.library-index.lock`` is excluded and checked separately. It is created
    by ``core.index_store._index_lock`` - the *shared read* lock every
    ``LibrarySession.load`` takes (``index_store.py:377``) - so merely opening
    a library creates it, on ``origin/main`` as much as here. Folding it into
    this comparison would report "the library was modified" for every
    read-only run. It is still checked, because a lock file that has grown
    content would mean something else entirely.
    """
    record = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != INDEX_LOCK_FILENAME:
            stat = path.stat()
            record[str(path.relative_to(directory))] = (
                stat.st_size,
                stat.st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return record


class Client:
    """Minimal token-carrying HTTP client, stdlib only."""

    def __init__(self, server):
        import http.client

        self._http = http.client
        self.host, self.port = server.socket_address
        self.token = server.token

    def request(self, method, path, payload=None):
        connection = self._http.HTTPConnection(self.host, self.port, timeout=30)
        try:
            headers = {"X-Coco-Token": self.token}
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload).encode("utf-8")
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else None
        finally:
            connection.close()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, payload):
        return self.request("POST", path, payload)


class GatedExportService(ExportService):
    """The real service, with a hook that lets the harness stop mid-run.

    The hook wraps the *progress callback*, which is the real one the exporter
    calls per seed. Nothing about the export itself is simulated: the ranking,
    the file writes and the cancel check are the shipping code.
    """

    def __init__(self, library, pause_at=None):
        super().__init__(library)
        self.pause_at = pause_at
        self.reached = threading.Event()
        self.may_continue = threading.Event()

    def export_per_seed(self, track_ids, out_dir, per_track, progress=None, cancel=None):
        def hooked(current, total, message):
            if progress is not None:
                progress(current, total, message)
            if self.pause_at is not None and current == self.pause_at:
                self.reached.set()
                if not self.may_continue.wait(timeout=WAIT):
                    raise AssertionError("the harness never released the export")

        return super().export_per_seed(
            track_ids, out_dir, per_track, progress=hooked, cancel=cancel
        )


def wait_for_terminal(client, job_id, timeout=WAIT):
    """Poll until the job is terminal. Bounded, and it sleeps rather than spins."""
    deadline = time.monotonic() + timeout
    polls = 0
    while time.monotonic() < deadline:
        status, body = client.get(f"/api/jobs/{job_id}")
        polls += 1
        assert status == 200, body
        if body["job"]["state"] != "running":
            return body["job"], polls
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached a terminal state")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=5, help="seeds for the small run")
    parser.add_argument("--pause-at", type=int, default=3, help="cancel after N seeds")
    arguments = parser.parse_args()

    data_dir = REPO / "data"
    if not data_dir.is_dir():
        print(f"no library at {data_dir}", file=sys.stderr)
        return 2

    print(f"library      {data_dir}")
    before = fingerprint(data_dir)
    print(f"fingerprint  {len(before)} files")

    library = LibrarySession.load(data_dir)
    settings = SettingsStore(data_dir / "settings.json")
    track_ids = [str(track_id) for track_id in library.meta_ix.index]
    print(f"tracks       {len(track_ids)}")

    out_root = Path(tempfile.mkdtemp(prefix="coco-jobs-manual-"))
    print(f"output       {out_root}\n")

    exports = GatedExportService(library, pause_at=arguments.pause_at)
    api = CocoApi(library, settings, export_service_factory=lambda _: exports)
    server = CocoServer(api, assets.static_dir())
    server.start()
    client = Client(server)

    try:
        # -- 1. a full-library export, cancelled part-way -------------------
        print("1. full-library export, cancelled part-way")
        cancel_dir = out_root / "cancelled"
        status, started = client.post(
            "/api/jobs/export",
            {"out_dir": str(cancel_dir), "recommendations_per_track": RECOMMENDATIONS_PER_TRACK},
        )
        check("start is 202", status == 202, f"got {status}")
        job = started["job"]
        job_id = job["id"]
        check(
            "the whole library is the default seed set",
            job["progress"]["total"] == len(track_ids),
            f"{job['progress']['total']} vs {len(track_ids)}",
        )

        status, refused = client.post(
            "/api/jobs/export", {"out_dir": str(out_root / "second")}
        )
        check("a second job is refused with 409", status == 409, f"got {status}")
        check(
            "the refusal names the running job",
            refused and job_id in refused["error"]["message"],
        )

        check(
            f"the export reached seed {arguments.pause_at}",
            exports.reached.wait(timeout=WAIT),
        )
        status, polled = client.get(f"/api/jobs/{job_id}")
        check(
            "progress is visible while it runs",
            polled["job"]["progress"]["current"] == arguments.pause_at,
            f"current={polled['job']['progress']['current']}",
        )
        check(
            "the progress message names a track",
            " - " in polled["job"]["progress"]["message"],
            polled["job"]["progress"]["message"],
        )

        status, cancelled = client.post(f"/api/jobs/{job_id}/cancel", {})
        check("cancel is 200", status == 200, f"got {status}")
        check("cancel is recorded", cancelled["job"]["cancel_requested"] is True)
        exports.may_continue.set()

        final, polls = wait_for_terminal(client, job_id)
        check("the cancelled job is terminal", final["state"] == "cancelled", final["state"])
        result = final["result"]
        check("the record says it was cancelled", result["cancelled"] is True)

        # -- 2. what the cancel left on disk --------------------------------
        print("\n2. partial results on disk")
        written = sorted(cancel_dir.glob("*.m3u"))
        check("playlists survived the cancel", len(written) > 0, f"{len(written)} files")
        check(
            "the record's count matches the directory",
            result["playlists_created"] == len(written),
            f"record {result['playlists_created']} vs disk {len(written)}",
        )
        check(
            "the record names where they are",
            result["output"] == str(cancel_dir),
        )
        check(
            "far short of the whole library, as expected of a cancel",
            len(written) < len(track_ids),
            f"{len(written)} of {len(track_ids)}",
        )
        complete = [
            path
            for path in written
            if path.read_text(encoding="utf-8").startswith("#EXTM3U")
        ]
        check(
            "every surviving playlist is complete",
            len(complete) == len(written),
            f"{len(complete)}/{len(written)}",
        )

        # -- 3. a small export that runs to completion ----------------------
        print("\n3. a small export, run to completion")
        exports.pause_at = None
        small_dir = out_root / "small"
        seeds = track_ids[: arguments.seeds]
        began = time.monotonic()
        status, started = client.post(
            "/api/jobs/export",
            {
                "out_dir": str(small_dir),
                "track_ids": "\n".join(seeds),
                "recommendations_per_track": RECOMMENDATIONS_PER_TRACK,
            },
        )
        check("start is 202", status == 202, f"got {status}")
        done, polls = wait_for_terminal(client, started["job"]["id"])
        elapsed = time.monotonic() - began
        check("it succeeded", done["state"] == "succeeded", done["state"])
        on_disk = sorted(small_dir.glob("*.m3u"))
        check(
            "one playlist per seed",
            done["result"]["playlists_created"] == len(on_disk) == len(seeds),
            f"record {done['result']['playlists_created']}, disk {len(on_disk)}, seeds {len(seeds)}",
        )
        print(f"       {len(seeds)} seeds in {elapsed:.2f}s ({polls} polls)")

        # -- 4. what a poll costs -------------------------------------------
        print("\n4. the cost of one poll")
        samples = 200
        began = time.monotonic()
        for _ in range(samples):
            client.get(f"/api/jobs/{started['job']['id']}")
        per_poll = (time.monotonic() - began) / samples
        print(f"       {per_poll * 1000:.2f} ms per GET /api/jobs/{{id}} over {samples} calls")
        check(
            "a poll is cheap enough to do several times a second",
            per_poll < 0.05,
            f"{per_poll * 1000:.2f} ms",
        )

        # -- 5. the library is untouched ------------------------------------
        print("\n5. the real library")
        after = fingerprint(data_dir)
        check(
            "every data/ content file is byte-identical",
            after == before,
            _describe_diff(before, after),
        )
        lock = data_dir / INDEX_LOCK_FILENAME
        check(
            "the index lock is empty (it is a flock target, not a store)",
            not lock.exists() or lock.stat().st_size == 0,
            f"{lock.stat().st_size} bytes" if lock.exists() else "absent",
        )

    finally:
        server.stop()
        shutil.rmtree(out_root, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


def _describe_diff(before, after):
    if before == after:
        return f"{len(before)} files unchanged"
    changed = sorted(set(before) ^ set(after)) or [
        name for name in before if before[name] != after.get(name)
    ]
    return f"changed: {changed}"


if __name__ == "__main__":
    sys.exit(main())
