# src/ta_lab2/features/ensure.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import pandas as pd

# We’ll call into your indicators module to avoid re-implementing math
from ta_lab2.features import indicators as ind


def ensure_close(df: pd.DataFrame) -> None:
    if "close" not in df.columns:
        # Try to infer a close-like column
        for c in df.columns:
            lc = c.lower()
            if lc == "price" or "close" in lc or lc == "last":
                df.rename(columns={c: "close"}, inplace=True)
                break
    if "close" not in df.columns:
        raise KeyError("DataFrame must contain a 'close' column.")


def ensure_ema(df: pd.DataFrame, span: int) -> None:
    ensure_close(df)
    col = f"ema_{span}"
    if col not in df:
        df[col] = df["close"].ewm(span=span, adjust=False).mean()


def ensure_rsi(df: pd.DataFrame, n: int = 14, col: str | None = None) -> str:
    ensure_close(df)
    target = col or f"rsi_{n}"
    if target not in df:
        # expects your indicators module to expose an RSI function that writes/returns series
        s = ind.rsi(df["close"], n=n)  # adjust if your signature differs
        df[target] = s
    return target


def ensure_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[str, str, str]:
    ensure_close(df)
    base, sig, hist = "macd", "macd_signal", "macd_hist"
    need = any(c not in df for c in (base, sig, hist))
    if need:
        # adjust if your indicators.macd returns (macd, signal, hist) or writes columns
        m, s, h = ind.macd(df["close"], fast=fast, slow=slow, signal=signal)
        df[base], df[sig], df[hist] = m, s, h
    return base, sig, hist


def ensure_adx(df: pd.DataFrame, n: int = 14) -> str:
    # Optional now; stub-friendly if you add ADX later
    col = f"adx_{n}"
    if col not in df:
        # If you already have ADX in indicators, wire it:
        # df[col] = ind.adx(df["high"], df["low"], df["close"], n=n)
        pass
    return col


def ensure_obv(df: pd.DataFrame) -> str:
    col = "obv"
    if col not in df:
        # If implemented in indicators:
        # df[col] = ind.obv(df["close"], df.get("volume"))
        pass
    return col
