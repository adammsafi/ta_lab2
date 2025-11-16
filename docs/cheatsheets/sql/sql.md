
#docs/cheatsheets/sql.md

This file organizes and documents the main SQL queries you’re using to:
Example starter:

```markdown
# SQL Cheatsheet (cmc_price_histories7)

## Inspect table

```sql
SELECT *
FROM cmc_price_histories7
ORDER BY timeopen DESC
LIMIT 50;
```

```markdown
# Count rows per id

```
```sql
SELECT id, COUNT(*) AS n_rows
FROM cmc_price_histories7
GROUP BY id
ORDER BY n_rows DESC;

```
```sql
DELETE FROM cmc_price_histories7 a
USING cmc_price_histories7 b
WHERE a.ctid < b.ctid
  AND a.id = b.id
  AND a.timeopen = b.timeopen;


# CMC EMA / Price SQL Reference


- Inspect **daily EMAs**
- Join **prices + EMAs** on the daily grid
- Work with **multi-timeframe EMAs** (including `roll`, `d1`, `d2`, `d1_roll`, `d2_roll`)
- Create reusable **views** for charting and analysis
- Run **diagnostic** and **schema** checks

You can copy-paste individual queries or whole sections directly into pgAdmin.

---

## 1. Basic sanity checks

### 1.1 Inspect daily EMAs for a single asset

Purpose:  
Quickly check the raw contents of `cmc_ema_daily` for a given `id`. Useful to verify EMA values, periods, and timestamps before doing any joins.

```sql
SELECT *
FROM cmc_ema_daily
WHERE id = 1
ORDER BY ts DESC;
```

---

### 1.2 Inspect raw price history for a single asset

Purpose:  
Look at the daily OHLCV + timestamp for a given asset in `cmc_price_histories7`. This is your “ground truth” bar data.

```sql
SELECT *
FROM cmc_price_histories7
WHERE id = 1
ORDER BY timestamp DESC;
```

If you need oldest → newest instead:

```sql
SELECT *
FROM cmc_price_histories7
WHERE id = 1
ORDER BY timestamp ASC;
```

---

### 1.3 Join daily EMAs to daily prices (simple version)

Purpose:  
Join `cmc_ema_daily` to `cmc_price_histories7` on the **daily bar close** so you can inspect how EMA overlays on top of price for a single asset.

```sql
SELECT
    e.id,
    e.tf_days,
    e.ts          AS ema_ts,      -- ts from cmc_ema_daily (aligned to timeclose)
    p.timeclose   AS bar_ts,      -- bar close time from price table
    p.close,
    p.volume,
    p.marketcap,                  -- adjust if your column name differs
    e.period,
    e.ema
FROM cmc_ema_daily        AS e
JOIN cmc_price_histories7 AS p
  ON  e.id = p.id
  AND e.ts = p.timeclose          -- exact 1:1 match on bar close
WHERE e.id = 1
ORDER BY
    bar_ts DESC,
    e.period;
```

---

## 2. Unified EMA view: `all_emas`

This view combines:

- **Daily EMAs** from `cmc_ema_daily`
- **Multi-timeframe EMAs** from `cmc_ema_multi_tf`

It also standardizes slope fields:

- `d1`, `d2` → **rolling** per-bar diffs (daily: `d1/d2`, multi-TF: `d1_roll/d2_roll`)
- `d1_close`, `d2_close`, `roll` → **closing-only** diffs & flag (only non-NULL for multi-TF)

### 2.1 Create or update the view `all_emas`

Run this once (and re-run after schema changes):

