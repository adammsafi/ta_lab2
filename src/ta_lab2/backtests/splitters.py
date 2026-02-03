"""
Time-series split helpers (expanding and walk-forward).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, List, Tuple
import pandas as pd


@dataclass
class Split:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


def expanding_walk_forward(
    index: pd.DatetimeIndex,
    insample_years: int,
    oos_years: int,
) -> List[Split]:
    """
    Build expanding-window walk-forward splits by calendar years.
    Example: IS=2016-2019, OOS=2020; then IS=2016-2020, OOS=2021; etc.
    """
    years = sorted(set(index.year))
    splits: List[Split] = []
    if len(years) < (insample_years + oos_years):
        return splits

    for cut in range(insample_years, len(years) - oos_years + 1):
        is_start = pd.Timestamp(f"{years[0]}-01-01")
        is_end = pd.Timestamp(f"{years[cut-1]}-12-31")
        oos_end = pd.Timestamp(f"{years[cut+oos_years-1]}-12-31")
        splits.append(
            Split(
                name=f"IS_{years[0]}-{years[cut-1]}__OOS_{years[cut]}-{years[cut+oos_years-1]}",
                start=is_start,
                end=oos_end,
            )
        )
    return splits


def fixed_date_splits(
    windows: Iterable[Tuple[str, str]],
    prefix: str = "SPLIT",
) -> List[Split]:
    """Build splits from explicit date windows (inclusive)."""
    out: List[Split] = []
    for i, (start, end) in enumerate(windows, 1):
        out.append(
            Split(
                name=f"{prefix}_{i}", start=pd.Timestamp(start), end=pd.Timestamp(end)
            )
        )
    return out
