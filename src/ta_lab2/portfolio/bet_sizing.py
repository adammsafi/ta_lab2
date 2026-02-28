"""
Probability-based bet sizing module.

Implements the de Prado (AFML, Chapter 10) formula for mapping a signal
probability to a scalar bet size, plus a BetSizer class that applies the
formula to optimizer output weights.

ASCII-only file -- no UTF-8 box-drawing characters.
"""

from __future__ import annotations

import logging
from typing import Optional

from scipy.stats import norm

from ta_lab2.portfolio import load_portfolio_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standalone function
# ---------------------------------------------------------------------------


def probability_bet_size(
    signal_probability: float,
    side: int,
    w: float = 2.0,
) -> float:
    """
    Map signal probability to a scalar bet size.

    Formula (de Prado, AFML Chapter 10):
        z = (signal_probability - 0.5) * w
        bet_size = side * (2 * N(z) - 1)

    where N() is the standard normal CDF.

    Properties
    ----------
    - At prob=0.5 -> bet_size = 0   (no edge, no position).
    - At prob=1.0 -> bet_size -> +side (full conviction, approaches 1).
    - At prob=0.0 -> bet_size -> -side (full conviction against).
    - Result is in [-1, +1].

    Parameters
    ----------
    signal_probability : float
        Probability that the signal is correct. Must be in [0, 1].
    side : int
        +1 for long, -1 for short.
    w : float
        Width parameter. Larger w = more aggressive scaling.
        Default 2.0 (matches portfolio.yaml bet_sizing.w_parameter).

    Returns
    -------
    float
        Scalar bet size in [-1, +1].
    """
    z = (signal_probability - 0.5) * w
    return side * (2.0 * norm.cdf(z) - 1.0)


# ---------------------------------------------------------------------------
# BetSizer class
# ---------------------------------------------------------------------------


class BetSizer:
    """
    Scale optimizer weights by signal probability.

    Two modes (portfolio.yaml -> bet_sizing.mode):

    optimizer_first
        final_weight = raw_weight * probability_bet_size(prob, side, w)
        Starts from the optimizer's weight allocation and shrinks it
        proportionally to signal confidence.

    sizing_as_constraints
        Returns (lower, upper) bound dict per asset to feed as weight_bounds
        back into EfficientFrontier.  The bounds are derived from bet size.

    Assets below min_confidence receive zero weight in both modes.
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        if config is None:
            config = load_portfolio_config()

        bs_cfg = config.get("bet_sizing", {})
        self.mode: str = str(bs_cfg.get("mode", "optimizer_first"))
        self.w: float = float(bs_cfg.get("w_parameter", 2.0))
        self.min_confidence: float = float(bs_cfg.get("min_confidence", 0.2))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scale_weights(
        self,
        raw_weights: dict,
        signal_probabilities: dict,
        sides: dict,
    ) -> dict:
        """
        Scale optimizer weights by signal probability.

        Parameters
        ----------
        raw_weights : dict[asset_id, float]
            Optimizer output weights (e.g. from PortfolioOptimizer.run_all()).
        signal_probabilities : dict[asset_id, float]
            P(signal is correct) per asset, in [0, 1].
        sides : dict[asset_id, int]
            +1 for long, -1 for short, per asset.

        Returns
        -------
        dict[asset_id, float]
            Scaled weights.  Assets below min_confidence receive weight 0.
        """
        if self.mode == "optimizer_first":
            return self._scale_optimizer_first(raw_weights, signal_probabilities, sides)
        elif self.mode == "sizing_as_constraints":
            # In constraints mode, scale_weights returns the bound dict,
            # not final weights.  The caller feeds this to compute_bounds
            # or directly to EfficientFrontier(weight_bounds).
            logger.debug(
                "scale_weights: mode='sizing_as_constraints'; returning bounds dict. "
                "Call compute_bounds() directly for explicit bound semantics."
            )
            max_pos = max(raw_weights.values()) if raw_weights else 0.15
            return self.compute_bounds(signal_probabilities, sides, max_pos)
        else:
            logger.warning(
                "scale_weights: unknown mode %r; defaulting to optimizer_first.",
                self.mode,
            )
            return self._scale_optimizer_first(raw_weights, signal_probabilities, sides)

    def compute_bounds(
        self,
        signal_probabilities: dict,
        sides: dict,
        max_position_pct: float,
    ) -> dict:
        """
        Compute per-asset weight bounds from bet sizing for sizing_as_constraints mode.

        Upper bound = max_position_pct * abs(bet_size).
        Lower bound = 0.0 (long-only portfolio).

        Assets below min_confidence get bounds (0, 0) -- excluded.

        Parameters
        ----------
        signal_probabilities : dict[asset_id, float]
            P(signal is correct) per asset.
        sides : dict[asset_id, int]
            +1 or -1 per asset.
        max_position_pct : float
            Absolute position cap from optimizer config.

        Returns
        -------
        dict[asset_id, tuple[float, float]]
            Per-asset (lower_bound, upper_bound).
        """
        bounds = {}
        for asset, prob in signal_probabilities.items():
            if prob < self.min_confidence:
                bounds[asset] = (0.0, 0.0)
                continue

            side = sides.get(asset, 1)
            bet = probability_bet_size(prob, side, self.w)
            upper = max_position_pct * abs(bet)
            bounds[asset] = (0.0, upper)

        return bounds

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scale_optimizer_first(
        self,
        raw_weights: dict,
        signal_probabilities: dict,
        sides: dict,
    ) -> dict:
        """
        optimizer_first mode: final_weight = raw_weight * probability_bet_size(prob, side, w).
        """
        scaled = {}
        for asset, raw_w in raw_weights.items():
            prob = signal_probabilities.get(asset)
            if prob is None or prob < self.min_confidence:
                # Skip assets with no probability or below minimum confidence.
                scaled[asset] = 0.0
                logger.debug(
                    "_scale_optimizer_first: asset=%s excluded (prob=%s < min_confidence=%.2f).",
                    asset,
                    prob,
                    self.min_confidence,
                )
                continue

            side = sides.get(asset, 1)
            bet = probability_bet_size(prob, side, self.w)
            scaled[asset] = raw_w * bet

        return scaled
