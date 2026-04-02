# Phase 97: FRED Macro Expansion - Research

**Researched:** 2026-03-30
**Domain:** FRED macro pipeline (fred_reader, feature_computer, cross_asset), DB schema extensions
**Confidence:** HIGH (all findings from direct source file inspection)

---

## Summary

Phase 97 adds SP500, NASDAQCOM, and DJIA to the macro feature pipeline and extends
`cross_asset.py` with multi-window BTC-equity correlation and risk-on/off divergence
signals. The three equity series are already partially wired (FFILL_LIMITS has them) but
are absent from SERIES_TO_LOAD and from the feature pipeline.

Two distinct workstreams compose this phase:

**MACRO-01 (fred_reader.py + feature_computer.py):** Add SP500/NASDAQCOM/DJIA to
SERIES_TO_LOAD, write a new generic `compute_per_series_features()` function, add 3x
derived feature sets to fred.fred_macro_features (new DB columns), update `_RENAME_MAP`
and `db_columns` allowlist, and update the VM FRED collector series list via `~/.fred.env`.

**MACRO-02 (cross_asset.py):** Extend `compute_crypto_macro_corr()` for multi-window
(30/60/90/180d) rolling correlation between all tier-1 crypto assets and the three equity
indices stored in `fred.fred_macro_features`. Add `window` column to
`crypto_macro_corr_regimes` PK (schema migration required). Compute SP500 realized vol
regime independently and cross-validate against VIX. Compute risk-on/off divergence
signal (dual method: z-score spread + correlation band breach) and store alongside
correlation values.

**Primary recommendation:** Implement MACRO-01 first (pure pipeline extension, no schema
conflicts), then MACRO-02 (schema migration + new computation logic). Both are
self-contained within the macro module; no other modules require changes.

---

## 1. Existing Infrastructure

### 1.1 fred_reader.py

**File:** `src/ta_lab2/macro/fred_reader.py`

**SERIES_TO_LOAD** (18 series currently):
- Does NOT include SP500, NASDAQCOM, DJIA — confirmed by inspection.
- The function signature: `load_series_wide(engine, series_ids=SERIES_TO_LOAD, start_date, end_date)`
- Returns wide DataFrame: `DatetimeIndex (tz-naive, daily 'D')`, columns = uppercase FRED IDs.

**FORWARD_FILL_LIMITS** is in `forward_fill.py` (not `fred_reader.py`). The three equity
indices ARE already in `FFILL_LIMITS` with limit=5:
```python
# In src/ta_lab2/macro/forward_fill.py lines 71-74
"SP500": 5,
"NASDAQCOM": 5,
"DJIA": 5,
"NASDAQ100": 5,  # also present but not part of Phase 97
```

NASDAQ100 is in FFILL_LIMITS but is NOT in the Phase 97 requirements. Do not add it to
SERIES_TO_LOAD.

### 1.2 feature_computer.py

**File:** `src/ta_lab2/macro/feature_computer.py`

**_RENAME_MAP** maps uppercase FRED ID to lowercase DB column name (18 entries). The
equity series are NOT in this map yet.

**compute_macro_features()** pipeline steps:
1. `load_series_wide()` — loads raw series
2. `forward_fill_with_limits()` — applies per-series limits
3. `compute_derived_features()` — Phase 65 specific columns (net_liquidity, rate_spreads, etc.)
4. `compute_derived_features_66()` — Phase 66 specific columns (hy_oas, nfci, m2, etc.)
5. Rename uppercase -> lowercase via `_RENAME_MAP`
6. Add source_freq provenance columns
7. Compute days_since_* from source_dates
8. **Filter to allowlist `db_columns`** — CRITICAL: new columns must be added to this list.

**No generic per-series feature function exists.** The 26 derived features per new series
(returns, vol, drawdown, MA ratios) must be implemented as a new function
`compute_per_series_features_97()` or similar.

### 1.3 fred.fred_macro_features Schema

**Migration history:**
- `a1b2c3d4e5f6_fred_macro_features.py` — Phase 65 baseline (PK: date, 11 raw + 8 derived + provenance cols)
- `c4d5e6f7a8b9_fred_phase66_derived_columns.py` — Phase 66 (adds 7 raw + 18 derived cols)

