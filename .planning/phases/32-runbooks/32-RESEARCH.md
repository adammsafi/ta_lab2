# Phase 32: Runbooks - Research

**Researched:** 2026-02-22
**Domain:** Operational documentation — regime pipeline, backtest pipeline, asset onboarding, disaster recovery
**Confidence:** HIGH

---

## Summary

This phase writes four operational runbooks by documenting existing scripts, their exact CLI flags, verification queries, and failure modes. The research involved reading every relevant script, SQL file, and existing operations doc directly from source — no inference, no training data.

All four runbooks are documentation tasks, not build tasks. The challenge is accuracy: every command, flag, and table name must match the actual code. This research provides that ground truth so the planner can write tasks that produce correct runbook content without touching the code.

The existing `docs/operations/DAILY_REFRESH.md` is the format reference — Quick Start with copy-paste commands at top, structured sections with brief "why" context, troubleshooting with specific error messages. That format should be followed with per-runbook tailoring.

**Primary recommendation:** Read each runbook's subject scripts directly rather than relying on memory. The scripts have accurate docstrings and argparse help text that are the source of truth for flag names.

---

## RUNB-01: Regime Pipeline

### Entry Points (verified from source)

**Via orchestrator (preferred):**
```bash
# Regimes only (after bars/EMAs already fresh)
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids all

# Full pipeline including regimes
python -m ta_lab2.scripts.run_daily_refresh --all --ids all

# Dry run to see what would execute
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids 1 --dry-run
```

**Direct script (fine-grained control):**
```bash
# All active assets
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --all

# Specific IDs
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1,2

# Dry run (computes but does not write to DB)
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 --dry-run

# Verbose output (DEBUG logging)
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 -v

# Disable hysteresis (raw labels, no smoothing)
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 --no-hysteresis

# Override data budget thresholds
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 --min-bars-l0 30 --min-bars-l1 26

# Custom policy file
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --all --policy-file configs/my_policies.yaml

# Custom calendar scheme
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --all --cal-scheme us
```

### All CLI Flags for refresh_cmc_regimes (verified from argparse)

| Flag | Default | Purpose |
|------|---------|---------|
| `--ids ID[,ID...]` | (required, mutually exclusive with --all) | Specific asset IDs |
| `--all` | (required, mutually exclusive with --ids) | All active assets from dim_assets |
| `--cal-scheme` | `iso` | Calendar scheme: `iso` or `us` |
| `--policy-file PATH` | `configs/regime_policies.yaml` | YAML policy overlay path |
| `--dry-run` | False | Compute but do not write to DB |
| `-v` / `--verbose` | False | Enable DEBUG logging |
| `--db-url URL` | `$TARGET_DB_URL` | PostgreSQL connection URL |
| `--min-bars-l0 N` | None (uses default) | Override monthly bars threshold for L0 |
| `--min-bars-l1 N` | None (uses default) | Override weekly bars threshold for L1 |
| `--min-bars-l2 N` | None (uses default) | Override daily bars threshold for L2 |
| `--no-hysteresis` | False | Disable hysteresis smoothing (raw labels) |
| `--min-hold-bars N` | 3 | Bars before loosening regime change accepted |

### regime_inspect — All Modes (verified from source)

```bash
# Default: show latest stored regime for an asset
python -m ta_lab2.scripts.regimes.regime_inspect --id 1

# Show last N days of regime history
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --history 30

# Show recent regime transitions (last 20 from cmc_regime_flips)
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --flips

# Compute live (not stored; uses compute_regimes_for_id directly)
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --live

# Specific timeframe (default: 1D)
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --tf 1D

# Verbose debug output
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --verbose
```

**regime_inspect output (default mode) shows:**
- Asset symbol (from dim_assets) and ID
- Timestamp of latest regime row
- Feature tier (full/lite)
- L0 (Monthly), L1 (Weekly), L2 (Daily) labels with enabled/disabled status
- Resolved Policy: regime_key, size_mult, stop_mult, orders, pyramids, gross_cap
- Version hash and last updated timestamp

**regime_inspect --history N shows:** Table of: Date, Regime Key, Size Mult, Stop Mult, Cap, Orders (oldest-first, N rows)

**regime_inspect --flips shows:** Table of: Date, Layer, Old Regime, New Regime, Bars Held (last 20 transitions, oldest-first)

### Regime Tables (verified from DDL sql/regimes/)

| Table | DDL File | Purpose |
|-------|----------|---------|
| `cmc_regimes` | `080_cmc_regimes.sql` | Per-bar regime labels and resolved policy. PK: (id, ts, tf) |
| `cmc_regime_flips` | `081_cmc_regime_flips.sql` | Regime transition events. Columns: id, ts, tf, layer, old_regime, new_regime, duration_bars |
| `cmc_regime_stats` | `082_cmc_regime_stats.sql` | Aggregated stats per regime key |
| `cmc_regime_comovement` | `084_cmc_regime_comovement.sql` | EMA comovement metrics |

