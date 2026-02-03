from __future__ import annotations
from typing import Iterable
import numpy as np
import pandas as pd


def _annualization(freq: str) -> float:
    # crude but effective; adjust if you prefer business-day logic
    if freq.endswith("B"):
        return np.sqrt(252)
    if freq.endswith("W"):
        return np.sqrt(52)
    if freq.endswith("M"):
        return np.sqrt(12)
    if freq in ("A", "Y"):
        return 1.0
    if freq.endswith("D"):
        try:
            k = float(freq[:-1])  # e.g. "10D" -> 10
            return np.sqrt(365.0 / k)
        except Exception:
            return np.sqrt(365.0)
    return np.sqrt(365.0)


def attach_core_features(
    df: pd.DataFrame,
    freq: str,
    ema_periods: Iterable[int] = (9, 21, 50, 90, 100, 180, 200, 270),
    vol_windows: Iterable[int] = (10, 21, 50),
    acorr_lags: Iterable[int] = (1, 5, 10, 21),
) -> pd.DataFrame:
    """
    df must be a single-timeframe OHLCV frame with a monotonic UTC 'timestamp'.
    Adds: close_pct_delta, close_log_delta, rel, ATR(14), EMAs, vol_annual_{w}, acorr_logret_{lag}.
    """
    d = df.copy()
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d["open"] = pd.to_numeric(d["open"], errors="coerce")
    d["high"] = pd.to_numeric(d["high"], errors="coerce")
    d["low"] = pd.to_numeric(d["low"], errors="coerce")

    # returns
    d["close_pct_delta"] = d["close"].pct_change()
    d["close_log_delta"] = np.log(d["close"]).diff()
    d["rel"] = 1.0 + d["close_pct_delta"]

    # ATR (14 bars of this timeframe)
    tr = (d["high"] - d["low"]).abs()
    tr = np.maximum(tr, (d["high"] - d["close"].shift()).abs())
    tr = np.maximum(tr, (d["low"] - d["close"].shift()).abs())
    d["atr_14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # EMAs on close
    for p in ema_periods:
        alpha = 2.0 / (p + 1.0)
        d[f"close_ema_{p}"] = d["close"].ewm(alpha=alpha, adjust=False).mean()

    # realized vol (annualized) over log-returns
    ann = _annualization(freq)
    for w in vol_windows:
        stdev = d["close_log_delta"].rolling(w).std()
        d[f"vol_ann_{w}"] = stdev * np.sqrt(ann)  # annualized

    # autocorrelation of log-returns at fixed lags (non-rolling)
    # store a small table-like summary as columns for quick inspection
    lr = d["close_log_delta"]
    for lag in acorr_lags:
        d[f"acorr_logret_lag{lag}"] = lr.autocorr(lag=lag)

    return d
