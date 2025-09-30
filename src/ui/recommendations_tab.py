"""Recommendations tab functionality for DJ Companion UI."""

from typing import TYPE_CHECKING
import time
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

from ui.dialogs import SimplePicker

if TYPE_CHECKING:
    from ui.app import App


class RecommendationsTabMixin:
    """Mixin class for recommendations tab functionality."""
    
    def create_recommendations_tab(self: "App"):
        """Create the recommendations tab with existing functionality."""
        rec_frame = ttk.Frame(self.notebook)
        self.notebook.add(rec_frame, text="Explore")

        # Buttons row: left-aligned Back, centered actions
        btns = tk.Frame(rec_frame); btns.pack(fill="x", pady=8)

        # Left: Back button
        left_btns = tk.Frame(btns)
        left_btns.pack(side="left")
        self.back_btn = tk.Button(left_btns, text="← Back", command=self.go_back, state="disabled")
        self.back_btn.pack(side="left", padx=8)

        # Center: action buttons (centered using expanding spacers)
        center_btns = tk.Frame(btns)
        center_btns.pack(side="left", expand=True, fill="x")
        tk.Frame(center_btns).pack(side="left", expand=True)
        tk.Button(center_btns, text="Set Current Track", command=self.pick_current).pack(side="left", padx=6)
        tk.Button(center_btns, text="Copy Selected to Clipboard", command=self.copy_selected).pack(side="left", padx=6)
        tk.Button(center_btns, text="Set Selected as Current", command=self.set_selected_as_current).pack(side="left", padx=6)
        tk.Frame(center_btns).pack(side="left", expand=True)

        # Right spacer to visually balance the left Back button and shift center group slightly left
        tk.Frame(btns, width=90).pack(side="right")

        # Sorting + Top-N container
        sort_frame = tk.Frame(rec_frame); sort_frame.pack(fill="x", pady=4)

        # Left: sorting buttons
        sort_left = tk.Frame(sort_frame)
        sort_left.pack(side="left")
        tk.Label(sort_left, text="Sort by:", font=("Helvetica", 10, "bold")).pack(side="left")
        tk.Button(sort_left, text="Score", command=lambda: self.sort_suggestions("score")).pack(side="left", padx=2)
        tk.Button(sort_left, text="Cosine", command=lambda: self.sort_suggestions("cosine")).pack(side="left", padx=2)
        tk.Button(sort_left, text="Key", command=lambda: self.sort_suggestions("key")).pack(side="left", padx=2)
        tk.Button(sort_left, text="BPM", command=lambda: self.sort_suggestions("bpm")).pack(side="left", padx=2)
        tk.Button(sort_left, text="Artist", command=lambda: self.sort_suggestions("artist")).pack(side="left", padx=2)

        # Right: Top-N in bordered rectangle
        sort_right = tk.Frame(sort_frame)
        sort_right.pack(side="right")
        tk.Label(sort_right, text="Top:", font=("Helvetica", 10, "bold")).pack(side="left", padx=(0, 6))
        self.topn_var = tk.StringVar(value="50")
        topn_box = ttk.Combobox(sort_right, textvariable=self.topn_var, values=["10", "20", "30", "50", "100"], width=5, state="readonly")
        topn_box.pack(side="left")
        topn_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_suggestions())

        self.listbox = tk.Listbox(rec_frame, height=20)
        self.listbox.pack(fill="both", expand=True)
        
        # Add double-click event to set current track
        self.listbox.bind("<Double-Button-1>", self.on_suggestion_double_click)
        
        # Add right-click context menu
        self.setup_context_menu()
    
    def setup_context_menu(self: "App"):
        """Setup right-click context menu for the suggestions list."""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Set as Current Track", command=self.set_selected_as_current)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy to Clipboard", command=self.copy_selected)
        
        # Bind right-click to show context menu
        self.listbox.bind("<Button-3>", self.show_context_menu)  # Right-click on Windows/Linux
        self.listbox.bind("<Button-2>", self.show_context_menu)  # Right-click on Mac

    def show_context_menu(self: "App", event):
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

    def on_suggestion_double_click(self: "App", event):
        """Handle double-click on suggestion to set as current track."""
        selection = self.listbox.curselection()
        if selection:
            self.set_selected_as_current()

    def save_current_state_to_history(self: "App"):
        """Save the current state to history before changing tracks."""
        if self.current_id and self.current_recommendations:
            history_entry = {
                'track_id': self.current_id,
                'recommendations': self.current_recommendations.copy(),
                'timestamp': time.time()
            }
            
            # Add to history
            self.history.append(history_entry)
            
            # Limit history size
            if len(self.history) > self.max_history:
                self.history.pop(0)  # Remove oldest entry
            
            # Enable back button
            self.back_btn.config(state="normal")

    def go_back(self: "App"):
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

    def set_selected_as_current(self: "App"):
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

    def pick_current(self: "App"):
        """Pick a current track using search dialog."""
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

    def set_current(self: "App", track_id: str, add_to_history: bool = True):
        """Set current track and refresh suggestions."""
        # Save current state to history if requested
        if add_to_history and self.current_id:
            self.save_current_state_to_history()
        
        self.current_id = track_id
        self.update_current_track_display()
        self.refresh_suggestions()

    def update_current_track_display(self: "App"):
        """Update the current track display label."""
        if self.current_id:
            m = self.meta_ix.loc[self.current_id]
            self.lbl_current.config(text=f"Current track: {m.get('artist','')} – {m.get('title','')}  [Key {m.get('key','?')}  BPM {m.get('bpm','?')}]")
        else:
            self.lbl_current.config(text="Current track: —")

    def refresh_suggestions(self: "App"):
        """Refresh recommendations for the current track."""
        from recommendations import recommend_for
        
        if not self.current_id:
            self.current_recommendations = []
            self.update_listbox()
            return
        
        # Get fresh recommendations
        try:
            topn = int(getattr(self, 'topn_var', tk.StringVar(value="50")).get())
        except Exception:
            topn = 50
        self.current_recommendations = recommend_for(self.current_id, self.meta_ix, self.emb_ix, self.idx, final_top=topn)
        self.update_listbox()

    def sort_suggestions(self: "App", sort_by: str):
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

    def update_listbox(self: "App"):
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

    def copy_selected(self: "App"):
        """Copy selected track title to clipboard."""
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
