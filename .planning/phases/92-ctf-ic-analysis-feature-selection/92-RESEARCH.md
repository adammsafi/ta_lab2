# Phase 92: CTF IC Analysis & Feature Selection - Research

**Researched:** 2026-03-23
**Domain:** CTF pivot loading, IC pipeline integration, feature tier classification, separate DB table, config pruning
**Confidence:** HIGH

---

## Summary

Phase 92 scores the CTF feature table through the existing IC pipeline from Phase 80.
The IC infrastructure (`batch_compute_ic`, `save_ic_results`, `classify_feature_tier`,
`build_feature_selection_config`) is complete and proven. The CTF schema (`public.ctf`,
`dim_ctf_indicators`, `ctf_state`) is fully deployed from Phases 89-91. The main new
work is: (1) a pivot loader `load_ctf_features()` that reads normalized CTF rows and
reshapes them to a wide DataFrame matching `batch_compute_ic()` expectations, (2) a
new CTF sweep script (`run_ctf_ic_sweep.py`) following the same pattern as
`run_ic_sweep.py`, (3) a new Alembic migration for `dim_ctf_feature_selection`, and
(4) a comparison report script that checks CTF vs AMA IC-IR redundancy.

The context decisions constrain four key design choices: separate DB table (not
`dim_feature_selection`), IC-IR cutoff 0.5 (not 1.0), all 6 base TFs analyzed, pruned
config written to `ctf_config_pruned.yaml` (not overwriting the original).

**Primary recommendation:** Add `load_ctf_features()` to
`src/ta_lab2/features/cross_timeframe.py` (not a new module), using per-asset-base_tf
batching to avoid materializing all 792 columns for all 109 assets at once.

---

## 1. batch_compute_ic() Input/Output Contract

**Source:** `src/ta_lab2/analysis/ic.py` lines 623-801. Confidence: HIGH (direct code read).

### Input requirements

```python
batch_compute_ic(
    features_df: pd.DataFrame,   # UTC-indexed, columns = feature names, numeric only
    close: pd.Series,            # UTC-indexed close prices, same or broader index
    train_start: pd.Timestamp,   # REQUIRED, no default
    train_end: pd.Timestamp,     # REQUIRED, no default
    feature_cols: list[str],     # optional - defaults to all numeric cols except 'close'
    horizons: list[int],         # default [1,2,3,5,10,20,60]
    return_types: list[str],     # default ['arith','log']
    rolling_window: int,         # default 63
    tf_days_nominal: int,        # default 1 - IMPORTANT: must match base_tf
    min_obs: int,                # default 20
)
```

Critical requirements for `features_df`:
- **Index**: DatetimeIndex, timezone-aware UTC (`pd.to_datetime(utc=True)` pattern)
- **Columns**: numeric (float), no string/categorical columns — the function uses `select_dtypes(include=[np.number])` when `feature_cols=None`
- **`close` column**: excluded automatically by name, but the pivot loader should NOT include a `close` column in `features_df` — pass `close` as the separate Series
- **NULL handling**: NaN values are dropped per-feature internally (`dropna()`); all-null columns should be pre-filtered before calling

### Output

```python
pd.DataFrame  # one row per (feature, horizon, return_type)
# Columns: feature, horizon, return_type, ic, ic_t_stat, ic_p_value,
#          ic_ir, ic_ir_t_stat, turnover, n_obs
```

The `feature` column holds the column name from `features_df`. For CTF features, this will be the pivot column name (e.g., `rsi_14_7d_slope`).

### tf_days_nominal requirement

This parameter is CRITICAL for boundary masking. For Phase 92, the base_tf maps to:

| base_tf | tf_days_nominal |
|---------|----------------|
| 1D      | 1               |
| 2D      | 2               |
| 3D      | 3               |
| 7D      | 7               |
| 14D     | 14              |
| 30D     | 30              |

Use `DimTimeframe.tf_days(base_tf)` (same as `run_ic_sweep.py`) to resolve this.

---

## 2. Feature Selection Tier Classification

**Source:** `src/ta_lab2/analysis/feature_selection.py` lines 408-491. Confidence: HIGH.

### classify_feature_tier() signature

```python
classify_feature_tier(
    ic_ir_mean: float,
    pass_rate: float,
    stationarity: str,      # 'STATIONARY'|'NON_STATIONARY'|'AMBIGUOUS'|'INSUFFICIENT_DATA'
    regime_ic: Optional[pd.DataFrame],  # None = no regime data
    ic_ir_cutoff: float,    # default 0.3 — Phase 92 uses 0.5
) -> str  # 'active'|'conditional'|'watch'|'archive'
```

### Tier rules (with 0.5 cutoff for Phase 92)

