# EMA Table Auto-Creation Feature

## Overview

All EMA refresher scripts now automatically create their output tables if they don't exist. This eliminates the need to run separate DDL scripts before running the EMA refreshers.

## What Changed

### 1. New Function: `ensure_ema_table_exists()`

Located in: `src/ta_lab2/scripts/emas/base_ema_refresher.py`

This function:
- Generates `CREATE TABLE IF NOT EXISTS` DDL for any EMA table type
- Includes all columns, constraints, indexes, and partial unique indexes
- Uses schema information extracted from production tables via dbtool

### 2. Updated Base Class

Located in: `src/ta_lab2/scripts/emas/base_ema_refresher.py`

Changes:
- Added `get_table_type()` method to determine table schema type
- Added `_ensure_output_table_exists()` to actually create tables
- Added table creation call in `__init__()` method (before any computation)

### 3. Supported Table Types

| Table Name | Type | Auto-Detected? | Columns |
|------------|------|----------------|---------|
| `cmc_ema_multi_tf` | `multi_tf` | Yes (default) | 12 |
| `cmc_ema_multi_tf_v2` | `v2` | Yes (contains "_v2") | 12 |
| `cmc_ema_multi_tf_cal_iso` | `cal` | Yes (contains "_cal_") | 18 |
| `cmc_ema_multi_tf_cal_us` | `cal` | Yes (contains "_cal_") | 18 |
| `cmc_ema_multi_tf_cal_anchor_iso` | `cal_anchor` | Yes (contains "cal_anchor") | 18 |
| `cmc_ema_multi_tf_cal_anchor_us` | `cal_anchor` | Yes (contains "cal_anchor") | 18 |

## Usage

### Running EMA Refreshers

No changes needed! Just run the scripts as before:

```bash
# Individual script
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py --ids all --periods all --full-refresh

# Or via orchestrator
python src/ta_lab2/scripts/emas/run_all_ema_refreshes.py --ids all --periods all
```

Tables will be created automatically on first run.

### Custom Table Type

If you create a new EMA refresher subclass, you can override `get_table_type()`:

```python
class MyCustomEMARefresher(BaseEMARefresher):
    def get_table_type(self) -> str:
        return "multi_tf"  # or "v2", "cal", "cal_anchor"
```

## DDL Details

### Multi-TF Tables (12 columns)
- Primary key: `(id, ts, tf, period)`
- Columns: id (INTEGER), ts, tf, period, ema, ingested_at, d1, d2, tf_days, roll, d1_roll, d2_roll
- Partial index for roll=TRUE queries
- Unique partial index for canonical (roll=FALSE) rows

### V2 Tables (12 columns)
- Primary key: `(id, ts, tf, period)`
- Columns: Same as multi_tf but id is BIGINT, tf_days and roll are NOT NULL
- Index on `(id, tf, period, ts)`
- Unique partial index for canonical rows

### Calendar Tables (18 columns)
- Primary key: `(id, tf, ts, period)`
- Additional columns: ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar
- Indexes on `(id, ts)` and `(tf, ts)`
- Unique partial index for canonical rows

### Calendar Anchor Tables (18 columns)
- Identical schema to calendar tables
- Same indexes and constraints

## Tables Already Auto-Created

These tables were ALREADY created automatically in the base refresher:
- **State tables** - Created by `EMAStateManager.ensure_state_table()`
- **Rejects tables** - Created by `_ensure_rejects_table()` (if validation enabled)

**New:** Output tables now also auto-created!

## Testing

Run the test script to verify DDL generation:

```bash
python test_ema_table_ddl.py
```

This generates DDL for all 6 EMA table types without connecting to a database.

## Benefits

1. **Zero Setup** - No need to run DDL scripts before EMA refreshers
2. **Consistency** - DDL matches production schema exactly
3. **Maintainability** - Schema changes in one place
4. **Flexibility** - Works for standalone scripts and orchestrator
5. **Idempotent** - Safe to run multiple times (CREATE IF NOT EXISTS)

## Implementation Details

### Schema Extraction

Schemas were extracted from production using dbtool:

```bash
python -m ta_lab2.tools.dbtool describe public cmc_ema_multi_tf
python -m ta_lab2.tools.dbtool indexes public cmc_ema_multi_tf
python -m ta_lab2.tools.dbtool describe public cmc_ema_multi_tf_v2
python -m ta_lab2.tools.dbtool describe public cmc_ema_multi_tf_cal_iso
```

### Type Detection Logic

```python
def get_table_type(self) -> str:
    table_name = self.config.output_table.lower()

    if "_v2" in table_name:
        return "v2"
    elif "cal_anchor" in table_name:
        return "cal_anchor"
    elif "_cal_" in table_name:
        return "cal"
    else:
        return "multi_tf"
```

### Execution Flow

```
BaseEMARefresher.__init__()
  ↓
_ensure_output_table_exists()  ← NEW!
  ↓
get_table_type() → DDL generation → CREATE TABLE IF NOT EXISTS
  ↓
_ensure_rejects_table() (if validation enabled)
  ↓
ready for computation
```

## Backward Compatibility

This change is **100% backward compatible**:

- Existing tables are NOT modified (CREATE IF NOT EXISTS)
- All existing DDL scripts still work
- Scripts can still be run independently
- No changes to orchestrator behavior
- State and rejects tables still auto-created as before

## Complete Rebuild Workflow

With both bar and EMA auto-creation, the complete rebuild is now simpler:

```bash
# 1. Drop all tables
psql -U postgres -d marketdata -f sql/ddl/drop_all_bars_and_emas.sql

# 2. Create dimension tables (still required)
psql -U postgres -d marketdata -f sql/ddl/create_dim_assets.sql
psql -U postgres -d marketdata -f sql/ddl/create_dim_timeframe.sql
psql -U postgres -d marketdata -f sql/ddl/create_dim_period.sql
psql -U postgres -d marketdata -f sql/ddl/create_ema_alpha_lookup.sql

# 3. Run builders - ALL tables auto-created!
python src/ta_lab2/scripts/bars/run_all_bar_builders.py --ids all
python src/ta_lab2/scripts/emas/run_all_ema_refreshes.py --ids all --periods all
```

Or use the unified rebuild script:

```bash
rebuild_all.bat
```

## Future Enhancements

Possible improvements:
- Add migration support for schema changes
- Add table validation (check schema matches expected)
- Support custom schemas beyond "public"
- Auto-create stats tables similarly
