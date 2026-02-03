# src/ta_lab2/research/queries/opt_cf_generic.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, re, argparse, os
from pathlib import Path
import pandas as pd

repo_src = r"C:\Users\asafi\Downloads\ta_lab2\src"
if repo_src not in sys.path:
    sys.path.insert(0, repo_src)

from ta_lab2.backtests import CostModel
from ta_lab2.backtests.orchestrator import run_multi_strategy
from ta_lab2.backtests.splitters import fixed_date_splits
from ta_lab2.signals.registry import get_strategy


def _norm_cols(df):
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", c.strip().lower()) for c in df.columns]
    return df


def load_df(path):
    d = pd.read_csv(path)
    d = _norm_cols(d)
    ts = next(
        c
        for c in d.columns
        if c
        in ("timestamp", "timeopen", "time open", "date", "timeclose", "time close")
    )
    px = (
        "close"
        if "close" in d.columns
        else next(c for c in d.columns if "close" in c or c in ("price", "last"))
    )
    d[ts] = pd.to_datetime(d[ts], errors="coerce")
    d = d.dropna(subset=[ts]).set_index(ts).sort_index()
    try:
        d.index = d.index.tz_localize(None)
    except:
        pass
    if px != "close":
        d = d.rename(columns={px: "close"})
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    return d.dropna(subset=["close"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to price CSV")
    ap.add_argument(
        "--strategy", default="ema_trend", help="Strategy key from registry"
    )
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--end", default="2024-12-30")
    ap.add_argument(
        "--out",
        default=r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\opt_generic.csv",
    )
    ap.add_argument("--fee_bps", type=float, default=5)
    ap.add_argument("--slip_bps", type=float, default=5)
    ap.add_argument("--freq_per_year", type=int, default=365)
    args = ap.parse_args()

    outdir = Path(args.out).parent
    os.makedirs(outdir, exist_ok=True)

    spec = get_strategy(args.strategy)
    df = load_df(args.csv).loc[args.start : args.end].copy()

    # Precompute features needed for the WHOLE grid cheaply
    grid = spec.grid()
    # Call ensure once per unique requirement pattern (here we just loop)
    for p in grid:
        spec.ensure(df, p)

    # Build splits (single full-window split for coarse scan)
    splits = fixed_date_splits([(args.start, args.end)], prefix="GEN")
    cost = CostModel(fee_bps=args.fee_bps, slippage_bps=args.slip_bps)

    # Orchestrate
    strategies = {args.strategy: grid}
    mr = run_multi_strategy(
        df=df,
        strategies=strategies,
        splits=splits,
        cost=cost,
        price_col="close",
        freq_per_year=args.freq_per_year,
    )

    res = mr.results.sort_values(
        ["mar", "sharpe", "cagr"], ascending=[False, False, False]
    )
    res.to_csv(args.out, index=False)
    print(f"Saved generic leaderboard: {args.out}")
    print(
        res.head(12)[
            [
                "split",
                "p_fast_ema",
                "p_slow_ema",
                "trades",
                "total_return",
                "cagr",
                "mdd",
                "mar",
                "sharpe",
            ]
        ]
        if "p_fast_ema" in res.columns
        else res.head(12)[
            ["split", "trades", "total_return", "cagr", "mdd", "mar", "sharpe"]
        ]
    )


if __name__ == "__main__":
    main()
