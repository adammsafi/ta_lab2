#!/usr/bin/env python
"""
Master orchestrator for all AMA refresh scripts.

Runs the complete AMA pipeline in logical order with unified CLI and error
reporting:

  1. AMA values  -- multi_tf, cal (us+iso), cal_anchor (us+iso)
  2. AMA returns -- all sources
  3. Z-scores    -- AMA returns tables

Usage:
    # Run all stages for all assets, all TFs
    python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs

    # Run only specific value refreshers
    python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --only multi_tf,cal

    # Single asset, single TF
    python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids 1 --tf 1D

    # KAMA only
    python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --indicators KAMA

    # Use 8 parallel processes
    python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs -n 8

    # Dry run to see what would execute
    python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --dry-run

    # Continue on errors
    python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --continue-on-error
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass

from ta_lab2.scripts.emas.logging_config import setup_logging, add_logging_args

# Timeout tiers (seconds); matches EMA tier
TIMEOUT_AMAS = 10800  # 3 hours -- AMA refreshers (full pipeline takes ~90min)


# =============================================================================
# Data structures
# =============================================================================


@dataclass
class RefresherConfig:
    """Configuration for an AMA value refresher."""

    name: str
    module: str
    description: str
    supports_scheme: bool = False  # For cal/cal_anchor with us/iso/both


@dataclass
class PostStep:
    """A post-processing step run after value refreshers complete."""

    name: str
    description: str
    module: str | None = None  # If set, run via python -m module
    script: str | None = None  # If set, run via script file in amas dir
    extra_args: list[str] | None = None  # Extra fixed args (e.g. --tables amas)


@dataclass
class RefresherResult:
    """Result of running a refresher or post-step."""

    name: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


# =============================================================================
# Configuration: value refreshers
# =============================================================================

ALL_AMA_VALUE_REFRESHERS = [
    RefresherConfig(
        name="multi_tf",
        module="ta_lab2.scripts.amas.refresh_ama_multi_tf",
        description="Multi-TF AMAs",
        supports_scheme=False,
    ),
    RefresherConfig(
        name="cal",
        module="ta_lab2.scripts.amas.refresh_ama_multi_tf_cal_from_bars",
        description="Calendar AMAs (us+iso)",
        supports_scheme=True,
    ),
    RefresherConfig(
        name="cal_anchor",
        module="ta_lab2.scripts.amas.refresh_ama_multi_tf_cal_anchor_from_bars",
        description="Calendar anchor AMAs (us+iso)",
        supports_scheme=True,
    ),
]

REFRESHER_NAME_MAP = {r.name: r for r in ALL_AMA_VALUE_REFRESHERS}

# Post-steps run after ALL value refreshers (or those that succeeded) complete
POST_STEPS = [
    PostStep(
        name="returns",
        module="ta_lab2.scripts.amas.refresh_returns_ama",
        description="AMA returns",
    ),
    PostStep(
        name="zscores",
        module="ta_lab2.scripts.returns.refresh_returns_zscore",
        description="AMA z-scores",
        extra_args=["--tables", "amas"],
    ),
]


# =============================================================================
# Helpers
# =============================================================================


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
    Determine which value refreshers to run based on include filter.

    Args:
        include: If specified, only run these refreshers.

    Returns:
        List of RefresherConfig objects to execute.
    """
    if include:
        invalid = [name for name in include if name not in REFRESHER_NAME_MAP]
        if invalid:
            raise ValueError(
                f"Invalid refresher names: {', '.join(invalid)}. "
                f"Valid options: {', '.join(REFRESHER_NAME_MAP.keys())}"
            )
        return [REFRESHER_NAME_MAP[name] for name in include]
    return ALL_AMA_VALUE_REFRESHERS.copy()


def build_value_command(
    refresher: RefresherConfig,
    *,
    ids: str,
    tf: str | None,
    all_tfs: bool,
    indicators: str | None,
    num_processes: int | None,
    full_rebuild: bool,
    verbose: bool,
    db_url: str | None,
) -> list[str]:
    """
    Build subprocess command for a value refresher.

    Args:
        refresher: Refresher configuration.
        ids: Comma-separated ID list or "all".
        tf: Specific TF (e.g. "1D").
        all_tfs: If True, pass --all-tfs.
        indicators: Comma-separated indicator filter (e.g. "KAMA,DEMA").
        num_processes: Number of parallel processes.
        full_rebuild: If True, pass --full-rebuild.
        verbose: If True, pass --verbose.
        db_url: Database URL to forward.

    Returns:
        Command as list of strings.
    """
    cmd = [sys.executable, "-m", refresher.module]

    cmd.extend(["--ids", ids])

    if all_tfs:
        cmd.append("--all-tfs")
    elif tf:
        cmd.extend(["--tf", tf])

    if indicators:
        cmd.extend(["--indicators", indicators])

    if num_processes is not None:
        cmd.extend(["--num-processes", str(num_processes)])

    if full_rebuild:
        cmd.append("--full-rebuild")

    # Note: --verbose is NOT passed to sub-scripts (not all accept it).
    # Verbose output is controlled at the orchestrator level via stream_output.

    if db_url:
        cmd.extend(["--db-url", db_url])

    # Calendar refreshers: pass --scheme both by default
    if refresher.supports_scheme:
        cmd.extend(["--scheme", "both"])

    return cmd