**Key cmc_regimes columns:** id, ts, tf, l0_label, l1_label, l2_label, l3_label (always NULL), l4_label (always NULL), regime_key, size_mult, stop_mult, orders, gross_cap, pyramids, feature_tier, l0_enabled, l1_enabled, l2_enabled, regime_version_hash, updated_at

### Execution Flow (verified from refresh_cmc_regimes.py)

For each asset:
1. Load bars + EMAs for M/W/D timeframes (via regime_data_loader.py)
2. Assess data budget — determine feature_tier (full/lite) and which layers are enabled
3. Label enabled layers: L0 (monthly), L1 (weekly), L2 (daily)
4. Proxy fallback for disabled layers (uses BTC id=1 as market proxy)
5. Forward-fill sparse (M/W) labels to daily index
6. Resolve policy row-by-row with optional hysteresis
7. Detect flips (detect_regime_flips)
8. Compute stats (compute_regime_stats)
9. Compute comovement (compute_and_write_comovement)
10. Write all 4 tables via scoped DELETE + INSERT

**Note:** Full recompute per asset on each run (no watermark). Incremental deferred to future phase. Regime computation is fast — < 1 second per asset.

### run_daily_refresh --regimes flags (verified)

```bash
# Disable hysteresis when running via orchestrator
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids all --no-regime-hysteresis

# Dry run propagates to subprocess
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids 1 --dry-run --verbose
```

Timeout for regime subprocess: 1800 seconds (30 minutes).

### Execution Order Dependency

```
cmc_price_bars_multi_tf (bars) -> cmc_ema_multi_tf_u (EMAs) -> cmc_regimes (regimes)
```

Regimes read from bars + EMAs tables. If those are stale, regimes will use stale data (no gate; operator must ensure freshness).

### Common Failure Modes (regime pipeline)

**"No daily data for asset_id=X, returning empty"**
- Cause: No 1D bars in cmc_price_bars_multi_tf for this ID
- Fix: Run bars refresh first: `python -m ta_lab2.scripts.run_daily_refresh --bars --ids X`

**"No regime data found for id=X tf=1D" (from regime_inspect)**
- Cause: Regime refresh never ran or failed for this asset
- Fix: `python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids X -v`

**"L0/L1/L2 labeler failed: [exception]"**
- Cause: Insufficient data (EMA data missing or too few bars)
- Effect: That layer falls back to proxy or stays NULL — not a hard failure
- Check: `python -m ta_lab2.scripts.regimes.regime_inspect --id X -v` to see which layers are enabled

**"No DB URL provided. Set TARGET_DB_URL or pass --db-url."**
- Cause: Environment variable not set
- Fix: `export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"`

**"Failed: [exception]" (per-asset error in summary)**
- Script continues to next asset by default (no --continue-on-error needed)
- Failed assets listed at end of summary

**Assets errored > 0 in final summary**
- Exit code is 1 when any asset errors (useful for cron alerting)

### Verification Queries (regime pipeline)

```sql
-- Check regime data is fresh
SELECT id, MAX(ts) as latest_regime, MIN(ts) as earliest_regime, COUNT(*) as n_rows
FROM public.cmc_regimes
WHERE tf = '1D'
GROUP BY id
ORDER BY latest_regime DESC
LIMIT 10;

-- Check regime distribution for BTC (id=1)
SELECT regime_key, COUNT(*) as n_bars, AVG(size_mult) as avg_size
FROM public.cmc_regimes
WHERE id = 1 AND tf = '1D'
GROUP BY regime_key
ORDER BY n_bars DESC;

-- Check recent flips
SELECT id, ts, layer, old_regime, new_regime, duration_bars
FROM public.cmc_regime_flips
WHERE tf = '1D'
ORDER BY ts DESC
LIMIT 20;

-- Check version hash consistency (all same = consistent run)
SELECT DISTINCT regime_version_hash, COUNT(*) as n_rows
FROM public.cmc_regimes
WHERE tf = '1D'
GROUP BY regime_version_hash;

-- Check how many assets have regimes
SELECT COUNT(DISTINCT id) as n_assets_with_regimes FROM public.cmc_regimes WHERE tf = '1D';
```

### State Reset (regime pipeline)

Regimes use full recompute (no state table). To force recompute:
- Just re-run the script. DELETE + INSERT always replaces.

