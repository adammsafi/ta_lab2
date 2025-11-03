# -*- coding: utf-8 -*-
"""
Signal generator orchestrating rule combinations into entry/exit/position columns.
"""

import pandas as pd
import numpy as np
from . import rules

def generate_signals(
    df: pd.DataFrame,
    *,
    close_col: str = "close",
    fast_ema: str = "ema_21",
    slow_ema: str = "ema_50",
    rsi_col: str = "rsi_14",
    atr_col: str = "atr_14",
    use_rsi_filter: bool = True,
    use_vol_filter: bool = False,
    rsi_min_long: int = 45,
    rsi_max_short: int = 55,
    min_atr_pct: float = 0.003,
    allow_shorts: bool = True,
    cooldown_bars: int = 0,
) -> pd.DataFrame:
    """
    Combine indicator-based rules into directional trading signals.

    Returns df with:
        entry_long, exit_long, entry_short, exit_short, signal, position, size
    """
    d = df.copy()

    # Entry rules
    long_entry  = rules.ema_crossover_long(d, fast_ema, slow_ema)
    short_entry = rules.ema_crossover_short(d, fast_ema, slow_ema) if allow_shorts else pd.Series(False, d.index)

    # Optional filters
    if use_rsi_filter:
        long_entry  &= rules.rsi_ok_long(d, rsi_col, rsi_min_long)
        if allow_shorts:
            short_entry &= rules.rsi_ok_short(d, rsi_col, rsi_max_short)
    if use_vol_filter:
        vol_ok = rules.volatility_filter(d, atr_col, close_col, min_atr_pct)
        long_entry  &= vol_ok
        if allow_shorts:
            short_entry &= vol_ok

    # Exit triggers (opposite crosses)
    exit_long  = rules.ema_crossover_short(d, fast_ema, slow_ema)
    exit_short = rules.ema_crossover_long(d, fast_ema, slow_ema) if allow_shorts else pd.Series(False, d.index)

    # Base signal series
    signal = np.where(long_entry, 1, np.where(short_entry, -1, 0))
    signal = pd.Series(signal, index=d.index)

    # Carry forward position
    position = signal.replace(0, np.nan).ffill().fillna(0)

    # Optional cooldown to prevent immediate re-entry
    if cooldown_bars > 0:
        flips = position.ne(position.shift(1)).fillna(False)
        block = flips.shift(1).rolling(cooldown_bars, min_periods=1).max().fillna(0).astype(bool)
        long_entry  &= ~block
        short_entry &= ~block

    # Rebuild exits with cooldown applied
    exit_long  = exit_long | short_entry
    exit_short = exit_short | long_entry

    # Final recomputed position
    signal2  = np.where(long_entry, 1, np.where(short_entry, -1, 0))
    position = pd.Series(signal2, index=d.index).replace(0, np.nan).ffill().fillna(0)

    # Position sizing example
    atr_pct = (d[atr_col] / d[close_col]).clip(lower=1e-9)
    size = (1.0 / atr_pct)
    size = (size / size.quantile(0.95)).clip(upper=1.0)

    # Attach
    d["entry_long"]  = long_entry.astype(bool)
    d["exit_long"]   = exit_long.astype(bool)
    d["entry_short"] = short_entry.astype(bool)
    d["exit_short"]  = exit_short.astype(bool)
    d["signal"]      = pd.Series(np.sign(position), index=d.index).astype(int)
    d["position"]    = position.astype(int)
    d["size"]        = size.astype(float)
    return d


def attach_signals_from_config(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Read YAML-style config and attach signals."""
    s = cfg.get("signals", {}) if cfg else {}
    return generate_signals(
        df,
        fast_ema      = s.get("fast_ema", "ema_21"),
        slow_ema      = s.get("slow_ema", "ema_50"),
        rsi_col       = s.get("rsi_col", "rsi_14"),
        atr_col       = s.get("atr_col", "atr_14"),
        use_rsi_filter= bool(s.get("use_rsi_filter", True)),
        use_vol_filter= bool(s.get("use_vol_filter", False)),
        rsi_min_long  = int(s.get("rsi_min_long", 45)),
        rsi_max_short = int(s.get("rsi_max_short", 55)),
        min_atr_pct   = float(s.get("min_atr_pct", 0.003)),
        allow_shorts  = bool(s.get("allow_shorts", True)),
        cooldown_bars = int(s.get("cooldown_bars", 0)),
    )
