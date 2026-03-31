# src/ta_lab2/signals/ctf_threshold.py
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
CTF (Cross-Timeframe Feature) threshold signal adapter for ta_lab2.signals.

Generates entry/exit signals based on a CTF feature column crossing a threshold.
Designed for use with features from dim_feature_selection (IC-promoted CTF features
such as ret_arith_365d_divergence, vol_ratio_30d, ema_cross_score, etc.).

Signal logic:
- Long:  entry when feature > entry_threshold,
         exit  when feature < exit_threshold
- Short: entry when feature < entry_threshold,
         exit  when feature > exit_threshold

Optionally overlays a time-based exit when holding_bars > 0.

Signature (compatible with REGISTRY):
    (df: pd.DataFrame, **params)
    -> (entries: bool Series, exits: bool Series, size: Optional[Series])
"""

__all__ = ["make_signals"]

from typing import Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bars_since_entry(entries: pd.Series) -> pd.Series:
    """
    Return a Series counting bars elapsed since the most recent True in `entries`.
    Returns 0 on entry bars and increments from there.  Returns NaN before the
    first entry.
    """
    result = pd.Series(np.nan, index=entries.index, dtype=float)
    counter: Optional[int] = None
    for i, val in enumerate(entries):
        if val:
            counter = 0
        elif counter is not None:
            counter += 1
        if counter is not None:
            result.iloc[i] = counter
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_signals(
    df: pd.DataFrame,
    **params: object,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    CTF threshold signal adapter.

    Extracts a pre-computed CTF feature column from *df* and generates
    entry/exit signals based on threshold crossings.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain the column specified by *feature_col*.
    **params : keyword arguments
        feature_col : str
            Name of the CTF feature column in df.  **Required.**
        entry_threshold : float
            Threshold for entry signal.  Default 0.0.
            Long:  enter when feature > entry_threshold.
            Short: enter when feature < entry_threshold.
        exit_threshold : float
            Threshold for exit signal.  Default 0.0.
            Long:  exit when feature < exit_threshold.
            Short: exit when feature > exit_threshold.
        direction : str
            ``'long'`` (default) or ``'short'``.
        holding_bars : int
            Maximum holding period in bars before forced exit.
            ``0`` disables the time-based exit.  Default 0.

    Returns
    -------
    entries : pd.Series[bool]
        True on bars where an entry fires.
    exits : pd.Series[bool]
        True on bars where an exit fires.
    size : None
        Position sizing is delegated to the risk/sizing layer.

    Raises
    ------
    KeyError
        If *feature_col* is not present in *df*.
    """
    # ---- Extract params with defaults -----------------------------------
    feature_col: str = str(params.get("feature_col", ""))
    entry_threshold: float = float(params.get("entry_threshold", 0.0))
    exit_threshold: float = float(params.get("exit_threshold", 0.0))
    direction: str = str(params.get("direction", "long")).lower()
    holding_bars: int = int(params.get("holding_bars", 0))

    # ---- Validate feature_col presence ----------------------------------
    if not feature_col:
        raise KeyError("'feature_col' parameter is required for ctf_threshold signal.")
    if feature_col not in df.columns:
        raise KeyError(
            f"CTF feature column '{feature_col}' not found in DataFrame. "
            f"Available columns: {list(df.columns)}"
        )

    # ---- Prepare feature series ------------------------------------------
    feature = df[feature_col].astype(float).fillna(0.0)

    # ---- Threshold crossing logic ----------------------------------------
    if direction == "long":
        entry_mask = feature > entry_threshold
        exit_mask = feature < exit_threshold
    else:
        # Short: enter when feature is below threshold, exit when above
        entry_mask = feature < entry_threshold
        exit_mask = feature > exit_threshold

    entries = entry_mask.fillna(False).astype(bool)
    exits = exit_mask.fillna(False).astype(bool)

    # ---- Optional time-based holding exit --------------------------------
    if holding_bars > 0:
        bars_held = _bars_since_entry(entries)
        holding_exit = (bars_held >= holding_bars).fillna(False)
        exits = exits | holding_exit

    # ---- Align to original index ----------------------------------------
    entries = entries.reindex(df.index, fill_value=False)
    exits = exits.reindex(df.index, fill_value=False)

    return entries, exits, None
