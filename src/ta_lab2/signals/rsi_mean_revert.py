from __future__ import annotations
from typing import Optional, Tuple
import pandas as pd
import numpy as np
from .position_sizing import volatility_size_pct, clamp_size


def make_signals(
    df: pd.DataFrame,
    rsi_col: str = "rsi_14",
    lower: float = 30.0,
    upper: float = 70.0,
    confirm_cross: bool = True,
    allow_shorts: bool = False,
    atr_col: str = "atr_14",
    risk_pct: float = 0.5,          # % of equity risked per trade (for sizing)
    atr_mult_stop: float = 1.5,     # stop distance in ATRs for sizing calc
    price_col: str = "close",
    max_leverage: float = 1.0,      # clamp position size
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    RSI mean-revert:
      Long: enter when RSI recovers from <=lower (crosses back up), exit when RSI reaches >=upper (or crosses down).
      Short (optional): symmetric logic.
    """
    if rsi_col not in df.columns:
        raise KeyError(f"Required column '{rsi_col}' missing")

    rsi = df[rsi_col].astype(float)
    close = df[price_col].astype(float)

    # Cross conditions
    below = rsi <= lower
    above = rsi >= upper
    below_prev = below.shift(1).fillna(False)
    above_prev = above.shift(1).fillna(False)

    # Entry when recovering upward from oversold
    if confirm_cross:
        entry_long = (~below) & below_prev
        exit_long = above if not confirm_cross else (above & ~above_prev) | (rsi.shift(1) > rsi)
    else:
        entry_long = (~below) & below_prev
        exit_long = above

    # Optional symmetric shorts
    if allow_shorts:
        entry_short = (~above) & above_prev
        exit_short = below if not confirm_cross else (below & ~below_prev) | (rsi.shift(1) < rsi)
        entries = (entry_long | entry_short).astype(bool)
        exits   = (exit_long  | exit_short).astype(bool)
    else:
        entries = entry_long.astype(bool)
        exits   = exit_long.astype(bool)

    # Volatility-aware size (optional): risk_pct of equity per trade, ATR * atr_mult_stop stop distance
    size = None
    if atr_col in df.columns and atr_mult_stop > 0 and risk_pct > 0:
        atr = df[atr_col].astype(float)
        size = volatility_size_pct(
            price=close,
            atr=atr,
            risk_pct=risk_pct / 100.0 if risk_pct > 1 else risk_pct,
            atr_mult=atr_mult_stop,
        )
        size = clamp_size(size, max_abs=max_leverage)

    # Align and fill
    entries = entries.reindex(df.index, fill_value=False)
    exits   = exits.reindex(df.index, fill_value=False)
    if size is not None:
        size = size.reindex(df.index).fillna(0.0)

    return entries, exits, size
