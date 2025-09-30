#!/usr/bin/env python3
"""Duplicate track detection and removal."""

import os
import pandas as pd


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
