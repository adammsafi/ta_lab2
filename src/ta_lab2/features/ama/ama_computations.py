"""
AMA Computation Functions.

Pure functions for computing Adaptive Moving Average indicators.
No database code, no side effects — inputs are arrays/Series, outputs are arrays/Series.

Indicators:
    - KAMA: Kaufman Adaptive Moving Average (uses numpy loop — recursive dependency)
    - DEMA: Double Exponential Moving Average (uses ewm, alpha=2/(period+1), adjust=False)
    - TEMA: Triple Exponential Moving Average (uses ewm, alpha=2/(period+1), adjust=False)
    - HMA:  Hull Moving Average (uses rolling WMA — NOT ewm)

Alpha Convention:
    DEMA and TEMA use alpha = 2 / (period + 1) with adjust=False. This matches the
    existing EMA infrastructure in ema_operations.py (calculate_alpha_from_period).
    Do NOT use ewm(span=period) — use ewm(alpha=alpha, adjust=False).

WMA Convention:
    HMA uses rolling weighted moving average with linear weights [1, 2, ..., period].
    This is mathematically different from EWM — do not substitute ewm() for WMA.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


# =============================================================================
# Internal Helpers
# =============================================================================


def _wma(series: pd.Series, period: int) -> pd.Series:
    """
    Weighted Moving Average with linear weights.

    Weights: [1, 2, ..., period] — most recent bar has the highest weight.
    Uses rolling().apply(raw=True) for correctness.

    Args:
        series: Input price series.
        period: WMA window length.

    Returns:
        WMA series. NaN for the first (period - 1) rows.
    """
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()

    return series.rolling(window=period, min_periods=period).apply(
        lambda x: np.dot(x, weights) / weight_sum,
        raw=True,
    )


# =============================================================================
# KAMA — Kaufman Adaptive Moving Average
# =============================================================================


def compute_kama(
    close: np.ndarray,
    er_period: int,
    fast_period: int,
    slow_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute KAMA (Kaufman Adaptive Moving Average) and Efficiency Ratio (ER).

    The Smoothing Constant (SC) adapts based on ER — high ER (trending) produces
    a fast SC close to fast_sc; low ER (choppy) produces a slow SC close to slow_sc.

    Formula:
        Direction[i] = abs(close[i] - close[i - er_period + 1])
        Volatility[i] = sum(abs(diff(close[i - er_period + 1 : i + 1])))
        ER[i] = Direction / Volatility  (0.0 when Volatility == 0)

        fast_sc = 2 / (fast_period + 1)
        slow_sc = 2 / (slow_period + 1)
        SC[i]   = (ER[i] * (fast_sc - slow_sc) + slow_sc) ** 2

        KAMA[er_period - 1] = close[er_period - 1]  (seed)
        KAMA[i] = KAMA[i-1] + SC[i] * (close[i] - KAMA[i-1])

    Args:
        close: 1D numpy array of close prices. Must not be empty.
        er_period: Efficiency Ratio lookback period (e.g. 10).
        fast_period: Fast EMA period for SC upper bound (e.g. 2).
        slow_period: Slow EMA period for SC lower bound (e.g. 30).

    Returns:
        Tuple of (kama, er) — both numpy arrays of length len(close).
        Rows 0 .. er_period - 2 are NaN (warmup guard).
        Row er_period - 1 is seeded with close[er_period - 1].

    Warmup:
        er_period bars required before first valid value.
    """
    n = len(close)
    kama = np.full(n, np.nan)
    er = np.full(n, np.nan)

    # Guard: need at least er_period bars to produce a single valid value
    if n < er_period:
        return kama, er

    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    # Compute ER for all valid positions (0-based: starts at er_period - 1)
    for i in range(er_period - 1, n):
        direction = abs(close[i] - close[i - er_period + 1])
        volatility = np.sum(np.abs(np.diff(close[i - er_period + 1 : i + 1])))
        er[i] = direction / volatility if volatility != 0 else 0.0

    # Seed KAMA at the first valid position
    kama[er_period - 1] = close[er_period - 1]

    # Propagate KAMA forward
    for i in range(er_period, n):
        sc = (er[i] * (fast_sc - slow_sc) + slow_sc) ** 2
        kama[i] = kama[i - 1] + sc * (close[i] - kama[i - 1])

    return kama, er


# =============================================================================
# DEMA — Double Exponential Moving Average
# =============================================================================


