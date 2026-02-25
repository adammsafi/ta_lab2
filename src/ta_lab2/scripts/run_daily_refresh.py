#!/usr/bin/env python
"""
Unified daily refresh orchestration script.

Coordinates bars, EMAs, AMAs, desc_stats, regimes, and stats with
state-based checking and clear visibility.

Usage:
    # Full daily refresh (bars then EMAs then AMAs then desc_stats then regimes then stats)
    python run_daily_refresh.py --all --ids 1,52,825

    # Bars only
    python run_daily_refresh.py --bars --ids all

    # EMAs only (with bar freshness check)
    python run_daily_refresh.py --emas --ids all

    # AMAs only
    python run_daily_refresh.py --amas --ids all

    # Desc stats only (asset stats + correlation)
    python run_daily_refresh.py --desc-stats --ids all

    # Regimes only
    python run_daily_refresh.py --regimes --ids all

    # Stats only
    python run_daily_refresh.py --stats

    # Weekly QC digest
    python run_daily_refresh.py --weekly-digest

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
TIMEOUT_STATS = 3600  # 1 hour -- stats runners scan large tables
TIMEOUT_EXCHANGE_PRICES = 120  # 2 minutes -- live price fetches from exchanges


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
        cmd.extend(["--skip", "1d_tvc"])
    elif source == "tvc":
        cmd.extend(["--skip", "1d"])

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
    cmd = [sys.executable, str(script_dir / "refresh_cmc_regimes.py")]

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
    threshold derived from cmc_asset_stats.

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


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description=(
            "Unified daily refresh orchestration for bars, EMAs, AMAs, "
            "desc_stats, regimes, and stats."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full daily refresh (bars then EMAs then AMAs then regimes then stats)
  python run_daily_refresh.py --all --ids 1,52,825

  # Bars only
  python run_daily_refresh.py --bars --ids all

  # EMAs only (automatically checks bar freshness)
  python run_daily_refresh.py --emas --ids all

  # AMAs only
  python run_daily_refresh.py --amas --ids all

  # Regimes only
  python run_daily_refresh.py --regimes --ids all

  # Stats only (data quality check on all tables)
  python run_daily_refresh.py --stats

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
        "--regimes",
        action="store_true",
        help="Run regime refresher only",
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
            "Run bars then EMAs then AMAs then desc_stats then regimes then stats "
            "(full refresh)"
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
        choices=["cmc", "tvc", "all"],
        default="all",
        help=(
            "Data source filter for bar builders: "
            "'cmc' = CMC 1D only, 'tvc' = TVC 1D only, 'all' = both (default: all)"
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

    args = p.parse_args(argv)

    # Validation: require explicit target
    if args.weekly_digest:
        # Weekly digest is a standalone reporting operation -- does not combine
        # with pipeline flags. Run it and exit immediately.
        pass
    elif args.exchange_prices:
        # Exchange prices is a standalone fetch -- does not combine with pipeline.
        pass
    elif not (
        args.bars
        or args.emas
        or args.amas
        or args.desc_stats
        or args.regimes
        or args.stats
        or args.all
    ):
        p.error(
            "Must specify --bars, --emas, --amas, --desc-stats, --regimes, --stats, "
            "--all, --weekly-digest, or --exchange-prices"
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
    run_bars = args.bars or args.all
    run_emas = args.emas or args.all
    run_amas = args.amas or args.all
    run_desc_stats = args.desc_stats or args.all
    run_regimes = args.regimes or args.all
    run_stats = args.stats or args.all

    # Build component description string
    components = []
    if run_bars:
        components.append("bars")
    if run_emas:
        components.append("EMAs")
    if run_amas:
        components.append("AMAs")
    if run_desc_stats:
        components.append("desc_stats")
    if run_regimes:
        components.append("regimes")
    if run_stats:
        components.append("stats")
    components_str = " + ".join(components)

    print(f"\n{'=' * 70}")
    print("DAILY REFRESH ORCHESTRATOR")
    print(f"{'=' * 70}")
    print(f"\nComponents: {components_str}")
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

    # Run desc stats if requested (after AMAs, before regimes)
    if run_desc_stats:
        desc_result = run_desc_stats_refresher(args, db_url, parsed_ids)
        results.append(("desc_stats", desc_result))

        if not desc_result.success and not args.continue_on_error:
            print("\n[STOPPED] Desc stats failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            return 1

    # Run regimes if requested (after bars, EMAs, AMAs, and desc_stats)
    if run_regimes:
        regime_result = run_regime_refresher(args, db_url, parsed_ids)
        results.append(("regimes", regime_result))

    # Run stats if requested (final stage -- after bars, EMAs, regimes)
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

    # Print combined summary
    if not args.dry_run:
        all_success = print_combined_summary(results)
        return 0 if all_success else 1
    else:
        print(f"\n[DRY RUN] Would have executed {len(results)} component(s)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