```sql
-- Manually delete regimes for a specific asset (then re-run)
DELETE FROM public.cmc_regimes WHERE id = 2 AND tf = '1D';
DELETE FROM public.cmc_regime_flips WHERE id = 2 AND tf = '1D';
DELETE FROM public.cmc_regime_stats WHERE id = 2 AND tf = '1D';
DELETE FROM public.cmc_regime_comovement WHERE id = 2 AND tf = '1D';
```

---

## RUNB-02: Backtest Pipeline

### Signal Generation — Entry Points (verified from source)

**Run all 3 signal types in parallel (standard):**
```bash
# Incremental refresh (default)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Full refresh (regenerate all signals)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --full-refresh

# Skip reproducibility validation
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --skip-validation

# Validate only (no signal generation)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only

# Exit on first failure (default: continue partial results)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --fail-fast

# Specific assets
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --ids 1 2 52

# Disable regime context (A/B mode)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --no-regime

# Verbose
python -m ta_lab2.scripts.signals.run_all_signal_refreshes -v
```

**Run a single signal type directly:**
```bash
# RSI mean reversion
python -m ta_lab2.scripts.signals.refresh_cmc_signals_rsi_mean_revert

# Full refresh for specific assets
python -m ta_lab2.scripts.signals.refresh_cmc_signals_rsi_mean_revert --ids 1 52 --full-refresh

# Dry run
python -m ta_lab2.scripts.signals.refresh_cmc_signals_rsi_mean_revert --dry-run --verbose

# Specific signal config
python -m ta_lab2.scripts.signals.refresh_cmc_signals_rsi_mean_revert --signal-id 4

# EMA crossover
python -m ta_lab2.scripts.signals.refresh_cmc_signals_ema_crossover

# ATR breakout
python -m ta_lab2.scripts.signals.refresh_cmc_signals_atr_breakout
```

### Signal Types and Tables (verified from source)

| Signal Type | Generator Class | Config in dim_signals | Output Table |
|-------------|----------------|----------------------|--------------|
| `ema_crossover` | `EMASignalGenerator` | ema_9_21_long, ema_21_50_long, ema_50_200_long | `cmc_signals_ema_crossover` |
| `rsi_mean_revert` | `RSISignalGenerator` | rsi_30_70_mr, rsi_25_75_mr | `cmc_signals_rsi_mean_revert` |
| `atr_breakout` | `ATRSignalGenerator` | atr_20_donchian | `cmc_signals_atr_breakout` |

**Signal feature sources (verified from validate_reproducibility.py):**
- EMA crossover uses: `close`, `rsi_14`, `atr_14` from cmc_features + EMAs 9,10,21,50,200 from cmc_ema_multi_tf_u
- RSI mean revert uses: `close`, `rsi_14`, `rsi_7`, `rsi_21`, `atr_14` from cmc_features + EMA 21 from cmc_ema_multi_tf_u
- ATR breakout uses: `close`, `atr_14`, `bb_up_20_2`, `bb_lo_20_2`, `rsi_14` from cmc_features + EMA 21 from cmc_ema_multi_tf_u

### Running a Backtest (verified from run_backtest_signals.py)

```bash
# Clean mode (no transaction costs) — for reproducibility testing
python -m ta_lab2.scripts.backtests.run_backtest_signals \
    --signal-type ema_crossover \
    --signal-id 1 \
    --asset-id 1 \
    --start 2023-01-01 \
    --end 2023-12-31 \
    --clean-pnl

# Realistic mode with fees
python -m ta_lab2.scripts.backtests.run_backtest_signals \
    --signal-type rsi_mean_revert \
    --signal-id 2 \
    --asset-id 1 \
    --start 2023-01-01 \
    --end 2023-12-31 \
    --fee-bps 10 \
    --slippage-bps 5 \
    --save-results

# With JSON output
python -m ta_lab2.scripts.backtests.run_backtest_signals \
    --signal-type atr_breakout \
    --signal-id 3 \
    --asset-id 1 \
    --start 2023-01-01 \
    --end 2023-12-31 \
    --save-results \
    --output-json results.json
```

### Backtest Pipeline Flow

```
cmc_features (1D) + cmc_ema_multi_tf_u
    -> signal generators (RSI/EMA/ATR)
    -> cmc_signals_* tables
    -> SignalBacktester (vectorbt 0.28.1)
    -> cmc_backtest_runs (metadata + summary metrics)
    -> cmc_backtest_trades (individual trades)
    -> cmc_backtest_metrics (performance metrics)
```

### Backtest Result Tables (verified from DDL sql/backtests/)

**cmc_backtest_runs** (PK: run_id UUID):
- signal_type, signal_id, asset_id
- start_ts, end_ts
- cost_model (JSONB), signal_params_hash, feature_hash
- signal_version, vbt_version, run_timestamp
- total_return, sharpe_ratio, max_drawdown, trade_count

