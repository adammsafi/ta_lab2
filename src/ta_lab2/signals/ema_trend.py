# src/ta_lab2/signals/ema_trend.py
from __future__ import annotations
from typing import Optional, Tuple
import pandas as pd
from .generator import generate_signals


def make_signals(
    df: pd.DataFrame,
    *,
    fast_ema: str = "ema_21",
    slow_ema: str = "ema_50",
    # Optional filters: will be auto-disabled if their columns are absent
    rsi_col: str = "rsi_14",
    atr_col: str = "atr_14",
    use_rsi_filter: bool = False,
    use_vol_filter: bool = False,
    rsi_min_long: int = 45,
    rsi_max_short: int = 55,
    min_atr_pct: float = 0.003,
    # Strategy toggles
    allow_shorts: bool = False,
    cooldown_bars: int = 0,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    EMA crossover adapter.
      - Entries when fast EMA crosses above slow EMA
      - Exits   when fast EMA crosses below slow EMA
    This adapter NEVER requires columns you didn't provide:
      - If `use_rsi_filter=True` but `rsi_col` is missing, the RSI filter is auto-disabled.
      - If `use_vol_filter=True` but `atr_col` is missing, the vol filter is auto-disabled.

    Returns:
      (entries: bool Series, exits: bool Series, size: Optional[float Series])
    """

    # Validate the two EMAs minimally (clear error if truly missing)
    if fast_ema not in df.columns:
        raise KeyError(f"Missing fast EMA column: {fast_ema!r}")
    if slow_ema not in df.columns:
        raise KeyError(f"Missing slow EMA column: {slow_ema!r}")

    # Auto-disable filters if their inputs aren't present
    _use_rsi = bool(use_rsi_filter and (rsi_col in df.columns))
    _use_vol = bool(use_vol_filter and (atr_col in df.columns))

    d = generate_signals(
        df=df,
        fast_ema=fast_ema,
        slow_ema=slow_ema,
        rsi_col=rsi_col,
        atr_col=atr_col,
        use_rsi_filter=_use_rsi,
        use_vol_filter=_use_vol,
        rsi_min_long=rsi_min_long,
        rsi_max_short=rsi_max_short,
        min_atr_pct=min_atr_pct,
        allow_shorts=allow_shorts,
        cooldown_bars=cooldown_bars,
    )

    if allow_shorts:
        entries = (d["entry_long"] | d["entry_short"]).astype(bool)
        exits   = (d["exit_long"]  | d["exit_short"]).astype(bool)
    else:
        entries = d["entry_long"].astype(bool)
        exits   = d["exit_long"].astype(bool)

    size = d.get("size")  # may be absent; that's fine (runners handle None)

    # Ensure alignment to original index
    entries = entries.reindex(df.index, fill_value=False)
    exits   = exits.reindex(df.index, fill_value=False)
    if size is not None:
        size = size.reindex(df.index).astype(float)

    return entries, exits, size
