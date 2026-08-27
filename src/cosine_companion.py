#!/usr/bin/env python3
"""
Cosine Companion - Main application entry point.

A tool for finding similar tracks based on audio content, key compatibility,
and BPM matching. Uses Essentia's Discogs-EffNet embeddings and exact cosine search for
efficient similarity search.
"""

import os
import sys


WEB_FRONTEND = "web"
TK_FRONTEND = "tk"

# This is the entire default-frontend switch. Both the frozen no-argument path
# and the generic `ui` command go through it; changing this one identifier back
# to TK_FRONTEND restores the previous default without removing either UI.
DEFAULT_FRONTEND = WEB_FRONTEND


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


def _native_launch_dialog(title, message, *, error=False):
    """Show a native dialog for a frozen launch that has no terminal."""
    try:
        from tkinter import messagebox

        show = messagebox.showerror if error else messagebox.showwarning
        show(title, message)
    except Exception as dialog_error:  # noqa: BLE001 - use an OS-level fallback
        # If Tk itself is the reason both frontends failed, its messagebox is
        # unavailable too. macOS still provides Standard Additions through
        # osascript, so the final explanation need not disappear with Tk.
        if sys.platform == 'darwin':
            try:
                import subprocess

                style = "critical" if error else "warning"
                script = (
                    "on run argv\n"
                    "display alert (item 1 of argv) message (item 2 of argv) "
                    f"as {style}\n"
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
            except Exception as os_dialog_error:  # noqa: BLE001 - last resort
                _diagnostic(
                    "Could not show either native launch error dialog "
                    f"({_failure_details(os_dialog_error)})"
                )
                return

        _diagnostic(
            "Could not show the launch error dialog "
            f"({_failure_details(dialog_error)})"
        )


def _run_web_frontend(*, debug=False, data_dir=None):
    """Run only the web frontend, allowing startup errors to reach the caller."""
    from pathlib import Path

    from web.host import run_web_ui

    run_web_ui(data_dir=Path(data_dir) if data_dir else None, debug=debug)


def _run_tk_frontend():
    """Run only the retained Tkinter frontend."""
    from ui import run_ui

    run_ui()


def _failure_details(error):
    detail = str(error).strip()
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def _run_default_frontend(*, debug=False, data_dir=None):
    """Run the configured default, falling back to Tkinter if web cannot start."""
    if DEFAULT_FRONTEND == TK_FRONTEND:
        _run_tk_frontend()
        return
    if DEFAULT_FRONTEND != WEB_FRONTEND:  # pragma: no cover - developer error
        raise RuntimeError(f"Unknown default frontend: {DEFAULT_FRONTEND}")

    try:
        _run_web_frontend(debug=debug, data_dir=data_dir)
        return
    except Exception as web_error:  # noqa: BLE001 - every startup failure falls back
        web_details = _failure_details(web_error)
        message = (
            "The web interface could not start. Cosine Companion will open "
            "the classic interface instead.\n\n"
            f"Technical details: {web_details}"
        )
        _diagnostic(message)
        if _is_frozen_gui_launch():
            _native_launch_dialog("Cosine Companion", message)

    try:
        _run_tk_frontend()
    except Exception as tk_error:  # noqa: BLE001 - report the loss of both UIs
        message = (
            "Neither Cosine Companion interface could start.\n\n"
            f"Web interface: {web_details}\n"
            f"Classic interface: {_failure_details(tk_error)}"
        )
        _diagnostic(message)
        if _is_frozen_gui_launch():
            _native_launch_dialog("Cosine Companion could not start", message, error=True)
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
    # Running as a bundled app with no arguments: launch the default UI before
    # importing Typer. A web startup failure is visible and falls back to Tk.
    _run_default_frontend()
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
    """Open the default web UI, falling back to the classic UI if needed."""
    _run_default_frontend(debug=debug, data_dir=data_dir)


@cli.command("ui-tk")
def ui_tk():
    """Open the retained classic Tkinter UI directly."""
    _run_tk_frontend()


@cli.command("ui-web")
def ui_web(
    debug: bool = typer.Option(False, "--debug", help="Open with devtools enabled"),
    data_dir: str = typer.Option(None, "--data-dir", help="Index directory to open (default: the configured one)")
):
    """Open only the web UI (compatibility alias; no Tkinter fallback)."""
    try:
        _run_web_frontend(debug=debug, data_dir=data_dir)
    except Exception as error:  # noqa: BLE001 - turn startup failures into a clean CLI error
        install_hint = (
            "\nInstall it with:  pip install pywebview"
            if isinstance(error, ImportError)
            else ""
        )
        typer.echo(
            f"The web UI could not start ({_failure_details(error)})."
            f"{install_hint}",
            err=True,
        )
        raise typer.Exit(code=1)


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
    # Lazy imports throughout, matching the other subcommands: neither UI
    # should load playlist-import dependencies merely to open a window.
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
