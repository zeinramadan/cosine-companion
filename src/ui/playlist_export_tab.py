"""Playlist export tab functionality for Cosine Companion UI."""

from typing import TYPE_CHECKING, Set
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading

from recommendations.playlist_exporter import export_recommendations_as_playlists, export_single_playlist
from ui.track_selector_dialog import TrackSelectorDialog

if TYPE_CHECKING:
    from ui.app import App


class PlaylistExportTabMixin:
    """Mixin class for playlist export tab functionality."""
    
    def create_playlist_export_tab(self: "App"):
        """Create the playlist export tab."""
        export_frame = ttk.Frame(self.notebook)
        self.notebook.add(export_frame, text="Playlist Export")
        
        # Main container with padding
        container = tk.Frame(export_frame, padx=20, pady=15)
        container.pack(fill="both", expand=True)
        
        # Title and description
        title = tk.Label(
            container,
            text="Export Recommendation Playlists",
            font=("Helvetica", 14, "bold")
        )
        title.pack(anchor="w", pady=(0, 5))
        
        desc = tk.Label(
            container,
            text="Generate .m3u playlists with track recommendations that can be imported into Rekordbox.",
            font=("Helvetica", 9),
            fg="gray",
            wraplength=850,
            justify="left"
        )
        desc.pack(anchor="w", pady=(0, 15))
        
        # === Track Selection Section ===
        selection_frame = tk.LabelFrame(
            container,
            text="1. Select Tracks",
            font=("Helvetica", 10, "bold"),
            padx=10,
            pady=10
        )
        selection_frame.pack(fill="x", pady=(0, 10))
        
        # Selection mode and Add button
        mode_frame = tk.Frame(selection_frame)
        mode_frame.pack(fill="x", pady=(0, 8))
        
        self.export_selection_var = tk.StringVar(value="manual")
        
        tk.Radiobutton(
            mode_frame,
            text="Selected tracks:",
            variable=self.export_selection_var,
            value="manual",
            font=("Helvetica", 9),
            command=self.on_export_selection_change
        ).pack(side="left")
        
        tk.Button(
            mode_frame,
            text="+ Add Tracks",
            command=self.open_track_selector,
            bg="lightgreen",
            font=("Helvetica", 9, "bold")
        ).pack(side="left", padx=10)
        
        tk.Button(
            mode_frame,
            text="Clear All",
            command=self.clear_selected_tracks,
            font=("Helvetica", 9)
        ).pack(side="left", padx=2)
        
        # Selected tracks listbox (compact)
        self.export_selected_listbox = tk.Listbox(
            selection_frame,
            height=6,
            selectmode=tk.EXTENDED,
            exportselection=False
        )
        self.export_selected_listbox.pack(fill="x", pady=(0, 8))
        
        # "All tracks" option
        tk.Radiobutton(
            selection_frame,
            text="All tracks in collection",
            variable=self.export_selection_var,
            value="all",
            font=("Helvetica", 9),
            command=self.on_export_selection_change
        ).pack(anchor="w")
        
        # Selection info label
        self.export_selection_info = tk.Label(
            selection_frame,
            text="",
            font=("Helvetica", 9),
            fg="blue"
        )
        self.export_selection_info.pack(anchor="w", pady=(5, 0))
        
        # Initialize selected tracks set
        self.export_selected_track_ids: Set[str] = set()
        
        # === Playlist Configuration Section ===
        config_frame = tk.LabelFrame(
            container,
            text="2. Configure Playlists",
            font=("Helvetica", 10, "bold"),
            padx=10,
            pady=10
        )
        config_frame.pack(fill="x", pady=(0, 10))
        
        # Configuration options in a more compact layout
        options_frame = tk.Frame(config_frame)
        options_frame.pack(fill="x")
        
        # Recommendations per track
        tk.Label(
            options_frame,
            text="Recommendations per track:",
            font=("Helvetica", 9)
        ).grid(row=0, column=0, sticky="w", pady=3)
        
        self.export_recs_var = tk.StringVar(value="25")
        recs_combo = ttk.Combobox(
            options_frame,
            textvariable=self.export_recs_var,
            values=["10", "15", "20", "25", "30", "40", "50"],
            width=6,
            state="readonly"
        )
        recs_combo.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)
        
        # Export format
        tk.Label(
            options_frame,
            text="Export format:",
            font=("Helvetica", 9)
        ).grid(row=1, column=0, sticky="w", pady=3)
        
        self.export_format_var = tk.StringVar(value="separate")
        
        format_frame = tk.Frame(options_frame)
        format_frame.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=3)
        
        tk.Radiobutton(
            format_frame,
            text="Separate playlist per track",
            variable=self.export_format_var,
            value="separate",
            font=("Helvetica", 9)
        ).pack(side="left", padx=(0, 10))
        
        tk.Radiobutton(
            format_frame,
            text="Single combined playlist",
            variable=self.export_format_var,
            value="combined",
            font=("Helvetica", 9)
        ).pack(side="left")
        
        # === Output Location Section ===
        output_frame = tk.LabelFrame(
            container,
            text="3. Output Location",
            font=("Helvetica", 10, "bold"),
            padx=10,
            pady=10
        )
        output_frame.pack(fill="x", pady=(0, 10))
        
        path_row = tk.Frame(output_frame)
        path_row.pack(fill="x")
        
        self.export_output_var = tk.StringVar(value=str(Path.home() / "Desktop" / "Cosine_Playlists"))
        
        tk.Entry(
            path_row,
            textvariable=self.export_output_var,
            font=("Helvetica", 10),
            width=60
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        tk.Button(
            path_row,
            text="Browse...",
            command=self.browse_export_output,
            font=("Helvetica", 10)
        ).pack(side="left")
        
        # === Export Button and Progress ===
        action_frame = tk.Frame(container)
        action_frame.pack(fill="x", pady=(10, 0))
        
        self.export_btn = tk.Button(
            action_frame,
            text="🎵 Generate Playlists",
            command=self.start_playlist_export,
            font=("Helvetica", 12, "bold"),
            bg="lightgreen",
            padx=20,
            pady=10
        )
        self.export_btn.pack()
        
        # Progress section (initially hidden)
        self.export_progress_frame = tk.Frame(container)
        
        self.export_progress_label = tk.Label(
            self.export_progress_frame,
            text="",
            font=("Helvetica", 10)
        )
        self.export_progress_label.pack(pady=(10, 5))
        
        self.export_progress_bar = ttk.Progressbar(
            self.export_progress_frame,
            mode='determinate',
            length=400
        )
        self.export_progress_bar.pack()
        
        self.export_status_label = tk.Label(
            self.export_progress_frame,
            text="",
            font=("Helvetica", 9),
            fg="gray"
        )
        self.export_status_label.pack(pady=(5, 0))
        
        # Initialize selection info
        self.update_export_selection_info()
    
    def open_track_selector(self: "App"):
        """Open dialog to select tracks."""
        dialog = TrackSelectorDialog(self, self.meta_ix, self.export_selected_track_ids)
        self.wait_window(dialog)
        
        if dialog.result:
            # Add selected tracks to our set
            for track_id in dialog.result:
                self.export_selected_track_ids.add(track_id)
            
            self.update_selected_tracks_display()
    
    def clear_selected_tracks(self: "App"):
        """Clear all selected tracks."""
        self.export_selected_track_ids.clear()
        self.update_selected_tracks_display()
    
    def update_selected_tracks_display(self: "App"):
        """Update the display of selected tracks."""
        self.export_selected_listbox.delete(0, tk.END)
        
        # Get track info and sort by artist/title
        tracks_info = []
        for track_id in self.export_selected_track_ids:
            if track_id in self.meta_ix.index:
                row = self.meta_ix.loc[track_id]
                tracks_info.append({
                    'track_id': track_id,
                    'artist': row.get('artist', ''),
                    'title': row.get('title', ''),
                    'key': row.get('key', ''),
                    'bpm': row.get('bpm', ''),
                })
        
        tracks_info.sort(key=lambda x: (x['artist'].lower(), x['title'].lower()))
        
        # Display tracks
        for track in tracks_info:
            key_bpm = []
            if track['key']:
                key_bpm.append(f"[{track['key']}]")
            if track['bpm']:
                key_bpm.append(f"({track['bpm']} BPM)")
            
            extra_info = " ".join(key_bpm)
            display = f"{track['artist']} – {track['title']} {extra_info}".strip()
            self.export_selected_listbox.insert(tk.END, display)
        
        self.update_export_selection_info()
    
    def on_export_selection_change(self: "App"):
        """Handle changes to track selection mode."""
        self.update_export_selection_info()
    
    def update_export_selection_info(self: "App"):
        """Update the selection info label."""
        mode = self.export_selection_var.get()
        
        if mode == "all":
            count = len(self.meta)
            self.export_selection_info.config(
                text=f"✓ Will generate playlists for all {count} tracks in your collection",
                fg="blue"
            )
        elif mode == "manual":
            count = len(self.export_selected_track_ids)
            if count > 0:
                self.export_selection_info.config(
                    text=f"✓ {count} track(s) selected • Click '+ Add Tracks' to add more",
                    fg="blue"
                )
            else:
                self.export_selection_info.config(
                    text="⚠ No tracks selected. Click '+ Add Tracks' to select tracks",
                    fg="orange"
                )
    
    def browse_export_output(self: "App"):
        """Browse for output directory."""
        current = self.export_output_var.get()
        directory = filedialog.askdirectory(
            title="Select Output Directory",
            initialdir=current if current else str(Path.home())
        )
        if directory:
            self.export_output_var.set(directory)
    
    def get_export_track_ids(self: "App"):
        """Get the list of track IDs to export based on selection."""
        mode = self.export_selection_var.get()
        
        if mode == "all":
            return list(self.meta['track_id'].values)
        elif mode == "manual":
            return list(self.export_selected_track_ids)
        
        return []
    
    def start_playlist_export(self: "App"):
        """Start the playlist export process."""
        # Get track IDs
        track_ids = self.get_export_track_ids()
        
        if not track_ids:
            messagebox.showwarning(
                "No Tracks Selected",
                "Please select tracks to export playlists for."
            )
            return
        
        # Get configuration
        recommendations_per_track = int(self.export_recs_var.get())
        output_dir = self.export_output_var.get()
        export_format = self.export_format_var.get()
        
        # Validate output directory
        if not output_dir:
            messagebox.showwarning(
                "No Output Directory",
                "Please select an output directory."
            )
            return
        
        # Confirm with user
        format_desc = "separate playlists" if export_format == "separate" else "a single combined playlist"
        message = (
            f"This will generate {format_desc} for {len(track_ids)} track(s),\n"
            f"with {recommendations_per_track} recommendations per track.\n\n"
            f"Output directory: {output_dir}\n\n"
            f"Continue?"
        )
        
        if not messagebox.askyesno("Confirm Export", message):
            return
        
        # Disable button and show progress
        self.export_btn.config(state="disabled")
        self.export_progress_frame.pack(pady=(20, 0))
        self.export_progress_bar['value'] = 0
        self.export_progress_label.config(text="Generating playlists...")
        self.export_status_label.config(text="")
        
        # Run export in background thread
        def export_worker():
            try:
                if export_format == "separate":
                    stats = export_recommendations_as_playlists(
                        track_ids,
                        output_dir,
                        recommendations_per_track,
                        self.meta_ix,
                        self.emb_ix,
                        self.idx,
                        progress_callback=self.update_export_progress
                    )
                else:
                    # Combined playlist
                    output_path = Path(output_dir) / "Cosine_Recommendations.m3u"
                    stats = export_single_playlist(
                        track_ids,
                        str(output_path),
                        "Cosine Recommendations",
                        self.meta_ix,
                        self.emb_ix,
                        self.idx,
                        recommendations_per_track
                    )
                
                # Update UI on main thread
                self.after(0, lambda: self.export_complete(stats, output_dir))
            except Exception as e:
                self.after(0, lambda: self.export_error(str(e)))
        
        thread = threading.Thread(target=export_worker, daemon=True)
        thread.start()
    
    def update_export_progress(self: "App", current: int, total: int, track_name: str):
        """Update progress bar during export."""
        def update():
            progress = (current / total) * 100
            self.export_progress_bar['value'] = progress
            self.export_progress_label.config(
                text=f"Generating playlists... ({current}/{total})"
            )
            self.export_status_label.config(text=f"Current: {track_name}")
            self.update_idletasks()
        
        self.after(0, update)
    
    def export_complete(self: "App", stats: dict, output_dir: str):
        """Handle successful export completion."""
        self.export_btn.config(state="normal")
        self.export_progress_frame.pack_forget()
        
        message = (
            f"✓ Export Complete!\n\n"
            f"Playlists created: {stats['playlists_created']}\n"
            f"Successful: {stats['successful']}\n"
            f"Total recommendations: {stats['total_recommendations']}\n"
            f"Failed: {stats['failed']}\n\n"
            f"Location: {output_dir}\n\n"
            f"You can now import these .m3u files into Rekordbox:\n"
            f"File → Import → Playlist → Select .m3u file(s)"
        )
        
        messagebox.showinfo("Export Complete", message)
    
    def export_error(self: "App", error_msg: str):
        """Handle export error."""
        self.export_btn.config(state="normal")
        self.export_progress_frame.pack_forget()
        
        messagebox.showerror(
            "Export Error",
            f"An error occurred during export:\n\n{error_msg}"
        )