**cmc_backtest_trades** (FK: run_id):
- entry_ts, entry_price, exit_ts, exit_price
- direction, size, pnl_pct, pnl_dollars

**cmc_backtest_metrics** (FK: run_id):
- total_return, cagr, sharpe_ratio, sortino_ratio, calmar_ratio
- max_drawdown, max_drawdown_duration_days
- trade_count, win_rate, profit_factor, avg_win, avg_loss
- avg_holding_period_days, var_95, expected_shortfall

### Reproducibility Validation (verified from validate_reproducibility.py)

`validate_reproducibility.py` runs the same backtest twice and compares:
- PnL (total_return): must match within tolerance 1e-10
- Metrics: all metrics match within tolerance
- Trade count: must be identical
- Feature hash: detects if underlying feature data changed

**Modes:**
- `strict=True`: Raise RuntimeError on any difference
- `strict=False` (default in orchestrator): Log warning but proceed

**Run manually:**
```bash
# Validate only (no signal generation)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only
```

### Querying Backtest Results (verified from SQL)

```sql
-- Latest runs per signal type
SELECT signal_type, signal_id, asset_id, total_return, sharpe_ratio,
       max_drawdown, trade_count, run_timestamp
FROM public.cmc_backtest_runs
ORDER BY run_timestamp DESC
LIMIT 20;

-- Metrics for a specific run
SELECT r.signal_type, r.signal_id, r.asset_id,
       m.total_return, m.cagr, m.sharpe_ratio, m.sortino_ratio,
       m.max_drawdown, m.trade_count, m.win_rate, m.profit_factor
FROM public.cmc_backtest_runs r
JOIN public.cmc_backtest_metrics m ON r.run_id = m.run_id
WHERE r.signal_type = 'ema_crossover'
ORDER BY r.run_timestamp DESC
LIMIT 10;

-- Trades for a specific run
SELECT entry_ts, entry_price, exit_ts, exit_price, direction, pnl_pct
FROM public.cmc_backtest_trades
WHERE run_id = '[uuid here]'
ORDER BY entry_ts;

-- Check signal count by type
SELECT signal_type, COUNT(*) as n_signals
FROM public.cmc_signals_ema_crossover
GROUP BY signal_type
UNION ALL
SELECT 'rsi_mean_revert', COUNT(*) FROM public.cmc_signals_rsi_mean_revert
UNION ALL
SELECT 'atr_breakout', COUNT(*) FROM public.cmc_signals_atr_breakout;
```

### Common Failure Modes (backtest pipeline)

**"TARGET_DB_URL environment variable not set"**
- Fix: `export TARGET_DB_URL="postgresql://..."`

**"No asset IDs to process"**
- Cause: cmc_features is empty or no 1D data
- Fix: Run feature refresh first

**Signal generation fails for one type**
- Default behavior: continue with partial results (other types succeed)
- Use `--fail-fast` to exit immediately on first failure
- Check: Run the individual signal script with `--verbose` to see specific error

**Reproducibility validation FAILED**
- Means two runs of identical backtest produced different results
- Cause: Non-deterministic data loading or floating point issues
- Check: `--validate-only --verbose` to see which signal type failed

**"Backtest run not found: [uuid]"**
- run_id doesn't exist in cmc_backtest_runs
- Check run_id is correct: `SELECT run_id FROM public.cmc_backtest_runs ORDER BY run_timestamp DESC LIMIT 5;`

### Interpreting backtest_metrics

| Metric | Good | Concerning |
|--------|------|------------|
| `total_return` | Positive | Negative |
| `sharpe_ratio` | > 1.0 | < 0 |
| `sortino_ratio` | > 1.5 | < 0 |
| `max_drawdown` | < 0.20 | > 0.40 |
| `win_rate` | > 0.50 | < 0.35 |
| `profit_factor` | > 1.5 | < 1.0 |
| `trade_count` | > 10 | < 5 (low statistical significance) |

---

## RUNB-03: New-Asset Onboarding

### The 6-Step Process

**Step 1: Register in dim_assets**
```sql
-- Check if asset already exists
SELECT id, symbol FROM public.dim_assets WHERE id = 2;

-- Insert if missing (ETH example, id=2)
INSERT INTO public.dim_assets (id, symbol, asset_class)
VALUES (2, 'ETH', 'CRYPTO')
ON CONFLICT (id) DO NOTHING;

-- Verify
SELECT * FROM public.dim_assets WHERE id = 2;
```

**Note:** dim_assets is created as `CREATE TABLE AS SELECT ... FROM dim_sessions WHERE asset_class = 'CRYPTO'`. If the asset is in dim_sessions/cmc_da_ids, you can also re-create from source. If not, INSERT directly.

