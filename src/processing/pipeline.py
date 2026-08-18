#!/usr/bin/env python3
"""Indexing pipeline for processing audio files and building the search index."""

import os
import sys
import time
import numpy as np
import pandas as pd

from config import DATA
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
DiscogsEffnetEmbedder = None


# index_library's three terminal outcomes. Both "nothing to do" outcomes used to
# return a bare None, so a caller could not tell "your index is already up to
# date" (success) from "there were new tracks and not one of them could be
# embedded" (failure). The CLI never read the return value, but the service
# layer does, and PR 3 would otherwise report a failed run as a success.
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


def index_library(rb_xml: str, force_full: bool = False, sample_size: int | None = None,
                  cancel_check=None, progress=None):
    """
    Incremental indexing pipeline: parse XML, generate embeddings for new tracks, build index.
    
    Only processes tracks that haven't been indexed before, saving significant time
    when adding new tracks to an existing collection.
    
    Args:
        rb_xml: Path to Rekordbox XML export file
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
        existing_meta, existing_emb = load_existing_data(progress=progress)
    
    # Read current XML
    report("read_xml", "📖 Reading Rekordbox XML...")
    current_meta = read_rekordbox_xml(rb_xml)
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
    current_meta = filter_deleted_tracks(current_meta, progress=progress)
    
    # Find new tracks to process
    new_tracks = find_new_tracks(current_meta, existing_meta, progress=progress)

    # Optionally limit for debug/sample runs
    if sample_size is not None and sample_size > 0:
        report("plan", f"🔬 Debug sample enabled: limiting to first {sample_size} new tracks")
        new_tracks = new_tracks.head(sample_size)
    
    if len(new_tracks) == 0:
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
    
    # Merge metadata properly - keep existing metadata + add new metadata
    # This ensures we don't lose metadata for tracks that might not be in current XML
    if existing_meta is not None:
        # Update existing metadata with current XML data (for tracks that are in the XML)
        # Keep all existing tracks, update with new values where available
        report("merge", "🔄 Merging metadata...")
        
        # Create a dict from current_meta for fast lookup
        current_meta_dict = {row['track_id']: row for _, row in current_meta.iterrows()}
        
        # Build combined metadata by merging existing and new
        combined_meta_rows = []
        seen_ids = set()
        
        # First, add/update all tracks from current XML
        for tid in combined_track_ids:
            if tid in current_meta_dict:
                combined_meta_rows.append(current_meta_dict[tid])
                seen_ids.add(tid)
        
        # Then add any tracks from existing_meta that weren't in current XML
        # (these are tracks that were previously indexed but removed from Rekordbox)
        for _, row in existing_meta.iterrows():
            tid = row['track_id']
            if tid in combined_track_ids and tid not in seen_ids:
                combined_meta_rows.append(row.to_dict())
                seen_ids.add(tid)
        
        combined_meta = pd.DataFrame(combined_meta_rows)
    else:
        combined_meta = current_meta
    
    # Save all data
    save_index_data(combined_meta, combined_emb, combined_vectors, combined_track_ids)
    
    report("complete", "=" * 50)
    report("complete", f"✅ Indexing complete!")
    report("complete", f"   • Total tracks indexed: {len(combined_track_ids)}")
    report("complete", f"   • New tracks added: {len(new_track_ids)}")
    report("complete", f"   • Data saved to: {DATA}/")
    if printing:
        print()  # the queue writer always dropped this blank line
    report("complete", "🚀 Ready to use! Run 'python cosine_companion.py ui' to start the application.")

    return {
        "status": STATUS_INDEXED,
        "total_tracks_indexed": len(combined_track_ids),
        "new_tracks_added": len(new_track_ids),
        "new_tracks_found": total,
    }
