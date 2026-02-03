# src/ta_lab2/research/queries/wf_validate_ema.py
# -*- coding: utf-8 -*-
"""
Walk-forward validation for EMA crossover picked from the refined leaderboard.

Assumptions:
- You already ran the coarse + refined scans.
- The outputs directory already exists (we do NOT create folders here).
- opt_cf_ema_refined.csv exists at the configured path.
"""
from __future__ import annotations
import sys
import re
import pandas as pd

# ---- Repo import path (adjust if your repo lives elsewhere) ----
repo_src = r"C:\Users\asafi\Downloads\ta_lab2\src"
if repo_src not in sys.path:
    sys.path.insert(0, repo_src)

from ta_lab2.backtests import CostModel
from ta_lab2.backtests.orchestrator import run_multi_strategy
from ta_lab2.backtests.splitters import Split

# ---- Config ----
CSV = r"C:\Users\asafi\Downloads\ta_lab2\data\Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
REFINED = r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\opt_cf_ema_refined.csv"
OUT = r"C:\Users\asafi\Downloads\ta_lab2\research\outputs\wf_ema_results.csv"

START, END = "2017-01-01", "2024-12-30"
FREQ_PER_YEAR = 365  # BTC daily; change for intraday


# ---- Utils ----
def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", c.strip().lower()) for c in df.columns]
    return df


def load_df(path: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    d = _norm_cols(d)

    # pick a timestamp column
    ts = next(
        c
        for c in d.columns
        if c
        in ("timestamp", "timeopen", "time open", "date", "timeclose", "time close")
    )
    # pick a close column
    px = (
        "close"
        if "close" in d.columns
        else next(c for c in d.columns if "close" in c or c in ("price", "last"))
    )

    d[ts] = pd.to_datetime(d[ts], errors="coerce")
    d = d.dropna(subset=[ts]).set_index(ts).sort_index()

    # drop tz info if present
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


def rolling_train_test_splits(
    start: str,
    end: str,
    train_days: int = 730,  # ~24 months
    test_days: int = 182,  # ~6 months
    step_days: int = 182,  # step forward ~6 months
):
    """Yield (TRAIN_i, TEST_i) Split pairs from [start, end]."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    cur = s
    i = 0
    out = []
    while True:
        tr_start = cur
        tr_end = min(tr_start + pd.Timedelta(days=train_days - 1), e)
        te_start = tr_end + pd.Timedelta(days=1)
        te_end = min(te_start + pd.Timedelta(days=test_days - 1), e)

        if te_start > e or tr_start >= tr_end:
            break

        out.append(
            (
                Split(name=f"TRAIN_{i:02d}", start=tr_start, end=tr_end),
                Split(name=f"TEST_{i:02d}", start=te_start, end=te_end),
            )
        )

        cur = cur + pd.Timedelta(days=step_days)
        i += 1
        if te_end >= e:
            break
    return out


# ---- Main ----
def main():
    # Load dataset and clamp to window
    df = load_df(CSV).loc[START:END].copy()

    # Load refined leaderboard and pick the *single best* pair
    ref = pd.read_csv(REFINED)
    if ref.empty:
        raise ValueError(f"No rows in {REFINED}. Run the refine step first.")

    ref = ref.sort_values(
        ["mar", "sharpe", "cagr"], ascending=[False, False, False]
    ).head(1)
    f_name = ref["p_fast_ema"].iloc[0]
    s_name = ref["p_slow_ema"].iloc[0]
    f = int(str(f_name).split("_")[-1])
    s = int(str(s_name).split("_")[-1])

    # Ensure the EMAs we need exist
    ensure_ema(df, f)
    ensure_ema(df, s)

    # One strategy: the chosen EMA pair
    strategies = {"ema_trend": [{"fast_ema": f"ema_{f}", "slow_ema": f"ema_{s}"}]}
    cost = CostModel(fee_bps=5, slippage_bps=5)

    # Build rolling train/test pairs; evaluate on TEST windows only
    pairs = rolling_train_test_splits(
        START, END, train_days=730, test_days=182, step_days=182
    )

    rows = []
    for tr_split, te_split in pairs:
        mr = run_multi_strategy(
            df=df,
            strategies=strategies,
            splits=[te_split],  # evaluate out-of-sample
            cost=cost,
            price_col="close",
            freq_per_year=FREQ_PER_YEAR,
        )
        r = mr.results.copy()
        r["train_start"], r["train_end"] = tr_split.start, tr_split.end
        r["test_start"], r["test_end"] = te_split.start, te_split.end
        rows.append(r)

    if not rows:
        raise RuntimeError(
            "No walk-forward TEST rows produced; check date ranges and data length."
        )

    out = pd.concat(rows, ignore_index=True).sort_values("test_start")
    out.to_csv(OUT, index=False)

    print("Saved walk-forward tests:", OUT)
    cols = [
        "split",
        "p_fast_ema",
        "p_slow_ema",
        "test_start",
        "test_end",
        "trades",
        "total_return",
        "cagr",
        "mdd",
        "mar",
        "sharpe",
    ]
    print(out[cols])

    # Quick OOS sanity stats
    means = (
        out[["total_return", "cagr", "mdd", "mar", "sharpe"]]
        .mean(numeric_only=True)
        .to_dict()
    )
    print("\nOOS means:", means)


if __name__ == "__main__":
    main()
