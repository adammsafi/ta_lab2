# New Asset Onboarding Guide

**Phase:** 21 - Comprehensive Review
**Answers:** RVWQ-04 - How do I add a new asset?
**Created:** 2026-02-05
**Purpose:** End-to-end checklist for onboarding new cryptocurrency assets

---

## Executive Summary

Adding a new asset to ta_lab2 requires 6 sequential steps: (1) Add asset metadata to dim_assets, (2) Build 1D bars from price_histories7, (3) Build multi-TF bars, (4) Compute EMAs, (5) Validate output, and (6) Verify incremental refresh. Each step depends on the previous step's output. Total time: 10-30 minutes per asset depending on history depth.

**Key insight:** Asset IDs from dim_assets drive all downstream processing. The `id` column is the primary key used across all bar and EMA tables.

---

## Prerequisites

Before starting, verify these conditions are met:

### Data Availability
- [ ] **Asset has CoinMarketCap listing:** CMC ID required for API integration
- [ ] **Asset is liquid enough:** Minimum daily volume threshold (suggested: $100K+ daily volume)
- [ ] **price_histories7 has data:** Raw price history populated from CMC API
  - Verify: `SELECT COUNT(*) FROM public.price_histories7 WHERE id = <cmc_id>;`
  - Should return: Rows covering desired date range

### Infrastructure Ready
- [ ] **Database accessible:** Connection to PostgreSQL database with ta_lab2 schema
- [ ] **Scripts executable:** Python environment with ta_lab2 package installed
- [ ] **dim_timeframe populated:** Timeframe definitions exist for bar builders
  - Verify: `SELECT COUNT(*) FROM public.dim_timeframe;`
  - Should return: 20+ timeframe rows

### Asset Metadata Known
- [ ] **CoinMarketCap ID (CMC ID):** Numeric identifier from CMC API (e.g., 1 for Bitcoin, 52 for XRP)
- [ ] **Symbol:** Ticker symbol (e.g., "BTC", "ETH", "XRP")
- [ ] **Name:** Full asset name (e.g., "Bitcoin", "Ethereum", "Ripple")

---

## Step 1: Add to dim_assets

### Purpose
Register asset metadata in dimension table. This creates the internal asset ID used by all downstream processes.

### Action
```sql
-- Insert into dim_assets (if not already present)
INSERT INTO public.dim_assets (id, cmc_id, symbol, name)
VALUES (
    <internal_id>,      -- Internal ID (sequential, e.g., 1, 52, 1027)
    <cmc_id>,           -- CoinMarketCap ID (from CMC API)
    '<symbol>',         -- Ticker symbol (e.g., 'BTC', 'ETH')
    '<name>'            -- Full name (e.g., 'Bitcoin', 'Ethereum')
)
ON CONFLICT (id) DO NOTHING;
```

**Example:**
```sql
-- Add Bitcoin (if not present)
INSERT INTO public.dim_assets (id, cmc_id, symbol, name)
VALUES (1, 1, 'BTC', 'Bitcoin')
ON CONFLICT (id) DO NOTHING;

-- Add Ethereum (if not present)
INSERT INTO public.dim_assets (id, cmc_id, symbol, name)
VALUES (52, 1027, 'ETH', 'Ethereum')
ON CONFLICT (id) DO NOTHING;
```

### Verification Queries
```sql
-- Verify asset exists in dim_assets
SELECT id, cmc_id, symbol, name
FROM public.dim_assets
WHERE id = <internal_id>;

-- Check for duplicates (should return 0 rows)
SELECT cmc_id, COUNT(*)
FROM public.dim_assets
GROUP BY cmc_id
HAVING COUNT(*) > 1;

-- Verify price_histories7 has data for this CMC ID
SELECT
    id,
    MIN(timestamp) as first_date,
    MAX(timestamp) as last_date,
    COUNT(*) as row_count
FROM public.price_histories7
WHERE id = <cmc_id>  -- Note: price_histories7 uses cmc_id, not internal id
GROUP BY id;
```

### Common Issues
**Issue:** Duplicate cmc_id in dim_assets
**Solution:** Check if asset already exists with different internal id. Use existing id instead of creating duplicate.

**Issue:** No data in price_histories7 for cmc_id
**Solution:** Verify CMC ID is correct. Run data ingestion script to populate price_histories7 first.

---

## Step 2: Build 1D Bars

