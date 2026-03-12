"""
BaseAMARefresher - Abstract base class for AMA refresh scripts.

Template Method Pattern for all AMA table refresh scripts:
- Standardised CLI argument parsing
- State management via AMAStateManager
- ID and TF resolution
- Parallel asset processing with NullPool workers
- Incremental watermark-based refresh

Subclasses implement:
- get_feature_class(): Return the concrete BaseAMAFeature subclass to use
- get_default_output_table(): Return the default output table name
- get_default_state_table(): Return the default state table name
- get_description(): Return script description string for --help

Design choices:
- AMA workers receive AMAWorkerTask (not EMA WorkerTask) — uses param_sets list
- NullPool is REQUIRED for multiprocessing workers (prevents "too many clients")
- State is updated per (id, tf, indicator, params_hash) after each successful write
- --full-rebuild clears state for affected IDs before processing

Migration note: AMA refreshers do NOT inherit from BaseEMARefresher because
the PK structure (indicator + params_hash vs period) and state management
are fundamentally different.
"""

from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from typing import Any, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ta_lab2.features.ama.ama_multi_timeframe import populate_dim_ama_params
from ta_lab2.features.ama.ama_params import ALL_AMA_PARAMS, AMAParamSet
from ta_lab2.features.ama.base_ama_feature import AMAFeatureConfig, TFSpec
from ta_lab2.scripts.amas.ama_state_manager import AMAStateManager
from ta_lab2.scripts.bars.common_snapshot_contract import load_all_ids
from ta_lab2.scripts.emas.logging_config import add_logging_args, setup_logging
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)


# =============================================================================
# Worker Task
# =============================================================================


@dataclass
class AMAWorkerTask:
    """
    Task for a single AMA worker process.

    Encapsulates all parameters needed to compute AMAs for one asset_id
    across a subset (or all) of TFs and param_sets.

    Attributes:
        asset_id: Asset primary key from dim_assets.
        db_url: Full database URL with password (not masked).
        param_sets: Which AMAParamSet instances to compute.
        state_table: State table name for AMAStateManager.
        output_schema: Target schema name.
        output_table: Target AMA table name.
        bars_schema: Schema for source bars table.
        bars_table: Source bars table name.
        tf_subset: Optional list of TF labels to process. None = all TFs.
        full_rebuild: If True, skip state watermark and process full history.
        extra_config: Additional config for subclass-specific overrides.
    """

    asset_id: int
    db_url: str
    param_sets: list[AMAParamSet]
    state_table: str
    output_schema: str
    output_table: str
    bars_schema: str = "public"
    bars_table: str = "price_bars_multi_tf"
    tf_subset: Optional[list[str]] = None
    full_rebuild: bool = False
    extra_config: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Module-level worker function (must be picklable for multiprocessing)
# =============================================================================


