"""StopLadder: multi-tier stop-loss and take-profit exit scaling (PORT-05).

Implements the stop laddering requirement from CONTEXT.md: "Stop laddering:
Configurable at per-asset x per-strategy granularity."

Override resolution order (later wins):
  1. defaults
  2. per_strategy_overrides[strategy]
  3. per_asset_overrides[str(asset_id)]
  4. per_asset_overrides["{asset_id}:{strategy}"]  (most specific)

Config section: stop_laddering
  enabled (bool):          globally enable/disable
  defaults:
    sl_stops (list[float]): adverse move fractions e.g. [0.02, 0.03, 0.05]
    tp_stops (list[float]): favorable move fractions e.g. [0.03, 0.05, 0.10]
    sl_sizes (list[float]): position fraction to exit at each SL tier (sum=1)
    tp_sizes (list[float]): position fraction to exit at each TP tier (sum=1)
  per_strategy_overrides (dict): strategy_name -> partial override dict
  per_asset_overrides    (dict): str(asset_id) or "{asset_id}:{strategy}" -> partial override dict
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Tolerance for validating that tier sizes sum to 1.0
_SUM_TOLERANCE = 0.01

# Default ladder if no config is provided at all
_BUILTIN_DEFAULTS: dict[str, Any] = {
    "sl_stops": [0.02, 0.03, 0.05],
    "tp_stops": [0.03, 0.05, 0.10],
    "sl_sizes": [0.33, 0.33, 0.34],
    "tp_sizes": [0.33, 0.33, 0.34],
}


def _validate_tiers(tier_config: dict[str, Any], source: str) -> None:
    """Validate that stop/size lists are consistent and sizes sum to ~1.0."""
    sl_stops = tier_config.get("sl_stops", [])
    tp_stops = tier_config.get("tp_stops", [])
    sl_sizes = tier_config.get("sl_sizes", [])
    tp_sizes = tier_config.get("tp_sizes", [])

    if sl_stops and sl_sizes and len(sl_stops) != len(sl_sizes):
        raise ValueError(
            f"[{source}] sl_stops length ({len(sl_stops)}) != "
            f"sl_sizes length ({len(sl_sizes)})"
        )
    if tp_stops and tp_sizes and len(tp_stops) != len(tp_sizes):
        raise ValueError(
            f"[{source}] tp_stops length ({len(tp_stops)}) != "
            f"tp_sizes length ({len(tp_sizes)})"
        )
    if sl_sizes and abs(sum(sl_sizes) - 1.0) > _SUM_TOLERANCE:
        raise ValueError(
            f"[{source}] sl_sizes sum to {sum(sl_sizes):.4f}, expected ~1.0"
        )
    if tp_sizes and abs(sum(tp_sizes) - 1.0) > _SUM_TOLERANCE:
        raise ValueError(
            f"[{source}] tp_sizes sum to {sum(tp_sizes):.4f}, expected ~1.0"
        )


class StopLadder:
    """Compute and track multi-tier SL/TP exit schedules.

    Parameters
    ----------
    config : dict, optional
        Full portfolio config dict. Reads ``stop_laddering`` section.
        If None, calls load_portfolio_config() from portfolio.__init__.
    """

    def __init__(self, config: dict | None = None) -> None:
        if config is None:
            from ta_lab2.portfolio import load_portfolio_config

            config = load_portfolio_config()

        sl_cfg = config.get("stop_laddering", {})
        self.enabled: bool = bool(sl_cfg.get("enabled", True))

        # Merge user-supplied defaults over the hard-coded builtins
        user_defaults = sl_cfg.get("defaults", {})
        merged: dict[str, Any] = deepcopy(_BUILTIN_DEFAULTS)
        merged.update(user_defaults)
        _validate_tiers(merged, "defaults")
        self._defaults: dict[str, Any] = merged

        self._per_strategy: dict[str, dict[str, Any]] = dict(
            sl_cfg.get("per_strategy_overrides", {}) or {}
        )
        self._per_asset: dict[str, dict[str, Any]] = dict(
            sl_cfg.get("per_asset_overrides", {}) or {}
        )

        # Validate all stored overrides up front
        for name, override in self._per_strategy.items():
            _validate_tiers(override, f"per_strategy_overrides[{name}]")
        for key, override in self._per_asset.items():
            _validate_tiers(override, f"per_asset_overrides[{key}]")

        logger.debug(
            "StopLadder initialised: enabled=%s, %d SL tiers, %d TP tiers",
            self.enabled,
            len(self._defaults["sl_stops"]),
            len(self._defaults["tp_stops"]),
        )

    # ------------------------------------------------------------------
    # DB-seeded constructor
    # ------------------------------------------------------------------

    @classmethod
    def from_db_calibrations(
        cls,
        engine: Engine,
        config: dict | None = None,
    ) -> StopLadder:
        """Construct a StopLadder with per-asset overrides from stop_calibrations.

        Queries all rows from public.stop_calibrations and injects them into
        the ladder's _per_asset dict using the "{id}:{strategy}" combined key
        format (most-specific layer, overrides all others for that combination).

        Stop levels from the DB:
          sl_stops = [sl_p25, sl_p50, sl_p75]  -- tight to wide (3 tiers)
          tp_stops = [tp_p50, tp_p75]           -- conservative to aggressive (2 tiers)
          sl_sizes = [0.33, 0.33, 0.34]         -- equal weight across SL tiers
          tp_sizes = [0.50, 0.50]               -- equal weight across TP tiers

        Assets not present in stop_calibrations fall back to global defaults
        from portfolio.yaml (the normal StopLadder behavior).

        Parameters
        ----------
        engine : sqlalchemy.engine.Engine
            Active SQLAlchemy engine. Use NullPool for batch scripts.
        config : dict, optional
            Full portfolio config dict. If None, loads from portfolio.yaml.

        Returns
        -------
        StopLadder
            Ladder instance with DB-calibrated per-asset-strategy overrides merged in.
        """
        from sqlalchemy import text

        ladder = cls(config=config)

        sql = text(
            """
            SELECT id, strategy, sl_p25, sl_p50, sl_p75, tp_p50, tp_p75
            FROM public.stop_calibrations
            ORDER BY id, strategy
            """
        )

        try:
            with engine.connect() as conn:
                rows = conn.execute(sql).fetchall()
        except Exception as exc:
            logger.warning(
                "StopLadder.from_db_calibrations: DB query failed -- "
                "returning ladder with no DB overrides: %s",
                exc,
            )
            return ladder

        loaded = 0
        for row in rows:
            asset_id, strategy, sl_p25, sl_p50, sl_p75, tp_p50, tp_p75 = (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
            )

            # Build the combined key used by get_tiers() layer 4
            combined_key = f"{asset_id}:{strategy}"

            # Validate that we have the needed values before building the override
            sl_stops = [float(v) for v in (sl_p25, sl_p50, sl_p75) if v is not None]
            tp_stops = [float(v) for v in (tp_p50, tp_p75) if v is not None]

            if not sl_stops or not tp_stops:
                logger.debug(
                    "StopLadder.from_db_calibrations: skipping key=%s -- "
                    "missing sl or tp values",
                    combined_key,
                )
                continue

            # Equal-weight sizing: 3 SL tiers, 2 TP tiers
            if len(sl_stops) == 3:
                sl_sizes = [0.33, 0.33, 0.34]
            else:
                # Fallback for partial rows: equal weight
                n = len(sl_stops)
                base = round(1.0 / n, 4)
                sl_sizes = [base] * (n - 1) + [round(1.0 - base * (n - 1), 4)]

            if len(tp_stops) == 2:
                tp_sizes = [0.50, 0.50]
            else:
                n = len(tp_stops)
                base = round(1.0 / n, 4)
                tp_sizes = [base] * (n - 1) + [round(1.0 - base * (n - 1), 4)]

            override: dict[str, Any] = {
                "sl_stops": sl_stops,
                "tp_stops": tp_stops,
                "sl_sizes": sl_sizes,
                "tp_sizes": tp_sizes,
            }

            try:
                _validate_tiers(override, f"stop_calibrations[{combined_key}]")
            except ValueError as exc:
                logger.warning(
                    "StopLadder.from_db_calibrations: invalid tiers for key=%s: %s",
                    combined_key,
                    exc,
                )
                continue

            ladder._per_asset[combined_key] = override
            loaded += 1

        logger.info(
            "StopLadder.from_db_calibrations: loaded %d per-asset-strategy overrides",
            loaded,
        )
        return ladder

    # ------------------------------------------------------------------
    # Tier resolution
    # ------------------------------------------------------------------

    def get_tiers(
        self,
        asset_id: int,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        """Resolve the effective stop ladder config for asset + strategy.

        Resolution order (later overrides earlier):
          1. defaults
          2. per_strategy_overrides[strategy]
          3. per_asset_overrides[str(asset_id)]
          4. per_asset_overrides["{asset_id}:{strategy}"]

        Parameters
        ----------
        asset_id : int
            Numeric asset identifier.
        strategy : str, optional
            Strategy name (e.g. 'rsi', 'ema_crossover').

        Returns
        -------
        dict
            Keys: sl_stops, tp_stops, sl_sizes, tp_sizes.
        """
        tiers: dict[str, Any] = deepcopy(self._defaults)

        # Layer 2: per-strategy override
        if strategy and strategy in self._per_strategy:
            override = self._per_strategy[strategy]
            tiers.update({k: v for k, v in override.items() if v is not None})
            logger.debug(
                "StopLadder: applied per_strategy_overrides[%s] for asset=%d",
                strategy,
                asset_id,
            )

        # Layer 3: per-asset override (asset_id as string key)
        asset_key = str(asset_id)
        if asset_key in self._per_asset:
            override = self._per_asset[asset_key]
            tiers.update({k: v for k, v in override.items() if v is not None})
            logger.debug(
                "StopLadder: applied per_asset_overrides[%s]",
                asset_key,
            )

        # Layer 4: combined per-asset x per-strategy key (most specific)
        if strategy:
            combined_key = f"{asset_id}:{strategy}"
            if combined_key in self._per_asset:
                override = self._per_asset[combined_key]
                tiers.update({k: v for k, v in override.items() if v is not None})
                logger.debug(
                    "StopLadder: applied per_asset_overrides[%s] (combined key)",
                    combined_key,
                )

        return tiers

    # ------------------------------------------------------------------
    # Exit schedule computation
    # ------------------------------------------------------------------

    def compute_exit_schedule(
        self,
        entry_price: float,
        side: int,
        asset_id: int,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        """Compute concrete SL/TP price levels for a position.

        Parameters
        ----------
        entry_price : float
            Position entry price.
        side : int
            +1 for long, -1 for short.
        asset_id : int
            Numeric asset identifier for tier resolution.
        strategy : str, optional
            Strategy name for tier resolution.

        Returns
        -------
        dict
            Keys: sl_levels, tp_levels, entry_price, side.
            sl_levels and tp_levels are lists of dicts with
            {price, size_frac, tier}.
        """
        tiers = self.get_tiers(asset_id, strategy)
        sl_stops = tiers["sl_stops"]
        tp_stops = tiers["tp_stops"]
        sl_sizes = tiers["sl_sizes"]
        tp_sizes = tiers["tp_sizes"]

        sl_levels = []
        for i, (stop, size) in enumerate(zip(sl_stops, sl_sizes), start=1):
            if side == 1:  # long: adverse = below entry
                price = entry_price * (1.0 - stop)
            else:  # short: adverse = above entry
                price = entry_price * (1.0 + stop)
            sl_levels.append({"price": price, "size_frac": size, "tier": i})

        tp_levels = []
        for i, (stop, size) in enumerate(zip(tp_stops, tp_sizes), start=1):
            if side == 1:  # long: favorable = above entry
                price = entry_price * (1.0 + stop)
            else:  # short: favorable = below entry
                price = entry_price * (1.0 - stop)
            tp_levels.append({"price": price, "size_frac": size, "tier": i})

        return {
            "sl_levels": sl_levels,
            "tp_levels": tp_levels,
            "entry_price": entry_price,
            "side": side,
        }

    # ------------------------------------------------------------------
    # Trigger checking
    # ------------------------------------------------------------------

    def check_triggers(
        self,
        current_price: float,
        entry_price: float,
        side: int,
        asset_id: int,
        strategy: str | None = None,
        already_triggered: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Identify which stop/TP tiers are newly triggered at current_price.

        Parameters
        ----------
        current_price : float
            Latest market price.
        entry_price : float
            Original entry price for the position.
        side : int
            +1 for long, -1 for short.
        asset_id : int
            Numeric asset identifier.
        strategy : str, optional
            Strategy name for tier resolution.
        already_triggered : set, optional
            Set of tier identifiers already executed, formatted as
            "sl_{tier}" or "tp_{tier}". Avoids re-triggering.

        Returns
        -------
        list[dict]
            Newly triggered tiers: [{type, tier, price, size_frac}, ...].
        """
        if already_triggered is None:
            already_triggered = set()

        schedule = self.compute_exit_schedule(entry_price, side, asset_id, strategy)
        newly_triggered: list[dict[str, Any]] = []

        # Check SL tiers
        for level in schedule["sl_levels"]:
            tier_key = f"sl_{level['tier']}"
            if tier_key in already_triggered:
                continue
            # Long: SL fires when price drops to or below sl level
            # Short: SL fires when price rises to or above sl level
            if (side == 1 and current_price <= level["price"]) or (
                side == -1 and current_price >= level["price"]
            ):
                newly_triggered.append(
                    {
                        "type": "sl",
                        "tier": level["tier"],
                        "price": level["price"],
                        "size_frac": level["size_frac"],
                    }
                )

        # Check TP tiers
        for level in schedule["tp_levels"]:
            tier_key = f"tp_{level['tier']}"
            if tier_key in already_triggered:
                continue
            # Long: TP fires when price rises to or above tp level
            # Short: TP fires when price drops to or below tp level
            if (side == 1 and current_price >= level["price"]) or (
                side == -1 and current_price <= level["price"]
            ):
                newly_triggered.append(
                    {
                        "type": "tp",
                        "tier": level["tier"],
                        "price": level["price"],
                        "size_frac": level["size_frac"],
                    }
                )

        return newly_triggered
