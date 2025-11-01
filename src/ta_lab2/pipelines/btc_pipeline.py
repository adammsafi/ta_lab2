# -*- coding: utf-8 -*-
"""
Created on Fri Oct 31 16:05:09 2025

@author: asafi
"""

import os, re, argparse
import pandas as pd
import numpy as np

from ta_lab2.resample import bin_by_calendar
from ta_lab2.features.calendar import expand_datetime_features_inplace
from ta_lab2.features.ema import add_ema_columns, add_ema_d1, add_ema_d2
from ta_lab2.features.returns import add_returns
from ta_lab2.features.vol import add_atr
from ta_lab2.regimes.comovement import build_alignment_frame, sign_agreement, rolling_agreement
from ta_lab2.regimes.flips import (
    sign_from_series, detect_flips, label_regimes_from_flips,
    attach_regimes, regime_stats
)

# -------- utils --------

def _clean_headers(cols):
    return [re.sub(r"\s+", " ", c.strip().lower()).replace(" ", "_") for c in cols]

def _to_num(s):
    return pd.to_numeric(
        pd.Series(s).astype(str).str.replace(",", "", regex=False).replace({"-": None, "": None}),
        errors="coerce"
    )

def _parse_epoch_series(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x, errors="coerce")
    if x.dropna().median() > 10_000_000_000:
        return pd.to_datetime(x, unit="ms", utc=True, errors="coerce")
    return pd.to_datetime(x, unit="s", utc=True, errors="coerce")

def _scal(s):
    return s.iloc[0] if hasattr(s, "iloc") else s

# -------- IO + cleaning --------

def load_clean_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = _clean_headers(df.columns)

    # Build timeopen (prefer timeopen; fallback to epoch timestamp)
    if "timeopen" in df.columns:
        dt = pd.to_datetime(df["timeopen"], errors="coerce", utc=True)
    else:
        dt = pd.NaT

    if dt.isna().mean() > 0.5 and "timestamp" in df.columns:
        ts_dt = _parse_epoch_series(df["timestamp"])
        if ts_dt.notna().sum() > dt.notna().sum():
            dt = ts_dt

    if pd.isna(dt).all():
        raise KeyError("Could not parse timestamps from 'timeOpen' or 'timestamp'.")

    df["timeopen"] = dt
    for col in ["open", "high", "low", "close", "volume", "marketcap"]:
        if col in df.columns:
            df[col] = _to_num(df[col])

    df = df.dropna(subset=["timeopen"]).sort_values("timeopen").reset_index(drop=True)

    print("Loaded rows:", len(df))
    print("Date range:", df["timeopen"].min(), "→", df["timeopen"].max())
    print("Columns now:", list(df.columns))
    return df

# -------- timeframes --------

def build_timeframes(df: pd.DataFrame):
    expand_datetime_features_inplace(df, "timeopen", prefix="timeopen")

    weekly = bin_by_calendar(df, "timeopen", "W-SUN").rename(columns={"period_end": "date"})
    weekly["timeframe"] = "1W"

    monthly = bin_by_calendar(df, "timeopen", "MS").rename(columns={"period_end": "date"})
    monthly["timeframe"] = "1M"

    daily = df.rename(columns={"timeopen": "date"})[["date","open","high","low","close","volume"]].copy()
    daily["timeframe"] = "1D"

    for d in (daily, weekly, monthly):
        d["symbol"] = "BTC-USD"

    return daily, weekly, monthly

# -------- enrichment --------

def enrich(bars: pd.DataFrame) -> pd.DataFrame:
    add_returns(bars, close_col="close")  # local impl: creates close_ret_1
    add_ema_columns(bars, ["close"], [21,50,100,200])
    add_ema_d1(bars, ["close"], [21,50,100,200])
    add_ema_d2(bars, ["close"], [21,50,100,200])
    add_atr(bars, period=14, high_col="high", low_col="low", close_col="close")
    return bars

def enrich_all(daily, weekly, monthly):
    return enrich(daily.copy()), enrich(weekly.copy()), enrich(monthly.copy())

# -------- diagnostics --------