### Purpose
Create canonical daily bars from raw price_histories7 data. These bars have OHLC validation and quality flags.

### Script
`src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py`

### Command
```bash
# Incremental build for single asset (recommended for new assets)
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py \
    --ids <internal_id> \
    --keep-rejects \
    --fail-on-rejects

# Full rebuild (if asset already has bars and needs clean slate)
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py \
    --ids <internal_id> \
    --rebuild \
    --keep-rejects \
    --fail-on-rejects
```

**Example:**
```bash
# Build 1D bars for Bitcoin (id=1)
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py \
    --ids 1 \
    --keep-rejects
```

### What Happens
1. **Load state:** Query `cmc_price_bars_1d_state` for `last_src_ts` (script-inventory.md line 244)
2. **Query source:** Load price_histories7 rows WHERE timestamp > last_src_ts - 3 days (script-inventory.md line 283)
3. **Process bars:**
   - Assign tf='1D', bar_seq via dense_rank (script-inventory.md line 282)
   - Calculate OHLC (open=first, high=max, low=min, close=last, volume=sum)
   - Repair time_high/time_low if NULL or out-of-window (script-inventory.md lines 334-365)
4. **Validate OHLC invariants:** (validation-points.md section 1.1)
   - NOT NULL checks on all OHLC/timestamp/volume/market_cap fields
   - `time_open <= time_close`
   - `time_high, time_low in [time_open, time_close]`
   - `high >= low`, `high >= max(open, close)`, `low <= min(open, close)`
5. **Upsert or reject:**
   - Pass validation → Upsert to `cmc_price_bars_1d`
   - Fail validation → Insert to `cmc_price_bars_1d_rejects` with reason (validation-points.md lines 589-604)
6. **Update state:** Write `last_src_ts = max(timestamp)` to state table

### Verification Queries
```sql
-- Check 1D bars created
SELECT
    id,
    COUNT(*) as bar_count,
    MIN(timestamp) as first_bar,
    MAX(timestamp) as last_bar
FROM public.cmc_price_bars_1d
WHERE id = <internal_id>
GROUP BY id;

-- Verify quality flags (should all be FALSE for 1D bars)
SELECT
    is_partial_start,
    is_partial_end,
    is_missing_days,
    COUNT(*) as count
FROM public.cmc_price_bars_1d
WHERE id = <internal_id>
GROUP BY is_partial_start, is_partial_end, is_missing_days;
-- Expected: All FALSE (1D bars are always complete)

-- Check for rejects (should be 0 for clean data)
SELECT reason, COUNT(*)
FROM public.cmc_price_bars_1d_rejects
WHERE id = <internal_id>
GROUP BY reason
ORDER BY COUNT(*) DESC;

-- Verify state table updated
SELECT id, last_src_ts, last_run_ts, last_upserted
FROM public.cmc_price_bars_1d_state
WHERE id = <internal_id>;
```

### Common Issues
**Issue:** High reject rate (>5% of rows)
**Cause:** Data quality issues in price_histories7 (NULL OHLCs, inverted high/low)
**Solution:** Investigate reject reasons via query above. May need to clean source data or adjust validation thresholds.

**Issue:** No rows created but script succeeds
**Cause:** price_histories7 query returns empty (wrong id, date range issue)
**Solution:** Verify price_histories7 has data for this `id` (not cmc_id—mapping may be issue).

---

## Step 3: Build Multi-TF Bars

### Purpose
Create multi-timeframe bar snapshots (7D, 14D, 30D, etc.) from daily price data. Required for multi-TF EMAs.

### Script
Choose ONE variant based on use case:

| Variant | Script | Purpose | When to Use |
|---------|--------|---------|-------------|
| **Standard (tf_day)** | refresh_cmc_price_bars_multi_tf.py | Row-count multi-TF (7D = 7 days rolling) | Default for most assets |
| **Calendar US** | refresh_cmc_price_bars_multi_tf_cal_us.py | US Sunday-start weeks | Monthly/quarterly analysis (US markets) |
| **Calendar ISO** | refresh_cmc_price_bars_multi_tf_cal_iso.py | ISO Monday-start weeks | International markets, ISO compliance |
| **Calendar Anchor US** | refresh_cmc_price_bars_multi_tf_cal_anchor_us.py | Year-anchored US calendar | Fiscal year analysis, year-over-year comparisons |
| **Calendar Anchor ISO** | refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py | Year-anchored ISO calendar | International fiscal year analysis |

