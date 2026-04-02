#!/usr/bin/env python
"""
Signals pipeline: macro gates, macro alerts, signal generation, validation gate, IC staleness.

This pipeline runs locally and is the third step in the local chain:
  Data → Features → Signals [→ sync_signals_to_vm → Execution on VM]

Stage order:
  1. macro_gates         -- pre-flight gate on macro conditions (VIX, carry, credit, FOMC)
  2. macro_alerts        -- transition detection + Telegram
  3. signals             -- all 7 signal types (EMA, RSI, ATR, MACD, AMA x3)
  4. signal_validation_gate -- anomaly detection; rc=2 sets signal_gate_blocked
  5. ic_staleness_check  -- IC freshness check (non-blocking)

Signal gate blocked behavior:
  When signal_validation_gate exits with code 2 (anomalies detected), the
  signal_gate_blocked flag is set. If --chain is active, sync_signals_to_vm
  is NOT triggered -- the VM executor sees no new signals and does nothing.

Usage:
    # Dry run
    python -m ta_lab2.scripts.pipelines.run_signals_pipeline --dry-run

    # Full signals pipeline
    python -m ta_lab2.scripts.pipelines.run_signals_pipeline --db-url postgresql://...

    # Auto-chain: sync to VM after completion (if gate not blocked)
    python -m ta_lab2.scripts.pipelines.run_signals_pipeline --chain

    # Skip validation gate (testing/debug)
    python -m ta_lab2.scripts.pipelines.run_signals_pipeline --no-signal-gate

    # Resume from specific stage
    python -m ta_lab2.scripts.pipelines.run_signals_pipeline --from-stage signals
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from ta_lab2.scripts.pipeline_utils import (
    STAGE_ORDER,
    ComponentResult,
    _check_dead_man,
    _complete_pipeline_run,
    _fire_dead_man_alert,
    _log_stage_complete,
    _log_stage_start,
    _maybe_kill,
    _start_pipeline_run,
    print_combined_summary,
)
from ta_lab2.scripts.run_daily_refresh import (
    run_evaluate_macro_gates,
    run_ic_staleness_check_stage,
    run_macro_alerts,
    run_signal_refreshes,
    run_signal_validation_gate,
)

PIPELINE_NAME = "signals"

# Signals pipeline stage order (subset of STAGE_ORDER relevant to this pipeline)
_SIGNALS_STAGES = [
    "macro_gates",
    "macro_alerts",
    "signals",
    "signal_validation_gate",
    "ic_staleness_check",
]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Signals pipeline: macro gates → macro alerts → signals → gate → IC check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("TARGET_DB_URL", ""),
        help="Database URL (or set TARGET_DB_URL env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed subprocess output",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue to next stage even if a stage fails",
    )
    parser.add_argument(
        "--no-signal-gate",
        action="store_true",
        help="Skip the signal_validation_gate stage",
    )
    parser.add_argument(
        "--no-ic-staleness",
        action="store_true",
        help="Skip the ic_staleness_check stage",
    )
    parser.add_argument(
        "--from-stage",
        choices=_SIGNALS_STAGES,
        default=None,
        help="Start from a specific stage (skip earlier stages)",
    )
    parser.add_argument(
        "--chain",
        action="store_true",
        help=(
            "After completion, trigger sync_signals_to_vm subprocess "
            "(skipped if signal gate is blocked)"
        ),
    )
    return parser.parse_args(argv)


def _should_run_stage(stage: str, from_stage: str | None) -> bool:
    """Return True if the stage should be executed given --from-stage."""
    if from_stage is None:
        return True
    # Use STAGE_ORDER for canonical ordering
    try:
        from_idx = STAGE_ORDER.index(from_stage)
        stage_idx = STAGE_ORDER.index(stage)
        return stage_idx >= from_idx
    except ValueError:
        return True


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_url = args.db_url

    pipeline_start = time.perf_counter()
    results: list[tuple[str, ComponentResult]] = []

    # --- Pipeline run log ---
    pipeline_run_id = (
        _start_pipeline_run(db_url, pipeline_name=PIPELINE_NAME)
        if not args.dry_run
        else None
    )

    # --- Dead-man switch check ---
    if not args.dry_run and db_url:
        if _check_dead_man(db_url, pipeline_name=PIPELINE_NAME):
            _fire_dead_man_alert(db_url)

    # --- Stage tracking ---
    signal_gate_blocked = False

    # ==========================================================================
    # Stage 1: macro_gates
    # ==========================================================================
    if _should_run_stage("macro_gates", args.from_stage):
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
            return 2

        stage_log_id = _log_stage_start(db_url, pipeline_run_id, "macro_gates")
        result = run_evaluate_macro_gates(args)
        results.append(("macro_gates", result))
        _log_stage_complete(
            db_url,
            stage_log_id,
            result.success,
            result.duration_sec,
            result.error_message,
        )

        if not result.success and not args.continue_on_error:
            if pipeline_run_id:
                _complete_pipeline_run(
                    db_url,
                    pipeline_run_id,
                    "failed",
                    [n for n, r in results if r.success],
                    time.perf_counter() - pipeline_start,
                    f"Stage macro_gates failed: {result.error_message}",
                )
            print_combined_summary(results)
            return 1

    # ==========================================================================
    # Stage 2: macro_alerts
    # ==========================================================================
    if _should_run_stage("macro_alerts", args.from_stage):
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
            return 2

        stage_log_id = _log_stage_start(db_url, pipeline_run_id, "macro_alerts")
        result = run_macro_alerts(args)
        results.append(("macro_alerts", result))
        _log_stage_complete(
            db_url,
            stage_log_id,
            result.success,
            result.duration_sec,
            result.error_message,
        )

        if not result.success and not args.continue_on_error:
            if pipeline_run_id:
                _complete_pipeline_run(
                    db_url,
                    pipeline_run_id,
                    "failed",
                    [n for n, r in results if r.success],
                    time.perf_counter() - pipeline_start,
                    f"Stage macro_alerts failed: {result.error_message}",
                )
            print_combined_summary(results)
            return 1

    # ==========================================================================
    # Stage 3: signals
    # ==========================================================================
    if _should_run_stage("signals", args.from_stage):
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
            return 2

        stage_log_id = _log_stage_start(db_url, pipeline_run_id, "signals")
        result = run_signal_refreshes(args, db_url)
        results.append(("signals", result))
        _log_stage_complete(
            db_url,
            stage_log_id,
            result.success,
            result.duration_sec,
            result.error_message,
        )

        if not result.success and not args.continue_on_error:
            if pipeline_run_id:
                _complete_pipeline_run(
                    db_url,
                    pipeline_run_id,
                    "failed",
                    [n for n, r in results if r.success],
                    time.perf_counter() - pipeline_start,
                    f"Stage signals failed: {result.error_message}",
                )
            print_combined_summary(results)
            return 1

    # ==========================================================================
    # Stage 4: signal_validation_gate (optional -- --no-signal-gate skips)
    # ==========================================================================
    if (
        _should_run_stage("signal_validation_gate", args.from_stage)
        and not args.no_signal_gate
    ):
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
            return 2

        stage_log_id = _log_stage_start(
            db_url, pipeline_run_id, "signal_validation_gate"
        )
        result = run_signal_validation_gate(args, db_url)
        results.append(("signal_validation_gate", result))
        _log_stage_complete(
            db_url,
            stage_log_id,
            result.success,
            result.duration_sec,
            result.error_message,
        )

        if result.returncode == 2:
            signal_gate_blocked = True
            print(
                "\n[GATE] Signal validation gate BLOCKED -- "
                "signals will NOT be synced to VM"
            )
        elif not result.success and not args.continue_on_error:
            if pipeline_run_id:
                _complete_pipeline_run(
                    db_url,
                    pipeline_run_id,
                    "failed",
                    [n for n, r in results if r.success],
                    time.perf_counter() - pipeline_start,
                    f"Stage signal_validation_gate failed: {result.error_message}",
                )
            print_combined_summary(results)
            return 1

    # ==========================================================================
    # Stage 5: ic_staleness_check (optional -- --no-ic-staleness skips)
    # ==========================================================================
    if (
        _should_run_stage("ic_staleness_check", args.from_stage)
        and not args.no_ic_staleness
    ):
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
            return 2

        stage_log_id = _log_stage_start(db_url, pipeline_run_id, "ic_staleness_check")
        result = run_ic_staleness_check_stage(args, db_url)
        results.append(("ic_staleness_check", result))
        _log_stage_complete(
            db_url,
            stage_log_id,
            result.success,
            result.duration_sec,
            result.error_message,
        )
        # IC staleness is non-blocking: log result but never halt pipeline

    # ==========================================================================
    # Completion
    # ==========================================================================
    total_duration = time.perf_counter() - pipeline_start
    all_success = all(r.success for _, r in results)
    status = "complete" if all_success else "failed"
    error_summary = (
        None
        if all_success
        else "; ".join(
            f"{n}: {r.error_message}"
            for n, r in results
            if not r.success and r.error_message
        )
    )

    if pipeline_run_id:
        _complete_pipeline_run(
            db_url,
            pipeline_run_id,
            status,
            [n for n, r in results if r.success],
            total_duration,
            error_summary,
        )
    print_combined_summary(results)

    # ==========================================================================
    # Chain: sync_signals_to_vm (only if all_success AND gate not blocked)
    # ==========================================================================
    if args.chain and all_success and not signal_gate_blocked:
        print("\n[CHAIN] Triggering sync_signals_to_vm...")
        chain_result = subprocess.run(
            [sys.executable, "-m", "ta_lab2.scripts.etl.sync_signals_to_vm"],
            check=False,
        )
        if chain_result.returncode != 0:
            print(
                f"[WARN] sync_signals_to_vm exited with code {chain_result.returncode} "
                "(script may not exist yet -- see Plan 04)"
            )
    elif args.chain and signal_gate_blocked:
        print("\n[CHAIN] Skipping sync_signals_to_vm -- signal gate is BLOCKED")

    return 0 if all_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