| Tier       | Condition |
|------------|-----------|
| active     | `ic_ir_mean >= 0.75` (NON_STATIONARY) or `>= 0.5` (others) AND `pass_rate >= 0.30` |
| conditional | regime specialist (`best_regime_ic >= 0.5`) OR borderline (`0.15 <= ic_ir_mean < 0.5 AND pass_rate >= 0.20`) |
| watch      | `ic_ir_mean >= 0.10` |
| archive    | `ic_ir_mean < 0.10` |

Note: Non-stationary features get 1.5x cutoff = 0.75 at Phase 92's 0.5 default.

### build_feature_selection_config() data flow

`build_feature_selection_config()` takes:
- `ranking_df` — from `load_ic_ranking()` (queries `ic_results` grouped by feature)
- `stationarity_results` — dict keyed by feature name
- `ljungbox_results` — dict keyed by feature name
- `monotonicity_scores` — dict of float keyed by feature name
- `regime_ic_map` — dict of DataFrames keyed by feature name

The CTF phase can reuse this function directly. However, for CTF features,
`load_ic_ranking()` queries `ic_results` with no filter on feature name prefix — so
after CTF IC rows are persisted to `ic_results`, `load_ic_ranking()` will return CTF
features mixed with Phase 80 features. Phase 92 must filter by feature name prefix
(e.g., only rows where `feature` matches CTF naming pattern `{indicator}_{ref_tf}_{composite}`).

### save_to_db() — NOT to be reused for CTF

`save_to_db()` in `feature_selection.py` truncates `dim_feature_selection` on every run
(line 754: `TRUNCATE TABLE public.dim_feature_selection`). This would wipe Phase 80
entries. A separate `save_ctf_to_db()` function must be written that targets
`dim_ctf_feature_selection` and uses `ON CONFLICT DO UPDATE` semantics.

---

## 3. dim_feature_selection Schema and Phase 80 Entries

**Source:** `alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py`. Confidence: HIGH.

```sql
CREATE TABLE public.dim_feature_selection (
    feature_name          TEXT NOT NULL PRIMARY KEY,
    tier                  TEXT NOT NULL CHECK (tier IN ('active','conditional','watch','archive')),
    ic_ir_mean            NUMERIC,
    pass_rate             NUMERIC,
    quintile_monotonicity NUMERIC,
    stationarity          TEXT CHECK (stationarity IN ('STATIONARY','NON_STATIONARY','AMBIGUOUS','INSUFFICIENT_DATA')),
    ljung_box_flag        BOOLEAN DEFAULT FALSE,
    regime_specialist     BOOLEAN DEFAULT FALSE,
    specialist_regimes    TEXT[],
    selected_at           TIMESTAMPTZ DEFAULT now(),
    yaml_version          TEXT,
    rationale             TEXT
)
```

Phase 80 entries include features like `ret_is_outlier`, `TEMA_0fca19a1_ama`,
`DEMA_0fca19a1_ama`, `KAMA_987fc105_ama`, `bb_ma_20`, `close_fracdiff` (confirmed from
`configs/feature_selection.yaml` which is the current output of Phase 80 run).

The CTF-separate table (`dim_ctf_feature_selection`) should mirror this schema but may
add a `base_tf` column since CTF features are per-base_tf, and an `indicator_name`
column for grouping. Alternatively, use the same schema and encode base_tf in the
`feature_name` (which will be the pivot column name like `rsi_14_7d_slope`). The
pivot column name already encodes the indicator, ref_tf, and composite — so the same
schema can be used without modification.

---

## 4. run_ic_sweep.py and run_feature_selection.py Patterns

**Source:** Direct code read. Confidence: HIGH.

### run_ic_sweep.py pattern (to replicate for CTF)

The sweep script follows this structure:
1. `_discover_features_pairs()` — finds (asset_id, tf, n_rows) qualifying combos from `asset_data_coverage`
2. `_load_features_and_close()` — loads feature columns + close from `features` table
3. `batch_compute_ic()` — computes all IC metrics for all features at once
4. `_rows_from_ic_df()` — converts output DataFrame to list of dicts for persistence
5. `save_ic_results(conn, rows, overwrite=True)` — upserts to `ic_results`
6. Multiprocessing via `Pool` + `ICWorkerTask` frozen dataclass with `maxtasksperchild=1`

The `ICWorkerTask` pattern (frozen dataclass, module-level worker function) is MANDATORY
on Windows for multiprocessing pickling. The CTF sweep worker must follow this same
pattern.

### Key run_ic_sweep.py utilities to reuse for CTF

```python
from ta_lab2.analysis.ic import batch_compute_ic, save_ic_results
from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.scripts.sync_utils import get_columns, table_exists
from ta_lab2.time.dim_timeframe import DimTimeframe
```

- `_to_utc_timestamp()` helper for Windows tz-fix — copy or import
- `DimTimeframe.from_db(db_url)` — resolves `tf_days_nominal` for boundary masking
- `_rows_from_ic_df()` — exact same output format as features IC; reuse directly

### run_feature_selection.py pipeline steps

