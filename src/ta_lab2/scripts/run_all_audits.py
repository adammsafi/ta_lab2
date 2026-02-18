#!/usr/bin/env python
"""
Master orchestrator for all audit scripts.

Runs all audit scripts for bars, EMAs, and returns:
- Bar integrity, samples, and table audits
- EMA integrity, samples, table, and coverage audits
- Returns integrity audits for all table types

Usage:
    # Run all audits
    python run_all_audits.py

    # Run only bar audits
    python run_all_audits.py --types bars

    # Run only EMA audits
    python run_all_audits.py --types emas

    # Dry run
    python run_all_audits.py --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AuditScript:
    """Configuration for an audit script."""

    name: str
    script_path: str
    description: str
    category: str  # "bars", "emas", "returns"


# All audit scripts organized by category
ALL_AUDIT_SCRIPTS = [
    # Bar audits
    AuditScript(
        name="bar_integrity",
        script_path="bars/audit_price_bars_integrity.py",
        description="Bar integrity checks (OHLC, time ordering)",
        category="bars",
    ),
    AuditScript(
        name="bar_samples",
        script_path="bars/audit_price_bars_samples.py",
        description="Bar sample data validation",
        category="bars",
    ),
    AuditScript(
        name="bar_tables",
        script_path="bars/audit_price_bars_tables.py",
        description="Bar table structure and coverage",
        category="bars",
    ),
    # EMA audits
    AuditScript(
        name="ema_integrity",
        script_path="emas/audit_ema_integrity.py",
        description="EMA integrity checks (NaN, infinity, bounds)",
        category="emas",
    ),
    AuditScript(
        name="ema_samples",
        script_path="emas/audit_ema_samples.py",
        description="EMA sample data validation",
        category="emas",
    ),
    AuditScript(
        name="ema_tables",
        script_path="emas/audit_ema_tables.py",
        description="EMA table structure and coverage",
        category="emas",
    ),
    AuditScript(
        name="ema_coverage",
        script_path="emas/audit_ema_expected_coverage.py",
        description="EMA expected coverage validation",
        category="emas",
    ),
    # Returns audits (bars)
    AuditScript(
        name="returns_d1",
        script_path="returns/audit_returns_d1_integrity.py",
        description="Returns integrity (1D bars)",
        category="returns",
    ),
    AuditScript(
        name="returns_bars_multi_tf",
        script_path="returns/audit_returns_bars_multi_tf_integrity.py",
        description="Returns integrity (multi-TF bars)",
        category="returns",
    ),
    AuditScript(
        name="returns_bars_cal_iso",
        script_path="returns/audit_returns_bars_multi_tf_cal_iso_integrity.py",
        description="Returns integrity (calendar ISO bars)",
        category="returns",
    ),
    AuditScript(
        name="returns_bars_cal_us",
        script_path="returns/audit_returns_bars_multi_tf_cal_us_integrity.py",
        description="Returns integrity (calendar US bars)",
        category="returns",
    ),
    AuditScript(
        name="returns_bars_cal_anchor_iso",
        script_path="returns/audit_returns_bars_multi_tf_cal_anchor_iso_integrity.py",
        description="Returns integrity (calendar anchor ISO bars)",
        category="returns",
    ),
    AuditScript(
        name="returns_bars_cal_anchor_us",
        script_path="returns/audit_returns_bars_multi_tf_cal_anchor_us_integrity.py",
        description="Returns integrity (calendar anchor US bars)",
        category="returns",
    ),
    # Returns audits (EMAs)
    AuditScript(
        name="returns_ema_multi_tf",
        script_path="returns/audit_returns_ema_multi_tf_integrity.py",
        description="Returns integrity (multi-TF EMAs)",
        category="returns",
    ),
    AuditScript(
        name="returns_ema_multi_tf_v2",
        script_path="returns/audit_returns_ema_multi_tf_v2_integrity.py",
        description="Returns integrity (multi-TF V2 EMAs)",
        category="returns",
    ),
    AuditScript(
        name="returns_ema_multi_tf_u",
        script_path="returns/audit_returns_ema_multi_tf_u_integrity.py",
        description="Returns integrity (multi-TF U EMAs)",
        category="returns",
    ),
    AuditScript(
        name="returns_ema_cal",
        script_path="returns/audit_returns_ema_multi_tf_cal_integrity.py",
        description="Returns integrity (calendar EMAs)",
        category="returns",
    ),
    AuditScript(
        name="returns_ema_cal_anchor",
        script_path="returns/audit_returns_ema_multi_tf_cal_anchor_integrity.py",
        description="Returns integrity (calendar anchor EMAs)",
        category="returns",
    ),
]


@dataclass
class ComponentResult:
    """Result of running an audit script."""

    name: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


def run_audit_script(
    script: AuditScript,
    db_url: str | None,
    verbose: bool,
    dry_run: bool,
) -> ComponentResult:
    """
    Run an audit script via subprocess.

    Args:
        script: Audit script configuration
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

    if db_url:
        cmd.extend(["--db-url", db_url])

    print(f"\n{'=' * 70}")
    print(f"RUNNING: {script.description} ({script.name})")
    print(f"{'=' * 70}")
    if verbose:
        print(f"Command: {' '.join(cmd)}")

    if dry_run:
        print("[DRY RUN] Would execute audit")
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
                print(f"\n[ERROR] Audit failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] {script.description} passed in {duration:.1f}s")
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
        True if all audits passed, False otherwise
    """
    print(f"\n{'=' * 70}")
    print("AUDIT SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for r in results)
    passed = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nTotal audits: {len(results)}")
    print(f"Passed: {len(passed)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if passed:
        print("\n[OK] Passed audits:")
        for r in passed:
            print(f"  - {r.name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed audits:")
        for r in failed:
            error_info = f" ({r.error_message})" if r.error_message else ""
            print(f"  - {r.name}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'=' * 70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} audit(s) failed!")
        return False
    else:
        print("\n[OK] All audits passed!")
        return True


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Master orchestrator for all audit scripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all audits
  python run_all_audits.py

  # Run only bar audits
  python run_all_audits.py --types bars

  # Run only EMA audits
  python run_all_audits.py --types emas

  # Run bar and EMA audits (exclude returns)
  python run_all_audits.py --types bars,emas

  # Dry run
  python run_all_audits.py --dry-run

  # Continue on errors
  python run_all_audits.py --continue-on-error
        """,
    )

    p.add_argument(
        "--types",
        help='Comma-separated types to run: "bars", "emas", "returns" (default: all)',
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
        help="Continue running remaining audits if one fails",
    )

    args = p.parse_args(argv)

    # Filter scripts by type if specified
    if args.types:
        requested_types = set(args.types.split(","))
        scripts_to_run = [s for s in ALL_AUDIT_SCRIPTS if s.category in requested_types]

        unknown_types = requested_types - {"bars", "emas", "returns"}
        if unknown_types:
            print(f"[WARNING] Unknown types: {unknown_types}")
            print("Available types: bars, emas, returns")

        if not scripts_to_run:
            print("[ERROR] No valid audit types specified")
            return 1
    else:
        scripts_to_run = ALL_AUDIT_SCRIPTS

    # Group by category for display
    by_category = {}
    for script in scripts_to_run:
        if script.category not in by_category:
            by_category[script.category] = []
        by_category[script.category].append(script)

    print(f"\n{'=' * 70}")
    print("AUDIT ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nTotal audits to run: {len(scripts_to_run)}")
    for category, scripts in sorted(by_category.items()):
        print(f"\n{category.upper()} audits ({len(scripts)}):")
        for script in scripts:
            print(f"  - {script.name}: {script.description}")
    print(f"\nContinue on error: {args.continue_on_error}")

    results: list[ComponentResult] = []

    # Run each audit
    for script in scripts_to_run:
        result = run_audit_script(
            script=script,
            db_url=args.db_url,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
        results.append(result)

        if not result.success and not args.continue_on_error:
            print(f"\n[STOPPED] {script.name} failed, stopping execution")
            print("(Use --continue-on-error to run remaining audits)")
            break

    # Print summary
    if not args.dry_run:
        all_success = print_summary(results)
        return 0 if all_success else 1
    else:
        print(f"\n[DRY RUN] Would have executed {len(results)} audit(s)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
