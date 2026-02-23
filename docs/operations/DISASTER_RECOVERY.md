# Disaster Recovery Guide

This guide covers two recovery scenarios in priority order:

1. **Scenario 1: Restore from backup** — DB is lost or corrupted; a recent `pg_dump` backup exists.
2. **Scenario 2: Full rebuild from scratch** — No backup available (or intentional clean-slate rebuild).

No automated backup exists yet — this documents manual procedures. Automated daily backups are recommended as a future improvement.

---

## Prerequisites

**Environment variable (required):**

```bash
export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"
```

Fallback lookup order used by all ta_lab2 scripts:
1. `$TARGET_DB_URL`
2. `$DB_URL`
3. `$MARKETDATA_DB_URL`

**Python environment:**

```bash
source venv/bin/activate       # Linux/macOS
venv\Scripts\activate          # Windows
pip install -e ".[all]"        # verify install
```

**PostgreSQL client tools required:**

```bash
psql --version    # query tool + schema creation
pg_dump --version # backup creation
createdb --version # database creation
```

---

## Scenario 1: Restore from Backup

Use this scenario when: the database is lost or corrupted and you have a recent `pg_dump` backup file.

### Creating a Backup (while DB is healthy)

Run this regularly. Recommended: daily cron job.

```bash
# Create compressed backup
pg_dump ta_lab2 | gzip > /backups/ta_lab2_$(date +%Y%m%d).sql.gz

# Recommended cron schedule (daily at 2 AM)
# crontab -e
# 0 2 * * * pg_dump ta_lab2 | gzip > /backups/ta_lab2_$(date +\%Y\%m\%d).sql.gz
```

Store backups off-machine (separate server, cloud storage). A backup on the same machine as the DB provides no protection against host failure.

### Restoring from Backup

```bash
# If the database still exists but is corrupted, drop and recreate first:
# dropdb ta_lab2
# createdb ta_lab2

# Restore from compressed backup
gunzip -c /backups/ta_lab2_20260201.sql.gz | psql ta_lab2
```

### Verification After Restore

Run these queries to confirm key tables have data:

```sql
SELECT COUNT(*) as price_rows      FROM public.cmc_price_histories7;
SELECT COUNT(*) as bar_rows        FROM public.cmc_price_bars_multi_tf;
SELECT COUNT(*) as ema_rows        FROM public.cmc_ema_multi_tf_u;
SELECT COUNT(*) as feature_rows    FROM public.cmc_features;
SELECT COUNT(*) as regime_rows     FROM public.cmc_regimes;
```

Cross-check row counts against your last known good values. If any table shows 0 rows unexpectedly, the backup may be partial.

### After Restore: Catch Up to Present

Run an incremental refresh to bring all derived data up to the current date:

```bash
python -m ta_lab2.scripts.run_daily_refresh --all --verbose
```

### Alembic Migration State (if Phase 33 is complete)

If Alembic migrations have been set up, mark the migration state as current after restore to prevent Alembic from re-applying migrations:

```bash
alembic stamp head
```

---

## Scenario 2: Full Rebuild from Scratch

Use this scenario when: no backup exists, or you want a clean-slate rebuild from source data.

This is the nuclear option. Source data is CoinMarketCap price history; all derived tables are recomputable. Expect several hours for a full rebuild with many assets.

Pipeline order: **Schema -> Source ingest -> Bars -> EMAs -> Features -> Regimes -> Signals**

---

### Phase A: Schema Creation

Create the database and all tables in dependency order. Every command uses `psql` directly — do not use Python's `open()` with default encoding on Windows, as SQL files with UTF-8 box-drawing characters in comments will cause `UnicodeDecodeError` with the default `cp1252` encoding.

**Step 1: Create database**

```bash
createdb ta_lab2
```

**Step 2: Create observability schema**

```bash
psql -d ta_lab2 -f sql/ddl/create_observability_schema.sql
```

**Step 3: Create dimension tables** (dim_timeframe, dim_sessions)

```bash
python -m ta_lab2.scripts.setup.ensure_dim_tables
```

**Step 4: Create dim_assets**

```bash
psql -d ta_lab2 -f sql/ddl/create_dim_assets.sql
```

