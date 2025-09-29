#!/usr/bin/env python3
"""Tkinter user interface for DJ Companion."""

from typing import Optional, List, Dict, Any
import time

import tkinter as tk
from tkinter import simpledialog, messagebox
import pandas as pd

from recommendations import load_all, recommend_for


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

        # Main buttons
        btns = tk.Frame(self); btns.pack(fill="x", pady=8)
        tk.Button(btns, text="Set Current Track", command=self.pick_current).pack(side="left")
        tk.Button(btns, text="Copy Selected to Clipboard", command=self.copy_selected).pack(side="left", padx=8)
        tk.Button(btns, text="Set Selected as Current", command=self.set_selected_as_current).pack(side="left", padx=8)
        
        # Back button
        self.back_btn = tk.Button(btns, text="← Back", command=self.go_back, state="disabled")
        self.back_btn.pack(side="left", padx=8)

        # Sorting buttons
        sort_frame = tk.Frame(self); sort_frame.pack(fill="x", pady=4)
        tk.Label(sort_frame, text="Sort by:", font=("Helvetica", 10, "bold")).pack(side="left")
        tk.Button(sort_frame, text="Score", command=lambda: self.sort_suggestions("score")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="Cosine", command=lambda: self.sort_suggestions("cosine")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="Key", command=lambda: self.sort_suggestions("key")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="BPM", command=lambda: self.sort_suggestions("bpm")).pack(side="left", padx=2)
        tk.Button(sort_frame, text="Artist", command=lambda: self.sort_suggestions("artist")).pack(side="left", padx=2)

        self.listbox = tk.Listbox(self, height=20)
        self.listbox.pack(fill="both", expand=True)
        
        # Add double-click event to set current track
        self.listbox.bind("<Double-Button-1>", self.on_suggestion_double_click)
        
        # Add right-click context menu
        self.setup_context_menu()

        self.status = tk.Label(self, text="💡 Tip: Double-click any suggestion to set it as current track", anchor="w", font=("Helvetica", 9), fg="gray")
        self.status.pack(fill="x")

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


def run_ui():
    app = App()
    app.mainloop()