**Current column count:** 11+8 raw/derived (Phase 65) + 7+18 (Phase 66) + 6 provenance = ~50 cols.

**New columns needed for MACRO-01** (per-series, 3 series x ~8-9 cols each):
For each of SP500, NASDAQCOM, DJIA, add:
- Raw level: `sp500`, `nasdaqcom`, `djia` (Float, nullable)
- Returns: `sp500_ret_1d`, `sp500_ret_5d`, `sp500_ret_21d`, `sp500_ret_63d` (Float)
- Volatility: `sp500_vol_21d` (21d rolling vol of daily returns, Float)
- Drawdown from peak: `sp500_drawdown_pct` (Float, magnitude only, negative = below peak)
- MA ratios: `sp500_ma_ratio_50_200d` (price / 200d MA, Float) — or price/50d vs price/200d
- Z-score: `sp500_zscore_252d` (rolling z-score of level, 252d window)

**Total: ~3 raw + 3x8 derived = ~27 new columns.** These need a new alembic migration.

### 1.4 crypto_macro_corr_regimes Schema

**Migration:** `e1f2a3b4c5d6_cross_asset_aggregation_tables.py`

**Current PK:** `(date, asset_id, macro_var)` — single-window only.

**Current columns:** `date, asset_id, macro_var, corr_60d, prev_corr_60d, sign_flip_flag, corr_regime, ingested_at`

**CRITICAL GAP:** The `corr_60d` column is hardcoded to 60d window. The CONTEXT.md
decision requires 4 windows (30/60/90/180d). The CONTEXT.md says the schema "already has
window" — this is INCORRECT based on the actual migration file. A schema migration is
needed to:
1. Add `window INTEGER NOT NULL DEFAULT 60` column
2. Change PK from `(date, asset_id, macro_var)` to `(date, asset_id, macro_var, window)`
3. Rename `corr_60d` -> `correlation` (window-agnostic column name) OR add
   multi-window columns. The simpler approach: add `window` to PK + rename `corr_60d` to
   `correlation`. The rename + PK change must handle existing data.

**Existing indexes:**
- `idx_crypto_macro_corr_regimes_asset` on `(asset_id, date DESC)`
- `idx_crypto_macro_corr_regimes_flip` on `(sign_flip_flag)` WHERE TRUE

**Additional columns needed for MACRO-02:**
- `equity_vol_regime TEXT` (low/normal/high from SP500 realized vol — per row where macro_var is SP500/NASDAQCOM/DJIA)
- `vix_agreement_flag BOOLEAN` (vol_regime_agreement: 1=aligned, 0=diverged)
- `realized_vol_z FLOAT` (SP500 realized vol z-score for vol regime)
- `vix_z FLOAT` (VIX z-score, from fred_macro_features, for cross-validation)
- `vol_spread FLOAT` (continuous: realized_vol_z - vix_z)
- `divergence_zscore FLOAT` (z-score of asset_ret - SPX_ret, for risk-on/off)
- `divergence_flag BOOLEAN` (|z| > threshold OR correlation below 1-sigma band)

### 1.5 cross_asset.py

**File:** `src/ta_lab2/macro/cross_asset.py`

**compute_crypto_macro_corr():**
- Currently computes single 60d rolling corr per (asset, macro_var)
- `macro_var_columns` config dict maps label -> fred_macro_features column
- Loads from `fred.fred_macro_features` — new equity series will be available there after MACRO-01
- Stores to `crypto_macro_corr_regimes` with `ON CONFLICT (date, asset_id, macro_var) DO UPDATE`

**Key function signature:**
```python
def compute_crypto_macro_corr(engine, config, start_date=None, end_date=None,
                               alert_new_only=True) -> Tuple[pd.DataFrame, pd.DataFrame]:
```
Returns `(corr_df, regime_df)` where corr_df has columns:
`date, asset_id, macro_var, corr_60d, prev_corr_60d, sign_flip_flag, corr_regime`

**upsert_crypto_macro_corr()** uses `ON CONFLICT (date, asset_id, macro_var) DO UPDATE` —
must be updated to include `window` in the conflict target after schema migration.

