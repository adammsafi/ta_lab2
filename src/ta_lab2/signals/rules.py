# -*- coding: utf-8 -*-
"""
Primitive rule functions for signal generation.

Each rule returns a boolean Series marking where its condition is True.
They can be mixed, matched, or composed in generator.py.
"""

import pandas as pd


def ema_crossover_long(df: pd.DataFrame, fast="ema_21", slow="ema_50") -> pd.Series:
    """True when fast EMA crosses ABOVE slow EMA."""
    f, s = df[fast], df[slow]
    return (f > s) & (f.shift(1) <= s.shift(1))


def ema_crossover_short(df: pd.DataFrame, fast="ema_21", slow="ema_50") -> pd.Series:
    """True when fast EMA crosses BELOW slow EMA."""
    f, s = df[fast], df[slow]
    return (f < s) & (f.shift(1) >= s.shift(1))


def rsi_ok_long(df: pd.DataFrame, rsi_col="rsi_14", min_long=45) -> pd.Series:
    """Allow long entries only when RSI >= min_long."""
    return (df[rsi_col] >= min_long).fillna(False)


def rsi_ok_short(df: pd.DataFrame, rsi_col="rsi_14", max_short=55) -> pd.Series:
    """Allow short entries only when RSI <= max_short."""
    return (df[rsi_col] <= max_short).fillna(False)


def volatility_filter(
    df: pd.DataFrame, atr_col="atr_14", close_col="close", min_atr_pct=0.003
) -> pd.Series:
    """Require ATR/close >= threshold to avoid low-volatility conditions."""
    return (df[atr_col] / df[close_col] >= min_atr_pct).fillna(False)
