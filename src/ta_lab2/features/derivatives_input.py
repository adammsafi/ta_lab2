"""
Venue-agnostic normalized input layer for derivatives indicators.

Provides two adapter classes:
  - HyperliquidAdapter: Loads OI, funding rate, volume, price, and mark_px
    from Hyperliquid tables (hyperliquid schema), keyed on CMC id.
  - MockAdapter: Returns empty DataFrame for testing / graceful degradation.

The unified output schema (DerivativesFrame) is:
  [id, venue_id, ts, oi, funding_rate, volume, close, mark_px]

All timestamps are UTC. ts is daily (DATE_TRUNC to day).

HL-to-CMC ID resolution:
  JOIN hyperliquid.hl_assets (asset_type='perp', asset_id < 20000)
  with dim_listings (venue='HYPERLIQUID') on symbol match.
  Only assets with a confirmed CMC id (dim_listings.id) are included.
  This mirrors the approach in scripts/etl/seed_hl_assets.py.

OI priority:
  hl_candles.close_oi is primary.
  hl_open_interest.close is used as gap fill via COALESCE.

Funding rate:
  Aggregated from hourly to daily via SUM(funding_rate) GROUP BY day.

Note: ASCII-only comments throughout (Windows cp1252 compatibility).
"""

from __future__ import annotations

import logging
from typing import Sequence

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Canonical column order for DerivativesFrame.
_FRAME_COLUMNS: list[str] = [
    "id",
    "venue_id",
    "ts",
    "oi",
    "funding_rate",
    "volume",
    "close",
    "mark_px",
]


