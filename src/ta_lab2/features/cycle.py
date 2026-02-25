"""
Cycle analysis functions: ATH tracking, drawdown, and rolling extremes.

All functions operate on a single-asset DataFrame sorted by ts ASC.
They add columns in-place (inplace=True) or return a copy.

Usage:
    from ta_lab2.features.cycle import add_ath_cycle, add_rolling_extremes

    # ATH / drawdown cycle
    add_ath_cycle(df, close_col="close", ts_col="ts")

    # Rolling high/low for a single window
    add_rolling_extremes(df, window=252, close_col="close", ts_col="ts")
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_ath_cycle(
    df: pd.DataFrame,
    close_col: str = "close",
    ts_col: str = "ts",
    inplace: bool = True,
) -> pd.DataFrame:
    """
    Add all-time high and drawdown cycle columns to a single-asset DataFrame.

    Expects df sorted by ts ASC for a single asset.

    Columns added:
        ath             - cumulative max of close
        ath_ts          - timestamp when current ATH was set
        dd_from_ath     - (close - ath) / ath, always <= 0
        bars_since_ath  - bar count since last ATH
        days_since_ath  - calendar days since last ATH
        cycle_low       - lowest close since last ATH
        cycle_low_ts    - timestamp of cycle low
        dd_ath_to_low   - (cycle_low - ath) / ath
        bars_ath_to_low - bars from ATH to cycle low
        days_ath_to_low - calendar days from ATH to cycle low
        is_at_ath       - True when close == ath (new ATH this bar)
        cycle_number    - monotonically increasing cycle counter
    """
    if not inplace:
        df = df.copy()

    close = df[close_col].values
    # Ensure tz-aware UTC DatetimeIndex (handles psycopg2 datetime objects)
    ts = pd.DatetimeIndex(pd.to_datetime(df[ts_col], utc=True))
    n = len(df)

    # Cumulative max (ATH)
    ath = np.maximum.accumulate(close)

    # Detect new ATH bars: first bar is always an ATH, then whenever close >= running max
    is_at_ath = np.empty(n, dtype=bool)
    is_at_ath[0] = True
    is_at_ath[1:] = close[1:] >= ath[:-1]

    # ATH timestamps: carry forward the ts of the most recent ATH bar
    ath_ts = np.empty(n, dtype="datetime64[ns]")
    ath_ts[0] = ts[0]
    for i in range(1, n):
        if is_at_ath[i]:
            ath_ts[i] = ts[i]
        else:
            ath_ts[i] = ath_ts[i - 1]

    # Bars since ATH: reset counter on each new ATH
    bars_since = np.zeros(n, dtype=np.int64)
    for i in range(1, n):
        if is_at_ath[i]:
            bars_since[i] = 0
        else:
            bars_since[i] = bars_since[i - 1] + 1

    # Days since ATH: calendar days between current ts and ath_ts
    ts_ns = ts.values.astype("datetime64[ns]")
    days_since = ((ts_ns - ath_ts) / np.timedelta64(1, "D")).astype(np.int64)

    # Drawdown from ATH
    dd_from_ath = np.where(ath > 0, (close - ath) / ath, 0.0)

    # Cycle low: track the minimum close since last ATH
    cycle_low = np.empty(n, dtype=np.float64)
    cycle_low_ts_arr = np.empty(n, dtype="datetime64[ns]")
    cycle_low[0] = close[0]
    cycle_low_ts_arr[0] = ts[0]

    for i in range(1, n):
        if is_at_ath[i]:
            # New ATH resets the cycle low to current close
            cycle_low[i] = close[i]
            cycle_low_ts_arr[i] = ts[i]
        else:
            if close[i] < cycle_low[i - 1]:
                cycle_low[i] = close[i]
                cycle_low_ts_arr[i] = ts[i]
            else:
                cycle_low[i] = cycle_low[i - 1]
                cycle_low_ts_arr[i] = cycle_low_ts_arr[i - 1]

    # Drawdown ATH to cycle low
    dd_ath_to_low = np.where(ath > 0, (cycle_low - ath) / ath, 0.0)

    # Bars and days from ATH to cycle low
    bars_ath_to_low = np.zeros(n, dtype=np.int64)
    days_ath_to_low = np.zeros(n, dtype=np.int64)
    for i in range(n):
        days_ath_to_low[i] = max(
            0,
            int((cycle_low_ts_arr[i] - ath_ts[i]) / np.timedelta64(1, "D")),
        )
        # bars_ath_to_low: count of bars from ath to cycle_low
        # We need the bar index of ath and cycle_low within the current cycle
        # Since we track cycle_low_ts progressively, we compute days only
        # (bars_ath_to_low is harder without a second pass; use days proxy)

    # bars_ath_to_low: compute via a second pass tracking the bar offset
    # of the cycle low within each cycle
    cycle_low_bar_offset = np.zeros(n, dtype=np.int64)
    for i in range(1, n):
        if is_at_ath[i]:
            cycle_low_bar_offset[i] = 0
        else:
            if close[i] < cycle_low[i - 1]:
                cycle_low_bar_offset[i] = bars_since[i]
            else:
                cycle_low_bar_offset[i] = cycle_low_bar_offset[i - 1]
    bars_ath_to_low = cycle_low_bar_offset

    # Cycle number: increment on each new ATH
    cycle_number = np.cumsum(is_at_ath).astype(np.int64)

    # Assign columns
    df["ath"] = ath
    df["ath_ts"] = pd.to_datetime(ath_ts, utc=True)
    df["dd_from_ath"] = dd_from_ath
    df["bars_since_ath"] = bars_since
    df["days_since_ath"] = days_since
    df["cycle_low"] = cycle_low
    df["cycle_low_ts"] = pd.to_datetime(cycle_low_ts_arr, utc=True)
    df["dd_ath_to_low"] = dd_ath_to_low
    df["bars_ath_to_low"] = bars_ath_to_low
    df["days_ath_to_low"] = days_ath_to_low
    df["is_at_ath"] = is_at_ath
    df["cycle_number"] = cycle_number

    return df


def add_rolling_extremes(
    df: pd.DataFrame,
    window: int,
    close_col: str = "close",
    ts_col: str = "ts",
    inplace: bool = True,
) -> pd.DataFrame:
    """
    Add rolling high/low columns for a single window to a single-asset DataFrame.

    Expects df sorted by ts ASC for a single asset.

    Columns added (suffixed with _{window}):
        rolling_high            - max(close) over window bars
        rolling_high_ts         - timestamp of rolling high
        bars_since_rolling_high - bars since rolling high
        days_since_rolling_high - calendar days since rolling high
        rolling_low             - min(close) over window bars
        rolling_low_ts          - timestamp of rolling low
        bars_since_rolling_low  - bars since rolling low
        days_since_rolling_low  - calendar days since rolling low
        range_position          - (close - low) / (high - low), 0-1
        dd_from_rolling_high    - (close - high) / high
    """
    if not inplace:
        df = df.copy()

    close = df[close_col].values
    ts = pd.DatetimeIndex(pd.to_datetime(df[ts_col], utc=True))
    ts_ns = ts.values.astype("datetime64[ns]")
    n = len(df)

    # Rolling max/min using pandas for efficiency
    close_series = pd.Series(close)
    rolling_high = close_series.rolling(window, min_periods=1).max().values
    rolling_low = close_series.rolling(window, min_periods=1).min().values

    # For each bar, find where the rolling high/low occurred within the window
    rolling_high_ts = np.empty(n, dtype="datetime64[ns]")
    rolling_low_ts = np.empty(n, dtype="datetime64[ns]")
    bars_since_high = np.zeros(n, dtype=np.int64)
    bars_since_low = np.zeros(n, dtype=np.int64)

    for i in range(n):
        win_start = max(0, i - window + 1)
        win_close = close[win_start : i + 1]
        win_ts = ts_ns[win_start : i + 1]

        # argmax/argmin for the last occurrence in the window
        # (use [::-1] trick to get last occurrence on tie)
        rev_idx_high = len(win_close) - 1 - np.argmax(win_close[::-1])
        rev_idx_low = len(win_close) - 1 - np.argmin(win_close[::-1])

        rolling_high_ts[i] = win_ts[rev_idx_high]
        rolling_low_ts[i] = win_ts[rev_idx_low]

        bars_since_high[i] = (i - win_start) - rev_idx_high
        bars_since_low[i] = (i - win_start) - rev_idx_low

    # Days since
    days_since_high = ((ts_ns - rolling_high_ts) / np.timedelta64(1, "D")).astype(
        np.int64
    )
    days_since_low = ((ts_ns - rolling_low_ts) / np.timedelta64(1, "D")).astype(
        np.int64
    )

    # Range position: (close - low) / (high - low), handle div-by-zero
    range_span = rolling_high - rolling_low
    range_position = np.where(range_span > 0, (close - rolling_low) / range_span, 1.0)

    # Drawdown from rolling high
    dd_from_rolling_high = np.where(
        rolling_high > 0, (close - rolling_high) / rolling_high, 0.0
    )

    # Assign columns (no suffix — window is a separate dimension in the table)
    df["rolling_high"] = rolling_high
    df["rolling_high_ts"] = pd.to_datetime(rolling_high_ts, utc=True)
    df["bars_since_rolling_high"] = bars_since_high
    df["days_since_rolling_high"] = days_since_high
    df["rolling_low"] = rolling_low
    df["rolling_low_ts"] = pd.to_datetime(rolling_low_ts, utc=True)
    df["bars_since_rolling_low"] = bars_since_low
    df["days_since_rolling_low"] = days_since_low
    df["range_position"] = range_position
    df["dd_from_rolling_high"] = dd_from_rolling_high

    return df