**WARMUP_DAYS = 120** — sufficient for 180d window (add margin: should be at least 200d
for 180d window + correlation warmup).

**Config:** `configs/cross_asset_config.yaml`
- `crypto_macro.corr_window: 60` — currently single window
- `crypto_macro.macro_var_columns` — add SP500/NASDAQCOM/DJIA entries here
- Need: `btc_equity_corr_windows: [30, 60, 90, 180]` for new multi-window computation

### 1.6 VM FRED Collector

**File on VM:** `~/fred_pull.py` (copy at `.planning/vm_files/fred_pull.py`)

**Series list control:** `FRED_SERIES` environment variable in `~/.fred.env` on the GCP VM.

**To add SP500/NASDAQCOM/DJIA:** SSH to VM and edit `~/.fred.env` to add the three IDs to
the FRED_SERIES list. The `fred_pull.py` code reads `os.environ.get("FRED_SERIES", ...)`.

**No code changes to fred_pull.py needed** — it already handles any series via env var.
The sync script (`sync_fred_from_vm.py`) auto-discovers new series via `get_vm_counts()`
and pulls any series not yet in local DB.

### 1.7 Tier 1 Asset Definition

**Standard query:**
```sql
SELECT DISTINCT id FROM public.dim_assets WHERE pipeline_tier = 1 ORDER BY id
```
Used consistently throughout:
- `src/ta_lab2/scripts/desc_stats/refresh_cross_asset_corr.py:177`
- `src/ta_lab2/scripts/baseline/capture_baseline.py:887`
- `src/ta_lab2/scripts/desc_stats/refresh_asset_stats.py:420`

**cross_asset.py does NOT filter to tier 1 currently.** It loads all assets from
`returns_bars_multi_tf_u`. The CONTEXT.md says "all tier 1 assets." Phase 97 should add a
`WHERE id IN (SELECT id FROM dim_assets WHERE pipeline_tier = 1)` filter to the returns
query in `compute_crypto_macro_corr()`.

### 1.8 Macro Pipeline Execution Order

```
sync_fred_vm -> macro_features -> macro_regimes -> macro_analytics -> cross_asset_agg
             -> macro_gates -> macro_alerts -> regimes -> features -> signals
```

Phase 97 changes slot into:
- MACRO-01: `macro_features` step (no ordering change)
- MACRO-02: `cross_asset_agg` step (no ordering change, reads from fred_macro_features
  which is populated by the `macro_features` step)

---

## 2. Integration Points

### 2.1 SERIES_TO_LOAD in fred_reader.py

Add 3 entries to the list (after line 58, before closing `]`):
```python
# MACRO-01: US equity indices for BTC correlation
"SP500",       # S&P 500 index (daily, business days)
"NASDAQCOM",   # NASDAQ Composite index (daily, business days)
"DJIA",        # Dow Jones Industrial Average (daily, business days)
```

### 2.2 _RENAME_MAP in feature_computer.py

Add 3 entries:
```python
"SP500": "sp500",
"NASDAQCOM": "nasdaqcom",
"DJIA": "djia",
```

### 2.3 New Function: compute_per_series_features_97()

New function added to `feature_computer.py`. Called after `compute_derived_features_66()`.
Computes for each of SP500/NASDAQCOM/DJIA in the wide DataFrame:
- Returns: `.pct_change(1)`, `.pct_change(5)`, `.pct_change(21)`, `.pct_change(63)` (raw fractions or *100, consistent with existing DEXJPUS pattern which uses *100)
- Vol: rolling(21).std() of daily returns (annualizable, but store raw 21d std)
- Drawdown from peak: cummax() tracking, `(price - cummax) / cummax`
- MA ratio 50/200d: `price.rolling(50).mean() / price.rolling(200).mean()`
- Z-score: `_rolling_zscore(price, 252)` using existing helper

### 2.4 New Alembic Migration for fred_macro_features (MACRO-01 columns)

