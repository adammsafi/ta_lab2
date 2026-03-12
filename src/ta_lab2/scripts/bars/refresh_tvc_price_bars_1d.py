"""
1D Bar Builder for TradingView data.

Builds daily OHLC bars from tvc_price_histories into price_bars_1d.
Writes to the SAME output table as the CMC builder so downstream pipeline
(multi-TF bars, EMAs, features, signals) works without changes.

Key differences from CMC builder:
- Source: tvc_price_histories (not cmc_price_histories7)
- No timehigh/timelow: synthesized as timestamp (bar close)
- No market_cap: set to NULL
- Multi-venue: builds bars for ALL venues, ranks from dim_listings.venue_rank
- No OHLC repair needed (no intraday timestamps to fix)

Usage:
    python -m ta_lab2.scripts.bars.refresh_tvc_price_bars_1d --ids all --full-rebuild
    python -m ta_lab2.scripts.bars.refresh_tvc_price_bars_1d --ids 100002 100003
    python -m ta_lab2.scripts.bars.refresh_tvc_price_bars_1d --ids all --venue GATE
"""

from __future__ import annotations

import argparse
from typing import Any, List, Optional, Sequence

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

# Prefer psycopg v3, fall back to psycopg2
try:
    import psycopg  # type: ignore

    PSYCOPG3 = True
except Exception:
    psycopg = None
    PSYCOPG3 = False

try:
    import psycopg2  # type: ignore

    PSYCOPG2 = True
except Exception:
    psycopg2 = None
    PSYCOPG2 = False


def _normalize_db_url(url: str) -> str:
    """Remove SQLAlchemy dialect prefix for psycopg connection."""
    if not url:
        return url
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+psycopg3://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
        "postgres+psycopg3://",
    ):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _connect(db_url: str):
    """Create psycopg connection (v3 preferred, v2 fallback)."""
    url = _normalize_db_url(db_url)
    if PSYCOPG3:
        return psycopg.connect(url, autocommit=True)
    if PSYCOPG2:
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn
    raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")


