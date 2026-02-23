# New Asset Onboarding SOP

This guide walks through adding a new crypto asset to the ta_lab2 pipeline end-to-end.
Uses **ETH (id=2)** as the worked example throughout.

## Quick Start

For the impatient — the 6 commands in order:

```bash
# 1. Register in dim_assets
psql -d ta_lab2 -c "INSERT INTO public.dim_assets (id, symbol, asset_class) VALUES (2, 'ETH', 'CRYPTO') ON CONFLICT (id) DO NOTHING;"

# 2. Ingest source price history (requires CMC data file)
python -c "from ta_lab2.io import upsert_cmc_history; upsert_cmc_history(db_url='$TARGET_DB_URL', source_file='path/to/cmc_ETH.json')"

# 3. Build multi-TF bars
python -m ta_lab2.scripts.run_daily_refresh --bars --ids 2 --verbose

# 4. Compute EMAs
python -m ta_lab2.scripts.run_daily_refresh --emas --ids 2 --verbose

# 5. Compute features and regimes
python -m ta_lab2.scripts.features.run_all_feature_refreshes --ids 2 --tf 1D
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 2 -v

# 6. Verify incremental refresh works
python -m ta_lab2.scripts.run_daily_refresh --all --ids 2 --verbose
```

Total time: 18-43 minutes for one asset with full history.

---

## Prerequisites

Before starting, confirm:

- **Database is running** and accessible
- **`TARGET_DB_URL` is set:**
  ```bash
  export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"
  ```
  Fallback lookup order: `$TARGET_DB_URL` -> `$DB_URL` -> `$MARKETDATA_DB_URL`
- **Python environment is activated:**
  ```bash
  source venv/bin/activate       # Linux/macOS
  venv\Scripts\activate          # Windows
  pip install -e ".[all]"        # verify install
  ```
- **CMC data file is available** for the new asset (downloaded JSON/CSV export from CoinMarketCap)

---

## Step-by-Step Walkthrough (ETH, id=2)

Follow these steps in order. Each step includes a verification query so you can confirm success before moving on.

---

### Step 1: Register in dim_assets (~30 seconds)

Every asset must exist in `dim_assets` before any pipeline steps run. The table holds the registry of tracked assets.

```sql
-- Check if asset already exists
SELECT id, symbol, asset_class FROM public.dim_assets WHERE id = 2;

-- Insert if missing
INSERT INTO public.dim_assets (id, symbol, asset_class)
VALUES (2, 'ETH', 'CRYPTO')
ON CONFLICT (id) DO NOTHING;
```

If your schema has an `is_active` column (check with `\d dim_assets` in psql), set it:

```sql
UPDATE public.dim_assets SET is_active = TRUE WHERE id = 2;
```

**Verify:**

```sql
SELECT * FROM public.dim_assets WHERE id = 2;
```

Expected: One row with `id=2`, `symbol='ETH'`, `asset_class='CRYPTO'`.

---

### Step 2: Ingest price_histories7 source data (2-5 min)

The source table `cmc_price_histories7` holds raw daily price history from CoinMarketCap. All derived tables (bars, EMAs, features) are built from this source. Nothing downstream can run until this table has rows for the asset.

```python
from ta_lab2.io import upsert_cmc_history

upsert_cmc_history(
    db_url="postgresql://...",           # or set TARGET_DB_URL
    source_file="path/to/cmc_ETH.json",
)
```

**Verify:**

```sql
SELECT MIN(timeclose) as first_date, MAX(timeclose) as last_date, COUNT(*) as n_rows
FROM public.cmc_price_histories7
WHERE id = 2;
```

Expected: ETH data starts around **2015-08-07**. A full history load should show 3000+ rows.

---

### Step 3: Build multi-TF bars (5-10 min)

Bars are the resampled OHLCV aggregates derived from `cmc_price_histories7`. This step builds all 6 bar variants: 1D, multi-TF rolling, and four calendar-aligned variants.

```bash
python -m ta_lab2.scripts.run_daily_refresh --bars --ids 2 --verbose
```

This runs all 6 bar builders in order:
1. **1d** — canonical daily bars from price_histories7
2. **multi_tf** — rolling multi-timeframe bars (7D, 14D, 30D, ...)
3. **cal_iso** — ISO calendar-aligned (ISO week/month/quarter/year)
4. **cal_us** — US calendar-aligned (Sunday week start)
5. **cal_anchor_iso** — ISO anchored with partial snapshots
6. **cal_anchor_us** — US anchored with partial snapshots

**Verify:**

```sql
-- 1D bar count
SELECT MIN(ts) as first_bar, MAX(ts) as last_bar, COUNT(*) as n_bars
FROM public.cmc_price_bars_multi_tf
WHERE id = 2 AND tf = '1D';
-- Expected: ~3000+ bars, first_bar around 2015-08-07

-- Multi-TF coverage (how many timeframes have bars)
SELECT tf, COUNT(*) as n_bars
FROM public.cmc_price_bars_multi_tf
WHERE id = 2
GROUP BY tf
ORDER BY tf;
```

---

### Step 4: Compute EMAs (5-15 min)

EMAs are computed from the bars built in Step 3. Each EMA variant corresponds to its bar variant. EMA data populates the unified `cmc_ema_multi_tf_u` table used by signal generators and the regime pipeline.

```bash
python -m ta_lab2.scripts.run_daily_refresh --emas --ids 2 --verbose
```

