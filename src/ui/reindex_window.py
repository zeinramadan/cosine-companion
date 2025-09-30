#!/usr/bin/env python3
"""Reindexing window for updating library."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from processing.pipeline import index_library


class ReindexWindow(tk.Toplevel):
    """Window for reindexing the library."""
    
    def __init__(self, parent, xml_path, force_full=False):
        super().__init__(parent)
        self.xml_path = xml_path
        self.force_full = force_full
        self.indexing_complete = False
        self.parent_app = parent
        
        title = "Full Re-index" if force_full else "Update Library"
        self.title(f"{title} - DJ Companion")
        self.geometry("600x400")
        self.resizable(False, False)
        
        # Make it modal
        self.transient(parent)
        self.grab_set()
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (300)
        y = (self.winfo_screenheight() // 2) - (200)
        self.geometry(f"600x400+{x}+{y}")
        
        self.create_ui()
        
        # Start indexing immediately
        self.after(100, self.start_indexing)
    
    def create_ui(self):
        """Create the UI."""
        # Header
        mode_text = "Reprocessing Entire Library" if self.force_full else "Checking for New Tracks"
        header = tk.Label(
            self,
            text=mode_text,
            font=("Helvetica", 16, "bold"),
            pady=15
        )
        header.pack()
        
        # Status label
        self.status_label = tk.Label(
            self,
            text="Starting...",
            font=("Helvetica", 11),
            wraplength=500
        )
        self.status_label.pack(pady=10)
        
        # Progress bar
        progress_frame = tk.Frame(self)
        progress_frame.pack(pady=10)
        
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            mode='indeterminate',
            length=400
        )
        self.progress_bar.pack()
        
        # Log text area
        log_frame = tk.Frame(self)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=10)
        
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(
            log_frame,
            height=12,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            font=("Courier", 9)
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)
        
        # Button frame (initially empty, filled after completion)
        self.button_frame = tk.Frame(self)
        self.button_frame.pack(pady=10)
    
    def log_message(self, message):
        """Add a message to the log."""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.update()
    
    def start_indexing(self):
        """Start the indexing process."""
        self.progress_bar.start(10)
        
        # Start in background thread
        self.indexing_thread = threading.Thread(target=self.run_indexing, daemon=True)
        self.indexing_thread.start()
        
        # Check for completion
        self.check_indexing_status()
    
    def run_indexing(self):
        """Run the indexing process (in background thread)."""
        import sys
        from io import StringIO
        
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        try:
            # Run indexing
            index_library(self.xml_path, force_full=self.force_full, sample_size=None)
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
            # Still running
            self.after(500, self.check_indexing_status)
        else:
            # Complete
            self.progress_bar.stop()
            
            if self.indexing_complete:
                self.show_completion()
            else:
                self.show_error()
    
    def show_completion(self):
        """Show completion state."""
        self.status_label.config(
            text="✅ Library updated successfully!",
            font=("Helvetica", 12, "bold"),
            fg="green"
        )
        
        tk.Button(
            self.button_frame,
            text="Done",
            command=self.finish,
            font=("Helvetica", 11, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=8
        ).pack()
    
    def show_error(self):
        """Show error state."""
        self.status_label.config(
            text="❌ An error occurred",
            font=("Helvetica", 12, "bold"),
            fg="red"
        )
        
        tk.Button(
            self.button_frame,
            text="Close",
            command=self.destroy,
            font=("Helvetica", 11),
            padx=30,
            pady=8
        ).pack()
    
    def finish(self):
        """Finish and reload main app."""
        # Notify user they may want to restart
        result = messagebox.askyesno(
            "Restart Required",
            "Library has been updated!\n\n"
            "To see new tracks in the UI, you should restart DJ Companion.\n\n"
            "Restart now?"
        )
        
        if result:
            # Restart the app
            self.destroy()
            if hasattr(self.parent_app, 'destroy'):
                self.parent_app.destroy()
                # The app will need to be relaunched manually
                import sys
                sys.exit(0)
        else:
            self.destroy()
