# Phase 108: Pipeline Batch Performance Optimization

**Goal:** Eliminate per-key SQL queries across the pipeline. Replace individual queries per (id, tf, period, venue_id) with batch SQL operations that process all TFs/periods for an asset in a single query.

## Problem Statement

The daily refresh pipeline processes ~5.7M individual SQL operations for a 4-day incremental update (1,811 new rows). Each (id, tf, period, venue_id) combination triggers its own SELECT + INSERT query. At 50ms per query, this takes hours even though the actual data delta is tiny.

### Key Counts by Script

| Script | Keys per Run | Pattern | Current Time | Target |
|--------|-------------|---------|-------------|--------|
| returns_ema_multi_tf | 2,037,648 | per (id,tf,period,venue) | ~40 min | ~5 min |
| returns_ema_cal (×2) | ~668K each | per (id,tf,period,venue) | ~20 min each | ~3 min |
| returns_ema_cal_anchor (×2) | ~668K each | per (id,tf,period,venue) | ~20 min each | ~3 min |
| returns_ama | 693,648 | per (id,alignment_source) | ~15 min | ~3 min |
| returns_bars_multi_tf | 120,048 | per (id,tf,venue) | ~10 min | ~2 min |
| ema_multi_tf (dirty window) | 492 IDs | loads 15yr history | ~59 min | ~10 min |
| asset_stats | 30,080 | per (id,tf) | ~33 min→3 min (fixed) | done |
| bars (multi_tf) | 120,048 | per (id,tf,venue) | ~37 min | ~10 min |
| bars (cal variants ×4) | ~20K each | per (id,spec,venue) | 3hr→min (fixed) | done |

**Total current time for incremental: ~5-6 hours**
**Target: ~1-1.5 hours**

## Root Cause

Every returns/stats script follows this anti-pattern:
```python
keys = [(id, tf, period, venue_id) for id in ids for tf in tfs for period in periods ...]
for key in keys:
    result = conn.execute(per_key_sql, key_params)  # 1 query per key
```

The fix for all of them is the same batch pattern:
```python
for id_ in ids:
    # One query computes returns for ALL (tf, period) combos using PARTITION BY
    result = conn.execute(batch_sql_for_id, {"id": id_})  # 1 query per asset
```

## Plan

### Plan 1: EMA Returns Batch (highest impact — 2M keys → 492 queries)

**Scripts:** `refresh_returns_ema_multi_tf.py`, `refresh_returns_ema_multi_tf_cal.py`, `refresh_returns_ema_multi_tf_cal_anchor.py`

**Current:** One SQL CTE per (id, tf, period, venue_id) — 2M+ individual queries.

**Fix:** Replace the per-key `_run_one_key()` with a per-ID batch query:
```sql
WITH src AS (
    SELECT id, venue_id, ts, tf, period, roll, ema, ema_bar
    FROM ema_multi_tf_u
    WHERE id = :id AND alignment_source = :as
      AND ts >= :seed_ts  -- watermark - 2 rows
),
lagged AS (
    SELECT *,
        LAG(ema) OVER (PARTITION BY tf, period, venue_id ORDER BY ts) AS prev_ema,
        LAG(ema) OVER (PARTITION BY tf, period, venue_id, roll ORDER BY ts) AS prev_ema_c,
        ...
    FROM src
)
INSERT INTO returns_ema_multi_tf_u ...
SELECT ... FROM lagged
WHERE ts > :watermark  -- only new rows
ON CONFLICT DO NOTHING
```

One query per ID computes returns for ALL (tf, period, venue_id) combos at once using `PARTITION BY`. SQL window functions handle the LAG naturally.

**Watermark optimization:** Preload all watermarks in one query (same pattern as desc_stats fix). Skip IDs where max source ts <= watermark.

**Estimated effort:** ~200 LOC refactor per script (3 scripts).
**Expected speedup:** 2M queries → 492 queries → ~5 min.

### Plan 2: AMA Returns Batch

**Script:** `refresh_returns_ama.py`

**Current:** One SQL CTE per (alignment_source, id) — ~700K keys (already partially fixed with incremental watermark).

**Fix:** Same batch SQL pattern — one query per ID that partitions by (tf, indicator, params_hash, venue_id). Already uses SQL window functions, just needs to remove the per-key loop.

**Estimated effort:** ~100 LOC.
**Expected speedup:** ~15 min → ~3 min.

### Plan 3: Bar Returns Batch

**Script:** `refresh_returns_bars_multi_tf.py`

**Current:** One SQL per (id, tf, venue_id) — 120K keys.

**Fix:** One query per ID, PARTITION BY (tf, venue_id).

**Estimated effort:** ~100 LOC.
**Expected speedup:** ~10 min → ~2 min.

### Plan 4: EMA Dirty Window Optimization

**Script:** `ema_state_manager.py` → `refresh_ema_multi_tf_from_bars.py`

**Current:** Uses min() watermark across all TFs, loading 15+ years of history. **Already fixed** to use max() - 730 days.

**Remaining:** The EMA feature class still recomputes ALL TFs from the start point. For an asset with state at 2026-03-27, it loads 730 days of data and recomputes 122 TFs × 17 periods. A true incremental would use `previous_ema + alpha * (new_close - previous_ema)` — one arithmetic op per (tf, period), no history needed.

**Fix:** Add a fast-path in the EMA worker: if the watermark is recent (within 7 days), load last EMA values from the _u table and compute forward using the recursive formula. Fall back to full recompute if watermark is old.

**Estimated effort:** ~150 LOC.
**Expected speedup:** ~25 min → ~2-3 min for daily.

### Plan 5: Multi-TF Bars — Batch Upsert State Updates

**Script:** `refresh_price_bars_multi_tf.py`

**Current:** Per (id, tf, venue_id) loop through 120K combos. Already uses Polars for snapshot computation but loops per-TF for state updates.

**Fix:** Already significantly improved with incremental path fix. Remaining optimization: batch state updates (one INSERT...ON CONFLICT per ID instead of per TF).

**Estimated effort:** ~50 LOC.
**Expected speedup:** ~37 min → ~15 min.

## Execution Order

1. **Plan 1** (EMA returns batch) — highest impact, most keys
2. **Plan 4** (EMA fast-path) — second highest time consumer
3. **Plan 2** (AMA returns batch)
4. **Plan 3** (Bar returns batch)
5. **Plan 5** (Multi-TF state batch)

Plans 1 + 4 alone would cut the pipeline from ~5 hours to ~2.5 hours.
All 5 plans would bring it to ~1-1.5 hours for an incremental daily refresh.

## Success Criteria

- [ ] Full `--all` incremental run completes in < 2 hours (currently 5-6 hours)
- [ ] EMA returns: < 10 min (currently 40+ min)
- [ ] No data correctness regressions (returns match before/after)
- [ ] All scripts still support `--full-rebuild` for initial/backfill runs

## Dependencies

- Phase 107 (pipeline dashboard) — timing data useful for monitoring
- All fixes from this session (EMA batch upsert, cal incremental, etc.)
