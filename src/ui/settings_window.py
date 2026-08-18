#!/usr/bin/env python3
"""Settings and library management window."""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime

from config import DATA, META_PQ
from services import SettingsStore


class SettingsWindow(tk.Toplevel):
    """Settings window for library management and preferences."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings - Cosine Companion")
        self.geometry("600x600")
        self.resizable(False, False)
        
        # Set window icon
        from utils.icon import set_window_icon
        set_window_icon(self)
        
        # Make it modal
        self.transient(parent)
        self.grab_set()
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (300)
        y = (self.winfo_screenheight() // 2) - (300)
        self.geometry(f"600x600+{x}+{y}")
        
        self.create_ui()
        self.load_settings()
        
        # Force window to show on macOS
        self.deiconify()
        self.lift()
        self.focus_force()
        self.update()
    
    def create_ui(self):
        """Create the settings UI."""
        # Header
        header = tk.Label(
            self,
            text="⚙️ Settings",
            font=("Helvetica", 18, "bold"),
            pady=15
        )
        header.pack()
        
        # Main content frame
        content = tk.Frame(self)
        content.pack(fill=tk.BOTH, expand=True, padx=30, pady=10)
        
        # Library Section
        self.create_library_section(content)
        
        # Separator
        ttk.Separator(content, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=20)
        
        # Index Statistics Section
        self.create_stats_section(content)
        
        # Separator
        ttk.Separator(content, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=20)
        
        # Deleted Tracks Section
        self.create_deleted_tracks_section(content)
        
        # Separator
        ttk.Separator(content, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=20)
        
        # Actions Section
        self.create_actions_section(content)
        
        # Close button
        tk.Button(
            self,
            text="Close",
            command=self.destroy,
            font=("Helvetica", 11),
            padx=40,
            pady=8
        ).pack(pady=15)
    
    def create_library_section(self, parent):
        """Create library configuration section."""
        section = tk.Frame(parent)
        section.pack(fill=tk.X, pady=5)
        
        tk.Label(
            section,
            text="Library Configuration",
            font=("Helvetica", 13, "bold")
        ).pack(anchor=tk.W, pady=(0, 10))
        
        # XML Path
        xml_frame = tk.Frame(section)
        xml_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(
            xml_frame,
            text="Rekordbox XML:",
            font=("Helvetica", 10, "bold"),
            width=15,
            anchor=tk.W
        ).pack(side=tk.LEFT)
        
        self.xml_path_label = tk.Label(
            xml_frame,
            text="Not set",
            font=("Helvetica", 9),
            fg="gray",
            anchor=tk.W
        )
        self.xml_path_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        tk.Button(
            xml_frame,
            text="Change",
            command=self.change_xml_path,
            font=("Helvetica", 9)
        ).pack(side=tk.RIGHT)
    
    def create_stats_section(self, parent):
        """Create index statistics section."""
        section = tk.Frame(parent)
        section.pack(fill=tk.X, pady=5)
        
        tk.Label(
            section,
            text="Library Statistics",
            font=("Helvetica", 13, "bold")
        ).pack(anchor=tk.W, pady=(0, 10))
        
        # Stats frame
        stats_frame = tk.Frame(section)
        stats_frame.pack(fill=tk.X)
        
        # Total tracks
        self.tracks_label = tk.Label(
            stats_frame,
            text="Total Tracks: Loading...",
            font=("Helvetica", 10),
            anchor=tk.W
        )
        self.tracks_label.pack(anchor=tk.W, pady=2)
        
        # Last indexed
        self.last_indexed_label = tk.Label(
            stats_frame,
            text="Last Indexed: Unknown",
            font=("Helvetica", 10),
            anchor=tk.W
        )
        self.last_indexed_label.pack(anchor=tk.W, pady=2)
        
        # Index size
        self.size_label = tk.Label(
            stats_frame,
            text="Index Size: Calculating...",
            font=("Helvetica", 10),
            anchor=tk.W
        )
        self.size_label.pack(anchor=tk.W, pady=2)
    
    def create_deleted_tracks_section(self, parent):
        """Create deleted tracks management section."""
        section = tk.Frame(parent)
        section.pack(fill=tk.X, pady=5)
        
        tk.Label(
            section,
            text="Deleted Tracks",
            font=("Helvetica", 13, "bold")
        ).pack(anchor=tk.W, pady=(0, 10))
        
        # Deleted tracks info
        self.deleted_tracks_label = tk.Label(
            section,
            text="Deleted Tracks: Loading...",
            font=("Helvetica", 10),
            anchor=tk.W
        )
        self.deleted_tracks_label.pack(anchor=tk.W, pady=2)
        
        # Description
        tk.Label(
            section,
            text="Deleted tracks won't be re-added during re-indexing",
            font=("Helvetica", 9),
            fg="gray",
            anchor=tk.W
        ).pack(anchor=tk.W, pady=(0, 10))
        
        # Manage buttons
        manage_frame = tk.Frame(section)
        manage_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(
            manage_frame,
            text="Manage Deleted Tracks...",
            command=self.manage_deleted_tracks,
            font=("Helvetica", 10),
            padx=15,
            pady=6
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Button(
            manage_frame,
            text="Clear All",
            command=self.clear_all_deleted_tracks,
            font=("Helvetica", 10),
            padx=15,
            pady=6
        ).pack(side=tk.LEFT)
    
    def create_actions_section(self, parent):
        """Create actions section."""
        section = tk.Frame(parent)
        section.pack(fill=tk.X, pady=5)
        
        tk.Label(
            section,
            text="Library Actions",
            font=("Helvetica", 13, "bold")
        ).pack(anchor=tk.W, pady=(0, 10))
        
        # Update/Re-index button
        update_frame = tk.Frame(section)
        update_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(
            update_frame,
            text="🔄 Update Library (Incremental)",
            command=self.update_library,
            font=("Helvetica", 11, "bold"),
            padx=15,
            pady=8
        ).pack(side=tk.LEFT)
        
        tk.Label(
            update_frame,
            text="  Process only new tracks",
            font=("Helvetica", 9),
            fg="gray"
        ).pack(side=tk.LEFT)
        
        # Full re-index button
        reindex_frame = tk.Frame(section)
        reindex_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(
            reindex_frame,
            text="🔄 Full Re-index",
            command=self.full_reindex,
            font=("Helvetica", 10),
            padx=15,
            pady=8
        ).pack(side=tk.LEFT)
        
        tk.Label(
            reindex_frame,
            text="  Reprocess entire library (slow)",
            font=("Helvetica", 9),
            fg="gray"
        ).pack(side=tk.LEFT)
    
    def load_settings(self):
        """Load and display current settings."""
        settings = SettingsStore(DATA / "settings.json")

        # Only an existing file repaints the label. When it is absent the label
        # keeps its grey "Not set" placeholder; when it exists without an
        # xml_path the same text is shown in black. Preserved deliberately.
        if settings.path.exists():
            xml_path = settings.get("xml_path", "Not set")

            # Truncate long path
            if len(xml_path) > 50:
                xml_path = "..." + xml_path[-47:]

            self.xml_path_label.config(text=xml_path, fg="black")

        
        # Load statistics
        self.load_statistics()
    
    def load_statistics(self):
        """Load and display index statistics."""
        try:
            # Count tracks
            if META_PQ.exists():
                import pandas as pd
                meta = pd.read_parquet(META_PQ)
                track_count = len(meta)
                self.tracks_label.config(text=f"Total Tracks: {track_count:,}")
                
                # Get last modified time
                mtime = META_PQ.stat().st_mtime
                last_indexed = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                self.last_indexed_label.config(text=f"Last Indexed: {last_indexed}")
            else:
                self.tracks_label.config(text="Total Tracks: 0")
                self.last_indexed_label.config(text="Last Indexed: Never")
            
            # Calculate total size
            total_size = 0
            for file in DATA.glob("*.parquet"):
                total_size += file.stat().st_size
            for file in DATA.glob("*.npy"):
                total_size += file.stat().st_size
            for file in DATA.glob("*.json"):
                total_size += file.stat().st_size
            
            size_mb = total_size / (1024 * 1024)
            self.size_label.config(text=f"Index Size: {size_mb:.1f} MB")
            
            # Load deleted tracks count
            from core.deleted_tracks import load_deleted_tracks_with_info
            deleted_tracks = load_deleted_tracks_with_info()
            deleted_count = len(deleted_tracks)
            self.deleted_tracks_label.config(text=f"Deleted Tracks: {deleted_count:,}")
            
        except Exception as e:
            print(f"Error loading statistics: {e}")
    
    def change_xml_path(self):
        """Change the XML file path."""
        new_path = filedialog.askopenfilename(
            title="Select Rekordbox XML Export",
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")]
        )
        
        if new_path:
            # Update settings, merging into whatever is already there
            SettingsStore(DATA / "settings.json").set("xml_path", new_path)
            
            # Update display
            display_path = new_path
            if len(display_path) > 50:
                display_path = "..." + display_path[-47:]
            self.xml_path_label.config(text=display_path, fg="black")
            
            messagebox.showinfo(
                "XML Path Updated",
                "XML file path has been updated. Click 'Update Library' to process any new tracks."
            )
    
    def manage_deleted_tracks(self):
        """Open dialog to manage deleted tracks."""
        from ui.dialogs import DeletedTracksDialog
        
        dialog = DeletedTracksDialog(self)
        self.wait_window(dialog)
        # Reload statistics in case tracks were removed
        self.load_statistics()
    
    def clear_all_deleted_tracks(self):
        """Clear all deleted tracks at once."""
        from core.deleted_tracks import load_deleted_tracks_with_info, save_deleted_tracks_with_info
        
        deleted_tracks = load_deleted_tracks_with_info()
        
        if not deleted_tracks:
            messagebox.showinfo(
                "No Deleted Tracks",
                "There are no deleted tracks to clear."
            )
            return
        
        # Confirm
        result = messagebox.askyesno(
            "Clear All Deleted Tracks",
            f"This will clear ALL {len(deleted_tracks)} deleted track(s) from the list.\n\n"
            "After clearing, running 'Update Library' will re-add these tracks if they're in your Rekordbox XML.\n\n"
            "Continue?"
        )
        
        if result:
            # Clear the list
            save_deleted_tracks_with_info({})
            messagebox.showinfo(
                "Deleted Tracks Cleared",
                f"Cleared {len(deleted_tracks)} deleted track(s).\n\n"
                "Run 'Update Library' to restore these tracks."
            )
            # Reload statistics to update display
            self.load_statistics()
    
    def update_library(self):
        """Trigger incremental library update."""
        from ui.reindex_window import ReindexWindow
        
        # Get XML path. The exists() check is kept because a missing file and an
        # existing file without an xml_path show *different* dialogs.
        settings = SettingsStore(DATA / "settings.json")
        if not settings.path.exists():
            messagebox.showerror(
                "No XML Path",
                "Please set your Rekordbox XML file path first."
            )
            return

        xml_path = settings.xml_path
        
        if not xml_path or not Path(xml_path).exists():
            messagebox.showerror(
                "XML File Not Found",
                f"The XML file could not be found:\n{xml_path}\n\nPlease update the path in settings."
            )
            return
        
        # Close settings and show reindex window
        self.destroy()
        ReindexWindow(self.master, xml_path, force_full=False)
    
    def full_reindex(self):
        """Trigger full library re-index."""
        from ui.reindex_window import ReindexWindow
        
        # Confirm
        result = messagebox.askyesno(
            "Confirm Full Re-index",
            "This will reprocess your entire library, which may take a while.\n\n"
            "Only do this if you're experiencing issues.\n\n"
            "Continue?"
        )
        
        if not result:
            return
        
        # Get XML path. The exists() check is kept because a missing file and an
        # existing file without an xml_path show *different* dialogs.
        settings = SettingsStore(DATA / "settings.json")
        if not settings.path.exists():
            messagebox.showerror(
                "No XML Path",
                "Please set your Rekordbox XML file path first."
            )
            return

        xml_path = settings.xml_path
        
        if not xml_path or not Path(xml_path).exists():
            messagebox.showerror(
                "XML File Not Found",
                f"The XML file could not be found:\n{xml_path}\n\nPlease update the path in settings."
            )
            return
        
        # Close settings and show reindex window
        self.destroy()
        ReindexWindow(self.master, xml_path, force_full=True)
