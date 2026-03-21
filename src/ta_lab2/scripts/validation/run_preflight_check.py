"""
run_preflight_check.py
~~~~~~~~~~~~~~~~~~~~~~
V1 Validation Pre-Flight Checklist CLI.

Verifies 15 conditions that MUST pass before starting the 14-day validation
clock.  Each check queries the DB (or inspects config) and prints PASS / WARN
/ FAIL with a detail message.

Exit codes:
  0  -- no FAILs (WARNs are informational, not blocking)
  1  -- one or more FAILs

Usage:
    python -m ta_lab2.scripts.validation.run_preflight_check
    python -m ta_lab2.scripts.validation.run_preflight_check --db-url postgresql://...

Design notes:
  - Each check is wrapped in try/except: any unexpected error = FAIL.
  - Staleness checks compare MAX(ts) against now() - 30 hours (UTC).
  - Check 15 (slippage mode) is WARN not FAIL: zero-mode is valid for parity
    testing but means VAL-03 slippage measurement will show 0 bps.
  - ALL file operations use encoding='utf-8' (Windows cp1252 safety per MEMORY.md).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEPARATOR = "=" * 60
_STALENESS_HOURS = 30


# ---------------------------------------------------------------------------
# DB engine helper (NullPool pattern -- project convention)
# ---------------------------------------------------------------------------


def _get_engine(db_url: str | None = None):
    """Create SQLAlchemy engine with NullPool."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.db.config import resolve_db_url

    url = db_url or resolve_db_url()
    return create_engine(url, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Check result type
# ---------------------------------------------------------------------------

PreflightCheck = namedtuple("PreflightCheck", ["name", "query", "validator"])
"""
name      -- human-readable check name (shown in output)
query     -- SQL string to execute (may be None for non-DB checks)
validator -- callable(result) -> (passed: bool, detail: str)
             result is the raw fetchone() result (or None if no rows)
"""

_CheckResult = namedtuple("_CheckResult", ["name", "status", "detail"])
"""Populated result after running a check."""


# ---------------------------------------------------------------------------
# Validator helpers
# ---------------------------------------------------------------------------


def _val_count_gte(expected: int, label: str) -> Callable:
    """Return validator that passes when COUNT(*) result >= expected."""

    def validator(row):
        count = int(row[0]) if row else 0
        if count >= expected:
            return True, f"{count} {label}"
        return False, f"expected >= {expected} {label}, found {count}"

    return validator


def _val_equals(expected, label: str) -> Callable:
    """Return validator that passes when single scalar equals expected."""

    def validator(row):
        value = row[0] if row else None
        if value == expected:
            return True, f"{label} = {value!r}"
        return False, f"expected {label} = {expected!r}, got {value!r}"

    return validator


def _val_is_false(label: str) -> Callable:
    """Return validator that passes when single boolean value is False/falsy."""

    def validator(row):
        value = row[0] if row else None
        if not value:
            return True, f"{label} = {value!r} (OK)"
        return False, f"expected {label} = False, got {value!r}"

    return validator


def _val_not_null_positive(label: str) -> Callable:
    """Return validator that passes when value is NOT NULL and > 0."""

    def validator(row):
        value = row[0] if row else None
        if value is not None and float(value) > 0:
            return True, f"{label} = {value}"
        return False, f"expected {label} to be NOT NULL and > 0, got {value!r}"

    return validator


def _val_stale_check(label: str) -> Callable:
    """Return validator that passes when MAX(ts) is within the last 30 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_STALENESS_HOURS)

    def validator(row):
        raw_ts = row[0] if row else None
        if raw_ts is None:
            return False, f"no rows found for {label}"
        # Parse timestamp with UTC awareness
        ts = pd.Timestamp(raw_ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        if ts >= cutoff:
            return (
                True,
                f"latest {label} = {ts.isoformat()} (within {_STALENESS_HOURS}h)",
            )
        hours_stale = (
            datetime.now(timezone.utc) - ts.to_pydatetime()
        ).total_seconds() / 3600
        return (
            False,
            f"latest {label} = {ts.isoformat()} ({hours_stale:.1f}h ago, expect < {_STALENESS_HOURS}h)",
        )

    return validator


def _val_accessible(label: str) -> Callable:
    """Return validator that passes when query executes without error (row may be None)."""

    def validator(row):
        # If we got here without exception, the table is accessible
        return True, f"{label} accessible"

    return validator


def _val_count_zero(label: str) -> Callable:
    """Return validator that passes when COUNT(*) == 0."""

    def validator(row):
        count = int(row[0]) if row else 0
        if count == 0:
            return True, f"0 {label} (OK)"
        return False, f"found {count} {label}"

    return validator


# ---------------------------------------------------------------------------
# Standard preflight checks (checks 1-14)
# ---------------------------------------------------------------------------


def _build_standard_checks() -> list[PreflightCheck]:
    """Return the 14 standard PASS/FAIL preflight checks."""
    return [
        # 1. DB connectivity
        PreflightCheck(
            name="DB connectivity",
            query="SELECT 1",
            validator=lambda row: (True, "connected")
            if row
            else (False, "no response"),
        ),
        # 2. dim_executor_config has active rows
        PreflightCheck(
            name="dim_executor_config has active rows",
            query="SELECT COUNT(*) FROM dim_executor_config WHERE is_active=TRUE",
            validator=_val_count_gte(1, "active configs"),
        ),
        # 3. Both EMA configs active (ema_trend 17,77 and ema_trend 21,50)
        PreflightCheck(
            name="Both EMA configs active",
            query=(
                "SELECT COUNT(*) FROM dim_executor_config "
                "WHERE is_active=TRUE AND signal_type='ema_crossover'"
            ),
            validator=_val_count_gte(2, "active ema_crossover configs"),
        ),
        # 4. dim_risk_state row exists
        PreflightCheck(
            name="dim_risk_state row exists",
            query="SELECT COUNT(*) FROM dim_risk_state WHERE state_id=1",
            validator=_val_count_gte(1, "rows"),
        ),
        # 5. trading_state is active
        PreflightCheck(
            name="trading_state is active",
            query="SELECT trading_state FROM dim_risk_state WHERE state_id=1",
            validator=_val_equals("active", "trading_state"),
        ),
        # 6. drift_paused is false
        PreflightCheck(
            name="drift_paused is false",
            query="SELECT drift_paused FROM dim_risk_state WHERE state_id=1",
            validator=_val_is_false("drift_paused"),
        ),
        # 7. dim_risk_limits row exists (global row, asset_id IS NULL)
        PreflightCheck(
            name="dim_risk_limits row exists (global)",
            query="SELECT COUNT(*) FROM dim_risk_limits WHERE asset_id IS NULL",
            validator=_val_count_gte(1, "global risk limit rows"),
        ),
        # 8. daily_loss_pct_threshold set and positive
        PreflightCheck(
            name="daily_loss_pct_threshold set",
            query=(
                "SELECT daily_loss_pct_threshold "
                "FROM dim_risk_limits WHERE asset_id IS NULL"
            ),
            validator=_val_not_null_positive("daily_loss_pct_threshold"),
        ),
        # 9. BTC price bars current (< 30 hours)
        PreflightCheck(
            name="BTC price bars current (< 30h)",
            query=(
                "SELECT MAX(ts) FROM price_bars_multi_tf_u "
                "WHERE id=1 AND tf='1D' AND alignment_source='multi_tf'"
            ),
            validator=_val_stale_check("BTC 1D bar ts"),
        ),
        # 10. features current (< 30 hours)
        PreflightCheck(
            name="features current (< 30h)",
            query="SELECT MAX(ts) FROM features WHERE id=1 AND tf='1D'",
            validator=_val_stale_check("features 1D ts"),
        ),
        # 11. EMA data current (< 30 hours)
        PreflightCheck(
            name="EMA data current (< 30h)",
            query=("SELECT MAX(ts) FROM ema_multi_tf_u WHERE id=1 AND tf='1D'"),
            validator=_val_stale_check("ema_multi_tf_u 1D ts"),
        ),
        # 12. No orphaned orders (created/submitted status)
        PreflightCheck(
            name="No orphaned orders",
            query=(
                "SELECT COUNT(*) FROM orders WHERE status IN ('created','submitted')"
            ),
            validator=_val_count_zero("orphaned orders"),
        ),
        # 13. Executor run log accessible
        PreflightCheck(
            name="Executor run log accessible",
            query="SELECT 1 FROM executor_run_log LIMIT 1",
            validator=_val_accessible("executor_run_log"),
        ),
        # 14. drift_metrics accessible
        PreflightCheck(
            name="drift_metrics accessible",
            query="SELECT 1 FROM drift_metrics LIMIT 0",
            validator=_val_accessible("drift_metrics"),
        ),
    ]


# ---------------------------------------------------------------------------
# Check 15: Slippage mode (WARN not FAIL)
# ---------------------------------------------------------------------------


def _run_slippage_mode_check(engine) -> list[_CheckResult]:
    """Run check 15: warn if any active config uses slippage_mode='zero'.

    Returns a list of _CheckResult objects (one per config that uses zero mode,
    or one overall PASS if none do).
    """
    sql = text(
        "SELECT config_id, slippage_mode FROM dim_executor_config WHERE is_active=TRUE"
    )
    results = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()

        zero_mode_configs = [r for r in rows if r[1] == "zero"]
        if not zero_mode_configs:
            results.append(
                _CheckResult(
                    name="Slippage mode check",
                    status="PASS",
                    detail="No active configs use slippage_mode='zero'",
                )
            )
        else:
            for r in zero_mode_configs:
                results.append(
                    _CheckResult(
                        name="Slippage mode check",
                        status="WARN",
                        detail=(
                            f"config_id={r[0]} uses 'zero' mode -- "
                            "VAL-03 slippage measurement requires non-zero slippage mode"
                        ),
                    )
                )
    except Exception as exc:
        results.append(
            _CheckResult(
                name="Slippage mode check",
                status="WARN",
                detail=f"Could not query slippage_mode: {exc}",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------


def _run_check(engine, check: PreflightCheck) -> _CheckResult:
    """Execute one preflight check and return its result."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text(check.query)).fetchone()
        passed, detail = check.validator(row)
        return _CheckResult(
            name=check.name,
            status="PASS" if passed else "FAIL",
            detail=detail,
        )
    except Exception as exc:
        return _CheckResult(
            name=check.name,
            status="FAIL",
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _status_tag(status: str) -> str:
    return f"[{status}]"


def _print_checklist(results: list[_CheckResult]) -> None:
    """Print the formatted checklist output."""
    print(_SEPARATOR)
    print("V1 VALIDATION PRE-FLIGHT CHECKLIST")
    print(_SEPARATOR)
    for r in results:
        tag = _status_tag(r.status)
        print(f"  {tag:<8} {r.name}")
        if r.status != "PASS":
            print(f"           --> {r.detail}")
    print(_SEPARATOR)

    n_pass = sum(1 for r in results if r.status == "PASS")
    n_warn = sum(1 for r in results if r.status == "WARN")
    n_fail = sum(1 for r in results if r.status == "FAIL")

    summary_parts = [f"{n_pass} PASS"]
    if n_warn:
        summary_parts.append(f"{n_warn} WARN")
    if n_fail:
        summary_parts.append(f"{n_fail} FAIL")
    summary = ", ".join(summary_parts)

    if n_fail == 0:
        verdict = "GO: all checks pass -- ready to start 14-day validation clock"
    else:
        verdict = f"HOLD: resolve {n_fail} FAIL(s) before starting 14-day clock"

    print(f"Result: {summary}")
    print(verdict)
    print(_SEPARATOR)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_preflight(db_url: str | None = None) -> int:
    """Run all 15 preflight checks.

    Args:
        db_url: Optional database URL override.  Defaults to resolve_db_url().

    Returns:
        Exit code: 0 if no FAILs, 1 if any FAIL.
    """
    engine = _get_engine(db_url)
    standard_checks = _build_standard_checks()

    results: list[_CheckResult] = []
    for check in standard_checks:
        results.append(_run_check(engine, check))

    # Check 15: slippage mode (WARN, not FAIL)
    results.extend(_run_slippage_mode_check(engine))

    _print_checklist(results)

    n_fail = sum(1 for r in results if r.status == "FAIL")
    return 0 if n_fail == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "V1 Validation Pre-Flight Checklist. "
            "Verifies 15 conditions before starting the 14-day validation clock. "
            "Exit 0 = all pass (no FAILs). Exit 1 = one or more FAILs."
        )
    )
    parser.add_argument(
        "--db-url",
        default=None,
        metavar="URL",
        help="Database URL (defaults to resolve_db_url() from db_config.env)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    sys.exit(run_preflight(db_url=args.db_url))


if __name__ == "__main__":
    main()
