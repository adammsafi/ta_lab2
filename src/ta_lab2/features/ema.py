# src/ta_lab2/features/ema.py
"""
EMA helpers for ta_lab2

- add_ema:           compute a single EMA column
- add_ema_columns:   compute EMAs for multiple fields/periods (batch)
- add_ema_d1:        first difference of EMA columns (slope)
- add_ema_d2:        second difference of EMA columns (acceleration)

Compatibility shims (used by older code/tests):
- compute_ema(df, price_col="close", period=21, out_col=None)
- prepare_ema_helpers(price_col="close") -> (ema_fn, ema_d1_fn, ema_d2_fn)
"""

from __future__ import annotations
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------
def add_ema(
    df: pd.DataFrame,
    *,
    price_col: str = "close",
    period: int = 21,
    out_col: str | None = None,
    suffix_fmt: str = "{field}_ema_{period}",
) -> pd.DataFrame:
    """
    Compute a single EMA on `price_col` and write it to `out_col`.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe containing `price_col`.
    price_col : str, default "close"
        Column to use for EMA calculation.
    period : int, default 21
        EMA period (span).
    out_col : str or None, default None
        Name of the output column. If None, uses suffix_fmt.
    suffix_fmt : str, default "{field}_ema_{period}"
        Format string for default output name (field, period).

    Returns
    -------
    pd.DataFrame
        df with the new EMA column added.
    """
    if price_col not in df:
        raise KeyError(f"Column '{price_col}' not found in dataframe.")

    col = out_col or suffix_fmt.format(field=price_col, period=period)
    s = df[price_col].astype(float)
    df[col] = s.ewm(span=period, adjust=False).mean()
    return df


def add_ema_columns(
    df: pd.DataFrame,
    fields: list[str] | tuple[str, ...],
    periods: list[int] | tuple[int, ...],
    suffix_fmt: str = "{field}_ema_{period}",
) -> pd.DataFrame:
    """
    Compute EMAs for multiple fields/periods (vectorized loop).

    Example
    -------
    add_ema_columns(df, fields=["close"], periods=[21,50,100,200])
      -> columns: close_ema_21, close_ema_50, ...
    """
    for field in fields:
        if field not in df:
            raise KeyError(f"Column '{field}' not found in dataframe.")
        x = df[field].astype(float)
        for p in periods:
            df[suffix_fmt.format(field=field, period=p)] = x.ewm(span=p, adjust=False).mean()
    return df


def add_ema_d1(
    df: pd.DataFrame,
    fields: list[str] | tuple[str, ...],
    periods: list[int] | tuple[int, ...],
    round_places: int | None = None,
    suffix_fmt: str = "{field}_ema_{period}",
) -> pd.DataFrame:
    """
    Add first-difference (slope) columns for precomputed EMA columns.

    Produces: f"{field}_ema_{period}_d1"
    """
    for field in fields:
        for p in periods:
            col = suffix_fmt.format(field=field, period=p)
            if col not in df:
                raise KeyError(f"EMA column '{col}' not found. Run add_ema/add_ema_columns first.")
            d1 = df[col].diff()
            if round_places is not None:
                d1 = d1.round(round_places)
            df[f"{col}_d1"] = d1
    return df


def add_ema_d2(
    df: pd.DataFrame,
    fields: list[str] | tuple[str, ...],
    periods: list[int] | tuple[int, ...],
    round_places: int | None = None,
    suffix_fmt: str = "{field}_ema_{period}",
) -> pd.DataFrame:
    """
    Add second-difference (acceleration) columns for precomputed EMA columns.

    Produces: f"{field}_ema_{period}_d2"
    """
    for field in fields:
        for p in periods:
            col = suffix_fmt.format(field=field, period=p)
            if col not in df:
                raise KeyError(f"EMA column '{col}' not found. Run add_ema/add_ema_columns first.")
            d2 = df[col].diff().diff()
            if round_places is not None:
                d2 = d2.round(round_places)
            df[f"{col}_d2"] = d2
    return df


# ---------------------------------------------------------------------
# Convenience / orchestration
# ---------------------------------------------------------------------
def add_ema_features(
    df: pd.DataFrame,
    *,
    fields: list[str] | tuple[str, ...] = ("close",),
    periods: list[int] | tuple[int, ...] = (21, 50, 100, 200),
    include_d1: bool = True,
    include_d2: bool = True,
    round_places: int | None = None,
) -> pd.DataFrame:
    """
    Convenience orchestrator: EMAs (+ optional d1/d2) in one call.
    """
    add_ema_columns(df, fields=fields, periods=periods)
    if include_d1:
        add_ema_d1(df, fields=fields, periods=periods, round_places=round_places)
    if include_d2:
        add_ema_d2(df, fields=fields, periods=periods, round_places=round_places)
    return df


# ---------------------------------------------------------------------
# Compatibility aliases expected by older tests/code
# ---------------------------------------------------------------------
def compute_ema(
    obj,  # pd.Series or pd.DataFrame
    price_col: str = "close",
    period: int | None = None,
    window: int | None = None,
    out_col: str | None = None,
):
    """
    Back-compat helper:
      - If `obj` is a Series, return a Series EMA with span=(window or period or 21).
      - If `obj` is a DataFrame, compute/return df with an EMA column on `price_col`.
      - Accepts `window` as an alias for `period`.
    """
    if period is None and window is not None:
        period = window
    if period is None:
        period = 21

    # Series path (what the test uses)
    if isinstance(obj, pd.Series):
        return obj.astype(float).ewm(span=period, adjust=False).mean()

    # DataFrame path
    if isinstance(obj, pd.DataFrame):
        return add_ema(obj, price_col=price_col, period=period, out_col=out_col)

    raise TypeError("compute_ema expected a pandas Series or DataFrame.")



def prepare_ema_helpers(price_col: str = "close"):
    """
    Return (ema_fn, ema_d1_fn, ema_d2_fn) callables operating on `price_col`.

    - ema_fn(df, period)     -> pd.Series of EMA(period)
    - ema_d1_fn(df, period)  -> first difference of EMA (slope)
    - ema_d2_fn(df, period)  -> second difference of EMA (acceleration)

    These helpers compute (and cache in df) columns named:
      f"{price_col}_ema_{period}", plus _d1 / _d2.
    """
    def _ensure(df: pd.DataFrame):
        if not isinstance(df, pd.DataFrame):
            raise TypeError("df must be a pandas DataFrame")
        if price_col not in df:
            raise KeyError(f"'{price_col}' not in DataFrame")

    def ema_fn(df: pd.DataFrame, period: int) -> pd.Series:
        _ensure(df)
        col = f"{price_col}_ema_{period}"
        if col not in df:
            add_ema(df, price_col=price_col, period=period, out_col=col)
        return df[col]

    def ema_d1_fn(df: pd.DataFrame, period: int) -> pd.Series:
        base = ema_fn(df, period)
        d1_col = f"{price_col}_ema_{period}_d1"
        if d1_col not in df:
            df[d1_col] = base.diff()
        return df[d1_col]

    def ema_d2_fn(df: pd.DataFrame, period: int) -> pd.Series:
        base = ema_fn(df, period)
        d2_col = f"{price_col}_ema_{period}_d2"
        if d2_col not in df:
            df[d2_col] = base.diff().diff()
        return df[d2_col]

    return ema_fn, ema_d1_fn, ema_d2_fn
