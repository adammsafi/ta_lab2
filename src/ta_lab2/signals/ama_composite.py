# src/ta_lab2/signals/ama_composite.py
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
AMA-based signal generators for the Phase 82 bake-off.

Three signal generators, one per strategy archetype:

1. ama_momentum_signal (momentum / trend-following)
   Computes an IC-IR-weighted composite from the top-5 AMA columns by IC-IR,
   z-scores the composite over a rolling window, and enters long when the
   z-score exceeds a threshold.

2. ama_mean_reversion_signal (mean-reversion)
   Computes the spread between price and a chosen AMA, z-scores it, and enters
   long when price is significantly below the AMA (spread z-score < entry_zscore).

3. ama_regime_conditional_signal (regime-conditional)
   Uses the sign of an AMA's first derivative as the trend direction, then
   gates entries on ADX strength.  If `filter_col` (ADX) is absent from the
   DataFrame it is computed locally from OHLC.

CRITICAL: All three functions READ pre-computed AMA columns from the DataFrame.
They do NOT re-compute AMA values from price.  AMA columns are loaded from the
database by load_strategy_data_with_ama() (Plan 01) before these functions are
called.  See the "Pitfall 6" section of 82-RESEARCH.md for why this matters:
local AMA recomputation introduces fold-boundary lookback contamination.

Signature for all three:
    (df: pd.DataFrame, **params) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]
returning (entries: bool Series, exits: bool Series, size: None or float Series).
"""

__all__ = [
    "ama_momentum_signal",
    "ama_mean_reversion_signal",
    "ama_regime_conditional_signal",
]

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants: top-5 AMA features by IC-IR from configs/feature_selection.yaml
# (IC-IR values from 82-RESEARCH.md: TEMA_0fca19a1=1.433, DEMA_0fca19a1=1.376,
#  KAMA_987fc105=1.291, HMA_514ffe35=1.271, TEMA_514ffe35=1.257)
# ---------------------------------------------------------------------------
_DEFAULT_AMA_COLS: List[str] = [
    "TEMA_0fca19a1_ama",
    "KAMA_987fc105_ama",
    "HMA_514ffe35_ama",
    "TEMA_514ffe35_ama",
    "DEMA_0fca19a1_ama",
]

_DEFAULT_IC_IR_WEIGHTS: List[float] = [1.433, 1.291, 1.271, 1.257, 1.376]


def _normalize_weights(weights: List[float]) -> List[float]:
    """Normalize a list of weights so they sum to 1.0."""
    total = sum(weights)
    if total <= 0:
        n = len(weights)
        return [1.0 / n] * n
    return [w / total for w in weights]


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling z-score with a minimum of 2 observations."""
    roll = series.rolling(window=window, min_periods=2)
    mean = roll.mean()
    std = roll.std(ddof=1).replace(0.0, np.nan)
    return (series - mean) / std


def _bars_since_entry(entries: pd.Series) -> pd.Series:
    """
    Return a Series counting bars elapsed since the most recent True in `entries`.
    Returns 0 on entry bars and increments from there.  Returns NaN before the
    first entry.
    """
    result = pd.Series(np.nan, index=entries.index, dtype=float)
    counter: Optional[int] = None
    for i, (idx, val) in enumerate(entries.items()):
        if val:
            counter = 0
        elif counter is not None:
            counter += 1
        if counter is not None:
            result.iloc[i] = counter
    return result


