#!/usr/bin/env python
"""
Master orchestrator for all EMA stats refresh scripts.

Runs all stats computation scripts in the correct order:
1. Daily stats (ema_daily_stats)
2. Multi-TF stats (ema_multi_tf_stats)
3. Calendar stats (ema_multi_tf_cal_stats)
4. Calendar anchor stats (ema_multi_tf_cal_anchor_stats)

Usage:
    # Run all stats refreshers
    python run_all_stats_refreshes.py --ids all

    # Run specific stats types
    python run_all_stats_refreshes.py --ids 1,52 --types daily,multi_tf

    # Dry run
    python run_all_stats_refreshes.py --ids all --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StatsScript:
    """Configuration for a stats refresh script."""

    name: str
    script_path: str
    description: str
    subdirectory: str


# All stats scripts in execution order
ALL_STATS_SCRIPTS = [
    StatsScript(
        name="daily",
        script_path="daily/refresh_ema_daily_stats.py",
        description="Daily EMA stats",
        subdirectory="daily",
    ),
    StatsScript(
        name="multi_tf",
        script_path="multi_tf/refresh_ema_multi_tf_stats.py",
        description="Multi-TF rolling EMA stats",
        subdirectory="multi_tf",
    ),
    StatsScript(
        name="cal",
        script_path="multi_tf_cal/refresh_ema_multi_tf_cal_stats.py",
        description="Calendar-aligned EMA stats",
        subdirectory="multi_tf_cal",
    ),
    StatsScript(
        name="cal_anchor",
        script_path="multi_tf_cal_anchor/refresh_ema_multi_tf_cal_anchor_stats.py",
        description="Calendar-anchored EMA stats",
        subdirectory="multi_tf_cal_anchor",
    ),
]


@dataclass
class ComponentResult:
    """Result of running a stats script."""

    name: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


def run_stats_script(
    script: StatsScript,
    ids: str,
    db_url: str | None,
    verbose: bool,
    dry_run: bool,
) -> ComponentResult:
    """
    Run a stats refresh script via subprocess.

    Args:
        script: Stats script configuration
        ids: Comma-separated IDs or "all"
        db_url: Database URL (optional)
        verbose: Show detailed output
        dry_run: Show what would execute without running

    Returns:
        ComponentResult with execution details
    """
    script_dir = Path(__file__).parent
    script_path = script_dir / script.script_path

    if not script_path.exists():
        return ComponentResult(
            name=script.name,
            success=False,
            duration_sec=0.0,
            returncode=-1,
            error_message=f"Script not found: {script_path}",
        )

    cmd = [sys.executable, str(script_path)]
    cmd.extend(["--ids", ids])

    if db_url:
        cmd.extend(["--db-url", db_url])

    print(f"\n{'=' * 70}")
    print(f"RUNNING: {script.description} ({script.name})")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if dry_run:
        print("[DRY RUN] Would execute stats refresh")
        return ComponentResult(
            name=script.name,
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if verbose:
            # Stream output
            result = subprocess.run(cmd, check=False)
        else:
            # Capture output
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)

            # Show output on error
            if result.returncode != 0:
                print(f"\n[ERROR] Stats refresh failed with code {result.returncode}")
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


def print_summary(results: list[ComponentResult]) -> bool:
    """
    Print execution summary.

    Args:
        results: List of ComponentResults

    Returns:
        True if all components succeeded, False otherwise
    """
    print(f"\n{'=' * 70}")
    print("STATS REFRESH SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for r in results)
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nTotal scripts: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if successful:
        print("\n[OK] Successful stats refreshes:")
        for r in successful:
            print(f"  - {r.name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed stats refreshes:")
        for r in failed:
            error_info = f" ({r.error_message})" if r.error_message else ""
            print(f"  - {r.name}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'=' * 70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} stats refresh(es) failed!")
        return False
    else:
        print("\n[OK] All stats refreshes completed successfully!")
        return True


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Master orchestrator for all EMA stats refresh scripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all stats refreshers
  python run_all_stats_refreshes.py --ids all

  # Run specific stats types
  python run_all_stats_refreshes.py --ids 1,52 --types daily,multi_tf

  # Dry run
  python run_all_stats_refreshes.py --ids all --dry-run

  # Continue on errors
  python run_all_stats_refreshes.py --ids all --continue-on-error
        """,
    )

    p.add_argument(
        "--ids",
        default="all",
        help='Comma-separated IDs or "all" (default: all)',
    )
    p.add_argument(
        "--types",
        help='Comma-separated types to run (e.g., "daily,multi_tf"), or omit for all',
    )
    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env)",
    )
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
        help="Continue running remaining scripts if one fails",
    )

    args = p.parse_args(argv)

    # Filter scripts by type if specified
    if args.types:
        requested_types = set(args.types.split(","))
        scripts_to_run = [s for s in ALL_STATS_SCRIPTS if s.name in requested_types]

        unknown_types = requested_types - {s.name for s in scripts_to_run}
        if unknown_types:
            print(f"[WARNING] Unknown types: {unknown_types}")
            print(f"Available types: {', '.join(s.name for s in ALL_STATS_SCRIPTS)}")

        if not scripts_to_run:
            print("[ERROR] No valid stats types specified")
            return 1
    else:
        scripts_to_run = ALL_STATS_SCRIPTS

    print(f"\n{'=' * 70}")
    print("STATS REFRESH ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nScripts to run: {len(scripts_to_run)}")
    for script in scripts_to_run:
        print(f"  - {script.name}: {script.description}")
    print(f"\nIDs: {args.ids}")
    print(f"Continue on error: {args.continue_on_error}")

    results: list[ComponentResult] = []

    # Run each script
    for script in scripts_to_run:
        result = run_stats_script(
            script=script,
            ids=args.ids,
            db_url=args.db_url,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
        results.append(result)

        if not result.success and not args.continue_on_error:
            print(f"\n[STOPPED] {script.name} failed, stopping execution")
            print("(Use --continue-on-error to run remaining scripts)")
            break

    # Print summary
    if not args.dry_run:
        all_success = print_summary(results)
        return 0 if all_success else 1
    else:
        print(f"\n[DRY RUN] Would have executed {len(results)} script(s)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