def build_post_command(
    step: PostStep,
    *,
    ids: str | None,
    tf: str | None,
    all_tfs: bool,
    verbose: bool,
    db_url: str | None,
) -> list[str]:
    """
    Build subprocess command for a post-processing step.

    Args:
        step: Post-step configuration.
        ids: Comma-separated ID list or "all" (forwarded to returns step).
        tf: Specific TF.
        all_tfs: If True, pass --all-tfs.
        verbose: If True, pass --verbose.
        db_url: Database URL to forward.

    Returns:
        Command as list of strings.
    """
    assert step.module is not None, "PostStep must have a module"

    cmd = [sys.executable, "-m", step.module]

    # Only returns step accepts --ids / --tf / --all-tfs
    if step.name == "returns":
        if ids:
            cmd.extend(["--ids", ids])
        if all_tfs:
            cmd.append("--all-tfs")
        elif tf:
            cmd.extend(["--tf", tf])

    if step.extra_args:
        cmd.extend(step.extra_args)

    # Note: --verbose is NOT passed to sub-scripts (not all accept it).

    if db_url:
        cmd.extend(["--db-url", db_url])

    return cmd


def run_step(
    name: str,
    description: str,
    cmd: list[str],
    *,
    verbose: bool,
) -> RefresherResult:
    """
    Execute a subprocess step (value refresher or post-step).

    Args:
        name: Step identifier.
        description: Human-readable step description.
        cmd: Command to execute.
        verbose: If True, stream output; otherwise capture and show on error.

    Returns:
        RefresherResult with execution details.
    """
    print(f"\n{'=' * 70}")
    print(f"Running: {name} - {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'=' * 70}")

    start = time.perf_counter()

    try:
        if verbose:
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_AMAS)
            returncode = result.returncode
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_AMAS,
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
            return RefresherResult(
                name=name,
                success=True,
                duration_sec=duration,
                returncode=returncode,
            )
        else:
            error_msg = f"Exited with code {returncode}"
            print(f"\n[FAILED] {name} failed: {error_msg}")
            return RefresherResult(
                name=name,
                success=False,
                duration_sec=duration,
                returncode=returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_AMAS}s"
        print(f"\n[TIMEOUT] {name}: {error_msg}")
        return RefresherResult(
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
        return RefresherResult(
            name=name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def print_summary(results: list[RefresherResult]) -> bool:
    """Print execution summary. Returns True if all steps succeeded."""
    print(f"\n{'=' * 70}")
    print("AMA PIPELINE EXECUTION SUMMARY")
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
        print("\n[OK] All AMA pipeline steps completed successfully!")
        return True


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the complete AMA refresh pipeline with unified configuration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all stages for all assets, all TFs
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs

  # Single asset, single TF
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids 1 --tf 1D

  # Run only multi_tf and cal value refreshers (skips cal_anchor)
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --only multi_tf,cal

  # KAMA only for assets 1 and 52
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids 1,52 --all-tfs --indicators KAMA

  # Use 8 parallel processes for AMA computation
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs -n 8

  # Continue on errors (don't stop if a step fails)
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --continue-on-error

  # Dry run (show commands without executing)
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --dry-run

  # Full rebuild for asset 1
  python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids 1 --all-tfs --full-rebuild

Pipeline stages (in order):
  multi_tf    -- Multi-TF AMAs (KAMA, DEMA, TEMA, HMA)
  cal         -- Calendar-aligned AMAs (us+iso)
  cal_anchor  -- Calendar-anchored AMAs (us+iso)
  returns     -- AMA returns for all sources
  zscores     -- Z-scores on AMA returns tables

CONNECTION NOTES: AMA refreshers use parallel workers (default: 4).
Use -n/--num-processes to increase or decrease parallelism.
If you see "too many clients already" errors, reduce -n or close other DB clients.
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
        "--all-tfs",
        action="store_true",
        help="Process all timeframes (recommended for daily refresh)",
    )

    # Value refresher selection
    p.add_argument(
        "--only",
        default="",
        help=(
            "Comma-separated list of value refreshers to run "
            "(default: all). Options: multi_tf, cal, cal_anchor"
        ),
    )

    # AMA type filter
    p.add_argument(
        "--indicators",
        default=None,
        help=(
            "Comma-separated AMA indicator filter forwarded to value refreshers "
            "(e.g. KAMA,DEMA). Default: all indicators"
        ),
    )

    # Execution options
    p.add_argument(
        "-n",
        "--num-processes",
        type=int,
        help="Number of parallel processes for AMA computation (default: 4)",
    )
    p.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Clear state and recompute all AMA values from scratch",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running remaining steps if one fails",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show subprocess output (default: only show on error)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: from config/env)",
    )

    add_logging_args(p)

    return p.parse_args()


