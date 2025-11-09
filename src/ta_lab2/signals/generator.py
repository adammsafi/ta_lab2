# src/ta_lab2/signals/generator.py
from __future__ import annotations
from typing import Optional, Tuple
import numpy as np
import pandas as pd
from . import rules

def generate_signals(
    df: pd.DataFrame,
    *,
    close_col: str = "close",
    fast_ema: str = "ema_21",
    slow_ema: str = "ema_50",
    # optional filters (auto-disabled if inputs missing)
    rsi_col: str = "rsi_14",
    atr_col: str = "atr_14",
    use_rsi_filter: bool = False,
    use_vol_filter: bool = False,
    rsi_min_long: int = 45,
    rsi_max_short: int = 55,
    min_atr_pct: float = 0.003,
    # strategy toggles
    allow_shorts: bool = False,
    cooldown_bars: int = 0,
) -> pd.DataFrame:
    """
    Compose primitive rules into a full signal dataframe.

    Returns a DataFrame with at least:
      - entry_long, exit_long (bool)
      - if allow_shorts: entry_short, exit_short (bool)
      - signal (int in {-1,0,1}) and position (ffill)
      - size (optional pd.Series[float]); absent/None if no ATR sizing
    """
    d = df.copy()

    # --- Basic validations for required columns ---
    if close_col not in d.columns:
        raise KeyError(f"Missing price column: {close_col!r}")
    if fast_ema not in d.columns:
        raise KeyError(f"Missing fast EMA column: {fast_ema!r}")
    if slow_ema not in d.columns:
        raise KeyError(f"Missing slow EMA column: {slow_ema!r}")

    # --- Core entries/exits from EMA cross rules ---
    long_entry  = rules.ema_crossover_long(d, fast_ema, slow_ema)
    long_exit   = rules.ema_crossover_short(d, fast_ema, slow_ema)

    if allow_shorts:
        short_entry = rules.ema_crossover_short(d, fast_ema, slow_ema)
        short_exit  = rules.ema_crossover_long(d, fast_ema, slow_ema)
    else:
        short_entry = pd.Series(False, index=d.index)
        short_exit  = pd.Series(False, index=d.index)

    # --- Optional RSI gates (auto-disable if column missing) ---
    _use_rsi = bool(use_rsi_filter and (rsi_col in d.columns))
    if _use_rsi:
        long_entry  &= rules.rsi_ok_long(d, rsi_col, rsi_min_long)
        if allow_shorts:
            short_entry &= rules.rsi_ok_short(d, rsi_col, rsi_max_short)

    # --- Optional ATR/volatility gate (auto-disable if column missing) ---
    _use_vol = bool(use_vol_filter and (atr_col in d.columns))
    if _use_vol:
        long_entry  &= rules.atr_ok(d, atr_col, close_col, min_atr_pct=min_atr_pct)
        if allow_shorts:
            short_entry &= rules.atr_ok(d, atr_col, close_col, min_atr_pct=min_atr_pct)

    # --- Cooldown (optional) ---
    if cooldown_bars and cooldown_bars > 0:
        ce = (long_exit | short_exit)
        # after any exit, block re-entry for N bars
        block = ce.copy().astype(int)
        for i in range(1, cooldown_bars + 1):
            block |= ce.shift(i, fill_value=False).astype(int)
        # mask out entries during cooldown
        long_entry  &= ~block.astype(bool)
        if allow_shorts:
            short_entry &= ~block.astype(bool)

    # --- Compose signal and position ---
    # signal2 picks last nonzero of [long_entry -> +1, long_exit -> 0, short_entry -> -1, short_exit -> 0]
    # Simpler: start from previous position, flip on entries/exits
    signal = pd.Series(0, index=d.index, dtype=int)
    # Long side
    signal = np.where(long_entry,  1, signal)
    signal = np.where(long_exit,   0, signal)
    # Short side (if enabled)
    if allow_shorts:
        signal = np.where(short_entry, -1, signal)
        signal = np.where(short_exit,   0, signal)
    signal = pd.Series(signal, index=d.index, dtype=int)
    position = signal.replace(0, np.nan).ffill().fillna(0).astype(int)

    # --- Position sizing ---
    size: Optional[pd.Series] = None
    if _use_vol:
        # Only compute ATR-based sizing if atr_col exists and vol filter is actually enabled
        close = d[close_col].astype(float)
        atr = d[atr_col].astype(float)
        atr_pct = (atr / close).replace([np.inf, -np.inf], np.nan).clip(lower=1e-12)
        raw = (1.0 / atr_pct)  # inverse vol
        # normalize to a reasonable cap (e.g., 95th percentile to 1.0)
        denom = raw.quantile(0.95)
        size = (raw / denom).clip(upper=1.0).fillna(0.0)

    # --- Assemble output frame ---
    out = pd.DataFrame(
        {
            "entry_long": long_entry.astype(bool),
            "exit_long":  long_exit.astype(bool),
        },
        index=d.index,
    )
    if allow_shorts:
        out["entry_short"] = short_entry.astype(bool)
        out["exit_short"]  = short_exit.astype(bool)

    out["signal"]   = signal.astype(int)
    out["position"] = position.astype(int)

    # Attach size only if computed
    if size is not None:
        out["size"] = size.astype(float)

    return out
