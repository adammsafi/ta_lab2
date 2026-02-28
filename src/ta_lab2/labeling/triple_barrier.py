"""
Triple barrier labeling for financial machine learning.

Implements the triple barrier method from AFML Ch.3 (Lopez de Prado, 2018)
from scratch -- no mlfinpy dependency.

The triple barrier method labels each event (entry) with one of three outcomes:
  +1  profit target (upper barrier) hit first
  -1  stop loss (lower barrier) hit first
   0  vertical barrier (timeout) hit first, or no barrier reached

Barriers are vol-scaled: the distance to each barrier is proportional to the
EWM standard deviation of log returns at the event start (daily_vol).

Functions
---------
get_daily_vol(close, span=100)
    EWM std of log returns. Used to size barriers.

add_vertical_barrier(t_events, close, num_bars=5)
    Bar-count-based vertical barrier timestamps.

apply_triple_barriers(close, t_events, pt_sl, target, num_bars=5, side_prediction=None)
    Core labeler. Returns DataFrame with t1/ret/bin/barrier_type columns.
    Index is tz-aware UTC DatetimeIndex (t0 timestamps).
    t1 column is tz-aware UTC.

get_bins(triple_barrier_df, close)
    Convenience wrapper: recomputes ret from close prices.

get_t1_series(triple_barrier_df)
    Extract t1_series compatible with PurgedKFoldSplitter/CPCVSplitter.
    Uses .tolist() to preserve tz-aware timestamps (avoids .values tz-strip pitfall).

Notes
-----
- All timestamps are tz-aware UTC (compatible with PurgedKFoldSplitter/CPCVSplitter
  in src/ta_lab2/backtests/cv.py).
- Bar-count vertical barriers are used (NOT calendar time) to avoid the pitfall
  of variable bar density around weekends/holidays.
- CRITICAL: On Windows, series.values on tz-aware datetime Series returns
  tz-NAIVE numpy.datetime64. Use get_t1_series() or .tolist() to preserve tz.
- Performance: correctness-first Python loop over events, vectorized search per event.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def get_daily_vol(close: pd.Series, span: int = 100) -> pd.Series:
    """
    Compute EWM standard deviation of log returns.

    This is the daily volatility estimate used to scale barrier distances.
    The result is aligned to the same index as close (with NaN at the start
    where no return can be computed).

    Parameters
    ----------
    close : pd.Series
        Close prices. Index must be a DatetimeIndex (tz-aware recommended).
    span : int, default 100
        Span for EWM std calculation. Higher values produce smoother vol.

    Returns
    -------
    pd.Series
        EWM std of log returns, same index as close. First value is NaN.
    """
    log_ret = np.log(close / close.shift(1))
    daily_vol = log_ret.ewm(span=span).std()
    return daily_vol


def add_vertical_barrier(
    t_events: pd.DatetimeIndex,
    close: pd.Series,
    num_bars: int = 5,
) -> pd.Series:
    """
    Compute bar-count-based vertical barrier timestamps.

    For each event in t_events, finds the timestamp num_bars bars later
    in the close index. Uses bar count (NOT calendar time) so the barrier
    distance is consistent regardless of trading session gaps.

    Parameters
    ----------
    t_events : pd.DatetimeIndex
        Event start timestamps. Must be a subset of close.index.
    close : pd.Series
        Close prices. Index must be monotonically increasing DatetimeIndex.
    num_bars : int, default 5
        Number of bars after t0 to place the vertical barrier.

    Returns
    -------
    pd.Series
        Index = t_events (subsetted to valid events), tz-aware UTC.
        Values = vertical barrier timestamps, tz-aware UTC.
    """
    # Find index positions of each event in close
    t0_positions = close.index.searchsorted(t_events)

    # Advance by num_bars, clamped to last bar
    t1_positions = np.minimum(t0_positions + num_bars, len(close) - 1)

    # Map back to timestamps using tolist() to preserve tz-awareness
    # (avoids the Windows numpy.datetime64 tz-strip pitfall on .values)
    t1_timestamps = pd.DatetimeIndex(close.index[t1_positions].tolist())

    # Build Series aligned to t_events that are within the close index
    valid_mask = t0_positions < len(close)
    valid_events = t_events[valid_mask]
    valid_t1 = t1_timestamps[valid_mask]

    return pd.Series(valid_t1.tolist(), index=valid_events, dtype="datetime64[ns, UTC]")


def apply_triple_barriers(
    close: pd.Series,
    t_events: pd.DatetimeIndex,
    pt_sl: list[float],
    target: pd.Series,
    num_bars: int = 5,
    side_prediction: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Apply the triple barrier method to label each event.

    For each event (entry) at time t0:
    1. Compute vol-scaled barriers using target[t0] (EWM daily vol).
    2. Upper barrier: entry_price * (1 + pt_sl[0] * vol) -- profit target.
    3. Lower barrier: entry_price * (1 - pt_sl[1] * vol) -- stop loss.
    4. Vertical barrier: close at t0 + num_bars bars -- timeout.
    5. Search the price path [t0, t1_vert] for the first barrier touch.
    6. Assign bin: +1 (upper hit), -1 (lower hit), 0 (no barrier or timeout).

    Parameters
    ----------
    close : pd.Series
        Close prices. Index must be a tz-aware DatetimeIndex.
    t_events : pd.DatetimeIndex
        Event start timestamps (label start = entry time).
    pt_sl : list of float
        [pt_multiplier, sl_multiplier]. Multiply by daily vol to get barrier width.
        Pass [0.0, X] to disable profit target. Pass [X, 0.0] to disable stop loss.
    target : pd.Series
        Daily vol series from get_daily_vol(). Used to size the barriers.
    num_bars : int, default 5
        Number of bars for the vertical barrier (timeout).
    side_prediction : pd.Series or None, optional
        If provided, enables meta-labeling mode:
        - side=+1: only upper barrier counts as profit (lower is stop).
        - side=-1: only lower barrier counts as profit (upper is stop).
        Index must match t_events.

    Returns
    -------
    pd.DataFrame
        Index = t_events (only events where vol is available), tz-aware UTC.
        Columns:
          t1           : datetime64[ns, UTC] -- when barrier was hit (or vertical barrier)
          ret          : float64 -- log return at barrier hit
          bin          : int8 -- +1, -1, or 0
          barrier_type : str -- 'pt', 'sl', or 'vb'

    Notes
    -----
    Use get_t1_series(result) to extract the t1_series for PurgedKFoldSplitter.
    Do NOT use result['t1'].values -- on Windows this strips tz-awareness.
    """
    # Build vertical barriers for all events
    t1_vertical = add_vertical_barrier(t_events, close, num_bars=num_bars)

    pt_mult = pt_sl[0]
    sl_mult = pt_sl[1]

    records: list[dict] = []
    valid_t0_list: list = []

    for t0 in t_events:
        # Skip events not in the price index
        if t0 not in close.index:
            continue

        # Skip events where target vol is not available
        if t0 not in target.index or pd.isna(target.loc[t0]):
            continue

        vol = float(target.loc[t0])
        entry_price = float(close.loc[t0])

        # Vertical barrier timestamp
        if t0 not in t1_vertical.index:
            continue
        t1_vert = t1_vertical.loc[t0]

        # Determine side for meta-labeling (default: treat as long)
        if side_prediction is not None and t0 in side_prediction.index:
            side = int(side_prediction.loc[t0])
        else:
            side = 1  # Default: long

        # Compute barrier levels
        if side == 1:
            # Long: upper = profit target, lower = stop loss
            upper = entry_price * (1.0 + pt_mult * vol) if pt_mult > 0 else np.inf
            lower = entry_price * (1.0 - sl_mult * vol) if sl_mult > 0 else -np.inf
        else:
            # Short: lower = profit target, upper = stop loss
            upper = entry_price * (1.0 + sl_mult * vol) if sl_mult > 0 else np.inf
            lower = entry_price * (1.0 - pt_mult * vol) if pt_mult > 0 else -np.inf

        # Extract price path from t0 to t1_vert (inclusive)
        path = close.loc[t0:t1_vert]

        # Search for first barrier touch
        hit_t1 = t1_vert
        hit_bin = 0
        hit_type = "vb"

        for ts, price in path.items():
            if ts == t0:
                continue  # skip entry bar itself
            if side == 1:
                if price >= upper:
                    hit_t1 = ts
                    hit_bin = 1
                    hit_type = "pt"
                    break
                if price <= lower:
                    hit_t1 = ts
                    hit_bin = -1
                    hit_type = "sl"
                    break
            else:
                # Short: lower hit = profit, upper hit = stop
                if price <= lower:
                    hit_t1 = ts
                    hit_bin = 1
                    hit_type = "pt"
                    break
                if price >= upper:
                    hit_t1 = ts
                    hit_bin = -1
                    hit_type = "sl"
                    break

        # Compute return at barrier hit
        hit_price = float(close.loc[hit_t1]) if hit_t1 in close.index else np.nan
        if np.isfinite(entry_price) and entry_price > 0 and np.isfinite(hit_price):
            ret = np.log(hit_price / entry_price)
        else:
            ret = np.nan

        records.append(
            {
                "t1": hit_t1,
                "ret": ret,
                "bin": hit_bin,
                "barrier_type": hit_type,
            }
        )
        valid_t0_list.append(t0)

    if not records:
        idx = pd.DatetimeIndex([], tz="UTC")
        return pd.DataFrame(columns=["t1", "ret", "bin", "barrier_type"], index=idx)

    # Build tz-aware UTC index using tolist() to preserve tz
    # (avoids Windows numpy.datetime64 tz-strip pitfall when using .values)
    idx = (
        pd.DatetimeIndex(valid_t0_list).tz_localize("UTC")
        if (len(valid_t0_list) > 0 and pd.DatetimeIndex(valid_t0_list).tz is None)
        else pd.DatetimeIndex(valid_t0_list)
    )

    result = pd.DataFrame(records, index=idx)

    # Ensure t1 column is tz-aware UTC
    # Use tolist() on any existing tz-aware series to avoid tz-strip via .values
    t1_vals = [r["t1"] for r in records]
    result["t1"] = (
        pd.DatetimeIndex(t1_vals).tz_localize("UTC")
        if (len(t1_vals) > 0 and pd.DatetimeIndex(t1_vals).tz is None)
        else pd.DatetimeIndex(t1_vals)
    )

    # Typed columns
    result["bin"] = result["bin"].astype("int8")

    return result


