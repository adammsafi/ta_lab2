"""
Features pipeline: EMAs, AMAs, returns, desc_stats, macro, cross_asset, regimes, features, garch.

Standalone entry point for the Features layer of the pipeline chain:
  Data -> Features -> Signals -> Execution

Stages (in order):
  1.  emas           -- EMA refreshers (multi-TF)
  2.  returns_ema    -- EMA returns (incremental watermark)
  3.  amas           -- AMA refreshers (multi-TF, all-tfs)
  4.  returns_ama    -- AMA returns (5 alignment sources)
  5.  desc_stats     -- Per-asset descriptive stats + rolling correlations
  6.  macro_features -- FRED macro feature refresh
  7.  macro_regimes  -- 4-dimension macro regime classification
  8.  macro_analytics -- HMM + lead-lag analytics
  9.  cross_asset_agg -- BTC/ETH corr, funding z-scores, crypto-macro corr
  10. regimes        -- Per-asset regime refresher (L0-L2 + hysteresis)
  11. features       -- Feature store refresh (1D timeframe)
  12. garch          -- GARCH conditional volatility forecasts

Usage:
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids 1 --dry-run
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all --chain
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
from ta_lab2.scripts.refresh_utils import get_fresh_ids, parse_ids, resolve_db_url
from ta_lab2.scripts.run_daily_refresh import (
    run_ama_refreshers,
    run_cross_asset_agg,
    run_desc_stats_refresher,
    run_ema_refreshers,
    run_feature_refresh_stage,
    run_garch_forecasts,
    run_macro_analytics,
    run_macro_features,
    run_macro_regimes,
    run_regime_refresher,
    run_returns_ama,
    run_returns_ema,
)

PIPELINE_NAME = "features"

# Canonical stage ordering for --from-stage support
_STAGE_ORDER = [
    "emas",
    "returns_ema",
    "amas",
    "returns_ama",
    "desc_stats",
    "macro_features",
    "macro_regimes",
    "macro_analytics",
    "cross_asset_agg",
    "regimes",
    "features",
    "garch",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Features pipeline: EMAs, AMAs, returns, desc_stats, macro, "
            "cross_asset, regimes, features, garch. "
            "Part of the pipeline chain: Data -> Features -> Signals -> Execution."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full features pipeline for all assets
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all

  # Dry run to preview commands
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids 1 --dry-run

  # Skip bar staleness check (e.g. after explicit bar refresh)
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all --skip-stale-check

  # Skip slow optional stages
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all --no-garch --no-macro-analytics

  # Resume from a specific stage (skip earlier stages)
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all --from-stage regimes

  # Chain into Signals pipeline on success
  python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all --chain
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
        "--skip-stale-check",
        action="store_true",
        help=(
            "Skip bar freshness check before EMA stage "
            "(default: check and filter to fresh IDs only)"
        ),
    )
    p.add_argument(
        "--staleness-hours",
        type=float,
        default=36.0,
        help="Hours threshold for bar freshness check (default: 36)",
    )
    p.add_argument(
        "-n",
        "--num-processes",
        type=int,
        default=None,
        help="Parallel processes for EMA/AMA workers",
    )
    p.add_argument(
        "--no-macro",
        action="store_true",
        help="Skip macro_features stage",
    )
    p.add_argument(
        "--no-macro-regimes",
        action="store_true",
        help="Skip macro_regimes stage",
    )
    p.add_argument(
        "--no-macro-analytics",
        action="store_true",
        help="Skip macro_analytics stage",
    )
    p.add_argument(
        "--no-cross-asset-agg",
        action="store_true",
        help="Skip cross_asset_agg stage",
    )
    p.add_argument(
        "--no-garch",
        action="store_true",
        help="Skip garch stage",
    )
    p.add_argument(
        "--from-stage",
        choices=_STAGE_ORDER,
        default=None,
        metavar="STAGE",
        help=(
            "Start from a specific stage, skipping all prior stages. "
            f"Valid values: {', '.join(_STAGE_ORDER)}"
        ),
    )
    p.add_argument(
        "--chain",
        action="store_true",
        help=(
            "After successful completion, automatically launch the Signals pipeline "
            "via subprocess (--chain passes --ids and --db-url through)"
        ),
    )
    return p


def _should_run(stage: str, from_stage: str | None) -> bool:
    """Return True if this stage should run given --from-stage."""
    if from_stage is None:
        return True
    try:
        start_idx = _STAGE_ORDER.index(from_stage)
        stage_idx = _STAGE_ORDER.index(stage)
        return stage_idx >= start_idx
    except ValueError:
        return True


def main(argv: list[str] | None = None) -> int:
    """Features pipeline entry point. Returns 0 on success, 1 on failure, 2 on kill."""
    p = build_parser()
    args = p.parse_args(argv)

    db_url = args.db_url or resolve_db_url()
    parsed_ids = parse_ids(args.ids)
    from_stage = args.from_stage

    print(f"\n{'=' * 70}")
    print("FEATURES PIPELINE")
    print(f"{'=' * 70}")
    print(f"\nPipeline: {PIPELINE_NAME}")
    print(f"IDs: {args.ids}")
    print(f"Continue on error: {args.continue_on_error}")
    if from_stage:
        print(f"Resuming from stage: {from_stage}")
    if not args.skip_stale_check:
        print(f"Bar staleness threshold: {args.staleness_hours} hours")
    if args.chain:
        print("Chain: will launch Signals pipeline on success")

    results: list[tuple[str, ComponentResult]] = []
    pipeline_run_id: str | None = None
    pipeline_start_time = time.perf_counter()

    if not args.dry_run:
        pipeline_run_id = _start_pipeline_run(db_url, pipeline_name=PIPELINE_NAME)

    # ------------------------------------------------------------------
    # Bar staleness check -- determines ids_for_emas
    # ------------------------------------------------------------------
    ids_for_emas = parsed_ids

    if _should_run("emas", from_stage) and not args.skip_stale_check:
        print(f"\n{'=' * 70}")
        print("CHECKING BAR FRESHNESS")
        print(f"{'=' * 70}")

        fresh_ids, stale_ids = get_fresh_ids(db_url, parsed_ids, args.staleness_hours)

        if stale_ids:
            print(f"\n[WARNING] {len(stale_ids)} ID(s) have stale bars:")
            print(f"  Stale IDs: {stale_ids}")
            print("\n[INFO] Consider running Data pipeline first to refresh bars")
            ids_for_emas = fresh_ids
            print(f"\n[INFO] Running EMAs for {len(fresh_ids)} ID(s) with fresh bars")
        else:
            print(
                f"\n[OK] All {len(fresh_ids) if fresh_ids else 'requested'} ID(s) have fresh bars"
            )

    # ------------------------------------------------------------------
    # Stage 1: emas
    # ------------------------------------------------------------------
    if _should_run("emas", from_stage):
        _slid = _log_stage_start(db_url, pipeline_run_id, "emas")
        ema_result = run_ema_refreshers(args, db_url, ids_for_emas)
        results.append(("emas", ema_result))
        _log_stage_complete(
            db_url,
            _slid,
            ema_result.success,
            ema_result.duration_sec,
            ema_result.error_message,
        )
        if not ema_result.success and not args.continue_on_error:
            print("\n[STOPPED] EMA refreshers failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                ema_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 2: returns_ema
    # ------------------------------------------------------------------
    if _should_run("returns_ema", from_stage):
        _slid = _log_stage_start(db_url, pipeline_run_id, "returns_ema")
        ret_ema_result = run_returns_ema(args, db_url)
        results.append(("returns_ema", ret_ema_result))
        _log_stage_complete(
            db_url,
            _slid,
            ret_ema_result.success,
            ret_ema_result.duration_sec,
            ret_ema_result.error_message,
        )
        if not ret_ema_result.success and not args.continue_on_error:
            print("\n[STOPPED] EMA returns failed, stopping execution")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                ret_ema_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 3: amas
    # EMA IDs carry through to AMAs (same freshness logic as monolith)
    # ------------------------------------------------------------------
    if _should_run("amas", from_stage):
        # When emas ran, use ids_for_emas; otherwise use parsed_ids
        ids_for_amas = ids_for_emas if _should_run("emas", from_stage) else parsed_ids
        _slid = _log_stage_start(db_url, pipeline_run_id, "amas")
        ama_result = run_ama_refreshers(args, db_url, ids_for_amas)
        results.append(("amas", ama_result))
        _log_stage_complete(
            db_url,
            _slid,
            ama_result.success,
            ama_result.duration_sec,
            ama_result.error_message,
        )
        if not ama_result.success and not args.continue_on_error:
            print("\n[STOPPED] AMA refreshers failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                ama_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 4: returns_ama
    # ------------------------------------------------------------------
    if _should_run("returns_ama", from_stage):
        _slid = _log_stage_start(db_url, pipeline_run_id, "returns_ama")
        ret_ama_result = run_returns_ama(args, db_url)
        results.append(("returns_ama", ret_ama_result))
        _log_stage_complete(
            db_url,
            _slid,
            ret_ama_result.success,
            ret_ama_result.duration_sec,
            ret_ama_result.error_message,
        )
        if not ret_ama_result.success and not args.continue_on_error:
            print("\n[STOPPED] AMA returns failed, stopping execution")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                ret_ama_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 5: desc_stats
    # ------------------------------------------------------------------
    if _should_run("desc_stats", from_stage):
        _slid = _log_stage_start(db_url, pipeline_run_id, "desc_stats")
        desc_result = run_desc_stats_refresher(args, db_url, parsed_ids)
        results.append(("desc_stats", desc_result))
        _log_stage_complete(
            db_url,
            _slid,
            desc_result.success,
            desc_result.duration_sec,
            desc_result.error_message,
        )
        if not desc_result.success and not args.continue_on_error:
            print("\n[STOPPED] Desc stats failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                desc_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 6: macro_features
    # ------------------------------------------------------------------
    if _should_run("macro_features", from_stage) and not args.no_macro:
        _slid = _log_stage_start(db_url, pipeline_run_id, "macro_features")
        macro_result = run_macro_features(args)
        results.append(("macro_features", macro_result))
        _log_stage_complete(
            db_url,
            _slid,
            macro_result.success,
            macro_result.duration_sec,
            macro_result.error_message,
        )
        if not macro_result.success and not args.continue_on_error:
            print("\n[STOPPED] Macro feature refresh failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                macro_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 7: macro_regimes
    # ------------------------------------------------------------------
    if _should_run("macro_regimes", from_stage) and not args.no_macro_regimes:
        _slid = _log_stage_start(db_url, pipeline_run_id, "macro_regimes")
        macro_regimes_result = run_macro_regimes(args)
        results.append(("macro_regimes", macro_regimes_result))
        _log_stage_complete(
            db_url,
            _slid,
            macro_regimes_result.success,
            macro_regimes_result.duration_sec,
            macro_regimes_result.error_message,
        )
        if not macro_regimes_result.success and not args.continue_on_error:
            print("\n[STOPPED] Macro regime classification failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                macro_regimes_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 8: macro_analytics
    # ------------------------------------------------------------------
    if _should_run("macro_analytics", from_stage) and not args.no_macro_analytics:
        _slid = _log_stage_start(db_url, pipeline_run_id, "macro_analytics")
        macro_analytics_result = run_macro_analytics(args)
        results.append(("macro_analytics", macro_analytics_result))
        _log_stage_complete(
            db_url,
            _slid,
            macro_analytics_result.success,
            macro_analytics_result.duration_sec,
            macro_analytics_result.error_message,
        )
        if not macro_analytics_result.success and not args.continue_on_error:
            print("\n[STOPPED] Macro analytics failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                macro_analytics_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 9: cross_asset_agg
    # ------------------------------------------------------------------
    if _should_run("cross_asset_agg", from_stage) and not args.no_cross_asset_agg:
        _slid = _log_stage_start(db_url, pipeline_run_id, "cross_asset_agg")
        cross_asset_result = run_cross_asset_agg(args)
        results.append(("cross_asset_agg", cross_asset_result))
        _log_stage_complete(
            db_url,
            _slid,
            cross_asset_result.success,
            cross_asset_result.duration_sec,
            cross_asset_result.error_message,
        )
        if not cross_asset_result.success and not args.continue_on_error:
            print("\n[STOPPED] Cross-asset aggregation failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                cross_asset_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 10: regimes
    # ------------------------------------------------------------------
    if _should_run("regimes", from_stage):
        _slid = _log_stage_start(db_url, pipeline_run_id, "regimes")
        regime_result = run_regime_refresher(args, db_url, parsed_ids)
        results.append(("regimes", regime_result))
        _log_stage_complete(
            db_url,
            _slid,
            regime_result.success,
            regime_result.duration_sec,
            regime_result.error_message,
        )
        if not regime_result.success and not args.continue_on_error:
            print("\n[STOPPED] Regime refresher failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                regime_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 11: features
    # ------------------------------------------------------------------
    if _should_run("features", from_stage):
        _slid = _log_stage_start(db_url, pipeline_run_id, "features")
        feature_result = run_feature_refresh_stage(args, db_url)
        results.append(("features", feature_result))
        _log_stage_complete(
            db_url,
            _slid,
            feature_result.success,
            feature_result.duration_sec,
            feature_result.error_message,
        )
        if not feature_result.success and not args.continue_on_error:
            print("\n[STOPPED] Feature refresh failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                feature_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Stage 12: garch
    # ------------------------------------------------------------------
    if _should_run("garch", from_stage) and not args.no_garch:
        _slid = _log_stage_start(db_url, pipeline_run_id, "garch")
        garch_result = run_garch_forecasts(args, db_url)
        results.append(("garch", garch_result))
        _log_stage_complete(
            db_url,
            _slid,
            garch_result.success,
            garch_result.duration_sec,
            garch_result.error_message,
        )
        if not garch_result.success and not args.continue_on_error:
            print("\n[STOPPED] GARCH forecast refresh failed, stopping execution")
            print("(Use --continue-on-error to run remaining components)")
            _complete_pipeline_run(
                db_url,
                pipeline_run_id,
                "failed",
                [name for name, r in results if r.success],
                time.perf_counter() - pipeline_start_time,
                garch_result.error_message,
            )
            return 1
        if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
            return 2

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------
    total_duration = time.perf_counter() - pipeline_start_time
    stages_completed = [name for name, r in results if r.success]
    all_success = all(r.success for _, r in results)
    status = "complete" if all_success else "failed"

    if pipeline_run_id:
        _complete_pipeline_run(
            db_url,
            pipeline_run_id,
            status,
            stages_completed,
            total_duration,
            None if all_success else "One or more stages failed",
        )

    print_combined_summary(results)

    # ------------------------------------------------------------------
    # Chain: launch Signals pipeline
    # ------------------------------------------------------------------
    if args.chain and all_success:
        print(f"\n{'=' * 70}")
        print("CHAINING: Launching Signals pipeline")
        print(f"{'=' * 70}")
        chain_cmd = [
            sys.executable,
            "-m",
            "ta_lab2.scripts.pipelines.run_signals_pipeline",
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
