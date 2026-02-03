# -*- coding: utf-8 -*-
"""
Core performance utilities:
- returns/equity curve
- basic metrics (CAGR, Sharpe, Sortino, MaxDD, Calmar, Hit-rate, Turnover)
- evaluation wrappers for a signal DataFrame
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Optional

# --------- primitive transforms ---------


def pct_change(close: pd.Series, periods: int = 1) -> pd.Series:
    """Simple % returns (no log)."""
    return close.pct_change(periods)


def log_returns(close: pd.Series) -> pd.Series:
    """Log returns (safer additive over time)."""
    return np.log(close).diff()


def equity_from_returns(returns: pd.Series, start_equity: float = 1.0) -> pd.Series:
    """Cumulative equity curve from returns."""
    return start_equity * (1.0 + returns.fillna(0)).cumprod()


# --------- metrics ---------


def _annualize_scale(freq: str | None) -> float:
    """Return periods-per-year scaling for common frequencies."""
    if not freq:
        return 252.0
    f = freq.upper()
    if f in ("B", "D"):
        return 252.0
    if f in ("W", "W-FRI"):
        return 52.0
    if f in ("M", "MS"):
        return 12.0
    if f.endswith("H"):
        return 24.0 * 252.0  # trading days * hours/day (roughly)
    if f.endswith("T") or f.endswith("MIN"):
        return 252.0 * 24.0 * 6.0  # ~6*24 bars per day
    return 252.0


def sharpe(
    returns: pd.Series, risk_free: float = 0.0, freq: Optional[str] = None
) -> float:
    """Annualized Sharpe; risk_free given as per-period rate."""
    r = returns.dropna()
    if r.empty:
        return 0.0
    scale = _annualize_scale(freq)
    ex = r - risk_free
    return float(np.sqrt(scale) * ex.mean() / (ex.std(ddof=1) + 1e-12))


def sortino(
    returns: pd.Series, risk_free: float = 0.0, freq: Optional[str] = None
) -> float:
    """Annualized Sortino using downside std."""
    r = returns.dropna()
    if r.empty:
        return 0.0
    scale = _annualize_scale(freq)
    ex = r - risk_free
    downside = ex[ex < 0]
    denom = downside.std(ddof=1) + 1e-12
    return float(np.sqrt(scale) * ex.mean() / denom)


def max_drawdown(equity: pd.Series) -> float:
    """Max drawdown (as a negative fraction)."""
    e = equity.fillna(method="ffill").fillna(1.0)
    peak = e.cummax()
    dd = e / peak - 1.0
    return float(dd.min())


def calmar(returns: pd.Series, freq: Optional[str] = None) -> float:
    """Calmar = annualized return / |MaxDD|."""
    eq = equity_from_returns(returns)
    ann = annual_return(returns, freq=freq)
    mdd = abs(max_drawdown(eq)) + 1e-12
    return float(ann / mdd)


def annual_return(returns: pd.Series, freq: Optional[str] = None) -> float:
    """CAGR-like annualized return from per-period returns."""
    scale = _annualize_scale(freq)
    r = returns.dropna()
    if r.empty:
        return 0.0
    mean = (1 + r).prod() ** (scale / len(r)) - 1.0
    return float(mean)


def hit_rate(returns: pd.Series) -> float:
    """Fraction of positive-return periods."""
    r = returns.dropna()
    if r.empty:
        return 0.0
    return float((r > 0).mean())


def turnover(position: pd.Series) -> float:
    """
    Average absolute change in position between bars.
    For discrete positions (-1,0,1), this is trade frequency proxy.
    """
    p = position.fillna(0)
    return float(p.diff().abs().mean())


# --------- evaluation wrappers ---------


def position_returns(
    close: pd.Series,
    position: pd.Series,
    costs_bps: float = 0.0,
) -> pd.Series:
    """
    Convert price series + position into strategy returns.
    - costs_bps applied when position changes (one-way cost).
    """
    r = pct_change(close).fillna(0.0)
    pos = position.fillna(0.0).shift(1).fillna(0.0)  # enter at next bar
    strat = pos * r

    if costs_bps > 0:
        changes = pos.diff().abs().fillna(0.0)
        cost = (costs_bps * 1e-4) * changes
        strat = strat - cost
    return strat


def evaluate_signals(
    df: pd.DataFrame,
    close_col: str = "close",
    position_col: str = "position",
    costs_bps: float = 0.0,
    freq: Optional[str] = None,
) -> Dict[str, float]:
    """
    Compute a compact metrics dict from a signal DataFrame containing close and position.
    """
    close = df[close_col]
    pos = df[position_col]
    strat = position_returns(close, pos, costs_bps=costs_bps)
    eq = equity_from_returns(strat)

    return {
        "ann_return": annual_return(strat, freq=freq),
        "sharpe": sharpe(strat, freq=freq),
        "sortino": sortino(strat, freq=freq),
        "max_drawdown": max_drawdown(eq),
        "calmar": calmar(strat, freq=freq),
        "hit_rate": hit_rate(strat),
        "turnover": turnover(pos),
        "n_bars": int(len(df)),
    }
