"""Economic data utilities extracted from fedtools2.

This module provides time series consolidation and I/O utilities
that were extracted from the archived fedtools2 package. These
utilities have general applicability for economic and financial
time series work.

Extracted from: fedtools2 (archived 2026-02-03)
Original purpose: ETL consolidation of Federal Reserve policy target datasets
Archive location: .archive/external-packages/2026-02-03/fedtools2/

Functions:
    combine_timeframes: Merge multiple time series with coverage tracking
    missing_ranges: Detect gaps in boolean mask series
    read_csv: Read CSV with standardized DataFrame output
    ensure_dir: Create directory with parents if needed

Example:
    >>> from ta_lab2.utils.economic import combine_timeframes, missing_ranges
    >>> merged = combine_timeframes([df1, df2], ["series1", "series2"])
    >>> gaps = missing_ranges(merged["has_series1"] == False)
"""

from ta_lab2.utils.economic.consolidation import combine_timeframes, missing_ranges
from ta_lab2.utils.economic.io_helpers import read_csv, ensure_dir

__all__ = [
    "combine_timeframes",
    "missing_ranges",
    "read_csv",
    "ensure_dir",
]
