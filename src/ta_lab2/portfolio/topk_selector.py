"""TopkDropoutSelector: top-K asset selection with turnover-controlled dropout.

Selects the top-K scoring assets and replaces only N worst held assets per
rebalance period. This limits turnover to at most N sells + N buys per cycle,
regardless of how many assets are ranked above the current holdings.

Config section: topk_selection
  topk   (int, default 10): number of assets to hold
  n_drop (int, default 2):  maximum number to swap per rebalance
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

import pandas as pd

logger = logging.getLogger(__name__)


class TopkDropoutSelector:
    """Select top-K assets with controlled dropout (at most N replacements per cycle).

    Parameters
    ----------
    config : dict, optional
        Full portfolio config dict. Reads ``topk_selection`` section.
        If None, uses default topk=10, n_drop=2.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = (config or {}).get("topk_selection", {})
        self.topk: int = int(cfg.get("topk", 10))
        self.n_drop: int = int(cfg.get("n_drop", 2))
        logger.debug(
            "TopkDropoutSelector initialised: topk=%d, n_drop=%d",
            self.topk,
            self.n_drop,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(
        self,
        scores: pd.Series,
        current_holdings: set,
    ) -> tuple[set, set]:
        """Determine which assets to buy and sell this rebalance.

        Parameters
        ----------
        scores : pd.Series
            Index = asset IDs (any hashable), values = signal scores.
            Higher score means more bullish / preferred.
        current_holdings : set
            Set of asset IDs currently held.

        Returns
        -------
        (to_buy, to_sell) : tuple[set, set]
            Asset IDs to open (to_buy) and close (to_sell).
            Both sets are bounded to at most n_drop entries unless this is
            an initial portfolio construction (current_holdings is empty).
        """
        if scores.empty:
            logger.warning(
                "TopkDropoutSelector.select: scores is empty, returning no action"
            )
            return set(), set()

        k = min(self.topk, len(scores))
        sorted_desc = scores.sort_values(ascending=False)

        # Top-K set by score
        top_assets: set = set(sorted_desc.iloc[:k].index)

        # Empty holdings = initial construction: buy top-K, sell nothing
        if not current_holdings:
            n_buy = len(top_assets)
            logger.info(
                "TopK: %d, dropping 0 (initial portfolio), buying %d", self.topk, n_buy
            )
            return set(top_assets), set()

        # Held assets that fell outside the top-K window
        held_below: set = current_holdings - top_assets

        # Sort held_below by score ascending (worst first)
        held_below_scores = scores.reindex(list(held_below)).sort_values(ascending=True)
        n_sell = min(self.n_drop, len(held_below_scores))
        to_sell: set = set(held_below_scores.iloc[:n_sell].index)

        # Buy replacements: top_assets not already held, best first
        candidates = sorted_desc[sorted_desc.index.isin(top_assets - current_holdings)]
        to_buy: set = set(candidates.iloc[: len(to_sell)].index)

        logger.info(
            "TopK: %d, dropping %d, buying %d", self.topk, len(to_sell), len(to_buy)
        )
        return to_buy, to_sell

    def get_target_universe(self, scores: pd.Series) -> set:
        """Return the top-K asset IDs by score, ignoring current holdings.

        Useful for initial portfolio construction or universe filtering
        upstream of the optimizer.

        Parameters
        ----------
        scores : pd.Series
            Index = asset IDs, values = signal scores.

        Returns
        -------
        set
            Top-K asset IDs (or fewer if scores has fewer entries).
        """
        if scores.empty:
            return set()
        k = min(self.topk, len(scores))
        return set(scores.nlargest(k).index)