**Step 5: Create dim_signals** (signal configurations + seed data)

```bash
psql -d ta_lab2 -f sql/lookups/030_dim_signals.sql
```

**Step 6: Create price bar tables** (6 files: base + 4 calendar variants + unified)

```bash
psql -d ta_lab2 -f sql/ddl/price_bars__cmc_price_bars_multi_tf.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_price_bars_1d_state.sql
psql -d ta_lab2 -f sql/features/031_cmc_price_bars_multi_tf_cal_iso.sql
psql -d ta_lab2 -f sql/features/031_cmc_price_bars_multi_tf_cal_us.sql
psql -d ta_lab2 -f sql/features/033_cmc_price_bars_multi_tf_cal_anchor_us.sql
psql -d ta_lab2 -f sql/features/034_cmc_price_bars_multi_tf_cal_anchor_iso.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_price_bars_multi_tf_u.sql
```

**Step 7: Create EMA tables**

```bash
psql -d ta_lab2 -f sql/ddl/create_cmc_ema_refresh_state.sql
psql -d ta_lab2 -f sql/features/030_cmc_ema_multi_tf_u_create.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_ema_multi_tf_cal_tables.sql
```

**Step 8: Create returns tables** (6 files: base + 4 calendar variants + 3 unified tables)

```bash
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_iso.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_us.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_anchor_iso.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_anchor_us.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_bars_multi_tf_u.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf_cal_unified.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf_u.sql
```

**Step 9: Create feature tables** (vol, ta, cmc_features)

```bash
psql -d ta_lab2 -f sql/features/041_cmc_vol.sql
psql -d ta_lab2 -f sql/features/042_cmc_ta.sql
psql -d ta_lab2 -f sql/views/050_cmc_features.sql
```

**Step 10: Create regime tables** (4 files)

```bash
psql -d ta_lab2 -f sql/regimes/080_cmc_regimes.sql
psql -d ta_lab2 -f sql/regimes/081_cmc_regime_flips.sql
psql -d ta_lab2 -f sql/regimes/082_cmc_regime_stats.sql
psql -d ta_lab2 -f sql/regimes/084_cmc_regime_comovement.sql
```

**Step 11: Create signal tables** (4 files: 3 signal tables + state)

```bash
psql -d ta_lab2 -f sql/signals/060_cmc_signals_ema_crossover.sql
psql -d ta_lab2 -f sql/signals/061_cmc_signals_rsi_mean_revert.sql
psql -d ta_lab2 -f sql/signals/062_cmc_signals_atr_breakout.sql
psql -d ta_lab2 -f sql/signals/063_cmc_signal_state.sql
```

**Step 12: Create backtest tables** (3 files)

```bash
psql -d ta_lab2 -f sql/backtests/070_cmc_backtest_runs.sql
psql -d ta_lab2 -f sql/backtests/071_cmc_backtest_trades.sql
psql -d ta_lab2 -f sql/backtests/072_cmc_backtest_metrics.sql
```

Schema creation complete. All 24 data tables plus state and dimension tables are now ready.

---

### Phase B: Source Data Ingest

Ingest CoinMarketCap price history into `cmc_price_histories7`. This is a per-asset step — repeat for each asset you want to track.

```python
from ta_lab2.io import upsert_cmc_history

# Ingest one asset
upsert_cmc_history(
    db_url="postgresql://...",
    source_file="path/to/cmc_BTC.json",  # downloaded CMC JSON file
)

# Repeat for each asset
upsert_cmc_history(db_url=..., source_file="path/to/cmc_ETH.json")
# ...
```

Source data is the CMC JSON/CSV exports downloaded from CoinMarketCap. Each asset has its own file. See [NEW_ASSET_ONBOARDING.md](NEW_ASSET_ONBOARDING.md) for the complete per-asset onboarding procedure including dim_assets registration.

---

### Phase C: Derived Data Rebuild

Build all derived tables in dependency order. Each step depends on the previous completing successfully.

**Bars** (all assets, full rebuild — expect 1-3 hours for ~100 assets):

```bash
python -m ta_lab2.scripts.run_daily_refresh --bars --ids all --verbose
```

