# Incremental Refresh: How It Works

## Executive Summary

Incremental refresh in ta_lab2 uses watermark-based state tracking to process only new data since the last run. Bar builders track `last_src_ts` (1D) or `daily_min_seen/daily_max_seen` (multi-TF) to determine what needs processing. EMA refreshers track `last_time_close` or `last_canonical_ts` per (id, tf, period) to compute only new EMAs. Backfill detection triggers full rebuilds when historical data appears earlier than previously seen watermarks.

## Bar Builder Incremental Refresh

### State Table Schemas

#### 1D Bars (cmc_price_bars_1d_state)

| Column | Type | Purpose |
|--------|------|---------|
| id | integer | Asset ID (primary key) |
| last_src_ts | timestamptz | Last processed source timestamp from price_histories7 |
| last_run_ts | timestamptz | Timestamp of last refresh run |
| last_upserted | integer | Count of rows upserted in last run |
| last_repaired_timehigh | integer | Count of timehigh repairs in last run |
| last_repaired_timelow | integer | Count of timelow repairs in last run |
| last_rejected | integer | Count of rejected rows in last run |

**Location:** `refresh_cmc_price_bars_1d.py` lines 202-214 (DDL_CREATE_STATE)

**Schema characteristics:**
- Simple watermark: single timestamp per asset
- No TF column (1D is the only timeframe)
- Includes diagnostic counters for repairs and rejections

#### Multi-TF Bars (cmc_price_bars_multi_tf_state)

| Column | Type | Purpose |
|--------|------|---------|
| id | integer | Asset ID (part of composite primary key) |
| tf | text | Timeframe label (part of composite primary key) |
| daily_min_seen | timestamptz | Earliest daily timestamp ever processed |
| daily_max_seen | timestamptz | Latest daily timestamp ever processed |
| last_bar_seq | integer | Last bar sequence number written |
| last_time_close | timestamptz | Last bar close timestamp written |
| updated_at | timestamptz | Last state update timestamp |

**Location:** `common_snapshot_contract.py` lines 488-521 (ensure_state_table)

**Primary key:** (id, tf)

**Schema characteristics:**
- Backfill detection: `daily_min_seen` tracks earliest data seen
- Range tracking: `daily_min_seen` and `daily_max_seen` bracket all processed data
- Per-timeframe state: separate watermark for each (id, tf) combination

#### Calendar Multi-TF State (with timezone)

Same schema as multi-TF bars, plus:

| Column | Type | Purpose |
|--------|------|---------|
| tz | text | Timezone for calendar alignment (NOT in primary key) |

**Location:** `common_snapshot_contract.py` lines 488-521 (ensure_state_table with `with_tz=True`)

**Primary key:** (id, tf) — **NOT** (id, tf, tz)

**Note:** The `tz` column is metadata only. Primary key remains (id, tf).

### Refresh Flow

**1D Bar Builder:** `refresh_cmc_price_bars_1d.py`

1. **Load state** (line 710: `last_src_ts = _get_last_src_ts(conn, state, id_)`)
   - Query: `SELECT last_src_ts FROM {state} WHERE id = %s`
   - Returns last processed timestamp or None for first run

2. **Determine query window** (lines 716-727: params construction)
   - If `last_src_ts` exists: Query `WHERE timestamp > (last_src_ts - lookback_days * INTERVAL '1 day')`
   - Lookback (default 3 days) handles late-arriving data revisions
   - If no state: Process all available data

3. **Query source** (line 267-320: `_insert_valid_and_return_stats_sql`)
   - CTE `ranked_all`: Assigns dense_rank bar_seq over ALL rows for id
   - CTE `src_rows`: Filters to window `timestamp >= cutoff AND timestamp < time_max`
   - Joins to get bar_seq for windowed rows
   - Applies OHLC repairs and validation in SQL

4. **Process and upsert** (lines 733-738: `_fetchone(conn, ins_sql, params)`)
   - Single SQL statement inserts valid rows with `ON CONFLICT (id, timestamp) DO UPDATE`
   - Returns aggregate stats: upserted count, repairs, max_src_ts

5. **Update state** (lines 741-756: state upsert)
   - Write new `last_src_ts = max_src_ts` from processed rows
   - Update diagnostic counters (upserted, repaired, rejected)
   - SQL: `INSERT ... ON CONFLICT (id) DO UPDATE SET last_src_ts = COALESCE(EXCLUDED.last_src_ts, {state}.last_src_ts), ...`

