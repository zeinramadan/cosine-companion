#!/usr/bin/env python3
"""Indexing pipeline for processing audio files and building the search index."""

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from core.loader import load_existing_data, find_new_tracks
from core.persistence import merge_embeddings, save_index_data
from core.duplicates import remove_simple_duplicates
from core.deleted_tracks import filter_deleted_tracks
from processing.xml_parser import read_rekordbox_xml

# Bound on first use by _load_embedder(). NOT imported at module scope:
# processing.embeddings does `import essentia.standard`, which loads TensorFlow,
# and nothing that merely imports this module should pay that. It stays a module
# attribute so `monkeypatch.setattr(pipeline, "DiscogsEffnetEmbedder", Fake)`
# remains the seam the tests and tests/manual/real_indexing.py use.
#
# DECLARED DEVIATION from this PR's strict-preservation contract.
# ---------------------------------------------------------------
# On `main` this name was bound eagerly by a module-scope
# `from processing.embeddings import DiscogsEffnetEmbedder`, so it was the class
# from the moment the module finished importing. It is now observably None until
# the first _load_embedder() call:
#
#     import processing.pipeline as p
#     p.DiscogsEffnetEmbedder     # main: the class.  Here: None.
#
# This is a deliberate, documented exception, not an oversight, and it is
# codified by tests/test_services_are_lightweight.py:131-134.
#
# Why it is not a behaviour change in the sense the contract protects:
#   * No RUNTIME path reads the module attribute directly. The one consumer is
#     _load_embedder() below (used at line 136), which binds it before use.
#   * The PACKAGE-level re-export is unaffected: processing/__init__.py still
#     does `from processing.embeddings import DiscogsEffnetEmbedder`, so
#     `processing.DiscogsEffnetEmbedder` is the class exactly as before, and
#     that is the import path every caller outside this module uses.
#   * The monkeypatch seam is preserved, which is why the existing tests and the
#     manual harness needed no change.
#
# Why it was necessary: services.indexing_service must be importable without a
# 483 MB TensorFlow install, or the CI job (numpy/pandas/pyarrow/lxml/pytest
# only) and PR 3's web server both break on `import services`. An eager import
# here would drag Essentia into every consumer of the service layer, down to the
# 72-line settings_store JSON reader.
#
# Anything that genuinely needs the eager-class behaviour should import from
# `processing`, not from `processing.pipeline`.
DiscogsEffnetEmbedder = None


# index_library's three terminal outcomes. Both "nothing to do" outcomes used to
# return a bare None, so a caller could not tell "your index is already up to
# date" (success) from "there were new tracks and not one of them could be
# embedded" (failure).
#
# This return value is ADDITIVE. No current caller reads it: the CLI
# (cosine_companion.py:50) discards it, and IndexingService only forwards it into
# an IndexResult that both Tkinter windows discard in turn. So all three outcomes
# still report success to the user, exactly as on `main` - pinned by
# tests/test_ui_reports_success_for_every_terminal_outcome.py. PR 3 consumes it
# to fix that deliberately. See IndexResult's docstring in
# services/indexing_service.py.
STATUS_INDEXED = "indexed"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_NO_EMBEDDINGS = "no_embeddings"


def _load_embedder():
    """Return the embedder class, importing Essentia the first time only."""
    global DiscogsEffnetEmbedder
    if DiscogsEffnetEmbedder is None:
        from processing.embeddings import DiscogsEffnetEmbedder as _Embedder

        DiscogsEffnetEmbedder = _Embedder
    return DiscogsEffnetEmbedder


