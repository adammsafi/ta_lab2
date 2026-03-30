# src/ta_lab2/signals/macd_crossover.py
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
MACD Crossover signal adapter for ta_lab2.signals.

Generates entry/exit signals based on MACD line crossing its signal line.

Signal logic:
- Long entry: MACD crosses ABOVE signal line (current bar: macd > macd_signal,
  previous bar: macd <= macd_signal)
- Long exit: MACD crosses BELOW signal line
- Short direction: inverse crossover conditions

MACD columns are computed in-memory if not already present in the DataFrame.
The helper function _compute_macd is self-contained (no imports from registry)
to avoid circular imports (registry imports this module).

Signature (compatible with REGISTRY):
    (df: pd.DataFrame, **params)
    -> (entries: bool Series, exits: bool Series, size: None)
"""

from typing import Optional, Tuple

import pandas as pd


def _compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[str, str, str]:
    """
    Compute MACD columns in-place on *df* if not already present.

    This is a self-contained copy of the logic in registry._ensure_macd,
    duplicated here to avoid a circular import (registry imports this module).

    Args:
        df: DataFrame with a ``close`` column.
        fast: Fast EMA span (default 12).
        slow: Slow EMA span (default 26).
        signal: Signal-line EMA span (default 9).

    Returns:
        Tuple of column names: (macd_col, signal_col, hist_col).
    """
    macd_col, sig_col, hist_col = "macd", "macd_signal", "macd_hist"
    if (
        macd_col not in df.columns
        or sig_col not in df.columns
        or hist_col not in df.columns
    ):
        ema_f = df["close"].ewm(span=fast, adjust=False).mean()
        ema_s = df["close"].ewm(span=slow, adjust=False).mean()
        macd = ema_f - ema_s
        macd_sig = macd.ewm(span=signal, adjust=False).mean()
        df[macd_col] = macd
        df[sig_col] = macd_sig
        df[hist_col] = macd - macd_sig
    return macd_col, sig_col, hist_col


def make_signals(
    df: pd.DataFrame,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    direction: str = "long",
    **_kwargs: object,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    Generate MACD crossover entry and exit signals.

    MACD columns (``macd``, ``macd_signal``, ``macd_hist``) are computed
    in-memory via :func:`_compute_macd` if not already present in *df*.
    Existing MACD columns (e.g., loaded from the database) are used as-is.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain a ``close`` column.  If ``macd`` / ``macd_signal``
        columns are already present they are used as-is.
    fast : int
        Fast EMA span (default 12).
    slow : int
        Slow EMA span (default 26).
    signal : int
        Signal-line EMA span (default 9).
    direction : str
        ``'long'`` (default) or ``'short'``.
    **_kwargs
        Absorbed silently so callers can pass extra params without error.

    Returns
    -------
    entries : pd.Series[bool]
        True on bars where the MACD crossover fires an entry.
    exits : pd.Series[bool]
        True on bars where the MACD crossover fires an exit.
    size : None
        Position sizing is not handled here (delegated to risk layer).
    """
    df = df.copy()

    # Ensure MACD columns exist (computes from close if missing)
    macd_col, sig_col, _hist_col = _compute_macd(
        df, fast=fast, slow=slow, signal=signal
    )

    macd = df[macd_col]
    macd_sig = df[sig_col]

    prev_macd = macd.shift(1)
    prev_sig = macd_sig.shift(1)

    if direction == "long":
        # Entry: MACD crosses ABOVE signal line
        entries = (macd > macd_sig) & (prev_macd <= prev_sig)
        # Exit: MACD crosses BELOW signal line
        exits = (macd < macd_sig) & (prev_macd >= prev_sig)
    else:
        # Short direction: entry on downward crossover, exit on upward crossover
        entries = (macd < macd_sig) & (prev_macd >= prev_sig)
        exits = (macd > macd_sig) & (prev_macd <= prev_sig)

    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    return entries, exits, None
