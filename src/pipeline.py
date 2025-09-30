#!/usr/bin/env python3
"""Indexing pipeline for processing audio files and building the search index."""

import json
import os
import numpy as np
import pandas as pd
from pathlib import Path

from config import META_PQ, EMB_PQ, IDX_NPY, IDS_JSON, DATA
from rekordbox import read_rekordbox_xml
from embeddings import DiscogsEffnetEmbedder


def load_existing_data():
    """
    Load existing metadata and embeddings if they exist.
    
    Returns:
        Tuple of (existing_meta_df, existing_embeddings_df) or (None, None) if no data exists
    """
    if not META_PQ.exists() or not EMB_PQ.exists():
        return None, None
    
    try:
        existing_meta = pd.read_parquet(META_PQ)
        existing_emb = pd.read_parquet(EMB_PQ)
        print(f"Found existing data: {len(existing_meta)} tracks already indexed")
        return existing_meta, existing_emb
    except Exception as e:
        print(f"Warning: Could not load existing data ({e}), starting fresh")
        return None, None


def find_new_tracks(current_meta, existing_meta):
    """
    Find tracks that need to be processed (new or changed).
    
    Args:
        current_meta: Current metadata from XML
        existing_meta: Previously processed metadata
        
    Returns:
        DataFrame of tracks that need processing
    """
    if existing_meta is None:
        return current_meta
    
    # Find tracks not in existing data
    existing_ids = set(existing_meta['track_id'].values)
    new_tracks = current_meta[~current_meta['track_id'].isin(existing_ids)]
    
    print(f"Found {len(new_tracks)} new tracks to process")
    return new_tracks


def merge_embeddings(existing_emb, new_emb_df, new_track_ids, new_vectors):
    """
    Merge existing embeddings with new ones.
    
    Args:
        existing_emb: Existing embeddings DataFrame
        new_emb_df: New embeddings DataFrame  
        new_track_ids: List of new track IDs
        new_vectors: Array of new vectors
        
    Returns:
        Tuple of (combined_embeddings_df, combined_vectors, combined_track_ids)
    """
    if existing_emb is None:
        return new_emb_df, new_vectors, new_track_ids
    
    # Combine DataFrames
    combined_emb = pd.concat([existing_emb, new_emb_df], ignore_index=True)
    
    # Reconstruct vectors from existing embeddings
    existing_vcols = [c for c in existing_emb.columns if c.startswith("v")]
    existing_vectors = existing_emb[existing_vcols].values.astype("float32")
    existing_track_ids = existing_emb['track_id'].tolist()
    
    # Combine vectors and track IDs
    if len(new_vectors) > 0:
        combined_vectors = np.vstack([existing_vectors, new_vectors])
    else:
        combined_vectors = existing_vectors
    
    combined_track_ids = existing_track_ids + new_track_ids
    
    return combined_emb, combined_vectors, combined_track_ids


