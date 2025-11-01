# src/ta_lab2/features/ema.py
from __future__ import annotations

from typing import Iterable, Optional, Sequence
import numpy as np
import pandas as pd

__all__ = [
    "compute_ema",
    "add_ema_columns",
    "add_ema_d1",
    "add_ema_d2",
]

# ---------------------------------------------------------------------------
# Core EMA helper
# ---------------------------------------------------------------------------

def compute_ema(
    s: pd.Series,
    window: int,
    *,
    adjust: bool = False,
    min_periods: Optional[int] = None,
    name: Optional[str] = None,
) -> pd.Series:
    """
    Series EMA with a Pandas-backed implementation.

    Parameters
    ----------
    s : pd.Series
    window : int
        EMA span.
    adjust : bool
        Pass-through to pandas ewm(adjust=...).
    min_periods : Optional[int]
        Pass-through to pandas ewm(min_periods=...).
    name : Optional[str]
        Optional name for the returned Series.

    Returns
    -------
    pd.Series
    """
    out = (
        s.astype(float)
         .ewm(span=int(window), adjust=adjust, min_periods=min_periods)
         .mean()
    )
    if name is not None:
        out = out.rename(name)
    return out


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _flip_for_direction(obj: pd.DataFrame | pd.Series, direction: str):
    """
    If data are newest-first, flip to chronological for diff/EMA, and tell caller
    to flip back afterwards.
    """
    if direction not in ("oldest_top", "newest_top"):
        raise ValueError("direction must be 'oldest_top' or 'newest_top'")
    if direction == "newest_top":
        return obj.iloc[::-1], True
    return obj, False


def _maybe_round(s: pd.Series, round_places: Optional[int]) -> pd.Series:
    return s.round(round_places) if round_places is not None else s


def _ensure_list(x: Sequence[str] | Iterable[str]) -> list[str]:
    return list(x) if not isinstance(x, list) else x


# ---------------------------------------------------------------------------
# Column builders (in-place, return df)
# ---------------------------------------------------------------------------

def add_ema_columns(
    df: pd.DataFrame,
    base_price_cols: Sequence[str],
    ema_windows: Sequence[int],
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
    adjust: bool = False,
    min_periods: Optional[int] = None,
) -> pd.DataFrame:
    """
    For each `col` in base_price_cols and each `w` in ema_windows, add:
      `{col}_ema_{w}`

    Supports `direction='newest_top'` (flip -> compute -> flip back).
    """
    base_price_cols = _ensure_list(base_price_cols)
    ema_windows = [int(w) for w in ema_windows]

    # Work on a view with optional flip for direction; we’ll copy results back.
    work, flipped = _flip_for_direction(df, direction)

    new_cols: dict[str, pd.Series] = {}
    for col in base_price_cols:
        if col not in work.columns:
            continue
        s = work[col].astype(float)
        for w in ema_windows:
            out_name = f"{col}_ema_{w}"
            if not overwrite and out_name in df.columns:
                continue
            ema = compute_ema(s, w, adjust=adjust, min_periods=min_periods, name=out_name)
            if flipped:
                ema = ema.iloc[::-1]
            ema = _maybe_round(ema, round_places)
            new_cols[out_name] = ema

    if new_cols:
        df[list(new_cols.keys())] = pd.DataFrame(new_cols, index=df.index)
    return df


def add_ema_d1(
    df: pd.DataFrame,
    base_price_cols: Sequence[str],
    ema_windows: Sequence[int],
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
) -> pd.DataFrame:
    """
    First difference of EMA:
      `{col}_ema_{w}_d1 = diff({col}_ema_{w})`

    Respects `direction='newest_top'` by flipping for chronological diff.
    """
    base_price_cols = _ensure_list(base_price_cols)
    ema_windows = [int(w) for w in ema_windows]

    work, flipped = _flip_for_direction(df, direction)

    new_cols: dict[str, pd.Series] = {}
    for col in base_price_cols:
        for w in ema_windows:
            ema_col = f"{col}_ema_{w}"
            if ema_col not in work.columns:
                # compute on-the-fly if missing
                if col in work.columns:
                    work[ema_col] = compute_ema(work[col].astype(float), w)
                else:
                    continue
            d1_name = f"{ema_col}_d1"
            if not overwrite and d1_name in df.columns:
                continue
            d1 = work[ema_col].astype(float).diff()
            if flipped:
                d1 = d1.iloc[::-1]
            d1 = _maybe_round(d1.rename(d1_name), round_places)
            new_cols[d1_name] = d1

    if new_cols:
        df[list(new_cols.keys())] = pd.DataFrame(new_cols, index=df.index)
    return df


def add_ema_d2(
    df: pd.DataFrame,
    base_price_cols: Sequence[str],
    ema_windows: Sequence[int],
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
) -> pd.DataFrame:
    """
    Second difference of EMA:
      `{col}_ema_{w}_d2 = diff(diff({col}_ema_{w}))`
    """
    base_price_cols = _ensure_list(base_price_cols)
    ema_windows = [int(w) for w in ema_windows]

    work, flipped = _flip_for_direction(df, direction)

    new_cols: dict[str, pd.Series] = {}
    for col in base_price_cols:
        for w in ema_windows:
            ema_col = f"{col}_ema_{w}"
            if ema_col not in work.columns:
                if col in work.columns:
                    work[ema_col] = compute_ema(work[col].astype(float), w)
                else:
                    continue
            d2_name = f"{ema_col}_d2"
            if not overwrite and d2_name in df.columns:
                continue
            d2 = work[ema_col].astype(float).diff().diff()
            if flipped:
                d2 = d2.iloc[::-1]
            d2 = _maybe_round(d2.rename(d2_name), round_places)
            new_cols[d2_name] = d2

    if new_cols:
        df[list(new_cols.keys())] = pd.DataFrame(new_cols, index=df.index)
    return df
