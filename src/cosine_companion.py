#!/usr/bin/env python3
"""
Cosine Companion - Main application entry point.

A tool for finding similar tracks based on audio content, key compatibility,
and BPM matching. Uses Essentia's Discogs-EffNet embeddings and FAISS for
efficient similarity search.
"""

import os
import sys
# Avoid OpenMP duplicate runtime crash on macOS when multiple libs are present.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# Check if running as frozen executable with no CLI args (GUI mode)
if getattr(sys, 'frozen', False) and len(sys.argv) == 1:
    # Running as bundled app with no arguments - launch UI directly
    print("Launching Cosine Companion UI...")
    from ui import run_ui
    run_ui()
    sys.exit(0)

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
    from processing.pipeline import index_library
    index_library(xml, force_full=force, sample_size=sample)


@cli.command()
def ui():
    """Open the minimal UI (manual 'Set Current' for v1)."""
    from ui import run_ui
    run_ui()


@cli.command()
def clean_duplicates(
    xml: str = typer.Argument(..., help="Path to Rekordbox XML export")
):
    """Analyze duplicate tracks in your collection using fast file-based detection."""
    # Lazy imports to avoid loading heavy dependencies
    from core.duplicates import remove_simple_duplicates
    from processing.xml_parser import read_rekordbox_xml
    
    print("🧹 Cosine Companion - Duplicate Analyzer")
    print("=" * 50)
    
    # Read XML
    print("📖 Reading Rekordbox XML...")
    current_meta = read_rekordbox_xml(xml)
    print(f"   Found {len(current_meta)} tracks in XML")
    
    if len(current_meta) < 2:
        print("✅ Not enough tracks to check for duplicates.")
        return
    
    print("🔍 Analyzing duplicates using file size and metadata...")
    cleaned_meta, duplicates_info = remove_simple_duplicates(current_meta)
    
    if duplicates_info["removed_count"] > 0:
        print(f"\n✨ Found {duplicates_info['removed_count']} duplicate tracks!")
        print(f"   Your collection would have {len(cleaned_meta)} unique tracks after cleaning")
        
        if duplicates_info["details"]:
            print("\n📋 Duplicates found:")
            for detail in duplicates_info["details"]:
                print(f"   • {detail}")
        
        print(f"\n💡 These duplicates will be automatically removed during indexing.")
        print(f"   Just run: python src/dj_companion.py index {xml}")
    else:
        print("✅ No duplicates found in your collection!")
        print("   Your collection is already clean.")


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