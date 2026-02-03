# -*- coding: utf-8 -*-
"""
Genesis-compatible runner that reproduces df2 updates, plots, and flip/regime stats.

Usage (Spyder):
    F5  (auto-discovers CSV in data/btc.csv, btc.csv, etc.)

Usage (terminal):
    python run_btc_genesis.py --csv data/btc.csv
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Make 'src' importable if running from source
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parent
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))

# ---- Package imports ----
from ta_lab2.regimes.comovement import compute_ema_comovement_hierarchy
from ta_lab2.features.segments import build_flip_segments
from ta_lab2.features.ema import (
    add_ema_columns,
    add_ema_d1,
    add_ema_d2,
    prepare_ema_helpers,
)
from ta_lab2.features.returns import b2t_pct_delta, b2t_log_delta
from ta_lab2.features.vol import (
    add_parkinson_vol,
    add_garman_klass_vol,
    add_rogers_satchell_vol,
    add_atr,
    add_logret_stdev_vol,
)
from ta_lab2.features.calendar import expand_datetime_features_inplace


def _find_default_csv() -> str | None:
    candidates = [
        "data/btc.csv",
        "data/BTC.csv",
        "data/btcusd.csv",
        "data/btc_usd.csv",
        "data/Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv",
        "btc.csv",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    for pat in ("data/*btc*.csv", "data/*.csv", "*.csv"):
        for p in REPO_ROOT.glob(pat):
            return str(p)
    return None


# -----------------------------
# Minimal plotting helpers (in-script) to match genesis visuals
# -----------------------------
def _plot_ema_w_slopes_flips(
    df, base_cols, periods, include_slopes=True, include_flips=True
):
    if isinstance(base_cols, str):
        base_cols = [base_cols]
    x = np.arange(len(df))
    for base_col in base_cols:
        for p in periods:
            ema_col = f"{base_col}_ema_{p}"
            d1_bps = f"{ema_col}_d1_bps"
            d1_pct = f"{ema_col}_d1_norm"
            flipcol = f"{ema_col}_flip"

            if ema_col not in df.columns:
                continue

            fig, ax = plt.subplots(figsize=(14, 7))
            ax.plot(
                x,
                df[ema_col].to_numpy(),
                linewidth=2,
                label=f"{base_col.upper()} EMA {p}",
            )
            ax.invert_xaxis()
            ax.set_title(f"{base_col.upper()} EMA {p} + slopes + flips")
            ax.set_xlabel("Bars (newest on right)")
            ax.legend(loc="upper left")

            if include_slopes and (d1_bps in df.columns or d1_pct in df.columns):
                ax2 = ax.twinx()
                if d1_bps in df.columns:
                    ax2.plot(x, df[d1_bps].to_numpy(), alpha=0.6, label="Slope (bps)")
                if d1_pct in df.columns:
                    ax2.plot(x, df[d1_pct].to_numpy(), alpha=0.6, label="Slope (%)")
                ax2.axhline(0, linestyle="--", linewidth=1, alpha=0.8)
                ax2.legend(loc="upper right")

            if include_flips and flipcol in df.columns:
                idx = np.where(df[flipcol].fillna(False).to_numpy())[0]
                if len(idx):
                    ax.scatter(idx, df[ema_col].to_numpy()[idx], s=25, zorder=5)

            plt.tight_layout()
            plt.show()


def _plot_consolidated_emas(
    df, base_col, periods, include_slopes=False, include_flips=False
):
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(14, 7))
    for p in periods:
        ema_col = f"{base_col}_ema_{p}"
        if ema_col in df.columns:
            ax.plot(
                x,
                df[ema_col].to_numpy(),
                linewidth=1.8,
                label=f"{base_col.upper()} EMA {p}",
            )
    ax.invert_xaxis()
    ax.set_title(f"{base_col.upper()} EMAs {', '.join(map(str, periods))}")
    ax.set_xlabel("Bars (newest on right)")
    ax.legend(loc="upper left")

    if include_slopes:
        ax2 = ax.twinx()
        for p in periods:
            bps_col = f"{base_col}_ema_{p}_d1_bps"
            if bps_col in df.columns:
                ax2.plot(
                    x, df[bps_col].to_numpy(), alpha=0.5, label=f"Slope bps (p={p})"
                )
        ax2.axhline(0, linestyle="--", linewidth=1, alpha=0.8)
        ax2.legend(loc="upper right")

    if include_flips:
        for p in periods:
            ema_col = f"{base_col}_ema_{p}"
            flipcol = f"{ema_col}_flip"
            if ema_col in df.columns and flipcol in df.columns:
                idx = np.where(df[flipcol].fillna(False).to_numpy())[0]
                if len(idx):
                    ax.scatter(idx, df[ema_col].to_numpy()[idx], s=20, zorder=5)

    plt.tight_layout()
    plt.show()


def _plot_regime_hitrates(major_stats, sub_stats, sub_mixsum):
    # Expect DataFrames with columns including 'regime_label' and 'hit_rate_pct'
    if isinstance(major_stats, pd.DataFrame) and "hit_rate_pct" in major_stats.columns:
        dfp = major_stats.sort_values("hit_rate_pct", ascending=False).head(25)
        ax = dfp.plot(
            kind="bar",
            x="regime_label",
            y="hit_rate_pct",
            figsize=(12, 5),
            legend=False,
        )
        ax.set_title("Hitrate (next close > 0) by regime — Major")
        ax.set_ylabel("hitrate %")
        plt.tight_layout()
        plt.show()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Genesis-like BTC analysis runner")
    p.add_argument("--csv", dest="csv_path", default=None, help="Path to input CSV")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    csv_path = args.csv_path or _find_default_csv()
    if not csv_path:
        raise FileNotFoundError(
            "No input CSV found. Supply --csv or drop a file at data/btc.csv"
        )

    # ============================
    # 1) Build df2 the 'genesis' way (explicit steps)
    # ============================
    df2 = pd.read_csv(csv_path)
    df2.columns = [str(c).strip().lower() for c in df2.columns]

    # calendar / time expansions (matches genesis loops)
    for col in [c for c in df2.columns if c.startswith("time")]:
        expand_datetime_features_inplace(df2, col)

    # engineered columns
    df2["close-open"] = df2["close"].astype(float) - df2["open"].astype(float)
    df2["range"] = df2["high"].astype(float) - df2["low"].astype(float)

    # returns (pct + log) and realized vol batch
    b2t_pct_delta(
        df2,
        cols=["open", "high", "low", "close", "close-open"],
        extra_cols=["range"],
        round_places=6,
        direction="newest_top",
        open_col="open",
        close_col="close",
    )
    b2t_log_delta(
        df2,
        cols=["open", "high", "low", "close", "close-open"],
        extra_cols=["range"],
        prefix="_log_delta",
        round_places=6,
        add_intraday=True,
        open_col="open",
        close_col="close",
    )

    # logret rolling stdev (genesis)
    add_logret_stdev_vol(
        df2,
        windows=(30, 60, 90),
        logret_cols=[
            "open_log_delta",
            "high_log_delta",
            "low_log_delta",
            "close_log_delta",
            "intraday_log_delta",
        ],
        direction="newest_top",
    )

    # single-bar realized vol estimators (genesis)
    add_parkinson_vol(df2, windows=(30, 60, 90), direction="newest_top")
    add_garman_klass_vol(df2, windows=(30, 60, 90), direction="newest_top")
    add_rogers_satchell_vol(df2, windows=(30, 60, 90), direction="newest_top")

    # ATR
    add_atr(df2, atr_len=14, method="wilder", direction="newest_top")

    # EMAs + slopes + helpers (genesis targets)
    ema_periods = [21, 50, 100, 200]
    ema_fields = ["open", "high", "low", "close"]
    add_ema_columns(df2, ema_fields, ema_periods)
    add_ema_d1(df2, ema_fields, ema_periods, round_places=6, direction="newest_top")
    add_ema_d2(df2, ema_fields, ema_periods, round_places=6, direction="newest_top")
    prepare_ema_helpers(
        df2,
        ema_fields,
        ema_periods,
        direction="newest_top",
        overwrite=False,
        scale="bps",
    )

    print("Rows:", len(df2))
    for f in ema_fields:
        ema_cols = [c for c in df2.columns if c.startswith(f + "_ema_")]
        print(f"{f}: {ema_cols[:8]}{' ...' if len(ema_cols) > 8 else ''}")

    # ============================
    # 2) Flip segments (genesis)
    # ============================
    segments_df, flip_summary, flip_summary_by_year = build_flip_segments(
        df2,
        base_cols=("close",),
        periods=ema_periods,
        direction="newest_top",
        scale="bps",
        date_col="timestamp" if "timestamp" in df2.columns else None,
        ema_name_fmt="{field}_ema_{period}",
    )

    print("segments_df rows:", len(segments_df))
    if isinstance(flip_summary, pd.DataFrame):
        print(flip_summary.head(10))
    if (
        isinstance(flip_summary_by_year, pd.DataFrame)
        and not flip_summary_by_year.empty
    ):
        print("\n=== Flip segment summary by year ===")
        print(
            flip_summary_by_year.sort_values(["year", "field", "ema_period"]).head(40)
        )

    # ============================
    # 3) Regime hierarchy (genesis)
    # ============================
    major_stats, sub_stats, sub_stats_mixsum = compute_ema_comovement_hierarchy(
        df2,
        periods=ema_periods,
        close_col="close",
        direction="newest_top",
    )
    print("\n=== Major categories ===")
    try:
        print(major_stats.sort_values("count", ascending=False).head(10))
    except Exception:
        print(major_stats.head(10))

    print("\n=== Subcategories ===")
    try:
        print(sub_stats.sort_values("count", ascending=False).head(10))
    except Exception:
        print(sub_stats.head(10))

    print("\n=== Subcategories + MIXED (sum) ===")
    try:
        print(sub_stats_mixsum.sort_values("count", ascending=False).head(10))
    except Exception:
        print(sub_stats_mixsum.head(10))

    # ============================
    # 4) Plots to match genesis visuals
    # ============================
    _plot_ema_w_slopes_flips(
        df2,
        base_cols="close",
        periods=ema_periods,
        include_slopes=True,
        include_flips=True,
    )
    _plot_consolidated_emas(
        df2,
        base_col="close",
        periods=ema_periods,
        include_slopes=False,
        include_flips=False,
    )
    _plot_regime_hitrates(major_stats, sub_stats, sub_stats_mixsum)

    # Save a small sample like the original script
    df2_top201 = df2.head(201)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_name = f"df2_{ts}.csv"
    df2_top201.to_csv(out_name, index=False)
    print("Saved file as:", out_name)

    # Print the same tiny header the standard runner shows
    ts_col = "timestamp" if "timestamp" in df2.columns else df2.columns[0]
    tmin = pd.to_datetime(df2[ts_col].min())
    tmax = pd.to_datetime(df2[ts_col].max())
    print(f"\nLoaded rows: {len(df2)}")
    print(f"Date range: {tmin} → {tmax}")
    print(
        f"Columns now: {list(df2.columns)[:12]} ... (+{max(0, len(df2.columns)-12)} more)"
    )

    return df2, segments_df, major_stats, sub_stats, sub_stats_mixsum


if __name__ == "__main__":
    main()
