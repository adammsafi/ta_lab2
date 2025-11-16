# src/ta_lab2/research/queries/opt_cf_ema_sensitivity.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, re, os
import pandas as pd

# --- repo import path ---
repo_src = r"C:\Users\asafi\Downloads\ta_lab2\src"
if repo_src not in sys.path:
    sys.path.insert(0, repo_src)

from ta_lab2.backtests import CostModel
from ta_lab2.backtests.orchestrator import run_multi_strategy
from ta_lab2.backtests.splitters import fixed_date_splits

# --- config (defaults + optional env overrides) ---
DEFAULT_CSV = r"C:\Users\asafi\Downloads\ta_lab2\data\Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
DEFAULT_REFINED = r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\opt_cf_ema_refined.csv"
DEFAULT_OUT = r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\opt_cf_ema_sensitivity.csv"

# Allow overriding paths from the environment, but keep your current defaults
CSV = os.getenv("TA_LAB2_OPT_CF_EMA_SENS_CSV", DEFAULT_CSV)
REFINED = os.getenv("TA_LAB2_OPT_CF_EMA_SENS_REFINED", DEFAULT_REFINED)
OUT = os.getenv("TA_LAB2_OPT_CF_EMA_SENS_OUT", DEFAULT_OUT)

START, END = "2017-01-01", "2024-12-30"
FREQ_PER_YEAR = 365

# Only create a directory if there *is* a directory component
_out_dir = os.path.dirname(OUT)
if _out_dir:
    os.makedirs(_out_dir, exist_ok=True)


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", c.strip().lower()) for c in df.columns]
    return df


def load_df(p: str) -> pd.DataFrame:
    d = pd.read_csv(p)
    d = _norm_cols(d)
    ts = next(
        c
        for c in d.columns
        if c
        in (
            "timestamp",
            "timeopen",
            "time open",
            "date",
            "timeclose",
            "time close",
        )
    )
    px = (
        "close"
        if "close" in d.columns
        else next(
            c
            for c in d.columns
            if "close" in c or c in ("price", "last")
        )
    )
    d[ts] = pd.to_datetime(d[ts], errors="coerce")
    d = d.dropna(subset=[ts]).set_index(ts).sort_index()
    try:
        d.index = d.index.tz_localize(None)
    except Exception:
        pass
    if px != "close":
        d = d.rename(columns={px: "close"})
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    return d.dropna(subset=["close"])


def ensure_ema(df: pd.DataFrame, span: int) -> None:
    col = f"ema_{span}"
    if col not in df:
        df[col] = df["close"].ewm(span=span, adjust=False).mean()


def build_grid(f: int, s: int, f_pad=10, s_pad=20, delta=5):
    fasts = [x for x in range(max(5, f - f_pad), f + f_pad + 1)]
    slows = [x for x in range(max(f + delta, s - s_pad), s + s_pad + 1)]
    return [
        {"fast_ema": f"ema_{fi}", "slow_ema": f"ema_{si}"}
        for fi in fasts
        for si in slows
        if si >= fi + delta
    ]


def main():
    ref = pd.read_csv(REFINED)
    if ref.empty:
        raise ValueError(
            f"No rows in {REFINED}. Run the refine step first."
        )

    ref = ref.sort_values(
        ["mar", "sharpe", "cagr"],
        ascending=[False, False, False],
    ).head(1)
    f = int(str(ref["p_fast_ema"].iloc[0]).split("_")[-1])
    s = int(str(ref["p_slow_ema"].iloc[0]).split("_")[-1])

    df = load_df(CSV).loc[START:END].copy()

    # Precompute EMA spans in the sensitivity neighborhood
    spans = set(range(max(5, f - 10), f + 11)).union(
        set(range(max(10, s - 20), s + 21))
    )
    for span in spans:
        ensure_ema(df, span)

    strategies = {
        "ema_trend": build_grid(f, s, f_pad=10, s_pad=20, delta=5)
    }
    splits = fixed_date_splits([(START, END)], prefix="SENS")
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
        ["mar", "sharpe", "cagr"],
        ascending=[False, False, False],
    )
    res.to_csv(OUT, index=False)
    print("Saved sensitivity:", OUT)
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