The 7-step pipeline can be reused for CTF with modifications:
- Step 0: IC decay sweep — query `ic_results` filtered to CTF feature names
- Step 1: Load IC ranking — query `ic_results` filtered to CTF features
- Step 2: Stationarity tests — but CTF has no raw feature values in `features` table; must load from `ctf` table via `load_ctf_features()`
- Step 3: Ljung-Box — same, loads via CTF pivot loader
- Step 4: Regime IC — `load_regime_ic()` queries `ic_results` by feature name — works as-is after CTF IC is persisted
- Step 5: Quintile monotonicity — CTF features are per-asset-base_tf, not cross-sectional; quintile analysis is questionable for CTF (time-series, not cross-sectional)
- Step 6: Build config — `build_feature_selection_config()` reusable as-is
- Step 7: Write to `dim_ctf_feature_selection` (not `dim_feature_selection`)

---

## 5. CTF Table Schema and Data Volume

**Source:** `alembic/versions/j4k5l6m7n8o9_ctf_schema.py`. Confidence: HIGH.

### CTF fact table schema

```sql
CREATE TABLE public.ctf (
    id               INTEGER NOT NULL,
    venue_id         SMALLINT NOT NULL REFERENCES dim_venues(venue_id),
    ts               TIMESTAMPTZ NOT NULL,
    base_tf          TEXT NOT NULL,
    ref_tf           TEXT NOT NULL,
    indicator_id     SMALLINT NOT NULL REFERENCES dim_ctf_indicators(indicator_id),
    alignment_source TEXT NOT NULL,
    ref_value        DOUBLE PRECISION,
    base_value       DOUBLE PRECISION,
    slope            DOUBLE PRECISION,
    divergence       DOUBLE PRECISION,
    agreement        DOUBLE PRECISION,
    crossover        DOUBLE PRECISION,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)
)
```

### dim_ctf_indicators (22 seeded indicators)

| indicator_name       | source_table            | is_directional |
|----------------------|-------------------------|----------------|
| rsi_14, rsi_7, rsi_21 | ta                    | FALSE          |
| macd_12_26, macd_hist_12_26_9, macd_8_17, macd_hist_8_17_9 | ta | TRUE |
| adx_14, bb_width_20, stoch_k_14, atr_14 | ta            | FALSE          |
| vol_parkinson_20, vol_gk_20, vol_rs_20, vol_log_roll_20 | vol | FALSE |
| vol_parkinson_63, vol_gk_63, vol_log_roll_63 | vol        | FALSE          |
| ret_arith, ret_log   | returns_bars_multi_tf_u | TRUE           |
| close_fracdiff       | features                | TRUE           |
| sadf_stat            | features                | FALSE          |

Total: 11 TA (non-directional/directional mix) + 7 vol (non-directional) + 2 returns (directional) + 2 features = 22 indicators.

Directional count: 7 (4 MACD + 2 returns + fracdiff)
Non-directional count: 15 (RSI + ADX + BB + Stoch + ATR + all vol + SADF)

### CTF timeframe pairs and ref_tf counts

| base_tf | ref_tfs count | ref_tfs |
|---------|---------------|---------|
| 1D      | 6             | 7D, 14D, 30D, 90D, 180D, 365D |
| 2D      | 6             | 7D, 14D, 30D, 90D, 180D, 365D |
| 3D      | 6             | 7D, 14D, 30D, 90D, 180D, 365D |
| 7D      | 4             | 30D, 90D, 180D, 365D |
| 14D     | 3             | 90D, 180D, 365D |
| 30D     | 2             | 180D, 365D |

Total (base_tf, ref_tf) pairs: 6+6+6+4+3+2 = 27

### Pivot dimension calculation

For each (asset, base_tf) pair, the pivot has up to:
- 22 indicators × N ref_tfs × 6 composites = columns
  - At 1D base_tf: 22 × 6 × 6 = 792 columns
  - At 30D base_tf: 22 × 2 × 6 = 264 columns

Total potential unique CTF feature names: 22 × 27 pairs × 6 composites = 3,564. However:
- 15 non-directional indicators produce NaN for `crossover` (agreement may also be
  restricted) — reducing active non-null columns
- Actual non-null column count per base_tf will be lower than theoretical max

### Memory considerations for pivot

For 109 assets × 1,000 bars (typical at 1D) × 792 columns at 8 bytes = ~690 MB per
base_tf if done all at once. Per-asset processing avoids this: 1 asset × 1,000 bars
× 792 cols = ~6.3 MB per asset, well within memory.

**Recommendation:** Process CTF IC analysis per-asset (same pattern as `run_ic_sweep.py`).
Load all CTF rows for one asset + one base_tf, pivot, compute IC, persist, move on.

---

## 6. cross_timeframe.py Structure and load_ctf_features() Placement

**Source:** `src/ta_lab2/features/cross_timeframe.py` (full read). Confidence: HIGH.

