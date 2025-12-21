-- =============================================================================
-- File: sql/ddl/price_bars__cmc_price_bars_multi_tf.sql
-- Purpose:
--   - Define cmc_price_bars_multi_tf (tf-day bars)
--   - Provide a QA suite for invariants (continuity, no partial bars, OHLC correctness)
--
-- IMPORTANT:
--   If you are using Alembic migrations, treat this as reference or “manual DDL”,
--   not necessarily something you run repeatedly in prod.
-- =============================================================================

-- =============================================================================
-- Table: cmc_price_bars_multi_tf
--
-- Bars are defined purely by tf_days (e.g., 2D, 7D, 30D...), with:
--   * no calendar alignment
--   * no partial bars (every bar contains exactly tf_days daily rows)
--   * origin anchored to each id's first available daily timestamp
--
-- Each row = one completed bar for (id, tf).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf (
    id            INTEGER NOT NULL,
    tf            TEXT    NOT NULL,     -- logical label (e.g., '2D', '7D', '30D', '1W' if you still want)
    tf_days       INTEGER NOT NULL,     -- bar length in days; bars are exactly tf_days daily rows

    -- Bar identity (sequence from the first full bar)
    bar_seq       INTEGER NOT NULL,     -- 1,2,3... per (id, tf); only full bars included

    -- Time boundaries of the bar (daily-close timestamps)
    time_open     TIMESTAMPTZ NOT NULL,
    time_close    TIMESTAMPTZ NOT NULL,

    -- Time extrema within the bar (timestamps where H/L occurred)
    time_high     TIMESTAMPTZ,
    time_low      TIMESTAMPTZ,

    -- OHLCV + market cap
    open          DOUBLE PRECISION NOT NULL,
    high          DOUBLE PRECISION NOT NULL,
    low           DOUBLE PRECISION NOT NULL,
    close         DOUBLE PRECISION NOT NULL,
    volume        DOUBLE PRECISION,
    market_cap    DOUBLE PRECISION,

    -- audit
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_cmc_price_bars_multi_tf
        PRIMARY KEY (id, tf, bar_seq),

    CONSTRAINT uq_cmc_price_bars_multi_tf_timeclose
        UNIQUE (id, tf, time_close),

    CONSTRAINT ck_cmc_price_bars_multi_tf_tf_days
        CHECK (tf_days > 0),

    CONSTRAINT ck_cmc_price_bars_multi_tf_time_order
        CHECK (time_open < time_close),

    CONSTRAINT ck_cmc_price_bars_multi_tf_ohlc
        CHECK (high >= GREATEST(open, close) AND low <= LEAST(open, close) AND high >= low)
);

-- Helpful indexes for typical queries
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_id_tf_timeclose
    ON public.cmc_price_bars_multi_tf (id, tf, time_close);

CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_tf_timeclose
    ON public.cmc_price_bars_multi_tf (tf, time_close);

CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_id_tf_barseq
    ON public.cmc_price_bars_multi_tf (id, tf, bar_seq);

-- =============================================================================
-- QA / invariants
-- =============================================================================

-- Quick sample
SELECT *
FROM public.cmc_price_bars_multi_tf
WHERE id = 1 AND tf_days = 2
LIMIT 10;

-- Source sanity: early daily rows
SELECT *
FROM public.cmc_price_histories7
WHERE id=1
ORDER BY "timestamp"
LIMIT 20;

-- DANGEROUS: full reset (only if rebuilding)
-- TRUNCATE TABLE public.cmc_price_bars_multi_tf;

-- -----------------------------------------------------------------------------
-- A) Schema sanity: column types
-- -----------------------------------------------------------------------------
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name='cmc_price_bars_multi_tf'
ORDER BY ordinal_position;

-- -----------------------------------------------------------------------------
-- B) Key sanity: constraints include (id, tf, bar_seq)
-- -----------------------------------------------------------------------------
SELECT
  tc.constraint_name,
  tc.constraint_type,
  kcu.column_name,
  kcu.ordinal_position
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
WHERE tc.table_schema='public'
  AND tc.table_name='cmc_price_bars_multi_tf'
ORDER BY tc.constraint_name, kcu.ordinal_position;

-- -----------------------------------------------------------------------------
-- 1) Continuity invariant (your core requirement)
--    time_open must equal lag(time_close) + 1ms per (id, tf)
-- -----------------------------------------------------------------------------
WITH x AS (
  SELECT
    id, tf, bar_seq, time_open, time_close,
    lag(time_close) OVER (PARTITION BY id, tf ORDER BY bar_seq) AS prev_close
  FROM public.cmc_price_bars_multi_tf
  WHERE id = 1 AND tf = '12M_CAL'
)
SELECT
  id, tf, bar_seq,
  time_open,
  time_close,
  prev_close,
  (time_open - (prev_close + interval '1 millisecond')) AS open_minus_expected
