"""
Microstructure Feature Module - MICRO-01 through MICRO-04.

Computes per-bar microstructural features and writes them to features
using UPDATE (supplemental columns on existing rows):

  MICRO-01: Fractional Differentiation (close_fracdiff, close_fracdiff_d)
  MICRO-02: Liquidity Impact (kyle_lambda, amihud_lambda, hasbrouck_lambda)
  MICRO-03: Rolling ADF / SADF proxy (sadf_stat, sadf_is_explosive)
  MICRO-04: Entropy (entropy_shannon, entropy_lz)

Uses pure math from ta_lab2.features.microstructure -- no duplication.

Write strategy: UPDATE existing features rows (not DELETE+INSERT).
Microstructure columns are supplemental to the base feature table.

Usage:
    python -m ta_lab2.scripts.features.microstructure_feature --ids 1 --tf 1D
    python -m ta_lab2.scripts.features.microstructure_feature --all --tf 1D
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.features.microstructure import (
    amihud_lambda,
    find_min_d,
    frac_diff_ffd,
    hasbrouck_lambda,
    kyle_lambda,
    rolling_adf,
    rolling_entropy,
)
from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class MicrostructureConfig(FeatureConfig):
    """
    Configuration for microstructure feature computation.

    Attributes:
        feature_type: 'microstructure'
        output_table: 'features' (writes to existing features rows)
        null_strategy: 'forward_fill' (forward fill price/volume gaps)
        add_zscore: False (no z-score normalization for microstructure)
        ffd_threshold: Weight cutoff for FFD filter (default 1e-2)
        liquidity_window: Rolling window for lambda calculations (default 20)
        adf_window: Rolling window for ADF test (default 63, ~1 quarter)
        entropy_window: Rolling window for entropy (default 50)
        entropy_bins: Quantile bins for entropy encoding (default 10)
    """

    feature_type: str = "microstructure"
    output_table: str = "features"
    null_strategy: str = "forward_fill"
    add_zscore: bool = False

    # MICRO-01: Fractional differentiation
    ffd_threshold: float = 1e-2

    # MICRO-02: Liquidity
    liquidity_window: int = 20

    # MICRO-03: Rolling ADF
    adf_window: int = 63

    # MICRO-04: Entropy
    entropy_window: int = 50
    entropy_bins: int = 10


# =============================================================================
# Feature columns
# =============================================================================

MICROSTRUCTURE_COLUMNS = [
    "close_fracdiff",
    "close_fracdiff_d",
    "kyle_lambda",
    "amihud_lambda",
    "hasbrouck_lambda",
    "sadf_stat",
    "sadf_is_explosive",
    "entropy_shannon",
    "entropy_lz",
]


# =============================================================================
# Microstructure Feature Class
# =============================================================================


class MicrostructureFeature(BaseFeature):
    """
    Compute microstructural features from OHLCV bars.

    Uses existing microstructure.py functions for all calculations:
    - find_min_d / frac_diff_ffd: Fractional differentiation (MICRO-01)
    - kyle_lambda / amihud_lambda / hasbrouck_lambda: Liquidity (MICRO-02)
    - rolling_adf: Structural breaks / SADF proxy (MICRO-03)
    - rolling_entropy: Shannon + LZ entropy (MICRO-04)

    Write strategy: UPDATE existing features rows (supplemental columns).

    Template method flow:
    1. Load OHLCV data from price_bars_multi_tf_u
    2. Apply forward_fill null handling
    3. Compute all microstructure features
    4. No normalization / no outlier flags (overridden to no-op)
    5. UPDATE features rows with computed values
    """

    SOURCE_TABLE = "public.price_bars_multi_tf_u"
    TS_COLUMN = "time_close"

    def __init__(self, engine: Engine, config: Optional[MicrostructureConfig] = None):
        """
        Initialize microstructure feature module.

        Args:
            engine: SQLAlchemy engine
            config: Microstructure configuration (defaults to MicrostructureConfig())
        """
        if config is None:
            config = MicrostructureConfig()
        super().__init__(engine, config)
        self.micro_config = config  # Type-safe reference

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
        Load OHLCV data from price_bars_multi_tf_u.

        Args:
            ids: List of asset IDs
            start: Optional start date (inclusive, ISO format)
            end: Optional end date (inclusive, ISO format)

        Returns:
            DataFrame with columns: id, ts, open, high, low, close, volume,
            tf, alignment_source, venue, venue_rank
            Sorted by id ASC, ts ASC
        """
        where_clauses = [
            "p.id = ANY(:ids)",
            "p.tf = :tf",
            "p.alignment_source = :as_",
        ]
        params: dict = {
            "ids": ids,
            "tf": self.config.tf,
            "as_": self.get_alignment_source(),
        }

        if self.config.venue_id is not None:
            where_clauses.append("p.venue_id = :venue_id")
            params["venue_id"] = self.config.venue_id

        if start:
            where_clauses.append(f"p.{self.TS_COLUMN} >= :start")
            params["start"] = start

        if end:
            where_clauses.append(f"p.{self.TS_COLUMN} <= :end")
            params["end"] = end

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                p.id,
                p.{self.TS_COLUMN} as ts,
                p.venue_id,
                p.venue,
                p.venue_rank,
                p.open,
                p.high,
                p.low,
                p.close,
                p.volume
            FROM {self.SOURCE_TABLE} p
            WHERE {where_sql}
            ORDER BY p.id ASC, ts ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)

        return df

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all microstructure features from OHLCV data.

        Processes each (id, venue) group separately:
        1. MICRO-01: FFD - find_min_d + frac_diff_ffd on log(close)
        2. MICRO-02: Kyle/Amihud/Hasbrouck lambdas
        3. MICRO-03: Rolling ADF on log(close) -> sadf_stat, sadf_is_explosive
        4. MICRO-04: Shannon + LZ entropy on log returns

        Args:
            df_source: Source OHLCV data (with nulls handled)

        Returns:
            DataFrame with computed microstructure columns + id, ts, tf,
            alignment_source, venue
        """
        if df_source.empty:
            return pd.DataFrame()

        df = df_source.copy()
        results = []

        for (id_val, venue_id_val), df_id in df.groupby(["id", "venue_id"]):
            df_id = df_id.copy()
            df_id = df_id.sort_values("ts")

            close = df_id["close"].values.astype(np.float64)
            volume = df_id["volume"].values.astype(np.float64)
            n = len(close)

            # Guard: need minimum data for any computation
            if n < 30:
                logger.warning(
                    f"Skipping id={id_val}, venue_id={venue_id_val}: only {n} bars (<30)"
                )
                continue

            log_close = np.log(np.maximum(close, 1e-12))

            # -----------------------------------------------------------------
            # MICRO-01: Fractional Differentiation
            # -----------------------------------------------------------------
            try:
                d_opt = find_min_d(close)
                ffd_series = frac_diff_ffd(
                    log_close,
                    d=d_opt,
                    threshold=self.micro_config.ffd_threshold,
                )
            except Exception as exc:
                logger.warning(f"FFD failed for id={id_val}: {exc}")
                d_opt = np.nan
                ffd_series = np.full(n, np.nan)

            df_id["close_fracdiff"] = ffd_series
            df_id["close_fracdiff_d"] = d_opt

            # -----------------------------------------------------------------
            # MICRO-02: Liquidity Impact Measures
            # -----------------------------------------------------------------
            window = self.micro_config.liquidity_window
            try:
                df_id["kyle_lambda"] = kyle_lambda(close, volume, window=window)
            except Exception as exc:
                logger.warning(f"kyle_lambda failed for id={id_val}: {exc}")
                df_id["kyle_lambda"] = np.nan

            try:
                df_id["amihud_lambda"] = amihud_lambda(close, volume, window=window)
            except Exception as exc:
                logger.warning(f"amihud_lambda failed for id={id_val}: {exc}")
                df_id["amihud_lambda"] = np.nan

            try:
                df_id["hasbrouck_lambda"] = hasbrouck_lambda(
                    close, volume, window=window
                )
            except Exception as exc:
                logger.warning(f"hasbrouck_lambda failed for id={id_val}: {exc}")
                df_id["hasbrouck_lambda"] = np.nan

            # -----------------------------------------------------------------
            # MICRO-03: Rolling ADF / SADF Proxy
            # -----------------------------------------------------------------
            try:
                adf_vals = rolling_adf(log_close, window=self.micro_config.adf_window)
                df_id["sadf_stat"] = adf_vals
                df_id["sadf_is_explosive"] = adf_vals > 1.5
            except Exception as exc:
                logger.warning(f"rolling_adf failed for id={id_val}: {exc}")
                df_id["sadf_stat"] = np.nan
                df_id["sadf_is_explosive"] = False

            # -----------------------------------------------------------------
            # MICRO-04: Entropy Features
            # -----------------------------------------------------------------
            # Compute log returns for entropy (entropy must use returns, not levels)
            log_returns = np.empty(n, dtype=np.float64)
            log_returns[0] = np.nan
            log_returns[1:] = log_close[1:] - log_close[:-1]

            try:
                shannon_vals, lz_vals = rolling_entropy(
                    log_returns,
                    window=self.micro_config.entropy_window,
                    n_bins=self.micro_config.entropy_bins,
                )
                df_id["entropy_shannon"] = shannon_vals
                df_id["entropy_lz"] = lz_vals
            except Exception as exc:
                logger.warning(f"rolling_entropy failed for id={id_val}: {exc}")
                df_id["entropy_shannon"] = np.nan
                df_id["entropy_lz"] = np.nan

            results.append(df_id)

        if not results:
            return pd.DataFrame()

        df_features = pd.concat(results, ignore_index=True)

        # Add tf, alignment_source columns
        df_features["tf"] = self.config.tf
        df_features["alignment_source"] = self.get_alignment_source()

        return df_features

    def get_output_schema(self) -> dict[str, str]:
        """
        Get output table schema definition.

        Not used for table creation (features already exists).
        Provided for BaseFeature contract compliance.
        """
        return {
            "id": "INTEGER NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "tf": "TEXT NOT NULL",
            "venue_id": "SMALLINT NOT NULL DEFAULT 1",
            "venue": "TEXT NOT NULL DEFAULT 'CMC_AGG'",
            "alignment_source": "TEXT NOT NULL DEFAULT 'multi_tf'",
            "close_fracdiff": "DOUBLE PRECISION",
            "close_fracdiff_d": "DOUBLE PRECISION",
            "kyle_lambda": "DOUBLE PRECISION",
            "amihud_lambda": "DOUBLE PRECISION",
            "hasbrouck_lambda": "DOUBLE PRECISION",
            "sadf_stat": "DOUBLE PRECISION",
            "sadf_is_explosive": "BOOLEAN DEFAULT FALSE",
            "entropy_shannon": "DOUBLE PRECISION",
            "entropy_lz": "DOUBLE PRECISION",
        }

    def get_feature_columns(self) -> list[str]:
        """
        Get list of computed microstructure feature columns.

        Returns:
            List of 9 column names (MICRO-01 through MICRO-04)
        """
        return list(MICROSTRUCTURE_COLUMNS)

    # =========================================================================
    # Overrides: No normalization / no outlier flags
    # =========================================================================

    def add_normalizations(self, df: pd.DataFrame) -> pd.DataFrame:
        """No-op: microstructure features are not z-score normalized."""
        return df

    def add_outlier_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """No-op: microstructure features do not have outlier flags."""
        return df

    # =========================================================================
    # Override: UPDATE instead of DELETE+INSERT
    # =========================================================================

    def write_to_db(self, df: pd.DataFrame) -> int:
        """
        Write microstructure features to features via UPDATE.

        Uses batch UPDATE to set only microstructure columns on existing rows.
        Rows that do not exist in features are skipped (microstructure
        features are supplemental -- they require a base row from the
        daily_features_view refresh).

        Args:
            df: DataFrame with computed features (must have id, ts, tf,
                venue_id, alignment_source + microstructure columns)

        Returns:
            Number of rows updated
        """
        if df.empty:
            return 0

        # Build UPDATE SQL with parameterized placeholders
        set_clauses = ", ".join(f"{col} = :{col}" for col in MICROSTRUCTURE_COLUMNS)
        update_sql = text(f"""
            UPDATE public.features
            SET {set_clauses},
                updated_at = now()
            WHERE id = :id
              AND ts = :ts
              AND tf = :tf
              AND venue_id = :venue_id
              AND alignment_source = :alignment_source
        """)

        # Prepare rows as list of dicts for executemany
        pk_cols = ["id", "ts", "tf", "venue_id", "alignment_source"]
        required_cols = pk_cols + list(MICROSTRUCTURE_COLUMNS)

        # Filter to only required columns
        df_write = df[required_cols].copy()

        rows = df_write.to_dict("records")

        total_updated = 0
        batch_size = 5000

        t0 = time.time()

        with self.engine.begin() as conn:
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                for row in batch:
                    # Convert numpy types to Python natives for psycopg2;
                    # NaN/NaT -> None (SQL NULL)
                    clean_row = {}
                    for k, v in row.items():
                        if v is None:
                            clean_row[k] = None
                        elif isinstance(v, float) and np.isnan(v):
                            clean_row[k] = None
                        elif hasattr(v, "item"):
                            val = v.item()
                            # numpy scalar .item() can return float nan
                            if isinstance(val, float) and np.isnan(val):
                                clean_row[k] = None
                            else:
                                clean_row[k] = val
                        elif isinstance(v, pd.Timestamp):
                            clean_row[k] = v.to_pydatetime()
                        elif isinstance(v, pd.NaT.__class__):
                            clean_row[k] = None
                        else:
                            clean_row[k] = v
                    result = conn.execute(update_sql, clean_row)
                    total_updated += result.rowcount

                logger.info(
                    f"  Batch {i // batch_size + 1}: "
                    f"processed {min(i + batch_size, len(rows))}/{len(rows)} rows"
                )

        elapsed = time.time() - t0
        logger.info(
            f"Updated {total_updated}/{len(rows)} rows in features in {elapsed:.1f}s"
        )

        return total_updated

    def __repr__(self) -> str:
        return (
            f"MicrostructureFeature("
            f"output_table={self.config.output_schema}.{self.config.output_table}, "
            f"liquidity_window={self.micro_config.liquidity_window}, "
            f"adf_window={self.micro_config.adf_window}, "
            f"entropy_window={self.micro_config.entropy_window})"
        )


# =============================================================================
# CLI
# =============================================================================


def _get_all_ids(engine: Engine) -> list[int]:
    """Get all asset IDs that have rows in features."""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT DISTINCT id FROM public.features ORDER BY id")
        )
        return [row[0] for row in result]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Compute microstructure features (MICRO-01 through MICRO-04) "
            "and write to features via UPDATE. "
            "Features: FFD, Kyle/Amihud/Hasbrouck lambdas, rolling ADF, "
            "Shannon/LZ entropy."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compute microstructure features for BTC (id=1)
  python -m ta_lab2.scripts.features.microstructure_feature --ids 1 --tf 1D

  # Compute for all assets
  python -m ta_lab2.scripts.features.microstructure_feature --all --tf 1D

  # Different timeframe
  python -m ta_lab2.scripts.features.microstructure_feature --ids 1,52 --tf 7D

Feature columns written:
  MICRO-01: close_fracdiff, close_fracdiff_d
  MICRO-02: kyle_lambda, amihud_lambda, hasbrouck_lambda
  MICRO-03: sadf_stat, sadf_is_explosive
  MICRO-04: entropy_shannon, entropy_lz
""",
    )

    # Asset selection
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        help="Comma-separated asset IDs (e.g., 1,52,1027)",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        dest="all_ids",
        help="Process all assets in features",
    )

    # Timeframe
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe (default: 1D)",
    )

    # Alignment source
    parser.add_argument(
        "--alignment-source",
        default="multi_tf",
        help="Alignment source (default: multi_tf)",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not TARGET_DB_URL:
        logger.error("TARGET_DB_URL not set")
        return 1

    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    try:
        # Resolve IDs
        if args.all_ids:
            ids = _get_all_ids(engine)
            logger.info(f"Processing all {len(ids)} assets")
        else:
            ids = [int(x.strip()) for x in args.ids.split(",")]
            logger.info(f"Processing IDs: {ids}")

        if not ids:
            logger.warning("No asset IDs found")
            return 0

        # Create config and feature instance
        config = MicrostructureConfig(
            tf=args.tf,
            alignment_source=args.alignment_source,
        )
        feature = MicrostructureFeature(engine, config)
        logger.info(f"Initialized: {feature}")

        t0 = time.time()
        rows_updated = feature.compute_for_ids(ids)
        elapsed = time.time() - t0

        print(
            f"\nMicrostructure feature refresh complete: "
            f"{rows_updated} rows updated in features "
            f"(tf={args.tf}, ids={len(ids)} assets, {elapsed:.1f}s)"
        )
        return 0

    except Exception as exc:
        logger.error(f"Microstructure feature refresh failed: {exc}", exc_info=True)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
