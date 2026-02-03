# backtests/orchestrator.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

from .vbt_runner import sweep_grid
from .costs import CostModel
from .splitters import Split

# package-relative import so it works inside ta_lab2
from ..signals.registry import REGISTRY


@dataclass
class MultiResult:
    results: pd.DataFrame  # all strategies merged
    leaders: Dict[str, pd.DataFrame]  # per-strategy leaderboards


def _leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    """Rank rows by MAR, then Sharpe, then CAGR (desc)."""
    cols = ["mar", "sharpe", "cagr"]
    existing = [c for c in cols if c in df.columns]
    if not existing:
        return df
    return df.sort_values(existing, ascending=[False] * len(existing)).reset_index(
        drop=True
    )


def run_multi_strategy(
    df: pd.DataFrame,
    strategies: Mapping[str, Iterable[Mapping[str, Any]]],
    splits: Iterable[Split],
    cost: CostModel,
    price_col: str = "close",
    freq_per_year: int = 365,
) -> MultiResult:
    """
    Orchestrate backtests for multiple strategies.

    Parameters
    ----------
    df : pd.DataFrame
        Price dataframe (indexed by Timestamp) with required columns for each strategy.
    strategies : Mapping[str, Iterable[Mapping[str, Any]]]
        Dict of strategy name -> iterable of parameter dicts.
        Example: {"ema_trend": [{"fast_ema": "ema_50", "slow_ema": "ema_100"}]}
    splits : Iterable[Split]
        Date windows to evaluate.
    cost : CostModel
        Commission/slippage/funding model.
    price_col : str
        Column used as the price series for vectorbt.
    freq_per_year : int
        Trading periods per year for annualized metrics (365 for daily crypto).

    Returns
    -------
    MultiResult
        `results`: tidy table with metrics/params across all strategies & splits.
        `leaders`: per-strategy leaderboards ranked by MAR, then Sharpe, then CAGR.
    """
    frames: List[pd.DataFrame] = []

    for strat_name, grid in strategies.items():
        if strat_name not in REGISTRY:
            raise KeyError(
                f"Strategy '{strat_name}' not found in signals.registry.REGISTRY"
            )

        signal_fn = REGISTRY[strat_name]
        bundle = sweep_grid(
            df=df,
            signal_func=signal_fn,
            param_grid=grid,
            splits=splits,
            cost=cost,
            price_col=price_col,
            freq_per_year=freq_per_year,
        )
        t = bundle.table.copy()
        t.insert(0, "strategy", strat_name)
        frames.append(t)

    # Merge all strategies’ results
    results = pd.concat(frames, ignore_index=True)

    # Build per-strategy leaderboards
    leaders: Dict[str, pd.DataFrame] = {
        name: _leaderboard(results[results["strategy"] == name])
        for name in results["strategy"].unique()
    }

    return MultiResult(results=results, leaders=leaders)


# ---- Back-compat alias (so existing imports keep working) ----
run_strategies = run_multi_strategy