There is also an `is_active` column used by some scripts — check if it exists in your DB schema. If present, set it: `UPDATE public.dim_assets SET is_active = TRUE WHERE id = 2;`

Timing: ~30 seconds

**Step 2: Ingest price_histories7 source data**

Price data comes from CoinMarketCap CSV exports. The source table `cmc_price_histories7` must have rows for this asset ID before any bars can be built.

```python
# Using update_cmc_history.py (requires path to downloaded CMC JSON/CSV)
from ta_lab2.io import upsert_cmc_history
upsert_cmc_history(
    db_url="postgresql://...",
    source_file="path/to/cmc_ETH_history.json",
)
```

Verify:
```sql
SELECT MIN(timeclose) as first_date, MAX(timeclose) as last_date, COUNT(*) as n_rows
FROM public.cmc_price_histories7
WHERE id = 2;
-- Expected: ETH data starts around 2015-08-07
```

Timing: 2-5 minutes depending on history length

**Step 3: Build multi-TF bars**
```bash
# Build all bars for ETH
python -m ta_lab2.scripts.run_daily_refresh --bars --ids 2 --verbose
```

This runs all 6 bar builders:
1. 1d (1D bars from price_histories7)
2. multi_tf (rolling multi-TF bars)
3. cal_iso (ISO calendar-aligned)
4. cal_us (US calendar-aligned)
5. cal_anchor_iso (ISO anchored with partials)
6. cal_anchor_us (US anchored with partials)

Verify:
```sql
-- Check 1D bars
SELECT MIN(ts) as first_bar, MAX(ts) as last_bar, COUNT(*) as n_bars
FROM public.cmc_price_bars_multi_tf
WHERE id = 2 AND tf = '1D';

-- Check multi-TF coverage
SELECT tf, COUNT(*) as n_bars
FROM public.cmc_price_bars_multi_tf
WHERE id = 2
GROUP BY tf
ORDER BY tf;
```

Timing: ~5-10 minutes for ETH (full history ~3000+ 1D bars)

**Step 4: Compute EMAs**
```bash
python -m ta_lab2.scripts.run_daily_refresh --emas --ids 2 --verbose
```

This runs all 4 EMA refreshers:
1. multi_tf
2. cal
3. cal_anchor
4. (v2 if applicable)

Verify:
```sql
-- Check EMA coverage
SELECT tf, period, COUNT(*) as n_rows, MAX(ts) as latest
FROM public.cmc_ema_multi_tf_u
WHERE id = 2
GROUP BY tf, period
ORDER BY tf, period
LIMIT 20;
```

Timing: ~5-15 minutes for ETH

**Step 5: Compute features and regimes**
```bash
# Features (vol, ta, cmc_features)
python -m ta_lab2.scripts.features.run_all_feature_refreshes --ids 2 --tf 1D

# Regimes
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 2 -v
```

Verify features:
```sql
SELECT MIN(ts) as first_ts, MAX(ts) as last_ts, COUNT(*) as n_rows
FROM public.cmc_features
WHERE id = 2 AND tf = '1D';
```

Verify regimes:
```bash
python -m ta_lab2.scripts.regimes.regime_inspect --id 2
```

Timing: Features ~2-5 minutes, Regimes ~1-2 minutes

**Step 6: Verify incremental refresh works**
```bash
# Run full pipeline for ETH and confirm no errors
python -m ta_lab2.scripts.run_daily_refresh --all --ids 2 --verbose
```

Verify the asset appears in asset_data_coverage:
```sql
SELECT id, source_table, n_rows, first_ts, last_ts
FROM public.asset_data_coverage
WHERE id = 2
ORDER BY source_table;
```

### Removal Process

```sql
-- Remove all derived data for an asset (order matters due to FKs)
DELETE FROM public.cmc_backtest_trades WHERE run_id IN (
    SELECT run_id FROM public.cmc_backtest_runs WHERE asset_id = 2
);
DELETE FROM public.cmc_backtest_metrics WHERE run_id IN (
    SELECT run_id FROM public.cmc_backtest_runs WHERE asset_id = 2
);
DELETE FROM public.cmc_backtest_runs WHERE asset_id = 2;
DELETE FROM public.cmc_signals_ema_crossover WHERE id = 2;
DELETE FROM public.cmc_signals_rsi_mean_revert WHERE id = 2;
DELETE FROM public.cmc_signals_atr_breakout WHERE id = 2;
DELETE FROM public.cmc_regimes WHERE id = 2;
DELETE FROM public.cmc_regime_flips WHERE id = 2;
DELETE FROM public.cmc_regime_stats WHERE id = 2;
DELETE FROM public.cmc_regime_comovement WHERE id = 2;
DELETE FROM public.cmc_features WHERE id = 2;
DELETE FROM public.cmc_vol WHERE id = 2;
DELETE FROM public.cmc_ta WHERE id = 2;
DELETE FROM public.cmc_returns_bars_multi_tf_u WHERE id = 2;
DELETE FROM public.cmc_ema_multi_tf_u WHERE id = 2;
DELETE FROM public.cmc_price_bars_multi_tf_u WHERE id = 2;
-- State tables
DELETE FROM public.cmc_price_bars_1d_state WHERE id = 2;
DELETE FROM public.cmc_ema_refresh_state WHERE id = 2;
-- Source data (only if decommissioning)
-- DELETE FROM public.cmc_price_histories7 WHERE id = 2;
-- Registry (only if decommissioning entirely)
-- DELETE FROM public.dim_assets WHERE id = 2;
```

