#!/usr/bin/env python
"""
Master orchestrator for all stats runner scripts.

Runs all 6 stats runners covering bars, EMAs, returns, and features:
- Price bars stats (multi-TF)
- EMA stats (multi-TF, calendar, calendar-anchor)
- Returns EMA stats
- CMC features stats

After all runners complete, queries aggregate PASS/WARN/FAIL status from the
stats tables and sends Telegram alerts on FAIL or WARN.

CRITICAL: Stats runners exit 0 even when tests produce FAIL rows in the DB.
This orchestrator queries the DB AFTER all runners complete to determine
aggregate status. Do NOT rely solely on subprocess return codes.

Usage:
    # Run all stats runners
    python -m ta_lab2.scripts.stats.run_all_stats_runners

    # Full refresh (ignores incremental watermarks)
    python -m ta_lab2.scripts.stats.run_all_stats_runners --full-refresh

    # Dry run (list runners, no execution)
    python -m ta_lab2.scripts.stats.run_all_stats_runners --dry-run

    # Verbose (stream subprocess output)
    python -m ta_lab2.scripts.stats.run_all_stats_runners --verbose
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text

from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# Timeout tiers (seconds); initial estimate, tune after observing actual runtimes
TIMEOUT_STATS = 3600  # 1 hour -- stats runners scan large tables

# Stats tables queried for aggregate PASS/WARN/FAIL status
STATS_TABLES = [
    "price_bars_multi_tf_stats",
    "ema_multi_tf_stats",
    "ema_multi_tf_cal_stats",
    "ema_multi_tf_cal_anchor_stats",
    "returns_ema_stats",
    "cmc_features_stats",
]


@dataclass
class StatsScript:
    """Configuration for a stats runner script."""

    name: str
    module: str
    description: str
    extra_args: list[str] = field(default_factory=list)


@dataclass
class ComponentResult:
    """Result of running a stats script."""

    name: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


# All 6 stats runners -- invoked directly via -m (not through intermediate orchestrators)
ALL_STATS_SCRIPTS = [
    StatsScript(
        name="bars",
        module="ta_lab2.scripts.bars.stats.refresh_price_bars_stats",
        description="Price bars stats (multi-TF OHLC, gap, freshness)",
        extra_args=[],
    ),
    StatsScript(
        name="ema_multi_tf",
        module="ta_lab2.scripts.emas.stats.multi_tf.refresh_ema_multi_tf_stats",
        description="EMA stats (multi-TF)",
        extra_args=[],
    ),
    StatsScript(
        name="ema_cal",
        module="ta_lab2.scripts.emas.stats.multi_tf_cal.refresh_ema_multi_tf_cal_stats",
        description="EMA stats (calendar variants)",
        extra_args=[],
    ),
    StatsScript(
        name="ema_cal_anchor",
        module="ta_lab2.scripts.emas.stats.multi_tf_cal_anchor.refresh_ema_multi_tf_cal_anchor_stats",
        description="EMA stats (calendar-anchor variants)",
        extra_args=[],
    ),
    StatsScript(
        name="returns_ema",
        module="ta_lab2.scripts.returns.stats.refresh_returns_ema_stats",
        description="Returns EMA stats (all families)",
        extra_args=["--families", "all"],
    ),
    StatsScript(
        name="features",
        module="ta_lab2.scripts.features.stats.refresh_cmc_features_stats",
        description="CMC features stats",
        extra_args=[],
    ),
]


def run_stats_script(
    script: StatsScript,
    db_url: str | None,
    verbose: bool,
    dry_run: bool,
    full_refresh: bool = True,
) -> ComponentResult:
    """
    Run a stats script via subprocess.

    Stats runners are invoked as Python modules (-m) for clean isolation.
    All 6 runners complete before aggregate DB status is queried.

    Args:
        script: Stats script configuration
        db_url: Database URL (optional, uses config/env if None)
        verbose: Stream subprocess output to stdout
        dry_run: Show what would execute without running
        full_refresh: Pass --full-refresh to ignore incremental watermarks

    Returns:
        ComponentResult with execution details
    """
    cmd = [sys.executable, "-m", script.module]

    # Append runner-specific args first
    cmd.extend(script.extra_args)

    # Common arguments
    if full_refresh:
        cmd.append("--full-refresh")
    if db_url:
        cmd.extend(["--db-url", db_url])
    if verbose:
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print(f"RUNNING: {script.description} ({script.name})")
    print(f"{'=' * 70}")
    if verbose:
        print(f"Command: {' '.join(cmd)}")

    if dry_run:
        print("[DRY RUN] Would execute stats runner")
        return ComponentResult(
            name=script.name,
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if verbose:
            # Stream output directly
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_STATS)
        else:
            # Capture output; show only on error
            result = subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=TIMEOUT_STATS
            )

            if result.returncode != 0:
                print(f"\n[ERROR] Stats runner failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] {script.description} completed in {duration:.1f}s")
            return ComponentResult(
                name=script.name,
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] {script.description} failed: {error_msg}")
            return ComponentResult(
                name=script.name,
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_STATS}s"
        print(f"\n[TIMEOUT] {script.description}: {error_msg}")
        return ComponentResult(
            name=script.name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] {script.description} raised exception: {error_msg}")
        return ComponentResult(
            name=script.name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def query_stats_status(engine, window_hours: int = 2) -> dict[str, dict[str, int]]:
    """
    Query aggregate PASS/WARN/FAIL counts from all stats tables.

    Checks rows written in the last window_hours to capture results from
    the current refresh run. Tables that don't exist are silently skipped
    (returns empty dict for that table).

    Args:
        engine: SQLAlchemy engine connected to the database
        window_hours: Hours to look back for recent rows (default: 2)

    Returns:
        dict mapping table_name -> {status: count}
        e.g. {"price_bars_multi_tf_stats": {"PASS": 10, "FAIL": 2}}
    """
    status_map: dict[str, dict[str, int]] = {}

    with engine.connect() as conn:
        for table in STATS_TABLES:
            try:
                query = text(
                    f"SELECT status, COUNT(*) AS n "  # noqa: S608
                    f"FROM public.{table} "
                    f"WHERE checked_at >= NOW() - INTERVAL ':window_hours hours' "
                    f"GROUP BY status"
                )
                rows = conn.execute(query, {"window_hours": window_hours}).fetchall()
                status_map[table] = {row[0]: int(row[1]) for row in rows}
            except Exception as e:
                # Table may not exist or have no checked_at column -- skip silently
                logger.debug(f"Could not query {table}: {e}")
                status_map[table] = {}

    return status_map


def send_stats_alerts(
    status_results: dict[str, dict[str, int]],
    failed_runners: list[str],
    warn_runners: list[str],
) -> None:
    """
    Send Telegram alerts for FAIL or WARN status.

    FAIL: critical severity -- data quality check failed, pipeline gated.
    WARN: warning severity -- anomalies detected, pipeline continues.

    Args:
        status_results: DB query results from query_stats_status()
        failed_runners: Runner names that crashed (non-zero exit)
        warn_runners: Table names with WARN rows in DB
    """
    try:
        from ta_lab2.notifications import telegram

        if not telegram.is_configured():
            logger.debug("Telegram not configured -- skipping stats alerts")
            return

        # Build lists of tables with each status from DB
        db_fail_tables = [
            t for t, counts in status_results.items() if counts.get("FAIL", 0) > 0
        ]
        db_warn_tables = [
            t for t, counts in status_results.items() if counts.get("WARN", 0) > 0
        ]

        has_fail = bool(db_fail_tables or failed_runners)
        has_warn = bool(db_warn_tables or warn_runners)

        if has_fail:
            parts = []
            if db_fail_tables:
                parts.append(f"DB FAIL rows in: {', '.join(db_fail_tables)}")
            if failed_runners:
                parts.append(f"Crashed runners: {', '.join(failed_runners)}")
            message = "\n".join(parts)
            telegram.send_alert(
                title="Daily Refresh: Stats FAILED",
                message=message,
                severity="critical",
            )
        elif has_warn:
            parts = []
            if db_warn_tables:
                parts.append(f"DB WARN rows in: {', '.join(db_warn_tables)}")
            if warn_runners:
                parts.append(f"Warning runners: {', '.join(warn_runners)}")
            message = "\n".join(parts)
            telegram.send_alert(
                title="Daily Refresh: Stats WARN",
                message=message,
                severity="warning",
            )

    except ImportError:
        logger.debug("Telegram module not available -- skipping alerts")
    except Exception as e:
        logger.warning(f"Failed to send stats Telegram alert: {e}")


def run_all_stats(
    db_url: str,
    verbose: bool = False,
    dry_run: bool = False,
    full_refresh: bool = True,
) -> tuple[str, list[ComponentResult], dict[str, dict[str, int]]]:
    """
    Run all 6 stats runners sequentially, then query DB for aggregate status.

    ALL runners execute to completion before aggregate determination.
    A crash (non-zero returncode) is treated as FAIL for that runner.
    DB rows are the authoritative source of PASS/WARN/FAIL status.

    Args:
        db_url: Database connection URL
        verbose: Stream subprocess output
        dry_run: Dry-run mode (no actual execution)
        full_refresh: Pass --full-refresh to each runner

    Returns:
        (overall_status, results, db_status) where overall_status is
        "FAIL", "WARN", or "PASS"
    """
    results: list[ComponentResult] = []

    # Run ALL 6 stats scripts -- never bail early
    for script in ALL_STATS_SCRIPTS:
        result = run_stats_script(
            script=script,
            db_url=db_url,
            verbose=verbose,
            dry_run=dry_run,
            full_refresh=full_refresh,
        )
        results.append(result)

    # Identify crashed runners (subprocess returned non-zero)
    failed_runners = [r.name for r in results if not r.success]

    # Query DB for aggregate PASS/WARN/FAIL status (skip in dry-run)
    db_status: dict[str, dict[str, int]] = {}
    if not dry_run:
        try:
            engine = create_engine(db_url)
            db_status = query_stats_status(engine)
        except Exception as e:
            logger.warning(f"Could not query stats status from DB: {e}")

    # Determine tables with WARN rows
    warn_runners = [t for t, counts in db_status.items() if counts.get("WARN", 0) > 0]

    # Determine overall status
    db_fail_tables = [t for t, counts in db_status.items() if counts.get("FAIL", 0) > 0]
    if db_fail_tables or failed_runners:
        overall_status = "FAIL"
    elif warn_runners:
        overall_status = "WARN"
    else:
        overall_status = "PASS"

    # Send Telegram alerts
    if not dry_run:
        send_stats_alerts(db_status, failed_runners, warn_runners)

    return overall_status, results, db_status


def print_summary(
    results: list[ComponentResult],
    overall_status: str,
    db_status: dict[str, dict[str, int]],
) -> None:
    """Print execution and DB status summary."""
    print(f"\n{'=' * 70}")
    print("STATS RUNNERS SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for r in results)
    passed = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nTotal runners: {len(results)}")
    print(f"Subprocess success: {len(passed)}")
    print(f"Subprocess failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if passed:
        print("\n[OK] Successful runners:")
        for r in passed:
            print(f"  - {r.name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed runners (subprocess crash):")
        for r in failed:
            error_info = f" ({r.error_message})" if r.error_message else ""
            print(f"  - {r.name}: {r.duration_sec:.1f}s{error_info}")

    # DB aggregate status
    if db_status:
        print("\n[DB] Stats table status (recent rows):")
        for table, counts in db_status.items():
            if counts:
                status_str = ", ".join(f"{s}={n}" for s, n in sorted(counts.items()))
                print(f"  - {table}: {status_str}")
            else:
                print(f"  - {table}: (no recent rows)")

    print(f"\n{'=' * 70}")
    print(f"Overall status: {overall_status}")
    print(f"{'=' * 70}")


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Master orchestrator for all stats runner scripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all stats runners
  python -m ta_lab2.scripts.stats.run_all_stats_runners

  # Full refresh (ignore incremental watermarks)
  python -m ta_lab2.scripts.stats.run_all_stats_runners --full-refresh

  # Dry run (list runners, no execution)
  python -m ta_lab2.scripts.stats.run_all_stats_runners --dry-run

  # Verbose output
  python -m ta_lab2.scripts.stats.run_all_stats_runners --verbose
        """,
    )

    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env)",
    )
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Ignore incremental watermarks; recompute all stats",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would execute without running",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Stream subprocess output directly to stdout",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Resolve database URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    print(f"\n{'=' * 70}")
    print("STATS RUNNER ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nTotal runners: {len(ALL_STATS_SCRIPTS)}")
    for script in ALL_STATS_SCRIPTS:
        print(f"  - {script.name}: {script.description}")
    print(f"\nFull refresh: {args.full_refresh}")
    print(f"Dry run: {args.dry_run}")

    overall_status, results, db_status = run_all_stats(
        db_url=db_url,
        verbose=args.verbose,
        dry_run=args.dry_run,
        full_refresh=args.full_refresh,
    )

    if args.dry_run:
        print(f"\n[DRY RUN] Would have executed {len(results)} stats runner(s)")
        return 0

    print_summary(results, overall_status, db_status)

    # Exit 0 for PASS/WARN (pipeline continues), 1 for FAIL (pipeline gated)
    if overall_status == "FAIL":
        print(
            "\n[FAIL] Stats reported FAIL status -- "
            "data quality check failed. Review stats tables."
        )
        return 1
    elif overall_status == "WARN":
        print(
            "\n[WARN] Stats reported WARN status -- anomalies detected, review recommended."
        )
        return 0
    else:
        print("\n[PASS] All stats checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
