"""DataFrame consolidation utilities for time-series data.

Purpose:
--------
General-purpose utilities for merging and analyzing time-series
DataFrames with differing date granularities or missing values.

Works with any dataset containing a date column
(e.g., financial, weather, IoT, crypto).

Functions:
-----------
1. _prep(df, name)
   → Normalize a single DataFrame (rename date, prefix columns,
     set datetime index, add coverage flag).

2. combine_timeframes(dfs, names, persist=True, limit=None)
   → Merge multiple DataFrames into one unified set aligned on date.

3. missing_ranges(mask)
   → Identify consecutive missing-date intervals.

Usage examples:
    # Library usage
    from ta_lab2.tools.data_tools.processing.DataFrame_Consolidation import combine_timeframes, missing_ranges

    # Merge multiple timeframes (e.g. daily, weekly, monthly)
    merged = combine_timeframes(
        [df1, df2, df3],
        ["daily", "weekly", "monthly"],
        persist=True
    )

    # Identify gaps in coverage
    gaps = missing_ranges(~merged["has_daily"])
    print(gaps)

Commenting style:
-----------------
- (S#) Short comment for fast scanning
- (V#) Verbose explanation mapped to the same number (only when helpful)

You can map short ↔ verbose using their numbers.
"""

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None

from functools import reduce
from typing import List, Tuple, Optional


def _check_pandas():
    """Check if pandas is available and raise helpful error if not."""
    if not PANDAS_AVAILABLE:
        raise ImportError(
            "pandas is required for DataFrame_Consolidation. "
            "Install it with: pip install pandas"
        )


# ===========================================================
# STEP 1: Normalize Each Individual DataFrame
# ===========================================================
def _prep(df, name: str):
    """Prepare (normalize) a single DataFrame before merging.

    Args:
        df: pandas DataFrame with date column
        name: Name to prefix columns with

    Returns:
        Normalized DataFrame with prefixed columns and coverage flag
    """
    _check_pandas()

    # (S1) Make a copy to avoid mutating the original object
    df = df.copy()

    # (S2) Rename first column to 'date'
    df.rename(columns={df.columns[0]: "date"}, inplace=True)

    # (V2) Many datasets call their date column 'Date', 'observation_date',
    # or 'timestamp'. Renaming to 'date' ensures uniform expectations later.

    # (S3) Convert date to datetime and sort ascending
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # (V3) Sorting ensures chronological order for forward-filling,
    # cumulative calculations, and clean merges.

    # (S4) Prefix all data columns with the source name
    df.columns = [f"{name}_{c}" for c in df.columns]

    # (V4) Prefixing prevents collisions if multiple sources share
    # identical column names (like "value", "rate", "close", etc.).

    # (S5) Add coverage flag column
    df[f"has_{name}"] = True

    # (V5) This Boolean column marks which dates contain actual data
    # from this source. When we outer-join, missing dates will be False.

    return df


# ===========================================================
# STEP 2: Merge All DataFrames & Handle Missing Data
# ===========================================================
def combine_timeframes(
    dfs: List,
    names: List[str],
    persist: bool = True,
    limit: Optional[int] = None
):
    """Merge multiple DataFrames with different time granularities into one unified, aligned DataFrame.

    Args:
        dfs: List of pandas DataFrames with date columns
        names: List of names for each DataFrame (used for column prefixing)
        persist: If True, forward-fill numeric columns to propagate values
        limit: Maximum number of consecutive NaNs to forward fill (None = unlimited)

    Returns:
        Merged DataFrame with all dates aligned and coverage flags
    """
    _check_pandas()

    # (S6) Validate inputs
    assert len(dfs) == len(names), "dfs and names must be the same length"

    # (V6) Each DataFrame in dfs must have a matching entry in names.
    # Example: dfs=[df1,df2], names=['A','B'] → used for prefixing and flags.

    # (S7) Normalize each DataFrame with _prep()
    prepped = [_prep(df, nm) for df, nm in zip(dfs, names)]

    # (V7) After this, each DataFrame will have standardized columns
    # like '<name>_<col>' and a coverage flag 'has_<name>'.

    # (S8) Outer-join all DataFrames on the date index
    out = reduce(lambda left, right: left.join(right, how="outer"), prepped)

    # (V8) Outer join keeps *all* dates from every dataset — even if
    # one DataFrame doesn't have data on those dates. This avoids losing
    # valuable time points and ensures complete coverage.

    # (S9) Replace missing flags (NaN) with False
    for nm in names:
        out[f"has_{nm}"] = out[f"has_{nm}"].fillna(False)

    # (V9) After joining, some coverage columns will have NaN for
    # missing dates. Setting them to False makes the mask binary again.

    # (S10) Optionally forward-fill numeric columns
    if persist:
        value_cols = [c for c in out.columns if not c.startswith("has_")]
        out[value_cols] = out[value_cols].ffill(limit=limit)

    # (V10) Forward-filling "carries forward" the last known value.
    # Useful in data where values persist until updated (e.g. rates,
    # policies, or measurements not recorded every day).
    # limit=None → fill indefinitely; limit=N → stop after N gaps.

    return out


# ===========================================================
# STEP 3: Identify Missing Date Ranges (warning-free)
# ===========================================================
def missing_ranges(mask) -> List[Tuple]:
    """Identify consecutive missing-date ranges for a given boolean mask.

    Args:
        mask: pandas Series where True = missing, False = present

    Returns:
        List of (start_date, end_date) tuples for consecutive missing ranges
    """
    _check_pandas()

    # (S11) Exit early if mask is empty
    if mask.empty:
        return []

    # (S12) Normalize to pure boolean and handle stray NaNs (treat as not-missing)
    #       (cast to pandas 'boolean' dtype first to avoid FutureWarning on fillna)
    b = mask.astype('boolean').fillna(False)

    # (S13) Detect run starts/ends using shift (no FutureWarnings)
    starts = (~b.shift(1, fill_value=False)) & b    # False→True
    ends   = b & (~b.shift(-1, fill_value=False))   # True→False

    # (V13) 'starts' marks transitions where a missing block begins;
    # 'ends' marks where it ends. We pair these into intervals.

    # (S14) Build (start, end) pairs of missing ranges
    starts_idx = b.index[starts]
    ends_idx   = b.index[ends]
    return list(zip(starts_idx, ends_idx))


# ===========================================================
# Public API
# ===========================================================
__all__ = [
    "combine_timeframes",
    "missing_ranges",
]
