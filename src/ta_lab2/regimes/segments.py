# src/ta_lab2/regimes/segments.py
"""
Shim to preserve legacy imports:
    from ta_lab2.regimes.segments import build_flip_segments

The actual implementation lives in `ta_lab2.features.segments`.
"""

from __future__ import annotations
from ..features.segments import build_flip_segments

__all__ = ["build_flip_segments"]
