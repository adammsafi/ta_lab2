"""
1D Bar Builder for Hyperliquid data.

Builds daily OHLC bars from hyperliquid.hl_candles into price_bars_1d.
Writes to the SAME output table as the CMC/TVC builders so downstream pipeline
(multi-TF bars, EMAs, features, signals) works without changes.

Key differences from TVC builder:
- Source: hyperliquid.hl_candles WHERE interval = '1d'
- ID mapping: JOIN dim_asset_identifiers to translate hl_candles.asset_id → dim_assets.id
- Venue: hardcode 'HYPERLIQUID', venue_rank from dim_listings
- No market_cap: set to NULL (same as TVC)
- No timehigh/timelow: synthesized as bar timestamp (same as TVC)
- src_name: 'Hyperliquid'
- Asset filtering: Only Y-marked assets from HL_YN.csv

Usage:
    python -m ta_lab2.scripts.bars.refresh_hl_price_bars_1d --ids all --full-rebuild
    python -m ta_lab2.scripts.bars.refresh_hl_price_bars_1d --ids 1,28,65
    python -m ta_lab2.scripts.bars.refresh_hl_price_bars_1d --ids all
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.base_bar_builder import BaseBarBuilder
from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    parse_ids,
    resolve_db_url,
    ensure_coverage_table,
    upsert_coverage,
)
from ta_lab2.db.psycopg_helpers import (
    connect,
    execute,
    fetchone,
    fetchall,
)

logger = logging.getLogger(__name__)

# Default path to HL_YN.csv (project root)
_DEFAULT_CSV = Path(__file__).resolve().parents[4] / "HL_YN.csv"


_HL_VENUE_ID = 2  # dim_venues: HYPERLIQUID = 2


def _get_last_src_ts(conn, state: str, id_: int) -> Optional[str]:
    """Get last processed timestamp for incremental refresh."""
    row = fetchone(
        conn,
        f"SELECT last_src_ts FROM {state} WHERE id = %s AND venue_id = %s AND tf = '1D';",
        [id_, _HL_VENUE_ID],
    )
    if not row or row[0] is None:
        return None
    return str(row[0])


def _load_y_asset_ids(csv_path: str | Path | None = None) -> set[int]:
    """Load Y-marked HL asset_ids from HL_YN.csv."""
    path = Path(csv_path) if csv_path else _DEFAULT_CSV
    if not path.exists():
        raise FileNotFoundError(f"HL_YN.csv not found at {path}")

    y_ids: set[int] = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Y/N", "").strip().upper() == "Y":
                y_ids.add(int(row["asset_id"].strip()))
    logger.info("Loaded %d Y-marked HL asset_ids from %s", len(y_ids), path)
    return y_ids


def _load_hl_ids(db_url: str, csv_path: str | Path | None = None) -> list[int]:
    """
    Load dim_assets IDs for Y-marked HL assets.

    Reads HL_YN.csv for Y asset_ids, then JOINs dim_asset_identifiers
    WHERE id_type='HL' to translate to dim_assets.id.
    """
    y_asset_ids = _load_y_asset_ids(csv_path)
    if not y_asset_ids:
        logger.warning("No Y-marked assets found in HL_YN.csv")
        return []

    conn = connect(db_url)
    placeholders = ",".join(["%s"] * len(y_asset_ids))
    rows = fetchall(
        conn,
        f"""
        SELECT DISTINCT dai.id
        FROM dim_asset_identifiers dai
        WHERE dai.id_type = 'HL'
          AND dai.id_value::int IN ({placeholders})
        ORDER BY dai.id
        """,
        list(y_asset_ids),
    )
    conn.close()

    dim_ids = [r[0] for r in rows]
    logger.info(
        "Resolved %d dim_assets IDs from %d Y-marked HL asset_ids",
        len(dim_ids),
        len(y_asset_ids),
    )
    return dim_ids


def _build_insert_bars_sql(dst: str) -> str:
    """
    Build SQL CTE for HL 1D bar computation.

    Source: hyperliquid.hl_candles joined to dim_asset_identifiers for ID mapping.
    Similar to TVC builder but reads from HL candles table.
    """
    return f"""
