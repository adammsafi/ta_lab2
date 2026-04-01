"""
TAFeature - Technical indicators feature computation.

Computes RSI, MACD, Stochastic, Bollinger Bands, ATR, ADX with configurable
parameter sets loaded from dim_indicators metadata table.

Extended in Phase 103 to support 20 additional indicator types via
indicators_extended.py: ichimoku, willr, keltner, cci, elder_ray,
force_index, vwap, cmf, chaikin_osc, hurst, vidya, frama, aroon, trix,
ultimate_osc, vortex, emv, mass_index, kst, coppock.

Design:
- Extends BaseFeature with template method pattern
- Reuses indicators.py functions with inplace=True for efficiency
- Parameter sets dynamically loaded from dim_indicators (database-driven)
- Handles missing volume gracefully (skips volume-based indicators)

Usage:
    from ta_lab2.scripts.features.ta_feature import TAFeature, TAConfig

    config = TAConfig()
    feature = TAFeature(engine, config)
    rows = feature.compute_for_ids(ids=[1, 52], start="2023-01-01")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import json

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig
from ta_lab2.features import indicators_extended as indx
from ta_lab2.features.indicators import (
    rsi,
    macd,
    stoch_kd,
    bollinger,
    atr,
    adx,
)


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class TAConfig(FeatureConfig):
    """
    Configuration for technical indicators computation.

    Attributes:
        feature_type: Type of feature (default: "ta")
        output_table: Output table name (default: "ta_daily")
        null_strategy: Null handling strategy (default: "interpolate")
        add_zscore: Whether to add z-score normalization (default: True)
        load_indicators_from_db: Load parameter sets from dim_indicators (default: True)
    """

    feature_type: str = "ta"
    output_table: str = "ta"
    null_strategy: str = "interpolate"  # Per CONTEXT.md - indicators interpolate
    add_zscore: bool = True
    load_indicators_from_db: bool = True


# =============================================================================
# TAFeature Class
# =============================================================================


class TAFeature(BaseFeature):
    """
    Compute daily technical indicators.

    Uses existing indicators.py functions:
    - rsi(): RSI with configurable period
    - macd(): MACD with fast/slow/signal
    - stoch_kd(): Stochastic %K/%D
    - bollinger(): Bollinger Bands
    - atr(): Average True Range
    - adx(): ADX

    Parameter sets loaded from dim_indicators table for database-driven configuration.
    """

    def __init__(self, engine: Engine, config: TAConfig):
        """
        Initialize TAFeature.

        Args:
            engine: SQLAlchemy engine
            config: TA configuration
        """
        super().__init__(engine, config)
        self.config: TAConfig = config  # Type hint for IDE support
        self._indicator_params: Optional[list[dict]] = None

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def load_source_data(
        self,
        ids: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load OHLCV data from price_bars_multi_tf for configured tf.

        Args:
            ids: List of asset IDs
            start: Optional start date (inclusive, ISO format)
            end: Optional end date (inclusive, ISO format)

        Returns:
            DataFrame with columns: id, ts, open, high, low, close, volume
            Sorted by id, ts ASC
        """
        where_clauses = [
            "id = ANY(:ids)",
            "tf = :tf",
            "alignment_source = :as_",
        ]
        params = {
            "ids": ids,
            "tf": self.config.tf,
            "as_": self.config.alignment_source,
        }

        if self.config.venue_id is not None:
            where_clauses.append("venue_id = :venue_id")
            params["venue_id"] = self.config.venue_id

        if start:
            where_clauses.append(f"{self.TS_COLUMN} >= :start")
            params["start"] = start

        if end:
            where_clauses.append(f"{self.TS_COLUMN} <= :end")
            params["end"] = end

        where_sql = " AND ".join(where_clauses)

        sql_text = f"""
            SELECT
                id,
                {self.TS_COLUMN} AS ts,
                venue_id,
                open,
                high,
                low,
                close,
                volume
            FROM {self.SOURCE_TABLE}
            WHERE {where_sql}
            ORDER BY id, venue_id, ts ASC
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)

        return df

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all active technical indicators.

        For each ID:
        1. Apply null handling (interpolate per config)
        2. For each active indicator in dim_indicators:
           - Parse params from JSONB
           - Call corresponding indicators.py function
           - Add columns to result

        Args:
            df_source: Source data with OHLCV (null handling already applied)

        Returns:
            DataFrame with computed indicator columns
        """
        if df_source.empty:
            return pd.DataFrame()

        # Load active indicator parameters
        indicator_params = self.load_indicator_params()

        # Process each (id, venue_id) separately
        results = []

        for (id_val, venue_id_val), df_id in df_source.groupby(["id", "venue_id"]):
            df_id = df_id.copy()

            # Compute each active indicator
            for ind in indicator_params:
                ind_type = ind["indicator_type"]
                ind_name = ind["indicator_name"]
                params = ind["params"]

                try:
                    if ind_type == "rsi":
                        self._compute_rsi(df_id, params)
                    elif ind_type == "macd":
                        self._compute_macd(df_id, params)
                    elif ind_type == "stoch":
                        self._compute_stoch(df_id, params)
                    elif ind_type == "bb":
                        self._compute_bollinger(df_id, params)
                    elif ind_type == "atr":
                        self._compute_atr(df_id, params)
                    elif ind_type == "adx":
                        self._compute_adx(df_id, params)
                    # --- Phase 103 extended indicators ---
                    elif ind_type == "ichimoku":
                        self._compute_ichimoku(df_id, params)
                    elif ind_type == "willr":
                        self._compute_willr(df_id, params)
                    elif ind_type == "keltner":
                        self._compute_keltner(df_id, params)
                    elif ind_type == "cci":
                        self._compute_cci(df_id, params)
                    elif ind_type == "elder_ray":
                        self._compute_elder_ray(df_id, params)
                    elif ind_type == "force_index":
                        self._compute_force_index(df_id, params)
                    elif ind_type == "vwap":
                        self._compute_vwap(df_id, params)
                    elif ind_type == "cmf":
                        self._compute_cmf(df_id, params)
                    elif ind_type == "chaikin_osc":
                        self._compute_chaikin_osc(df_id, params)
                    elif ind_type == "hurst":
                        self._compute_hurst(df_id, params)
                    elif ind_type == "vidya":
                        self._compute_vidya(df_id, params)
                    elif ind_type == "frama":
                        self._compute_frama(df_id, params)
                    elif ind_type == "aroon":
                        self._compute_aroon(df_id, params)
                    elif ind_type == "trix":
                        self._compute_trix(df_id, params)
                    elif ind_type == "ultimate_osc":
                        self._compute_ultimate_osc(df_id, params)
                    elif ind_type == "vortex":
                        self._compute_vortex(df_id, params)
                    elif ind_type == "emv":
                        self._compute_emv(df_id, params)
                    elif ind_type == "mass_index":
                        self._compute_mass_index(df_id, params)
                    elif ind_type == "kst":
                        self._compute_kst(df_id, params)
                    elif ind_type == "coppock":
                        self._compute_coppock(df_id, params)
                except Exception as e:
                    # Log error but continue with other indicators
                    print(f"Warning: Failed to compute {ind_name} for id={id_val}: {e}")
                    continue

            results.append(df_id)

        if not results:
            return pd.DataFrame()

        # Combine all IDs
        df_result = pd.concat(results, ignore_index=True)

        # Add tf, alignment_source, and tf_days columns
        df_result["tf"] = self.config.tf
        df_result["alignment_source"] = self.get_alignment_source()
        df_result["tf_days"] = self.get_tf_days()

        # Select output columns
        output_cols = [
            "id",
            "ts",
            "tf",
            "tf_days",
            "venue_id",
            "close",
        ] + [
            col
            for col in df_result.columns
            if col
            not in [
                "id",
                "ts",
                "tf",
                "tf_days",
                "venue_id",
                "close",
                "open",
                "high",
                "low",
                "volume",
            ]
        ]

        return df_result[output_cols]

    def get_output_schema(self) -> dict[str, str]:
        """
        Get output table schema definition.

        Returns:
            Dictionary mapping column names to SQL types
        """
        # Base schema (static columns)
        schema = {
            "id": "INTEGER NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "tf": "TEXT NOT NULL",
            "venue_id": "SMALLINT NOT NULL DEFAULT 1",
            "alignment_source": "TEXT NOT NULL",
            "tf_days": "INTEGER NOT NULL",
            "close": "DOUBLE PRECISION",
        }

        # Add columns for all possible indicators
        # (Dynamic based on dim_indicators in production, static for table creation)
        schema.update(
            {
                # RSI variations
                "rsi_7": "DOUBLE PRECISION",
                "rsi_14": "DOUBLE PRECISION",
                "rsi_21": "DOUBLE PRECISION",
                # MACD variations
                "macd_12_26": "DOUBLE PRECISION",
                "macd_signal_9": "DOUBLE PRECISION",
                "macd_hist_12_26_9": "DOUBLE PRECISION",
                "macd_8_17": "DOUBLE PRECISION",
                "macd_signal_9_fast": "DOUBLE PRECISION",
                "macd_hist_8_17_9": "DOUBLE PRECISION",
                # Stochastic
                "stoch_k_14": "DOUBLE PRECISION",
                "stoch_d_3": "DOUBLE PRECISION",
                # Bollinger Bands
                "bb_ma_20": "DOUBLE PRECISION",
                "bb_up_20_2": "DOUBLE PRECISION",
                "bb_lo_20_2": "DOUBLE PRECISION",
                "bb_width_20": "DOUBLE PRECISION",
                # ATR and ADX
                "atr_14": "DOUBLE PRECISION",
                "adx_14": "DOUBLE PRECISION",
                # Normalized versions
                "rsi_14_zscore": "DOUBLE PRECISION",
                # Data quality
                "is_outlier": "BOOLEAN DEFAULT FALSE",
                # Metadata
                "updated_at": "TIMESTAMPTZ DEFAULT now()",
                # --- Phase 103 extended indicators ---
                # Ichimoku Cloud
                "ichimoku_tenkan": "DOUBLE PRECISION",
                "ichimoku_kijun": "DOUBLE PRECISION",
                "ichimoku_span_a": "DOUBLE PRECISION",
                "ichimoku_span_b": "DOUBLE PRECISION",
                "ichimoku_chikou": "DOUBLE PRECISION",
                # Williams %R
                "willr_14": "DOUBLE PRECISION",
                # Keltner Channels
                "kc_mid_20": "DOUBLE PRECISION",
                "kc_upper_20": "DOUBLE PRECISION",
                "kc_lower_20": "DOUBLE PRECISION",
                "kc_width_20": "DOUBLE PRECISION",
                # CCI
                "cci_20": "DOUBLE PRECISION",
                # Elder Ray
                "elder_bull_13": "DOUBLE PRECISION",
                "elder_bear_13": "DOUBLE PRECISION",
                # Force Index
                "fi_1": "DOUBLE PRECISION",
                "fi_13": "DOUBLE PRECISION",
                # VWAP
                "vwap_14": "DOUBLE PRECISION",
                "vwap_dev_14": "DOUBLE PRECISION",
                # Chaikin Money Flow
                "cmf_20": "DOUBLE PRECISION",
                # Chaikin Oscillator
                "chaikin_osc": "DOUBLE PRECISION",
                # Hurst Exponent
                "hurst_100": "DOUBLE PRECISION",
                # VIDYA
                "vidya_9": "DOUBLE PRECISION",
                # FRAMA
                "frama_16": "DOUBLE PRECISION",
                # Aroon
                "aroon_up_25": "DOUBLE PRECISION",
                "aroon_dn_25": "DOUBLE PRECISION",
                "aroon_osc_25": "DOUBLE PRECISION",
                # TRIX
                "trix_15": "DOUBLE PRECISION",
                "trix_signal_9": "DOUBLE PRECISION",
                # Ultimate Oscillator
                "uo_7_14_28": "DOUBLE PRECISION",
                # Vortex
                "vi_plus_14": "DOUBLE PRECISION",
                "vi_minus_14": "DOUBLE PRECISION",
                # EMV
                "emv_1": "DOUBLE PRECISION",
                "emv_14": "DOUBLE PRECISION",
                # Mass Index
                "mass_idx_25": "DOUBLE PRECISION",
                # KST
                "kst": "DOUBLE PRECISION",
                "kst_signal": "DOUBLE PRECISION",
                # Coppock Curve
                "coppock": "DOUBLE PRECISION",
            }
        )

        return schema

    def get_feature_columns(self) -> list[str]:
        """
        Get list of computed feature columns.

        Returns:
            List of feature column names (excluding id, ts, metadata columns)
        """
        # Get active indicators from database
        indicator_params = self.load_indicator_params()

        feature_cols = []

        for ind in indicator_params:
            ind_type = ind["indicator_type"]
            params = ind["params"]

            if ind_type == "rsi":
                period = params.get("period", 14)
                feature_cols.append(f"rsi_{period}")
            elif ind_type == "macd":
                fast = params.get("fast", 12)
                slow = params.get("slow", 26)
                signal = params.get("signal", 9)
                feature_cols.extend(
                    [
                        f"macd_{fast}_{slow}",
                        f"macd_signal_{signal}",
                        f"macd_hist_{fast}_{slow}_{signal}",
                    ]
                )
            elif ind_type == "stoch":
                k = params.get("k", 14)
                d = params.get("d", 3)
                feature_cols.extend([f"stoch_k_{k}", f"stoch_d_{d}"])
            elif ind_type == "bb":
                window = params.get("window", 20)
                n_sigma = params.get("n_sigma", 2.0)
                # Convert float to string without decimal if it's a whole number
                sigma_str = (
                    str(int(n_sigma)) if n_sigma == int(n_sigma) else str(n_sigma)
                )
                feature_cols.extend(
                    [
                        f"bb_ma_{window}",
                        f"bb_up_{window}_{sigma_str}",
                        f"bb_lo_{window}_{sigma_str}",
                        f"bb_width_{window}",
                    ]
                )
            elif ind_type == "atr":
                period = params.get("period", 14)
                feature_cols.append(f"atr_{period}")
            elif ind_type == "adx":
                period = params.get("period", 14)
                feature_cols.append(f"adx_{period}")
            # --- Phase 103 extended indicators ---
            elif ind_type == "ichimoku":
                feature_cols.extend(
                    [
                        "ichimoku_tenkan",
                        "ichimoku_kijun",
                        "ichimoku_span_a",
                        "ichimoku_span_b",
                        "ichimoku_chikou",
                    ]
                )
            elif ind_type == "willr":
                window = params.get("window", 14)
                feature_cols.append(f"willr_{window}")
            elif ind_type == "keltner":
                ema_period = params.get("ema_period", 20)
                feature_cols.extend(
                    [
                        f"kc_mid_{ema_period}",
                        f"kc_upper_{ema_period}",
                        f"kc_lower_{ema_period}",
                        f"kc_width_{ema_period}",
                    ]
                )
            elif ind_type == "cci":
                window = params.get("window", 20)
                feature_cols.append(f"cci_{window}")
            elif ind_type == "elder_ray":
                period = params.get("period", 13)
                feature_cols.extend([f"elder_bull_{period}", f"elder_bear_{period}"])
            elif ind_type == "force_index":
                smooth = params.get("smooth", 13)
                feature_cols.extend(["fi_1", f"fi_{smooth}"])
            elif ind_type == "vwap":
                window = params.get("window", 14)
                feature_cols.extend([f"vwap_{window}", f"vwap_dev_{window}"])
            elif ind_type == "cmf":
                window = params.get("window", 20)
                feature_cols.append(f"cmf_{window}")
            elif ind_type == "chaikin_osc":
                feature_cols.append("chaikin_osc")
            elif ind_type == "hurst":
                window = params.get("window", 100)
                feature_cols.append(f"hurst_{window}")
            elif ind_type == "vidya":
                vidya_period = params.get("vidya_period", 9)
                feature_cols.append(f"vidya_{vidya_period}")
            elif ind_type == "frama":
                period = params.get("period", 16)
                feature_cols.append(f"frama_{period}")
            elif ind_type == "aroon":
                window = params.get("window", 25)
                feature_cols.extend(
                    [f"aroon_up_{window}", f"aroon_dn_{window}", f"aroon_osc_{window}"]
                )
            elif ind_type == "trix":
                period = params.get("period", 15)
                signal_period = params.get("signal_period", 9)
                feature_cols.extend([f"trix_{period}", f"trix_signal_{signal_period}"])
            elif ind_type == "ultimate_osc":
                p1 = params.get("p1", 7)
                p2 = params.get("p2", 14)
                p3 = params.get("p3", 28)
                feature_cols.append(f"uo_{p1}_{p2}_{p3}")
            elif ind_type == "vortex":
                window = params.get("window", 14)
                feature_cols.extend([f"vi_plus_{window}", f"vi_minus_{window}"])
            elif ind_type == "emv":
                window = params.get("window", 14)
                feature_cols.extend(["emv_1", f"emv_{window}"])
            elif ind_type == "mass_index":
                sum_period = params.get("sum_period", 25)
                feature_cols.append(f"mass_idx_{sum_period}")
            elif ind_type == "kst":
                feature_cols.extend(["kst", "kst_signal"])
            elif ind_type == "coppock":
                feature_cols.append("coppock")

        return feature_cols

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def load_indicator_params(self) -> list[dict]:
        """
        Load active indicator parameters from dim_indicators.

        Returns:
            List of dicts with indicator_type, indicator_name, params

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On database errors
        """
        if not self.config.load_indicators_from_db:
            # Return default indicators if not loading from DB
            return self._get_default_indicators()

        # Cache indicator params to avoid repeated DB queries
        if self._indicator_params is not None:
            return self._indicator_params

        sql = text(
            """
            SELECT
                indicator_type,
                indicator_name,
                params
            FROM public.dim_indicators
            WHERE is_active = TRUE
            ORDER BY indicator_id
        """
        )

        with self.engine.connect() as conn:
            result = conn.execute(sql)
            rows = result.fetchall()

        indicators = []
        for row in rows:
            indicators.append(
                {
                    "indicator_type": row[0],
                    "indicator_name": row[1],
                    "params": json.loads(row[2]) if isinstance(row[2], str) else row[2],
                }
            )

        self._indicator_params = indicators
        return indicators

    def _get_default_indicators(self) -> list[dict]:
        """Get default indicator parameters when not loading from DB."""
        return [
            {
                "indicator_type": "rsi",
                "indicator_name": "rsi_14",
                "params": {"period": 14},
            },
            {
                "indicator_type": "rsi",
                "indicator_name": "rsi_21",
                "params": {"period": 21},
            },
            {
                "indicator_type": "rsi",
                "indicator_name": "rsi_7",
                "params": {"period": 7},
            },
            {
                "indicator_type": "macd",
                "indicator_name": "macd_12_26_9",
                "params": {"fast": 12, "slow": 26, "signal": 9},
            },
            {
                "indicator_type": "macd",
                "indicator_name": "macd_8_17_9",
                "params": {"fast": 8, "slow": 17, "signal": 9},
            },
            {
                "indicator_type": "stoch",
                "indicator_name": "stoch_14_3",
                "params": {"k": 14, "d": 3},
            },
            {
                "indicator_type": "bb",
                "indicator_name": "bb_20_2",
                "params": {"window": 20, "n_sigma": 2.0},
            },
            {
                "indicator_type": "atr",
                "indicator_name": "atr_14",
                "params": {"period": 14},
            },
            {
                "indicator_type": "adx",
                "indicator_name": "adx_14",
                "params": {"period": 14},
            },
        ]

    # =========================================================================
    # Override normalization/outlier to match DDL
    # =========================================================================

    def add_normalizations(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Override: only add rsi_14_zscore (matches DDL).

        The DDL only defines rsi_14_zscore — not zscore for every indicator.
        """
        if not self.config.add_zscore:
            return df

        from ta_lab2.features.feature_utils import add_zscore as add_zscore_util

        if "rsi_14" in df.columns:
            group_cols = ["id", "venue_id"] if "venue_id" in df.columns else ["id"]
            for _, df_asset in df.groupby(group_cols):
                idx = df_asset.index
                add_zscore_util(
                    df_asset,
                    "rsi_14",
                    window=self.config.zscore_window,
                    out_col="rsi_14_zscore",
                )
                df.loc[idx, "rsi_14_zscore"] = df_asset["rsi_14_zscore"]

        return df

    def add_outlier_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Override: single is_outlier column (matches DDL).

        Flag if any indicator value is extreme (4-sigma on RSI).
        """
        from ta_lab2.features.feature_utils import flag_outliers

        df["is_outlier"] = False
        if "rsi_14" in df.columns:
            df["is_outlier"] = df["is_outlier"] | flag_outliers(
                df["rsi_14"], n_sigma=4.0, method="zscore"
            )
        return df

    def _compute_rsi(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute RSI indicator.

        Args:
            df: DataFrame with close column
            params: RSI parameters (period)

        Returns:
            DataFrame with RSI column added (inplace)
        """
        period = params.get("period", 14)
        out_col = f"rsi_{period}"
        rsi(df, period=period, out_col=out_col, inplace=True)
        return df

    def _compute_macd(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute MACD indicator.

        Args:
            df: DataFrame with close column
            params: MACD parameters (fast, slow, signal)

        Returns:
            DataFrame with MACD columns added (inplace)
        """
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal = params.get("signal", 9)

        # MACD returns separate columns, need custom out_cols
        out_cols = (
            f"macd_{fast}_{slow}",
            f"macd_signal_{signal}",
            f"macd_hist_{fast}_{slow}_{signal}",
        )
        macd(df, fast=fast, slow=slow, signal=signal, out_cols=out_cols, inplace=True)
        return df

    def _compute_stoch(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute Stochastic indicator.

        Args:
            df: DataFrame with high, low, close columns
            params: Stochastic parameters (k, d)

        Returns:
            DataFrame with Stoch K/D columns added (inplace)
        """
        k = params.get("k", 14)
        d = params.get("d", 3)

        out_cols = (f"stoch_k_{k}", f"stoch_d_{d}")
        stoch_kd(df, k=k, d=d, out_cols=out_cols, inplace=True)
        return df

    def _compute_bollinger(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute Bollinger Bands indicator.

        Args:
            df: DataFrame with close column
            params: Bollinger parameters (window, n_sigma)

        Returns:
            DataFrame with BB columns added (inplace)
        """
        window = params.get("window", 20)
        n_sigma = params.get("n_sigma", 2.0)

        # Convert float to string without decimal if it's a whole number
        sigma_str = str(int(n_sigma)) if n_sigma == int(n_sigma) else str(n_sigma)

        out_cols = (
            f"bb_ma_{window}",
            f"bb_up_{window}_{sigma_str}",
            f"bb_lo_{window}_{sigma_str}",
            f"bb_width_{window}",
        )
        bollinger(df, window=window, n_sigma=n_sigma, out_cols=out_cols, inplace=True)
        return df

    def _compute_atr(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute ATR indicator.

        Args:
            df: DataFrame with high, low, close columns
            params: ATR parameters (period)

        Returns:
            DataFrame with ATR column added (inplace)
        """
        period = params.get("period", 14)
        atr(df, period=period, inplace=True)
        return df

    def _compute_adx(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute ADX indicator.

        Args:
            df: DataFrame with high, low, close columns
            params: ADX parameters (period)

        Returns:
            DataFrame with ADX column added (inplace)
        """
        period = params.get("period", 14)
        adx(df, period=period, inplace=True)
        return df

    # =========================================================================
    # Phase 103 Extended Indicator Helpers
    # =========================================================================

    def _compute_ichimoku(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Ichimoku Cloud (5 output columns)."""
        tenkan = params.get("tenkan", 9)
        kijun = params.get("kijun", 26)
        senkou_b = params.get("senkou_b", 52)
        indx.ichimoku(df, tenkan=tenkan, kijun=kijun, senkou_b=senkou_b, inplace=True)
        return df

    def _compute_willr(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Williams %R."""
        window = params.get("window", 14)
        indx.williams_r(df, window, inplace=True)
        return df

    def _compute_keltner(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Keltner Channels (4 output columns)."""
        ema_period = params.get("ema_period", 20)
        atr_period = params.get("atr_period", 10)
        multiplier = params.get("multiplier", 2.0)
        indx.keltner(
            df,
            ema_period=ema_period,
            atr_period=atr_period,
            multiplier=multiplier,
            inplace=True,
        )
        return df

    def _compute_cci(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Commodity Channel Index."""
        window = params.get("window", 20)
        indx.cci(df, window, inplace=True)
        return df

    def _compute_elder_ray(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Elder Ray Index (2 output columns)."""
        period = params.get("period", 13)
        indx.elder_ray(df, period=period, inplace=True)
        return df

    def _compute_force_index(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Force Index (2 output columns: fi_1 and fi_smooth)."""
        smooth = params.get("smooth", 13)
        indx.force_index(df, smooth=smooth, inplace=True)
        return df

    def _compute_vwap(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute rolling VWAP (2 output columns: vwap_N and vwap_dev_N)."""
        window = params.get("window", 14)
        indx.vwap(df, window, inplace=True)
        return df

    def _compute_cmf(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Chaikin Money Flow."""
        window = params.get("window", 20)
        indx.cmf(df, window, inplace=True)
        return df

    def _compute_chaikin_osc(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Chaikin Oscillator."""
        fast = params.get("fast", 3)
        slow = params.get("slow", 10)
        # Use fixed output column name to match schema
        indx.chaikin_osc(df, fast=fast, slow=slow, out_col="chaikin_osc", inplace=True)
        return df

    def _compute_hurst(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Hurst Exponent."""
        window = params.get("window", 100)
        max_lag = params.get("max_lag", 20)
        indx.hurst(df, window, max_lag=max_lag, inplace=True)
        return df

    def _compute_vidya(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Variable Index Dynamic Average (VIDYA)."""
        cmo_period = params.get("cmo_period", 9)
        vidya_period = params.get("vidya_period", 9)
        indx.vidya(df, cmo_period=cmo_period, vidya_period=vidya_period, inplace=True)
        return df

    def _compute_frama(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Fractal Adaptive Moving Average (FRAMA)."""
        period = params.get("period", 16)
        indx.frama(df, period=period, inplace=True)
        return df

    def _compute_aroon(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Aroon Indicator (3 output columns: up, dn, osc)."""
        window = params.get("window", 25)
        indx.aroon(df, window, inplace=True)
        return df

    def _compute_trix(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute TRIX oscillator (2 output columns: trix and trix_signal)."""
        period = params.get("period", 15)
        signal_period = params.get("signal_period", 9)
        indx.trix(df, period=period, signal_period=signal_period, inplace=True)
        return df

    def _compute_ultimate_osc(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Ultimate Oscillator."""
        p1 = params.get("p1", 7)
        p2 = params.get("p2", 14)
        p3 = params.get("p3", 28)
        indx.ultimate_osc(df, p1=p1, p2=p2, p3=p3, inplace=True)
        return df

    def _compute_vortex(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Vortex Indicator (2 output columns: vi_plus, vi_minus)."""
        window = params.get("window", 14)
        indx.vortex(df, window, inplace=True)
        return df

    def _compute_emv(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Ease of Movement (2 output columns: emv_1 and emv_smooth)."""
        window = params.get("window", 14)
        indx.emv(df, window, inplace=True)
        return df

    def _compute_mass_index(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Mass Index."""
        ema_period = params.get("ema_period", 9)
        sum_period = params.get("sum_period", 25)
        indx.mass_index(df, ema_period=ema_period, sum_period=sum_period, inplace=True)
        return df

    def _compute_kst(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Know Sure Thing (KST) oscillator (2 output columns: kst, kst_signal)."""
        indx.kst(df, inplace=True)
        return df

    def _compute_coppock(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Compute Coppock Curve. Output column name fixed to 'coppock'."""
        roc_long = params.get("roc_long", 14)
        roc_short = params.get("roc_short", 11)
        wma_period = params.get("wma_period", 10)
        indx.coppock(
            df,
            roc_long=roc_long,
            roc_short=roc_short,
            wma_period=wma_period,
            out_col="coppock",
            inplace=True,
        )
        return df