def _exec(conn, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    """Execute SQL statement."""
    params = params or []
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()


def _fetchone(conn, sql: str, params: Optional[Sequence[Any]] = None):
    """Execute SQL and return first row."""
    params = params or []
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row


def _get_last_src_ts(conn, state: str, id_: int) -> Optional[str]:
    """Get last processed timestamp for incremental refresh."""
    row = _fetchone(conn, f"SELECT last_src_ts FROM {state} WHERE id = %s;", [id_])
    if not row or row[0] is None:
        return None
    return str(row[0])


def _build_insert_bars_sql(dst: str, src: str, venue_filter: str | None) -> str:
    """
    Build SQL CTE for TVC 1D bar computation.

    Simpler than CMC version:
    - No timehigh/timelow repair (synthesized as ts)
    - No market_cap
    - Builds ALL venues by default (venue_filter=None)
    - Writes venue + venue_rank columns for multi-exchange support
    """
    venue_clause = ""
    if venue_filter:
        venue_clause = f"AND s.venue = '{venue_filter}'"

    return f"""
WITH src_filtered AS (
  SELECT DISTINCT ON (s.id, s.venue, s.ts)
    s.id,
    s.venue,
    s.ts AS "timestamp",
    s.open,
    s.high,
    s.low,
    s.close,
    s.volume,
    COALESCE(dl.venue_rank, 50) AS venue_rank,
    s.source_file,
    s.ingested_at
  FROM {src} s
  LEFT JOIN public.dim_listings dl
    ON dl.id = s.id AND dl.venue = s.venue
  WHERE s.id = %s
    {venue_clause}
  ORDER BY s.id, s.venue, s.ts
),
ranked AS (
  SELECT
    id,
    venue,
    venue_rank,
    "timestamp",
    dense_rank() OVER (PARTITION BY id, venue ORDER BY "timestamp" ASC)::integer AS bar_seq,
    open, high, low, close, volume,
    source_file, ingested_at
  FROM src_filtered
  WHERE id = %s
    AND (%s IS NULL OR "timestamp" >= %s)
    AND (%s IS NULL OR "timestamp" <  %s)
),
final AS (
  SELECT
    id,
    venue,
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

    'TradingView'::text AS src_name,
    ingested_at AS src_load_ts,
    source_file AS src_file
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
    venue, venue_rank
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
    src_name, src_load_ts, src_file,
    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,
    venue, venue_rank
  FROM final
  WHERE
    id IS NOT NULL
    AND "timestamp" IS NOT NULL
    AND open IS NOT NULL
    AND close IS NOT NULL
    AND high >= low
  ON CONFLICT (id, tf, bar_seq, venue, "timestamp") DO UPDATE SET
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


def _load_tvc_ids(db_url: str) -> list[int]:
    """Load all asset IDs that have data in tvc_price_histories."""
    from sqlalchemy import text

    engine = get_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT id FROM tvc_price_histories ORDER BY id")
        ).fetchall()
    return [r[0] for r in rows]


class TvcOneDayBarBuilder(BaseBarBuilder):
    """
    1D Bar Builder for TradingView data.

    Builds daily OHLC bars from tvc_price_histories into price_bars_1d.
    Uses the same output table as the CMC builder so the downstream pipeline
    works transparently for both CMC and TVC assets.
    """

    STATE_TABLE = "public.price_bars_1d_state"
    OUTPUT_TABLE = "public.price_bars_1d"
    SOURCE_TABLE = "public.tvc_price_histories"

    def __init__(
        self, config: BarBuilderConfig, engine: Engine, venue: str | None = None
    ):
        super().__init__(config, engine)
        self.psycopg_conn = _connect(config.db_url)
        self.venue = venue

    def get_state_table_name(self) -> str:
        return self.STATE_TABLE

    def get_output_table_name(self) -> str:
        return self.OUTPUT_TABLE

    def get_source_query(self, id_: int, start_ts: Optional[str] = None) -> str:
        return f"SELECT * FROM {self.SOURCE_TABLE} WHERE id = {id_}"

    def ensure_state_table_exists(self) -> None:
        """Ensure 1D state table exists (shared with CMC builder)."""
        state_table = self.get_state_table_name()
        self.logger.info(f"Ensuring state table exists: {state_table}")

        if "." in state_table:
            fq_table = state_table
        else:
            fq_table = f"public.{state_table}"

        ddl = f"""
        CREATE TABLE IF NOT EXISTS {fq_table} (
            id INTEGER NOT NULL,
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
            PRIMARY KEY (id, tf)
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
        """Build 1D bars for one TVC asset ID."""
        conn = self.psycopg_conn
        src = self.SOURCE_TABLE
        dst = self.OUTPUT_TABLE
        state = self.STATE_TABLE

        # Full rebuild: delete existing bars for this ID
        if self.config.full_rebuild:
            _exec(
                conn,
                f"DELETE FROM {dst} WHERE id = %s AND tf = '1D' AND src_name = 'TradingView';",
                [id_],
            )
            _exec(conn, f"DELETE FROM {state} WHERE id = %s AND tf = '1D';", [id_])

        last_src_ts = _get_last_src_ts(conn, state, id_)
        time_max = None

        params: List[Any] = [
            id_,  # src_filtered WHERE id
            id_,  # ranked WHERE id
            last_src_ts,  # >= start
            last_src_ts,
            time_max,  # < end
            time_max,
        ]

        ins_sql = _build_insert_bars_sql(dst=dst, src=src, venue_filter=self.venue)
        row = _fetchone(conn, ins_sql, params)

        upserted = int(row[0]) if row and row[0] is not None else 0
        max_src_ts = row[1] if row else None

        if max_src_ts is not None:
            _exec(
                conn,
                f"""
                INSERT INTO {state} (id, tf, last_src_ts, last_run_ts, last_upserted)
                VALUES (%s, '1D', %s, now(), %s)
                ON CONFLICT (id, tf) DO UPDATE SET
                  last_src_ts = COALESCE(EXCLUDED.last_src_ts, {state}.last_src_ts),
                  last_run_ts = now(),
                  last_upserted = EXCLUDED.last_upserted;
                """,
                [id_, max_src_ts, upserted],
            )

            # Coverage tracking
            stats_row = _fetchone(
                conn,
                f"SELECT MIN(ts), MAX(ts), COUNT(*)::bigint FROM {src} WHERE id = %s;",
                [id_],
            )
            if stats_row and stats_row[2]:
                try:
                    upsert_coverage(
                        self.engine,
                        id_=id_,
                        source_table=src,
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
            description="Build 1D bars from TradingView price data.",
            default_daily_table="public.tvc_price_histories",
            default_bars_table="public.price_bars_1d",
            default_state_table="public.price_bars_1d_state",
            include_tz=False,
        )
        parser.add_argument(
            "--venue",
            type=str,
            default=None,
            help="Filter to specific venue (e.g., GATE). Default: build ALL venues.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "TvcOneDayBarBuilder":
        db_url = resolve_db_url(args.db_url)
        engine = get_engine(db_url)

        ids_parsed = parse_ids(args.ids)
        if ids_parsed == "all":
            ids = _load_tvc_ids(db_url)
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

        venue = getattr(args, "venue", None)
        return cls(config=config, engine=engine, venue=venue)


def _sync_1d_to_multi_tf(db_url: str) -> None:
    """Copy TVC 1D bars to price_bars_multi_tf for downstream pipeline."""
    import logging

    logger = logging.getLogger(__name__)
    conn = _connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO public.price_bars_multi_tf
            SELECT * FROM public.price_bars_1d
            WHERE src_name = 'TradingView'
            ON CONFLICT (id, tf, bar_seq, venue, "timestamp") DO UPDATE SET
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
        logger.info("Synced TVC 1D bars to price_bars_multi_tf")
        cur.close()
    except Exception as e:
        logger.warning("Failed to sync 1D bars to multi_tf: %s", e)


def main() -> None:
    parser = TvcOneDayBarBuilder.create_argument_parser()
    args = parser.parse_args()
    builder = TvcOneDayBarBuilder.from_cli_args(args)
    builder.run()
    _sync_1d_to_multi_tf(builder.config.db_url)


if __name__ == "__main__":
    main()
