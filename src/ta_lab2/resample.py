from typing import Dict, Optional
import pandas as pd
import numpy as np
from pandas.api.types import is_datetime64_any_dtype

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _ensure_datetime_index(df: pd.DataFrame, dt_col: str):
    w = df.copy()

    # Robust tz-aware parsing
    if not is_datetime64_any_dtype(w[dt_col]):
        w[dt_col] = pd.to_datetime(w[dt_col], errors="coerce", utc=True)

    # Drop NaT and sort
    w = w.dropna(subset=[dt_col])
    asc_now = True
    if len(w) >= 2:
        asc_now = bool(w[dt_col].iloc[0] <= w[dt_col].iloc[-1])

    # Set tz-aware DatetimeIndex (resample works fine with tz)
    w = w.set_index(dt_col).sort_index()
    return w, asc_now


def _apply_ohlcv_agg(
    w: pd.DataFrame,
    ohlc_cols=("open", "high", "low", "close"),
    sum_cols=("volume",),
    extra_aggs: Optional[Dict[str, str]] = None,
):
    """Return a flat agg mapping suitable for pandas >= 1.5."""
    agg = {}
    o, h, l, c = ohlc_cols
    if o in w.columns:
        agg[o] = "first"
    if h in w.columns:
        agg[h] = "max"
    if l in w.columns:
        agg[l] = "min"
    if c in w.columns:
        agg[c] = "last"
    for sc in sum_cols:
        if sc in w.columns:
            agg[sc] = "sum"
    if extra_aggs:
        for col, fn in extra_aggs.items():
            if col in w.columns:
                agg[col] = fn
    return agg


def _flatten_agg_columns(r: pd.DataFrame) -> pd.DataFrame:
    # kept for backward-compat; not used by the flat-agg path
    if isinstance(r.columns, pd.MultiIndex):
        r.columns = [
            "_".join([c for c in tup if c]) for tup in r.columns.to_flat_index()
        ]
    return r


# ---------------------------------------------------------------------
# Calendar resampling with smart defaults for label/closed
# ---------------------------------------------------------------------


def _auto_label_closed(freq: str, label: Optional[str], closed: Optional[str]):
    """
    Start-anchored (MS, QS, AS, BMS, W-<DAY>) -> ('left','left')
    End-anchored   (M,  Q,  A,  BM)           -> ('right','right')
    Otherwise keep user overrides or default to right/right.
    """
    if label is not None and closed is not None:
        return label, closed

    f = str(freq).upper()

    # Weekly with explicit anchor (e.g., W-SUN, W-MON) -> start-anchored
    if f.startswith("W-"):
        return label or "left", closed or "left"

    # Month/Quarter/Year "start" anchors end with 'S'
    if f.endswith("MS") or f.endswith("QS") or f.endswith("AS") or f.endswith("BMS"):
        return label or "left", closed or "left"

    # Classic end-anchored periods (month end, quarter end, year end)
    if f in {"M", "Q", "A", "BM", "BQ", "BA"}:
        return label or "right", closed or "right"

    # Fallback default: right/right
    return label or "right", closed or "right"


def bin_by_calendar(
    df: pd.DataFrame,
    dt_col: str,
    freq: str,
    *,
    ohlc_cols=("open", "high", "low", "close"),
    sum_cols=("volume",),
    extra_aggs: Optional[Dict[str, str]] = None,
    label: Optional[str] = None,
    closed: Optional[str] = None,
) -> pd.DataFrame:
    # Auto-pick sensible label/closed defaults if not supplied
    label, closed = _auto_label_closed(freq, label, closed)

    w, asc_was = _ensure_datetime_index(df, dt_col)
    agg = _apply_ohlcv_agg(
        w, ohlc_cols=ohlc_cols, sum_cols=sum_cols, extra_aggs=extra_aggs
    )

    r = (
        w.resample(freq, label=label, closed=closed)
        .agg(agg)
        .dropna(how="all")
        .reset_index()
        .rename(columns={w.index.name: "period_end"})
    )

    if not asc_was:
        r = r.iloc[::-1].reset_index(drop=True)
    return r


