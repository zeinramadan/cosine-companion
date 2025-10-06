#!/bin/bash
# Launcher script for Cosine Companion on macOS
# Sets SDL environment variables before launching the app

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set SDL environment variables to prevent GUI initialization
export SDL_VIDEODRIVER=dummy
export SDL_AUDIODRIVER=dummy
export SDL_RENDER_DRIVER=software

# Set OpenMP variables to avoid conflicts
export KMP_DUPLICATE_LIB_OK=TRUE
export OMP_NUM_THREADS=1

# Launch the actual executable (in the same directory)
exec "$SCRIPT_DIR/Cosine Companion.bin" "$@"

