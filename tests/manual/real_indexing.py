#!/usr/bin/env python3
"""Task 8 Step 6: a REAL indexing pass through ReindexWindow.

Mocked tests cannot prove the Tk wiring, so this drives the actual window with
the actual Essentia embedder over a handful of real tracks, then repeats it and
cancels partway. ReindexWindow's required data_dir binds every index and
playlist write to a fresh throwaway directory. The checkout's data and model
files, including /Users/zein/dj-cosine, are only ever read.
"""
import shutil, sys, tempfile, time
from pathlib import Path
from urllib.parse import quote

import os
REPO = Path(os.environ.get("COCO_REPO", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO / "src"))

TMP = Path(tempfile.mkdtemp(prefix="coco-realindex-"))
SCRATCH_DATA = TMP / "data"; SCRATCH_DATA.mkdir()

# The .pb model is gitignored, so it only exists in the primary checkout.
# READ ONLY - nothing is written there.
import processing.embeddings as E
E.MODELS = Path(os.environ.get("COCO_MODELS", REPO / "models"))

import pandas as pd
meta = pd.read_parquet(REPO / "data" / "meta.parquet")
import os
usable = meta[meta["path_local"].apply(lambda p: bool(p) and os.path.exists(p))]

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
picked = usable.head(N)


def write_xml(path, rows):
    entries = "".join(
        f'<TRACK TrackID="{r.track_id}" Name="{r.title}" Artist="{r.artist}" '
        f'AverageBpm="{r.bpm:.2f}" Tonality="{r.key}" Album="" '
        f'Location="file://localhost{quote(str(r.path_local))}"/>'
        for r in rows.itertuples()
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="{len(rows)}">'
        f"{entries}</COLLECTION></DJ_PLAYLISTS>", encoding="utf-8")
    return path


xml = write_xml(TMP / "small.xml", picked)
print(f"fixture XML: {N} real tracks -> {xml}")

import tkinter as tk
from tkinter import messagebox
import ui.reindex_window as rw
rw.messagebox.askyesno = lambda *a, **k: True

root = tk.Tk(); root.withdraw()

FAILURES = []
def expect(cond, label):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        FAILURES.append(label)


# ---------------------------------------------------------------- run 1
print("\n=== RUN 1: full pass, no cancellation ===")
t0 = time.time()
win = rw.ReindexWindow(root, str(xml), force_full=False, data_dir=SCRATCH_DATA)

def poll1():
    if not win.indexing_thread.is_alive() and win.message_queue.empty():
        root.quit(); return
    if time.time() - t0 > 900:
        print("  TIMED OUT"); root.quit(); return
    root.after(200, poll1)

root.after(500, poll1)
root.mainloop()
for _ in range(10):
    root.update_idletasks(); root.update()

log = win.log_text.get("1.0", tk.END)
elapsed = time.time() - t0
print(f"--- log ({elapsed:.1f}s) ---")
print(log.strip())
print("--- end log ---")

expect("🎵 Cosine Companion - Incremental Indexing" in log, "header line rendered")
expect("📖 Reading Rekordbox XML..." in log, "XML phase rendered")
expect(f"   Found {N} tracks in XML" in log, "XML track count rendered")
expect("🔍 Checking for duplicate tracks..." in log, "duplicates phase rendered")
expect(f"🎯 Processing {N} new tracks..." in log, "processing header rendered")
expect(f"[  1/{N}]" in log, "per-track progress line 1 shows i/N")
expect(f"[{N:3d}/{N}]" in log, f"per-track progress line {N} shows i/N")
expect(f"✨ Generated {N} new embeddings" in log, "embedding summary rendered")
expect("✅ Indexing complete!" in log, "completion banner rendered")
expect(f"   • Total tracks indexed: {N}" in log, "total count rendered")
expect("✅ Indexing completed successfully!" in log, "window success line appended")
expect(win.status_label.cget("text") == "✅ Library updated successfully!", "green success status")
expect(str(win.status_label.cget("fg")) == "green", "status colour green")
buttons = [w.cget("text") for w in win.button_frame.winfo_children()]
expect(buttons == ["Done"], f"Cancel replaced by Done (got {buttons})")
expect(not win.cancel_requested, "cancel flag clear")
expect((SCRATCH_DATA / "meta.parquet").exists(), "meta.parquet written")
expect(len(pd.read_parquet(SCRATCH_DATA / "meta.parquet")) == N, "all tracks persisted")
expect(sys.stdout is not None and hasattr(sys.stdout, "isatty"), "sys.stdout never swapped")
win.destroy()

