#!/usr/bin/env python3
"""Run real Essentia indexing through the shipping web job API.

This is deliberately a manual harness: it reads real track metadata and audio,
loads the real Discogs-EffNet model, and can take minutes. Every write is bound
to a temporary data directory. The source library is fingerprinted before and
after so a mistaken global-path write is a failure.

    COCO_MODELS=/path/to/models PYTHONPATH=src python tests/manual/real_indexing.py 4
"""

import hashlib
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote


REPO = Path(os.environ.get("COCO_REPO", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO / "src"))

import pandas as pd  # noqa: E402

import processing.embeddings as embeddings_module  # noqa: E402
from services.library_session import LibrarySession  # noqa: E402
from services.settings_store import SettingsStore, XML_PATH_KEY  # noqa: E402
from web.api import CocoApi  # noqa: E402
from web.jobs import CANCELLED, RUNNING, SUCCEEDED  # noqa: E402


embeddings_module.MODELS = Path(
    os.environ.get("COCO_MODELS", REPO / "models")
)

WAIT_SECONDS = 900.0
INDEX_FILES = ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json")
FAILURES = []


def expect(condition, label, detail=""):
    mark = "PASS" if condition else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        FAILURES.append(label)


def fingerprint(directory):
    """Size, mtime, and sha256 for every content file in ``directory``."""
    record = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            stat = path.stat()
            record[str(path.relative_to(directory))] = (
                stat.st_size,
                stat.st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return record


def write_xml(path, rows):
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(rows)))
    for row in rows.itertuples():
        ET.SubElement(
            collection,
            "TRACK",
            TrackID=str(row.track_id),
            Name=str(row.title),
            Artist=str(row.artist),
            AverageBpm=f"{row.bpm:.2f}",
            Tonality=str(row.key),
            Album="",
            Location="file://localhost" + quote(str(row.path_local), safe="/"),
        )
    ET.SubElement(root, "PLAYLISTS")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def api_for(data_dir, xml_path):
    settings = SettingsStore(data_dir / "settings.json")
    settings.set(XML_PATH_KEY, str(xml_path))
    return CocoApi(LibrarySession(data_dir), settings)


def read_job(api, job_id):
    status, body = api.handle("GET", f"/api/jobs/{job_id}", {})
    assert status == 200, body
    return body["job"]


def wait_for_terminal(api, job_id, *, on_progress=None):
    deadline = time.monotonic() + WAIT_SECONDS
    last_progress = None
    while time.monotonic() < deadline:
        job = read_job(api, job_id)
        progress = job["progress"]
        marker = (progress["current"], progress["total"], progress["message"])
        if marker != last_progress:
            print(f"    {progress['message']}")
            last_progress = marker
        if on_progress is not None:
            on_progress(job)
        if job["state"] != RUNNING:
            return job
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish within {WAIT_SECONDS}s")


def start_reindex(api):
    status, body = api.handle(
        "POST", "/api/jobs/reindex", {}, {"force_full": False}
    )
    assert status == 202, body
    return body["job"]["id"]


def complete_run(scratch_data, xml_path, track_count):
    print("\n=== RUN 1: full pass through POST /api/jobs/reindex ===")
    api = api_for(scratch_data, xml_path)
    started_at = time.monotonic()
    terminal = wait_for_terminal(api, start_reindex(api))
    elapsed = time.monotonic() - started_at

    expect(terminal["state"] == SUCCEEDED, "job succeeded", terminal["state"])
    result = terminal["result"] or {}
    expect(result.get("status") == "indexed", "result says indexed", str(result))
    expect(
        result.get("total_tracks_indexed") == track_count,
        "result reports every track",
        str(result.get("total_tracks_indexed")),
    )
    expect(
        all((scratch_data / name).is_file() for name in INDEX_FILES),
        "all four index files were committed",
    )
    expect(
        len(pd.read_parquet(scratch_data / "meta.parquet")) == track_count,
        "all tracks were persisted",
    )
    status, library = api.handle("GET", "/api/library", {})
    expect(status == 200, "library endpoint remains available")
    expect(
        library["track_count"] == track_count,
        "live API session published the new index",
        str(library["track_count"]),
    )
    print(f"    elapsed {elapsed:.1f}s")


def cancelled_run(scratch_data, xml_path, track_count):
    print("\n=== RUN 2: cancel through POST /api/jobs/{id}/cancel ===")
    api = api_for(scratch_data, xml_path)
    job_id = start_reindex(api)
    cancellation = {}

    def cancel_after_second_track(job):
        progress = job["progress"]
        if (
            not cancellation
            and progress["total"] == track_count
            and progress["current"] >= 2
        ):
            status, body = api.handle(
                "POST", f"/api/jobs/{job_id}/cancel", {}, {}
            )
            cancellation.update(status=status, body=body)

    terminal = wait_for_terminal(
        api, job_id, on_progress=cancel_after_second_track
    )

    expect(cancellation.get("status") == 200, "cancel endpoint accepted the stop")
    cancelled_job = cancellation.get("body", {}).get("job", {})
    expect(
        cancelled_job.get("cancel_requested") is True,
        "cancel signal was delivered",
    )
    expect(terminal["state"] == CANCELLED, "job reports cancelled", terminal["state"])
    expect(terminal["result"] is None, "cancelled job has no partial result")
    expect(
        not any((scratch_data / name).exists() for name in INDEX_FILES),
        "cancelled run committed no index files",
    )


def main():
    source_data = REPO / "data"
    if not (source_data / "meta.parquet").is_file():
        print(f"no real library at {source_data}", file=sys.stderr)
        return 2

    before = fingerprint(source_data)
    metadata = pd.read_parquet(source_data / "meta.parquet")
    usable = metadata[
        metadata["path_local"].apply(lambda value: bool(value) and os.path.exists(value))
    ]
    requested = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    if requested < 1:
        print("track count must be positive", file=sys.stderr)
        return 2
    if len(usable) < max(requested, 6):
        print("at least six real audio files are required", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="coco-realindex-") as temporary:
        root = Path(temporary)

        complete_data = root / "complete-data"
        complete_data.mkdir()
        complete_xml = write_xml(root / "complete.xml", usable.head(requested))
        complete_run(complete_data, complete_xml, requested)

        cancel_count = max(requested, 6)
        cancelled_data = root / "cancelled-data"
        cancelled_data.mkdir()
        cancelled_xml = write_xml(root / "cancelled.xml", usable.head(cancel_count))
        cancelled_run(cancelled_data, cancelled_xml, cancel_count)

    after = fingerprint(source_data)
    expect(after == before, "source data directory is byte- and mtime-identical")

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nALL REAL-INDEXING WEB-JOB CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
