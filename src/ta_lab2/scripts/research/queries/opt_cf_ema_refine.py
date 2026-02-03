# src/ta_lab2/research/queries/opt_cf_ema_refine.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, re, pandas as pd

repo_src = r"C:\Users\asafi\Downloads\ta_lab2\src"
if repo_src not in sys.path:
    sys.path.insert(0, repo_src)

from ta_lab2.backtests import CostModel
from ta_lab2.backtests.orchestrator import run_multi_strategy
from ta_lab2.backtests.splitters import fixed_date_splits

CSV = r"C:\Users\asafi\Downloads\ta_lab2\data\Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
COARSE = r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\opt_cf_ema_coarse.csv"
OUT2 = r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\opt_cf_ema_refined.csv"
START, END = "2017-01-01", "2024-12-30"
FREQ_PER_YEAR = 365


def _norm_cols(df):
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", c.strip().lower()) for c in df.columns]
    return df


def load_df(p):
    d = pd.read_csv(p)
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


def ensure_ema(df, span):
    col = f"ema_{span}"
    if col not in df:
        df[col] = df["close"].ewm(span=span, adjust=False).mean()


def refine_ranges(tops, f_pad=10, s_pad=20, f_min=5, f_max=200, s_min=10, s_max=300):
    fset, sset = set(), set()
    for f_name, s_name in tops:
        f = int(str(f_name).split("_")[-1])
        s = int(str(s_name).split("_")[-1])
        fset.update(range(max(f_min, f - f_pad), min(f_max, f + f_pad) + 1))
        sset.update(range(max(s_min, s - s_pad), min(s_max, s + s_pad) + 1))
    return sorted(fset), sorted(sset)


def build_grid(fasts, slows, delta=5):
    return [
        {"fast_ema": f"ema_{f}", "slow_ema": f"ema_{s}"}
        for f in fasts
        for s in slows
        if s >= f + delta
    ]


def main():
    coarse = pd.read_csv(COARSE)
    # grab top-5
    tops = (
        coarse.sort_values(["mar", "sharpe", "cagr"], ascending=[False, False, False])
        .head(5)[["p_fast_ema", "p_slow_ema"]]
        .values.tolist()
    )

    df = load_df(CSV).loc[START:END].copy()
    fine_f, fine_s = refine_ranges(tops, f_pad=10, s_pad=20)
    for span in set(fine_f + fine_s):
        ensure_ema(df, span)

    strategies = {"ema_trend": build_grid(fine_f, fine_s, delta=5)}
    splits = fixed_date_splits([(START, END)], prefix="REFINE")
    cost = CostModel(fee_bps=5, slippage_bps=5)

    mr = run_multi_strategy(
        df=df,
        strategies=strategies,
        splits=splits,
        cost=cost,
        price_col="close",
        freq_per_year=FREQ_PER_YEAR,
    )

    res = mr.results.sort_values(
        ["mar", "sharpe", "cagr"], ascending=[False, False, False]
    )
    res.to_csv(OUT2, index=False)
    print("Saved refined leaderboard:", OUT2)
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
    )


if __name__ == "__main__":
    main()