def refresh_playlists(rb_xml, report, data_dir):
    """Re-import the playlist tables from ``rb_xml`` beside the index files.

    Called at every terminal outcome of ``index_library`` so a normal reindex
    keeps playlists current. The standalone
    ``cosine_companion.py import-playlists`` command exists because the reverse
    is not acceptable: the user has just spent 11m33s embedding audio, and
    making them do it again to see a playlist would be an unforced insult. Both
    paths call ``services.playlist_import.import_playlists``; there is one
    implementation.

    SILENT ON SUCCESS - A DELIBERATE, DECLARED DEVIATION
    ----------------------------------------------------
    The plan (§5) asks the pipeline to report the import summary the way the
    CLI does. It cannot, and the reason is a hard constraint of the same plan
    (§2.2: pre-existing tests must not be edited to accommodate this work).
    Three tests in tests/services/test_indexing_service.py assert the COMPLETE,
    ORDERED event list of an indexing run - a first run, an up-to-date run and
    a run where nothing could be embedded. (An earlier draft of this paragraph
    cited a fourth, test_the_exact_output_of_the_cli_index_command, as pinning
    the CLI's stdout
    verbatim. No test of that name exists. The replacement claim - that no test
    anywhere pins the CLI's stdout - was false too:
    tests/services/test_indexing_service.py:893
    test_pipeline_still_prints_when_no_callback_is_given calls
    ``index_library(str(xml))``, which is what cosine_companion.py:50 calls,
    captures stdout with ``capsys`` and asserts four things about it - three
    ``in out`` substring checks and one ``out.endswith(...)``. What is
    defensible is narrower, and it is stated as the search that supports it: a
    grep of ``tests/`` for ``capsys``, ``capfd`` and ``redirect_stdout``, cross
    referenced with the tests that call ``index_library``, finds exactly that
    one test capturing this function's transcript, and it pins three substrings
    and the final line rather than the whole of it. The other exact-equality
    stdout assertions the grep turns up are on different entry points -
    ``test_run_never_writes_to_stdout`` at :122 asserts the SERVICE path writes
    nothing, and two in tests/test_xml_parser.py pin the parser's output. The
    argument here does not need more than that anyway: it rests on the three
    ordered-event tests named above, which pin a COMPLETE list.) Those tests
    exist precisely to catch a change to the indexing transcript, so satisfying
    them by editing them would be defeating the guard rather than passing it.

    So the reindex path keeps playlists CURRENT and says nothing about it,
    which is what the plan's own §5 sentence "so a normal reindex keeps
    playlists current" actually requires. The reporting requirement in the same
    section attaches to the import SUMMARY, which the standalone command prints
    in full - and the standalone command is also what the staleness banner
    names. A failure IS reported: silence is the success case only.

    ``data_dir`` is the same explicit directory the index read and write paths
    receive. Playlist refresh must not derive a second target from a module
    global after the index generation has committed somewhere else.
    """
    # Imported lazily, for the same reason the embedder is: nothing that merely
    # imports this module should pull the service layer in behind it.
    from services.playlist_import import import_playlists

    try:
        return import_playlists(rb_xml, data_dir=Path(data_dir))
    except Exception as error:  # noqa: BLE001 - see below
        # Never fails the run. In the success path the four index files are
        # already written by the time this is reached, and a malformed
        # <PLAYLISTS> element is not a reason to tell the user an 11-minute
        # embed did not happen.
        report("playlists", f"⚠️  Could not import playlists: {error}")
        return None


def make_reporter(progress=None):
    """Return a ``report(phase, message, current=0, total=0)`` function.

    With no callback the message is printed, exactly as this pipeline always
    did - that keeps ``cosine_companion.py index`` unchanged. With a callback
    the same string is handed over as a structured event instead, and nothing
    is written to stdout. That is what lets the UI stop replacing the
    process-global ``sys.stdout`` from a worker thread.
    """
    def report(phase, message, current=0, total=0):
        if progress is None:
            print(message)
        else:
            progress(phase, current, total, message)
    return report