**Recommendation for new assets:** Start with standard (tf_day) variant unless specific calendar alignment needed.

### Command (Standard Variant)
```bash
# Incremental build for single asset
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py \
    --ids <internal_id>

# With parallel processing (faster for multiple assets)
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py \
    --ids <internal_id> \
    --num-processes 4
```

**Example:**
```bash
# Build multi-TF bars for Bitcoin (id=1)
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py --ids 1
```

### What Happens
1. **Load timeframes:** Query `dim_timeframe` for alignment_type='tf_day' (script-inventory.md lines 105-148)
   - Returns: 7D, 14D, 21D, 30D, 90D, 365D (canonical timeframes)
2. **Load state:** Query `cmc_price_bars_multi_tf_state` for (id, tf) watermarks (script-inventory.md lines 762-774)
3. **For each (id, tf):**
   - Check backfill: if daily_min_ts < daily_min_seen → DELETE bars, full rebuild (incremental-refresh.md lines 863-895)
   - Check new data: if daily_max_ts > last_time_close → append incremental (incremental-refresh.md lines 911-970)
   - Build snapshots: One row per day per bar (snapshot model)
4. **Validate:**
   - assert_one_row_per_local_day: Unique (id, date) in source data (script-inventory.md line 196)
   - enforce_ohlc_sanity: Clamp OHLC to satisfy invariants (script-inventory.md line 312)
5. **Upsert bars:** Append-only snapshots to `cmc_price_bars_multi_tf`
6. **Update state:** Write daily_min_seen, daily_max_seen, last_bar_seq, last_time_close per (id, tf)

### Verification Queries
```sql
-- Check multi-TF bars created (should see rows for each TF)
SELECT
    tf,
    COUNT(DISTINCT bar_seq) as bar_count,
    COUNT(*) as snapshot_count,
    MIN(time_close) as first_close,
    MAX(time_close) as last_close
FROM public.cmc_price_bars_multi_tf
WHERE id = <internal_id>
GROUP BY tf
ORDER BY tf;

-- Verify quality flags
SELECT
    tf,
    is_partial_start,
    is_partial_end,
    is_missing_days,
    COUNT(*) as count
FROM public.cmc_price_bars_multi_tf
WHERE id = <internal_id>
GROUP BY tf, is_partial_start, is_partial_end, is_missing_days
ORDER BY tf;

-- Check state table (one row per TF)
SELECT id, tf, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close
FROM public.cmc_price_bars_multi_tf_state
WHERE id = <internal_id>
ORDER BY tf;

-- Validate OHLC relationships (should return 0 violations)
SELECT COUNT(*)
FROM public.cmc_price_bars_multi_tf
WHERE id = <internal_id>
  AND (high < low OR high < GREATEST(open, close) OR low > LEAST(open, close));
-- Expected: 0 (OHLC sanity enforced)
```

### Common Issues
**Issue:** No multi-TF bars created but 1D bars exist
**Cause:** dim_timeframe query returns empty (alignment_type='tf_day' filter too restrictive)
**Solution:** Verify dim_timeframe has canonical TFs: `SELECT tf FROM dim_timeframe WHERE alignment_type='tf_day' AND is_canonical=TRUE;`

**Issue:** is_missing_days=TRUE for many bars
**Cause:** Gaps in price_histories7 data (weekends, holidays, data outages)
**Solution:** This is informational, not an error. Downstream systems can filter bars with gaps if needed.

---

## Step 4: Compute EMAs

### Purpose
Calculate Exponential Moving Averages at various timeframes and periods. EMAs are core technical indicators for trading strategies.

### Script
Choose EMA variant matching bar variant from Step 3:

| Bar Variant | EMA Script | Output Table |
|-------------|-----------|--------------|
| Standard (tf_day) | refresh_cmc_ema_multi_tf_from_bars.py | cmc_ema_multi_tf_u |
| Standard (v2 synthetic) | refresh_cmc_ema_multi_tf_v2.py | cmc_ema_multi_tf_v2 |
| Calendar US | refresh_cmc_ema_multi_tf_cal_from_bars.py --scheme=us | cmc_ema_multi_tf_cal_us |
| Calendar ISO | refresh_cmc_ema_multi_tf_cal_from_bars.py --scheme=iso | cmc_ema_multi_tf_cal_iso |
| Calendar Anchor US | refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py --scheme=us | cmc_ema_multi_tf_cal_anchor_us |
| Calendar Anchor ISO | refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py --scheme=iso | cmc_ema_multi_tf_cal_anchor_iso |

