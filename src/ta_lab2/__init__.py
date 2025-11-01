# src/ta_lab2/__init__.py
"""
ta_lab2
--------

Technical Analysis and Regime Detection Lab
Modular feature extraction, volatility analytics, and visualization toolkit.
"""

from .regimes.run_btc_pipeline import run_btc_pipeline

# === Feature Modules ===
from .features.calendar import (
    expand_datetime_features_inplace,
    expand_multiple_timestamps,
)
from .features.trend import compute_trend_labels
from .features.segments import build_flip_segments

# === Visualization ===
from .viz.all_plots import (
    plot_ema_with_trend,
    plot_consolidated_emas_like,
    plot_realized_vol,
)

__version__ = "0.1.0"

__all__ = [
    # Core pipeline
    "run_btc_pipeline",

    # Features
    "expand_datetime_features_inplace",
    "expand_multiple_timestamps",
    "compute_trend_labels",
    "build_flip_segments",

    # Visualization
    "plot_ema_with_trend",
    "plot_consolidated_emas_like",
    "plot_realized_vol",
]