WITH src_filtered AS (
  SELECT DISTINCT ON (dai.id, c.ts)
    dai.id,
    'HYPERLIQUID'::text AS venue,
    {_HL_VENUE_ID}::smallint AS venue_id,
    c.ts AS "timestamp",
    c.open::double precision,
    c.high::double precision,
    c.low::double precision,
    c.close::double precision,
    c.volume::double precision,
    COALESCE(dl.venue_rank, 50) AS venue_rank
  FROM hyperliquid.hl_candles c
  JOIN dim_asset_identifiers dai
    ON dai.id_type = 'HL'
   AND dai.id_value::int = c.asset_id
  LEFT JOIN public.dim_listings dl
    ON dl.id = dai.id AND dl.venue = 'HYPERLIQUID'
  WHERE dai.id = %s
    AND c.interval = '1d'
  ORDER BY dai.id, c.ts
),
ranked AS (
  SELECT
    id,
    venue,
    venue_id,
    venue_rank,
    "timestamp",
    dense_rank() OVER (PARTITION BY id ORDER BY "timestamp" ASC)::integer AS bar_seq,
    open, high, low, close, volume
  FROM src_filtered
  WHERE id = %s
    AND (%s IS NULL OR "timestamp" >= %s)
    AND (%s IS NULL OR "timestamp" <  %s)
),
final AS (
  SELECT
    id,
    venue,
    venue_id,
    venue_rank,
    "timestamp",
    '1D'::text AS tf,
    bar_seq,

    "timestamp" AS time_open,
    "timestamp" AS time_close,
    "timestamp" AS time_high,
    "timestamp" AS time_low,

    open,
    GREATEST(high, open, close, low) AS high,
    LEAST(low, open, close, high) AS low,
    close,
    volume,
    NULL::double precision AS market_cap,

    false::boolean AS is_partial_start,
    false::boolean AS is_partial_end,
    false::boolean AS is_missing_days,

    1::integer AS tf_days,
    1::integer AS pos_in_bar,
    1::integer AS count_days,
    0::integer AS count_days_remaining,
    0::integer AS count_missing_days,
    0::integer AS count_missing_days_start,
    0::integer AS count_missing_days_end,
    0::integer AS count_missing_days_interior,

    false::boolean AS repaired_timehigh,
    false::boolean AS repaired_timelow,
    false::boolean AS repaired_high,
    false::boolean AS repaired_low,

    'Hyperliquid'::text AS src_name
  FROM ranked
),
ins AS (
  INSERT INTO {dst} (
    id, "timestamp",
    tf, bar_seq,
    time_open, time_close, time_high, time_low,
    time_open_bar, time_close_bar,
    last_ts_half_open,
    open, high, low, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    tf_days, pos_in_bar, count_days, count_days_remaining,
    count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
    src_name, src_load_ts, src_file,
    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,
    venue, venue_id, venue_rank
  )
  SELECT
    id, "timestamp",
    tf, bar_seq,
    time_open, time_close, time_high, time_low,
    time_open AS time_open_bar, time_close AS time_close_bar,
    "timestamp" + interval '1 millisecond' AS last_ts_half_open,
    open, high, low, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    tf_days, pos_in_bar, count_days, count_days_remaining,
    count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
    src_name, now() AS src_load_ts, NULL::text AS src_file,
    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,
    venue, venue_id, venue_rank
  FROM final
  WHERE
    id IS NOT NULL
    AND "timestamp" IS NOT NULL
    AND open IS NOT NULL
    AND close IS NOT NULL
    AND high >= low
  ON CONFLICT (id, tf, bar_seq, venue_id, "timestamp") DO UPDATE SET
    time_open = EXCLUDED.time_open,
    time_close = EXCLUDED.time_close,
    time_high = EXCLUDED.time_high,
    time_low = EXCLUDED.time_low,
    time_open_bar = EXCLUDED.time_open_bar,
    time_close_bar = EXCLUDED.time_close_bar,
    last_ts_half_open = EXCLUDED.last_ts_half_open,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low  = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    market_cap = EXCLUDED.market_cap,
    src_name = EXCLUDED.src_name,
    src_load_ts = EXCLUDED.src_load_ts,
    src_file = EXCLUDED.src_file,
    venue_rank = EXCLUDED.venue_rank
  RETURNING "timestamp"
)
SELECT
  count(*)::int AS upserted,
  max("timestamp") AS max_src_ts
