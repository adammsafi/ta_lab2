# -*- coding: utf-8 -*-
"""
Vol-sizing library for tail-risk backtests (Phase 49, TAIL-01).

Provides:
- compute_vol_sized_position: ATR-based position sizing
- compute_realized_vol_position: realized-vol (rolling std) position sizing,
  with optional GARCH blend support (Phase 81)
- run_vol_sized_backtest: vectorbt wrapper with integrated vol-sizing at entry,
  with optional per-bar GARCH blend support (Phase 81)
- worst_n_day_returns: tail-risk characterization (flat dict of worst-N-day means)
- compute_comparison_metrics: comprehensive flat metrics dict from a vbt.Portfolio
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import vectorbt as vbt  # type: ignore[import]
except ImportError:  # pragma: no cover
    vbt = None  # type: ignore[assignment]

from ta_lab2.analysis.performance import (
    calmar,
    equity_from_returns,
    hit_rate,
    max_drawdown,
    sharpe,
    sortino,
)


# ---------------------------------------------------------------------------
# Position-sizing primitives
# ---------------------------------------------------------------------------


def compute_vol_sized_position(
    close: float,
    atr_14: Optional[float],
    init_cash: float,
    risk_budget: float,
    max_position_pct: float = 0.30,
) -> float:
    """
    Compute ATR-based vol-sized position in units.

    Parameters
    ----------
    close:
        Current price of the asset.
    atr_14:
        14-bar ATR in DOLLAR terms (from features atr_14 column).
    init_cash:
        Starting cash for the position (used as portfolio NAV reference).
    risk_budget:
        Fraction of NAV to risk per trade (e.g. 0.01 = 1%).
    max_position_pct:
        Maximum fraction of NAV that can be in this position (default 30%).

    Returns
    -------
    float
        Position size in asset units. Returns 0.0 for invalid inputs.
    """
    if atr_14 is None or atr_14 <= 0 or close <= 0:
        return 0.0
    atr_pct = atr_14 / close
    position_pct = min(risk_budget / atr_pct, max_position_pct)
    position_units = position_pct * init_cash / close
    return float(position_units)


def compute_realized_vol_position(
    rolling_std: float,
    close: float,
    init_cash: float,
    risk_budget: float,
    max_position_pct: float = 0.30,
    garch_vol: float | None = None,
    garch_mode: str = "sizing_only",
    blend_weight: float = 1.0,
) -> float:
    """
    Compute realized-vol-based position in units.

    When *garch_vol* is provided and *garch_mode* is ``"sizing_only"`` or
    ``"sizing_and_limits"``, an effective volatility is computed as a blend
    of the GARCH conditional forecast and the rolling standard deviation::

        effective_vol = blend_weight * garch_vol + (1 - blend_weight) * rolling_std

    In ``"advisory"`` mode the GARCH vol is logged for comparison but does
    **not** affect the position size (rolling_std is used as-is).

    Parameters
    ----------
    rolling_std:
        20-day rolling std of daily returns (expressed as a fraction, e.g. 0.04 = 4%).
    close:
        Current price of the asset.
    init_cash:
        Starting cash for the position.
    risk_budget:
        Fraction of NAV to risk per trade (e.g. 0.01 = 1%).
    max_position_pct:
        Maximum fraction of NAV that can be in this position (default 30%).
    garch_vol:
        Optional GARCH conditional volatility forecast (decimal, e.g. 0.03 = 3%).
        When None, behaviour is identical to the pre-GARCH implementation.
    garch_mode:
        How the GARCH vol influences sizing.  One of:
        - ``"sizing_only"``       -- blend affects position size only.
        - ``"sizing_and_limits"`` -- blend affects position size and risk limits.
        - ``"advisory"``          -- log the GARCH vol but do not use it for sizing.
    blend_weight:
        Weight on the GARCH estimate in [0.0, 1.0].  0 = pure rolling,
        1 = pure GARCH.  Default 1.0.

    Returns
    -------
    float
        Position size in asset units. Returns 0.0 for invalid inputs.
    """
    # Determine effective volatility
    if garch_vol is not None and garch_mode in ("sizing_only", "sizing_and_limits"):
        effective_vol = blend_weight * garch_vol + (1.0 - blend_weight) * rolling_std
        if effective_vol <= 0:
            return 0.0
    else:
        # No GARCH or advisory mode -- fall back to rolling_std
        if garch_vol is not None and garch_mode == "advisory":
            logger.debug(
                "compute_realized_vol_position advisory: "
                "garch_vol=%.6f vs rolling_std=%.6f (ratio=%.2f)",
                garch_vol,
                rolling_std,
                garch_vol / rolling_std if rolling_std > 0 else float("inf"),
            )
        effective_vol = rolling_std

    if effective_vol <= 0:
        return 0.0
    position_pct = min(risk_budget / effective_vol, max_position_pct)
    position_units = position_pct * init_cash / close
    return float(position_units)


# ---------------------------------------------------------------------------
# Vectorbt backtest wrapper
# ---------------------------------------------------------------------------


def run_vol_sized_backtest(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    vol_series: pd.Series,
    vol_type: str,
    risk_budget: float,
    max_position_pct: float = 0.30,
    init_cash: float = 1000.0,
    fee_bps: float = 16.0,
    sl_stop: Optional[float] = None,
    garch_vol_series: Optional[pd.Series] = None,
    garch_mode: str = "sizing_only",
    garch_blend_weight: float = 1.0,
) -> "vbt.Portfolio":
    """
    Run a vectorbt backtest with vol-sized position at each entry bar.

    Parameters
    ----------
    price:
        Asset close price series (DatetimeIndex, UTC).
    entries:
        Boolean Series of entry signals (True = enter long).
    exits:
        Boolean Series of exit signals (True = exit long).
    vol_series:
        Volatility measure series aligned to price index.
        If vol_type='atr': dollar ATR (e.g. atr_14 from features).
        If vol_type='realized': rolling std of daily returns (fraction, e.g. 0.04).
    vol_type:
        'atr' or 'realized'.
    risk_budget:
        Fraction of NAV to risk per trade (e.g. 0.01 = 1%).
    max_position_pct:
        Maximum fraction of NAV allocated to one position (default 30%).
    init_cash:
        Starting cash for the portfolio.
    fee_bps:
        One-way trading fee in basis points (default 16 bps = 0.16%).
    sl_stop:
        Stop-loss fraction from entry price (e.g. 0.05 = 5% stop). None = disabled.
    garch_vol_series:
        Optional per-bar GARCH conditional vol forecast (decimal, aligned to
        price index).  When provided, each bar's effective vol is blended as
        ``garch_blend_weight * garch_vol + (1 - garch_blend_weight) * vol_pct``.
        Bars where garch_vol_series is NaN fall back to vol_pct unblended.
    garch_mode:
        How GARCH vol influences sizing.  One of ``"sizing_only"`` (default),
        ``"sizing_and_limits"``, or ``"advisory"`` (log only, no blend).
    garch_blend_weight:
        Weight on the GARCH estimate in [0.0, 1.0].  Default 1.0.

    Returns
    -------
    vbt.Portfolio
        Vectorbt portfolio object.
    """
    if vbt is None:
        raise ImportError(
            "vectorbt is required for run_vol_sized_backtest; "
            "please `pip install vectorbt`."
        )

    # Compute vol percentage
    if vol_type == "atr":
        # atr_14 is in dollar terms; convert to fraction of price
        vol_pct = vol_series / price
    elif vol_type == "realized":
        # Already a percentage (rolling std of returns)
        vol_pct = vol_series
    else:
        raise ValueError(f"vol_type must be 'atr' or 'realized', got {vol_type!r}")

    # Clamp to avoid division by zero or negative vol
    vol_pct_safe = vol_pct.clip(lower=1e-8)

    # Blend with GARCH vol when available and not in advisory mode
    effective_vol = vol_pct_safe.values.copy()
    if garch_vol_series is not None and garch_mode in (
        "sizing_only",
        "sizing_and_limits",
    ):
        garch_vals = garch_vol_series.reindex(vol_pct_safe.index).values
        has_garch = ~np.isnan(garch_vals) & (garch_vals > 0)
        effective_vol[has_garch] = (
            garch_blend_weight * garch_vals[has_garch]
            + (1.0 - garch_blend_weight) * vol_pct_safe.values[has_garch]
        )
        # Safety: ensure blended vol stays positive
        effective_vol = np.maximum(effective_vol, 1e-8)
    elif garch_vol_series is not None and garch_mode == "advisory":
        logger.debug(
            "run_vol_sized_backtest: advisory mode -- GARCH vol logged, not applied"
        )

    # Compute per-bar position sizes (in asset units) -- raw
    raw_position_pct = np.minimum(risk_budget / effective_vol, max_position_pct)
    position_units = raw_position_pct * init_cash / price.values

    # Only entry bars get a size; NaN elsewhere (vbt uses NaN as "keep position")
    size_array = np.where(entries.values.astype(bool), position_units, np.nan)

    # Strip tz from price index -- vectorbt 0.28.1 tz boundary issue
    if hasattr(price.index, "tz") and price.index.tz is not None:
        price_no_tz = price.copy()
        price_no_tz.index = price.index.tz_localize(None)
    else:
        price_no_tz = price

    # Build portfolio kwargs
    pf_kwargs: Dict = dict(
        entries=entries.to_numpy().astype(bool),
        exits=exits.to_numpy().astype(bool),
        size=size_array,
        direction="longonly",
        freq="D",
        init_cash=init_cash,
        fees=fee_bps / 1e4,
    )
    if sl_stop is not None:
        pf_kwargs["sl_stop"] = sl_stop

    return vbt.Portfolio.from_signals(price_no_tz, **pf_kwargs)


# ---------------------------------------------------------------------------
# Tail-risk characterization helpers
# ---------------------------------------------------------------------------


def worst_n_day_returns(
    returns: np.ndarray,
    n_values: List[int] = None,
) -> Dict[str, float]:
    """
    Compute the mean of the worst N daily returns for tail-risk characterization.

    Parameters
    ----------
    returns:
        Array of daily returns (numpy array or Series).
    n_values:
        List of N values to compute (default [1, 3, 5, 10]).

    Returns
    -------
    dict
        Flat dict with keys like 'worst_1_day_mean', 'worst_5_day_mean', etc.
        All values are plain Python floats.
    """
    if n_values is None:
        n_values = [1, 3, 5, 10]

    arr = np.asarray(returns, dtype=float)
    sorted_rets = np.sort(arr)  # ascending: worst returns first

    result: Dict[str, float] = {}
    for n in n_values:
        n_clipped = min(n, len(sorted_rets))
        if n_clipped == 0:
            result[f"worst_{n}_day_mean"] = 0.0
        else:
            result[f"worst_{n}_day_mean"] = float(sorted_rets[:n_clipped].mean())
    return result


# ---------------------------------------------------------------------------
# Comparison metrics extractor
# ---------------------------------------------------------------------------


def _compute_recovery_bars(returns: pd.Series) -> int:
    """
    Compute the maximum consecutive bars spent in drawdown (below prior equity peak).
    """
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    running_max = equity.cummax()
    in_drawdown = equity < running_max

    if not in_drawdown.any():
        return 0

    # Group consecutive runs and find the longest in-drawdown streak
    groups = (~in_drawdown).cumsum()
    recovery_bars = int(in_drawdown.groupby(groups).sum().max())
    return recovery_bars


def compute_comparison_metrics(
    portfolio: "vbt.Portfolio",
    returns_series: Optional[pd.Series] = None,
) -> Dict[str, float]:
    """
    Extract a flat comparison metrics dict from a vectorbt Portfolio.

    Parameters
    ----------
    portfolio:
        A vbt.Portfolio object from run_vol_sized_backtest or similar.
    returns_series:
        Optional override for portfolio returns (defaults to portfolio.returns()).

    Returns
    -------
    dict
        Flat dict with all metrics at the top level:
        - sharpe, sortino, calmar, max_dd, total_return, n_trades, win_rate,
          recovery_bars, worst_1_day_mean, worst_3_day_mean,
          worst_5_day_mean, worst_10_day_mean
    """
    pf = portfolio
    pf_returns = returns_series if returns_series is not None else pf.returns()

    # Equity from portfolio returns for drawdown computation
    pf_equity = equity_from_returns(pf_returns)

    # Trade-level returns for win_rate
    try:
        trade_records = pf.trades.records_readable
        if len(trade_records) > 0 and "Return" in trade_records.columns:
            trade_returns = pd.Series(trade_records["Return"].values, dtype=float)
        else:
            trade_returns = pd.Series(dtype=float)
        n_trades = int(len(trade_records))
    except Exception:
        trade_returns = pd.Series(dtype=float)
        n_trades = 0

    win_rate_val = hit_rate(trade_returns) if len(trade_returns) > 0 else 0.0

    try:
        total_return = float(pf.total_return())
    except Exception:
        eq = pf_equity
        total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0

    result: Dict[str, float] = {
        "sharpe": sharpe(pf_returns, freq="D"),
        "sortino": sortino(pf_returns, freq="D"),
        "calmar": calmar(pf_returns, freq="D"),
        "max_dd": max_drawdown(pf_equity),
        "total_return": total_return,
        "n_trades": float(n_trades),
        "win_rate": win_rate_val,
        "recovery_bars": float(_compute_recovery_bars(pf_returns)),
        **worst_n_day_returns(pf_returns.dropna().values),
    }
    return result
