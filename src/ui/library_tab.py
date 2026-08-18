"""Library tab functionality for Cosine Companion UI."""

from typing import TYPE_CHECKING
import tkinter as tk
from tkinter import ttk, messagebox

if TYPE_CHECKING:
    from ui.app import App


class LibraryTabMixin:
    """Mixin class for library tab functionality."""
    
    def create_library_tab(self: "App"):
        """Create the library tab for browsing and managing all tracks."""
        lib_frame = ttk.Frame(self.notebook)
        self.notebook.add(lib_frame, text="Library")
        
        # Search and filter controls
        search_frame = tk.Frame(lib_frame); search_frame.pack(fill="x", pady=8)
        tk.Label(search_frame, text="Search:", font=("Helvetica", 10, "bold")).pack(side="left")
        self.library_search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.library_search_var, width=30)
        search_entry.pack(side="left", padx=4)
        search_entry.bind("<KeyRelease>", self.filter_library)
        
        tk.Button(search_frame, text="Clear", command=self.clear_library_search).pack(side="left", padx=4)
        tk.Button(search_frame, text="Refresh", command=self.refresh_library).pack(side="left", padx=4)
        
        # Library controls
        controls_frame = tk.Frame(lib_frame); controls_frame.pack(fill="x", pady=4)
        tk.Button(controls_frame, text="Delete Selected", command=self.delete_selected_tracks, bg="lightcoral").pack(side="left")
        tk.Button(controls_frame, text="Set as Current", command=self.set_library_selected_as_current).pack(side="left", padx=8)
        
        # Stats label
        self.library_stats_label = tk.Label(controls_frame, text="", font=("Helvetica", 9), fg="gray")
        self.library_stats_label.pack(side="right")
        
        # Library tracks listbox with scrollbar
        list_frame = tk.Frame(lib_frame)
        list_frame.pack(fill="both", expand=True)
        
        self.library_listbox = tk.Listbox(list_frame, height=20, selectmode=tk.EXTENDED, exportselection=False)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.config(command=self.library_listbox.yview)
        self.library_listbox.config(yscrollcommand=scrollbar.set)
        
        self.library_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Double-click to set as current
        self.library_listbox.bind("<Double-Button-1>", self.on_library_double_click)
        
        # Initialize library data
        self.library_tracks = []  # Full list of tracks
        self.filtered_library_tracks = []  # Filtered list for display
        self.refresh_library()

    def refresh_library(self: "App"):
        """Refresh the library with all indexed tracks."""
        try:
            # Get all tracks from metadata
            self.library_tracks = []
            for track_id, row in self.library.meta_ix.iterrows():
                self.library_tracks.append({
                    "track_id": track_id,
                    "artist": row.get("artist", ""),
                    "title": row.get("title", ""),
                    "album": row.get("album", ""),
                    "bpm": row.get("bpm", ""),
                    "key": row.get("key", ""),
                    "path_local": row.get("path_local", ""),
                    "display_name": f"{row.get('artist', '')} – {row.get('title', '')}"
                })
            
            # Sort by artist, then title
            self.library_tracks.sort(key=lambda x: (x["artist"].lower(), x["title"].lower()))
            
            # Apply current filter
            self.filter_library()
            
        except Exception as e:
            self.status.config(text=f"❌ Error loading library: {str(e)}")
    
    def filter_library(self: "App", event=None):
        """Filter library tracks based on search query."""
        query = self.library_search_var.get().lower()
        
        if not query:
            self.filtered_library_tracks = self.library_tracks.copy()
        else:
            self.filtered_library_tracks = [
                track for track in self.library_tracks
                if (query in track["artist"].lower() or 
                    query in track["title"].lower() or
                    query in track["album"].lower() or
                    query in track["key"].lower())
            ]
        
        self.update_library_display()
    
    def update_library_display(self: "App"):
        """Update the library listbox with filtered tracks."""
        self.library_listbox.delete(0, tk.END)
        
        for track in self.filtered_library_tracks:
            # Format: "Artist – Title [Key] (BPM)"
            key_bpm = []
            if track["key"]:
                key_bpm.append(f"[{track['key']}]")
            if track["bpm"]:
                key_bpm.append(f"({track['bpm']} BPM)")
            
            extra_info = " ".join(key_bpm)
            display_text = f"{track['display_name']} {extra_info}".strip()
            
            self.library_listbox.insert(tk.END, display_text)
        
        # Update stats
        total_tracks = len(self.library_tracks)
        shown_tracks = len(self.filtered_library_tracks)
        if total_tracks == shown_tracks:
            stats_text = f"{total_tracks} tracks"
        else:
            stats_text = f"{shown_tracks} of {total_tracks} tracks"
        self.library_stats_label.config(text=stats_text)
    
    def clear_library_search(self: "App"):
        """Clear the search filter."""
        self.library_search_var.set("")
        self.filter_library()
    
    def on_library_double_click(self: "App", event=None):
        """Handle double-click on library track."""
        self.set_library_selected_as_current()
    
    def set_library_selected_as_current(self: "App"):
        """Set the selected library track as current."""
        sel = self.library_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a track from the library.")
            return
        
        selected_track = self.filtered_library_tracks[sel[0]]
        track_id = selected_track["track_id"]
        
        self.current_id = track_id
        self.update_current_track_display()  # Use the proper display method with key/BPM
        self.refresh_suggestions()
        
        # Switch to recommendations tab to see suggestions
        self.notebook.select(0)  # Select first tab (recommendations)
    
    def delete_selected_tracks(self: "App"):
        """Delete selected tracks from the library with confirmation."""
        selections = self.library_listbox.curselection()
        if not selections:
            messagebox.showwarning("No Selection", "Please select tracks to delete.")
            return
        
        selected_tracks = [self.filtered_library_tracks[i] for i in selections]
        
        # Confirmation dialog
        if len(selected_tracks) == 1:
            track = selected_tracks[0]
            msg = f"Delete this track from your library?\n\n{track['display_name']}\n\nThis will remove it from recommendations but won't delete the audio file."
        else:
            msg = f"Delete {len(selected_tracks)} selected tracks from your library?\n\nThis will remove them from recommendations but won't delete the audio files."
        
        if not messagebox.askyesno("Confirm Deletion", msg):
            return
        
        # Delete tracks
        try:
            # Remember scroll position and track info before deletion
            first_visible = self.library_listbox.nearest(0)
            deleted_track_ids = {track["track_id"] for track in selected_tracks}
            
            # Count how many deleted tracks are above the first visible item
            deleted_above_count = 0
            for i in range(min(first_visible, len(self.filtered_library_tracks))):
                if self.filtered_library_tracks[i]["track_id"] in deleted_track_ids:
                    deleted_above_count += 1
            
            deleted_count = self.library.delete_tracks(deleted_track_ids)
            
            if deleted_count > 0:
                self.status.config(text=f"✅ Deleted {deleted_count} tracks from library")
                
                # Refresh library data and display
                self.refresh_library()
                
                # Restore scroll position (adjust for deleted items above the visible area)
                new_position = max(0, first_visible - deleted_above_count)
                if new_position < len(self.filtered_library_tracks):
                    self.library_listbox.see(new_position)
                
                # Clear current track if it was deleted
                if self.current_id and any(track["track_id"] == self.current_id for track in selected_tracks):
                    self.current_id = None
                    self.lbl_current.config(text="Current track: —")
                    self.current_recommendations = []
                    self.update_listbox()
            else:
                self.status.config(text="❌ No tracks were deleted")
                
        except Exception as e:
            messagebox.showerror("Deletion Error", f"Failed to delete tracks: {str(e)}")
            self.status.config(text="❌ Error deleting tracks")
    