```sql
CREATE OR REPLACE VIEW all_emas AS
SELECT
    -- Daily EMA rows
    d.id,
    d.ts,
    '1D'::text          AS tf,      -- label for daily timeframe
    1::int              AS tf_days, -- daily = 1 "day unit"
    d.period,
    d.ema,

    -- Unified "rolling" slopes for this EMA series
    d.d1                AS d1,
    d.d2                AS d2,

    -- Closing-only slopes (not applicable for pure daily EMA)
    NULL::double precision AS d1_close,
    NULL::double precision AS d2_close,
    NULL::boolean          AS roll
FROM cmc_ema_daily AS d

UNION ALL

SELECT
    -- Multi-timeframe EMA rows (on the same daily grid)
    m.id,
    m.ts,
    m.tf,
    m.tf_days,
    m.period,
    m.ema,

    -- Unified "rolling" slopes → use d1_roll/d2_roll
    m.d1_roll           AS d1,
    m.d2_roll           AS d2,

    -- Also expose closing-only slopes & roll flag
    m.d1                AS d1_close,
    m.d2                AS d2_close,
    m.roll
FROM cmc_ema_multi_tf AS m;
```

---

### 2.2 Join prices with `all_emas` (full EMA + slope context)

Purpose:  
Join **every daily bar** in `cmc_price_histories7` to **all** EMAs (daily + multi-TF) with slope fields, so you can inspect price plus EMA families on a single grid.

```sql
SELECT
    p.id,
    p.timeclose     AS bar_ts,     -- every daily bar
    p.close,
    p.volume,
    p.marketcap,

    -- EMA side (may be NULL when not enough history yet)
    ae.tf,
    ae.tf_days,
    ae.ts           AS ema_ts,     -- matches bar_ts when present
    ae.period,
    ae.ema,

    -- Unified rolling slopes
    ae.d1,
    ae.d2,

    -- Multi-TF closing-only slopes & roll (NULL for daily tf)
    ae.d1_close,
    ae.d2_close,
    ae.roll
FROM cmc_price_histories7 AS p
LEFT JOIN all_emas AS ae
  ON  ae.id = p.id
  AND ae.ts = p.timeclose          -- daily grid alignment
WHERE p.id = 1
ORDER BY
    bar_ts DESC,
    ae.tf_days DESC NULLS LAST,
    ae.period DESC NULLS LAST;
```

Notes:

- `LEFT JOIN` ensures **every daily price bar** is present, with EMAs attached when available.
- Sorting by `tf_days DESC, period DESC` gives you “higher TF first, then larger period first” per bar.

---

## 3. Multi-timeframe EMA diagnostics

These queries help inspect and manage the `cmc_ema_multi_tf` table.

### 3.1 Inspect multi-timeframe EMAs for one asset

Purpose:  
See all TFs and periods for a given `id`, with latest timestamps first and sorted by TF size and period size.

```sql
SELECT *
FROM cmc_ema_multi_tf
WHERE id = 1
ORDER BY ts DESC, tf_days DESC, period DESC;
```

### 3.2 Look at a specific TF/period (e.g., weekly 21-period EMA)

Purpose:  
Zoom in on one multi-TF series and verify `roll` and slopes (`d1`, `d2`, `d1_roll`, `d2_roll`).

```sql
SELECT *
FROM cmc_ema_multi_tf
WHERE id = 1
  AND tf = '1W'
  AND period = 21
ORDER BY ts DESC
LIMIT 50;
```

---

### 3.3 Check `roll` distribution (true closes vs rolling bars)

Purpose:  
Confirm both rolling rows and true higher-TF closes exist.

```sql
SELECT DISTINCT roll
FROM cmc_ema_multi_tf;
```

```sql
SELECT roll, COUNT(*) 
FROM cmc_ema_multi_tf
GROUP BY roll;
```

- `roll = FALSE` → true higher-TF close
- `roll = TRUE`  → intra-bar / rolling value

---

### 3.4 Truncate multi-timeframe EMA table (rebuild from scratch)

Purpose:  
Clear all data before recomputing multi-TF EMAs with a new algorithm.

```sql
TRUNCATE TABLE public.cmc_ema_multi_tf;
```

> **Warning:** This removes all rows from `cmc_ema_multi_tf`. Only run when you intend to fully regenerate it from your Python pipeline.

---

### 3.5 Add `roll`, `d1_roll`, and `d2_roll` columns (one-time schema update)

Purpose:  
If not already present, extend `cmc_ema_multi_tf` to support rolling vs closing-only slope metrics.

