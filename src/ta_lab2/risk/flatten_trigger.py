"""
Flatten trigger evaluation for tail risk policy.

Pure evaluation module -- no database or numerical library dependencies.
Evaluates 4 trigger types in priority order and returns EscalationState.

Thresholds are calibrated from BTC 2010-2025 (5613 bars):
  - reduce_vol_threshold   = 0.0923  (mean + 2*std of 20d rolling vol, ~5.3% of days)
  - flatten_vol_threshold  = 0.1194  (mean + 3*std, ~2.3% of days)
  - flatten_abs_return     = 0.15    (|daily return| > 15%, ~1.8% of days)
  - flatten_corr_breakdown = -0.20   (BTC/ETH 30d rolling correlation, ~5th percentile)

Usage:
    from ta_lab2.risk.flatten_trigger import (
        EscalationState, FlattenTriggerResult, check_flatten_trigger,
    )

    result = check_flatten_trigger(
        rolling_vol_20d=0.12,
        latest_daily_return=-0.08,
        api_healthy=True,
        correlation_30d=None,
    )
    if result.state == EscalationState.FLATTEN:
        # Block all new orders
        ...
    elif result.state == EscalationState.REDUCE:
        # Halve buy order quantities
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and data classes
# ---------------------------------------------------------------------------


class EscalationState(str, Enum):
    """
    Three-level tail risk escalation state.

    Values match the dim_risk_state.tail_risk_state CHECK constraint:
      normal  -- no elevated risk, full position sizing
      reduce  -- moderate risk, buy orders halved
      flatten -- extreme risk, all new orders blocked
    """

    NORMAL = "normal"
    REDUCE = "reduce"
    FLATTEN = "flatten"


@dataclass
class FlattenTriggerResult:
    """
    Result of check_flatten_trigger().

    Attributes:
        state:           Highest-severity escalation state that triggered.
        trigger_type:    Which condition fired: "vol_spike", "abs_return",
                         "exchange_halt", "correlation_breakdown", or None (NORMAL).
        trigger_value:   Actual metric value that breached the threshold (e.g. 0.13
                         for vol, -0.22 for a daily return). None when state is NORMAL.
        threshold_used:  The specific threshold that was breached.
        details:         Human-readable explanation with actual formatted values.
    """

    state: EscalationState
    trigger_type: Optional[str]
    trigger_value: Optional[float]
    threshold_used: float
    details: str


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


def check_flatten_trigger(
    rolling_vol_20d: float,
    latest_daily_return: float,
    api_healthy: bool = True,
    correlation_30d: Optional[float] = None,
    reduce_vol_threshold: float = 0.0923,
    flatten_vol_threshold: float = 0.1194,
    flatten_abs_return_threshold: float = 0.15,
    flatten_corr_breakdown_threshold: float = -0.20,
) -> FlattenTriggerResult:
    """
    Evaluate current market conditions against flatten/reduce trigger thresholds.

    Triggers are checked in strict priority order (highest severity first).
    The first matching trigger defines the returned state and trigger_type.

    Priority order:
      1. FLATTEN: exchange halt          -- api_healthy == False
      2. FLATTEN: extreme daily return   -- abs(latest_daily_return) > flatten_abs_return_threshold
      3. FLATTEN: vol spike (3-sigma)    -- rolling_vol_20d > flatten_vol_threshold
      4. FLATTEN: correlation breakdown  -- correlation_30d < flatten_corr_breakdown_threshold
      5. REDUCE:  vol spike (2-sigma)    -- rolling_vol_20d > reduce_vol_threshold
      6. NORMAL:  no triggers fired

    Args:
        rolling_vol_20d:               20-day rolling standard deviation of daily returns.
        latest_daily_return:           Most recent daily arithmetic return (signed).
        api_healthy:                   False if the exchange API is unavailable (triggers halt).
        correlation_30d:               30-day rolling BTC/ETH correlation. None = skip check.
        reduce_vol_threshold:          Vol threshold for REDUCE state. Default 0.0923 (mean+2std).
        flatten_vol_threshold:         Vol threshold for FLATTEN state. Default 0.1194 (mean+3std).
        flatten_abs_return_threshold:  Absolute return threshold for FLATTEN. Default 0.15 (15%).
        flatten_corr_breakdown_threshold:
                                       Correlation below which FLATTEN is triggered. Default -0.20.

    Returns:
        FlattenTriggerResult with the highest-severity matching state.
    """
    # ----- Priority 1: Exchange halt ----------------------------------------
    if not api_healthy:
        details = (
            "Exchange API unavailable -- all trading halted until connectivity restored"
        )
        logger.warning("Flatten trigger: %s", details)
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="exchange_halt",
            trigger_value=None,
            threshold_used=0.0,
            details=details,
        )

    # ----- Priority 2: Extreme single-day return ----------------------------
    abs_return = abs(latest_daily_return)
    if abs_return > flatten_abs_return_threshold:
        details = (
            f"Extreme daily return: {latest_daily_return:.2%} "
            f"(|{abs_return:.2%}| > threshold {flatten_abs_return_threshold:.2%})"
        )
        logger.warning("Flatten trigger: %s", details)
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="abs_return",
            trigger_value=latest_daily_return,
            threshold_used=flatten_abs_return_threshold,
            details=details,
        )

    # ----- Priority 3: Vol spike -- 3-sigma (FLATTEN) -----------------------
    if rolling_vol_20d > flatten_vol_threshold:
        details = (
            f"Vol spike (3-sigma): 20d vol {rolling_vol_20d:.2%} "
            f"> flatten threshold {flatten_vol_threshold:.2%}"
        )
        logger.warning("Flatten trigger: %s", details)
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="vol_spike",
            trigger_value=rolling_vol_20d,
            threshold_used=flatten_vol_threshold,
            details=details,
        )

    # ----- Priority 4: Correlation breakdown --------------------------------
    if (
        correlation_30d is not None
        and correlation_30d < flatten_corr_breakdown_threshold
    ):
        details = (
            f"Correlation breakdown: BTC/ETH 30d correlation {correlation_30d:.2f} "
            f"< threshold {flatten_corr_breakdown_threshold:.2f}"
        )
        logger.warning("Flatten trigger: %s", details)
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="correlation_breakdown",
            trigger_value=correlation_30d,
            threshold_used=flatten_corr_breakdown_threshold,
            details=details,
        )

    # ----- Priority 5: Vol spike -- 2-sigma (REDUCE) ------------------------
    if rolling_vol_20d > reduce_vol_threshold:
        details = (
            f"Vol spike (2-sigma): 20d vol {rolling_vol_20d:.2%} "
            f"> reduce threshold {reduce_vol_threshold:.2%} "
            f"(below flatten threshold {flatten_vol_threshold:.2%})"
        )
        logger.info("Reduce trigger: %s", details)
        return FlattenTriggerResult(
            state=EscalationState.REDUCE,
            trigger_type="vol_spike",
            trigger_value=rolling_vol_20d,
            threshold_used=reduce_vol_threshold,
            details=details,
        )

    # ----- Priority 6: Normal -----------------------------------------------
    details = (
        f"No triggers: 20d vol {rolling_vol_20d:.2%} "
        f"(< reduce threshold {reduce_vol_threshold:.2%}), "
        f"daily return {latest_daily_return:.2%}"
    )
    logger.debug("No flatten trigger: %s", details)
    return FlattenTriggerResult(
        state=EscalationState.NORMAL,
        trigger_type=None,
        trigger_value=None,
        threshold_used=0.0,
        details=details,
    )
