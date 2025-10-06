"""Cosine Companion UI package."""

import tkinter as tk
from ui.app import App
from ui.onboarding import OnboardingWindow, needs_onboarding


def run_ui():
    """Run the Cosine Companion UI application."""
    # Create root window (initially hidden)
    root = tk.Tk(className='Cosine Companion')
    # Set icon on the root immediately to avoid initial oversized icon before UI is shown
    try:
        from utils.icon import set_window_icon
        set_window_icon(root)
    except Exception:
        pass
    root.withdraw()  # Hide until ready
    
    if needs_onboarding():
        # Show onboarding for first-time users
        def on_onboarding_complete():
            # Destroy the onboarding window and root to clean up
            root.quit()  # Exit the mainloop
            root.destroy()  # Destroy the root window
            # Create and run the main app
            app = App()
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
