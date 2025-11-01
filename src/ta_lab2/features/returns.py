# src/ta_lab2/features/returns.py
from __future__ import annotations

from typing import Iterable, Sequence, Optional, Union
import numpy as np
import pandas as pd

__all__ = ["b2t_pct_delta", "b2t_log_delta"]

Number = Union[int, float, np.number]


def _coerce_cols(cols: Optional[Union[str, Sequence[str]]]) -> list[str]:
    """Normalize None / str / sequence -> list[str]."""
    if cols is None:
        return []
    if isinstance(cols, str):
        return [cols]
    return [str(c) for c in cols]


def _as_float_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        raise KeyError(f"Column '{col}' not found in DataFrame.")
    return df[col].astype(float)


def _b2b_change(
    s: pd.Series, *, mode: str = "pct", direction: str = "oldest_top"
) -> pd.Series:
    """
    Compute bar-to-bar change for a single Series.

    Parameters
    ----------
    s : Series
        Numeric series.
    mode : {"pct","log"}
        Percent change or log change.
    direction : {"oldest_top","newest_top"}
        If the DataFrame is sorted newest row first, pass "newest_top" so we
        compute changes in true chronological order and then restore order.
    """
    if direction not in ("oldest_top", "newest_top"):
        raise ValueError("direction must be 'oldest_top' or 'newest_top'")

    # Work in chronological order
    if direction == "newest_top":
        s_work = s.iloc[::-1]
        flip_back = True
    else:
        s_work = s
        flip_back = False

    if mode == "pct":
        out = s_work.pct_change()
    elif mode == "log":
        out = np.log(s_work / s_work.shift(1))
    else:
        raise ValueError("mode must be 'pct' or 'log'")

    if flip_back:
        out = out.iloc[::-1]

    return out


def _apply_b2b(
    df: pd.DataFrame,
    *,
    cols: Sequence[str],
    mode: str,
    suffix: str,
    extra_cols: Sequence[str] = (),
    round_places: Optional[int] = None,
    direction: str = "oldest_top",
) -> pd.DataFrame:
    all_cols = list(dict.fromkeys([*cols, *extra_cols]))  # dedupe keep order

    for c in all_cols:
        s = _as_float_series(df, c)
        chg = _b2b_change(s, mode=mode, direction=direction)
        if round_places is not None:
            chg = chg.round(round_places)
        df[f"{c}_{suffix}"] = chg

    return df


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------
def b2t_pct_delta(
    df: pd.DataFrame,
    *,
    cols: Optional[Sequence[str]] = None,
    columns: Optional[Sequence[str]] = None,  # legacy alias
    extra_cols: Optional[Sequence[str]] = None,
    round_places: Optional[int] = 6,
    direction: str = "oldest_top",  # or "newest_top"
    open_col: str = "open",         # kept for compatibility; not required here
    close_col: str = "close",       # kept for compatibility; not required here
) -> pd.DataFrame:
    """
    Add bar-to-bar **percent** change columns for each requested column.

    The function mutates `df` in place and also returns `df`.

    Parameters
    ----------
    df : DataFrame
    cols / columns : list[str] or str
        Columns to compute b2b deltas for.
    extra_cols : list[str], optional
        Additional columns to include.
    round_places : int or None
        Decimal places to round to; None disables rounding.
    direction : {"oldest_top", "newest_top"}
        If your data is sorted with newest row on top, pass "newest_top".
    open_col, close_col : str
        Preserved for legacy call sites; not used by this implementation.
    """
    base = _coerce_cols(columns if columns is not None else cols)
    extras = _coerce_cols(extra_cols)

    if not base and not extras:
        # Nothing to do; no-op but keep compatibility
        return df

    return _apply_b2b(
        df,
        cols=base,
        extra_cols=extras,
        mode="pct",
        suffix="b2t_pct",
        round_places=round_places,
        direction=direction,
    )


def b2t_log_delta(
    df: pd.DataFrame,
    *,
    cols: Optional[Sequence[str]] = None,
    columns: Optional[Sequence[str]] = None,  # legacy alias
    extra_cols: Optional[Sequence[str]] = None,
    round_places: Optional[int] = 6,
    direction: str = "oldest_top",
    open_col: str = "open",   # kept for compatibility; not required here
    close_col: str = "close", # kept for compatibility; not required here
) -> pd.DataFrame:
    """
    Add bar-to-bar **log** change columns for each requested column.

    Mutates `df` in place and returns `df`.
    """
    base = _coerce_cols(columns if columns is not None else cols)
    extras = _coerce_cols(extra_cols)

    if not base and not extras:
        return df

    return _apply_b2b(
        df,
        cols=base,
        extra_cols=extras,
        mode="log",
        suffix="b2t_log",
        round_places=round_places,
        direction=direction,
    )
