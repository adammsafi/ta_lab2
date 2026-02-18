#!/usr/bin/env python
"""
Unified daily refresh orchestration script.

Coordinates bars and EMAs with state-based checking and clear visibility.

Usage:
    # Full daily refresh (bars then EMAs)
    python run_daily_refresh.py --all --ids 1,52,825

    # Bars only
    python run_daily_refresh.py --bars --ids all

    # EMAs only (with bar freshness check)
    python run_daily_refresh.py --emas --ids all

    # Use 8 parallel processes for bar builders
    python run_daily_refresh.py --all --ids all -n 8

    # Dry run
    python run_daily_refresh.py --all --ids 1 --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ta_lab2.scripts.refresh_utils import (
    get_fresh_ids,
    parse_ids,
    resolve_db_url,
)


@dataclass
class ComponentResult:
    """Result of running a component (bars or EMAs)."""

    component: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


def run_bar_builders(
    args, db_url: str, parsed_ids: list[int] | None
) -> ComponentResult:
    """
    Run bar orchestrator via subprocess.

    Args:
        args: CLI arguments
        db_url: Database URL
        parsed_ids: Parsed ID list or None for "all"

    Returns:
        ComponentResult with execution details
    """
    script_dir = Path(__file__).parent / "bars"
    cmd = [sys.executable, str(script_dir / "run_all_bar_builders.py")]

    # Add arguments
    cmd.extend(["--ids", args.ids])
    cmd.extend(["--db-url", db_url])

    if args.verbose:
        cmd.append("--verbose")
    if args.continue_on_error:
        cmd.append("--continue-on-error")
    if args.num_processes:
        cmd.extend(["--num-processes", str(args.num_processes)])

    print(f"\n{'=' * 70}")
    print("RUNNING BAR BUILDERS")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute bar builders")
        return ComponentResult(
            component="bars",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False)
        else:
            # Capture output
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)

            # Show output on error
            if result.returncode != 0:
                print(f"\n[ERROR] Bar builders failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Bar builders completed successfully in {duration:.1f}s")
            return ComponentResult(
                component="bars",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Bar builders failed: {error_msg}")
            return ComponentResult(
                component="bars",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Bar builders raised exception: {error_msg}")
        return ComponentResult(
            component="bars",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_ema_refreshers(
    args, db_url: str, ids_for_emas: list[int] | None
) -> ComponentResult:
    """
    Run EMA orchestrator via subprocess.

    Args:
        args: CLI arguments
        db_url: Database URL
        ids_for_emas: Filtered ID list (fresh bars only) or None for "all"

    Returns:
        ComponentResult with execution details
    """
    script_dir = Path(__file__).parent / "emas"
    cmd = [sys.executable, str(script_dir / "run_all_ema_refreshes.py")]

    # Format IDs for EMA subprocess
    if ids_for_emas is None:
        ids_str = "all"
    elif len(ids_for_emas) == 0:
        print("[INFO] No IDs with fresh bars - skipping EMA refresh")
        return ComponentResult(
            component="emas",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )
    else:
        ids_str = ",".join(str(i) for i in ids_for_emas)

    cmd.extend(["--ids", ids_str])

    if args.verbose:
        cmd.append("--verbose")
    if args.num_processes:
        cmd.extend(["--num-processes", str(args.num_processes)])

    print(f"\n{'=' * 70}")
    print("RUNNING EMA REFRESHERS")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute EMA refreshers")
        return ComponentResult(
            component="emas",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False)
        else:
            # Capture output
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)

            # Show output on error
            if result.returncode != 0:
                print(f"\n[ERROR] EMA refreshers failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] EMA refreshers completed successfully in {duration:.1f}s")
            return ComponentResult(
                component="emas",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] EMA refreshers failed: {error_msg}")
            return ComponentResult(
                component="emas",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] EMA refreshers raised exception: {error_msg}")
        return ComponentResult(
            component="emas",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def print_combined_summary(results: list[tuple[str, ComponentResult]]) -> bool:
    """
    Print combined execution summary.

    Args:
        results: List of (component_name, result) tuples

    Returns:
        True if all components succeeded, False otherwise
    """
    print(f"\n{'=' * 70}")
    print("DAILY REFRESH SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for _, r in results)
    successful = [r for _, r in results if r.success]
    failed = [r for _, r in results if not r.success]

    print(f"\nTotal components: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if successful:
        print("\n[OK] Successful components:")
        for name, r in results:
            if r.success:
                print(f"  - {name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed components:")
        for name, r in results:
            if not r.success:
                error_info = f" ({r.error_message})" if r.error_message else ""
                print(f"  - {name}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'=' * 70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} component(s) failed!")
        return False
    else:
        print("\n[OK] All components completed successfully!")
        return True


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Unified daily refresh orchestration for bars and EMAs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full daily refresh (bars then EMAs)
  python run_daily_refresh.py --all --ids 1,52,825

  # Bars only
  python run_daily_refresh.py --bars --ids all

  # EMAs only (automatically checks bar freshness)
  python run_daily_refresh.py --emas --ids all

  # Dry run to see what would execute
  python run_daily_refresh.py --all --ids 1 --dry-run

  # Continue on errors
  python run_daily_refresh.py --all --ids all --continue-on-error

  # Use 8 parallel processes for bar builders
  python run_daily_refresh.py --all --ids all -n 8

  # Skip bar freshness check for EMAs
  python run_daily_refresh.py --emas --ids all --skip-stale-check
        """,
    )

    # Target selection (required)
    p.add_argument(
        "--bars",
        action="store_true",
        help="Run bar builders only",
    )
    p.add_argument(
        "--emas",
        action="store_true",
        help="Run EMA refreshers only",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Run bars then EMAs (full refresh)",
    )

    # Common arguments
    p.add_argument(
        "--ids",
        default="all",
        help='Comma-separated IDs or "all" (default: all)',
    )
    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env)",
    )

    # Execution options
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would execute without running",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output from subprocesses",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running remaining components if one fails",
    )
    p.add_argument(
        "-n",
        "--num-processes",
        type=int,
        help="Number of parallel processes for bar builders (default: 6)",
    )

    # EMA-specific options
    p.add_argument(
        "--skip-stale-check",
        action="store_true",
        help="Skip bar freshness check before running EMAs",
    )
    p.add_argument(
        "--staleness-hours",
        type=float,
        default=48.0,
        help="Max hours for bar freshness (default: 48.0)",
    )

    args = p.parse_args(argv)

    # Validation: require explicit target
    if not (args.bars or args.emas or args.all):
        p.error("Must specify --bars, --emas, or --all")

    # Resolve database URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    # Parse IDs
    try:
        parsed_ids = parse_ids(args.ids, db_url)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    # Determine what to run
    run_bars = args.bars or args.all
    run_emas = args.emas or args.all

    print(f"\n{'=' * 70}")
    print("DAILY REFRESH ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(
        f"\nComponents: {('bars' if run_bars else '') + (' + ' if run_bars and run_emas else '') + ('EMAs' if run_emas else '')}"
    )
    print(f"IDs: {args.ids}")
    print(f"Continue on error: {args.continue_on_error}")
    if run_emas and not args.skip_stale_check:
        print(f"Bar staleness threshold: {args.staleness_hours} hours")

    results: list[tuple[str, ComponentResult]] = []

    # Run bars if requested
    if run_bars:
        bar_result = run_bar_builders(args, db_url, parsed_ids)
        results.append(("bars", bar_result))

        if not bar_result.success and not args.continue_on_error:
            print("\n[STOPPED] Bar builders failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run EMAs if requested
    if run_emas:
        # Check bar freshness first (unless --skip-stale-check)
        ids_for_emas = parsed_ids

        # Skip stale check when bars were just refreshed (--all mode)
        skip_stale = args.skip_stale_check or run_bars

        if not skip_stale:
            print(f"\n{'=' * 70}")
            print("CHECKING BAR FRESHNESS")
            print(f"{'=' * 70}")

            fresh_ids, stale_ids = get_fresh_ids(
                db_url, parsed_ids, args.staleness_hours
            )

            if stale_ids:
                print(f"\n[WARNING] {len(stale_ids)} ID(s) have stale bars:")
                print(f"  Stale IDs: {stale_ids}")

                print("\n[INFO] Consider running with --all to refresh bars first")

                # Filter to fresh IDs only
                ids_for_emas = fresh_ids
                print(
                    f"\n[INFO] Running EMAs for {len(fresh_ids)} ID(s) with fresh bars"
                )
            else:
                print(
                    f"\n[OK] All {len(fresh_ids) if fresh_ids else 'requested'} ID(s) have fresh bars"
                )
        elif run_bars:
            print("\n[INFO] Skipping bar freshness check (bars just refreshed)")

        ema_result = run_ema_refreshers(args, db_url, ids_for_emas)
        results.append(("emas", ema_result))

    # Print combined summary
    if not args.dry_run:
        all_success = print_combined_summary(results)
        return 0 if all_success else 1
    else:
        print(f"\n[DRY RUN] Would have executed {len(results)} component(s)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
