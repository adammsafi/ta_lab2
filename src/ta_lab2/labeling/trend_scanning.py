"""
Trend scanning labels -- AFML "Machine Learning for Asset Managers" Ch.2
(Lopez de Prado, 2020).

Overview
--------
Trend scanning is an *alternative* to triple-barrier labeling suited for
trend-following strategies.  Instead of defining a fixed holding period and
barrier levels, trend scanning searches over a range of look-forward windows
and selects the window with the maximum absolute OLS t-statistic.

The core idea: fit an OLS regression of log-price on time for each candidate
window [i, i+L-1].  The t-value of the slope coefficient measures how
*strongly trending* the price was over that window.  A large positive t-value
indicates an uptrend; a large negative t-value indicates a downtrend.

Label assignment::

    bin = sign(t_value)   if |t_value| > min_tvalue_threshold
    bin = 0               otherwise   (weak or no trend)

Comparison with triple barrier
--------------------------------
- Triple barrier: requires upfront barrier calibration (pt/sl/t1).  Good for
  mean-reversion and regime-aware strategies.
- Trend scanning: self-adaptive; no barrier calibration needed.  Better for
  pure trend-following.  t-values double as sample weights (higher confidence
  labels receive more weight in training).

Performance note
----------------
The naive O(n * L) loop is slow for large series (>10K bars).  For
production, apply trend scanning only on CUSUM-filtered events:

    from ta_lab2.labeling.cusum_filter import cusum_filter
    t_events = cusum_filter(close, threshold)
    labels = trend_scanning_labels(close, t_events=t_events)

This reduces n by 80-95% and makes the computation tractable.

Downstream compatibility
------------------------
``get_t1_series`` returns a ``pd.Series`` in the format expected by
``ta_lab2.experiments.cv.PurgedKFoldSplitter``.  Trend scanning is a
*standalone library module* -- it is not wired to any downstream consumer in
Phase 57.  It will be consumed by Phase 60+ trend-following strategy
development.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import linregress


# ---------------------------------------------------------------------------
# Core labeling function
# ---------------------------------------------------------------------------


def trend_scanning_labels(
    price_series: pd.Series,
    look_forward_window: int = 20,
    min_sample_length: int = 5,
    min_tvalue_threshold: float = 0.0,
    t_events: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Compute OLS t-value based trend scanning labels.

    For each position in the series (or each event in ``t_events``), OLS
    regressions are fit over windows from ``min_sample_length`` to
    ``look_forward_window`` bars.  The window with the maximum absolute
    t-value is selected.  The t-value sign gives the label direction.

    Parameters
    ----------
    price_series : pd.Series
        Close price series with a DatetimeIndex (tz-aware recommended).
    look_forward_window : int
        Maximum number of bars to look forward from each event.  Default 20.
    min_sample_length : int
        Minimum OLS regression window.  Must be >= 2.  Default 5.
    min_tvalue_threshold : float
        Minimum |t-value| for a non-zero label.  Labels with
        |t_value| <= threshold are assigned bin=0.  Default 0.0 (every
        bar gets +1 or -1).
    t_events : pd.DatetimeIndex or None
        If provided, only compute labels for these timestamps.  Must be a
        subset of ``price_series.index``.  If None, compute for every bar
        that has at least ``min_sample_length`` bars remaining.

    Returns
    -------
    pd.DataFrame
        Index: label start timestamps (subset of price_series.index).
        Columns:
            ``t1``     -- end timestamp of the optimal regression window
            ``tvalue`` -- OLS t-statistic at optimal window length
            ``bin``    -- label in {-1, 0, +1}
    """
    if min_sample_length < 2:
        raise ValueError(f"min_sample_length must be >= 2, got {min_sample_length}")
    if look_forward_window < min_sample_length:
        raise ValueError(
            f"look_forward_window ({look_forward_window}) must be >= "
            f"min_sample_length ({min_sample_length})"
        )

    log_close = np.log(price_series)
    idx = price_series.index
    n = len(idx)

    # Determine which start positions to evaluate
    if t_events is not None:
        # Only positions corresponding to t_events
        positions = [
            i
            for i, ts in enumerate(idx)
            if ts in t_events and i + min_sample_length <= n
        ]
    else:
        # Every bar that has at least min_sample_length bars ahead
        positions = list(range(n - min_sample_length + 1))

    records: list[dict] = []

    for i in positions:
        max_abs_t = -1.0
        best_t_val = 0.0
        best_end_idx = i + min_sample_length - 1

        # Upper bound of window: cannot exceed series length
        max_L = min(look_forward_window, n - i)

        for L in range(min_sample_length, max_L + 1):
            y = log_close.iloc[i : i + L].values
            x = np.arange(L, dtype=float)

            result = linregress(x, y)
            slope = result.slope
            stderr = result.stderr

            # t-value of slope = slope / stderr
            t_val = slope / stderr if stderr > 1e-15 else 0.0

            abs_t = abs(t_val)
            if abs_t > max_abs_t:
                max_abs_t = abs_t
                best_t_val = t_val
                best_end_idx = i + L - 1

        t1_ts = idx[best_end_idx]
        bin_label = int(np.sign(best_t_val)) if max_abs_t > min_tvalue_threshold else 0

        records.append(
            {
                "t0": idx[i],
                "t1": t1_ts,
                "tvalue": best_t_val,
                "bin": bin_label,
            }
        )

    if not records:
        return pd.DataFrame(
            columns=["t1", "tvalue", "bin"],
            index=pd.DatetimeIndex([], tz=getattr(idx, "tz", None)),
        )

    df = pd.DataFrame(records).set_index("t0")
    df.index.name = None
    return df[["t1", "tvalue", "bin"]]


