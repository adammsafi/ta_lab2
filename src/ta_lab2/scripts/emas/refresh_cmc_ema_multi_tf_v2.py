"""
Refresh cmc_ema_multi_tf_v2 using BaseEMARefresher architecture.

Key differences from other refreshers:
- Uses cmc_price_bars_1d (validated bars) exclusively
- Computes all TFs from daily data (no multi-tf bars needed)
- Loads TFs dynamically from dim_timeframe
- Incremental watermark is per (id, tf, period)

REFACTORED VERSION - Uses new base class for:
- Standardized CLI parsing
- State management via EMAStateManager
- Parallel execution via EMAComputationOrchestrator
- Reduced code duplication

Migrated from: refresh_cmc_ema_multi_tf_v2.py
"""

from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.features.m_tf.ema_multi_tf_v2 import (
    refresh_cmc_ema_multi_tf_v2_incremental,
)
from ta_lab2.scripts.bars.common_snapshot_contract import resolve_db_url, get_engine
from ta_lab2.scripts.emas.base_ema_refresher import (
    BaseEMARefresher,
    EMARefresherConfig,
)
from ta_lab2.scripts.emas.ema_state_manager import EMAStateConfig
from ta_lab2.scripts.emas.ema_computation_orchestrator import WorkerTask
from ta_lab2.scripts.emas.logging_config import get_worker_logger


# Default EMA periods
DEFAULT_PERIODS = [9, 10, 21, 50, 100, 200]


# =============================================================================
# Worker Function (Module-level for pickling)
# =============================================================================


def _process_id_worker(task: WorkerTask) -> int:
    """
    Worker function for parallel processing of individual IDs.

    Creates own engine with NullPool to avoid connection pooling issues.

    Args:
        task: WorkerTask containing id, db_url, periods, start, extra_config

    Returns:
        Number of rows inserted/updated (always 0 - v2 doesn't report row count)
    """
    worker_id = str(task.id_)
    logger = get_worker_logger(
        name="ema_v2",
        worker_id=worker_id,
        log_level="INFO",
        log_file=None,
    )

    try:
        logger.info(f"Starting EMA computation for id={task.id_}")

        # Create engine with NullPool for worker
        engine = create_engine(task.db_url, poolclass=NullPool, future=True)

        # Extract configuration
        alignment_type = task.extra_config.get("alignment_type", "tf_day")
        canonical_only = task.extra_config.get("canonical_only", True)
        price_schema = task.extra_config.get("price_schema", "public")
        price_table = task.extra_config.get("price_table", "cmc_price_bars_1d")
        out_schema = task.extra_config.get("out_schema", "public")
        out_table = task.extra_config.get("out_table", "cmc_ema_multi_tf_v2")

        # V2 feature module handles incremental refresh internally
        refresh_cmc_ema_multi_tf_v2_incremental(
            engine,
            periods=task.periods,
            ids=[task.id_],
            alignment_type=alignment_type,
            canonical_only=canonical_only,
            price_schema=price_schema,
            price_table=price_table,
            out_schema=out_schema,
            out_table=out_table,
        )

        engine.dispose()
        logger.info(f"Completed EMA computation for id={task.id_}")
        return 0  # V2 doesn't report row count

    except Exception as e:
        logger.error(f"Worker failed for id={task.id_}: {e}", exc_info=True)
        return 0


# =============================================================================
# Refresher Implementation
# =============================================================================


