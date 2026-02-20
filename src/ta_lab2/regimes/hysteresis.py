# src/ta_lab2/regimes/hysteresis.py
"""
HysteresisTracker: Prevent rapid regime flipping by requiring a minimum hold period.

Design:
- ``min_bars_hold`` (default 3): Number of consecutive identical change bars required
  before a *loosening* regime change is accepted.
- Tightening changes (risk-reducing) bypass the hold and are applied immediately.
- State is fully stateful per layer: current key, pending key, pending count.

Usage::

    tracker = HysteresisTracker(min_bars_hold=3)
    for row in regime_df.itertuples():
        is_tighten = is_tightening_change(tracker.get_current("L2"), row.regime_key, policy_table)
        accepted = tracker.update("L2", row.regime_key, is_tightening=is_tighten)
        row_result = accepted   # Use accepted key in output

Integrates with resolver.py's ``resolve_policy_from_table`` (public API) and
``DEFAULT_POLICY_TABLE`` to determine whether a regime transition is tightening
(risk-reducing) or loosening (risk-increasing).
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional

from .resolver import (
    DEFAULT_POLICY_TABLE,
    TightenOnlyPolicy,
    resolve_policy_from_table,
)


class HysteresisTracker:
    """
    Stateful per-layer hysteresis filter preventing rapid regime flipping.

    Loosening changes (risk-increasing) are held for ``min_bars_hold`` consecutive
    identical change bars before acceptance. Tightening changes (risk-reducing)
    bypass the hold and take effect immediately.

    State is tracked per *layer* string key (e.g. 'L0', 'L1', 'L2', 'composite').

    Args:
        min_bars_hold: Minimum consecutive bars the same new key must appear before
            a loosening change is accepted. Default 3.

    Example::

        tracker = HysteresisTracker(min_bars_hold=3)

        # First call always accepted (no prior state)
        result = tracker.update("L2", "Up-Normal-Normal")
        assert result == "Up-Normal-Normal"

        # Loosening change is held...
        result = tracker.update("L2", "Sideways-High-")  # count=1
        assert result == "Up-Normal-Normal"               # still held

        result = tracker.update("L2", "Sideways-High-")  # count=2
        assert result == "Up-Normal-Normal"               # still held

        result = tracker.update("L2", "Sideways-High-")  # count=3 -> accepted
        assert result == "Sideways-High-"
    """

    def __init__(self, min_bars_hold: int = 3) -> None:
        if min_bars_hold < 0:
            raise ValueError("min_bars_hold must be >= 0")
        self.min_bars_hold = min_bars_hold

        # layer -> currently accepted regime key
        self._current: Dict[str, str] = {}
        # layer -> pending (not-yet-accepted) key
        self._pending: Dict[str, Optional[str]] = {}
        # layer -> consecutive bars pending key has been seen
        self._pending_count: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        layer: str,
        new_key: str,
        *,
        is_tightening: bool = False,
    ) -> str:
        """
        Apply a new regime key for a layer, honouring hysteresis rules.

        Args:
            layer: Layer identifier (e.g. 'L0', 'L1', 'L2', 'composite').
            new_key: The proposed new regime key string.
            is_tightening: If True, accept immediately regardless of hold period.
                           If False, require ``min_bars_hold`` consecutive occurrences
                           before accepting a change from the current value.

        Returns:
            The accepted regime key for this bar (may be current or new_key).
        """
        # If no current state for layer, accept immediately (first bar ever)
        if layer not in self._current:
            self._current[layer] = new_key
            self._pending[layer] = None
            self._pending_count[layer] = 0
            return new_key

        current = self._current[layer]

        # No change — clear pending and return current
        if new_key == current:
            self._pending[layer] = None
            self._pending_count[layer] = 0
            return current

        # Tightening change — accept immediately
        if is_tightening or self.min_bars_hold <= 0:
            self._current[layer] = new_key
            self._pending[layer] = None
            self._pending_count[layer] = 0
            return new_key

        # Loosening change — apply hold period
        if self._pending.get(layer) == new_key:
            # Same pending key as last bar; increment counter
            self._pending_count[layer] = self._pending_count.get(layer, 0) + 1
        else:
            # Different pending key or no pending; reset counter to 1
            self._pending[layer] = new_key
            self._pending_count[layer] = 1

        if self._pending_count[layer] >= self.min_bars_hold:
            # Hold satisfied — accept the change
            self._current[layer] = new_key
            self._pending[layer] = None
            self._pending_count[layer] = 0
            return new_key

        # Still holding — return current (unchanged)
        return current

    def get_current(self, layer: str) -> Optional[str]:
        """
        Return the currently accepted regime key for a layer, or None if unseen.

        Args:
            layer: Layer identifier.

        Returns:
            Current regime key string, or None if the layer has never been updated.
        """
        return self._current.get(layer)

    def reset(self) -> None:
        """Clear all state for all layers. Use between assets or fresh runs."""
        self._current.clear()
        self._pending.clear()
        self._pending_count.clear()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"HysteresisTracker(min_bars_hold={self.min_bars_hold}, "
            f"layers={list(self._current.keys())})"
        )


# ---------------------------------------------------------------------------
# is_tightening_change helper
# ---------------------------------------------------------------------------


def is_tightening_change(
    old_key: Optional[str],
    new_key: str,
    policy_table: Mapping[str, Mapping[str, object]] = DEFAULT_POLICY_TABLE,
) -> bool:
    """
    Determine whether transitioning from ``old_key`` to ``new_key`` is tightening
    (risk-reducing) or loosening (risk-increasing).

    Uses the public ``resolve_policy_from_table`` API to evaluate the policy for
    each regime key, then compares ``size_mult`` (lower = tighter) as the primary
    signal. Falls back to True (treat as tightening / accept immediately) when
    old_key is None or keys cannot be compared.

    A transition is considered *tightening* when the new policy would impose a
    smaller position size or larger stop multiplier than the current policy.

    Args:
        old_key: Current regime key string. None if no prior regime.
        new_key: Proposed new regime key string.
        policy_table: Policy lookup table. Defaults to DEFAULT_POLICY_TABLE.

    Returns:
        True if the transition is tightening (new is more conservative).
        False if the transition is loosening (new allows more risk).
        True on any comparison error or when old_key is None.

    Notes:
        Uses public ``resolve_policy_from_table`` (not private ``_match_policy``)
        to remain decoupled from resolver internals.
    """
    if old_key is None:
        return True  # No prior state → treat as tightening (accept immediately)

    if old_key == new_key:
        return False  # No change → not tightening

    try:
        old_policy: TightenOnlyPolicy = resolve_policy_from_table(
            policy_table, L2=old_key
        )
        new_policy: TightenOnlyPolicy = resolve_policy_from_table(
            policy_table, L2=new_key
        )
        # Tightening = new size is smaller OR new stop is larger
        size_tightens = new_policy.size_mult < old_policy.size_mult
        stop_tightens = new_policy.stop_mult > old_policy.stop_mult
        return size_tightens or stop_tightens
    except Exception:
        # Any error → default to conservative (tightening = accept)
        return True
