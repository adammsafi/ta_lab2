# Bar Builders Architecture

## Overview

The bar builders create multi-timeframe OHLCV bar snapshots from daily price data. After refactoring (Jan 2026), the codebase uses two key abstractions to eliminate code duplication and improve maintainability:

1. **Polars Utilities** (`polars_bar_operations.py`) - Reusable vectorized operations
2. **Multiprocessing Orchestrator** (`ta_lab2.orchestration`) - Generic parallel execution

## Quick Start: Running All Builders

### Master Orchestrator Script

Use `run_all_bar_builders.py` to execute multiple builders with unified configuration:

```bash
# Run all builders for specific IDs
python run_all_bar_builders.py --ids 1,52,825

# Run all builders with full rebuild
python run_all_bar_builders.py --ids all --full-rebuild

# Run only specific builders
python run_all_bar_builders.py --ids all --builders 1d,multi_tf,cal_iso

# Skip specific builders
python run_all_bar_builders.py --ids all --skip cal_anchor_iso,cal_anchor_us

# Continue even if a builder fails
python run_all_bar_builders.py --ids all --continue-on-error

# Dry run (show commands without executing)
python run_all_bar_builders.py --ids all --dry-run
```

### Available Builders

| Builder | Description | Supports Full Rebuild |
|---------|-------------|----------------------|
| `1d` | 1D canonical bars (SQL-based) | Yes |
| `multi_tf` | Multi-timeframe rolling bars | Yes |
| `cal_iso` | Calendar-aligned (ISO week) | Yes |
| `cal_us` | Calendar-aligned (US week) | Yes |
| `cal_anchor_iso` | Calendar-anchored with partial snapshots (ISO) | Yes |
| `cal_anchor_us` | Calendar-anchored with partial snapshots (US) | Yes |

### Common Options

- `--ids` - Comma-separated ID list or "all" (required)
- `--db-url` - Database URL (default: TARGET_DB_URL env var)
- `--full-rebuild` - Run full rebuild for all builders
- `--num-processes` - Number of parallel processes for multi-TF builders
- `--tz` - Timezone for calendar builders (default: America/New_York)
- `--continue-on-error` - Continue running other builders if one fails
- `--verbose` - Show builder output (default: only show on error)

## Architecture Layers

```
┌─────────────────────────────────────────────────────────┐
│            Bar Builder Scripts (5 variants)             │
│  - refresh_cmc_price_bars_multi_tf.py                  │
│  - refresh_cmc_price_bars_multi_tf_cal_iso.py          │
│  - refresh_cmc_price_bars_multi_tf_cal_us.py           │
│  - refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py   │
│  - refresh_cmc_price_bars_multi_tf_cal_anchor_us.py    │
└─────────────────────────────────────────────────────────┘
                        │ uses
                        ▼
┌─────────────────────────────────────────────────────────┐
│         Polars Bar Operations (Pure Functions)          │
│  - apply_ohlcv_cumulative_aggregations()               │
│  - compute_extrema_timestamps_*()                      │
│  - compute_day_time_open()                             │
│  - compute_missing_days_gaps()                         │
│  - apply_standard_polars_pipeline()                    │
└─────────────────────────────────────────────────────────┘
                        │
                        │ uses in parallel
                        ▼
┌─────────────────────────────────────────────────────────┐
│      MultiprocessingOrchestrator (Generic Pattern)      │
│  - Task preparation & filtering                        │
│  - Parallel/serial execution with Pool                 │
│  - Result aggregation (state_updates + stats)          │
│  - Progress tracking with rate/ETA                     │
│  - Error resilience                                    │
└─────────────────────────────────────────────────────────┘
```

## Refactoring Impact

### Before (Jan 2026)

- **Code duplication**: ~60% of each builder was identical
  - Multiprocessing boilerplate: 15-20 lines × 5 builders = 75-100 lines
  - Polars operations: 120 lines × 5 builders = 600 lines
  - Manual result aggregation loops
  - No progress tracking

- **Maintenance burden**: Bug fixes required changes in 5-6 files
- **Inconsistency**: Each builder had slightly different error handling

### After (Current)

- **Single source of truth**: Polars utilities + orchestrator
- **Code reduction**: ~510 lines eliminated across 5 builders
- **New features**: Built-in progress tracking with rate/ETA display
- **Consistency**: All builders use the same execution pattern
- **Type safety**: Generic orchestrator with Protocol definitions

## Using the Polars Utilities

### Basic Pattern

