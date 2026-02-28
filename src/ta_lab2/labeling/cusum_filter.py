"""
Symmetric CUSUM event filter -- AFML Ch.17 (Lopez de Prado, 2018).

Overview
--------
The symmetric CUSUM filter is a noise-reduction pre-filter that converts a
continuous price series into a sparse set of event timestamps.  Only these
"interesting" timestamps are passed to triple-barrier labeling, which:

1. Reduces the number of labels to train on (less overlap, less leakage).
2. Focuses the model on bars where something actually happened.

The algorithm tracks two running sums (s_pos for up-moves, s_neg for
down-moves).  Whenever one of them crosses a threshold h the current
timestamp is recorded as an event and **that accumulator is reset to zero**.
The reset-to-zero mechanism is essential: without it the filter would
double-fire on sustained trends, producing pathologically high densities.

Symmetric CUSUM vs one-sided CUSUM
------------------------------------
Lopez de Prado uses the *symmetric* variant (tracks both sides) so the filter
captures both bullish and bearish events.  A one-sided CUSUM (e.g., only
s_pos) would miss downside events and bias the label distribution.

Downstream usage
----------------
The returned ``pd.DatetimeIndex`` is passed directly as ``t_events`` to
``apply_triple_barriers`` (see ``ta_lab2.labeling.triple_barrier``):

    from ta_lab2.labeling.cusum_filter import cusum_filter, get_cusum_threshold
    from ta_lab2.labeling.triple_barrier import apply_triple_barriers

    h = get_cusum_threshold(close)
    t_events = cusum_filter(close, h)
    labels = apply_triple_barriers(close, t_events=t_events, ...)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Core filter
# ---------------------------------------------------------------------------


def cusum_filter(raw_series: pd.Series, threshold: float) -> pd.DatetimeIndex:
    """Apply a symmetric CUSUM filter and return event timestamps.

    The filter operates on the first difference of *raw_series* (typically
    close prices).  It accumulates positive deviations in ``s_pos`` and
    negative deviations in ``s_neg``.  When either accumulator crosses
    +-threshold the current timestamp is appended to the event list and that
    accumulator is **reset to zero** (not the other one).

    Parameters
    ----------
    raw_series : pd.Series
        Price (or any level) series with a DatetimeIndex.  The function
        computes diff() internally so you should pass close prices, not
        returns.
    threshold : float
        Positive scalar.  Smaller thresholds produce more events (higher
        density).  Use ``get_cusum_threshold`` to calibrate per-asset.

    Returns
    -------
    pd.DatetimeIndex
        Timestamps of triggered events, tz-aware if the input index is
        tz-aware.  Length is between 0 and len(raw_series).
    """
    if threshold <= 0:
        raise ValueError(f"threshold must be positive, got {threshold}")

    t_events: list = []
    s_pos: float = 0.0
    s_neg: float = 0.0

    # Use log-price differences so the filter operates on the same scale
    # as the log-return-based threshold from get_cusum_threshold.
    # For a price series p, log(p[t]) - log(p[t-1]) ≈ (p[t]-p[t-1]) / p[t-1],
    # which is consistent with the EWM std of log-returns used as threshold.
    log_series = np.log(raw_series)
    diff = log_series.diff().dropna()

    for ts, val in diff.items():
        s_pos = max(0.0, s_pos + val)
        s_neg = min(0.0, s_neg + val)

        if s_pos >= threshold:
            s_pos = 0.0
            t_events.append(ts)
        elif s_neg <= -threshold:
            s_neg = 0.0
            t_events.append(ts)

    return pd.DatetimeIndex(t_events)


# ---------------------------------------------------------------------------
# Threshold calibration
# ---------------------------------------------------------------------------


def get_cusum_threshold(
    close: pd.Series,
    multiplier: float = 2.0,
    vol_span: int = 100,
) -> float:
    """Compute a per-asset CUSUM threshold from exponential-weighted volatility.

    The threshold is derived from the mean EWM standard deviation of
    log-returns, scaled by *multiplier*.  This keeps the filter adaptive:
    high-volatility assets get a larger threshold (fewer triggers) while
    low-volatility assets get a smaller one.

    Parameters
    ----------
    close : pd.Series
        Close price series.
    multiplier : float
        Scaling factor applied to the EWM std.  Default 2.0 gives roughly
        5-30% event density on typical crypto daily data.
    vol_span : int
        EWM span (in bars) for the volatility estimate.  Default 100.

    Returns
    -------
    float
        Positive threshold scalar.
    """
    log_returns = np.log(close / close.shift(1)).dropna()
    ewm_std = log_returns.ewm(span=vol_span).std()
    threshold = float(ewm_std.mean() * multiplier)
    return threshold


# ---------------------------------------------------------------------------
# Density validation
# ---------------------------------------------------------------------------


def validate_cusum_density(
    n_events: int,
    n_bars: int,
    target_min: float = 0.05,
    target_max: float = 0.60,
) -> dict:
    """Validate that the event density is within a target range.

    Density = n_events / n_bars.  Targets of 5-60% are typical:
    - Below 5%: Too sparse -- model will have very few training samples.
    - Above 60%: Too dense -- filter is not reducing noise meaningfully.

    Parameters
    ----------
    n_events : int
        Number of events returned by ``cusum_filter``.
    n_bars : int
        Total number of bars in the original series.
    target_min : float
        Minimum acceptable density.  Default 0.05.
    target_max : float
        Maximum acceptable density.  Default 0.60.

    Returns
    -------
    dict
        Keys: ``density`` (float), ``within_target`` (bool),
        ``recommendation`` (str).
    """
    if n_bars <= 0:
        raise ValueError(f"n_bars must be positive, got {n_bars}")

    density = n_events / n_bars
    within_target = target_min <= density <= target_max

    if density > target_max:
        recommendation = (
            f"threshold too low -- increase multiplier "
            f"(density={density:.1%} > target_max={target_max:.1%})"
        )
    elif density < target_min:
        recommendation = (
            f"threshold too high -- decrease multiplier "
            f"(density={density:.1%} < target_min={target_min:.1%})"
        )
    else:
        recommendation = (
            f"threshold is well-calibrated "
            f"(density={density:.1%} within [{target_min:.1%}, {target_max:.1%}])"
        )

    return {
        "density": density,
        "within_target": within_target,
        "recommendation": recommendation,
    }