The file is 862 lines and contains:
- Module-level helpers: `_compute_slope`, `_compute_divergence`, `_compute_agreement`, `_compute_crossover`
- `CTFConfig` frozen dataclass (lines 221-237)
- `CTFFeature` class (lines 245-861) with: `_load_ctf_config`, `_load_dim_ctf_indicators`, `_load_indicators_batch`, `_align_timeframes`, `_get_table_columns`, `_write_to_db`, `_compute_one_source`, `compute_for_ids`

### Where to add load_ctf_features()

`load_ctf_features()` is a **read-side** function that queries `public.ctf` and returns
a wide-format DataFrame for IC analysis. It does not belong inside the `CTFFeature`
class (which is write-side). It should be a module-level function in `cross_timeframe.py`
alongside the existing module-level helpers.

### Required signature (from CONTEXT.md decisions)

```python
def load_ctf_features(
    conn,                      # SQLAlchemy connection
    asset_id: int,
    base_tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    *,
    ref_tfs: Optional[list[str]] = None,   # None = all ref_tfs in data
    indicator_names: Optional[list[str]] = None,  # None = all indicators
    alignment_source: str = "multi_tf",
    venue_id: int = 1,
) -> pd.DataFrame:
    """
    Load CTF rows for one asset + base_tf, pivot to wide format.

    Column naming: {indicator_name}_{ref_tf_lowercase}_{composite}
    e.g., rsi_14_7d_slope, macd_12_26_30d_crossover

    Returns:
        pd.DataFrame indexed by ts (UTC), one column per (indicator, ref_tf, composite).
        Only composites with non-all-null data are included.
        Compatible with batch_compute_ic() feature_cols discovery.
    """
```

### Pivot SQL query pattern

```sql
SELECT
    c.ts,
    d.indicator_name,
    c.ref_tf,
    c.ref_value,
    c.base_value,
    c.slope,
    c.divergence,
    c.agreement,
    c.crossover
FROM public.ctf c
JOIN public.dim_ctf_indicators d ON d.indicator_id = c.indicator_id
WHERE c.id = :asset_id
  AND c.base_tf = :base_tf
  AND c.ts >= :train_start
  AND c.ts <= :train_end
  AND c.alignment_source = :alignment_source
  AND c.venue_id = :venue_id
ORDER BY c.ts, d.indicator_name, c.ref_tf
```

Then pivot using pandas: `melt` + column name construction + `pivot_table(index='ts')`.

### ref_tf formatting in column names

The context decision specifies `{indicator_name}_{ref_tf}_{composite}` with example
`rsi_14_7d_slope`. The `ref_tf` in the database is stored as `"7D"`, `"30D"`, etc.
Convert to lowercase for column names: `ref_tf.lower()` (7d, 30d, etc.).

---

## 7. Forward Returns Data and IC Computation Access

**Source:** `src/ta_lab2/analysis/ic.py` `compute_forward_returns()` and `batch_compute_ic()`. Confidence: HIGH.

`batch_compute_ic()` computes forward returns internally from the `close` Series passed
to it. It calls `compute_forward_returns(close, horizon, log)` which does `close.shift(-horizon) / close - 1.0`.

For CTF IC analysis, `close` must come from `features` (not from CTF itself). The
pattern in `run_ic_sweep.py` is:

```python
features_df, close_series = _load_features_and_close(conn, asset_id, tf, feature_cols)
```

For CTF, the loader will be:
```python
ctf_pivot_df = load_ctf_features(conn, asset_id, base_tf, train_start, train_end)
close_series = _load_close_for_asset(conn, asset_id, base_tf)
```

The `close` series should come from `features` table (same source as Phase 80):
```sql
SELECT ts, close FROM public.features
WHERE id = :asset_id AND tf = :base_tf
ORDER BY ts
```

**Important**: `features` table uses `tf` column (string, e.g. `'1D'`), `venue_id` defaults
to 1 (CMC_AGG), and does NOT have `alignment_source` column. The `features` query does
not need `venue_id` or `alignment_source` filters.

---

## 8. feature_selection.yaml Structure and ic_results Conflict

**Source:** `configs/feature_selection.yaml` + `feature_selection.py`. Confidence: HIGH.

### ic_results table is SHARED

Both Phase 80 and Phase 92 write to the SAME `ic_results` table. The `feature` column
stores the column name (e.g., `TEMA_0fca19a1_ama`, `rsi_14_7d_slope`). This is
intentional — CTF IC results live alongside AMA/features IC results, enabling direct
SQL comparison queries.

The `ic_results` unique conflict key is:
```
(asset_id, tf, feature, horizon, return_type, regime_col, regime_label, train_start, train_end)
```

CTF features have distinctive names (`{indicator}_{ref_tf}_{composite}`) that do not
collide with Phase 80 feature names (which are column names from `features` or
`ama_multi_tf_u`). No conflict risk.

### load_ic_ranking() filtering for CTF