**Recommendation:** Use script matching bar variant from Step 3.

### Command (Standard Variant)
```bash
# Incremental EMA computation for single asset
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py \
    --ids <internal_id>

# With custom periods (default: 6,9,10,12,14,17,20,21,26,30,50,52,77,100,200,252,365)
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py \
    --ids <internal_id> \
    --periods 9,21,50,100,200

# Full refresh (recompute all EMAs from scratch)
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py \
    --ids <internal_id> \
    --full-refresh
```

**Example:**
```bash
# Compute EMAs for Bitcoin (id=1) with standard periods
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py --ids 1
```

### What Happens
1. **Load timeframes:** Query `dim_timeframe` for alignment_type='tf_day', canonical_only=TRUE (script-inventory.md lines 76-82)
2. **Load state:** Query `cmc_ema_multi_tf_state` for (id, tf, period) watermarks (script-inventory.md line 152)
3. **For each (id, tf, period):**
   - Select bars table: Use `cmc_price_bars_1d` for 1D TF, `cmc_price_bars_multi_tf` for others (script-inventory.md lines 87-91)
   - Query bars: WHERE time_close > last_time_close AND is_partial_end = FALSE (incremental-refresh.md lines 296-305)
   - Compute EMA: Use compute_ema function with alpha = 2/(period+1) (ema-variants.md lines 407-424)
4. **Upsert EMAs:** Write to output table (e.g., cmc_ema_multi_tf_u)
5. **Update state:** Write daily_min_seen, daily_max_seen, last_time_close, last_canonical_ts per (id, tf, period)

### Verification Queries
```sql
-- Check EMA rows created (should see combinations of tf × period)
SELECT
    tf,
    period,
    COUNT(*) as row_count,
    MIN(ts) as first_ts,
    MAX(ts) as last_ts
FROM public.cmc_ema_multi_tf_u
WHERE id = <internal_id>
GROUP BY tf, period
ORDER BY tf, period;

-- Count distinct TF × period combinations (should match expectation)
SELECT COUNT(DISTINCT (tf, period))
FROM public.cmc_ema_multi_tf_u
WHERE id = <internal_id>;
-- Expected: (# of TFs) × (# of periods)
-- Example: 7 TFs × 17 periods = 119 combinations

-- Verify EMA values are reasonable (not NaN, within price range)
SELECT
    tf,
    period,
    MIN(ema) as min_ema,
    MAX(ema) as max_ema,
    AVG(ema) as avg_ema,
    COUNT(CASE WHEN ema IS NULL THEN 1 END) as null_count
FROM public.cmc_ema_multi_tf_u
WHERE id = <internal_id>
GROUP BY tf, period
ORDER BY tf, period;
-- Expected: min/max/avg within reasonable range, null_count = 0 for mature bars

-- Check state table (one row per tf × period)
SELECT id, tf, period, last_time_close, last_canonical_ts
FROM public.cmc_ema_multi_tf_state
WHERE id = <internal_id>
ORDER BY tf, period;
```

### Common Issues
**Issue:** EMA rows sparse or missing for some (tf, period) combinations
**Cause:** Not enough complete bars for EMA seeding (requires min_periods bars, default = period)
**Solution:** Expected for short-history assets. EMAs will populate as more bars accumulate.

**Issue:** EMA values are NULL
**Cause:** Bars have is_partial_end=TRUE (incomplete bars filtered out) or insufficient seeding data
**Solution:** Verify bars exist with is_partial_end=FALSE. Check MIN(bar_seq) for tf has at least `period` bars.

---

## Step 5: Validate Output

### Purpose
Cross-check output against known-good asset to confirm correctness and completeness.

### Validation Checklist

#### 5.1 Bar Counts (Compare to Reference Asset)
```sql
-- Query bar counts for reference asset (e.g., Bitcoin id=1)
SELECT
    '1D' as source,
    COUNT(*) as row_count,
    MIN(timestamp) as first_date,
    MAX(timestamp) as last_date
FROM public.cmc_price_bars_1d
WHERE id = 1
UNION ALL
SELECT
    'multi_tf',
    COUNT(*),
    MIN(time_close),
    MAX(time_close)
FROM public.cmc_price_bars_multi_tf
WHERE id = 1;

-- Query bar counts for NEW asset (replace <internal_id>)
SELECT
    '1D' as source,
    COUNT(*) as row_count,
    MIN(timestamp) as first_date,
    MAX(timestamp) as last_date
FROM public.cmc_price_bars_1d
WHERE id = <internal_id>
UNION ALL
SELECT
    'multi_tf',
    COUNT(*),
    MIN(time_close),
    MAX(time_close)
FROM public.cmc_price_bars_multi_tf
WHERE id = <internal_id>;
```

