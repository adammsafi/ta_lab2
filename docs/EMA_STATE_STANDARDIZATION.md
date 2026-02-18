# EMA State Table Standardization

## Overview

All EMA refresh scripts now use a unified state table schema and consistent function names managed through the shared `state_management.py` module.

## Unified State Table Schema

```sql
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    -- Primary key (standardized across all EMA scripts)
    id                  INTEGER         NOT NULL,
    tf                  TEXT            NOT NULL,
    period              INTEGER         NOT NULL,

    -- Timestamp range (populated by ALL scripts)
    daily_min_seen      TIMESTAMPTZ     NULL,
    daily_max_seen      TIMESTAMPTZ     NULL,
    last_time_close     TIMESTAMPTZ     NULL,
    last_canonical_ts   TIMESTAMPTZ     NULL,

    -- Bar sequence (only populated by multi_tf scripts, NULL for cal/anchor)
    last_bar_seq        INTEGER         NULL,

    -- Metadata
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);
```

### Field Population by Script Type

**ALL Scripts Populate ALL Fields:**
- `daily_min_seen` - Earliest bar timestamp (from bars table)
- `daily_max_seen` - Latest bar timestamp (from bars table)
- `last_bar_seq` - Highest canonical bar sequence number (from bars table)
- `last_time_close` - Most recent close timestamp (from output table)
- `last_canonical_ts` - Most recent canonical close timestamp (from output table)

All scripts read from pre-computed bar tables that contain `bar_seq`, so all scripts populate all fields consistently.

## Standardized Function Names

All EMA scripts now use these consistent function names:

| Function | Purpose |
|----------|---------|
| `ensure_ema_state_table(engine, schema, table)` | Create unified state table if it doesn't exist |
| `load_ema_state(engine, schema, table)` | Load state from table |
| `update_ema_state_from_output(engine, schema, state_table, output_table, ...)` | Update state from output table |
| `compute_dirty_window_start(state_df, selected_ids, default_start)` | Compute incremental refresh start timestamp |

## Updated Scripts

### 1. refresh_cmc_ema_multi_tf_cal_from_bars.py
- **State table:** `cmc_ema_multi_tf_cal_us_state`, `cmc_ema_multi_tf_cal_iso_state`
- **Bars table:** `cmc_price_bars_multi_tf_cal_us`, `cmc_price_bars_multi_tf_cal_iso`
- **State columns populated (ALL):**
  - `last_canonical_ts` - MAX(ts) WHERE roll = FALSE (from output)
  - `last_time_close` - Same as last_canonical_ts (from output)
  - `daily_min_seen` - MIN(time_open) (from bars table)
  - `daily_max_seen` - MAX(time_close) (from bars table)
  - `last_bar_seq` - MAX(bar_seq) WHERE is_partial_end = FALSE (from bars table)
- **Update strategy:** Combines bars table metadata with output table timestamps

### 2. refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py
- **State table:** `cmc_ema_multi_tf_cal_anchor_us_state`, `cmc_ema_multi_tf_cal_anchor_iso_state`
- **Bars table:** `cmc_price_bars_multi_tf_cal_anchor_us`, `cmc_price_bars_multi_tf_cal_anchor_iso`
- **State columns populated (ALL):**
  - `last_canonical_ts` - MAX(ts) WHERE roll_bar = FALSE (from output)
  - `last_time_close` - Same as last_canonical_ts (from output)
  - `daily_min_seen` - MIN(time_open) (from bars table)
  - `daily_max_seen` - MAX(time_close) (from bars table)
  - `last_bar_seq` - MAX(bar_seq) WHERE is_partial_end = FALSE (from bars table)
- **Update strategy:** Combines bars table metadata with output table timestamps
- **Special handling:** Validates output schema to find correct timestamp column

### 3. refresh_cmc_ema_multi_tf_from_bars.py
- **State table:** `cmc_ema_multi_tf_state`
- **State columns populated:**
  - `last_time_close` - MAX(time_close) from output table
  - `last_bar_seq` - MAX(bar_seq) from output table
  - `daily_min_seen` - From bars table (shared across periods)
  - `daily_max_seen` - From bars table (shared across periods)
  - `last_canonical_ts` - Not used by this script
- **Update strategy:**
  - Bar state from `cmc_price_bars_multi_tf` (per id, tf - shared across periods)
  - EMA state from output table (per id, tf, period)

### 4. refresh_cmc_ema_multi_tf_v2.py
- **State table:** `cmc_ema_multi_tf_v2_state` (created but not yet populated)
- **State columns:** Table created with unified schema for future use
- **Note:** V2 refresh function handles incremental refresh internally (state update not yet implemented)

## Migration Notes

### Breaking Changes
- **Primary key changed** from `(id, tf)` to `(id, tf, period)` for multi_tf state
- **State tables will be automatically migrated** when scripts run (CREATE TABLE IF NOT EXISTS)
- **Old state data** per (id, tf) will need manual migration if you want to preserve it

### Migration SQL (if needed)

If you have existing state data in old schema and want to migrate:

```sql
-- Example: Migrate multi_tf state from old (id, tf) to new (id, tf, period) schema
-- This creates one row per period for each existing (id, tf) pair

INSERT INTO public.cmc_ema_multi_tf_state_new (id, tf, period, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at)
SELECT
    old.id,
    old.tf,
    p.period,
    old.daily_min_seen,
    old.daily_max_seen,
    old.last_bar_seq,
    old.last_time_close,
    old.updated_at
FROM public.cmc_ema_multi_tf_state_old old
CROSS JOIN (SELECT DISTINCT period FROM public.ema_alpha_lookup) p
ON CONFLICT (id, tf, period) DO NOTHING;
```

## Benefits

1. **Consistency:** All EMA scripts populate the same fields (except last_bar_seq)
2. **Maintainability:** Shared code reduces duplication
3. **Uniformity:** No NULL confusion - all scripts populate all applicable fields
4. **Precision:** Per-period watermarks enable efficient incremental refresh
5. **Extensibility:** Easy to add new state columns in future
6. **Completeness:** Each state record has full timestamp range information

## Testing

After standardization, verify each script works:

```bash
# Test cal script
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_from_bars.py --ids 1 --periods 6,9 --scheme us --log-level INFO

# Test cal anchor script
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py --ids 1 --periods 6,9 --scheme us --log-level INFO

# Test multi_tf script
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py --ids 1 --periods 6,9 --log-level INFO

# Test v2 script
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_v2.py --ids 1 --periods 6,9 --log-level INFO
```

## Files Modified

1. **New:** `src/ta_lab2/scripts/emas/state_management.py` - Shared state management module
2. **Updated:** `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_from_bars.py`
3. **Updated:** `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py`
4. **Updated:** `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py`
5. **Updated:** `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_v2.py`

## Future Enhancements

Consider adding to the shared module:
- State cleanup utilities (remove old periods)
- State validation (check for orphaned records)
- State reporting (coverage analysis per id/tf/period)
