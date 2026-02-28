"""TurnoverTracker: compute turnover cost and decompose gross vs net return.

Estimates the transaction cost incurred when rebalancing and tracks
cumulative cost over the strategy lifetime.

Config section: rebalancing
  fee_bps (float, default 10.0): one-way estimated cost in basis points.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TurnoverTracker:
    """Track portfolio turnover and decompose return into gross/cost/net.

    Parameters
    ----------
    config : dict, optional
        Full portfolio config dict. Reads ``rebalancing.fee_bps``.
        If None, defaults to fee_bps=10.0.
    """

    def __init__(self, config: dict | None = None) -> None:
        reb_cfg = (config or {}).get("rebalancing", {})
        self.fee_bps: float = float(reb_cfg.get("fee_bps", 10.0))
        self.history: list[dict[str, Any]] = []
        logger.debug("TurnoverTracker initialised: fee_bps=%.1f", self.fee_bps)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute(
        self,
        old_weights: dict[Any, float],
        new_weights: dict[Any, float],
        portfolio_value: float,
    ) -> dict[str, Any]:
        """Compute turnover and cost between two weight dictionaries.

        Parameters
        ----------
        old_weights : dict
            Previous portfolio weights keyed by asset ID.
        new_weights : dict
            Target portfolio weights keyed by asset ID.
        portfolio_value : float
            Total portfolio notional value in base currency.

        Returns
        -------
        dict
            Keys: turnover_pct, cost_pct, notional_cost, n_buys, n_sells.
        """
        all_assets = set(old_weights) | set(new_weights)

        turnover_pct = 0.0
        n_buys = 0
        n_sells = 0

        for asset in all_assets:
            old_w = old_weights.get(asset, 0.0)
            new_w = new_weights.get(asset, 0.0)
            delta = new_w - old_w
            turnover_pct += abs(delta)
            if delta > 0:
                n_buys += 1
            elif delta < 0:
                n_sells += 1

        cost_pct = turnover_pct * self.fee_bps / 10_000.0
        notional_cost = portfolio_value * cost_pct

        return {
            "turnover_pct": turnover_pct,
            "cost_pct": cost_pct,
            "notional_cost": notional_cost,
            "n_buys": n_buys,
            "n_sells": n_sells,
        }

    # ------------------------------------------------------------------
    # Tracking over time
    # ------------------------------------------------------------------

    def track(
        self,
        ts: Any,
        old_weights: dict[Any, float],
        new_weights: dict[Any, float],
        gross_return: float,
        portfolio_value: float,
    ) -> dict[str, Any]:
        """Compute costs and record a gross/net return entry in history.

        Parameters
        ----------
        ts : any
            Timestamp or period identifier for this rebalance.
        old_weights : dict
            Previous portfolio weights.
        new_weights : dict
            Target portfolio weights.
        gross_return : float
            Gross period return (e.g., 0.02 = 2%).
        portfolio_value : float
            Portfolio notional at the start of this period.

        Returns
        -------
        dict
            Full cost/return decomposition record appended to self.history.
        """
        cost_result = self.compute(old_weights, new_weights, portfolio_value)
        record: dict[str, Any] = {
            "ts": ts,
            "gross_return": gross_return,
            "cost_pct": cost_result["cost_pct"],
            "net_return": gross_return - cost_result["cost_pct"],
            "turnover_pct": cost_result["turnover_pct"],
            "notional_cost": cost_result["notional_cost"],
        }
        self.history.append(record)
        logger.debug(
            "Tracked ts=%s: gross=%.4f, cost=%.6f, net=%.4f",
            ts,
            gross_return,
            cost_result["cost_pct"],
            record["net_return"],
        )
        return record

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @property
    def cumulative_costs(self) -> float:
        """Total notional cost across all tracked rebalances."""
        return sum(r["notional_cost"] for r in self.history)
