#!/usr/bin/env python3
"""Main application class for DJ Companion UI."""

from typing import Optional, List, Dict, Any
import tkinter as tk
from tkinter import ttk

from recommendations import load_all
from ui.recommendations_tab import RecommendationsTabMixin
from ui.set_creator_tab import SetCreatorTabMixin
from ui.library_tab import LibraryTabMixin


class App(RecommendationsTabMixin, SetCreatorTabMixin, LibraryTabMixin, tk.Tk):
    """Main application window for DJ Companion."""
    
    def __init__(self):
        super().__init__()
        self.title("Cosine Companion - Explore your taste")
        self.geometry("900x720")
        self.minsize(820, 640)
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
        
        # Create tabs (methods from mixins)
        self.create_recommendations_tab()
        self.create_set_creator_tab()
        self.create_library_tab()
        
        # Ensure all buttons are properly initialized
        self.initialize_ui_state()
        # Also re-apply after UI settles, on map, and at a few delays (macOS theme timing)
        self.after_idle(self.initialize_ui_state)
        self.after(300, self.initialize_ui_state)
        self.after(1000, self.initialize_ui_state)
        self.bind("<Map>", lambda e: self.initialize_ui_state())
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.status = tk.Label(self, text="💡 Choose a track to start using 'Set Current Track' button, double-click any suggestion to set it as current track", anchor="w", font=("Helvetica", 9), fg="gray")
        # Keep status bar visible regardless of window height by sticking it to the bottom
        self.status.pack(fill="x", side="bottom")
        # Initialize bottom status hint for current tab
        self.after(0, self.set_default_status_hint)

    def initialize_ui_state(self):
        """Ensure all UI elements are in the correct initial state."""
        # Make sure the Add Anchor button is enabled and styled
        if hasattr(self, 'add_anchor_btn'):
            self.add_anchor_btn.config(state="normal", bg="lightgreen", font=("Helvetica", 10, "bold"))

    def on_tab_changed(self, event=None):
        """Re-apply styles when switching tabs to avoid platform/theme resets."""
        try:
            current_tab = self.notebook.select()
            tab_text = self.notebook.tab(current_tab, "text")
            if tab_text == "Set Creator" and hasattr(self, 'add_anchor_btn'):
                # Force re-enable and restyle when the tab becomes visible
                self.add_anchor_btn.config(state="normal", bg="lightgreen", font=("Helvetica", 10, "bold"))
                self.update_idletasks()
            # Update bottom hint based on active tab
            self.set_default_status_hint()
        except Exception:
            pass

    def get_hint_for_tab(self, tab_text: str) -> str:
        """Return the default hint text for a given tab name."""
        if tab_text == "Explore":
            return "💡 Choose a track to start using 'Set Current Track' button, double-click any suggestion to set it as current track"
        if tab_text == "Set Creator":
            return ("💡 1) Click '+ Add Anchor' and choose a track + it's position in the set. "
                    "2) Set 'Total Tracks'. 3) Click 'Generate Set'. 4) Adjust anchors and regenerate as needed.")
        if tab_text == "Library":
            return "💡 Ctrl+Click to multi-select • Shift+Click to select range • Double-click to set as current track in explore tab"

    def set_default_status_hint(self):
        """Set the bottom status label to the default hint for the active tab."""
        try:
            current_tab = self.notebook.select()
            tab_text = self.notebook.tab(current_tab, "text")
            self.status.config(text=self.get_hint_for_tab(tab_text), fg="gray")
        except Exception:
            self.status.config(text="💡 Tip: Double-click any suggestion to set it as current track", fg="gray")
