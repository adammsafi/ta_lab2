"""
Refresh cmc_ema_multi_tf using BaseEMARefresher architecture.

REFACTORED VERSION - Uses new base class for:
- Standardized CLI parsing
- State management via EMAStateManager
- Parallel execution via EMAComputationOrchestrator
- Reduced code duplication

Migrated from: refresh_cmc_ema_multi_tf_from_bars.py (~500 LOC → ~150 LOC)
"""

from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.features.m_tf.ema_multi_timeframe import write_multi_timeframe_ema_to_db
from ta_lab2.scripts.bars.common_snapshot_contract import resolve_db_url, get_engine
from ta_lab2.scripts.emas.base_ema_refresher import (
    BaseEMARefresher,
    EMARefresherConfig,
)
from ta_lab2.scripts.emas.ema_state_manager import EMAStateConfig
from ta_lab2.scripts.emas.ema_computation_orchestrator import WorkerTask
from ta_lab2.scripts.emas.logging_config import get_worker_logger
from ta_lab2.time.dim_timeframe import list_tfs


# Default EMA periods for multi-tf
DEFAULT_PERIODS = [6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365]


# =============================================================================
# Worker Function (Module-level for pickling)
# =============================================================================


def _process_id_worker(task: WorkerTask) -> int:
    """
    Worker function for parallel processing of individual IDs.

    Creates own engine with NullPool to avoid connection pooling issues.
    Processes all timeframes for the given ID.

    Args:
        task: WorkerTask containing id, db_url, periods, start, extra_config

    Returns:
        Number of rows inserted/updated
    """
    worker_id = str(task.id_)
    logger = get_worker_logger(
        name="ema_multi_tf",
        worker_id=worker_id,
        log_level="INFO",
        log_file=None,
    )

    try:
        logger.info(f"Starting EMA computation for id={task.id_}")

        # Create engine with NullPool for worker
        engine = create_engine(task.db_url, poolclass=NullPool, future=True)

        # Extract configuration
        bars_table = task.extra_config.get("bars_table", "cmc_price_bars_multi_tf")
        bars_schema = task.extra_config.get("bars_schema", "public")
        out_schema = task.extra_config.get("out_schema", "public")
        out_table = task.extra_config.get("out_table", "cmc_ema_multi_tf")
        tfs = task.extra_config.get("tfs")  # Optional TF subset

        # Load timeframes if not provided
        if not tfs:
            tfs = list_tfs(
                db_url=task.db_url,
                alignment_type="tf_day",
                canonical_only=True,
            )

        # Process all timeframes for this ID
        total_rows = 0
        for tf in tfs:
            # Special handling for 1D: use cmc_price_bars_1d (validated bars)
            actual_bars_table = "cmc_price_bars_1d" if tf == "1D" else bars_table

            if tf == "1D":
                logger.debug(f"Using validated 1D bars table: {actual_bars_table}")

            n = write_multi_timeframe_ema_to_db(
                ids=[task.id_],
                start=task.start,
                end=task.end,
                ema_periods=task.periods,
                tf_subset=[tf],
                db_url=task.db_url,
                schema=out_schema,
                out_table=out_table,
                bars_schema=bars_schema,
                bars_table_tf_day=actual_bars_table,
            )
            total_rows += n
            logger.debug(f"ID {task.id_}, TF {tf}: {n} rows")

        engine.dispose()
        logger.info(f"Completed EMA computation for id={task.id_}: {total_rows} rows")
        return total_rows

    except Exception as e:
        logger.error(f"Worker failed for id={task.id_}: {e}", exc_info=True)
        return 0


# =============================================================================
# Refresher Implementation
# =============================================================================


