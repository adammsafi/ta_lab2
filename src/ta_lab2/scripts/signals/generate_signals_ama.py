"""
AMA Signal Generator - Generate AMA-based signals from pre-computed AMA values.

This module wraps all three AMA signal types (momentum, mean-reversion, regime-conditional)
in a single generator class.  The critical difference from EMA/RSI/ATR/MACD generators is
that AMA columns MUST be loaded from `ama_multi_tf_u` before calling signal functions.
AMA values should NOT be re-computed from price in this module (see CRITICAL note below).

CRITICAL: AMA columns are pre-computed by the AMA refresh pipeline and stored in
`ama_multi_tf_u`.  Re-computing them locally introduces fold-boundary lookback
contamination (Pitfall 6 in 82-RESEARCH.md).  This generator therefore:
1. Loads features from `features` table (OHLC, rsi, atr)
2. Loads AMA values from `ama_multi_tf_u` and pivots into columns
3. Merges them by (id, ts) before calling signal functions from ama_composite.py

For this reason, AMA generators run in Batch 2 of run_all_signal_refreshes.py
(after the AMA refresh has completed), not in Batch 1 with EMA/RSI/ATR/MACD.

Usage:
    from ta_lab2.scripts.signals.generate_signals_ama import AMASignalGenerator
    from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig

    config = SignalStateConfig(signal_type='ama_momentum')
    state_manager = SignalStateManager(engine, config)
    generator = AMASignalGenerator(
        engine=engine,
        state_manager=state_manager,
        signal_subtype='ama_momentum'
    )

    signal_config = {
        'signal_id': 6,
        'signal_name': 'ama_momentum_v1',
        'params': {'holding_bars': 7, 'threshold': 0.0}
    }

    n_signals = generator.generate_for_ids(
        ids=[1, 52],
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

from ta_lab2.signals.ama_composite import (
    ama_momentum_signal,
    ama_mean_reversion_signal,
    ama_regime_conditional_signal,
)
from .signal_state_manager import SignalStateManager
from .signal_utils import compute_feature_hash, compute_params_hash
from .regime_utils import load_regime_context_batch, merge_regime_context


logger = logging.getLogger(__name__)

# Mapping from signal subtype to target signal table
_TABLE_MAP: dict[str, str] = {
    "ama_momentum": "signals_ama_momentum",
    "ama_mean_reversion": "signals_ama_mean_reversion",
    "ama_regime_conditional": "signals_ama_regime_conditional",
}

# Mapping from signal subtype to signal function
_SIGNAL_FN_MAP = {
    "ama_momentum": ama_momentum_signal,
    "ama_mean_reversion": ama_mean_reversion_signal,
    "ama_regime_conditional": ama_regime_conditional_signal,
}


@dataclass
class AMASignalGenerator:
    """
    Generate AMA-based signals from pre-computed AMA values.

    Wraps all three AMA signal archetypes behind a single class.  The subtype
    determines which signal function and target table are used.

    IMPORTANT: AMA values are always loaded from ama_multi_tf_u.  Never
    re-compute AMA from price inside this generator.

    Attributes:
        engine: SQLAlchemy engine for database operations
        state_manager: SignalStateManager for position lifecycle tracking
        signal_subtype: One of 'ama_momentum', 'ama_mean_reversion',
                        'ama_regime_conditional'
        signal_version: Signal code version (default: "1.0")
        venue_id: Optional venue filter; None means all venues
    """

    engine: Engine
    state_manager: SignalStateManager
    signal_subtype: str = "ama_momentum"
    signal_version: str = "1.0"
    venue_id: int | None = None

    def __post_init__(self) -> None:
        valid_subtypes = set(_TABLE_MAP)
        if self.signal_subtype not in valid_subtypes:
            raise ValueError(
                f"signal_subtype must be one of {sorted(valid_subtypes)}, "
                f"got '{self.signal_subtype}'"
            )

    def generate_for_ids(
        self,
        ids: list[int],
        signal_config: dict,
        full_refresh: bool = False,
        dry_run: bool = False,
        regime_enabled: bool = True,
    ) -> int:
        """
        Generate AMA signals for specified assets.

        Loads features and pre-computed AMA columns, then calls the appropriate
        signal function based on signal_subtype.

        Args:
            ids: List of asset IDs to generate signals for
            signal_config: Signal configuration from dim_signals
                Required keys: signal_id, signal_name, params
            full_refresh: If True, recompute all signals (ignore state)
            dry_run: If True, preview without writing to database
            regime_enabled: If True, load regime context and attach regime_key

        Returns:
            Number of signal records generated (both entries and exits)
        """
        signal_id = signal_config["signal_id"]
        signal_name = signal_config["signal_name"]
        params = signal_config["params"]
        signal_table = _TABLE_MAP[self.signal_subtype]

        logger.info(
            f"Generating AMA ({self.signal_subtype}) signals for {signal_name} "
            f"(signal_id={signal_id})"
        )
        logger.debug(
            f"  IDs: {len(ids)}, full_refresh={full_refresh}, "
            f"dry_run={dry_run}, regime_enabled={regime_enabled}"
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

        # 3. Load features (OHLC + indicators)
        features_df = self._load_features(ids, start_ts)

        if features_df.empty:
            logger.warning("  No features found - skipping signal generation")
            return 0

        logger.debug(f"  Loaded {len(features_df)} feature rows")

        # 4. Load and pivot AMA values from ama_multi_tf_u
        ama_df = self._load_ama_columns(ids, start_ts)
        if not ama_df.empty:
            features_df = features_df.merge(ama_df, on=["id", "ts"], how="left")
            n_ama_cols = ama_df.shape[1] - 2  # subtract id, ts
            logger.info(f"  Merged {n_ama_cols} AMA column(s) into features")
        else:
            logger.warning(
                "  No AMA values found in ama_multi_tf_u — "
                "AMA signal functions will return empty signals (graceful degradation)"
            )

        # 5. Load and merge regime context (if enabled)
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

        # 6. Generate signals using the appropriate AMA function
        signal_fn = _SIGNAL_FN_MAP[self.signal_subtype]
        entries, exits, size = signal_fn(features_df, **params)

        logger.debug(f"  Generated {entries.sum()} entries, {exits.sum()} exits")

        # 7. Transform to stateful records
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

        # 8. Write to database
        if not dry_run:
            self._write_signals(records, signal_table)
            logger.info(f"  Wrote {len(records)} signals to {signal_table}")
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
        Load OHLC features from features table.

        Loads open, high, low, close (needed for ADX computation in regime-
        conditional signal) plus rsi_14 and atr_14 for feature snapshots.

        Args:
            ids: List of asset IDs
            start_ts: Earliest timestamp to load (None = all history)

        Returns:
            DataFrame with columns: id, venue_id, ts, open, high, low, close, rsi_14, atr_14
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
            SELECT id, venue_id, ts, open, high, low, close, rsi_14, atr_14
            FROM public.features
            WHERE {where_sql}
            ORDER BY id, ts
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql_text), conn, params=params)

        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)

        return df

    def _load_ama_columns(
        self,
        ids: list[int],
        start_ts: Optional[pd.Timestamp],
    ) -> pd.DataFrame:
        """
        Load pre-computed AMA values from ama_multi_tf_u and pivot to wide format.

        Each (indicator, params_hash) combination becomes a column named
        ``{INDICATOR}_{ph}_ama`` (e.g., ``TEMA_0fca19a1_ama``).

        Uses DISTINCT ON to deduplicate where multiple alignment_source rows
        exist for the same (id, ts, indicator, params_hash).

        Args:
            ids: List of asset IDs
            start_ts: Earliest timestamp to load (None = all history)

        Returns:
            Wide DataFrame indexed by (id, ts) with one column per AMA variant.
            Returns empty DataFrame if no AMA data found.
        """
        effective_venue_id = self.venue_id if self.venue_id is not None else 1

        where_clauses = [
            "a.id = ANY(:ids)",
            "a.tf = '1D'",
            "a.venue_id = :venue_id",
            "a.alignment_source = 'multi_tf'",
            "a.roll = FALSE",
        ]
        params: dict = {"ids": ids, "venue_id": effective_venue_id}

        if start_ts is not None:
            where_clauses.append("a.ts >= :start_ts")
            params["start_ts"] = start_ts

        where_sql = " AND ".join(where_clauses)

        sql_text = f"""
            SELECT DISTINCT ON (a.id, a.ts, a.indicator, LEFT(a.params_hash, 8))
                a.id,
                a.ts,
                a.indicator,
                LEFT(a.params_hash, 8) AS ph,
                a.ama
            FROM public.ama_multi_tf_u a
            WHERE {where_sql}
            ORDER BY a.id, a.ts, a.indicator, LEFT(a.params_hash, 8)
        """

        with self.engine.connect() as conn:
            raw = pd.read_sql(text(sql_text), conn, params=params)

        if raw.empty:
            return pd.DataFrame()

        if "ts" in raw.columns:
            raw["ts"] = pd.to_datetime(raw["ts"], utc=True)

        # Build column name: {INDICATOR}_{ph}_ama
        raw["col_name"] = raw["indicator"] + "_" + raw["ph"] + "_ama"

        # Pivot: one row per (id, ts), one column per AMA variant
        pivoted = raw.pivot_table(
            index=["id", "ts"],
            columns="col_name",
            values="ama",
            aggfunc="first",
        ).reset_index()
        pivoted.columns.name = None

        return pivoted

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
        - Capture feature_snapshot at entry with close, rsi_14, atr_14

        Args:
            df: Features DataFrame with AMA columns merged in
            entries: Boolean Series indicating entry signals
            exits: Boolean Series indicating exit signals
            signal_id: Signal ID from dim_signals
            params: Signal parameters dict
            open_positions: DataFrame of existing open positions

        Returns:
            DataFrame with columns matching the target signal table schema
        """
        direction = params.get("direction", "long")
        params_hash = compute_params_hash(params)

        # Use a stable set of features for hashing
        feature_cols_for_hash = [
            c for c in ["close", "rsi_14", "atr_14"] if c in df.columns
        ]
        feature_hash = compute_feature_hash(df, feature_cols_for_hash)

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
                        "rsi_14": float(row["rsi_14"])
                        if "rsi_14" in row.index and pd.notna(row["rsi_14"])
                        else None,
                        "atr_14": float(row["atr_14"])
                        if "atr_14" in row.index and pd.notna(row["atr_14"])
                        else None,
                        "signal_subtype": self.signal_subtype,
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
        signal_table: str,
    ) -> None:
        """
        Write signal records to target signal table via temp-table upsert.

        Uses INSERT ... ON CONFLICT DO UPDATE for idempotent incremental runs.

        Args:
            records: DataFrame with signal records
            signal_table: Target table name (e.g., 'signals_ama_momentum')
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
        tmp = f"_tmp_{signal_table}"

        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
            conn.execute(
                text(
                    f"CREATE TEMP TABLE {tmp} "
                    f"(LIKE public.{signal_table} INCLUDING DEFAULTS) ON COMMIT DROP"
                )
            )
            records.to_sql(tmp, conn, if_exists="append", index=False, method="multi")
            set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in data_cols)
            conn.execute(
                text(
                    f"INSERT INTO public.{signal_table} ({', '.join(records.columns)}) "
                    f"SELECT {', '.join(records.columns)} FROM {tmp} "
                    f"ON CONFLICT ({', '.join(pk_cols)}) DO UPDATE SET {set_clause}"
                )
            )
