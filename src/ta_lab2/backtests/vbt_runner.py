# src/ta_lab2/backtests/vbt_runner.py
"""
Vectorbt-based runner for fast research & sweeps.

Requires: vectorbt, numpy, pandas
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None  # type: ignore[assignment]


# ---------- Protocols & dataclasses ----------

class SignalFunc(Protocol):
    """Callable that turns a price DataFrame + params into (entries, exits, size)."""
    def __call__(self, df: pd.DataFrame, **params) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]: ...


@dataclass
class CostModel:
    """Costs in basis points; funding is daily bps applied to gross position value."""
    fee_bps: float = 0.0          # per trade commission (bps of notional)
    slippage_bps: float = 0.0     # per trade slippage (bps of price)
    funding_bps_day: float = 0.0  # daily bps on absolute position value (for perps)

    def to_vbt_kwargs(self) -> Dict[str, Any]:
        # vectorbt expects decimals, not bps
        fees = self.fee_bps / 1e4
        slippage = self.slippage_bps / 1e4
        return dict(fees=fees, slippage=slippage)


@dataclass
class Split:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


@dataclass
class ResultRow:
    split: str
    params: Mapping[str, Any]
    trades: int
    total_return: float
    cagr: float
    mdd: float
    mar: float
    sharpe: float
    equity_last: float


@dataclass
class ResultBundle:
    rows: List[ResultRow]
    table: pd.DataFrame


# ---------- helpers ----------

def _cagr(equity: pd.Series, freq_per_year: int) -> float:
    if equity.empty:
        return 0.0
    start, end = equity.iloc[0], equity.iloc[-1]
    n = len(equity)
    years = n / freq_per_year
    if start <= 0 or years <= 0:
        return 0.0
    return (end / start) ** (1 / years) - 1


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    dd = (equity / running_max) - 1.0
    return float(dd.min())


def _sharpe(returns: pd.Series, rf: float = 0.0, freq_per_year: int = 252) -> float:
    if returns.std(ddof=0) == 0:
        return 0.0
    mu = returns.mean() - rf / freq_per_year
    sig = returns.std(ddof=0)
    return float(np.sqrt(freq_per_year) * mu / sig)


# ---------- core API ----------

def run_vbt_on_split(
    df: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    size: Optional[pd.Series],
    cost: CostModel,
    split: Split,
    price_col: str = "close",
    freq_per_year: int = 365,  # BTC daily; change for intraday
) -> ResultRow:
    """Run vectorbt on a single time split and compute core metrics."""
    # Slice window
    d = df.loc[split.start:split.end]

    # Align signals to window (keep original indices)
    e_in = entries.loc[split.start:split.end].astype(bool)
    e_out = exits.loc[split.start:split.end].astype(bool)

    # Next-bar execution WITHOUT creating NaNs (no fillna needed)
    # Using fill_value avoids the FutureWarning from downcasting on fillna/ffill/bfill
    e_in = e_in.shift(1, fill_value=False).astype(np.bool_)
    e_out = e_out.shift(1, fill_value=False).astype(np.bool_)

    # Optional sizing aligned to window (force float dtype)
    sz = None
    if size is not None:
        sz = size.loc[split.start:split.end].astype(float)

    # Build portfolio (pass NumPy arrays to avoid pandas dtype warnings)
    pf = vbt.Portfolio.from_signals(
        d[price_col],
        entries=e_in.to_numpy(),                           # ndarray(bool)
        exits=e_out.to_numpy(),                            # ndarray(bool)
        size=None if sz is None else sz.to_numpy(),        # ndarray(float) or None
        **cost.to_vbt_kwargs(),
        init_cash=1_000.0,                                 # normalized; scale via equity_last externally
        freq="D",
    )

    equity = pf.value()
    ret_series = pf.returns()
    trades = int(pf.trades.count())
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = _cagr(equity, freq_per_year=freq_per_year)
    mdd = _max_drawdown(equity)
    mar = float(cagr / abs(mdd)) if mdd != 0 else 0.0
    sharpe = _sharpe(ret_series, rf=0.0, freq_per_year=freq_per_year)
    equity_last = float(equity.iloc[-1])  # explicit last equity

    return ResultRow(
        split=split.name,
        params={},  # filled by caller in sweep
        trades=trades,
        total_return=total_return,
        cagr=cagr,
        mdd=mdd,
        mar=mar,
        sharpe=sharpe,
        equity_last=equity_last,
    )


def sweep_grid(
    df: pd.DataFrame,
    signal_func: SignalFunc,
    param_grid: Iterable[Mapping[str, Any]],
    splits: Iterable[Split],
    cost: CostModel,
    price_col: str = "close",
    freq_per_year: int = 365,
) -> ResultBundle:
    if vbt is None:
        raise ImportError(
            "vectorbt is required for ta_lab2.backtests; please `pip install vectorbt` "
            "to use the backtest runner."
        )
    """Run many parameter sets across many splits; return a tidy table."""
    rows: List[ResultRow] = []
    for params in param_grid:
        entries, exits, size = signal_func(df, **params)
        for split in splits:
            row = run_vbt_on_split(
                df, entries, exits, size, cost, split, price_col, freq_per_year
            )
            # attach params for this run
            row.params = dict(params)
            rows.append(row)

    table = pd.DataFrame(
        [{
            "split": r.split,
            **{f"p_{k}": v for k, v in r.params.items()},
            "trades": r.trades,
            "total_return": r.total_return,
            "cagr": r.cagr,
            "mdd": r.mdd,
            "mar": r.mar,
            "sharpe": r.sharpe,
            "equity_last": r.equity_last,
        } for r in rows]
    ).sort_values(["split"])
    return ResultBundle(rows=rows, table=table)