class MultiTFEMARefresher(BaseEMARefresher):
    """
    EMA refresher for multi-timeframe EMAs from tf_day bars.

    Uses:
    - dim_timeframe (alignment_type='tf_day', canonical_only=True) for TFs
    - cmc_price_bars_multi_tf for tf_day canonical bars
    - cmc_price_bars_1d for 1D timeframe (validated bars)
    - Parallel execution at ID level
    """

    DEFAULT_PERIODS = DEFAULT_PERIODS

    def __init__(
        self,
        config: EMARefresherConfig,
        state_config: EMAStateConfig,
        engine,
    ):
        super().__init__(config, state_config, engine)
        self.bars_table = config.extra_config.get(
            "bars_table", "cmc_price_bars_multi_tf"
        )
        self.bars_schema = config.extra_config.get("bars_schema", "public")

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def get_timeframes(self) -> list[str]:
        """Load tf_day canonical timeframes from dim_timeframe."""
        tfs = list_tfs(
            db_url=self.config.db_url,
            alignment_type="tf_day",
            canonical_only=True,
        )
        return tfs

    def compute_emas_for_id(
        self,
        id_: int,
        periods: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
        **extra_args,
    ) -> int:
        """
        Compute multi-tf EMAs for single ID (sequential across TFs).

        Note: This method is not used by the parallel execution flow,
        but is provided for testing and direct invocation.
        """
        tfs = extra_args.get("tfs", self.get_timeframes())

        total_rows = 0
        for tf in tfs:
            # Special handling for 1D
            actual_bars_table = "cmc_price_bars_1d" if tf == "1D" else self.bars_table

            n = write_multi_timeframe_ema_to_db(
                ids=[id_],
                start=start or "2010-01-01",
                end=end,
                ema_periods=periods,
                tf_subset=[tf],
                db_url=self.config.db_url,
                schema=self.config.output_schema,
                out_table=self.config.output_table,
                bars_schema=self.bars_schema,
                bars_table_tf_day=actual_bars_table,
            )
            total_rows += n

        return total_rows

    def get_source_table_info(self) -> dict[str, str]:
        """Return source bars table information."""
        return {
            "bars_table": self.bars_table,
            "bars_schema": self.bars_schema,
        }

    @staticmethod
    def get_worker_function():
        """Return module-level worker function for multiprocessing."""
        return _process_id_worker

    # =========================================================================
    # CLI Integration
    # =========================================================================

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """Create argument parser with multi-tf specific arguments."""
        # Use base parser to get standardized arguments including validation
        p = cls.create_base_argument_parser(
            description="Refresh cmc_ema_multi_tf from tf_day bars (refactored).",
        )

        # Override defaults for this script
        p.set_defaults(
            out_table="cmc_ema_multi_tf",
            state_table="cmc_ema_multi_tf_state",
        )

        # Script-specific arguments
        p.add_argument("--bars-table", default="cmc_price_bars_multi_tf")
        p.add_argument("--bars-schema", default="public")
        p.add_argument("--tfs", default=None)

        return p

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "MultiTFEMARefresher":
        """Create refresher instance from CLI arguments."""
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Create engine
        engine = get_engine(db_url)

        # Create temporary instance to use helper methods
        temp_config = EMARefresherConfig(
            db_url=db_url,
            ids=[],  # Will be set below
            periods=[],  # Will be set below
            output_schema=args.out_schema,
            output_table=args.out_table,
            state_table=args.state_table,
            num_processes=args.num_processes,
            full_refresh=args.full_refresh,
            log_level=args.log_level,
            log_file=args.log_file,
            quiet=args.quiet,
            debug=args.debug,
            validate_output=args.validate_output,
            ema_rejects_table=args.ema_rejects_table,
            extra_config={
                "bars_table": args.bars_table,
                "bars_schema": args.bars_schema,
                "tfs": args.tfs.split(",") if args.tfs else None,
            },
        )

        temp_state_config = EMAStateConfig(
            state_schema=args.out_schema,
            state_table=args.state_table,
            ts_column="ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=args.bars_table,
            bars_schema=args.bars_schema,
            bars_partial_filter="is_partial_end = FALSE",
        )

        temp_instance = cls(temp_config, temp_state_config, engine)

        # Load IDs and periods using helper methods
        ids = temp_instance.load_ids(args.ids)
        periods = temp_instance.load_periods(args.periods)

        # Create final config with loaded IDs and periods
        final_config = EMARefresherConfig(
            db_url=db_url,
            ids=ids,
            periods=periods,
            output_schema=args.out_schema,
            output_table=args.out_table,
            state_table=args.state_table,
            num_processes=args.num_processes,
            full_refresh=args.full_refresh,
            log_level=args.log_level,
            log_file=args.log_file,
            quiet=args.quiet,
            debug=args.debug,
            validate_output=args.validate_output,
            ema_rejects_table=args.ema_rejects_table,
            extra_config={
                "bars_table": args.bars_table,
                "bars_schema": args.bars_schema,
                "out_schema": args.out_schema,
                "out_table": args.out_table,
                "tfs": args.tfs.split(",") if args.tfs else None,
            },
        )

        state_config = EMAStateConfig(
            state_schema=args.out_schema,
            state_table=args.state_table,
            ts_column="ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=args.bars_table,
            bars_schema=args.bars_schema,
            bars_partial_filter="is_partial_end = FALSE",
        )

        return cls(final_config, state_config, engine)


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    MultiTFEMARefresher.main()