def _ama_worker(task: AMAWorkerTask) -> int:
    """
    Worker function for parallel AMA computation.

    Called by multiprocessing.Pool.map(). Must be module-level (not a method)
    for pickling to work across processes.

    Creates its own engine with NullPool — CRITICAL for multiprocessing to
    prevent "too many clients already" PostgreSQL errors.

    Args:
        task: AMAWorkerTask with all parameters.

    Returns:
        Number of rows written (0 if worker failed or no data).
    """
    _logger = logging.getLogger(f"ama_worker.{task.asset_id}")

    try:
        # CRITICAL: NullPool prevents connection pooling across processes
        engine = create_engine(task.db_url, poolclass=NullPool)

        from ta_lab2.features.ama.ama_multi_timeframe import MultiTFAMAFeature

        config = AMAFeatureConfig(
            param_sets=task.param_sets,
            output_schema=task.output_schema,
            output_table=task.output_table,
        )
        feature = MultiTFAMAFeature(
            engine=engine,
            config=config,
            bars_schema=task.bars_schema,
            bars_table=task.bars_table,
        )

        state_manager = AMAStateManager(engine, task.state_table)

        # Load all TF specs for this asset
        all_tf_specs: list[TFSpec] = feature._get_timeframes(engine)

        # Filter to requested subset if provided
        if task.tf_subset:
            tf_set = set(task.tf_subset)
            tf_specs = [s for s in all_tf_specs if s.tf in tf_set]
        else:
            tf_specs = all_tf_specs

        if not tf_specs:
            _logger.warning(
                "No TF specs found for asset_id=%s (tf_subset=%s)",
                task.asset_id,
                task.tf_subset,
            )
            engine.dispose()
            return 0

        total_rows = 0

        for tf_spec in tf_specs:
            # Determine start_ts from state (or None for full history)
            if task.full_rebuild:
                start_ts = None
            else:
                # Find the minimum last_canonical_ts across all param_sets for this TF
                # This ensures we recompute any param_set that has fallen behind
                min_watermark: Optional[pd.Timestamp] = None
                for ps in task.param_sets:
                    wm = state_manager.load_state(
                        asset_id=task.asset_id,
                        tf=tf_spec.tf,
                        indicator=ps.indicator,
                        params_hash=ps.params_hash,
                    )
                    if wm is None:
                        # At least one param_set has no state — do full history
                        min_watermark = None
                        break
                    wm_ts = pd.Timestamp(wm)
                    if min_watermark is None or wm_ts < min_watermark:
                        min_watermark = wm_ts

                start_ts = min_watermark

            _logger.debug(
                "asset_id=%s tf=%s start_ts=%s param_sets=%d",
                task.asset_id,
                tf_spec.tf,
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
            )

            if df.empty:
                _logger.debug(
                    "No AMA rows for asset_id=%s tf=%s — skipping write",
                    task.asset_id,
                    tf_spec.tf,
                )
                continue

            rows = feature.write_to_db(
                engine=engine,
                df=df,
                schema=task.output_schema,
                table=task.output_table,
            )
            total_rows += rows

            # Update state watermarks per param_set
            for ps in task.param_sets:
                ps_mask = (df["indicator"] == ps.indicator) & (
                    df["params_hash"] == ps.params_hash
                )
                ps_df = df[ps_mask]
                if ps_df.empty:
                    continue

                # Get most recent ts for this param_set
                latest_ts = ps_df["ts"].max()
                if pd.notna(latest_ts):
                    state_manager.save_state(
                        asset_id=task.asset_id,
                        tf=tf_spec.tf,
                        indicator=ps.indicator,
                        params_hash=ps.params_hash,
                        last_ts=pd.Timestamp(latest_ts).to_pydatetime(),
                    )

        _logger.info(
            "asset_id=%s: wrote %d rows across %d TFs",
            task.asset_id,
            total_rows,
            len(tf_specs),
        )
        engine.dispose()
        return total_rows

    except Exception as exc:
        _logger.error(
            "Worker failed for asset_id=%s: %s", task.asset_id, exc, exc_info=True
        )
        return 0


# =============================================================================
# BaseAMARefresher
# =============================================================================


