#!/usr/bin/env python
"""
Baseline capture orchestration script.

Implements Snapshot -> Truncate -> Rebuild -> Compare workflow to validate
that bar and EMA refactoring preserved calculation correctness.

Usage:
    # Full workflow for specific IDs
    python capture_baseline.py --ids 1,52,825

    # Dry run to see commands
    python capture_baseline.py --ids 1 --dry-run

    # Skip rebuild, only snapshot + compare
    python capture_baseline.py --ids all --skip-rebuild

    # Verbose output from subprocesses
    python capture_baseline.py --ids all --verbose

Pattern from Phase 23: subprocess isolation, dry-run, verbose control, summary reporting
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
import pandas as pd

from ta_lab2.scripts.baseline.comparison_utils import (
    compare_tables,
    COLUMN_TOLERANCES,
)
from ta_lab2.scripts.baseline.metadata_tracker import (
    BaselineConfig,
    capture_metadata,
    save_metadata,
)


# =============================================================================
# Table Configuration
# =============================================================================

# All 6 bar tables from Phase 21 documentation
BAR_TABLES = [
    "public.cmc_price_bars_1d",
    "public.cmc_price_bars_multi_tf",
    "public.cmc_price_bars_multi_tf_cal_iso",
    "public.cmc_price_bars_multi_tf_cal_us",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso",
    "public.cmc_price_bars_multi_tf_cal_anchor_us",
]

# All 5 EMA tables
EMA_TABLES = [
    "public.cmc_ema_multi_tf",
    "public.cmc_ema_multi_tf_cal_us",
    "public.cmc_ema_multi_tf_cal_iso",
    "public.cmc_ema_multi_tf_cal_anchor_us",
    "public.cmc_ema_multi_tf_cal_anchor_iso",
]

# Bar table column configuration
BAR_KEY_COLUMNS = ["id", "tf", "bar_seq", "timestamp"]
BAR_FLOAT_COLUMNS = ["open", "high", "low", "close", "volume", "market_cap"]

# EMA table column configuration
EMA_KEY_COLUMNS = ["id", "tf", "period", "ts"]
EMA_FLOAT_COLUMNS = ["ema"]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SubprocessResult:
    """Result of running a subprocess (bars or EMAs)."""

    component: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


@dataclass
class SnapshotInfo:
    """Information about a created snapshot."""

    table_name: str
    snapshot_name: str
    row_count: int
    created: bool


@dataclass
class ComparisonSummary:
    """Summary of comparison for one table."""

    table_name: str
    passed: bool
    match_rate: float
    mismatch_count: int
    max_diff: float
    mean_diff: float
    severity: str


# =============================================================================
# Phase 1: Snapshot Creation
# =============================================================================


def create_snapshots(
    engine,
    tables: list[str],
    timestamp_suffix: str,
    asset_ids: list[int] | None,
    *,
    dry_run: bool = False,
) -> list[SnapshotInfo]:
    """
    Create timestamped snapshots of all tables.

    Args:
        engine: SQLAlchemy engine
        tables: List of table names (schema.table format)
        timestamp_suffix: Timestamp suffix (YYYYMMDD_HHMMSS)
        asset_ids: List of asset IDs to snapshot (None = all)
        dry_run: If True, print SQL without executing

    Returns:
        List of SnapshotInfo objects
    """
    print(f"\n{'=' * 70}")
    print("PHASE 1: CREATING SNAPSHOTS")
    print(f"{'=' * 70}")
    print(f"Timestamp suffix: {timestamp_suffix}")
    print(f"Tables to snapshot: {len(tables)}")
    print(f"Asset filter: {asset_ids if asset_ids else 'all'}")

    snapshots = []

    for table in tables:
        # Parse schema.table
        schema, table_name = table.split(".")
        snapshot_name = f"{table_name}_snapshot_{timestamp_suffix}"
        full_snapshot_name = f"{schema}.{snapshot_name}"

        print(f"\n[Snapshot] {table} -> {full_snapshot_name}")

        # Build CREATE TABLE AS SELECT with optional WHERE clause
        if asset_ids:
            id_list = ",".join(str(i) for i in asset_ids)
            sql = f"CREATE TABLE {full_snapshot_name} AS SELECT * FROM {table} WHERE id IN ({id_list});"
        else:
            sql = f"CREATE TABLE {full_snapshot_name} AS SELECT * FROM {table};"

        if dry_run:
            print(f"[DRY RUN] {sql}")
            snapshots.append(
                SnapshotInfo(
                    table_name=table,
                    snapshot_name=full_snapshot_name,
                    row_count=0,
                    created=False,
                )
            )
            continue

        try:
            # Create snapshot
            with engine.begin() as conn:
                conn.execute(text(sql))

            # Get row count
            with engine.begin() as conn:
                result = conn.execute(
                    text(f"SELECT COUNT(*) FROM {full_snapshot_name}")
                )
                row_count = result.scalar()

            print(f"[OK] Snapshot created with {row_count:,} rows")

            # Add primary key for efficient comparison (bar tables)
            if "bar" in table_name.lower():
                pk_name = f"{snapshot_name}_pkey"
                pk_cols = ", ".join(BAR_KEY_COLUMNS)
                pk_sql = f"ALTER TABLE {full_snapshot_name} ADD CONSTRAINT {pk_name} PRIMARY KEY ({pk_cols});"

                with engine.begin() as conn:
                    conn.execute(text(pk_sql))

                print(f"[OK] Primary key added: ({pk_cols})")

            # Add primary key for EMA tables
            elif "ema" in table_name.lower():
                pk_name = f"{snapshot_name}_pkey"
                pk_cols = ", ".join(EMA_KEY_COLUMNS)
                pk_sql = f"ALTER TABLE {full_snapshot_name} ADD CONSTRAINT {pk_name} PRIMARY KEY ({pk_cols});"

                with engine.begin() as conn:
                    conn.execute(text(pk_sql))

                print(f"[OK] Primary key added: ({pk_cols})")

            snapshots.append(
                SnapshotInfo(
                    table_name=table,
                    snapshot_name=full_snapshot_name,
                    row_count=row_count,
                    created=True,
                )
            )

        except Exception as e:
            print(f"[ERROR] Failed to create snapshot: {e}")
            snapshots.append(
                SnapshotInfo(
                    table_name=table,
                    snapshot_name=full_snapshot_name,
                    row_count=0,
                    created=False,
                )
            )

    # Summary
    created_count = sum(1 for s in snapshots if s.created)
    total_rows = sum(s.row_count for s in snapshots)
    print(f"\n[Summary] {created_count}/{len(tables)} snapshots created")
    print(f"[Summary] Total rows: {total_rows:,}")

    return snapshots


# =============================================================================
# Phase 2: Truncate Tables
# =============================================================================


def truncate_tables(
    engine, tables: list[str], *, dry_run: bool = False
) -> dict[str, bool]:
    """
    Truncate all tables to prepare for rebuild.

    Args:
        engine: SQLAlchemy engine
        tables: List of table names (schema.table format)
        dry_run: If True, print SQL without executing

    Returns:
        Dict mapping table name to success boolean
    """
    print(f"\n{'=' * 70}")
    print("PHASE 2: TRUNCATING TABLES")
    print(f"{'=' * 70}")
    print(f"Tables to truncate: {len(tables)}")

    results = {}

    for table in tables:
        print(f"\n[Truncate] {table}")

        sql = f"TRUNCATE TABLE {table};"

        if dry_run:
            print(f"[DRY RUN] {sql}")
            results[table] = True
            continue

        try:
            with engine.begin() as conn:
                conn.execute(text(sql))

            # Verify truncation
            with engine.begin() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                row_count = result.scalar()

            if row_count == 0:
                print("[OK] Truncated successfully (verified 0 rows)")
                results[table] = True
            else:
                print(f"[WARNING] Truncate failed - {row_count} rows remain")
                results[table] = False

        except Exception as e:
            print(f"[ERROR] Failed to truncate: {e}")
            results[table] = False

    # Summary
    success_count = sum(1 for success in results.values() if success)
    print(f"\n[Summary] {success_count}/{len(tables)} tables truncated")

    return results


# =============================================================================
# Phase 3: Rebuild Bars and EMAs
# =============================================================================


def run_bar_builders(
    ids: str, db_url: str, verbose: bool, dry_run: bool
) -> SubprocessResult:
    """
    Run bar builders via subprocess.

    Args:
        ids: Comma-separated ID list or "all"
        db_url: Database URL
        verbose: Show subprocess output
        dry_run: Print command without executing

    Returns:
        SubprocessResult with execution details
    """
    script_dir = Path(__file__).parent.parent / "bars"
    cmd = [
        sys.executable,
        str(script_dir / "run_all_bar_builders.py"),
        "--ids",
        ids,
        "--db-url",
        db_url,
        "--full-rebuild",
    ]

    if verbose:
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print("PHASE 3A: REBUILDING BARS")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if dry_run:
        print("[DRY RUN] Would execute bar builders")
        return SubprocessResult(
            component="bars",
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
                print(f"\n[ERROR] Bar builders failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Bar builders completed in {duration:.1f}s")
            return SubprocessResult(
                component="bars",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Bar builders: {error_msg}")
            return SubprocessResult(
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
        return SubprocessResult(
            component="bars",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_ema_refreshers(
    ids: str, db_url: str, verbose: bool, dry_run: bool
) -> SubprocessResult:
    """
    Run EMA refreshers via subprocess.

    Args:
        ids: Comma-separated ID list or "all"
        db_url: Database URL (not used by current EMA orchestrator)
        verbose: Show subprocess output
        dry_run: Print command without executing

    Returns:
        SubprocessResult with execution details
    """
    script_dir = Path(__file__).parent.parent / "emas"
    cmd = [
        sys.executable,
        str(script_dir / "run_all_ema_refreshes.py"),
        "--ids",
        ids,
    ]

    if verbose:
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print("PHASE 3B: REBUILDING EMAS")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if dry_run:
        print("[DRY RUN] Would execute EMA refreshers")
        return SubprocessResult(
            component="emas",
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
                print(f"\n[ERROR] EMA refreshers failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] EMA refreshers completed in {duration:.1f}s")
            return SubprocessResult(
                component="emas",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] EMA refreshers: {error_msg}")
            return SubprocessResult(
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
        return SubprocessResult(
            component="emas",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


# =============================================================================
# Phase 4: Compare Snapshots to Rebuilt Tables
# =============================================================================


def sample_table_for_comparison(
    engine,
    table_name: str,
    asset_ids: list[int] | None,
    *,
    beginning_days: int = 30,
    end_days: int = 30,
    random_sample_pct: float = 0.05,
) -> pd.DataFrame:
    """
    Intelligent sampling strategy per RESEARCH.md Pattern 3.

    Samples:
    1. First N days per asset (beginning focus - drift detection)
    2. Last N days per asset (end focus - recent data verification)
    3. Stratified random sample from interior (5% default)

    Args:
        engine: SQLAlchemy engine
        table_name: Table name (schema.table format)
        asset_ids: List of asset IDs to sample (None = all)
        beginning_days: Number of days to sample from beginning (default: 30)
        end_days: Number of days to sample from end (default: 30)
        random_sample_pct: Random sample percentage for interior (default: 0.05)

    Returns:
        DataFrame with combined sample
    """
    # Determine timestamp column based on table type
    if "bar" in table_name.lower():
        ts_col = "timestamp"
    else:  # EMA tables
        ts_col = "ts"

    # Build WHERE clause for asset filter
    where_clause = ""
    if asset_ids:
        id_list = ",".join(str(i) for i in asset_ids)
        where_clause = f"WHERE id IN ({id_list})"

    # Beginning sample (first N days)
    beginning_sql = f"""
    SELECT * FROM {table_name}
    {where_clause}
    {" AND " if where_clause else "WHERE "} {ts_col} <= (
        SELECT MIN({ts_col}) + INTERVAL '{beginning_days} days'
        FROM {table_name}
        {where_clause}
    )
    ORDER BY id, {ts_col}
    """

    # End sample (last N days)
    end_sql = f"""
    SELECT * FROM {table_name}
    {where_clause}
    {" AND " if where_clause else "WHERE "} {ts_col} >= (
        SELECT MAX({ts_col}) - INTERVAL '{end_days} days'
        FROM {table_name}
        {where_clause}
    )
    ORDER BY id, {ts_col}
    """

    # Random interior sample (exclude beginning/end)
    random_sql = f"""
    SELECT * FROM {table_name}
    {where_clause}
    {" AND " if where_clause else "WHERE "} random() < {random_sample_pct}
    AND {ts_col} > (
        SELECT MIN({ts_col}) + INTERVAL '{beginning_days} days'
        FROM {table_name}
        {where_clause}
    )
    AND {ts_col} < (
        SELECT MAX({ts_col}) - INTERVAL '{end_days} days'
        FROM {table_name}
        {where_clause}
    )
    ORDER BY id, {ts_col}
    """

    # Execute queries and combine
    with engine.connect() as conn:
        beginning_df = pd.read_sql(text(beginning_sql), conn)
        end_df = pd.read_sql(text(end_sql), conn)
        random_df = pd.read_sql(text(random_sql), conn)

    # Combine and drop duplicates (beginning/end may overlap)
    combined = pd.concat([beginning_df, end_df, random_df], ignore_index=True)

    # Determine key columns for deduplication
    if "bar" in table_name.lower():
        key_cols = BAR_KEY_COLUMNS
    else:
        key_cols = EMA_KEY_COLUMNS

    combined = combined.drop_duplicates(subset=key_cols, keep="first")

    print(
        f"[Sample] {table_name}: {len(beginning_df)} beginning + {len(end_df)} end + {len(random_df)} random = {len(combined)} total"
    )

    return combined


def compare_snapshot_to_rebuilt(
    engine,
    snapshot_name: str,
    rebuilt_table: str,
    asset_ids: list[int] | None,
    sample_config: dict,
) -> ComparisonSummary:
    """
    Compare snapshot to rebuilt table using sampling and epsilon tolerance.

    Args:
        engine: SQLAlchemy engine
        snapshot_name: Snapshot table name (schema.table_snapshot_YYYYMMDD_HHMMSS)
        rebuilt_table: Rebuilt table name (schema.table)
        asset_ids: List of asset IDs to compare (None = all)
        sample_config: Sampling configuration dict

    Returns:
        ComparisonSummary with pass/fail and statistics
    """
    print(f"\n[Compare] {rebuilt_table}")
    print(f"  Snapshot: {snapshot_name}")

    # Determine table type and columns
    if "bar" in rebuilt_table.lower():
        key_columns = BAR_KEY_COLUMNS
        float_columns = BAR_FLOAT_COLUMNS
    else:  # EMA tables
        key_columns = EMA_KEY_COLUMNS
        float_columns = EMA_FLOAT_COLUMNS

    # Sample both tables
    snapshot_sample = sample_table_for_comparison(
        engine,
        snapshot_name,
        asset_ids,
        beginning_days=sample_config.get("beginning_days", 30),
        end_days=sample_config.get("end_days", 30),
        random_sample_pct=sample_config.get("random_sample_pct", 0.05),
    )

    rebuilt_sample = sample_table_for_comparison(
        engine,
        rebuilt_table,
        asset_ids,
        beginning_days=sample_config.get("beginning_days", 30),
        end_days=sample_config.get("end_days", 30),
        random_sample_pct=sample_config.get("random_sample_pct", 0.05),
    )

    # Compare using hybrid tolerance
    result = compare_tables(
        snapshot_sample,
        rebuilt_sample,
        key_columns=key_columns,
        float_columns=float_columns,
        column_tolerances=COLUMN_TOLERANCES,
    )

    # Print summary
    print(f"  Match rate: {result.summary['match_rate']:.2%}")
    print(f"  Mismatches: {result.summary['mismatch_count']}")
    print(f"  Severity: {result.summary['severity']}")

    if not result.passed:
        print(f"  Max diff: {result.summary['max_diff']:.6e}")
        print(f"  Mean diff: {result.summary['mean_diff']:.6e}")

    return ComparisonSummary(
        table_name=rebuilt_table,
        passed=result.passed,
        match_rate=result.summary["match_rate"],
        mismatch_count=result.summary["mismatch_count"],
        max_diff=result.summary["max_diff"],
        mean_diff=result.summary["mean_diff"],
        severity=result.summary["severity"],
    )


def compare_all_tables(
    engine,
    snapshots: list[SnapshotInfo],
    asset_ids: list[int] | None,
    sample_config: dict,
) -> list[ComparisonSummary]:
    """
    Compare all snapshots to rebuilt tables.

    Args:
        engine: SQLAlchemy engine
        snapshots: List of SnapshotInfo objects
        asset_ids: List of asset IDs to compare (None = all)
        sample_config: Sampling configuration dict

    Returns:
        List of ComparisonSummary objects
    """
    print(f"\n{'=' * 70}")
    print("PHASE 4: COMPARING SNAPSHOTS TO REBUILT TABLES")
    print(f"{'=' * 70}")
    print(f"Tables to compare: {len(snapshots)}")
    print(f"Sample config: {sample_config}")

    summaries = []

    for snapshot in snapshots:
        if not snapshot.created:
            print(f"\n[SKIP] {snapshot.table_name} - snapshot was not created")
            continue

        summary = compare_snapshot_to_rebuilt(
            engine,
            snapshot.snapshot_name,
            snapshot.table_name,
            asset_ids,
            sample_config,
        )

        summaries.append(summary)

    return summaries


# =============================================================================
# Phase 5: Generate Report
# =============================================================================


def generate_report(
    summaries: list[ComparisonSummary],
    rebuild_results: list[SubprocessResult],
    output_dir: Path,
    metadata,
) -> bool:
    """
    Generate comprehensive comparison report.

    Args:
        summaries: List of ComparisonSummary objects
        rebuild_results: List of SubprocessResult objects
        output_dir: Output directory for reports
        metadata: BaselineMetadata object

    Returns:
        True if all comparisons passed, False otherwise
    """
    print(f"\n{'=' * 70}")
    print("PHASE 5: GENERATING REPORT")
    print(f"{'=' * 70}")

    # Overall pass/fail
    all_passed = all(s.passed for s in summaries)
    rebuild_success = all(r.success for r in rebuild_results)

    # Create report
    report_lines = [
        "=" * 70,
        "BASELINE CAPTURE REPORT",
        "=" * 70,
        "",
        f"Timestamp: {metadata.capture_timestamp}",
        f"Git commit: {metadata.git_commit_hash}",
        f"Git branch: {metadata.git_branch}",
        f"Git dirty: {metadata.git_is_dirty}",
        "",
        "REBUILD RESULTS",
        "-" * 70,
    ]

    for result in rebuild_results:
        status = "OK" if result.success else "FAILED"
        report_lines.append(
            f"[{status}] {result.component}: {result.duration_sec:.1f}s"
        )
        if not result.success and result.error_message:
            report_lines.append(f"  Error: {result.error_message}")

    report_lines.extend(["", "COMPARISON RESULTS", "-" * 70])

    for summary in summaries:
        status = "PASS" if summary.passed else "FAIL"
        report_lines.append(
            f"[{status}] {summary.table_name} - {summary.match_rate:.2%} match rate ({summary.severity})"
        )
        if not summary.passed:
            report_lines.append(f"  Mismatches: {summary.mismatch_count}")
            report_lines.append(f"  Max diff: {summary.max_diff:.6e}")
            report_lines.append(f"  Mean diff: {summary.mean_diff:.6e}")

    report_lines.extend(["", "OVERALL RESULT", "-" * 70])

    if all_passed and rebuild_success:
        report_lines.append("[PASS] All comparisons passed within tolerance")
    else:
        report_lines.append("[FAIL] Some comparisons failed or rebuild errors occurred")
        if not rebuild_success:
            report_lines.append(
                "  Rebuild failures detected - comparison may be incomplete"
            )
        if not all_passed:
            failed_count = sum(1 for s in summaries if not s.passed)
            report_lines.append(
                f"  {failed_count}/{len(summaries)} tables failed comparison"
            )

    report_lines.append("=" * 70)

    # Print to console
    print("\n".join(report_lines))

    # Save to file
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"baseline-capture-{metadata.capture_timestamp}.txt"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(f"\n[OK] Report saved to: {report_path}")

    return all_passed and rebuild_success


# =============================================================================
# Main Entry Point
# =============================================================================


def parse_ids(ids_arg: str, engine) -> list[int] | None:
    """
    Parse IDs argument.

    Args:
        ids_arg: Comma-separated IDs or "all"
        engine: SQLAlchemy engine for querying dim_assets

    Returns:
        List of integer IDs or None for "all"
    """
    if ids_arg.lower() == "all":
        # Query dim_assets for all IDs
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT DISTINCT id FROM public.dim_assets ORDER BY id")
            )
            ids = [row[0] for row in result]
        print(f"[Info] Resolved 'all' to {len(ids)} IDs from dim_assets")
        return ids
    else:
        # Parse comma-separated list
        return [int(x.strip()) for x in ids_arg.split(",")]


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Baseline capture orchestration for bar/EMA validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full workflow for specific IDs
  python capture_baseline.py --ids 1,52,825

  # Full workflow for all IDs
  python capture_baseline.py --ids all

  # Dry run to see commands
  python capture_baseline.py --ids 1 --dry-run

  # Skip rebuild, only snapshot + compare
  python capture_baseline.py --ids all --skip-rebuild

  # Verbose output from subprocesses
  python capture_baseline.py --ids all --verbose

  # Custom sampling parameters
  python capture_baseline.py --ids all --sample-beginning 60 --sample-end 60 --sample-random-pct 0.10
        """,
    )

    p.add_argument(
        "--ids",
        required=True,
        help='Comma-separated IDs or "all"',
    )
    p.add_argument(
        "--db-url",
        help="Database URL (default: from TARGET_DB_URL env var)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show commands without executing",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show subprocess output",
    )
    p.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Only snapshot + compare (don't truncate/rebuild)",
    )
    p.add_argument(
        "--output-dir",
        default=".logs/baseline",
        help="Output directory for logs/reports (default: .logs/baseline)",
    )
    p.add_argument(
        "--sample-beginning",
        type=int,
        default=30,
        help="Days to sample from beginning (default: 30)",
    )
    p.add_argument(
        "--sample-end",
        type=int,
        default=30,
        help="Days to sample from end (default: 30)",
    )
    p.add_argument(
        "--sample-random-pct",
        type=float,
        default=0.05,
        help="Random sample percentage for interior (default: 0.05)",
    )

    args = p.parse_args(argv)

    # Resolve database URL
    import os

    db_url = args.db_url or os.environ.get("TARGET_DB_URL")
    if not db_url:
        print("[ERROR] --db-url required (or set TARGET_DB_URL env var)")
        return 1

    # Create engine
    engine = create_engine(db_url)

    # Parse IDs
    try:
        asset_ids = parse_ids(args.ids, engine)
    except Exception as e:
        print(f"[ERROR] Failed to parse IDs: {e}")
        return 1

    # Sampling configuration
    sample_config = {
        "beginning_days": args.sample_beginning,
        "end_days": args.sample_end,
        "random_sample_pct": args.sample_random_pct,
    }

    # Generate timestamp suffix
    timestamp_suffix = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Create baseline config for metadata
    config = BaselineConfig(
        assets=asset_ids or [],
        start_date="2010-01-01",  # Full history for rebuild
        end_date=datetime.utcnow().strftime("%Y-%m-%d"),
        bar_scripts=["run_all_bar_builders.py"],
        ema_scripts=["run_all_ema_refreshes.py"],
        db_url=db_url,
        sampling=sample_config,
    )

    # Capture metadata
    try:
        metadata = capture_metadata(config)
    except Exception as e:
        print(f"[WARNING] Failed to capture metadata: {e}")
        # Continue without metadata
        metadata = None

    print(f"\n{'=' * 70}")
    print("BASELINE CAPTURE ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"IDs: {args.ids}")
    print(f"Asset count: {len(asset_ids) if asset_ids else 'all'}")
    print(f"Timestamp suffix: {timestamp_suffix}")
    print(f"Skip rebuild: {args.skip_rebuild}")
    print(f"Dry run: {args.dry_run}")
    print(f"Sampling config: {sample_config}")

    # Phase 1: Create snapshots
    all_tables = BAR_TABLES + EMA_TABLES
    snapshots = create_snapshots(
        engine,
        all_tables,
        timestamp_suffix,
        asset_ids,
        dry_run=args.dry_run,
    )

    # Check if any snapshots failed
    failed_snapshots = [s for s in snapshots if not s.created and not args.dry_run]
    if failed_snapshots:
        print(
            f"\n[WARNING] {len(failed_snapshots)} snapshot(s) failed - continuing anyway"
        )

    # Phase 2 & 3: Truncate and rebuild (unless --skip-rebuild)
    rebuild_results = []

    if not args.skip_rebuild:
        # Phase 2: Truncate
        truncate_results = truncate_tables(engine, all_tables, dry_run=args.dry_run)

        failed_truncates = [
            t
            for t, success in truncate_results.items()
            if not success and not args.dry_run
        ]
        if failed_truncates:
            print(
                f"\n[WARNING] {len(failed_truncates)} truncate(s) failed - continuing anyway"
            )

        # Phase 3: Rebuild
        bar_result = run_bar_builders(args.ids, db_url, args.verbose, args.dry_run)
        rebuild_results.append(bar_result)

        ema_result = run_ema_refreshers(args.ids, db_url, args.verbose, args.dry_run)
        rebuild_results.append(ema_result)

    else:
        print("\n[SKIP] Truncate and rebuild skipped (--skip-rebuild)")

    # Phase 4: Compare
    if not args.dry_run:
        comparison_summaries = compare_all_tables(
            engine, snapshots, asset_ids, sample_config
        )
    else:
        print("\n[DRY RUN] Would compare snapshots to rebuilt tables")
        comparison_summaries = []

    # Phase 5: Generate report
    if not args.dry_run and metadata:
        output_dir = Path(args.output_dir)
        all_passed = generate_report(
            comparison_summaries, rebuild_results, output_dir, metadata
        )

        # Save metadata
        metadata_path = output_dir / f"metadata-{timestamp_suffix}.json"
        save_metadata(metadata, metadata_path)
        print(f"[OK] Metadata saved to: {metadata_path}")

        return 0 if all_passed else 1
    elif args.dry_run:
        print("\n[DRY RUN] Would generate report and save metadata")
        return 0
    else:
        print("\n[WARNING] No metadata available - skipping report generation")
        return 0


if __name__ == "__main__":
    sys.exit(main())