**EMAs** (depends on bars — expect 1-3 hours for ~100 assets):

```bash
python -m ta_lab2.scripts.run_daily_refresh --emas --ids all --verbose
```

**Features** (depends on bars and EMAs):

```bash
# 1D features only (faster)
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D

# All timeframes (comprehensive, slower)
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --all-tfs
```

**Regimes** (depends on bars and EMAs):

```bash
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --all -v
```

**Signals** (depends on features):

```bash
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --full-refresh
```

**Backtests** — no automated full-rebuild script. Run `run_backtest_signals.py` per signal configuration as needed. See [BACKTEST_PIPELINE.md](BACKTEST_PIPELINE.md) for backtest commands.

---

### Phase D: Verification

Check row counts across key tables to confirm the rebuild completed:

```sql
SELECT
    'cmc_price_bars_multi_tf'   as tbl, COUNT(*) as n FROM public.cmc_price_bars_multi_tf
UNION ALL
SELECT 'cmc_ema_multi_tf_u',         COUNT(*) FROM public.cmc_ema_multi_tf_u
UNION ALL
SELECT 'cmc_features',               COUNT(*) FROM public.cmc_features
UNION ALL
SELECT 'cmc_regimes',                COUNT(*) FROM public.cmc_regimes
UNION ALL
SELECT 'cmc_signals_ema_crossover',  COUNT(*) FROM public.cmc_signals_ema_crossover;
```

Compare these counts against your expected values (e.g., prior backup counts or known totals). For reference, a full rebuild of ~100 assets produces approximately:
- `cmc_price_bars_multi_tf`: ~4.1M rows
- `cmc_ema_multi_tf_u`: ~14.8M rows
- `cmc_features`: ~2.1M rows (1D TF only)

---

## Recovery Time Estimates

| Scenario / Phase | Estimate | Notes |
|------------------|----------|-------|
| Restore from pg_dump backup | 10-30 min | Depends on DB size; network speed if restoring remotely |
| Schema recreation (DDL only) | 5-10 min | All `CREATE TABLE IF NOT EXISTS` — fast |
| Source data ingest (1 asset, full history) | 1-5 min | Depends on history length (ETH: ~10 years) |
| Bars rebuild (all assets) | 1-3 hours | ~100 assets; 6 bar builders each |
| EMA rebuild (all assets) | 1-3 hours | ~100 assets; 4 EMA refreshers each |
| Feature rebuild (1D, all assets) | 30-60 min | Parallelized vol + ta + cmc_features |
| Regime rebuild (all assets) | 10-30 min | Fast computation (<1s per asset) |
| Signals rebuild | 30-60 min | 3 signal generators, parallelized |

Full rebuild from scratch (all phases, ~100 assets): **4-10 hours**.

---

## SQL File Reference

All schema DDL files are in the `sql/` directory:

```
sql/
├── ddl/           -- Table creation scripts (price bars, state tables, indexes)
├── features/      -- Feature table DDL (ema_u, calendar bar variants, vol, ta)
├── lookups/       -- Dimension table seed data (dim_timeframe, dim_signals)
├── regimes/       -- Regime table DDL (cmc_regimes, flips, stats, comovement)
├── signals/       -- Signal table DDL (cmc_signals_*, dim_signals)
├── backtests/     -- Backtest table DDL (runs, trades, metrics)
├── views/         -- cmc_features DDL
└── migration/     -- ALTER TABLE scripts for schema changes
```

If a table is missing after restore, check the corresponding DDL file in this directory and apply it with `psql -d ta_lab2 -f <path>`.

---

## See Also

- [DAILY_REFRESH.md](DAILY_REFRESH.md) — Daily incremental refresh operations
- [NEW_ASSET_ONBOARDING.md](NEW_ASSET_ONBOARDING.md) — Per-asset onboarding walkthrough
- [STATE_MANAGEMENT.md](STATE_MANAGEMENT.md) — State table schemas and reset patterns
- [REGIME_PIPELINE.md](REGIME_PIPELINE.md) — Regime pipeline details
- [BACKTEST_PIPELINE.md](BACKTEST_PIPELINE.md) — Backtest pipeline details
