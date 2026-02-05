"""
Refresh calendar-aligned EMA tables using BaseEMARefresher architecture.

Targets:
  - public.cmc_ema_multi_tf_cal_us
  - public.cmc_ema_multi_tf_cal_iso

REFACTORED VERSION - Uses new base class for:
- Standardized CLI parsing
- State management via EMAStateManager
- Parallel execution via EMAComputationOrchestrator
- Reduced code duplication

Migrated from: refresh_cmc_ema_multi_tf_cal_from_bars.py
"""

from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.features.m_tf.ema_multi_tf_cal import write_multi_timeframe_ema_cal_to_db
from ta_lab2.scripts.bars.common_snapshot_contract import resolve_db_url, get_engine
from ta_lab2.scripts.emas.base_ema_refresher import (
    BaseEMARefresher,
    EMARefresherConfig,
)
from ta_lab2.scripts.emas.ema_state_manager import EMAStateConfig
from ta_lab2.scripts.emas.ema_computation_orchestrator import WorkerTask
from ta_lab2.scripts.emas.logging_config import get_worker_logger


# Default EMA periods for calendar EMAs
DEFAULT_PERIODS = [6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365]


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
        Number of rows inserted/updated
    """
    scheme = task.extra_config.get("scheme", "us")
    worker_id = f"{task.id_}-{scheme}"
    logger = get_worker_logger(
        name="ema_cal",
        worker_id=worker_id,
        log_level="INFO",
        log_file=None,
    )

    try:
        logger.info(f"Starting EMA computation for id={task.id_}, scheme={scheme}")

        # Create engine with NullPool for worker
        engine = create_engine(task.db_url, poolclass=NullPool, future=True)

        # Extract configuration
        schema = task.extra_config.get("schema", "public")
        out_table = task.extra_config.get("out_table")
        alpha_schema = task.extra_config.get("alpha_schema", "public")
        alpha_table = task.extra_config.get("alpha_table", "ema_alpha_lookup")

        n = write_multi_timeframe_ema_cal_to_db(
            engine,
            [task.id_],
            scheme=scheme,
            start=task.start,
            end=task.end,
            ema_periods=task.periods,
            schema=schema,
            out_table=out_table,
            alpha_schema=alpha_schema,
            alpha_table=alpha_table,
        )

        engine.dispose()
        logger.info(f"Completed EMA computation for id={task.id_}: {n} rows")
        return int(n or 0)

    except Exception as e:
        logger.error(f"Worker failed for id={task.id_}: {e}", exc_info=True)
        return 0


# =============================================================================
# Refresher Implementation
# =============================================================================


class CalEMARefresher(BaseEMARefresher):
    """
    EMA refresher for calendar-aligned EMAs (US/ISO schemes).

    Uses:
    - cmc_price_bars_multi_tf_cal_us or cmc_price_bars_multi_tf_cal_iso
    - Calendar-aligned timeframes
    - Separate output and state tables per scheme
    """

    DEFAULT_PERIODS = DEFAULT_PERIODS

    def __init__(
        self,
        config: EMARefresherConfig,
        state_config: EMAStateConfig,
        engine,
        scheme: str,
    ):
        super().__init__(config, state_config, engine)
        self.scheme = scheme
        self.bars_table = f"cmc_price_bars_multi_tf_cal_{scheme}"
        self.bars_schema = "public"

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def get_timeframes(self) -> list[str]:
        """
        Load calendar timeframes from bars table.

        Note: Calendar scripts don't use dim_timeframe - timeframes are
        implicit from the bars table structure.
        """
        # For calendar EMAs, timeframes are loaded from bars table
        # The feature module handles this internally
        return []  # Not needed for cal scripts

    def compute_emas_for_id(
        self,
        id_: int,
        periods: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
        **extra_args,
    ) -> int:
        """
        Compute calendar EMAs for single ID.

        Note: This method is not used by the parallel execution flow,
        but is provided for testing and direct invocation.
        """
        n = write_multi_timeframe_ema_cal_to_db(
            self.engine,
            [id_],
            scheme=self.scheme,
            start=start or "2010-01-01",
            end=end,
            ema_periods=periods,
            schema=self.config.output_schema,
            out_table=self.config.output_table,
            alpha_schema=extra_args.get("alpha_schema", "public"),
            alpha_table=extra_args.get("alpha_table", "ema_alpha_lookup"),
        )
        return int(n or 0)

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
        """Create argument parser with calendar-specific arguments."""
        # Use base parser to get standardized arguments including validation
        p = cls.create_base_argument_parser(
            description="Refresh calendar-aligned EMAs (US/ISO schemes) - refactored.",
        )

        # Calendar-specific arguments
        p.add_argument(
            "--scheme",
            default="us",
            choices=["us", "iso", "both"],
            help="Calendar scheme: us, iso, or both. Default: us",
        )
        p.add_argument(
            "--schema",
            default="public",
            help="Schema for output tables (default: public)",
        )
        p.add_argument("--out-us", default="cmc_ema_multi_tf_cal_us")
        p.add_argument("--out-iso", default="cmc_ema_multi_tf_cal_iso")
        p.add_argument("--alpha-schema", default="public")
        p.add_argument("--alpha-table", default="ema_alpha_lookup")

        return p

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "CalEMARefresher":
        """
        Create refresher instance from CLI arguments.

        Note: If --scheme both, this creates and runs two separate refreshers.
        """
        # This method is called per scheme, not for "both"
        # The main() method handles the "both" case
        raise NotImplementedError(
            "Use from_cli_args_for_scheme() instead. "
            "The main() method handles --scheme both by creating two refreshers."
        )

    @classmethod
    def from_cli_args_for_scheme(
        cls,
        args: argparse.Namespace,
        scheme: str,
    ) -> "CalEMARefresher":
        """Create refresher instance for a specific scheme."""
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Create engine
        engine = get_engine(db_url)

        # Determine output and state tables for this scheme
        out_table = args.out_us if scheme == "us" else args.out_iso
        state_table = f"{out_table}_state"

        # Create temporary instance to use helper methods
        temp_config = EMARefresherConfig(
            db_url=db_url,
            ids=[],
            periods=[],
            output_schema=args.schema,
            output_table=out_table,
            state_table=state_table,
            num_processes=args.num_processes,
            full_refresh=args.full_refresh,
            log_level=args.log_level,
            log_file=args.log_file,
            quiet=args.quiet,
            debug=args.debug,
            validate_output=args.validate_output,
            ema_rejects_table=args.ema_rejects_table,
            extra_config={},
        )

        temp_state_config = EMAStateConfig(
            state_schema=args.schema,
            state_table=state_table,
            ts_column="canonical_ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=f"cmc_price_bars_multi_tf_cal_{scheme}",
            bars_schema="public",
            bars_partial_filter="is_partial_end = FALSE",
        )

        temp_instance = cls(temp_config, temp_state_config, engine, scheme)

        # Load IDs and periods using helper methods
        ids = temp_instance.load_ids(args.ids)
        periods = temp_instance.load_periods(args.periods)

        # Create final config
        final_config = EMARefresherConfig(
            db_url=db_url,
            ids=ids,
            periods=periods,
            output_schema=args.schema,
            output_table=out_table,
            state_table=state_table,
            num_processes=args.num_processes,
            full_refresh=args.full_refresh,
            log_level=args.log_level,
            log_file=args.log_file,
            quiet=args.quiet,
            debug=args.debug,
            validate_output=args.validate_output,
            ema_rejects_table=args.ema_rejects_table,
            extra_config={
                "scheme": scheme,
                "schema": args.schema,
                "out_table": out_table,
                "alpha_schema": args.alpha_schema,
                "alpha_table": args.alpha_table,
            },
        )

        state_config = EMAStateConfig(
            state_schema=args.schema,
            state_table=state_table,
            ts_column="canonical_ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=f"cmc_price_bars_multi_tf_cal_{scheme}",
            bars_schema="public",
            bars_partial_filter="is_partial_end = FALSE",
        )

        return cls(final_config, state_config, engine, scheme)

    @classmethod
    def main_for_schemes(cls, argv=None) -> None:
        """
        CLI entry point that handles --scheme both by running two refreshers.
        """
        parser = cls.create_argument_parser()
        args = parser.parse_args(argv)

        schemes_to_run = []
        if args.scheme == "both":
            schemes_to_run = ["us", "iso"]
        else:
            schemes_to_run = [args.scheme]

        for scheme in schemes_to_run:
            print(f"\n{'='*80}")
            print(f"Running calendar EMA refresh for scheme: {scheme.upper()}")
            print(f"{'='*80}\n")

            refresher = cls.from_cli_args_for_scheme(args, scheme)
            refresher.run()


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    CalEMARefresher.main_for_schemes()