---

## RUNB-04: Disaster Recovery

### Environment Prerequisites

**Required environment variable:**
```bash
export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"
```

**Fallback lookup order** (from config.py):
1. `$TARGET_DB_URL`
2. `$DB_URL`
3. `$MARKETDATA_DB_URL`

**Python environment:**
```bash
# Activate venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate      # Windows

# Verify install
pip install -e ".[all]"
```

### Scenario 1: DB Loss / Corruption (restore from backup)

**Step 1: Create backup (while DB is healthy)**
```bash
# Daily backup
pg_dump ta_lab2 | gzip > /backups/ta_lab2_$(date +%Y%m%d).sql.gz

# Restore from backup
gunzip -c /backups/ta_lab2_20260201.sql.gz | psql ta_lab2
```

**Note:** No automated backup exists yet. This is a manual procedure that should be run on a schedule (cron). The DR guide should document this as a recommended next step.

**Step 2: Verify restore**
```sql
-- Check key tables have data
SELECT COUNT(*) FROM public.cmc_price_histories7;
SELECT COUNT(*) FROM public.cmc_price_bars_multi_tf;
SELECT COUNT(*) FROM public.cmc_ema_multi_tf_u;
SELECT COUNT(*) FROM public.cmc_features;
SELECT COUNT(*) FROM public.cmc_regimes;
```

### Scenario 2: Full Environment Rebuild from Scratch

**This is the nuclear option.** Source data is CoinMarketCap; all derived tables are recomputable. Expect several hours for full rebuild with many assets.

**Rebuild order (each step depends on the previous):**

**Phase A: Schema**
```bash
# 1. Create database
createdb ta_lab2

# 2. Create observability schema
psql -d ta_lab2 -f sql/ddl/create_observability_schema.sql

# 3. Create dimension tables (dim_timeframe, dim_sessions)
python -m ta_lab2.scripts.setup.ensure_dim_tables

# 4. Create dim_assets (from dim_sessions or manual insert)
psql -d ta_lab2 -f sql/ddl/create_dim_assets.sql

# 5. Create dim_signals (signal configurations + seed data)
psql -d ta_lab2 -f sql/lookups/030_dim_signals.sql

# 6. Create price bar tables
psql -d ta_lab2 -f sql/ddl/price_bars__cmc_price_bars_multi_tf.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_price_bars_1d_state.sql
psql -d ta_lab2 -f sql/features/031_cmc_price_bars_multi_tf_cal_iso.sql
psql -d ta_lab2 -f sql/features/031_cmc_price_bars_multi_tf_cal_us.sql
psql -d ta_lab2 -f sql/features/033_cmc_price_bars_multi_tf_cal_anchor_us.sql
psql -d ta_lab2 -f sql/features/034_cmc_price_bars_multi_tf_cal_anchor_iso.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_price_bars_multi_tf_u.sql

# 7. Create EMA tables
psql -d ta_lab2 -f sql/ddl/create_cmc_ema_refresh_state.sql
psql -d ta_lab2 -f sql/features/030_cmc_ema_multi_tf_u_create.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_ema_multi_tf_cal_tables.sql

# 8. Create returns tables
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_iso.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_us.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_anchor_iso.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf_cal_anchor_us.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_bars_multi_tf_u.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf_cal_unified.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf_u.sql

# 9. Create feature tables
psql -d ta_lab2 -f sql/features/041_cmc_vol.sql
psql -d ta_lab2 -f sql/features/042_cmc_ta.sql
psql -d ta_lab2 -f sql/views/050_cmc_features.sql

# 10. Create regime tables
psql -d ta_lab2 -f sql/regimes/080_cmc_regimes.sql
psql -d ta_lab2 -f sql/regimes/081_cmc_regime_flips.sql
psql -d ta_lab2 -f sql/regimes/082_cmc_regime_stats.sql
psql -d ta_lab2 -f sql/regimes/084_cmc_regime_comovement.sql

# 11. Create signal tables
psql -d ta_lab2 -f sql/signals/060_cmc_signals_ema_crossover.sql
psql -d ta_lab2 -f sql/signals/061_cmc_signals_rsi_mean_revert.sql
psql -d ta_lab2 -f sql/signals/062_cmc_signals_atr_breakout.sql
psql -d ta_lab2 -f sql/signals/063_cmc_signal_state.sql

# 12. Create backtest tables
psql -d ta_lab2 -f sql/backtests/070_cmc_backtest_runs.sql
psql -d ta_lab2 -f sql/backtests/071_cmc_backtest_trades.sql
psql -d ta_lab2 -f sql/backtests/072_cmc_backtest_metrics.sql
```

