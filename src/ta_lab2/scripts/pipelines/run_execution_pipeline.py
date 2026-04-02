#!/usr/bin/env python
"""
Execution pipeline: calibrate_stops, portfolio refresh, paper executor.

This pipeline runs on the Oracle VM (always-on). In single-shot mode it runs
the 3 execution stages once and exits. In polling mode (--loop) it continuously
checks for fresh signals and runs the stages when new signals are detected.

Stage order:
  1. calibrate_stops  -- compute stop levels for active positions
  2. portfolio        -- portfolio optimizer (BL weights, TopK selection)
  3. executor         -- paper executor (signal polling + order generation)

Usage:
    # Single-shot dry run
    python -m ta_lab2.scripts.pipelines.run_execution_pipeline --dry-run

    # Single-shot execution
    python -m ta_lab2.scripts.pipelines.run_execution_pipeline --db-url postgresql://...

    # Polling loop mode (for VM deployment, polls every 5 minutes)
    python -m ta_lab2.scripts.pipelines.run_execution_pipeline --loop --db-url postgresql://...

    # Custom poll interval
    python -m ta_lab2.scripts.pipelines.run_execution_pipeline --loop --poll-interval 120

    # Only calibrate stops
    python -m ta_lab2.scripts.pipelines.run_execution_pipeline --calibrate-only

    # Only portfolio refresh
    python -m ta_lab2.scripts.pipelines.run_execution_pipeline --portfolio-only
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

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
    run_calibrate_stops_stage,
    run_paper_executor_stage,
    run_portfolio_refresh_stage,
)

PIPELINE_NAME = "execution"
POLL_INTERVAL_SEC = 300  # 5 minutes default

# Signal tables to check for freshness
_SIGNAL_TABLES = [
    "signals_ema_crossover",
    "signals_rsi_mean_revert",
    "signals_atr_breakout",
    "signals_macd_crossover",
    "signals_ama_momentum",
    "signals_ama_mean_reversion",
    "signals_ama_regime_conditional",
]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execution pipeline: calibrate_stops -> portfolio -> executor",
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
        "--loop",
        action="store_true",
        help="Enable polling mode: continuously check for fresh signals and run",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=POLL_INTERVAL_SEC,
        help=f"Seconds between polls in --loop mode (default: {POLL_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--calibrate-only",
        action="store_true",
        help="Run only the calibrate_stops stage",
    )
    parser.add_argument(
        "--portfolio-only",
        action="store_true",
        help="Run only the portfolio refresh stage",
    )
    return parser.parse_args(argv)


def _should_run_stage(stage: str, from_stage: str | None) -> bool:
    """Return True if the stage should be executed given --from-stage."""
    if from_stage is None:
        return True
    try:
        from_idx = STAGE_ORDER.index(from_stage)
        stage_idx = STAGE_ORDER.index(stage)
        return stage_idx >= from_idx
    except ValueError:
        return True


def _get_last_signal_ts(db_url: str) -> datetime | None:
    """Query MAX(ts) across all signal tables. Return None if no signals exist."""
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine, text

        selects = " UNION ALL ".join(
            f"SELECT MAX(ts) AS ts FROM {tbl}" for tbl in _SIGNAL_TABLES
        )
        query = f"SELECT MAX(ts) FROM ({selects}) AS all_signals"

        engine = create_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(text(query)).fetchone()
        engine.dispose()
        if row and row[0] is not None:
            ts = row[0]
            # Ensure timezone-aware
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        return None
    except Exception as exc:
        print(f"[WARN] Could not query signal tables for freshness check: {exc}")
        return None


def _get_last_execution_ts(db_url: str) -> datetime | None:
    """Query MAX(completed_at) from pipeline_run_log for completed execution runs."""
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT MAX(completed_at)
                    FROM pipeline_run_log
                    WHERE pipeline_name = :name
                      AND status = 'complete'
                """),
                {"name": PIPELINE_NAME},
            ).fetchone()
        engine.dispose()
        if row and row[0] is not None:
            ts = row[0]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        return None
    except Exception as exc:
        print(f"[WARN] Could not query pipeline_run_log for last execution ts: {exc}")
        return None


