"""
RSI Signal Generator - Generate RSI mean reversion signals from features.

This module provides RSI mean reversion signal generation following the existing
rsi_mean_revert.py adapter logic. Signals are stored in signals_rsi_mean_revert
with position lifecycle tracking and RSI value analytics.

Key features:
- Database-driven thresholds from dim_signals params
- RSI values tracked at entry and exit for analysis
- Adaptive threshold support via rolling percentiles
- Full feature snapshot and version hashing for reproducibility

Usage:
    from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig
    from ta_lab2.scripts.signals.generate_signals_rsi import RSISignalGenerator

    config = SignalStateConfig(signal_type='rsi_mean_revert')
    state_manager = SignalStateManager(engine, config)

    generator = RSISignalGenerator(engine, state_manager)
    count = generator.generate_for_ids(
        ids=[1, 52],
        signal_config={'signal_id': 4, 'params': {'lower': 30, 'upper': 70}},
        full_refresh=False,
        use_adaptive=False
    )
"""

from dataclasses import dataclass
from typing import Optional
import json
import logging
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.signals.signal_state_manager import SignalStateManager
from ta_lab2.scripts.signals.signal_utils import (
    compute_feature_hash,
    compute_params_hash,
)
from ta_lab2.scripts.signals.regime_utils import (
    load_regime_context_batch,
    merge_regime_context,
)
from ta_lab2.signals.rsi_mean_revert import make_signals
from ta_lab2.labeling.cusum_filter import cusum_filter, get_cusum_threshold


logger = logging.getLogger(__name__)


# =============================================================================
# Adaptive Threshold Utilities
# =============================================================================


def compute_adaptive_thresholds(
    df: pd.DataFrame,
    rsi_col: str,
    lookback: int = 100,
    lower_pct: float = 20.0,  # 20th percentile
    upper_pct: float = 80.0,  # 80th percentile
) -> tuple[pd.Series, pd.Series]:
    """
    Compute rolling percentile-based adaptive RSI thresholds.

    Uses rolling quantiles instead of static thresholds from dim_signals.
    This enables per-asset calibration and volatility regime adaptation.

    Args:
        df: DataFrame with RSI values
        rsi_col: Column name containing RSI values
        lookback: Rolling window size in periods (default: 100)
        lower_pct: Lower percentile threshold (default: 20.0 = 20th percentile)
        upper_pct: Upper percentile threshold (default: 80.0 = 80th percentile)

    Returns:
        Tuple of (lower_threshold_series, upper_threshold_series) aligned to df.index

    Examples:
        >>> df = pd.DataFrame({'rsi_14': [30, 40, 50, 60, 70, 30, 40]})
        >>> lower, upper = compute_adaptive_thresholds(df, 'rsi_14', lookback=5)
        >>> # First 5 rows will have NaN (insufficient data)
        >>> # Rows 5+ will have rolling percentile thresholds
    """
    if rsi_col not in df.columns:
        raise KeyError(f"Column '{rsi_col}' not found in DataFrame")

    rsi = df[rsi_col].astype(float)

    # Compute rolling percentiles
    lower = rsi.rolling(window=lookback, min_periods=1).quantile(lower_pct / 100.0)
    upper = rsi.rolling(window=lookback, min_periods=1).quantile(upper_pct / 100.0)

    return lower, upper


# =============================================================================
# Signal Generator Class
# =============================================================================