```python
from ta_lab2.scripts.bars.polars_bar_operations import (
    normalize_timestamps_for_polars,
    apply_standard_polars_pipeline,
    restore_utc_timezone,
    compact_output_types,
)

# 1. Prepare pandas DataFrame for Polars
df = normalize_timestamps_for_polars(df_daily)

# 2. Convert to Polars and add builder-specific columns (e.g., bar_seq)
pl_df = pl.from_pandas(df).sort("ts")
pl_df = pl_df.with_columns([...])  # Add bar_seq, etc.

# 3. Apply standard pipeline (OHLCV aggregations, extrema, missing days)
pl_df = apply_standard_polars_pipeline(
    pl_df,
    group_col="bar_seq",
    include_missing_days=True,
)

# 4. Convert back to pandas
out = pl_df.select([...]).to_pandas()

# 5. Restore timezone and compact types
out = restore_utc_timezone(out)
out = compact_output_types(out)
```

### Available Functions

#### Database Loading Utilities (from common_snapshot_contract.py)

**NEW: These utilities were extracted from all 5 builders (Jan 2026)**

##### `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start=None, tz="America/New_York")`
Load daily OHLCV rows for a single cryptocurrency with validation.
- Enforces 1-row-per-local-day invariant
- Normalizes timestamp columns to UTC
- Optionally filters by start timestamp
- **Identical across all 5 builders** - extracted to eliminate duplication

##### `delete_bars_for_id_tf(db_url, bars_table, *, id_, tf)`
Delete all bar snapshots for a specific (id, tf) combination.
- Used in full rebuild mode

##### `load_last_snapshot_row(db_url, bars_table, *, id_, tf)`
Load the most recent snapshot row for (id, tf).
- Returns dict or None
- Used for incremental updates

##### `load_last_snapshot_info_for_id_tfs(db_url, bars_table, *, id_, tfs)`
**Batch-load** latest snapshot info for multiple timeframes in 1 query.
- Uses PostgreSQL `DISTINCT ON` for efficiency
- Returns: `{tf: {last_bar_seq, last_time_close}}`
- **Critical for performance**: 1 query instead of N queries

#### Polars Bar Operations

##### `normalize_timestamps_for_polars(df)`
Converts timestamps to UTC and strips timezone info for Polars compatibility.

#### `apply_ohlcv_cumulative_aggregations(pl_df, group_col="bar_seq")`
Applies OHLCV aggregations within each bar:
- `open_bar`: First open in bar
- `close_bar`: Last close in bar
- `high_bar`: Cumulative max high
- `low_bar`: Cumulative min low
- `vol_bar`: Cumulative sum volume
- `mc_bar`: Forward-filled market cap

#### `compute_extrema_timestamps_with_new_extreme_detection(pl_df, ...)`
Computes `time_high` and `time_low` with proper new-extreme reset behavior.
**Critical**: Correctly handles the case where a new extreme replaces an old one.

#### `compute_day_time_open(pl_df, ts_col="ts")`
Computes `day_time_open` as previous timestamp + 1ms.

#### `compute_missing_days_gaps(pl_df, group_col="bar_seq", ts_col="ts")`
Calculates `missing_incr` and `count_missing_days` based on timestamp gaps.

#### `compact_output_types(df)`
Reduces memory usage by converting int64→int32 and object→bool.

#### `restore_utc_timezone(df, ts_cols=...)`
Re-adds UTC timezone after Polars round-trip.

#### `apply_standard_polars_pipeline(pl_df, ...)`
High-level pipeline that composes all operations in the correct order.

## Using the Orchestrator

### Basic Pattern

```python
from ta_lab2.orchestration import (
    MultiprocessingOrchestrator,
    OrchestratorConfig,
    ProgressTracker,
)

# 1. Prepare tasks (list of tuples/objects to process)
tasks = [
    (id_, db_url, daily_table, bars_table, state_table, tf_list, ...),
    ...
]

# 2. Configure orchestrator
config = OrchestratorConfig(
    num_processes=6,           # Or None for auto-detect
    maxtasksperchild=50,       # Worker restart interval
    use_imap_unordered=True,   # Stream results (good for long tasks)
)

# 3. Set up progress tracking
progress = ProgressTracker(
    total=len(tasks),
    log_interval=5,            # Log every 5 completions
    prefix="[my_builder]",
)

# 4. Create orchestrator
orchestrator = MultiprocessingOrchestrator(
    worker_fn=my_worker_function,
    config=config,
    progress_callback=progress.update,
)

# 5. Execute tasks
all_state_updates, totals = orchestrator.execute(
    tasks,
    stats_template={"upserted": 0, "rebuilds": 0, "errors": 0}
)
```

### Worker Function Contract