**Multi-TF Bar Builder:** `refresh_cmc_price_bars_multi_tf.py`

1. **Load state and daily metadata** (lines 762-774: `load_state` and `load_daily_min_max`)
   - Load state for all requested ids: `load_state(db_url, state_table, ids, with_tz=False)`
   - Query daily range: `SELECT id, MIN(timestamp), MAX(timestamp) FROM {daily_table} WHERE id = ANY(:ids) GROUP BY id`
   - Build maps: `state_map[(id, tf)] = {daily_min_seen, daily_max_seen, last_bar_seq, last_time_close}`

2. **Per (id, tf): Determine action** (lines 789-810: decision tree)
   - **No state AND no bars:** Full build (lines 794-821)
   - **Has state OR bars:** Check for backfill (line 863: `if daily_min_ts < daily_min_seen`)
   - **Backfill detected:** Rebuild (lines 863-895)
   - **No new data:** No-op (lines 897-909: `if daily_max_ts <= last['last_time_close']`)
   - **New data available:** Incremental append (lines 911-970)

3. **Backfill detection** (line 863)
   ```python
   if daily_min_ts < daily_min_seen:
       print(f"Backfill detected: id={id_}, tf={tf_label}, "
             f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding.")
       delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=tf_label)
       # ... full rebuild ...
   ```
   - Compares current `daily_min_ts` from source table to stored `daily_min_seen`
   - If source min is **earlier** than state min → historical data was backfilled
   - Triggers DELETE + full rebuild for that (id, tf)

4. **Incremental append** (lines 449-738: `_append_incremental_rows_for_id_tf`)
   - Query daily rows: `load_daily_prices_for_id(id_=id_, ts_start=last_time_close + 1ms)`
   - Iterate new daily closes, building snapshot rows
   - Carry-forward optimization: O(1) update when strict gate passes (lines 589-629)
   - Fallback: Explicit incremental math for high/low/volume (lines 631-733)
   - Each new daily close creates ONE snapshot row

5. **Update state** (line 972: `upsert_state`)
   - Write updated watermarks: `daily_min_seen = min(old, new)`, `daily_max_seen = max(old, new)`
   - Write last bar position: `last_bar_seq`, `last_time_close`
   - Batch upsert: all (id, tf) state rows updated together

### Gap Handling

**1D Bars:**
- **Quality flags only** (lines 407-410)
  - `is_partial_start = FALSE` (1D bars are always complete)
  - `is_partial_end = FALSE` (1D bars are always complete)
  - `is_missing_days = FALSE` (1D bars have no concept of multi-day windows)
- **No rejection:** Missing days between 1D bars don't cause rejection
- **Rationale:** Each daily close is an independent bar; no gap validation needed

**Multi-TF Bars:**
- **Gap detection** (lines 367-376 in `build_snapshots_for_id`)
  ```python
  gaps = df.groupby("bar_seq", sort=False)["ts"].diff()
  missing_incr = gaps / pd.Timedelta(days=1)
  missing_incr = missing_incr.fillna(0).astype("int64") - 1
  missing_incr = missing_incr.clip(lower=0).astype("int64")
  df["count_missing_days"] = df.groupby("bar_seq", sort=False)["missing_incr"].cumsum()
  df["is_missing_days"] = df["count_missing_days"] > 0
  ```
- **How it works:**
  - Compute diff between consecutive timestamps within same bar_seq
  - Convert to days: `gaps / pd.Timedelta(days=1)`
  - Subtract 1 to get missing days: `missing_incr = (days_diff) - 1`
  - Cumsum within bar to get total missing days for bar
  - Flag set: `is_missing_days = TRUE` if any days missing

- **Action taken:** Flag set, processing continues (no rejection)
- **Missing days diagnostics** (lines 582-586 in `_append_incremental_rows_for_id_tf`)
  ```python
  miss_diag = compute_missing_days_diagnostics(
      bar_start_day_local=cur_bar_start_day_local,
      snapshot_day_local=snapshot_day_local,
      observed_local_days=cur_bar_local_days,
  )
  ```
  - Returns: `{is_missing_days, count_days, count_missing_days, first_missing_day, last_missing_day}`
  - Used to populate bar snapshot quality flags

### Backfill Detection

**Mechanism:** Compare current source data range to stored state range

**1D Bars:** No backfill detection
- State tracks `last_src_ts` only (not min)
- Always processes from `last_src_ts - lookback_days` forward
- No detection of historical data appearing before first processed row

