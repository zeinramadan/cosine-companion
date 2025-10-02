#!/usr/bin/env python3
"""Icon utility for DJ Companion application."""

import sys
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk
import tempfile
import os


def get_icon_path():
    """Get the path to the app icon file."""
    # Try to find the icon in different locations
    possible_paths = [
        Path(__file__).parent.parent.parent / "assets" / "coco_logo_small.png",  # Development - smaller version
        Path(sys._MEIPASS) / "assets" / "coco_logo_small.png" if hasattr(sys, '_MEIPASS') else None,  # PyInstaller bundle
    ]
    
    for path in possible_paths:
        if path and path.exists():
            return path
    
    return None


def set_window_icon(window: tk.Tk | tk.Toplevel):
    """
    Set the window icon for a Tk window.
    
    Args:
        window: The Tk or Toplevel window to set the icon for
    """
    icon_path = get_icon_path()
    
    if not icon_path:
        # No icon file found, skip silently
        return
    
    try:
        # For macOS and Linux, use iconphoto with PNG
        if sys.platform in ('darwin', 'linux'):
            # Load the image (already sized appropriately)
            img = Image.open(icon_path)
            photo = ImageTk.PhotoImage(img)
            window.iconphoto(True, photo)
            # Keep a reference to prevent garbage collection
            window._icon_photo = photo
            
        # For Windows, try iconbitmap (requires .ico file)
        elif sys.platform == 'win32':
            ico_path = icon_path.parent / "coco_logo_small.ico"
            if ico_path.exists():
                window.iconbitmap(str(ico_path))
    except Exception as e:
        # Fail silently if icon can't be loaded
        print(f"Warning: Could not load app icon: {e}")

