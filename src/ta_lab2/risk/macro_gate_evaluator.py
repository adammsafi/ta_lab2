"""MacroGateEvaluator: 7-gate macro risk evaluation with composite stress score.

Reads FRED macro features and event calendar, evaluates individual and composite
gate conditions, manages state with cooldown, and sends Telegram alerts on
gate state transitions.

Gates:
  1. Event gates -- FOMC (+/-24h / 0.5), CPI (+/-24h / 0.7), NFP (+/-12h / 0.75)
  2. VIX gate -- REDUCE at vixcls > 30 (0.5); FLATTEN threshold DB-configurable
  3. Carry gate -- REDUCE at dexjpus_daily_zscore magnitude > 2.0 with sign awareness
  4. Credit gate -- >1.5 -> 0.7, >2.5 -> 0.4 (no FLATTEN)
  5. Freshness gate -- >3 biz days = warn+reduce, >6 = disable macro
  6. Composite score -- weighted average (0-100) persisted to macro_stress_history
  7. State management with 4h cooldown to prevent oscillation

Usage::

    from sqlalchemy import create_engine
    from ta_lab2.risk.macro_gate_evaluator import MacroGateEvaluator

    engine = create_engine(db_url)
    evaluator = MacroGateEvaluator(engine)
    result = evaluator.evaluate()
    print(result.state, result.size_mult, result.active_gates)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Telegram import -- gracefully degrade if not configured
# ---------------------------------------------------------------------------
try:
    from ta_lab2.notifications.telegram import send_alert as _send_alert

    _TELEGRAM_AVAILABLE = True
except ImportError:
    _send_alert = None  # type: ignore[assignment]
    _TELEGRAM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Event gate defaults (hours window around event, size_mult during window)
_EVENT_GATE_DEFAULTS: dict[str, tuple[float, float]] = {
    "fomc": (24.0, 0.5),
    "cpi": (24.0, 0.7),
    "nfp": (12.0, 0.75),
}

# Composite score weights (must sum to 1.0)
_COMPOSITE_WEIGHTS: dict[str, float] = {
    "vix": 0.40,
    "hy": 0.25,
    "carry": 0.20,
    "nfci": 0.15,
}

# Composite score -> stress tier boundaries (0-100 scale)
_STRESS_TIERS: list[tuple[float, str, float]] = [
    (25.0, "calm", 1.0),
    (50.0, "elevated", 0.8),
    (75.0, "stressed", 0.6),
    (101.0, "crisis", 0.4),
]

# Default cooldown: 4 hours between gate state de-escalations
_COOLDOWN_HOURS: float = 4.0

# Freshness thresholds (business days)
_FRESHNESS_WARN_DAYS: int = 3
_FRESHNESS_DISABLE_DAYS: int = 6


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MacroGateResult:
    """Result of MacroGateEvaluator.evaluate().

    Attributes:
        state: Worst-of composite gate state ('normal', 'reduce', 'flatten').
        size_mult: Position size multiplier to apply (0.0 - 1.0).
        active_gates: List of gate IDs that are currently not in 'normal' state.
        details: Human-readable summary of active gate conditions.
    """

    state: str
    size_mult: float
    active_gates: list[str] = field(default_factory=list)
    details: str = ""


# ---------------------------------------------------------------------------
# MacroGateEvaluator
# ---------------------------------------------------------------------------


class MacroGateEvaluator:
    """Evaluate all 7 macro risk gates and return composite MacroGateResult.

    Call evaluate() once per evaluation cycle (e.g., daily or at strategy start).
    Call check_order_gates() from the hot path (per-order) for lightweight checks.
    """

    def __init__(self, engine: Engine) -> None:
        from ta_lab2.risk.macro_gate_overrides import GateOverrideManager

        self._engine = engine
        self._overrides = GateOverrideManager(engine)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self) -> MacroGateResult:
        """Evaluate all gates and return composite MacroGateResult.

        Reads fred.fred_macro_features (latest row) and dim_macro_events,
        evaluates each gate, computes composite stress score, updates
        dim_macro_gate_state, sends Telegram alerts on transitions, and
        returns the worst-of result.

        Returns:
            MacroGateResult with worst-of state, size_mult, active_gates, and details.
        """
        # Load latest macro features
        features = self._load_latest_features()

        # Collect per-gate results: gate_id -> (state, size_mult)
        gate_results: dict[str, tuple[str, float]] = {}

        # 1-3: Event gates
        for event_type in ("fomc", "cpi", "nfp"):
            window_h, mult = _EVENT_GATE_DEFAULTS[event_type]
            gate_results[event_type] = self._check_event_gate(
                event_type, mult, window_h
            )

        # 4: VIX gate
        vixcls = features.get("vixcls")
        vix_flatten = features.get("_vix_flatten_threshold")  # None = disabled
        gate_results["vix"] = self._check_vix_gate(
            vixcls, flatten_threshold=vix_flatten
        )

        # 5: Carry gate
        dexjpus_zscore = features.get("dexjpus_daily_zscore")
        rate_spread = features.get("us_jp_rate_spread")
        carry_flatten = features.get("_carry_flatten_threshold")  # None = disabled
        gate_results["carry"] = self._check_carry_gate(
            dexjpus_zscore, rate_spread, flatten_threshold=carry_flatten
        )

        # 6: Credit gate
        hy_oas_zscore = features.get("hy_oas_30d_zscore")
        gate_results["credit"] = self._check_credit_gate(hy_oas_zscore)

        # 7: Freshness gate
        gate_results["freshness"] = self._check_freshness_gate()

        # Composite score
        nfci_level = features.get("nfci_level")
        composite_state, composite_mult = self._compute_composite_score(
            vixcls=vixcls,
            hy_oas_zscore=hy_oas_zscore,
            carry_zscore=dexjpus_zscore,
            nfci_level=nfci_level,
        )
        gate_results["composite"] = (composite_state, composite_mult)

        # Apply overrides -- check each gate for active override
        for gate_id in list(gate_results.keys()):
            override_type = self._overrides.check_override(gate_id)
            if override_type == "disable_gate":
                gate_results[gate_id] = ("normal", 1.0)
                logger.info("Gate %s disabled by override", gate_id)
            elif override_type == "force_normal":
                gate_results[gate_id] = ("normal", 1.0)
                logger.info("Gate %s forced to normal by override", gate_id)
            elif override_type == "force_reduce":
                # Force to reduce only if currently less restrictive
                current_state, current_mult = gate_results[gate_id]
                if current_state == "normal":
                    gate_results[gate_id] = ("reduce", 0.5)
                    logger.info("Gate %s forced to reduce by override", gate_id)

        # Update DB state and detect transitions
        self._update_gate_state(gate_results)

        # Compute worst-of result
        state_order = {"normal": 0, "reduce": 1, "flatten": 2}
        worst_state = "normal"
        worst_mult = 1.0
        active_gates: list[str] = []

        for gate_id, (state, mult) in gate_results.items():
            if state != "normal":
                active_gates.append(gate_id)
                if state_order.get(state, 0) > state_order.get(worst_state, 0):
                    worst_state = state
                    worst_mult = mult
                elif state == worst_state and mult < worst_mult:
                    worst_mult = mult  # tightest multiplier wins among equal states

        details_parts = []
        for gate_id in active_gates:
            st, ml = gate_results[gate_id]
            details_parts.append(f"{gate_id}={st}({ml:.2f})")
        details = "; ".join(details_parts) if details_parts else "all gates normal"

        return MacroGateResult(
            state=worst_state,
            size_mult=worst_mult,
            active_gates=active_gates,
            details=details,
        )

    def check_order_gates(self) -> tuple[str, float]:
        """Lightweight read of aggregate gate state for per-order checks.

        Reads current worst-of state from dim_macro_gate_state directly (no
        computation, no DB writes). Suitable for the hot path.

        Returns:
            (state, size_mult) from stored composite gate state.
            Returns ('normal', 1.0) if no gate state found.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT gate_state, size_mult
                    FROM public.dim_macro_gate_state
                    WHERE gate_state != 'normal'
                    ORDER BY
                        CASE gate_state
                            WHEN 'flatten' THEN 2
                            WHEN 'reduce' THEN 1
                            ELSE 0
                        END DESC,
                        size_mult ASC
                    LIMIT 1
                    """
                )
            ).fetchone()

        if rows is None:
            return ("normal", 1.0)

        return (str(rows[0]), float(rows[1]))

    # ------------------------------------------------------------------
    # Gate methods
    # ------------------------------------------------------------------

    def _check_event_gate(
        self, event_type: str, size_mult: float, window_hours: float
    ) -> tuple[str, float]:
        """Check if current time falls within the event window for this event type.

        Args:
            event_type: 'fomc', 'cpi', or 'nfp'
            size_mult: Size multiplier to apply when gate is active
            window_hours: Hours before and after event for the gate window

        Returns:
            ('reduce', size_mult) if within window, ('normal', 1.0) otherwise
        """
        now = datetime.now(timezone.utc)
        window_delta = timedelta(hours=window_hours)

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT event_ts
                    FROM public.dim_macro_events
                    WHERE event_type = :event_type
                      AND event_ts BETWEEN :start AND :end
                    ORDER BY event_ts ASC
                    LIMIT 1
                    """
                ),
                {
                    "event_type": event_type,
                    "start": now - window_delta,
                    "end": now + window_delta,
                },
            ).fetchone()

        if row is not None:
            event_ts = row[0]
            hours_to_event = abs((event_ts - now).total_seconds() / 3600.0)
            logger.info(
                "Event gate %s triggered: %.1fh to/from event (window=+/-%.1fh, mult=%.2f)",
                event_type,
                hours_to_event,
                window_hours,
                size_mult,
            )
            return ("reduce", size_mult)

        return ("normal", 1.0)

    def _check_vix_gate(
        self,
        vixcls: Optional[float],
        flatten_threshold: Optional[float] = None,
    ) -> tuple[str, float]:
        """Evaluate VIX gate.

        REDUCE at vixcls > 30 (0.5).
        FLATTEN threshold is DB-configurable (default None = disabled).
        If vixcls is None (stale), gate is inactive (staleness handled by freshness gate).

        Args:
            vixcls: Raw VIX value from fred.fred_macro_features.
            flatten_threshold: VIX level that triggers FLATTEN. None = disabled.

        Returns:
            ('flatten', 0.0), ('reduce', 0.5), or ('normal', 1.0)
        """
        if vixcls is None:
            return ("normal", 1.0)

        # FLATTEN first (most restrictive)
        if flatten_threshold is not None and vixcls > flatten_threshold:
            logger.warning(
                "VIX gate FLATTEN: vixcls=%.2f > flatten_threshold=%.2f",
                vixcls,
                flatten_threshold,
            )
            return ("flatten", 0.0)

        # REDUCE
        if vixcls > 30.0:
            logger.info("VIX gate REDUCE: vixcls=%.2f > 30.0 (mult=0.5)", vixcls)
            return ("reduce", 0.5)

        return ("normal", 1.0)

    def _check_carry_gate(
        self,
        dexjpus_zscore: Optional[float],
        rate_spread: Optional[float],
        flatten_threshold: Optional[float] = None,
    ) -> tuple[str, float]:
        """Evaluate carry unwind gate.

        Sign convention: DEXJPUS = JPY per USD (higher = USD stronger vs JPY).
        JPY strengthening = carry unwind = negative dexjpus z-score.
        carry_signal = -dexjpus_zscore: positive when JPY strengthening (carry unwind).
        REDUCE at carry_signal magnitude > 2.0 (0.6).
        FLATTEN threshold DB-configurable (default None = disabled).

        Args:
            dexjpus_zscore: dexjpus_daily_zscore from fred.fred_macro_features.
            rate_spread: us_jp_rate_spread (informational, used for context logging).
            flatten_threshold: carry_signal magnitude that triggers FLATTEN. None = disabled.

        Returns:
            ('flatten', 0.0), ('reduce', 0.6), or ('normal', 1.0)
        """
        if dexjpus_zscore is None:
            return ("normal", 1.0)

        # carry_signal: positive = JPY strengthening = carry unwind pressure
        carry_signal = -dexjpus_zscore

        # FLATTEN first
        if flatten_threshold is not None and abs(carry_signal) > flatten_threshold:
            logger.warning(
                "Carry gate FLATTEN: carry_signal=%.3f (dexjpus_zscore=%.3f), threshold=%.2f",
                carry_signal,
                dexjpus_zscore,
                flatten_threshold,
            )
            return ("flatten", 0.0)

        # REDUCE
        if abs(carry_signal) > 2.0:
            direction = (
                "JPY strengthening" if carry_signal > 0 else "USD weakening vs JPY"
            )
            logger.info(
                "Carry gate REDUCE: carry_signal=%.3f > 2.0 (%s, mult=0.6)",
                carry_signal,
                direction,
            )
            return ("reduce", 0.6)

        return ("normal", 1.0)

    def _check_credit_gate(self, hy_oas_zscore: Optional[float]) -> tuple[str, float]:
        """Evaluate HY OAS credit stress gate.

        >1.5 z-score -> REDUCE (0.7)
        >2.5 z-score -> REDUCE (0.4)
        No FLATTEN tier for credit gate.

        Args:
            hy_oas_zscore: hy_oas_30d_zscore from fred.fred_macro_features.

        Returns:
            ('reduce', 0.4), ('reduce', 0.7), or ('normal', 1.0)
        """
        if hy_oas_zscore is None:
            return ("normal", 1.0)

        if hy_oas_zscore > 2.5:
            logger.info(
                "Credit gate REDUCE (severe): hy_oas_zscore=%.3f > 2.5 (mult=0.4)",
                hy_oas_zscore,
            )
            return ("reduce", 0.4)

        if hy_oas_zscore > 1.5:
            logger.info(
                "Credit gate REDUCE: hy_oas_zscore=%.3f > 1.5 (mult=0.7)",
                hy_oas_zscore,
            )
            return ("reduce", 0.7)

        return ("normal", 1.0)

    def _check_freshness_gate(self) -> tuple[str, float]:
        """Evaluate data freshness gate using business-day calendar.

        Checks per-series staleness by comparing the latest observation date
        in fred.series_values against today's date using USFederalHolidayCalendar
        (so weekend gaps don't count as stale).

        >3 business days stale -> warn + reduce (0.8)
        >6 business days stale -> disable macro (0.5) -- macro regime unreliable

        Returns:
            ('reduce', 0.8), ('reduce', 0.5), or ('normal', 1.0)
        """
        try:
            import pandas as pd
            from pandas.tseries.holiday import USFederalHolidayCalendar
            from pandas.tseries.offsets import CustomBusinessDay

            bday = CustomBusinessDay(calendar=USFederalHolidayCalendar())
        except ImportError:
            logger.warning("pandas not available -- skipping freshness gate")
            return ("normal", 1.0)

        today = datetime.now(timezone.utc).date()

        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT series_id, MAX(date) AS last_date
                        FROM fred.series_values
                        GROUP BY series_id
                        """
                    )
                ).fetchall()
        except Exception as exc:
            logger.warning("Freshness gate: cannot query fred.series_values: %s", exc)
            return ("normal", 1.0)

        if not rows:
            logger.warning("Freshness gate: no rows in fred.series_values")
            return ("normal", 1.0)

        worst_biz_days = 0
        stale_series: list[str] = []

        for series_id, last_date in rows:
            if last_date is None:
                continue

            # Convert last_date to Python date if needed
            if hasattr(last_date, "date"):
                last_date = last_date.date()

            # Compute business days between last observation and today
            if last_date >= today:
                biz_days_stale = 0
            else:
                try:
                    biz_days_stale = (
                        len(
                            pd.bdate_range(
                                start=str(last_date),
                                end=str(today),
                                freq=bday,
                            )
                        )
                        - 1
                    )  # exclude the last_date itself
                    biz_days_stale = max(0, biz_days_stale)
                except Exception:
                    biz_days_stale = (today - last_date).days  # fallback

            if biz_days_stale > _FRESHNESS_WARN_DAYS:
                stale_series.append(f"{series_id}({biz_days_stale}d)")
                worst_biz_days = max(worst_biz_days, biz_days_stale)

        if worst_biz_days > _FRESHNESS_DISABLE_DAYS:
            logger.warning(
                "Freshness gate REDUCE (macro disabled): max stale=%d biz days. Series: %s",
                worst_biz_days,
                ", ".join(stale_series[:5]),
            )
            return ("reduce", 0.5)

        if worst_biz_days > _FRESHNESS_WARN_DAYS:
            logger.warning(
                "Freshness gate REDUCE (warn): max stale=%d biz days. Series: %s",
                worst_biz_days,
                ", ".join(stale_series[:5]),
            )
            return ("reduce", 0.8)

        return ("normal", 1.0)

    def _compute_composite_score(
        self,
        vixcls: Optional[float],
        hy_oas_zscore: Optional[float],
        carry_zscore: Optional[float],
        nfci_level: Optional[float],
    ) -> tuple[str, float]:
        """Compute composite stress score (0-100) and persist to macro_stress_history.

        Weights: VIX=0.40, HY OAS=0.25, carry=0.20, NFCI=0.15.
        Score tiers: 0-25=calm(1.0), 25-50=elevated(0.8), 50-75=stressed(0.6), 75+=crisis(0.4)

        Normalization:
        - VIX: min=10, max=50 -> 0-100 scale (clamped)
        - HY OAS z-score: 0->0, 2->50, 4->100 (clamped, sign-insensitive)
        - Carry z-score: 0->0, 2->50, 4->100 (clamped, absolute value)
        - NFCI: -1->0, 0->50, 1->100 (NFCI normal ~0, tighter conditions positive)

        Args:
            vixcls: Raw VIX level.
            hy_oas_zscore: HY OAS 30-day z-score.
            carry_zscore: dexjpus_daily_zscore (sign-aware but magnitude matters).
            nfci_level: NFCI raw level.

        Returns:
            (stress_tier, size_mult_for_tier) based on composite score.
        """
        components: dict[str, Optional[float]] = {}

        # Normalize VIX to 0-100 (VIX=10 -> 0, VIX=50 -> 100)
        if vixcls is not None:
            vix_norm = max(0.0, min(100.0, (vixcls - 10.0) / 40.0 * 100.0))
            components["vix"] = vix_norm
        else:
            components["vix"] = None

        # Normalize HY OAS z-score to 0-100 (z=0 -> 0, z=4 -> 100)
        if hy_oas_zscore is not None:
            hy_norm = max(0.0, min(100.0, abs(hy_oas_zscore) / 4.0 * 100.0))
            components["hy"] = hy_norm
        else:
            components["hy"] = None

        # Normalize carry z-score to 0-100 (magnitude: z=0 -> 0, z=4 -> 100)
        if carry_zscore is not None:
            carry_norm = max(0.0, min(100.0, abs(carry_zscore) / 4.0 * 100.0))
            components["carry"] = carry_norm
        else:
            components["carry"] = None

        # Normalize NFCI to 0-100 (NFCI=-1 -> 0, NFCI=0 -> 50, NFCI=1 -> 100)
        if nfci_level is not None:
            nfci_norm = max(0.0, min(100.0, (nfci_level + 1.0) / 2.0 * 100.0))
            components["nfci"] = nfci_norm
        else:
            components["nfci"] = None

        # Weighted average (skip None components, re-weight)
        total_weight = 0.0
        weighted_sum = 0.0
        for key, value in components.items():
            if value is not None:
                w = _COMPOSITE_WEIGHTS[key]
                weighted_sum += value * w
                total_weight += w

        if total_weight < 0.01:
            # No data at all -- default to calm
            composite_score = 0.0
        else:
            composite_score = weighted_sum / total_weight

        # Determine stress tier
        stress_tier = "calm"
        tier_mult = 1.0
        for threshold, tier_name, mult in _STRESS_TIERS:
            if composite_score < threshold:
                stress_tier = tier_name
                tier_mult = mult
                break

        # Persist to macro_stress_history
        now = datetime.now(timezone.utc)
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO public.macro_stress_history
                            (ts, composite_score, stress_tier,
                             vix_raw, hy_oas_zscore, carry_velocity_zscore,
                             nfci_level, dexjpus_zscore_raw)
                        VALUES
                            (:ts, :composite_score, :stress_tier,
                             :vix_raw, :hy_oas_zscore, :carry_velocity_zscore,
                             :nfci_level, :dexjpus_zscore_raw)
                        ON CONFLICT (ts) DO UPDATE
                            SET composite_score = EXCLUDED.composite_score,
                                stress_tier = EXCLUDED.stress_tier,
                                vix_raw = EXCLUDED.vix_raw,
                                hy_oas_zscore = EXCLUDED.hy_oas_zscore,
                                carry_velocity_zscore = EXCLUDED.carry_velocity_zscore,
                                nfci_level = EXCLUDED.nfci_level,
                                dexjpus_zscore_raw = EXCLUDED.dexjpus_zscore_raw
                        """
                    ),
                    {
                        "ts": now,
                        "composite_score": composite_score,
                        "stress_tier": stress_tier,
                        "vix_raw": vixcls,
                        "hy_oas_zscore": hy_oas_zscore,
                        "carry_velocity_zscore": carry_zscore,
                        "nfci_level": nfci_level,
                        "dexjpus_zscore_raw": carry_zscore,
                    },
                )
        except Exception as exc:
            logger.warning("Failed to persist composite stress score: %s", exc)

        logger.info(
            "Composite stress score: %.1f (%s, mult=%.2f) -- VIX=%.1f HY=%.1f "
            "carry=%.1f NFCI=%.1f",
            composite_score,
            stress_tier,
            tier_mult,
            components.get("vix") or 0.0,
            components.get("hy") or 0.0,
            components.get("carry") or 0.0,
            components.get("nfci") or 0.0,
        )

        # Composite gate only triggers at stressed/crisis
        if stress_tier in ("stressed", "crisis"):
            return ("reduce", tier_mult)

        return ("normal", 1.0)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _update_gate_state(self, gate_results: dict[str, tuple[str, float]]) -> None:
        """UPSERT dim_macro_gate_state with cooldown-aware de-escalation.

        For each gate:
        - Escalation (normal->reduce, reduce->flatten) is immediate.
        - De-escalation requires cooldown to have expired.

        Sends Telegram alerts on any state transition.

        Args:
            gate_results: Mapping of gate_id -> (new_state, size_mult)
        """
        now = datetime.now(timezone.utc)
        cooldown_delta = timedelta(hours=_COOLDOWN_HOURS)
        state_order = {"normal": 0, "reduce": 1, "flatten": 2}

        # Read current states in a single query
        with self._engine.connect() as conn:
            current_rows = conn.execute(
                text(
                    """
                    SELECT gate_id, gate_state, size_mult, cooldown_ends_at, triggered_at
                    FROM public.dim_macro_gate_state
                    """
                )
            ).fetchall()

        current_states: dict[str, dict] = {
            row[0]: {
                "gate_state": row[1],
                "size_mult": float(row[2]),
                "cooldown_ends_at": row[3],
                "triggered_at": row[4],
            }
            for row in current_rows
        }

        for gate_id, (new_state, new_mult) in gate_results.items():
            current = current_states.get(gate_id, {})
            old_state = current.get("gate_state", "normal")
            cooldown_ends_at = current.get("cooldown_ends_at")

            is_escalation = state_order.get(new_state, 0) > state_order.get(
                old_state, 0
            )
            is_de_escalation = state_order.get(new_state, 0) < state_order.get(
                old_state, 0
            )
            is_same_state = new_state == old_state

            if is_same_state:
                # No state change -- update size_mult if it changed
                if abs(new_mult - current.get("size_mult", 1.0)) > 0.001:
                    self._upsert_gate_state(
                        gate_id, new_state, new_mult, reason=None, triggered_at=None
                    )
                continue

            if is_escalation:
                # Immediate escalation -- set new cooldown
                cooldown_ends = now + cooldown_delta
                reason = (
                    f"Gate escalated: {old_state} -> {new_state} (mult={new_mult:.2f})"
                )
                self._upsert_gate_state(
                    gate_id,
                    new_state,
                    new_mult,
                    reason=reason,
                    triggered_at=now,
                    cooldown_ends_at=cooldown_ends,
                )
                self._send_gate_transition_alert(
                    gate_id, old_state, new_state, new_mult, severity="warning"
                )
                self._log_risk_event(
                    gate_id=gate_id,
                    old_state=old_state,
                    new_state=new_state,
                    size_mult=new_mult,
                )
                logger.warning(
                    "Gate %s escalated: %s -> %s (mult=%.2f)",
                    gate_id,
                    old_state,
                    new_state,
                    new_mult,
                )

            elif is_de_escalation:
                # De-escalation requires cooldown to have expired
                if cooldown_ends_at is not None:
                    # Ensure cooldown_ends_at is tz-aware
                    if (
                        hasattr(cooldown_ends_at, "tzinfo")
                        and cooldown_ends_at.tzinfo is None
                    ):
                        cooldown_ends_at = cooldown_ends_at.replace(tzinfo=timezone.utc)

                    if now < cooldown_ends_at:
                        remaining = (cooldown_ends_at - now).total_seconds() / 3600.0
                        logger.info(
                            "Gate %s de-escalation blocked by cooldown: %.1f hours remaining",
                            gate_id,
                            remaining,
                        )
                        continue  # stay at current state

                # Cooldown expired (or no cooldown set) -- allow de-escalation
                reason = f"Gate cleared: {old_state} -> {new_state} (cooldown expired)"
                self._upsert_gate_state(
                    gate_id,
                    new_state,
                    new_mult,
                    reason=reason,
                    triggered_at=None,
                    cleared_at=now,
                )
                self._send_gate_transition_alert(
                    gate_id, old_state, new_state, new_mult, severity="info"
                )
                self._log_risk_event(
                    gate_id=gate_id,
                    old_state=old_state,
                    new_state=new_state,
                    size_mult=new_mult,
                )
                logger.info(
                    "Gate %s de-escalated: %s -> %s (mult=%.2f)",
                    gate_id,
                    old_state,
                    new_state,
                    new_mult,
                )

    def _upsert_gate_state(
        self,
        gate_id: str,
        gate_state: str,
        size_mult: float,
        reason: Optional[str],
        triggered_at: Optional[datetime],
        cooldown_ends_at: Optional[datetime] = None,
        cleared_at: Optional[datetime] = None,
    ) -> None:
        """UPSERT dim_macro_gate_state for a single gate."""
        now = datetime.now(timezone.utc)
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO public.dim_macro_gate_state
                            (gate_id, gate_state, size_mult, trigger_reason,
                             triggered_at, cleared_at, cooldown_ends_at, updated_at)
                        VALUES
                            (:gate_id, :gate_state, :size_mult, :reason,
                             :triggered_at, :cleared_at, :cooldown_ends_at, :now)
                        ON CONFLICT (gate_id) DO UPDATE
                            SET gate_state = EXCLUDED.gate_state,
                                size_mult = EXCLUDED.size_mult,
                                trigger_reason = COALESCE(EXCLUDED.trigger_reason,
                                                          dim_macro_gate_state.trigger_reason),
                                triggered_at = COALESCE(EXCLUDED.triggered_at,
                                                        dim_macro_gate_state.triggered_at),
                                cleared_at = COALESCE(EXCLUDED.cleared_at,
                                                      dim_macro_gate_state.cleared_at),
                                cooldown_ends_at = COALESCE(EXCLUDED.cooldown_ends_at,
                                                            dim_macro_gate_state.cooldown_ends_at),
                                updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "gate_id": gate_id,
                        "gate_state": gate_state,
                        "size_mult": size_mult,
                        "reason": reason,
                        "triggered_at": triggered_at,
                        "cleared_at": cleared_at,
                        "cooldown_ends_at": cooldown_ends_at,
                        "now": now,
                    },
                )
        except Exception as exc:
            logger.warning("Failed to upsert gate state for %s: %s", gate_id, exc)

    def _send_gate_transition_alert(
        self,
        gate_id: str,
        old_state: str,
        new_state: str,
        size_mult: float,
        severity: str = "warning",
    ) -> None:
        """Send Telegram alert on gate state transition.

        Uses plain string severity ('info', 'warning', 'critical') -- NOT enum.
        Gracefully degrades if Telegram is not configured or unavailable.

        Args:
            gate_id: Gate identifier.
            old_state: Previous gate state.
            new_state: New gate state.
            size_mult: New size multiplier.
            severity: Alert severity ('info', 'warning', 'critical').
        """
        if not _TELEGRAM_AVAILABLE or _send_alert is None:
            return

        direction = "ESCALATED" if new_state != "normal" else "CLEARED"
        title = f"Macro Gate {direction}: {gate_id.upper()}"
        message = (
            f"Gate: {gate_id}\n"
            f"Transition: {old_state} -> {new_state}\n"
            f"Size multiplier: {size_mult:.2f}\n"
            f"Time: {datetime.now(timezone.utc).isoformat()}"
        )

        try:
            _send_alert(title=title, message=message, severity=severity)
        except Exception as exc:
            logger.warning("Failed to send gate transition alert: %s", exc)

    def _log_risk_event(
        self,
        gate_id: str,
        old_state: str,
        new_state: str,
        size_mult: float,
    ) -> None:
        """Insert to risk_events for gate state transition.

        Args:
            gate_id: Gate identifier.
            old_state: Previous gate state.
            new_state: New gate state.
            size_mult: New size multiplier.
        """
        is_clearing = new_state == "normal"
        event_type = (
            "macro_gate_cleared"
            if is_clearing
            else "macro_event_gate_triggered"
            if gate_id in ("fomc", "cpi", "nfp")
            else "macro_stress_gate_triggered"
        )
        reason = (
            f"Macro gate {gate_id}: {old_state} -> {new_state} "
            f"(size_mult={size_mult:.2f})"
        )
        metadata = {
            "gate_id": gate_id,
            "old_state": old_state,
            "new_state": new_state,
            "size_mult": size_mult,
        }

        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO public.risk_events
                            (event_type, trigger_source, reason, metadata)
                        VALUES
                            (:event_type, 'macro_gate', :reason, :metadata)
                        """
                    ),
                    {
                        "event_type": event_type,
                        "reason": reason,
                        "metadata": json.dumps(metadata),
                    },
                )
        except Exception as exc:
            logger.warning("Failed to log risk event for gate %s: %s", gate_id, exc)

    # ------------------------------------------------------------------
    # Feature loading
    # ------------------------------------------------------------------

    def _load_latest_features(self) -> dict[str, Optional[float]]:
        """Load the latest row from fred.fred_macro_features.

        Returns a flat dict of column_name -> value.
        Returns empty dict if no data found or table doesn't exist.
        """
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT
                            vixcls,
                            hy_oas_30d_zscore,
                            dexjpus_daily_zscore,
                            us_jp_rate_spread,
                            nfci_level
                        FROM fred.fred_macro_features
                        ORDER BY date DESC
                        LIMIT 1
                        """
                    )
                ).fetchone()
        except Exception as exc:
            logger.warning(
                "Failed to load fred.fred_macro_features: %s. "
                "Gates relying on macro features will return normal.",
                exc,
            )
            return {}

        if row is None:
            logger.warning("fred.fred_macro_features is empty")
            return {}

        m = row._mapping
        return {
            "vixcls": float(m["vixcls"]) if m["vixcls"] is not None else None,
            "hy_oas_30d_zscore": float(m["hy_oas_30d_zscore"])
            if m["hy_oas_30d_zscore"] is not None
            else None,
            "dexjpus_daily_zscore": float(m["dexjpus_daily_zscore"])
            if m["dexjpus_daily_zscore"] is not None
            else None,
            "us_jp_rate_spread": float(m["us_jp_rate_spread"])
            if m["us_jp_rate_spread"] is not None
            else None,
            "nfci_level": float(m["nfci_level"])
            if m["nfci_level"] is not None
            else None,
            # Configurable thresholds -- None means disabled (default)
            # Future: load from dim_macro_gate_state or dim_risk_limits
            "_vix_flatten_threshold": None,
            "_carry_flatten_threshold": None,
        }
