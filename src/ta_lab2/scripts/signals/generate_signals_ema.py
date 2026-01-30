"""
EMA Signal Generator - Generate EMA crossover signals from cmc_daily_features.

This module generates EMA crossover trading signals using the existing ema_trend.py
adapter. Signals are stored in cmc_signals_ema_crossover with full feature snapshots
and version hashes for reproducibility.

Architecture:
- Load signal configurations from dim_signals (not hardcoded)
- Fetch features from cmc_daily_features
- Generate signals using ema_trend.make_signals
- Transform to stateful position records (open/closed)
- Store in database with feature hashing

Usage:
    from ta_lab2.scripts.signals.generate_signals_ema import EMASignalGenerator
    from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig

    config = SignalStateConfig(signal_type='ema_crossover')
    state_manager = SignalStateManager(engine, config)
    generator = EMASignalGenerator(engine, state_manager)

    signal_config = {
        'signal_id': 1,
        'signal_name': 'ema_9_21_long',
        'params': {'fast_period': 9, 'slow_period': 21, 'direction': 'long'}
    }

    n_signals = generator.generate_for_ids(
        ids=[1, 52, 1027],
        signal_config=signal_config,
        full_refresh=False
    )
"""

from dataclasses import dataclass
from typing import Optional
import logging
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.signals.ema_trend import make_signals
from .signal_state_manager import SignalStateManager
from .signal_utils import compute_feature_hash, compute_params_hash


logger = logging.getLogger(__name__)