`load_ic_ranking()` returns ALL features from `ic_results`. After CTF IC sweep completes,
must filter to CTF-only features. Two options:
1. Filter by naming convention: `WHERE feature LIKE '%_slope' OR feature LIKE '%_divergence' OR ...`
2. Query `dim_ctf_indicators` to get valid indicator names, then filter

Option 2 is more robust. Build the filter set: join indicator names × ref_tfs × composites.

---

## 9. dim_ctf_feature_selection Alembic Migration

**Confidence:** HIGH (confirmed from CONTEXT.md: "Persist to SEPARATE table").

A new Alembic migration is required. Current alembic head is
`k5l6m7n8o9p0_ctf_state.py`. New migration should set:
- `down_revision = "k5l6m7n8o9p0"`
- Choose next revision ID: `l6m7n8o9p0q1` (following the pattern)

### Proposed schema

```sql
CREATE TABLE public.dim_ctf_feature_selection (
    feature_name          TEXT NOT NULL,       -- e.g. rsi_14_7d_slope
    base_tf               TEXT NOT NULL,       -- e.g. '1D', '7D'
    tier                  TEXT NOT NULL
        CHECK (tier IN ('active','conditional','watch','archive')),
    ic_ir_mean            NUMERIC,
    pass_rate             NUMERIC,
    stationarity          TEXT
        CHECK (stationarity IN ('STATIONARY','NON_STATIONARY','AMBIGUOUS','INSUFFICIENT_DATA')),
    ljung_box_flag        BOOLEAN DEFAULT FALSE,
    selected_at           TIMESTAMPTZ DEFAULT now(),
    yaml_version          TEXT,
    rationale             TEXT,
    PRIMARY KEY (feature_name, base_tf)
)
```

Adding `base_tf` to the PK is necessary because the same CTF feature name (e.g.,
`rsi_14_7d_slope`) will be evaluated at multiple base TFs (1D, 2D, 3D, 7D) and may
have different IC-IR at each.

Note: `quintile_monotonicity`, `regime_specialist`, and `specialist_regimes` are omitted
from the CTF table. Quintile monotonicity is inapplicable (CTF features are per-asset,
not cross-sectional). Regime specialist can be added later if needed.

---

## 10. Comparison Report Structure

**Source:** Phase 80 context decisions + `reports/bakeoff/` patterns. Confidence: MEDIUM.

### Existing report patterns

The `reports/bakeoff/feature_ic_ranking.csv` is a simple CSV with columns:
`feature, mean_abs_ic, mean_ic_ir, mean_abs_ic_ir, n_observations, n_asset_tf_pairs`.

The `reports/bakeoff/phase82_results.md` is a structured markdown with Overview,
Gate Application, and Strategy Summary sections.

### Recommended CTF comparison report structure

Write to `reports/ctf/ctf_ic_comparison_report.md`:

```markdown
# CTF vs AMA Feature IC Comparison Report

**Generated:** {timestamp}
**IC-IR cutoff:** 0.5
**Assets analyzed:** {N}
**Base TFs analyzed:** 1D, 2D, 3D, 7D, 14D, 30D

## Summary Statistics

| Source | Features analyzed | Active (>=0.5) | Conditional | Watch | Archive |
|--------|------------------|----------------|-------------|-------|---------|
| CTF    | N                | N              | N           | N     | N       |
| AMA    | N                | N              | N           | N     | N       |

## Top CTF Features by IC-IR (horizon=1, arith)

| Feature | IC-IR | IC | pass_rate | tier |
|---------|-------|----|-----------|------|
| ...     |       |    |           |      |

## Redundancy Analysis

For each CTF feature that reaches active/conditional tier:
- Spearman correlation between CTF IC series and nearest AMA IC series
- Conclusion: redundant (corr > 0.7) or non-redundant (corr <= 0.7)

## Head-to-Head: CTF IC-IR vs Best AMA IC-IR

| Metric | CTF best | AMA best | CTF advantage |
|--------|----------|----------|---------------|
| ...    |          |          |               |

## Pruning Recommendations

CTF combinations to retain in ctf_config_pruned.yaml:
- Indicators with any active/conditional feature at any base_tf × ref_tf
- All 6 base_tfs retained (per context decision)

CTF combinations to archive:
- Indicators where ALL composites are archive at ALL base_tf × ref_tf combinations
```

Also write a companion JSON at `reports/ctf/ctf_ic_comparison_report.json` with the
same data in machine-readable format for downstream scripts.

---

## Architecture Patterns

### Recommended script structure

```
src/ta_lab2/features/cross_timeframe.py
  + load_ctf_features()               # NEW: pivot loader, module-level function

src/ta_lab2/scripts/analysis/
  run_ctf_ic_sweep.py                 # NEW: IC sweep for CTF features
  run_ctf_feature_selection.py        # NEW: tier classification + comparison report

alembic/versions/
  l6m7n8o9p0q1_dim_ctf_feature_selection.py  # NEW: separate table migration
```

### run_ctf_ic_sweep.py structure

