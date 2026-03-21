"""
funding_adjuster.py
===================

Post-simulation funding P&L adjustment for perpetual futures backtests.

FundingAdjuster replays funding payments against a vectorbt portfolio's
position timeline to produce funding-adjusted equity curves. This is a
*post-simulation* step -- it does NOT modify vectorbt callbacks or
vbt_runner.py.

Sign convention (standard perpetual futures):
    - Positive funding rate -> longs PAY, shorts RECEIVE
    - Funding payment = position_value * funding_rate
    - Long  payment: negative cash flow (subtract from equity)
    - Short payment: positive cash flow (add to equity)

Modes:
    - 'daily':         reads tf='1d' rows from funding_rates (pre-rolled daily sum)
    - 'per_settlement': reads tf IN ('1h','4h','8h') native granularity rows

CRITICAL (MEMORY.md):
    - vbt outputs tz-naive index on this system; strip tz from funding rate
      DatetimeIndex before aligning with vbt equity series.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FundingAdjustedResult:
    """Result of post-simulation funding adjustment for a perp backtest."""

    equity_adjusted: pd.Series
    """Equity curve with cumulative funding applied (index = DatetimeIndex)."""

    total_funding_paid: float
    """Cumulative funding paid (negative = received by the position holder)."""

    total_return_adjusted: float
    """Total return of the funding-adjusted equity curve."""

    sharpe_adjusted: float
    """Annualised Sharpe ratio of the funding-adjusted equity curve (sqrt(365))."""

    funding_payments_series: pd.Series
    """Per-bar funding cash flows (negative = outflow for longs, positive = inflow)."""


# ---------------------------------------------------------------------------
# Core pure function
# ---------------------------------------------------------------------------


def compute_funding_payments(
    position_timeline: pd.Series,
    funding_rates: pd.Series,
    is_short: bool = False,
) -> pd.Series:
    """
    Compute per-bar funding cash flows for a perpetual futures position.

    Parameters
    ----------
    position_timeline:
        Absolute notional value at each bar (index = DatetimeIndex, values >= 0).
        Represents |mark_price * quantity| at each bar.
    funding_rates:
        Funding rate at each settlement (index = DatetimeIndex).
        May be at a different frequency than position_timeline.
    is_short:
        If True, the position holder is short.  Sign is flipped: shorts receive
        positive funding rates and pay negative ones.

    Returns
    -------
    pd.Series
        Per-bar funding payments with the same index as position_timeline.
        Negative values = cash outflow (longs paying positive rate).
        Positive values = cash inflow (shorts receiving positive rate).
    """
    if position_timeline.empty:
        return pd.Series([], dtype=float, name="funding_payment")

    # --- Strip tz from both indexes before aligning (vbt outputs tz-naive) ---
    pos_index = _strip_tz(position_timeline.index)
    pos = position_timeline.copy()
    pos.index = pos_index

    if funding_rates.empty:
        return pd.Series(np.zeros(len(pos)), index=pos_index, name="funding_payment")

    rate_index = _strip_tz(funding_rates.index)
    rates = funding_rates.copy()
    rates.index = rate_index

    # Align funding rates to position_timeline: forward-fill within bar window
    aligned_rates = rates.reindex(pos_index, method="ffill")

    # Payment = position_value * aligned_funding_rate
    payments = pos * aligned_rates

    # Sign convention for longs: positive rate -> negative payment (outflow)
    # payments already has the right sign for longs (positive rate * positive position = positive)
    # We want longs to have NEGATIVE payments when rate is positive, so flip.
    payments = -payments

    # Shorts receive the opposite
    if is_short:
        payments = -payments

    payments.name = "funding_payment"
    return payments


# ---------------------------------------------------------------------------
# DB access helpers
# ---------------------------------------------------------------------------


def load_funding_rates_for_backtest(
    engine,
    venue: str,
    symbol: str,
    start: datetime,
    end: datetime,
    mode: str = "daily",
) -> pd.Series:
    """
    Load funding rates from funding_rates for a backtest window.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    venue:
        Exchange venue (e.g. 'binance').
    symbol:
        Asset symbol (e.g. 'BTC').
    start:
        Backtest start timestamp (UTC).
    end:
        Backtest end timestamp (UTC).
    mode:
        'daily'          -> SELECT WHERE tf='1d'   (pre-rolled daily sums)
        'per_settlement' -> SELECT WHERE tf IN ('1h','4h','8h')

    Returns
    -------
    pd.Series
        DatetimeIndex (tz-naive UTC) -> float funding_rate.
        Empty Series if no data found.
    """
    from sqlalchemy import text

    if mode == "daily":
        tf_filter = "tf = '1d'"
    else:
        tf_filter = "tf IN ('1h', '4h', '8h')"

    sql = text(
        f"""
        SELECT ts, funding_rate
        FROM funding_rates
        WHERE venue = :venue
          AND symbol = :symbol
          AND {tf_filter}
          AND ts >= :start
          AND ts <= :end
        ORDER BY ts ASC
        """
    )

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sql,
                {"venue": venue, "symbol": symbol, "start": start, "end": end},
            ).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load funding rates for %s/%s (%s): %s", venue, symbol, mode, exc
        )
        return pd.Series([], dtype=float, name="funding_rate")

    if not rows:
        logger.warning(
            "No funding rates found for venue=%s symbol=%s mode=%s [%s, %s]",
            venue,
            symbol,
            mode,
            start,
            end,
        )
        return pd.Series([], dtype=float, name="funding_rate")

    ts_list = [r[0] for r in rows]
    rate_list = [float(r[1]) for r in rows]
    index = pd.DatetimeIndex(ts_list).tz_localize(None)  # strip tz -> naive UTC
    return pd.Series(rate_list, index=index, name="funding_rate")


def get_funding_rate_with_fallback(
    engine,
    venue: str,
    symbol: str,
    ts: datetime,
    tf: str = "8h",
) -> Optional[float]:
    """
    Look up a single funding rate.  Exact match first, then cross-venue
    average within a +/-30 min window.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    venue:
        Preferred venue.
    symbol:
        Asset symbol (e.g. 'BTC').
    ts:
        Settlement timestamp to look up.
    tf:
        Time frame (e.g. '8h').

    Returns
    -------
    float or None
        Funding rate, or None if no data found in any venue.
    """
    from sqlalchemy import text

    # --- Exact match ---
    sql_exact = text(
        """
        SELECT funding_rate
        FROM funding_rates
        WHERE venue  = :venue
          AND symbol = :symbol
          AND ts     = :ts
          AND tf     = :tf
        LIMIT 1
        """
    )
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sql_exact, {"venue": venue, "symbol": symbol, "ts": ts, "tf": tf}
            ).fetchone()
        if row is not None:
            return float(row[0])
    except Exception as exc:
        logger.warning("Exact funding rate lookup failed: %s", exc)

    # --- Cross-venue average fallback within +/- 30 min ---
    sql_fallback = text(
        """
        SELECT AVG(funding_rate)
        FROM funding_rates
        WHERE symbol = :symbol
          AND tf     = :tf
          AND ts BETWEEN :ts_lo AND :ts_hi
        """
    )
    ts_lo = pd.Timestamp(ts) - pd.Timedelta(minutes=30)
    ts_hi = pd.Timestamp(ts) + pd.Timedelta(minutes=30)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sql_fallback,
                {"symbol": symbol, "tf": tf, "ts_lo": ts_lo, "ts_hi": ts_hi},
            ).fetchone()
        if row is not None and row[0] is not None:
            return float(row[0])
    except Exception as exc:
        logger.warning("Fallback funding rate lookup failed: %s", exc)

    return None


# ---------------------------------------------------------------------------
# FundingAdjuster class
# ---------------------------------------------------------------------------


class FundingAdjuster:
    """
    Post-simulation funding P&L adjuster for perpetual futures backtests.

    Usage::

        adjuster = FundingAdjuster(engine, venue='binance', symbol='BTC')
        result   = adjuster.adjust(pf, is_short=False)
        print(result.total_funding_paid, result.sharpe_adjusted)

    Vectorbt is imported lazily inside ``adjust()`` to avoid import errors
    in test environments without vectorbt installed.
    """

    def __init__(
        self,
        engine,
        venue: str,
        symbol: str,
        mode: str = "daily",
    ) -> None:
        self.engine = engine
        self.venue = venue
        self.symbol = symbol
        self.mode = mode

    def adjust(self, pf, is_short: bool = False) -> FundingAdjustedResult:
        """
        Compute funding-adjusted equity curve for a vectorbt Portfolio.

        Parameters
        ----------
        pf:
            A vectorbt Portfolio object returned by vbt.Portfolio.from_signals()
            or similar.
        is_short:
            Whether the position is short (flips sign convention).

        Returns
        -------
        FundingAdjustedResult
        """
        equity: pd.Series = pf.value()

        if equity.empty:
            return FundingAdjustedResult(
                equity_adjusted=equity.copy(),
                total_funding_paid=0.0,
                total_return_adjusted=0.0,
                sharpe_adjusted=0.0,
                funding_payments_series=pd.Series(
                    [], dtype=float, name="funding_payment"
                ),
            )

        # vbt equity is tz-naive (MEMORY.md pitfall); use as-is for position_timeline
        # Use equity as position approximation (absolute notional value)
        position_timeline = equity.abs()

        # Determine backtest window from equity index
        naive_start = _strip_tz(pd.Index([equity.index[0]]))[0]
        naive_end = _strip_tz(pd.Index([equity.index[-1]]))[0]
        start_dt = (
            pd.Timestamp(naive_start).to_pydatetime().replace(tzinfo=timezone.utc)
        )
        end_dt = pd.Timestamp(naive_end).to_pydatetime().replace(tzinfo=timezone.utc)

        # Load funding rates
        funding_rates = load_funding_rates_for_backtest(
            self.engine,
            self.venue,
            self.symbol,
            start_dt,
            end_dt,
            mode=self.mode,
        )

        # Compute per-bar funding payments
        funding_payments = compute_funding_payments(
            position_timeline, funding_rates, is_short=is_short
        )

        # Align funding_payments index to equity index (in case of any diff)
        funding_payments = funding_payments.reindex(
            _strip_tz(equity.index), fill_value=0.0
        )

        # Adjust equity: equity_adj[t] = equity[t] + cumulative_funding_up_to_t
        # (funding_payments are cash flows: negative = outflow, reduces equity)
        equity_naive = equity.copy()
        equity_naive.index = _strip_tz(equity.index)
        equity_adjusted = equity_naive + funding_payments.cumsum()

        # Metrics on adjusted equity
        total_funding_paid = float(funding_payments.sum())
        total_return_adjusted = _total_return(equity_adjusted)
        sharpe_adj = _sharpe_daily(equity_adjusted, annualize=365)

        return FundingAdjustedResult(
            equity_adjusted=equity_adjusted,
            total_funding_paid=total_funding_paid,
            total_return_adjusted=total_return_adjusted,
            sharpe_adjusted=sharpe_adj,
            funding_payments_series=funding_payments,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _strip_tz(index: pd.Index) -> pd.Index:
    """Return index with timezone info removed (tz-naive)."""
    if hasattr(index, "tz") and index.tz is not None:
        return index.tz_localize(None)
    if isinstance(index, pd.DatetimeIndex):
        return index
    # Attempt conversion (handles object arrays of Timestamps)
    try:
        dti = pd.DatetimeIndex(index)
        if dti.tz is not None:
            return dti.tz_localize(None)
        return dti
    except Exception:
        return index


def _total_return(equity: pd.Series) -> float:
    """Total return as a decimal fraction."""
    if equity.empty or equity.iloc[0] == 0:
        return 0.0
    return float((equity.iloc[-1] - equity.iloc[0]) / equity.iloc[0])


def _sharpe_daily(equity: pd.Series, annualize: int = 365) -> float:
    """Annualised Sharpe of daily returns (no risk-free rate)."""
    if len(equity) < 2:
        return 0.0
    rets = equity.pct_change().dropna()
    std = float(rets.std(ddof=0))
    if std == 0 or math.isnan(std):
        return 0.0
    return float(rets.mean() / std * math.sqrt(annualize))