**Multi-TF Bars:** Backfill detection via `daily_min_seen`
- **Detection logic** (line 863: `if daily_min_ts < daily_min_seen`)
  ```python
  daily_min_ts = mm["daily_min_ts"]  # Current MIN(timestamp) from source table
  daily_min_seen = state["daily_min_seen"]  # Previously stored min

  if daily_min_ts < daily_min_seen:
      # Historical data backfilled → rebuild required
      delete_bars_for_id_tf(...)
      df_full = load_daily_prices_for_id(id_=id_)
      bars = build_snapshots_for_id_polars(df_full, ...)
      upsert_bars(bars, ...)
  ```

- **Why rebuild needed:**
  - Bar sequence numbers (`bar_seq`) are assigned from first row: `bar_seq = (row_index // tf_days) + 1`
  - If historical data appears before previously-first row, ALL bar_seq values shift
  - Cannot incrementally adjust bar_seq → must rebuild from scratch

- **Trigger condition:**
  - Source table `MIN(timestamp)` becomes **earlier** than state `daily_min_seen`
  - Example: State has `daily_min_seen = 2020-01-15`, but source now has data from 2020-01-10
  - Rebuild ensures correct bar_seq assignment from new earliest row

**Calendar variants:** Same backfill detection logic (inherited from common_snapshot_contract.py)

## EMA Incremental Refresh

### State Table Schema (EMAStateManager)

**Unified State Schema** (all 6 EMA variants use this)

| Column | Type | Purpose |
|--------|------|---------|
| id | integer | Asset ID (primary key component) |
| tf | text | Timeframe (primary key component) |
| period | integer | EMA period (primary key component) |
| daily_min_seen | timestamptz | Earliest bar timestamp seen from source |
| daily_max_seen | timestamptz | Latest bar timestamp seen from source |
| last_time_close | timestamptz | Latest bar time_close with EMA computed |
| last_canonical_ts | timestamptz | Latest canonical timestamp (for calendar variants) |
| last_bar_seq | integer | Latest bar_seq from source bars |
| updated_at | timestamptz | Last state update timestamp |

**Location:** `ema_state_manager.py` lines 78-99 (UNIFIED_STATE_SCHEMA)

**Primary key:** (id, tf, period)

**Schema characteristics:**
- **Finer granularity than bars:** Separate state per EMA period
- **Dual timestamp tracking:**
  - `last_time_close`: Used by multi_tf variants
  - `last_canonical_ts`: Used by calendar/anchor variants (tracks canonical bars only)
- **Bar metadata:** `daily_min_seen`, `daily_max_seen`, `last_bar_seq` populated from source bars table

### EMAStateManager API

**Location:** `ema_state_manager.py` lines 102-449

**Key methods:**

1. **ensure_state_table()** (lines 126-137)
   - Creates state table if doesn't exist
   - Idempotent: safe to call multiple times
   - Uses unified schema DDL

2. **load_state(ids, tfs, periods)** (lines 139-207)
   - Query: `SELECT id, tf, period, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, last_canonical_ts FROM {state_table} WHERE id = ANY(:ids) AND tf = ANY(:tfs) AND period = ANY(:periods)`
   - Returns DataFrame with optional filters
   - Returns empty DataFrame if table doesn't exist

3. **update_state_from_output(output_table, output_schema)** (lines 209-236)
   - Delegates to mode-specific updater based on config
   - `_update_canonical_ts_mode` (lines 238-367): Calendar/anchor variants
   - `_update_multi_tf_mode` (lines 369-393): Multi-TF variants

4. **compute_dirty_window_starts(ids, default_start)** (lines 395-442)
   - Determines incremental start timestamp per ID
   - Uses `last_canonical_ts` or `last_time_close` (whichever available)
   - Returns `{id: start_timestamp}` map
   - IDs with no state map to `default_start` (full rebuild)

### Refresh Flow

**Multi-TF EMA Refresher:** `refresh_cmc_ema_multi_tf_from_bars.py`

1. **Initialize state manager** (typical usage)
   ```python
   from ta_lab2.scripts.emas.ema_state_manager import EMAStateManager, EMAStateConfig

   config = EMAStateConfig(
       state_schema="public",
       state_table="cmc_ema_multi_tf_state",
       ts_column="time_close",
       use_canonical_ts=False,  # multi_tf mode
   )
   manager = EMAStateManager(engine, config)
   manager.ensure_state_table()
   ```

