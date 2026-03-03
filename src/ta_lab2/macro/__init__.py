"""ta_lab2.macro -- FRED macro feature computation.

Public API:
    load_series_wide        -- Read fred.series_values, pivot to wide DataFrame
    forward_fill_with_limits -- Forward-fill with per-frequency limits + provenance
    compute_macro_features  -- Full pipeline: load -> ffill -> derive -> rename

Phase 65: FRED Table & Core Features
"""

from ta_lab2.macro.feature_computer import compute_macro_features
from ta_lab2.macro.forward_fill import forward_fill_with_limits
from ta_lab2.macro.fred_reader import load_series_wide

__all__ = [
    "load_series_wide",
    "forward_fill_with_limits",
    "compute_macro_features",
]
