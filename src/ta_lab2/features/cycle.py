"""
Cycle analysis functions: ATH tracking, drawdown, and rolling extremes.

All functions operate on a single-asset DataFrame sorted by ts ASC.
They add columns in-place (inplace=True) or return a copy.

Performance: Inner loops use numba JIT. Rolling argmax/argmin uses O(n)
monotonic deque algorithm instead of O(n*w) naive scan.

Usage:
    from ta_lab2.features.cycle import add_ath_cycle, add_rolling_extremes

    # ATH / drawdown cycle
    add_ath_cycle(df, close_col="close", ts_col="ts")

    # Rolling high/low for a single window
    add_rolling_extremes(df, window=252, close_col="close", ts_col="ts")
"""

from __future__ import annotations

import warnings

import numba as nb
import numpy as np
import pandas as pd


# =============================================================================
# Numba kernels — compiled once, reused across calls
# =============================================================================


@nb.njit(cache=True)
def _ath_cycle_kernel(
    close: np.ndarray,
    ts_i64: np.ndarray,
    ath: np.ndarray,
    ath_ts_i64: np.ndarray,
    is_at_ath: np.ndarray,
    bars_since: np.ndarray,
    cycle_low: np.ndarray,
    cycle_low_ts_i64: np.ndarray,
    cycle_low_bar_offset: np.ndarray,
) -> None:
    """Single-pass ATH cycle kernel. All arrays pre-allocated by caller."""
    n = len(close)
    if n == 0:
        return

    ath[0] = close[0]
    is_at_ath[0] = True
    ath_ts_i64[0] = ts_i64[0]
    bars_since[0] = 0
    cycle_low[0] = close[0]
    cycle_low_ts_i64[0] = ts_i64[0]
    cycle_low_bar_offset[0] = 0

    for i in range(1, n):
        # ATH: cummax
        if close[i] >= ath[i - 1]:
            ath[i] = close[i]
            is_at_ath[i] = True
            ath_ts_i64[i] = ts_i64[i]
            bars_since[i] = 0
            cycle_low[i] = close[i]
            cycle_low_ts_i64[i] = ts_i64[i]
            cycle_low_bar_offset[i] = 0
        else:
            ath[i] = ath[i - 1]
            is_at_ath[i] = False
            ath_ts_i64[i] = ath_ts_i64[i - 1]
            bars_since[i] = bars_since[i - 1] + 1
            # Cycle low tracking
            if close[i] < cycle_low[i - 1]:
                cycle_low[i] = close[i]
                cycle_low_ts_i64[i] = ts_i64[i]
                cycle_low_bar_offset[i] = bars_since[i]
            else:
                cycle_low[i] = cycle_low[i - 1]
                cycle_low_ts_i64[i] = cycle_low_ts_i64[i - 1]
                cycle_low_bar_offset[i] = cycle_low_bar_offset[i - 1]


@nb.njit(cache=True)
def _rolling_argmax_deque(close: np.ndarray, window: int) -> np.ndarray:
    """
    O(n) sliding window argmax using monotonic deque.

    Returns array where result[i] = index of max value in close[max(0,i-w+1):i+1].
    On ties, returns the LAST (most recent) occurrence.
    """
    n = len(close)
    result = np.empty(n, dtype=np.int64)

    # Monotonic deque: stores indices in decreasing order of close value
    # We simulate a deque with a fixed-size array + head/tail pointers
    dq = np.empty(n, dtype=np.int64)
    head = 0
    tail = 0  # dq[head:tail] is the active deque

    for i in range(n):
        # Remove elements outside the window
        while head < tail and dq[head] < i - window + 1:
            head += 1
        # Remove elements smaller than current (maintain decreasing order)
        # Use >= to keep the LAST occurrence on tie
        while head < tail and close[dq[tail - 1]] <= close[i]:
            tail -= 1
        dq[tail] = i
        tail += 1
        result[i] = dq[head]

    return result


@nb.njit(cache=True)
def _rolling_argmin_deque(close: np.ndarray, window: int) -> np.ndarray:
    """
    O(n) sliding window argmin using monotonic deque.

    Returns array where result[i] = index of min value in close[max(0,i-w+1):i+1].
    On ties, returns the LAST (most recent) occurrence.
    """
    n = len(close)
    result = np.empty(n, dtype=np.int64)

    dq = np.empty(n, dtype=np.int64)
    head = 0
    tail = 0

    for i in range(n):
        while head < tail and dq[head] < i - window + 1:
            head += 1
        # Use >= to keep the LAST occurrence on tie
        while head < tail and close[dq[tail - 1]] >= close[i]:
            tail -= 1
        dq[tail] = i
        tail += 1
        result[i] = dq[head]

    return result


