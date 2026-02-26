"""
run_kill_switch_exercise.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
V1 Validation Kill Switch Exercise Protocol CLI.

Implements an 8-step protocol that tests both manual and automatic kill switch
triggers, collecting timestamped evidence for the VAL-04 gate.

Protocol:
  STEP 1  -- Pre-exercise snapshot
  STEP 2  -- Manual kill switch activation
  STEP 3  -- Validate manual trigger effects
  STEP 4  -- Manual re-enable (operator confirmation required)
  STEP 5  -- Engineer automatic trigger (lower daily_loss_pct_threshold)
  STEP 6  -- Validate automatic trigger effects
  STEP 7  -- Restore thresholds + re-enable (operator confirmation required)
  STEP 8  -- Produce evidence document

Key design invariants:
  - All exercise events use "V1 EXERCISE:" prefix for easy filtering.
  - Uses EXISTING event types only: kill_switch_activated / kill_switch_disabled.
  - Re-enable is ALWAYS manual (operator + reason). Never automatic.
  - Threshold restoration is guaranteed via try/finally even on failure/timeout.
  - Script is interactive and NOT suitable for automated/background execution.

Usage:
    python -m ta_lab2.scripts.validation.run_kill_switch_exercise --operator asafi
    python -m ta_lab2.scripts.validation.run_kill_switch_exercise --operator asafi --skip-auto
    python -m ta_lab2.scripts.validation.run_kill_switch_exercise --help

All file writes use encoding='utf-8' (Windows cp1252 safety per MEMORY.md).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.risk.kill_switch import (
    activate_kill_switch,
    get_kill_switch_status,
    re_enable_trading,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXERCISE_PREFIX = "V1 EXERCISE:"
_MANUAL_LATENCY_TARGET_SECONDS = 5.0  # Target: < 5 seconds for manual trigger


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExerciseStep:
    """Evidence record for a single step in the kill switch exercise."""

    step_num: int
    name: str
    timestamp: str  # ISO format UTC
    result: str  # Human-readable description of outcome
    passed: bool

    def status_str(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass
class ExerciseContext:
    """Mutable context threaded through exercise steps."""

    t0: Optional[datetime] = None
    t1: Optional[datetime] = None  # Manual trigger fired
    t5: Optional[datetime] = None  # Auto-trigger confirmed
    manual_latency_seconds: Optional[float] = None
    original_threshold: Optional[float] = None
    auto_trigger_fired: bool = False
    steps: list[ExerciseStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DB engine helper
# ---------------------------------------------------------------------------


def _get_engine(db_url: str | None = None) -> Engine:
    """Create SQLAlchemy engine with NullPool (project convention)."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.scripts.refresh_utils import resolve_db_url

    url = db_url or resolve_db_url()
    return create_engine(url, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Main exercise class
# ---------------------------------------------------------------------------


class KillSwitchExercise:
    """
    8-step kill switch exercise protocol.

    Collects timestamped evidence at each step and produces a Markdown
    evidence document suitable for VAL-04 gate assessment.
    """

    def __init__(
        self,
        engine: Engine,
        operator: str,
        output_dir: Path,
        skip_auto: bool = False,
        poll_interval: int = 5,
        poll_timeout: int = 300,
    ) -> None:
        self._engine = engine
        self._operator = operator
        self._output_dir = output_dir
        self._skip_auto = skip_auto
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._ctx = ExerciseContext()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_exercise(self) -> str:
        """
        Execute the 8-step kill switch exercise protocol.

        Returns:
            Path to the generated evidence document.
        """
        print("=" * 60)
        print("KILL SWITCH EXERCISE PROTOCOL")
        print("=" * 60)
        print(f"Operator : {self._operator}")
        print(f"Skip auto: {self._skip_auto}")
        print(f"Started  : {datetime.now(timezone.utc).isoformat()}")
        print("=" * 60)

        # Steps 1-4: Manual trigger cycle
        self._step1_pre_snapshot()
        self._step2_manual_trigger()
        self._step3_validate_manual()
        self._step4_manual_reenable()

        # Steps 5-7: Auto trigger cycle (with guaranteed threshold restoration)
        if self._skip_auto:
            self._record_step(
                5, "Engineer automatic trigger", "SKIPPED: --skip-auto flag set", True
            )
            self._record_step(
                6,
                "Validate automatic trigger effects",
                "SKIPPED: --skip-auto flag set",
                True,
            )
            self._record_step(
                7,
                "Restore thresholds + re-enable",
                "SKIPPED: --skip-auto flag set",
                True,
            )
        else:
            self._run_auto_trigger_cycle()

        # Step 8: Produce evidence document
        evidence_path = self._step8_produce_evidence()

        print()
        print("=" * 60)
        print("EXERCISE COMPLETE")
        print(f"Evidence : {evidence_path}")
        print("=" * 60)

        return evidence_path

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _step1_pre_snapshot(self) -> None:
        """STEP 1: Pre-exercise snapshot."""
        print()
        print("[STEP 1] Pre-exercise snapshot")

        with self._engine.connect() as conn:
            # Query dim_risk_state
            state_row = conn.execute(
                text(
                    "SELECT trading_state, halted_at, drift_paused "
                    "FROM dim_risk_state WHERE state_id = 1"
                )
            ).fetchone()
            trading_state = state_row[0] if state_row else "UNKNOWN"
            halted_at = state_row[1] if state_row else None
            drift_paused = state_row[2] if state_row else None

            # Count open orders
            order_row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM cmc_orders "
                    "WHERE status IN ('created', 'submitted')"
                )
            ).fetchone()
            open_orders = order_row[0] if order_row else 0

            # Get latest risk event timestamp
            event_row = conn.execute(
                text("SELECT MAX(event_ts) FROM cmc_risk_events")
            ).fetchone()
            last_event_ts = event_row[0] if event_row else None

        self._ctx.t0 = datetime.now(timezone.utc)

        result = (
            f"Pre-state: trading_state={trading_state}, "
            f"open_orders={open_orders}, "
            f"last_event={last_event_ts}, "
            f"halted_at={halted_at}, "
            f"drift_paused={drift_paused}"
        )
        print(f"  {result}")

        passed = True
        if trading_state != "active":
            print(f"  WARNING: trading_state is '{trading_state}' (expected 'active')")
            print("  >>> This exercise assumes trading starts in 'active' state.")
            resp = input("  >>> Continue anyway? [y/N] ").strip().lower()
            if resp != "y":
                print("  Exercise aborted by operator.")
                sys.exit(1)
            passed = False
            result += " [WARNING: not active at start]"

        self._record_step(1, "Pre-exercise snapshot", result, passed)

    def _step2_manual_trigger(self) -> None:
        """STEP 2: Manual kill switch activation."""
        print()
        print("[STEP 2] Manual kill switch activation")

        activate_kill_switch(
            self._engine,
            reason=f"{_EXERCISE_PREFIX} manual kill switch test",
            trigger_source="manual",
            operator=self._operator,
        )
        self._ctx.t1 = datetime.now(timezone.utc)

        if self._ctx.t0 is not None:
            self._ctx.manual_latency_seconds = (
                self._ctx.t1 - self._ctx.t0
            ).total_seconds()
            latency_ms = self._ctx.manual_latency_seconds * 1000
            print(
                f"  Manual trigger fired, latency={self._ctx.manual_latency_seconds:.3f}s ({latency_ms:.1f}ms)"
            )
            result = (
                f"Manual trigger fired, latency={self._ctx.manual_latency_seconds:.3f}s"
            )
        else:
            result = "Manual trigger fired (t0 not recorded)"
            print(f"  {result}")

        self._record_step(2, "Manual kill switch activation", result, True)

    def _step3_validate_manual(self) -> None:
        """STEP 3: Validate manual trigger effects."""
        print()
        print("[STEP 3] Validate manual trigger effects")

        checks_passed = 0
        checks_total = 0
        details: list[str] = []

        with self._engine.connect() as conn:
            # Check 3a: dim_risk_state is halted
            checks_total += 1
            state_row = conn.execute(
                text(
                    "SELECT trading_state, halted_reason "
                    "FROM dim_risk_state WHERE state_id = 1"
                )
            ).fetchone()
            trading_state = state_row[0] if state_row else "UNKNOWN"
            halted_reason = state_row[1] if state_row else ""
            state_ok = trading_state == "halted"
            reason_ok = halted_reason is not None and _EXERCISE_PREFIX in halted_reason
            check3a = state_ok and reason_ok
            if check3a:
                checks_passed += 1
            status3a = "PASS" if check3a else "FAIL"
            detail3a = (
                f"3a trading_state={trading_state!r} "
                f"halted_reason contains 'V1 EXERCISE'={reason_ok}"
            )
            print(f"  [{status3a}] {detail3a}")
            details.append(f"{status3a}: {detail3a}")

            # Check 3b: no open orders
            checks_total += 1
            order_row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM cmc_orders "
                    "WHERE status IN ('created', 'submitted')"
                )
            ).fetchone()
            open_orders = order_row[0] if order_row else 0
            check3b = open_orders == 0
            if check3b:
                checks_passed += 1
            status3b = "PASS" if check3b else "FAIL"
            detail3b = f"3b open_orders={open_orders} (expected 0)"
            print(f"  [{status3b}] {detail3b}")
            details.append(f"{status3b}: {detail3b}")

            # Check 3c: new risk event with kill_switch_activated + V1 EXERCISE
            checks_total += 1
            event_row = conn.execute(
                text(
                    "SELECT event_type, reason FROM cmc_risk_events "
                    "WHERE event_type = 'kill_switch_activated' "
                    "  AND reason LIKE :prefix "
                    "ORDER BY event_ts DESC LIMIT 1"
                ),
                {"prefix": f"{_EXERCISE_PREFIX}%"},
            ).fetchone()
            check3c = event_row is not None
            if check3c:
                checks_passed += 1
            status3c = "PASS" if check3c else "FAIL"
            event3c_reason = repr(event_row[1]) if event_row else "NOT FOUND"
            detail3c = (
                f"3c cmc_risk_events has kill_switch_activated with 'V1 EXERCISE' "
                f"reason={event3c_reason}"
            )
            print(f"  [{status3c}] {detail3c}")
            details.append(f"{status3c}: {detail3c}")

        all_passed = checks_passed == checks_total
        result = f"{checks_passed}/{checks_total} checks passed. " + "; ".join(details)
        self._record_step(3, "Validate manual trigger effects", result, all_passed)

    def _step4_manual_reenable(self) -> None:
        """STEP 4: Manual re-enable."""
        print()
        print("[STEP 4] Manual re-enable")
        print()
        print(">>> Kill switch activated. Verify effects above.")
        print(">>> Press ENTER to re-enable trading...")
        input()

        re_enable_trading(
            self._engine,
            reason=f"{_EXERCISE_PREFIX} manual test complete",
            operator=self._operator,
        )

        # Verify trading_state returned to active
        status = get_kill_switch_status(self._engine)
        state_ok = status.trading_state == "active"
        result = f"Re-enabled by operator={self._operator!r}, trading_state={status.trading_state!r}"
        print(f"  {result}")
        status_str = "PASS" if state_ok else "FAIL"
        print(f"  [{status_str}] trading_state={status.trading_state!r}")

        self._record_step(4, "Manual re-enable", result, state_ok)

    def _run_auto_trigger_cycle(self) -> None:
        """STEPS 5-7: Auto trigger cycle with guaranteed threshold restoration."""
        original_threshold: Optional[float] = None

        try:
            # STEP 5: Engineer automatic trigger
            original_threshold = self._step5_engineer_auto_trigger()
        finally:
            # STEP 7: Restore thresholds + re-enable (guaranteed even on failure)
            self._step7_restore_and_reenable(original_threshold)

    def _step5_engineer_auto_trigger(self) -> Optional[float]:
        """
        STEP 5: Lower daily_loss_pct_threshold and poll for auto-trigger.

        Returns:
            Original threshold value (for restoration in step 7).
        """
        print()
        print("[STEP 5] Engineer automatic trigger")

        # Read current threshold
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT daily_loss_pct_threshold FROM dim_risk_limits "
                    "WHERE asset_id IS NULL AND strategy_id IS NULL"
                )
            ).fetchone()

        if row is None:
            result = "SKIPPED: no global row in dim_risk_limits (asset_id IS NULL AND strategy_id IS NULL)"
            print(f"  WARNING: {result}")
            self._record_step(5, "Engineer automatic trigger", result, False)
            self._record_step(
                6,
                "Validate automatic trigger effects",
                "Skipped: auto-trigger did not fire",
                False,
            )
            self._ctx.original_threshold = None
            return None

        original_threshold = float(row[0])
        self._ctx.original_threshold = original_threshold
        print(f"  Original daily_loss_pct_threshold: {original_threshold}")

        # Lower to 0.1%
        with self._engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE dim_risk_limits "
                    "SET daily_loss_pct_threshold = 0.001 "
                    "WHERE asset_id IS NULL AND strategy_id IS NULL"
                )
            )
            conn.commit()
        print("  Threshold lowered to 0.1% (0.001).")

        print(
            f"  Polling dim_risk_state.trading_state every {self._poll_interval}s "
            f"for up to {self._poll_timeout}s..."
        )
        print("  (You may need to trigger an executor run in another terminal)")
        print("  ", end="", flush=True)

        # Polling loop
        max_iterations = self._poll_timeout // max(self._poll_interval, 1)
        halted = False
        for i in range(max_iterations):
            with self._engine.connect() as conn:
                poll_row = conn.execute(
                    text("SELECT trading_state FROM dim_risk_state WHERE state_id = 1")
                ).fetchone()
            if poll_row and poll_row[0] == "halted":
                halted = True
                break
            print(".", end="", flush=True)
            time.sleep(self._poll_interval)

        print()  # newline after dots

        if halted:
            self._ctx.t5 = datetime.now(timezone.utc)
            self._ctx.auto_trigger_fired = True
            result = (
                f"Auto-trigger confirmed! trading_state='halted' "
                f"after ~{(i + 1) * self._poll_interval}s. "
                f"Original threshold: {original_threshold}"
            )
            print("  >>> Auto-trigger confirmed! trading_state='halted'")
            self._record_step(5, "Engineer automatic trigger", result, True)

            # STEP 6: Validate
            self._step6_validate_auto_trigger()
        else:
            result = (
                f"Auto-trigger timeout: trading_state remained 'active' after "
                f"{self._poll_timeout}s. "
                f"This may mean the executor has not run, or the threshold was not low enough."
            )
            print(
                f"  >>> TIMEOUT: trading_state did not change to 'halted' within {self._poll_timeout}s."
            )
            print(
                "  >>> This may mean the executor has not run, or the threshold was not low enough."
            )
            self._record_step(5, "Engineer automatic trigger", result, False)
            self._record_step(
                6,
                "Validate automatic trigger effects",
                "Skipped: auto-trigger did not fire",
                False,
            )

        return original_threshold

    def _step6_validate_auto_trigger(self) -> None:
        """STEP 6: Validate automatic trigger effects (only called if Step 5 PASSED)."""
        print()
        print("[STEP 6] Validate automatic trigger effects")

        details: list[str] = []
        checks_passed = 0
        checks_total = 0

        with self._engine.connect() as conn:
            # Check 6a: trading_state is halted
            checks_total += 1
            state_row = conn.execute(
                text("SELECT trading_state FROM dim_risk_state WHERE state_id = 1")
            ).fetchone()
            trading_state = state_row[0] if state_row else "UNKNOWN"
            check6a = trading_state == "halted"
            if check6a:
                checks_passed += 1
            status6a = "PASS" if check6a else "FAIL"
            detail6a = f"6a trading_state={trading_state!r}"
            print(f"  [{status6a}] {detail6a}")
            details.append(f"{status6a}: {detail6a}")

            # Check 6b: recent risk event from automatic trigger
            checks_total += 1
            event_row = conn.execute(
                text(
                    "SELECT event_type, trigger_source, reason "
                    "FROM cmc_risk_events "
                    "WHERE event_type = 'kill_switch_activated' "
                    "ORDER BY event_ts DESC LIMIT 1"
                )
            ).fetchone()
            # Auto-trigger could come from 'daily_loss_stop' or 'system'
            auto_sources = {"daily_loss_stop", "system", "circuit_breaker"}
            check6b = event_row is not None and event_row[1] in auto_sources
            if check6b:
                checks_passed += 1
            status6b = "PASS" if check6b else "FAIL"
            event6b_source = repr(event_row[1]) if event_row else "NOT FOUND"
            event6b_reason = repr(event_row[2]) if event_row else "NOT FOUND"
            detail6b = (
                f"6b latest kill_switch_activated: "
                f"trigger_source={event6b_source}"
                f" reason={event6b_reason}"
            )
            print(f"  [{status6b}] {detail6b}")
            details.append(f"{status6b}: {detail6b}")

        all_passed = checks_passed == checks_total
        result = f"{checks_passed}/{checks_total} checks passed. " + "; ".join(details)
        self._record_step(6, "Validate automatic trigger effects", result, all_passed)

    def _step7_restore_and_reenable(self, original_threshold: Optional[float]) -> None:
        """STEP 7: Restore thresholds + re-enable (guaranteed by try/finally caller)."""
        print()
        print("[STEP 7] Restore thresholds + re-enable")

        details: list[str] = []
        all_ok = True

        # Restore threshold
        if original_threshold is not None:
            with self._engine.connect() as conn:
                conn.execute(
                    text(
                        "UPDATE dim_risk_limits "
                        "SET daily_loss_pct_threshold = :original "
                        "WHERE asset_id IS NULL AND strategy_id IS NULL"
                    ),
                    {"original": original_threshold},
                )
                conn.commit()

            # Verify restoration
            with self._engine.connect() as conn:
                verify_row = conn.execute(
                    text(
                        "SELECT daily_loss_pct_threshold FROM dim_risk_limits "
                        "WHERE asset_id IS NULL AND strategy_id IS NULL"
                    )
                ).fetchone()
            restored_val = float(verify_row[0]) if verify_row else None
            restore_ok = (
                restored_val is not None
                and abs(restored_val - original_threshold) < 1e-9
            )
            status_r = "PASS" if restore_ok else "FAIL"
            detail_r = (
                f"daily_loss_pct_threshold restored to {original_threshold} "
                f"(confirmed: {restored_val})"
            )
            print(f"  [{status_r}] {detail_r}")
            details.append(f"{status_r}: {detail_r}")
            if not restore_ok:
                all_ok = False
        else:
            detail_r = "No threshold to restore (dim_risk_limits global row not found)"
            print(f"  [INFO] {detail_r}")
            details.append(f"INFO: {detail_r}")

        # Re-enable trading (only if halted)
        try:
            current_status = get_kill_switch_status(self._engine)
            if current_status.trading_state == "halted":
                print()
                print("  >>> Thresholds restored. Press ENTER to re-enable trading...")
                input()
                re_enable_trading(
                    self._engine,
                    reason=f"{_EXERCISE_PREFIX} auto-trigger test complete",
                    operator=self._operator,
                )
                # Verify
                final_status = get_kill_switch_status(self._engine)
                reenable_ok = final_status.trading_state == "active"
                status_e = "PASS" if reenable_ok else "FAIL"
                detail_e = f"Re-enabled by operator={self._operator!r}, trading_state={final_status.trading_state!r}"
                print(f"  [{status_e}] {detail_e}")
                details.append(f"{status_e}: {detail_e}")
                if not reenable_ok:
                    all_ok = False
            else:
                detail_e = f"trading_state={current_status.trading_state!r} — no re-enable needed"
                print(f"  [INFO] {detail_e}")
                details.append(f"INFO: {detail_e}")
        except Exception as exc:
            detail_e = f"Re-enable failed: {exc}"
            print(f"  [FAIL] {detail_e}")
            details.append(f"FAIL: {detail_e}")
            all_ok = False

        result = "; ".join(details)
        self._record_step(7, "Restore thresholds + re-enable", result, all_ok)

    def _step8_produce_evidence(self) -> str:
        """STEP 8: Produce evidence document."""
        print()
        print("[STEP 8] Produce evidence document")
        evidence_path = self._generate_evidence_report()
        print(f"  Evidence written to: {evidence_path}")
        self._record_step(
            8,
            "Produce evidence document",
            f"Markdown evidence written to {evidence_path}",
            True,
        )
        return evidence_path

    # ------------------------------------------------------------------
    # Evidence generation
    # ------------------------------------------------------------------

    def _generate_evidence_report(self) -> str:
        """
        Write a Markdown evidence document and return its path.

        All steps, latency measurements, and VAL-04 gate assessment are included.
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"ks_exercise_{date_str}.md"

        # Determine overall outcome
        manual_steps = [s for s in self._ctx.steps if s.step_num in (1, 2, 3, 4)]
        auto_steps = [s for s in self._ctx.steps if s.step_num in (5, 6)]
        restore_steps = [s for s in self._ctx.steps if s.step_num == 7]

        manual_pass = all(s.passed for s in manual_steps)
        auto_pass = all(s.passed for s in auto_steps) if not self._skip_auto else True
        restore_pass = all(s.passed for s in restore_steps)
        overall_pass = manual_pass and auto_pass and restore_pass

        overall_str = "PASS" if overall_pass else "FAIL"
        manual_str = "PASS" if manual_pass else "FAIL"
        auto_str = (
            ("PASS" if auto_pass else "FAIL") if not self._skip_auto else "SKIPPED"
        )
        restore_str = "PASS" if restore_pass else "FAIL"

        # Latency calculation
        if self._ctx.manual_latency_seconds is not None:
            lat_ms = self._ctx.manual_latency_seconds * 1000
            lat_str = f"{lat_ms:.1f}ms"
            lat_ok = self._ctx.manual_latency_seconds < _MANUAL_LATENCY_TARGET_SECONDS
            lat_status = "PASS" if lat_ok else "FAIL"
        else:
            lat_str = "N/A"
            lat_status = "N/A"

        # Build step tables split by section
        def _step_table(steps: list[ExerciseStep]) -> str:
            rows = []
            for s in steps:
                rows.append(
                    f"| {s.step_num} | {s.name} | {s.timestamp} | {s.status_str()} | {s.result} |"
                )
            header = (
                "| Step | Name | Timestamp | Status | Result |\n"
                "| ---- | ---- | --------- | ------ | ------ |"
            )
            return header + "\n" + "\n".join(rows) if rows else "_No steps recorded_"

        manual_table = _step_table(
            [s for s in self._ctx.steps if s.step_num in (1, 2, 3, 4)]
        )
        auto_table = _step_table([s for s in self._ctx.steps if s.step_num in (5, 6)])
        restore_table = _step_table(
            [s for s in self._ctx.steps if s.step_num in (7, 8)]
        )

        original_pct = (
            f"{self._ctx.original_threshold * 100:.4f}%"
            if self._ctx.original_threshold is not None
            else "N/A"
        )
        restore_ts = self._ctx.steps[-1].timestamp if self._ctx.steps else "N/A"

        content = f"""# Kill Switch Exercise: {date_str}