```python
def my_worker_function(task: TTask) -> tuple[list[TStateUpdate], TStats]:
    """
    Process a single task.

    Args:
        task: Task data (typically a tuple of arguments)

    Returns:
        Tuple of (state_updates, stats) where:
        - state_updates: List of state records to upsert
        - stats: Dictionary of statistics {"upserted": N, "errors": M, ...}
    """
    # Process task...
    state_updates = [{"id": 1, "tf": "7d", ...}]
    stats = {"upserted": 1, "errors": 0}
    return (state_updates, stats)
```

### Error Resilience

For workers that may fail, wrap them with error handling:

```python
from ta_lab2.orchestration import create_resilient_worker

stats_template = {"upserted": 0, "errors": 0}
safe_worker = create_resilient_worker(
    my_worker_function,
    stats_template,
    error_logger=my_logger,  # Optional custom logger
)

orchestrator = MultiprocessingOrchestrator(worker_fn=safe_worker, ...)
```

## Builder Variants

### 1. `refresh_cmc_price_bars_multi_tf.py`
- **Window type**: Row-count based (tf_days)
- **Anchoring**: Data-start (first available row per ID)
- **Semantics**: Simplest variant, no calendar alignment

### 2. `refresh_cmc_price_bars_multi_tf_cal_iso.py`
- **Window type**: Calendar-aligned (ISO weeks/months/years)
- **Week start**: Monday
- **Partial bars**: Start/end bars excluded (no partial periods)

### 3. `refresh_cmc_price_bars_multi_tf_cal_us.py`
- **Window type**: Calendar-aligned (US weeks/months/years)
- **Week start**: Sunday
- **Partial bars**: Start/end bars excluded

### 4. `refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py`
- **Window type**: Calendar-aligned + anchored (ISO)
- **Anchoring**: Fixed reference date (1970-01-05 Monday)
- **Partial bars**: Allowed (with diagnostics)

### 5. `refresh_cmc_price_bars_multi_tf_cal_anchor_us.py`
- **Window type**: Calendar-aligned + anchored (US)
- **Anchoring**: Fixed reference date (1970-01-04 Sunday)
- **Partial bars**: Allowed (with diagnostics)

## Adding a New Builder

### Step 1: Determine Requirements

1. What type of window? (row-count, calendar, anchored)
2. What timezone? (default: America/New_York)
3. Allow partial bars? (start/end of series)
4. What diagnostic fields? (missing_days, gaps, etc.)

### Step 2: Create Script Structure

```python
# Standard imports
from ta_lab2.scripts.bars.polars_bar_operations import (
    normalize_timestamps_for_polars,
    apply_standard_polars_pipeline,
    restore_utc_timezone,
    compact_output_types,
)
from ta_lab2.orchestration import (
    MultiprocessingOrchestrator,
    OrchestratorConfig,
    ProgressTracker,
)
from ta_lab2.scripts.bars.common_snapshot_contract import (
    # Import shared utilities...
)

# Define worker function
def _process_single_id_with_all_specs(args: tuple) -> tuple[list[dict], dict]:
    """Process one ID across all TF specs."""
    # Unpack args, process, return (state_updates, stats)
    ...

# Define main refresh function
def refresh_incremental(...):
    """Incremental refresh with orchestrator."""
    # Prepare tasks
    tasks = [...]

    # Use orchestrator
    config = OrchestratorConfig(num_processes=num_processes)
    progress = ProgressTracker(total=len(tasks), prefix="[my_builder]")
    orchestrator = MultiprocessingOrchestrator(
        worker_fn=_process_single_id_with_all_specs,
        config=config,
        progress_callback=progress.update,
    )

    all_state_updates, totals = orchestrator.execute(
        tasks,
        stats_template={"upserted": 0, "errors": 0}
    )

    # Upsert state
    upsert_state(db_url, state_table, all_state_updates)
    ...
```

### Step 3: Implement Builder-Specific Logic

The **only** parts that should differ between builders:

1. **TF spec loading**: How to query `dim_timeframe` or define TF list
2. **Bar assignment**: How to compute `bar_seq` (row-count vs calendar)
3. **Polars pipeline usage**: Which utilities to use and in what order

Everything else (Pool management, result aggregation, CLI parsing) should use the shared abstractions.

### Step 4: Test and Validate

```bash
# 1. Verify script parses
python my_new_builder.py --help

# 2. Test with small dataset
python my_new_builder.py --ids 1,52,825 --db-url ...

# 3. Compare output to expected (if migrating from old script)
# 4. Run full dataset

# 5. Verify progress tracking works
# (Should see "[my_builder] 5/100 (5.0%) | Rate: 2.3/s | ETA: 41s | ..." logs)
```

## Performance Characteristics

### Polars Utilities

