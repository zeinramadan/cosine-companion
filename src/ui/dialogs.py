"""Dialog windows for Cosine Companion UI."""

from typing import Optional, Dict
import tkinter as tk
from tkinter import messagebox
import pandas as pd

from recommendations import search_tracks


class SimplePicker(tk.Toplevel):
    """Simple dialog for picking a track from search results."""
    
    def __init__(self, master, df: pd.DataFrame):
        super().__init__(master)
        self.title("Choose Track")
        self.geometry("560x420")
        self.chosen = None
        self.df = df.reset_index(drop=True)

        lb = tk.Listbox(self, height=20)
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        for _, r in self.df.iterrows():
            lb.insert(tk.END, f"{r['artist']} – {r['title']}")
        btn = tk.Button(self, text="Select", command=lambda: self._done(lb.curselection()))
        btn.pack(pady=6)

    def _done(self, sel):
        if sel:
            self.chosen = self.df.loc[sel[0], "track_id"]
        self.destroy()


class AddAnchorDialog(tk.Toplevel):
    """Dialog for adding an anchor track at a specific position."""
    
    def __init__(self, parent, meta_ix: pd.DataFrame, existing_anchors: Dict[int, str]):
        super().__init__(parent)
        self.title("Add Anchor Track")
        self.geometry("500x500")  # Made taller to show all elements
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        
        self.meta_ix = meta_ix
        self.existing_anchors = existing_anchors
        self.result = None
        
        # Position input
        pos_frame = tk.Frame(self); pos_frame.pack(fill="x", padx=10, pady=10)
        tk.Label(pos_frame, text="Position in Set:", font=("Helvetica", 10, "bold")).pack(side="left")
        self.position_var = tk.StringVar()
        tk.Entry(pos_frame, textvariable=self.position_var, width=5).pack(side="left", padx=4)
        
        # Search input
        search_frame = tk.Frame(self); search_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(search_frame, text="Search for Track:", font=("Helvetica", 10, "bold")).pack(anchor="w")
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(fill="x", pady=2)
        search_entry.bind("<KeyRelease>", self.on_search_change)
        
        # Results listbox
        tk.Label(self, text="Search Results:", font=("Helvetica", 10, "bold")).pack(anchor="w", padx=10)
        self.results_listbox = tk.Listbox(self, height=15)
        self.results_listbox.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Add double-click support
        self.results_listbox.bind("<Double-Button-1>", self.on_double_click)
        
        # Buttons
        btn_frame = tk.Frame(self); btn_frame.pack(fill="x", padx=10, pady=10)
        tk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right")
        tk.Button(btn_frame, text="Add to Set", command=self.add_selected, bg="lightgreen").pack(side="right", padx=5)
        
        # Initialize with some tracks
        self.update_search_results("")
    
    def on_search_change(self, event=None):
        """Handle search input changes."""
        query = self.search_var.get()
        self.update_search_results(query)
    
    def update_search_results(self, query: str):
        """Update search results based on query."""
        self.results_listbox.delete(0, tk.END)
        
        results = search_tracks(query, self.meta_ix, limit=50)
        for result in results:
            self.results_listbox.insert(tk.END, result["display_name"])
        
        # Store results for selection
        self.search_results = results
    
    def on_double_click(self, event=None):
        """Handle double-click on search results - same as clicking Add to Set."""
        self.add_selected()
    
    def add_selected(self):
        """Add the selected track as an anchor."""
        sel = self.results_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a track.")
            return
        
        try:
            position = int(self.position_var.get())
        except ValueError:
            messagebox.showerror("Invalid Position", "Please enter a valid position number.")
            return
        
        if position < 1:
            messagebox.showerror("Invalid Position", "Position must be 1 or greater.")
            return
        
        if position in self.existing_anchors:
            if not messagebox.askyesno("Position Taken", f"Position {position} already has an anchor track. Replace it?"):
                return
        
        selected_result = self.search_results[sel[0]]
        self.result = (position, selected_result["track_id"])
        self.destroy()