# ---------------------------------------------------------------------
# Seasonal binning
# ---------------------------------------------------------------------

_SEASON_ORDER = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}


def _season_id_from_exact_row(ts: pd.Timestamp, season_label: str):
    if pd.isna(ts) or not season_label:
        return (np.nan, np.nan)
    if season_label == "Winter":
        if ts.month == 12:
            return (ts.year, "Winter")
        else:
            return (ts.year - 1, "Winter")
    return (ts.year, season_label)


def bin_by_season(
    df: pd.DataFrame,
    dt_col: str,
    *,
    season_col_exact: str = None,
    season_col_approx: str = None,
    n: int = 1,
    ohlc_cols=("open", "high", "low", "close"),
    sum_cols=("volume",),
    extra_aggs: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    # choose season label column
    if season_col_exact and season_col_exact in df.columns:
        s_col = season_col_exact
    elif season_col_approx and season_col_approx in df.columns:
        s_col = season_col_approx
    else:
        raise KeyError(
            "Season column not found. Provide season_col_exact or season_col_approx."
        )

    w, asc_was = _ensure_datetime_index(df, dt_col)
    w["_season_label"] = df.loc[w.index, s_col]

    # map each timestamp to (season_year, season_label) with Winter spanning year boundary
    season_year, labels = [], []
    for ts, lab in zip(w.index, w["_season_label"]):
        y, lbl = _season_id_from_exact_row(ts, lab)
        season_year.append(y)
        labels.append(lbl)
    w["_season_year"] = season_year
    w["_season_lbl"] = labels
    w = w.dropna(subset=["_season_year", "_season_lbl"])

    # ordinal season index for n-season blocking
    ordinals = w["_season_year"].astype(int) * 4 + w["_season_lbl"].map(
        _SEASON_ORDER
    ).astype(int)
    w["_season_ord"] = ordinals

    # group keys: single season or n-season blocks
    if n <= 1:
        grp_keys = ["_season_year", "_season_lbl"]
    else:
        w["_season_block"] = w["_season_ord"] // n
        grp_keys = ["_season_block"]

    # --- flat aggregation path (avoid nested renamers) ---
    # attach timestamp copy for bounds
    w["__ts"] = w.index

    # core OHLCV agg
    agg = _apply_ohlcv_agg(
        w, ohlc_cols=ohlc_cols, sum_cols=sum_cols, extra_aggs=extra_aggs
    )
    g = w.groupby(grp_keys)

    core = g.agg(agg).reset_index()
    bounds = g["__ts"].agg(period_start="min", period_end="max").reset_index()

    r = core.merge(bounds, on=grp_keys, how="inner")

    # human-readable bin label
    if n <= 1:
        r["season_bin"] = (
            r["_season_year"].astype(int).astype(str) + "-" + r["_season_lbl"]
        )
    else:
        name_map = (
            w.groupby("_season_block")
            .apply(
                lambda g2: f"{int(g2['_season_year'].iloc[0])}-{g2['_season_lbl'].iloc[0]}__to__{int(g2['_season_year'].iloc[-1])}-{g2['_season_lbl'].iloc[-1]}"
            )
            .rename("season_bin")
        ).to_dict()
        r["season_bin"] = r["_season_block"].map(name_map)

    # order & clean columns
    keep_first = ["period_start", "period_end", "season_bin"]
    drop_these = {"__ts", "_season_year", "_season_lbl", "_season_ord", "_season_block"}
    rest = [
        c
        for c in r.columns
        if c not in drop_these and c not in keep_first and c not in grp_keys
    ]
    r = r[keep_first + rest].sort_values("period_end").reset_index(drop=True)

    if not asc_was:
        r = r.iloc[::-1].reset_index(drop=True)

    return r
