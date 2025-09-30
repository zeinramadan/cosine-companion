"""DJ Companion UI package."""

from ui.app import App


def run_ui():
    """Run the DJ Companion UI application."""
    app = App()
    app.mainloop()


__all__ = ['App', 'run_ui']