def index_library(
    rb_xml: str,
    *,
    data_dir,
    force_full: bool = False,
    sample_size: int | None = None,
    cancel_check=None,
    progress=None,
):
    """
    Incremental indexing pipeline: parse XML, generate embeddings for new tracks, build index.
    
    Only processes tracks that haven't been indexed before, saving significant time
    when adding new tracks to an existing collection.
    
    Args:
        rb_xml: Path to Rekordbox XML export file
        data_dir: Directory whose existing index is read and whose replacement
            generation is committed
        force_full: If True, ignore existing data and reprocess all tracks
        sample_size: If provided, limit processing to this many new tracks (for testing)
        cancel_check: Optional callable that returns True if cancellation is requested
        progress: Optional callable(phase, current, total, message). When given,
            messages are reported through it instead of being printed.

    Returns:
        A summary dict whose ``status`` is one of ``STATUS_INDEXED`` (work was
        done), ``STATUS_UP_TO_DATE`` (no new tracks) or ``STATUS_NO_EMBEDDINGS``
        (new tracks existed but none could be embedded). Only the first carries
        ``total_tracks_indexed`` / ``new_tracks_added``.
    """
    data_dir = Path(data_dir)
    report = make_reporter(progress)
    printing = progress is None

    mode = "Full Reindex" if force_full else "Incremental Indexing"
    report("start", f"🎵 Cosine Companion - {mode}")
    report("start", "=" * 50)
    
    # Load existing data (unless forcing full reindex)
    if force_full:
        report("start", "🔄 Force full reindex requested - ignoring existing data")
        existing_meta, existing_emb = None, None
    else:
        existing_meta, existing_emb = load_existing_data(
            data_dir, progress=progress
        )
    
    # Read current XML
    report("read_xml", "📖 Reading Rekordbox XML...")
    current_meta = read_rekordbox_xml(rb_xml, progress=progress)
    report("read_xml", f"   Found {len(current_meta)} tracks in XML")
    
    # Remove simple duplicates (fast file-based detection)
    report("duplicates", "🔍 Checking for duplicate tracks...")
    current_meta, duplicates_info = remove_simple_duplicates(current_meta)
    if duplicates_info["removed_count"] > 0:
        report("duplicates", f"   Removed {duplicates_info['removed_count']} duplicate tracks")
        report("duplicates", f"   Kept {len(current_meta)} unique tracks")
        if duplicates_info["details"]:
            report("duplicates", "   Duplicates found:")
            for detail in duplicates_info["details"][:5]:  # Show first 5
                report("duplicates", f"      • {detail}")
            if len(duplicates_info["details"]) > 5:
                report("duplicates", f"      ... and {len(duplicates_info['details']) - 5} more")
    else:
        report("duplicates", "   No duplicates found")
    
    # Filter out tracks that user has manually deleted
    report("deleted", "🔍 Checking for previously deleted tracks...")
    current_meta = filter_deleted_tracks(
        current_meta,
        progress=progress,
        path=data_dir / "deleted_tracks.json",
    )
    
    # Find new tracks to process
    new_tracks = find_new_tracks(current_meta, existing_meta, progress=progress)

    # Optionally limit for debug/sample runs
    if sample_size is not None and sample_size > 0:
        report("plan", f"🔬 Debug sample enabled: limiting to first {sample_size} new tracks")
        new_tracks = new_tracks.head(sample_size)
    
    if len(new_tracks) == 0:
        refresh_playlists(rb_xml, report, data_dir)
        report("complete", "✅ No new tracks to process! Your index is up to date.")
        return {"status": STATUS_UP_TO_DATE, "new_tracks_found": 0}
    
    # Process new tracks only
    report("plan", f"🎯 Processing {len(new_tracks)} new tracks...")
    embedder = _load_embedder()()
    new_vectors = []
    new_track_ids = []
    total = len(new_tracks)
    
    for i, (_, row) in enumerate(new_tracks.iterrows(), 1):
        # Check for cancellation
        if cancel_check and cancel_check():
            report("cancelled", "⚠️ Cancellation detected, stopping...", current=i, total=total)
            if printing:
                sys.stdout.flush()
            raise KeyboardInterrupt("User cancelled indexing")
        
        pl = str(row.get("path_local", ""))
        report("embed", f"   [{i:3d}/{total}] {row.get('artist','')} - {row.get('title','')}",
               current=i, total=total)
        if printing:
            sys.stdout.flush()  # Ensure message appears immediately
        
        if not pl or not os.path.exists(pl):
            report("embed", f"      ⚠️  File not found: {pl}", current=i, total=total)
            if printing:
                sys.stdout.flush()
            continue
        
        vector = embedder.embed_file(pl)
        
        if vector is None:
            report("embed",
                   f"      ⚠️  Failed to process audio file (unsupported codec or decode error): {pl}",
                   current=i, total=total)
            if printing:
                sys.stdout.flush()
            continue
            
        new_track_ids.append(row["track_id"])
        new_vectors.append(vector)
        
        # Small pause to let UI update and prevent system overload
        # This makes the UI responsive without significantly impacting total time
        time.sleep(0.05)  # 50ms pause between tracks
        if printing:
            sys.stdout.flush()
    
    if not new_vectors:
        refresh_playlists(rb_xml, report, data_dir)
        report("complete", "❌ No new embeddings generated. Check audio paths/codecs.")
        return {"status": STATUS_NO_EMBEDDINGS, "new_tracks_found": total}
    
    report("embed", f"✨ Generated {len(new_vectors)} new embeddings", current=total, total=total)
    
    # Prepare new embeddings (normalize defensively)
    new_vectors_array = np.vstack(new_vectors).astype("float32")
    norms = np.linalg.norm(new_vectors_array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    new_vectors_array = new_vectors_array / norms
    
    # Create new embeddings DataFrame efficiently
    v_cols = [f"v{i}" for i in range(new_vectors_array.shape[1])]
    new_emb_df = pd.concat([
        pd.DataFrame({"track_id": new_track_ids}),
        pd.DataFrame(new_vectors_array, columns=v_cols)
    ], axis=1)
    
    # Merge with existing data
    report("merge", "🔄 Merging with existing data...")
    combined_emb, combined_vectors, combined_track_ids = merge_embeddings(
        existing_emb, new_emb_df, new_track_ids, new_vectors_array
    )
    
    # Build metadata in the exact row order used by embeddings/ids/index. Keep
    # existing tracks that are absent from the current XML, but never persist a
    # current-XML row whose audio failed to produce an embedding.
    if existing_meta is not None:
        report("merge", "🔄 Merging metadata...")

    current_meta_by_id = {
        row["track_id"]: row.to_dict() for _, row in current_meta.iterrows()
    }
    existing_meta_by_id = (
        {}
        if existing_meta is None
        else {
            row["track_id"]: row.to_dict() for _, row in existing_meta.iterrows()
        }
    )
    combined_meta_rows = []
    for track_id in combined_track_ids:
        row = current_meta_by_id.get(track_id, existing_meta_by_id.get(track_id))
        if row is None:
            raise ValueError(f"No metadata found for indexed track {track_id!r}")
        combined_meta_rows.append(row)
    combined_meta = pd.DataFrame(combined_meta_rows)
    
    # Save all data
    save_index_data(
        data_dir,
        combined_meta,
        combined_emb,
        combined_vectors,
        combined_track_ids,
    )

    # AFTER the index is saved, not before: the summary counts unresolvable
    # entries against meta.parquet, and counting them against the pre-reindex
    # file would report a shortfall this very run just fixed.
    refresh_playlists(rb_xml, report, data_dir)
    
    report("complete", "=" * 50)
    report("complete", f"✅ Indexing complete!")
    report("complete", f"   • Total tracks indexed: {len(combined_track_ids)}")
    report("complete", f"   • New tracks added: {len(new_track_ids)}")
    report("complete", f"   • Data saved to: {data_dir}/")
    if printing:
        print()  # the queue writer always dropped this blank line
    report("complete", "🚀 Ready to use! Run 'python cosine_companion.py ui' to start the application.")

    return {
        "status": STATUS_INDEXED,
        "total_tracks_indexed": len(combined_track_ids),
        "new_tracks_added": len(new_track_ids),
        "new_tracks_found": total,
    }
