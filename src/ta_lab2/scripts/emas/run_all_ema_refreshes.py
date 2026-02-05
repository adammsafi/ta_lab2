#!/usr/bin/env python
"""
Master orchestrator for all EMA refresh scripts.

Runs all EMA refreshers in logical order with unified CLI and error reporting.

Usage:
    # Run all refreshers
    python run_all_ema_refreshes.py --ids 1,52,825

    # Run only specific refreshers
    python run_all_ema_refreshes.py --ids all --only multi_tf,cal

    # Dry run to see what would execute
    python run_all_ema_refreshes.py --ids all --dry-run

    # Continue on errors
    python run_all_ema_refreshes.py --ids all --continue-on-error
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ta_lab2.scripts.emas.logging_config import setup_logging, add_logging_args


@dataclass
class RefresherConfig:
    """Configuration for an EMA refresher."""

    name: str
    script_path: str
    description: str
    supports_scheme: bool = False  # For cal/cal_anchor with us/iso/both
    custom_args: dict[str, str] | None = None


# All available refreshers in logical execution order
ALL_REFRESHERS = [
    RefresherConfig(
        name="multi_tf",
        script_path="refresh_cmc_ema_multi_tf_from_bars.py",
        description="Multi-TF EMAs (tf_day based)",
        supports_scheme=False,
    ),
    RefresherConfig(
        name="cal",
        script_path="refresh_cmc_ema_multi_tf_cal_from_bars.py",
        description="Calendar-aligned EMAs (us/iso)",
        supports_scheme=True,
    ),
    RefresherConfig(
        name="cal_anchor",
        script_path="refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py",
        description="Calendar-anchored EMAs",
        supports_scheme=True,
    ),
    RefresherConfig(
        name="v2",
        script_path="refresh_cmc_ema_multi_tf_v2.py",
        description="Daily-space EMAs (v2)",
        supports_scheme=False,
    ),
]

REFRESHER_NAME_MAP = {r.name: r for r in ALL_REFRESHERS}


@dataclass
class RefresherResult:
    """Result of running a refresher."""

    name: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


def parse_refresher_list(refresher_arg: str) -> list[str]:
    """Parse comma-separated refresher names."""
    if not refresher_arg:
        return []
    return [name.strip() for name in refresher_arg.split(",") if name.strip()]


def get_refreshers_to_run(
    *,
    include: list[str] | None = None,
) -> list[RefresherConfig]:
    """
    Determine which refreshers to run based on include filter.

    Args:
        include: If specified, only run these refreshers

    Returns:
        List of RefresherConfig objects to execute
    """
    if include:
        # Validate refresher names
        invalid = [name for name in include if name not in REFRESHER_NAME_MAP]
        if invalid:
            raise ValueError(
                f"Invalid refresher names: {', '.join(invalid)}. "
                f"Valid options: {', '.join(REFRESHER_NAME_MAP.keys())}"
            )
        refreshers = [REFRESHER_NAME_MAP[name] for name in include]
    else:
        refreshers = ALL_REFRESHERS.copy()

    return refreshers


def build_command(
    refresher: RefresherConfig,
    *,
    ids: str,
    start: str,
    end: str | None,
    periods: str,
    cal_scheme: str | None,
    anchor_scheme: str | None,
    no_update: bool,
    full_refresh: bool,
    v2_alignment_type: str,
    v2_include_noncanonical: bool,
    price_schema: str,
    price_table: str,
    out_schema: str,
    v2_out_table: str,
    quiet: bool,
) -> list[str]:
    """
    Build subprocess command for a refresher.

    Args:
        refresher: Refresher configuration
        ids: Comma-separated ID list or "all"
        start: Start date
        end: End date (optional)
        periods: Period specification (comma-separated or "lut")
        cal_scheme: Scheme for calendar-aligned EMAs (us/iso/both)
        anchor_scheme: Scheme for calendar-anchored EMAs (us/iso/both)
        no_update: Whether to skip update
        full_refresh: Whether to do full refresh
        v2_alignment_type: Alignment type for v2
        v2_include_noncanonical: Include noncanonical for v2
        price_schema: Price schema for v2
        price_table: Price table for v2
        out_schema: Output schema for v2
        v2_out_table: Output table for v2
        quiet: Quiet mode

    Returns:
        Command as list of strings
    """
    script_dir = Path(__file__).parent
    script_path = script_dir / refresher.script_path

    cmd = [sys.executable, str(script_path)]

    # Build command based on refresher type
    if refresher.name == "multi_tf":
        # refresh_cmc_ema_multi_tf_from_bars.py
        cmd.extend(["--ids", ids])
        cmd.extend(["--start", start])
        if end:
            cmd.extend(["--end", end])
        cmd.extend(["--periods", periods])
        if no_update:
            cmd.append("--no-update")

    elif refresher.name == "cal":
        # refresh_cmc_ema_multi_tf_cal_from_bars.py
        cmd.extend(["--ids", ids])
        scheme = cal_scheme or "both"
        cmd.extend(["--scheme", scheme])
        if start:
            cmd.extend(["--start", start])
        if end:
            cmd.extend(["--end", end])
        cmd.extend(["--periods", periods])
        if full_refresh:
            cmd.append("--full-refresh")

    elif refresher.name == "cal_anchor":
        # refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py
        cmd.extend(["--ids", ids])
        scheme = anchor_scheme or "both"
        cmd.extend(["--scheme", scheme])
        cmd.extend(["--start", start])
        if end:
            cmd.extend(["--end", end])
        cmd.extend(["--periods", periods])
        if no_update:
            cmd.append("--no-update")
        if quiet:
            cmd.append("--quiet")

    elif refresher.name == "v2":
        # refresh_cmc_ema_multi_tf_v2.py
        cmd.extend(["--ids", ids])
        cmd.extend(["--periods", periods])
        cmd.extend(["--alignment-type", v2_alignment_type])
        if v2_include_noncanonical:
            cmd.append("--include-noncanonical")
        cmd.extend(["--price-schema", price_schema])
        cmd.extend(["--price-table", price_table])
        cmd.extend(["--out-schema", out_schema])
        cmd.extend(["--out-table", v2_out_table])

    return cmd


def run_refresher(
    refresher: RefresherConfig,
    cmd: list[str],
    *,
    verbose: bool,
) -> RefresherResult:
    """
    Execute a refresher subprocess.

    Args:
        refresher: Refresher configuration
        cmd: Command to execute
        verbose: Whether to show refresher output

    Returns:
        RefresherResult with execution details
    """
    print(f"\n{'='*70}")
    print(f"Running: {refresher.name} - {refresher.description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*70}")

    start = time.perf_counter()

    try:
        if verbose:
            # Stream output to console
            result = subprocess.run(cmd, check=False)
            returncode = result.returncode
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
            returncode = result.returncode

            # Show output only on error
            if returncode != 0:
                print(f"\n[ERROR] Refresher failed with code {returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if returncode == 0:
            print(f"\n[OK] {refresher.name} completed successfully in {duration:.1f}s")
            return RefresherResult(
                name=refresher.name,
                success=True,
                duration_sec=duration,
                returncode=returncode,
            )
        else:
            error_msg = f"Exited with code {returncode}"
            print(f"\n[FAILED] {refresher.name} failed: {error_msg}")
            return RefresherResult(
                name=refresher.name,
                success=False,
                duration_sec=duration,
                returncode=returncode,
                error_message=error_msg,
            )

    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] {refresher.name} raised exception: {error_msg}")
        return RefresherResult(
            name=refresher.name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def print_summary(results: list[RefresherResult]) -> bool:
    """Print execution summary."""
    print(f"\n{'='*70}")
    print("EXECUTION SUMMARY")
    print(f"{'='*70}")

    total_duration = sum(r.duration_sec for r in results)
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nTotal refreshers: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if successful:
        print("\n[OK] Successful refreshers:")
        for r in successful:
            print(f"  - {r.name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed refreshers:")
        for r in failed:
            error_info = f" ({r.error_message})" if r.error_message else ""
            print(f"  - {r.name}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'='*70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} refresher(s) failed!")
        return False
    else:
        print("\n[OK] All refreshers completed successfully!")
        return True


def run_validation(args) -> bool:
    """Run rowcount validation on unified EMA table."""
    from ta_lab2.scripts.emas.validate_ema_rowcounts import (
        validate_rowcounts,
        summarize_validation,
    )
    from ta_lab2.notifications.telegram import send_validation_alert, is_configured
    from ta_lab2.config import TARGET_DB_URL
    from sqlalchemy import create_engine

    print("\nRunning post-refresh rowcount validation...")

    if not TARGET_DB_URL:
        print("[ERROR] TARGET_DB_URL not set - cannot run validation")
        return False

    db_url = TARGET_DB_URL
    engine = create_engine(db_url)

    # Use same date range as refresh
    start = args.start
    end = args.end or datetime.now().strftime("%Y-%m-%d")

    # Parse periods for validation
    if args.periods == "lut":
        # For LUT, use common periods for validation
        periods = [9, 10, 20, 50]
    else:
        periods = [int(x.strip()) for x in args.periods.split(",")]

    # Validate unified table
    try:
        df = validate_rowcounts(
            engine=engine,
            table="cmc_ema_multi_tf_u",
            schema="public",
            ids=None,  # all
            tfs=None,  # all canonical
            periods=periods,
            start_date=start,
            end_date=end,
            db_url=db_url,
        )
    except Exception as e:
        print(f"[ERROR] Validation failed: {e}")
        return False

    summary = summarize_validation(df)

    if summary["gaps"] > 0 or summary["duplicates"] > 0:
        print(
            f"[WARNING] Validation found issues: {summary['gaps']} gaps, {summary['duplicates']} duplicates"
        )

        if args.alert_on_validation_error and is_configured():
            send_validation_alert(summary)
            print("[INFO] Telegram alert sent")
        elif args.alert_on_validation_error:
            print("[WARNING] Telegram not configured - skipping alert")

        return False

    print(f"[OK] Validation passed: {summary['ok']}/{summary['total']} checks OK")
    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run all EMA refreshers with unified configuration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all refreshers for specific IDs
  python run_all_ema_refreshes.py --ids 1,52,825

  # Run all refreshers with periods from LUT
  python run_all_ema_refreshes.py --ids all --periods lut

  # Run only multi_tf and cal refreshers
  python run_all_ema_refreshes.py --ids all --only multi_tf,cal

  # Continue on errors (don't stop if a refresher fails)
  python run_all_ema_refreshes.py --ids all --continue-on-error

  # Dry run (show commands without executing)
  python run_all_ema_refreshes.py --ids all --dry-run

Available refreshers:
  multi_tf    - Multi-TF EMAs (tf_day based)
  cal         - Calendar-aligned EMAs (us/iso)
  cal_anchor  - Calendar-anchored EMAs
  v2          - Daily-space EMAs (v2)

CONNECTION NOTES: The multi_tf script uses parallel workers (default: 4).
If you see "too many clients already" errors:
  1. Close other database clients (PgAdmin, DBeaver, etc.)
  2. Check active connections: SELECT count(*) FROM pg_stat_activity;
  3. Increase Postgres max_connections if needed
        """,
    )

    p.add_argument(
        "--ids",
        default="all",
        help='Comma-separated ID list or "all"',
    )
    p.add_argument(
        "--start",
        default="2010-01-01",
        help="Start date for refreshers that accept it",
    )
    p.add_argument("--end", default="", help="End date (optional)")
    p.add_argument(
        "--periods",
        default="lut",
        help="Comma list like 10,21,50 or 'lut' (recommended) to load from public.ema_alpha_lookup",
    )

    p.add_argument("--cal-scheme", default="both", choices=["us", "iso", "both"])
    p.add_argument("--anchor-scheme", default="both", choices=["us", "iso", "both"])

    p.add_argument(
        "--no-update",
        action="store_true",
        help="Passes through to scripts that support it",
    )
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="For CAL runner: ignore state and run full/args.start",
    )

    # v2-specific knobs
    p.add_argument("--v2-alignment-type", default="tf_day")
    p.add_argument("--v2-include-noncanonical", action="store_true")
    p.add_argument("--price-schema", default="public")
    p.add_argument(
        "--price-table",
        default="cmc_price_bars_1d",
        help="V2 price table (default: cmc_price_bars_1d - validated bars)",
    )
    p.add_argument("--out-schema", default="public")
    p.add_argument("--v2-out-table", default="cmc_ema_multi_tf_v2")

    p.add_argument(
        "--only",
        default="",
        help="Comma-separated list of refreshers to run (default: all)",
    )

    # Validation options
    p.add_argument(
        "--validate",
        action="store_true",
        help="Run rowcount validation after refresh completes",
    )
    p.add_argument(
        "--alert-on-validation-error",
        action="store_true",
        help="Send Telegram alert if validation finds issues (requires --validate)",
    )

    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running other refreshers if one fails",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show refresher output (default: only show on error)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )

    add_logging_args(p)

    args = p.parse_args()
    args.end = args.end.strip() or None
    return args


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging (for validation step which still uses logger)
    _logger = setup_logging(
        name="ema_runner",
        level=args.log_level,
        log_file=args.log_file,
        quiet=args.quiet,
        debug=args.debug,
    )

    # Determine which refreshers to run
    try:
        include = parse_refresher_list(args.only) if args.only else None
        refreshers = get_refreshers_to_run(include=include)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    if not refreshers:
        print("[ERROR] No refreshers selected!")
        return 1

    print(f"\n{'='*70}")
    print("EMA REFRESHERS ORCHESTRATOR")
    print(f"{'='*70}")
    print(f"\nRefreshers to run: {', '.join(r.name for r in refreshers)}")
    print(f"IDs: {args.ids}")
    print(f"Start: {args.start}")
    if args.end:
        print(f"End: {args.end}")
    print(f"Periods: {args.periods}")
    print(f"Cal scheme: {args.cal_scheme}")
    print(f"Anchor scheme: {args.anchor_scheme}")
    print(f"Continue on error: {args.continue_on_error}")

    # Execute refreshers
    results: list[RefresherResult] = []

    for refresher in refreshers:
        cmd = build_command(
            refresher,
            ids=args.ids,
            start=args.start,
            end=args.end,
            periods=args.periods,
            cal_scheme=args.cal_scheme,
            anchor_scheme=args.anchor_scheme,
            no_update=args.no_update,
            full_refresh=args.full_refresh,
            v2_alignment_type=args.v2_alignment_type,
            v2_include_noncanonical=args.v2_include_noncanonical,
            price_schema=args.price_schema,
            price_table=args.price_table,
            out_schema=args.out_schema,
            v2_out_table=args.v2_out_table,
            quiet=args.quiet,
        )

        if args.dry_run:
            print(f"\n[DRY RUN] {refresher.name}:")
            print(f"  {' '.join(cmd)}")
            continue

        result = run_refresher(refresher, cmd, verbose=args.verbose)
        results.append(result)

        # Stop on error if not continuing
        if not result.success and not args.continue_on_error:
            print(f"\n[STOPPED] Refresher {refresher.name} failed, stopping execution")
            print("(Use --continue-on-error to run remaining refreshers)")
            break

    if args.dry_run:
        print(f"\n[DRY RUN] Would have executed {len(refreshers)} refresher(s)")
        return 0

    # Print summary
    all_success = print_summary(results)

    # Run validation if requested
    if args.validate and all_success:
        validation_passed = run_validation(args)
        if not validation_passed:
            print("[WARNING] Validation found issues - check output for details")
            # Don't fail the overall run, just warn

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
