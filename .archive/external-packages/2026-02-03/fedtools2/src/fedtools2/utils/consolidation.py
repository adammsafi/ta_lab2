# -*- coding: utf-8 -*-
"""
Dual-layer commented utilities for time-series consolidation.
(S#) short, (V#) verbose.
"""
from __future__ import annotations

import pandas as pd
from functools import reduce

def _prep(df: pd.DataFrame, name: str) -> pd.DataFrame:
    # (S1) Copy and normalize first column -> 'date' (index)
    df = df.copy()
    df.rename(columns={df.columns[0]: "date"}, inplace=True)
    # (V1) Standardize unknown date column naming conventions.

    # (S2) Datetime index sorted
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # (V2) Sorted index is required for ffill and time joins.

    # (S3) Prefix data columns + coverage flag
    df.columns = [f"{name}_{c}" for c in df.columns]
    df[f"has_{name}"] = True
    # (V3) Avoid column collisions and mark coverage.
    return df

def combine_timeframes(
    dfs: list[pd.DataFrame],
    names: list[str],
    persist: bool = True,
    limit: int | None = None
) -> pd.DataFrame:
    # (S4) Validate and normalize
    assert len(dfs) == len(names), "dfs and names must be the same length"
    prepped = [_prep(df, nm) for df, nm in zip(dfs, names)]

    # (S5) Outer-join all on date
    out = reduce(lambda l, r: l.join(r, how="outer"), prepped)

    # (S6) Fill flags to False; ffill values if requested
    for nm in names:
        out[f"has_{nm}"] = out[f"has_{nm}"].fillna(False)

    if persist:
        value_cols = [c for c in out.columns if not c.startswith("has_")]
        out[value_cols] = out[value_cols].ffill(limit=limit)
    return out

def missing_ranges(mask: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    # (S7) Early exit
    if mask.empty:
        return []
    # (S8) Normalize to pandas nullable boolean to avoid FutureWarnings
    b = mask.astype("boolean").fillna(False)

    # (S9) Detect False→True (start) and True→False (end)
    starts = (~b.shift(1, fill_value=False)) & b
    ends   = b & (~b.shift(-1, fill_value=False))
    # (V9) Pair into intervals
    return list(zip(b.index[starts], b.index[ends]))