# ---------------------------------------------------------------- run 2
print("\n=== RUN 2: cancel partway ===")
shutil.rmtree(SCRATCH_DATA); SCRATCH_DATA.mkdir()
M = max(N, 6)
xml2 = write_xml(TMP / "small2.xml", usable.head(M))
t0 = time.time()
win2 = rw.ReindexWindow(root, str(xml2), force_full=False, data_dir=SCRATCH_DATA)
cancelled_at = {}

def poll2():
    text = win2.log_text.get("1.0", tk.END)
    if "[  2/" in text and not win2.cancel_requested:
        cancelled_at["log"] = text
        win2.cancel_indexing()
    if not win2.indexing_thread.is_alive() and win2.message_queue.empty():
        root.quit(); return
    if time.time() - t0 > 900:
        print("  TIMED OUT"); root.quit(); return
    root.after(150, poll2)

root.after(300, poll2)
root.mainloop()
for _ in range(10):
    root.update_idletasks(); root.update()

log2 = win2.log_text.get("1.0", tk.END)
print(f"--- log ({time.time()-t0:.1f}s) ---")
print(log2.strip())
print("--- end log ---")

# SCOPE OF THIS HARNESS, stated so it is not mistaken for full coverage:
#
# * It exercises TIMING A only (inventory Sec 2.13). It cancels after track 2 of
#   at least 6, which guarantees a later per-track checkpoint, so the pipeline
#   always raises KeyboardInterrupt here. It cannot observe timing B - a cancel
#   first set after the LAST checkpoint - which completes the run, writes the
#   data files and DOES append "Indexing cancelled by user" (defect #17). That
#   timing is pinned deterministically instead, in
#   tests/services/test_indexing_service.py and
#   tests/test_ui_reports_success_for_every_terminal_outcome.py.
# * The two assertions below check PRESENCE, deliberately. The order of the two
#   cancellation lines is a race (defect #18): cancel_indexing sets the Event
#   before it queues its own line, so the worker can queue its line first. An
#   ordering assertion here would pass almost always and fail in the field.
expect(win2.cancel_requested, "cancel flag set")
expect("⚠️ Cancellation requested..." in log2, "cancellation-requested line rendered")
expect("⚠️ Cancellation detected, stopping..." in log2, "pipeline cancellation line rendered")
expect("⚠️ Indexing cancelled by user" not in log2,
       "'cancelled by user' line still ABSENT (KeyboardInterrupt is a BaseException)")
expect(win2.status_label.cget("text") == "⚠️ Indexing cancelled", "orange cancelled status")
expect(str(win2.status_label.cget("fg")) == "orange", "status colour orange")
buttons2 = [w.cget("text") for w in win2.button_frame.winfo_children()]
expect(buttons2 == ["Close"], f"Cancel replaced by Close (got {buttons2})")
expect(not (SCRATCH_DATA / "meta.parquet").exists(),
       "cancelled run persisted NOTHING (work discarded, defect #4)")
win2.destroy()
root.destroy()

print(f"\nscratch data dir: {TMP}")
if FAILURES:
    print(f"\n{len(FAILURES)} FAILED:")
    for f in FAILURES: print("  -", f)
    sys.exit(1)
print("\nALL REAL-INDEXING CHECKS PASSED")