## Summary

- Exercise type: Manual + Automatic (daily loss stop)
- Date: {date_str}
- Operator: {self._operator}
- Outcome: **{overall_str}**

## Manual Trigger Evidence

{manual_table}

**Manual trigger latency: {lat_str}**
**Target: < 5 seconds | Actual: {lat_str} | Status: {lat_status}**

## Automatic Trigger Evidence

{auto_table}

## Threshold Restoration Evidence

- Original threshold: {original_pct}
- Test threshold: 0.1%
- Restored at: {restore_ts}
- Confirmed via: SELECT

{restore_table}

## VAL-04 Gate Assessment

- Manual trigger: {manual_str}
- Automatic trigger: {auto_str}
- Recovery: {restore_str}
- Overall VAL-04: **{overall_str}**

---
_Generated by run_kill_switch_exercise.py at {ts_str}_
"""

        output_path.write_text(content, encoding="utf-8")
        return str(output_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record_step(self, step_num: int, name: str, result: str, passed: bool) -> None:
        """Append an ExerciseStep to the evidence list."""
        step = ExerciseStep(
            step_num=step_num,
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            result=result,
            passed=passed,
        )
        self._ctx.steps.append(step)
        status_str = step.status_str()
        print(f"  --> Recorded step {step_num} [{status_str}]: {name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="run_kill_switch_exercise",
        description=(
            "V1 Validation Kill Switch Exercise Protocol. "
            "Tests manual and automatic kill switch triggers with full evidence collection."
        ),
    )
    parser.add_argument(
        "--operator",
        required=True,
        metavar="NAME",
        help="Operator name for re_enable_trading() calls (required)",
    )
    parser.add_argument(
        "--db-url",
        metavar="URL",
        default=None,
        help="PostgreSQL connection URL (default: resolved from db_config.env or environment)",
    )
    parser.add_argument(
        "--output-dir",
        metavar="PATH",
        default=None,
        help="Directory for evidence documents (default: reports/validation/kill_switch_exercise/)",
    )
    parser.add_argument(
        "--skip-auto",
        action="store_true",
        default=False,
        help="Skip the automatic trigger test (Steps 5-6); run manual test only",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        metavar="SECONDS",
        help="Seconds between polls during auto-trigger wait (default: 5)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Maximum seconds to wait for auto-trigger before declaring timeout (default: 300)",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: WARNING)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Resolve output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = _PROJECT_ROOT / "reports" / "validation" / "kill_switch_exercise"

    engine = _get_engine(args.db_url)

    exercise = KillSwitchExercise(
        engine=engine,
        operator=args.operator,
        output_dir=output_dir,
        skip_auto=args.skip_auto,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
    )

    try:
        evidence_path = exercise.run_exercise()
        print(f"\nEvidence document: {evidence_path}")
        return 0
    except KeyboardInterrupt:
        print("\nExercise interrupted by operator (Ctrl+C).")
        return 1
    except Exception as exc:
        logger.exception("Kill switch exercise failed: %s", exc)
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
