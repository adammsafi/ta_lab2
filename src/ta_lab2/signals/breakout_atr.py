from __future__ import annotations
from typing import Optional, Tuple
import pandas as pd
import numpy as np
from .position_sizing import volatility_size_pct, clamp_size, ema_smooth


def _rolling_high(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).max()


def _rolling_low(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).min()


def make_signals(
    df: pd.DataFrame,
    lookback: int = 20,            # Donchian breakout window
    atr_col: str = "atr_14",
    price_cols: tuple[str, str, str, str] = ("open", "high", "low", "close"),
    confirm_close: bool = True,    # require close breakout vs. intrabar
    exit_on_channel_crossback: bool = True,
    use_trailing_atr_stop: bool = True,
    trail_atr_mult: float = 2.0,
    risk_pct: float = 0.5,         # equity risk fraction per trade for sizing
    size_smoothing_ema: Optional[int] = 5,
    max_leverage: float = 1.0,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    Breakout strategy:
      Long entry: close breaks above highest high of `lookback`.
      Exit: channel crossback OR trailing ATR stop (configurable).
      Short side omitted by default (add later if desired).
    """
    o, h, l, c = [df[col].astype(float) for col in price_cols]
    high_n = _rolling_high(h, lookback)
    low_n  = _rolling_low(l, lookback)

    if confirm_close:
        entry_long = c > high_n.shift(1)     # break above prior channel
        exit_long_cb = c < low_n.shift(1)    # cross back into/below channel
    else:
        entry_long = h > high_n.shift(1)
        exit_long_cb = l < low_n.shift(1)

    # Optional ATR trailing stop exit
    if use_trailing_atr_stop and atr_col in df.columns:
        atr = df[atr_col].astype(float)
        stop_long = c - trail_atr_mult * atr
        # Trailing stop line (max of prior stops)
        trail_line = stop_long.copy()
        trail_line = pd.Series(np.maximum.accumulate(trail_line.values), index=trail_line.index)
        exit_long_ts = c < trail_line
    else:
        exit_long_ts = pd.Series(False, index=df.index)

    exit_long = exit_long_cb if exit_on_channel_crossback else exit_long_ts

    entries = entry_long.astype(bool)
    exits   = exit_long.astype(bool)

    # Volatility-aware size (ATR)
    size = None
    if atr_col in df.columns and risk_pct > 0:
        atr = df[atr_col].astype(float)
        size = volatility_size_pct(
            price=c,
            atr=atr,
            risk_pct=risk_pct / 100.0 if risk_pct > 1 else risk_pct,
            atr_mult=trail_atr_mult if use_trailing_atr_stop else 1.0,
        )
        if size_smoothing_ema:
            size = ema_smooth(size, span=size_smoothing_ema)
        size = clamp_size(size, max_abs=max_leverage)

    entries = entries.reindex(df.index, fill_value=False)
    exits   = exits.reindex(df.index, fill_value=False)
    if size is not None:
        size = size.reindex(df.index).fillna(0.0)

    return entries, exits, size
