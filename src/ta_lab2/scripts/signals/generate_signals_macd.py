"""
MACD Crossover Signal Generator - Generate MACD crossover signals from features.

This module generates MACD crossover trading signals using the macd_crossover.py
adapter.  Signals are stored in signals_macd_crossover with full feature snapshots
and version hashes for reproducibility.

MACD values are computed in-memory from the close price loaded from the features
table.  No separate pre-computed table is required (unlike AMA generators).

Architecture:
- Load signal configurations from dim_signals (not hardcoded)
- Fetch close prices from features table
- Compute MACD columns in-memory via macd_crossover.make_signals
- Transform to stateful position records (open/closed)
- Store in signals_macd_crossover with feature hashing

Usage:
    from ta_lab2.scripts.signals.generate_signals_macd import MACDSignalGenerator
    from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig

    config = SignalStateConfig(signal_type='macd_crossover')
    state_manager = SignalStateManager(engine, config)
    generator = MACDSignalGenerator(engine, state_manager)

    signal_config = {
        'signal_id': 5,
        'signal_name': 'macd_12_26_9_long',
        'params': {'fast': 12, 'slow': 26, 'signal': 9, 'direction': 'long'}
    }

    n_signals = generator.generate_for_ids(
        ids=[1, 52, 1027],
        signal_config=signal_config,
        full_refresh=False
    )
"""

from dataclasses import dataclass
from typing import Optional
import json
import logging
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.signals.macd_crossover import make_signals
from ta_lab2.labeling.cusum_filter import cusum_filter, get_cusum_threshold
from .signal_state_manager import SignalStateManager
from .signal_utils import compute_feature_hash, compute_params_hash
from .regime_utils import load_regime_context_batch, merge_regime_context


logger = logging.getLogger(__name__)

# Target table for MACD crossover signals
_SIGNAL_TABLE = "signals_macd_crossover"


