# src/ta_lab2/regimes/data_budget.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional
import pandas as pd


@dataclass(frozen=True)
class DataBudgetContext:
    enabled_layers: Dict[str, bool]
    feature_tier: str  # "full" | "lite"
    bars_by_tf: Dict[str, int]


_MIN_BARS = {
    "L0": 60,  # monthly bars (~5y) for Cycle
    "L1": 52,  # weekly bars (~1y) minimal; 100+ ideal
    "L2": 120,  # daily bars (~6m) minimal; 250+ ideal
    "L3": 300,  # 4H/1H bars (a few months)
    "L4": 1,  # execution can always run
}


def _count(df: Optional[pd.DataFrame]) -> int:
    return int(len(df)) if isinstance(df, pd.DataFrame) else 0


def assess_data_budget(
    *,
    monthly: Optional[pd.DataFrame] = None,
    weekly: Optional[pd.DataFrame] = None,
    daily: Optional[pd.DataFrame] = None,
    intraday: Optional[pd.DataFrame] = None,
    min_bars_overrides: Optional[Dict[str, int]] = None,
) -> DataBudgetContext:
    bars = {
        "M": _count(monthly),
        "W": _count(weekly),
        "D": _count(daily),
        "I": _count(intraday),
    }

    thresholds = dict(_MIN_BARS)
    if min_bars_overrides:
        thresholds.update(min_bars_overrides)

    enabled = {
        "L0": bars["M"] >= thresholds["L0"],
        "L1": bars["W"] >= thresholds["L1"],
        "L2": bars["D"] >= thresholds["L2"],
        "L3": bars["I"] >= thresholds["L3"],
        "L4": True,
    }

    # Feature tier: full if we have comfortable depth across major layers
    full = (
        (bars["W"] >= 100)
        and (bars["D"] >= 250)
        and (bars["M"] >= 60 or not enabled["L0"])
    )
    tier = "full" if full else "lite"

    return DataBudgetContext(enabled_layers=enabled, feature_tier=tier, bars_by_tf=bars)
