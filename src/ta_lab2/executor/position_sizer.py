"""
PositionSizer - Convert signals into target positions with configurable sizing modes.

Supports five sizing modes:
  - fixed_fraction: constant fraction of portfolio value
  - regime_adjusted: fraction scaled by current market regime
  - signal_strength: fraction scaled by signal confidence
  - target_vol: fraction scaled so portfolio vol targets a configured annualized vol.
      Uses GARCH blended conditional vol (passed via garch_vol kwarg by caller).
      Falls back to fixed_fraction when GARCH vol is unavailable or not configured.
  - bl_weight: fraction taken from the most recent Black-Litterman optimizer output
      in portfolio_allocations. Returns 0 (flat) when BL de-selects the asset.
      Falls back to fixed_fraction when conn/asset_id are not provided.

All arithmetic uses decimal.Decimal for precision.

get_current_price() supports a VM-aware 5-tier fallback chain:
  1. PriceCache (if provided, sub-second WebSocket price)
  2. exchange_price_feed (existing REST snapshot, unchanged)
  3. hl_assets.mark_px (VM only: updated by HL collector every ~6h)
  4. hl_candles latest close (VM only: last-resort HL bar data)
  5. price_bars_multi_tf_u (local only: skipped when vm_mode=True)

Tiers 3-4 are only queried when vm_mode=True (the default is False, so local
execution is identical to before this change).  This is a backward-compatible
extension: callers that don't pass price_cache or vm_mode see exactly the same
behaviour as before.

Exports: PositionSizer, compute_target_position, compute_order_delta,
         ExecutorConfig, REGIME_MULTIPLIERS
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from ta_lab2.executor.price_cache import PriceCache

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
        One of 'fixed_fraction', 'regime_adjusted', 'signal_strength', 'bl_weight'.
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
    target_annual_vol : float or None
        Target annualized volatility fraction (e.g. 0.80 = 80% annual vol target).
        Used when sizing_mode='target_vol'. When None or 0, target_vol falls back
        to fixed_fraction. Maps to dim_executor_config.target_annual_vol column.
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
    target_annual_vol: float | None = None


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
    **kwargs: Any,
) -> Decimal:
    """
    Convenience wrapper -- delegates to PositionSizer.compute_target_position.

    Accepts **kwargs (e.g. garch_vol) and passes them through to the static method.
    """
    return PositionSizer.compute_target_position(
        latest_signal=latest_signal,
        portfolio_value=portfolio_value,
        current_price=current_price,
        config=config,
        regime_label=regime_label,
        signal_confidence=signal_confidence,
        **kwargs,
    )


def compute_order_delta(current_qty: Decimal, target_qty: Decimal) -> Decimal:
    """
    Convenience wrapper — delegates to PositionSizer.compute_order_delta.
    """
    return PositionSizer.compute_order_delta(current_qty, target_qty)


# ---------------------------------------------------------------------------
# Private price-resolution helpers (used by PositionSizer.get_price tiers)
# ---------------------------------------------------------------------------


def _resolve_symbol(asset_id: int, conn: Any) -> str | None:
    """Return the ticker symbol for *asset_id* from dim_assets.

    Returns None if the symbol cannot be resolved (non-fatal; caller skips
    PriceCache lookup and falls through to the next tier).
    """
    sql = text("SELECT symbol FROM public.dim_assets WHERE id = :asset_id LIMIT 1")
    try:
        row = conn.execute(sql, {"asset_id": asset_id}).fetchone()
        if row and row.symbol:
            return str(row.symbol)
    except Exception as exc:  # noqa: BLE001
        logger.debug("_resolve_symbol: query failed for asset_id=%s: %s", asset_id, exc)
    return None


def _get_from_exchange_price_feed(conn: Any, asset_id: int) -> Decimal | None:
    """Tier 2: query exchange_price_feed. Returns Decimal or None (stale/missing)."""
    from datetime import datetime, timezone  # local import to avoid circular

    feed_sql = text(
        "SELECT last_price, fetched_at "
        "FROM public.exchange_price_feed "
        "WHERE asset_id = :asset_id "
        "ORDER BY fetched_at DESC "
        "LIMIT 1"
    )
    row = conn.execute(feed_sql, {"asset_id": asset_id}).fetchone()
    if row and row.last_price is not None:
        fetched_at = row.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600.0
        if age_hours <= 24.0:
            price = Decimal(str(row.last_price))
            logger.debug(
                "get_price: asset_id=%s price=%s source=exchange_price_feed (age=%.1fh, tier2)",
                asset_id,
                price,
                age_hours,
            )
            return price
        logger.debug(
            "get_price: exchange_price_feed stale (%.1fh) for asset_id=%s",
            age_hours,
            asset_id,
        )
    return None


def _get_from_hl_assets_mark_px(conn: Any, asset_id: int) -> Decimal | None:
    """Tier 3 (VM only): query hl_assets.mark_px via dim_listings join.

    Resolves the HL asset_id for the given CMC asset_id using dim_listings
    (venue = 'HYPERLIQUID'), then reads mark_px from hyperliquid.hl_assets.
    Returns Decimal or None if no HL asset is found.
    """
    # Resolve CMC asset_id -> HL asset_id via dim_listings
    listing_sql = text(
        """
        SELECT ha.asset_id, ha.mark_px
        FROM hyperliquid.hl_assets ha
        JOIN public.dim_listings dl
            ON dl.ticker_on_venue = ha.symbol
        WHERE dl.id = :asset_id
          AND dl.venue = 'HYPERLIQUID'
          AND ha.mark_px IS NOT NULL
        LIMIT 1
        """
    )
    row = conn.execute(listing_sql, {"asset_id": asset_id}).fetchone()
    if row and row.mark_px is not None:
        price = Decimal(str(row.mark_px))
        logger.debug(
            "get_price: asset_id=%s price=%s source=hl_assets.mark_px (tier3)",
            asset_id,
            price,
        )
        return price
    return None


def _get_from_hl_candles(conn: Any, asset_id: int) -> Decimal | None:
    """Tier 4 (VM only): query latest close from hyperliquid.hl_candles.

    Uses the same dim_listings join to resolve CMC asset_id -> HL asset_id.
    Returns Decimal or None if no HL candle is found.
    """
    candle_sql = text(
        """
        SELECT hc.close
        FROM hyperliquid.hl_candles hc
        JOIN hyperliquid.hl_assets ha ON ha.asset_id = hc.asset_id
        JOIN public.dim_listings dl
            ON dl.ticker_on_venue = ha.symbol
        WHERE dl.id = :asset_id
          AND dl.venue = 'HYPERLIQUID'
        ORDER BY hc.ts DESC
        LIMIT 1
        """
    )
    row = conn.execute(candle_sql, {"asset_id": asset_id}).fetchone()
    if row and row.close is not None:
        price = Decimal(str(row.close))
        logger.debug(
            "get_price: asset_id=%s price=%s source=hl_candles (tier4)",
            asset_id,
            price,
        )
        return price
    return None


def _get_from_price_bars(conn: Any, asset_id: int) -> Decimal | None:
    """Tier 5 (local only): query latest daily close from price_bars_multi_tf_u.

    Returns Decimal or None if no bar is found.
    """
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
            "get_current_price: asset_id=%s price=%s source=price_bars_multi_tf_u (tier5)",
            asset_id,
            price,
        )
        return price
    return None


# ---------------------------------------------------------------------------
# PositionSizer
# ---------------------------------------------------------------------------


class PositionSizer:
    """
    Position sizing calculator with optional VM-aware price resolution.

    The class can be used in two modes:

    **Stateless (original behaviour)**
        All public methods are static and accept values directly.  Instantiation
        is not required.  This mode is the default and is fully backward-compatible.

    **Stateful with PriceCache / VM mode**
        Pass ``price_cache`` and/or ``vm_mode=True`` to ``__init__`` to enable
        the extended price fallback chain in ``get_current_price()``.

        ``price_cache`` is a ``PriceCache`` instance (from ``ws_feeds``) that
        provides sub-second WebSocket prices.  When provided it is consulted
        first (Tier 1) before any DB queries.

        ``vm_mode=True`` activates Tiers 3-4 (HL collector tables) and skips
        Tier 5 (``price_bars_multi_tf_u``) which does not exist on the VM.

    Parameters
    ----------
    price_cache : PriceCache | None
        Optional shared price cache from WebSocket feeds.  When provided,
        ``get_current_price`` checks it first.
    vm_mode : bool
        When True, use HL collector tables as fallback and skip
        ``price_bars_multi_tf_u``.  Default False (local mode).
    """

    def __init__(
        self,
        price_cache: "PriceCache | None" = None,
        vm_mode: bool = False,
    ) -> None:
        self._price_cache = price_cache
        self._vm_mode = vm_mode

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
        **kwargs: Any,
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
        **kwargs : Any
            Additional keyword arguments passed from the caller.
            garch_vol : float | None
                GARCH blended daily conditional vol (decimal, e.g. 0.02 = 2% daily vol).
                Used when sizing_mode='target_vol'. Passed by paper_executor via
                get_blended_vol(). MUST be a daily vol -- annualized internally via
                sqrt(252) before computing the vol scalar.
                If None or not provided, target_vol falls back to fixed_fraction.
            conn : sqlalchemy connection | None
                Active DB connection. Required for sizing_mode='bl_weight' to look
                up the most recent BL weight from portfolio_allocations.
            asset_id : int | None
                Asset identifier. Required for sizing_mode='bl_weight'.

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

        elif sizing_mode == "target_vol":
            # Scale position fraction so realized portfolio vol targets config.target_annual_vol.
            # CRITICAL: garch_vol is daily decimal vol; annualize via sqrt(252) before
            # computing the scalar. Forgetting annualization causes ~15x oversizing.
            target_ann_vol = getattr(config, "target_annual_vol", None)
            garch_vol = kwargs.get("garch_vol")

            if target_ann_vol and target_ann_vol > 0 and garch_vol:
                # Annualize daily GARCH vol: daily_vol * sqrt(252)
                current_ann_vol = float(garch_vol) * (252**0.5)
                if current_ann_vol > 1e-6:
                    vol_scalar = float(target_ann_vol) / current_ann_vol
                    fraction = Decimal(str(config.position_fraction)) * Decimal(
                        str(vol_scalar)
                    )
                else:
                    # Near-zero vol: fallback to fixed_fraction
                    fraction = Decimal(str(config.position_fraction))
                    logger.warning(
                        "compute_target_position: target_vol -- current_ann_vol near "
                        "zero (%.8f), using fixed_fraction",
                        current_ann_vol,
                    )
            else:
                # Fallback: no GARCH vol available or target not configured
                fraction = Decimal(str(config.position_fraction))
                if target_ann_vol and not garch_vol:
                    logger.info(
                        "compute_target_position: target_vol -- no garch_vol provided, "
                        "falling back to fixed_fraction"
                    )

        elif sizing_mode == "bl_weight":
            # Look up the most recent BL weight from portfolio_allocations.
            # Caller MUST pass conn and asset_id via kwargs (paper_executor does this).
            # When BL de-selects an asset (weight=0 or no row), return 0 immediately
            # so the executor closes any open position rather than holding stale sizing.
            conn = kwargs.get("conn")
            asset_id = kwargs.get("asset_id")
            if conn is not None and asset_id is not None:
                bl_sql = text(
                    "SELECT COALESCE(final_weight, weight) AS bl_weight "
                    "FROM public.portfolio_allocations "
                    "WHERE asset_id = :asset_id AND optimizer = 'bl' "
                    "ORDER BY ts DESC LIMIT 1"
                )
                row = conn.execute(bl_sql, {"asset_id": asset_id}).fetchone()
                if row and row.bl_weight is not None and float(row.bl_weight) > 0:
                    fraction = Decimal(str(row.bl_weight))
                    logger.debug(
                        "compute_target_position: bl_weight=%.6f for asset_id=%s",
                        float(fraction),
                        asset_id,
                    )
                else:
                    # BL de-selected or no BL row: close position (return 0)
                    logger.info(
                        "compute_target_position: bl_weight=0 or missing for "
                        "asset_id=%s, returning flat",
                        asset_id,
                    )
                    return Decimal("0")
            else:
                # No connection provided: fall back to fixed_fraction
                logger.warning(
                    "compute_target_position: bl_weight mode but conn/asset_id not "
                    "provided, falling back to fixed_fraction"
                )
                # fraction already set to config.position_fraction above

        # else: fixed_fraction -- no adjustment

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
        Retrieve the most recent price for an asset (local mode).

        Tries exchange_price_feed first (real-time). Falls back to the most recent
        daily bar close from price_bars_multi_tf_u when the feed is stale (>24h)
        or missing.

        This static method is the original 2-tier implementation.  For the
        VM-aware 5-tier chain, instantiate PositionSizer with ``vm_mode=True``
        and/or a ``PriceCache`` and call ``get_price(conn, asset_id)`` instead.

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
        return PositionSizer._get_price_from_feed_or_bars(conn, asset_id)

    def get_price(self, conn: Any, asset_id: int) -> Decimal:
        """
        Retrieve the most recent price via the VM-aware 5-tier fallback chain.

        Tier 1: PriceCache (WebSocket live tick, sub-second) — only when
                ``self._price_cache`` is set.  Symbol is resolved via
                ``_resolve_symbol(asset_id, conn)`` before cache lookup.
        Tier 2: exchange_price_feed (REST snapshot, existing logic, unchanged).
        Tier 3: hl_assets.mark_px (HL collector, updated every ~6h)
                — only when ``self._vm_mode`` is True.
        Tier 4: hl_candles latest close (HL bar data, last resort)
                — only when ``self._vm_mode`` is True.
        Tier 5: price_bars_multi_tf_u (local daily bar close)
                — skipped when ``self._vm_mode`` is True (table absent on VM).

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
            When no price is available from any tier.
        """
        # --- Tier 1: PriceCache (WebSocket) ---
        if self._price_cache is not None:
            symbol = _resolve_symbol(asset_id, conn)
            if symbol:
                price = self._price_cache.get(symbol)
                if price is not None:
                    logger.debug(
                        "get_price: asset_id=%s symbol=%s price=%s source=price_cache (tier1)",
                        asset_id,
                        symbol,
                        price,
                    )
                    return price
                logger.debug(
                    "get_price: price_cache miss for symbol=%s asset_id=%s",
                    symbol,
                    asset_id,
                )

        # --- Tier 2: exchange_price_feed ---
        try:
            price = _get_from_exchange_price_feed(conn, asset_id)
            if price is not None:
                return price
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "get_price: exchange_price_feed unavailable (%s), continuing", exc
            )

        # --- VM-only tiers ---
        if self._vm_mode:
            # Tier 3: hl_assets.mark_px
            try:
                price = _get_from_hl_assets_mark_px(conn, asset_id)
                if price is not None:
                    return price
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "get_price: hl_assets.mark_px unavailable (%s), continuing", exc
                )

            # Tier 4: hl_candles latest close
            try:
                price = _get_from_hl_candles(conn, asset_id)
                if price is not None:
                    return price
            except Exception as exc:  # noqa: BLE001
                logger.debug("get_price: hl_candles unavailable (%s), continuing", exc)

            raise ValueError(
                f"No price available for asset_id={asset_id} from any VM source "
                f"(price_cache, exchange_price_feed, hl_assets, hl_candles)."
            )

        # --- Tier 5: price_bars_multi_tf_u (local only) ---
        price = _get_from_price_bars(conn, asset_id)
        if price is not None:
            return price

        raise ValueError(f"No price available for asset_id={asset_id} from any source.")

    # ------------------------------------------------------------------
    # Internal: original 2-tier implementation (kept for static compat)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_price_from_feed_or_bars(conn: Any, asset_id: int) -> Decimal:
        """Original 2-tier price lookup used by the static get_current_price()."""
        # Try live feed first
        try:
            price = _get_from_exchange_price_feed(conn, asset_id)
            if price is not None:
                return price
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "get_current_price: exchange_price_feed unavailable (%s), using bar fallback",
                exc,
            )

        # Fall back to daily bar close
        price = _get_from_price_bars(conn, asset_id)
        if price is not None:
            return price

        raise ValueError(f"No price available for asset_id={asset_id} from any source.")
