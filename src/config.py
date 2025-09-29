#!/usr/bin/env python3
"""Configuration and shared constants for DJ Companion."""

from pathlib import Path

# Data paths (relative to project root, not src/)
# Get the directory where this config.py file is located (src/)
# Then go up one level to get project root, then into data/models
_CONFIG_DIR = Path(__file__).parent
_PROJECT_ROOT = _CONFIG_DIR.parent

DATA = _PROJECT_ROOT / "data"
DATA.mkdir(exist_ok=True)

# Model paths
MODELS = _PROJECT_ROOT / "models"

META_PQ = DATA / "meta.parquet"
EMB_PQ = DATA / "embeddings.parquet"
IDX_NPY = DATA / "index.npy"  # stores vectors
IDS_JSON = DATA / "ids.json"  # track_id order

# Default embedding parameters
DEFAULT_SAMPLE_RATE = 32000

# Default scoring weights (cosine, key, bpm)
DEFAULT_SCORING_WEIGHTS = (0.7, 0.2, 0.1)

# Default recommendation parameters
DEFAULT_TOPK = 200
DEFAULT_FINAL_TOP = 15
