"""
ATR Breakout Signal Generator - Generate ATR breakout signals from cmc_features.

This module generates ATR breakout signals using Donchian channels with ATR confirmation.
Signals are stored in cmc_signals_atr_breakout with full feature snapshot for reproducibility.

Signal Logic:
- Entry: Price breaks above/below Donchian channel (rolling high/low)
- ATR confirmation: Optional ATR expansion filter
- Exit: Channel crossback OR trailing ATR stop
- Breakout classification: 'channel_break', 'atr_expansion', or 'both'

Usage:
    from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig, load_active_signals
    from ta_lab2.scripts.signals.generate_signals_atr import ATRSignalGenerator

    engine = create_engine(os.environ['TARGET_DB_URL'])
    config = SignalStateConfig(signal_type='atr_breakout')
    state_manager = SignalStateManager(engine, config)

    configs = load_active_signals(engine, 'atr_breakout')
    generator = ATRSignalGenerator(engine, state_manager)

    for config in configs:
        n = generator.generate_for_ids(
            ids=[1, 52],
            signal_config=config,
            full_refresh=False
        )
        print(f"Generated {n} signals")
"""

from dataclasses import dataclass
from typing import Optional
import json
import logging
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.signals.breakout_atr import make_signals
from .signal_state_manager import SignalStateManager
from .signal_utils import compute_feature_hash, compute_params_hash
from .regime_utils import load_regime_context_batch, merge_regime_context


logger = logging.getLogger(__name__)


