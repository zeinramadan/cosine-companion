#!/usr/bin/env python3
"""Runtime hook for macOS to set environment variables before modules import.

This runs very early in PyInstaller boot sequence, before most Python imports,
ensuring SDL/Tk and OpenMP env vars are set to avoid GUI/driver crashes.
"""

import os
import sys

if sys.platform == 'darwin':
    # Prevent SDL from attempting to access unavailable displays/audio on macOS
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("SDL_RENDER_DRIVER", "software")

    # Avoid OpenMP duplicate symbols crash (e.g., with numpy and essentia)
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")

    # Silence deprecated Tk warnings; avoid forcing TCL/TK paths which may mismatch
    os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

