"""Dialog windows for DJ Companion UI."""

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
