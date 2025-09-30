"""Configuration and shared constants for DJ Companion."""

from config.paths import DATA, MODELS, META_PQ, EMB_PQ, IDX_NPY, IDS_JSON
from config.defaults import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SCORING_WEIGHTS,
    DEFAULT_TOPK,
    DEFAULT_FINAL_TOP
)

__all__ = [
    'DATA',
    'MODELS',
    'META_PQ',
    'EMB_PQ',
    'IDX_NPY',
    'IDS_JSON',
    'DEFAULT_SAMPLE_RATE',
    'DEFAULT_SCORING_WEIGHTS',
    'DEFAULT_TOPK',
    'DEFAULT_FINAL_TOP',
]
