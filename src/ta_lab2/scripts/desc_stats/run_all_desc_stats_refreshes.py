#!/usr/bin/env python
"""
Orchestrator for all descriptive stats refresh scripts.

Runs the complete descriptive stats pipeline in logical order with unified CLI
and error reporting:

  1. Asset stats    -- per-asset descriptive statistics (cmc_asset_stats)
  2. Correlation    -- pairwise rolling correlations (cmc_cross_asset_corr)

Usage:
    # Run all stages for all assets, all TFs
    python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all

    # Single asset, single TF
    python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids 1 --tf 1D

    # Dry run to see what would execute
    python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all --dry-run

    # Continue on errors (still run correlation if asset stats fails)
    python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all --continue-on-error

    # Full rebuild
    python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all --full-rebuild

Pipeline stages (in order):
  asset_stats   -- Per-asset descriptive statistics
  correlation   -- Pairwise rolling correlations across assets
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass

# Timeout tiers (seconds)
TIMEOUT_DESC_STATS = 1800  # 30 minutes per subscript


# =============================================================================
# Data structures
# =============================================================================


@dataclass
class StepResult:
    """Result of running a desc stats step."""

    name: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


# =============================================================================
# Command builders
# =============================================================================


def build_asset_stats_command(
    *,
    ids: str,
    tf: str | None,
    windows: str | None,
    full_rebuild: bool,
    dry_run: bool,
    continue_on_error: bool,
    workers: int | None,
    db_url: str | None,
    verbose: bool,
) -> list[str]:
    """Build subprocess command for asset stats refresher."""
    cmd = [sys.executable, "-m", "ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats"]

    cmd.extend(["--ids", ids])

    if tf:
        cmd.extend(["--tf", tf])
    if windows:
        cmd.extend(["--windows", windows])
    if full_rebuild:
        cmd.append("--full-rebuild")
    if dry_run:
        cmd.append("--dry-run")
    if continue_on_error:
        cmd.append("--continue-on-error")
    if workers is not None:
        cmd.extend(["--workers", str(workers)])
    if db_url:
        cmd.extend(["--db-url", db_url])
    if verbose:
        cmd.append("--verbose")

    return cmd


def build_correlation_command(
    *,
    ids: str,
    tf: str | None,
    windows: str | None,
    full_rebuild: bool,
    dry_run: bool,
    continue_on_error: bool,
    workers: int | None,
    db_url: str | None,
    verbose: bool,
) -> list[str]:
    """Build subprocess command for cross-asset correlation refresher."""
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.desc_stats.refresh_cmc_cross_asset_corr",
    ]

    cmd.extend(["--ids", ids])

    if tf:
        cmd.extend(["--tf", tf])
    if windows:
        cmd.extend(["--windows", windows])
    if full_rebuild:
        cmd.append("--full-rebuild")
    if dry_run:
        cmd.append("--dry-run")
    if continue_on_error:
        cmd.append("--continue-on-error")
    if workers is not None:
        cmd.extend(["--workers", str(workers)])
    if db_url:
        cmd.extend(["--db-url", db_url])
    if verbose:
        cmd.append("--verbose")

    return cmd


# =============================================================================
# Step runner
# =============================================================================


def run_step(
    name: str,
    description: str,
    cmd: list[str],
    *,
    verbose: bool,
    timeout: int = TIMEOUT_DESC_STATS,
) -> StepResult:
    """
    Execute a subprocess step.

    Args:
        name: Step identifier.
        description: Human-readable step description.
        cmd: Command to execute.
        verbose: If True, stream output; otherwise capture and show on error.
        timeout: Subprocess timeout in seconds.

    Returns:
        StepResult with execution details.
    """
    print(f"\n{'=' * 70}")
    print(f"Running: {name} - {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'=' * 70}")

    start = time.perf_counter()

    try:
        if verbose:
            result = subprocess.run(cmd, check=False, timeout=timeout)
            returncode = result.returncode
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            returncode = result.returncode

            if returncode != 0:
                print(f"\n[ERROR] {name} failed with code {returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if returncode == 0:
            print(f"\n[OK] {name} completed successfully in {duration:.1f}s")
            return StepResult(
                name=name,
                success=True,
                duration_sec=duration,
                returncode=returncode,
            )
        else:
            error_msg = f"Exited with code {returncode}"
            print(f"\n[FAILED] {name} failed: {error_msg}")
            return StepResult(
                name=name,
                success=False,
                duration_sec=duration,
                returncode=returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {timeout}s"
        print(f"\n[TIMEOUT] {name}: {error_msg}")
        return StepResult(
            name=name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] {name} raised exception: {error_msg}")
        return StepResult(
            name=name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


# =============================================================================
# Summary
# =============================================================================


def print_summary(results: list[StepResult]) -> bool:
    """Print execution summary. Returns True if all steps succeeded."""
    print(f"\n{'=' * 70}")
    print("DESC STATS PIPELINE EXECUTION SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for r in results)
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nTotal steps: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if successful:
        print("\n[OK] Successful steps:")
        for r in successful:
            print(f"  - {r.name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed steps:")
        for r in failed:
            error_info = f" ({r.error_message})" if r.error_message else ""
            print(f"  - {r.name}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'=' * 70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} step(s) failed!")
        return False
    else:
        print("\n[OK] All desc stats pipeline steps completed successfully!")
        return True


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the complete descriptive stats refresh pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all stages for all assets
  python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all

  # Single asset, single TF
  python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids 1 --tf 1D

  # Custom correlation windows
  python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all --windows 30,90,180

  # Dry run (show commands without executing)
  python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all --dry-run

  # Continue on errors (still run correlation if asset stats fails)
  python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids all --continue-on-error

  # Full rebuild for asset 1
  python -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes --ids 1 --full-rebuild

Pipeline stages (in order):
  asset_stats   -- Per-asset descriptive statistics (mean, std, skew, kurtosis, VaR)
  correlation   -- Pairwise rolling correlations across assets
        """,
    )

    # ID and TF selection
    p.add_argument(
        "--ids",
        default="all",
        help='Comma-separated ID list or "all" (default: all)',
    )
    p.add_argument(
        "--tf",
        default=None,
        help="Specific timeframe to process (e.g. 1D, 4H)",
    )
    p.add_argument(
        "--windows",
        default=None,
        help="Comma-separated rolling window sizes (default: 30,60,90,252)",
    )

    # Execution options
    p.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Clear state and recompute all stats from scratch",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running correlation even if asset stats fails",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: 4)",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: from config/env)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show subprocess output (default: only show on error)",
    )

    return p.parse_args()