def _empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the DerivativesFrame schema."""
    return pd.DataFrame(columns=_FRAME_COLUMNS)


def _get_hl_to_cmc_id_map(conn) -> dict[int, int]:
    """
    Build a mapping of HL asset_id -> CMC id (dim_listings.id).

    Joins hyperliquid.hl_assets (perp only, asset_id < 20000 excludes km)
    with dim_listings (venue='HYPERLIQUID') on matching ticker_on_venue = symbol.

    Only assets with a CMC match are returned. km assets (asset_id >= 20000)
    are excluded because they have no CMC id.

    Returns:
        dict mapping hl_asset_id (int) -> cmc_id (int)
    """
    rows = conn.execute(
        text("""
            SELECT
                ha.asset_id,
                dl.id AS cmc_id
            FROM hyperliquid.hl_assets ha
            JOIN dim_listings dl
                ON dl.ticker_on_venue = ha.symbol
               AND dl.venue = 'HYPERLIQUID'
            WHERE ha.asset_type = 'perp'
              AND ha.asset_id < 20000
              AND dl.id IS NOT NULL
        """)
    ).fetchall()

    result = {int(r[0]): int(r[1]) for r in rows}
    logger.debug("_get_hl_to_cmc_id_map: %d HL assets mapped to CMC ids", len(result))
    return result


class HyperliquidAdapter:
    """
    Loads derivatives data from Hyperliquid tables and returns a
    DerivativesFrame keyed on CMC id.

    VENUE_ID = 2 (HYPERLIQUID in dim_venues).

    Usage:
        adapter = HyperliquidAdapter(engine)
        df = adapter.load(cmc_ids=[1, 1027], start='2024-01-01', end='2024-12-31')
    """

    VENUE_ID: int = 2

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load(
        self,
        cmc_ids: Sequence[int],
        start: str | None = None,
        end: str | None = None,
        tf: str = "1D",  # noqa: ARG002 -- reserved for future multi-tf support
    ) -> pd.DataFrame:
        """
        Load normalized derivatives data for requested CMC ids.

        Steps:
          1. Build HL asset_id -> CMC id map; invert to cmc_id -> hl_asset_id.
          2. Filter to requested cmc_ids. If none match, return empty frame.
          3. Query hl_candles (interval='1d') for close, volume, close_oi.
          4. COALESCE with hl_open_interest.close for OI gap fill.
          5. Aggregate hl_funding_rates to daily SUM per asset.
          6. Get mark_px from hl_oi_snapshots (latest snapshot per day).
          7. Merge all sources; map hl_asset_id -> cmc_id; add venue_id.
          8. Return DataFrame with columns [id, venue_id, ts, oi, funding_rate,
             volume, close, mark_px].

        Args:
            cmc_ids: CMC ids to load data for.
            start:   Optional ISO date string (inclusive). e.g. '2024-01-01'
            end:     Optional ISO date string (inclusive). e.g. '2024-12-31'
            tf:      Timeframe string (currently only '1D' supported).

        Returns:
            DataFrame with _FRAME_COLUMNS schema. Empty if no matching assets.
        """
        cmc_ids_list = list(cmc_ids)
        if not cmc_ids_list:
            return _empty_frame()

        with self._engine.connect() as conn:
            hl_to_cmc = _get_hl_to_cmc_id_map(conn)
            if not hl_to_cmc:
                logger.warning("HyperliquidAdapter: no HL-to-CMC mappings found")
                return _empty_frame()

            # Invert: cmc_id -> hl_asset_id, then filter to requested ids.
            cmc_to_hl = {v: k for k, v in hl_to_cmc.items()}
            matched = {
                cmc_id: cmc_to_hl[cmc_id]
                for cmc_id in cmc_ids_list
                if cmc_id in cmc_to_hl
            }

            if not matched:
                logger.debug(
                    "HyperliquidAdapter: none of %d requested CMC ids have HL mappings",
                    len(cmc_ids_list),
                )
                return _empty_frame()

            hl_asset_ids = list(matched.values())
            logger.debug(
                "HyperliquidAdapter: loading %d HL assets for %d CMC ids",
                len(hl_asset_ids),
                len(matched),
            )

            # ------------------------------------------------------------------
            # Build date filter clauses.
            # ------------------------------------------------------------------
            date_params: dict = {}
            candle_date_filter = ""
            funding_date_filter = ""
            snapshot_date_filter = ""
            oi_date_filter = ""

            if start is not None:
                candle_date_filter += " AND c.ts >= :start"
                funding_date_filter += " AND fr.ts >= :start"
                snapshot_date_filter += " AND s.ts >= :start"
                oi_date_filter += " AND oi.ts >= :start"
                date_params["start"] = start
            if end is not None:
                # Use exclusive upper bound for end-of-day coverage.
                candle_date_filter += " AND c.ts < :end_exclusive"
                funding_date_filter += " AND fr.ts < :end_exclusive"
                snapshot_date_filter += " AND s.ts < :end_exclusive"
                oi_date_filter += " AND oi.ts < :end_exclusive"
                date_params["end_exclusive"] = pd.Timestamp(end) + pd.Timedelta(days=1)

            # ------------------------------------------------------------------
            # Query 1: hl_candles + hl_open_interest OI gap fill.
            # interval filter is always '1d'.
            # COALESCE(c.close_oi, oi.close) for OI.
            # ------------------------------------------------------------------
            candle_sql = text(f"""
                SELECT
                    c.asset_id,
                    DATE_TRUNC('day', c.ts) AS day,
                    c.close,
                    c.volume,
                    COALESCE(c.close_oi, oi.close) AS oi
                FROM hyperliquid.hl_candles c
                LEFT JOIN hyperliquid.hl_open_interest oi
                    ON oi.asset_id = c.asset_id
                   AND DATE_TRUNC('day', oi.ts) = DATE_TRUNC('day', c.ts)
                WHERE c.interval = '1d'
                  AND c.asset_id = ANY(:asset_ids)
                  {candle_date_filter}
                ORDER BY c.asset_id, day
            """)
            candle_rows = conn.execute(
                candle_sql,
                {"asset_ids": hl_asset_ids, **date_params},
            ).fetchall()

            df_candles = pd.DataFrame(
                candle_rows, columns=["asset_id", "day", "close", "volume", "oi"]
            )

            # ------------------------------------------------------------------
            # Query 2: hl_funding_rates aggregated to daily SUM.
            # ------------------------------------------------------------------
            funding_sql = text(f"""
                SELECT
                    fr.asset_id,
                    DATE_TRUNC('day', fr.ts) AS day,
                    SUM(fr.funding_rate) AS funding_rate
                FROM hyperliquid.hl_funding_rates fr
                WHERE fr.asset_id = ANY(:asset_ids)
                  {funding_date_filter}
                GROUP BY fr.asset_id, DATE_TRUNC('day', fr.ts)
                ORDER BY fr.asset_id, day
            """)
            funding_rows = conn.execute(
                funding_sql,
                {"asset_ids": hl_asset_ids, **date_params},
            ).fetchall()

            df_funding = pd.DataFrame(
                funding_rows, columns=["asset_id", "day", "funding_rate"]
            )

            # ------------------------------------------------------------------
            # Query 3: hl_oi_snapshots for mark_px -- latest per day per asset.
            # DISTINCT ON (asset_id, day) ORDER BY day DESC gives latest snapshot.
            # ------------------------------------------------------------------
            snapshot_sql = text(f"""
                SELECT DISTINCT ON (s.asset_id, DATE_TRUNC('day', s.ts))
                    s.asset_id,
                    DATE_TRUNC('day', s.ts) AS day,
                    s.mark_px
                FROM hyperliquid.hl_oi_snapshots s
                WHERE s.asset_id = ANY(:asset_ids)
                  {snapshot_date_filter}
                ORDER BY s.asset_id, DATE_TRUNC('day', s.ts), s.ts DESC
            """)
            snapshot_rows = conn.execute(
                snapshot_sql,
                {"asset_ids": hl_asset_ids, **date_params},
            ).fetchall()

            df_snapshots = pd.DataFrame(
                snapshot_rows, columns=["asset_id", "day", "mark_px"]
            )

        # ------------------------------------------------------------------
        # Merge all sources on (asset_id, day).
        # Base is df_candles (close + volume + oi).
        # LEFT JOIN funding (may be missing for some days).
        # LEFT JOIN mark_px snapshots.
        # ------------------------------------------------------------------
        if df_candles.empty:
            logger.debug("HyperliquidAdapter: no candle rows returned")
            return _empty_frame()

        df = df_candles.copy()

        if not df_funding.empty:
            df = df.merge(df_funding, on=["asset_id", "day"], how="left")
        else:
            df["funding_rate"] = None

        if not df_snapshots.empty:
            df = df.merge(df_snapshots, on=["asset_id", "day"], how="left")
        else:
            df["mark_px"] = None

        # ------------------------------------------------------------------
        # Map hl_asset_id -> CMC id; add venue_id.
        # ------------------------------------------------------------------
        df["id"] = df["asset_id"].map(hl_to_cmc)
        df["venue_id"] = self.VENUE_ID
        df = df.rename(columns={"day": "ts"})

        # Ensure ts is UTC-aware.
        if not df.empty and hasattr(df["ts"], "dt"):
            if df["ts"].dt.tz is None:
                df["ts"] = df["ts"].dt.tz_localize("UTC")

        # Select and reorder canonical columns.
        df = df[_FRAME_COLUMNS].copy()

        # Cast numeric columns to float.
        for col in ("oi", "funding_rate", "volume", "close", "mark_px"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.debug(
            "HyperliquidAdapter: returning %d rows for %d assets",
            len(df),
            df["id"].nunique() if not df.empty else 0,
        )
        return df


class MockAdapter:
    """
    Mock adapter for testing and graceful degradation.

    Returns an empty DataFrame with the correct DerivativesFrame schema.
    Never accesses the database.

    VENUE_ID = 99 (sentinel for test/mock venue).
    """

    VENUE_ID: int = 99

    def load(self, cmc_ids: Sequence[int], **kwargs) -> pd.DataFrame:  # noqa: ARG002
        """
        Return empty DataFrame with DerivativesFrame schema.

        Args:
            cmc_ids: Ignored.
            **kwargs: Ignored.

        Returns:
            Empty DataFrame with columns [id, venue_id, ts, oi,
            funding_rate, volume, close, mark_px].
        """
        return _empty_frame()
