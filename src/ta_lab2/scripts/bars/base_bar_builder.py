"""
Base class for bar refresh scripts - Template Method Pattern.

Standardizes the execution flow for all bar refresh scripts:
- CLI argument parsing
- Database connection management
- State table management
- ID resolution
- Full rebuild vs incremental logic
- Multiprocessing orchestration
- OHLC validation and reject logging

Subclasses implement:
- get_state_table_name(): Return state table name for this builder variant
- get_output_table_name(): Return output bars table name
- get_source_query(): Load source data for one ID
- build_bars_for_id(): Build bars from daily data for one ID
- create_argument_parser(): Add script-specific arguments
- from_cli_args(): Factory to create from CLI args

Design Pattern: Template Method
- Base class defines execution flow
- Subclasses implement specific behavior
- Reduces code duplication across 6 bar builders

Migration: This replaces duplicated code in:
- refresh_cmc_price_bars_1d.py
- refresh_cmc_price_bars_multi_tf.py
- refresh_cmc_price_bars_multi_tf_cal_us.py
- refresh_cmc_price_bars_multi_tf_cal_iso.py
- refresh_cmc_price_bars_multi_tf_cal_anchor_us.py
- refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence
import argparse
import logging

import pandas as pd

from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.common_snapshot_contract import (
    parse_ids,
    load_all_ids,
    ensure_state_table,
    ensure_bar_table_exists,
    load_state,
    create_bar_builder_argument_parser,
)


# =============================================================================
# Base Bar Builder
# =============================================================================


class BaseBarBuilder(ABC):
    """
    Abstract base class for bar refresh scripts.

    Template Method Pattern:
    - Defines the execution flow (run → _run_incremental/_run_full_rebuild)
    - Delegates script-specific behavior to abstract methods
    - Standardizes state management, logging, multiprocessing

    Subclasses must implement:
    - get_state_table_name(): Return state table name for this builder variant
    - get_output_table_name(): Return output bars table name
    - get_source_query(): Load source data for one ID
    - build_bars_for_id(): Build bars from daily data for one ID (the core logic)
    - from_cli_args(): Factory to create instance from CLI arguments
    - create_argument_parser(): Add script-specific arguments to base parser

    Invariants:
    - State table uses unified schema (id, tf) PRIMARY KEY
    - All scripts use incremental refresh by default
    - Full rebuild is opt-in via --full-rebuild flag
    - State is updated after successful computation

    Thread-safety: Not thread-safe. Create separate instances per worker.
    """

    def __init__(
        self,
        config: BarBuilderConfig,
        engine: Engine,
    ):
        """
        Initialize bar builder.

        Args:
            config: Bar builder configuration
            engine: SQLAlchemy engine for database operations
        """
        self.config = config
        self.engine = engine
        self.logger = self._setup_logging(
            name=self.__class__.__name__,
            level=config.log_level,
            log_file=config.log_file,
        )

    # =========================================================================
    # Logging Setup
    # =========================================================================

    def _setup_logging(
        self,
        name: str,
        level: str,
        log_file: Optional[str] = None,
    ) -> logging.Logger:
        """
        Configure logging for this builder.

        Args:
            name: Logger name (typically class name)
            level: Logging level (INFO, DEBUG, etc.)
            log_file: Optional log file path

        Returns:
            Configured logger instance
        """
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))

        # Clear existing handlers
        logger.handlers.clear()

        # Console handler
        console = logging.StreamHandler()
        console.setLevel(logger.level)
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console.setFormatter(fmt)
        logger.addHandler(console)

        # File handler (if requested)
        if log_file:
            fh = logging.FileHandler(log_file)
            fh.setLevel(logger.level)
            fh.setFormatter(fmt)
            logger.addHandler(fh)

        return logger

    # =========================================================================
    # Abstract Methods (MUST override)
    # =========================================================================

    @abstractmethod
    def get_state_table_name(self) -> str:
        """
        Return state table name for this builder variant.

        Returns:
            Fully qualified state table name (e.g., "public.cmc_price_bars_1d_state")

        Note on calendar builder state tables:
            The tz column in calendar builder state tables is metadata only,
            NOT part of PRIMARY KEY. Calendar builders process single timezone
            per run (--tz flag). See sql/ddl/calendar_state_tables.sql for full
            rationale.
        """

    @abstractmethod
    def get_output_table_name(self) -> str:
        """
        Return output bars table name for this builder variant.

        Returns:
            Fully qualified output table name (e.g., "public.cmc_price_bars_1d")
        """

    @abstractmethod
    def get_source_query(self, id_: int, start_ts: Optional[str] = None) -> str:
        """
        Return SQL query to load source data for one ID.

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp for incremental refresh

        Returns:
            SQL query string to load source data

        Example:
            return f'''
                SELECT id, timestamp, open, high, low, close, volume, market_cap
                FROM {self.config.daily_table}
                WHERE id = {id_}
                  AND ('{start_ts}' IS NULL OR timestamp >= '{start_ts}')
                ORDER BY timestamp;
            '''
        """

    @abstractmethod
    def build_bars_for_id(
        self,
        id_: int,
        start_ts: Optional[str] = None,
    ) -> int:
        """
        Build bars from daily data for one ID - variant-specific logic.

        This is the core computation method that delegates to the
        appropriate bar building logic (1D, multi-TF, calendar, etc.).

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp (for incremental refresh)

        Returns:
            Number of rows inserted/updated (0 if not available)

        Raises:
            Exception: On computation errors (logged and re-raised)
        """

    @classmethod
    @abstractmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create argument parser with script-specific arguments.

        Subclasses should:
        1. Call cls.create_base_argument_parser() to get base parser
        2. Add script-specific arguments (e.g., --tz for calendar builders)
        3. Return the parser

        Returns:
            ArgumentParser with all arguments configured
        """

    @classmethod
    @abstractmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "BaseBarBuilder":
        """
        Factory method: Create builder from CLI arguments.

        Subclasses implement this to:
        1. Resolve db_url from args.db_url
        2. Create engine
        3. Load IDs from args.ids (using parse_ids + load_all_ids helpers)
        4. Build BarBuilderConfig
        5. Return instance

        Args:
            args: Parsed CLI arguments from ArgumentParser

        Returns:
            Instance of the bar builder subclass
        """

    # =========================================================================
    # Template Methods (Concrete - define execution flow)
    # =========================================================================

    def run(self) -> None:
        """
        Main execution: Orchestrate bar building workflow.

        Template Method:
        1. Ensure state table exists
        2. Resolve IDs
        3. Execute full rebuild or incremental refresh
        4. Update state table

        This method defines the execution flow but delegates
        specifics to abstract methods.
        """
        self.logger.info(f"Starting bar builder: {self.__class__.__name__}")
        self.logger.info(
            f"Configuration: {len(self.config.ids)} IDs, "
            f"mode={'FULL REBUILD' if self.config.full_rebuild else 'INCREMENTAL'}"
        )

        # Ensure tables exist
        state_table = self.get_state_table_name()
        output_table = self.get_output_table_name()

        # Create tables (can be overridden by subclasses for custom schemas)
        self.ensure_state_table_exists()
        self.ensure_output_table_exists()
        self.logger.info(f"State table: {state_table}")
        self.logger.info(f"Output table: {output_table}")

        # Resolve IDs
        ids = self.config.ids
        self.logger.info(f"Processing {len(ids)} IDs")

        # Execute
        try:
            if self.config.full_rebuild:
                self.logger.info("Running FULL REBUILD")
                self._run_full_rebuild()
            else:
                self.logger.info("Running INCREMENTAL refresh")
                self._run_incremental()

            self.logger.info("Bar building complete")
        except Exception as e:
            self.logger.error(f"Bar building failed: {e}", exc_info=True)
            raise
        finally:
            # Ensure pooled connections are released
            self.engine.dispose()
            self.logger.debug("Database engine disposed")

    def _run_incremental(self) -> None:
        """
        Incremental mode: Load state, build bars for new/updated data.

        This method:
        1. Loads existing state
        2. For each ID, determines what needs to be built
        3. Calls build_bars_for_id() for each ID
        4. Updates state table after completion
        """
        state_table = self.get_state_table_name()
        with_tz = self.config.tz is not None

        # Load existing state
        state_df = load_state(
            self.config.db_url,
            state_table,
            self.config.ids,
            with_tz=with_tz,
        )

        if state_df.empty:
            self.logger.info("No existing state found - will build full history")
            start_times = {id_: None for id_ in self.config.ids}
        else:
            self.logger.info(f"Loaded state with {len(state_df)} records")
            # Build mapping of id -> MIN(last_time_close) for incremental start point.
            # State table PK is (id, tf), so multiple rows exist per ID.
            # We need the earliest last_time_close across all TFs for each ID
            # so that daily data loaded covers all TFs' incremental needs.
            start_times = {}
            for id_ in self.config.ids:
                id_state = state_df[state_df["id"] == id_]
                if id_state.empty:
                    start_times[id_] = None
                else:
                    ts_values = pd.to_datetime(
                        id_state["last_time_close"], errors="coerce"
                    ).dropna()
                    start_times[id_] = (
                        str(ts_values.min()) if not ts_values.empty else None
                    )

        # Process each ID
        total_rows = 0
        for id_ in self.config.ids:
            start_ts = start_times.get(id_)
            self.logger.info(
                f"Processing ID={id_}"
                + (f" (from {start_ts})" if start_ts else " (full history)")
            )

            try:
                rows = self.build_bars_for_id(id_=id_, start_ts=start_ts)
                total_rows += rows
                self.logger.info(f"ID={id_} complete: {rows} rows")
            except Exception as e:
                self.logger.error(f"ID={id_} failed: {e}", exc_info=True)
                continue

        self.logger.info(f"Completed: {total_rows} total rows")

    def _run_full_rebuild(self) -> None:
        """
        Full rebuild mode: Delete and rebuild all bars from scratch.

        This method:
        1. For each ID, calls build_bars_for_id() with start_ts=None
        2. Updates state table after completion
        """
        total_rows = 0

        for id_ in self.config.ids:
            self.logger.info(f"Processing ID={id_} (full rebuild)")

            try:
                rows = self.build_bars_for_id(id_=id_, start_ts=None)
                total_rows += rows
                self.logger.info(f"ID={id_} complete: {rows} rows")
            except Exception as e:
                self.logger.error(f"ID={id_} failed: {e}", exc_info=True)
                continue

        self.logger.info(f"Completed: {total_rows} total rows")

    # =========================================================================
    # Utility Methods (Helpers for subclasses)
    # =========================================================================

    def load_ids(self, ids_arg: str | list[int]) -> list[int]:
        """
        Load cryptocurrency IDs from argument.

        Supports:
        - "all": Load all IDs from source daily table
        - [1, 52, 825]: List of IDs

        Args:
            ids_arg: IDs argument from CLI

        Returns:
            List of cryptocurrency IDs
        """
        parsed = parse_ids(ids_arg)

        if parsed == "all":
            ids = load_all_ids(self.config.db_url, self.config.daily_table)
            self.logger.info(f"Loaded {len(ids)} IDs from {self.config.daily_table}")
            return ids

        # Already a list of integers
        self.logger.info(f"Processing {len(parsed)} IDs from command line")
        return parsed

    def get_table_type(self) -> str:
        """
        Get table type for DDL generation.

        Subclasses should override to specify their table type:
        - "1d" for refresh_cmc_price_bars_1d
        - "multi_tf" for refresh_cmc_price_bars_multi_tf
        - "cal" for cal_iso and cal_us builders
        - "cal_anchor" for cal_anchor_iso and cal_anchor_us builders

        Returns:
            Table type string (default: "multi_tf")
        """
        # Default to multi_tf, subclasses should override
        table_name = self.get_output_table_name().lower()

        if "_1d" in table_name:
            return "1d"
        elif "cal_anchor" in table_name:
            return "cal_anchor"
        elif "_cal_" in table_name:
            return "cal"
        else:
            return "multi_tf"

    def ensure_state_table_exists(self) -> None:
        """
        Create state table if it doesn't exist.

        Default implementation uses generic multi-TF state schema.
        Subclasses (like 1D builder) can override for custom schemas.
        """
        state_table = self.get_state_table_name()
        with_tz = self.config.tz is not None

        self.logger.info(f"Ensuring state table exists: {state_table}")

        try:
            ensure_state_table(self.config.db_url, state_table, with_tz=with_tz)
            self.logger.info(f"State table ready: {state_table}")
        except Exception as e:
            self.logger.error(f"Failed to create state table {state_table}: {e}")
            raise

    def ensure_output_table_exists(self) -> None:
        """
        Create output table if it doesn't exist.

        Uses get_table_type() to determine schema, then generates
        and executes CREATE TABLE IF NOT EXISTS DDL.

        Subclasses can override get_table_type() to control table schema.
        """
        table_name = self.get_output_table_name()
        table_type = self.get_table_type()

        self.logger.info(f"Ensuring table exists: {table_name} (type={table_type})")

        try:
            ensure_bar_table_exists(
                self.engine,
                table_name,
                table_type=table_type,
                schema="public",
            )
            self.logger.info(f"Table ready: {table_name}")
        except Exception as e:
            self.logger.error(f"Failed to create table {table_name}: {e}")
            raise

    # =========================================================================
    # CLI Integration
    # =========================================================================

    @classmethod
    def create_base_argument_parser(
        cls,
        description: str,
        default_daily_table: str,
        default_bars_table: str,
        default_state_table: str,
        include_tz: bool = False,
        default_tz: str = "America/New_York",
    ) -> argparse.ArgumentParser:
        """
        Create argument parser with common bar builder arguments.

        Subclasses should call this method and add script-specific arguments.

        Args:
            description: Script description for --help
            default_daily_table: Default daily price table name
            default_bars_table: Default output bars table name
            default_state_table: Default state table name
            include_tz: Add --tz flag (for calendar builders)
            default_tz: Default timezone value

        Returns:
            ArgumentParser with common arguments configured
        """
        return create_bar_builder_argument_parser(
            description=description,
            default_daily_table=default_daily_table,
            default_bars_table=default_bars_table,
            default_state_table=default_state_table,
            default_tz=default_tz,
            include_tz=include_tz,
            include_fail_on_gaps=False,
        )

    @classmethod
    def main(cls, argv: Sequence[str] | None = None) -> None:
        """
        Standard CLI entry point.

        Usage:
            if __name__ == "__main__":
                MultiTFBarBuilder.main()

        Args:
            argv: Command line arguments (default: sys.argv)
        """
        parser = cls.create_argument_parser()
        args = parser.parse_args(argv)
        builder = cls.from_cli_args(args)
        builder.run()
