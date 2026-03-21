"""
PositionSizer - Convert signals into target positions with configurable sizing modes.

Supports three sizing modes:
  - fixed_fraction: constant fraction of portfolio value
  - regime_adjusted: fraction scaled by current market regime
  - signal_strength: fraction scaled by signal confidence

All arithmetic uses decimal.Decimal for precision.

Exports: PositionSizer, compute_target_position, compute_order_delta,
         ExecutorConfig, REGIME_MULTIPLIERS
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regime multiplier table
# ---------------------------------------------------------------------------

REGIME_MULTIPLIERS: dict[str, Decimal] = {
    "bull_low_vol": Decimal("1.0"),
    "bull_high_vol": Decimal("0.7"),
    "ranging": Decimal("0.5"),
    "bear_low_vol": Decimal("0.3"),
    "bear_high_vol": Decimal("0.0"),
}


# ---------------------------------------------------------------------------
# ExecutorConfig dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExecutorConfig:
    """
    Runtime configuration for the executor, derived from dim_executor_config.

    Attributes
    ----------
    config_id : int
        Primary key from dim_executor_config.
    config_name : str
        Human-readable label for the strategy configuration.
    signal_type : str
        Signal category: 'ema_crossover', 'rsi_mean_revert', 'atr_breakout'.
    signal_id : int
        FK to dim_signals; identifies which signal series to read.
    exchange : str
        Exchange identifier (e.g. 'paper', 'binance').
    sizing_mode : str
        One of 'fixed_fraction', 'regime_adjusted', 'signal_strength'.
    position_fraction : float
        Base fraction of portfolio to allocate per position (0.0 – 1.0).
    max_position_fraction : float
        Hard cap on effective fraction after any adjustments (0.0 – 1.0).
    fill_price_mode : str
        How fill price is determined: 'bar_close', 'exchange_mid', 'vwap'.
    cadence_hours : float
        Maximum acceptable age (hours) for the latest signal before raising
        StaleSignalError.
    last_processed_signal_ts : datetime | None
        High-water mark from the previous execution; None on first run.
    initial_capital : Decimal
        Starting portfolio value used when no positions exist yet.
    """

    config_id: int
    config_name: str
    signal_type: str
    signal_id: int
    exchange: str
    sizing_mode: str
    position_fraction: float
    max_position_fraction: float
    fill_price_mode: str
    cadence_hours: float
    last_processed_signal_ts: datetime | None
    initial_capital: Decimal = field(default_factory=lambda: Decimal("100000"))


# ---------------------------------------------------------------------------
# Module-level convenience wrappers (re-export from PositionSizer)
# ---------------------------------------------------------------------------


def compute_target_position(
    latest_signal: dict | None,
    portfolio_value: Decimal,
    current_price: Decimal,
    config: ExecutorConfig,
    regime_label: str | None = None,
    signal_confidence: float = 1.0,
) -> Decimal:
    """
    Convenience wrapper — delegates to PositionSizer.compute_target_position.
    """
    return PositionSizer.compute_target_position(
        latest_signal=latest_signal,
        portfolio_value=portfolio_value,
        current_price=current_price,
        config=config,
        regime_label=regime_label,
        signal_confidence=signal_confidence,
    )


def compute_order_delta(current_qty: Decimal, target_qty: Decimal) -> Decimal:
    """
    Convenience wrapper — delegates to PositionSizer.compute_order_delta.
    """
    return PositionSizer.compute_order_delta(current_qty, target_qty)


# ---------------------------------------------------------------------------
# PositionSizer
# ---------------------------------------------------------------------------


class PositionSizer:
    """
    Stateless position sizing calculator.

    All public methods are static so the class can be used without
    instantiation. Each method accepts the values it needs directly rather
    than relying on shared state.
    """

    # ------------------------------------------------------------------
    # Core sizing
    # ------------------------------------------------------------------

    @staticmethod
    def compute_target_position(
        latest_signal: dict | None,
        portfolio_value: Decimal,
        current_price: Decimal,
        config: ExecutorConfig,
        regime_label: str | None = None,
        signal_confidence: float = 1.0,
    ) -> Decimal:
        """
        Compute the target position quantity (in asset units).

        Parameters
        ----------
        latest_signal : dict | None
            Most recent signal for the asset, or None if no signal.
        portfolio_value : Decimal
            Current total portfolio value in base currency.
        current_price : Decimal
            Current asset price in base currency.
        config : ExecutorConfig
            Strategy configuration.
        regime_label : str | None
            Current market regime key (used when sizing_mode='regime_adjusted').
        signal_confidence : float
            Signal confidence score 0.0-1.0 (used when sizing_mode='signal_strength').

        Returns
        -------
        Decimal
            Target quantity. Positive for long, negative for short, zero to close.
        """
        # No signal or closed position -> flat
        if latest_signal is None:
            return Decimal("0")

        position_state = latest_signal.get("position_state", "")
        if position_state == "closed":
            return Decimal("0")

        direction: str = latest_signal.get("direction", "long")
        fraction = Decimal(str(config.position_fraction))
        max_fraction = Decimal(str(config.max_position_fraction))

        sizing_mode = config.sizing_mode

        if sizing_mode == "regime_adjusted":
            multiplier = REGIME_MULTIPLIERS.get(regime_label or "", Decimal("1.0"))
            fraction = fraction * multiplier

        elif sizing_mode == "signal_strength":
            # Clamp minimum signal strength at 10%
            confidence = max(Decimal(str(signal_confidence)), Decimal("0.10"))
            fraction = fraction * confidence

        # else: fixed_fraction — no adjustment

        # Hard cap
        if fraction > max_fraction:
            fraction = max_fraction

        if current_price == Decimal("0"):
            logger.warning("compute_target_position: current_price is 0, returning 0")
            return Decimal("0")

        qty = (portfolio_value * fraction) / current_price

        if direction.lower() == "short":
            qty = -qty

        logger.debug(
            "compute_target_position: mode=%s direction=%s fraction=%s qty=%s",
            sizing_mode,
            direction,
            fraction,
            qty,
        )
        return qty

    # ------------------------------------------------------------------
    # Order delta
    # ------------------------------------------------------------------

    @staticmethod
    def compute_order_delta(current_qty: Decimal, target_qty: Decimal) -> Decimal:
        """
        Compute the signed quantity delta needed to move from current to target.

        Parameters
        ----------
        current_qty : Decimal
            Current position quantity (positive = long, negative = short, 0 = flat).
        target_qty : Decimal
            Desired position quantity.

        Returns
        -------
        Decimal
            Signed delta. Positive means buy, negative means sell.
        """
        return target_qty - current_qty

    # ------------------------------------------------------------------
    # Portfolio value
    # ------------------------------------------------------------------

    @staticmethod
    def get_portfolio_value(
        conn: Any,
        strategy_id: int,
        initial_capital: Decimal = Decimal("100000"),
    ) -> Decimal:
        """
        Retrieve current portfolio value from aggregated position view.

        Attempts to read from v_positions_agg. Falls back to initial_capital
        when no rows exist.

        Parameters
        ----------
        conn :
            Active SQLAlchemy connection.
        strategy_id : int
            Strategy identifier to filter positions.
        initial_capital : Decimal
            Fallback value when no positions are found.

        Returns
        -------
        Decimal
            Total portfolio value (initial_capital + realized_pnl + unrealized_pnl).
        """
        sql = text(
            "SELECT COALESCE(SUM(realized_pnl), 0) + COALESCE(SUM(unrealized_pnl), 0) AS total_pnl "
            "FROM public.v_positions_agg "
            "WHERE strategy_id = :strategy_id"
        )
        try:
            row = conn.execute(sql, {"strategy_id": strategy_id}).fetchone()
            if row and row.total_pnl is not None:
                portfolio_value = initial_capital + Decimal(str(row.total_pnl))
                logger.debug(
                    "get_portfolio_value: strategy_id=%s portfolio_value=%s (from DB)",
                    strategy_id,
                    portfolio_value,
                )
                return portfolio_value
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_portfolio_value: DB query failed (%s), using initial_capital=%s",
                exc,
                initial_capital,
            )

        logger.debug(
            "get_portfolio_value: no positions found for strategy_id=%s, using initial_capital=%s",
            strategy_id,
            initial_capital,
        )
        return initial_capital

    # ------------------------------------------------------------------
    # Current price
    # ------------------------------------------------------------------

    @staticmethod
    def get_current_price(conn: Any, asset_id: int) -> Decimal:
        """
        Retrieve the most recent price for an asset.

        Tries exchange_price_feed first (real-time). Falls back to the most recent
        daily bar close from price_bars_multi_tf when the feed is stale (>24h)
        or missing.

        Parameters
        ----------
        conn :
            Active SQLAlchemy connection.
        asset_id : int
            Asset (coin) identifier.

        Returns
        -------
        Decimal
            Most recent price as Decimal.

        Raises
        ------
        ValueError
            When no price is available from any source.
        """
        # Try live feed first
        feed_sql = text(
            "SELECT last_price, fetched_at "
            "FROM public.exchange_price_feed "
            "WHERE asset_id = :asset_id "
            "ORDER BY fetched_at DESC "
            "LIMIT 1"
        )
        try:
            row = conn.execute(feed_sql, {"asset_id": asset_id}).fetchone()
            if row and row.last_price is not None:
                from datetime import timezone  # local import to avoid circular

                fetched_at = row.fetched_at
                if fetched_at.tzinfo is None:
                    fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                from datetime import datetime

                age_hours = (
                    datetime.now(timezone.utc) - fetched_at
                ).total_seconds() / 3600.0
                if age_hours <= 24.0:
                    price = Decimal(str(row.last_price))
                    logger.debug(
                        "get_current_price: asset_id=%s price=%s source=exchange_price_feed (age=%.1fh)",
                        asset_id,
                        price,
                        age_hours,
                    )
                    return price
                else:
                    logger.debug(
                        "get_current_price: exchange_price_feed stale (%.1fh) for asset_id=%s, using bar fallback",
                        age_hours,
                        asset_id,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "get_current_price: exchange_price_feed unavailable (%s), using bar fallback",
                exc,
            )

        # Fall back to daily bar close
        bar_sql = text(
            "SELECT close "
            "FROM public.price_bars_multi_tf_u "
            "WHERE id = :asset_id AND tf = '1D' "
            "AND alignment_source = 'multi_tf' "
            "ORDER BY ts DESC "
            "LIMIT 1"
        )
        row = conn.execute(bar_sql, {"asset_id": asset_id}).fetchone()
        if row and row.close is not None:
            price = Decimal(str(row.close))
            logger.debug(
                "get_current_price: asset_id=%s price=%s source=price_bars_multi_tf_u",
                asset_id,
                price,
            )
            return price

        raise ValueError(f"No price available for asset_id={asset_id} from any source.")
