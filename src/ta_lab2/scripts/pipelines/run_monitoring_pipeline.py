#!/usr/bin/env python
"""
Monitoring pipeline: drift_monitor, pipeline_alerts, stats.

This pipeline runs on the Oracle VM on an external timer (systemd timer or cron,
configured in Phase 113). It runs once and exits -- no polling loop needed since
the external timer handles scheduling.

Stage order:
  1. drift_monitor    -- requires --paper-start; silently skipped if absent
  2. pipeline_alerts  -- Telegram digest (non-blocking: failure never stops pipeline)
  3. stats            -- data quality gate (failure IS terminal)

Usage:
    # Dry run
    python -m ta_lab2.scripts.pipelines.run_monitoring_pipeline --dry-run

    # With drift monitoring enabled
    python -m ta_lab2.scripts.pipelines.run_monitoring_pipeline \\
        --db-url postgresql://... \\
        --paper-start 2025-01-01

    # Without Telegram
    python -m ta_lab2.scripts.pipelines.run_monitoring_pipeline --no-telegram

    # Stats only
    python -m ta_lab2.scripts.pipelines.run_monitoring_pipeline --stats-only
"""

from __future__ import annotations

import argparse
import os
import time

from ta_lab2.scripts.pipeline_utils import (
    ComponentResult,
    _check_dead_man,
    _complete_pipeline_run,
    _fire_dead_man_alert,
    _log_stage_complete,
    _log_stage_start,
    _maybe_kill,
    _start_pipeline_run,
    print_combined_summary,
    run_pipeline_completion_alert,
)
from ta_lab2.scripts.run_daily_refresh import (
    run_drift_monitor_stage,
    run_stats_runners,
)

PIPELINE_NAME = "monitoring"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitoring pipeline: drift_monitor -> pipeline_alerts -> stats",
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
        "--paper-start",
        default=None,
        help="Paper trading start date (YYYY-MM-DD) -- required for drift monitor",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Suppress Telegram alerts from pipeline_alerts stage",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Run only the stats stage (skip drift and pipeline_alerts)",
    )
    return parser.parse_args(argv)


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

    # ==========================================================================
    # Stage 1: drift_monitor (silently skipped if --paper-start not provided)
    # ==========================================================================
    if not args.stats_only:
        if getattr(args, "paper_start", None):
            if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
                return 2

            stage_log_id = _log_stage_start(db_url, pipeline_run_id, "drift_monitor")
            result = run_drift_monitor_stage(args, db_url)
            results.append(("drift_monitor", result))
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
                        f"Stage drift_monitor failed: {result.error_message}",
                    )
                print_combined_summary(results)
                return 1
        else:
            print(
                "\n[INFO] drift_monitor skipped: --paper-start not provided "
                "(pass --paper-start YYYY-MM-DD to enable)"
            )

        # ======================================================================
        # Stage 2: pipeline_alerts (non-blocking -- failure never stops pipeline)
        # ======================================================================
        if not args.no_telegram:
            if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
                return 2

            stage_log_id = _log_stage_start(db_url, pipeline_run_id, "pipeline_alerts")
            result = run_pipeline_completion_alert(args, db_url, results)
            results.append(("pipeline_alerts", result))
            _log_stage_complete(
                db_url,
                stage_log_id,
                result.success,
                result.duration_sec,
                result.error_message,
            )
            # pipeline_alerts is always non-blocking: run_pipeline_completion_alert
            # returns success=True even on failure (see pipeline_utils.py)

    # ==========================================================================
    # Stage 3: stats (data quality gate -- failure IS terminal)
    # ==========================================================================
    if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start):
        return 2

    stage_log_id = _log_stage_start(db_url, pipeline_run_id, "stats")
    result = run_stats_runners(args, db_url)
    results.append(("stats", result))
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
                f"Stage stats failed: {result.error_message}",
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


if __name__ == "__main__":
    raise SystemExit(main())