Follows `run_ic_sweep.py` exactly, with these differences:
- Discovery: query `ctf` table for qualifying (asset_id, base_tf) pairs with >= 500 rows
- Data loading: `load_ctf_features(conn, asset_id, base_tf, train_start, train_end)` instead of `_load_features_and_close()`
- Close loading: `SELECT ts, close FROM features WHERE id=:id AND tf=:base_tf ORDER BY ts`
- Feature naming: pivot column names are already the feature names for `ic_results`
- `feature` column in `ic_results` will store e.g. `rsi_14_7d_slope`
- `tf` column in `ic_results` stores `base_tf` (e.g. `'1D'`)
- tf_days_nominal: derived from base_tf via `DimTimeframe.tf_days(base_tf)`
- Parallel pattern: same `ICWorkerTask` frozen dataclass + module-level worker + `Pool(maxtasksperchild=1)`

### run_ctf_feature_selection.py structure

Steps:
1. Query `ic_results` for CTF features (filter by feature names matching CTF pattern)
2. Build `ranking_df` grouped by feature, compute `mean_abs_ic_ir` and `pass_rate`
3. Run stationarity tests on representative CTF series (load via `load_ctf_features()`)
4. Run Ljung-Box on rolling IC series
5. Classify tiers using `classify_feature_tier()` with `ic_ir_cutoff=0.5`
6. Build comparison: load AMA IC results, compute IC-IR correlation by feature
7. Write `dim_ctf_feature_selection` via new `save_ctf_to_db()`
8. Write `ctf_config_pruned.yaml` — copy original `ctf_config.yaml`, remove indicators that are all-archive
9. Write `reports/ctf/ctf_ic_comparison_report.md`

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Spearman IC computation | Custom rank correlation | `batch_compute_ic()` | Handles boundary masking, rolling IC-IR, turnover, pre-computed fwd returns cache |
| Feature tier classification | Custom tier rules | `classify_feature_tier()` | Exact same tier semantics as Phase 80 |
| IC persistence | Custom upsert | `save_ic_results(conn, rows, overwrite=True)` | Handles numpy scalar normalization, correct conflict key |
| IC ranking query | Custom SQL | `load_ic_ranking(engine, horizon, return_type)` | Returns correct column format for `build_feature_selection_config()` |
| Stationarity testing | ADF from scratch | `test_stationarity()` from `feature_selection.py` | Handles both ADF and KPSS with opposing null hypotheses |
| Ljung-Box test | Custom autocorrelation | `test_ljungbox_on_ic()` from `feature_selection.py` | Applied to IC series not raw values |
| Config building | Custom tier YAML | `build_feature_selection_config()` | Handles all tier metadata and rationale strings |
| YAML output | Custom dump | `save_to_yaml()` from `feature_selection.py` | Handles Windows UTF-8 encoding |
| TF days resolution | Hardcoded dict | `DimTimeframe.from_db(db_url).tf_days(tf)` | Reads from DB, handles all 109 TFs |

---

## Common Pitfalls

### Pitfall 1: close column in features_df
**What goes wrong:** If `load_ctf_features()` accidentally includes a `close` column, `batch_compute_ic()` will exclude it by name — but the caller should still not pass it to avoid confusion.
**How to avoid:** Pivot only the composite columns (ref_value, base_value, slope, divergence, agreement, crossover). Never include close in the pivot output.

### Pitfall 2: Mixing base_tf rows in a single batch_compute_ic() call
**What goes wrong:** CTF rows are stored per (base_tf, ref_tf). If you pivot across base_tfs, you get NULL-heavy columns that inflate NaN counts and reduce IC reliability.
**How to avoid:** Always pass a single `base_tf` to `load_ctf_features()`. One IC sweep call per (asset_id, base_tf) combination.

### Pitfall 3: tf_days_nominal mismatch
**What goes wrong:** Using `tf_days_nominal=1` for all base_tfs causes incorrect boundary masking. A 7D base_tf with `tf_days_nominal=1` at `horizon=1` only masks the last 1 day instead of the last 7 days.
**How to avoid:** Always derive `tf_days_nominal` from `DimTimeframe.tf_days(base_tf)`.

### Pitfall 4: save_to_db() truncates dim_feature_selection
**What goes wrong:** Calling the existing `save_to_db()` for CTF results truncates Phase 80 entries.
**How to avoid:** Write a dedicated `save_ctf_to_db()` that targets `dim_ctf_feature_selection`. Never call `save_to_db()` from `feature_selection.py` in the CTF scripts.

### Pitfall 5: Non-directional composites (agreement/crossover for non-directional indicators)
**What goes wrong:** For the 15 non-directional indicators, `crossover` is all NaN (the engine returns `pd.Series(np.nan, ...)`). If the pivot includes these all-NaN columns, `batch_compute_ic()` silently skips them (`notna().any()` check in `_ic_worker`). This is fine but creates many zero-row IC results.
**How to avoid:** After pivoting, pre-filter with `df = df[[c for c in df.columns if df[c].notna().any()]]` before calling `batch_compute_ic()`. The CONTEXT.md decision to "include NULL composites" means include them in the pivot, not that they must produce IC results.

