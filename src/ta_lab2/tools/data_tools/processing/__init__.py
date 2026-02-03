"""Processing tools migrated from Data_Tools.

Tools:
- DataFrame_Consolidation: Time-series DataFrame merging utilities with differing granularities

Usage examples:
    # Import functions directly
    from ta_lab2.tools.data_tools.processing import combine_timeframes, missing_ranges

    # Merge multiple timeframes (e.g. daily, weekly, monthly)
    merged = combine_timeframes(
        [df1, df2, df3],
        ["daily", "weekly", "monthly"],
        persist=True
    )

    # Identify gaps in coverage
    gaps = missing_ranges(~merged["has_daily"])

Dependencies:
    - pandas: pip install pandas
"""

from ta_lab2.tools.data_tools.processing.DataFrame_Consolidation import (
    combine_timeframes,
    missing_ranges,
)

__all__ = [
    "combine_timeframes",
    "missing_ranges",
]
