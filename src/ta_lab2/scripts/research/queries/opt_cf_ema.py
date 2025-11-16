# src/ta_lab2/research/queries/opt_cf_ema.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, re, pandas as pd

# --- repo import path ---
repo_src = r"C:\Users\asafi\Downloads\ta_lab2\src"
if repo_src not in sys.path: sys.path.insert(0, repo_src)

from ta_lab2.backtests import CostModel
from ta_lab2.backtests.orchestrator import run_multi_strategy
from ta_lab2.backtests.splitters import fixed_date_splits

CSV   = r"C:\Users\asafi\Downloads\ta_lab2\data\Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
START, END = "2017-01-01", "2024-12-30"
OUT1  = r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\opt_cf_ema_coarse.csv"
FREQ_PER_YEAR = 365

def _norm_cols(df):
    df = df.copy()
    df.columns = [re.sub(r"\s+"," ",c.strip().lower()) for c in df.columns]
    return df

def load_df(p):
    d = pd.read_csv(p)
    d = _norm_cols(d)
    ts = next(c for c in d.columns if c in ("timestamp","timeopen","time open","date","timeclose","time close"))
    px = "close" if "close" in d.columns else next(c for c in d.columns if "close" in c or c in ("price","last"))
    d[ts] = pd.to_datetime(d[ts], errors="coerce")
    d = d.dropna(subset=[ts]).set_index(ts).sort_index()
    try: d.index = d.index.tz_localize(None)
    except: pass
    if px != "close":
        d = d.rename(columns={px:"close"})
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    return d.dropna(subset=["close"])

def ensure_ema(df, span):
    col = f"ema_{span}"
    if col not in df:
        df[col] = df["close"].ewm(span=span, adjust=False).mean()

def build_grid(fasts, slows, delta=5):
    # delta is min gap to avoid nearly identical EMAs
    return [{"fast_ema": f"ema_{f}", "slow_ema": f"ema_{s}"} for f in fasts for s in slows if s >= f + delta]

def main():
    df = load_df(CSV).loc[START:END].copy()

    # coarse ranges
    fasts = list(range(5, 61, 5))        # 5,10,...,60
    slows = [80, 100, 120, 150, 200]

    # precompute only what we need
    for s in set(fasts + slows):
        ensure_ema(df, s)

    strategies = {
        "ema_trend": build_grid(fasts, slows, delta=5)
    }

    # single full-window split for coarse scan
    splits = fixed_date_splits([(START, END)], prefix="COARSE")
    cost = CostModel(fee_bps=5, slippage_bps=5)

    mr = run_multi_strategy(
        df=df,
        strategies=strategies,
        splits=splits,
        cost=cost,
        price_col="close",
        freq_per_year=FREQ_PER_YEAR,
    )

    res = mr.results.sort_values(["mar","sharpe","cagr"], ascending=[False,False,False])
    res.to_csv(OUT1, index=False)
    print("Saved coarse leaderboard:", OUT1)
    print(res.head(12)[["split","p_fast_ema","p_slow_ema","trades","total_return","cagr","mdd","mar","sharpe"]])

if __name__ == "__main__":
    main()
