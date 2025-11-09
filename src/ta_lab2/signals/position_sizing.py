from __future__ import annotations
from typing import Optional
import pandas as pd
import numpy as np


def clamp_size(size: pd.Series, max_abs: float = 1.0) -> pd.Series:
    """Clamp position size to +/- max_abs (e.g., leverage cap)."""
    s = size.astype(float).copy()
    s = s.clip(lower=-abs(max_abs), upper=abs(max_abs))
    return s


def ema_smooth(series: pd.Series, span: int = 5) -> pd.Series:
    """Smooth a sizing series to reduce churn."""
    return series.astype(float).ewm(span=span, adjust=False).mean()


def volatility_size_pct(
    price: pd.Series,
    atr: pd.Series,
    risk_pct: float = 0.005,   # 0.5% of equity per trade (0.005 as fraction)
    atr_mult: float = 1.5,     # stop distance in ATRs
    equity: float = 1.0,       # normalized backtest equity
) -> pd.Series:
    """
    Position sizing based on risk parity vs ATR:
      target_dollar_risk = equity * risk_pct
      stop_distance = atr_mult * ATR
      units = target_dollar_risk / stop_distance
      size_fraction = (units * price) / equity  -> simplified to risk_pct * price / (atr_mult*ATR)
    Returned size is a fraction of equity to allocate (can be >1 if not clamped).
    """
    p = price.astype(float)
    a = atr.astype(float).replace(0, np.nan)
    stop_dist = atr_mult * a
    # Avoid division by zero
    raw = (risk_pct * p) / stop_dist
    raw = raw.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    return raw


def target_dollar_position(
    equity: float,
    size_fraction: pd.Series,
) -> pd.Series:
    """Convert a size fraction (relative to equity) to notional dollars."""
    return (size_fraction.astype(float) * float(equity)).astype(float)


def fixed_fractional(
    price: pd.Series,
    fraction: float = 0.5,
) -> pd.Series:
    """
    Simple constant fraction sizing (e.g., 50% of equity).
    Handy as a baseline when ATR is unavailable.
    """
    s = pd.Series(float(fraction), index=price.index)
    return s


def inverse_volatility(
    vol: pd.Series,
    target: float = 0.5,
    min_size: float = 0.0,
    max_size: float = 1.0,
    eps: float = 1e-12,
) -> pd.Series:
    """
    Size inversely to a volatility proxy (e.g., ATR% or rolling stdev).
    target ~ average desired size when vol is typical.
    """
    v = vol.astype(float).abs().replace(0, np.nan)
    base = target / (v + eps)
    base = base.fillna(0.0)
    return base.clip(lower=min_size, upper=max_size)