**Note on SQL files with UTF-8 box-drawing characters:** Always use `psql` directly (handles encoding). If running via Python, use `encoding='utf-8'` when opening SQL files — Windows default (cp1252) will fail on files with `═══` box-drawing chars in comments.

**Phase B: Source Data Ingest**
```python
# Ingest CoinMarketCap price history CSVs into cmc_price_histories7
# Source: downloaded CMC JSON files per asset
from ta_lab2.io import upsert_cmc_history
upsert_cmc_history(db_url=..., source_file="path/to/cmc_BTC.json")
# Repeat for each asset
```

**Phase C: Derived Data Rebuild**
```bash
# Bars (all assets, full rebuild)
python -m ta_lab2.scripts.run_daily_refresh --bars --ids all --verbose
# Expected: Hours for many assets

# EMAs
python -m ta_lab2.scripts.run_daily_refresh --emas --ids all --verbose
# Expected: Hours for many assets

# Returns (z-score post-processing, if applicable)
# python -m ta_lab2.scripts.returns.refresh_returns_zscore --all-ids

# Features (vol, ta, cmc_features)
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D
# For all TFs:
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --all-tfs

# Regimes
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --all -v

# Signals
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --full-refresh

# Backtests (re-run for each signal configuration as needed)
# No automated full-rebuild script — run run_backtest_signals.py per config
```

**Phase D: Verify**
```sql
-- Check table row counts
SELECT
    'cmc_price_bars_multi_tf' as tbl, COUNT(*) as n FROM public.cmc_price_bars_multi_tf
UNION ALL SELECT 'cmc_ema_multi_tf_u', COUNT(*) FROM public.cmc_ema_multi_tf_u
UNION ALL SELECT 'cmc_features', COUNT(*) FROM public.cmc_features
UNION ALL SELECT 'cmc_regimes', COUNT(*) FROM public.cmc_regimes
UNION ALL SELECT 'cmc_signals_ema_crossover', COUNT(*) FROM public.cmc_signals_ema_crossover;
```

### Key SQL File Locations (for DR reference)

```
sql/
├── ddl/           -- Table creation scripts (price bars, state, indexes)
├── features/      -- Feature table DDL (ema_u, returns, vol, ta, backtest)
├── lookups/       -- Dimension table seed data (dim_timeframe, dim_signals)
├── regimes/       -- Regime table DDL (cmc_regimes, flips, stats, comovement)
├── signals/       -- Signal table DDL (cmc_signals_*, dim_signals)
├── backtests/     -- Backtest table DDL (runs, trades, metrics)
├── views/         -- cmc_features DDL
└── migration/     -- ALTER TABLE scripts for schema changes
```

### Recovery Time Estimates

| Scenario | Estimate | Notes |
|----------|----------|-------|
| Restore from pg_dump backup | 10-30 min | Depends on DB size |
| Schema recreation (DDL only) | 5-10 min | All CREATE TABLE IF NOT EXISTS |
| Price ingest (1 asset, full history) | 1-5 min | Depends on history length |
| Bars rebuild (all assets) | 1-3 hours | ~100 assets |
| EMA rebuild (all assets) | 1-3 hours | ~100 assets |
| Feature rebuild | 30-60 min | Parallelized |
| Regime rebuild | 10-30 min | Fast computation |
| Signals rebuild | 30-60 min | Parallelized |

---

## mkdocs Nav Integration

### Current nav structure (verified from mkdocs.yml)

```yaml
nav:
  - Home: index.md
  - Getting Started:
    - Quick Start: index.md
    - Installation: deployment.md
  - Design:
    - Overview: DESIGN.md
    - Architecture: architecture/architecture.md
  - Components:
    - Time Model: time/time_model_overview.md
    - Features: time/returns_volatility.md
    - Signals: time/regime_integration.md
  - Deployment: deployment.md
  - API Reference:
    - Memory API: api/memory.md
    - Orchestrator CLI: api/orchestrator.md
  - Changelog: CHANGELOG.md
```

**No Operations section exists yet.** The planner must add one.

