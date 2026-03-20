"""
Refresh calendar-aligned AMA tables from bar data.

Targets:
  - public.ama_multi_tf_cal_us   (US calendar-aligned bars)
  - public.ama_multi_tf_cal_iso  (ISO calendar-aligned bars)

Uses:
  - CalUSAMAFeature  / CalISOAMAFeature from ama_multi_tf_cal
  - BaseAMARefresher for standardised CLI, state management, and parallelism

CLI usage:
  # Refresh US calendar scheme for asset 1
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf_cal_from_bars \\
      --ids 1 --all-tfs --scheme us

  # Refresh ISO calendar scheme for all assets
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf_cal_from_bars \\
      --ids all --all-tfs --scheme iso

  # Refresh both schemes for assets 1 and 52
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf_cal_from_bars \\
      --ids 1,52 --all-tfs --scheme both

  # KAMA only, full rebuild for US scheme
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf_cal_from_bars \\
      --ids all --all-tfs --scheme us --indicators KAMA --full-rebuild

  # Dry run
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf_cal_from_bars \\
      --ids 1 --all-tfs --scheme both --dry-run
"""

from __future__ import annotations

import argparse
from multiprocessing import Pool, cpu_count

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.features.ama.ama_multi_tf_cal import CalUSAMAFeature, CalISOAMAFeature
from ta_lab2.features.ama.ama_multi_timeframe import populate_dim_ama_params
from ta_lab2.features.ama.ama_params import ALL_AMA_PARAMS
from ta_lab2.features.ama.base_ama_feature import AMAFeatureConfig, TFSpec
from ta_lab2.scripts.amas.ama_state_manager import AMAStateManager
from ta_lab2.scripts.amas.base_ama_refresher import (
    BaseAMARefresher,
    AMAWorkerTask,
)
from ta_lab2.scripts.bars.common_snapshot_contract import load_all_ids
from ta_lab2.scripts.emas.logging_config import setup_logging
from ta_lab2.scripts.refresh_utils import resolve_db_url


# =============================================================================
# Scheme Map
# =============================================================================

SCHEME_MAP = {
    "us": {
        "feature_class": CalUSAMAFeature,
        "bars_table": "price_bars_multi_tf_cal_us",
        "output_table": "ama_multi_tf_cal_us",
        "state_table": "ama_multi_tf_cal_us_state",
        "description": "US calendar-aligned AMA",
    },
    "iso": {
        "feature_class": CalISOAMAFeature,
        "bars_table": "price_bars_multi_tf_cal_iso",
        "output_table": "ama_multi_tf_cal_iso",
        "state_table": "ama_multi_tf_cal_iso_state",
        "description": "ISO calendar-aligned AMA",
    },
}


# =============================================================================
# Worker Function (Module-level for pickling)
# =============================================================================


