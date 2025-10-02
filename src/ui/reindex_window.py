#!/usr/bin/env python3
"""Reindexing window for updating library."""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk


class ReindexWindow(tk.Toplevel):
    """Window for reindexing the library."""
    
    def __init__(self, parent, xml_path, force_full=False):
        super().__init__(parent)
        self.xml_path = xml_path
        self.force_full = force_full
        self.indexing_complete = False
        self.parent_app = parent
        self.message_queue = queue.Queue()
        self.cancel_requested = False  # Flag for cancellation
        
        title = "Full Re-index" if force_full else "Update Library"
        self.title(f"{title} - Cosine Companion")
        self.geometry("600x400")
        self.resizable(False, False)
        
        # Set window icon
        from utils.icon import set_window_icon
        set_window_icon(self)
        
        # Make it modal
        self.transient(parent)
        self.grab_set()
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (300)
        y = (self.winfo_screenheight() // 2) - (200)
        self.geometry(f"600x400+{x}+{y}")
        
        self.create_ui()
        
        # Force window to show on macOS
        self.deiconify()
        self.lift()
        self.focus_force()
        self.update()
        
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
        
        # Add Cancel button during processing
        self.cancel_btn = tk.Button(
            self.button_frame,
            text="Cancel",
            command=self.cancel_indexing,
            font=("Helvetica", 11, "bold"),
            padx=30,
            pady=8
        )
        self.cancel_btn.pack()
    
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
    
    def cancel_indexing(self):
        """Cancel the indexing process."""
        if messagebox.askyesno("Cancel Indexing", "Are you sure you want to cancel? Progress will be lost."):
            self.cancel_requested = True
            self.message_queue.put(('log', "\n⚠️ Cancellation requested..."))
    
    def run_indexing(self):
        """Run the indexing process (in background thread)."""
        import sys
        from processing.pipeline import index_library
        
        # Create a custom writer that sends to queue
        class QueueWriter:
            def __init__(self, message_queue):
                self.queue = message_queue
                self.buffer = ""
            
            def write(self, text):
                self.buffer += text
                # Send complete lines to queue
                while '\n' in self.buffer:
                    line, self.buffer = self.buffer.split('\n', 1)
                    if line.strip():  # Only send non-empty lines
                        self.queue.put(('log', line))
            
            def flush(self):
                if self.buffer.strip():
                    self.queue.put(('log', self.buffer))
                    self.buffer = ""
        
        # Redirect stdout to queue
        old_stdout = sys.stdout
        sys.stdout = QueueWriter(self.message_queue)
        
        try:
            # Run indexing with cancellation callback
            index_library(
                self.xml_path, 
                force_full=self.force_full, 
                sample_size=None,
                cancel_check=lambda: self.cancel_requested
            )
            
            if self.cancel_requested:
                self.message_queue.put(('cancelled', True))
                self.message_queue.put(('log', "\n⚠️ Indexing cancelled by user"))
            else:
                self.message_queue.put(('complete', True))
                self.message_queue.put(('log', "\n✅ Indexing completed successfully!"))
        except Exception as e:
            if self.cancel_requested:
                self.message_queue.put(('cancelled', True))
                self.message_queue.put(('log', "\n⚠️ Indexing cancelled"))
            else:
                self.message_queue.put(('complete', False))
                self.message_queue.put(('log', f"\n❌ Error during indexing: {str(e)}"))
                import traceback
                self.message_queue.put(('log', traceback.format_exc()))
        finally:
            # Restore stdout
            sys.stdout.flush()
            sys.stdout = old_stdout
    
    def check_indexing_status(self):
        """Check if indexing is complete and process queue messages."""
        # Process all pending messages from queue (non-blocking)
        # Limit how many messages we process at once to keep UI responsive
        messages_processed = 0
        max_messages_per_check = 10  # Process max 10 messages per UI update
        
        try:
            while messages_processed < max_messages_per_check:
                msg_type, msg_data = self.message_queue.get_nowait()
                if msg_type == 'log':
                    # Add log message to UI
                    if hasattr(self, 'log_text'):
                        self.log_text.insert(tk.END, msg_data + "\n")
                        self.log_text.see(tk.END)
                elif msg_type == 'complete':
                    self.indexing_complete = msg_data
                elif msg_type == 'cancelled':
                    self.indexing_complete = False
                    self.cancel_requested = True
                messages_processed += 1
        except queue.Empty:
            pass  # No more messages
        
        if self.indexing_thread.is_alive():
            # Still running (200ms is gentler on CPU)
            self.after(200, self.check_indexing_status)
        else:
            # Complete - process any remaining messages
            try:
                while True:
                    msg_type, msg_data = self.message_queue.get_nowait()
                    if msg_type == 'log':
                        if hasattr(self, 'log_text'):
                            self.log_text.insert(tk.END, msg_data + "\n")
                            self.log_text.see(tk.END)
                    elif msg_type == 'complete':
                        self.indexing_complete = msg_data
                    elif msg_type == 'cancelled':
                        self.indexing_complete = False
                        self.cancel_requested = True
            except queue.Empty:
                pass
            
            self.progress_bar.stop()
            
            # Remove cancel button
            if hasattr(self, 'cancel_btn'):
                self.cancel_btn.destroy()
            
            if self.cancel_requested:
                self.show_cancelled()
            elif self.indexing_complete:
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
            font=("Helvetica", 12, "bold"),
            padx=30,
            pady=10
        ).pack()
    
    def show_cancelled(self):
        """Show cancelled state."""
        self.status_label.config(
            text="⚠️ Indexing cancelled",
            font=("Helvetica", 12, "bold"),
            fg="orange"
        )
        
        tk.Button(
            self.button_frame,
            text="Close",
            command=self.destroy,
            font=("Helvetica", 12),
            padx=30,
            pady=10
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
            font=("Helvetica", 12),
            padx=30,
            pady=10
        ).pack()
    
    def finish(self):
        """Finish and reload main app."""
        # Notify user they may want to restart
        result = messagebox.askyesno(
            "Restart Required",
            "Library has been updated!\n\n"
            "To see new tracks in the UI, you should restart Cosine Companion.\n\n"
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
