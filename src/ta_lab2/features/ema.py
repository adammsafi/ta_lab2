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
    **kwargs,  # swallow legacy extras
) -> pd.Series:
    """
    Series EMA with a Pandas-backed implementation.
    Accepts extra kwargs for backward-compatibility (ignored).
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
        # be forgiving; treat unknown as oldest_top
        return obj, False
    if direction == "newest_top":
        return obj.iloc[::-1], True
    return obj, False


def _maybe_round(s: pd.Series, round_places: Optional[int]) -> pd.Series:
    return s.round(round_places) if round_places is not None else s


def _ensure_list(x: Sequence[str] | Iterable[str]) -> list[str]:
    return list(x) if not isinstance(x, list) else x


# ---------------------------------------------------------------------------
# Column builders (in-place, return df) — tolerant to extra kwargs
# ---------------------------------------------------------------------------

def add_ema_columns(
    df: pd.DataFrame,
    base_price_cols: Sequence[str] | None,
    ema_windows: Sequence[int] | None,
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
    adjust: bool = False,
    min_periods: Optional[int] = None,
    # Back-compat knobs we ignore but accept
    price_cols: Sequence[str] | None = None,
    ema_periods: Sequence[int] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    For each `col` in base_price_cols and each `w` in ema_windows, add:
      `{col}_ema_{w}`

    Accepts legacy kwargs and aliases:
      - price_cols (alias of base_price_cols)
      - ema_periods (alias of ema_windows)
      - arbitrary **kwargs (ignored)
    """
    if base_price_cols is None:
        base_price_cols = price_cols or []
    if ema_windows is None:
        ema_windows = ema_periods or []

    base_price_cols = _ensure_list(base_price_cols)
    ema_windows = [int(w) for w in ema_windows]

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
    base_price_cols: Sequence[str] | None,
    ema_windows: Sequence[int] | None,
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
    # legacy aliases/kwargs tolerated
    price_cols: Sequence[str] | None = None,
    ema_periods: Sequence[int] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    First difference of EMA:
      `{col}_ema_{w}_d1 = diff({col}_ema_{w})`

    Accepts and ignores unknown kwargs; supports direction flipping.
    """
    if base_price_cols is None:
        base_price_cols = price_cols or []
    if ema_windows is None:
        ema_windows = ema_periods or []

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
    base_price_cols: Sequence[str] | None,
    ema_windows: Sequence[int] | None,
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
    # legacy aliases/kwargs tolerated
    price_cols: Sequence[str] | None = None,
    ema_periods: Sequence[int] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Second difference of EMA:
      `{col}_ema_{w}_d2 = diff(diff({col}_ema_{w}))`

    Accepts and ignores unknown kwargs; supports direction flipping.
    """
    if base_price_cols is None:
        base_price_cols = price_cols or []
    if ema_windows is None:
        ema_windows = ema_periods or []

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


# ---- Legacy compatibility shims ----
def add_ema(df, col: str = "close", windows=(21, 50, 100, 200), prefix: str = "ema"):
    """
    Legacy wrapper: adds EMA columns for one price column.
    Mirrors old API but delegates to the new add_ema_columns.
    """
    cols = [col]
    add_ema_columns(df, cols, list(windows))
    return df

# make sure it's exported
try:
    __all__.append("add_ema")  # if __all__ exists
except NameError:
    __all__ = ["add_ema"]