@dataclass
class RSISignalGenerator:
    """
    Generates RSI mean reversion signals from features.

    Leverages existing rsi_mean_revert.py adapter logic with database-driven
    threshold configuration from dim_signals. Stores signals in
    signals_rsi_mean_revert with full position lifecycle tracking.

    Attributes:
        engine: SQLAlchemy engine for database operations
        state_manager: SignalStateManager for position state tracking
        signal_version: Signal code version for reproducibility (default: "1.0")
    """

    engine: Engine
    state_manager: SignalStateManager
    signal_version: str = "1.0"
    venue_id: int | None = None

    def _apply_cusum_filter(
        self,
        features_df: pd.DataFrame,
        multiplier: float,
    ) -> pd.DataFrame:
        """
        Apply per-asset symmetric CUSUM pre-filter to features DataFrame.

        For each asset, computes an EWM-vol-calibrated threshold and retains
        only the rows at CUSUM event timestamps.

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
                    f"CUSUM threshold <= 0 for id={asset_id}, skipping filter"
                )
                filtered_parts.append(group)
                continue

            cusum_events = cusum_filter(close, threshold)

            if len(cusum_events) == 0:
                logger.warning(
                    f"CUSUM returned 0 events for id={asset_id} "
                    f"(threshold={threshold:.6f}), retaining all bars"
                )
                filtered_parts.append(group)
                continue

            event_set = set(pd.to_datetime(cusum_events, utc=True).tolist())
            ts_utc = pd.to_datetime(group["ts"], utc=True)
            mask = ts_utc.isin(event_set)
            filtered_group = group[mask]

            n_retained = len(filtered_group)
            n_total = len(group)
            reduction_pct = (1 - n_retained / n_total) * 100 if n_total > 0 else 0
            logger.info(
                f"CUSUM id={asset_id}: {n_retained}/{n_total} bars retained "
                f"({reduction_pct:.1f}% reduction, threshold={threshold:.6f})"
            )

            filtered_parts.append(filtered_group)

        if not filtered_parts:
            return pd.DataFrame(columns=features_df.columns)

        result = pd.concat(filtered_parts, ignore_index=True)
        n_after = len(result)
        total_reduction = (1 - n_after / n_before) * 100 if n_before > 0 else 0
        logger.info(
            f"CUSUM total: {n_after}/{n_before} rows retained "
            f"({total_reduction:.1f}% reduction, multiplier={multiplier})"
        )
        return result

    def load_features(
        self,
        ids: list[int],
        start_ts: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """
        Load feature data from features.

        Args:
            ids: List of asset IDs to load
            start_ts: Optional start timestamp for incremental refresh
                     If None, loads all available history

        Returns:
            DataFrame with columns: id, ts, close, rsi_14, rsi_7, rsi_21, atr_14
            Sorted by (id, ts) for chronological processing
        """
        where_clauses = ["id = ANY(:ids)", "tf = '1D'"]
        params = {"ids": ids}

        if self.venue_id is not None:
            where_clauses.append("venue_id = :venue_id")
            params["venue_id"] = self.venue_id

        if start_ts is not None:
            where_clauses.append("ts >= :start_ts")
            params["start_ts"] = start_ts

        where_sql = " AND ".join(where_clauses)

        sql_text = f"""
            SELECT
                id, venue_id, ts, close,
                rsi_14, rsi_7, rsi_21,
                atr_14
            FROM public.features
            WHERE {where_sql}
            ORDER BY id, ts
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)

        # Ensure timestamp is timezone-aware
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)

        return df

    def transform_signals_to_records(
        self,
        entries: pd.Series,
        exits: pd.Series,
        df_features: pd.DataFrame,
        signal_id: int,
        params: dict,
        feature_hash: str,
        params_hash: str,
        rsi_col: str = "rsi_14",
    ) -> pd.DataFrame:
        """
        Transform entry/exit signals to stateful position records.

        Pairs entry and exit signals into position lifecycle records with
        RSI value tracking at entry and exit.

        Args:
            entries: Boolean series indicating entry signals
            exits: Boolean series indicating exit signals
            df_features: DataFrame with feature data (close, RSI, ATR)
            signal_id: Signal ID from dim_signals
            params: Signal parameters from dim_signals
            feature_hash: Hash of feature data used
            params_hash: Hash of signal parameters
            rsi_col: RSI column to track (default: "rsi_14")

        Returns:
            DataFrame with columns matching signals_rsi_mean_revert schema
            Each row represents either an open or closed position
        """
        records = []

        # Group by asset ID and venue_id for stateful processing
        for (id_, venue_id), group in df_features.groupby(["id", "venue_id"]):
            group = group.sort_values("ts").reset_index(drop=True)

            # Get entry/exit signals for this asset
            entry_mask = entries.loc[group.index].values
            exit_mask = exits.loc[group.index].values

            # Track position state
            position_open = False

            for idx in range(len(group)):
                # Entry signal - open new position
                if entry_mask[idx] and not position_open:
                    direction = "long"  # RSI mean reversion typically trades longs

                    # Check if short signal (RSI was overbought)
                    if params.get("allow_shorts", False):
                        rsi_val = group.loc[idx, rsi_col]
                        if rsi_val >= params.get("upper", 70.0):
                            direction = "short"

                    # Create entry record
                    feature_snapshot = {
                        "close": float(group.loc[idx, "close"]),
                        rsi_col: float(group.loc[idx, rsi_col]),
                        "atr_14": float(group.loc[idx, "atr_14"])
                        if "atr_14" in group.columns
                        else None,
                    }

                    records.append(
                        {
                            "id": int(id_),
                            "venue_id": int(venue_id),
                            "ts": group.loc[idx, "ts"],
                            "signal_id": signal_id,
                            "direction": direction,
                            "position_state": "open",
                            "entry_price": float(group.loc[idx, "close"]),
                            "entry_ts": group.loc[idx, "ts"],
                            "exit_price": None,
                            "exit_ts": None,
                            "pnl_pct": None,
                            "rsi_at_entry": float(group.loc[idx, rsi_col]),
                            "rsi_at_exit": None,
                            "feature_snapshot": feature_snapshot,
                            "signal_version": self.signal_version,
                            "feature_version_hash": feature_hash,
                            "params_hash": params_hash,
                        }
                    )

                    position_open = True

                # Exit signal - close position
                elif exit_mask[idx] and position_open:
                    entry_record = records[-1]  # Last record is the entry

                    # Compute PnL
                    entry_price = entry_record["entry_price"]
                    exit_price = float(group.loc[idx, "close"])

                    if entry_record["direction"] == "long":
                        pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
                    else:  # short
                        pnl_pct = ((entry_price - exit_price) / entry_price) * 100.0

                    # Update entry record to closed
                    entry_record["position_state"] = "closed"
                    entry_record["exit_price"] = exit_price
                    entry_record["exit_ts"] = group.loc[idx, "ts"]
                    entry_record["pnl_pct"] = pnl_pct
                    entry_record["rsi_at_exit"] = float(group.loc[idx, rsi_col])

                    position_open = False

        if not records:
            # Return empty DataFrame with correct schema
            return pd.DataFrame(
                columns=[
                    "id",
                    "venue_id",
                    "ts",
                    "signal_id",
                    "direction",
                    "position_state",
                    "entry_price",
                    "entry_ts",
                    "exit_price",
                    "exit_ts",
                    "pnl_pct",
                    "rsi_at_entry",
                    "rsi_at_exit",
                    "feature_snapshot",
                    "signal_version",
                    "feature_version_hash",
                    "params_hash",
                ]
            )

        return pd.DataFrame(records)

    def generate_for_ids(
        self,
        ids: list[int],
        signal_config: dict,
        full_refresh: bool = False,
        dry_run: bool = False,
        # Adaptive RSI evaluated in Phase 55 A/B comparison; static retained as default.
        # IC-IR: static wins 14/14 horizon/asset combos (mean |IC-IR| 0.51 vs 0.29).
        # Walk-forward Sharpe: adaptive wins 4/5 folds but misses IC criterion.
        # Both conditions required per policy; inconclusive -> status quo retained.
        # See reports/evaluation/adaptive_rsi_ab_comparison.md
        use_adaptive: bool = False,
        regime_enabled: bool = True,
        cusum_enabled: bool = False,
        cusum_threshold_multiplier: float = 2.0,
    ) -> int:
        """
        Generate RSI mean reversion signals for specified asset IDs.

        Args:
            ids: List of asset IDs to generate signals for
            signal_config: Configuration from dim_signals with keys:
                          - signal_id: Signal identifier
                          - signal_name: Signal name
                          - params: Signal parameters (lower, upper, rsi_col, etc.)
            full_refresh: If True, regenerate all signals from scratch
                         If False, use incremental refresh based on state
            dry_run: If True, don't write to database (validation mode)
            use_adaptive: If True, use adaptive rolling percentile thresholds
                         instead of static thresholds from dim_signals
            regime_enabled: If True, load regime context and attach regime_key
                to signal records. Set False (--no-regime) for A/B comparison.
            cusum_enabled: If True, apply symmetric CUSUM pre-filter before signal
                generation. Only event timestamps are passed to the signal logic.
                Default False preserves backward-compatible behavior.
            cusum_threshold_multiplier: EWM-vol multiplier for CUSUM threshold.
                Default 2.0. Higher = fewer events.

        Returns:
            Number of signal records generated

        Raises:
            ValueError: If required parameters missing
            KeyError: If required features not in features
        """
        signal_id = signal_config["signal_id"]
        params = signal_config["params"]

        logger.info(
            f"Generating RSI signals for {len(ids)} assets, "
            f"signal_id={signal_id}, full_refresh={full_refresh}, "
            f"use_adaptive={use_adaptive}, regime_enabled={regime_enabled}"
        )

        # Determine start timestamp for incremental refresh
        if full_refresh:
            start_ts = None
        else:
            dirty_windows = self.state_manager.get_dirty_window_start(ids, signal_id)
            # Use earliest dirty window across all IDs
            start_timestamps = [ts for ts in dirty_windows.values() if ts is not None]
            start_ts = min(start_timestamps) if start_timestamps else None

        # Load features
        df_features = self.load_features(ids, start_ts)

        if df_features.empty:
            logger.warning(f"No features found for ids={ids}, start_ts={start_ts}")
            return 0

        logger.info(f"Loaded {len(df_features)} feature rows")

        # Apply CUSUM pre-filter (if enabled)
        if cusum_enabled:
            df_features = self._apply_cusum_filter(
                df_features, cusum_threshold_multiplier
            )
            if df_features.empty:
                logger.warning("CUSUM filter removed all rows - skipping")
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

        # Extract parameters
        rsi_col = params.get("rsi_col", "rsi_14")
        lower = params.get("lower", 30.0)
        upper = params.get("upper", 70.0)
        confirm_cross = params.get("confirm_cross", True)
        allow_shorts = params.get("allow_shorts", False)

        # Override with adaptive thresholds if requested
        if use_adaptive:
            logger.info("Using adaptive rolling percentile thresholds")

            # Group by ID and compute adaptive thresholds per asset
            df_features_adaptive = df_features.copy()

            for id_, group in df_features.groupby("id"):
                group = group.sort_values("ts")

                # Compute adaptive thresholds for this asset
                adaptive_lower, adaptive_upper = compute_adaptive_thresholds(
                    group,
                    rsi_col=rsi_col,
                    lookback=params.get("adaptive_lookback", 100),
                    lower_pct=params.get("adaptive_lower_pct", 20.0),
                    upper_pct=params.get("adaptive_upper_pct", 80.0),
                )

                # Store adaptive thresholds in DataFrame for signal generation
                idx = group.index
                df_features_adaptive.loc[idx, "adaptive_lower"] = adaptive_lower.values
                df_features_adaptive.loc[idx, "adaptive_upper"] = adaptive_upper.values

            # Note: make_signals doesn't support dynamic thresholds per row
            # For now, we use average adaptive thresholds as static override
            # Future enhancement: modify make_signals to accept threshold series
            logger.warning(
                "Adaptive thresholds computed but using global average. "
                "Full per-row adaptive logic requires make_signals enhancement."
            )
            lower = df_features_adaptive["adaptive_lower"].mean()
            upper = df_features_adaptive["adaptive_upper"].mean()

        # Generate signals using existing adapter
        entries, exits, size = make_signals(
            df=df_features,
            rsi_col=rsi_col,
            lower=lower,
            upper=upper,
            confirm_cross=confirm_cross,
            allow_shorts=allow_shorts,
            atr_col="atr_14",
            risk_pct=params.get("risk_pct", 0.5),
            atr_mult_stop=params.get("atr_mult_stop", 1.5),
            price_col="close",
            max_leverage=params.get("max_leverage", 1.0),
        )

        logger.info(
            f"Generated {entries.sum()} entry signals, {exits.sum()} exit signals"
        )

        # Compute feature hash for reproducibility
        feature_cols = ["close", rsi_col, "atr_14"]
        feature_hash = compute_feature_hash(df_features, feature_cols)

        # Compute params hash
        params_hash = compute_params_hash(params)

        # Transform to stateful records
        df_records = self.transform_signals_to_records(
            entries=entries,
            exits=exits,
            df_features=df_features,
            signal_id=signal_id,
            params=params,
            feature_hash=feature_hash,
            params_hash=params_hash,
            rsi_col=rsi_col,
        )

        if df_records.empty:
            logger.warning("No signals generated after transformation")
            return 0

        logger.info(f"Transformed to {len(df_records)} signal records")

        # Attach regime_key from features (join on id + entry_ts)
        # Use entry_ts: the regime at signal entry determines the regime_key for the record
        if "regime_key" in df_features.columns:
            regime_lookup = df_features[["id", "ts", "regime_key"]].copy()
            regime_lookup.columns = ["id", "entry_ts", "regime_key"]
            # Ensure compatible types for merge
            df_records["entry_ts"] = pd.to_datetime(df_records["entry_ts"], utc=True)
            regime_lookup["entry_ts"] = pd.to_datetime(
                regime_lookup["entry_ts"], utc=True
            )
            df_records = df_records.merge(
                regime_lookup, on=["id", "entry_ts"], how="left"
            )
            n_tagged = df_records["regime_key"].notna().sum()
            logger.info(f"Regime-tagged {n_tagged}/{len(df_records)} signal records")
        else:
            df_records["regime_key"] = None

        # Write to database (unless dry run)
        if not dry_run:
            signal_table = "signals_rsi_mean_revert"

            # Convert JSONB column to JSON strings for database insertion
            # Fix: serialize dict values to JSON string (pre-existing bug: no-op lambda)
            df_records["feature_snapshot"] = df_records["feature_snapshot"].apply(
                lambda x: json.dumps(x) if isinstance(x, dict) else x
            )

            pk_cols = ["id", "venue_id", "ts", "signal_id"]
            df_records = df_records.drop_duplicates(subset=pk_cols, keep="last")
            data_cols = [
                c for c in df_records.columns if c not in pk_cols and c != "created_at"
            ]
            tmp = f"_tmp_{signal_table}"

            with self.engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
                conn.execute(
                    text(
                        f"CREATE TEMP TABLE {tmp} (LIKE public.{signal_table} INCLUDING DEFAULTS) ON COMMIT DROP"
                    )
                )
                df_records.to_sql(
                    tmp, conn, if_exists="append", index=False, method="multi"
                )
                set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in data_cols)
                conn.execute(
                    text(
                        f"INSERT INTO public.{signal_table} ({', '.join(df_records.columns)}) "
                        f"SELECT {', '.join(df_records.columns)} FROM {tmp} "
                        f"ON CONFLICT ({', '.join(pk_cols)}) DO UPDATE SET {set_clause}"
                    )
                )

            logger.info(f"Inserted {len(df_records)} records into {signal_table}")

            # Update state table
            rows_updated = self.state_manager.update_state_after_generation(
                signal_table=signal_table,
                signal_id=signal_id,
            )
            logger.info(f"Updated {rows_updated} state rows")
        else:
            logger.info("DRY RUN: Would insert {} records".format(len(df_records)))

        return len(df_records)