FROM ins;
"""


class HlOneDayBarBuilder(BaseBarBuilder):
    """
    1D Bar Builder for Hyperliquid data.

    Builds daily OHLC bars from hyperliquid.hl_candles into price_bars_1d.
    Uses the same output table as CMC/TVC builders so the downstream pipeline
    works transparently for all sources.
    """

    STATE_TABLE = "public.price_bars_1d_state"
    OUTPUT_TABLE = "public.price_bars_1d"

    def __init__(self, config: BarBuilderConfig, engine: Engine):
        super().__init__(config, engine)
        self.psycopg_conn = connect(config.db_url)

    def get_state_table_name(self) -> str:
        return self.STATE_TABLE

    def get_output_table_name(self) -> str:
        return self.OUTPUT_TABLE

    def get_source_query(self, id_: int, start_ts: Optional[str] = None) -> str:
        return (
            f"SELECT * FROM hyperliquid.hl_candles c "
            f"JOIN dim_asset_identifiers dai ON dai.id_type = 'HL' "
            f"AND dai.id_value::int = c.asset_id "
            f"WHERE dai.id = {id_} AND c.interval = '1d'"
        )

    def ensure_state_table_exists(self) -> None:
        """Ensure 1D state table exists (shared with CMC/TVC builder)."""
        state_table = self.get_state_table_name()
        self.logger.info(f"Ensuring state table exists: {state_table}")

        if "." in state_table:
            fq_table = state_table
        else:
            fq_table = f"public.{state_table}"

        ddl = f"""
        CREATE TABLE IF NOT EXISTS {fq_table} (
            id INTEGER NOT NULL,
            venue_id SMALLINT NOT NULL DEFAULT 1,
            tf TEXT NOT NULL DEFAULT '1D',
            last_src_ts TIMESTAMPTZ,
            daily_min_seen TIMESTAMPTZ,
            daily_max_seen TIMESTAMPTZ,
            last_bar_seq INTEGER,
            last_time_close TIMESTAMPTZ,
            last_run_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_upserted INTEGER NOT NULL DEFAULT 0,
            last_repaired_timehigh INTEGER NOT NULL DEFAULT 0,
            last_repaired_timelow INTEGER NOT NULL DEFAULT 0,
            last_rejected INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, venue_id, tf)
        );
        """

        from sqlalchemy import text as sa_text

        try:
            with self.engine.begin() as conn:
                conn.execute(sa_text(ddl))
            self.logger.info(f"State table ready: {state_table}")
        except Exception as e:
            self.logger.error(f"Failed to ensure state table {state_table}: {e}")
            raise

        ensure_coverage_table(self.engine)

    def build_bars_for_id(
        self,
        id_: int,
        start_ts: Optional[str] = None,
    ) -> int:
        """Build 1D bars for one HL asset ID (dim_assets.id)."""
        conn = self.psycopg_conn
        dst = self.OUTPUT_TABLE
        state = self.STATE_TABLE

        # Full rebuild: delete existing HL bars for this ID
        if self.config.full_rebuild:
            execute(
                conn,
                f"DELETE FROM {dst} WHERE id = %s AND tf = '1D' AND venue_id = %s;",
                [id_, _HL_VENUE_ID],
            )
            execute(
                conn,
                f"DELETE FROM {state} WHERE id = %s AND venue_id = %s AND tf = '1D';",
                [id_, _HL_VENUE_ID],
            )

        last_src_ts = _get_last_src_ts(conn, state, id_)
        time_max = None

        params: List[Any] = [
            id_,  # src_filtered WHERE dai.id
            id_,  # ranked WHERE id
            last_src_ts,  # >= start
            last_src_ts,
            time_max,  # < end
            time_max,
        ]

        ins_sql = _build_insert_bars_sql(dst=dst)
        row = fetchone(conn, ins_sql, params)

        upserted = int(row[0]) if row and row[0] is not None else 0
        max_src_ts = row[1] if row else None

        if max_src_ts is not None:
            execute(
                conn,
                f"""
                INSERT INTO {state} (id, venue_id, tf, last_src_ts, last_run_ts, last_upserted)
                VALUES (%s, %s, '1D', %s, now(), %s)
                ON CONFLICT (id, venue_id, tf) DO UPDATE SET
                  last_src_ts = COALESCE(EXCLUDED.last_src_ts, {state}.last_src_ts),
                  last_run_ts = now(),
                  last_upserted = EXCLUDED.last_upserted;
                """,
                [id_, _HL_VENUE_ID, max_src_ts, upserted],
            )

            # Coverage tracking
            stats_row = fetchone(
                conn,
                """
                SELECT MIN(c.ts), MAX(c.ts), COUNT(*)::bigint
                FROM hyperliquid.hl_candles c
                JOIN dim_asset_identifiers dai
                  ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id
                WHERE dai.id = %s AND c.interval = '1d';
                """,
                [id_],
            )
            if stats_row and stats_row[2]:
                try:
                    upsert_coverage(
                        self.engine,
                        id_=id_,
                        source_table="hyperliquid.hl_candles",
                        granularity="1D",
                        n_rows=int(stats_row[2]),
                        n_days=int(stats_row[2]),
                        first_ts=stats_row[0],
                        last_ts=stats_row[1],
                    )
                except Exception as e:
                    self.logger.warning(f"ID={id_}: coverage upsert failed: {e}")

        self.logger.debug(f"ID={id_}: upserted={upserted}")
        return upserted

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        parser = cls.create_base_argument_parser(
            description="Build 1D bars from Hyperliquid candle data.",
            default_daily_table="hyperliquid.hl_candles",
            default_bars_table="public.price_bars_1d",
            default_state_table="public.price_bars_1d_state",
            include_tz=False,
        )
        parser.add_argument(
            "--csv",
            type=str,
            default=None,
            help="Path to HL_YN.csv (default: project root HL_YN.csv)",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HlOneDayBarBuilder":
        db_url = resolve_db_url(args.db_url)
        engine = get_engine(db_url)

        ids_parsed = parse_ids(args.ids)
        if ids_parsed == "all":
            csv_path = getattr(args, "csv", None)
            ids = _load_hl_ids(db_url, csv_path)
        else:
            ids = ids_parsed

        config = BarBuilderConfig(
            db_url=db_url,
            ids=ids,
            daily_table=args.daily_table,
            bars_table=args.bars_table,
            state_table=args.state_table,
            full_rebuild=args.full_rebuild,
            keep_rejects=False,
            rejects_table=f"{args.bars_table}_rejects",
            num_processes=getattr(args, "num_processes", 6),
            log_level="INFO",
            log_file=None,
            tz=None,
        )

        return cls(config=config, engine=engine)


def _sync_1d_to_multi_tf(db_url: str) -> None:
    """Copy HL 1D bars to price_bars_multi_tf for downstream pipeline."""
    logger.info("Syncing HL 1D bars to price_bars_multi_tf...")
    conn = connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO public.price_bars_multi_tf
            SELECT * FROM public.price_bars_1d
            WHERE src_name = 'Hyperliquid'
            ON CONFLICT (id, tf, bar_seq, venue_id, "timestamp") DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low  = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                market_cap = EXCLUDED.market_cap,
                src_name = EXCLUDED.src_name,
                src_load_ts = EXCLUDED.src_load_ts,
                src_file = EXCLUDED.src_file,
                venue_rank = EXCLUDED.venue_rank
        """)
        logger.info("Synced HL 1D bars to price_bars_multi_tf")
        cur.close()
    except Exception as e:
        logger.warning("Failed to sync 1D bars to multi_tf: %s", e)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = HlOneDayBarBuilder.create_argument_parser()
    args = parser.parse_args()
    builder = HlOneDayBarBuilder.from_cli_args(args)
    builder.run()
    _sync_1d_to_multi_tf(builder.config.db_url)


if __name__ == "__main__":
    main()
