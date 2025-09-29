#!/usr/bin/env python3
"""Configuration and shared constants for DJ Companion."""

from pathlib import Path

# Data paths
DATA = Path("data")
DATA.mkdir(exist_ok=True)

META_PQ = DATA / "meta.parquet"
EMB_PQ = DATA / "embeddings.parquet"
IDX_NPY = DATA / "index.npy"  # stores vectors
IDS_JSON = DATA / "ids.json"  # track_id order

# Default embedding parameters
DEFAULT_FRAME_SEC = 1.0
DEFAULT_HOP_SEC = 0.5
DEFAULT_SAMPLE_RATE = 32000

# Default scoring weights (cosine, key, bpm)
DEFAULT_SCORING_WEIGHTS = (0.7, 0.2, 0.1)

# Default recommendation parameters
DEFAULT_TOPK = 200
DEFAULT_FINAL_TOP = 15
