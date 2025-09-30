#!/usr/bin/env python3
"""First-run onboarding flow for DJ Companion."""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from config import META_PQ
from processing.pipeline import index_library


class OnboardingWindow(tk.Toplevel):
    """Onboarding window for first-time setup."""
    
    def __init__(self, parent, on_complete_callback):
        super().__init__(parent)
        self.title("Welcome to DJ Companion")
        self.geometry("600x400")
        self.resizable(False, False)
        
        # Make it modal
        self.transient(parent)
        self.grab_set()
        
        self.on_complete_callback = on_complete_callback
        self.xml_path = None
        self.indexing_complete = False
        
        # Center the window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.winfo_screenheight() // 2) - (400 // 2)
        self.geometry(f"600x400+{x}+{y}")
        
        self.create_welcome_screen()
    
    def create_welcome_screen(self):
        """Create the initial welcome screen."""
        # Clear any existing widgets
        for widget in self.winfo_children():
            widget.destroy()
        
        # Welcome header
        header = tk.Label(
            self,
            text="🎵 Welcome to DJ Companion",
            font=("Helvetica", 20, "bold"),
            pady=20
        )
        header.pack()
        
        # Description
        desc_frame = tk.Frame(self)
        desc_frame.pack(pady=20, padx=40)
        
        description = """DJ Companion helps you discover tracks that mix well together.

To get started, we need to index your music library.

This requires:
• Your Rekordbox XML export file
• A few minutes to process your tracks
• About 1KB per track of disk space

You only need to do this once. After that, you can add new tracks incrementally."""
        
        tk.Label(
            desc_frame,
            text=description,
            font=("Helvetica", 11),
            justify=tk.LEFT,
            wraplength=500
        ).pack()
        
        # Buttons
        button_frame = tk.Frame(self)
        button_frame.pack(pady=30)
        
        tk.Button(
            button_frame,
            text="Get Started",
            command=self.select_xml_file,
            font=("Helvetica", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=10
        ).pack(side=tk.LEFT, padx=10)
        
        tk.Button(
            button_frame,
            text="Exit",
            command=self.quit_app,
            font=("Helvetica", 12),
            padx=30,
            pady=10
        ).pack(side=tk.LEFT, padx=10)
        
        # Help text
        help_text = tk.Label(
            self,
            text="Need help? Export your library from Rekordbox:\nFile → Export Collection in xml format",
            font=("Helvetica", 9),
            fg="gray"
        )
        help_text.pack(pady=10)
    
    def select_xml_file(self):
        """Show file dialog to select Rekordbox XML."""
        xml_path = filedialog.askopenfilename(
            title="Select Rekordbox XML Export",
            filetypes=[
                ("XML files", "*.xml"),
                ("All files", "*.*")
            ]
        )
        
        if not xml_path:
            return  # User cancelled
        
        self.xml_path = xml_path
        self.confirm_indexing()
    
    def confirm_indexing(self):
        """Show confirmation before starting indexing."""
        # Clear screen
        for widget in self.winfo_children():
            widget.destroy()
        
        # Confirmation header
        header = tk.Label(
            self,
            text="Ready to Index",
            font=("Helvetica", 18, "bold"),
            pady=20
        )
        header.pack()
        
        # File info
        info_frame = tk.Frame(self)
        info_frame.pack(pady=20, padx=40, fill=tk.BOTH, expand=True)
        
        tk.Label(
            info_frame,
            text="Selected file:",
            font=("Helvetica", 11, "bold")
        ).pack(anchor=tk.W)
        
        tk.Label(
            info_frame,
            text=self.xml_path,
            font=("Helvetica", 10),
            fg="gray",
            wraplength=500
        ).pack(anchor=tk.W, pady=5)
        
        tk.Label(
            info_frame,
            text="\nIndexing will:",
            font=("Helvetica", 11, "bold")
        ).pack(anchor=tk.W, pady=(20, 5))
        
        steps = [
            "• Read track metadata from the XML file",
            "• Generate audio embeddings for each track",
            "• Build a similarity search index",
            "• This may take a few minutes depending on library size"
        ]
        
        for step in steps:
            tk.Label(
                info_frame,
                text=step,
                font=("Helvetica", 10),
                justify=tk.LEFT
            ).pack(anchor=tk.W)
        
        # Buttons
        button_frame = tk.Frame(self)
        button_frame.pack(pady=20)
        
        tk.Button(
            button_frame,
            text="Start Indexing",
            command=self.start_indexing,
            font=("Helvetica", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=10
        ).pack(side=tk.LEFT, padx=10)
        
        tk.Button(
            button_frame,
            text="Choose Different File",
            command=self.select_xml_file,
            font=("Helvetica", 12),
            padx=20,
            pady=10
        ).pack(side=tk.LEFT, padx=10)
    
    def start_indexing(self):
        """Start the indexing process."""
        # Clear screen
        for widget in self.winfo_children():
            widget.destroy()
        
        # Progress header
        header = tk.Label(
            self,
            text="Indexing Your Library",
            font=("Helvetica", 18, "bold"),
            pady=20
        )
        header.pack()
        
        # Progress frame
        progress_frame = tk.Frame(self)
        progress_frame.pack(pady=20, padx=40, fill=tk.BOTH, expand=True)
        
        self.status_label = tk.Label(
            progress_frame,
            text="Starting indexing process...",
            font=("Helvetica", 11),
            wraplength=500
        )
        self.status_label.pack(pady=10)
        
        # Progress bar
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            mode='indeterminate',
            length=400
        )
        self.progress_bar.pack(pady=20)
        self.progress_bar.start(10)
        
        # Log text area
        log_frame = tk.Frame(progress_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(
            log_frame,
            height=10,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            font=("Courier", 9)
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)
        
        # Start indexing in background thread
        self.indexing_thread = threading.Thread(target=self.run_indexing, daemon=True)
        self.indexing_thread.start()
        
        # Start checking for completion
        self.check_indexing_status()
    
    def log_message(self, message):
        """Add a message to the log."""
        if hasattr(self, 'log_text'):
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.update()
    
    def run_indexing(self):
        """Run the indexing process (in background thread)."""
        import sys
        from io import StringIO
        
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        try:
            # Run indexing
            index_library(self.xml_path, force_full=False, sample_size=None)
            self.indexing_complete = True
            self.log_message("\n✅ Indexing completed successfully!")
        except Exception as e:
            self.indexing_complete = False
            self.log_message(f"\n❌ Error during indexing: {str(e)}")
        finally:
            # Restore stdout
            output = captured_output.getvalue()
            sys.stdout = old_stdout
            
            # Display captured output
            for line in output.split('\n'):
                if line.strip():
                    self.log_message(line)
    
    def check_indexing_status(self):
        """Check if indexing is complete."""
        if self.indexing_thread.is_alive():
            # Still running, check again soon
            self.after(500, self.check_indexing_status)
        else:
            # Indexing complete
            self.progress_bar.stop()
            
            if self.indexing_complete:
                self.show_completion()
            else:
                self.show_error()
    
    def show_completion(self):
        """Show completion screen."""
        self.status_label.config(
            text="🎉 Your library has been indexed!",
            font=("Helvetica", 14, "bold"),
            fg="green"
        )
        
        # Add completion button
        button_frame = tk.Frame(self)
        button_frame.pack(pady=20)
        
        tk.Button(
            button_frame,
            text="Start Using DJ Companion",
            command=self.complete_onboarding,
            font=("Helvetica", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=10
        ).pack()
    
    def show_error(self):
        """Show error screen."""
        self.status_label.config(
            text="⚠️ Indexing encountered an error",
            font=("Helvetica", 14, "bold"),
            fg="red"
        )
        
        # Add buttons
        button_frame = tk.Frame(self)
        button_frame.pack(pady=20)
        
        tk.Button(
            button_frame,
            text="Try Again",
            command=self.create_welcome_screen,
            font=("Helvetica", 12, "bold"),
            bg="#FF9800",
            fg="white",
            padx=30,
            pady=10
        ).pack(side=tk.LEFT, padx=10)
        
        tk.Button(
            button_frame,
            text="Exit",
            command=self.quit_app,
            font=("Helvetica", 12),
            padx=30,
            pady=10
        ).pack(side=tk.LEFT, padx=10)
    
    def complete_onboarding(self):
        """Complete onboarding and launch main app."""
        # Save the XML path to settings
        self.save_settings()
        
        # Close onboarding window
        self.destroy()
        
        # Call the callback to show main app
        if self.on_complete_callback:
            self.on_complete_callback()
    
    def save_settings(self):
        """Save user settings."""
        from config import DATA
        settings_file = DATA / "settings.json"
        
        import json
        settings = {
            "xml_path": self.xml_path,
            "first_run_complete": True
        }
        
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=2)
    
    def quit_app(self):
        """Quit the application."""
        if messagebox.askokcancel("Exit", "Are you sure you want to exit?"):
            self.master.quit()


def needs_onboarding():
    """Check if the app needs to show onboarding."""
    from config import DATA
    
    # Check if data files exist
    if not META_PQ.exists():
        return True
    
    # Check if settings indicate first run complete
    settings_file = DATA / "settings.json"
    if settings_file.exists():
        import json
        with open(settings_file, 'r') as f:
            settings = json.load(f)
            return not settings.get("first_run_complete", False)
    
    return True