2. **Load state for incremental computation**
   ```python
   state_df = manager.load_state(ids=[1, 52], periods=[9, 10])
   # Returns: DataFrame with last_time_close, last_bar_seq per (id, tf, period)
   ```

3. **Determine query cutoff** (conceptual flow - script-specific)
   ```python
   for id_ in ids:
       id_state = state_df[state_df["id"] == id_]
       if id_state.empty:
           # No state → full rebuild
           cutoff_ts = None
       else:
           # Has state → query bars WHERE time_close > last_time_close
           cutoff_ts = id_state["last_time_close"].max()
   ```

4. **Query source bars** (WHERE clause based on cutoff)
   ```sql
   SELECT * FROM {bars_table}
   WHERE id = :id
     AND tf = :tf
     AND time_close > :cutoff_ts  -- Only new bars
     AND is_partial_end = FALSE   -- Only complete bars
   ORDER BY time_close
   ```

5. **Compute EMAs incrementally**
   - Use existing EMA state (last value, last timestamp) as seed
   - Compute EMA for new bars only
   - Formula: `EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}`
   - Requires previous EMA value → state provides `last_time_close` as seed point

6. **Update state** (via `update_state_from_output`)
   ```python
   manager.update_state_from_output(
       output_table="cmc_ema_multi_tf",
       output_schema="public",
   )
   ```
   - **Multi-TF mode** (lines 369-393):
     ```sql
     INSERT INTO {state_table} (id, tf, period, last_time_close, last_bar_seq, updated_at)
     SELECT
         id, tf, period,
         MAX(time_close) as last_time_close,
         MAX(bar_seq) as last_bar_seq,
         now() as updated_at
     FROM {output_table}
     WHERE time_close IS NOT NULL
     GROUP BY id, tf, period
     ON CONFLICT (id, tf, period) DO UPDATE SET
         last_time_close = EXCLUDED.last_time_close,
         last_bar_seq = EXCLUDED.last_bar_seq,
         updated_at = EXCLUDED.updated_at
     ```
   - Reads MAX(time_close), MAX(bar_seq) from output table
   - Upserts state per (id, tf, period)

**Calendar/Anchor EMA Refresher:** (e.g., `refresh_cmc_ema_cal_us.py`)

1. **Config difference:**
   ```python
   config = EMAStateConfig(
       use_canonical_ts=True,  # Canonical timestamp mode
       roll_filter="roll = FALSE",  # Filter for canonical rows
       bars_table="cmc_price_bars_multi_tf_cal_us",  # Source bars
       bars_schema="public",
   )
   ```

2. **State update with canonical timestamp** (lines 238-367: `_update_canonical_ts_mode`)
   ```sql
   WITH canonical_ts AS (
       -- Max ts WHERE roll = FALSE (canonical closes only)
       SELECT id, tf, period, MAX(ts) as last_canonical_ts
       FROM {output_table}
       WHERE roll = FALSE
       GROUP BY id, tf, period
   ),
   bar_metadata AS (
       -- Bar range and bar_seq from bars table
       SELECT id, tf,
           MIN(time_open) as daily_min_seen,
           MAX(time_close) as daily_max_seen,
           MAX(CASE WHEN is_partial_end = FALSE THEN bar_seq END) as last_bar_seq
       FROM {bars_table}
       GROUP BY id, tf
   )
   INSERT INTO {state_table} (...)
   SELECT
       p.id, p.tf, p.period,
       c.last_canonical_ts,
       c.last_canonical_ts as last_time_close,
       b.daily_min_seen, b.daily_max_seen, b.last_bar_seq,
       now()
   FROM canonical_ts c
   JOIN bar_metadata b ON c.id = b.id AND c.tf = b.tf
   ON CONFLICT (...) DO UPDATE SET ...
   ```
   - Uses `roll = FALSE` filter to track only canonical closes
   - Reads bar metadata from bars table (not EMA output table)
   - Populates both `last_canonical_ts` and `last_time_close`

### Dirty Window Handling

**Purpose:** Determine incremental query start point when state exists for some (id, tf, period) but not all

**Method:** `compute_dirty_window_starts(ids, default_start)` (lines 395-442)