@dataclass
class EMASignalGenerator:
    """
    Generate EMA crossover signals from cmc_daily_features.

    Attributes:
        engine: SQLAlchemy engine for database operations
        state_manager: SignalStateManager for position lifecycle tracking
        signal_version: Signal code version (default: "1.0")
    """

    engine: Engine
    state_manager: SignalStateManager
    signal_version: str = "1.0"

    def generate_for_ids(
        self,
        ids: list[int],
        signal_config: dict,
        full_refresh: bool = False,
        dry_run: bool = False,
    ) -> int:
        """
        Generate EMA crossover signals for specified assets.

        Main entry point for signal generation. Handles incremental vs full refresh,
        loads features, generates signals using ema_trend adapter, transforms to
        stateful records, and writes to database.

        Args:
            ids: List of asset IDs to generate signals for
            signal_config: Signal configuration from dim_signals
                Required keys: signal_id, signal_name, params
                params must contain: fast_period, slow_period, direction
            full_refresh: If True, recompute all signals (ignore state)
            dry_run: If True, preview without writing to database

        Returns:
            Number of signal records generated (both entries and exits)

        Raises:
            KeyError: If required params missing from signal_config
            ValueError: If features DataFrame empty
            sqlalchemy.exc.SQLAlchemyError: On database errors
        """
        signal_id = signal_config['signal_id']
        signal_name = signal_config['signal_name']
        params = signal_config['params']

        logger.info(f"Generating signals for {signal_name} (signal_id={signal_id})")
        logger.debug(f"  IDs: {len(ids)}, full_refresh={full_refresh}, dry_run={dry_run}")

        # 1. Load open positions if incremental
        open_positions = pd.DataFrame()
        if not full_refresh:
            open_positions = self.state_manager.load_open_positions(ids, signal_id)
            logger.debug(f"  Loaded {len(open_positions)} open positions")

        # 2. Determine dirty window start
        if full_refresh:
            start_ts = None  # Load all history
        else:
            # Get per-ID dirty windows
            dirty_windows = self.state_manager.get_dirty_window_start(ids, signal_id)
            # Use minimum start_ts across all IDs (conservative)
            start_timestamps = [ts for ts in dirty_windows.values() if ts is not None]
            start_ts = min(start_timestamps) if start_timestamps else None

        logger.debug(f"  Dirty window start: {start_ts}")

        # 3. Load features from cmc_daily_features
        features_df = self._load_features(ids, start_ts)

        if features_df.empty:
            logger.warning("  No features found - skipping signal generation")
            return 0

        logger.debug(f"  Loaded {len(features_df)} feature rows")

        # 4. Generate signals using ema_trend adapter
        entries, exits, size = self._generate_signals(features_df, params)

        logger.debug(f"  Generated {entries.sum()} entries, {exits.sum()} exits")

        # 5. Transform to stateful records
        records = self._transform_signals_to_records(
            df=features_df,
            entries=entries,
            exits=exits,
            signal_id=signal_id,
            params=params,
            open_positions=open_positions,
        )

        if records.empty:
            logger.info("  No signals to write")
            return 0

        logger.info(f"  Transformed to {len(records)} signal records")

        # 6. Write to database
        if not dry_run:
            self._write_signals(records, 'cmc_signals_ema_crossover')
            logger.info(f"  Wrote {len(records)} signals to database")
        else:
            logger.info(f"  DRY RUN: Would write {len(records)} signals")

        return len(records)

    def _load_features(
        self,
        ids: list[int],
        start_ts: Optional[pd.Timestamp],
    ) -> pd.DataFrame:
        """
        Load features from cmc_daily_features.

        Uses explicit column list for hash stability (ensures same columns
        in same order every time).

        Args:
            ids: List of asset IDs
            start_ts: Timestamp to load from (None = all history)

        Returns:
            DataFrame with columns: id, ts, close, ema_9, ema_10, ema_21, ema_50, ema_200, rsi_14, atr_14
        """
        # Explicit column list for hash stability
        columns = [
            "id", "ts", "close",
            "ema_9", "ema_10", "ema_21", "ema_50", "ema_200",
            "rsi_14", "atr_14"
        ]

        where_clauses = ["id = ANY(:ids)"]
        params = {"ids": ids}

        if start_ts is not None:
            where_clauses.append("ts >= :start_ts")
            params["start_ts"] = start_ts

        where_sql = " AND ".join(where_clauses)

        sql_text = f"""
            SELECT {', '.join(columns)}
            FROM public.cmc_daily_features
            WHERE {where_sql}
            ORDER BY id, ts
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            return pd.read_sql(sql, conn, params=params)

    def _generate_signals(
        self,
        df: pd.DataFrame,
        params: dict,
    ) -> tuple[pd.Series, pd.Series, Optional[pd.Series]]:
        """
        Generate signals using ema_trend.make_signals adapter.

        Maps signal params to ema_trend function parameters.

        Args:
            df: Features DataFrame with EMA columns
            params: Signal parameters from dim_signals
                Must contain: fast_period, slow_period
                Optional: direction, use_rsi_filter, rsi_min_long, etc.

        Returns:
            Tuple of (entries, exits, size) - all boolean/float Series indexed by df.index
        """
        # Map params to ema_trend column names
        fast_period = params['fast_period']
        slow_period = params['slow_period']
        fast_ema = f"ema_{fast_period}"
        slow_ema = f"ema_{slow_period}"

        # Get optional parameters with defaults
        use_rsi_filter = params.get('use_rsi_filter', False)
        use_vol_filter = params.get('use_vol_filter', False)
        allow_shorts = params.get('direction', 'long') != 'long'
        rsi_min_long = params.get('rsi_min_long', 45)
        rsi_max_short = params.get('rsi_max_short', 55)
        min_atr_pct = params.get('min_atr_pct', 0.003)
        cooldown_bars = params.get('cooldown_bars', 0)

        # Call ema_trend adapter
        entries, exits, size = make_signals(
            df=df,
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            use_rsi_filter=use_rsi_filter,
            use_vol_filter=use_vol_filter,
            rsi_min_long=rsi_min_long,
            rsi_max_short=rsi_max_short,
            min_atr_pct=min_atr_pct,
            allow_shorts=allow_shorts,
            cooldown_bars=cooldown_bars,
        )

        return entries, exits, size

    def _transform_signals_to_records(
        self,
        df: pd.DataFrame,
        entries: pd.Series,
        exits: pd.Series,
        signal_id: int,
        params: dict,
        open_positions: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Transform entry/exit signals to stateful position records.

        Logic:
        - Entry event: Create record with position_state='open', entry_price=close
        - Exit event: Find matching open position, update to 'closed', compute pnl_pct
        - Capture feature_snapshot at entry: {close, fast_ema, slow_ema, rsi, atr}
        - Compute feature_version_hash, params_hash for reproducibility

        Args:
            df: Features DataFrame with all columns
            entries: Boolean Series indicating entry signals
            exits: Boolean Series indicating exit signals
            signal_id: Signal ID from dim_signals
            params: Signal parameters dict
            open_positions: DataFrame of existing open positions (from state manager)

        Returns:
            DataFrame with columns matching cmc_signals_ema_crossover schema
        """
        fast_period = params['fast_period']
        slow_period = params['slow_period']
        fast_ema = f"ema_{fast_period}"
        slow_ema = f"ema_{slow_period}"
        direction = params.get('direction', 'long')

        records = []

        # Compute hashes for reproducibility
        feature_cols = ['close', fast_ema, slow_ema, 'rsi_14', 'atr_14']
        feature_hash = compute_feature_hash(df, feature_cols)
        params_hash = compute_params_hash(params)

        # Group by ID for per-asset processing
        for asset_id, group in df.groupby('id'):
            # Get open positions for this asset
            asset_open = open_positions[open_positions['id'] == asset_id] if not open_positions.empty else pd.DataFrame()

            # Track open positions as we iterate chronologically
            open_list = list(asset_open.to_dict('records')) if not asset_open.empty else []

            for idx, row in group.iterrows():
                ts = row['ts']
                close = row['close']

                # Handle entry signals
                if entries[idx]:
                    feature_snapshot = {
                        'close': float(close),
                        'fast_ema': float(row[fast_ema]),
                        'slow_ema': float(row[slow_ema]),
                        'rsi_14': float(row['rsi_14']) if pd.notna(row['rsi_14']) else None,
                        'atr_14': float(row['atr_14']) if pd.notna(row['atr_14']) else None,
                    }

                    record = {
                        'id': asset_id,
                        'ts': ts,
                        'signal_id': signal_id,
                        'direction': direction,
                        'position_state': 'open',
                        'entry_price': close,
                        'entry_ts': ts,
                        'exit_price': None,
                        'exit_ts': None,
                        'pnl_pct': None,
                        'feature_snapshot': feature_snapshot,
                        'signal_version': self.signal_version,
                        'feature_version_hash': feature_hash,
                        'params_hash': params_hash,
                    }
                    records.append(record)
                    open_list.append(record)

                # Handle exit signals
                if exits[idx]:
                    # Find oldest open position (FIFO)
                    if open_list:
                        open_pos = open_list.pop(0)
                        entry_price = open_pos['entry_price']
                        entry_ts = open_pos['entry_ts']

                        # Compute PnL
                        if direction == 'long':
                            pnl_pct = ((close - entry_price) / entry_price) * 100
                        else:  # short
                            pnl_pct = ((entry_price - close) / entry_price) * 100

                        # Create exit record
                        record = {
                            'id': asset_id,
                            'ts': ts,
                            'signal_id': signal_id,
                            'direction': direction,
                            'position_state': 'closed',
                            'entry_price': entry_price,
                            'entry_ts': entry_ts,
                            'exit_price': close,
                            'exit_ts': ts,
                            'pnl_pct': pnl_pct,
                            'feature_snapshot': open_pos['feature_snapshot'],  # Keep entry snapshot
                            'signal_version': self.signal_version,
                            'feature_version_hash': feature_hash,
                            'params_hash': params_hash,
                        }
                        records.append(record)

        return pd.DataFrame(records)

    def _write_signals(
        self,
        records: pd.DataFrame,
        signal_table: str,
    ) -> None:
        """
        Write signal records to database.

        Uses pandas to_sql with append mode. Note: This does not handle duplicates.
        For true idempotency, would need UPSERT logic.

        Args:
            records: DataFrame with signal records
            signal_table: Target table name (e.g., 'cmc_signals_ema_crossover')
        """
        # Convert feature_snapshot dict to JSON (pandas handles this automatically for JSONB)
        records.to_sql(
            signal_table,
            self.engine,
            schema='public',
            if_exists='append',
            index=False,
            method='multi',
        )
