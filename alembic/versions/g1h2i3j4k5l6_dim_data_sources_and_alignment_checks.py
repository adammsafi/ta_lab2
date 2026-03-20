"""dim_data_sources table and alignment_source CHECK constraints

Creates the dim_data_sources dimension table that captures per-source
differences (source table, venue_id, OHLC repair flag, SQL CTE templates)
for CMC, TVC, and Hyperliquid data sources. Also adds CHECK constraints
on alignment_source in all 6 _u tables to prevent typo-driven silent failures.

Operations (in order):
  A. Insert TVC into dim_venues (venue_id=11) -- required before FK reference
  B. Create dim_data_sources table with CMC/TVC/HL seed rows
  C. Add alignment_source CHECK constraints to all 6 _u tables
     (with 'unknown' remediation for ema_multi_tf_u before adding constraint)

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: g1h2i3j4k5l6
Revises: a0b1c2d3e4f5
Create Date: 2026-03-20
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, Sequence[str], None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Valid alignment_source values (all 5 sources across all 6 _u table families)
# ---------------------------------------------------------------------------
_VALID_ALIGNMENT_SOURCES = (
    "multi_tf",
    "multi_tf_cal_us",
    "multi_tf_cal_iso",
    "multi_tf_cal_anchor_us",
    "multi_tf_cal_anchor_iso",
)

_IN_LIST = ", ".join(f"'{v}'" for v in _VALID_ALIGNMENT_SOURCES)

# ---------------------------------------------------------------------------
# CMC CTE template (extracted from refresh_price_bars_1d.py _build_insert_bars_sql)
# Placeholders: {dst} = destination table, {src} = source table
# Runtime psycopg params (%s) for: id, time_max x2, id, time_min x2,
#   time_max x2, last_src_ts x2, lookback_days
# ---------------------------------------------------------------------------
_CMC_CTE_TEMPLATE = """\
WITH ranked_all AS (
  SELECT
    s.id,
    s."timestamp",
    dense_rank() OVER (PARTITION BY s.id ORDER BY s."timestamp" ASC)::integer AS bar_seq
  FROM {src} s
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" < %s)
),
src_rows AS (
  SELECT
    s.id,
    s.name,
    s.source_file,
    s.load_ts,

    s.timeopen  AS time_open,
    s.timeclose AS time_close,
    s.timehigh  AS time_high,
    s.timelow   AS time_low,

    s."timestamp",

    s.open,
    s.high,
    s.low,
    s.close,
    s.volume,
    s.marketcap AS market_cap,

    r.bar_seq
  FROM {src} s
  JOIN ranked_all r
    ON r.id = s.id
   AND r."timestamp" = s."timestamp"
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" >= %s)
    AND (%s IS NULL OR s."timestamp" <  %s)
    AND (
      %s IS NULL
      OR s."timestamp" > (%s::timestamptz - (%s * INTERVAL '1 day'))
    )
),
base AS (
  SELECT
    id,
    "timestamp",
    bar_seq,

    name,
    source_file,
    load_ts,

    time_open,
    time_close,

    (time_high IS NULL OR time_high < time_open OR time_high > time_close) AS needs_timehigh_repair,
    (time_low  IS NULL OR time_low  < time_open OR time_low  > time_close) AS needs_timelow_repair,

    open, high, low, close, volume, market_cap,
    time_high,
    time_low
  FROM src_rows
),
repaired AS (
  SELECT
    id,
    "timestamp",
    bar_seq,

    name,
    source_file,
    load_ts,

    time_open,
    time_close,

    CASE
      WHEN needs_timehigh_repair THEN
        CASE WHEN close >= open THEN time_close ELSE time_open END
      ELSE time_high
    END AS time_high_fix,

    CASE
      WHEN needs_timelow_repair THEN
        CASE WHEN close <= open THEN time_close ELSE time_open END
      ELSE time_low
    END AS time_low_fix,

    CASE
      WHEN needs_timehigh_repair THEN GREATEST(open, close)
      ELSE high
    END AS high_1,

    CASE
      WHEN needs_timelow_repair THEN LEAST(open, close)
      ELSE low
    END AS low_1,

    open,
    close,
    volume,
    market_cap,

    needs_timehigh_repair AS repaired_timehigh,
    needs_timelow_repair  AS repaired_timelow
  FROM base
),
final AS (
  SELECT
    id,
    "timestamp",
    '1D'::text AS tf,
    bar_seq,

    time_open,
    time_close,

    time_high_fix,
    time_low_fix,

    open,
    close,
    volume,
    market_cap,

    GREATEST(high_1, open, close, low_1) AS high_fix,
    LEAST(low_1,  open, close, high_1)  AS low_fix,

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

    repaired_timehigh,
    repaired_timelow,
    (GREATEST(high_1, open, close, low_1) <> high_1)::boolean AS repaired_high,
    (LEAST(low_1, open, close, high_1)  <> low_1)::boolean  AS repaired_low,

    name,
    load_ts,
    source_file
  FROM repaired
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
    repaired_timehigh, repaired_timelow, repaired_high, repaired_low
  )
  SELECT
    id, "timestamp",
    tf, bar_seq,
    time_open, time_close, time_high_fix, time_low_fix,
    time_open AS time_open_bar, time_close AS time_close_bar,
    "timestamp" + interval '1 millisecond' AS last_ts_half_open,
    open, high_fix, low_fix, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    tf_days, pos_in_bar, count_days, count_days_remaining,
    count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
    name, load_ts, source_file,
    repaired_timehigh, repaired_timelow, repaired_high, repaired_low
  FROM final
  WHERE
    id IS NOT NULL
    AND "timestamp" IS NOT NULL
    AND tf IS NOT NULL
    AND bar_seq IS NOT NULL
    AND time_open IS NOT NULL
    AND time_close IS NOT NULL
    AND open IS NOT NULL
    AND close IS NOT NULL
    AND volume IS NOT NULL
    AND time_high_fix IS NOT NULL
    AND time_low_fix IS NOT NULL
    AND high_fix IS NOT NULL
    AND low_fix IS NOT NULL
    AND time_open <= time_close
    AND time_open <= time_high_fix AND time_high_fix <= time_close
    AND time_open <= time_low_fix  AND time_low_fix  <= time_close
    AND high_fix >= low_fix
    AND high_fix >= GREATEST(open, close, low_fix)
    AND low_fix  <= LEAST(open, close, high_fix)
  ON CONFLICT (id, venue_id, tf, bar_seq, "timestamp") DO UPDATE SET
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
    is_partial_start = EXCLUDED.is_partial_start,
    is_partial_end   = EXCLUDED.is_partial_end,
    is_missing_days  = EXCLUDED.is_missing_days,
    tf_days = EXCLUDED.tf_days,
    pos_in_bar = EXCLUDED.pos_in_bar,
    count_days = EXCLUDED.count_days,
    count_days_remaining = EXCLUDED.count_days_remaining,
    count_missing_days = EXCLUDED.count_missing_days,
    count_missing_days_start = EXCLUDED.count_missing_days_start,
    count_missing_days_end = EXCLUDED.count_missing_days_end,
    count_missing_days_interior = EXCLUDED.count_missing_days_interior,
    src_name = EXCLUDED.src_name,
    src_load_ts = EXCLUDED.src_load_ts,
    src_file = EXCLUDED.src_file,
    repaired_timehigh = EXCLUDED.repaired_timehigh,
    repaired_timelow  = EXCLUDED.repaired_timelow,
    repaired_high = EXCLUDED.repaired_high,
    repaired_low = EXCLUDED.repaired_low
  RETURNING repaired_timehigh, repaired_timelow, "timestamp"
)
SELECT
  count(*)::int AS upserted,
  coalesce(sum((repaired_timehigh)::int), 0)::int AS repaired_timehigh,
  coalesce(sum((repaired_timelow)::int), 0)::int  AS repaired_timelow,
  max("timestamp") AS max_src_ts