### Pitfall 6: ctf_config_pruned.yaml indicator pruning scope
**What goes wrong:** Pruning at the indicator level (removing entire indicator entries) when only some ref_tf pairs are dead.
**How to avoid:** Per context decisions, prune at the ref_tf level within each indicator's entry. Only remove an entire indicator from the config if ALL its composites at ALL base_tf × ref_tf combinations are archive.

### Pitfall 7: Windows pd.read_sql tz gotcha
**What goes wrong:** `pd.read_sql()` returns timestamps as tz-naive on Windows for some TIMESTAMPTZ columns.
**How to avoid:** Always apply `pd.to_datetime(df["ts"], utc=True)` after loading from CTF table — exactly as done in `cross_timeframe.py` line 453 and `run_ic_sweep.py` line 250.

---

## Code Examples

### load_ctf_features() pivot implementation

```python
# Source: cross_timeframe.py pattern + ic.py batch_compute_ic() requirements
def load_ctf_features(
    conn,
    asset_id: int,
    base_tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    *,
    ref_tfs: Optional[list[str]] = None,
    indicator_names: Optional[list[str]] = None,
    alignment_source: str = "multi_tf",
    venue_id: int = 1,
) -> pd.DataFrame:
    sql = text("""
        SELECT
            c.ts,
            d.indicator_name,
            c.ref_tf,
            c.ref_value,
            c.base_value,
            c.slope,
            c.divergence,
            c.agreement,
            c.crossover
        FROM public.ctf c
        JOIN public.dim_ctf_indicators d ON d.indicator_id = c.indicator_id
        WHERE c.id = :asset_id
          AND c.base_tf = :base_tf
          AND c.ts >= :train_start
          AND c.ts <= :train_end
          AND c.alignment_source = :alignment_source
          AND c.venue_id = :venue_id
        ORDER BY c.ts
    """)
    df = pd.read_sql(sql, conn, params={...})
    if df.empty:
        return pd.DataFrame()

    # CRITICAL: fix Windows tz-naive bug
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # Build pivot column names
    composites = ["ref_value", "base_value", "slope", "divergence", "agreement", "crossover"]
    rows = []
    for _, row in df.iterrows():
        ref_tf_lower = row["ref_tf"].lower()  # "7D" -> "7d"
        for comp in composites:
            col_name = f"{row['indicator_name']}_{ref_tf_lower}_{comp}"
            rows.append({"ts": row["ts"], "col": col_name, "val": row[comp]})

    long = pd.DataFrame(rows)
    wide = long.pivot_table(index="ts", columns="col", values="val", aggfunc="first")
    wide.columns.name = None
    wide.index.name = "ts"

    # Drop all-null columns
    wide = wide.dropna(axis=1, how="all")
    return wide
```

Note: The above uses a row-by-row approach for clarity. In production, use vectorized
pandas operations (`assign` + `pivot_table`) for speed. See architecture note below.

### Vectorized pivot (faster for production)

```python
# Vectorized approach for load_ctf_features()
df["ref_tf_lower"] = df["ref_tf"].str.lower()
df["col_base"] = df["indicator_name"] + "_" + df["ref_tf_lower"]

# Melt composites into long format
composite_cols = ["ref_value", "base_value", "slope", "divergence", "agreement", "crossover"]
melted = df.melt(
    id_vars=["ts", "col_base"],
    value_vars=composite_cols,
    var_name="composite",
    value_name="val"
)
melted["feature_col"] = melted["col_base"] + "_" + melted["composite"]

wide = melted.pivot_table(index="ts", columns="feature_col", values="val", aggfunc="first")
wide.columns.name = None
wide = wide.dropna(axis=1, how="all")
```

### IC sweep discovery for CTF

```python
# Source: adapted from _discover_features_pairs() in run_ic_sweep.py
def _discover_ctf_pairs(engine, min_bars: int) -> list[tuple[int, str, int]]:
    sql = text("""
        SELECT id AS asset_id, base_tf, COUNT(DISTINCT ts) AS n_ts
        FROM public.ctf
        WHERE alignment_source = 'multi_tf'
          AND venue_id = 1
        GROUP BY id, base_tf
        HAVING COUNT(DISTINCT ts) >= :min_bars
        ORDER BY id, base_tf
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"min_bars": min_bars})
    return list(zip(df["asset_id"], df["base_tf"], df["n_ts"]))
```

### save_ctf_to_db() for dim_ctf_feature_selection

