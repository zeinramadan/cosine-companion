#!/usr/bin/env python3
"""Tkinter user interface for DJ Companion."""

from typing import Optional, List, Dict, Any
import time

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import pandas as pd

from recommendations import load_all, recommend_for
from set_creator import generate_set, search_tracks, SetTrack


class SimplePicker(tk.Toplevel):
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cosine Companion - Explore your taste")
        self.geometry("800x600")
        self.configure(padx=12, pady=12)

        self.meta, self.meta_ix, self.emb_ix, self.idx, self.V, self.ids = load_all()
        self.current_id: Optional[str] = None
        self.current_recommendations: List[Dict[str, Any]] = []
        
        # History tracking for back functionality
        self.history: List[Dict[str, Any]] = []  # List of {track_id, recommendations, sort_state}
        self.max_history = 20  # Limit history to prevent memory issues

        self.lbl_current = tk.Label(self, text="Current track: —", font=("Helvetica", 14, "bold"), anchor="w", justify="left")
        self.lbl_current.pack(fill="x")

        # Create tabbed interface
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, pady=8)
        
        # Create tabs
        self.create_recommendations_tab()
        self.create_set_creator_tab()

        self.status = tk.Label(self, text="💡 Tip: Double-click any suggestion to set it as current track", anchor="w", font=("Helvetica", 9), fg="gray")
        self.status.pack(fill="x")

    def create_recommendations_tab(self):
        """Create the recommendations tab with existing functionality."""
        rec_frame = ttk.Frame(self.notebook)
        self.notebook.add(rec_frame, text="AI Suggestions")
        
        # Main buttons
        btns = tk.Frame(rec_frame); btns.pack(fill="x", pady=8)
        tk.Button(btns, text="Set Current Track", command=self.pick_current).pack(side="left")
        tk.Button(btns, text="Copy Selected to Clipboard", command=self.copy_selected).pack(side="left", padx=8)
        tk.Button(btns, text="Set Selected as Current", command=self.set_selected_as_current).pack(side="left", padx=8)
        
        # Back button
        self.back_btn = tk.Button(btns, text="← Back", command=self.go_back, state="disabled")
        self.back_btn.pack(side="left", padx=8)

        # Sorting buttons
        sort_frame = tk.Frame(rec_frame); sort_frame.pack(fill="x", pady=4)
        tk.Label(sort_frame, text="Sort by:", font=("Helvetica", 10, "bold")).pack(side="left")
        tk.Button(sort_frame, text="Score", command=lambda: self.sort_suggestions("score")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="Cosine", command=lambda: self.sort_suggestions("cosine")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="Key", command=lambda: self.sort_suggestions("key")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="BPM", command=lambda: self.sort_suggestions("bpm")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="Artist", command=lambda: self.sort_suggestions("artist")).pack(side="left", padx=2)

        self.listbox = tk.Listbox(rec_frame, height=20)
        self.listbox.pack(fill="both", expand=True)
        
        # Add double-click event to set current track
        self.listbox.bind("<Double-Button-1>", self.on_suggestion_double_click)
        
        # Add right-click context menu
        self.setup_context_menu()
    
    def create_set_creator_tab(self):
        """Create the set creator tab."""
        set_frame = ttk.Frame(self.notebook)
        self.notebook.add(set_frame, text="Set Creator")
        
        # Set configuration
        config_frame = tk.Frame(set_frame); config_frame.pack(fill="x", pady=8)
        tk.Label(config_frame, text="Total Tracks:", font=("Helvetica", 10, "bold")).pack(side="left")
        self.total_tracks_var = tk.StringVar(value="10")
        tk.Entry(config_frame, textvariable=self.total_tracks_var, width=5).pack(side="left", padx=4)
        tk.Button(config_frame, text="Generate Set", command=self.generate_set_ui, bg="lightgreen").pack(side="left", padx=8)
        tk.Button(config_frame, text="Clear Set", command=self.clear_set).pack(side="left", padx=4)
        
        # Anchor tracks section
        anchor_frame = tk.Frame(set_frame); anchor_frame.pack(fill="x", pady=8)
        tk.Label(anchor_frame, text="Anchor Tracks:", font=("Helvetica", 10, "bold")).pack(side="left")
        tk.Button(anchor_frame, text="+ Add Anchor", command=self.add_anchor_track).pack(side="left", padx=8)
        
        # Anchor tracks list
        self.anchor_listbox = tk.Listbox(anchor_frame, height=4)
        self.anchor_listbox.pack(fill="x", expand=True, padx=(0, 80))
        tk.Button(anchor_frame, text="Remove", command=self.remove_anchor_track).pack(side="right")
        
        # Generated set
        tk.Label(set_frame, text="Generated Set:", font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(8, 4))
        self.set_listbox = tk.Listbox(set_frame, height=15)
        self.set_listbox.pack(fill="both", expand=True)
        
        # Set controls
        set_controls = tk.Frame(set_frame); set_controls.pack(fill="x", pady=4)
        tk.Button(set_controls, text="Export to Clipboard", command=self.export_set).pack(side="left")
        
        # Initialize data structures
        self.anchor_tracks: Dict[int, str] = {}  # position -> track_id
        self.generated_set: List[SetTrack] = []

    def setup_context_menu(self):
        """Setup right-click context menu for the suggestions list."""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Set as Current Track", command=self.set_selected_as_current)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy to Clipboard", command=self.copy_selected)
        
        # Bind right-click to show context menu
        self.listbox.bind("<Button-3>", self.show_context_menu)  # Right-click on Windows/Linux
        self.listbox.bind("<Button-2>", self.show_context_menu)  # Right-click on Mac

    def show_context_menu(self, event):
        """Show context menu on right-click."""
        # Select the item under cursor
        index = self.listbox.nearest(event.y)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        
        # Show context menu
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def on_suggestion_double_click(self, event):
        """Handle double-click on suggestion to set as current track."""
        selection = self.listbox.curselection()
        if selection:
            self.set_selected_as_current()

    def save_current_state_to_history(self):
        """Save the current state to history before changing tracks."""
        if self.current_id and self.current_recommendations:
            history_entry = {
                'track_id': self.current_id,
                'recommendations': self.current_recommendations.copy(),
                'timestamp': time.time()  # Fixed: use time.time() instead of tk.time.time()
            }
            
            # Add to history
            self.history.append(history_entry)
            
            # Limit history size
            if len(self.history) > self.max_history:
                self.history.pop(0)  # Remove oldest entry
            
            # Enable back button
            self.back_btn.config(state="normal")

    def go_back(self):
        """Go back to the previous track and recommendations."""
        if not self.history:
            return
        
        # Get the last history entry
        previous_state = self.history.pop()
        
        # Restore previous state
        self.current_id = previous_state['track_id']
        self.current_recommendations = previous_state['recommendations']
        
        # Update UI without saving to history (to avoid infinite back loop)
        self.update_current_track_display()
        self.update_listbox()
        
        # Update back button state
        if not self.history:
            self.back_btn.config(state="disabled")
        
        # Update status
        m = self.meta_ix.loc[self.current_id]
        self.status.config(text=f"↩️ Went back to '{m.get('artist','')} – {m.get('title','')}'", fg="blue")
        self.after(3000, lambda: self.status.config(text="💡 Tip: Double-click any suggestion to set it as current track", fg="gray"))

    def set_selected_as_current(self):
        """Set the selected suggestion as the current track."""
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showinfo("No Selection", "Please select a track from the suggestions list.")
            return
        
        if not self.current_recommendations:
            messagebox.showinfo("No Recommendations", "No recommendations available.")
            return
        
        selected_index = selection[0]
        if selected_index >= len(self.current_recommendations):
            messagebox.showerror("Error", "Invalid selection.")
            return
        
        # Get the track ID from the selected recommendation
        selected_track = self.current_recommendations[selected_index]
        track_id = selected_track['track_id']
        
        # Save current state to history before changing
        self.save_current_state_to_history()
        
        # Set as current track
        self.set_current(track_id, add_to_history=False)  # Don't add to history since we just saved it
        
        # Update status to show the change
        self.status.config(text=f"✅ Set '{selected_track['artist']} – {selected_track['title']}' as current track", fg="green")
        self.after(3000, lambda: self.status.config(text="💡 Tip: Double-click any suggestion to set it as current track", fg="gray"))

    def pick_current(self):
        query = simpledialog.askstring("Pick Current", "Search artist/title:")
        if not query:
            return
        q = query.lower()
        m = self.meta[(self.meta["artist"].str.lower().str.contains(q, na=False)) | (self.meta["title"].str.lower().str.contains(q, na=False))].head(50)
        if m.empty:
            messagebox.showinfo("No match", "Couldn't find any tracks.")
            return
        pick = SimplePicker(self, m[["artist", "title", "track_id"]])
        self.wait_window(pick)
        if pick.chosen is None:
            return
        
        # Save current state to history before changing (if we have a current track)
        if self.current_id:
            self.save_current_state_to_history()
        
        self.set_current(pick.chosen, add_to_history=False)

    def set_current(self, track_id: str, add_to_history: bool = True):
        """Set current track and refresh suggestions."""
        # Save current state to history if requested
        if add_to_history and self.current_id:
            self.save_current_state_to_history()
        
        self.current_id = track_id
        self.update_current_track_display()
        self.refresh_suggestions()

    def update_current_track_display(self):
        """Update the current track display label."""
        if self.current_id:
            m = self.meta_ix.loc[self.current_id]
            self.lbl_current.config(text=f"Current track: {m.get('artist','')} – {m.get('title','')}  [Key {m.get('key','?')}  BPM {m.get('bpm','?')}]")
        else:
            self.lbl_current.config(text="Current track: —")

    def refresh_suggestions(self):
        if not self.current_id:
            self.current_recommendations = []
            self.update_listbox()
            return
        
        # Get fresh recommendations
        self.current_recommendations = recommend_for(self.current_id, self.meta_ix, self.emb_ix, self.idx, final_top=20)
        self.update_listbox()

    def sort_suggestions(self, sort_by: str):
        """Sort current recommendations by the specified field."""
        if not self.current_recommendations:
            return
        
        # Define sort keys and reverse flags
        if sort_by == "score":
            key_func = lambda x: float(x.get('score', 0))
            reverse = True
        elif sort_by == "cosine":
            key_func = lambda x: float(x.get('cosine', 0))
            reverse = True
        elif sort_by == "key":
            key_func = lambda x: str(x.get('key', ''))
            reverse = False
        elif sort_by == "bpm":
            key_func = lambda x: float(x.get('bpm', 0) or 0)
            reverse = True
        elif sort_by == "artist":
            key_func = lambda x: str(x.get('artist', '')).lower()
            reverse = False
        else:
            return
        
        # Sort recommendations
        self.current_recommendations.sort(key=key_func, reverse=reverse)
        self.update_listbox()

    def update_listbox(self):
        """Update the listbox with current recommendations."""
        self.listbox.delete(0, tk.END)
        
        for r in self.current_recommendations:
            cosine = float(r.get('cosine', 0))
            score = float(r.get('score', 0))
            cos_pct = cosine * 100.0
            score_pct = max(0.0, min(1.0, score)) * 100.0
            line = f"{r['artist']} – {r['title']}   [Key {r['key'] or '?'}  BPM {r['bpm'] or '?'}  Cos {cos_pct:.1f}%  Score {score_pct:.1f}%]"
            self.listbox.insert(tk.END, line)
        
        suggestion_count = self.listbox.size()
        if suggestion_count > 0:
            history_info = f" ({len(self.history)} in history)" if self.history else ""
            self.status.config(text=f"{suggestion_count} suggestions{history_info} - 💡 Tip: Double-click any suggestion to set it as current track", fg="gray")
        else:
            self.status.config(text="No suggestions available", fg="gray")

    def copy_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        # Extract just the track title (after the separator)
        full_text = self.listbox.get(sel[0]).split("   [")[0]  # Get "Artist – Title" part
        
        # Try different separators in order of preference
        separators = [" – ", " | ", " - ", "|", "–", "-"]
        track_title = full_text  # Default fallback
        
        for separator in separators:
            if separator in full_text:
                track_title = full_text.split(separator, 1)[1].strip()  # Get everything after first separator
                break
        
        self.clipboard_clear()
        self.clipboard_append(track_title)
        self.update()

    # Set Creator methods
    def add_anchor_track(self):
        """Add an anchor track at a specific position."""
        dialog = AddAnchorDialog(self, self.meta_ix, self.anchor_tracks)
        self.wait_window(dialog)
        if dialog.result:
            position, track_id = dialog.result
            self.anchor_tracks[position] = track_id
            self.update_anchor_listbox()
    
    def remove_anchor_track(self):
        """Remove selected anchor track."""
        sel = self.anchor_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select an anchor track to remove.")
            return
        
        # Parse position from listbox item
        item_text = self.anchor_listbox.get(sel[0])
        try:
            position = int(item_text.split(".")[0])
            if position in self.anchor_tracks:
                del self.anchor_tracks[position]
                self.update_anchor_listbox()
        except (ValueError, IndexError):
            pass
    
    def update_anchor_listbox(self):
        """Update the anchor tracks display."""
        self.anchor_listbox.delete(0, tk.END)
        for position in sorted(self.anchor_tracks.keys()):
            track_id = self.anchor_tracks[position]
            if track_id in self.meta_ix.index:
                row = self.meta_ix.loc[track_id]
                display_name = f"{row.get('artist', '')} – {row.get('title', '')}"
                self.anchor_listbox.insert(tk.END, f"{position}. {display_name}")
    
    def generate_set_ui(self):
        """Generate a complete set with current anchor tracks."""
        try:
            total_tracks = int(self.total_tracks_var.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid number for total tracks.")
            return
        
        if not self.anchor_tracks:
            messagebox.showwarning("No Anchors", "Please add at least one anchor track before generating a set.")
            return
        
        if total_tracks < len(self.anchor_tracks):
            messagebox.showerror("Invalid Configuration", "Total tracks must be greater than the number of anchor tracks.")
            return
        
        try:
            self.status.config(text="🎵 Generating set... This may take a moment.")
            self.update()
            
            self.generated_set = generate_set(
                self.anchor_tracks, 
                total_tracks,
                self.meta_ix, 
                self.emb_ix, 
                self.idx
            )
            self.update_set_listbox()
            self.status.config(text=f"✅ Generated {len(self.generated_set)}-track set successfully!")
            
        except Exception as e:
            messagebox.showerror("Generation Error", f"Failed to generate set: {str(e)}")
            self.status.config(text="❌ Set generation failed.")
    
    def update_set_listbox(self):
        """Update the generated set display."""
        self.set_listbox.delete(0, tk.END)
        for track in self.generated_set:
            score_text = ""
            if not track.is_anchor and track.score > 0:
                score_text = f" ({track.score:.0%} match)"
            
            display_text = f"[{track.position:2d}] {track.icon} {track.display_name}{score_text}"
            self.set_listbox.insert(tk.END, display_text)
    
    def clear_set(self):
        """Clear all anchor tracks and generated set."""
        self.anchor_tracks.clear()
        self.generated_set.clear()
        self.update_anchor_listbox()
        self.update_set_listbox()
        self.status.config(text="🧹 Set cleared.")
    
    def export_set(self):
        """Export the generated set to clipboard."""
        if not self.generated_set:
            messagebox.showwarning("No Set", "Please generate a set first.")
            return
        
        # Create playlist text
        playlist_lines = []
        for track in self.generated_set:
            if track.display_name and "No suitable track found" not in track.display_name:
                playlist_lines.append(track.display_name)
        
        playlist_text = "\n".join(playlist_lines)
        self.clipboard_clear()
        self.clipboard_append(playlist_text)
        self.update()
        
        messagebox.showinfo("Exported", f"Copied {len(playlist_lines)} tracks to clipboard!")


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


def run_ui():
    app = App()
    app.mainloop()