New migration file: `alembic/versions/p0q1r2s3t4u5_phase97_fred_equity_indices.py`
- `down_revision = "o9p0q1r2s3t4"`
- Adds raw columns: `sp500`, `nasdaqcom`, `djia` (Float, nullable, schema="fred")
- Adds derived columns per series (ret_1d, ret_5d, ret_21d, ret_63d, vol_21d, drawdown_pct, ma_ratio_50_200d, zscore_252d) x 3 series = 24 new derived columns

### 2.5 New Alembic Migration for crypto_macro_corr_regimes (MACRO-02 schema)

Separate migration or combined with MACRO-01:
- Add `window INTEGER NOT NULL DEFAULT 60` column
- DROP old PK constraint `(date, asset_id, macro_var)`
- ADD new PK constraint `(date, asset_id, macro_var, window)`
- Rename `corr_60d` -> `correlation` (optional: can keep corr_60d name but it's misleading)
  Recommendation: rename for clarity. Update all references in cross_asset.py.
- Add new signal columns: `equity_vol_regime`, `vix_agreement_flag`, `realized_vol_z`, `vix_z`, `vol_spread`, `divergence_zscore`, `divergence_flag`
- Update existing index `idx_crypto_macro_corr_regimes_asset` (add `window` to make unique scans efficient)

### 2.6 cross_asset.py Extensions

Extend `compute_crypto_macro_corr()`:
1. Add equity macro_var_columns from config (SP500, NASDAQCOM, DJIA mapping to lowercase column names)
2. Multi-window loop: for each window in `[30, 60, 90, 180]`:
   - Compute `asset_returns.rolling(window).corr(macro_series)`
   - Store with `window` field in row dict
3. SP500 realized vol regime classification (independent of VIX):
   - Load SP500 daily returns from fred_macro_features (sp500_ret_1d)
   - Compute rolling 21d realized vol
   - Classify: low/normal/high (configurable thresholds in YAML)
   - Compare to VIX regime from fred_macro_features
4. Divergence signal (per asset, per equity macro_var):
   - Z-score method: rolling z-score of (asset_ret - spx_ret_1d)
   - Band method: detect when correlation drops below (corr_mean - 1*corr_std) over 60d rolling window
5. Update `upsert_crypto_macro_corr()` conflict target to include `window`
6. Update `WARMUP_DAYS` from 120 to 210 (covers 180d + 30d margin)

### 2.7 cross_asset_config.yaml Extensions

Add new config section:
```yaml
btc_equity:
  corr_windows: [30, 60, 90, 180]
  equity_macro_vars:
    sp500: sp500_ret_1d      # daily return of SP500 for correlation vs raw level
    nasdaqcom: nasdaqcom_ret_1d
    djia: djia_ret_1d
  # OR if using level changes (matching existing vix/dxy pattern):
  # sp500: sp500             # raw level, daily diff applied in code
  vol_regime_thresholds:
    low_vol_pct: 10.0        # annualized %, below = low regime
    high_vol_pct: 20.0       # annualized %, above = high regime
  divergence_zscore_threshold: 2.0
  tier1_assets_only: true
```

---

## 3. Patterns to Follow

### 3.1 Adding New FRED Series (from Phase 66 precedent)

Phase 66 added 7 series to SERIES_TO_LOAD. The pattern:
1. Add IDs to `SERIES_TO_LOAD` in `fred_reader.py`
2. Add entries to `FFILL_LIMITS` in `forward_fill.py` (already done for SP500/NASDAQCOM/DJIA)
3. Add rename entries to `_RENAME_MAP` in `feature_computer.py`
4. Add derived computation function `compute_derived_features_66()` style
5. Add column names to `db_columns` allowlist in `compute_macro_features()`
6. Add Alembic migration for new columns
7. Update `_FEATURE_GROUPS` in `refresh_macro_features.py` for summary logging

### 3.2 Rolling Z-Score Pattern (from existing `_rolling_zscore()`)

```python
# Source: src/ta_lab2/macro/feature_computer.py lines 168-190
def _rolling_zscore(series: pd.Series, window: int, min_fill_pct: float = 0.80) -> pd.Series:
    min_periods = max(1, int(min_fill_pct * window))
    roll_mean = series.rolling(window, min_periods=min_periods).mean()
    roll_std = series.rolling(window, min_periods=min_periods).std()
    return (series - roll_mean) / roll_std
```
Use this existing helper directly. Do not re-implement.

### 3.3 Per-Series Pct Change Pattern (from DEXJPUS)

```python
# Source: src/ta_lab2/macro/feature_computer.py lines 316-331
jpy = result["DEXJPUS"]
result["dexjpus_5d_pct_change"] = jpy.pct_change(5) * 100.0
daily_ret = jpy.pct_change(1) * 100.0
result["dexjpus_20d_vol"] = daily_ret.rolling(20, min_periods=16).std()
```
Use pct_change (not diff) for price-like series. Multiply by 100 for percent.
min_periods = 0.8 * window rounded.

### 3.4 Drawdown From Peak Pattern

```python
# Pattern to implement (no existing template in macro module):
price_series = result["SP500"]
cummax = price_series.cummax()
result["sp500_drawdown_pct"] = ((price_series - cummax) / cummax * 100.0).where(price_series.notna(), other=None)
```
Magnitude-only means we store the signed negative value (0 at ATH, negative below).

### 3.5 MA Ratio Pattern

```python
# Pattern to implement:
price_series = result["SP500"]
ma50 = price_series.rolling(50, min_periods=40).mean()
ma200 = price_series.rolling(200, min_periods=160).mean()
result["sp500_ma_ratio_50_200d"] = (ma50 / ma200).where(ma200.notna() & (ma200 != 0), other=None)
```

### 3.6 Multi-Window Correlation (from existing single-window pattern)

```python
# Source: src/ta_lab2/macro/cross_asset.py lines 1019-1070 (inner loop)
# Extend to loop over windows:
for window in btc_equity_windows:  # [30, 60, 90, 180]
    roll_corr = asset_returns.rolling(
        window=window, min_periods=_CORR_MIN_PERIODS
    ).corr(macro_series)
    # Store row with 'window': window field
```

### 3.7 Upsert to crypto_macro_corr_regimes (from upsert_crypto_macro_corr)

After schema migration adds `window` to PK:
```python
# Conflict target must include window:
f"ON CONFLICT (date, asset_id, macro_var, window) DO UPDATE SET {set_clause}"
```

### 3.8 NaN/numpy Safety

```python
# Source: src/ta_lab2/macro/cross_asset.py lines 133-141
def _to_python(v):
    if v is None: return None
    if hasattr(v, "item"): v = v.item()
    if isinstance(v, float) and (v != v): return None
    return v
```
Always call `_sanitize_dataframe(df)` before upsert. Never pass numpy scalars to psycopg2 directly.

### 3.9 Tier 1 Asset Filter

```python
# Source: src/ta_lab2/scripts/desc_stats/refresh_cross_asset_corr.py lines 172-180
# In the XAGG-04 returns query, add WHERE clause:
"WHERE pipeline_tier = 1"
# Or use subquery:
"WHERE id IN (SELECT id FROM public.dim_assets WHERE pipeline_tier = 1)"
```

---

## 4. Risks and Pitfalls

### 4.1 crypto_macro_corr_regimes PK Conflict

**What:** The CONTEXT.md states "already has window" but the actual schema does NOT have a
`window` column. Adding multi-window rows without the schema change will fail with PK
violation (duplicate `(date, asset_id, macro_var)` for different windows).

**Resolution:** Migration MUST add `window` to PK BEFORE Phase 97 code changes run.
The migration also needs to UPDATE existing rows to set `window = 60` so they remain valid.

**Migration order:**
```sql
-- Step 1: add column with default
ALTER TABLE crypto_macro_corr_regimes ADD COLUMN window INTEGER NOT NULL DEFAULT 60;
-- Step 2: drop old PK
ALTER TABLE crypto_macro_corr_regimes DROP CONSTRAINT crypto_macro_corr_regimes_pkey;
-- Step 3: add new PK
ALTER TABLE crypto_macro_corr_regimes ADD CONSTRAINT crypto_macro_corr_regimes_pkey
    PRIMARY KEY (date, asset_id, macro_var, window);
```
This is safe: existing rows have `window=60` from DEFAULT, new multi-window rows add new PK combinations.

### 4.2 corr_60d Column Name Mismatch

**What:** If we rename `corr_60d` to `correlation`, all existing code referencing `corr_60d`
breaks (upsert_crypto_macro_corr, send_sign_flip_alerts, dashboard queries, etc.).

**Resolution:** Do NOT rename the column in the migration. Add `window` to PK but keep
`corr_60d` column name. For the new multi-window computation, the `corr_60d` column stores
the correlation value regardless of window. The `window` column in PK distinguishes the rows.
Document this naming oddity. Plan a rename to `correlation` in a future cleanup phase.

**Implication:** The upsert code writes `corr_60d` column for all windows (30d, 60d, 90d,
180d). This is technically mislabeled but avoids a risky column rename touching many consumers.

### 4.3 Warmup Window Too Short for 180d Correlation

**What:** Current `WARMUP_DAYS = 120` in `cross_asset.py`. 180d rolling correlation
needs at least 180d warmup + buffer for min_periods.

**Resolution:** Increase `WARMUP_DAYS` to 210 in cross_asset.py to cover the 180d window.

### 4.4 Equity Returns: Daily Diff vs Pct Change

**What:** The existing XAGG-04 code applies `.diff()` to VIX, DXY, HY OAS (level series)
but uses the series level directly for net_liquidity. Equity indices (SP500/NASDAQCOM/DJIA)
are price-level series. The correlation should use RETURNS (pct_change), not level diff.

**What to use:** For BTC-equity correlation, use daily pct_change of equity price (consistent
with how crypto returns are computed from `ret_arith` in returns_bars_multi_tf_u). The
MACRO-01 feature set adds `sp500_ret_1d` etc. to fred_macro_features, which should be
used in the XAGG-04 correlation computation (not the raw price level).

**Implication:** `macro_var_columns` in config must map to `sp500_ret_1d` not `sp500`.
This is only valid AFTER MACRO-01 runs and populates the ret columns.

**Alternative:** Compute equity returns inline in cross_asset.py from the raw level columns
(`sp500`, `nasdaqcom`, `djia`). This avoids dependency on MACRO-01 column naming.

**Recommendation:** Use `sp500.diff()` (same pattern as vix/dxy) inside cross_asset.py
for simplicity. The MACRO-01 return columns in fred_macro_features can be used separately
for IC analysis etc.

### 4.5 VM FRED Series Must Be Added Before Sync Can Populate Data

**What:** SP500/NASDAQCOM/DJIA data is not yet in `fred.series_values` locally. The
`load_series_wide()` will return an empty or partial DataFrame for these columns until
the VM collector runs with the new series and `sync_fred_from_vm.py` syncs them.

**Resolution:** Phase 97 must include a step to update `~/.fred.env` on the GCP VM
(SSH command) AND trigger a `sync_fred_from_vm --full` to backfill history. Document
this in the plan as a setup prerequisite.

**Initial backfill:** SP500 data on FRED goes back to 2000-01-03. NASDAQCOM to 1971-02-05.
DJIA to 1928-10-01. The `FULL_HISTORY_START = "2000-01-01"` in refresh_macro_features.py
covers the needed range.

### 4.6 db_columns Allowlist in compute_macro_features()

**What:** At the end of `compute_macro_features()`, there is an explicit allowlist
`db_columns` that filters the final DataFrame. Any new column NOT added to this list
will be silently dropped, causing the DB upsert to never write the new features.

**Resolution:** All new equity columns (raw: sp500/nasdaqcom/djia, and derived: ret_1d,
ret_5d, ret_21d, ret_63d, vol_21d, drawdown_pct, ma_ratio_50_200d, zscore_252d for each
series) MUST be added to the `db_columns` list.

### 4.7 Divergence Signal Requires SP500 Return Series

**What:** The risk-on/off divergence z-score requires `asset_ret - spx_ret_1d`. The
crypto returns come from `returns_bars_multi_tf_u`, but SP500 returns must come from
either `fred_macro_features.sp500_ret_1d` (post-MACRO-01) or computed inline from the
`sp500` level column.

**Resolution:** Use `fred_macro_features.sp500_ret_1d` (requires MACRO-01 to run first
in the same pipeline invocation, which it does — macro_features runs before cross_asset_agg).

### 4.8 Sign-Flip Alerts Reference corr_60d Column

**What:** `send_sign_flip_alerts()` reads `row.get("prev_corr_60d")` and `row.get("corr_60d")`.
When multi-window rows exist in the DataFrame, this will generate alerts for EACH window
independently (e.g., 4 alerts per asset-macro_var pair per sign flip).

**Resolution:** Filter sign-flip alert logic to only the canonical 60d window
(`window == 60`) to avoid alert spam. Add `alert_df = alert_df[alert_df.get('window', 60) == 60]`
before `send_sign_flip_alerts()`.

---

## 5. Implementation Recommendations

### 5.1 MACRO-01 Implementation Order

1. Edit `fred_reader.py`: Add SP500/NASDAQCOM/DJIA to `SERIES_TO_LOAD`.
2. Edit `feature_computer.py`:
   a. Add 3 entries to `_RENAME_MAP`
   b. Write `compute_per_series_features_97(df)` function (returns, vol, drawdown, MA ratio, z-score)
   c. Call it in `compute_macro_features()` after `compute_derived_features_66()`
   d. Add all new columns to `db_columns` allowlist
3. Write alembic migration: `p0q1r2s3t4u5_phase97_fred_equity_indices.py`
   - Add raw columns `sp500`, `nasdaqcom`, `djia` to `fred.fred_macro_features`
   - Add derived columns per series (schema="fred")
4. Update `_FEATURE_GROUPS` in `refresh_macro_features.py` for summary logging
5. VM setup: SSH to GCP VM, update `~/.fred.env` FRED_SERIES, backfill via `sync_fred_from_vm --full`

### 5.2 MACRO-02 Implementation Order

1. Write alembic migration: `q1r2s3t4u5v6_phase97_crypto_equity_corr_schema.py`
   - ADD `window INTEGER NOT NULL DEFAULT 60` to `crypto_macro_corr_regimes`
   - DROP + RECREATE PK to include `window`
   - ADD signal columns: `equity_vol_regime`, `vix_agreement_flag`, `realized_vol_z`, `vix_z`, `vol_spread`, `divergence_zscore`, `divergence_flag`
2. Edit `cross_asset_config.yaml`: Add `btc_equity` config section with windows and thresholds
3. Edit `cross_asset.py`:
   a. Increase `WARMUP_DAYS` to 210
   b. Add equity macro_var support to `compute_crypto_macro_corr()`:
      - Read equity columns from fred_macro_features (sp500/nasdaqcom/djia level)
      - Apply `.diff()` for daily change (matches existing vix/dxy pattern)
      - Loop over 4 windows for equity correlations
      - SP500 realized vol regime classification inline
      - VIX cross-validation (vol spread + agreement flag)
      - Divergence signal computation (both methods)
   c. Add tier-1 asset filter to returns query
   d. Update `upsert_crypto_macro_corr()` conflict target to include `window`
   e. Filter sign-flip alerts to `window == 60`
4. Update `refresh_cross_asset_agg.py` print stats to include window breakdown

### 5.3 New Columns for fred_macro_features (MACRO-01)

For each series prefix `{pfx}` in (`sp500`, `nasdaqcom`, `djia`):
| Column | Type | Computation |
|--------|------|-------------|
| `{pfx}` | Float | Raw level (forward-filled) |
| `{pfx}_ret_1d` | Float | pct_change(1) * 100 |
| `{pfx}_ret_5d` | Float | pct_change(5) * 100 |
| `{pfx}_ret_21d` | Float | pct_change(21) * 100 |
| `{pfx}_ret_63d` | Float | pct_change(63) * 100 |
| `{pfx}_vol_21d` | Float | rolling(21).std() of ret_1d |
| `{pfx}_drawdown_pct` | Float | (price - cummax) / cummax * 100 |
| `{pfx}_ma_ratio_50_200d` | Float | rolling(50).mean() / rolling(200).mean() |
| `{pfx}_zscore_252d` | Float | _rolling_zscore(price, 252) |

Total new columns: 3 raw + 3x8 derived = 27 columns.

### 5.4 New Columns for crypto_macro_corr_regimes (MACRO-02)

| Column | Type | Notes |
|--------|------|-------|
| `window` | INTEGER NOT NULL DEFAULT 60 | Added to PK |
| `equity_vol_regime` | TEXT | low/normal/high (only for equity macro_vars) |
| `vix_agreement_flag` | BOOLEAN | vol_regime matches VIX regime |
| `realized_vol_z` | FLOAT | SP500 21d realized vol z-score |
| `vix_z` | FLOAT | VIX z-score (from fred_macro_features) |
| `vol_spread` | FLOAT | realized_vol_z - vix_z |
| `divergence_zscore` | FLOAT | z-score of (asset_ret - spx_ret) |
| `divergence_flag` | BOOLEAN | |z| > threshold OR corr < 1-sigma band |

### 5.5 Config Changes Summary

`configs/cross_asset_config.yaml` additions:
```yaml
btc_equity:
  corr_windows: [30, 60, 90, 180]
  equity_macro_vars:
    sp500: sp500            # fred_macro_features column (use .diff() for changes)
    nasdaqcom: nasdaqcom    # fred_macro_features column
    djia: djia              # fred_macro_features column
  vol_regime_thresholds:
    low_pct_annualized: 10.0    # 21d realized vol annualized, below = low
    high_pct_annualized: 20.0   # 21d realized vol annualized, above = high
  divergence_zscore_threshold: 2.0
  sign_flip_threshold_equity: 0.3   # same as existing macro vars
```

---

## Sources

### Primary (HIGH confidence — direct file inspection)
- `src/ta_lab2/macro/fred_reader.py` — SERIES_TO_LOAD structure, load_series_wide()
- `src/ta_lab2/macro/forward_fill.py` — FFILL_LIMITS (SP500/NASDAQCOM/DJIA already present)
- `src/ta_lab2/macro/feature_computer.py` — _RENAME_MAP, compute pipeline, db_columns allowlist
- `src/ta_lab2/macro/cross_asset.py` — compute_crypto_macro_corr(), upsert pattern, WARMUP_DAYS
- `src/ta_lab2/scripts/macro/refresh_macro_features.py` — WARMUP_DAYS=400, upsert_macro_features(), _FEATURE_GROUPS
- `src/ta_lab2/scripts/macro/refresh_cross_asset_agg.py` — orchestration pattern
- `alembic/versions/e1f2a3b4c5d6_cross_asset_aggregation_tables.py` — actual crypto_macro_corr_regimes schema
- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` — fred.fred_macro_features schema
- `alembic/versions/c4d5e6f7a8b9_fred_phase66_derived_columns.py` — Phase 66 column additions
- `alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py` — latest migration (down_revision)
- `configs/cross_asset_config.yaml` — current macro_var_columns configuration
- `.planning/vm_files/fred_pull.py` — VM series collection via FRED_SERIES env var
- `sql/migration/add_pipeline_tier.sql` — pipeline_tier=1 definition
- `src/ta_lab2/scripts/run_daily_refresh.py` — pipeline ordering confirmation

---

## Metadata

**Confidence breakdown:**
- Existing infrastructure (file paths, schemas, function signatures): HIGH — all verified by direct read
- SERIES_TO_LOAD gap (SP500 not present): HIGH — confirmed by reading fred_reader.py
- FFILL_LIMITS already has SP500/NASDAQCOM/DJIA: HIGH — confirmed in forward_fill.py lines 71-74
- crypto_macro_corr_regimes missing `window` column: HIGH — confirmed in migration file
- CONTEXT.md claim that schema "already has window": INCORRECT — actual schema does not
- Generic per-series feature function does not exist: HIGH — verified no such function in feature_computer.py
- VM env var controls series list (no code change to fred_pull.py needed): HIGH — from vm_files/fred_pull.py
- Tier 1 = `pipeline_tier = 1` in dim_assets: HIGH — from sql/migration and usage across codebase
- Correct alembic down_revision = "o9p0q1r2s3t4": HIGH — from phase96 migration inspection

**Research date:** 2026-03-30
**Valid until:** 2026-05-01 (stable codebase, 30-day horizon)
