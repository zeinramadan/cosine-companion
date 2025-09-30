#!/usr/bin/env python3
"""Data models for DJ set creation."""

from dataclasses import dataclass


@dataclass
class SetTrack:
    """Represents a track in a generated DJ set."""
    track_id: str
    position: int
    is_anchor: bool
    score: float = 0.0
    artist: str = ""
    title: str = ""
    
    @property
    def display_name(self) -> str:
        """Get display name for UI."""
        if self.artist and self.title:
            return f"{self.artist} – {self.title}"
        elif self.artist:
            return f"{self.artist} – (Unknown Title)"
        elif self.title:
            return f"(Unknown Artist) – {self.title}"
        else:
            # Last resort: return track_id, but clean it up if it looks like a number
            if self.track_id.isdigit():
                return f"Track #{self.track_id}"
            return self.track_id
    
    @property
    def icon(self) -> str:
        """Return icon for UI display."""
        return "🔒" if self.is_anchor else "🤖"