class V2EMARefresher(BaseEMARefresher):
    """
    V2 EMA refresher using daily bars with dynamic TF computation.

    Key differences from other refreshers:
    - Uses cmc_price_bars_1d (validated bars) exclusively
    - Computes all TFs from daily data (no multi-tf bars needed)
    - Loads TFs dynamically from dim_timeframe
    - Feature module handles incremental logic internally
    """

    DEFAULT_PERIODS = DEFAULT_PERIODS

    def __init__(
        self,
        config: EMARefresherConfig,
        state_config: EMAStateConfig,
        engine,
    ):
        super().__init__(config, state_config, engine)
        self.alignment_type = config.extra_config.get("alignment_type", "tf_day")
        self.canonical_only = config.extra_config.get("canonical_only", True)
        self.price_schema = config.extra_config.get("price_schema", "public")
        self.price_table = config.extra_config.get("price_table", "cmc_price_bars_1d")

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def get_timeframes(self) -> list[str]:
        """Load timeframes from dim_timeframe."""
        from ta_lab2.time.dim_timeframe import list_tfs

        tfs = list_tfs(
            db_url=self.config.db_url,
            alignment_type=self.alignment_type,
            canonical_only=self.canonical_only,
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
        Compute V2 EMAs for single ID.

        Note: V2 feature module handles incremental refresh internally,
        so start/end parameters are not used.
        """
        refresh_cmc_ema_multi_tf_v2_incremental(
            self.engine,
            periods=periods,
            ids=[id_],
            alignment_type=self.alignment_type,
            canonical_only=self.canonical_only,
            price_schema=self.price_schema,
            price_table=self.price_table,
            out_schema=self.config.output_schema,
            out_table=self.config.output_table,
        )
        return 0  # V2 doesn't report row count

    def get_source_table_info(self) -> dict[str, str]:
        """Return source bars table information."""
        return {
            "bars_table": self.price_table,
            "bars_schema": self.price_schema,
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
        """Create argument parser with V2-specific arguments."""
        # Use base parser to get standardized arguments including validation
        p = cls.create_base_argument_parser(
            description="Refresh cmc_ema_multi_tf_v2 from 1D bars (refactored).",
        )

        # Override defaults for this script
        p.set_defaults(
            out_table="cmc_ema_multi_tf_v2",
            state_table="cmc_ema_multi_tf_v2_state",
        )

        # V2-specific arguments
        p.add_argument(
            "--alignment-type",
            default="tf_day",
            help="dim_timeframe.alignment_type for TF selection. Default: tf_day",
        )
        p.add_argument(
            "--include-noncanonical",
            action="store_true",
            help="Include non-canonical TFs from dim_timeframe.",
        )
        p.add_argument("--price-schema", default="public")
        p.add_argument(
            "--price-table",
            default="cmc_price_bars_1d",
            help="1D bars table (validated data). Default: cmc_price_bars_1d",
        )

        return p

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "V2EMARefresher":
        """Create refresher instance from CLI arguments."""
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Create engine
        engine = get_engine(db_url)

        canonical_only = not args.include_noncanonical

        # Create temporary instance to use helper methods
        temp_config = EMARefresherConfig(
            db_url=db_url,
            ids=[],
            periods=[],
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
                "alignment_type": args.alignment_type,
                "canonical_only": canonical_only,
                "price_schema": args.price_schema,
                "price_table": args.price_table,
            },
        )

        temp_state_config = EMAStateConfig(
            state_schema=args.out_schema,
            state_table=args.state_table,
            ts_column="ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=args.price_table,
            bars_schema=args.price_schema,
            bars_partial_filter="is_partial_end = FALSE",
        )

        temp_instance = cls(temp_config, temp_state_config, engine)

        # Load IDs and periods using helper methods
        ids = temp_instance.load_ids(args.ids)
        periods = temp_instance.load_periods(args.periods)

        # Create final config
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
                "alignment_type": args.alignment_type,
                "canonical_only": canonical_only,
                "price_schema": args.price_schema,
                "price_table": args.price_table,
                "out_schema": args.out_schema,
                "out_table": args.out_table,
            },
        )

        state_config = EMAStateConfig(
            state_schema=args.out_schema,
            state_table=args.state_table,
            ts_column="ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=args.price_table,
            bars_schema=args.price_schema,
            bars_partial_filter="is_partial_end = FALSE",
        )

        return cls(final_config, state_config, engine)


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    V2EMARefresher.main()
