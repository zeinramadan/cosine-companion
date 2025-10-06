#!/bin/bash

# Set SDL environment variables to prevent GUI initialization issues
# These must be set BEFORE any SDL-using libraries (like essentia-tensorflow) are loaded by dyld.
export SDL_VIDEODRIVER="dummy"
export SDL_AUDIODRIVER="dummy"
export SDL_RENDER_DRIVER="software"

# Set OpenMP environment variables for performance and stability
export KMP_DUPLICATE_LIB_OK="TRUE"
export OMP_NUM_THREADS="1"

# Execute the actual PyInstaller-generated binary
# The binary is renamed to 'Cosine Companion.bin' in the .spec file
# The launcher script itself is copied to 'Cosine Companion'
exec "$(dirname "$0")/Cosine Companion.bin" "$@"