def compute_dema(close: pd.Series, period: int) -> pd.Series:
    """
    Compute DEMA (Double Exponential Moving Average).

    Formula (Mulloy 1994):
        EMA1 = EMA(close, period)
        EMA2 = EMA(EMA1, period)
        DEMA  = 2 * EMA1 - EMA2

    Alpha convention matches existing EMA infrastructure:
        alpha = 2 / (period + 1),  adjust=False

    Args:
        close: Input price series (pandas Series).
        period: EMA smoothing period (e.g. 21).

    Returns:
        DEMA series. Rows 0 .. (2 * period - 2) are NaN (warmup guard).

    Warmup:
        2 * period - 1 bars required before first valid value.
    """
    alpha = 2.0 / (period + 1)
    ema1 = close.ewm(alpha=alpha, adjust=False).mean()
    ema2 = ema1.ewm(alpha=alpha, adjust=False).mean()
    dema = 2 * ema1 - ema2
    # Explicit warmup guard
    warmup = 2 * period - 1
    dema.iloc[: max(0, warmup)] = np.nan
    return dema


# =============================================================================
# TEMA — Triple Exponential Moving Average
# =============================================================================


def compute_tema(close: pd.Series, period: int) -> pd.Series:
    """
    Compute TEMA (Triple Exponential Moving Average).

    Formula (Mulloy 1994):
        EMA1 = EMA(close, period)
        EMA2 = EMA(EMA1, period)
        EMA3 = EMA(EMA2, period)
        TEMA  = 3 * EMA1 - 3 * EMA2 + EMA3

    Alpha convention matches existing EMA infrastructure:
        alpha = 2 / (period + 1),  adjust=False

    Args:
        close: Input price series (pandas Series).
        period: EMA smoothing period (e.g. 21).

    Returns:
        TEMA series. Rows 0 .. (3 * period - 2) are NaN (warmup guard).

    Warmup:
        3 * period - 1 bars required before first valid value.
    """
    alpha = 2.0 / (period + 1)
    ema1 = close.ewm(alpha=alpha, adjust=False).mean()
    ema2 = ema1.ewm(alpha=alpha, adjust=False).mean()
    ema3 = ema2.ewm(alpha=alpha, adjust=False).mean()
    tema = 3 * ema1 - 3 * ema2 + ema3
    # Explicit warmup guard
    warmup = 3 * period - 1
    tema.iloc[: max(0, warmup)] = np.nan
    return tema


# =============================================================================
# HMA — Hull Moving Average
# =============================================================================


def compute_hma(close: pd.Series, period: int) -> pd.Series:
    """
    Compute HMA (Hull Moving Average).

    Formula (Alan Hull 2005):
        half_period = max(1, int(period / 2))
        sqrt_period = max(2, int(sqrt(period)))
        raw         = 2 * WMA(close, half_period) - WMA(close, period)
        HMA         = WMA(raw, sqrt_period)

    CRITICAL: Uses WMA (linearly weighted rolling window), NOT ewm().
    Using ewm() here would produce incorrect results.

    Args:
        close: Input price series (pandas Series).
        period: HMA base period (e.g. 21).

    Returns:
        HMA series. NaN naturally produced by rolling min_periods.
        Approximate warmup: period + int(sqrt(period)) - 2 bars.

    Warmup:
        NaN is produced naturally by WMA rolling — no explicit guard needed.
        Total warmup approximately period + sqrt(period) - 2 rows.
    """
    half_period = max(1, int(period / 2))
    sqrt_period = max(2, int(math.sqrt(period)))

    wma_half = _wma(close, half_period)
    wma_full = _wma(close, period)
    raw = 2 * wma_half - wma_full
    hma = _wma(raw, sqrt_period)
    return hma


# =============================================================================
# Dispatcher
# =============================================================================


def compute_ama(
    close: pd.Series,
    indicator: str,
    params: dict,
) -> tuple[pd.Series, pd.Series | None]:
    """
    Dispatch computation to the correct AMA function.

    Args:
        close: Input price series (pandas Series).
        indicator: One of "KAMA", "DEMA", "TEMA", "HMA" (case-insensitive).
        params: Canonical params dict for the indicator.

    Returns:
        Tuple of (ama_values, er_or_none).
        - ama_values: pd.Series of computed AMA values.
        - er_or_none: pd.Series of Efficiency Ratio for KAMA; None for DEMA/TEMA/HMA.

    Raises:
        ValueError: If indicator name is not recognised.
    """
    indicator_upper = indicator.upper()
    idx = close.index

    if indicator_upper == "KAMA":
        close_arr = close.to_numpy(dtype=float)
        kama_arr, er_arr = compute_kama(
            close_arr,
            er_period=params["er_period"],
            fast_period=params["fast_period"],
            slow_period=params["slow_period"],
        )
        return pd.Series(kama_arr, index=idx), pd.Series(er_arr, index=idx)

    elif indicator_upper == "DEMA":
        return compute_dema(close, params["period"]), None

    elif indicator_upper == "TEMA":
        return compute_tema(close, params["period"]), None

    elif indicator_upper == "HMA":
        return compute_hma(close, params["period"]), None

    else:
        raise ValueError(
            f"Unknown indicator '{indicator}'. Expected one of: KAMA, DEMA, TEMA, HMA."
        )