```sql
ALTER TABLE public.cmc_ema_multi_tf
ADD COLUMN roll      boolean,
ADD COLUMN d1_roll   double precision,
ADD COLUMN d2_roll   double precision;
```

Only needed once when updating schema.

---

## 4. Combined price + EMA view: `cmc_price_with_emas` (simple version)

This is an earlier, simplified price+EMA view that only exposes:

- `ema` (no slope fields)
- `tf`, `tf_days`, `period`

Useful if you want a lighter view without slopes.

### 4.1 Create or replace `cmc_price_with_emas`

```sql
CREATE OR REPLACE VIEW cmc_price_with_emas AS
WITH all_emas AS (
    -- Daily EMAs
    SELECT
        d.id,
        '1D'::text AS tf,
        1          AS tf_days,
        d.ts,
        d.period,
        d.ema
    FROM cmc_ema_daily AS d

    UNION ALL

    -- Multi-timeframe EMAs (already on daily grid)
    SELECT
        m.id,
        m.tf,
        m.tf_days,
        m.ts,
        m.period,
        m.ema
    FROM cmc_ema_multi_tf AS m
)
SELECT
    p.id,
    p.timeclose     AS bar_ts,
    p.close,
    p.volume,
    p.marketcap,
    ae.tf,
    ae.tf_days,
    ae.ts           AS ema_ts,
    ae.period,
    ae.ema
FROM cmc_price_histories7 AS p
LEFT JOIN all_emas AS ae
  ON  ae.id = p.id
  AND ae.ts = p.timeclose;
```

### 4.2 Query `cmc_price_with_emas` for a single asset

```sql
SELECT *
FROM cmc_price_with_emas
WHERE id = 1
ORDER BY
    bar_ts DESC,
    tf_days DESC NULLS LAST,
    period  DESC NULLS LAST;
```

---

## 5. Table metadata and max timestamp checks

These queries help confirm schema and data ranges.

### 5.1 Max timestamps in price table

Purpose:  
See the latest `timestamp` and `timeclose` for a given asset (useful for debugging ingestion windows).

```sql
SELECT
  max(timestamp) AS max_timestamp,
  max(timeclose) AS max_timeclose
FROM public.cmc_price_histories7
WHERE id = 1;
```

---

### 5.2 Inspect column names and types

Purpose:  
Verify the schema of your EMA and price tables.

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'cmc_ema_multi_tf'
ORDER BY ordinal_position;
```

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'cmc_price_histories7'
ORDER BY ordinal_position;
```

---

## 6. Exchange selection helper

Purpose:  
Quickly filter `exchange_map` to a known list of exchanges you care about.

```sql
SELECT *
FROM exchange_map
WHERE name IN (
    'Coinbase Exchange',
    'Binance',
    'Kraken',
    'Bitstamp by Robinhood',
    'Bitfinex',
    'Hyperliquid'
);
```

You can swap `IN` for `ILIKE '%pattern%'` when exploring unknown names.

---

## 7. Daily EMA reset (rare, destructive)

If you need to blow away all daily EMAs and recompute from scratch:

```sql
TRUNCATE TABLE public.cmc_ema_daily;
```

> **Warning:** This removes all rows from `cmc_ema_daily`. Only run when you’re certain your recompute pipeline is ready.

---

## 8. Summary of main workflows

**Common workflow (per asset, e.g. `id = 1`):**

1. Inspect raw data  
   - `SELECT * FROM cmc_price_histories7 WHERE id = 1 ORDER BY timestamp DESC;`
2. Inspect daily EMAs  
   - `SELECT * FROM cmc_ema_daily WHERE id = 1 ORDER BY ts DESC;`
3. Inspect multi-TF EMAs  
   - `SELECT * FROM cmc_ema_multi_tf WHERE id = 1 ORDER BY ts DESC, tf_days DESC, period DESC;`
4. Join prices + EMAs (with slopes)  
   - `SELECT ... FROM cmc_price_histories7 p LEFT JOIN all_emas ae ON ae.id = p.id AND ae.ts = p.timeclose WHERE p.id = 1 ...;`

With this markdown file, you’ve got a structured, documented reference for all of your EMA-related SQL.
