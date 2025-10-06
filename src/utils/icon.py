#!/usr/bin/env python3
"""Icon utility for Cosine Companion application."""

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
        # For macOS and Linux, use iconphoto with pre-scaled sizes for crisp, consistent icon
        if sys.platform in ('darwin', 'linux'):
            base_img = Image.open(icon_path)
            # Choose a small, consistent size to avoid large icon flashes on startup
            target_sizes = [16, 32, 64] if sys.platform == 'darwin' else [16, 32]
            photos = []
            for sz in target_sizes:
                resized = base_img.resize((sz, sz), Image.LANCZOS)
                photos.append(ImageTk.PhotoImage(resized))
            # Pass multiple sizes; Tk will pick best fit per scale factor
            window.iconphoto(True, *photos)
            # Keep references to prevent garbage collection
            window._icon_photos = photos
        
        # For Windows, try iconbitmap (requires .ico file)
        elif sys.platform == 'win32':
            ico_path = icon_path.parent / "coco_logo_small.ico"
            if ico_path.exists():
                window.iconbitmap(str(ico_path))
    except Exception as e:
        # Fail silently if icon can't be loaded
        print(f"Warning: Could not load app icon: {e}")

