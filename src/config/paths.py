#!/usr/bin/env python3
"""File path configuration."""

from pathlib import Path

# Data paths (relative to project root, not src/)
# Get the directory where this config module is located (src/config/)
# Then go up two levels to get project root, then into data/models
_CONFIG_DIR = Path(__file__).parent
_SRC_DIR = _CONFIG_DIR.parent
_PROJECT_ROOT = _SRC_DIR.parent

DATA = _PROJECT_ROOT / "data"
DATA.mkdir(exist_ok=True)

# Model paths
MODELS = _PROJECT_ROOT / "models"

# Data file paths
META_PQ = DATA / "meta.parquet"
EMB_PQ = DATA / "embeddings.parquet"
IDX_NPY = DATA / "index.npy"  # stores vectors
IDS_JSON = DATA / "ids.json"  # track_id order