@dataclass
class MACDSignalGenerator:
    """
    Generate MACD crossover signals from features.

    MACD columns (fast/slow EMA difference and its signal-line EMA) are computed
    in-memory from the close price so there is no dependency on a pre-computed
    table.  This keeps the generator self-contained and runnable as part of
    Batch 1 (alongside EMA, RSI, ATR generators) before any AMA refresh.

    Attributes:
        engine: SQLAlchemy engine for database operations
        state_manager: SignalStateManager for position lifecycle tracking
        signal_version: Signal code version (default: "1.0")
        venue_id: Optional venue filter; None means all venues
    """

    engine: Engine
    state_manager: SignalStateManager
    signal_version: str = "1.0"
    venue_id: int | None = None

    def generate_for_ids(
        self,
        ids: list[int],
        signal_config: dict,
        full_refresh: bool = False,
        dry_run: bool = False,
        regime_enabled: bool = True,
        cusum_enabled: bool = False,
        cusum_threshold_multiplier: float = 2.0,
    ) -> int:
        """
        Generate MACD crossover signals for specified assets.

        Main entry point for signal generation.  Handles incremental vs full
        refresh, loads features, generates signals using the macd_crossover
        adapter, transforms to stateful records, and writes to database.

        Args:
            ids: List of asset IDs to generate signals for
            signal_config: Signal configuration from dim_signals
                Required keys: signal_id, signal_name, params
                params keys: fast (int), slow (int), signal (int), direction (str)
            full_refresh: If True, recompute all signals (ignore state)
            dry_run: If True, preview without writing to database
            regime_enabled: If True, load regime context and attach regime_key
                to signal records.
            cusum_enabled: If True, apply symmetric CUSUM pre-filter to reduce
                noise.  Default False preserves backward-compatible behaviour.
            cusum_threshold_multiplier: EWM-vol multiplier for CUSUM threshold.
                Default 2.0.

        Returns:
            Number of signal records generated (both entries and exits)
        """
        signal_id = signal_config["signal_id"]
        signal_name = signal_config["signal_name"]
        params = signal_config["params"]

        logger.info(
            f"Generating MACD signals for {signal_name} (signal_id={signal_id})"
        )
        logger.debug(
            f"  IDs: {len(ids)}, full_refresh={full_refresh}, dry_run={dry_run}, "
            f"regime_enabled={regime_enabled}"
        )

        # 1. Load open positions for incremental mode
        open_positions = pd.DataFrame()
        if not full_refresh:
            open_positions = self.state_manager.load_open_positions(ids, signal_id)
            logger.debug(f"  Loaded {len(open_positions)} open positions")

        # 2. Determine dirty window start
        if full_refresh:
            start_ts = None
        else:
            dirty_windows = self.state_manager.get_dirty_window_start(ids, signal_id)
            start_timestamps = [ts for ts in dirty_windows.values() if ts is not None]
            start_ts = min(start_timestamps) if start_timestamps else None

        logger.debug(f"  Dirty window start: {start_ts}")

        # 3. Load features from features table
        features_df = self._load_features(ids, start_ts)

        if features_df.empty:
            logger.warning("  No features found - skipping signal generation")
            return 0

        logger.debug(f"  Loaded {len(features_df)} feature rows")

        # 3b. Apply CUSUM pre-filter (if enabled)
        if cusum_enabled:
            features_df = self._apply_cusum_filter(
                features_df, cusum_threshold_multiplier
            )
            if features_df.empty:
                logger.warning("  CUSUM filter removed all rows - skipping")
                return 0

        # 4. Load and merge regime context (if enabled)
        if regime_enabled:
            regime_df = load_regime_context_batch(
                engine=self.engine, ids=ids, start_ts=start_ts
            )
            features_df = merge_regime_context(features_df, regime_df)
            n_with_regime = features_df["regime_key"].notna().sum()
            logger.info(
                f"  Regime context: {n_with_regime}/{len(features_df)} rows have regime data"
            )
        else:
            logger.info("  Regime context disabled (--no-regime mode)")
            features_df["regime_key"] = None
            features_df["size_mult"] = None
            features_df["stop_mult"] = None
            features_df["orders"] = None

        # 5. Generate signals using macd_crossover adapter
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal_period = params.get("signal", 9)
        direction = params.get("direction", "long")

        entries, exits, size = make_signals(
            features_df,
            fast=fast,
            slow=slow,
            signal=signal_period,
            direction=direction,
        )

        logger.debug(f"  Generated {entries.sum()} entries, {exits.sum()} exits")

        # 6. Transform to stateful records
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

        # 7. Write to database
        if not dry_run:
            self._write_signals(records)
            logger.info(f"  Wrote {len(records)} signals to {_SIGNAL_TABLE}")
        else:
            logger.info(f"  DRY RUN: Would write {len(records)} signals")

        return len(records)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_features(
        self,
        ids: list[int],
        start_ts: Optional[pd.Timestamp],
    ) -> pd.DataFrame:
        """
        Load close prices (and basic OHLC) from features table.

        MACD is computed from close price only, so we load close plus
        rsi_14 and atr_14 for the feature snapshot.

        Args:
            ids: List of asset IDs
            start_ts: Earliest timestamp to load (None = all history)

        Returns:
            DataFrame with columns: id, venue_id, ts, close, rsi_14, atr_14
        """
        where_clauses = ["id = ANY(:ids)", "tf = '1D'"]
        params: dict = {"ids": ids}

        if self.venue_id is not None:
            where_clauses.append("venue_id = :venue_id")
            params["venue_id"] = self.venue_id

        if start_ts is not None:
            where_clauses.append("ts >= :start_ts")
            params["start_ts"] = start_ts

        where_sql = " AND ".join(where_clauses)

        sql_text = f"""
            SELECT id, venue_id, ts, close, rsi_14, atr_14
            FROM public.features
            WHERE {where_sql}
            ORDER BY id, ts
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql_text), conn, params=params)

        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)

        return df

    def _apply_cusum_filter(
        self,
        features_df: pd.DataFrame,
        multiplier: float,
    ) -> pd.DataFrame:
        """
        Apply per-asset symmetric CUSUM pre-filter.

        Args:
            features_df: DataFrame with columns id, ts, close (and others).
            multiplier: EWM-vol scaling factor for threshold calibration.

        Returns:
            Filtered DataFrame containing only CUSUM event rows.
        """
        n_before = len(features_df)
        filtered_parts = []

        for asset_id, group in features_df.groupby("id"):
            group = group.sort_values("ts").reset_index(drop=True)

            close = group.set_index("ts")["close"]
            if not isinstance(close.index, pd.DatetimeIndex):
                close.index = pd.to_datetime(close.index, utc=True)

            if len(close) < 2:
                filtered_parts.append(group)
                continue

            threshold = get_cusum_threshold(close, multiplier=multiplier)
            if threshold <= 0:
                logger.warning(
                    f"  CUSUM threshold <= 0 for id={asset_id}, skipping filter"
                )
                filtered_parts.append(group)
                continue

            cusum_events = cusum_filter(close, threshold)

            if len(cusum_events) == 0:
                logger.warning(
                    f"  CUSUM returned 0 events for id={asset_id} "
                    f"(threshold={threshold:.6f}), retaining all bars"
                )
                filtered_parts.append(group)
                continue

            event_set = set(pd.to_datetime(cusum_events, utc=True).tolist())
            ts_utc = pd.to_datetime(group["ts"], utc=True)
            mask = ts_utc.isin(event_set)
            filtered_parts.append(group[mask])

        if not filtered_parts:
            return pd.DataFrame(columns=features_df.columns)

        result = pd.concat(filtered_parts, ignore_index=True)
        n_after = len(result)
        total_reduction = (1 - n_after / n_before) * 100 if n_before > 0 else 0
        logger.info(
            f"  CUSUM total: {n_after}/{n_before} rows retained "
            f"({total_reduction:.1f}% reduction, multiplier={multiplier})"
        )
        return result

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
        - Exit event: Find matching open position (FIFO), update to 'closed',
          compute pnl_pct
        - Capture feature_snapshot at entry: {close, macd, macd_signal, rsi_14, atr_14}

        Args:
            df: Features DataFrame (must contain macd, macd_signal after make_signals
                has been called — those columns are added in-place by _ensure_macd).
            entries: Boolean Series indicating entry signals
            exits: Boolean Series indicating exit signals
            signal_id: Signal ID from dim_signals
            params: Signal parameters dict
            open_positions: DataFrame of existing open positions (from state manager)

        Returns:
            DataFrame with columns matching signals_macd_crossover schema
        """
        direction = params.get("direction", "long")
        params_hash = compute_params_hash(params)

        # Feature columns for hashing
        feature_cols = ["close", "macd", "macd_signal", "rsi_14", "atr_14"]
        # Only hash columns that actually exist in df
        existing_feature_cols = [c for c in feature_cols if c in df.columns]
        feature_hash = compute_feature_hash(df, existing_feature_cols)

        records = []

        for (asset_id, venue_id), group in df.groupby(["id", "venue_id"]):
            # Get open positions for this asset
            if not open_positions.empty:
                _mask = open_positions["id"] == asset_id
                if "venue_id" in open_positions.columns:
                    _mask = _mask & (open_positions["venue_id"] == venue_id)
                asset_open = open_positions[_mask]
            else:
                asset_open = pd.DataFrame()

            open_list = (
                list(asset_open.to_dict("records")) if not asset_open.empty else []
            )

            for idx, row in group.iterrows():
                ts = row["ts"]
                close = row["close"]

                # Regime key for this bar
                raw_rk = row.get("regime_key") if "regime_key" in row.index else None
                regime_key = (
                    None
                    if (
                        raw_rk is None
                        or (isinstance(raw_rk, float) and pd.isna(raw_rk))
                    )
                    else raw_rk
                )

                # Handle entry signals
                if entries[idx]:
                    feature_snapshot: dict = {
                        "close": float(close),
                        "macd": float(row["macd"])
                        if "macd" in row.index and pd.notna(row["macd"])
                        else None,
                        "macd_signal": float(row["macd_signal"])
                        if "macd_signal" in row.index and pd.notna(row["macd_signal"])
                        else None,
                        "rsi_14": float(row["rsi_14"])
                        if "rsi_14" in row.index and pd.notna(row["rsi_14"])
                        else None,
                        "atr_14": float(row["atr_14"])
                        if "atr_14" in row.index and pd.notna(row["atr_14"])
                        else None,
                    }

                    record: dict = {
                        "id": asset_id,
                        "venue_id": int(venue_id),
                        "ts": ts,
                        "signal_id": signal_id,
                        "direction": direction,
                        "position_state": "open",
                        "entry_price": close,
                        "entry_ts": ts,
                        "exit_price": None,
                        "exit_ts": None,
                        "pnl_pct": None,
                        "feature_snapshot": feature_snapshot,
                        "signal_version": self.signal_version,
                        "feature_version_hash": feature_hash,
                        "params_hash": params_hash,
                        "regime_key": regime_key,
                        "executor_processed_at": None,
                    }
                    records.append(record)
                    open_list.append(record)

                # Handle exit signals
                if exits[idx]:
                    if open_list:
                        open_pos = open_list.pop(0)
                        entry_price = open_pos["entry_price"]
                        entry_ts = open_pos["entry_ts"]

                        if direction == "long":
                            pnl_pct = ((close - entry_price) / entry_price) * 100
                        else:
                            pnl_pct = ((entry_price - close) / entry_price) * 100

                        record = {
                            "id": asset_id,
                            "venue_id": int(venue_id),
                            "ts": ts,
                            "signal_id": signal_id,
                            "direction": direction,
                            "position_state": "closed",
                            "entry_price": entry_price,
                            "entry_ts": entry_ts,
                            "exit_price": close,
                            "exit_ts": ts,
                            "pnl_pct": pnl_pct,
                            "feature_snapshot": open_pos["feature_snapshot"],
                            "signal_version": self.signal_version,
                            "feature_version_hash": feature_hash,
                            "params_hash": params_hash,
                            "regime_key": regime_key,
                            "executor_processed_at": None,
                        }
                        records.append(record)

        return pd.DataFrame(records)

    def _write_signals(
        self,
        records: pd.DataFrame,
    ) -> None:
        """
        Write signal records to signals_macd_crossover via temp-table upsert.

        Uses INSERT ... ON CONFLICT DO UPDATE for idempotent incremental runs.

        Args:
            records: DataFrame with signal records
        """
        records = records.copy()
        records["feature_snapshot"] = records["feature_snapshot"].apply(
            lambda x: json.dumps(x) if isinstance(x, dict) else x
        )

        pk_cols = ["id", "venue_id", "ts", "signal_id"]
        records = records.drop_duplicates(subset=pk_cols, keep="last")
        data_cols = [
            c for c in records.columns if c not in pk_cols and c != "created_at"
        ]
        tmp = f"_tmp_{_SIGNAL_TABLE}"

        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
            conn.execute(
                text(
                    f"CREATE TEMP TABLE {tmp} "
                    f"(LIKE public.{_SIGNAL_TABLE} INCLUDING DEFAULTS) ON COMMIT DROP"
                )
            )
            records.to_sql(tmp, conn, if_exists="append", index=False, method="multi")
            set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in data_cols)
            conn.execute(
                text(
                    f"INSERT INTO public.{_SIGNAL_TABLE} ({', '.join(records.columns)}) "
                    f"SELECT {', '.join(records.columns)} FROM {tmp} "
                    f"ON CONFLICT ({', '.join(pk_cols)}) DO UPDATE SET {set_clause}"
                )
            )
