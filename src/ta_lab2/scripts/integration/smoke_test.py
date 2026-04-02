"""
smoke_test.py
~~~~~~~~~~~~~
v1.2.0 End-to-End Pipeline Smoke Test.

Single-command pipeline health verification covering all 9 v1.2.0 pipeline
stages plus Step 0 prerequisites. Designed to be run before and during the
Phase 88 burn-in period.

Checks verify recency (ts >= NOW() - 48h) not just row existence for live
data tables. Executor and drift tables use existence-only checks (paper
trading may have no fills yet).

Exit codes:
  0  -- all checks PASS (or only WARN)
  1  -- one or more FAIL

Usage:
    python -m ta_lab2.scripts.integration.smoke_test
    python -m ta_lab2.scripts.integration.smoke_test --verbose
    python -m ta_lab2.scripts.integration.smoke_test --ids 1,52,825
    python -m ta_lab2.scripts.integration.smoke_test --db-url postgresql://...

Design notes:
  - Follows run_preflight_check.py namedtuple pattern exactly.
  - NullPool engine (project convention for CLI scripts).
  - resolve_db_url() from refresh_utils for DB URL resolution.
  - ASCII-only output (NO UTF-8 box-drawing chars -- Windows cp1252 safety).
  - All file I/O with encoding='utf-8'.
  - Test assets: BTC (id=1), ETH (id=52), plus extras [825, 5426] by default.
  - --ids flag allows runtime override of test assets.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from typing import Callable

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEPARATOR = "=" * 60
_STALENESS_HOURS = 48
_DEFAULT_IDS = [1, 52, 825, 5426]  # BTC, ETH, USDT, XRP

# ---------------------------------------------------------------------------
# Named tuples (mirrors run_preflight_check.py pattern)
# ---------------------------------------------------------------------------

SmokeCheck = namedtuple("SmokeCheck", ["name", "query", "validator"])
"""
name      -- human-readable check name (shown in output)
query     -- SQL string to execute
validator -- callable(row) -> (passed: bool, detail: str)
             row is the raw fetchone() result (or None if no rows)
"""

SmokeResult = namedtuple("SmokeResult", ["name", "status", "detail"])
"""Populated result after running a check."""

# ---------------------------------------------------------------------------
# DB engine helper (NullPool pattern -- project convention)
# ---------------------------------------------------------------------------


def _get_engine(db_url: str | None = None):
    """Create SQLAlchemy engine with NullPool."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.scripts.refresh_utils import resolve_db_url

    url = db_url or resolve_db_url()
    return create_engine(url, poolclass=NullPool)


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


def _val_count_zero(label: str) -> Callable:
    """Return validator that passes when COUNT(*) == 0."""

    def validator(row):
        count = int(row[0]) if row else 0
        if count == 0:
            return True, f"0 {label} (OK)"
        return False, f"found {count} {label}"

    return validator


