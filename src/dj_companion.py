#!/usr/bin/env python3
"""
DJ Companion - Main application entry point.

A tool for finding similar tracks based on audio content, key compatibility,
and BPM matching. Uses Essentia's Discogs-EffNet embeddings and FAISS for
efficient similarity search.
"""

import os
# Avoid OpenMP duplicate runtime crash on macOS when multiple libs are present.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from pipeline import cmd_index
from ui import run_ui

# --- CLI ---
import typer

cli = typer.Typer(add_completion=False)


@cli.command()
def index(
    xml: str = typer.Argument(..., help="Path to Rekordbox XML export"),
    force: bool = typer.Option(False, "--force", "-f", help="Force full reindex, ignoring existing data"),
    sample: int = typer.Option(None, "--sample", "-s", help="Limit number of new tracks to process (debug)")
):
    """Index your library: parses XML, embeds audio, builds FAISS (incremental by default)."""
    cmd_index(xml, force_full=force, sample_size=sample)


@cli.command()
def ui():
    """Open the minimal UI (manual 'Set Current' for v1)."""
    run_ui()


if __name__ == "__main__":
    cli()


"""
This script is used to index your Rekordbox library and launch the UI. First step is to index your library, then you can launch the UI to start mixing.

Current approach is to set the current track manually, then the UI will suggest tracks that are similar to the current track. 

Next iteration will be to set the current track automatically based on the last played track by polling the Rekordbox database.

First we need to export the library from Rekordbox and place the exported XML in the data/ directory, then we can index the library and launch the UI.

Step 1: python dj_companion.py index /path/to/rekordbox_export.xml
Step 2: python dj_companion.py ui
"""