# =============================================================================
# Main
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args()

    print(f"\n{'=' * 70}")
    print("DESC STATS ORCHESTRATOR")
    print(f"{'=' * 70}")
    print("\nPipeline stages: asset_stats, correlation")
    print(f"IDs: {args.ids}")
    if args.tf:
        print(f"TF: {args.tf}")
    if args.windows:
        print(f"Windows: {args.windows}")
    print(f"Full rebuild: {args.full_rebuild}")
    print(f"Continue on error: {args.continue_on_error}")
    if args.dry_run:
        print("[DRY RUN] Mode enabled -- commands will be printed but not executed")

    # Build commands
    asset_stats_cmd = build_asset_stats_command(
        ids=args.ids,
        tf=args.tf,
        windows=args.windows,
        full_rebuild=args.full_rebuild,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
        workers=args.workers,
        db_url=args.db_url,
        verbose=args.verbose,
    )
    correlation_cmd = build_correlation_command(
        ids=args.ids,
        tf=args.tf,
        windows=args.windows,
        full_rebuild=args.full_rebuild,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
        workers=args.workers,
        db_url=args.db_url,
        verbose=args.verbose,
    )

    # ------------------------------------------------------------------
    # Dry run: print commands and exit
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n[DRY RUN] Would execute the following commands:")
        print("\n[DRY RUN] asset_stats (Per-asset descriptive statistics):")
        print(f"  {' '.join(asset_stats_cmd)}")
        print("\n[DRY RUN] correlation (Pairwise rolling correlations):")
        print(f"  {' '.join(correlation_cmd)}")
        print(
            "\n[DRY RUN] Would have executed 2 step(s) sequentially (asset_stats then correlation)"
        )
        return 0

    results: list[StepResult] = []

    # ------------------------------------------------------------------
    # Stage 1: Asset stats
    # ------------------------------------------------------------------
    asset_stats_result = run_step(
        "asset_stats",
        "Per-asset descriptive statistics",
        asset_stats_cmd,
        verbose=args.verbose,
    )
    results.append(asset_stats_result)

    if not asset_stats_result.success and not args.continue_on_error:
        print("\n[STOPPED] Asset stats failed, stopping execution")
        print("(Use --continue-on-error to still run correlation)")
        print_summary(results)
        return 1

    # ------------------------------------------------------------------
    # Stage 2: Cross-asset correlation
    # ------------------------------------------------------------------
    correlation_result = run_step(
        "correlation",
        "Pairwise rolling correlations",
        correlation_cmd,
        verbose=args.verbose,
    )
    results.append(correlation_result)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    all_success = print_summary(results)
    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