def remove_simple_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Remove duplicate tracks using fast file-based detection.
    
    Removes:
    1. Exact same file path (same file imported multiple times)
    2. Same file size and similar filename (likely same file with different names)
    
    Args:
        df: DataFrame with track metadata
        
    Returns:
        Tuple of (cleaned_df, duplicates_info_dict)
    """
    if len(df) == 0:
        return df, {"removed_count": 0, "details": []}
    
    original_count = len(df)
    duplicates_details = []
    
    # Step 1: Remove exact file path duplicates
    path_duplicates = df[df.duplicated(subset=['path_local'], keep='first')]
    if len(path_duplicates) > 0:
        for _, row in path_duplicates.iterrows():
            duplicates_details.append(f"Same file path: {row.get('artist', '')} - {row.get('title', '')} ({row.get('path_local', '')})")
        df = df.drop_duplicates(subset=['path_local'], keep='first')
    
    # Step 2: Get file sizes for remaining tracks
    df_with_size = df.copy()
    df_with_size['file_size'] = 0
    
    for idx, row in df_with_size.iterrows():
        path_local = str(row.get("path_local", ""))
        if path_local and os.path.exists(path_local):
            try:
                df_with_size.at[idx, 'file_size'] = os.path.getsize(path_local)
            except:
                df_with_size.at[idx, 'file_size'] = 0
    
    # Step 3: Group by file size and check for likely duplicates
    # Only check files with the same size (much faster than comparing all pairs)
    size_groups = df_with_size.groupby('file_size')
    to_remove_indices = []
    
    for size, group in size_groups:
        if size == 0 or len(group) < 2:
            continue
            
        # For files with same size, check if artist+title are very similar
        group_list = group.to_dict('records')
        for i in range(len(group_list)):
            if group_list[i]['track_id'] in [df_with_size.iloc[idx]['track_id'] for idx in to_remove_indices]:
                continue
                
            for j in range(i + 1, len(group_list)):
                if group_list[j]['track_id'] in [df_with_size.iloc[idx]['track_id'] for idx in to_remove_indices]:
                    continue
                
                # Check if artist and title are identical (case-insensitive)
                artist_i = str(group_list[i].get('artist', '')).lower().strip()
                title_i = str(group_list[i].get('title', '')).lower().strip()
                artist_j = str(group_list[j].get('artist', '')).lower().strip()
                title_j = str(group_list[j].get('title', '')).lower().strip()
                
                if (artist_i and title_i and artist_j and title_j and 
                    artist_i == artist_j and title_i == title_j):
                    
                    # Same artist+title and same file size = likely duplicate
                    # Remove the second occurrence
                    j_idx = group.index[j]
                    to_remove_indices.append(j_idx)
                    
                    duplicates_details.append(
                        f"Likely duplicate: {group_list[j].get('artist', '')} - {group_list[j].get('title', '')} "
                        f"(same size as: {group_list[i].get('artist', '')} - {group_list[i].get('title', '')})"
                    )
    
    # Remove duplicates
    if to_remove_indices:
        df_cleaned = df_with_size.drop(to_remove_indices).reset_index(drop=True)
        df_cleaned = df_cleaned.drop(columns=['file_size'])  # Remove temporary column
    else:
        df_cleaned = df.copy()
    
    removed_count = original_count - len(df_cleaned)
    
    return df_cleaned, {
        "removed_count": removed_count,
        "details": duplicates_details
    }


def cmd_index(rb_xml: str, force_full: bool = False, sample_size: int | None = None):
    """
    Incremental indexing pipeline: parse XML, generate embeddings for new tracks, build index.
    
    Only processes tracks that haven't been indexed before, saving significant time
    when adding new tracks to an existing collection.
    
    Args:
        rb_xml: Path to Rekordbox XML export file
        force_full: If True, ignore existing data and reprocess all tracks
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
        if not pl or not os.path.exists(pl):
            print(f"      ⚠️  File not found: {pl}")
            continue
        vector = embedder.embed_file(pl)
        
        if vector is None:
            print(f"      ⚠️  Failed to process audio file (unsupported codec or decode error): {pl}")
            continue
            
        new_track_ids.append(row["track_id"])
        new_vectors.append(vector)
    
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
    
    # Update metadata (combine current XML with any existing processed tracks)
    current_meta.to_parquet(META_PQ, index=False)
    
    # Save combined embeddings and index
    np.save(IDX_NPY, combined_vectors)
    with open(IDS_JSON, "w") as f:
        json.dump(combined_track_ids, f)
    combined_emb.to_parquet(EMB_PQ, index=False)
    
    print("=" * 50)
    print(f"✅ Indexing complete!")
    print(f"   • Total tracks indexed: {len(combined_track_ids)}")
    print(f"   • New tracks added: {len(new_track_ids)}")
    print(f"   • Data saved to: {DATA}/")
    print()
    print("🚀 Ready to use! Run 'python dj_companion.py ui' to start the application.")
