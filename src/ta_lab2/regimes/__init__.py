# src/ta_lab2/regimes/__init__.py
"""
Public API for `ta_lab2.regimes`.

Exports analytics utilities from `comovement` and the `build_flip_segments`
shim (implementation lives in `ta_lab2.features.segments`).
"""

from .comovement import (
    compute_ema_comovement_stats,
    compute_ema_comovement_hierarchy,
    build_alignment_frame,
    sign_agreement,
    rolling_agreement,
    forward_return_split,
    lead_lag_max_corr,
)

# Legacy import path:
#   from ta_lab2.regimes.segments import build_flip_segments
# The actual implementation resides in ta_lab2.features.segments.
from .segments import build_flip_segments

__all__ = [
    "compute_ema_comovement_stats",
    "compute_ema_comovement_hierarchy",
    "build_alignment_frame",
    "sign_agreement",
    "rolling_agreement",
    "forward_return_split",
    "lead_lag_max_corr",
    "build_flip_segments",
]