def print_ema21_agreement(daily_en: pd.DataFrame, weekly_en: pd.DataFrame):
    d = daily_en[["date","close_ema_21_d1"]].sort_values("date")
    w = weekly_en[["date","close_ema_21_d1"]].sort_values("date").rename(columns={"close_ema_21_d1":"close_ema_21_d1_w"})
    cmp = pd.merge_asof(d, w, on="date", direction="backward")
    cmp["ema21_d1_agree"] = (cmp["close_ema_21_d1"] * cmp["close_ema_21_d1_w"]) > 0
    print("Daily vs Weekly EMA21 slope agreement:", f"{cmp['ema21_d1_agree'].mean():.2%}")

def boundary_check(daily, weekly, monthly, dates_utc):
    for dt_str in dates_utc:
        dt = pd.Timestamp(dt_str, tz="UTC")
        drow = daily.loc[daily["date"] == dt]
        wrow = weekly.loc[weekly["date"] == dt]
        mrow = monthly.loc[monthly["date"] == dt]
        if not drow.empty and not wrow.empty:
            print("WEEK check:", dt_str, "daily open:", float(_scal(drow["open"])), "weekly open:", float(_scal(wrow["open"])))
        if not drow.empty and not mrow.empty:
            print("MONTH check:", dt_str, "daily open:", float(_scal(drow["open"])), "monthly open:", float(_scal(mrow["open"])))

# -------- regimes --------

def compute_regimes(daily_en: pd.DataFrame):
    daily_sig = sign_from_series(daily_en.copy(), "close_ema_21_d1", out_col="d_slope_sign")

    if "close_ret_1" not in daily_sig.columns:
        add_returns(daily_sig, close_col="close")

    flips = detect_flips(daily_sig, "d_slope_sign", min_separation=2)
    regime_ids = label_regimes_from_flips(len(daily_sig), flips["idx"].tolist())
    daily_reg = attach_regimes(daily_sig, regime_ids, col="regime_id")

    if "close_ret_1" not in daily_reg.columns:
        # fallback: compute forward simple return
        daily_reg["close_ret_1"] = (daily_reg["close"].shift(-1) / daily_reg["close"]) - 1

    stats = regime_stats(daily_reg, regime_col="regime_id", ret_col="close_ret_1")
    return daily_reg, stats

# -------- comovement --------

def compute_comovement(daily_en: pd.DataFrame, weekly_en: pd.DataFrame):
    al = build_alignment_frame(
        daily_en, weekly_en,
        on="date", low_cols=["close_ema_21_d1"], high_cols=["close_ema_21_d1"]
    ).rename(columns={"close_ema_21_d1": "d_slope", "close_ema_21_d1_w": "w_slope"})
    al, pct = sign_agreement(al, "d_slope", "w_slope", out_col="agree")
    al = rolling_agreement(al, "d_slope", "w_slope", window=63)
    return al, pct

# -------- main --------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to BTC CSV (CoinMarketCap export).")
    ap.add_argument("--outdir", default="", help="Optional directory to save artifacts.")
    ap.add_argument("--check", nargs="*", help="Optional UTC dates to boundary-check, e.g. 2015-01-01 2015-02-01")
    args = ap.parse_args(argv)

    df = load_clean_csv(args.csv)
    daily, weekly, monthly = build_timeframes(df)
    daily_en, weekly_en, monthly_en = enrich_all(daily, weekly, monthly)

    print_ema21_agreement(daily_en, weekly_en)

    if args.check:
        boundary_check(daily, weekly, monthly, args.check)

    daily_reg, stats = compute_regimes(daily_en)
    print(stats.head())

    al, pct = compute_comovement(daily_en, weekly_en)

    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)
        daily_en.to_parquet(os.path.join(args.outdir, "daily_en.parquet"), index=False)
        weekly_en.to_parquet(os.path.join(args.outdir, "weekly_en.parquet"), index=False)
        monthly_en.to_parquet(os.path.join(args.outdir, "monthly_en.parquet"), index=False)
        daily_reg.to_parquet(os.path.join(args.outdir, "daily_regimes.parquet"), index=False)
        stats.to_csv(os.path.join(args.outdir, "regime_stats.csv"), index=False)
        al.to_parquet(os.path.join(args.outdir, "alignment.parquet"), index=False)
        print(f"Saved outputs to: {args.outdir}")
