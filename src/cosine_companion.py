#!/usr/bin/env python3
"""
Cosine Companion - Main application entry point.

A tool for finding similar tracks based on audio content, key compatibility,
and BPM matching. Uses Essentia's Discogs-EffNet embeddings and exact cosine search for
efficient similarity search.
"""

import os
import sys

# Note: For frozen executables on macOS, SDL and OpenMP env vars are set by the
# wrapper script (macos_launcher.sh) BEFORE the binary is loaded, which is necessary
# to prevent SDL from initializing GUI components that cause crashes.
# For development and non-macOS frozen builds, set them here:
if not getattr(sys, 'frozen', False) or (getattr(sys, 'frozen', False) and sys.platform != 'darwin'):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("SDL_RENDER_DRIVER", "software")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")

# Check if running as frozen executable in GUI mode
# On macOS when launched from Finder, LaunchServices passes a '-psn_*' arg.
# Treat that the same as no-arg GUI launch.
if getattr(sys, 'frozen', False) and (
    len(sys.argv) == 1 or (sys.platform == 'darwin' and len(sys.argv) == 2 and sys.argv[1].startswith('-psn_'))
):
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
    """Index your library: parse XML and embed audio (incremental by default)."""
    from config import DATA
    from processing.pipeline import index_library
    index_library(
        xml, data_dir=DATA, force_full=force, sample_size=sample
    )


@cli.command()
def ui():
    """Open the minimal UI (manual 'Set Current' for v1)."""
    from ui import run_ui
    run_ui()


@cli.command("ui-web")
def ui_web(
    debug: bool = typer.Option(False, "--debug", help="Open with devtools enabled"),
    data_dir: str = typer.Option(None, "--data-dir", help="Index directory to open (default: the configured one)")
):
    """EXPERIMENTAL: open the web UI in a pywebview window (Tkinter is still the default)."""
    # Imported here, not at module scope: this is the only path that needs
    # pywebview, and `ui` must keep launching Tkinter on a machine that does
    # not have it installed.
    try:
        from web.host import run_web_ui
    except ImportError as error:
        typer.echo(
            f"The web UI needs pywebview ({error}).\n"
            "Install it with:  pip install pywebview",
            err=True,
        )
        raise typer.Exit(code=1)

    from pathlib import Path
    run_web_ui(data_dir=Path(data_dir) if data_dir else None, debug=debug)


@cli.command("import-playlists")
def import_playlists_command(
    xml: str = typer.Argument(None, help="Path to Rekordbox XML export (default: the configured one)"),
    data_dir: str = typer.Option(None, "--data-dir", help="Index directory to write to (default: the configured one)")
):
    """Import Rekordbox playlists WITHOUT re-running the embedding pipeline.

    A full reindex already refreshes the playlist tables, but it costs ~12
    minutes of audio embedding. Seeing which playlists a track is in should not
    cost that, so this command exists and does only the parse and the two
    parquet writes - a second or so on a 1.5 MB export.

    With no argument it reads ``xml_path`` out of the same ``settings.json``
    the Tkinter app and the web UI use (``ui/app.py:185``), so the three agree
    about which export is current.

    ``--data-dir`` names the index directory to write into, matching
    ``ui-web --data-dir`` - including where ``settings.json`` is looked up, so
    "import into that directory" means the same thing to both commands. It is
    also what lets the concurrency tests run the real command against a
    scratch directory instead of the developer's library.
    """
    # Lazy imports throughout, matching the other subcommands: `ui` must keep
    # launching on a machine where these are not needed.
    from pathlib import Path

    from config import DATA
    from services.playlist_import import import_playlists
    from services.settings_store import SettingsStore

    target = Path(data_dir) if data_dir else DATA

    if xml is None:
        xml = SettingsStore(target / "settings.json").xml_path
        if not xml:
            typer.echo(
                "No Rekordbox XML is configured. Pass one:\n"
                "  python src/cosine_companion.py import-playlists <rekordbox.xml>",
                err=True,
            )
            raise typer.Exit(code=1)

    source = Path(xml)
    if not source.is_file():
        typer.echo(f"No such Rekordbox XML: {source}", err=True)
        raise typer.Exit(code=1)

    print("🗂  Cosine Companion - Playlist Import")
    print("=" * 50)
    print(f"📖 Reading {source.name}...")

    summary = import_playlists(source, data_dir=target)

    for line in summary.lines():
        print(line)
    print("=" * 50)
    print(f"✅ Playlists imported to: {target}/")


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