**Expected:** Similar row counts if date ranges overlap. New asset should have proportional row counts based on history length.

#### 5.2 EMA Coverage
```sql
-- Count EMA combinations for new asset
SELECT
    COUNT(DISTINCT tf) as tf_count,
    COUNT(DISTINCT period) as period_count,
    COUNT(DISTINCT (tf, period)) as combination_count
FROM public.cmc_ema_multi_tf_u
WHERE id = <internal_id>;

-- Compare to reference asset (Bitcoin id=1)
SELECT
    COUNT(DISTINCT tf) as tf_count,
    COUNT(DISTINCT period) as period_count,
    COUNT(DISTINCT (tf, period)) as combination_count
FROM public.cmc_ema_multi_tf_u
WHERE id = 1;
```

**Expected:** Same tf_count and period_count. combination_count = tf_count × period_count.

#### 5.3 State Table Completeness
```sql
-- Verify state tables have entries for new asset
SELECT 'bars_1d_state' as table_name, COUNT(*) as row_count
FROM public.cmc_price_bars_1d_state
WHERE id = <internal_id>
UNION ALL
SELECT 'bars_multi_tf_state', COUNT(*)
FROM public.cmc_price_bars_multi_tf_state
WHERE id = <internal_id>
UNION ALL
SELECT 'ema_multi_tf_state', COUNT(*)
FROM public.cmc_ema_multi_tf_state
WHERE id = <internal_id>;
```

**Expected:**
- bars_1d_state: 1 row (single id)
- bars_multi_tf_state: ~7 rows (one per TF)
- ema_multi_tf_state: ~119 rows (7 TFs × 17 periods)

#### 5.4 Quality Flags Distribution
```sql
-- Check quality flag distribution for multi-TF bars
SELECT
    is_partial_start,
    is_partial_end,
    is_missing_days,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as pct
FROM public.cmc_price_bars_multi_tf
WHERE id = <internal_id>
GROUP BY is_partial_start, is_partial_end, is_missing_days
ORDER BY count DESC;
```

**Expected:**
- is_partial_start: 100% FALSE (data-start anchoring)
- is_partial_end: Mix of TRUE (in-progress bars) and FALSE (complete bars)
- is_missing_days: Should be <10% TRUE for clean data

---

## Step 6: Verify Incremental Refresh

### Purpose
Confirm future updates will process incrementally (not rebuild from scratch each time).

### Test Procedure

#### 6.1 Record Current State
```sql
-- Capture current watermarks
SELECT 'bars_1d' as table_name, id, last_src_ts
FROM public.cmc_price_bars_1d_state
WHERE id = <internal_id>
UNION ALL
SELECT 'bars_multi_tf', id, last_time_close
FROM public.cmc_price_bars_multi_tf_state
WHERE id = <internal_id>
LIMIT 1;
```

#### 6.2 Run Incremental Refresh (No New Data Expected)
```bash
# Re-run 1D bar builder (should be no-op or minimal processing)
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py --ids <internal_id>

# Re-run multi-TF bar builder
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py --ids <internal_id>

# Re-run EMA computation
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py --ids <internal_id>
```

#### 6.3 Verify State Updated, Minimal New Rows
```sql
-- Check state tables updated (updated_at should be recent)
SELECT 'bars_1d' as table_name, id, last_src_ts, last_run_ts
FROM public.cmc_price_bars_1d_state
WHERE id = <internal_id>
UNION ALL
SELECT 'bars_multi_tf', id, last_time_close, updated_at
FROM public.cmc_price_bars_multi_tf_state
WHERE id = <internal_id>
LIMIT 1;

-- Count rows inserted since first run (should be 0-1 if no new data)
SELECT
    COUNT(*) as new_rows
FROM public.cmc_price_bars_1d
WHERE id = <internal_id>
  AND timestamp > (SELECT last_src_ts FROM public.cmc_price_bars_1d_state WHERE id = <internal_id> LIMIT 1);
```

