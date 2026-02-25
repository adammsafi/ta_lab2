# src/ta_lab2/analysis/stop_simulator.py
"""
Stop-loss simulation sweep: hard stop, trailing stop, time-stop via vectorbt 0.28.1.

This is a pure simulation library -- no DB reads, no CLI, no reports.
All functions return vectorbt Portfolio objects or DataFrames.

Usage:
    from ta_lab2.analysis.stop_simulator import sweep_stops, STOP_THRESHOLDS
    df = sweep_stops(price, entries, exits)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STOP_THRESHOLDS = [0.01, 0.03, 0.05, 0.07, 0.10, 0.15]
TIME_STOP_BARS = [5, 10, 20, 30]  # 5=~1 week, 10=~2 weeks, 20=~1 month, 30=~6 weeks
DEFAULT_FEE_BPS = 16  # 16 bps round-trip (consistent with bakeoff)

_RESULT_COLUMNS = [
    "stop_type",
    "threshold",
    "sharpe",
    "max_dd",
    "total_return",
    "trade_count",
    "win_rate",
    "avg_recovery_bars",
    "opportunity_cost",
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class StopScenarioResult:
    stop_type: str  # "hard", "trailing", "time"
    threshold: float  # percentage for hard/trailing, bar count for time
    sharpe: float
    max_dd: float
    total_return: float
    trade_count: int
    win_rate: float
    avg_recovery_bars: float  # NaN if no recovery events
    opportunity_cost: float  # total_return_baseline - total_return_with_stop


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_vbt() -> None:
    if vbt is None:
        raise ImportError(
            "vectorbt is required for stop_simulator; `pip install vectorbt`"
        )


def _strip_tz(price: pd.Series) -> pd.Series:
    """Return a copy of price with timezone stripped from index if tz-aware."""
    if hasattr(price.index, "tz") and price.index.tz is not None:
        price = price.copy()
        price.index = price.index.tz_localize(None)
    return price


def _coerce_signals(
    price: pd.Series, entries: pd.Series, exits: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """Ensure entries/exits are boolean pd.Series aligned to price index."""
    if not isinstance(entries, pd.Series):
        entries = pd.Series(entries, index=price.index, dtype=bool)
    else:
        entries = entries.astype(bool)

    if not isinstance(exits, pd.Series):
        exits = pd.Series(exits, index=price.index, dtype=bool)
    else:
        exits = exits.astype(bool)

    return entries, exits


def _has_any_entries(entries: pd.Series) -> bool:
    """Return True if there is at least one entry signal."""
    return bool(entries.any())


# ---------------------------------------------------------------------------
# Simulation functions
# ---------------------------------------------------------------------------


def simulate_hard_stop(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    sl_pct: float,
    fee_bps: float = DEFAULT_FEE_BPS,
):
    """
    Simulate a hard (fixed) stop-loss using vectorbt.

    Parameters
    ----------
    price : pd.Series
        OHLCV close price series.
    entries : pd.Series[bool]
        Boolean entry signals aligned to price index.
    exits : pd.Series[bool]
        Boolean exit signals aligned to price index.
    sl_pct : float
        Stop-loss threshold as a fraction (e.g. 0.05 = 5%).
    fee_bps : float
        Round-trip fee in basis points.

    Returns
    -------
    vbt.Portfolio
    """
    _require_vbt()
    price = _strip_tz(price)
    entries, exits = _coerce_signals(price, entries, exits)

    return vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        sl_stop=sl_pct,
        sl_trail=False,
        direction="longonly",
        freq="D",
        init_cash=1000.0,
        fees=fee_bps / 1e4,
    )


def simulate_trailing_stop(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    sl_pct: float,
    fee_bps: float = DEFAULT_FEE_BPS,
):
    """
    Simulate a trailing stop-loss using vectorbt.

    Parameters
    ----------
    price : pd.Series
        OHLCV close price series.
    entries : pd.Series[bool]
        Boolean entry signals aligned to price index.
    exits : pd.Series[bool]
        Boolean exit signals aligned to price index.
    sl_pct : float
        Trailing stop distance as a fraction (e.g. 0.05 = 5%).
    fee_bps : float
        Round-trip fee in basis points.

    Returns
    -------
    vbt.Portfolio
    """
    _require_vbt()
    price = _strip_tz(price)
    entries, exits = _coerce_signals(price, entries, exits)

    return vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        sl_stop=sl_pct,
        sl_trail=True,
        direction="longonly",
        freq="D",
        init_cash=1000.0,
        fees=fee_bps / 1e4,
    )


def simulate_time_stop(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    n_bars: int,
    fee_bps: float = DEFAULT_FEE_BPS,
):
    """
    Simulate a time-based stop using custom exit signal arrays.

    vectorbt 0.28.1 has no native time-stop parameter. We build a custom exit
    array that fires n_bars after each entry, then OR it with the original exits.

    Parameters
    ----------
    price : pd.Series
        OHLCV close price series.
    entries : pd.Series[bool]
        Boolean entry signals aligned to price index.
    exits : pd.Series[bool]
        Boolean exit signals aligned to price index.
    n_bars : int
        Number of bars after which to force an exit.
    fee_bps : float
        Round-trip fee in basis points.

    Returns
    -------
    vbt.Portfolio
    """
    _require_vbt()
    price = _strip_tz(price)
    entries, exits = _coerce_signals(price, entries, exits)

    n = len(price)

    # Vectorized: find all entry indices, add n_bars offset, clip to array bounds
    entry_indices = np.where(entries.values)[0]  # shape (n_entries,)
    time_exit_indices = np.clip(entry_indices + n_bars, 0, n - 1)

    # Build time-exit boolean array
    time_exits_arr = np.zeros(n, dtype=bool)
    if len(time_exit_indices) > 0:
        time_exits_arr[time_exit_indices] = True

    # Combine with original exits: fire on whichever comes first
    combined_exits = exits | pd.Series(time_exits_arr, index=price.index, dtype=bool)

    return vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=combined_exits,
        direction="longonly",
        freq="D",
        init_cash=1000.0,
        fees=fee_bps / 1e4,
    )


# ---------------------------------------------------------------------------
# Recovery time
# ---------------------------------------------------------------------------


def compute_recovery_time(equity: pd.Series) -> float:
    """
    Compute average bars from drawdown trough to equity recovery (return to peak).

    Algorithm:
    - Track cumulative maximum (running peak) of equity.
    - When equity < peak, we are in a drawdown.
    - When equity >= peak again, record the drawdown duration.

    Parameters
    ----------
    equity : pd.Series
        Portfolio equity / value series.

    Returns
    -------
    float
        Mean recovery duration in bars. np.nan if no recovery events occurred
        (i.e. equity never fully recovered, or there were no drawdowns).
    """
    if equity.empty or len(equity) < 2:
        return np.nan

    equity_arr = equity.values.astype(float)
    n = len(equity_arr)
    peak = equity_arr[0]

    recovery_durations: list[int] = []
    in_drawdown = False
    drawdown_start: int = 0

    for i in range(1, n):
        if equity_arr[i] < peak:
            if not in_drawdown:
                in_drawdown = True
                drawdown_start = i
        elif equity_arr[i] >= peak:
            if in_drawdown:
                # Recovered
                recovery_durations.append(i - drawdown_start)
                in_drawdown = False
            # Update peak
            peak = equity_arr[i]

    if not recovery_durations:
        return np.nan

    return float(np.mean(recovery_durations))


# ---------------------------------------------------------------------------
# Metrics extraction
# ---------------------------------------------------------------------------


def extract_scenario_metrics(
    pf,
    stop_type: str,
    threshold: float,
    baseline_return: float,
) -> StopScenarioResult:
    """
    Extract scenario metrics from a vbt.Portfolio into a StopScenarioResult.

    Parameters
    ----------
    pf : vbt.Portfolio
        Executed portfolio object.
    stop_type : str
        One of "hard", "trailing", "time".
    threshold : float
        Stop threshold (fraction for hard/trailing, bar count for time).
    baseline_return : float
        Total return from the no-stop baseline run.

    Returns
    -------
    StopScenarioResult
    """
    sharpe = float(pf.sharpe_ratio(freq=365))
    max_dd = float(pf.max_drawdown())
    total_return = float(pf.total_return())
    trade_count = int(pf.trades.count())

    if trade_count == 0:
        win_rate = 0.0
    else:
        try:
            win_rate = float(pf.trades.win_rate())
        except (ZeroDivisionError, Exception):
            win_rate = 0.0

    avg_recovery_bars = compute_recovery_time(pf.value())
    opportunity_cost = baseline_return - total_return

    return StopScenarioResult(
        stop_type=stop_type,
        threshold=threshold,
        sharpe=sharpe,
        max_dd=max_dd,
        total_return=total_return,
        trade_count=trade_count,
        win_rate=win_rate,
        avg_recovery_bars=avg_recovery_bars,
        opportunity_cost=opportunity_cost,
    )


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


def sweep_stops(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    thresholds: Optional[List[float]] = None,
    time_bars: Optional[List[int]] = None,
    fee_bps: float = DEFAULT_FEE_BPS,
) -> pd.DataFrame:
    """
    Sweep hard stop, trailing stop, and time-stop across threshold ranges.

    Parameters
    ----------
    price : pd.Series
        OHLCV close price series.
    entries : pd.Series[bool]
        Boolean entry signals.
    exits : pd.Series[bool]
        Boolean exit signals.
    thresholds : list of float, optional
        Stop-loss thresholds for hard/trailing. Defaults to STOP_THRESHOLDS.
    time_bars : list of int, optional
        Bar counts for time-stop. Defaults to TIME_STOP_BARS.
    fee_bps : float
        Round-trip fee in basis points.

    Returns
    -------
    pd.DataFrame
        Columns: stop_type, threshold, sharpe, max_dd, total_return, trade_count,
                 win_rate, avg_recovery_bars, opportunity_cost.
        Sorted by (stop_type, threshold).
    """
    _require_vbt()

    if thresholds is None:
        thresholds = STOP_THRESHOLDS
    if time_bars is None:
        time_bars = TIME_STOP_BARS

    # Coerce signals once
    entries, exits = _coerce_signals(price, entries, exits)

    # Guard: empty entries → return empty DataFrame with correct columns
    if not _has_any_entries(entries):
        return pd.DataFrame(columns=_RESULT_COLUMNS)

    # Baseline (no stop) for opportunity cost
    price_clean = _strip_tz(price)
    pf_baseline = vbt.Portfolio.from_signals(
        price_clean,
        entries=entries,
        exits=exits,
        direction="longonly",
        freq="D",
        init_cash=1000.0,
        fees=fee_bps / 1e4,
    )
    baseline_return = float(pf_baseline.total_return())

    results: list[StopScenarioResult] = []

    # Hard stops
    for sl_pct in thresholds:
        pf = simulate_hard_stop(price, entries, exits, sl_pct, fee_bps=fee_bps)
        results.append(extract_scenario_metrics(pf, "hard", sl_pct, baseline_return))

    # Trailing stops
    for sl_pct in thresholds:
        pf = simulate_trailing_stop(price, entries, exits, sl_pct, fee_bps=fee_bps)
        results.append(
            extract_scenario_metrics(pf, "trailing", sl_pct, baseline_return)
        )

    # Time stops
    for n_bars in time_bars:
        pf = simulate_time_stop(price, entries, exits, n_bars, fee_bps=fee_bps)
        results.append(
            extract_scenario_metrics(pf, "time", float(n_bars), baseline_return)
        )

    # Build DataFrame
    df = pd.DataFrame(
        [
            {
                "stop_type": r.stop_type,
                "threshold": r.threshold,
                "sharpe": r.sharpe,
                "max_dd": r.max_dd,
                "total_return": r.total_return,
                "trade_count": r.trade_count,
                "win_rate": r.win_rate,
                "avg_recovery_bars": r.avg_recovery_bars,
                "opportunity_cost": r.opportunity_cost,
            }
            for r in results
        ]
    )

    df = df.sort_values(["stop_type", "threshold"]).reset_index(drop=True)
    return df