def _val_stale_check(label: str, hours: int = _STALENESS_HOURS) -> Callable:
    """Return validator that passes when MAX(ts) is within the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    def validator(row):
        raw_ts = row[0] if row else None
        if raw_ts is None:
            return False, f"no rows found for {label}"
        ts = pd.Timestamp(raw_ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        if ts >= cutoff:
            return (
                True,
                f"latest {label} = {ts.isoformat()} (within {hours}h)",
            )
        hours_stale = (
            datetime.now(timezone.utc) - ts.to_pydatetime()
        ).total_seconds() / 3600
        return (
            False,
            f"latest {label} = {ts.isoformat()} ({hours_stale:.1f}h ago, expect < {hours}h)",
        )

    return validator


def _val_range(col_label: str, lo: float, hi: float) -> Callable:
    """Return validator that passes when lo <= row[0] <= hi."""

    def validator(row):
        value = row[0] if row else None
        if value is None:
            return False, f"{col_label} is NULL"
        val = float(value)
        if lo <= val <= hi:
            return True, f"{col_label} = {val:.6g} (in [{lo}, {hi}])"
        return False, f"{col_label} = {val:.6g} out of range [{lo}, {hi}]"

    return validator


def _val_accessible(label: str) -> Callable:
    """Return validator that passes whenever the query executes without error."""

    def validator(row):
        count = int(row[0]) if row else 0
        return True, f"{label} accessible ({count} rows)"

    return validator


def _val_positive(label: str) -> Callable:
    """Return validator that passes when value is NOT NULL and > 0."""

    def validator(row):
        value = row[0] if row else None
        if value is not None and float(value) > 0:
            return True, f"{label} = {value}"
        return False, f"expected {label} to be > 0, got {value!r}"

    return validator


def _val_direction_clean(label: str) -> Callable:
    """Return validator that passes when COUNT of invalid direction values == 0."""

    def validator(row):
        count = int(row[0]) if row else 0
        if count == 0:
            return True, f"all {label} directions valid"
        return False, f"{count} {label} rows with invalid direction"

    return validator


# ---------------------------------------------------------------------------
# Step 0: Prerequisites
# ---------------------------------------------------------------------------


def _build_step0_checks() -> list[SmokeCheck]:
    """Step 0: DB connectivity and alembic migration sanity."""
    return [
        SmokeCheck(
            name="[Step 0] DB connectivity",
            query="SELECT 1",
            validator=lambda row: (True, "connected")
            if row
            else (False, "no response"),
        ),
        SmokeCheck(
            name="[Step 0] Alembic migrations applied",
            query="SELECT COUNT(*) FROM alembic_version",
            validator=_val_count_gte(1, "alembic_version rows"),
        ),
        SmokeCheck(
            name="[Step 0] dim_venues has rows",
            query="SELECT COUNT(*) FROM dim_venues",
            validator=_val_count_gte(1, "venue rows"),
        ),
        SmokeCheck(
            name="[Step 0] dim_timeframe has rows",
            query="SELECT COUNT(*) FROM dim_timeframe",
            validator=_val_count_gte(1, "timeframe rows"),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 1: Price bars
# ---------------------------------------------------------------------------


def _build_bars_checks(ids: list[int]) -> list[SmokeCheck]:
    """Stage 1: price_bars_multi_tf_u recency and value sanity."""
    ids_literal = ",".join(str(i) for i in ids)
    return [
        SmokeCheck(
            name="[bars] recent 1D bars for test assets",
            query=(
                f"SELECT COUNT(*) FROM price_bars_multi_tf_u "
                f"WHERE id IN ({ids_literal}) AND tf='1D' "
                f"AND ts >= NOW() - INTERVAL '{_STALENESS_HOURS} hours'"
            ),
            validator=_val_count_gte(1, "recent 1D bars"),
        ),
        SmokeCheck(
            name="[bars] latest BTC 1D bar recency",
            query=(
                "SELECT MAX(ts) FROM price_bars_multi_tf_u "
                "WHERE id=1 AND tf='1D' AND alignment_source='multi_tf'"
            ),
            validator=_val_stale_check("BTC 1D bar ts"),
        ),
        SmokeCheck(
            name="[bars] no NULL close prices",
            query=(
                f"SELECT COUNT(*) FROM price_bars_multi_tf_u "
                f"WHERE id IN ({ids_literal}) AND tf='1D' AND close IS NULL"
            ),
            validator=_val_count_zero("NULL close prices"),
        ),
        SmokeCheck(
            name="[bars] close > 0 for test assets",
            query=(
                f"SELECT COUNT(*) FROM price_bars_multi_tf_u "
                f"WHERE id IN ({ids_literal}) AND tf='1D' AND close <= 0"
            ),
            validator=_val_count_zero("non-positive close prices"),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 2: EMAs
# ---------------------------------------------------------------------------


def _build_emas_checks(ids: list[int]) -> list[SmokeCheck]:
    """Stage 2: ema_multi_tf_u recency and value sanity."""
    ids_literal = ",".join(str(i) for i in ids)
    return [
        SmokeCheck(
            name="[emas] recent 1D EMA rows for test assets",
            query=(
                f"SELECT COUNT(*) FROM ema_multi_tf_u "
                f"WHERE id IN ({ids_literal}) AND tf='1D' "
                f"AND ts >= NOW() - INTERVAL '{_STALENESS_HOURS} hours'"
            ),
            validator=_val_count_gte(1, "recent 1D EMA rows"),
        ),
        SmokeCheck(
            name="[emas] latest BTC 1D EMA recency",
            query=("SELECT MAX(ts) FROM ema_multi_tf_u WHERE id=1 AND tf='1D'"),
            validator=_val_stale_check("ema_multi_tf_u 1D ts"),
        ),
        SmokeCheck(
            name="[emas] d1 > 0 for test assets",
            query=(
                f"SELECT COUNT(*) FROM ema_multi_tf_u "
                f"WHERE id IN ({ids_literal}) AND tf='1D' "
                f"AND ts >= NOW() - INTERVAL '{_STALENESS_HOURS} hours' "
                f"AND (d1 IS NULL OR d1 <= 0)"
            ),
            validator=_val_count_zero("EMA rows with d1 NULL or <= 0"),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 3: Features
# ---------------------------------------------------------------------------


def _build_features_checks(ids: list[int]) -> list[SmokeCheck]:
    """Stage 3: features recency and non-null sanity."""
    ids_literal = ",".join(str(i) for i in ids)
    return [
        SmokeCheck(
            name="[features] recent 1D feature rows for test assets",
            query=(
                f"SELECT COUNT(*) FROM features "
                f"WHERE id IN ({ids_literal}) AND tf='1D' "
                f"AND ts >= NOW() - INTERVAL '{_STALENESS_HOURS} hours'"
            ),
            validator=_val_count_gte(1, "recent 1D feature rows"),
        ),
        SmokeCheck(
            name="[features] latest BTC 1D features recency",
            query="SELECT MAX(ts) FROM features WHERE id=1 AND tf='1D'",
            validator=_val_stale_check("features 1D ts"),
        ),
        SmokeCheck(
            name="[features] rsi_14 not NULL for BTC 1D recent rows",
            query=(
                "SELECT COUNT(*) FROM features "
                "WHERE id=1 AND tf='1D' "
                "AND ts >= NOW() - INTERVAL '7 days' "
                "AND rsi_14 IS NOT NULL"
            ),
            validator=_val_count_gte(1, "rows with rsi_14 not NULL"),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 4: GARCH
# ---------------------------------------------------------------------------


def _build_garch_checks() -> list[SmokeCheck]:
    """Stage 4: garch_forecasts and garch_forecasts_latest sanity."""
    return [
        SmokeCheck(
            name="[garch] BTC has recent GARCH forecast",
            query=(
                "SELECT COUNT(*) FROM garch_forecasts "
                "WHERE id=1 "
                "AND created_at >= NOW() - INTERVAL '48 hours'"
            ),
            validator=_val_count_gte(1, "recent BTC GARCH forecasts"),
        ),
        SmokeCheck(
            name="[garch] garch_forecasts_latest BTC cond_vol in range",
            query=("SELECT cond_vol FROM garch_forecasts_latest WHERE id=1 LIMIT 1"),
            validator=_val_range("BTC cond_vol", 0.0, 5.0),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 5: Signals
# ---------------------------------------------------------------------------


def _build_signals_checks(ids: list[int]) -> list[SmokeCheck]:
    """Stage 5: signals_ema_crossover recency and direction validity."""
    ids_literal = ",".join(str(i) for i in ids)
    return [
        SmokeCheck(
            name="[signals] recent EMA crossover signals for test assets",
            query=(
                f"SELECT COUNT(*) FROM signals_ema_crossover "
                f"WHERE id IN ({ids_literal}) "
                f"AND ts >= NOW() - INTERVAL '{_STALENESS_HOURS} hours'"
            ),
            validator=_val_count_gte(1, "recent EMA crossover signal rows"),
        ),
        SmokeCheck(
            name="[signals] no invalid direction values",
            query=(
                f"SELECT COUNT(*) FROM signals_ema_crossover "
                f"WHERE id IN ({ids_literal}) "
                f"AND ts >= NOW() - INTERVAL '{_STALENESS_HOURS} hours' "
                f"AND direction NOT IN ('long', 'short')"
            ),
            validator=_val_direction_clean("EMA crossover"),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 6: Stop calibrations
# ---------------------------------------------------------------------------


def _build_stop_calibrations_checks() -> list[SmokeCheck]:
    """Stage 6: stop_calibrations row count and value sanity."""
    return [
        SmokeCheck(
            name="[stop_calibrations] table has rows",
            query="SELECT COUNT(*) FROM stop_calibrations",
            validator=_val_count_gte(1, "stop_calibration rows"),
        ),
        SmokeCheck(
            name="[stop_calibrations] sl_p50 in range (0, 1)",
            query=(
                "SELECT sl_p50 FROM stop_calibrations WHERE sl_p50 IS NOT NULL LIMIT 1"
            ),
            validator=_val_range("sl_p50", 0.0, 1.0),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 7: Portfolio allocations
# ---------------------------------------------------------------------------


def _build_portfolio_checks() -> list[SmokeCheck]:
    """Stage 7: portfolio_allocations row count and weight sanity."""
    return [
        SmokeCheck(
            name="[portfolio_allocations] table has rows",
            query="SELECT COUNT(*) FROM portfolio_allocations",
            validator=_val_count_gte(1, "portfolio_allocation rows"),
        ),
        SmokeCheck(
            name="[portfolio_allocations] no out-of-range weights",
            query=(
                "SELECT COUNT(*) FROM portfolio_allocations "
                "WHERE weight < -1.0 OR weight > 1.0"
            ),
            validator=_val_count_zero("out-of-range weight rows"),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 8: Executor (orders / fills)
# ---------------------------------------------------------------------------


def _build_executor_checks() -> list[SmokeCheck]:
    """Stage 8: orders and fills table accessibility + value sanity."""
    return [
        SmokeCheck(
            name="[executor] orders table accessible",
            query="SELECT COUNT(*) FROM orders",
            validator=_val_accessible("orders"),
        ),
        SmokeCheck(
            name="[executor] fills: fill_price > 0 where rows exist",
            query=(
                "SELECT COUNT(*) FROM fills "
                "WHERE fill_price IS NOT NULL AND fill_price <= 0"
            ),
            validator=_val_count_zero("fills with fill_price <= 0"),
        ),
    ]


# ---------------------------------------------------------------------------
# Stage 9: Drift
# ---------------------------------------------------------------------------


def _build_drift_checks() -> list[SmokeCheck]:
    """Stage 9: drift_metrics table accessibility and value sanity."""
    return [
        SmokeCheck(
            name="[drift] drift_metrics table accessible",
            query="SELECT COUNT(*) FROM drift_metrics",
            validator=_val_accessible("drift_metrics"),
        ),
        SmokeCheck(
            name="[drift] tracking_error_5d >= 0 where rows exist",
            query=(
                "SELECT COUNT(*) FROM drift_metrics "
                "WHERE tracking_error_5d IS NOT NULL AND tracking_error_5d < 0"
            ),
            validator=_val_count_zero("drift rows with negative tracking_error_5d"),
        ),
    ]


# ---------------------------------------------------------------------------
# Build all checks
# ---------------------------------------------------------------------------


def _build_all_checks(ids: list[int]) -> list[SmokeCheck]:
    """Combine all pipeline stage checks into ordered list."""
    checks: list[SmokeCheck] = []
    checks.extend(_build_step0_checks())
    checks.extend(_build_bars_checks(ids))
    checks.extend(_build_emas_checks(ids))
    checks.extend(_build_features_checks(ids))
    checks.extend(_build_garch_checks())
    checks.extend(_build_signals_checks(ids))
    checks.extend(_build_stop_calibrations_checks())
    checks.extend(_build_portfolio_checks())
    checks.extend(_build_executor_checks())
    checks.extend(_build_drift_checks())
    return checks


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------


def _run_check(engine, check: SmokeCheck) -> SmokeResult:
    """Execute one smoke check and return its result."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text(check.query)).fetchone()
        passed, detail = check.validator(row)
        return SmokeResult(
            name=check.name,
            status="PASS" if passed else "FAIL",
            detail=detail,
        )
    except Exception as exc:
        return SmokeResult(
            name=check.name,
            status="FAIL",
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _print_results(results: list[SmokeResult], verbose: bool) -> None:
    """Print all check results with summary."""
    print("=== v1.2.0 Pipeline Smoke Test ===")
    print()

    for r in results:
        tag = f"[{r.status}]"
        if verbose or r.status != "PASS":
            print(f"{tag:<8} {r.name}")
            if r.status != "PASS" or verbose:
                print(f"         --> {r.detail}")
        else:
            print(f"{tag:<8} {r.name}")

    print()
    print(_SEPARATOR)

    n_pass = sum(1 for r in results if r.status == "PASS")
    n_warn = sum(1 for r in results if r.status == "WARN")
    n_fail = sum(1 for r in results if r.status == "FAIL")
    total = len(results)

    summary_parts = [f"{n_pass}/{total} PASS"]
    if n_warn:
        summary_parts.append(f"{n_warn} WARN")
    if n_fail:
        summary_parts.append(f"{n_fail} FAIL")

    result_line = "SMOKE TEST RESULT: " + ", ".join(summary_parts)
    print(result_line)
    print(_SEPARATOR)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_smoke_test(
    db_url: str | None = None,
    verbose: bool = False,
    ids: list[int] | None = None,
) -> int:
    """
    Run all smoke test checks.

    Parameters
    ----------
    db_url:
        Optional database URL override. Defaults to resolve_db_url().
    verbose:
        Print all check detail lines (not just failures).
    ids:
        Asset IDs to use for per-asset checks. Defaults to _DEFAULT_IDS.

    Returns
    -------
    Exit code: 0 if no FAILs, 1 if any FAIL.
    """
    asset_ids = ids if ids is not None else _DEFAULT_IDS
    engine = _get_engine(db_url)
    all_checks = _build_all_checks(asset_ids)

    results: list[SmokeResult] = []
    for check in all_checks:
        result = _run_check(engine, check)
        results.append(result)

    _print_results(results, verbose=verbose)

    n_fail = sum(1 for r in results if r.status == "FAIL")
    return 0 if n_fail == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "v1.2.0 Pipeline Smoke Test. "
            "Verifies all 9 pipeline stages plus prerequisites. "
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
        help="Print all check detail lines, not just failures.",
    )
    parser.add_argument(
        "--ids",
        default=None,
        metavar="IDS",
        help=(
            "Comma-separated asset IDs to use for per-asset checks. "
            f"Default: {','.join(str(i) for i in _DEFAULT_IDS)} (BTC,ETH,USDT,XRP)."
        ),
    )
    args = parser.parse_args()

    # Parse --ids
    asset_ids: list[int] | None = None
    if args.ids is not None:
        try:
            asset_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        except ValueError as exc:
            print(f"ERROR: invalid --ids value: {exc}", file=sys.stderr)
            sys.exit(1)

    logging.basicConfig(level=logging.WARNING)

    sys.exit(run_smoke_test(db_url=args.db_url, verbose=args.verbose, ids=asset_ids))


if __name__ == "__main__":
    main()
