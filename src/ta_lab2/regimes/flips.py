# ta_lab2/regimes/flips.py
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import List

def sign_from_series(df: pd.DataFrame, src_col: str, out_col: str | None = None) -> pd.DataFrame:
    """
    Make a {-1,0,+1} sign column from a numeric series.
    NaN -> NaN (kept). Zeros stay 0.
    """
    if out_col is None:
        out_col = f"{src_col}_sign"
    s = pd.to_numeric(df[src_col], errors="coerce")
    df[out_col] = np.sign(s).astype("float").where(s.notna(), np.nan).astype("Int8")
    return df

def detect_flips(df: pd.DataFrame, sign_col: str, min_separation: int = 1) -> pd.DataFrame:
    """
    Return indices where the sign changes, enforcing a minimum bar gap.
    Output columns: idx, date (if present), from_sign, to_sign, direction {"up","down"}.
    """
    s = pd.to_numeric(df[sign_col], errors="coerce")
    s_prev = s.shift(1)
    flips = s.notna() & s_prev.notna() & (np.sign(s) != np.sign(s_prev))

    idx = np.flatnonzero(flips.values)
    if min_separation > 1 and len(idx):
        keep: List[int] = []
        last = -10**9
        for i in idx:
            if i - last >= min_separation:
                keep.append(i)
                last = i
        idx = np.array(keep, dtype=int)

    out = pd.DataFrame({
        "idx": idx,
        "from_sign": s.iloc[idx - 1].astype("Int8").values,
        "to_sign": s.iloc[idx].astype("Int8").values
    })
    out["direction"] = np.where(out["to_sign"] > out["from_sign"], "up", "down")
    if "date" in df.columns:
        out["date"] = df["date"].iloc[idx].values
        out = out[["idx", "date", "from_sign", "to_sign", "direction"]]
    return out.reset_index(drop=True)

def label_regimes_from_flips(n_rows: int, flip_idx: List[int], start_regime: int = 0) -> np.ndarray:
    """
    Convert flip indices to piecewise-constant regime IDs: 0,1,2,...
    """
    reg = np.full(n_rows, start_regime, dtype=int)
    rid = start_regime
    last = 0
    for i in sorted(flip_idx):
        if i <= last or i >= n_rows:
            continue
        rid += 1
        reg[i:] = rid
        last = i
    return reg

def attach_regimes(df: pd.DataFrame, regime_ids: np.ndarray, col: str = "regime_id") -> pd.DataFrame:
    """
    Attach regime IDs to a dataframe (length must match).
    """
    if len(df) != len(regime_ids):
        raise ValueError("len(regime_ids) must equal len(df)")
    df[col] = regime_ids
    return df

def regime_stats(df: pd.DataFrame, regime_col: str = "regime_id", ret_col: str = "close_ret_1") -> pd.DataFrame:
    """
    Per-regime summary: n_bars, start/end timestamps, duration, cumulative & average returns.
    Expects a 'date' column (tz-aware OK) and a return column.
    """
    if "date" not in df.columns:
        raise KeyError("regime_stats expects a 'date' column in df.")

    def _cumret(x: pd.Series) -> float:
        x = pd.to_numeric(x, errors="coerce").dropna()
        return float((1.0 + x).prod() - 1.0) if len(x) else np.nan

    g = df.groupby(regime_col, sort=True, dropna=False)
    out = g.agg(
        n_bars = (ret_col, "count"),
        start  = ("date", "min"),
        end    = ("date", "max"),
        avg_return = (ret_col, "mean"),
        cum_return = (ret_col, _cumret),
    ).reset_index()

    # duration in days (inclusive)
    out["duration_days"] = (pd.to_datetime(out["end"]) - pd.to_datetime(out["start"])).dt.days + 1
    return out[ [regime_col, "n_bars", "start", "end", "duration_days", "avg_return", "cum_return"] ]