**Logic:**
```python
def compute_dirty_window_starts(self, ids: list[int], default_start: str = "2010-01-01"):
    state_df = self.load_state(ids=ids)
    default_ts = pd.to_datetime(default_start, utc=True)

    result = {}
    for id_ in ids:
        id_state = state_df[state_df["id"] == id_]

        if id_state.empty:
            # No state for any (tf, period) → full rebuild
            result[id_] = default_ts
            continue

        # Use whichever timestamp is populated
        if "last_canonical_ts" in id_state.columns:
            ts_col = "last_canonical_ts"
        elif "last_time_close" in id_state.columns:
            ts_col = "last_time_close"
        else:
            result[id_] = default_ts
            continue

        # Get MINIMUM timestamp across all (tf, period) for this id
        ts_series = pd.to_datetime(id_state[ts_col], errors="coerce").dropna()

        if ts_series.empty:
            result[id_] = default_ts
        else:
            result[id_] = ts_series.min()  # Earliest across all (tf, period)

    return result
```

**Why MIN across (tf, period):**
- Different periods may have different last_time_close values
- To avoid querying too far back, use **minimum** last_time_close across all periods
- This ensures we fetch at least enough bars for the "most behind" period

**Use case:**
```python
# Script computes dirty windows
dirty_starts = manager.compute_dirty_window_starts(ids=[1, 52, 1027])
# Returns: {1: Timestamp('2024-01-01'), 52: Timestamp('2024-06-15'), ...}

for id_, start_ts in dirty_starts.items():
    # Query bars WHERE time_close >= start_ts
    # Compute EMAs from start_ts forward
    pass
```

## Key Differences: Bars vs EMAs

| Aspect | Bar Builders | EMA Refreshers |
|--------|--------------|----------------|
| **State granularity** | 1D: (id)<br>Multi-TF: (id, tf) | (id, tf, period) |
| **Watermark column** | 1D: `last_src_ts`<br>Multi-TF: `last_time_close` | Multi-TF: `last_time_close`<br>Calendar: `last_canonical_ts` |
| **Backfill detection** | 1D: None<br>Multi-TF: `daily_min_seen` comparison | Not applicable (EMAs computed from bars, not raw source) |
| **Gap handling** | 1D: No gaps (each day independent)<br>Multi-TF: Flag `is_missing_days`, continue processing | Skip bars with `is_partial_end = TRUE` or gaps during EMA computation |
| **State table location** | Same schema as bars table (public.cmc_price_bars_*_state) | Separate EMA state table (public.cmc_ema_*_state) |
| **State management** | Inline SQL upserts in builder scripts | OOP interface via EMAStateManager class |
| **Rebuild trigger** | 1D: Never (no backfill detection)<br>Multi-TF: daily_min moves earlier | Rarely needed (bars already validated); manual if bars rebuilt |
| **Incremental query** | 1D: `WHERE timestamp > (last_src_ts - lookback)`<br>Multi-TF: `WHERE ts > last_time_close + 1ms` | `WHERE time_close > last_time_close` (or last_canonical_ts) |
| **Lookback buffer** | 1D: 3 days (default `--lookback-days`)<br>Multi-TF: None (strict > comparison) | None (EMAs computed exactly from last_time_close) |

## Refresh Mode Comparison

| Mode | Trigger | Detection | Action |
|------|---------|-----------|--------|
| **First run (no state)** | State table empty or no state for (id, [tf], [period]) | Check state table | Full build: Query all source data, compute all bars/EMAs, write state |
| **Incremental (new data)** | Source max_ts > state watermark | Compare source MAX to state last_time_close | Query WHERE ts > watermark, compute new bars/EMAs, append to output, update state |
| **No-op (no new data)** | Source max_ts <= state watermark | Compare source MAX to state last_time_close | Skip processing, optionally update state updated_at timestamp |
| **Backfill (multi-TF bars only)** | Source min_ts < state daily_min_seen | Compare source MIN to state daily_min_seen | DELETE all bars for (id, tf), full rebuild from all source data, update state |
| **Full rebuild (manual)** | `--full-rebuild` flag | Flag set by user | DELETE all bars/state, rebuild from scratch (equivalent to first run) |

## Performance Considerations

### Bar Builders

**1D:**
- Single SQL statement per ID (lines 267-489: CTE pipeline)
- All processing in database: ranking, filtering, repairs, validation
- Minimal Python overhead

**Multi-TF:**
- Polars vectorization: 20-30% faster than pandas (line 176: `build_snapshots_for_id_polars`)
- Parallel processing: `--num-processes` flag (lines 1219-1304: `refresh_incremental_parallel`)
- Batch state loading: Single query per ID for all TFs (line 1014: `load_last_snapshot_info_for_id_tfs`)
- Carry-forward optimization: O(1) update when strict gate passes (lines 589-629)