```python
# New function in a new ctf_feature_selection.py module or in cross_timeframe.py
def save_ctf_to_db(engine, config: dict, base_tf: str, yaml_version: str) -> int:
    rows = []
    for tier in ("active", "conditional", "watch", "archive"):
        for entry in config.get(tier, []):
            rows.append({
                "feature_name": entry["name"],
                "base_tf": base_tf,
                "tier": tier,
                "ic_ir_mean": entry.get("ic_ir_mean"),
                "pass_rate": entry.get("pass_rate"),
                "stationarity": entry.get("stationarity", "INSUFFICIENT_DATA"),
                "ljung_box_flag": bool(entry.get("ljung_box_flag", False)),
                "selected_at": datetime.utcnow(),
                "yaml_version": yaml_version,
                "rationale": entry.get("rationale", ""),
            })

    insert_sql = text("""
        INSERT INTO public.dim_ctf_feature_selection
            (feature_name, base_tf, tier, ic_ir_mean, pass_rate, stationarity,
             ljung_box_flag, selected_at, yaml_version, rationale)
        VALUES (:feature_name, :base_tf, :tier, :ic_ir_mean, :pass_rate, :stationarity,
                :ljung_box_flag, :selected_at, :yaml_version, :rationale)
        ON CONFLICT (feature_name, base_tf)
        DO UPDATE SET
            tier = EXCLUDED.tier,
            ic_ir_mean = EXCLUDED.ic_ir_mean,
            pass_rate = EXCLUDED.pass_rate,
            stationarity = EXCLUDED.stationarity,
            ljung_box_flag = EXCLUDED.ljung_box_flag,
            selected_at = EXCLUDED.selected_at,
            yaml_version = EXCLUDED.yaml_version,
            rationale = EXCLUDED.rationale
    """)
    with engine.begin() as conn:
        conn.execute(insert_sql, rows)
    return len(rows)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-feature `compute_ic()` call | `batch_compute_ic()` with pre-computed fwd-return cache | Phase 80 | ~112x speedup |
| Store IC in memory only | Persist to `ic_results` with ON CONFLICT DO NOTHING/UPDATE | Phase 80 | Enables `load_ic_ranking()` aggregation |
| Single `dim_feature_selection` table | Separate `dim_ctf_feature_selection` table | Phase 92 (new) | Avoids truncation of Phase 80 entries |

---

## Open Questions

1. **Stationarity test for CTF composites**
   - What we know: `test_stationarity()` expects a raw feature value Series; for CTF composites (slope, divergence), the data lives in `public.ctf` not `public.features`
   - What's unclear: whether `load_ctf_features()` + stationarity per composite column is worth the compute time for 792 potential columns
   - Recommendation: Run stationarity only on top-N CTF features by IC-IR (matching Phase 80's `--top-n` approach), not all 792. Filter to top-50 candidates before running stationarity.

2. **Quintile monotonicity for CTF features**
   - What we know: `compute_quintile_returns()` requires cross-sectional data (multiple assets at same timestamp), not per-asset time series
   - What's unclear: whether quintile analysis makes sense for CTF features (they are per-asset, not cross-sectional signals by nature)
   - Recommendation: Skip quintile monotonicity for CTF (pass empty dict to `build_feature_selection_config()`). Add a comment in the script explaining why.

3. **ctf_config_pruned.yaml indicator pruning scope**
   - What we know: context says "whether to prune indicators section or only ref_tf pairs is discretion"
   - Recommendation: Prune at indicator × ref_tf level within each base_tf entry. Do NOT remove indicators from the `indicators:` section — only remove ref_tf entries from `timeframe_pairs` that have zero active/conditional features for a given indicator. This preserves the indicator catalog for future re-analysis.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/analysis/ic.py` — full read, `batch_compute_ic()` at lines 623-801
- `src/ta_lab2/analysis/feature_selection.py` — full read, tier classification at lines 408-491
- `src/ta_lab2/features/cross_timeframe.py` — full read, CTF engine at lines 1-862
- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` — full read, sweep pattern at lines 1-1422
- `src/ta_lab2/scripts/analysis/run_feature_selection.py` — full read, pipeline at lines 1-926
- `alembic/versions/j4k5l6m7n8o9_ctf_schema.py` — CTF table schema
- `alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py` — dim_feature_selection schema
- `configs/ctf_config.yaml` — 22 indicators, 6 base TFs, ref_tf counts per pair
- `configs/feature_selection.yaml` — Phase 80 active features confirmed (AMA dominance)
- `reports/bakeoff/feature_ic_ranking.csv` — Phase 80 IC-IR rankings (AMA top-18)

### Secondary (MEDIUM confidence)
- `.planning/phases/92-ctf-ic-analysis-feature-selection/92-CONTEXT.md` — phase decisions
- `.planning/phases/91-ctf-cli-pipeline-integration/91-VERIFICATION.md` — Phase 91 completion confirmed

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all IC pipeline code directly read, no inference
- Architecture: HIGH — pivot pattern matches existing CTF read patterns
- Pitfalls: HIGH — derived from direct code inspection of `batch_compute_ic()` and existing sweep scripts
- Separate table migration: HIGH — Alembic chain confirmed, schema design follows established pattern

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable domain, no external dependencies)
