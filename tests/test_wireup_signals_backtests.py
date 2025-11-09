# C:\Users\asafi\Downloads\ta_lab2\tests\test_wireup_signals_backtests.py
# -*- coding: utf-8 -*-
"""
Wire-up test: signals ↔ backtests (vectorbt) integration for ta_lab2.

- Confirms package imports
- Confirms strategy registry exposes ema_trend
- Runs a tiny end-to-end backtest on synthetic data
- Imports research query modules (guarded by if __name__ == "__main__")
"""

from __future__ import annotations
import sys
import numpy as np
import pandas as pd

# Ensure the package (under src/) is importable when running directly
REPO_SRC = r"C:\Users\asafi\Downloads\ta_lab2\src"
if REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)

from ta_lab2.backtests import CostModel
from ta_lab2.backtests.splitters import fixed_date_splits
from ta_lab2.backtests.orchestrator import run_multi_strategy
from ta_lab2.signals.registry import REGISTRY, get_strategy, ensure_for

def _make_synth_df(n_days: int = 400, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(loc=0.001, scale=0.02, size=n_days)
    close = 100 * (1 + steps).cumprod()
    high = close * (1 + rng.uniform(0.0, 0.01, size=n_days))
    low  = close * (1 - rng.uniform(0.0, 0.01, size=n_days))
    open_ = close / (1 + rng.uniform(-0.005, 0.005, size=n_days))
    vol   = rng.integers(1000, 5000, size=n_days)
    idx = pd.date_range("2021-01-01", periods=n_days, freq="D")  # tz-naive
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

def _ensure_ema(df: pd.DataFrame, span: int) -> None:
    col = f"ema_{span}"
    if col not in df:
        df[col] = df["close"].ewm(span=span, adjust=False).mean()

def run_wireup() -> pd.DataFrame:
    df = _make_synth_df()

    splits = fixed_date_splits([
        ("2021-02-01", "2021-06-30"),
        ("2021-07-01", "2021-10-31"),
    ], prefix="WIRE")

    grid = [
        {"fast_ema": "ema_10", "slow_ema": "ema_30"},
        {"fast_ema": "ema_12", "slow_ema": "ema_34"},
    ]

    for params in grid:
        ensure_for("ema_trend", df, params)

    for span in (10, 12, 30, 34):
        _ensure_ema(df, span)

    strategies = {"ema_trend": grid}
    cost = CostModel(fee_bps=5, slippage_bps=5)

    mr = run_multi_strategy(
        df=df,
        strategies=strategies,
        splits=splits,
        cost=cost,
        price_col="close",
        freq_per_year=365,
    )
    return mr.results

def import_research_queries() -> None:
    import ta_lab2.research.queries.run_ema_50_100 as q_run
    import ta_lab2.research.queries.opt_cf_ema as q_coarse
    import ta_lab2.research.queries.opt_cf_ema_refine as q_refine
    import ta_lab2.research.queries.opt_cf_ema_sensitivity as q_sens
    import ta_lab2.research.queries.wf_validate_ema as q_wf
    import ta_lab2.research.queries.opt_cf_generic as q_gen
    _ = (q_run, q_coarse, q_refine, q_sens, q_wf, q_gen)

def test_wireup_end_to_end():
    # Registry sanity
    assert "ema_trend" in REGISTRY, "ema_trend not registered"
    _ = get_strategy("ema_trend")

    # Backtest run
    res = run_wireup()
    assert not res.empty, "Wire-up backtest produced no rows."
    assert res["trades"].ge(0).all(), "Trades should be non-negative."

    # Research imports
    import_research_queries()