FROM x
WHERE bar_seq > 1
  AND time_open <> (prev_close + interval '1 millisecond')
ORDER BY bar_seq;

-- -----------------------------------------------------------------------------
-- 2) No partial bars (exactly tf_days daily rows per bar)
--    Example shown for 360-day bars (12M_CAL assumed tf_days=360).
-- -----------------------------------------------------------------------------
WITH d AS (
  SELECT
    id,
    "timestamp" AS ts,
    row_number() OVER (PARTITION BY id ORDER BY "timestamp") AS rn
  FROM public.cmc_price_histories7
  WHERE id = 1
),
d2 AS (
  SELECT
    id, ts,
    ((rn - 1) / 360) + 1 AS bar_seq
  FROM d
),
counts AS (
  SELECT id, bar_seq, count(*) AS n_days
  FROM d2
  GROUP BY id, bar_seq
)
SELECT *
FROM counts
WHERE n_days <> 360
ORDER BY bar_seq;

-- Confirm bars table does NOT contain remainder bar beyond last full bucket:
WITH d AS (
  SELECT
    id,
    row_number() OVER (PARTITION BY id ORDER BY "timestamp") AS rn
  FROM public.cmc_price_histories7
  WHERE id = 1
),
last_full AS (
  SELECT floor((count(*)::numeric) / 360) AS n_full
  FROM d
)
SELECT *
FROM public.cmc_price_bars_multi_tf b, last_full lf
WHERE b.id = 1 AND b.tf='12M_CAL'
  AND b.bar_seq > lf.n_full;

-- -----------------------------------------------------------------------------
-- 3) Bar bounds match the daily bucket (close = last daily close)
-- -----------------------------------------------------------------------------
WITH d AS (
  SELECT
    id,
    "timestamp" AS ts,
    row_number() OVER (PARTITION BY id ORDER BY "timestamp") AS rn
  FROM public.cmc_price_histories7
  WHERE id = 1
),
d2 AS (
  SELECT
    id, ts,
    ((rn - 1) / 360) + 1 AS bar_seq
  FROM d
),
expected AS (
  SELECT id, bar_seq, max(ts) AS expected_time_close
  FROM d2
  GROUP BY id, bar_seq
),
bars AS (
  SELECT id, tf, bar_seq, time_close
  FROM public.cmc_price_bars_multi_tf
  WHERE id = 1 AND tf='12M_CAL'
)
SELECT
  b.bar_seq,
  b.time_close,
  e.expected_time_close,
  (b.time_close = e.expected_time_close) AS matches
FROM bars b
JOIN expected e USING (id, bar_seq)
WHERE b.time_close <> e.expected_time_close
ORDER BY b.bar_seq;

-- -----------------------------------------------------------------------------
-- 4) Open price = first daily open in the bucket
-- -----------------------------------------------------------------------------
WITH d AS (
  SELECT
    id,
    "timestamp" AS ts,
    open,
    row_number() OVER (PARTITION BY id ORDER BY "timestamp") AS rn
  FROM public.cmc_price_histories7
  WHERE id = 1
),
d2 AS (
  SELECT
    id, ts, open,
    ((rn - 1) / 360) + 1 AS bar_seq,
    rn
  FROM d
),
expected AS (
  SELECT DISTINCT ON (id, bar_seq)
    id, bar_seq, open AS expected_open
  FROM d2
  ORDER BY id, bar_seq, rn
),
bars AS (
  SELECT id, tf, bar_seq, open AS bar_open
  FROM public.cmc_price_bars_multi_tf
  WHERE id=1 AND tf='12M_CAL'
)
SELECT
  b.bar_seq, b.bar_open, e.expected_open
FROM bars b
JOIN expected e USING (id, bar_seq)
WHERE b.bar_open IS DISTINCT FROM e.expected_open
ORDER BY b.bar_seq;

