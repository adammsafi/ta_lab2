# -*- coding: utf-8 -*-
"""
Created on Fri Oct 31 11:35:04 2025

@author: asafi
"""

import sys, os, re
import pandas as pd
import numpy as np

# Add the parent dir so Python can import the ta_lab2 package folder
sys.path.append(r"C:/Users/asafi/Downloads")   # << parent of ta_lab2

from ta_lab2.resample import bin_by_calendar, bin_by_season
from ta_lab2.features.calendar import expand_datetime_features_inplace
from ta_lab2.features.ema import add_ema_columns, add_ema_d1, add_ema_d2
from ta_lab2.features.returns import add_returns
from ta_lab2.features.vol import add_atr

# Regimes/co-movement helpers
from ta_lab2.regimes.comovement import (
    build_alignment_frame, sign_agreement, rolling_agreement
)
from ta_lab2.regimes.flips import (
    sign_from_series, detect_flips, label_regimes_from_flips,
    attach_regimes, regime_stats
)

# ---- helpers ---------------------------------------------------------------
def _clean_headers(cols):
    """Strip spaces, lower, collapse internal spaces -> single underscores."""
    out = []
    for c in cols:
        c2 = c.strip().lower()
        c2 = re.sub(r"\s+", " ", c2)          # collapse multiple spaces
        c2 = c2.replace(" ", "_")             # spaces -> underscore
        out.append(c2)
    return out

def _to_num(s):
    """Coerce numeric fields (remove commas, turn '-'/'' to NaN)."""
    return pd.to_numeric(
        pd.Series(s).astype(str)
        .str.replace(",", "", regex=False)
        .replace({"-": None, "": None}),
        errors="coerce"
    )

def _parse_epoch_series(x: pd.Series) -> pd.Series:
    """Try seconds vs milliseconds automatically."""
    x = pd.to_numeric(x, errors="coerce")
    if x.dropna().median() > 10_000_000_000:
        return pd.to_datetime(x, unit="ms", utc=True, errors="coerce")
    return pd.to_datetime(x, unit="s", utc=True, errors="coerce")


# ---- load your CSV ---------------------------------------------------------
csv_path = r"C:/Users/asafi/Downloads/ta_lab2/Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
df2 = pd.read_csv(csv_path)

# Normalize headers to stable names
df2.columns = _clean_headers(df2.columns)
# Expected: timeopen, timeclose, timehigh, timelow, name, open, high, low, close, volume, marketcap, timestamp

# Build 'timeopen' timestamp (prefer timeopen; fall back to epoch 'timestamp' if needed)
if "timeopen" in df2.columns:
    dt = pd.to_datetime(df2["timeopen"], errors="coerce", utc=True)
else:
    dt = pd.NaT

if dt.isna().mean() > 0.5 and "timestamp" in df2.columns:
    ts_dt = _parse_epoch_series(df2["timestamp"])
    if ts_dt.notna().sum() > dt.notna().sum():
        dt = ts_dt

if dt.isna().all():
    raise KeyError("Could not parse any timestamps from 'timeOpen' or 'timestamp' columns.")

df2["timeopen"] = dt
df2 = df2.dropna(subset=["timeopen"]).reset_index(drop=True)

# Coerce OHLCV to numeric
for col in ["open", "high", "low", "close", "volume", "marketcap"]:
    if col in df2.columns:
        df2[col] = _to_num(df2[col])

# Sort ascending by time
df2 = df2.sort_values("timeopen").reset_index(drop=True)

print("Loaded rows:", len(df2))
print("Date range:", df2["timeopen"].min(), "→", df2["timeopen"].max())
print("Columns now:", list(df2.columns))

# ---- calendar features (adds season + moon if astronomy-engine installed) ---
expand_datetime_features_inplace(df2, "timeopen", prefix="timeopen")

# ---- resample to weekly / monthly (smart defaults handle left/left) ---------
weekly = (
    bin_by_calendar(df2, "timeopen", "W-SUN")
      .rename(columns={"period_end": "date"})
)
weekly["timeframe"] = "1W"

monthly = (
    bin_by_calendar(df2, "timeopen", "MS")
      .rename(columns={"period_end": "date"})
)
monthly["timeframe"] = "1M"

# Daily from raw rows
daily = df2.rename(columns={"timeopen": "date"})[["date","open","high","low","close","volume"]].copy()
daily["timeframe"] = "1D"

