#!/usr/bin/env python
"""
Unified daily refresh orchestration script.

Coordinates VM data syncs, bars, EMAs, AMAs, desc_stats, macro features,
macro regimes, per-asset regimes, signals, executor, drift monitor, and
stats with state-based checking and clear visibility.

Usage:
    # Full daily refresh (sync VMs then bars then EMAs then AMAs then desc_stats then macro then regimes then signals then executor then stats)
    python run_daily_refresh.py --all --ids 1,52,825

    # Sync VMs only (FRED + Hyperliquid)
    python run_daily_refresh.py --sync-vms

    # Full refresh without VM sync
    python run_daily_refresh.py --all --no-sync-vms --ids all

    # Bars only
    python run_daily_refresh.py --bars --ids all

    # EMAs only (with bar freshness check)
    python run_daily_refresh.py --emas --ids all

    # AMAs only
    python run_daily_refresh.py --amas --ids all

    # Desc stats only (asset stats + correlation)
    python run_daily_refresh.py --desc-stats --ids all

    # FRED macro features only
    python run_daily_refresh.py --macro

    # Regimes only
    python run_daily_refresh.py --regimes --ids all

    # Signal generation only
    python run_daily_refresh.py --signals

    # Paper executor only
    python run_daily_refresh.py --execute

    # Drift monitor only (requires --paper-start)
    python run_daily_refresh.py --drift --paper-start 2025-01-01

    # Stats only
    python run_daily_refresh.py --stats

    # Weekly QC digest
    python run_daily_refresh.py --weekly-digest

    # Full pipeline without executor
    python run_daily_refresh.py --all --no-execute

    # Full pipeline with drift monitoring (--paper-start enables drift stage)
    python run_daily_refresh.py --all --paper-start 2025-01-01

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

from ta_lab2.scripts.alembic_utils import check_migration_status
from ta_lab2.scripts.refresh_utils import (
    get_fresh_ids,
    parse_ids,
    resolve_db_url,
)

# Timeout tiers (seconds); initial estimate, tune after observing actual runtimes
TIMEOUT_BARS = 7200  # 2 hours -- bar builders can be slow for full rebuilds
TIMEOUT_EMAS = 3600  # 1 hour -- EMA refreshers
TIMEOUT_AMAS = 3600  # 1 hour -- AMA refreshers
TIMEOUT_DESC_STATS = 3600  # 1 hour -- asset stats + correlation computation
TIMEOUT_REGIMES = 1800  # 30 minutes -- regime refresher
TIMEOUT_FEATURES = 1800  # 30 minutes -- feature refresh for all assets at 1D
TIMEOUT_SIGNALS = 1800  # 30 minutes -- signal generation for all types
TIMEOUT_CALIBRATE_STOPS = (
    300  # 5 minutes -- iterates over asset x strategy combos, mostly SQL reads
)
TIMEOUT_PORTFOLIO = 600  # 10 minutes -- portfolio optimizer runs all three methods
TIMEOUT_EXECUTOR = (
    300  # 5 minutes -- daily executor is fast (2 strategies, ~100 assets)
)
TIMEOUT_STATS = 3600  # 1 hour -- stats runners scan large tables
TIMEOUT_EXCHANGE_PRICES = 120  # 2 minutes -- live price fetches from exchanges
TIMEOUT_DRIFT = 600  # 10 minutes -- drift runs replays which involve backtest execution
TIMEOUT_MACRO = 300  # 5 minutes -- small FRED dataset, fast computation
TIMEOUT_MACRO_REGIMES = (
    300  # 5 minutes -- 4-dimension classification over FRED features
)
TIMEOUT_MACRO_ANALYTICS = (
    900  # 15 minutes -- HMM fitting can be slow (10 restarts x 2-3 state models)
)
TIMEOUT_CROSS_ASSET_AGG = (
    600  # 10 minutes -- rolling correlations across all assets + funding z-scores
)
TIMEOUT_MACRO_GATES = 120  # 2 minutes -- gate evaluation against FRED features
TIMEOUT_MACRO_ALERTS = 60  # 1 minute -- transition detection + Telegram send
TIMEOUT_GARCH = 1800  # 30 minutes -- GARCH fitting for 99 assets x 4 models
TIMEOUT_SYNC_FRED = 300  # 5 minutes -- SSH + psql COPY from GCP VM
TIMEOUT_SYNC_HL = 600  # 10 minutes -- SSH + psql COPY from Singapore VM (~3M rows)
TIMEOUT_SIGNAL_GATE = 120  # 2 minutes -- signal count queries are fast
TIMEOUT_IC_STALENESS = 300  # 5 minutes -- IC computation for ~10 features x 2 assets
TIMEOUT_PIPELINE_ALERT = 60  # 1 minute -- Telegram send only

# Canonical pipeline stage ordering -- used by --from-stage to skip prior stages.
# New Phase 87 stages: signal_validation_gate, ic_staleness_check, pipeline_alerts.
STAGE_ORDER = [
    "sync_vms",
    "bars",
    "emas",
    "amas",
    "desc_stats",
    "macro_features",
    "macro_regimes",
    "macro_analytics",
    "cross_asset_agg",
    "macro_gates",
    "macro_alerts",
    "regimes",
    "features",
    "garch",
    "signals",
    "signal_validation_gate",  # Phase 87
    "ic_staleness_check",  # Phase 87
    "calibrate_stops",
    "portfolio",
    "executor",
    "drift_monitor",
    "pipeline_alerts",  # Phase 87
    "stats",
]


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

    # Source filtering: skip builders that don't match --source
    source = getattr(args, "source", "all")
    if source == "cmc":
        cmd.extend(["--skip", "1d_tvc,1d_hl"])
    elif source == "tvc":
        cmd.extend(["--skip", "1d_cmc,1d_hl"])
    elif source == "hl":
        cmd.extend(["--skip", "1d_cmc,1d_tvc"])

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
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_BARS)
        else:
            # Capture output
            result = subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=TIMEOUT_BARS
            )

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

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_BARS}s"
        print(f"\n[TIMEOUT] Bar builders: {error_msg}")
        return ComponentResult(
            component="bars",
            success=False,
            duration_sec=duration,
            returncode=-1,
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
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_EMAS)
        else:
            # Capture output
            result = subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=TIMEOUT_EMAS
            )

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

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_EMAS}s"
        print(f"\n[TIMEOUT] EMA refreshers: {error_msg}")
        return ComponentResult(
            component="emas",
            success=False,
            duration_sec=duration,
            returncode=-1,
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


def run_ama_refreshers(
    args, db_url: str, ids_for_amas: list[int] | None
) -> ComponentResult:
    """
    Run AMA orchestrator via subprocess.

    AMAs run after EMAs complete (DEMA/TEMA are compositional EMAs that may
    reference EMA values) and before regimes (which could incorporate
    AMA-based features in future phases).

    Args:
        args: CLI arguments
        db_url: Database URL
        ids_for_amas: Filtered ID list or None for "all"

    Returns:
        ComponentResult with execution details
    """
    script_dir = Path(__file__).parent / "amas"
    cmd = [sys.executable, str(script_dir / "run_all_ama_refreshes.py")]

    # Format IDs for AMA subprocess
    if ids_for_amas is None:
        ids_str = "all"
    elif len(ids_for_amas) == 0:
        print("[INFO] No IDs - skipping AMA refresh")
        return ComponentResult(
            component="amas",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )
    else:
        ids_str = ",".join(str(i) for i in ids_for_amas)

    cmd.extend(["--ids", ids_str])

    # AMAs always run all TFs in daily refresh
    cmd.append("--all-tfs")

    if args.verbose:
        cmd.append("--verbose")
    if args.num_processes:
        cmd.extend(["--num-processes", str(args.num_processes)])
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING AMA REFRESHERS")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute AMA refreshers")
        return ComponentResult(
            component="amas",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_AMAS)
        else:
            # Capture output
            result = subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=TIMEOUT_AMAS
            )

            # Show output on error
            if result.returncode != 0:
                print(f"\n[ERROR] AMA refreshers failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] AMA refreshers completed successfully in {duration:.1f}s")
            return ComponentResult(
                component="amas",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] AMA refreshers failed: {error_msg}")
            return ComponentResult(
                component="amas",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_AMAS}s"
        print(f"\n[TIMEOUT] AMA refreshers: {error_msg}")
        return ComponentResult(
            component="amas",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] AMA refreshers raised exception: {error_msg}")
        return ComponentResult(
            component="amas",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_desc_stats_refresher(
    args, db_url: str, parsed_ids: list[int] | None
) -> ComponentResult:
    """
    Run descriptive stats orchestrator via subprocess.

    Desc stats run after AMAs and before regimes, computing per-asset
    descriptive statistics and pairwise rolling correlations.

    Args:
        args: CLI arguments
        db_url: Database URL
        parsed_ids: Parsed ID list or None for "all"

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes",
    ]

    # Format IDs for desc stats subprocess
    if parsed_ids is None:
        ids_str = "all"
    else:
        ids_str = ",".join(str(i) for i in parsed_ids)

    cmd.extend(["--ids", ids_str])
    cmd.extend(["--db-url", db_url])

    if args.verbose:
        cmd.append("--verbose")
    if args.num_processes:
        cmd.extend(["--workers", str(args.num_processes)])
    if args.continue_on_error:
        cmd.append("--continue-on-error")

    # CRITICAL: Propagate --dry-run to subprocess
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING DESC STATS REFRESHER")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute desc stats refresher")
        return ComponentResult(
            component="desc_stats",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_DESC_STATS)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_DESC_STATS,
            )

            # Show output on error
            if result.returncode != 0:
                print(
                    f"\n[ERROR] Desc stats refresher failed with code {result.returncode}"
                )
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(
                f"\n[OK] Desc stats refresher completed successfully in {duration:.1f}s"
            )
            return ComponentResult(
                component="desc_stats",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Desc stats refresher failed: {error_msg}")
            return ComponentResult(
                component="desc_stats",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_DESC_STATS}s"
        print(f"\n[TIMEOUT] Desc stats refresher: {error_msg}")
        return ComponentResult(
            component="desc_stats",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Desc stats refresher raised exception: {error_msg}")
        return ComponentResult(
            component="desc_stats",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_regime_refresher(
    args, db_url: str, parsed_ids: list[int] | None
) -> ComponentResult:
    """
    Run regime refresher via subprocess.

    Args:
        args: CLI arguments
        db_url: Database URL
        parsed_ids: Parsed ID list or None for "all"

    Returns:
        ComponentResult with execution details
    """
    script_dir = Path(__file__).parent / "regimes"
    cmd = [sys.executable, str(script_dir / "refresh_regimes.py")]

    # Format IDs for regime subprocess
    if parsed_ids is None:
        cmd.append("--all")
    else:
        cmd.extend(["--ids", ",".join(str(i) for i in parsed_ids)])

    cmd.extend(["--db-url", db_url])

    if args.verbose:
        cmd.append("--verbose")
    if getattr(args, "no_regime_hysteresis", False):
        cmd.append("--no-hysteresis")
    if getattr(args, "no_desc_stats_in_regimes", False):
        cmd.append("--no-desc-stats")

    # CRITICAL: Propagate --dry-run to subprocess
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING REGIME REFRESHER")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute regime refresher")
        return ComponentResult(
            component="regimes",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_REGIMES)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_REGIMES,
            )

            # Show output on error
            if result.returncode != 0:
                print(
                    f"\n[ERROR] Regime refresher failed with code {result.returncode}"
                )
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Regime refresher completed successfully in {duration:.1f}s")
            return ComponentResult(
                component="regimes",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Regime refresher failed: {error_msg}")
            return ComponentResult(
                component="regimes",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_REGIMES}s"
        print(f"\n[TIMEOUT] Regime refresher: {error_msg}")
        return ComponentResult(
            component="regimes",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Regime refresher raised exception: {error_msg}")
        return ComponentResult(
            component="regimes",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_feature_refresh_stage(args, db_url: str) -> ComponentResult:
    """
    Run features refresh via subprocess.

    Refreshes all feature columns in features for the 1D timeframe.
    Runs after regimes and before signals in the full pipeline.

    Args:
        args: CLI arguments
        db_url: Database URL (accepted for interface consistency but NOT passed to
                the subprocess, which reads TARGET_DB_URL from the environment).

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.features.run_all_feature_refreshes",
        "--all",
        "--tf",
        "1D",
    ]

    print(f"\n{'=' * 70}")
    print("RUNNING FEATURE REFRESH (features)")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would run feature refresh")
        return ComponentResult(
            component="features",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if getattr(args, "verbose", False):
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_FEATURES)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_FEATURES,
            )

            if result.returncode != 0:
                print(f"\n[ERROR] Feature refresh failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout[-2000:]}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr[-2000:]}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Feature refresh completed successfully in {duration:.1f}s")
            return ComponentResult(
                component="features",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Feature refresh failed: {error_msg}")
            return ComponentResult(
                component="features",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_FEATURES}s"
        print(f"\n[TIMEOUT] Feature refresh: {error_msg}")
        return ComponentResult(
            component="features",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Feature refresh raised exception: {error_msg}")
        return ComponentResult(
            component="features",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_garch_forecasts(args, db_url: str) -> ComponentResult:
    """
    Run GARCH conditional volatility forecast refresh via subprocess.

    Fits GARCH/GJR-GARCH/EGARCH/FIGARCH models per asset and writes forecasts
    to garch_forecasts table.  Runs after features and before signals.

    Args:
        args: CLI arguments
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    script_dir = Path(__file__).parent / "garch"
    cmd = [sys.executable, str(script_dir / "refresh_garch_forecasts.py")]

    # Pass through IDs and DB URL
    cmd.extend(["--ids", getattr(args, "ids", "all")])
    cmd.extend(["--db-url", db_url])

    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print("RUNNING GARCH FORECAST REFRESH")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would run GARCH forecast refresh")
        return ComponentResult(
            component="garch",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if getattr(args, "verbose", False):
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_GARCH)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_GARCH,
            )

            if result.returncode != 0:
                print(
                    f"\n[ERROR] GARCH forecast refresh failed with code {result.returncode}"
                )
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout[-2000:]}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr[-2000:]}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(
                f"\n[OK] GARCH forecast refresh completed successfully in {duration:.1f}s"
            )
            return ComponentResult(
                component="garch",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] GARCH forecast refresh failed: {error_msg}")
            return ComponentResult(
                component="garch",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_GARCH}s"
        print(f"\n[TIMEOUT] GARCH forecast refresh: {error_msg}")
        return ComponentResult(
            component="garch",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] GARCH forecast refresh raised exception: {error_msg}")
        return ComponentResult(
            component="garch",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_signal_refreshes(args, db_url: str) -> ComponentResult:
    """
    Run signal generation via subprocess.

    Generates EMA crossover, RSI, and ATR breakout signals for all assets.
    Runs after regimes (regime-aware signal generation) and before the executor.

    Args:
        args: CLI arguments
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.signals.run_all_signal_refreshes",
    ]

    print(f"\n{'=' * 70}")
    print("RUNNING SIGNAL GENERATION")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would run signal generation")
        return ComponentResult(
            component="signals",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if getattr(args, "verbose", False):
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_SIGNALS)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SIGNALS,
            )

            if result.returncode != 0:
                print(f"\n[ERROR] Signal generation failed (code {result.returncode})")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout[-2000:]}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr[-2000:]}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Signal generation completed in {duration:.1f}s")
            return ComponentResult(
                component="signals",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Signal generation failed: {error_msg}")
            return ComponentResult(
                component="signals",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_SIGNALS}s"
        print(f"\n[TIMEOUT] Signal generation: {error_msg}")
        return ComponentResult(
            component="signals",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Signal generation raised exception: {error_msg}")
        return ComponentResult(
            component="signals",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_calibrate_stops_stage(args, db_url: str) -> ComponentResult:
    """
    Run stop calibration via subprocess.

    Iterates over asset x strategy combinations and writes per-asset calibrated
    stop/take-profit ladders to stop_calibrations.  Runs after signals and
    before the portfolio refresh in the full pipeline.  Non-fatal: failure logs
    a warning and the pipeline continues to portfolio refresh.

    Args:
        args: CLI arguments
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.portfolio.calibrate_stops",
        "--ids",
        "all",
    ]
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print("RUNNING STOP CALIBRATION")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would execute stop calibration")
        return ComponentResult(
            component="calibrate_stops",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start_t = time.perf_counter()

    try:
        if getattr(args, "verbose", False):
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_CALIBRATE_STOPS)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_CALIBRATE_STOPS,
            )

            if result.returncode != 0:
                print(f"\n[ERROR] Stop calibration failed (code {result.returncode})")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout[-2000:]}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr[-2000:]}")

        duration = time.perf_counter() - start_t

        if result.returncode == 0:
            print(f"\n[OK] Stop calibration completed in {duration:.1f}s")
            return ComponentResult(
                component="calibrate_stops",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Stop calibration failed: {error_msg}")
            return ComponentResult(
                component="calibrate_stops",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start_t
        error_msg = f"Timed out after {TIMEOUT_CALIBRATE_STOPS}s"
        print(f"\n[TIMEOUT] Stop calibration: {error_msg}")
        return ComponentResult(
            component="calibrate_stops",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start_t
        error_msg = str(e)
        print(f"\n[ERROR] Stop calibration raised exception: {error_msg}")
        return ComponentResult(
            component="calibrate_stops",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_portfolio_refresh_stage(args, db_url: str) -> ComponentResult:
    """
    Run portfolio allocation refresh via subprocess.

    Runs PortfolioOptimizer (MV/CVaR/HRP) + optional BL + optional bet sizing
    and persists results to portfolio_allocations.  Runs after signals and
    before the paper executor in the full pipeline.

    Args:
        args: CLI arguments
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.portfolio.refresh_portfolio_allocations",
        "--db-url",
        db_url,
    ]
    if getattr(args, "verbose", False):
        cmd.append("--verbose")
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING PORTFOLIO ALLOCATION REFRESH")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would execute portfolio allocation refresh")
        return ComponentResult(
            component="portfolio",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start_t = time.perf_counter()

    try:
        if getattr(args, "verbose", False):
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_PORTFOLIO)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_PORTFOLIO,
            )

            if result.returncode != 0:
                print(f"\n[ERROR] Portfolio refresh failed (code {result.returncode})")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout[-2000:]}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr[-2000:]}")

        duration = time.perf_counter() - start_t

        if result.returncode == 0:
            print(f"\n[OK] Portfolio allocation refresh completed in {duration:.1f}s")
            return ComponentResult(
                component="portfolio",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Portfolio allocation refresh failed: {error_msg}")
            return ComponentResult(
                component="portfolio",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start_t
        error_msg = f"Timed out after {TIMEOUT_PORTFOLIO}s"
        print(f"\n[TIMEOUT] Portfolio allocation refresh: {error_msg}")
        return ComponentResult(
            component="portfolio",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start_t
        error_msg = str(e)
        print(f"\n[ERROR] Portfolio allocation refresh raised exception: {error_msg}")
        return ComponentResult(
            component="portfolio",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_paper_executor_stage(args, db_url: str) -> ComponentResult:
    """
    Run paper executor via subprocess.

    Processes new signals into paper orders and simulates fills for all active
    strategies in dim_executor_config. Runs after signals and before stats.

    Args:
        args: CLI arguments
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.executor.run_paper_executor",
        "--db-url",
        db_url,
    ]
    if getattr(args, "verbose", False):
        cmd.append("--verbose")
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING PAPER EXECUTOR")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would execute paper executor")
        return ComponentResult(
            component="executor",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if getattr(args, "verbose", False):
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_EXECUTOR)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_EXECUTOR,
            )

            if result.returncode != 0:
                print(f"\n[ERROR] Paper executor failed (code {result.returncode})")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout[-2000:]}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr[-2000:]}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Paper executor completed in {duration:.1f}s")
            return ComponentResult(
                component="executor",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Paper executor failed: {error_msg}")
            return ComponentResult(
                component="executor",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_EXECUTOR}s"
        print(f"\n[TIMEOUT] Paper executor: {error_msg}")
        return ComponentResult(
            component="executor",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Paper executor raised exception: {error_msg}")
        return ComponentResult(
            component="executor",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_drift_monitor_stage(args, db_url: str) -> ComponentResult:
    """
    Run drift monitor via subprocess.

    Runs parallel backtest replay and computes drift metrics for all active
    paper trading strategies. Activates drift pause when thresholds are breached.
    Runs after executor stage and before stats stage.

    Args:
        args: CLI arguments (must have args.paper_start)
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.drift.run_drift_monitor",
        "--paper-start",
        args.paper_start,
        "--db-url",
        db_url,
    ]
    if getattr(args, "verbose", False):
        cmd.append("--verbose")
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING DRIFT MONITOR")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would execute drift monitor")
        return ComponentResult(
            component="drift_monitor",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if getattr(args, "verbose", False):
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_DRIFT)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_DRIFT,
            )

            if result.returncode != 0:
                print(f"\n[ERROR] Drift monitor failed (code {result.returncode})")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout[-2000:]}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr[-2000:]}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Drift monitor completed in {duration:.1f}s")
            return ComponentResult(
                component="drift_monitor",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Drift monitor failed: {error_msg}")
            return ComponentResult(
                component="drift_monitor",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_DRIFT}s"
        print(f"\n[TIMEOUT] Drift monitor: {error_msg}")
        return ComponentResult(
            component="drift_monitor",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Drift monitor raised exception: {error_msg}")
        return ComponentResult(
            component="drift_monitor",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_stats_runners(args, db_url: str) -> ComponentResult:
    """
    Run stats runner orchestrator via subprocess.

    Stats runners query aggregate PASS/WARN/FAIL status from DB after all 6
    runners complete. The subprocess exits 1 on FAIL (data quality failure)
    and 0 on PASS or WARN (pipeline continues for WARN, Telegram alert sent).

    Args:
        args: CLI arguments
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.stats.run_all_stats_runners",
    ]

    cmd.extend(["--db-url", db_url])

    if args.verbose:
        cmd.append("--verbose")

    # CRITICAL: Propagate --dry-run to subprocess
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING STATS RUNNERS")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute stats runners")
        return ComponentResult(
            component="stats",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_STATS)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_STATS,
            )

            # Show output on error
            if result.returncode != 0:
                print(f"\n[ERROR] Stats runners failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Stats runners completed successfully in {duration:.1f}s")
            return ComponentResult(
                component="stats",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Stats runners failed: {error_msg}")
            return ComponentResult(
                component="stats",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_STATS}s"
        print(f"\n[TIMEOUT] Stats runners: {error_msg}")
        return ComponentResult(
            component="stats",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Stats runners raised exception: {error_msg}")
        return ComponentResult(
            component="stats",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_exchange_prices(args, db_url: str) -> ComponentResult:
    """
    Run the exchange price feed refresh via subprocess.

    Fetches live spot prices from Coinbase and Kraken for BTC/USD and ETH/USD,
    compares against the most recent daily bar close, and writes snapshots to
    exchange_price_feed. WARNING is logged when discrepancy exceeds the adaptive
    threshold derived from asset_stats.

    This component is NOT included in --all. Invoke explicitly with
    --exchange-prices.

    Args:
        args: CLI arguments
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.exchange.refresh_exchange_price_feed",
    ]

    cmd.extend(["--db-url", db_url])

    if args.verbose:
        cmd.append("--verbose")

    # Propagate --dry-run so no DB writes occur during verification
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING EXCHANGE PRICE FEED")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute exchange price feed refresh")
        return ComponentResult(
            component="exchange_prices",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_EXCHANGE_PRICES)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_EXCHANGE_PRICES,
            )

            # Always show output (price feed is informational)
            if result.stdout:
                print(result.stdout)
            if result.returncode != 0 and result.stderr:
                print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Exchange price feed completed in {duration:.1f}s")
            return ComponentResult(
                component="exchange_prices",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Exchange price feed failed: {error_msg}")
            return ComponentResult(
                component="exchange_prices",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_EXCHANGE_PRICES}s"
        print(f"\n[TIMEOUT] Exchange price feed: {error_msg}")
        return ComponentResult(
            component="exchange_prices",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Exchange price feed raised exception: {error_msg}")
        return ComponentResult(
            component="exchange_prices",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_weekly_digest(args, db_url: str) -> ComponentResult:
    """
    Run the weekly QC digest as a standalone subprocess.

    The digest aggregates PASS/WARN/FAIL counts across all stats tables with
    week-over-week delta comparison and delivers via Telegram if configured.

    This is a reporting operation only -- it does NOT run pipeline stages
    (bars, EMAs, regimes, stats) and is NOT included in --all.

    Args:
        args: CLI arguments (checked for dry_run, verbose, no_telegram)
        db_url: Database URL

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.stats.weekly_digest",
    ]

    cmd.extend(["--db-url", db_url])

    if args.verbose:
        cmd.append("--verbose")

    # Propagate --no-telegram if caller passed it
    if getattr(args, "no_telegram", False):
        cmd.append("--no-telegram")

    # CRITICAL: Propagate --dry-run to subprocess so no live DB connection is
    # attempted during verification (matches pattern in run_regime_refresher)
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("RUNNING WEEKLY QC DIGEST")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute weekly digest")
        return ComponentResult(
            component="weekly_digest",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_STATS)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_STATS,
            )

            # Show output (digest is informational -- always print stdout)
            if result.stdout:
                print(result.stdout)
            if result.returncode != 0 and result.stderr:
                print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Weekly digest completed in {duration:.1f}s")
            return ComponentResult(
                component="weekly_digest",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Weekly digest failed: {error_msg}")
            return ComponentResult(
                component="weekly_digest",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_STATS}s"
        print(f"\n[TIMEOUT] Weekly digest: {error_msg}")
        return ComponentResult(
            component="weekly_digest",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Weekly digest raised exception: {error_msg}")
        return ComponentResult(
            component="weekly_digest",
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


def run_sync_fred_vm(args) -> ComponentResult:
    """Sync FRED data from GCP VM to local fred.* schema.

    Runs incremental sync via SSH + psql COPY. Should run before macro
    features so downstream computations use the latest FRED data.

    Args:
        args: CLI arguments

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.etl.sync_fred_from_vm",
    ]

    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("SYNCING FRED DATA FROM GCP VM")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would sync FRED data from GCP VM")
        return ComponentResult(
            component="sync_fred_vm",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_SYNC_FRED)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SYNC_FRED,
            )
            if result.returncode != 0:
                print(f"\n[ERROR] FRED VM sync failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] FRED VM sync completed in {duration:.1f}s")
            return ComponentResult(
                component="sync_fred_vm",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] FRED VM sync: {error_msg}")
            return ComponentResult(
                component="sync_fred_vm",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_SYNC_FRED}s"
        print(f"\n[TIMEOUT] FRED VM sync: {error_msg}")
        return ComponentResult(
            component="sync_fred_vm",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_sync_hl_vm(args) -> ComponentResult:
    """Sync Hyperliquid data from Singapore VM to local hyperliquid.* schema.

    Runs incremental sync of all tables (assets, candles, funding, OI)
    via SSH + psql COPY. Should run before bars so downstream steps
    have fresh perps data.

    Args:
        args: CLI arguments

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.etl.sync_hl_from_vm",
    ]

    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    print(f"\n{'=' * 70}")
    print("SYNCING HYPERLIQUID DATA FROM SINGAPORE VM")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would sync Hyperliquid data from Singapore VM")
        return ComponentResult(
            component="sync_hl_vm",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_SYNC_HL)
        else:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SYNC_HL,
            )
            if result.returncode != 0:
                print(
                    f"\n[ERROR] Hyperliquid VM sync failed with code {result.returncode}"
                )
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Hyperliquid VM sync completed in {duration:.1f}s")
            return ComponentResult(
                component="sync_hl_vm",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Hyperliquid VM sync: {error_msg}")
            return ComponentResult(
                component="sync_hl_vm",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_SYNC_HL}s"
        print(f"\n[TIMEOUT] Hyperliquid VM sync: {error_msg}")
        return ComponentResult(
            component="sync_hl_vm",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_macro_features(args) -> ComponentResult:
    """Run FRED macro feature refresh via subprocess.

    Macro features are computed from fred.series_values (populated by
    sync_fred_from_vm.py) and upserted into fred.fred_macro_features.
    This stage runs after desc_stats and before regimes so that downstream
    regime classifiers (Phase 67 L4) can read macro context.

    Args:
        args: CLI arguments

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.macro.refresh_macro_features",
    ]

    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print("RUNNING MACRO FEATURES (FRED)")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute FRED macro feature refresh")
        return ComponentResult(
            component="macro_features",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_MACRO)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_MACRO,
            )

            # Show output on error
            if result.returncode != 0:
                print(
                    f"\n[ERROR] Macro feature refresh failed with code {result.returncode}"
                )
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(
                f"\n[OK] Macro feature refresh completed successfully in {duration:.1f}s"
            )
            return ComponentResult(
                component="macro_features",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Macro feature refresh failed: {error_msg}")
            return ComponentResult(
                component="macro_features",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_MACRO}s"
        print(f"\n[TIMEOUT] Macro feature refresh: {error_msg}")
        return ComponentResult(
            component="macro_features",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Macro feature refresh raised exception: {error_msg}")
        return ComponentResult(
            component="macro_features",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_macro_regimes(args) -> ComponentResult:
    """Run macro regime classification via subprocess.

    Classifies daily macro features into 4-dimensional regime labels
    (monetary_policy, liquidity, risk_appetite, carry) with hysteresis
    and upserts results into macro_regimes.

    This stage runs after macro_features and before per-asset regimes
    so that downstream pipeline stages can read the global macro context.

    Args:
        args: CLI arguments

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.macro.refresh_macro_regimes",
    ]

    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    # Propagate profile override if specified
    macro_regime_profile = getattr(args, "macro_regime_profile", None)
    if macro_regime_profile:
        cmd.extend(["--profile", macro_regime_profile])

    print(f"\n{'=' * 70}")
    print("RUNNING MACRO REGIME CLASSIFICATION")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute macro regime classification")
        return ComponentResult(
            component="macro_regimes",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_MACRO_REGIMES)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_MACRO_REGIMES,
            )

            # Show output on error
            if result.returncode != 0:
                print(
                    f"\n[ERROR] Macro regime classification failed with code {result.returncode}"
                )
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(
                f"\n[OK] Macro regime classification completed successfully in {duration:.1f}s"
            )
            return ComponentResult(
                component="macro_regimes",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Macro regime classification failed: {error_msg}")
            return ComponentResult(
                component="macro_regimes",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_MACRO_REGIMES}s"
        print(f"\n[TIMEOUT] Macro regime classification: {error_msg}")
        return ComponentResult(
            component="macro_regimes",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Macro regime classification raised exception: {error_msg}")
        return ComponentResult(
            component="macro_regimes",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_macro_analytics(args) -> ComponentResult:
    """Run macro analytics (HMM, lead-lag, transition probs) via subprocess.

    Runs after macro regimes and before per-asset regime refresh.
    Produces secondary analytical signals in hmm_regimes,
    macro_lead_lag_results, and macro_transition_probs.

    Pipeline ordering: macro_features -> macro_regimes -> macro_analytics -> regimes

    Args:
        args: CLI arguments

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.macro.refresh_macro_analytics",
    ]

    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print("RUNNING MACRO ANALYTICS (HMM + Lead-Lag + Transitions)")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute macro analytics")
        return ComponentResult(
            component="macro_analytics",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_MACRO_ANALYTICS)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_MACRO_ANALYTICS,
            )

            # Show output on error
            if result.returncode != 0:
                print(f"\n[ERROR] Macro analytics failed with code {result.returncode}")
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"\n[OK] Macro analytics completed successfully in {duration:.1f}s")
            return ComponentResult(
                component="macro_analytics",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Macro analytics failed: {error_msg}")
            return ComponentResult(
                component="macro_analytics",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_MACRO_ANALYTICS}s"
        print(f"\n[TIMEOUT] Macro analytics: {error_msg}")
        return ComponentResult(
            component="macro_analytics",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Macro analytics raised exception: {error_msg}")
        return ComponentResult(
            component="macro_analytics",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_cross_asset_agg(args) -> ComponentResult:
    """Run cross-asset aggregation (XAGG-01 through XAGG-04) via subprocess.

    Runs after macro analytics and before per-asset regime refresh.
    Produces cross-asset signals in cross_asset_agg, funding_rate_agg,
    and crypto_macro_corr_regimes.

    Pipeline ordering:
        macro_features -> macro_regimes -> macro_analytics
        -> cross_asset_agg -> regimes

    Args:
        args: CLI arguments

    Returns:
        ComponentResult with execution details
    """
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.macro.refresh_cross_asset_agg",
    ]

    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    print(f"\n{'=' * 70}")
    print("RUNNING CROSS-ASSET AGGREGATION (XAGG-01 through XAGG-04)")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would execute cross-asset aggregation")
        return ComponentResult(
            component="cross_asset_agg",
            success=True,
            duration_sec=0.0,
            returncode=0,
        )

    start = time.perf_counter()

    try:
        if args.verbose:
            # Stream output
            result = subprocess.run(cmd, check=False, timeout=TIMEOUT_CROSS_ASSET_AGG)
        else:
            # Capture output
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_CROSS_ASSET_AGG,
            )

            # Show output on error
            if result.returncode != 0:
                print(
                    f"\n[ERROR] Cross-asset aggregation failed with code "
                    f"{result.returncode}"
                )
                if result.stdout:
                    print(f"\nSTDOUT:\n{result.stdout}")
                if result.stderr:
                    print(f"\nSTDERR:\n{result.stderr}")

        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(
                f"\n[OK] Cross-asset aggregation completed successfully in {duration:.1f}s"
            )
            return ComponentResult(
                component="cross_asset_agg",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        else:
            error_msg = f"Exited with code {result.returncode}"
            print(f"\n[FAILED] Cross-asset aggregation failed: {error_msg}")
            return ComponentResult(
                component="cross_asset_agg",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=error_msg,
            )

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_CROSS_ASSET_AGG}s"
        print(f"\n[TIMEOUT] Cross-asset aggregation: {error_msg}")
        return ComponentResult(
            component="cross_asset_agg",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Cross-asset aggregation raised exception: {error_msg}")
        return ComponentResult(
            component="cross_asset_agg",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_evaluate_macro_gates(args) -> ComponentResult:
    """Evaluate macro gates (VIX, carry, credit, FOMC, freshness) and update gate state."""
    print("\n--- Evaluate Macro Gates ---")
    start = time.perf_counter()
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.risk.evaluate_macro_gates",
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_MACRO_GATES,
        )
        duration = time.perf_counter() - start
        if result.returncode == 0:
            print(f"  Macro gates evaluated ({duration:.1f}s)")
        else:
            print(f"  Macro gates: exit code {result.returncode} ({duration:.1f}s)")
            if result.stderr:
                print(f"  stderr: {result.stderr[:500]}")
        return ComponentResult(
            component="macro_gates",
            success=result.returncode in (0, 1),  # 0=normal, 1=reduce (both OK)
            duration_sec=duration,
            returncode=result.returncode,
        )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_MACRO_GATES}s"
        print(f"\n[TIMEOUT] Macro gates: {error_msg}")
        return ComponentResult(
            component="macro_gates",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Macro gates raised exception: {error_msg}")
        return ComponentResult(
            component="macro_gates",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_macro_alerts(args) -> ComponentResult:
    """Check for macro regime transitions and send Telegram alerts."""
    print("\n--- Macro Regime Alerts ---")
    start = time.perf_counter()
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.macro.run_macro_alerts",
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_MACRO_ALERTS,
        )
        duration = time.perf_counter() - start
        if result.returncode == 0:
            print(f"  Macro alerts checked ({duration:.1f}s)")
        else:
            print(f"  Macro alerts: exit code {result.returncode} ({duration:.1f}s)")
        return ComponentResult(
            component="macro_alerts",
            success=result.returncode == 0,
            duration_sec=duration,
            returncode=result.returncode,
        )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_MACRO_ALERTS}s"
        print(f"\n[TIMEOUT] Macro alerts: {error_msg}")
        return ComponentResult(
            component="macro_alerts",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Macro alerts raised exception: {error_msg}")
        return ComponentResult(
            component="macro_alerts",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


# ---------------------------------------------------------------------------
# Phase 87 stage runners: signal_validation_gate, ic_staleness_check,
# run_pipeline_completion_alert
# ---------------------------------------------------------------------------


def run_signal_validation_gate(args, db_url: str) -> ComponentResult:
    """Run the signal anomaly gate via subprocess.

    Returns a failed ComponentResult (success=False) when the gate detects
    anomalies (exit code 2).  The executor stage checks this flag and skips
    execution when blocked.
    """
    print("\n--- Signal Validation Gate ---")
    start = time.perf_counter()
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.signals.validate_signal_anomalies",
        "--db-url",
        db_url,
    ]
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SIGNAL_GATE,
        )
        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"  Signal gate: all signals clean ({duration:.1f}s)")
            return ComponentResult(
                component="signal_validation_gate",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        elif result.returncode == 2:
            print(
                f"  Signal gate: anomalies detected -- executor will be BLOCKED ({duration:.1f}s)"
            )
            return ComponentResult(
                component="signal_validation_gate",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message="Signal anomalies detected",
            )
        else:
            print(f"  Signal gate: exit code {result.returncode} ({duration:.1f}s)")
            return ComponentResult(
                component="signal_validation_gate",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=f"Exited with code {result.returncode}",
            )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_SIGNAL_GATE}s"
        print(f"\n[TIMEOUT] Signal validation gate: {error_msg}")
        return ComponentResult(
            component="signal_validation_gate",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] Signal validation gate raised exception: {error_msg}")
        return ComponentResult(
            component="signal_validation_gate",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_ic_staleness_check_stage(args, db_url: str) -> ComponentResult:
    """Run the IC staleness monitor via subprocess.

    Non-blocking: return code 2 (decay detected) is treated as a warning
    and logged, but the pipeline continues to executor and stats.
    """
    print("\n--- IC Staleness Check ---")
    start = time.perf_counter()
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.analysis.run_ic_staleness_check",
        "--db-url",
        db_url,
    ]
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")
    # Pass --ids if specified (non-default)
    ids_val = getattr(args, "ids", None)
    if ids_val and ids_val != "all":
        cmd.extend(["--ids", ids_val])

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_IC_STALENESS,
        )
        duration = time.perf_counter() - start

        if result.returncode == 0:
            print(f"  IC staleness: no decay detected ({duration:.1f}s)")
            return ComponentResult(
                component="ic_staleness_check",
                success=True,
                duration_sec=duration,
                returncode=result.returncode,
            )
        elif result.returncode == 2:
            print(
                f"  IC staleness: decay detected -- check dim_ic_weight_overrides ({duration:.1f}s)"
            )
            return ComponentResult(
                component="ic_staleness_check",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message="IC decay detected",
            )
        else:
            print(f"  IC staleness: exit code {result.returncode} ({duration:.1f}s)")
            return ComponentResult(
                component="ic_staleness_check",
                success=False,
                duration_sec=duration,
                returncode=result.returncode,
                error_message=f"Exited with code {result.returncode}",
            )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        error_msg = f"Timed out after {TIMEOUT_IC_STALENESS}s"
        print(f"\n[TIMEOUT] IC staleness check: {error_msg}")
        return ComponentResult(
            component="ic_staleness_check",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        print(f"\n[ERROR] IC staleness check raised exception: {error_msg}")
        return ComponentResult(
            component="ic_staleness_check",
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=error_msg,
        )


def run_pipeline_completion_alert(
    args, db_url: str, results: list[tuple[str, ComponentResult]]
) -> ComponentResult:
    """Send a daily pipeline digest alert via Telegram.

    Non-blocking: alert failures are logged but never stop the pipeline.
    Throttled to one alert per 20 hours via pipeline_alert_log.
    """
    start = time.perf_counter()
    _ALERT_TYPE = "pipeline_complete"
    _ALERT_KEY = "daily"
    _COOLDOWN_HOURS = 20

    # Build digest
    successful = [name for name, r in results if r.success]
    failed_items = [(name, r) for name, r in results if not r.success]
    total_duration = sum(r.duration_sec for _, r in results)
    severity = "info" if not failed_items else "warning"

    lines = [
        f"Pipeline complete: {len(successful)}/{len(results)} stages OK",
        f"Total duration: {total_duration:.0f}s",
    ]
    if failed_items:
        lines.append("Failed stages:")
        for name, r in failed_items:
            err = f" ({r.error_message})" if r.error_message else ""
            lines.append(f"  - {name}{err}")
    message = "\n".join(lines)

    if getattr(args, "dry_run", False):
        print(f"\n[DRY RUN] Would send pipeline completion alert ({severity})")
        duration = time.perf_counter() - start
        return ComponentResult(
            component="pipeline_alerts",
            success=True,
            duration_sec=duration,
            returncode=0,
        )

    try:
        # Lazy import to avoid hard dependency when running dry-run / tests
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        from ta_lab2.notifications import telegram

        engine = create_engine(db_url)

        # Check throttle
        throttled = False
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM pipeline_alert_log
                        WHERE alert_type = :atype
                          AND alert_key = :akey
                          AND sent_at > NOW() - (INTERVAL '1 hour' * :hours)
                          AND throttled = FALSE
                        LIMIT 1
                    """),
                    {
                        "atype": _ALERT_TYPE,
                        "akey": _ALERT_KEY,
                        "hours": _COOLDOWN_HOURS,
                    },
                ).fetchone()
                throttled = row is not None
        except (OperationalError, ProgrammingError):
            pass  # Table may not exist yet -- proceed without throttle check

        sent = False
        if not throttled:
            if telegram.is_configured():
                title = "Daily Pipeline Complete"
                try:
                    sent = telegram.send_alert(title, message, severity=severity)
                except Exception as exc:
                    print(f"  [WARN] Telegram send failed: {exc}")
            else:
                print("  [INFO] Telegram not configured -- skipping completion alert")

        # Log to pipeline_alert_log
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO pipeline_alert_log
                            (alert_type, alert_key, severity, message_preview, throttled)
                        VALUES (:atype, :akey, :sev, :preview, :throttled)
                    """),
                    {
                        "atype": _ALERT_TYPE,
                        "akey": _ALERT_KEY,
                        "sev": severity,
                        "preview": message[:500],
                        "throttled": throttled,
                    },
                )
        except (OperationalError, ProgrammingError) as exc:
            print(f"  [WARN] Could not log to pipeline_alert_log: {exc}")

        engine.dispose()

        status = "throttled" if throttled else ("sent" if sent else "skipped")
        duration = time.perf_counter() - start
        print(f"  Pipeline completion alert: {status} ({duration:.1f}s)")
        return ComponentResult(
            component="pipeline_alerts",
            success=True,
            duration_sec=duration,
            returncode=0,
        )

    except Exception as e:
        duration = time.perf_counter() - start
        print(f"\n[WARN] Pipeline completion alert failed (non-blocking): {e}")
        return ComponentResult(
            component="pipeline_alerts",
            success=True,  # Non-blocking -- always succeeds
            duration_sec=duration,
            returncode=0,
        )


# ---------------------------------------------------------------------------
# Phase 87 pipeline_run_log helpers
# ---------------------------------------------------------------------------


def _start_pipeline_run(db_url: str) -> str | None:
    """Insert a pipeline_run_log row with status='running'. Return the UUID run_id.

    Returns None on DB error (table may not exist if migration is pending).
    """
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        engine = create_engine(db_url)
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO pipeline_run_log (status) VALUES ('running') "
                    "RETURNING run_id"
                )
            ).fetchone()
        engine.dispose()
        return str(row[0]) if row else None
    except (OperationalError, ProgrammingError) as exc:
        print(
            f"[WARN] Could not start pipeline_run_log row (migration pending?): {exc}"
        )
        return None
    except Exception as exc:
        print(f"[WARN] pipeline_run_log insert error: {exc}")
        return None


def _complete_pipeline_run(
    db_url: str,
    run_id: str,
    status: str,
    stages: list[str],
    duration: float,
    error_msg: str | None,
) -> None:
    """Update the pipeline_run_log row with completion details."""
    import json

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE pipeline_run_log
                    SET completed_at        = now(),
                        status              = :status,
                        stages_completed    = CAST(:stages AS JSONB),
                        total_duration_sec  = :duration,
                        error_message       = :error
                    WHERE run_id = CAST(:run_id AS UUID)
                """),
                {
                    "run_id": run_id,
                    "status": status,
                    "stages": json.dumps(stages),
                    "duration": duration,
                    "error": error_msg,
                },
            )
        engine.dispose()
    except (OperationalError, ProgrammingError) as exc:
        print(f"[WARN] Could not update pipeline_run_log (migration pending?): {exc}")
    except Exception as exc:
        print(f"[WARN] pipeline_run_log update error: {exc}")


def _check_dead_man(db_url: str) -> bool:
    """Return True if yesterday's pipeline run is MISSING (dead-man should fire).

    Returns False when pipeline_run_log has 0 rows (first run) to avoid
    a false-positive alert on initial deployment.
    """
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        engine = create_engine(db_url)
        with engine.connect() as conn:
            # First, check if table has ANY rows at all
            count_row = conn.execute(
                text("SELECT COUNT(*) FROM pipeline_run_log")
            ).fetchone()
            if count_row and count_row[0] == 0:
                engine.dispose()
                return False  # First ever run -- no false alarm

            # Check if yesterday's run completed
            row = conn.execute(
                text("""
                    SELECT 1
                    FROM pipeline_run_log
                    WHERE DATE(completed_at AT TIME ZONE 'UTC')
                          = CURRENT_DATE - INTERVAL '1 day'
                      AND status = 'complete'
                    LIMIT 1
                """)
            ).fetchone()
        engine.dispose()
        return row is None  # True = no completed run yesterday
    except (OperationalError, ProgrammingError) as exc:
        print(f"[WARN] Could not check pipeline_run_log for dead-man switch: {exc}")
        return False
    except Exception as exc:
        print(f"[WARN] Dead-man switch check error: {exc}")
        return False


def _fire_dead_man_alert(db_url: str) -> None:
    """Send a CRITICAL dead-man switch alert (12h cooldown) via Telegram."""
    _ALERT_TYPE = "dead_man_switch"
    _ALERT_KEY = "daily"
    _COOLDOWN_HOURS = 12

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        from ta_lab2.notifications import telegram

        engine = create_engine(db_url)

        # Check throttle
        throttled = False
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM pipeline_alert_log
                        WHERE alert_type = :atype
                          AND alert_key = :akey
                          AND sent_at > NOW() - (INTERVAL '1 hour' * :hours)
                          AND throttled = FALSE
                        LIMIT 1
                    """),
                    {
                        "atype": _ALERT_TYPE,
                        "akey": _ALERT_KEY,
                        "hours": _COOLDOWN_HOURS,
                    },
                ).fetchone()
                throttled = row is not None
        except (OperationalError, ProgrammingError):
            pass  # Table may not exist yet

        sent = False
        if not throttled:
            if telegram.is_configured():
                try:
                    sent = telegram.send_alert(
                        "Dead-Man Switch",
                        "Yesterday's pipeline run did not complete! "
                        "Check pipeline_run_log for details.",
                        severity="critical",
                    )
                except Exception as exc:
                    print(f"  [WARN] Dead-man Telegram send failed: {exc}")
            else:
                print("  [WARN] Dead-man switch fired but Telegram not configured")
        else:
            print("  [INFO] Dead-man alert throttled (within 12h cooldown)")

        # Log to pipeline_alert_log
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO pipeline_alert_log
                            (alert_type, alert_key, severity, message_preview, throttled)
                        VALUES (:atype, :akey, 'critical',
                                'Dead-man switch fired: yesterday pipeline incomplete',
                                :throttled)
                    """),
                    {"atype": _ALERT_TYPE, "akey": _ALERT_KEY, "throttled": throttled},
                )
        except (OperationalError, ProgrammingError) as exc:
            print(f"  [WARN] Could not log dead-man alert: {exc}")

        engine.dispose()
        status_msg = (
            "throttled"
            if throttled
            else ("sent" if sent else "skipped (Telegram unconfigured)")
        )
        print(f"  [CRITICAL] Dead-man switch: {status_msg}")

    except Exception as exc:
        print(f"[WARN] Dead-man switch alert error (non-blocking): {exc}")


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description=(
            "Unified daily refresh orchestration for VM syncs, bars, EMAs, AMAs, "
            "desc_stats, macro features, regimes, signals, executor, and stats."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full daily refresh (bars -> EMAs -> AMAs -> desc_stats -> macro -> regimes -> signals -> executor -> stats)
  python run_daily_refresh.py --all --ids 1,52,825

  # Bars only
  python run_daily_refresh.py --bars --ids all

  # EMAs only (automatically checks bar freshness)
  python run_daily_refresh.py --emas --ids all

  # AMAs only
  python run_daily_refresh.py --amas --ids all

  # FRED macro features only
  python run_daily_refresh.py --macro

  # Regimes only
  python run_daily_refresh.py --regimes --ids all

  # Signal generation only
  python run_daily_refresh.py --signals

  # Paper executor only
  python run_daily_refresh.py --execute

  # Stats only (data quality check on all tables)
  python run_daily_refresh.py --stats

  # Full pipeline without executor
  python run_daily_refresh.py --all --no-execute

  # Run weekly QC digest
  python run_daily_refresh.py --weekly-digest

  # Dry run to see what would execute
  python run_daily_refresh.py --all --ids 1 --dry-run

  # Continue on errors
  python run_daily_refresh.py --all --ids all --continue-on-error

  # Use 8 parallel processes for bar builders
  python run_daily_refresh.py --all --ids all -n 8

  # Skip bar freshness check for EMAs
  python run_daily_refresh.py --emas --ids all --skip-stale-check

  # Run regimes without hysteresis smoothing
  python run_daily_refresh.py --regimes --ids 1 --no-regime-hysteresis
        """,
    )

    # Target selection (required)
    p.add_argument(
        "--sync-vms",
        action="store_true",
        help="Sync data from VMs only (FRED from GCP + Hyperliquid from Singapore)",
    )
    p.add_argument(
        "--no-sync-vms",
        action="store_true",
        help="Skip VM sync stage in --all mode",
    )
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
        "--amas",
        action="store_true",
        help="Run AMA refreshers only",
    )
    p.add_argument(
        "--desc-stats",
        action="store_true",
        help="Run descriptive stats refresh only (asset stats + correlation)",
    )
    p.add_argument(
        "--macro",
        action="store_true",
        help="Run FRED macro feature refresh only (incremental upsert into fred.fred_macro_features)",
    )
    p.add_argument(
        "--no-macro",
        action="store_true",
        help="Skip FRED macro feature refresh stage in --all mode",
    )
    p.add_argument(
        "--macro-regimes",
        action="store_true",
        help="Run macro regime classification only (4-dimension labeling into macro_regimes)",
    )
    p.add_argument(
        "--no-macro-regimes",
        action="store_true",
        help="Skip macro regime classification stage in --all mode",
    )
    p.add_argument(
        "--macro-regime-profile",
        type=str,
        default=None,
        help="Override macro regime YAML profile (default/conservative/aggressive)",
    )
    p.add_argument(
        "--macro-analytics",
        action="store_true",
        help=(
            "Run macro analytics only (HMM classifier, lead-lag analysis, "
            "transition probabilities -- Phase 68)"
        ),
    )
    p.add_argument(
        "--no-macro-analytics",
        action="store_true",
        help="Skip macro analytics stage in --all mode",
    )
    p.add_argument(
        "--cross-asset-agg",
        action="store_true",
        help=(
            "Run cross-asset aggregation only (XAGG-01 through XAGG-04: "
            "BTC/ETH corr, avg pairwise corr, funding rate z-scores, "
            "crypto-macro correlation regime -- Phase 70)"
        ),
    )
    p.add_argument(
        "--no-cross-asset-agg",
        action="store_true",
        help="Skip cross-asset aggregation stage in --all mode",
    )
    p.add_argument(
        "--regimes",
        action="store_true",
        help="Run regime refresher only",
    )
    p.add_argument(
        "--features",
        action="store_true",
        help="Run feature refresh only (features for 1D timeframe)",
    )
    p.add_argument(
        "--no-features",
        action="store_true",
        help="Skip feature refresh stage in --all mode",
    )
    p.add_argument(
        "--garch",
        action="store_true",
        help="Run GARCH conditional volatility forecast refresh only",
    )
    p.add_argument(
        "--no-garch",
        action="store_true",
        help="Skip GARCH forecast stage in --all mode",
    )
    p.add_argument(
        "--signals",
        action="store_true",
        help="Run signal generation only (EMA crossover, RSI, ATR breakout)",
    )
    p.add_argument(
        "--calibrate-stops",
        action="store_true",
        help=(
            "Run stop calibration only (per-asset SL/TP ladders from "
            "ATR-based statistics). Runs after signals, before portfolio."
        ),
    )
    p.add_argument(
        "--no-calibrate-stops",
        action="store_true",
        help="Skip stop calibration stage in --all mode",
    )
    p.add_argument(
        "--portfolio",
        action="store_true",
        help="Run portfolio allocation refresh only (MV/CVaR/HRP + optional BL + bet sizing)",
    )
    p.add_argument(
        "--no-portfolio",
        action="store_true",
        help="Skip portfolio stage in --all mode",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Run paper executor only (process signals into orders/fills)",
    )
    p.add_argument(
        "--no-execute",
        action="store_true",
        help="Skip executor stage in --all mode (signals still generated)",
    )
    p.add_argument(
        "--drift",
        action="store_true",
        help=(
            "Run drift monitor only (requires --paper-start). "
            "Computes drift metrics between paper executor and backtest replay."
        ),
    )
    p.add_argument(
        "--no-drift",
        action="store_true",
        help="Skip drift monitor stage in --all mode",
    )
    p.add_argument(
        "--paper-start",
        metavar="DATE",
        default=None,
        help=(
            "ISO date for paper trading start (e.g. 2025-01-01). "
            "REQUIRED for drift monitoring -- when absent, drift stage "
            "is skipped with a warning even if --drift or --all is specified."
        ),
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Run stats runners only (data quality check)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help=(
            "Run sync_vms then bars then EMAs then AMAs then desc_stats "
            "then macro then regimes then features then garch then signals "
            "then calibrate_stops then portfolio then executor then drift "
            "then stats (full refresh)"
        ),
    )
    p.add_argument(
        "--weekly-digest",
        action="store_true",
        help=(
            "Run weekly QC digest (aggregates stats across all tables, "
            "sends via Telegram). Standalone -- does not combine with pipeline flags."
        ),
    )
    p.add_argument(
        "--exchange-prices",
        action="store_true",
        help=(
            "Fetch live spot prices from exchanges and compare against bar closes. "
            "Writes snapshots to exchange_price_feed. "
            "NOT included in --all; invoke explicitly."
        ),
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
    p.add_argument(
        "--source",
        choices=["cmc", "tvc", "hl", "all"],
        default="all",
        help=(
            "Data source filter for bar builders: "
            "'cmc' = CMC 1D only, 'tvc' = TVC 1D only, "
            "'hl' = Hyperliquid 1D only, 'all' = all sources (default: all)"
        ),
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

    # Regime-specific options
    p.add_argument(
        "--no-regime-hysteresis",
        action="store_true",
        help="Disable hysteresis smoothing in regime refresher (pass --no-hysteresis to subprocess)",
    )
    p.add_argument(
        "--no-desc-stats-in-regimes",
        action="store_true",
        help=(
            "Disable rolling stats augmentation in regime refresher "
            "(passes --no-desc-stats to the regime subprocess)."
        ),
    )

    # Weekly digest options
    p.add_argument(
        "--no-telegram",
        action="store_true",
        help="Suppress Telegram delivery for weekly digest (passed through to weekly_digest subprocess)",
    )

    # Phase 87: re-run / skip options
    p.add_argument(
        "--from-stage",
        metavar="STAGE",
        default=None,
        choices=STAGE_ORDER,
        help=(
            "Resume pipeline from STAGE (skips all stages before it). "
            "Implicitly enables --all. Use for re-runs after failures. "
            "Available stages: " + ", ".join(STAGE_ORDER)
        ),
    )
    p.add_argument(
        "--no-signal-gate",
        action="store_true",
        help="Skip signal validation gate in --all mode",
    )
    p.add_argument(
        "--no-ic-staleness",
        action="store_true",
        help="Skip IC staleness check in --all mode",
    )

    args = p.parse_args(argv)

    # --from-stage implicitly enables --all and sets starting point
    from_stage = getattr(args, "from_stage", None)
    if from_stage:
        args.all = True  # --from-stage implicitly enables --all

    # Validation: require explicit target
    if args.weekly_digest:
        # Weekly digest is a standalone reporting operation -- does not combine
        # with pipeline flags. Run it and exit immediately.
        pass
    elif args.exchange_prices:
        # Exchange prices is a standalone fetch -- does not combine with pipeline.
        pass
    elif not (
        args.sync_vms
        or args.bars
        or args.emas
        or args.amas
        or args.desc_stats
        or args.macro
        or args.macro_regimes
        or args.macro_analytics
        or args.cross_asset_agg
        or args.regimes
        or args.features
        or args.garch
        or args.signals
        or args.calibrate_stops
        or args.portfolio
        or args.execute
        or args.drift
        or args.stats
        or args.all
        or from_stage
    ):
        p.error(
            "Must specify --sync-vms, --bars, --emas, --amas, --desc-stats, --macro, "
            "--macro-regimes, --macro-analytics, --cross-asset-agg, --regimes, "
            "--features, --garch, --signals, --calibrate-stops, --portfolio, "
            "--execute, --drift, --stats, --all, --from-stage STAGE, "
            "--weekly-digest, or --exchange-prices"
        )

    # Resolve database URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    # Check Alembic migration status (advisory, non-blocking)
    if not args.dry_run:
        if not check_migration_status(db_url):
            print(
                "[MIGRATION] Pending migrations detected. "
                "Run 'alembic upgrade head' before next refresh."
            )

    # Handle --weekly-digest as a standalone operation (exit after completion)
    if args.weekly_digest:
        digest_result = run_weekly_digest(args, db_url)
        return 0 if digest_result.success else 1

    # Handle --exchange-prices as a standalone operation (exit after completion)
    if args.exchange_prices:
        exchange_result = run_exchange_prices(args, db_url)
        return 0 if exchange_result.success else 1

    # Parse IDs
    try:
        parsed_ids = parse_ids(args.ids, db_url)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    # Determine what to run
    run_sync_vms = (args.sync_vms or args.all) and not getattr(
        args, "no_sync_vms", False
    )
    run_bars = args.bars or args.all
    run_emas = args.emas or args.all
    run_amas = args.amas or args.all
    run_desc_stats = args.desc_stats or args.all
    run_macro = (args.macro or args.all) and not getattr(args, "no_macro", False)
    run_macro_regimes_flag = (args.macro_regimes or args.all) and not getattr(
        args, "no_macro_regimes", False
    )
    run_macro_analytics_flag = (args.macro_analytics or args.all) and not getattr(
        args, "no_macro_analytics", False
    )
    run_cross_asset_agg_flag = (args.cross_asset_agg or args.all) and not getattr(
        args, "no_cross_asset_agg", False
    )
    run_regimes = args.regimes or args.all
    run_features = (args.features or args.all) and not getattr(
        args, "no_features", False
    )
    run_garch = (args.garch or args.all) and not getattr(args, "no_garch", False)
    run_signals = args.signals or args.all
    # Phase 87: signal validation gate and IC staleness (--all only, skippable)
    run_signal_gate = args.all and not getattr(args, "no_signal_gate", False)
    run_ic_staleness = args.all and not getattr(args, "no_ic_staleness", False)
    run_calibrate_stops = (args.calibrate_stops or args.all) and not getattr(
        args, "no_calibrate_stops", False
    )
    run_portfolio = (args.portfolio or args.all) and not getattr(
        args, "no_portfolio", False
    )
    run_executor = (args.execute or args.all) and not getattr(args, "no_execute", False)
    run_drift = (args.drift or args.all) and not getattr(args, "no_drift", False)
    run_stats = args.stats or args.all

    # Apply --from-stage: skip all stages that come before the named stage.
    # Uses explicit if-statements (not locals()) for reliable variable mutation.
    if from_stage:
        skip_idx = STAGE_ORDER.index(from_stage)
        skip_stages = set(STAGE_ORDER[:skip_idx])
        if "sync_vms" in skip_stages:
            run_sync_vms = False
        if "bars" in skip_stages:
            run_bars = False
        if "emas" in skip_stages:
            run_emas = False
        if "amas" in skip_stages:
            run_amas = False
        if "desc_stats" in skip_stages:
            run_desc_stats = False
        if "macro_features" in skip_stages:
            run_macro = False
        if "macro_regimes" in skip_stages:
            run_macro_regimes_flag = False
        if "macro_analytics" in skip_stages:
            run_macro_analytics_flag = False
        if "cross_asset_agg" in skip_stages:
            run_cross_asset_agg_flag = False
        if "regimes" in skip_stages:
            run_regimes = False
        if "features" in skip_stages:
            run_features = False
        if "garch" in skip_stages:
            run_garch = False
        if "signals" in skip_stages:
            run_signals = False
        if "signal_validation_gate" in skip_stages:
            run_signal_gate = False
        if "ic_staleness_check" in skip_stages:
            run_ic_staleness = False
        if "calibrate_stops" in skip_stages:
            run_calibrate_stops = False
        if "portfolio" in skip_stages:
            run_portfolio = False
        if "executor" in skip_stages:
            run_executor = False
        if "drift_monitor" in skip_stages:
            run_drift = False
        if "stats" in skip_stages:
            run_stats = False

    # Build component description string
    components = []
    if run_sync_vms:
        components.append("sync_vms")
    if run_bars:
        components.append("bars")
    if run_emas:
        components.append("EMAs")
    if run_amas:
        components.append("AMAs")
    if run_desc_stats:
        components.append("desc_stats")
    if run_macro:
        components.append("macro_features")
    if run_macro_regimes_flag:
        components.append("macro_regimes")
    if run_macro_analytics_flag:
        components.append("macro_analytics")
    if run_cross_asset_agg_flag:
        components.append("cross_asset_agg")
    if run_regimes:
        components.append("regimes")
    if run_features:
        components.append("features")
    if run_garch:
        components.append("garch")
    if run_signals:
        components.append("signals")
    if run_signal_gate:
        components.append("signal_validation_gate")
    if run_ic_staleness:
        components.append("ic_staleness_check")
    if run_calibrate_stops:
        components.append("calibrate_stops")
    if run_portfolio:
        components.append("portfolio")
    if run_executor:
        components.append("executor")
    if run_drift and getattr(args, "paper_start", None):
        components.append("drift_monitor")
    components.append("pipeline_alerts")  # Always shown in --all runs
    if run_stats:
        components.append("stats")
    components_str = " + ".join(components)

    print(f"\n{'=' * 70}")
    print("DAILY REFRESH ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nComponents: {components_str}")
    print(f"IDs: {args.ids}")
    print(f"Continue on error: {args.continue_on_error}")
    if from_stage:
        print(f"Resuming from stage: {from_stage}")
    if run_emas and not args.skip_stale_check:
        print(f"Bar staleness threshold: {args.staleness_hours} hours")

    results: list[tuple[str, ComponentResult]] = []

    # Phase 87: pipeline run logging and dead-man switch
    pipeline_run_id = None
    pipeline_start_time = time.perf_counter()
    if not args.dry_run:
        pipeline_run_id = _start_pipeline_run(db_url)
        # Dead-man switch: alert if yesterday's run is missing
        if _check_dead_man(db_url):
            print(
                "\n[CRITICAL] Dead-man switch: yesterday's pipeline run did not complete!"
            )
            _fire_dead_man_alert(db_url)

    # Sync VM data first (before any computations that depend on it)
    # Non-blocking: sync failures don't stop the pipeline (local data is
    # still usable, just potentially stale). Warns instead.
    if run_sync_vms:
        fred_result = run_sync_fred_vm(args)
        results.append(("sync_fred_vm", fred_result))
        if not fred_result.success:
            print("\n[WARN] FRED VM sync failed -- continuing with existing local data")

        hl_result = run_sync_hl_vm(args)
        results.append(("sync_hl_vm", hl_result))
        if not hl_result.success:
            print(
                "\n[WARN] Hyperliquid VM sync failed -- continuing with existing local data"
            )

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

        if not ema_result.success and not args.continue_on_error:
            print("\n[STOPPED] EMA refreshers failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run AMAs if requested (after EMAs, before regimes)
    if run_amas:
        # Use same IDs as EMAs when running --all (fresh bar IDs); otherwise use parsed_ids
        ids_for_amas = ids_for_emas if run_emas else parsed_ids
        ama_result = run_ama_refreshers(args, db_url, ids_for_amas)
        results.append(("amas", ama_result))

        if not ama_result.success and not args.continue_on_error:
            print("\n[STOPPED] AMA refreshers failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run desc stats if requested (after AMAs, before macro and regimes)
    if run_desc_stats:
        desc_result = run_desc_stats_refresher(args, db_url, parsed_ids)
        results.append(("desc_stats", desc_result))

        if not desc_result.success and not args.continue_on_error:
            print("\n[STOPPED] Desc stats failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run FRED macro features if requested (after desc_stats, before regimes)
    # Macro features read from fred.series_values (FRED raw data) -- independent of
    # bars/EMAs/AMAs. Placed here so downstream regime classifiers (Phase 67 L4)
    # can read macro context during regime computation.
    if run_macro:
        macro_result = run_macro_features(args)
        results.append(("macro_features", macro_result))

        if not macro_result.success and not args.continue_on_error:
            print("\n[STOPPED] Macro feature refresh failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run macro regime classification if requested (after macro_features, before per-asset regimes)
    # Pipeline ordering: macro_features -> macro_regimes -> regimes (MREG-09)
    if run_macro_regimes_flag:
        macro_regimes_result = run_macro_regimes(args)
        results.append(("macro_regimes", macro_regimes_result))

        if not macro_regimes_result.success and not args.continue_on_error:
            print("\n[STOPPED] Macro regime classification failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run macro analytics if requested (after macro_regimes, before per-asset regimes)
    # Pipeline ordering: macro_features -> macro_regimes -> macro_analytics -> regimes (MREG-12)
    if run_macro_analytics_flag:
        macro_analytics_result = run_macro_analytics(args)
        results.append(("macro_analytics", macro_analytics_result))

        if not macro_analytics_result.success and not args.continue_on_error:
            print("\n[STOPPED] Macro analytics failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run cross-asset aggregation if requested (after macro_analytics, before per-asset regimes)
    # Pipeline ordering: macro_analytics -> cross_asset_agg -> regimes (XAGG Phase 70)
    if run_cross_asset_agg_flag:
        cross_asset_result = run_cross_asset_agg(args)
        results.append(("cross_asset_agg", cross_asset_result))

        if not cross_asset_result.success and not args.continue_on_error:
            print("\n[STOPPED] Cross-asset aggregation failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run macro gate evaluation after macro_regimes (Phase 73 gap closure)
    # Non-blocking: gate failures don't stop the pipeline
    if run_macro_regimes_flag:
        gate_result = run_evaluate_macro_gates(args)
        results.append(("macro_gates", gate_result))

    # Run macro regime transition alerts after macro_regimes (Phase 73 gap closure)
    # Non-blocking: alert failures don't stop the pipeline
    if run_macro_regimes_flag:
        alert_result = run_macro_alerts(args)
        results.append(("macro_alerts", alert_result))

    # Run regimes if requested (after bars, EMAs, AMAs, desc_stats, macro, and macro_regimes)
    if run_regimes:
        regime_result = run_regime_refresher(args, db_url, parsed_ids)
        results.append(("regimes", regime_result))

        if not regime_result.success and not args.continue_on_error:
            print("\n[STOPPED] Regime refresher failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run feature refresh if requested (after regimes, before signals)
    if run_features:
        feature_result = run_feature_refresh_stage(args, db_url)
        results.append(("features", feature_result))

        if not feature_result.success and not args.continue_on_error:
            print("\n[STOPPED] Feature refresh failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run GARCH forecasts if requested (after features, before signals)
    if run_garch:
        garch_result = run_garch_forecasts(args, db_url)
        results.append(("garch", garch_result))

        if not garch_result.success and not args.continue_on_error:
            print("\n[STOPPED] GARCH forecast refresh failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run signal generation if requested (after features, before executor)
    if run_signals:
        signal_result = run_signal_refreshes(args, db_url)
        results.append(("signals", signal_result))

        if not signal_result.success and not args.continue_on_error:
            print("\n[STOPPED] Signal generation failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Phase 87: Signal validation gate -- runs AFTER signals, BEFORE executor.
    # BLOCKING: if gate detects anomalies (rc=2), executor is skipped.
    signal_gate_blocked = False
    if run_signal_gate:
        gate_result = run_signal_validation_gate(args, db_url)
        results.append(("signal_validation_gate", gate_result))
        if not gate_result.success:
            signal_gate_blocked = True
            print(
                "\n[GATE] Signal validation gate BLOCKED execution -- anomalies detected"
            )
            print("[GATE] Signals held back from executor. Review signal_anomaly_log.")

    # Phase 87: IC staleness check -- runs after signal gate, non-blocking.
    # IC decay findings are logged to dim_ic_weight_overrides but pipeline continues.
    if run_ic_staleness:
        ic_result = run_ic_staleness_check_stage(args, db_url)
        results.append(("ic_staleness_check", ic_result))
        if not ic_result.success:
            print(
                "\n[WARN] IC staleness check detected decay -- check dim_ic_weight_overrides"
            )

    # Run stop calibration if requested (after signals, before portfolio)
    # Non-fatal: failure logs a warning and pipeline continues to portfolio refresh
    if run_calibrate_stops:
        calibrate_result = run_calibrate_stops_stage(args, db_url)
        results.append(("calibrate_stops", calibrate_result))

        if not calibrate_result.success and not args.continue_on_error:
            print("\n[STOPPED] Stop calibration failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1
        elif not calibrate_result.success:
            print("\n[WARN] Stop calibration failed -- continuing to portfolio refresh")

    # Run portfolio allocation refresh if requested (after calibrate_stops, before executor)
    # Pipeline order: bars -> EMAs -> AMAs -> desc_stats -> regimes -> features
    #                 -> signals -> signal_gate -> ic_staleness -> calibrate_stops
    #                 -> portfolio -> executor -> drift -> pipeline_alerts -> stats
    if run_portfolio:
        portfolio_result = run_portfolio_refresh_stage(args, db_url)
        results.append(("portfolio", portfolio_result))

        if not portfolio_result.success and not args.continue_on_error:
            print("\n[STOPPED] Portfolio allocation refresh failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run paper executor if requested (after signals, before stats)
    # Phase 87: executor is gated by signal_gate_blocked flag.
    if run_executor:
        if signal_gate_blocked:
            print("\n[GATE] Skipping executor -- signal validation gate blocked")
            results.append(
                (
                    "executor",
                    ComponentResult(
                        component="executor",
                        success=False,
                        duration_sec=0.0,
                        returncode=2,
                        error_message="Blocked by signal validation gate",
                    ),
                )
            )
            if not args.continue_on_error:
                print(
                    "(Signal gate block is treated as pipeline stop; use --continue-on-error to override)"
                )
                # Do not return 1 here -- complete remaining stages (drift, stats, alerts)
        else:
            executor_result = run_paper_executor_stage(args, db_url)
            results.append(("executor", executor_result))

            if not executor_result.success and not args.continue_on_error:
                print("\n[STOPPED] Paper executor failed, stopping execution")
                print("(Use --continue-on-error to run remaining components)")
                return 1

    # Run drift monitor if requested (after executor, before stats)
    # --paper-start is OPTIONAL: if not provided, drift stage is silently skipped
    # even when --drift or --all is used. This allows --all to work without
    # requiring --paper-start every time.
    paper_start = getattr(args, "paper_start", None)
    if run_drift and paper_start:
        drift_result = run_drift_monitor_stage(args, db_url)
        results.append(("drift_monitor", drift_result))

        if not drift_result.success and not args.continue_on_error:
            print("\n[STOPPED] Drift monitor failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1
    elif run_drift and not paper_start:
        print()
        print("[WARN] Drift monitoring SKIPPED: --paper-start not provided")
        print(
            "       To enable drift monitoring, re-run with: --paper-start YYYY-MM-DD"
        )
        print(
            "       (Drift guard compares paper vs backtest to detect execution divergence)"
        )

    # Run stats if requested (final stage -- after bars, EMAs, regimes, executor)
    if run_stats:
        stats_result = run_stats_runners(args, db_url)
        results.append(("stats", stats_result))

        # Pipeline gate: stats FAIL means data quality issues
        if not stats_result.success:
            print(
                "\n[PIPELINE GATE] Stats runners reported FAIL -- data quality check failed"
            )
            print("Review stats tables for specific failures before using this data")
            # Don't check continue_on_error -- stats FAIL is always terminal
            return 1

    # Phase 87: Pipeline completion alert -- after stats, before summary.
    # Sends daily digest via Telegram (INFO if all green, WARNING if any failures).
    # Non-blocking: failure to send alert never stops the pipeline.
    if not args.dry_run and results:
        alert_result = run_pipeline_completion_alert(args, db_url, results)
        results.append(("pipeline_alerts", alert_result))

    # Print combined summary
    if not args.dry_run:
        all_success = print_combined_summary(results)

        # Phase 87: Update pipeline_run_log with completion details
        if pipeline_run_id:
            stages_completed = [name for name, r in results if r.success]
            total_duration = time.perf_counter() - pipeline_start_time
            overall_status = "complete" if all_success else "failed"
            error_msg: str | None = (
                "; ".join(
                    f"{name}: {r.error_message}"
                    for name, r in results
                    if not r.success and r.error_message
                )
                or None
            )
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                overall_status,
                stages_completed,
                total_duration,
                error_msg,
            )

        return 0 if all_success else 1
    else:
        print(f"\n[DRY RUN] Would have executed {len(results)} component(s)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
