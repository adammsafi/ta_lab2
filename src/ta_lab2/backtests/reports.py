from __future__ import annotations

"""
Reporting helpers: aggregate tables, simple charts, and file outputs.

Note: matplotlib is OPTIONAL.
- Importing this module must not require matplotlib.
- Plotting functions will raise a clear ImportError at call time if matplotlib
  isn't installed.
"""

from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:  # pragma: no cover
    plt = None


def _require_matplotlib() -> None:
    if plt is None:
        raise ImportError(
            "matplotlib is required for plotting in ta_lab2.backtests.reports. "
            "Install it with: pip install matplotlib"
        )


def save_table(df: pd.DataFrame, out_path: str | Path) -> Path:
    """
    Save a DataFrame to CSV (creates parent dirs).
    """
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return p


def equity_plot(
    equity: pd.Series,
    title: str = "Equity Curve",
    out_path: Optional[str | Path] = None,
) -> None:
    """
    Plot an equity curve. If out_path is provided, saves a PNG.
    """
    _require_matplotlib()

    assert plt is not None  # for type-checkers
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
    Rank parameter sets inside each group by MAR, then Sharpe, then CAGR.
    Expects columns: ['mar','sharpe','cagr'] plus whatever is in group_cols.
    Returns original rows plus '_rank' (1 = best).
    """
    cols = list(group_cols)
    if results.empty:
        return results.assign(_rank=pd.Series(dtype=int))

    sort_cols = cols + ["mar", "sharpe", "cagr"]
    out = results.sort_values(sort_cols, ascending=[True] * len(cols) + [False, False, False]).copy()
    out["_rank"] = out.groupby(cols).cumcount() + 1
    return out
