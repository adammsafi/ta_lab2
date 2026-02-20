"""
Regime scripts - DB-backed regime labeling and refresh utilities.

This package provides the integration layer between the regime module
(src/ta_lab2/regimes/) and the PostgreSQL feature pipeline.

The regime module is fully implemented (labels, resolver, data_budget, etc.).
This package provides the DB I/O glue: queries, pivots, and output writes.

Exports:
    - load_bars_for_tf: Load OHLCV bars from DB for a given TF
    - load_and_pivot_emas: Load EMAs from DB and pivot to wide format
    - load_regime_input_data: Master function loading all 3 TF datasets
    - pivot_emas_to_wide: Utility to pivot long-format EMAs to wide format
"""

from .regime_data_loader import (
    load_bars_for_tf,
    load_and_pivot_emas,
    load_regime_input_data,
    pivot_emas_to_wide,
)

__all__ = [
    "load_bars_for_tf",
    "load_and_pivot_emas",
    "load_regime_input_data",
    "pivot_emas_to_wide",
]
