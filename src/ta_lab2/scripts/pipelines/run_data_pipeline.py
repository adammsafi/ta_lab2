"""
Data pipeline: sync VMs, build bars, compute bar returns.

Standalone entry point for the Data layer of the pipeline chain:
  Data -> Features -> Signals -> Execution

Stages (in order):
  1. sync_fred_vm  -- SSH sync FRED data from GCP VM
  2. sync_hl_vm    -- SSH sync Hyperliquid data from Singapore VM
  3. sync_cmc_vm   -- SSH sync CMC price data from Singapore VM
  4. bars          -- Run all bar builders (CMC/TVC/HL)
  5. returns_bars  -- Compute bar returns (LAG-based incremental)

Usage:
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids 1,52,825 --dry-run
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all --chain
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

from ta_lab2.scripts.pipeline_utils import (
    ComponentResult,
    _complete_pipeline_run,
    _log_stage_complete,
    _log_stage_start,
    _maybe_kill,
    _start_pipeline_run,
    print_combined_summary,
)
from ta_lab2.scripts.refresh_utils import parse_ids, resolve_db_url
from ta_lab2.scripts.run_daily_refresh import (
    run_bar_builders,
    run_returns_bars,
    run_sync_cmc_vm,
    run_sync_fred_vm,
    run_sync_hl_vm,
)

PIPELINE_NAME = "data"

# Stages that are non-blocking (VM sync failures warn but don't stop the pipeline)
_NONBLOCKING_STAGES = {"sync_fred_vm", "sync_hl_vm", "sync_cmc_vm"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Data pipeline: sync VMs, build bars, compute bar returns. "
            "Part of the pipeline chain: Data -> Features -> Signals -> Execution."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full data pipeline for all assets
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all

  # Dry run to preview commands
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids 1 --dry-run

  # Skip VM syncs (use local data as-is)
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all --no-sync-vms

  # Chain into Features pipeline on success
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all --chain

  # CMC bars only (skip TVC and HL)
  python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all --source cmc
        """,
    )

    p.add_argument(
        "--ids",
        required=True,
        help="Asset IDs to process: comma-separated integers or 'all'",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: resolved from db_config.env or TARGET_DB_URL)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Stream subprocess output to stdout",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue to next stage on failure (default: stop on first failure)",
    )
    p.add_argument(
        "--no-sync-vms",
        action="store_true",
        help="Skip all VM sync stages (sync_fred_vm, sync_hl_vm, sync_cmc_vm)",
    )
    p.add_argument(
        "--source",
        choices=["cmc", "tvc", "hl", "all"],
        default="all",
        help="Bar source filter: only build bars from this source (default: all)",
    )
    p.add_argument(
        "-n",
        "--num-processes",
        type=int,
        default=None,
        help="Parallel processes for bar builders",
    )
    p.add_argument(
        "--chain",
        action="store_true",
        help=(
            "After successful completion, automatically launch the Features pipeline "
            "via subprocess (--chain passes --ids and --db-url through)"
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Data pipeline entry point. Returns 0 on success, 1 on failure, 2 on kill."""
    p = build_parser()
    args = p.parse_args(argv)

    db_url = args.db_url or resolve_db_url()
    parsed_ids = parse_ids(args.ids)

    print(f"\n{'=' * 70}")
    print("DATA PIPELINE")
    print(f"{'=' * 70}")
    print(f"\nPipeline: {PIPELINE_NAME}")
    print(f"IDs: {args.ids}")
    print(f"Source: {args.source}")
    print(f"Continue on error: {args.continue_on_error}")
    print(f"Skip VM syncs: {args.no_sync_vms}")
    if args.chain:
        print("Chain: will launch Features pipeline on success")

    results: list[tuple[str, ComponentResult]] = []
    pipeline_run_id: str | None = None
    pipeline_start_time = time.perf_counter()

    if not args.dry_run:
        pipeline_run_id = _start_pipeline_run(db_url, pipeline_name=PIPELINE_NAME)

    # ------------------------------------------------------------------
    # Stage 1-3: VM syncs (non-blocking -- failures warn, don't stop)
    # ------------------------------------------------------------------
    if not args.no_sync_vms:
        # sync_fred_vm
        _slid = _log_stage_start(db_url, pipeline_run_id, "sync_fred_vm")
        fred_result = run_sync_fred_vm(args)
        results.append(("sync_fred_vm", fred_result))
        _log_stage_complete(
            db_url,
            _slid,
            fred_result.success,
            fred_result.duration_sec,
            fred_result.error_message,
        )
        if not fred_result.success:
            print("\n[WARN] FRED VM sync failed -- continuing with existing local data")
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

        # sync_hl_vm
        _slid = _log_stage_start(db_url, pipeline_run_id, "sync_hl_vm")
        hl_result = run_sync_hl_vm(args)
        results.append(("sync_hl_vm", hl_result))
        _log_stage_complete(
            db_url,
            _slid,
            hl_result.success,
            hl_result.duration_sec,
            hl_result.error_message,
        )
        if not hl_result.success:
            print(
                "\n[WARN] Hyperliquid VM sync failed -- continuing with existing local data"
            )
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

        # sync_cmc_vm
        _slid = _log_stage_start(db_url, pipeline_run_id, "sync_cmc_vm")
        cmc_result = run_sync_cmc_vm(args)
        results.append(("sync_cmc_vm", cmc_result))
        _log_stage_complete(
            db_url,
            _slid,
            cmc_result.success,
            cmc_result.duration_sec,
            cmc_result.error_message,
        )
        if not cmc_result.success:
            print("\n[WARN] CMC VM sync failed -- continuing with existing local data")
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 4: bars
    # ------------------------------------------------------------------
    _slid = _log_stage_start(db_url, pipeline_run_id, "bars")
    bar_result = run_bar_builders(args, db_url, parsed_ids)
    results.append(("bars", bar_result))
    _log_stage_complete(
        db_url,
        _slid,
        bar_result.success,
        bar_result.duration_sec,
        bar_result.error_message,
    )
    if not bar_result.success and not args.continue_on_error:
        print("\n[STOPPED] Bar builders failed, stopping execution")
        print("(Use --continue-on-error to run remaining components)")
        _complete_pipeline_run(
            db_url,
            pipeline_run_id,
            "failed",
            [name for name, r in results if r.success],
            time.perf_counter() - pipeline_start_time,
            bar_result.error_message,
        )
        return 1
    if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
        return 2

    # ------------------------------------------------------------------
    # Stage 5: returns_bars
    # ------------------------------------------------------------------
    _slid = _log_stage_start(db_url, pipeline_run_id, "returns_bars")
    ret_bars_result = run_returns_bars(args, db_url)
    results.append(("returns_bars", ret_bars_result))
    _log_stage_complete(
        db_url,
        _slid,
        ret_bars_result.success,
        ret_bars_result.duration_sec,
        ret_bars_result.error_message,
    )
    if not ret_bars_result.success and not args.continue_on_error:
        print("\n[STOPPED] Bar returns failed, stopping execution")
        _complete_pipeline_run(
            db_url,
            pipeline_run_id,
            "failed",
            [name for name, r in results if r.success],
            time.perf_counter() - pipeline_start_time,
            ret_bars_result.error_message,
        )
        return 1
    if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
        return 2

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------
    total_duration = time.perf_counter() - pipeline_start_time
    stages_completed = [name for name, r in results if r.success]

    # Determine overall success: VM sync failures don't count against all_success
    blocking_failures = [
        (name, r)
        for name, r in results
        if not r.success and name not in _NONBLOCKING_STAGES
    ]
    all_success = len(blocking_failures) == 0

    status = "complete" if all_success else "failed"
    if pipeline_run_id:
        _complete_pipeline_run(
            db_url,
            pipeline_run_id,
            status,
            stages_completed,
            total_duration,
            None if all_success else f"{len(blocking_failures)} stage(s) failed",
        )

    print_combined_summary(results)

    # ------------------------------------------------------------------
    # Chain: launch Features pipeline
    # ------------------------------------------------------------------
    if args.chain and all_success:
        print(f"\n{'=' * 70}")
        print("CHAINING: Launching Features pipeline")
        print(f"{'=' * 70}")
        chain_cmd = [
            sys.executable,
            "-m",
            "ta_lab2.scripts.pipelines.run_features_pipeline",
            "--chain",
            "--ids",
            args.ids,
            "--db-url",
            db_url,
        ]
        if args.verbose:
            chain_cmd.append("--verbose")
        if args.continue_on_error:
            chain_cmd.append("--continue-on-error")
        if args.num_processes:
            chain_cmd.extend(["-n", str(args.num_processes)])
        print(f"Command: {' '.join(chain_cmd)}")
        chain_result = subprocess.run(chain_cmd, check=False)
        return chain_result.returncode

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