-- -----------------------------------------------------------------------------
-- 5) Close price = last daily close in the bucket
-- -----------------------------------------------------------------------------
WITH d AS (
  SELECT
    id,
    "timestamp" AS ts,
    close,
    row_number() OVER (PARTITION BY id ORDER BY "timestamp") AS rn
  FROM public.cmc_price_histories7
  WHERE id = 1
),
d2 AS (
  SELECT
    id, ts, close,
    ((rn - 1) / 360) + 1 AS bar_seq,
    rn
  FROM d
),
expected AS (
  SELECT DISTINCT ON (id, bar_seq)
    id, bar_seq, close AS expected_close
  FROM d2
  ORDER BY id, bar_seq, rn DESC
),
bars AS (
  SELECT id, tf, bar_seq, close AS bar_close
  FROM public.cmc_price_bars_multi_tf
  WHERE id=1 AND tf='12M_CAL'
)
SELECT
  b.bar_seq, b.bar_close, e.expected_close
FROM bars b
JOIN expected e USING (id, bar_seq)
WHERE b.bar_close IS DISTINCT FROM e.expected_close
ORDER BY b.bar_seq;

-- -----------------------------------------------------------------------------
-- 6) High/low + timestamps consistency
-- -----------------------------------------------------------------------------
WITH d AS (
  SELECT
    id,
    "timestamp" AS ts,
    high, timehigh,
    low,  timelow,
    row_number() OVER (PARTITION BY id ORDER BY "timestamp") AS rn
  FROM public.cmc_price_histories7
  WHERE id = 1
),
d2 AS (
  SELECT *,
    ((rn - 1) / 360) + 1 AS bar_seq
  FROM d
),
mx AS (
  SELECT id, bar_seq, max(high) AS max_high, min(low) AS min_low
  FROM d2
  GROUP BY id, bar_seq
),
pick_high AS (
  SELECT DISTINCT ON (id, bar_seq)
    d2.id, d2.bar_seq, d2.timehigh AS expected_time_high
  FROM d2
  JOIN mx ON mx.id=d2.id AND mx.bar_seq=d2.bar_seq AND d2.high=mx.max_high
  ORDER BY d2.id, d2.bar_seq, d2.ts
),
pick_low AS (
  SELECT DISTINCT ON (id, bar_seq)
    d2.id, d2.bar_seq, d2.timelow AS expected_time_low
  FROM d2
  JOIN mx ON mx.id=d2.id AND mx.bar_seq=d2.bar_seq AND d2.low=mx.min_low
  ORDER BY d2.id, d2.bar_seq, d2.ts
),
bars AS (
  SELECT id, tf, bar_seq, high, low, time_high, time_low
  FROM public.cmc_price_bars_multi_tf
  WHERE id=1 AND tf='12M_CAL'
)
SELECT
  b.bar_seq,
  b.high, mx.max_high,
  b.low,  mx.min_low,
  b.time_high, ph.expected_time_high,
  b.time_low,  pl.expected_time_low
FROM bars b
JOIN mx USING (id, bar_seq)
JOIN pick_high ph USING (id, bar_seq)
JOIN pick_low  pl USING (id, bar_seq)
WHERE b.high <> mx.max_high
   OR b.low  <> mx.min_low
   OR b.time_high <> ph.expected_time_high
   OR b.time_low  <> pl.expected_time_low
ORDER BY b.bar_seq;

-- -----------------------------------------------------------------------------
-- 7) Duplication smoke test
-- -----------------------------------------------------------------------------
SELECT id, tf, bar_seq, count(*) AS n
FROM public.cmc_price_bars_multi_tf
GROUP BY id, tf, bar_seq
HAVING count(*) > 1
ORDER BY n DESC, id, tf, bar_seq
LIMIT 50;

-- -----------------------------------------------------------------------------
-- 8) Coverage sanity: bar_seq starts at 1 and is dense
-- -----------------------------------------------------------------------------
WITH s AS (
  SELECT
    id, tf,
    min(bar_seq) AS min_seq,
    max(bar_seq) AS max_seq,
    count(*)      AS n_bars
  FROM public.cmc_price_bars_multi_tf
  WHERE id=1 AND tf='12M_CAL'
  GROUP BY id, tf
)
SELECT *,
  (min_seq = 1) AS starts_at_1,
  (n_bars = max_seq) AS no_gaps_assuming_dense
FROM s;

-- -----------------------------------------------------------------------------
-- Timezone debug helpers (optional)
-- -----------------------------------------------------------------------------
SELECT
  id, tf, bar_seq,
  time_open,
  time_close,
  (time_open  AT TIME ZONE 'UTC')               AS time_open_utc,
  (time_close AT TIME ZONE 'UTC')              AS time_close_utc,
  (time_open  AT TIME ZONE 'America/New_York')  AS time_open_ny,
  (time_close AT TIME ZONE 'America/New_York')  AS time_close_ny
FROM public.cmc_price_bars_multi_tf
WHERE id = 1 AND tf = '12M_CAL'
ORDER BY bar_seq;
