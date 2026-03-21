"""
Build VWAP (Volume-Weighted Average Price) consolidated 1D bars.

Reads per-venue 1D bars, computes VWAP across venues, writes as venue_id=1
(CMC_AGG slot) with src_name='VWAP' to distinguish from raw CMC data.

VWAP computation per (id, timestamp):
  close_vwap = sum(close_i * volume_i) / sum(volume_i)
  open_vwap  = sum(open_i * volume_i) / sum(volume_i)
  high       = max(high_i)      -- worst-case high across venues
  low        = min(low_i)       -- worst-case low across venues
  volume     = sum(volume_i)    -- total volume

Runs AFTER per-venue 1D bars are built, BEFORE multi-TF builder.

Input exclusion: venue_id=1 (CMC_AGG) is excluded from inputs so that
raw CMC aggregate data does not contaminate VWAP. Only venue_id >= 2
rows (HYPERLIQUID, BATS, NASDAQ, NYSE, TVC, etc.) feed the VWAP.

Output: venue_id=1, src_name='VWAP' — written into the CMC_AGG slot
to signal this is the consolidated VWAP bar for that asset.

Usage:
    python -m ta_lab2.scripts.bars.refresh_vwap_bars_1d --ids all
    python -m ta_lab2.scripts.bars.refresh_vwap_bars_1d --ids 12573
"""

from __future__ import annotations

import argparse
import logging
import os

from sqlalchemy import text

from ta_lab2.io import get_engine
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

BARS_TABLE = "public.price_bars_1d"
# venue_id=1 is CMC_AGG -- excluded from VWAP inputs so we don't mix
# the aggregate with per-exchange bars. VWAP output is written BACK as
# venue_id=1 with src_name='VWAP'.
EXCLUDED_VENUE_ID = 1  # CMC_AGG


def _build_vwap_sql(bars_table: str, excluded_venue_id: int) -> str:
    """Build INSERT SQL for VWAP consolidated bars."""
    return f"""
    INSERT INTO {bars_table} (
        id, "timestamp", tf, tf_days, bar_seq,
        pos_in_bar, count_days, count_days_remaining,
        time_open, time_close, time_high, time_low,
        time_open_bar, time_close_bar, last_ts_half_open,
        open, high, low, close, volume, market_cap,
        is_partial_start, is_partial_end, is_missing_days,
        count_missing_days, count_missing_days_start,
        count_missing_days_end, count_missing_days_interior,
        src_name, src_load_ts, src_file,
        repaired_timehigh, repaired_timelow,
        repaired_high, repaired_low,
        repaired_open, repaired_close,
        repaired_volume, repaired_market_cap,
        venue_id, ingested_at
    )
    SELECT
        id,
        "timestamp",
        '1D'::text AS tf,
        1::integer AS tf_days,
        ROW_NUMBER() OVER (PARTITION BY id ORDER BY "timestamp")::integer AS bar_seq,
        1::integer AS pos_in_bar,
        1::integer AS count_days,
        0::integer AS count_days_remaining,
        "timestamp" AS time_open,
        "timestamp" AS time_close,
        "timestamp" AS time_high,
        "timestamp" AS time_low,
        "timestamp" AS time_open_bar,
        "timestamp" AS time_close_bar,
        "timestamp" + interval '1 millisecond' AS last_ts_half_open,
        SUM(open * volume) / NULLIF(SUM(volume), 0) AS open,
        MAX(high) AS high,
        MIN(low) AS low,
        SUM(close * volume) / NULLIF(SUM(volume), 0) AS close,
        SUM(volume) AS volume,
        SUM(market_cap) AS market_cap,
        false AS is_partial_start,
        false AS is_partial_end,
        false AS is_missing_days,
        0::integer AS count_missing_days,
        0::integer AS count_missing_days_start,
        0::integer AS count_missing_days_end,
        0::integer AS count_missing_days_interior,
        'VWAP'::text AS src_name,
        NOW() AS src_load_ts,
        'refresh_vwap_bars_1d'::text AS src_file,
        false AS repaired_timehigh,
        false AS repaired_timelow,
        false AS repaired_high,
        false AS repaired_low,
        false AS repaired_open,
        false AS repaired_close,
        false AS repaired_volume,
        false AS repaired_market_cap,
        {excluded_venue_id}::smallint AS venue_id,
        NOW() AS ingested_at
    FROM {bars_table}
    WHERE venue_id != {excluded_venue_id}
      AND id = :id
      AND tf = '1D'
    GROUP BY id, "timestamp"
    HAVING COUNT(*) >= 2  -- Only consolidate when 2+ venues have data
    ON CONFLICT (id, tf, bar_seq, venue_id, "timestamp") DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low  = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        market_cap = EXCLUDED.market_cap,
        src_load_ts = EXCLUDED.src_load_ts,
        ingested_at = EXCLUDED.ingested_at
    """


def _load_ids_with_multiple_venues(db_url: str) -> list[int]:
    """Find IDs that have bars from 2+ non-CMC_AGG venues."""
    engine = get_engine(db_url)
    sql = text(f"""
        SELECT id
        FROM {BARS_TABLE}
        WHERE venue_id != {EXCLUDED_VENUE_ID} AND tf = '1D'
        GROUP BY id
        HAVING COUNT(DISTINCT venue_id) >= 2
        ORDER BY id
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [row[0] for row in rows]


def build_vwap_for_id(db_url: str, id_: int) -> int:
    """Build VWAP bars for one ID. Returns number of rows upserted."""
    engine = get_engine(db_url)
    sql = text(_build_vwap_sql(BARS_TABLE, EXCLUDED_VENUE_ID))

    with engine.begin() as conn:
        result = conn.execute(sql, {"id": int(id_)})
        return result.rowcount


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build VWAP consolidated 1D bars from per-venue bars."
    )
    parser.add_argument(
        "--ids",
        required=True,
        help='Comma-separated IDs or "all" (auto-detect multi-venue assets)',
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("TARGET_DB_URL"),
        help="Database URL (default: TARGET_DB_URL env var)",
    )
    args = parser.parse_args(argv)

    db_url = resolve_db_url(args.db_url)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.ids.lower() == "all":
        ids = _load_ids_with_multiple_venues(db_url)
        logger.info("Auto-detected %d IDs with multiple venues", len(ids))
    else:
        ids = [int(x.strip()) for x in args.ids.split(",")]

    total_rows = 0
    for id_ in ids:
        try:
            rows = build_vwap_for_id(db_url, id_)
            total_rows += rows
            logger.info("ID=%d: %d VWAP bars upserted", id_, rows)
        except Exception as e:
            logger.error("ID=%d: VWAP build failed: %s", id_, e, exc_info=True)

    logger.info(
        "VWAP build complete: %d total rows across %d IDs", total_rows, len(ids)
    )


if __name__ == "__main__":
    main()