def _cal_ama_worker(task: AMAWorkerTask) -> int:
    """
    Worker function for parallel calendar AMA computation.

    Called by multiprocessing.Pool.map(). Must be module-level (not a method)
    for pickling to work across processes.

    Creates its own engine with NullPool to prevent "too many clients" errors.
    Uses CalUSAMAFeature or CalISOAMAFeature based on task.extra_config["scheme"].

    Args:
        task: AMAWorkerTask with all parameters.

    Returns:
        Number of rows written (0 if worker failed or no data).
    """
    import logging
    import pandas as pd

    _logger = logging.getLogger(f"ama_cal_worker.{task.asset_id}")

    scheme = task.extra_config.get("scheme", "us")

    try:
        # CRITICAL: NullPool prevents connection pooling across processes
        engine = create_engine(task.db_url, poolclass=NullPool)

        # Select feature class by scheme
        if scheme == "us":
            feature_class = CalUSAMAFeature
        else:
            feature_class = CalISOAMAFeature

        config = AMAFeatureConfig(
            param_sets=task.param_sets,
            output_schema=task.output_schema,
            output_table=task.output_table,
        )
        feature = feature_class(
            engine=engine,
            config=config,
            bars_schema=task.bars_schema,
            bars_table=task.bars_table,
        )

        state_manager = AMAStateManager(engine, task.state_table)

        # Load TF specs for this calendar scheme
        all_tf_specs: list[TFSpec] = feature._get_timeframes(engine)

        # Filter to requested subset if provided
        if task.tf_subset:
            tf_set = set(task.tf_subset)
            tf_specs = [s for s in all_tf_specs if s.tf in tf_set]
        else:
            tf_specs = all_tf_specs

        if not tf_specs:
            _logger.warning(
                "No TF specs found for asset_id=%s scheme=%s (tf_subset=%s)",
                task.asset_id,
                scheme,
                task.tf_subset,
            )
            engine.dispose()
            return 0

        # Discover which venue_ids exist for this asset in the bars table
        from sqlalchemy import text as sa_text

        with engine.connect() as conn:
            venue_rows = conn.execute(
                sa_text(
                    f"SELECT DISTINCT venue_id FROM {task.bars_schema}.{task.bars_table}"
                    f" WHERE id = :id ORDER BY venue_id"
                ),
                {"id": task.asset_id},
            ).fetchall()
        venue_ids = [int(r[0]) for r in venue_rows] if venue_rows else [1]

        total_rows = 0
        state_updates: list[dict] = []

        # Preload ALL bars for this asset in 1 query (all TFs, all venues)
        feature.preload_all_bars(engine, task.asset_id)

        # Load ALL states for this asset in 1 query (instead of per-param-set per-TF)
        if not task.full_rebuild:
            all_states = state_manager.load_all_states(task.asset_id)
            ps_keys = {(ps.indicator, ps.params_hash) for ps in task.param_sets}
        else:
            all_states = pd.DataFrame()

        for venue_id in venue_ids:
            for tf_spec in tf_specs:
                # Determine start_ts from state (or None for full history)
                if task.full_rebuild:
                    start_ts = None
                else:
                    tf_states = (
                        all_states[all_states["tf"] == tf_spec.tf]
                        if not all_states.empty
                        else all_states
                    )
                    if tf_states.empty:
                        start_ts = None
                    else:
                        existing = set(
                            zip(tf_states["indicator"], tf_states["params_hash"])
                        )
                        if not ps_keys.issubset(existing):
                            start_ts = None
                        else:
                            mask = tf_states.apply(
                                lambda r: (r["indicator"], r["params_hash"]) in ps_keys,
                                axis=1,
                            )
                            min_ts = tf_states.loc[mask, "last_canonical_ts"].min()
                            start_ts = (
                                pd.Timestamp(min_ts) if pd.notna(min_ts) else None
                            )

                _logger.debug(
                    "asset_id=%s tf=%s venue_id=%s scheme=%s start_ts=%s param_sets=%d",
                    task.asset_id,
                    tf_spec.tf,
                    venue_id,
                    scheme,
                    start_ts,
                    len(task.param_sets),
                )

                df = feature.compute_for_asset_tf(
                    engine=engine,
                    asset_id=task.asset_id,
                    tf=tf_spec.tf,
                    tf_days=tf_spec.tf_days,
                    param_sets=task.param_sets,
                    start_ts=start_ts,
                    venue_id=venue_id,
                )

                if df.empty:
                    _logger.debug(
                        "No AMA rows for asset_id=%s tf=%s venue_id=%s scheme=%s — skipping write",
                        task.asset_id,
                        tf_spec.tf,
                        venue_id,
                        scheme,
                    )
                    continue

                rows = feature.write_to_db(
                    engine=engine,
                    df=df,
                    schema=task.output_schema,
                    table=task.output_table,
                )
                total_rows += rows

                # Collect state updates (batch write after all loops)
                for ps in task.param_sets:
                    ps_mask = (df["indicator"] == ps.indicator) & (
                        df["params_hash"] == ps.params_hash
                    )
                    ps_df = df[ps_mask]
                    if ps_df.empty:
                        continue

                    latest_ts = ps_df["ts"].max()
                    if pd.notna(latest_ts):
                        state_updates.append(
                            {
                                "id": task.asset_id,
                                "venue_id": 1,  # state tracked at default venue
                                "tf": tf_spec.tf,
                                "indicator": ps.indicator,
                                "params_hash": ps.params_hash,
                                "last_canonical_ts": pd.Timestamp(
                                    latest_ts
                                ).to_pydatetime(),
                            }
                        )

        # Batch upsert all state watermarks in 1 DB call
        state_manager.save_states_batch(state_updates)

        _logger.info(
            "asset_id=%s scheme=%s: wrote %d rows across %d TFs",
            task.asset_id,
            scheme,
            total_rows,
            len(tf_specs),
        )
        engine.dispose()
        return total_rows

    except Exception as exc:
        _logger.error(
            "Worker failed for asset_id=%s scheme=%s: %s",
            task.asset_id,
            scheme,
            exc,
            exc_info=True,
        )
        return 0


# =============================================================================
# Refresher Implementation
# =============================================================================