# =============================================================================
# Main
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args()

    _logger = setup_logging(
        name="ama_runner",
        level=args.log_level,
        log_file=args.log_file,
        quiet=args.quiet,
        debug=args.debug,
    )

    # Validate TF selection
    if not args.all_tfs and not args.tf and not args.dry_run:
        print(
            "[WARNING] Neither --tf nor --all-tfs specified. Defaulting to --all-tfs."
        )
        args.all_tfs = True

    # Determine which value refreshers to run
    try:
        include = parse_refresher_list(args.only) if args.only else None
        refreshers = get_refreshers_to_run(include=include)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    if not refreshers:
        print("[ERROR] No value refreshers selected!")
        return 1

    print(f"\n{'=' * 70}")
    print("AMA REFRESHERS ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nValue refreshers: {', '.join(r.name for r in refreshers)}")
    print(f"Post-steps: {', '.join(s.name for s in POST_STEPS)}")
    print(f"IDs: {args.ids}")
    if args.all_tfs:
        print("TFs: all")
    elif args.tf:
        print(f"TF: {args.tf}")
    if args.indicators:
        print(f"Indicators: {args.indicators}")
    print(f"Continue on error: {args.continue_on_error}")

    results: list[RefresherResult] = []
    any_value_succeeded = False

    # ------------------------------------------------------------------
    # Stage 1: Value refreshers
    # ------------------------------------------------------------------
    for refresher in refreshers:
        cmd = build_value_command(
            refresher,
            ids=args.ids,
            tf=args.tf,
            all_tfs=args.all_tfs,
            indicators=args.indicators,
            num_processes=args.num_processes,
            full_rebuild=args.full_rebuild,
            verbose=args.verbose,
            db_url=args.db_url,
        )

        if args.dry_run:
            print(f"\n[DRY RUN] {refresher.name} ({refresher.description}):")
            print(f"  {' '.join(cmd)}")
            continue

        result = run_step(
            refresher.name, refresher.description, cmd, verbose=args.verbose
        )
        results.append(result)

        if result.success:
            any_value_succeeded = True
        elif not args.continue_on_error:
            print(f"\n[STOPPED] {refresher.name} failed, stopping execution")
            print("(Use --continue-on-error to run remaining steps)")
            print_summary(results)
            return 1

    # ------------------------------------------------------------------
    # Stage 2: Post-steps (runs if any value refresher succeeded)
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n[DRY RUN] Post-steps would execute after value refreshers:")
        for step in POST_STEPS:
            cmd = build_post_command(
                step,
                ids=args.ids,
                tf=args.tf,
                all_tfs=args.all_tfs,
                verbose=args.verbose,
                db_url=args.db_url,
            )
            print(f"\n[DRY RUN] {step.name} ({step.description}):")
            print(f"  {' '.join(cmd)}")
        print(
            f"\n[DRY RUN] Would have executed {len(refreshers)} value refresher(s) + {len(POST_STEPS)} post-step(s)"
        )
        return 0

    if not any_value_succeeded:
        print("\n[SKIPPED] No value refreshers succeeded -- skipping post-steps")
        print_summary(results)
        return 1

    for step in POST_STEPS:
        cmd = build_post_command(
            step,
            ids=args.ids,
            tf=args.tf,
            all_tfs=args.all_tfs,
            verbose=args.verbose,
            db_url=args.db_url,
        )

        result = run_step(step.name, step.description, cmd, verbose=args.verbose)
        results.append(result)

        if not result.success and not args.continue_on_error:
            print(f"\n[STOPPED] Post-step {step.name} failed, stopping execution")
            print("(Use --continue-on-error to run remaining post-steps)")
            print_summary(results)
            return 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    all_success = print_summary(results)
    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
