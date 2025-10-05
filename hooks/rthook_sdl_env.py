"""
PyInstaller runtime hook to configure SDL environment variables.

This runs BEFORE any application code or imports, ensuring SDL
initializes in headless mode and doesn't try to create GUI dialogs.
"""
import os
import sys

# Configure SDL to run in headless/dummy mode
# MUST be set before SDL library initializes
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['SDL_RENDER_DRIVER'] = 'software'

# Also set OpenMP environment variables for safety
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('OMP_NUM_THREADS', '1')

# Print confirmation (only visible in console mode)
if '--verbose' in sys.argv or '-v' in sys.argv:
    print("[SDL Runtime Hook] Environment configured for headless mode")

