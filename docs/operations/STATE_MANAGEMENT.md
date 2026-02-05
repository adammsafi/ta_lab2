# State Management Patterns

This document describes how state is tracked across bar and EMA refresh scripts to enable reliable incremental updates.

## Overview

State management uses **watermarking** - tracking the last successfully processed timestamp to determine where to resume. This pattern:
- Enables incremental refresh (process only new data)
- Supports resume after failures
- Detects backfills that require full rebuilds

## State Tables

### cmc_price_bars_1d_state

Tracks state for 1D bar builder:

| Column | Type | Purpose |
|--------|------|---------|
| id | integer | Asset ID (FK to dim_assets) |
| last_src_ts | timestamptz | Latest source timestamp processed |
| daily_min_seen | timestamptz | Earliest timestamp ever seen (backfill detection) |
| last_run_ts | timestamptz | When script last ran |
| last_upserted | integer | Bars upserted in last run |
| last_repaired_timehigh | integer | Time_high repairs in last run |
| last_repaired_timelow | integer | Time_low repairs in last run |
| last_rejected | integer | Rows rejected in last run |

**Watermark pattern:**
- On each run, query `WHERE src.timestamp > state.last_src_ts`
- After successful upsert, update `last_src_ts = MAX(processed timestamps)`

**Backfill detection:**
- Compare current `MIN(src.timestamp)` to `daily_min_seen`
- If MIN < daily_min_seen, historical data was backfilled
- Full rebuild required to maintain bar_seq integrity

### cmc_ema_refresh_state

Tracks state for EMA refreshers:

| Column | Type | Purpose |
|--------|------|---------|
| id | integer | Asset ID |
| last_load_ts_daily | timestamptz | Last processed for daily EMAs |
| last_load_ts_multi | timestamptz | Last processed for multi-TF EMAs |
| last_load_ts_cal | timestamptz | Last processed for calendar EMAs |

**Watermark pattern:**
- Each EMA variant tracks its own last processed timestamp
- Query `WHERE bar.timestamp > state.last_load_ts_*`
- Update watermark after successful EMA computation

## Watermark Patterns

### Standard Incremental Refresh

```python
# 1. Read watermark
last_ts = get_state_watermark(id)

# 2. Query new data
new_data = query_source(where timestamp > last_ts)

# 3. Process and write
write_to_target(new_data)

# 4. Update watermark
update_state_watermark(id, max(new_data.timestamp))
```

### Lookback Window (Late-Arriving Data)

Some scripts use a lookback window to handle late-arriving data:

```python
# Instead of strict watermark
cutoff = last_ts - timedelta(days=lookback_days)
new_data = query_source(where timestamp > cutoff)

# UPSERT handles duplicates
upsert_to_target(new_data)
```

### Full Rebuild Trigger

Full rebuild is triggered when:
1. No state exists for an ID (first run)
2. `--full-rebuild` flag is passed
3. Backfill detected (MIN timestamp < daily_min_seen)
4. State is corrupted or inconsistent

## State-Based Coordination

The unified refresh script checks bar freshness before running EMAs:

```sql
-- Check bar freshness
SELECT id, last_src_ts,
       EXTRACT(EPOCH FROM (now() - last_src_ts)) / 3600 as staleness_hours
FROM cmc_price_bars_1d_state
WHERE staleness_hours > threshold;
```

If bars are stale, EMAs are skipped for those IDs (or user is warned).

**Default staleness threshold:** 48 hours

## Consistency Guarantees

1. **Atomic updates:** State is updated in same transaction as data writes
2. **Idempotent writes:** UPSERT ensures reruns produce same result
3. **Ordering preserved:** bar_seq maintains chronological order
4. **Quality flags:** is_missing_days, is_partial_end track data quality

## State Lifecycle

### First Run (New Asset)
1. No state row exists
2. Script queries entire source history
3. Builds all bars from scratch
4. Inserts state row with last_src_ts = MAX(timestamp)

### Incremental Run
1. Read last_src_ts from state
2. Query source WHERE timestamp > last_src_ts
3. Process incremental data
4. Update state row with new last_src_ts

### Full Rebuild
1. DELETE FROM state WHERE id = X (or pass --full-rebuild)
2. Script treats as first run
3. Rebuilds entire history
4. Inserts/updates state row

## Troubleshooting

### Reset state for an ID
```sql
DELETE FROM cmc_price_bars_1d_state WHERE id = 825;
-- Next run will do full history for ID 825
```

### Force full rebuild via CLI
```bash
python run_daily_refresh.py --all --full-rebuild --ids 825
```

### Check state freshness
```sql
SELECT id, last_src_ts, now() - last_src_ts as age
FROM cmc_price_bars_1d_state
ORDER BY age DESC;
```

### Check for stale bars before EMAs
```sql
SELECT id, last_src_ts,
       EXTRACT(EPOCH FROM (now() - last_src_ts)) / 3600 as staleness_hours
FROM cmc_price_bars_1d_state
WHERE EXTRACT(EPOCH FROM (now() - last_src_ts)) / 3600 > 48
ORDER BY staleness_hours DESC;
```

### Verify state consistency
```sql
-- Bar state should match actual data
SELECT s.id, s.last_src_ts, MAX(b."timestamp") as actual_max
FROM cmc_price_bars_1d_state s
LEFT JOIN cmc_price_bars_1d b ON s.id = b.id
GROUP BY s.id, s.last_src_ts
HAVING s.last_src_ts != MAX(b."timestamp");
```

## See Also

- [DAILY_REFRESH.md](DAILY_REFRESH.md) - Operational guide for daily refresh workflow
- `sql/ddl/create_cmc_price_bars_1d_state.sql` - Bar state table DDL
- `sql/ddl/create_cmc_ema_refresh_state.sql` - EMA state table DDL
