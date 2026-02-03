# -*- coding: utf-8 -*-
"""
Spyder-friendly interactive menu for ta_lab2.
- Loads CSV and prepares DF once (visible in Variable Explorer).
- Each action exports results to GLOBALS so you can inspect them.
- Plots render in Spyder's Plots pane.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

# Make 'src' importable if running from source
HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

# Package imports
from ta_lab2.pipelines.btc_pipeline import run_btc_pipeline
from ta_lab2.features.calendar import expand_datetime_features_inplace
from ta_lab2.features.returns import b2t_pct_delta, b2t_log_delta
from ta_lab2.features.ema import add_ema_columns
from ta_lab2.features.segments import build_flip_segments
from ta_lab2.utils.cache import disk_cache
from ta_lab2.features.resample import resample_many, seasonal_summary

# --- Spyder niceties ---
matplotlib.rcParams["figure.dpi"] = 110
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 50)


# =========================
# Helpers
# =========================
def _find_default_csv() -> str | None:
    for p in [
        "data/btc.csv",
        "data/BTC.csv",
        "data/btcusd.csv",
        "data/btc_usd.csv",
        "btc.csv",
    ]:
        if (HERE / p).exists():
            return str(HERE / p)
    for pat in ("data/*btc*.csv", "data/*.csv", "*.csv"):
        for p in (HERE).glob(pat):
            return str(p)
    return None


def _ensure_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    ts = (
        "timestamp"
        if "timestamp" in d.columns
        else next((c for c in d.columns if "time" in c or "date" in c), d.columns[0])
    )
    if ts != "timestamp":
        d = d.rename(columns={ts: "timestamp"})
    expand_datetime_features_inplace(d, "timestamp")
    if all(k in d.columns for k in ("open", "high", "low", "close")):
        d["close-open"] = d["close"].astype(float) - d["open"].astype(float)
        d["range"] = d["high"].astype(float) - d["low"].astype(float)
        b2t_pct_delta(
            d,
            cols=["open", "high", "low", "close", "close-open"],
            extra_cols=["range"],
            round_places=6,
            direction="newest_top",
            open_col="open",
            close_col="close",
        )
        b2t_log_delta(
            d,
            cols=["open", "high", "low", "close", "close-open"],
            extra_cols=["range"],
            prefix="_log_delta",
            round_places=6,
            add_intraday=True,
            open_col="open",
            close_col="close",
        )
        add_ema_columns(d, fields=["close"], periods=[21, 50, 90, 100, 180, 200, 270])
    return d


def _month_key(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True, errors="coerce").dt.to_period("M").astype(str)


def _show(fig):
    plt.tight_layout()
    plt.show()


# =========================
# Actions (each exports a GLOBAL)
# =========================
def monthly_returns(DF: pd.DataFrame):
    key = _month_key(DF["timestamp"])
    grp = DF.groupby(key, sort=False)
    arith = (grp["close"].last() / grp["close"].first() - 1.0).rename("arith_ret")
    daily_rel = DF["close_pct_delta"].fillna(0).add(1.0)
    geo = grp.apply(lambda g: (daily_rel.loc[g.index].prod() - 1.0)).rename("geo_ret")
    harm_rel = grp.apply(
        lambda g: len(g) / np.sum(1.0 / daily_rel.loc[g.index].clip(lower=1e-9))
    )
    harm = (harm_rel - 1.0).rename("harm_ret")
    out = pd.concat([arith, geo, harm], axis=1)

    # plot last 18 months (arith)
    fig, ax = plt.subplots(figsize=(14, 5))
    out["arith_ret"].tail(18).plot(
        kind="bar", ax=ax, title="Monthly Arithmetic Returns (last 18)"
    )
    ax.set_ylabel("return")
    _show(fig)

    globals()["MONTHLY_RET"] = out
    print("\nMONTHLY_RET ready (Variable Explorer).")
    return out


def rolling_compare_returns(DF: pd.DataFrame, window=90):
    pr = DF["close"].astype(float)
    pct = pr.pct_change()
    arith = pct.rolling(window).mean().rename(f"arith_{window}")
    geo = (
        pct.add(1).rolling(window).apply(np.prod, raw=True) ** (1.0 / window) - 1.0
    ).rename(f"geo_{window}")
    rel = pct.add(1).clip(lower=1e-9)
    harm = (
        window
        / rel.rolling(window).apply(
            lambda a: np.sum(1.0 / np.maximum(a, 1e-9)), raw=True
        )
        - 1.0
    ).rename(f"harm_{window}")
    dm = pd.concat([arith, geo, harm], axis=1)

    fig, ax = plt.subplots(figsize=(14, 6))
    dm.tail(1000).plot(
        ax=ax,
        lw=1.1,
        title=f"Rolling daily averages ({window}) — arithmetic vs geometric vs harmonic",
    )
    ax.set_ylabel("avg daily return")
    _show(fig)

    globals()["ROLLING_RET"] = dm
    print("\nROLLING_RET ready.")
    return dm


def comovement_daily_vs_weekly(DF: pd.DataFrame):
    z = DF.sort_values("timestamp").set_index("timestamp")
    # daily EMAs (90/180/270) on daily resample
    daily = z["close"].resample("D").last().dropna()
    d_ema = {
        90: daily.ewm(alpha=2 / (90 + 1), adjust=False).mean().reindex(z.index).ffill(),
        180: daily.ewm(alpha=2 / (180 + 1), adjust=False)
        .mean()
        .reindex(z.index)
        .ffill(),
        270: daily.ewm(alpha=2 / (270 + 1), adjust=False)
        .mean()
        .reindex(z.index)
        .ffill(),
    }
    # weekly EMAs (25/35/45) on weekly resample
    weekly = z["close"].resample("W").last().dropna()
    w_ema = {
        25: weekly.ewm(alpha=2 / (25 + 1), adjust=False)
        .mean()
        .reindex(z.index)
        .ffill(),
        35: weekly.ewm(alpha=2 / (35 + 1), adjust=False)
        .mean()
        .reindex(z.index)
        .ffill(),
        45: weekly.ewm(alpha=2 / (45 + 1), adjust=False)
        .mean()
        .reindex(z.index)
        .ffill(),
    }
    dfc = pd.DataFrame(
        {
            "d_ema_90": d_ema[90],
            "d_ema_180": d_ema[180],
            "d_ema_270": d_ema[270],
            "w_ema_25": w_ema[25],
            "w_ema_35": w_ema[35],
            "w_ema_45": w_ema[45],
            "close": z["close"],
        }
    ).dropna()

    for c in ["d_ema_90", "d_ema_180", "d_ema_270", "w_ema_25", "w_ema_35", "w_ema_45"]:
        dfc[f"{c}_slope"] = dfc[c].astype(float).diff()

    dfc["daily_all_up"] = (
        (dfc["d_ema_90_slope"] > 0)
        & (dfc["d_ema_180_slope"] > 0)
        & (dfc["d_ema_270_slope"] > 0)
    )
    dfc["weekly_all_up"] = (
        (dfc["w_ema_25_slope"] > 0)
        & (dfc["w_ema_35_slope"] > 0)
        & (dfc["w_ema_45_slope"] > 0)
    )
    dfc["agree"] = (dfc["daily_all_up"] == dfc["weekly_all_up"]).astype(int)
    agree_pct = 100.0 * dfc["agree"].mean()
    print(f"Daily(90/180/270) vs Weekly(25/35/45) ALL_UP agreement: {agree_pct:.2f}%")

    dd = dfc.tail(1000)
    fig, ax = plt.subplots(figsize=(14, 6))
    dd["close"].plot(
        ax=ax,
        lw=1.2,
        title="Close with Daily vs Weekly EMA regime agreement (last 1000)",
    )
    (dd["daily_all_up"].astype(int) * dd["close"].rolling(10).mean()).plot(
        ax=ax, alpha=0.35
    )
    (dd["weekly_all_up"].astype(int) * dd["close"].rolling(10).mean()).plot(
        ax=ax, alpha=0.35
    )
    ax.legend(["close", "daily_all_up proxy", "weekly_all_up proxy"])
    _show(fig)

    globals()["COMOVEMENT"] = dfc
    return agree_pct, dfc


def flip_segments_quick(DF: pd.DataFrame):
    segs = build_flip_segments(
        DF,
        base_cols=("close",),
        periods=(21, 50, 100, 200),
        direction="newest_top",
        scale="bps",
        date_col="timestamp",
        ema_name_fmt="{field}_ema_{period}",
    )
    if isinstance(segs, tuple):
        segments_df = segs[0]
    else:
        segments_df = segs
    print("Segments:", len(segments_df))
    globals()["SEGMENTS"] = segments_df
    return segments_df


def full_pipeline_summary(csv_path: str, save_artifacts: bool = True):
    out = run_btc_pipeline(csv_path, config=None)
    print("Pipeline summary:", out.get("summary"))
    if save_artifacts:
        Path("artifacts").mkdir(exist_ok=True)
        try:
            out["data"].to_parquet("artifacts/btc.parquet")
        except Exception:
            out["data"].to_csv("artifacts/btc.csv", index=False)
        print("Saved artifacts/btc.parquet (or .csv)")
    globals()["PIPELINE_OUT"] = out
    return out


# =========================
# Boot once, then menu
# =========================
def _boot():
    csv = _find_default_csv()
    if not csv:
        raise FileNotFoundError(
            "No input CSV found. Drop one at data/btc.csv or adjust _find_default_csv()."
        )
    raw = pd.read_csv(csv)
    df = _ensure_features(raw)
    globals()["DF"] = df  # expose to Variable Explorer
    print(
        f"DF ready, shape={df.shape}. Try monthly_returns(DF), rolling_compare_returns(DF, 90), comovement_daily_vs_weekly(DF), flip_segments_quick(DF), full_pipeline_summary(csv)."
    )
    return csv, df


if __name__ == "__main__":
    CSV_PATH, DF = _boot()

    # Simple text menu (optional; or just call functions directly in the console)
    while True:
        print("\n=== ta_lab2 (Spyder) ===")
        print("1) Monthly returns table + bar")
        print("2) Rolling arithmetic vs geometric vs harmonic (ask window)")
        print("3) Comovement: Daily(90/180/270) vs Weekly(25/35/45)")
        print("4) Flip segments (quick)")
        print("5) Full pipeline summary (save artifacts)")
        print("0) Exit")
        choice = input("Choose: ").strip()
        if choice == "1":
            monthly_returns(DF)
        elif choice == "2":
            try:
                w = int(input("Window (e.g., 90): ").strip() or "90")
            except Exception:
                w = 90
            rolling_compare_returns(DF, window=w)
        elif choice == "3":
            comovement_daily_vs_weekly(DF)
        elif choice == "4":
            flip_segments_quick(DF)
        elif choice == "5":
            full_pipeline_summary(CSV_PATH, save_artifacts=True)
        elif choice == "0":
            break
        else:
            print("Invalid.")


def comovement_menu(DF):
    d_per = [
        int(x) for x in input("Daily EMA periods (comma): ").split(",")
    ]  # e.g., 90,180,270
    w_per = [
        int(x) for x in input("Weekly EMA periods (comma): ").split(",")
    ]  # e.g., 25,35,45

    def _compute(d_periods, w_periods):
        # build EMAs from daily/weekly resamples (use your EMA bank if present)
        # compute diffs, signs, agreement%
        return {"agree_pct": agree, "table": dfc}

    res = disk_cache(
        "comovement_v2", _compute, d_periods=sorted(d_per), w_periods=sorted(w_per)
    )
    globals()["COMOVEMENT"] = res["table"]
    print(f"Agreement: {res['agree_pct']:.2f}%")
    res["table"].tail(1000)["close"].plot(figsize=(12, 5))
    plt.show()


# 1) load your daily input (CSV or artifacts/btc.parquet)
src_csv = Path("data/btc.csv")
if src_csv.exists():
    DF_DAILY = pd.read_csv(src_csv)
else:
    DF_DAILY = pd.read_parquet("artifacts/btc.parquet")

# 2) define the exact bins you want (calendar-day based)
FREQS = [
    "2D",
    "3D",
    "4D",
    "5D",
    "10D",
    "25D",
    "45D",  # calendar-day bins
    "W",
    "2W",
    "3W",  # weeks (Sunday-end)
    "W-FRI",  # market-friendly week
    "M",
    "2M",
    "3M",
    "6M",
    "A",  # month & annual (‘A’ ~ 1Yr)
]
# (Optional) business-day equivalents if you want “trading bar” versions:
FREQS_B = ["5B", "10B", "20B"]  # 5 business days ≈ trading week, etc.

# 3) build and persist
FRAMES = resample_many(DF_DAILY, FREQS, outdir="artifacts/frames", overwrite=True)
FRAMES_B = resample_many(DF_DAILY, FREQS_B, outdir="artifacts/frames_b", overwrite=True)

# 4) inspect
FRAMES["1M"].head()  # monthly OHLCV with calendar fields attached
FRAMES["W-FRI"].tail(3)  # market-aligned weekly
FRAMES["25D"].tail(3)  # 25-calendar-day bars

# 5) seasonal summaries on the original daily (or any frame)
SEASON_RET = seasonal_summary(DF_DAILY, price_col="close", ret_kind="arith")
SEASON_RET_G = seasonal_summary(DF_DAILY, price_col="close", ret_kind="geom")