class CalAMARefresher(BaseAMARefresher):
    """
    AMA refresher for calendar-aligned tables (US/ISO schemes).

    Handles --scheme us/iso/both by running one or two scheme-specific
    refresher passes. Each pass uses the corresponding CalUSAMAFeature
    or CalISOAMAFeature and its own state table.

    Note: create_argument_parser() uses cls() for description — the default
    constructor is used just to access get_description(), so scheme is not
    required at construction time for argument parsing.
    """

    def __init__(self, scheme: str = "us") -> None:
        """
        Initialise CalAMARefresher.

        Args:
            scheme: Calendar scheme for this refresher instance ("us" or "iso").
                    Used when the refresher runs a single scheme.
        """
        self.scheme = scheme

    # =========================================================================
    # Abstract Method Implementations (BaseAMARefresher)
    # =========================================================================

    def get_default_output_table(self) -> str:
        """Return default output table name for the current scheme."""
        return SCHEME_MAP[self.scheme]["output_table"]

    def get_default_state_table(self) -> str:
        """Return default state table name for the current scheme."""
        return SCHEME_MAP[self.scheme]["state_table"]

    def get_description(self) -> str:
        return (
            "Refresh calendar-aligned AMA tables (US/ISO schemes).\n\n"
            "Data sources:\n"
            "  price_bars_multi_tf_cal_us  -> ama_multi_tf_cal_us\n"
            "  price_bars_multi_tf_cal_iso -> ama_multi_tf_cal_iso\n\n"
            "Use --scheme us/iso/both to select which calendar scheme to refresh."
        )

    def get_bars_table(self) -> str:
        """Return source bars table for the current scheme."""
        return SCHEME_MAP[self.scheme]["bars_table"]

    # =========================================================================
    # CLI
    # =========================================================================

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """Create CLI argument parser with calendar-specific --scheme argument."""
        # BaseAMARefresher.create_argument_parser() calls cls() — needs no-arg constructor
        p = super().create_argument_parser()

        # Calendar-specific arguments (insert before logging args)
        p.add_argument(
            "--scheme",
            default="both",
            choices=["us", "iso", "both"],
            help=("Calendar scheme to refresh: us, iso, or both. Default: both"),
        )
        p.add_argument(
            "--out-us",
            default="ama_multi_tf_cal_us",
            help="Output table name for US scheme (default: ama_multi_tf_cal_us).",
        )
        p.add_argument(
            "--out-iso",
            default="ama_multi_tf_cal_iso",
            help="Output table name for ISO scheme (default: ama_multi_tf_cal_iso).",
        )

        return p

    @classmethod
    def main(cls, argv=None) -> None:
        """CLI entry point — delegates to main_for_schemes."""
        cls.main_for_schemes(argv)

    @classmethod
    def main_for_schemes(cls, argv=None) -> None:
        """
        CLI entry point that handles --scheme both by running two refresher passes.
        """
        parser = cls.create_argument_parser()
        args = parser.parse_args(argv)

        if args.scheme == "both":
            schemes_to_run = ["us", "iso"]
        else:
            schemes_to_run = [args.scheme]

        for scheme in schemes_to_run:
            print(f"\n{'=' * 80}")
            print(f"Running calendar AMA refresh for scheme: {scheme.upper()}")
            print(f"{'=' * 80}\n")

            refresher = cls(scheme=scheme)
            refresher._run_for_scheme(args, scheme)

    # =========================================================================
    # Scheme-specific run
    # =========================================================================

    def _run_for_scheme(self, args: argparse.Namespace, scheme: str) -> None:
        """
        Execute AMA refresh for a single calendar scheme.

        Mirrors BaseAMARefresher.run() but selects feature class, output table,
        and state table based on the scheme. Uses _cal_ama_worker for multiprocessing.

        Args:
            args: Parsed argparse.Namespace.
            scheme: Calendar scheme ("us" or "iso").
        """

        scheme_cfg = SCHEME_MAP[scheme]

        # Set up logging
        log_level = getattr(args, "log_level", "INFO")
        log_file = getattr(args, "log_file", None)
        quiet = getattr(args, "quiet", False)
        debug = getattr(args, "debug", False)
        run_logger = setup_logging(
            name=f"CalAMARefresher.{scheme.upper()}",
            level=log_level,
            log_file=log_file,
            quiet=quiet,
            debug=debug,
        )

        # Resolve DB URL
        db_url = resolve_db_url(getattr(args, "db_url", None))
        engine = create_engine(db_url)

        # Resolve output and state table names
        if scheme == "us":
            output_table = getattr(args, "out_us", None) or scheme_cfg["output_table"]
        else:
            output_table = getattr(args, "out_iso", None) or scheme_cfg["output_table"]

        output_schema = getattr(args, "out_schema", "public")
        state_table = getattr(args, "state_table", None) or scheme_cfg["state_table"]
        bars_table = scheme_cfg["bars_table"]
        bars_schema = "public"

        run_logger.info(
            "Starting CalAMARefresher[%s]: output=%s.%s state=%s",
            scheme.upper(),
            output_schema,
            output_table,
            state_table,
        )

        # Ensure state table exists
        state_manager = AMAStateManager(engine, state_table)
        state_manager.ensure_state_table()

        # Populate dim_ama_params (idempotent seed)
        populate_dim_ama_params(engine)

        # Resolve IDs
        ids_arg = getattr(args, "ids", "all").strip()
        if ids_arg.lower() == "all":
            source_table = f"{bars_schema}.{bars_table}"
            ids = load_all_ids(db_url, source_table)
            run_logger.info("Loaded %d IDs from %s", len(ids), source_table)
        else:
            ids = [int(x.strip()) for x in ids_arg.split(",") if x.strip()]
        run_logger.info("Resolved %d asset IDs", len(ids))

        # Resolve param_sets (all or filtered by --indicators)
        indicators_arg = getattr(args, "indicators", None)
        if not indicators_arg:
            param_sets = list(ALL_AMA_PARAMS)
        else:
            requested = {ind.strip().upper() for ind in indicators_arg.split(",")}
            param_sets = [ps for ps in ALL_AMA_PARAMS if ps.indicator in requested]
            if not param_sets:
                run_logger.warning(
                    "No matching param_sets for --indicators=%s — using all",
                    indicators_arg,
                )
                param_sets = list(ALL_AMA_PARAMS)

        run_logger.info(
            "Using %d param_sets across indicators: %s",
            len(param_sets),
            sorted({ps.indicator for ps in param_sets}),
        )

        # Resolve TF subset
        tf_arg = getattr(args, "tf", None)
        all_tfs = getattr(args, "all_tfs", False)
        if tf_arg:
            tf_subset = [tf_arg]
            run_logger.info("Using single TF: %s", tf_arg)
        elif all_tfs:
            tf_subset = None
            run_logger.info("Using all calendar TFs for scheme=%s", scheme.upper())
        else:
            run_logger.warning(
                "Neither --tf nor --all-tfs specified — defaulting to all TFs."
            )
            tf_subset = None

        # Full rebuild: clear state for affected IDs
        if getattr(args, "full_rebuild", False):
            run_logger.info(
                "Full rebuild requested — clearing state for %d IDs", len(ids)
            )
            for asset_id in ids:
                state_manager.clear_state(asset_id)

        # Dry run: just log the plan
        if getattr(args, "dry_run", False):
            tf_count = (
                len(tf_subset)
                if tf_subset
                else f"(all calendar TFs for {scheme.upper()})"
            )
            run_logger.info(
                "DRY RUN — would process: %d IDs x %s TFs x %d param_sets",
                len(ids),
                tf_count,
                len(param_sets),
            )
            run_logger.info("DRY RUN complete — no DB writes performed")
            engine.dispose()
            return

        # Build worker tasks
        db_url_with_pw = engine.url.render_as_string(hide_password=False)
        num_processes_arg = getattr(args, "num_processes", None)
        num_processes = (
            num_processes_arg
            if num_processes_arg and num_processes_arg > 0
            else min(6, cpu_count())
        )

        tasks = [
            AMAWorkerTask(
                asset_id=asset_id,
                db_url=db_url_with_pw,
                param_sets=param_sets,
                state_table=state_table,
                output_schema=output_schema,
                output_table=output_table,
                bars_schema=bars_schema,
                bars_table=bars_table,
                tf_subset=tf_subset,
                full_rebuild=getattr(args, "full_rebuild", False),
                extra_config={"scheme": scheme},
            )
            for asset_id in ids
        ]

        run_logger.info(
            "Dispatching %d worker tasks with %d processes",
            len(tasks),
            num_processes,
        )

        # Execute workers in parallel
        if num_processes == 1 or len(tasks) == 1:
            results = [_cal_ama_worker(t) for t in tasks]
        else:
            try:
                with Pool(processes=num_processes) as pool:
                    results = pool.map(_cal_ama_worker, tasks)
            except Exception as exc:
                run_logger.error("Pool execution failed: %s", exc, exc_info=True)
                results = [0] * len(tasks)

        total_rows = sum(results)
        successful = sum(1 for r in results if r > 0)
        failed = len(results) - successful

        run_logger.info(
            "Refresh complete [%s]: %d total rows, %d/%d assets succeeded, %d failed",
            scheme.upper(),
            total_rows,
            successful,
            len(ids),
            failed,
        )

        engine.dispose()


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    CalAMARefresher.main_for_schemes()
