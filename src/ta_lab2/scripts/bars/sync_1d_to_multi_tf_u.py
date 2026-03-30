"""
Sync price_bars_1d rows into price_bars_multi_tf_u.

The multi-TF builder (refresh_price_bars_multi_tf.py) only builds TFs >= 2D.
This script copies 1D rows from price_bars_1d into the unified _u table so
downstream consumers (EMAs, features, etc.) see all timeframes in one place.

Uses INSERT ... ON CONFLICT DO UPDATE to upsert — safe to run repeatedly.

Usage:
    python -m ta_lab2.scripts.bars.sync_1d_to_multi_tf_u
    python -m ta_lab2.scripts.bars.sync_1d_to_multi_tf_u --ids 1,52,1027
    python -m ta_lab2.scripts.bars.sync_1d_to_multi_tf_u --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import text

from ta_lab2.scripts.bars.common_snapshot_contract import resolve_db_url, get_engine

log = logging.getLogger(__name__)

SYNC_SQL = """
INSERT INTO price_bars_multi_tf_u (
    id, timestamp, tf, tf_days, bar_seq, alignment_source,
    pos_in_bar, count_days, count_days_remaining,
    time_open_bar, time_close_bar,
    open, high, low, close, volume, market_cap,
    time_high, time_low,
    is_partial_start, is_partial_end,
    time_open, time_close, last_ts_half_open,
    is_missing_days, count_missing_days,
    count_missing_days_start, count_missing_days_end,
    count_missing_days_interior, missing_days_where,
    first_missing_day, last_missing_day,
    repaired_timehigh, repaired_timelow,
    repaired_high, repaired_low,
    repaired_open, repaired_close,
    repaired_volume, repaired_market_cap,
    src_name, src_load_ts, src_file, ingested_at, venue_id
)
SELECT
    id, timestamp, tf, tf_days, bar_seq, 'multi_tf'::text,
    pos_in_bar, count_days, count_days_remaining,
    time_open_bar, time_close_bar,
    open, high, low, close, volume, market_cap,
    time_high, time_low,
    is_partial_start, is_partial_end,
    time_open, time_close, last_ts_half_open,
    is_missing_days, count_missing_days,
    count_missing_days_start, count_missing_days_end,
    count_missing_days_interior, missing_days_where,
    first_missing_day, last_missing_day,
    repaired_timehigh, repaired_timelow,
    repaired_high, repaired_low,
    repaired_open, repaired_close,
    repaired_volume, repaired_market_cap,
    src_name, src_load_ts, src_file, ingested_at, venue_id
FROM price_bars_1d
{where_clause}
ON CONFLICT (id, tf, bar_seq, venue_id, timestamp, alignment_source) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    market_cap = EXCLUDED.market_cap,
    src_load_ts = EXCLUDED.src_load_ts
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync price_bars_1d into price_bars_multi_tf_u"
    )
    parser.add_argument("--ids", default="all", help="Asset IDs (comma-separated or 'all')")
    parser.add_argument("--db-url", default=None, help="Database URL override")
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't sync")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_url = resolve_db_url(args.db_url)
    engine = get_engine(db_url)

    # Build WHERE clause for ID filtering
    if args.ids == "all":
        where_clause = ""
    else:
        id_list = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        where_clause = f"WHERE id IN ({','.join(str(i) for i in id_list)})"

    sql = SYNC_SQL.format(where_clause=where_clause)

    if args.dry_run:
        with engine.connect() as conn:
            count_sql = f"SELECT count(*) FROM price_bars_1d {where_clause}"
            n = conn.execute(text(count_sql)).scalar()
        log.info("[DRY RUN] Would sync %d rows from price_bars_1d → price_bars_multi_tf_u", n)
        return 0

    with engine.begin() as conn:
        r = conn.execute(text(sql))
        log.info("Synced %d rows from price_bars_1d → price_bars_multi_tf_u", r.rowcount)

    return 0


if __name__ == "__main__":
    sys.exit(main())