def get_bins(triple_barrier_df: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    """
    Recompute returns from close prices for a triple barrier output DataFrame.

    Convenience wrapper that recalculates the ret column using the actual
    close prices at t0 (index) and t1 (column). Useful when apply_triple_barriers
    was called on a subset of the price series and ret needs to be rechecked.

    Parameters
    ----------
    triple_barrier_df : pd.DataFrame
        Output from apply_triple_barriers(). Must have a 't1' column.
        Index = t0 (label start timestamps, tz-aware UTC).
    close : pd.Series
        Full close price series. Index must be a DatetimeIndex.

    Returns
    -------
    pd.DataFrame
        Same as triple_barrier_df but with 'ret' column filled from close prices.
        Rows where t0 or t1 is not in close.index get NaN ret.
    """
    df = triple_barrier_df.copy()

    t0_prices = close.reindex(df.index)
    # Use tolist() to preserve tz when building the DatetimeIndex for t1 lookup
    t1_idx = pd.DatetimeIndex(df["t1"].tolist())
    t1_prices = close.reindex(t1_idx)

    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.log(t1_prices.values / t0_prices.values)

    df["ret"] = np.where(np.isfinite(ret), ret, np.nan)

    return df


def get_t1_series(triple_barrier_df: pd.DataFrame) -> pd.Series:
    """
    Extract a tz-aware t1_series compatible with PurgedKFoldSplitter/CPCVSplitter.

    This is the canonical way to build the t1_series argument for
    PurgedKFoldSplitter and CPCVSplitter from apply_triple_barriers output.

    On Windows, using pd.Series(result['t1'].values, ...) strips tz-awareness
    from the datetime values (numpy.datetime64 loses tz info). This function
    uses .tolist() to correctly preserve tz-aware timestamps.

    Parameters
    ----------
    triple_barrier_df : pd.DataFrame
        Output from apply_triple_barriers(). Must have a 't1' column.
        Index = t0 (tz-aware UTC DatetimeIndex).

    Returns
    -------
    pd.Series
        Index = t0 timestamps (tz-aware UTC).
        Values = t1 timestamps (tz-aware UTC).
        Suitable for passing as t1_series to PurgedKFoldSplitter/CPCVSplitter.
    """
    # Use tolist() to preserve tz-awareness (avoids Windows .values tz-strip pitfall)
    t1_list = triple_barrier_df["t1"].tolist()
    return pd.Series(
        t1_list, index=triple_barrier_df.index, dtype="datetime64[ns, UTC]"
    )
