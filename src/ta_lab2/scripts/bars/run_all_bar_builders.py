#!/usr/bin/env python
"""
Master orchestrator for all bar builder scripts.

Runs all bar builders in logical order with unified CLI and error reporting.

Usage:
    # Run all builders
    python run_all_bar_builders.py --ids 1,52,825

    # Run only specific builders
    python run_all_bar_builders.py --ids all --builders 1d,multi_tf

    # Skip specific builders
    python run_all_bar_builders.py --ids all --skip cal_anchor_iso,cal_anchor_us

    # Full rebuild for all multi-TF builders
    python run_all_bar_builders.py --ids all --full-rebuild

    # Continue on errors
    python run_all_bar_builders.py --ids all --continue-on-error
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BuilderConfig:
    """Configuration for a bar builder."""

    name: str
    script_path: str
    description: str
    requires_tz: bool = False
    supports_full_rebuild: bool = False
    custom_args: dict[str, str] | None = None


# All available builders in logical execution order
ALL_BUILDERS = [
    BuilderConfig(
        name="1d",
        script_path="refresh_cmc_price_bars_1d.py",
        description="1D canonical bars (SQL-based)",
        requires_tz=False,
        supports_full_rebuild=True,  # Uses --rebuild flag
    ),
    BuilderConfig(
        name="multi_tf",
        script_path="refresh_cmc_price_bars_multi_tf.py",
        description="Multi-timeframe rolling bars (7d, 14d, ...)",
        requires_tz=False,
        supports_full_rebuild=True,
    ),
    BuilderConfig(
        name="cal_iso",
        script_path="refresh_cmc_price_bars_multi_tf_cal_iso.py",
        description="Calendar-aligned bars (ISO week, month, quarter, year)",
        requires_tz=True,
        supports_full_rebuild=True,
        custom_args={"tz": "America/New_York"},
    ),
    BuilderConfig(
        name="cal_us",
        script_path="refresh_cmc_price_bars_multi_tf_cal_us.py",
        description="Calendar-aligned bars (US week starts Sunday)",
        requires_tz=True,
        supports_full_rebuild=True,
        custom_args={"tz": "America/New_York"},
    ),
    BuilderConfig(
        name="cal_anchor_iso",
        script_path="refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py",
        description="Calendar-anchored bars with partial snapshots (ISO)",
        requires_tz=True,
        supports_full_rebuild=True,
        custom_args={"tz": "America/New_York"},
    ),
    BuilderConfig(
        name="cal_anchor_us",
        script_path="refresh_cmc_price_bars_multi_tf_cal_anchor_us.py",
        description="Calendar-anchored bars with partial snapshots (US)",
        requires_tz=True,
        supports_full_rebuild=True,
        custom_args={"tz": "America/New_York"},
    ),
]

BUILDER_NAME_MAP = {b.name: b for b in ALL_BUILDERS}


def parse_builder_list(builder_arg: str) -> list[str]:
    """Parse comma-separated builder names."""
    if not builder_arg:
        return []
    return [name.strip() for name in builder_arg.split(",") if name.strip()]


def get_builders_to_run(
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[BuilderConfig]:
    """
    Determine which builders to run based on include/exclude filters.

    Args:
        include: If specified, only run these builders
        exclude: Skip these builders

    Returns:
        List of BuilderConfig objects to execute
    """
    if include:
        # Validate builder names
        invalid = [name for name in include if name not in BUILDER_NAME_MAP]
        if invalid:
            raise ValueError(
                f"Invalid builder names: {', '.join(invalid)}. "
                f"Valid options: {', '.join(BUILDER_NAME_MAP.keys())}"
            )
        builders = [BUILDER_NAME_MAP[name] for name in include]
    else:
        builders = ALL_BUILDERS.copy()

    if exclude:
        exclude_set = set(exclude)
        builders = [b for b in builders if b.name not in exclude_set]

    return builders


def build_command(
    builder: BuilderConfig,
    *,
    ids: str,
    db_url: str,
    full_rebuild: bool,
    num_processes: int | None,
    tz: str | None,
    dry_run: bool,
) -> list[str]:
    """
    Build subprocess command for a builder.

    Args:
        builder: Builder configuration
        ids: Comma-separated ID list or "all"
        db_url: Database URL
        full_rebuild: Whether to do full rebuild
        num_processes: Number of parallel processes (multi-TF builders only)
        tz: Timezone (calendar builders only)
        dry_run: If True, print command instead of executing

    Returns:
        Command as list of strings
    """
    script_dir = Path(__file__).parent
    script_path = script_dir / builder.script_path

    cmd = [sys.executable, str(script_path)]

    # Common args
    if builder.name == "1d":
        # 1D builder has different CLI structure
        cmd.extend(["--db-url", db_url])
        cmd.extend(["--ids", ids])
        if full_rebuild:
            cmd.append("--full-rebuild")
        # 1D always uses --keep-rejects for visibility
        cmd.append("--keep-rejects")
    else:
        # Multi-TF builders use standard CLI
        cmd.extend(["--db-url", db_url])
        cmd.extend(["--ids", ids])

        if full_rebuild and builder.supports_full_rebuild:
            cmd.append("--full-rebuild")

        if num_processes is not None:
            cmd.extend(["--num-processes", str(num_processes)])

        # Add timezone for calendar builders
        if builder.requires_tz:
            tz_value = tz or (builder.custom_args or {}).get("tz", "America/New_York")
            cmd.extend(["--tz", tz_value])

    return cmd


@dataclass
class BuilderResult:
    """Result of running a builder."""

    name: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


def run_builder(
    builder: BuilderConfig,
    cmd: list[str],
    *,
    verbose: bool,
) -> BuilderResult:
    """
    Execute a builder subprocess.

    Args:
        builder: Builder configuration
        cmd: Command to execute
        verbose: Whether to show builder output

    Returns:
        BuilderResult with execution details
    """
    print(f"\n{'=' * 70}")
    print(f"Running: {builder.name} - {builder.description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'=' * 70}")

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
                print(f"\n[ERROR] Builder failed with code {returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if returncode == 0:
            print(f"\n[OK] {builder.name} completed successfully in {duration:.1f}s")
            return BuilderResult(
                name=builder.name,
                success=True,
                duration_sec=duration,
                returncode=returncode,
            )
        else:
            error_msg = f"Exited with code {returncode}"
            print(f"\n[FAILED] {builder.name} failed: {error_msg}")
            return BuilderResult(
                name=builder.name,
                success=False,
                duration_sec=duration,
                returncode=returncode,
                error_message=error_msg,
            )

    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] {builder.name} raised exception: {error_msg}")
        return BuilderResult(
            name=builder.name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def print_summary(results: list[BuilderResult]) -> None:
    """Print execution summary."""
    print(f"\n{'=' * 70}")
    print("EXECUTION SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for r in results)
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nTotal builders: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if successful:
        print("\n[OK] Successful builders:")
        for r in successful:
            print(f"  - {r.name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed builders:")
        for r in failed:
            error_info = f" ({r.error_message})" if r.error_message else ""
            print(f"  - {r.name}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'=' * 70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} builder(s) failed!")
        return False
    else:
        print("\n[OK] All builders completed successfully!")
        return True


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Run all bar builders with unified configuration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all builders for specific IDs
  python run_all_bar_builders.py --ids 1,52,825

  # Run all builders with full rebuild
  python run_all_bar_builders.py --ids all --full-rebuild

  # Run only 1d and multi_tf builders
  python run_all_bar_builders.py --ids all --builders 1d,multi_tf

  # Run all except cal_anchor builders
  python run_all_bar_builders.py --ids all --skip cal_anchor_iso,cal_anchor_us

  # Continue on errors (don't stop if a builder fails)
  python run_all_bar_builders.py --ids all --continue-on-error

  # Dry run (show commands without executing)
  python run_all_bar_builders.py --ids all --dry-run

Available builders:
  1d              - 1D canonical bars (SQL-based)
  multi_tf        - Multi-timeframe rolling bars
  cal_iso         - Calendar-aligned bars (ISO week)
  cal_us          - Calendar-aligned bars (US week)
  cal_anchor_iso  - Calendar-anchored with partial snapshots (ISO)
  cal_anchor_us   - Calendar-anchored with partial snapshots (US)
        """,
    )

    p.add_argument(
        "--ids",
        required=True,
        help='Comma-separated ID list or "all"',
    )
    p.add_argument(
        "--db-url",
        default=os.environ.get("TARGET_DB_URL"),
        help="Database URL (default: TARGET_DB_URL env var)",
    )
    p.add_argument(
        "--builders",
        help="Comma-separated list of builders to run (default: all)",
    )
    p.add_argument(
        "--skip",
        help="Comma-separated list of builders to skip",
    )
    p.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Run full rebuild for all builders",
    )
    p.add_argument(
        "--num-processes",
        type=int,
        help="Number of parallel processes for multi-TF builders (default: 6)",
    )
    p.add_argument(
        "--tz",
        help="Timezone for calendar builders (default: America/New_York)",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running other builders if one fails",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show builder output (default: only show on error)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )

    args = p.parse_args(argv)

    # Validate
    if not args.db_url:
        print("[ERROR] --db-url required (or set TARGET_DB_URL env var)")
        return 1

    # Determine which builders to run
    try:
        include = parse_builder_list(args.builders) if args.builders else None
        exclude = parse_builder_list(args.skip) if args.skip else None
        builders = get_builders_to_run(include=include, exclude=exclude)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    if not builders:
        print("[ERROR] No builders selected!")
        return 1

    print(f"\n{'=' * 70}")
    print("BAR BUILDERS ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nBuilders to run: {', '.join(b.name for b in builders)}")
    print(f"IDs: {args.ids}")
    print(f"Full rebuild: {args.full_rebuild}")
    if args.num_processes:
        print(f"Num processes: {args.num_processes}")
    if args.tz:
        print(f"Timezone: {args.tz}")
    print(f"Continue on error: {args.continue_on_error}")

    # Execute builders
    results: list[BuilderResult] = []

    for builder in builders:
        cmd = build_command(
            builder,
            ids=args.ids,
            db_url=args.db_url,
            full_rebuild=args.full_rebuild,
            num_processes=args.num_processes,
            tz=args.tz,
            dry_run=args.dry_run,
        )

        if args.dry_run:
            print(f"\n[DRY RUN] {builder.name}:")
            print(f"  {' '.join(cmd)}")
            continue

        result = run_builder(builder, cmd, verbose=args.verbose)
        results.append(result)

        # Stop on error if not continuing
        if not result.success and not args.continue_on_error:
            print(f"\n[STOPPED] Builder {builder.name} failed, stopping execution")
            print("(Use --continue-on-error to run remaining builders)")
            break

    if args.dry_run:
        print(f"\n[DRY RUN] Would have executed {len(builders)} builder(s)")
        return 0

    # Print summary
    all_success = print_summary(results)

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