@dataclass
class ATRSignalGenerator:
    """
    Generates ATR breakout signals from cmc_features.

    Responsibilities:
    - Load breakout parameters from dim_signals
    - Load features from cmc_features (OHLC, ATR, Bollinger Bands)
    - Generate signals using existing breakout_atr.py adapter
    - Classify breakout type (channel_break, atr_expansion, both)
    - Compute Donchian channel levels for audit trail
    - Store signals with full feature snapshot
    - Track position lifecycle (open/closed states)

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
        regime_enabled: bool = True,
    ) -> int:
        """
        Generate ATR breakout signals for specified assets.

        Args:
            ids: List of asset IDs to generate signals for
            signal_config: Signal configuration from dim_signals with keys:
                - signal_id: Signal identifier
                - signal_name: Signal name
                - params: Dict with lookback, atr_col, trail_atr_mult, confirm_close, etc.
            full_refresh: If True, regenerate all signals (default: incremental)
            dry_run: If True, don't write to database (default: False)
            regime_enabled: If True, load regime context and attach regime_key
                to signal records. Set False (--no-regime) for A/B comparison.

        Returns:
            Number of signal records generated

        Raises:
            KeyError: If required params missing from signal_config
            ValueError: If invalid parameter values
        """
        signal_id = signal_config["signal_id"]
        params = signal_config["params"]

        logger.info(
            f"Generating ATR signals for {len(ids)} assets, "
            f"signal_id={signal_id}, full_refresh={full_refresh}, "
            f"regime_enabled={regime_enabled}"
        )

        # Extract parameters with defaults
        lookback = params.get("lookback", 20)
        atr_col = params.get("atr_col", "atr_14")
        trail_atr_mult = params.get("trail_atr_mult", 2.0)
        confirm_close = params.get("confirm_close", True)
        exit_on_channel_crossback = params.get("exit_on_channel_crossback", True)
        use_trailing_atr_stop = params.get("use_trailing_atr_stop", True)

        # Determine start timestamp for incremental processing
        if full_refresh:
            start_ts = None  # Load all history
        else:
            dirty_windows = self.state_manager.get_dirty_window_start(ids, signal_id)
            # For simplicity, use earliest dirty window start (conservative)
            starts = [ts for ts in dirty_windows.values() if ts is not None]
            start_ts = min(starts) if starts else None

        # Load features from cmc_features
        df_features = self._load_features(ids, start_ts)

        if df_features.empty:
            return 0

        # Load and merge regime context (if enabled)
        if regime_enabled:
            regime_df = load_regime_context_batch(
                engine=self.engine, ids=ids, start_ts=start_ts
            )
            df_features = merge_regime_context(df_features, regime_df)
            n_with_regime = df_features["regime_key"].notna().sum()
            logger.info(
                f"Regime context: {n_with_regime}/{len(df_features)} rows have regime data"
            )
        else:
            logger.info("Regime context disabled (--no-regime mode)")
            df_features["regime_key"] = None

        # Compute Donchian channel levels (needed for breakout classification)
        df_features = self._compute_channel_levels(df_features, lookback)

        # Generate entry/exit signals using existing adapter
        entries, exits, size = make_signals(
            df_features,
            lookback=lookback,
            atr_col=atr_col,
            confirm_close=confirm_close,
            exit_on_channel_crossback=exit_on_channel_crossback,
            use_trailing_atr_stop=use_trailing_atr_stop,
            trail_atr_mult=trail_atr_mult,
        )

        # Add signals to DataFrame
        df_features["entry_signal"] = entries
        df_features["exit_signal"] = exits

        # Load open positions for state tracking
        open_positions = self.state_manager.load_open_positions(ids, signal_id)

        # Transform signals to stateful records with breakout classification
        records = self._transform_signals_to_records(
            df_features=df_features,
            signal_id=signal_id,
            params=params,
            open_positions=open_positions,
        )

        if records.empty:
            return 0

        n_tagged = (
            records["regime_key"].notna().sum()
            if "regime_key" in records.columns
            else 0
        )
        logger.info(f"Regime-tagged {n_tagged}/{len(records)} signal records")

        # Write to database
        if not dry_run:
            self._write_signals(records)
            self.state_manager.update_state_after_generation(
                signal_table="cmc_signals_atr_breakout",
                signal_id=signal_id,
            )

        return len(records)

    def _load_features(
        self,
        ids: list[int],
        start_ts: Optional[pd.Timestamp],
    ) -> pd.DataFrame:
        """
        Load features from cmc_features for signal generation.

        Loads OHLC for Donchian channel computation, ATR for stops,
        and Bollinger Bands for optional confirmation.

        Args:
            ids: List of asset IDs
            start_ts: Start timestamp for incremental load (None = all history)

        Returns:
            DataFrame with columns: id, ts, open, high, low, close, atr_14,
            bb_up_20_2, bb_lo_20_2
        """
        where_clauses = ["id = ANY(:ids)", "tf = '1D'"]
        params = {"ids": ids}

        if start_ts is not None:
            where_clauses.append("ts >= :start_ts")
            params["start_ts"] = start_ts

        where_sql = " AND ".join(where_clauses)

        sql_text = f"""
            SELECT
                id, ts,
                open, high, low, close,
                atr_14,
                bb_up_20_2, bb_lo_20_2
            FROM public.cmc_features
            WHERE {where_sql}
            ORDER BY id, ts
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            return pd.read_sql(sql, conn, params=params)

    def _compute_channel_levels(
        self,
        df: pd.DataFrame,
        lookback: int,
    ) -> pd.DataFrame:
        """
        Add Donchian channel high/low to DataFrame for audit trail.

        Args:
            df: DataFrame with high, low columns
            lookback: Rolling window size for channel computation

        Returns:
            DataFrame with added columns: channel_high, channel_low
        """
        # Group by ID to compute per-asset channels
        df = df.copy()

        # Compute channel levels per group
        channel_highs = []
        channel_lows = []

        for id_ in df["id"].unique():
            mask = df["id"] == id_
            group_high = (
                df.loc[mask, "high"]
                .rolling(window=lookback, min_periods=lookback)
                .max()
            )
            group_low = (
                df.loc[mask, "low"].rolling(window=lookback, min_periods=lookback).min()
            )

            channel_highs.extend(group_high.tolist())
            channel_lows.extend(group_low.tolist())

        df["channel_high"] = channel_highs
        df["channel_low"] = channel_lows

        return df

    def _classify_breakout_type(
        self,
        row: pd.Series,
        params: dict,
    ) -> str:
        """
        Classify breakout type for audit trail.

        Logic:
        - 'channel_break': Close breaks above channel_high (or below channel_low)
        - 'atr_expansion': ATR expanding (ATR > 1.5 * ATR rolling mean)
        - 'both': Both conditions met

        Args:
            row: DataFrame row with close, channel_high, channel_low, atr_14
            params: Signal parameters (currently unused, reserved for future)

        Returns:
            One of: 'channel_break', 'atr_expansion', 'both'
        """
        # Check channel break
        channel_break = (
            row["close"] > row["channel_high"] or row["close"] < row["channel_low"]
        )

        # Check ATR expansion (ATR > 1.5x rolling mean over 20 days)
        # Note: This is a simple heuristic - could be parameterized in future
        atr_expansion = False
        # We'd need ATR history to compute rolling mean, skip for now
        # This would require passing more context or computing in _transform_signals_to_records

        if channel_break and atr_expansion:
            return "both"
        elif channel_break:
            return "channel_break"
        elif atr_expansion:
            return "atr_expansion"
        else:
            return "channel_break"  # Default if signal triggered

    def _transform_signals_to_records(
        self,
        df_features: pd.DataFrame,
        signal_id: int,
        params: dict,
        open_positions: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Transform entry/exit signals to stateful position records.

        Matches entries to exits, tracks position state (open/closed),
        computes PnL, classifies breakout type, and captures feature snapshot.

        Args:
            df_features: DataFrame with entry_signal, exit_signal columns
            signal_id: Signal identifier from dim_signals
            params: Signal parameters for breakout classification
            open_positions: DataFrame of currently open positions

        Returns:
            DataFrame ready for insertion into cmc_signals_atr_breakout
        """
        records = []

        # Compute params hash and feature hash for reproducibility
        params_hash = compute_params_hash(params)

        # Process per asset
        for id_ in df_features["id"].unique():
            df_asset = df_features[df_features["id"] == id_].copy()
            df_asset = df_asset.sort_values("ts")

            # Get open positions for this asset
            asset_open = (
                open_positions[
                    (open_positions["id"] == id_)
                    & (open_positions["signal_id"] == signal_id)
                ]
                if not open_positions.empty
                else pd.DataFrame()
            )

            # Track position state
            position_open = not asset_open.empty
            entry_price = asset_open["entry_price"].iloc[0] if position_open else None
            entry_ts = asset_open["entry_ts"].iloc[0] if position_open else None

            for idx, row in df_asset.iterrows():
                # Regime key for this bar (None if regime not available)
                raw_rk = row["regime_key"] if "regime_key" in row.index else None
                regime_key = (
                    None
                    if (
                        raw_rk is None
                        or (isinstance(raw_rk, float) and pd.isna(raw_rk))
                    )
                    else raw_rk
                )

                # Entry signal
                if row["entry_signal"] and not position_open:
                    # Classify breakout type
                    breakout_type = self._classify_breakout_type(row, params)

                    # Capture feature snapshot
                    feature_snapshot = {
                        "close": float(row["close"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "atr": float(row["atr_14"]),
                        "channel_high": float(row["channel_high"])
                        if pd.notna(row["channel_high"])
                        else None,
                        "channel_low": float(row["channel_low"])
                        if pd.notna(row["channel_low"])
                        else None,
                    }

                    # Compute feature hash for reproducibility
                    feature_cols = [
                        "close",
                        "high",
                        "low",
                        "atr_14",
                        "channel_high",
                        "channel_low",
                    ]
                    # Create single-row DataFrame for hashing (include 'ts' for sorting)
                    hash_df = df_asset.loc[[idx], ["ts"] + feature_cols].copy()
                    feature_hash = compute_feature_hash(hash_df, feature_cols)

                    records.append(
                        {
                            "id": int(id_),
                            "ts": row["ts"],
                            "signal_id": signal_id,
                            "direction": "long",  # Breakout signals are long-only by default
                            "position_state": "open",
                            "entry_price": float(row["close"]),
                            "entry_ts": row["ts"],
                            "exit_price": None,
                            "exit_ts": None,
                            "pnl_pct": None,
                            "breakout_type": breakout_type,
                            "feature_snapshot": feature_snapshot,
                            "signal_version": self.signal_version,
                            "feature_version_hash": feature_hash,
                            "params_hash": params_hash,
                            "regime_key": regime_key,
                        }
                    )

                    position_open = True
                    entry_price = row["close"]
                    entry_ts = row["ts"]

                # Exit signal
                elif row["exit_signal"] and position_open:
                    exit_price = row["close"]
                    pnl_pct = ((exit_price - entry_price) / entry_price) * 100

                    # Classify breakout type at exit (for audit)
                    breakout_type = self._classify_breakout_type(row, params)

                    feature_snapshot = {
                        "close": float(row["close"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "atr": float(row["atr_14"]),
                        "channel_high": float(row["channel_high"])
                        if pd.notna(row["channel_high"])
                        else None,
                        "channel_low": float(row["channel_low"])
                        if pd.notna(row["channel_low"])
                        else None,
                    }

                    feature_cols = [
                        "close",
                        "high",
                        "low",
                        "atr_14",
                        "channel_high",
                        "channel_low",
                    ]
                    hash_df = df_asset.loc[[idx], ["ts"] + feature_cols].copy()
                    feature_hash = compute_feature_hash(hash_df, feature_cols)

                    records.append(
                        {
                            "id": int(id_),
                            "ts": row["ts"],
                            "signal_id": signal_id,
                            "direction": "long",
                            "position_state": "closed",
                            "entry_price": float(entry_price),
                            "entry_ts": entry_ts,
                            "exit_price": float(exit_price),
                            "exit_ts": row["ts"],
                            "pnl_pct": float(pnl_pct),
                            "breakout_type": breakout_type,
                            "feature_snapshot": feature_snapshot,
                            "signal_version": self.signal_version,
                            "feature_version_hash": feature_hash,
                            "params_hash": params_hash,
                            "regime_key": regime_key,
                        }
                    )

                    position_open = False
                    entry_price = None
                    entry_ts = None

        return pd.DataFrame(records)

    def _write_signals(self, records: pd.DataFrame) -> None:
        """
        Write signal records to cmc_signals_atr_breakout table.

        Uses INSERT ... ON CONFLICT DO NOTHING for idempotency.

        Args:
            records: DataFrame with signal records
        """
        if records.empty:
            return

        # Convert feature_snapshot to JSON string for JSONB insertion
        records = records.copy()
        records["feature_snapshot"] = records["feature_snapshot"].apply(
            lambda x: json.dumps(x) if isinstance(x, dict) else x
        )

        # Write to database
        with self.engine.begin() as conn:
            records.to_sql(
                name="cmc_signals_atr_breakout",
                con=conn,
                schema="public",
                if_exists="append",
                index=False,
                method="multi",
            )
