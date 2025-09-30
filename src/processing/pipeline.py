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
from processing.embeddings import DiscogsEffnetEmbedder
from processing.xml_parser import read_rekordbox_xml


def index_library(rb_xml: str, force_full: bool = False, sample_size: int | None = None):
    """
    Incremental indexing pipeline: parse XML, generate embeddings for new tracks, build index.
    
    Only processes tracks that haven't been indexed before, saving significant time
    when adding new tracks to an existing collection.
    
    Args:
        rb_xml: Path to Rekordbox XML export file
        force_full: If True, ignore existing data and reprocess all tracks
        sample_size: If provided, limit processing to this many new tracks (for testing)
    """
    mode = "Full Reindex" if force_full else "Incremental Indexing"
    print(f"🎵 DJ Companion - {mode}")
    print("=" * 50)
    
    # Load existing data (unless forcing full reindex)
    if force_full:
        print("🔄 Force full reindex requested - ignoring existing data")
        existing_meta, existing_emb = None, None
    else:
        existing_meta, existing_emb = load_existing_data()
    
    # Read current XML
    print("📖 Reading Rekordbox XML...")
    current_meta = read_rekordbox_xml(rb_xml)
    print(f"   Found {len(current_meta)} tracks in XML")
    
    # Remove simple duplicates (fast file-based detection)
    print("🔍 Checking for duplicate tracks...")
    current_meta, duplicates_info = remove_simple_duplicates(current_meta)
    if duplicates_info["removed_count"] > 0:
        print(f"   Removed {duplicates_info['removed_count']} duplicate tracks")
        print(f"   Kept {len(current_meta)} unique tracks")
        if duplicates_info["details"]:
            print("   Duplicates found:")
            for detail in duplicates_info["details"][:5]:  # Show first 5
                print(f"      • {detail}")
            if len(duplicates_info["details"]) > 5:
                print(f"      ... and {len(duplicates_info['details']) - 5} more")
    else:
        print("   No duplicates found")
    
    # Find new tracks to process
    new_tracks = find_new_tracks(current_meta, existing_meta)

    # Optionally limit for debug/sample runs
    if sample_size is not None and sample_size > 0:
        print(f"🔬 Debug sample enabled: limiting to first {sample_size} new tracks")
        new_tracks = new_tracks.head(sample_size)
    
    if len(new_tracks) == 0:
        print("✅ No new tracks to process! Your index is up to date.")
        return
    
    # Process new tracks only
    print(f"🎯 Processing {len(new_tracks)} new tracks...")
    embedder = DiscogsEffnetEmbedder()
    new_vectors = []
    new_track_ids = []
    
    for i, (_, row) in enumerate(new_tracks.iterrows(), 1):
        pl = str(row.get("path_local", ""))
        print(f"   [{i:3d}/{len(new_tracks)}] {row.get('artist','')} - {row.get('title','')}")
        sys.stdout.flush()  # Ensure message appears immediately
        
        if not pl or not os.path.exists(pl):
            print(f"      ⚠️  File not found: {pl}")
            sys.stdout.flush()
            continue
        
        vector = embedder.embed_file(pl)
        
        if vector is None:
            print(f"      ⚠️  Failed to process audio file (unsupported codec or decode error): {pl}")
            sys.stdout.flush()
            continue
            
        new_track_ids.append(row["track_id"])
        new_vectors.append(vector)
        
        # Small pause to let UI update and prevent system overload
        # This makes the UI responsive without significantly impacting total time
        time.sleep(0.05)  # 50ms pause between tracks
        sys.stdout.flush()
    
    if not new_vectors:
        print("❌ No new embeddings generated. Check audio paths/codecs.")
        return
    
    print(f"✨ Generated {len(new_vectors)} new embeddings")
    
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
    print("🔄 Merging with existing data...")
    combined_emb, combined_vectors, combined_track_ids = merge_embeddings(
        existing_emb, new_emb_df, new_track_ids, new_vectors_array
    )
    
    # Save all data
    save_index_data(current_meta, combined_emb, combined_vectors, combined_track_ids)
    
    print("=" * 50)
    print(f"✅ Indexing complete!")
    print(f"   • Total tracks indexed: {len(combined_track_ids)}")
    print(f"   • New tracks added: {len(new_track_ids)}")
    print(f"   • Data saved to: {DATA}/")
    print()
    print("🚀 Ready to use! Run 'python dj_companion.py ui' to start the application.")