**Expected:** State tables updated (last_run_ts/updated_at recent), but row counts unchanged (incremental detected no new data).

---

## Troubleshooting

### Problem: No rows in cmc_price_bars_1d
**Symptoms:** Script succeeds but no bars created.

**Diagnosis:**
```sql
-- Check if price_histories7 has data for asset
SELECT id, COUNT(*), MIN(timestamp), MAX(timestamp)
FROM public.price_histories7
WHERE id IN (<cmc_id>, <internal_id>)
GROUP BY id;
```

**Likely causes:**
1. **Wrong ID used:** price_histories7 may use cmc_id, not internal id (check ID mapping)
2. **No source data:** price_histories7 empty for this asset (run data ingestion first)
3. **Date range issue:** --time-min/--time-max flags exclude all data

**Solutions:**
- Verify dim_assets mapping: `SELECT id, cmc_id FROM dim_assets WHERE id = <internal_id>;`
- Check source table uses correct ID column
- Remove date range filters and retry

---

### Problem: High reject rate (>5% of bars rejected)
**Symptoms:** cmc_price_bars_1d_rejects table has many rows for asset.

**Diagnosis:**
```sql
-- Analyze reject reasons
SELECT reason, COUNT(*), ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as pct
FROM public.cmc_price_bars_1d_rejects
WHERE id = <internal_id>
GROUP BY reason
ORDER BY COUNT(*) DESC;
```

**Common reject reasons and fixes:**
| Reason | Cause | Fix |
|--------|-------|-----|
| null_ohlc | Missing open/high/low/close in source | Clean price_histories7 data, backfill missing values |
| high_lt_low | Inverted OHLC (high < low) | Data corruption in source, investigate CMC API issue |
| time_high_outside_window | time_high after time_close | Repair failed, check time_high logic in source |
| null_time_high_time_low_after_repair | Repair couldn't fix extrema timestamps | Source data missing timehigh/timelow columns |

**General solution:** Most rejects indicate source data quality issues. Investigate price_histories7 rows being rejected and fix at source.

---

### Problem: No multi-TF bars created but 1D bars exist
**Symptoms:** cmc_price_bars_1d has rows, but cmc_price_bars_multi_tf empty.

**Diagnosis:**
```sql
-- Check if dim_timeframe has canonical TFs
SELECT tf, tf_days_nominal, is_canonical
FROM public.dim_timeframe
WHERE alignment_type = 'tf_day'
  AND is_canonical = TRUE
ORDER BY tf_days_nominal;
```

**Likely causes:**
1. **dim_timeframe empty:** No timeframe definitions (should have ~7 canonical TFs)
2. **Script variant mismatch:** Using calendar script with tf_day bars

**Solutions:**
- Populate dim_timeframe: Run `python src/ta_lab2/scripts/setup/populate_dim_timeframe.py` (if exists)
- Verify TF query: Run diagnosis query above, should return 7D, 14D, 21D, 30D, 90D, 365D

---

### Problem: EMAs sparse or missing for many (tf, period) combinations
**Symptoms:** EMA table has rows but fewer than expected (tf_count × period_count).

**Diagnosis:**
```sql
-- Count complete bars per TF (EMAs require is_partial_end=FALSE)
SELECT
    tf,
    COUNT(*) as total_snapshots,
    COUNT(CASE WHEN is_partial_end = FALSE THEN 1 END) as complete_bars
FROM public.cmc_price_bars_multi_tf
WHERE id = <internal_id>
GROUP BY tf
ORDER BY tf;
```

**Likely causes:**
1. **Insufficient complete bars:** EMA seeding requires `min_periods` complete bars (default = period)
   - Example: 200-period EMA needs 200 complete bars
2. **Recent asset:** Short history, not enough data for long-period EMAs (e.g., 365D)

**Solutions:**
- **Expected for new assets:** Long-period EMAs (100, 200, 365) will populate as data accumulates
- **Check seeding:** EMA rows should appear once enough complete bars exist
- **Verify is_partial_end filter:** `SELECT COUNT(*) FROM cmc_price_bars_multi_tf WHERE id=<internal_id> AND tf='7D' AND is_partial_end=FALSE;`

---

## Automation Opportunities

### Current Manual Steps
1. **dim_assets insert:** Manual SQL INSERT (could be scripted with CMC ID validation)
2. **Script invocation:** Three separate commands (could be orchestrated)
3. **Validation queries:** Manual SQL verification (could be test suite)

