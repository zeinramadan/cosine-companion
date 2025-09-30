"""DJ Companion UI package."""

import tkinter as tk
from ui.app import App
from ui.onboarding import OnboardingWindow, needs_onboarding


def run_ui():
    """Run the DJ Companion UI application."""
    # Create root window (initially hidden)
    root = tk.Tk()
    root.withdraw()  # Hide until ready
    
    if needs_onboarding():
        # Show onboarding for first-time users
        def on_onboarding_complete():
            root.deiconify()  # Show main window
            app = App()
            # Transfer control to the new app window
            root.withdraw()
            app.mainloop()
        
        # Show onboarding window
        onboarding = OnboardingWindow(root, on_onboarding_complete)
        root.mainloop()
    else:
        # Show main app directly
        root.destroy()  # Clean up hidden root
        app = App()
        app.mainloop()


__all__ = ['App', 'run_ui', 'OnboardingWindow', 'needs_onboarding']