### Target nav addition

```yaml
  - Operations:
    - Daily Refresh: operations/DAILY_REFRESH.md
    - Regime Pipeline: operations/REGIME_PIPELINE.md
    - Backtest Pipeline: operations/BACKTEST_PIPELINE.md
    - New Asset Onboarding: operations/NEW_ASSET_ONBOARDING.md
    - Disaster Recovery: operations/DISASTER_RECOVERY.md
```

**Existing operations docs to include:**
- `docs/operations/DAILY_REFRESH.md` — already written, good format reference
- `docs/operations/STATE_MANAGEMENT.md` — state table reference

---

## Format Reference (from DAILY_REFRESH.md)

The existing `DAILY_REFRESH.md` format to follow:

1. **Quick Start** — copy-paste commands at top, most common use case first
2. **Entry Points** — all ways to invoke with flags table
3. **Execution Order** — numbered list of what runs in what order
4. **Logs and Monitoring** — how to check status
5. **Troubleshooting** — specific error messages with solutions
6. **Workflow Patterns** — scenario-based examples (standard, recovery, etc.)
7. **Performance** — timing table
8. **See Also** — links to related docs

**Tone:** Commands first, brief "why" in 1-2 sentences, links to design docs for background. Skip expected output for simple commands; include for non-obvious ones.

---

## Open Questions

1. **cmc_price_histories7 ingest automation**
   - What we know: `upsert_cmc_history()` exists in `ta_lab2.io`, takes a source_file path pointing to CMC JSON
   - What's unclear: The exact JSON format expected, and whether there's a batch ingest script for multiple assets
   - Recommendation: The onboarding SOP can note "ingest CMC price history for asset" as a manual step with the upsert_cmc_history function reference, acknowledging it's done once-per-asset

2. **dim_assets is_active column**
   - What we know: Some scripts query `WHERE is_active = TRUE`, others fall back if column missing
   - What's unclear: Whether the current DB schema has is_active on dim_assets (the create_dim_assets.sql only creates id, asset_class, symbol)
   - Recommendation: The onboarding runbook should mention checking for is_active and setting it if present

3. **Returns zscore post-processing script**
   - What we know: `refresh_returns_zscore.py` is referenced in MEMORY.md
   - What's unclear: Exact module path and CLI flags
   - Recommendation: Low priority for runbooks; mention in DR as a step if the script exists at rebuild time

4. **SQL file encoding on Windows**
   - What we know: UTF-8 box-drawing chars in SQL comments cause cp1252 errors
   - Recommendation: DR guide should note to use `psql` directly (handles encoding) rather than Python's open() with default encoding

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` — all CLI flags, execution flow, failure modes verified from argparse and code
- `src/ta_lab2/scripts/regimes/regime_inspect.py` — all modes, flags, output format verified from code
- `src/ta_lab2/scripts/run_daily_refresh.py` — orchestrator flags, timeout values, component integration verified
- `src/ta_lab2/scripts/signals/run_all_signal_refreshes.py` — signal pipeline flow, all flags verified
- `src/ta_lab2/scripts/signals/validate_reproducibility.py` — reproducibility validation logic, feature columns per signal type
- `src/ta_lab2/scripts/backtests/run_backtest_signals.py` — backtest CLI verified
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` — feature refresh flags verified
- `sql/regimes/` — all 4 regime table DDL files (schema, columns)
- `sql/backtests/` — backtest table DDL (runs, trades, metrics)
- `sql/signals/` — signal table DDL, dim_signals seed data
- `sql/ddl/create_dim_assets.sql` — dim_assets schema
- `docs/operations/DAILY_REFRESH.md` — format reference
- `docs/operations/STATE_MANAGEMENT.md` — state table reference
- `docs/deployment.md` — environment variables, DB setup, pg_dump/restore commands
- `mkdocs.yml` — current nav structure

### Secondary (MEDIUM confidence)
- MEMORY.md project memory — architecture overview, table families, data flow (confirmed against code)

---

## Metadata

**Confidence breakdown:**
- Regime pipeline commands: HIGH — all flags verified from argparse in refresh_cmc_regimes.py
- regime_inspect modes: HIGH — all modes verified from code
- Backtest pipeline commands: HIGH — verified from run_backtest_signals.py and run_all_signal_refreshes.py
- Signal types and tables: HIGH — verified from DDL and source
- Onboarding steps: HIGH for bars/EMAs/features/regimes; MEDIUM for price ingest (script is minimal)
- DR table creation order: MEDIUM — DDL files exist but some dependencies may need sequencing adjustment
- mkdocs nav: HIGH — verified from mkdocs.yml

**Research date:** 2026-02-22
**Valid until:** 2026-04-22 (stable system, unlikely to change)
