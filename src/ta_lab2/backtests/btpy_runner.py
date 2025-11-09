"""
Backtesting.py validator for trade-by-trade sanity checks.

Requires: backtesting, pandas, numpy
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from backtesting import Backtest, Strategy
except ImportError as e:
    raise ImportError("Please `pip install Backtesting` (package name: backtesting)") from e


@dataclass
class BTResult:
    stats: Dict[str, Any]
    equity: pd.Series


def _make_strategy_class(stop_pct: Optional[float] = None, trail_pct: Optional[float] = None):
    """Create a Strategy subclass that uses precomputed entry/exit columns."""
    class SignalStrategy(Strategy):
        # parameters can be tuned if desired
        stop_loss_pct = stop_pct
        trailing_stop_pct = trail_pct

        def init(self):
            pass

        def next(self):
            i = len(self.data.Close) - 1
            # entries/exits are boolean columns in data._df
            if self.data._df["entry"].iloc[i] and not self.position:
                self.buy()
            if self.data._df["exit"].iloc[i] and self.position:
                self.position.close()

            # optional static/trailing stops
            if self.stop_loss_pct and self.position.is_long:
                self.position.set_stop_loss(self.stop_loss_pct)
            if self.trailing_stop_pct and self.position.is_long:
                self.position.set_trailing_sl(self.trailing_stop_pct)

    return SignalStrategy


def run_bt(
    df: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    stop_pct: Optional[float] = None,
    trail_pct: Optional[float] = None,
) -> BTResult:
    """Run Backtesting.py using precomputed boolean signals."""
    data = df.copy()
    data = data.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    data["entry"] = entries.astype(bool)
    data["exit"] = exits.astype(bool)

    commission = fee_bps / 1e4
    slippage = slippage_bps / 1e4

    StrategyCls = _make_strategy_class(stop_pct=stop_pct, trail_pct=trail_pct)
    bt = Backtest(
        data,
        StrategyCls,
        cash=1_000.0,
        commission=commission,
        trade_on_close=False,
        hedging=False,
        exclusive_orders=True,
        margin=1.0,
        slippage=slippage,
    )
    stats = bt.run()
    equity = stats["_equity_curve"]["Equity"]
    return BTResult(stats=dict(stats), equity=equity)