### Proposed Automation (Phase 23+)

#### add_asset.py Script
```bash
# Hypothetical automated onboarding script
python src/ta_lab2/scripts/admin/add_asset.py \
    --cmc-id 1027 \
    --symbol ETH \
    --name Ethereum \
    --validate \
    --build-bars \
    --compute-emas
```

**Would automate:**
- dim_assets insert with duplicate detection
- CMC API validation (verify cmc_id exists, is active)
- Sequential execution: 1D bars → multi-TF bars → EMAs
- Validation queries with pass/fail reporting
- State verification for incremental refresh readiness

**Effort estimate:** 8-12 hours (CLI arg parsing, orchestration, validation framework)

---

## Cross-References

### Script Execution Order
See: data-flow-diagram.md section 2 (L1 System Overview)
- Source: price_histories7 (raw daily prices)
- Step 1: Bar builders (6 variants)
- Step 2: EMA refreshers (4+ variants)
- Output: Feature Store → Backtesting/Live Trading

### Validation Checks
See: validation-points.md for complete validation catalog
- Section 1: NULL rejection points (bars: lines 10-31)
- Section 2: OHLC invariant checks (bars: lines 131-186)
- Section 3: Quality flags (bars: lines 250-330)
- Section 4: EMA filtering (is_partial_end exclusion: line 335-343)

### State Management
See: incremental-refresh.md for state mechanics
- Section 1: Bar builder state (1D: lines 11-28, Multi-TF: lines 30-63)
- Section 2: EMA state (Unified schema: lines 209-233)
- Section 3: Backfill detection (Multi-TF: lines 170-202)
- Section 4: Incremental query patterns (lines 295-305)

### EMA Variant Selection
See: ema-variants.md section 1 (Executive Summary)
- Standard (v1): Persisted multi-TF bars (bars-dependent)
- Standard (v2): Synthetic multi-TF from daily (bars-independent)
- Calendar (cal_us/cal_iso): US/ISO calendar alignment
- Calendar Anchor: Year-anchored fiscal analysis

### Bar Variant Selection
See: variant-comparison.md section "Dimension-by-Dimension Analysis"
- tf_day (multi_tf): Row-count bars (7D = 7 rolling days)
- Calendar (cal_us/cal_iso): Fixed-start weeks/months/years
- Calendar Anchor: Year-boundary reset for fiscal analysis

---

## Quick Reference Command List

```bash
# Prerequisites: Verify data exists
psql -d ta_lab2 -c "SELECT COUNT(*) FROM price_histories7 WHERE id = <cmc_id>;"

# Step 1: Add to dim_assets (via psql)
psql -d ta_lab2 -c "INSERT INTO dim_assets (id, cmc_id, symbol, name) VALUES (<id>, <cmc_id>, '<symbol>', '<name>') ON CONFLICT (id) DO NOTHING;"

# Step 2: Build 1D bars
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py --ids <id> --keep-rejects

# Step 3: Build multi-TF bars
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py --ids <id>

# Step 4: Compute EMAs
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py --ids <id>

# Step 5: Validate output
psql -d ta_lab2 -c "SELECT tf, COUNT(*) FROM cmc_price_bars_multi_tf WHERE id = <id> GROUP BY tf;"
psql -d ta_lab2 -c "SELECT tf, period, COUNT(*) FROM cmc_ema_multi_tf_u WHERE id = <id> GROUP BY tf, period ORDER BY tf, period;"

# Step 6: Test incremental refresh (re-run commands from Steps 2-4)
```

---

## Summary

**Onboarding a new asset requires 6 steps:**
1. Add metadata to dim_assets (1 minute, manual SQL)
2. Build 1D bars (2-5 minutes, script)
3. Build multi-TF bars (3-10 minutes, script)
4. Compute EMAs (5-15 minutes, script)
5. Validate output (2-3 minutes, SQL queries)
6. Verify incremental refresh (2-3 minutes, re-run scripts)

**Total time:** 15-40 minutes per asset (scales with history depth)

**Key success criteria:**
- Bar counts match date range expectation
- EMA combinations = (# TFs) × (# periods)
- State tables populated with current watermarks
- Re-running scripts produces minimal new rows (incremental working)

**Next steps after onboarding:**
- Feature computation: Run feature pipeline scripts (returns, volatility, indicators)
- Signal generation: Compute trading signals (EMA crossovers, RSI mean reversion)
- Backtesting: Test strategies using new asset data
