# Bar Table Auto-Creation Feature

## Overview

All 6 bar builder scripts now automatically create their output tables if they don't exist. This eliminates the need to run separate DDL scripts before running the bar builders.

## What Changed

### 1. New Function: `ensure_bar_table_exists()`

Located in: `src/ta_lab2/scripts/bars/common_snapshot_contract.py`

This function:
- Generates `CREATE TABLE IF NOT EXISTS` DDL for any bar table type
- Includes all columns, constraints, indexes, and check constraints
- Uses schema information extracted from production tables via dbtool

### 2. Updated Base Class

Located in: `src/ta_lab2/scripts/bars/base_bar_builder.py`

Changes:
- Added `get_table_type()` method to determine table schema type
- Updated `ensure_output_table_exists()` to actually create tables
- Added table creation call in `run()` method

### 3. Supported Table Types

| Table Name | Type | Auto-Detected? |
|------------|------|----------------|
| `cmc_price_bars_1d` | `1d` | Yes (contains "_1d") |
| `cmc_price_bars_multi_tf` | `multi_tf` | Yes (default) |
| `cmc_price_bars_multi_tf_cal_iso` | `cal` | Yes (contains "_cal_") |
| `cmc_price_bars_multi_tf_cal_us` | `cal` | Yes (contains "_cal_") |
| `cmc_price_bars_multi_tf_cal_anchor_iso` | `cal_anchor` | Yes (contains "cal_anchor") |
| `cmc_price_bars_multi_tf_cal_anchor_us` | `cal_anchor` | Yes (contains "cal_anchor") |

## Usage

### Running Bar Builders

No changes needed! Just run the scripts as before:

```bash
# Individual script
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py --ids all --full-rebuild

# Or via orchestrator
python src/ta_lab2/scripts/bars/run_all_bar_builders.py --ids all
```

Tables will be created automatically on first run.

### Custom Table Type

If you create a new bar builder subclass, you can override `get_table_type()`:

```python
class MyCustomBarBuilder(BaseBarBuilder):
    def get_table_type(self) -> str:
        return "multi_tf"  # or "1d", "cal", "cal_anchor"
```

## DDL Details

### 1D Tables
- Primary key: `(id, timestamp)`
- Unique constraint: `(id, tf, bar_seq)`
- 22 columns including repair flags
- Indexes on `(id, tf, time_close)`

### Multi-TF Tables
- Primary key: `(id, tf, bar_seq, time_close)`
- 30 columns including snapshot metadata
- 6 indexes for query performance
- 2 unique partial indexes for canonical bars
- CHECK constraints for OHLC validation

### Calendar Tables
- Primary key: `(id, tf, bar_seq, time_close)`
- 30 columns similar to multi-TF
- Optimized for calendar-aligned queries
- `first_missing_day`/`last_missing_day` are DATE type

### Calendar Anchor Tables
- Primary key: `(id, tf, bar_seq, time_close)`
- 31 columns (includes `bar_anchor_offset`)
- 9 indexes for anchor-based queries
- Unique partial index for canonical bars

## Testing

Run the test script to verify DDL generation:

```bash
python test_bar_table_ddl.py
```

This generates DDL for all 6 table types without connecting to a database.

## Benefits

1. **Zero Setup** - No need to run DDL scripts before bar builders
2. **Consistency** - DDL matches production schema exactly
3. **Maintainability** - Schema changes in one place
4. **Flexibility** - Works for standalone scripts and orchestrator
5. **Idempotent** - Safe to run multiple times (CREATE IF NOT EXISTS)

## Implementation Details

### Schema Extraction

Schemas were extracted from production using dbtool:

```bash
python -m ta_lab2.tools.dbtool describe public cmc_price_bars_multi_tf
python -m ta_lab2.tools.dbtool indexes public cmc_price_bars_multi_tf
python -m ta_lab2.tools.dbtool constraints public cmc_price_bars_multi_tf
```

### Type Detection Logic

```python
def get_table_type(self) -> str:
    table_name = self.get_output_table_name().lower()

    if "_1d" in table_name:
        return "1d"
    elif "cal_anchor" in table_name:
        return "cal_anchor"
    elif "_cal_" in table_name:
        return "cal"
    else:
        return "multi_tf"
```

## Backward Compatibility

This change is **100% backward compatible**:

- Existing tables are NOT modified (CREATE IF NOT EXISTS)
- All existing DDL scripts still work
- Scripts can still be run independently
- No changes to orchestrator behavior

## Future Enhancements

Possible improvements:
- Add migration support for schema changes
- Generate DDL for EMA tables similarly
- Add table validation (check schema matches expected)
- Support custom schemas beyond "public"
