# src/ta_lab2/features/returns.py
"""
Return/Delta utilities.

b2t_pct_delta: percentage change over N bars
b2t_log_delta: log-return over N bars

Both write columns into df and return df for chaining.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def b2t_pct_delta(
    df: pd.DataFrame,
    *,
    price_col: str = "close",
    periods: tuple[int, ...] | list[int] = (1,),
    col_fmt: str = "{col}_r_pct_{p}",
    fill_method: str | None = None,
) -> pd.DataFrame:
    """
    Add percentage-change columns for each N in `periods`.

    Example:
        b2t_pct_delta(df, price_col="close", periods=(1, 5))
        -> adds: close_r_pct_1, close_r_pct_5
    """
    if price_col not in df:
        raise KeyError(f"Column '{price_col}' not found in dataframe.")

    s = df[price_col].astype(float)
    for p in periods:
        col = col_fmt.format(col=price_col, p=p)
        df[col] = s.pct_change(p)
        if fill_method:
            df[col] = df[col].fillna(method=fill_method)
    return df


def b2t_log_delta(
    df: pd.DataFrame,
    *,
    price_col: str = "close",
    periods: tuple[int, ...] | list[int] = (1,),
    col_fmt: str = "{col}_r_log_{p}",
    fill_method: str | None = None,
) -> pd.DataFrame:
    """
    Add log-return columns for each N in `periods`.

    Example:
        b2t_log_delta(df, price_col="close", periods=(1, 5))
        -> adds: close_r_log_1, close_r_log_5
    """
    if price_col not in df:
        raise KeyError(f"Column '{price_col}' not found in dataframe.")

    s = np.log(df[price_col].astype(float))
    for p in periods:
        col = col_fmt.format(col=price_col, p=p)
        df[col] = s.diff(p)
        if fill_method:
            df[col] = df[col].fillna(method=fill_method)
    return df
