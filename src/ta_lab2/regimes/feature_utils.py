# src/ta_lab2/regimes/feature_utils.py
from __future__ import annotations
import pandas as pd
import numpy as np

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def add_ema_pack(df: pd.DataFrame, *, tf: str, price_col: str = "close") -> pd.DataFrame:
    """
    Add the EMA set used by our labelers per time frame.
    tf in {"M","W","D","I"} for Monthly/Weekly/Daily/Intraday.
    """
    out = df.copy()
    c = out[price_col]
    if tf == "W":    # weekly
        out["close_ema_20"]  = _ema(c, 20)
        out["close_ema_50"]  = _ema(c, 50)
        out["close_ema_200"] = _ema(c, 200)
    elif tf == "D":  # daily
        out["close_ema_20"]  = _ema(c, 20)
        out["close_ema_50"]  = _ema(c, 50)
        out["close_ema_100"] = _ema(c, 100)
    elif tf == "M":  # monthly
        out["close_ema_12"]  = _ema(c, 12)
        out["close_ema_24"]  = _ema(c, 24)
        out["close_ema_48"]  = _ema(c, 48)
    else:            # intraday (4H/1H)
        out["close_ema_34"]  = _ema(c, 34)
        out["close_ema_55"]  = _ema(c, 55)
        out["close_ema_89"]  = _ema(c, 89)
    return out

def add_atr14(df: pd.DataFrame, *, price_col: str = "close") -> pd.DataFrame:
    """
    Adds a lightweight ATR(14) column named 'atr14'.
    If high/low exist, use true ATR; otherwise use a proxy from abs returns.
    """
    out = df.copy()
    if {"high","low","close"}.issubset(out.columns):
        # True Range
        prev_close = out["close"].shift(1)
        tr = pd.concat([
            (out["high"] - out["low"]).abs(),
            (out["high"] - prev_close).abs(),
            (out["low"]  - prev_close).abs()
        ], axis=1).max(axis=1)
        out["atr14"] = tr.rolling(14, min_periods=1).mean()
    else:
        # Proxy
        out["atr14"] = out[price_col].pct_change().abs().rolling(14, min_periods=1).mean() * out[price_col]
    return out

def ensure_regime_features(df: pd.DataFrame, *, tf: str, price_col: str = "close") -> pd.DataFrame:
    """
    One-shot: add EMAs + ATR columns appropriate for this TF.
    """
    out = add_ema_pack(df, tf=tf, price_col=price_col)
    out = add_atr14(out, price_col=price_col)
    return out
