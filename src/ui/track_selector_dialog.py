"""Track selector dialog for playlist export."""

from typing import Optional, List, Set
import tkinter as tk
from tkinter import messagebox
import pandas as pd

from recommendations import search_tracks


class TrackSelectorDialog(tk.Toplevel):
    """Dialog for selecting multiple tracks for playlist export."""
    
    def __init__(self, parent, meta_ix: pd.DataFrame, already_selected: Set[str]):
        super().__init__(parent)
        self.title("Select Tracks for Playlist Export")
        self.geometry("600x550")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        
        self.meta_ix = meta_ix
        self.already_selected = already_selected
        self.result: Optional[List[str]] = None
        self.search_results = []
        
        # Search input
        search_frame = tk.Frame(self)
        search_frame.pack(fill="x", padx=15, pady=(15, 10))
        
        tk.Label(
            search_frame,
            text="Search for tracks:",
            font=("Helvetica", 11, "bold")
        ).pack(anchor="w", pady=(0, 5))
        
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.search_var, font=("Helvetica", 10))
        search_entry.pack(fill="x")
        search_entry.bind("<KeyRelease>", self.on_search_change)
        search_entry.focus()
        
        # Info label
        tk.Label(
            search_frame,
            text="💡 Ctrl+Click to select multiple • Shift+Click to select range",
            font=("Helvetica", 9),
            fg="gray"
        ).pack(anchor="w", pady=(5, 0))
        
        # Results listbox
        results_frame = tk.Frame(self)
        results_frame.pack(fill="both", expand=True, padx=15, pady=10)
        
        tk.Label(
            results_frame,
            text="Search Results:",
            font=("Helvetica", 10, "bold")
        ).pack(anchor="w", pady=(0, 5))
        
        # Scrollbar
        scrollbar = tk.Scrollbar(results_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        
        self.results_listbox = tk.Listbox(
            results_frame,
            height=20,
            selectmode=tk.EXTENDED,
            exportselection=False,
            yscrollcommand=scrollbar.set,
            font=("Helvetica", 10)
        )
        self.results_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.results_listbox.yview)
        
        # Selection count
        self.selection_label = tk.Label(
            self,
            text="0 tracks selected",
            font=("Helvetica", 9),
            fg="blue"
        )
        self.selection_label.pack(padx=15, pady=(0, 10))
        
        # Update selection count on change
        self.results_listbox.bind("<<ListboxSelect>>", self.update_selection_count)
        
        # Quick action buttons
        quick_frame = tk.Frame(self)
        quick_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        tk.Button(
            quick_frame,
            text="Select All",
            command=self.select_all,
            font=("Helvetica", 9)
        ).pack(side="left", padx=(0, 5))
        
        tk.Button(
            quick_frame,
            text="Clear Selection",
            command=self.clear_selection,
            font=("Helvetica", 9)
        ).pack(side="left")
        
        # Buttons
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        tk.Button(
            btn_frame,
            text="Cancel",
            command=self.destroy,
            font=("Helvetica", 10),
            padx=20,
            pady=5
        ).pack(side="right", padx=(5, 0))
        
        tk.Button(
            btn_frame,
            text="Add Selected Tracks",
            command=self.add_selected,
            bg="lightgreen",
            font=("Helvetica", 10, "bold"),
            padx=20,
            pady=5
        ).pack(side="right")
        
        # Initialize with all tracks
        self.update_search_results("")
        
        # Mark already selected tracks
        self.highlight_already_selected()
    
    def on_search_change(self, event=None):
        """Handle search input changes."""
        query = self.search_var.get()
        self.update_search_results(query)
        self.highlight_already_selected()
    
    def update_search_results(self, query: str):
        """Update search results based on query."""
        self.results_listbox.delete(0, tk.END)
        
        # Get results (shows more tracks if query is empty)
        limit = 100 if not query else 50
        self.search_results = search_tracks(query, self.meta_ix, limit=limit)
        
        for result in self.search_results:
            track_id = result["track_id"]
            display = result["display_name"]
            
            # Add marker if already selected
            if track_id in self.already_selected:
                display = "✓ " + display
            
            self.results_listbox.insert(tk.END, display)
    
    def highlight_already_selected(self):
        """Highlight tracks that are already selected."""
        # This is done by adding ✓ prefix in update_search_results
        pass
    
    def update_selection_count(self, event=None):
        """Update the selection count label."""
        count = len(self.results_listbox.curselection())
        if count == 0:
            self.selection_label.config(text="0 tracks selected", fg="gray")
        elif count == 1:
            self.selection_label.config(text="1 track selected", fg="blue")
        else:
            self.selection_label.config(text=f"{count} tracks selected", fg="blue")
    
    def select_all(self):
        """Select all visible tracks."""
        self.results_listbox.selection_set(0, tk.END)
        self.update_selection_count()
    
    def clear_selection(self):
        """Clear selection."""
        self.results_listbox.selection_clear(0, tk.END)
        self.update_selection_count()
    
    def add_selected(self):
        """Add the selected tracks."""
        sel = self.results_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select at least one track.")
            return
        
        # Get selected track IDs
        selected_track_ids = [self.search_results[i]["track_id"] for i in sel]
        self.result = selected_track_ids
        self.destroy()