FROM ins"""

# ---------------------------------------------------------------------------
# TVC CTE template (extracted from refresh_tvc_price_bars_1d.py _build_insert_bars_sql)
# Placeholders: {dst} = destination table, {src} = source table
# Optional: {venue_clause} for filtering by venue (default: empty string)
# Runtime psycopg params (%s): id (src_filtered), id (ranked),
#   last_src_ts x2, time_max x2
# ---------------------------------------------------------------------------
_TVC_CTE_TEMPLATE = """\
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
  ON CONFLICT (id, venue_id, tf, bar_seq, "timestamp") DO UPDATE SET
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
FROM ins"""

# ---------------------------------------------------------------------------
# HL CTE template (extracted from refresh_hl_price_bars_1d.py _build_insert_bars_sql)
# Placeholders: {dst} = destination table
# Source is always: hyperliquid.hl_candles JOIN dim_asset_identifiers
# Runtime psycopg params (%s): id (src_filtered), id (ranked),
#   last_src_ts x2, time_max x2
# ---------------------------------------------------------------------------
_HL_CTE_TEMPLATE = """\
WITH src_filtered AS (
  SELECT DISTINCT ON (dai.id, c.ts)
    dai.id,
    'HYPERLIQUID'::text AS venue,
    2::smallint AS venue_id,
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
  ON CONFLICT (id, venue_id, tf, bar_seq, "timestamp") DO UPDATE SET
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
FROM ins"""


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # A. Insert TVC into dim_venues (venue_id=11)
    #    Must happen BEFORE dim_data_sources creation (FK dependency)
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        INSERT INTO public.dim_venues (venue_id, venue, description)
        VALUES (11, 'TVC', 'TradingView price feed')
        ON CONFLICT (venue_id) DO NOTHING
    """)
    )

    # ------------------------------------------------------------------
    # B. Create dim_data_sources table
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.dim_data_sources (
            source_key        TEXT PRIMARY KEY,
            source_name       TEXT NOT NULL UNIQUE,
            source_table      TEXT NOT NULL,
            venue_id          SMALLINT NOT NULL REFERENCES public.dim_venues(venue_id),
            default_venue     TEXT NOT NULL,
            ohlc_repair       BOOLEAN NOT NULL DEFAULT FALSE,
            has_market_cap    BOOLEAN NOT NULL DEFAULT FALSE,
            has_timehigh      BOOLEAN NOT NULL DEFAULT FALSE,
            id_loader_sql     TEXT,
            src_cte_template  TEXT NOT NULL,
            join_clause       TEXT,
            id_filter_sql     TEXT NOT NULL,
            ts_column         TEXT NOT NULL DEFAULT 'timestamp',
            conflict_columns  TEXT NOT NULL,
            src_name_label    TEXT NOT NULL,
            description       TEXT
        )
    """)
    )

    # ------------------------------------------------------------------
    # B1. Seed CMC row
    # Uses bindparams() to pass large TEXT values safely
    # ------------------------------------------------------------------
    conn.execute(
        text(
            "INSERT INTO public.dim_data_sources ("
            "    source_key, source_name, source_table, venue_id, default_venue,"
            "    ohlc_repair, has_market_cap, has_timehigh,"
            "    id_loader_sql, src_cte_template, join_clause,"
            "    id_filter_sql, ts_column, conflict_columns, src_name_label, description"
            ") VALUES ("
            "    'cmc', 'CoinMarketCap', 'public.cmc_price_histories7', 1, 'CMC_AGG',"
            "    TRUE, TRUE, TRUE,"
            "    'SELECT DISTINCT id FROM public.cmc_price_histories7',"
            "    :cte,"
            "    NULL,"
            "    'id = ANY(%(ids)s)', 'timestamp', 'id,venue_id,tf,bar_seq,timestamp',"
            "    'CoinMarketCap', 'CMC daily price histories with OHLC repair and market cap'"
            ") ON CONFLICT (source_key) DO NOTHING"
        ).bindparams(cte=_CMC_CTE_TEMPLATE)
    )

    # ------------------------------------------------------------------
    # B2. Seed TVC row
    # ------------------------------------------------------------------
    conn.execute(
        text(
            "INSERT INTO public.dim_data_sources ("
            "    source_key, source_name, source_table, venue_id, default_venue,"
            "    ohlc_repair, has_market_cap, has_timehigh,"
            "    id_loader_sql, src_cte_template, join_clause,"
            "    id_filter_sql, ts_column, conflict_columns, src_name_label, description"
            ") VALUES ("
            "    'tvc', 'TradingView', 'public.tvc_price_histories', 11, 'TVC',"
            "    FALSE, FALSE, FALSE,"
            "    'SELECT DISTINCT id FROM public.tvc_price_histories',"
            "    :cte,"
            "    NULL,"
            "    'id = ANY(%(ids)s)', 'ts', 'id,venue_id,tf,bar_seq,timestamp',"
            "    'TradingView', 'TradingView daily OHLC data -- no repair needed, synthesized time_high/low'"
            ") ON CONFLICT (source_key) DO NOTHING"
        ).bindparams(cte=_TVC_CTE_TEMPLATE)
    )

    # ------------------------------------------------------------------
    # B3. Seed HL row
    # Source join: hyperliquid.hl_candles JOIN dim_asset_identifiers
    # ------------------------------------------------------------------
    hl_id_loader = (
        "SELECT DISTINCT dai.id "
        "FROM dim_asset_identifiers dai "
        "JOIN hyperliquid.hl_candles c "
        "  ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id "
        "WHERE c.interval = '1d' "
        "ORDER BY dai.id"
    )
    hl_join_clause = (
        "JOIN dim_asset_identifiers dai "
        "  ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id"
    )
    conn.execute(
        text(
            "INSERT INTO public.dim_data_sources ("
            "    source_key, source_name, source_table, venue_id, default_venue,"
            "    ohlc_repair, has_market_cap, has_timehigh,"
            "    id_loader_sql, src_cte_template, join_clause,"
            "    id_filter_sql, ts_column, conflict_columns, src_name_label, description"
            ") VALUES ("
            "    'hl', 'Hyperliquid', 'hyperliquid.hl_candles', 2, 'HYPERLIQUID',"
            "    FALSE, FALSE, FALSE,"
            "    :id_loader,"
            "    :cte,"
            "    :join_clause,"
            "    'dai.id = ANY(%(ids)s)', 'ts', 'id,venue_id,tf,bar_seq,timestamp',"
            "    'Hyperliquid', 'Hyperliquid perpetuals daily candles via hl_candles + dim_asset_identifiers mapping'"
            ") ON CONFLICT (source_key) DO NOTHING"
        ).bindparams(
            cte=_HL_CTE_TEMPLATE,
            id_loader=hl_id_loader,
            join_clause=hl_join_clause,
        )
    )

    # ------------------------------------------------------------------
    # C. Add alignment_source CHECK constraints to all 6 _u tables
    #
    # Pre-check note: Query each table for unexpected alignment_source values
    # before adding the constraint. For ema_multi_tf_u specifically, the
    # research notes mention potential 'unknown' default values. The migration
    # includes a remediation UPDATE before adding the constraint.
    #
    # The 5 valid values are:
    #   multi_tf, multi_tf_cal_us, multi_tf_cal_iso,
    #   multi_tf_cal_anchor_us, multi_tf_cal_anchor_iso
    # ------------------------------------------------------------------

    # C1. Remediation: fix any 'unknown' alignment_source values in ema_multi_tf_u
    # (EMA state manager historically used 'unknown' as a default fallback)
    conn.execute(
        text(f"""
        UPDATE public.ema_multi_tf_u
        SET alignment_source = 'multi_tf'
        WHERE alignment_source NOT IN ({_IN_LIST})
    """)
    )

    # C2. Remediation: fix any unexpected values in remaining _u tables
    for tbl in [
        "price_bars_multi_tf_u",
        "ama_multi_tf_u",
        "returns_bars_multi_tf_u",
        "returns_ema_multi_tf_u",
        "returns_ama_multi_tf_u",
    ]:
        conn.execute(
            text(f"""
            UPDATE public.{tbl}
            SET alignment_source = 'multi_tf'
            WHERE alignment_source NOT IN ({_IN_LIST})
        """)
        )

    # C3. Add CHECK constraints
    conn.execute(
        text(f"""
        ALTER TABLE public.price_bars_multi_tf_u
        ADD CONSTRAINT chk_price_bars_u_alignment_source
        CHECK (alignment_source IN ({_IN_LIST}))
    """)
    )

    conn.execute(
        text(f"""
        ALTER TABLE public.ema_multi_tf_u
        ADD CONSTRAINT chk_ema_u_alignment_source
        CHECK (alignment_source IN ({_IN_LIST}))
    """)
    )

    conn.execute(
        text(f"""
        ALTER TABLE public.ama_multi_tf_u
        ADD CONSTRAINT chk_ama_u_alignment_source
        CHECK (alignment_source IN ({_IN_LIST}))
    """)
    )

    conn.execute(
        text(f"""
        ALTER TABLE public.returns_bars_multi_tf_u
        ADD CONSTRAINT chk_returns_bars_u_alignment_source
        CHECK (alignment_source IN ({_IN_LIST}))
    """)
    )

    conn.execute(
        text(f"""
        ALTER TABLE public.returns_ema_multi_tf_u
        ADD CONSTRAINT chk_returns_ema_u_alignment_source
        CHECK (alignment_source IN ({_IN_LIST}))
    """)
    )

    conn.execute(
        text(f"""
        ALTER TABLE public.returns_ama_multi_tf_u
        ADD CONSTRAINT chk_returns_ama_u_alignment_source
        CHECK (alignment_source IN ({_IN_LIST}))
    """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # C. Drop CHECK constraints (reverse order)
    for tbl, constraint in [
        ("returns_ama_multi_tf_u", "chk_returns_ama_u_alignment_source"),
        ("returns_ema_multi_tf_u", "chk_returns_ema_u_alignment_source"),
        ("returns_bars_multi_tf_u", "chk_returns_bars_u_alignment_source"),
        ("ama_multi_tf_u", "chk_ama_u_alignment_source"),
        ("ema_multi_tf_u", "chk_ema_u_alignment_source"),
        ("price_bars_multi_tf_u", "chk_price_bars_u_alignment_source"),
    ]:
        conn.execute(
            text(f"ALTER TABLE public.{tbl} DROP CONSTRAINT IF EXISTS {constraint}")
        )

    # B. Drop dim_data_sources table
    conn.execute(text("DROP TABLE IF EXISTS public.dim_data_sources"))

    # A. Remove TVC from dim_venues
    conn.execute(text("DELETE FROM public.dim_venues WHERE venue_id = 11"))