class DeletedTracksDialog(tk.Toplevel):
    """Dialog for managing deleted tracks."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Manage Deleted Tracks")
        self.geometry("700x500")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        
        # Set window icon
        from utils.icon import set_window_icon
        set_window_icon(self)
        
        # Load deleted tracks and metadata
        self.load_data()
        
        # Create UI
        self.create_ui()
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (350)
        y = (self.winfo_screenheight() // 2) - (250)
        self.geometry(f"700x500+{x}+{y}")
        
        # Force window to show on macOS
        self.deiconify()
        self.lift()
        self.focus_force()
    
    def load_data(self):
        """Load deleted tracks with their stored metadata."""
        from core.deleted_tracks import load_deleted_tracks_with_info
        
        # Load deleted tracks with metadata already stored
        self.track_info = load_deleted_tracks_with_info()
        self.deleted_track_ids = set(self.track_info.keys())
    
    def create_ui(self):
        """Create the dialog UI."""
        # Header
        header = tk.Label(
            self,
            text=f"Deleted Tracks ({len(self.deleted_track_ids)})",
            font=("Helvetica", 14, "bold"),
            pady=10
        )
        header.pack()
        
        # Info label
        tk.Label(
            self,
            text="Select tracks to restore (they'll be re-added during next library update)",
            font=("Helvetica", 10),
            fg="gray"
        ).pack(pady=(0, 10))
        
        # Listbox frame with scrollbar
        list_frame = tk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,  # Allow multi-select
            yscrollcommand=scrollbar.set,
            font=("Helvetica", 10)
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        
        # Populate listbox
        self.track_id_list = []  # Keep track of order
        for track_id in sorted(self.deleted_track_ids):
            info = self.track_info[track_id]
            display = f"{info['artist']} – {info['title']}"
            self.listbox.insert(tk.END, display)
            self.track_id_list.append(track_id)
        
        # Selection info
        self.selection_label = tk.Label(
            self,
            text="Select tracks using Ctrl+Click or Shift+Click",
            font=("Helvetica", 9),
            fg="gray"
        )
        self.selection_label.pack(pady=(0, 10))
        
        # Buttons
        button_frame = tk.Frame(self)
        button_frame.pack(pady=10)
        
        tk.Button(
            button_frame,
            text="Remove Selected from Deleted List",
            command=self.remove_selected,
            font=("Helvetica", 11, "bold"),
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            button_frame,
            text="Close",
            command=self.destroy,
            font=("Helvetica", 11),
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=5)
    
    def remove_selected(self):
        """Remove selected tracks from the deleted list."""
        from core.deleted_tracks import remove_from_deleted_tracks
        
        selected_indices = self.listbox.curselection()
        
        if not selected_indices:
            messagebox.showwarning(
                "No Selection",
                "Please select one or more tracks to remove from the deleted list."
            )
            return
        
        # Get selected track IDs
        selected_track_ids = {self.track_id_list[i] for i in selected_indices}
        
        # Confirm
        result = messagebox.askyesno(
            "Remove from Deleted List",
            f"Remove {len(selected_track_ids)} track(s) from the deleted list?\n\n"
            "These tracks will be re-added during the next library update."
        )
        
        if result:
            # Remove selected tracks
            remove_from_deleted_tracks(selected_track_ids)
            
            messagebox.showinfo(
                "Tracks Removed",
                f"Removed {len(selected_track_ids)} track(s) from deleted list.\n\n"
                "Run 'Update Library' to restore these tracks."
            )
            
            # Reload and refresh display
            self.load_data()
            self.refresh_list()
    
    def refresh_list(self):
        """Refresh the listbox display."""
        self.listbox.delete(0, tk.END)
        self.track_id_list = []
        
        for track_id in sorted(self.deleted_track_ids):
            info = self.track_info[track_id]
            display = f"{info['artist']} – {info['title']}"
            self.listbox.insert(tk.END, display)
            self.track_id_list.append(track_id)
        
        # Update header
        for widget in self.winfo_children():
            if isinstance(widget, tk.Label) and "Deleted Tracks" in widget.cget("text"):
                widget.config(text=f"Deleted Tracks ({len(self.deleted_track_ids)})")
                break
