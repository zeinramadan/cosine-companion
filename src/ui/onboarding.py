#!/usr/bin/env python3
"""First-run onboarding flow for Cosine Companion."""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from config import META_PQ


class OnboardingWindow(tk.Toplevel):
    """Onboarding window for first-time setup."""
    
    def __init__(self, parent, on_complete_callback):
        super().__init__(parent)
        self.title("Welcome to Cosine Companion")
        self.geometry("600x400")
        self.resizable(False, False)
        
        # Set window icon
        from utils.icon import set_window_icon
        set_window_icon(self)
        
        # Make it modal
        self.transient(parent)
        self.grab_set()
        
        self.on_complete_callback = on_complete_callback
        self.xml_path = None
        self.indexing_complete = False
        self.message_queue = queue.Queue()
        
        # Center the window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.winfo_screenheight() // 2) - (400 // 2)
        self.geometry(f"600x400+{x}+{y}")
        
        self.create_welcome_screen()
        
        # Force window to show on macOS
        self.deiconify()
        self.lift()
        self.focus_force()
        self.update()
    
    def create_welcome_screen(self):
        """Create the initial welcome screen."""
        # Clear any existing widgets
        for widget in self.winfo_children():
            widget.destroy()
        
        # Welcome header
        header = tk.Label(
            self,
            text="🎵 Welcome to Cosine Companion",
            font=("Helvetica", 20, "bold"),
            pady=20
        )
        header.pack()
        
        # Description
        desc_frame = tk.Frame(self)
        desc_frame.pack(pady=20, padx=40)
        
        description = """Cosine Companion helps you discover tracks that mix well together.

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
        
        # Custom "Get Started" button using Label for proper color display on macOS
        start_btn_frame = tk.Frame(button_frame, bg="#4CAF50", relief="raised", bd=2)
        start_btn_frame.pack(side=tk.LEFT, padx=10)
        
        start_btn = tk.Label(
            start_btn_frame,
            text="Get Started",
            font=("Helvetica", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=10,
            cursor="hand2"
        )
        start_btn.pack()
        
        # Bind click events
        def on_start_click(e):
            start_btn.config(bg="#45a049")
            self.after(100, lambda: self.select_xml_file())
        
        def on_start_enter(e):
            start_btn.config(bg="#45a049")
            start_btn_frame.config(bg="#45a049")
        
        def on_start_leave(e):
            start_btn.config(bg="#4CAF50")
            start_btn_frame.config(bg="#4CAF50")
        
        start_btn.bind("<Button-1>", on_start_click)
        start_btn.bind("<Enter>", on_start_enter)
        start_btn.bind("<Leave>", on_start_leave)
        
        # Custom "Exit" button with gray styling
        exit_btn_frame = tk.Frame(button_frame, bg="#757575", relief="raised", bd=2)
        exit_btn_frame.pack(side=tk.LEFT, padx=10)
        
        exit_btn = tk.Label(
            exit_btn_frame,
            text="Exit",
            font=("Helvetica", 12),
            bg="#757575",
            fg="white",
            padx=30,
            pady=10,
            cursor="hand2"
        )
        exit_btn.pack()
        
        # Bind click events
        def on_exit_click(e):
            exit_btn.config(bg="#616161")
            self.after(100, lambda: self.quit_app())
        
        def on_exit_enter(e):
            exit_btn.config(bg="#616161")
            exit_btn_frame.config(bg="#616161")
        
        def on_exit_leave(e):
            exit_btn.config(bg="#757575")
            exit_btn_frame.config(bg="#757575")
        
        exit_btn.bind("<Button-1>", on_exit_click)
        exit_btn.bind("<Enter>", on_exit_enter)
        exit_btn.bind("<Leave>", on_exit_leave)
        
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
        
        # Custom "Start Indexing" button using Label for proper color display on macOS
        start_idx_btn_frame = tk.Frame(button_frame, bg="#4CAF50", relief="raised", bd=2)
        start_idx_btn_frame.pack(side=tk.LEFT, padx=10)
        
        start_idx_btn = tk.Label(
            start_idx_btn_frame,
            text="Start Indexing",
            font=("Helvetica", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=10,
            cursor="hand2"
        )
        start_idx_btn.pack()
        
        # Bind click events
        def on_start_idx_click(e):
            start_idx_btn.config(bg="#45a049")
            self.after(100, lambda: self.start_indexing())
        
        def on_start_idx_enter(e):
            start_idx_btn.config(bg="#45a049")
            start_idx_btn_frame.config(bg="#45a049")
        
        def on_start_idx_leave(e):
            start_idx_btn.config(bg="#4CAF50")
            start_idx_btn_frame.config(bg="#4CAF50")
        
        start_idx_btn.bind("<Button-1>", on_start_idx_click)
        start_idx_btn.bind("<Enter>", on_start_idx_enter)
        start_idx_btn.bind("<Leave>", on_start_idx_leave)
        
        # Custom "Choose Different File" button with gray styling
        change_btn_frame = tk.Frame(button_frame, bg="#757575", relief="raised", bd=2)
        change_btn_frame.pack(side=tk.LEFT, padx=10)
        
        change_btn = tk.Label(
            change_btn_frame,
            text="Choose Different File",
            font=("Helvetica", 12),
            bg="#757575",
            fg="white",
            padx=20,
            pady=10,
            cursor="hand2"
        )
        change_btn.pack()
        
        # Bind click events
        def on_change_click(e):
            change_btn.config(bg="#616161")
            self.after(100, lambda: self.select_xml_file())
        
        def on_change_enter(e):
            change_btn.config(bg="#616161")
            change_btn_frame.config(bg="#616161")
        
        def on_change_leave(e):
            change_btn.config(bg="#757575")
            change_btn_frame.config(bg="#757575")
        
        change_btn.bind("<Button-1>", on_change_click)
        change_btn.bind("<Enter>", on_change_enter)
        change_btn.bind("<Leave>", on_change_leave)
    
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
            # Run indexing
            index_library(self.xml_path, force_full=False, sample_size=None)
            self.message_queue.put(('complete', True))
            self.message_queue.put(('log', "\n✅ Indexing completed successfully!"))
        except Exception as e:
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
                messages_processed += 1
        except queue.Empty:
            pass  # No more messages
        
        if self.indexing_thread.is_alive():
            # Still running, check again soon (200ms is gentler on CPU)
            self.after(200, self.check_indexing_status)
        else:
            # Indexing complete - process any remaining messages
            try:
                while True:
                    msg_type, msg_data = self.message_queue.get_nowait()
                    if msg_type == 'log':
                        if hasattr(self, 'log_text'):
                            self.log_text.insert(tk.END, msg_data + "\n")
                            self.log_text.see(tk.END)
                    elif msg_type == 'complete':
                        self.indexing_complete = msg_data
            except queue.Empty:
                pass
            
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
        
        # Custom "Start Using" button using Label for proper color display on macOS
        launch_btn_frame = tk.Frame(button_frame, bg="#4CAF50", relief="raised", bd=2)
        launch_btn_frame.pack()
        
        launch_btn = tk.Label(
            launch_btn_frame,
            text="Start Using Cosine Companion",
            font=("Helvetica", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=10,
            cursor="hand2"
        )
        launch_btn.pack()
        
        # Bind click events
        def on_launch_click(e):
            launch_btn.config(bg="#45a049")
            self.after(100, lambda: self.complete_onboarding())
        
        def on_launch_enter(e):
            launch_btn.config(bg="#45a049")
            launch_btn_frame.config(bg="#45a049")
        
        def on_launch_leave(e):
            launch_btn.config(bg="#4CAF50")
            launch_btn_frame.config(bg="#4CAF50")
        
        launch_btn.bind("<Button-1>", on_launch_click)
        launch_btn.bind("<Enter>", on_launch_enter)
        launch_btn.bind("<Leave>", on_launch_leave)
    
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
        
        # Custom "Try Again" button with orange styling
        retry_btn_frame = tk.Frame(button_frame, bg="#FF9800", relief="raised", bd=2)
        retry_btn_frame.pack(side=tk.LEFT, padx=10)
        
        retry_btn = tk.Label(
            retry_btn_frame,
            text="Try Again",
            font=("Helvetica", 12, "bold"),
            bg="#FF9800",
            fg="white",
            padx=30,
            pady=10,
            cursor="hand2"
        )
        retry_btn.pack()
        
        # Bind click events
        def on_retry_click(e):
            retry_btn.config(bg="#F57C00")
            self.after(100, lambda: self.create_welcome_screen())
        
        def on_retry_enter(e):
            retry_btn.config(bg="#F57C00")
            retry_btn_frame.config(bg="#F57C00")
        
        def on_retry_leave(e):
            retry_btn.config(bg="#FF9800")
            retry_btn_frame.config(bg="#FF9800")
        
        retry_btn.bind("<Button-1>", on_retry_click)
        retry_btn.bind("<Enter>", on_retry_enter)
        retry_btn.bind("<Leave>", on_retry_leave)
        
        # Custom "Exit" button with gray styling
        exit_err_btn_frame = tk.Frame(button_frame, bg="#757575", relief="raised", bd=2)
        exit_err_btn_frame.pack(side=tk.LEFT, padx=10)
        
        exit_err_btn = tk.Label(
            exit_err_btn_frame,
            text="Exit",
            font=("Helvetica", 12),
            bg="#757575",
            fg="white",
            padx=30,
            pady=10,
            cursor="hand2"
        )
        exit_err_btn.pack()
        
        # Bind click events
        def on_exit_err_click(e):
            exit_err_btn.config(bg="#616161")
            self.after(100, lambda: self.quit_app())
        
        def on_exit_err_enter(e):
            exit_err_btn.config(bg="#616161")
            exit_err_btn_frame.config(bg="#616161")
        
        def on_exit_err_leave(e):
            exit_err_btn.config(bg="#757575")
            exit_err_btn_frame.config(bg="#757575")
        
        exit_err_btn.bind("<Button-1>", on_exit_err_click)
        exit_err_btn.bind("<Enter>", on_exit_err_enter)
        exit_err_btn.bind("<Leave>", on_exit_err_leave)
    
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
        from services import SettingsStore

        # replace(), not set(): onboarding has always written the whole document,
        # discarding any other key that happened to be there.
        SettingsStore(DATA / "settings.json").replace({
            "xml_path": self.xml_path,
            "first_run_complete": True
        })
    
    def quit_app(self):
        """Quit the application."""
        if messagebox.askokcancel("Exit", "Are you sure you want to exit?"):
            self.master.quit()
            self.master.destroy()


def needs_onboarding():
    """Check if the app needs to show onboarding."""
    from config import DATA, IDS_JSON, IDX_NPY, EMB_PQ
    from services import SettingsStore

    # If we have all the essential data files, skip onboarding
    # This handles cases where user already has indexed data
    essential_files = [META_PQ, IDS_JSON, IDX_NPY, EMB_PQ]
    if all(f.exists() for f in essential_files):
        # Data exists, skip onboarding
        return False

    # Check if settings indicate first run complete. A missing settings file
    # reads as an empty document, so no data and no settings still means
    # onboarding is needed - exactly as before.
    settings = SettingsStore(DATA / "settings.json")
    return not settings.get("first_run_complete", False)
