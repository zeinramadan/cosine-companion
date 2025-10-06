#!/usr/bin/env python3
"""File path configuration."""

from pathlib import Path
import sys
import platform

# Data paths (relative to project root, not src/)
# Get the directory where this config module is located (src/config/)
# Then go up two levels to get project root, then into data/models
_CONFIG_DIR = Path(__file__).parent
_SRC_DIR = _CONFIG_DIR.parent
_PROJECT_ROOT = _SRC_DIR.parent

def _get_data_dir() -> Path:
    """Return writable data directory depending on runtime context.

    - For frozen apps, use a per-user application data directory
      (so we don't write inside the .app bundle).
    - For dev, use project-root/data as before.
    """
    if getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS'):
        system = platform.system()
        if system == 'Darwin':
            return Path.home() / 'Library' / 'Application Support' / 'Cosine Companion'
        if system == 'Windows':
            return Path.home() / 'AppData' / 'Local' / 'Cosine Companion'
        # Linux and others
        return Path.home() / '.local' / 'share' / 'cosine-companion'
    return _PROJECT_ROOT / 'data'

DATA = _get_data_dir()
DATA.mkdir(parents=True, exist_ok=True)

# Model paths (bundled under PyInstaller's MEIPASS when frozen)
def _get_models_dir() -> Path:
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'models'
    return _PROJECT_ROOT / 'models'

MODELS = _get_models_dir()

# Data file paths
META_PQ = DATA / "meta.parquet"
EMB_PQ = DATA / "embeddings.parquet"
IDX_NPY = DATA / "index.npy"  # stores vectors
IDS_JSON = DATA / "ids.json"  # track_id order
DELETED_TRACKS_JSON = DATA / "deleted_tracks.json"  # tracks manually deleted by user
