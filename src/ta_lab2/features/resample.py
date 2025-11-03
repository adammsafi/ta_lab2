# src/ta_lab2/features/resample.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, Iterable, Optional
import pandas as pd
import numpy as np

from ta_lab2.features.calendar import expand_datetime_features_inplace

# Default OHLCV aggregations for downsampling
_DEFAULT_AGG = {
    "open":   "first",
    "high":   "max",
    "low":    "min",
    "close":  "last",
    "volume": "sum",
}

# Helpful note:
# - 'W' in pandas ends weeks on Sunday by default. For markets, 'W-FRI' often aligns better.
# - 'M' = month-end (deprecated in newer pandas; use 'ME' internally), 'MS' = month-start
# - 'Q', 'A' (deprecated) ~ quarter/year end; use 'QE', 'YE' internally.
# - 'B' = business-day frequency (e.g., 5B ≈ trading week); 'D' = calendar days.


# ---------------------------
# Internal helpers
# ---------------------------

def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    if "timestamp" not in d.columns:
        # best guess
        ts = next((c for c in d.columns if "time" in c or "date" in c), None)
        if ts:
            d = d.rename(columns={ts: "timestamp"})
        else:
            raise ValueError("No timestamp column found.")
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    d = d.dropna(subset=["timestamp"]).sort_values("timestamp")
    return d


def _normalize_freq(freq: str) -> str:
    """
    Map deprecated aliases to current ones for resample():
      - 'M' -> 'ME' (month end)
      - 'A' -> 'YE' (year end)
    Pass everything else through as-is.
    """
    if freq == "M":
        return "ME"
    if freq == "A":
        return "YE"
    return freq


def _season_from_month(m: pd.Series) -> pd.Series:
    """
    Meteorological seasons derived from month number:
      DJF (12,1,2), MAM (3,4,5), JJA (6,7,8), SON (9,10,11)
    """
    m = pd.to_numeric(m, errors="coerce").astype("Int64")
    out = pd.Series(index=m.index, dtype="object")
    out[m.isin([12, 1, 2])]  = "DJF"
    out[m.isin([3, 4, 5])]   = "MAM"
    out[m.isin([6, 7, 8])]   = "JJA"
    out[m.isin([9, 10, 11])] = "SON"
    return out


# ---------------------------
# Public API
# ---------------------------

def resample_one(
    df: pd.DataFrame,
    freq: str,
    agg: Optional[dict] = None,
    align_to: Optional[str] = None,
) -> pd.DataFrame:
    """
    Resample a daily (or finer) dataframe with OHLCV into a target frequency.

    Parameters
    ----------
    df : DataFrame with columns timestamp, open/high/low/close/volume
    freq : pandas offset alias, e.g. '2D','3D','5D','10D','25D','45D','W','W-FRI','2W','3W','M','2M','3M','6M','A'
    agg  : dict of column -> aggregation; defaults to OHLCV-safe _DEFAULT_AGG
    align_to : optional tz name (e.g., 'UTC') if you need explicit tz conversion

    Returns
    -------
    DataFrame with same OHLCV schema at the new timeframe, plus calendar fields and 'tfreq'.
    """
    d = _normalize(df)
    if align_to:
        # d['timestamp'] is tz-aware UTC from _normalize, but we still honor explicit requests
        d["timestamp"] = d["timestamp"].dt.tz_convert(align_to)

    _freq = _normalize_freq(freq)  # avoid pandas deprecation warnings
    a = {k: v for k, v in (agg or _DEFAULT_AGG).items() if k in d.columns}

    out = (
        d.set_index("timestamp")
         .resample(_freq)          # use normalized frequency
         .agg(a)
         .dropna(how="any")
         .reset_index()
    )

    # Attach calendar fields (year, month, week, season, etc.)
    try:
        expand_datetime_features_inplace(out, "timestamp")
    except Exception:
        # If calendar expansion fails for any reason, proceed with a bare frame
        pass

    out["tfreq"] = _freq
    return out


def resample_many(
    df: pd.DataFrame,
    freqs: Iterable[str],
    agg: Optional[dict] = None,
    outdir: Optional[str | Path] = "artifacts/frames",
    overwrite: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Build multiple timeframe views and (optionally) persist as parquet/csv.

    Returns
    -------
    dict: {original_freq_string -> DataFrame}
    """
    outdir = Path(outdir) if outdir else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    frames: Dict[str, pd.DataFrame] = {}
    for f in freqs:
        view = resample_one(df, f, agg=agg)
        frames[f] = view
        if outdir:
            # Persist using the original frequency string in the filename for continuity
            path = outdir / f"{f}.parquet"
            if overwrite or not path.exists():
                try:
                    view.to_parquet(path)
                except Exception:
                    view.to_csv(path.with_suffix(".csv"), index=False)
    return frames


def add_season_label(df: pd.DataFrame, column: str = "season") -> pd.DataFrame:
    """
    Ensure a 'season' column exists (DJF/MAM/JJA/SON). Will attempt to use
    expand_datetime_features_inplace; if not present, derives from month.
    """
    d = _normalize(df).copy()
    # Try calendar expansion first (adds 'season' if implemented in calendar.py)
    try:
        expand_datetime_features_inplace(d, "timestamp")
    except Exception:
        pass

    # If still missing, derive from month manually
    if column not in d.columns or d[column].isna().all():
        month = pd.to_datetime(d["timestamp"], utc=True, errors="coerce").dt.month
        d[column] = _season_from_month(month)

    return d


def seasonal_summary(
    df: pd.DataFrame,
    price_col: str = "close",
    ret_kind: str = "arith",  # 'arith' or 'geom'
) -> pd.DataFrame:
    """
    Aggregate returns by season across years.

    'arith': within each (year, season), return = last/first - 1
    'geom' : within each (year, season), product(1+r_d) - 1 using daily 'close_pct_delta' if present;
             otherwise falls back to arithmetic.
    """
    d = _normalize(df).copy()

    # Attach calendar fields when available, but don't require them
    try:
        expand_datetime_features_inplace(d, "timestamp")
    except Exception:
        pass

    # Ensure 'year' and 'season'
    ts = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    if "year" not in d.columns:
        d["year"] = ts.dt.year
    if "season" not in d.columns or d["season"].isna().all():
        d["season"] = _season_from_month(ts.dt.month)

    d = d.dropna(subset=["season"]).sort_values("timestamp")

    if ret_kind == "geom" and "close_pct_delta" in d.columns:
        rel = d["close_pct_delta"].fillna(0).add(1.0)

        def _geo(g: pd.DataFrame) -> float:
            # product of relatives minus 1
            return rel.loc[g.index].prod() - 1.0

        season_ret = d.groupby(["year", "season"], sort=False).apply(_geo)
    else:
        def _arith(g: pd.DataFrame) -> float:
            c = pd.to_numeric(g[price_col], errors="coerce").dropna()
            return (c.iloc[-1] / c.iloc[0] - 1.0) if len(c) >= 2 else np.nan

        season_ret = d.groupby(["year", "season"], sort=False).apply(_arith)

    out = season_ret.rename("return").reset_index()

    # overall average by season
    overall = (
        out.groupby("season", as_index=False)["return"]
           .mean()
           .rename(columns={"return": "avg_return_by_season"})
    )
    return out.merge(overall, on="season", how="left")