This runs all 4 EMA refreshers:
1. **multi_tf** — rolling multi-timeframe EMAs
2. **cal** — calendar-aligned EMAs
3. **cal_anchor** — calendar-anchored EMAs
4. **v2** — daily-space EMAs

**Verify:**

```sql
-- EMA coverage by tf and period
SELECT tf, period, COUNT(*) as n_rows, MAX(ts) as latest
FROM public.cmc_ema_multi_tf_u
WHERE id = 2
GROUP BY tf, period
ORDER BY tf, period
LIMIT 20;
```

Expected: Multiple rows per (tf, period) combination. For 1D, you should see periods like 9, 10, 21, 50, 200.

---

### Step 5: Compute features and regimes (3-7 min)

Features are bar-level indicators (volatility, TA signals, returns) stored in `cmc_features`. Regimes classify market conditions using the feature and EMA data from prior steps.

**Features (~2-5 minutes):**

```bash
python -m ta_lab2.scripts.features.run_all_feature_refreshes --ids 2 --tf 1D
```

**Regimes (~1-2 minutes):**

```bash
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 2 -v
```

**Verify features:**

```sql
SELECT MIN(ts) as first_ts, MAX(ts) as last_ts, COUNT(*) as n_rows
FROM public.cmc_features
WHERE id = 2 AND tf = '1D';
```

**Verify regimes:**

```bash
python -m ta_lab2.scripts.regimes.regime_inspect --id 2
```

Expected: Regime inspect shows L0/L1/L2 labels and a resolved policy for the latest bar.

---

### Step 6: Verify incremental refresh works (2-5 min)

Run the full pipeline for ETH to confirm the asset is correctly integrated into the daily refresh workflow. This verifies that incremental (non-full-rebuild) runs complete cleanly.

```bash
python -m ta_lab2.scripts.run_daily_refresh --all --ids 2 --verbose
```

**Verify:**

```sql
-- Confirm asset appears in coverage summary
SELECT id, source_table, n_rows, first_ts, last_ts
FROM public.asset_data_coverage
WHERE id = 2
ORDER BY source_table;
```

If `asset_data_coverage` has no rows for id=2, the incremental refresh still ran — the coverage table is populated separately. Check that the run completed with no errors in the output.

---

## Total Time Estimate

| Step | Task | Estimate |
|------|------|----------|
| 1 | Register in dim_assets | ~30 seconds |
| 2 | Ingest price_histories7 | 2-5 min |
| 3 | Build multi-TF bars | 5-10 min |
| 4 | Compute EMAs | 5-15 min |
| 5 | Compute features and regimes | 3-7 min |
| 6 | Verify incremental refresh | 2-5 min |
| | **Total** | **18-43 min** |

Timing varies with history length. ETH has ~10 years of daily data; a newer asset with less history will be faster.

---

## Removing an Asset

To decommission an asset, delete its derived data in FK-aware order, then optionally remove source data and the registry entry.

```sql
-- Derived data: backtest (FK child tables first)
DELETE FROM public.cmc_backtest_trades WHERE run_id IN (
    SELECT run_id FROM public.cmc_backtest_runs WHERE asset_id = 2
);
DELETE FROM public.cmc_backtest_metrics WHERE run_id IN (
    SELECT run_id FROM public.cmc_backtest_runs WHERE asset_id = 2
);
DELETE FROM public.cmc_backtest_runs WHERE asset_id = 2;

-- Derived data: signals
DELETE FROM public.cmc_signals_ema_crossover WHERE id = 2;
DELETE FROM public.cmc_signals_rsi_mean_revert WHERE id = 2;
DELETE FROM public.cmc_signals_atr_breakout WHERE id = 2;

-- Derived data: regimes
DELETE FROM public.cmc_regimes WHERE id = 2;
DELETE FROM public.cmc_regime_flips WHERE id = 2;
DELETE FROM public.cmc_regime_stats WHERE id = 2;
DELETE FROM public.cmc_regime_comovement WHERE id = 2;

-- Derived data: features
DELETE FROM public.cmc_features WHERE id = 2;
DELETE FROM public.cmc_vol WHERE id = 2;
DELETE FROM public.cmc_ta WHERE id = 2;

-- Derived data: returns and bars (unified tables)
DELETE FROM public.cmc_returns_bars_multi_tf_u WHERE id = 2;
DELETE FROM public.cmc_ema_multi_tf_u WHERE id = 2;
DELETE FROM public.cmc_price_bars_multi_tf_u WHERE id = 2;

-- State tables (reset so next run starts clean)
DELETE FROM public.cmc_price_bars_1d_state WHERE id = 2;
DELETE FROM public.cmc_ema_refresh_state WHERE id = 2;

-- Source data (only if decommissioning — this loses all raw price history)
-- DELETE FROM public.cmc_price_histories7 WHERE id = 2;

-- Registry (only if removing the asset entirely)
-- DELETE FROM public.dim_assets WHERE id = 2;
```

The last two commands are commented out intentionally. Deleting `cmc_price_histories7` loses the source data; deleting `dim_assets` removes the asset from the registry. Only uncomment these for a full decommission.

---

## See Also

- [DAILY_REFRESH.md](DAILY_REFRESH.md) — Daily incremental refresh operations
- [STATE_MANAGEMENT.md](STATE_MANAGEMENT.md) — State table schemas and reset patterns
- [REGIME_PIPELINE.md](REGIME_PIPELINE.md) — Regime pipeline details and debugging
- [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) — Full rebuild from scratch
