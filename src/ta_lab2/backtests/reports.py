"""
Reporting helpers: aggregate tables, simple charts, and file outputs.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

import pandas as pd
import matplotlib.pyplot as plt


def save_table(df: pd.DataFrame, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def equity_plot(equity: pd.Series, title: str = "Equity Curve", out_path: Optional[str | Path] = None):
    plt.figure(figsize=(10, 4))
    equity.plot(lw=1.2)
    plt.title(title)
    plt.xlabel("")
    plt.ylabel("Equity")
    plt.tight_layout()
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(p, dpi=120)
    plt.close()


def leaderboard(results: pd.DataFrame, group_cols: Iterable[str] = ("split",)) -> pd.DataFrame:
    """
    Rank parameter sets inside each split by MAR, then Sharpe, then CAGR.
    Expects columns: ['split','mar','sharpe','cagr', 'trades', ...]
    """
    cols = list(group_cols)
    ranked = (
        results
        .assign(_rank=results.groupby(cols)
                .apply(lambda g: g
                       .sort_values(["mar", "sharpe", "cagr"], ascending=False)
                       .assign(_r=lambda x: range(1, len(x)+1)))
                .reset_index(level=0, drop=True)["_r"])
        .sort_values(cols + ["_rank"])
    )
    return ranked