- **Speedup**: 20-30% faster than pandas for large datasets (>10K rows)
- **Memory**: ~40% reduction via type compaction (int64→int32)
- **Overhead**: Negligible for small datasets (<1K rows)

### Orchestrator

- **Parallel efficiency**: Near-linear scaling up to 6-8 workers
- **Task granularity**: Optimized for per-ID tasks (typical: 1-10 seconds each)
- **Progress tracking**: <1% overhead with log_interval=5
- **Serial fallback**: Automatic when `num_processes=1`

### Typical Performance

| Builder | Mode | IDs | TFs | Time | Throughput |
|---------|------|-----|-----|------|------------|
| multi_tf | Incremental | 100 | 10 | ~5 min | ~200 (id,tf)/min |
| multi_tf | Full rebuild | 100 | 10 | ~15 min | ~67 (id,tf)/min |
| cal_iso | Incremental | 100 | 8 | ~4 min | ~200 (id,tf)/min |

## Migration Guide (Historical)

### Pre-Refactoring (Before Jan 2026)

Each builder had:
- Custom Pool management (~15 lines)
- Manual result aggregation loops (~10 lines)
- Duplicated Polars operations (~120 lines)
- No progress tracking

### Post-Refactoring (Current)

Same builders use:
- `OrchestratorConfig` + `orchestrator.execute()` (8 lines)
- `apply_standard_polars_pipeline()` (1 line + setup)
- Built-in progress tracking

### Key Differences

**Before:**
```python
with Pool(processes=nproc, maxtasksperchild=50) as pool:
    for state_updates, stats in pool.imap_unordered(worker_fn, tasks):
        all_state_updates.extend(state_updates)
        totals["upserted"] += int(stats.get("upserted", 0))
        totals["rebuilds"] += int(stats.get("rebuilds", 0))
        # ... more manual accumulation
```

**After:**
```python
config = OrchestratorConfig(num_processes=nproc, use_imap_unordered=True)
progress = ProgressTracker(total=len(tasks), prefix="[builder]")
orchestrator = MultiprocessingOrchestrator(
    worker_fn=worker_fn,
    config=config,
    progress_callback=progress.update,
)
all_state_updates, totals = orchestrator.execute(
    tasks,
    stats_template={"upserted": 0, "rebuilds": 0, ...}
)
```

## Troubleshooting

### Import Errors

If you see `ImportError: cannot import name 'MultiprocessingOrchestrator'`:
- Verify `src/ta_lab2/orchestration/` exists
- Check `__init__.py` has correct exports

### Polars Type Errors

If you see `polars.exceptions.SchemaError: unable to add timezone`:
- Ensure you call `normalize_timestamps_for_polars()` before Polars conversion
- Ensure you call `restore_utc_timezone()` after Polars conversion

### Progress Tracking Not Showing

If progress logs don't appear:
- Check `log_interval` setting (default: 10 completions)
- Ensure `progress_callback` is passed to orchestrator
- Verify tasks are actually completing (check for exceptions)

### Performance Regression

If builds are slower after refactoring:
- Check `maxtasksperchild` is set correctly (default: 50)
- Verify `use_imap_unordered=True` for streaming tasks
- Profile with `--num-processes=1` to isolate worker performance

## Testing

### Unit Tests

```bash
# Test Polars utilities
pytest tests/test_polars_bar_operations.py -v

# Test orchestrator
pytest tests/orchestration/test_multiprocessing_orchestrator.py -v
```

### Integration Tests

```bash
# Test specific builder
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py \
    --ids 1,52,825 \
    --db-url "postgresql://..." \
    --num-processes 2

# Verify progress logs appear
# Verify state table updated correctly
```

## References

- Original refactoring plan: `.planning/phases/03-06-SUMMARY.md`
- Polars utilities: `src/ta_lab2/scripts/bars/polars_bar_operations.py`
- Orchestration module: `src/ta_lab2/orchestration/`
- Test suite: `tests/test_polars_bar_operations.py`, `tests/orchestration/`

## Future Improvements

### Potential Enhancements

1. **BaseBuilder abstract class** - Template method pattern for builder structure
2. **Streaming result upsert** - Write state updates during execution (not after)
3. **Dynamic worker count** - Adjust num_processes based on system load
4. **Retry logic** - Automatic retry for transient database errors
5. **Metrics collection** - Detailed performance metrics per-builder

### Non-Goals

- **Over-abstraction**: Don't force-fit builders into a single class if logic diverges
- **Premature optimization**: Keep it simple; optimize only bottlenecks
- **Breaking changes**: Maintain backward compatibility with existing state tables

---

**Last updated**: January 2026
**Maintainer**: Data Engineering Team
**Related docs**: `docs/EMA_STATE_STANDARDIZATION.md`