# ---------------------------------------------------------------------------
# Signal 1: AMA momentum (momentum / trend-following archetype)
# ---------------------------------------------------------------------------
def ama_momentum_signal(
    df: pd.DataFrame,
    *,
    ama_cols: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
    holding_bars: int = 7,
    threshold: float = 0.0,
    zscore_window: int = 20,
    allow_shorts: bool = False,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    Momentum signal using an IC-IR-weighted composite of AMA columns.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain pre-loaded AMA columns (e.g., ``TEMA_0fca19a1_ama``).
    ama_cols : list[str], optional
        AMA feature columns to include in the composite.  Defaults to the
        top-5 by IC-IR from Phase 80 feature selection.
    weights : list[float], optional
        IC-IR weights corresponding to *ama_cols*.  Defaults to IC-IR values
        for the default columns.  Will be normalized to sum=1.
    holding_bars : int
        Maximum holding period in bars before a forced exit.
    threshold : float
        Composite z-score threshold.  Enter long when z-score > threshold;
        exit when z-score < -threshold.
    zscore_window : int
        Rolling window for composite z-score normalization.
    allow_shorts : bool
        If True, also enter short when z-score < -threshold.

    Returns
    -------
    entries, exits, size : (bool Series, bool Series, None)
    """
    if ama_cols is None:
        ama_cols = _DEFAULT_AMA_COLS
    if weights is None:
        # Use default IC-IR weights, keeping only the ones that correspond to
        # the default ama_cols ordering.
        if ama_cols is _DEFAULT_AMA_COLS or ama_cols == _DEFAULT_AMA_COLS:
            weights = list(_DEFAULT_IC_IR_WEIGHTS)
        else:
            weights = [1.0] * len(ama_cols)

    # Filter to only columns that are present in df (graceful degradation)
    pairs = [(col, w) for col, w in zip(ama_cols, weights) if col in df.columns]

    if not pairs:
        # No AMA columns available -- return empty signals
        empty = pd.Series(False, index=df.index)
        return empty, empty, None

    available_cols, available_weights = zip(*pairs)
    norm_weights = _normalize_weights(list(available_weights))

    # Weighted composite (NaN from warmup are treated as 0 contribution)
    composite = sum(
        w * df[col].fillna(0.0) for col, w in zip(available_cols, norm_weights)
    )

    # Rolling z-score of the composite
    zscore = _rolling_zscore(composite, zscore_window)

    # Entry / exit logic
    entries = pd.Series(False, index=df.index)
    exits = pd.Series(False, index=df.index)

    long_entry_mask = zscore > threshold
    long_exit_mask = zscore < -threshold

    # Holding-bar forced exit: exit if position has been open for >= holding_bars
    bars_held = _bars_since_entry(long_entry_mask)
    holding_exit = bars_held >= holding_bars

    entries = long_entry_mask
    exits = long_exit_mask | holding_exit

    if allow_shorts:
        # For simplicity in this implementation, entries include both long and
        # short triggers, and exits cover both directions.
        short_entry_mask = zscore < -threshold
        short_exit_mask = zscore > threshold
        short_bars_held = _bars_since_entry(short_entry_mask)
        short_holding_exit = short_bars_held >= holding_bars
        entries = entries | short_entry_mask
        exits = exits | short_exit_mask | short_holding_exit

    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    return entries, exits, None


# ---------------------------------------------------------------------------
# Signal 2: AMA mean-reversion (mean-reversion archetype)
# ---------------------------------------------------------------------------
def ama_mean_reversion_signal(
    df: pd.DataFrame,
    *,
    ama_col: str = "KAMA_de1106d5_ama",
    price_col: str = "close",
    zscore_window: int = 20,
    entry_zscore: float = -1.5,
    exit_zscore: float = 0.0,
    holding_bars: int = 10,
    allow_shorts: bool = False,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    Mean-reversion signal: enter when price deviates significantly below AMA.

    The spread ``price - AMA`` is z-scored over a rolling window.  A long
    entry fires when the z-score drops below *entry_zscore* (price is
    significantly below AMA), and exits when the z-score returns above
    *exit_zscore* (price has returned to AMA) or after *holding_bars* bars.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain *price_col* and *ama_col*.
    ama_col : str
        AMA column to revert to.  Defaults to KAMA_de1106d5_ama (KAMA 10,2,30
        — medium-speed adaptive MA, good for mean-reversion).
    price_col : str
        Price column.  Defaults to ``'close'``.
    zscore_window : int
        Rolling window for spread z-score.
    entry_zscore : float
        Spread z-score threshold for long entry (should be negative).
    exit_zscore : float
        Spread z-score threshold for long exit.
    holding_bars : int
        Maximum holding period in bars.
    allow_shorts : bool
        If True, enter short when spread z-score exceeds abs(entry_zscore).

    Returns
    -------
    entries, exits, size : (bool Series, bool Series, None)
    """
    entries = pd.Series(False, index=df.index)
    exits = pd.Series(False, index=df.index)

    if price_col not in df.columns or ama_col not in df.columns:
        return entries, exits, None

    price = df[price_col]
    ama = df[ama_col]

    # Spread: positive when price is above AMA, negative when below
    spread = price - ama

    # Z-score of spread using rolling std
    roll_std = spread.rolling(window=zscore_window, min_periods=2).std(ddof=1)
    roll_std = roll_std.replace(0.0, np.nan)
    roll_mean = spread.rolling(window=zscore_window, min_periods=2).mean()
    zscore = (spread - roll_mean) / roll_std

    # Long entry: price significantly below AMA (spread z-score very negative)
    long_entry = zscore < entry_zscore
    # Long exit: spread z-score has recovered or holding period exceeded
    long_exit_signal = zscore > exit_zscore
    bars_held = _bars_since_entry(long_entry)
    holding_exit = bars_held >= holding_bars

    entries = long_entry
    exits = long_exit_signal | holding_exit

    if allow_shorts:
        # Short when price is significantly above AMA (overextended to upside)
        short_threshold = abs(entry_zscore)
        short_entry = zscore > short_threshold
        short_exit_signal = zscore < -exit_zscore
        short_bars_held = _bars_since_entry(short_entry)
        short_holding_exit = short_bars_held >= holding_bars
        entries = entries | short_entry
        exits = exits | short_exit_signal | short_holding_exit

    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    return entries, exits, None


# ---------------------------------------------------------------------------
# Helper: minimal ADX computation (Wilder smoothing, 14-period)
# ---------------------------------------------------------------------------
def _compute_adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """
    Compute ADX from OHLC columns.  Requires 'high', 'low', 'close'.
    Returns a Series of ADX values indexed like df.  Returns a zero Series
    if required columns are missing.
    """
    req = {"high", "low", "close"}
    col = f"adx_{n}"
    if not req.issubset(set(df.columns)):
        return pd.Series(0.0, index=df.index, name=col)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    # True Range
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Directional movement
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Wilder smoothing
    atr_w = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = (
        100.0
        * plus_dm.ewm(alpha=1 / n, adjust=False).mean()
        / atr_w.replace(0.0, np.nan)
    )
    minus_di = (
        100.0
        * minus_dm.ewm(alpha=1 / n, adjust=False).mean()
        / atr_w.replace(0.0, np.nan)
    )

    # DX and ADX
    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()

    return adx.rename(col)


# ---------------------------------------------------------------------------
# Signal 3: AMA regime-conditional (regime-conditional archetype)
# ---------------------------------------------------------------------------
def ama_regime_conditional_signal(
    df: pd.DataFrame,
    *,
    trend_col: str = "DEMA_d47fe5cc_ama",
    filter_col: str = "adx_14",
    adx_threshold: float = 20.0,
    holding_bars: int = 7,
    allow_shorts: bool = False,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    Regime-conditional signal: AMA trend direction gated by ADX trend strength.

    Only enters when the market is trending (ADX > *adx_threshold*).  Trend
    direction is determined by the sign of the AMA's first derivative
    (``diff()``).

    Parameters
    ----------
    df : pd.DataFrame
        Should contain *trend_col*.  If *filter_col* (ADX) is absent, it is
        computed locally from OHLC columns.
    trend_col : str
        AMA column used to determine trend direction.  Defaults to
        DEMA_d47fe5cc_ama (DEMA with params hash d47fe5cc).
    filter_col : str
        ADX column name.  Computed locally if absent.
    adx_threshold : float
        Minimum ADX for entering trades (trending market filter).
    holding_bars : int
        Maximum holding period in bars before a forced exit.
    allow_shorts : bool
        If True, also enter short when trend is down and ADX > threshold.

    Returns
    -------
    entries, exits, size : (bool Series, bool Series, None)
    """
    entries = pd.Series(False, index=df.index)
    exits = pd.Series(False, index=df.index)

    if trend_col not in df.columns:
        return entries, exits, None

    # ADX: use from df if present, otherwise compute locally
    if filter_col in df.columns:
        adx = df[filter_col]
    else:
        # Parse period from col name if possible (e.g., "adx_14" -> 14)
        try:
            adx_period = int(filter_col.split("_")[-1])
        except (ValueError, IndexError):
            adx_period = 14
        adx = _compute_adx(df, adx_period)

    trend_series = df[trend_col]

    # Trend direction: sign of the first derivative of the AMA
    trend_direction = np.sign(trend_series.diff())

    # Trending market filter
    is_trending = adx > adx_threshold

    # Long entry: AMA trending up and market is trending
    long_entry = (trend_direction > 0) & is_trending
    # Long exit: trend reverses OR ADX drops below threshold
    long_exit_signal = (trend_direction < 0) | ~is_trending
    bars_held = _bars_since_entry(long_entry)
    holding_exit = bars_held >= holding_bars

    entries = long_entry
    exits = long_exit_signal | holding_exit

    if allow_shorts:
        # Short entry: AMA trending down and market is trending
        short_entry = (trend_direction < 0) & is_trending
        short_exit_signal = (trend_direction > 0) | ~is_trending
        short_bars_held = _bars_since_entry(short_entry)
        short_holding_exit = short_bars_held >= holding_bars
        entries = entries | short_entry
        exits = exits | short_exit_signal | short_holding_exit

    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    return entries, exits, None