class BaseAMARefresher(ABC):
    """
    Abstract base class for AMA table refresh scripts.

    Template Method Pattern:
    - Defines CLI parsing, state management, and multiprocessing flow
    - Subclasses provide table names and the concrete feature class

    Usage pattern (subclass):
        class MultiTFAMARefresher(BaseAMARefresher):
            def get_default_output_table(self):
                return "ama_multi_tf"
            def get_default_state_table(self):
                return "public.ama_multi_tf_state"
            def get_description(self):
                return "Refresh ama_multi_tf from multi-TF bars."

    Command line usage:
        python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --tf 1D
        python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids all --all-tfs
        python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --all-tfs \\
            --indicators KAMA --full-rebuild
    """

    # =========================================================================
    # Abstract Methods
    # =========================================================================

    @abstractmethod
    def get_default_output_table(self) -> str:
        """Return default output table name (e.g. 'ama_multi_tf')."""

    @abstractmethod
    def get_default_state_table(self) -> str:
        """Return default state table name (e.g. 'public.ama_multi_tf_state')."""

    @abstractmethod
    def get_description(self) -> str:
        """Return script description for --help output."""

    def get_bars_table(self) -> str:
        """Return source bars table name. Override in calendar subclasses."""
        return "price_bars_multi_tf"

    def get_bars_schema(self) -> str:
        """Return source bars schema. Override if needed."""
        return "public"

    # =========================================================================
    # CLI Entry Point
    # =========================================================================

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create CLI argument parser with all standard AMA refresh arguments.

        Returns:
            ArgumentParser configured with --ids, --tf, --all-tfs, --indicators,
            --full-rebuild, --num-processes, --dry-run, --db-url, and logging args.
        """
        instance = cls()
        p = argparse.ArgumentParser(
            description=instance.get_description(),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Refresh asset 1 on 1D timeframe
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --tf 1D

  # Refresh all assets on all TFs (incremental by default)
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids all --all-tfs

  # KAMA only for assets 1 and 52
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1,52 --all-tfs --indicators KAMA

  # Full rebuild for asset 1
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --all-tfs --full-rebuild

  # Dry run (no DB writes)
  python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --tf 1D --dry-run
""",
        )

        # Database
        p.add_argument(
            "--db-url",
            default=None,
            help="SQLAlchemy DB URL. Defaults to db_config.env / TARGET_DB_URL.",
        )

        # Input selection
        p.add_argument(
            "--ids",
            default="all",
            help="Comma-separated asset IDs (e.g. '1,52') or 'all' (default: all).",
        )

        # TF selection (mutually exclusive)
        tf_group = p.add_mutually_exclusive_group()
        tf_group.add_argument(
            "--tf",
            default=None,
            help="Single timeframe to refresh (e.g. '1D', '7D').",
        )
        tf_group.add_argument(
            "--all-tfs",
            action="store_true",
            default=False,
            help="Refresh all TFs from dim_timeframe.",
        )

        # Indicator filter
        p.add_argument(
            "--indicators",
            default=None,
            help=(
                "Comma-separated indicator names to run (e.g. 'KAMA,DEMA'). "
                "Default: all 4 indicators (KAMA, DEMA, TEMA, HMA)."
            ),
        )

        # Execution mode
        p.add_argument(
            "--full-rebuild",
            action="store_true",
            default=False,
            help="Clear state and recompute full history (default: incremental).",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Resolve IDs and TFs but do not write to DB.",
        )
        p.add_argument(
            "--num-processes",
            type=int,
            default=None,
            help="Parallel worker processes. Default: min(6, cpu_count()).",
        )

        # Output table overrides (rarely needed)
        p.add_argument("--out-schema", default="public", help="Output schema.")
        p.add_argument(
            "--out-table",
            default=None,
            help="Output table name override.",
        )
        p.add_argument(
            "--state-table",
            default=None,
            help="State table name override.",
        )

        # Logging
        add_logging_args(p)

        return p

    @classmethod
    def main(cls, argv=None) -> None:
        """Standard CLI entry point: parse args and run."""
        parser = cls.create_argument_parser()
        args = parser.parse_args(argv)
        instance = cls()
        instance.run(args)

    # =========================================================================
    # Run
    # =========================================================================

    def run(self, args: argparse.Namespace) -> None:
        """
        Main execution flow.

        Steps:
        1. Set up logging
        2. Resolve DB URL and create engine
        3. Ensure state table exists
        4. Populate dim_ama_params (idempotent)
        5. Resolve IDs and TFs
        6. Filter param_sets by --indicators if provided
        7. If --full-rebuild: clear state for affected IDs
        8. If --dry-run: log plan and exit
        9. Dispatch parallel workers (one per asset_id)
        10. Report summary

        Args:
            args: Parsed argparse.Namespace from create_argument_parser().
        """
        # Set up logging
        log_level = getattr(args, "log_level", "INFO")
        log_file = getattr(args, "log_file", None)
        quiet = getattr(args, "quiet", False)
        debug = getattr(args, "debug", False)
        run_logger = setup_logging(
            name=self.__class__.__name__,
            level=log_level,
            log_file=log_file,
            quiet=quiet,
            debug=debug,
        )

        # Resolve DB URL
        db_url = resolve_db_url(getattr(args, "db_url", None))
        engine = create_engine(db_url)

        # Resolve table names
        output_table = (
            getattr(args, "out_table", None) or self.get_default_output_table()
        )
        output_schema = getattr(args, "out_schema", "public")
        state_table = (
            getattr(args, "state_table", None) or self.get_default_state_table()
        )

        run_logger.info(
            "Starting %s: output=%s.%s state=%s",
            self.__class__.__name__,
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
        ids = self._resolve_ids(args, db_url, engine, run_logger)
        run_logger.info("Resolved %d asset IDs", len(ids))

        # Resolve param_sets (all or filtered by --indicators)
        param_sets = self._resolve_param_sets(args, run_logger)
        run_logger.info(
            "Using %d param_sets across indicators: %s",
            len(param_sets),
            sorted({ps.indicator for ps in param_sets}),
        )

        # Resolve TF subset (None means all TFs from dim_timeframe in each worker)
        tf_subset = self._resolve_tf_subset(args, engine, run_logger)

        # Full rebuild: clear state for affected IDs
        if getattr(args, "full_rebuild", False):
            run_logger.info(
                "Full rebuild requested — clearing state for %d IDs", len(ids)
            )
            for asset_id in ids:
                state_manager.clear_state(asset_id)

        # Dry run: just log the plan
        if getattr(args, "dry_run", False):
            tf_count = len(tf_subset) if tf_subset else "(all TFs from dim_timeframe)"
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
        num_processes = self._resolve_num_processes(args)

        tasks = [
            AMAWorkerTask(
                asset_id=asset_id,
                db_url=db_url_with_pw,
                param_sets=param_sets,
                state_table=state_table,
                output_schema=output_schema,
                output_table=output_table,
                bars_schema=self.get_bars_schema(),
                bars_table=self.get_bars_table(),
                tf_subset=tf_subset,
                full_rebuild=getattr(args, "full_rebuild", False),
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
            # Sequential execution for debugging or single-ID runs
            results = [_ama_worker(t) for t in tasks]
        else:
            try:
                with Pool(processes=num_processes) as pool:
                    results = pool.map(_ama_worker, tasks)
            except Exception as exc:
                run_logger.error("Pool execution failed: %s", exc, exc_info=True)
                results = [0] * len(tasks)

        total_rows = sum(results)
        successful = sum(1 for r in results if r > 0)
        failed = len(results) - successful

        run_logger.info(
            "Refresh complete: %d total rows, %d/%d assets succeeded, %d failed",
            total_rows,
            successful,
            len(ids),
            failed,
        )

        engine.dispose()

    # =========================================================================
    # Helpers
    # =========================================================================

    def _resolve_ids(
        self,
        args: argparse.Namespace,
        db_url: str,
        engine: Engine,
        run_logger: logging.Logger,
    ) -> list[int]:
        """Resolve asset IDs from --ids argument."""
        ids_arg = getattr(args, "ids", "all").strip()

        if ids_arg.lower() == "all":
            source_table = f"{self.get_bars_schema()}.{self.get_bars_table()}"
            ids = load_all_ids(db_url, source_table)
            run_logger.info("Loaded %d IDs from %s", len(ids), source_table)
            return ids

        # Comma-separated list
        ids = [int(x.strip()) for x in ids_arg.split(",") if x.strip()]
        return ids

    def _resolve_param_sets(
        self,
        args: argparse.Namespace,
        run_logger: logging.Logger,
    ) -> list[AMAParamSet]:
        """Resolve AMA param_sets from --indicators filter."""
        indicators_arg = getattr(args, "indicators", None)

        if not indicators_arg:
            return list(ALL_AMA_PARAMS)

        requested = {ind.strip().upper() for ind in indicators_arg.split(",")}
        filtered = [ps for ps in ALL_AMA_PARAMS if ps.indicator in requested]

        unknown = requested - {ps.indicator for ps in ALL_AMA_PARAMS}
        if unknown:
            run_logger.warning(
                "Unknown indicators in --indicators: %s (valid: KAMA, DEMA, TEMA, HMA)",
                unknown,
            )

        if not filtered:
            run_logger.warning(
                "No matching param_sets for --indicators=%s — using all",
                indicators_arg,
            )
            return list(ALL_AMA_PARAMS)

        run_logger.info(
            "Filtered to %d param_sets for indicators: %s",
            len(filtered),
            sorted(requested & {"KAMA", "DEMA", "TEMA", "HMA"}),
        )
        return filtered

    def _resolve_tf_subset(
        self,
        args: argparse.Namespace,
        engine: Engine,
        run_logger: logging.Logger,
    ) -> Optional[list[str]]:
        """
        Resolve TF subset from --tf or --all-tfs arguments.

        Returns:
            list[str] if --tf was specified (single TF),
            None if --all-tfs (workers will load all TFs from dim_timeframe).
        """
        tf_arg = getattr(args, "tf", None)
        all_tfs = getattr(args, "all_tfs", False)

        if tf_arg:
            run_logger.info("Using single TF: %s", tf_arg)
            return [tf_arg]

        if all_tfs:
            # Load TFs now just for logging; workers will re-query dim_timeframe
            sql = text("SELECT COUNT(*) FROM public.dim_timeframe")
            try:
                with engine.connect() as conn:
                    count = conn.execute(sql).scalar()
                run_logger.info("Using all %d TFs from dim_timeframe", count)
            except Exception:
                run_logger.info("Using all TFs from dim_timeframe")
            return None

        # Neither --tf nor --all-tfs specified
        run_logger.warning(
            "Neither --tf nor --all-tfs specified. "
            "Defaulting to all TFs from dim_timeframe. "
            "Use --tf <TF> for a single TF or --all-tfs explicitly."
        )
        return None

    def _resolve_num_processes(self, args: argparse.Namespace) -> int:
        """Resolve number of worker processes."""
        num = getattr(args, "num_processes", None)
        if num is not None and num > 0:
            return num
        return min(6, cpu_count())
