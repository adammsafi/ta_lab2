# Complete Rebuild Instructions

## Overview

This will drop ALL bar and EMA tables and rebuild everything from scratch.

**Total estimated time: ~3 hours**
- Bar builders: ~45 minutes
- EMA refreshers: ~2 hours

## What Gets Deleted

### Bar Tables (19 tables)
- All `cmc_price_bars_*` tables (1d, multi_tf, cal_iso, cal_us, cal_anchor_iso, cal_anchor_us)
- All bar state tables
- All bar snapshots and backups

### EMA Tables (17 tables)
- All `cmc_ema_*` tables (daily, multi_tf, v2, calendar variants)
- All EMA state tables
- All EMA snapshots

### Stats Tables (9 tables)
- All `ema_*_stats` tables
- All stats state tables

**Total: 45 tables will be dropped**

## Quick Start

### Option 1: Automated (Recommended)

Run the batch file which handles everything:

```bash
rebuild_all.bat
```

This will:
1. Drop all tables
2. Recreate dimension tables
3. Run all bar builders
4. Run all EMA refreshers

### Option 2: Manual Step-by-Step

#### Step 1: Drop All Tables

```bash
psql -U postgres -d marketdata -f sql/ddl/drop_all_bars_and_emas.sql
```

#### Step 2: Recreate Dimension Tables

```bash
psql -U postgres -d marketdata -f sql/ddl/create_dim_assets.sql
psql -U postgres -d marketdata -f sql/ddl/create_dim_timeframe.sql
psql -U postgres -d marketdata -f sql/ddl/create_dim_period.sql
psql -U postgres -d marketdata -f sql/ddl/create_ema_alpha_lookup.sql
```

#### Step 3: Build Bar Tables (~45 minutes)

```bash
python src/ta_lab2/scripts/bars/run_all_bar_builders.py --ids all
```

This builds:
- cmc_price_bars_1d (SQL-based, 7 assets × 1 TF)
- cmc_price_bars_multi_tf (7 assets × 119 TF = 833 combos)
- cmc_price_bars_multi_tf_cal_iso (calendar ISO)
- cmc_price_bars_multi_tf_cal_us (calendar US)
- cmc_price_bars_multi_tf_cal_anchor_iso (calendar anchor ISO)
- cmc_price_bars_multi_tf_cal_anchor_us (calendar anchor US)

#### Step 4: Build EMA Tables (~2 hours)

```bash
python src/ta_lab2/scripts/emas/run_all_ema_refreshes.py --ids all --periods all
```

This builds:
- cmc_ema_multi_tf (rolling EMAs)
- cmc_ema_multi_tf_v2 (calendar EMAs)
- cmc_ema_multi_tf_cal_iso (calendar ISO EMAs)
- cmc_ema_multi_tf_cal_us (calendar US EMAs)
- cmc_ema_multi_tf_cal_anchor_iso (calendar anchor ISO EMAs)
- cmc_ema_multi_tf_cal_anchor_us (calendar anchor US EMAs)

## Verification

After rebuild completes, verify row counts:

```bash
python -m ta_lab2.tools.dbtool query "
SELECT
    'cmc_price_bars_multi_tf' as table_name,
    COUNT(*) as rows,
    COUNT(DISTINCT id) as assets,
    COUNT(DISTINCT tf) as timeframes
FROM cmc_price_bars_multi_tf
"
```

**Expected results:**
- Rows: ~2,656,318
- Assets: 7
- Timeframes: 119

```bash
python -m ta_lab2.tools.dbtool query "
SELECT
    'cmc_ema_multi_tf' as table_name,
    COUNT(*) as rows,
    COUNT(DISTINCT id) as assets,
    COUNT(DISTINCT period) as periods
FROM cmc_ema_multi_tf
"
```

## Troubleshooting

### If bar builders fail:
- Check database connection
- Verify dim_assets, dim_sessions exist
- Check logs for specific error

### If EMA refreshers fail:
- Ensure bar tables built successfully first
- Check that ema_alpha_lookup table exists
- Verify dim_period table exists

### If you need to rebuild just one component:

**Just bars:**
```bash
python src/ta_lab2/scripts/bars/run_all_bar_builders.py --ids all
```

**Just EMAs:**
```bash
python src/ta_lab2/scripts/emas/run_all_ema_refreshes.py --ids all --periods all
```

**Just one bar builder:**
```bash
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py --ids all --full-rebuild
```

**Just one EMA refresher:**
```bash
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf.py --ids all --periods all --full-refresh
```

## Notes

- All dimension tables (dim_assets, dim_timeframe, etc.) are preserved
- Source data (cmc_price_histories7) is preserved
- This only affects derived/computed tables (bars and EMAs)
- State tables will be recreated automatically during rebuild
- The rebuild uses the CURRENT (Phase 24 refactored) code
