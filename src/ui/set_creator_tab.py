"""Set Creator tab functionality for Cosine Companion UI."""

from typing import TYPE_CHECKING, Dict, List
import tkinter as tk
from tkinter import ttk, messagebox

from recommendations import generate_set, SetTrack
from ui.dialogs import AddAnchorDialog

if TYPE_CHECKING:
    from ui.app import App


class SetCreatorTabMixin:
    """Mixin class for set creator tab functionality."""
    
    def create_set_creator_tab(self: "App"):
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
        self.add_anchor_btn = tk.Button(anchor_frame, text="+ Add Anchor", command=self.add_anchor_track, 
                                       bg="lightgreen", font=("Helvetica", 10, "bold"), state="normal")
        
        # Reduce right padding so the hint sits closer to the button
        self.add_anchor_btn.pack(side="left", padx=(2, 2))
    
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
    
    def add_anchor_track(self: "App"):
        """Add an anchor track at a specific position."""
        dialog = AddAnchorDialog(self, self.meta_ix, self.anchor_tracks)
        self.wait_window(dialog)
        if dialog.result:
            position, track_id = dialog.result
            self.anchor_tracks[position] = track_id
            self.update_anchor_listbox()
    
    def remove_anchor_track(self: "App"):
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
    
    def update_anchor_listbox(self: "App"):
        """Update the anchor tracks display."""
        self.anchor_listbox.delete(0, tk.END)
        for position in sorted(self.anchor_tracks.keys()):
            track_id = self.anchor_tracks[position]
            if track_id in self.meta_ix.index:
                row = self.meta_ix.loc[track_id]
                display_name = f"{row.get('artist', '')} – {row.get('title', '')}"
                self.anchor_listbox.insert(tk.END, f"{position}. {display_name}")
    
    def generate_set_ui(self: "App"):
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
    
    def update_set_listbox(self: "App"):
        """Update the generated set display."""
        self.set_listbox.delete(0, tk.END)
        for track in self.generated_set:
            score_text = ""
            if not track.is_anchor and track.score > 0:
                score_text = f" ({track.score:.0%} match)"
            
            display_text = f"[{track.position:2d}] {track.icon} {track.display_name}{score_text}"
            self.set_listbox.insert(tk.END, display_text)
    
    def clear_set(self: "App"):
        """Clear all anchor tracks and generated set."""
        self.anchor_tracks.clear()
        self.generated_set.clear()
        self.update_anchor_listbox()
        self.update_set_listbox()
        self.status.config(text="🧹 Set cleared.")
    
    def export_set(self: "App"):
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