def run_single_pass(args: argparse.Namespace, db_url: str) -> int:
    """Run the 3 execution stages once with full pipeline_run_log tracking.

    Returns:
        0 if all stages succeed, 1 if any stage fails.
    """
    pipeline_start = time.perf_counter()
    results: list[tuple[str, ComponentResult]] = []

    pipeline_run_id = (
        _start_pipeline_run(db_url, pipeline_name=PIPELINE_NAME)
        if not args.dry_run
        else None
    )

    # --calibrate-only: skip portfolio and executor
    run_portfolio = not args.calibrate_only
    run_executor = not args.calibrate_only and not args.portfolio_only

    # ==========================================================================
    # Stage 1: calibrate_stops
    # ==========================================================================
    if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
        return 2

    stage_log_id = _log_stage_start(db_url, pipeline_run_id, "calibrate_stops")
    result = run_calibrate_stops_stage(args, db_url)
    results.append(("calibrate_stops", result))
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
                f"Stage calibrate_stops failed: {result.error_message}",
            )
        print_combined_summary(results)
        return 1

    if args.calibrate_only:
        total_duration = time.perf_counter() - pipeline_start
        if pipeline_run_id:
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "complete",
                [n for n, r in results if r.success],
                total_duration,
                None,
            )
        print_combined_summary(results)
        return 0

    # ==========================================================================
    # Stage 2: portfolio (skipped if --calibrate-only)
    # ==========================================================================
    if run_portfolio:
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
            return 2

        stage_log_id = _log_stage_start(db_url, pipeline_run_id, "portfolio")
        result = run_portfolio_refresh_stage(args, db_url)
        results.append(("portfolio", result))
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
                    f"Stage portfolio failed: {result.error_message}",
                )
            print_combined_summary(results)
            return 1

    if args.portfolio_only:
        total_duration = time.perf_counter() - pipeline_start
        if pipeline_run_id:
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "complete" if all(r.success for _, r in results) else "failed",
                [n for n, r in results if r.success],
                total_duration,
                None,
            )
        print_combined_summary(results)
        return 0 if all(r.success for _, r in results) else 1

    # ==========================================================================
    # Stage 3: executor (skipped if --calibrate-only or --portfolio-only)
    # ==========================================================================
    if run_executor:
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
            return 2

        stage_log_id = _log_stage_start(db_url, pipeline_run_id, "executor")
        result = run_paper_executor_stage(args, db_url)
        results.append(("executor", result))
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
                    f"Stage executor failed: {result.error_message}",
                )
            print_combined_summary(results)
            return 1

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
    return 0 if all_success else 1


def run_polling_loop(args: argparse.Namespace, db_url: str) -> int:
    """Run execution stages in a polling loop until interrupted.

    Checks for fresh signals every args.poll_interval seconds. When new signals
    are detected (last_signal_ts > last_execution_ts), runs a full execution pass.
    On failure, sends a Telegram alert if configured.

    Args:
        args: Parsed CLI args (must have poll_interval, dry_run, verbose).
        db_url: Database connection URL.

    Returns:
        Exit code (0 on clean shutdown, 1 on repeated failures).
    """
    print(
        f"[EXEC] Starting polling loop (interval={args.poll_interval}s). "
        "Press Ctrl+C to stop."
    )
    consecutive_failures = 0
    _MAX_CONSECUTIVE_FAILURES = 3

    while True:
        last_signal_ts = _get_last_signal_ts(db_url)
        last_exec_ts = _get_last_execution_ts(db_url)

        if last_signal_ts and (last_exec_ts is None or last_signal_ts > last_exec_ts):
            print(
                f"[EXEC] Fresh signals detected (ts={last_signal_ts.isoformat()}) -- running"
            )
            exit_code = run_single_pass(args, db_url)
            if exit_code == 0:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                print(
                    f"[EXEC] Pass failed (exit_code={exit_code}, "
                    f"consecutive_failures={consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES})"
                )
                try:
                    from ta_lab2.notifications import telegram

                    if telegram.is_configured():
                        telegram.send_alert(
                            "Executor Pipeline Failed",
                            f"Exit code {exit_code}. Last signal ts: {last_signal_ts}. "
                            f"Consecutive failures: {consecutive_failures}",
                            severity="warning",
                        )
                except Exception as exc:
                    print(f"[WARN] Telegram alert failed: {exc}")

                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    print(
                        f"[EXEC] Too many consecutive failures ({consecutive_failures}) -- "
                        "stopping polling loop"
                    )
                    return 1
        else:
            print(
                f"[EXEC] No new signals "
                f"(last_signal={last_signal_ts}, last_exec={last_exec_ts}) "
                f"-- sleeping {args.poll_interval}s"
            )

        time.sleep(args.poll_interval)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_url = args.db_url

    # --- Dead-man switch check (single-shot mode only) ---
    if not args.loop and not args.dry_run and db_url:
        if _check_dead_man(db_url, pipeline_name=PIPELINE_NAME):
            _fire_dead_man_alert(db_url)

    if args.loop:
        if args.dry_run:
            print("[DRY RUN] Would start polling loop -- exiting immediately")
            return 0
        try:
            return run_polling_loop(args, db_url)
        except KeyboardInterrupt:
            print("\n[EXEC] Polling loop interrupted by user -- exiting cleanly")
            return 0

    return run_single_pass(args, db_url)


if __name__ == "__main__":
    raise SystemExit(main())
