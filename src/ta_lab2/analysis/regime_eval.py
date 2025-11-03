# -*- coding: utf-8 -*-
"""
Regime-conditional performance:
- split metrics by regime labels (e.g., trend_state in {-1,0,1})
- regime transition analysis stubs
"""
from __future__ import annotations
from typing import Dict, Optional
import pandas as pd

from .performance import evaluate_signals, position_returns

def metrics_by_regime(
    df: pd.DataFrame,
    regime_col: str = "trend_state",
    close_col: str = "close",
    position_col: str = "position",
    costs_bps: float = 0.0,
    freq: Optional[str] = None,
) -> pd.DataFrame:
    """
    Group evaluation by regime values; returns one row per regime.
    """
    rows = []
    for r, sub in df.groupby(regime_col):
        if len(sub) < 10:  # skip tiny groups
            continue
        m = evaluate_signals(sub, close_col=close_col, position_col=position_col, costs_bps=costs_bps, freq=freq)
        m["regime"] = r
        rows.append(m)
    out = pd.DataFrame(rows)
    cols = ["regime","ann_return","sharpe","sortino","max_drawdown","calmar","hit_rate","turnover","n_bars"]
    return out.reindex(columns=cols)

def regime_transition_pnl(
    df: pd.DataFrame,
    regime_col: str = "trend_state",
    close_col: str = "close",
    position_col: str = "position",
    costs_bps: float = 0.0,
) -> pd.DataFrame:
    """
    Evaluate performance around regime switches (entering/leaving states).
    Produces simple aggregates by (prev_regime -> next_regime).
    """
    d = df.copy()
    d["_reg_prev"] = d[regime_col].shift(1)
    d["_edge"] = (d[regime_col] != d["_reg_prev"]).fillna(False)

    # returns on the *first bar in a new regime*
    trans = d[d["_edge"]].copy()
    trans["ret"] = position_returns(trans[close_col], trans[position_col], costs_bps=costs_bps)

    grp = trans.groupby(["_reg_prev", regime_col])["ret"]
    out = grp.agg(["count","mean","std"]).reset_index().rename(
        columns={"_reg_prev":"reg_from", regime_col:"reg_to", "mean":"ret_mean", "std":"ret_std"}
    )
    return out