# ---------------------------------------------------------------------------
# Sample weight helper
# ---------------------------------------------------------------------------


def get_trend_weights(trend_df: pd.DataFrame) -> pd.Series:
    """Normalize absolute t-values to [0, 1] range for use as sample weights.

    Higher |t-value| = higher confidence label = higher training weight.
    This implements the t-value-as-sample-weight idea from AFML ML4AM Ch.2.

    Parameters
    ----------
    trend_df : pd.DataFrame
        Output of ``trend_scanning_labels``.  Must have a ``tvalue`` column.

    Returns
    -------
    pd.Series
        Float weights in [0, 1], same index as ``trend_df``.  If all
        t-values are equal (zero variance), returns uniform weights of 1.0.
    """
    abs_t = np.abs(trend_df["tvalue"])
    t_max = abs_t.max()
    if t_max == 0.0:
        return pd.Series(np.ones(len(trend_df)), index=trend_df.index)
    return abs_t / t_max


# ---------------------------------------------------------------------------
# cv.py-compatible t1_series helper
# ---------------------------------------------------------------------------


def get_t1_series(trend_df: pd.DataFrame) -> pd.Series:
    """Extract a t1_series compatible with ``PurgedKFoldSplitter``.

    ``PurgedKFoldSplitter`` (see ``ta_lab2.experiments.cv``) expects a
    ``pd.Series`` where index = label start timestamps and values = label
    end timestamps, both tz-aware UTC.

    Parameters
    ----------
    trend_df : pd.DataFrame
        Output of ``trend_scanning_labels``.  Must have a ``t1`` column.

    Returns
    -------
    pd.Series
        t1_series with tz-aware timestamps.  If the input ``t1`` values are
        tz-naive, they are localized to UTC to ensure downstream compatibility.
    """
    t1_col = trend_df["t1"]

    # Normalize to tz-aware UTC.
    # CRITICAL: .values on a tz-aware datetime Series strips the timezone
    # (returns tz-naive numpy.datetime64).  Use .tolist() instead to preserve
    # tz-aware Timestamp objects, then reconstruct via pd.DatetimeIndex.
    if hasattr(t1_col, "dt") and t1_col.dt.tz is not None:
        # Already tz-aware -- use tolist() to preserve tz info
        t1_list = t1_col.tolist()
    elif hasattr(t1_col, "dt") and t1_col.dt.tz is None:
        # Tz-naive -- localize to UTC
        t1_list = t1_col.dt.tz_localize("UTC").tolist()
    else:
        # Fallback: parse as UTC
        t1_list = pd.to_datetime(t1_col, utc=True).tolist()

    t1_index = pd.DatetimeIndex(t1_list)

    # Ensure index is tz-aware UTC
    idx = trend_df.index
    if hasattr(idx, "tz") and idx.tz is None:
        idx = idx.tz_localize("UTC")

    return pd.Series(t1_index, index=idx)
