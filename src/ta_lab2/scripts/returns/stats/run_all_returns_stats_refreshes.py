#!/usr/bin/env python
"""
Master orchestrator for returns EMA stats refresh.

Runs refresh_returns_ema_stats.py for each requested family group.

Usage:
    # Run all families
    python run_all_returns_stats_refreshes.py

    # Run specific families
    python run_all_returns_stats_refreshes.py --families multi_tf,cal_us

    # Dry run
    python run_all_returns_stats_refreshes.py --dry-run

    # Full refresh
    python run_all_returns_stats_refreshes.py --full-refresh
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ALL_FAMILY_LABELS = [
    "multi_tf",
    "cal_us",
    "cal_iso",
    "cal_anchor_us",
    "cal_anchor_iso",
    "u",
]

STATS_SCRIPT = "refresh_returns_ema_stats.py"


@dataclass
class ComponentResult:
    """Result of running a stats script invocation."""

    families: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


def run_stats_script(
    families: str,
    db_url: str | None,
    full_refresh: bool,
    verbose: bool,
    dry_run: bool,
) -> ComponentResult:
    """
    Run refresh_returns_ema_stats.py via subprocess.

    Args:
        families: Comma-separated family labels (e.g. "multi_tf,cal_us") or "all"
        db_url: Database URL (optional)
        full_refresh: Whether to pass --full-refresh
        verbose: Show detailed output
        dry_run: Show what would execute without running

    Returns:
        ComponentResult with execution details
    """
    script_dir = Path(__file__).parent
    script_path = script_dir / STATS_SCRIPT

    if not script_path.exists():
        return ComponentResult(
            families=families,
            success=False,
            duration_sec=0.0,
            returncode=-1,
            error_message=f"Script not found: {script_path}",
        )

    cmd = [sys.executable, str(script_path)]
    cmd.extend(["--families", families])

    if db_url:
        cmd.extend(["--db-url", db_url])

    if full_refresh:
        cmd.append("--full-refresh")

    print(f"\n{'=' * 70}")
    print(f"RUNNING: Returns EMA stats for families={families}")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if dry_run:
        print("[DRY RUN] Would execute stats refresh")
        return ComponentResult(
            families=families,
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if verbose:
            result = subprocess.run(cmd, check=False)
        else:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"\n[ERROR] Stats refresh failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Returns stats ({families}) completed in {duration:.1f}s")
            return ComponentResult(
                families=families,
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Returns stats ({families}) failed: {error_msg}")
            return ComponentResult(
                families=families,
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Returns stats ({families}) raised exception: {error_msg}")
        return ComponentResult(
            families=families,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def print_summary(results: list[ComponentResult]) -> bool:
    """Print execution summary. Returns True if all succeeded."""
    print(f"\n{'=' * 70}")
    print("RETURNS STATS REFRESH SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for r in results)
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nTotal invocations: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if successful:
        print("\n[OK] Successful:")
        for r in successful:
            print(f"  - {r.families}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed:")
        for r in failed:
            error_info = f" ({r.error_message})" if r.error_message else ""
            print(f"  - {r.families}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'=' * 70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} invocation(s) failed!")
        return False
    else:
        print("\n[OK] All returns stats refreshes completed successfully!")
        return True


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Master orchestrator for returns EMA stats refresh.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Run all families in one shot
  python run_all_returns_stats_refreshes.py

  # Run specific families
  python run_all_returns_stats_refreshes.py --families multi_tf,cal_us

  # Dry run
  python run_all_returns_stats_refreshes.py --dry-run

Available families: {', '.join(ALL_FAMILY_LABELS)}
        """,
    )

    p.add_argument(
        "--families",
        default="all",
        help=(
            'Comma-separated family labels or "all" (default: all). '
            f"Available: {', '.join(ALL_FAMILY_LABELS)}"
        ),
    )
    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env)",
    )
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Pass --full-refresh to the stats script",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would execute without running",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output from subprocess",
    )

    args = p.parse_args(argv)

    families_str: str = args.families.strip()
    if families_str.lower() == "all":
        families_to_run = "all"
    else:
        requested = [f.strip() for f in families_str.split(",") if f.strip()]
        unknown = set(requested) - set(ALL_FAMILY_LABELS)
        if unknown:
            print(f"[WARNING] Unknown families: {unknown}")
            print(f"Available: {', '.join(ALL_FAMILY_LABELS)}")
        families_to_run = ",".join(f for f in requested if f in set(ALL_FAMILY_LABELS))
        if not families_to_run:
            print("[ERROR] No valid families specified")
            return 1

    print(f"\n{'=' * 70}")
    print("RETURNS STATS REFRESH ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nFamilies: {families_to_run}")
    print(f"Full refresh: {args.full_refresh}")

    # Run as a single invocation (the stats script handles all families)
    result = run_stats_script(
        families=families_to_run,
        db_url=args.db_url,
        full_refresh=args.full_refresh,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )

    results = [result]

    if not args.dry_run:
        all_success = print_summary(results)
        return 0 if all_success else 1
    else:
        print(f"\n[DRY RUN] Would have executed stats refresh for: {families_to_run}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
