"""
Base class for EMA refresh scripts - Template Method Pattern.

Standardizes the execution flow for all EMA refresh scripts:
- CLI argument parsing
- Database connection management
- State table management
- ID and period resolution
- Full refresh vs incremental logic
- Multiprocessing orchestration

Subclasses implement:
- get_timeframes(): Load TFs from dim_timeframe or hardcoded
- compute_emas_for_id(): Compute EMAs for a single ID
- get_source_table_info(): Return source table metadata
- from_cli_args(): Factory to create from CLI args
- create_argument_parser(): Add script-specific arguments

Design Pattern: Template Method
- Base class defines execution flow
- Subclasses implement specific behavior
- Reduces code duplication across 4 EMA scripts

Migration: This replaces duplicated code in:
- refresh_cmc_ema_multi_tf_from_bars.py
- refresh_cmc_ema_multi_tf_cal_from_bars.py
- refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py
- refresh_cmc_ema_multi_tf_v2.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Sequence, Any
import argparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.bars.common_snapshot_contract import (
    resolve_db_url,
    parse_ids,
    load_all_ids,
    load_periods as load_periods_from_lut,
)
from ta_lab2.scripts.emas.logging_config import (
    setup_logging,
    add_logging_args,
)
from ta_lab2.scripts.emas.ema_state_manager import (
    EMAStateManager,
    EMAStateConfig,
)
from ta_lab2.scripts.emas.ema_computation_orchestrator import (
    EMAComputationOrchestrator,
    WorkerTask,
)


# =============================================================================
# Configuration
# =============================================================================

@dataclass(frozen=True)
class EMARefresherConfig:
    """
    Configuration for EMA refresh execution.

    Attributes:
        db_url: SQLAlchemy database URL
        ids: List of cryptocurrency IDs to process
        periods: List of EMA periods to compute
        output_schema: Schema for output EMA table
        output_table: Output EMA table name
        state_table: State table name for incremental tracking
        num_processes: Number of parallel worker processes
        full_refresh: If True, ignore state and recompute from scratch
        log_level: Logging level (INFO, DEBUG, etc.)
        log_file: Optional log file path
        quiet: Suppress console output
        debug: Enable debug mode
        extra_config: Script-specific configuration (alignment_type, etc.)
    """
    db_url: str
    ids: list[int]
    periods: list[int]
    output_schema: str
    output_table: str
    state_table: str
    num_processes: int
    full_refresh: bool
    log_level: str
    log_file: Optional[str] = None
    quiet: bool = False
    debug: bool = False
    extra_config: dict[str, Any] = None

    def __post_init__(self):
        if self.extra_config is None:
            object.__setattr__(self, 'extra_config', {})


# =============================================================================
# Base EMA Refresher
# =============================================================================

class BaseEMARefresher(ABC):
    """
    Abstract base class for EMA refresh scripts.

    Template Method Pattern:
    - Defines the execution flow (run → _run_incremental/_run_full_refresh)
    - Delegates script-specific behavior to abstract methods
    - Standardizes state management, logging, multiprocessing

    Subclasses must implement:
    - get_timeframes(): Load timeframes from dim_timeframe or hardcoded
    - compute_emas_for_id(): Compute EMAs for a single ID (the core logic)
    - get_source_table_info(): Return source bars table metadata
    - from_cli_args(): Factory to create instance from CLI arguments
    - create_argument_parser(): Add script-specific arguments to base parser

    Invariants:
    - State table uses unified schema (id, tf, period) PRIMARY KEY
    - All scripts use incremental refresh by default
    - Full refresh is opt-in via --full-refresh flag
    - State is updated after successful computation

    Thread-safety: Not thread-safe. Create separate instances per worker.
    """

    # Default EMA periods (can be overridden by subclasses)
    DEFAULT_PERIODS = [9, 10, 21, 50, 100, 200]

    def __init__(
        self,
        config: EMARefresherConfig,
        state_config: EMAStateConfig,
        engine: Engine,
    ):
        """
        Initialize EMA refresher.

        Args:
            config: Refresher configuration
            state_config: State manager configuration
            engine: SQLAlchemy engine for database operations
        """
        self.config = config
        self.engine = engine
        self.state_manager = EMAStateManager(engine, state_config)
        self.logger = setup_logging(
            name=self.__class__.__name__,
            level=config.log_level,
            log_file=config.log_file,
            quiet=config.quiet,
            debug=config.debug,
        )

    # =========================================================================
    # Abstract Methods (MUST override)
    # =========================================================================

    @abstractmethod
    def get_timeframes(self) -> list[str]:
        """
        Load timeframes to compute.

        For scripts using dim_timeframe:
            - Query dim_timeframe with alignment_type filter
            - Return canonical_only=True timeframes

        For scripts with hardcoded TFs:
            - Return fixed list like ["1D", "7D", "28D"]

        Returns:
            List of timeframe strings (e.g., ["1D", "7D", "28D"])
        """

    @abstractmethod
    def compute_emas_for_id(
        self,
        id_: int,
        periods: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
        **extra_args,
    ) -> int:
        """
        Compute EMAs for a single ID.

        This is the core computation method that delegates to the
        appropriate feature module (e.g., ema_multi_tf, ema_multi_tf_cal).

        Args:
            id_: Cryptocurrency ID
            periods: List of EMA periods to compute
            start: Optional start timestamp (for incremental refresh)
            end: Optional end timestamp (for date range filtering)
            **extra_args: Script-specific arguments (e.g., alignment_type)

        Returns:
            Number of rows inserted/updated (0 if not available)

        Raises:
            Exception: On computation errors (logged and re-raised)
        """

    @abstractmethod
    def get_source_table_info(self) -> dict[str, str]:
        """
        Return source table information for logging and ID resolution.

        Returns:
            Dictionary with keys:
            - "bars_table": Source bars table name
            - "bars_schema": Source bars schema name

        Example:
            {"bars_table": "cmc_price_bars_multi_tf", "bars_schema": "public"}
        """

    @staticmethod
    @abstractmethod
    def get_worker_function():
        """
        Return module-level worker function for multiprocessing.

        The worker function must:
        1. Accept a WorkerTask as its only parameter
        2. Be defined at module level (not instance method) for pickling
        3. Create its own engine with NullPool
        4. Call the appropriate feature module function
        5. Return number of rows inserted/updated

        Example:
            @staticmethod
            def get_worker_function():
                return _process_id_worker  # Module-level function

            def _process_id_worker(task: WorkerTask) -> int:
                from sqlalchemy import create_engine
                from sqlalchemy.pool import NullPool

                engine = create_engine(task.db_url, poolclass=NullPool)
                # ... call feature module ...
                return rows_written

        Returns:
            Callable that takes WorkerTask and returns int (row count)
        """

    @classmethod
    @abstractmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "BaseEMARefresher":
        """
        Factory method: Create refresher from CLI arguments.

        Subclasses implement this to:
        1. Resolve db_url from args.db_url
        2. Create engine
        3. Load IDs from args.ids (using load_ids helper)
        4. Load periods from args.periods (using load_periods helper)
        5. Build EMARefresherConfig and EMAStateConfig
        6. Return instance

        Args:
            args: Parsed CLI arguments from ArgumentParser

        Returns:
            Instance of the EMA refresher subclass
        """

    @classmethod
    @abstractmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create argument parser with script-specific arguments.

        Subclasses should:
        1. Call cls.create_base_argument_parser() to get base parser
        2. Add script-specific arguments (e.g., --alignment-type)
        3. Return the parser

        Returns:
            ArgumentParser with all arguments configured
        """

    # =========================================================================
    # Template Methods (Concrete - define execution flow)
    # =========================================================================

    def run(self) -> None:
        """
        Main execution: Orchestrate full refresh flow.

        Template Method:
        1. Ensure state table exists
        2. Load timeframes
        3. Execute full refresh or incremental refresh
        4. Update state table

        This method defines the execution flow but delegates
        specifics to abstract methods.
        """
        self.logger.info(f"Starting EMA refresh: {self.__class__.__name__}")
        self.logger.info(f"Configuration: {len(self.config.ids)} IDs, "
                        f"{len(self.config.periods)} periods")

        # Ensure state table exists
        self.state_manager.ensure_state_table()
        self.logger.info(f"State table: {self.state_manager.config.state_schema}."
                        f"{self.state_manager.config.state_table}")

        # Load timeframes
        tfs = self.get_timeframes()
        self.logger.info(f"Loaded {len(tfs)} timeframes: {tfs}")

        # Log source table info
        source_info = self.get_source_table_info()
        self.logger.info(f"Source: {source_info['bars_schema']}.{source_info['bars_table']}")
        self.logger.info(f"Target: {self.config.output_schema}.{self.config.output_table}")

        # Execute
        try:
            if self.config.full_refresh:
                self.logger.info("Running FULL REFRESH (ignoring state)")
                self._run_full_refresh()
            else:
                self.logger.info("Running INCREMENTAL refresh")
                self._run_incremental()

            self.logger.info("Refresh complete")
        except Exception as e:
            self.logger.error(f"Refresh failed: {e}", exc_info=True)
            raise
        finally:
            # Ensure pooled connections are released
            self.engine.dispose()
            self.logger.debug("Database engine disposed")

    def _run_incremental(self) -> None:
        """
        Incremental mode: Load state, compute dirty windows, execute in parallel.

        This method:
        1. Loads existing state
        2. For each ID, computes dirty window start based on state
        3. Creates WorkerTask objects for parallel execution
        4. Uses EMAComputationOrchestrator to execute tasks in parallel
        5. Updates state table after all IDs complete

        Parallelization: Uses num_processes workers (default: min(cpu_count(), 4))
        """
        # Load existing state
        state_df = self.state_manager.load_state(
            ids=self.config.ids,
            periods=self.config.periods,
        )

        if state_df.empty:
            self.logger.info("No existing state found - will compute full history")
            start_times = {id_: "2010-01-01" for id_ in self.config.ids}
        else:
            self.logger.info(f"Loaded state with {len(state_df)} records")
            # Compute dirty window starts per ID
            start_times = self.state_manager.compute_dirty_window_starts(
                ids=self.config.ids,
                default_start="2010-01-01",
            )

        # IMPORTANT: Extract db_url with password preserved (not masked)
        # SQLAlchemy's str(engine.url) masks password as ***
        db_url = self.engine.url.render_as_string(hide_password=False)
        self.logger.debug("Extracted db_url for workers (password preserved)")

        # Create worker tasks
        tasks = []
        for id_ in self.config.ids:
            start = start_times.get(id_, "2010-01-01")
            task = WorkerTask(
                id_=id_,
                db_url=db_url,
                periods=self.config.periods,
                start=start,
                end=None,
                extra_config=self.config.extra_config,
            )
            tasks.append(task)

        self.logger.info(f"Created {len(tasks)} worker tasks")

        # Execute in parallel using orchestrator
        orchestrator = EMAComputationOrchestrator(
            worker_fn=self.get_worker_function(),
            num_processes=self.config.num_processes,
            logger=self.logger,
        )

        results = orchestrator.execute(tasks)
        total_rows = sum(results)

        # Update state
        self.logger.info("Updating state table...")
        rows_updated = self.state_manager.update_state_from_output(
            output_table=self.config.output_table,
            output_schema=self.config.output_schema,
        )
        self.logger.info(f"State updated: {rows_updated} rows upserted")

        self.logger.info(f"Completed: {total_rows} total rows")

    def _run_full_refresh(self) -> None:
        """
        Full refresh mode: Ignore state, recompute everything from 2010-01-01 in parallel.

        This method:
        1. Creates WorkerTask objects for each ID with start="2010-01-01"
        2. Uses EMAComputationOrchestrator to execute tasks in parallel
        3. Updates state table after all IDs complete

        Parallelization: Uses num_processes workers (default: min(cpu_count(), 4))
        """
        # IMPORTANT: Extract db_url with password preserved (not masked)
        db_url = self.engine.url.render_as_string(hide_password=False)
        self.logger.debug("Extracted db_url for workers (password preserved)")

        # Create worker tasks (all start from 2010-01-01)
        tasks = []
        for id_ in self.config.ids:
            task = WorkerTask(
                id_=id_,
                db_url=db_url,
                periods=self.config.periods,
                start="2010-01-01",
                end=None,
                extra_config=self.config.extra_config,
            )
            tasks.append(task)

        self.logger.info(f"Created {len(tasks)} worker tasks (full refresh)")

        # Execute in parallel using orchestrator
        orchestrator = EMAComputationOrchestrator(
            worker_fn=self.get_worker_function(),
            num_processes=self.config.num_processes,
            logger=self.logger,
        )

        results = orchestrator.execute(tasks)
        total_rows = sum(results)

        # Update state
        self.logger.info("Updating state table...")
        rows_updated = self.state_manager.update_state_from_output(
            output_table=self.config.output_table,
            output_schema=self.config.output_schema,
        )
        self.logger.info(f"State updated: {rows_updated} rows upserted")

        self.logger.info(f"Completed: {total_rows} total rows")

    # =========================================================================
    # Utility Methods (Helpers for subclasses)
    # =========================================================================

    def load_periods(self, periods_arg: Optional[str]) -> list[int]:
        """
        Load EMA periods from argument.

        Supports:
        - "lut": Load distinct periods from public.ema_alpha_lookup
        - "9,10,21": Comma-separated list of periods
        - None or empty: Use DEFAULT_PERIODS

        Args:
            periods_arg: Periods argument from CLI

        Returns:
            List of EMA periods (positive integers)
        """
        if not periods_arg:
            self.logger.info(f"Using {len(self.DEFAULT_PERIODS)} default periods")
            return list(self.DEFAULT_PERIODS)

        periods_arg = periods_arg.strip().lower()

        if periods_arg == "lut":
            periods = list(load_periods_from_lut(self.engine, "lut"))
            self.logger.info(f"Loaded {len(periods)} periods from ema_alpha_lookup")
            return periods

        # Parse comma-separated list
        periods = [int(p.strip()) for p in periods_arg.split(",") if p.strip()]
        periods = [p for p in periods if p > 0]
        self.logger.info(f"Using {len(periods)} periods from command line")
        return periods

    def load_ids(self, ids_arg: str) -> list[int]:
        """
        Load cryptocurrency IDs from argument.

        Supports:
        - "all": Load all IDs from source bars table
        - "1,52,825": Comma-separated list of IDs

        Args:
            ids_arg: IDs argument from CLI

        Returns:
            List of cryptocurrency IDs
        """
        ids_arg = ids_arg.strip()

        if ids_arg.lower() == "all":
            source_info = self.get_source_table_info()
            source_table_fq = f"{source_info['bars_schema']}.{source_info['bars_table']}"
            ids = load_all_ids(self.config.db_url, source_table_fq)
            self.logger.info(f"Loaded {len(ids)} IDs from {source_table_fq}")
            return ids

        # Parse comma-separated list
        ids = [int(x.strip()) for x in ids_arg.split(",") if x.strip()]
        self.logger.info(f"Processing {len(ids)} IDs from command line")
        return ids

    # =========================================================================
    # CLI Integration
    # =========================================================================

    @classmethod
    def create_base_argument_parser(
        cls,
        description: str,
        epilog: Optional[str] = None,
    ) -> argparse.ArgumentParser:
        """
        Create argument parser with common EMA refresh arguments.

        Subclasses should call this method and add script-specific arguments.

        Args:
            description: Script description for --help
            epilog: Optional epilog text (usage examples, notes)

        Returns:
            ArgumentParser with common arguments configured
        """
        default_epilog = """
CONNECTION LIMITS: This script uses multiprocessing. Each worker needs database connections.
If you see "too many clients already" errors:
  1. Reduce --num-processes (default: 4, safe for most setups)
  2. Increase Postgres max_connections in postgresql.conf
  3. Check for other processes holding connections (pg_stat_activity)
        """

        p = argparse.ArgumentParser(
            description=description,
            epilog=epilog or default_epilog,
        )

        # Database
        p.add_argument(
            "--db-url",
            default=None,
            help="SQLAlchemy DB URL (or load from db_config.env / TARGET_DB_URL env)."
        )

        # Input selection
        p.add_argument(
            "--ids",
            default="all",
            help="Comma list of ids (e.g., 1,52) or 'all' (default)."
        )
        p.add_argument(
            "--periods",
            default=None,
            help=(
                f"Comma list of EMA periods, or 'lut' to load from ema_alpha_lookup "
                f"(default: {','.join(map(str, cls.DEFAULT_PERIODS))})."
            ),
        )

        # Output configuration
        p.add_argument("--out-schema", default="public")
        p.add_argument("--out-table", required=True, help="Output EMA table name")
        p.add_argument(
            "--state-table",
            required=True,
            help="State table name for incremental tracking"
        )

        # Execution mode
        p.add_argument(
            "--full-refresh",
            action="store_true",
            help="Ignore state and run full history refresh"
        )
        p.add_argument(
            "--num-processes",
            type=int,
            default=None,
            help="Number of parallel processes. Default: min(cpu_count(), 4)"
        )

        # Logging
        add_logging_args(p)

        return p

    @classmethod
    def main(cls, argv: Sequence[str] | None = None) -> None:
        """
        Standard CLI entry point.

        Usage:
            if __name__ == "__main__":
                MultiTFEMARefresher.main()

        Args:
            argv: Command line arguments (default: sys.argv)
        """
        parser = cls.create_argument_parser()
        args = parser.parse_args(argv)
        refresher = cls.from_cli_args(args)
        refresher.run()
