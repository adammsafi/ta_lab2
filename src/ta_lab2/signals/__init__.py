# src/ta_lab2/signals/__init__.py
# -*- coding: utf-8 -*-
"""
Signal package initializer for ta_lab2.

Exports:
- generate_signals: core composer returning a rich signal DataFrame.
- rules: primitive boolean rules (EMA cross, RSI gates, ATR gates).
- REGISTRY: strategy-name -> callable(df, **params) returning (entries, exits, size).
- attach_signals_from_config: light wrapper to build a signal frame from a named strategy.
"""

from __future__ import annotations
from typing import Optional, Tuple
import pandas as pd

from .generator import generate_signals
from . import rules
from .registry import REGISTRY  # strategy registry (e.g., "ema_trend" -> callable)


def attach_signals_from_config(
    df: pd.DataFrame,
    strategy: str,
    **params,
) -> pd.DataFrame:
    """
    Back-compat helper.
    Builds a minimal signal frame for a given named strategy using REGISTRY.

    Returns a DataFrame with:
      - entry_long, exit_long (bool)
      - entry_short, exit_short (bool) only if the strategy produced them
      - size (float) if the strategy returned it
    """
    if strategy not in REGISTRY:
        raise KeyError(f"Strategy '{strategy}' not found in signals.REGISTRY")

    entries, exits, size = REGISTRY[strategy](df, **params)

    out = pd.DataFrame(index=df.index)
    # We don't know long/short semantics from generic adapters, so map to longs.
    # Adapters that produce both sides should return via generator() instead.
    out["entry_long"] = entries.astype(bool)
    out["exit_long"] = exits.astype(bool)
    if size is not None:
        out["size"] = pd.to_numeric(size, errors="coerce")

    return out


__all__ = [
    "generate_signals",
    "rules",
    "REGISTRY",
    "attach_signals_from_config",
]
