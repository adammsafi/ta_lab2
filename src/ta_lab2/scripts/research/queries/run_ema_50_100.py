# src/ta_lab2/research/queries/run_ema_50_100.py
from __future__ import annotations
import sys
import re
import pandas as pd

# ---- Configure paths/dates/capital ----
CSV = r"C:\Users\asafi\Downloads\ta_lab2\data\Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
START, END = "2017-01-01", "2024-12-30"
INITIAL = 10_000.0

# ---- Ensure the package is importable when running directly (Spyder/REPL) ----
repo_src = r"C:\Users\asafi\Downloads\ta_lab2\src"
if repo_src not in sys.path:
    sys.path.insert(0, repo_src)

# Import through the package (with back-compat alias run_strategies)
from ta_lab2.backtests import CostModel, fixed_date_splits, run_strategies


# --------- Robust CSV loading / normalization ---------
def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [re.sub(r"\s+", " ", c.strip().lower()) for c in d.columns]
    return d


def _find_ts_col(cols) -> str:
    for c in ("timestamp", "timeopen", "time open", "date", "timeclose", "time close"):
        if c in cols:
            return c
    for c in cols:
        if ("time" in c) or ("date" in c):
            return c
    raise KeyError(f"No timestamp-like column found. Columns: {list(cols)}")


def _find_close_col(cols) -> str:
    for c in ("close", "close usd", "adj close", "adjusted close"):
        if c in cols:
            return c
    for c in cols:
        if "close" in c:
            return c
    for c in ("price", "last", "last price"):
        if c in cols:
            return c
    raise KeyError(f"No close/price-like column found. Columns: {list(cols)}")


def load_price_df(csv_path: str) -> pd.DataFrame:
    raw = pd.read_csv(csv_path)
    df = _normalize_cols(raw)
    ts_col = _find_ts_col(df.columns)
    px_col = _find_close_col(df.columns)

    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce", utc=False)
    df = df.dropna(subset=[ts_col]).set_index(ts_col).sort_index()

    # **Normalize timezone to tz-naive to avoid slice errors**
    try:
        df.index = df.index.tz_localize(None)
    except Exception:
        # If already tz-naive, this will error; ignore.
        pass

    if px_col != "close":
        df = df.rename(columns={px_col: "close"})

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    return df


# --------- EMA helpers ---------
def ensure_ema(df: pd.DataFrame, span: int, out_col: str) -> None:
    if out_col not in df.columns:
        df[out_col] = df["close"].ewm(span=span, adjust=False).mean()


# --------- Main run ---------
def main():
    df = load_price_df(CSV)

    # compute EMAs if missing
    ensure_ema(df, 50, "ema_50")
    ensure_ema(df, 100, "ema_100")

    # restrict to requested window (now tz-naive, so slicing won't error)
    df = df.loc[START:END].copy()

    # single fixed param (no sweep); ema_trend auto-disables filters if cols absent
    strategies = {"ema_trend": [{"fast_ema": "ema_50", "slow_ema": "ema_100"}]}
    splits = fixed_date_splits([(START, END)], prefix="BTC_DAILY")
    cost = CostModel(fee_bps=5.0, slippage_bps=5.0)

    mr = run_strategies(
        df=df,
        strategies=strategies,
        splits=splits,
        cost=cost,
        price_col="close",
        freq_per_year=365,
    )

    row = mr.results.iloc[0]
    total_return = float(row["total_return"])
    final_equity = INITIAL * (1.0 + total_return)
    gain = final_equity - INITIAL
    pct = (final_equity / INITIAL - 1.0) * 100.0

    print("=== EMA 50/100 crossover (buy 50>100, sell 100>50) ===")
    print(f"Window: {START} → {END}, fees=0, slippage=0")
    print(f"Initial:  $ {INITIAL:,.2f}")
    print(f"Final:    $ {final_equity:,.2f}")
    print(f"Gain:     $ {gain:,.2f}")
    print(f"Return:     {pct:.2f}%")


if __name__ == "__main__":
    main()