# =============================================================================
# Public API
# =============================================================================


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
        ath, ath_ts, dd_from_ath, bars_since_ath, days_since_ath,
        cycle_low, cycle_low_ts, dd_ath_to_low, bars_ath_to_low,
        days_ath_to_low, is_at_ath, cycle_number
    """
    if not inplace:
        df = df.copy()

    close = df[close_col].values.astype(np.float64)
    ts = pd.DatetimeIndex(pd.to_datetime(df[ts_col], utc=True))
    ts_ns = ts.values.astype("datetime64[ns]")
    ts_i64 = ts_ns.view(np.int64)
    n = len(df)

    # Pre-allocate output arrays
    ath = np.empty(n, dtype=np.float64)
    ath_ts_i64 = np.empty(n, dtype=np.int64)
    is_at_ath = np.empty(n, dtype=np.bool_)
    bars_since = np.empty(n, dtype=np.int64)
    cycle_low = np.empty(n, dtype=np.float64)
    cycle_low_ts_i64 = np.empty(n, dtype=np.int64)
    cycle_low_bar_offset = np.empty(n, dtype=np.int64)

    # Single-pass numba kernel
    _ath_cycle_kernel(
        close,
        ts_i64,
        ath,
        ath_ts_i64,
        is_at_ath,
        bars_since,
        cycle_low,
        cycle_low_ts_i64,
        cycle_low_bar_offset,
    )

    # Vectorized derived columns (numpy, no loops)
    ath_ts_ns = ath_ts_i64.view("datetime64[ns]")
    cycle_low_ts_ns = cycle_low_ts_i64.view("datetime64[ns]")

    dd_from_ath = np.where(ath > 0, (close - ath) / ath, 0.0)
    days_since = ((ts_ns - ath_ts_ns) / np.timedelta64(1, "D")).astype(np.int64)
    dd_ath_to_low = np.where(ath > 0, (cycle_low - ath) / ath, 0.0)
    days_ath_to_low = np.maximum(
        0,
        ((cycle_low_ts_ns - ath_ts_ns) / np.timedelta64(1, "D")).astype(np.int64),
    )
    cycle_number = np.cumsum(is_at_ath).astype(np.int64)

    # Assign columns — suppress numpy tz warnings (we restore UTC below)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        df["ath"] = ath
        df["ath_ts"] = pd.to_datetime(ath_ts_ns, utc=True)
        df["dd_from_ath"] = dd_from_ath
        df["bars_since_ath"] = bars_since
        df["days_since_ath"] = days_since
        df["cycle_low"] = cycle_low
        df["cycle_low_ts"] = pd.to_datetime(cycle_low_ts_ns, utc=True)
        df["dd_ath_to_low"] = dd_ath_to_low
        df["bars_ath_to_low"] = cycle_low_bar_offset
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

    Uses O(n) monotonic deque for argmax/argmin (not O(n*w) naive scan).

    Columns added:
        rolling_high, rolling_high_ts, bars_since_rolling_high,
        days_since_rolling_high, rolling_low, rolling_low_ts,
        bars_since_rolling_low, days_since_rolling_low,
        range_position, dd_from_rolling_high
    """
    if not inplace:
        df = df.copy()

    close = df[close_col].values.astype(np.float64)
    ts = pd.DatetimeIndex(pd.to_datetime(df[ts_col], utc=True))
    ts_ns = ts.values.astype("datetime64[ns]")
    n = len(df)

    # O(n) rolling argmax/argmin via numba monotonic deque
    idx_high = _rolling_argmax_deque(close, window)
    idx_low = _rolling_argmin_deque(close, window)

    # Gather values at the argmax/argmin positions (vectorized)
    rolling_high = close[idx_high]
    rolling_low = close[idx_low]
    rolling_high_ts_ns = ts_ns[idx_high]
    rolling_low_ts_ns = ts_ns[idx_low]

    # Bars since = current index - argmax/argmin index
    arange = np.arange(n, dtype=np.int64)
    bars_since_high = arange - idx_high
    bars_since_low = arange - idx_low

    # Days since (vectorized)
    days_since_high = ((ts_ns - rolling_high_ts_ns) / np.timedelta64(1, "D")).astype(
        np.int64
    )
    days_since_low = ((ts_ns - rolling_low_ts_ns) / np.timedelta64(1, "D")).astype(
        np.int64
    )

    # Range position and drawdown (vectorized)
    range_span = rolling_high - rolling_low
    with np.errstate(invalid="ignore"):
        range_position = np.where(
            range_span > 0, (close - rolling_low) / range_span, 1.0
        )
    dd_from_rolling_high = np.where(
        rolling_high > 0, (close - rolling_high) / rolling_high, 0.0
    )

    # Assign columns
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        df["rolling_high"] = rolling_high
        df["rolling_high_ts"] = pd.to_datetime(rolling_high_ts_ns, utc=True)
        df["bars_since_rolling_high"] = bars_since_high
        df["days_since_rolling_high"] = days_since_high
        df["rolling_low"] = rolling_low
        df["rolling_low_ts"] = pd.to_datetime(rolling_low_ts_ns, utc=True)
        df["bars_since_rolling_low"] = bars_since_low
        df["days_since_rolling_low"] = days_since_low
        df["range_position"] = range_position
        df["dd_from_rolling_high"] = dd_from_rolling_high

    return df
