"""
Core metrics: CAGR, MDD, MAR, Sharpe, Sortino, PSR/DSR placeholders.
"""
from __future__ import annotations
from typing import Dict
import numpy as np
import pandas as pd


def cagr(equity: pd.Series, freq_per_year: int) -> float:
    if equity.empty:
        return 0.0
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    years = len(equity) / freq_per_year
    if start <= 0 or years <= 0:
        return 0.0
    return (end / start) ** (1 / years) - 1


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def sharpe(returns: pd.Series, rf: float = 0.0, freq_per_year: int = 252) -> float:
    if returns.std(ddof=0) == 0:
        return 0.0
    mu = returns.mean() - rf / freq_per_year
    sig = returns.std(ddof=0)
    return float(np.sqrt(freq_per_year) * mu / sig)


def sortino(returns: pd.Series, rf: float = 0.0, freq_per_year: int = 252) -> float:
    downside = returns[returns < 0]
    if downside.std(ddof=0) == 0:
        return 0.0
    mu = returns.mean() - rf / freq_per_year
    dsig = downside.std(ddof=0)
    return float(np.sqrt(freq_per_year) * mu / dsig)


def mar(cagr_value: float, mdd_value: float) -> float:
    return float(cagr_value / abs(mdd_value)) if mdd_value != 0 else 0.0


def psr_placeholder(
    returns: pd.Series, rf: float = 0.0, freq_per_year: int = 252
) -> float:
    """
    Placeholder Probabilistic Sharpe Ratio (PSR).
    For production: implement the full PSR (Lopez de Prado) or use mlfinlab.
    """
    s = sharpe(returns, rf, freq_per_year)
    # naive stub maps Sharpe to a (0,1) score with a soft cap
    return float(1 / (1 + np.exp(-s)))


def summarize(
    equity: pd.Series, returns: pd.Series, freq_per_year: int = 365
) -> Dict[str, float]:
    c = cagr(equity, freq_per_year)
    m = max_drawdown(equity)
    return {
        "cagr": c,
        "mdd": m,
        "mar": mar(c, m),
        "sharpe": sharpe(returns, freq_per_year=freq_per_year),
        "sortino": sortino(returns, freq_per_year=freq_per_year),
        "psr": psr_placeholder(returns, freq_per_year=freq_per_year),
    }
