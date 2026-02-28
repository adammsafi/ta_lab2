"""
ta_lab2.labeling -- AFML-inspired labeling primitives.

Modules:
    cusum_filter      -- Symmetric CUSUM event filter (AFML Ch.17)
    trend_scanning    -- OLS t-value trend scanning labels (AFML ML4AM Ch.2)
    triple_barrier    -- Triple barrier labels (+1/-1/0) with vol-scaled barriers (AFML Ch.3)
"""

from ta_lab2.labeling.cusum_filter import (
    cusum_filter,
    get_cusum_threshold,
    validate_cusum_density,
)
from ta_lab2.labeling.trend_scanning import (
    trend_scanning_labels,
    get_trend_weights,
    get_t1_series,
)
from ta_lab2.labeling.triple_barrier import (
    add_vertical_barrier,
    apply_triple_barriers,
    get_bins,
    get_daily_vol,
)

__all__ = [
    # CUSUM event filter
    "cusum_filter",
    "get_cusum_threshold",
    "validate_cusum_density",
    # Trend scanning
    "trend_scanning_labels",
    "get_trend_weights",
    "get_t1_series",
    # Triple barrier
    "get_daily_vol",
    "add_vertical_barrier",
    "apply_triple_barriers",
    "get_bins",
]