for d in (daily, weekly, monthly):
    d["symbol"] = "BTC-USD"

# ---- indicator enrichment ---------------------------------------------------
def enrich(bars: pd.DataFrame) -> pd.DataFrame:
    add_returns(bars, close_col="close")  # adds close_ret_1 by default (per your local impl)
    add_ema_columns(bars, ["close"], [21,50,100,200])
    add_ema_d1(bars, ["close"], [21,50,100,200])
    add_ema_d2(bars, ["close"], [21,50,100,200])
    add_atr(bars, period=14, high_col="high", low_col="low", close_col="close")
    return bars

daily_en   = enrich(daily.copy())
weekly_en  = enrich(weekly.copy())
monthly_en = enrich(monthly.copy())

# ---- quick cross-timeframe comparison: EMA21 slope agreement ---------------
d = daily_en[["date","close_ema_21_d1"]].sort_values("date")
w = weekly_en[["date","close_ema_21_d1"]].sort_values("date").rename(columns={"close_ema_21_d1":"close_ema_21_d1_w"})
cmp = pd.merge_asof(d, w, on="date", direction="backward")
cmp["ema21_d1_agree"] = (cmp["close_ema_21_d1"] * cmp["close_ema_21_d1_w"]) > 0
print("Daily vs Weekly EMA21 slope agreement:", f"{cmp['ema21_d1_agree'].mean():.2%}")

# ---- boundary sanity checks (scalar-safe) ----------------------------------
def _scal(s):
    return s.iloc[0] if hasattr(s, "iloc") else s

def check_boundary(dt_str):
    dt = pd.Timestamp(dt_str, tz="UTC")
    drow = daily.loc[daily["date"] == dt]
    wrow = weekly.loc[weekly["date"] == dt]
    mrow = monthly.loc[monthly["date"] == dt]

    if not drow.empty and not wrow.empty:
        print("WEEK check:", dt_str,
              "daily open:", float(_scal(drow["open"])),
              "weekly open:", float(_scal(wrow["open"])))
    if not drow.empty and not mrow.empty:
        print("MONTH check:", dt_str,
              "daily open:", float(_scal(drow["open"])),
              "monthly open:", float(_scal(mrow["open"])))


check_boundary("2015-02-01")
check_boundary("2015-01-01")

# ---- regime labelling on daily EMA21 slope ---------------------------------
# Start from the enriched daily (has EMAs and close_ret_1 already from enrich())
daily_sig = sign_from_series(daily_en.copy(), "close_ema_21_d1", out_col="d_slope_sign")

# Defensive: ensure the forward return column exists on the working frame
if "close_ret_1" not in daily_sig.columns:
    add_returns(daily_sig, close_col="close")  # no unsupported kwargs

# Detect sign flips and build regimes
flips = detect_flips(daily_sig, "d_slope_sign", min_separation=2)
regime_ids = label_regimes_from_flips(len(daily_sig), flips["idx"].tolist())
daily_reg = attach_regimes(daily_sig, regime_ids, col="regime_id")

# Ensure we have forward 1-bar return named exactly 'close_ret_1' before stats
if "close_ret_1" not in daily_reg.columns:
    # Try to reuse any existing close-return column if present
    candidates = [c for c in daily_reg.columns if c.startswith("close") and "ret" in c]
    if candidates:
        daily_reg["close_ret_1"] = daily_reg[candidates[0]]
    else:
        # Compute forward simple return: (close[t+1] / close[t]) - 1
        daily_reg["close_ret_1"] = (daily_reg["close"].shift(-1) / daily_reg["close"]) - 1

# Summarize regimes
stats = regime_stats(daily_reg, regime_col="regime_id", ret_col="close_ret_1")
print(stats.head())

# ---- daily↔weekly co-movement analysis -------------------------------------
al = build_alignment_frame(
    daily_en, weekly_en,
    on="date",
    low_cols=["close_ema_21_d1"],
    high_cols=["close_ema_21_d1"]
).rename(columns={"close_ema_21_d1": "d_slope", "close_ema_21_d1_w": "w_slope"})

al, pct = sign_agreement(al, "d_slope", "w_slope", out_col="agree")
al = rolling_agreement(al, "d_slope", "w_slope", window=63)
