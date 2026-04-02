"""
DerivativesFeature - Crypto-native derivatives indicator computation.

Computes 8 derivatives-market indicators from Hyperliquid data and writes
them to public.features:
  1. oi_momentum (per-asset)
  2. oi_price_divergence (per-asset)
  3. funding_zscore (per-asset)
  4. funding_momentum (per-asset)
  5. vol_oi_regime (per-asset)
  6. force_index_deriv (per-asset)
  7. oi_concentration_ratio (cross-asset)
  8. liquidation_pressure (composite, requires 1+2+3)

Design:
  - Extends BaseFeature with template method pattern (same as TAFeature)
  - Uses HyperliquidAdapter for data loading (derivatives_input.py)
  - Per-asset groupby for indicators 1-6, full-frame for 7, composite for 8
  - Pre-flight check validates migration was applied before writing
  - Empty adapter data produces empty output without crash

Usage:
    from ta_lab2.scripts.features.derivatives_feature import DerivativesFeature, DerivativesConfig

    config = DerivativesConfig()
    feature = DerivativesFeature(engine, config)
    rows = feature.compute_for_ids(ids=[1, 1027], start='2024-01-01')

CLI:
    python -m ta_lab2.scripts.features.derivatives_feature --all
    python -m ta_lab2.scripts.features.derivatives_feature --ids 1 1027 --tf 1D

Note: ASCII-only comments throughout (Windows cp1252 compatibility).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.features.derivatives_input import HyperliquidAdapter
from ta_lab2.features.indicators_derivatives import (
    force_index_deriv,
    funding_momentum,
    funding_zscore,
    liquidation_pressure,
    oi_concentration_ratio,
    oi_momentum,
    oi_price_divergence,
    vol_oi_regime,
)
from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Derivatives column names (must match Alembic migration x7y8z9a0b1c2)
# ---------------------------------------------------------------------------

_DERIVATIVES_COLUMNS: list[str] = [
    "oi_mom_14",
    "oi_price_div_z",
    "funding_z_14",
    "funding_mom_14",
    "vol_oi_regime",
    "force_idx_deriv_13",
    "oi_conc_ratio",
    "liq_pressure",
]


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class DerivativesConfig(FeatureConfig):
    """
    Configuration for derivatives indicator computation.

    Attributes:
        feature_type:    Type of feature (default: 'derivatives').
        output_table:    Output table name (default: 'features').
        venue_id:        Venue filter -- 2 = HYPERLIQUID (default).
        add_zscore:      Disabled -- derivatives columns do not get zscore columns.
        null_strategy:   Skip NaN rows (derivatives NaN is informative warmup).
    """

    feature_type: str = "derivatives"
    output_table: str = "features"
    venue_id: int = 2  # HYPERLIQUID
    add_zscore: bool = False  # derivatives indicators do not get zscore columns
    null_strategy: str = "skip"


# =============================================================================
# DerivativesFeature
# =============================================================================


class DerivativesFeature(BaseFeature):
    """
    Compute derivatives-market indicators from Hyperliquid data.

    Template method flow (from BaseFeature.compute_for_ids):
      1. load_source_data  -> HyperliquidAdapter.load()
      2. compute_features  -> 8 indicator functions
      3. write_to_db       -> scoped DELETE + INSERT into public.features

    Subclasses BaseFeature; overrides load_source_data, compute_features,
    get_output_schema, get_feature_columns, add_normalizations, add_outlier_flags.
    """

    def __init__(
        self,
        engine: Engine,
        config: DerivativesConfig,
        adapter=None,
    ) -> None:
        """
        Initialize DerivativesFeature.

        Args:
            engine:  SQLAlchemy engine.
            config:  DerivativesConfig instance.
            adapter: Optional adapter override (e.g., MockAdapter for testing).
                     If None, HyperliquidAdapter(engine) is created automatically.
        """
        super().__init__(engine, config)
        self.config: DerivativesConfig = config
        self.adapter = adapter if adapter is not None else HyperliquidAdapter(engine)

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
        Load normalized derivatives data via the adapter.

        Args:
            ids:   CMC asset IDs to load.
            start: Optional start date (inclusive, ISO format).
            end:   Optional end date (inclusive, ISO format).

        Returns:
            DataFrame with DerivativesFrame schema [id, venue_id, ts, oi,
            funding_rate, volume, close, mark_px]. Empty if no data.
        """
        df = self.adapter.load(ids, start=start, end=end, tf=self.config.tf)
        if df.empty:
            logger.warning(
                "DerivativesFeature.load_source_data: adapter returned empty DataFrame "
                "for %d ids (start=%s, end=%s)",
                len(ids),
                start,
                end,
            )
        return df

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all 8 derivatives indicators.

        Step 1: Per-asset groupby for indicators 1-6.
        Step 2: Cross-asset OI concentration ratio (7) on full frame.
        Step 3: Composite liquidation_pressure (8) on full frame.

        Args:
            df_source: DerivativesFrame from load_source_data().

        Returns:
            DataFrame with 8 indicator columns added.
            Empty DataFrame if df_source is empty.
        """
        if df_source.empty:
            return pd.DataFrame()

        # ------------------------------------------------------------------
        # Step 1: Per-asset indicators (groupby id, venue_id).
        # ------------------------------------------------------------------
        asset_groups = []
        for (id_val, venue_id_val), df_g in df_source.groupby(
            ["id", "venue_id"], sort=False
        ):
            df_g = df_g.sort_values("ts").copy()

            try:
                oi_momentum(df_g, window=14, inplace=True)
            except Exception as exc:
                logger.warning("oi_momentum failed for id=%s: %s", id_val, exc)

            try:
                oi_price_divergence(df_g, window=20, inplace=True)
            except Exception as exc:
                logger.warning("oi_price_divergence failed for id=%s: %s", id_val, exc)

            try:
                funding_zscore(df_g, window=14, inplace=True)
            except Exception as exc:
                logger.warning("funding_zscore failed for id=%s: %s", id_val, exc)

            try:
                funding_momentum(df_g, window=14, inplace=True)
            except Exception as exc:
                logger.warning("funding_momentum failed for id=%s: %s", id_val, exc)

            try:
                vol_oi_regime(df_g, inplace=True)
            except Exception as exc:
                logger.warning("vol_oi_regime failed for id=%s: %s", id_val, exc)

            try:
                force_index_deriv(df_g, span=13, inplace=True)
            except Exception as exc:
                logger.warning("force_index_deriv failed for id=%s: %s", id_val, exc)

            asset_groups.append(df_g)

        if not asset_groups:
            return pd.DataFrame()

        df_full = pd.concat(asset_groups, ignore_index=True)

        # ------------------------------------------------------------------
        # Step 2: Cross-asset OI concentration ratio.
        # Requires full multi-asset frame sorted by ts.
        # ------------------------------------------------------------------
        df_full = df_full.sort_values(["ts", "id"]).reset_index(drop=True)
        try:
            oi_concentration_ratio(df_full, window=30, inplace=True)
        except Exception as exc:
            logger.warning("oi_concentration_ratio failed: %s", exc)
            df_full["oi_conc_ratio"] = float("nan")

        # ------------------------------------------------------------------
        # Step 3: Composite liquidation pressure.
        # Requires funding_z_14, oi_mom_14, oi_price_div_z (steps 1+2).
        # ------------------------------------------------------------------
        try:
            liquidation_pressure(df_full, inplace=True)
        except Exception as exc:
            logger.warning("liquidation_pressure failed: %s", exc)
            df_full["liq_pressure"] = float("nan")

        # ------------------------------------------------------------------
        # Add metadata columns required by features table PK.
        # ------------------------------------------------------------------
        df_full["tf"] = self.config.tf
        df_full["alignment_source"] = self.get_alignment_source()
        df_full["tf_days"] = self.get_tf_days()

        return df_full

    def get_output_schema(self) -> dict[str, str]:
        """
        Get output table schema.

        DerivativesFeature writes to the pre-existing public.features table
        (created by TAFeature / Phase 103 migrations). This method returns
        only the derivatives-specific columns for reference.
        """
        return {
            "id": "INTEGER NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "tf": "TEXT NOT NULL",
            "venue_id": "SMALLINT NOT NULL DEFAULT 1",
            "alignment_source": "TEXT NOT NULL",
            "tf_days": "INTEGER NOT NULL",
            # Derivatives indicators (added by migration x7y8z9a0b1c2)
            "oi_mom_14": "DOUBLE PRECISION",
            "oi_price_div_z": "DOUBLE PRECISION",
            "funding_z_14": "DOUBLE PRECISION",
            "funding_mom_14": "DOUBLE PRECISION",
            "vol_oi_regime": "INTEGER",
            "force_idx_deriv_13": "DOUBLE PRECISION",
            "oi_conc_ratio": "DOUBLE PRECISION",
            "liq_pressure": "DOUBLE PRECISION",
        }

    def get_feature_columns(self) -> list[str]:
        """Return list of derivatives indicator column names."""
        return list(_DERIVATIVES_COLUMNS)

    # =========================================================================
    # Override normalization / outlier (no zscore, no outlier flags)
    # =========================================================================

    def add_normalizations(self, df: pd.DataFrame) -> pd.DataFrame:
        """No-op: derivatives indicators do not get z-score columns."""
        return df

    def add_outlier_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """No-op: derivatives indicators do not get outlier flag columns."""
        return df

    # =========================================================================
    # Pre-flight check
    # =========================================================================

    def _preflight_check(self) -> None:
        """
        Verify that at least one derivatives column exists in the features table.

        Raises RuntimeError if migration x7y8z9a0b1c2 has not been applied.
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                      AND table_name = :table
                      AND column_name = ANY(:cols)
                """),
                {
                    "schema": self.config.output_schema,
                    "table": self.config.output_table,
                    "cols": _DERIVATIVES_COLUMNS,
                },
            )
            count = result.scalar() or 0

        if count == 0:
            raise RuntimeError(
                f"Derivatives columns not found in "
                f"{self.config.output_schema}.{self.config.output_table}. "
                "Run: alembic upgrade head  (migration x7y8z9a0b1c2 adds the 8 columns)"
            )
        logger.debug(
            "DerivativesFeature pre-flight: %d/%d derivatives columns present",
            count,
            len(_DERIVATIVES_COLUMNS),
        )

    # =========================================================================
    # Override _ensure_output_table to skip CREATE TABLE
    # =========================================================================

    def _ensure_output_table(self) -> None:
        """
        Skip CREATE TABLE -- public.features is managed by Alembic migrations.

        Only run the pre-flight migration check instead.
        """
        self._preflight_check()


# =============================================================================
# Helper: resolve all HL-mapped CMC ids
# =============================================================================


def _get_all_hl_mapped_ids(engine: Engine) -> list[int]:
    """
    Return all CMC ids that have Hyperliquid perp mappings.

    Uses the same dim_listings JOIN as HyperliquidAdapter._get_hl_to_cmc_id_map.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT DISTINCT dl.id
                FROM hyperliquid.hl_assets ha
                JOIN dim_listings dl
                    ON dl.ticker_on_venue = ha.symbol
                   AND dl.venue = 'HYPERLIQUID'
                WHERE ha.asset_type = 'perp'
                  AND ha.asset_id < 20000
                  AND dl.id IS NOT NULL
                ORDER BY dl.id
            """)
        ).fetchall()
    return [int(r[0]) for r in rows]


# =============================================================================
# CLI entry point
# =============================================================================


def _build_engine(db_url: str | None = None):
    """Create SQLAlchemy engine from URL or env."""
    import os

    from sqlalchemy import create_engine

    url = db_url or os.environ.get("TARGET_DB_URL", "postgresql://localhost/marketdata")
    return create_engine(url)


def main() -> None:
    """
    CLI entry point.

    Usage:
        python -m ta_lab2.scripts.features.derivatives_feature --all
        python -m ta_lab2.scripts.features.derivatives_feature --ids 1 1027 --tf 1D
        python -m ta_lab2.scripts.features.derivatives_feature --ids 1 --start 2024-01-01
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute and write derivatives indicators to public.features"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Compute for all HL-mapped CMC ids",
    )
    group.add_argument(
        "--ids",
        nargs="+",
        type=int,
        metavar="ID",
        help="CMC asset ids to compute",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe code (default: 1D)",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Start date ISO string (e.g. 2024-01-01)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date ISO string (e.g. 2024-12-31)",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=2,
        help="Venue id (default: 2 = HYPERLIQUID)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: TARGET_DB_URL env var or postgresql://localhost/marketdata)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine = _build_engine(args.db_url)

    config = DerivativesConfig(
        tf=args.tf,
        venue_id=args.venue_id,
    )
    feature = DerivativesFeature(engine, config)

    # Resolve ids.
    if args.all:
        ids = _get_all_hl_mapped_ids(engine)
        logger.info("DerivativesFeature: found %d HL-mapped CMC ids", len(ids))
    else:
        ids = args.ids

    if not ids:
        logger.warning("No ids to process. Exiting.")
        return

    logger.info(
        "DerivativesFeature: computing for %d ids, tf=%s, start=%s, end=%s",
        len(ids),
        args.tf,
        args.start,
        args.end,
    )

    rows = feature.compute_for_ids(ids, start=args.start, end=args.end)
    logger.info("DerivativesFeature: wrote %d rows to %s", rows, config.output_table)
    print(f"Done. {rows} rows written.")


if __name__ == "__main__":
    main()