### EMA Refreshers

**State loading:**
- Optional filters: Load state only for requested (ids, tfs, periods)
- Reduces memory for partial refreshes

**Dirty window computation:**
- MIN aggregation across (tf, period) avoids redundant bar queries
- Single query per ID yields start timestamp for all EMA computations

**Batch state updates:**
- Single INSERT ... ON CONFLICT for all (id, tf, period) combinations
- Populated from output table via GROUP BY (id, tf, period)

## Example: Incremental Refresh Walkthrough

**Scenario:** Multi-TF bar builder refreshing ID=1, TF=7D

**Initial state:**
```
daily_min_seen: 2024-01-01
daily_max_seen: 2024-06-30
last_bar_seq: 26
last_time_close: 2024-06-30 23:59:59.999 UTC
```

**New source data:** Daily rows through 2024-07-07 (7 new days)

**Refresh execution:**

1. **Load state and daily metadata**
   ```python
   state = load_state(db_url, state_table, ids=[1])
   # Returns: {(1, '7D'): {daily_min_seen: 2024-01-01, daily_max_seen: 2024-06-30, ...}}

   daily_mm = load_daily_min_max(db_url, daily_table, [1])
   # Returns: {1: {daily_min_ts: 2024-01-01, daily_max_ts: 2024-07-07}}
   ```

2. **Check for backfill**
   ```python
   daily_min_ts = 2024-01-01  # From source
   daily_min_seen = 2024-01-01  # From state

   if daily_min_ts < daily_min_seen:  # 2024-01-01 < 2024-01-01 → FALSE
       # No backfill → proceed to incremental
   ```

3. **Check for new data**
   ```python
   daily_max_ts = 2024-07-07  # From source
   last_time_close = 2024-06-30  # From state

   if daily_max_ts <= last_time_close:  # 2024-07-07 <= 2024-06-30 → FALSE
       # New data available → incremental append
   ```

4. **Incremental append**
   ```python
   ts_start = last_time_close + 1ms  # 2024-07-01 00:00:00
   df_new = load_daily_prices_for_id(id_=1, ts_start=ts_start)
   # Returns 7 daily rows: 2024-07-01 through 2024-07-07

   new_rows = _append_incremental_rows_for_id_tf(
       id_=1, tf_days=7, tf_label='7D',
       daily_max_ts=2024-07-07,
       last={'last_bar_seq': 26, 'last_time_close': 2024-06-30, 'last_pos_in_bar': 7}
   )
   # Bar 26 was complete (pos_in_bar=7 for 7D)
   # Create bar 27: 7 snapshot rows (pos_in_bar 1-7)
   # Returns 7 rows for bar_seq=27
   ```

5. **Upsert bars and update state**
   ```python
   upsert_bars(new_rows, db_url=db_url, bars_table=bars_table)
   # Inserts 7 snapshot rows (bar_seq=27, pos_in_bar 1-7)

   upsert_state(db_url, state_table, [{
       'id': 1, 'tf': '7D',
       'daily_min_seen': 2024-01-01,  # Unchanged
       'daily_max_seen': 2024-07-07,  # Updated
       'last_bar_seq': 27,  # Incremented
       'last_time_close': 2024-07-07  # Updated
   }])
   ```

**Result:**
- 7 new snapshot rows created (bar_seq=27, positions 1-7)
- State updated: last_bar_seq=27, last_time_close=2024-07-07
- Next run will start from 2024-07-08

## Error Handling and Edge Cases

### No source data
- **1D:** `_list_all_ids` returns empty list → no processing
- **Multi-TF:** `load_daily_min_max` returns empty DataFrame → print message and return

### State exists but no bars
- **Multi-TF:** (lines 834-861) Rebuild from scratch, trust source data over state

### Bars exist but no state
- **Multi-TF:** (lines 794-821) Full rebuild, populate state from built bars

### Incremental append fails
- **Multi-TF:** (lines 956-970) Catch exception, log error, update state to preserve last known good watermark

### Carry-forward gate fails
- **Multi-TF:** (lines 631-733) Fallback to explicit incremental math (no error)

### Time zone handling
- **All builders:** Daily data loaded with `assert_one_row_per_local_day(tz="America/New_York")` enforced
- Guarantees 1 row per calendar day in specified timezone before any bar logic
