"""Track recommendation system with similarity search and set generation."""

from recommendations.engine import recommend_for, vector_for
from recommendations.scoring import key_compat, bpm_compat, final_score
from recommendations.models import SetTrack
from recommendations.set_generator import generate_set
from recommendations.transitions import calculate_transition_score
from recommendations.search import search_tracks

__all__ = [
    'recommend_for',
    'vector_for',
    'key_compat',
    'bpm_compat',
    'final_score',
    'SetTrack',
    'generate_set',
    'calculate_transition_score',
    'search_tracks',
]
