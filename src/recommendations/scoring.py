#!/usr/bin/env python3
"""Key and BPM compatibility scoring for DJ mixing."""

from typing import Optional

from config import DEFAULT_SCORING_WEIGHTS


camelot_to_idx = {f"{n}{l}": i for i, (n, l) in enumerate((n, l) for l in ("A", "B") for n in range(1, 13))}

key_to_camelot = {
    # Minors (A): 1A..12A
    "G#m": "1A", "Abm": "1A",
    "D#m": "2A", "Ebm": "2A",
    "A#m": "3A", "Bbm": "3A",
    "Fm": "4A",
    "Cm": "5A",
    "Gm": "6A",
    "Dm": "7A",
    "Am": "8A",
    "Em": "9A",
    "Bm": "10A",
    "F#m": "11A", "Gbm": "11A",
    "C#m": "12A", "Dbm": "12A",

    # Majors (B): 1B..12B
    "B": "1B", "Cb": "1B",
    "F#": "2B", "Gb": "2B",
    "Db": "3B", "C#": "3B",
    "Ab": "4B", "G#": "4B",
    "Eb": "5B", "D#": "5B",
    "Bb": "6B", "A#": "6B",
    "F": "7B", "E#": "7B",
    "C": "8B",
    "G": "9B",
    "D": "10B",
    "A": "11B",
    "E": "12B", "Fb": "12B",
}


def to_camelot(k: str | None) -> Optional[str]:
    """Convert a musical key to Camelot notation."""
    if not k:
        return None
    k = k.strip()
    if k in camelot_to_idx:
        return k
    return key_to_camelot.get(k)


def key_compat(src: Optional[str], dst: Optional[str]) -> float:
    """
    Calculate key compatibility score between two tracks.
    
    Returns:
        1.0 for perfect match, 0.8 for adjacent keys, 0.6 for relative keys,
        0.4 for 2-step keys, 0.0 for incompatible keys
    """
    s = to_camelot(src)
    d = to_camelot(dst)
    if not s or not d:
        return 0.0
    sn, sm = int(s[:-1]), s[-1]
    dn, dm = int(d[:-1]), d[-1]
    if s == d:
        return 1.0
    if sm == dm and ((sn - dn) % 12 in (1, 11)):
        return 0.8
    if sn == dn and sm != dm:
        return 0.6
    if sm == dm and ((sn - dn) % 12 in (2, 10)):
        return 0.4
    return 0.0


def bpm_compat(sbpm: Optional[float], dbpm: Optional[float], pct: float = 0.06) -> float:
    """
    Calculate BPM compatibility score between two tracks.
    
    Returns:
        1.0 for matching BPM (within tolerance), 0.7 for half/double time, 0.0 otherwise
    """
    if not sbpm or not dbpm:
        return 0.0
    lo, hi = sbpm * (1 - pct), sbpm * (1 + pct)
    if lo <= dbpm <= hi:
        return 1.0
    for mult in (0.5, 2.0):
        b = sbpm * mult
        lo, hi = b * (1 - pct), b * (1 + pct)
        if lo <= dbpm <= hi:
            return 0.7
    return 0.0


def final_score(cosine: float, key_score: float, bpm_score: float,
               weights: tuple = DEFAULT_SCORING_WEIGHTS) -> float:
    """
    Calculate final recommendation score from component scores.
    
    Args:
        cosine: Cosine similarity score
        key_score: Key compatibility score
        bpm_score: BPM compatibility score
        weights: Tuple of (cosine_weight, key_weight, bpm_weight)
        
    Returns:
        Weighted final score
    """
    a, b, c = weights
    return a * cosine + b * key_score + c * bpm_score
