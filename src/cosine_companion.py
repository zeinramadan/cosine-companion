#!/usr/bin/env python3
"""
Cosine Companion - Main application entry point.

A tool for finding similar tracks based on audio content, key compatibility,
and BPM matching. Uses Essentia's Discogs-EffNet embeddings and exact cosine search for
efficient similarity search.
"""

import os
import sys


def _is_frozen_gui_launch():
    """Whether LaunchServices (or an equivalent no-arg launch) opened us."""
    return getattr(sys, 'frozen', False) and (
        len(sys.argv) == 1
        or (
            sys.platform == 'darwin'
            and len(sys.argv) == 2
            and sys.argv[1].startswith('-psn_')
        )
    )


def _diagnostic(message):
    """Write a launch diagnostic when a terminal exists.

    PyInstaller windowed applications may replace stderr with ``None``, so a
    diagnostic must never become a second startup failure.
    """
    try:
        if sys.stderr is not None:
            print(message, file=sys.stderr, flush=True)
    except Exception:
        pass


def _native_launch_dialog(title, message):
    """Show a platform-native error when a frozen app has no terminal."""
    try:
        if sys.platform == "darwin":
            import subprocess

            script = (
                "on run argv\n"
                "display alert (item 1 of argv) message (item 2 of argv) "
                "as critical\n"
                "end run"
            )
            subprocess.run(
                ["/usr/bin/osascript", "-e", script, title, message],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            return

        if sys.platform == "win32":
            import ctypes

            # MB_OK | MB_ICONERROR. MessageBoxW blocks until the user has seen
            # and dismissed the failure, which is exactly what a windowed app
            # with no stderr needs here.
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return

        _diagnostic("No native launch-error dialog is available on this platform.")
    except Exception as dialog_error:  # noqa: BLE001 - last visible fallback
        _diagnostic(
            "Could not show the native launch-error dialog "
            f"({_failure_details(dialog_error)})"
        )


def _run_web_frontend(*, debug=False, data_dir=None):
    """Run only the web frontend, allowing startup errors to reach the caller."""
    from pathlib import Path

    from web.host import run_web_ui

    run_web_ui(data_dir=Path(data_dir) if data_dir else None, debug=debug)


def _failure_details(error):
    detail = str(error).strip()
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def _run_default_frontend(*, debug=False, data_dir=None):
    """Run the web frontend and make startup failures visible before raising."""
    try:
        _run_web_frontend(debug=debug, data_dir=data_dir)
    except (Exception, SystemExit) as web_error:  # noqa: BLE001 - libraries may call sys.exit
        install_hint = (
            "\n\nInstall it with: pip install pywebview"
            if isinstance(web_error, ImportError)
            else ""
        )
        message = (
            "The Cosine Companion interface could not start.\n\n"
            f"Technical details: {_failure_details(web_error)}"
            f"{install_hint}"
        )
        _diagnostic(message)
        if _is_frozen_gui_launch():
            _native_launch_dialog("Cosine Companion could not start", message)
        raise

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
if _is_frozen_gui_launch():
    # Run before importing Typer. If startup fails, the native dialog above is
    # the only reliable output channel in a windowed double-click launch.
    try:
        _run_default_frontend(
            data_dir=os.environ.get("COSINE_COMPANION_DATA_DIR")
        )
    except (Exception, SystemExit):  # noqa: BLE001 - already reported above
        sys.exit(1)
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
def ui(
    debug: bool = typer.Option(False, "--debug", help="Open web devtools"),
    data_dir: str = typer.Option(None, "--data-dir", help="Index directory to open (default: the configured one)")
):
    """Open the web UI."""
    try:
        _run_default_frontend(debug=debug, data_dir=data_dir)
    except (Exception, SystemExit):  # noqa: BLE001 - details already printed
        raise typer.Exit(code=1) from None


@cli.command("ui-web")
def ui_web(
    debug: bool = typer.Option(False, "--debug", help="Open with devtools enabled"),
    data_dir: str = typer.Option(None, "--data-dir", help="Index directory to open (default: the configured one)")
):
    """Open the web UI (compatibility alias for ``ui``)."""
    ui(debug=debug, data_dir=data_dir)


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
    the web UI uses, so both commands agree about which export is current.

    ``--data-dir`` names the index directory to write into, matching
    ``ui-web --data-dir`` - including where ``settings.json`` is looked up, so
    "import into that directory" means the same thing to both commands. It is
    also what lets the concurrency tests run the real command against a
    scratch directory instead of the developer's library.
    """
    # Lazy imports throughout: the UI should not load playlist-import
    # dependencies merely to open a window.
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
