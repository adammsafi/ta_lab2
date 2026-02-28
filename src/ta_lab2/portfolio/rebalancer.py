"""RebalanceScheduler: time/signal/threshold-based rebalancing trigger logic.

Determines whether a rebalance should occur at the current timestamp given
portfolio state and signal arrival. Supports three trigger modes:

  time_based        -- rebalance when enough time has elapsed since last rebalance
  signal_driven     -- rebalance whenever a new signal arrives
  threshold_based   -- rebalance when weight drift exceeds a threshold

Config section: rebalancing
  mode            (str,   default 'time_based')
  frequency       (str,   default '1D')       -- used by time_based
  drift_threshold (float, default 0.05)       -- used by threshold_based and optional overlay
  turnover_penalty (bool, default false)      -- passed through; not consumed here
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frequency string to timedelta mapping
# ---------------------------------------------------------------------------

_FREQ_MAP: dict[str, timedelta] = {
    "1D": timedelta(days=1),
    "7D": timedelta(days=7),
    "1W": timedelta(weeks=1),
    "14D": timedelta(days=14),
    "2W": timedelta(weeks=2),
    "30D": timedelta(days=30),
    "1M": timedelta(days=30),
    "60D": timedelta(days=60),
    "2M": timedelta(days=60),
    "90D": timedelta(days=90),
    "3M": timedelta(days=90),
}


class RebalanceScheduler:
    """Determine whether a rebalance should fire at the current timestamp.

    Parameters
    ----------
    config : dict, optional
        Full portfolio config dict. Reads ``rebalancing`` section.
        If None, defaults to mode='time_based', frequency='1D',
        drift_threshold=0.05.
    """

    def __init__(self, config: dict | None = None) -> None:
        reb_cfg = (config or {}).get("rebalancing", {})
        self.mode: str = str(reb_cfg.get("mode", "time_based"))
        self.frequency: timedelta = self.parse_frequency(
            str(reb_cfg.get("frequency", "1D"))
        )
        self.drift_threshold: float = float(reb_cfg.get("drift_threshold", 0.05))
        self.turnover_penalty: bool = bool(reb_cfg.get("turnover_penalty", False))
        logger.debug(
            "RebalanceScheduler initialised: mode=%s, frequency=%s, drift_threshold=%.3f",
            self.mode,
            self.frequency,
            self.drift_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_rebalance(
        self,
        current_ts: Any,
        last_rebalance_ts: Any,
        current_weights: dict[Any, float],
        target_weights: dict[Any, float],
        new_signal_arrived: bool = False,
    ) -> bool:
        """Determine if a rebalance should occur now.

        Parameters
        ----------
        current_ts : datetime-like
            Current timestamp.
        last_rebalance_ts : datetime-like or None
            Timestamp of the last rebalance. None triggers immediate rebalance.
        current_weights : dict
            Actual current portfolio weights keyed by asset ID.
        target_weights : dict
            Target (optimizer) weights keyed by asset ID.
        new_signal_arrived : bool
            True when fresh signal data has arrived this period.

        Returns
        -------
        bool
            True if a rebalance should be executed.
        """
        # Guard: first ever rebalance
        if last_rebalance_ts is None:
            logger.debug("should_rebalance: no prior rebalance, triggering initial")
            return True

        if self.mode == "signal_driven":
            result = new_signal_arrived
            logger.debug("should_rebalance (signal_driven): %s", result)
            return result

        if self.mode == "threshold_based":
            result = self._drift_triggered(current_weights, target_weights)
            logger.debug("should_rebalance (threshold_based): %s", result)
            return result

        # Default: time_based (with optional drift overlay)
        time_elapsed = current_ts - last_rebalance_ts
        time_trigger = time_elapsed >= self.frequency
        if self.drift_threshold > 0:
            drift_trigger = self._drift_triggered(current_weights, target_weights)
            result = time_trigger or drift_trigger
            logger.debug(
                "should_rebalance (time_based+drift): time=%s drift=%s => %s",
                time_trigger,
                drift_trigger,
                result,
            )
        else:
            result = time_trigger
            logger.debug("should_rebalance (time_based): %s", result)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_frequency(freq_str: str) -> timedelta:
        """Parse a frequency string like '1D', '7D', '1W', '30D' to timedelta.

        Parameters
        ----------
        freq_str : str
            Frequency string. Supported values: see _FREQ_MAP.
            Falls back to numeric-day parsing: '5D' -> timedelta(days=5).

        Returns
        -------
        timedelta
        """
        freq_upper = freq_str.strip().upper()
        if freq_upper in _FREQ_MAP:
            return _FREQ_MAP[freq_upper]

        # Generic numeric parse: e.g. '5D' -> 5 days, '3W' -> 3 weeks
        if freq_upper.endswith("D") and freq_upper[:-1].isdigit():
            return timedelta(days=int(freq_upper[:-1]))
        if freq_upper.endswith("W") and freq_upper[:-1].isdigit():
            return timedelta(weeks=int(freq_upper[:-1]))
        if freq_upper.endswith("M") and freq_upper[:-1].isdigit():
            return timedelta(days=30 * int(freq_upper[:-1]))

        raise ValueError(
            f"Unsupported frequency string '{freq_str}'. "
            "Use formats like '1D', '7D', '1W', '30D', '1M'."
        )

    def _drift_triggered(
        self,
        current_weights: dict[Any, float],
        target_weights: dict[Any, float],
    ) -> bool:
        """Return True if any asset's absolute weight drift exceeds the threshold."""
        if self.drift_threshold <= 0:
            return False
        all_assets = set(current_weights) | set(target_weights)
        if not all_assets:
            return False
        max_drift = max(
            abs(current_weights.get(a, 0.0) - target_weights.get(a, 0.0))
            for a in all_assets
        )
        return max_drift > self.drift_threshold
