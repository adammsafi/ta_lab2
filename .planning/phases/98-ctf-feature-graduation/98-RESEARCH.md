# Phase 98: CTF Feature Graduation - Research

**Researched:** 2026-03-31
**Domain:** CTF feature promotion to features table, asset-specific dim_feature_selection,
cross-asset composites, lead-lag IC matrix
**Confidence:** HIGH

---

## Summary

Phase 92 (complete) built CTF IC infrastructure: `run_ctf_ic_sweep.py` sweeps all
(asset_id, base_tf) pairs and persists to `ic_results`; `run_ctf_feature_selection.py`
reads those rows and persists tier assignments to `dim_ctf_feature_selection`.

Phase 98 takes the *output* of Phase 92 and graduates passing CTF features into the
main production pipeline. The four plans build on proven infrastructure: the existing
`save_ic_results` / `classify_feature_tier` / `load_ctf_features` stack handles
everything through the IC layer. New work is: (1) an ETL bridge that pivots CTF data
into `features` table columns plus a YAML registration step, (2) an asset-specific
selection tier in `dim_feature_selection` via a new Alembic migration, (3) a
cross-asset composite script with a new `ctf_composites` table and a `features` write
pass, and (4) a lead-lag IC matrix script with its own `lead_lag_ic` table.

**Primary recommendation:** Treat Phase 98 as four independent ETL/analysis scripts,
all reading from the already-computed `ctf`, `ic_results`, and
`dim_ctf_feature_selection` tables. No new heavy computation — the expensive IC sweep
was done in Phase 92.

---

## 1. Existing CTF Infrastructure (Phase 89-92)

**Source:** Direct code read of all Phase 89-92 scripts. Confidence: HIGH.

### Tables deployed

| Table | PK | Purpose |
|-------|-----|---------|
| `public.ctf` | `(id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)` | CTF fact rows: 6 composite columns per (asset, ts, base_tf, ref_tf, indicator) |
| `public.ctf_state` | `(id, venue_id, base_tf, ref_tf, indicator_id, alignment_source)` | Watermark per CTF computation scope |
| `public.dim_ctf_indicators` | `indicator_id` | 22 seeded indicator definitions |
| `public.dim_ctf_feature_selection` | `(feature_name, base_tf)` | CTF tier assignments from Phase 92 |
| `public.ic_results` | (UUID, unique on 10-col natural key) | Shared IC results table — CTF and AMA features both live here |

### CTF table schema

```sql
CREATE TABLE public.ctf (
    id               INTEGER NOT NULL,
    venue_id         SMALLINT NOT NULL,
    ts               TIMESTAMPTZ NOT NULL,
    base_tf          TEXT NOT NULL,
    ref_tf           TEXT NOT NULL,
    indicator_id     SMALLINT NOT NULL,
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

### dim_ctf_feature_selection schema

```sql
CREATE TABLE public.dim_ctf_feature_selection (
    feature_name   TEXT NOT NULL,
    base_tf        TEXT NOT NULL,
    tier           TEXT NOT NULL CHECK (tier IN ('active','conditional','watch','archive')),
    ic_ir_mean     NUMERIC,
    pass_rate      NUMERIC,
    stationarity   TEXT,
    ljung_box_flag BOOLEAN DEFAULT FALSE,
    selected_at    TIMESTAMPTZ DEFAULT now(),
    yaml_version   TEXT,
    rationale      TEXT,
    PRIMARY KEY (feature_name, base_tf)
)
```

### 22 CTF indicators and timeframe pairs

Indicators: `rsi_14`, `rsi_7`, `rsi_21`, `macd_12_26`, `macd_hist_12_26_9`,
`macd_8_17`, `macd_hist_8_17_9`, `adx_14`, `bb_width_20`, `stoch_k_14`, `atr_14`,
`vol_parkinson_20`, `vol_gk_20`, `vol_rs_20`, `vol_log_roll_20`, `vol_parkinson_63`,
`vol_gk_63`, `vol_log_roll_63`, `ret_arith`, `ret_log`, `close_fracdiff`, `sadf_stat`

6 composites: `ref_value`, `base_value`, `slope`, `divergence`, `agreement`, `crossover`

Base TFs: `1D` (6 ref TFs), `2D` (6), `3D` (6), `7D` (4), `14D` (3), `30D` (2)

Theoretical max CTF feature names: 22 × 27 pairs × 6 composites = 3,564

### Existing CLI scripts

```bash
python -m ta_lab2.scripts.features.refresh_ctf --all --workers 6
python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --all
python -m ta_lab2.scripts.analysis.run_ctf_feature_selection --all
```

### `load_ctf_features()` — already exists

Located at `src/ta_lab2/features/cross_timeframe.py` line 221. Signature:

```python
def load_ctf_features(
    conn,
    asset_id: int,
    base_tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    *,
    alignment_source: str = "multi_tf",
    venue_id: int = 1,
) -> pd.DataFrame  # UTC-indexed, columns = {indicator}_{ref_tf_lower}_{composite}
```

Column naming convention: `rsi_14_7d_slope`, `macd_12_26_30d_crossover`, etc.

---

## 2. Features Table Schema and Write Pattern

**Source:** Code reads of `daily_features_view.py`, `microstructure_feature.py`,
`base_feature.py`, and `refresh_cs_norms.py`. Confidence: HIGH.

### Key facts about `public.features`

- PK: `(id, venue_id, ts, tf, alignment_source)` — five-column composite
- No `asset_id` column — uses `id` (same as all other analytics tables)
- Columns are dynamic: new feature columns are added via `op.add_column` in Alembic migrations
- `_get_table_columns()` queries `information_schema.columns` at runtime to determine which columns exist — this silently drops any DataFrame columns not in the actual DB table
- Table was renamed from `cmc_features` to `features` in migration `a0b1c2d3e4f5`

### Feature column write pattern

There are two write patterns for `features`:

**Pattern A: scoped DELETE + INSERT** (base_feature.py, the standard pattern)

```python
# 1. Introspect actual table columns
table_cols = self._get_table_columns()  # queries information_schema
# 2. Filter DataFrame to only existing columns (CRITICAL: prevents silent data loss)
df = df[[c for c in df.columns if c in table_cols]]
# 3. Scoped delete by (ids, tf, alignment_source, venue_id)
DELETE FROM public.features WHERE id = ANY(:ids) AND tf = :tf
  AND alignment_source = :as_ AND venue_id = ANY(:venue_ids)
# 4. Insert via df.to_sql(..., if_exists='append', method='multi', chunksize=10000)
```

**Pattern B: UPDATE existing rows** (microstructure_feature.py, for supplemental columns)

```python
UPDATE public.features SET col1 = :col1, col2 = :col2, ... WHERE id=:id AND ts=:ts ...
```

**For 98-01 (refresh_ctf_promoted.py):** Use Pattern B (UPDATE existing rows).
Promoted CTF columns are supplemental — the base row from `daily_features_view.py`
already exists. Doing DELETE + INSERT would break other feature columns. UPDATE by
`(id, ts, tf, venue_id, alignment_source)`.

### Alembic migration is REQUIRED before writing CTF columns

Before `refresh_ctf_promoted.py` can write CTF feature columns into `features`, each
new column must be added via `op.add_column()` in an Alembic migration. The migration
runs first; then the script writes values. Example from `d4e5f6a1b2c3`:

```python
op.add_column(
    "features",
    sa.Column("rsi_14_7d_slope", sa.Float(), nullable=True),
    schema="public",
)
```

**CRITICAL WARNING:** `_get_table_columns()` queries `information_schema` at runtime.
Any CTF column in the DataFrame that is NOT in the DB table will be silently dropped
before the INSERT/UPDATE. Always migrate first, write second.

---

## 3. dim_feature_selection Schema and Asset-Specific Tier

**Source:** Alembic migration `h2i3j4k5l6m7` + code read. Confidence: HIGH.

### Current dim_feature_selection schema (no asset_id)

```sql
CREATE TABLE public.dim_feature_selection (
    feature_name          TEXT NOT NULL PRIMARY KEY,
    tier                  TEXT NOT NULL CHECK (tier IN ('active','conditional','watch','archive')),
    ic_ir_mean            NUMERIC,
    pass_rate             NUMERIC,
    quintile_monotonicity NUMERIC,
    stationarity          TEXT,
    ljung_box_flag        BOOLEAN DEFAULT FALSE,
    regime_specialist     BOOLEAN DEFAULT FALSE,
    specialist_regimes    TEXT[],
    selected_at           TIMESTAMPTZ DEFAULT now(),
    yaml_version          TEXT,
    rationale             TEXT
)
```

### CRITICAL: save_to_db() truncates the table

In `analysis/feature_selection.py`, `save_to_db()` does:
```python
conn.execute(text("TRUNCATE TABLE public.dim_feature_selection"))
conn.execute(insert_sql, rows_to_insert)
```
This wipes ALL rows on every run. The Phase 98 asset-specific tier rows must NOT be
written to `dim_feature_selection` using `save_to_db()`. Use a separate upsert function
targeting only `tier = 'asset_specific'` rows.

### Required Alembic migration for asset-specific tier

`dim_feature_selection` currently has `feature_name` as its sole PK (TEXT). To support
per-asset rows with `tier = 'asset_specific'`, an Alembic migration must:

1. Add `asset_id INTEGER NULL` column (nullable — global rows have NULL asset_id)
2. Add `'asset_specific'` to the tier CHECK constraint
3. Rebuild PK as `(feature_name, asset_id)` with `COALESCE(asset_id, 0)` or use a
   partial unique index approach

**Recommended schema change:**

```sql
-- Add asset_id column (nullable for global rows)
ALTER TABLE public.dim_feature_selection
    ADD COLUMN asset_id INTEGER NULL REFERENCES cmc_da_ids(id);

-- Drop old PK
ALTER TABLE public.dim_feature_selection DROP CONSTRAINT dim_feature_selection_pkey;

-- New PK (NULL coalesce trick for composite PK with nullable column):
-- Use a unique index with COALESCE(asset_id, 0) instead of true PK
CREATE UNIQUE INDEX dim_feature_selection_uq
    ON public.dim_feature_selection (feature_name, COALESCE(asset_id, 0));

-- Update tier check to include asset_specific
ALTER TABLE public.dim_feature_selection
    DROP CONSTRAINT chk_dim_feature_selection_tier;
ALTER TABLE public.dim_feature_selection
    ADD CONSTRAINT chk_dim_feature_selection_tier
    CHECK (tier IN ('active','conditional','watch','archive','asset_specific'));
```

**Alternative approach (simpler):** Add a `scope` column (`'global'` or `'asset_specific'`)
and keep `feature_name` as PK for global rows while using a separate table
`dim_feature_selection_asset` for asset-specific rows. Given the CONTEXT decision
("superset" relationship and one row per (feature, asset_id)), a separate table is
cleaner and avoids PK gymnastics.

**Recommended: Create a new `dim_feature_selection_asset` table** (parallel to
`dim_feature_selection`) rather than modifying the existing table PK. This avoids
disturbing the `TRUNCATE` pattern in `save_to_db()`.

```sql
CREATE TABLE public.dim_feature_selection_asset (
    feature_name  TEXT NOT NULL,
    asset_id      INTEGER NOT NULL,
    tier          TEXT NOT NULL DEFAULT 'asset_specific',
    ic_ir_mean    NUMERIC,
    pass_rate     NUMERIC,
    stationarity  TEXT,
    selected_at   TIMESTAMPTZ DEFAULT now(),
    yaml_version  TEXT,
    rationale     TEXT,
    PRIMARY KEY (feature_name, asset_id)
);
```

---

## 4. feature_selection.yaml Structure

**Source:** `configs/feature_selection.yaml` (first 100 lines). Confidence: HIGH.

### Current structure

```yaml
# Feature Selection Config -- generated by Phase 80
active:
- ic_ir_mean: 1.6512
  ljung_box_flag: true
  mean_abs_ic: 0.0439
  monotonicity: 0.5
  name: ret_is_outlier
  pass_rate: 0.4545
  rationale: '...'
  stationarity: AMBIGUOUS
- ...
conditional: [...]
watch: [...]
archive: [...]
```

### What Phase 98 adds

`refresh_ctf_promoted.py` should append promoted CTF features to the `active:` (or
appropriate tier) section. Rather than modifying existing YAML structure, add a new
top-level section:

```yaml
# Appended by Phase 98 refresh_ctf_promoted.py
ctf_promoted:
  generated_at: "2026-03-31T..."
  ic_threshold: 0.02
  source: dim_ctf_feature_selection
  features:
  - name: rsi_14_7d_slope
    ic_threshold: 0.02
    source_ctf_config: ctf_config.yaml
    base_tf: 1D
    tier: active
    ic_ir_mean: 0.xxxx
  - ...
```

**Note:** The CONTEXT.md specifies IC > 0.02 (mean IC, not IC-IR) as the graduation
threshold. This differs from Phase 92's IC-IR 0.5 threshold used for tier
classification. Phase 98 uses a direct `mean_abs_ic` query against `ic_results`
for promotion decisions.

---

## 5. IC Analysis Infrastructure

**Source:** `src/ta_lab2/analysis/ic.py` + `feature_selection.py`. Confidence: HIGH.

### batch_compute_ic() contract (already used by Phase 92)

```python
batch_compute_ic(
    features_df: pd.DataFrame,   # UTC-indexed, numeric columns only
    close: pd.Series,            # UTC-indexed close prices
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    feature_cols: list[str],
    horizons: list[int],         # default [1,2,3,5,10,20,60]
    return_types: list[str],     # default ['arith','log']
    rolling_window: int,         # default 63
    tf_days_nominal: int,        # CRITICAL: use DimTimeframe.tf_days(base_tf)
) -> pd.DataFrame  # columns: feature, horizon, return_type, ic, ic_ir, ...
```

### save_ic_results() upsert signature

```python
save_ic_results(
    conn,               # active SQLAlchemy connection (within transaction)
    rows: list[dict],   # dicts with asset_id, tf, feature, horizon, return_type, ...
    *,
    overwrite: bool,    # True = ON CONFLICT DO UPDATE, False = DO NOTHING
) -> int  # rows written
```

Unique constraint: `(asset_id, tf, feature, horizon, return_type, regime_col, regime_label, train_start, train_end, alignment_source)`

### IC query for promotion (Plan 98-01)

To find CTF features passing IC > 0.02 threshold across tier-1 assets:

```sql
SELECT feature,
       AVG(ABS(ic)) AS median_abs_ic,   -- use PERCENTILE_CONT for true median
       COUNT(DISTINCT asset_id) AS n_assets,
       COUNT(*) AS n_obs
FROM public.ic_results
WHERE horizon = 1
  AND return_type = 'arith'
  AND regime_col = 'all'
  AND regime_label = 'all'
  AND ic IS NOT NULL
  AND feature LIKE '%_slope'       -- CTF feature pattern
     OR feature LIKE '%_divergence'
     OR feature LIKE '%_agreement'
     OR feature LIKE '%_crossover'
     OR feature LIKE '%_ref_value'
     OR feature LIKE '%_base_value'
GROUP BY feature
HAVING PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > 0.02
ORDER BY median_abs_ic DESC;
```

**CRITICAL:** The CONTEXT specifies "cross-asset median IC" as the aggregation method.
Use `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic))` not AVG, for the cross-asset
aggregation.

### classify_feature_tier() signature (for per-asset evaluation)

```python
classify_feature_tier(
    ic_ir_mean: float,
    pass_rate: float,
    stationarity: str,
    regime_ic: Optional[pd.DataFrame],
    ic_ir_cutoff: float = 0.3,  # Phase 98 uses 0.02 IC (not IC-IR)
) -> str  # 'active'|'conditional'|'watch'|'archive'
```

Note: `classify_feature_tier` uses IC-IR as its primary metric. For Phase 98's
per-asset tier at IC > 0.02 threshold, evaluate `mean_abs_ic >= 0.02` directly
rather than routing through `classify_feature_tier`.

---

## 6. Cross-Asset Patterns (Plan 98-03)

**Source:** `src/ta_lab2/macro/cross_asset.py` + `cross_asset_config.yaml` patterns.
Confidence: HIGH.

### Established cross-asset write pattern

`cross_asset.py` uses **temp table + INSERT...ON CONFLICT upsert**:

```python
# 1. Load data into pandas DataFrame
# 2. Write to temp table
df.to_sql("_tmp_xagg", engine, schema="public", if_exists="replace", index=False)
# 3. Upsert from temp to target
conn.execute(text("""
    INSERT INTO public.cross_asset_agg (...)
    SELECT ... FROM public._tmp_xagg
    ON CONFLICT (date, ...) DO UPDATE SET ...
"""))
# 4. Drop temp table
conn.execute(text("DROP TABLE IF EXISTS public._tmp_xagg"))
```

### Config-driven design pattern

`cross_asset.py` reads thresholds from `configs/cross_asset_config.yaml`. Phase 98
composites should follow this pattern — put PCA variance threshold, z-score window,
and min-assets-for-composite in `configs/ctf_composites_config.yaml`.

### Required new table: ctf_composites

**Suggested schema:**

```sql
CREATE TABLE public.ctf_composites (
    ts            TIMESTAMPTZ NOT NULL,
    tf            TEXT NOT NULL,           -- base_tf of source CTF features
    venue_id      SMALLINT NOT NULL DEFAULT 1,
    composite_name TEXT NOT NULL,          -- e.g. 'sentiment_mean', 'relative_value_z'
    method        TEXT NOT NULL,           -- 'cross_asset_mean', 'pca_1', 'cs_zscore', 'lagged_corr'
    value         DOUBLE PRECISION,
    n_assets      INTEGER,                 -- how many assets contributed
    computed_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ts, tf, venue_id, composite_name, method)
);
```

### Three composite types

**Sentiment (cross-asset mean of CTF feature):**
```python
# For each (ts, tf): pivot CTF feature across all tier-1 assets, compute mean
sentiment = ctf_pivot.groupby(level='ts').mean()
```

**Sentiment (PCA first component):**
```python
from sklearn.decomposition import PCA
scaler = StandardScaler()
X = scaler.fit_transform(ctf_pivot.dropna(axis=0))
pca = PCA(n_components=1)
pca_score = pca.fit_transform(X)[:, 0]
# Sign-correct: align with majority-sign of loadings (Claude's discretion)
```

**Relative-value (cross-sectional z-score):**
```python
# For each ts: compute z-score of asset's CTF feature relative to cross-section
rv = ctf_pivot.subtract(ctf_pivot.mean(axis=1), axis=0).divide(ctf_pivot.std(axis=1), axis=0)
```

**Leader-follower (lagged correlation):**
```python
# For each asset pair (A, B): Pearson corr at lags [1, 3, 5]
# Uses lead_lag_max_corr() from regimes.comovement
from ta_lab2.regimes.comovement import lead_lag_max_corr
result = lead_lag_max_corr(df, col_a=asset_a_ctf, col_b=asset_b_ctf, lags=range(-5, 6))
```

### sklearn.decomposition.PCA availability

PCA is available: `from sklearn.decomposition import PCA` — sklearn is installed in the
project environment (confirmed: sklearn OK, version available). It is NOT in
`pyproject.toml` as an explicit dependency (it is a transitive dep via other packages).
Consider adding `scikit-learn` to `pyproject.toml` optional extras to make it explicit.

---

## 7. Lead-Lag IC Matrix (Plan 98-04)

**Source:** `src/ta_lab2/macro/lead_lag_analyzer.py` + `regimes/comovement.py`.
Confidence: HIGH.

### Existing `lead_lag_max_corr()` function

```python
# src/ta_lab2/regimes/comovement.py:109
def lead_lag_max_corr(
    df: pd.DataFrame,
    col_a: str,         # reference series (potential leader)
    col_b: str,         # target series
    lags: range = range(-10, 11),
) -> Dict[str, object]:
    """Returns {best_lag, best_corr, corr_by_lag: pd.Series}"""
```

**Convention:** `best_lag < 0` means col_a *leads* col_b (col_a is ahead in time).

### Phase 98 lead-lag IC scope

- Asset pairs: all-vs-all tier-1 (~109 assets → 109×108/2 = 5,886 pairs)
- Horizons: [1, 3, 5] bars
- Metric: Spearman IC between Asset A's CTF feature at t and Asset B's forward returns
  at t+horizon (not Pearson pairwise correlation)
- BH FDR correction: `statsmodels.stats.multitest.multipletests(pvals, method='fdr_bh')`

### BH FDR correction — NEW, not yet used in codebase

`multipletests` is not currently used in the codebase. Import from statsmodels:

```python
from statsmodels.stats.multitest import multipletests

# After computing IC p-values for all (asset_a, asset_b, feature, horizon) combos:
pvals = [row['ic_p_value'] for row in all_ic_rows]
reject, p_corrected, _, _ = multipletests(pvals, alpha=0.05, method='fdr_bh')
```

statsmodels is already in `pyproject.toml` (`>=0.14.0`), so this import works.

### Required new table: lead_lag_ic

**Suggested schema (following macro_lead_lag_results pattern):**

```sql
CREATE TABLE public.lead_lag_ic (
    asset_a_id     INTEGER NOT NULL,       -- "leader" asset
    asset_b_id     INTEGER NOT NULL,       -- "follower" asset (whose return we predict)
    feature        TEXT NOT NULL,          -- CTF feature name used as predictor
    horizon        INTEGER NOT NULL,       -- forward return horizon in bars
    tf             TEXT NOT NULL,          -- base_tf of feature
    venue_id       SMALLINT NOT NULL DEFAULT 1,
    ic             NUMERIC,               -- Spearman IC
    ic_p_value     NUMERIC,               -- p-value before FDR
    ic_p_bh        NUMERIC,               -- p-value after BH correction
    is_significant BOOLEAN,               -- True if ic_p_bh < 0.05
    n_obs          INTEGER,
    computed_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (asset_a_id, asset_b_id, feature, horizon, tf, venue_id)
);
```

### Scale concern: 5,886 pairs × N features × 3 horizons

At 109 tier-1 assets × 108 = 5,886 pairs. If we restrict to top-N CTF features (e.g.,
20 promoted features) × 3 horizons = 353,160 IC computations. This is tractable in
parallel. Use the existing `Pool + maxtasksperchild=1` pattern.

---

## 8. Alembic Migration Chain

**Source:** `alembic/versions/` directory listing. Confidence: HIGH.

### Latest revision

The latest migration file is `q1r2s3t4u5v6_phase97_crypto_macro_corr_schema.py`
with:
- `revision = "q1r2s3t4u5v6"`
- `down_revision = "p0q1r2s3t4u5"`

Phase 98 migrations must chain from `q1r2s3t4u5v6`.

### Required Phase 98 migrations

Phase 98 requires 3 migrations:

**Migration 1 (Plan 98-01): Add CTF promoted columns to features table**
```python
revision = "r2s3t4u5v6w7"  # example ID
down_revision = "q1r2s3t4u5v6"
# op.add_column("features", sa.Column("rsi_14_7d_slope", sa.Float(), nullable=True), schema="public")
# ... repeat for all promoted columns (15-20 columns)
```

**Migration 2 (Plan 98-02): New dim_feature_selection_asset table**
```python
revision = "s3t4u5v6w7x8"
down_revision = "r2s3t4u5v6w7"
# CREATE TABLE public.dim_feature_selection_asset (feature_name, asset_id, tier, ...)
```

**Migration 3 (Plans 98-03 + 98-04): ctf_composites and lead_lag_ic tables**
```python
revision = "t4u5v6w7x8y9"
down_revision = "s3t4u5v6w7x8"
# CREATE TABLE public.ctf_composites (...)
# CREATE TABLE public.lead_lag_ic (...)
```

### Migration naming convention

Existing pattern: `{random_hex_id}_{description}.py`. Use sequential IDs like
`r2s3t4u5v6w7` continuing the alphabetical pattern.

---

## 9. Common Pitfalls

**Source:** MEMORY.md, Phase 92 research, code reads. Confidence: HIGH.

### Pitfall 1: Silent column drop in features write

**What goes wrong:** `_get_table_columns()` silently discards any DataFrame column not
in the DB table. If you write CTF columns before running the Alembic migration, the
entire column is silently dropped — no error, just missing data.

**Prevention:** Always run the Alembic migration before running `refresh_ctf_promoted.py`.
Add an explicit check at script start:

```python
missing_cols = set(ctf_col_names) - get_columns(engine, "public.features")
if missing_cols:
    raise RuntimeError(f"Run Alembic migration first. Missing: {missing_cols}")
```

### Pitfall 2: save_to_db() truncates dim_feature_selection

**What goes wrong:** If you accidentally call `save_to_db()` (from `feature_selection.py`)
during the asset-specific tier write, it will `TRUNCATE TABLE dim_feature_selection`,
wiping all Phase 80 entries.

**Prevention:** Plan 98-02 writes to `dim_feature_selection_asset` (separate table),
never touches `dim_feature_selection`. Do NOT reuse `save_to_db()`.

### Pitfall 3: dim_ctf_feature_selection IC-IR threshold vs IC threshold

**What goes wrong:** `dim_ctf_feature_selection` uses IC-IR >= 0.5 for tier
classification (Phase 92 convention). Phase 98 CONTEXT specifies IC > 0.02 (mean IC,
not IC-IR) for graduation to `features` table.

**Prevention:** Query `ic_results` directly with `AVG(ABS(ic)) > 0.02` (or
`PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > 0.02`) for promotion
decisions. Do NOT rely on `dim_ctf_feature_selection.tier = 'active'` as a proxy
for IC > 0.02 — the thresholds are different.

### Pitfall 4: Windows tz-aware timestamp issue

**What goes wrong:** `pd.read_sql()` on Windows with psycopg2 returns mixed tz-offset
object dtype for TIMESTAMPTZ columns.

**Prevention:** Always use `pd.to_datetime(df['ts'], utc=True)` after loading from DB.
This is established practice throughout the codebase.

### Pitfall 5: NullPool required in multiprocessing workers

**What goes wrong:** SQLAlchemy default connection pool causes "can't use connection
in child process" errors when `Pool` creates worker subprocesses.

**Prevention:** All worker functions create their own engine:
```python
engine = create_engine(task.db_url, poolclass=NullPool)
```
Follow the exact pattern from `_ctf_worker()` in `refresh_ctf.py`.

### Pitfall 6: maxtasksperchild=1 on Windows is MANDATORY

**What goes wrong:** Without `maxtasksperchild=1`, Windows processes accumulate memory
and eventually crash or hang.

**Prevention:**
```python
with Pool(processes=n_workers, maxtasksperchild=1) as pool:
    for result in pool.imap_unordered(worker_fn, tasks): ...
```

### Pitfall 7: Frozen dataclass required for multiprocessing pickling

**What goes wrong:** Regular dataclasses or classes with unhashable attributes fail
to pickle on Windows `spawn` start method.

**Prevention:** All task objects must be `@dataclass(frozen=True)` with only
primitive/tuple/string attributes — no engine objects, no DataFrames.

### Pitfall 8: PCA sign ambiguity

**What goes wrong:** PCA first component sign is arbitrary — it can flip between runs,
making the sentiment score meaningless or inverted.

**Prevention:** After PCA, align sign to majority vote of loadings:
```python
loadings = pca.components_[0]
dominant_sign = np.sign(loadings[np.abs(loadings).argmax()])
pca_scores = pca_scores * dominant_sign
```
This is identified as a Claude's Discretion item in CONTEXT.md.

---

## 10. Plan Dependencies

**Source:** Phase description and CONTEXT.md. Confidence: HIGH.

```
98-01 (refresh_ctf_promoted.py + feature_selection.yaml)
    |
    +-- Requires: Migration 1 (CTF columns in features)
    +-- Reads from: dim_ctf_feature_selection, ic_results, ctf

98-02 (dim_feature_selection asset_specific tier)
    |
    +-- Requires: Migration 2 (dim_feature_selection_asset table)
    +-- Reads from: ic_results (per-asset IC for CTF features)
    +-- Independent of 98-01

98-03 (cross-asset CTF composites)
    |
    +-- Requires: Migration 3a (ctf_composites table)
    +-- Reads from: ctf, dim_ctf_feature_selection
    +-- Writes to: ctf_composites + features (UPDATE pattern)
    +-- Requires: features columns from Migration 1 (for the features.UPDATE pass)
    +-- Depends on: 98-01 Alembic migration being applied first

98-04 (lead-lag IC matrix)
    |
    +-- Requires: Migration 3b (lead_lag_ic table)
    +-- Reads from: ic_results, ctf (via load_ctf_features), ic_results
    +-- Independent of 98-01/02/03
    +-- BUT: naturally runs after 98-01 since it needs promoted feature list
```

**Execution order:** Migration 1 → 98-01 → Migration 2 → 98-02 → Migration 3 → 98-03 → 98-04

---

## Code Examples

### Pattern: Query CTF features passing IC > 0.02 for promotion

```python
# Source: ic.py save_ic_results, ic analysis patterns
from sqlalchemy import text
import pandas as pd

def load_promoted_ctf_features(engine, ic_threshold: float = 0.02) -> list[str]:
    """
    Return CTF feature names where cross-asset median IC > ic_threshold.
    Uses horizon=1, return_type='arith', regime_col='all' (standard convention).
    """
    ctf_suffixes = ('_slope', '_divergence', '_agreement', '_crossover',
                    '_ref_value', '_base_value')
    conditions = " OR ".join(f"feature LIKE '%{s}'" for s in ctf_suffixes)

    sql = text(f"""
        SELECT feature,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) AS median_abs_ic,
               COUNT(DISTINCT asset_id) AS n_assets
        FROM public.ic_results
        WHERE horizon = 1
          AND return_type = 'arith'
          AND regime_col = 'all'
          AND regime_label = 'all'
          AND ic IS NOT NULL
          AND ({conditions})
        GROUP BY feature
        HAVING PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > :threshold
        ORDER BY median_abs_ic DESC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={'threshold': ic_threshold})
    return df['feature'].tolist()
```

### Pattern: Write CTF promoted values into features table (UPDATE pattern)

```python
# Source: microstructure_feature.py lines 416-445
from sqlalchemy import text

def write_ctf_to_features(engine, df: pd.DataFrame, ctf_cols: list[str]) -> int:
    """
    UPDATE existing features rows with promoted CTF column values.
    df must have: id, ts, tf, venue_id, alignment_source + ctf_cols
    """
    set_clauses = ", ".join(f"{col} = :{col}" for col in ctf_cols)
    sql = text(f"""
        UPDATE public.features
        SET {set_clauses}
        WHERE id = :id
          AND ts = :ts
          AND tf = :tf
          AND venue_id = :venue_id
          AND alignment_source = :alignment_source
    """)

    rows = df[['id', 'ts', 'tf', 'venue_id', 'alignment_source'] + ctf_cols].to_dict('records')
    total = 0
    with engine.begin() as conn:
        for i in range(0, len(rows), 5000):
            batch = rows[i:i+5000]
            result = conn.execute(sql, batch)
            total += result.rowcount
    return total
```

### Pattern: BH FDR correction on IC p-values

```python
# Source: statsmodels docs (confirmed available: statsmodels>=0.14.0)
from statsmodels.stats.multitest import multipletests

def apply_bh_correction(ic_rows: list[dict]) -> list[dict]:
    """Apply Benjamini-Hochberg FDR correction to IC p-values."""
    pvals = [row.get('ic_p_value') or 1.0 for row in ic_rows]
    reject, p_corrected, _, _ = multipletests(pvals, alpha=0.05, method='fdr_bh')
    for row, p_bh, sig in zip(ic_rows, p_corrected, reject):
        row['ic_p_bh'] = float(p_bh)
        row['is_significant'] = bool(sig)
    return ic_rows
```

### Pattern: Temp table + upsert (cross_asset.py pattern)

```python
# Source: cross_asset.py (cross-asset aggregation write pattern)
df.to_sql("_tmp_ctf_composites", engine, schema="public",
          if_exists="replace", index=False)
with engine.begin() as conn:
    conn.execute(text("""
        INSERT INTO public.ctf_composites
            (ts, tf, venue_id, composite_name, method, value, n_assets)
        SELECT ts, tf, venue_id, composite_name, method, value, n_assets
        FROM public._tmp_ctf_composites
        ON CONFLICT (ts, tf, venue_id, composite_name, method) DO UPDATE SET
            value      = EXCLUDED.value,
            n_assets   = EXCLUDED.n_assets,
            computed_at = now()
    """))
    conn.execute(text("DROP TABLE IF EXISTS public._tmp_ctf_composites"))
```

---

## State of the Art

| Old Approach | Current Approach | Phase Changed | Impact |
|--------------|-----------------|---------------|--------|
| CTF features only in `ctf` table | CTF features in `features` for downstream use | Phase 98 | BL optimizer, signals, ML can consume CTF directly |
| Global feature selection only | Per-asset selection tier | Phase 98 | Sparse assets return empty set (fine per CONTEXT) |
| No cross-asset CTF signals | CTF composites in `ctf_composites` + `features` | Phase 98 | Market sentiment + relative-value signals |
| No CTF lead-lag analysis | `lead_lag_ic` table with BH-corrected significance | Phase 98 | Identify CTF leader-follower pairs across asset universe |

---

## Open Questions

1. **How many CTF features actually pass IC > 0.02?**
   - What we know: Phase 92 computed IC-IR, but IC > 0.02 is a different threshold.
     CTF features are generally weaker than AMA features (Phase 92 report).
   - What's unclear: Could be 5 features or 50. Run
     `run_ctf_feature_selection.py --dry-run` to check.
   - Recommendation: Run a quick dry-run query before designing the migration. If
     fewer than 5 features pass, revisit whether features-table promotion is worthwhile.

2. **Does `features` table have all tier-1 assets for all 6 base TFs?**
   - What we know: `features` is populated by `daily_features_view.py` which uses
     `price_bars_multi_tf_u` as source. The CTF uses `alignment_source='multi_tf'`.
   - What's unclear: Whether all 6 base TFs (1D, 2D, 3D, 7D, 14D, 30D) have rows
     in `features`.
   - Recommendation: Check with
     `SELECT DISTINCT tf FROM public.features ORDER BY tf`.

3. **Granger causality lag order selection for leader-follower validation**
   - Identified as Claude's Discretion in CONTEXT.md
   - Recommendation: Use statsmodels `grangercausalitytests(data, maxlag=5)`
     with `addconst=True`. Select lag via minimum AIC across lags 1-5. This is
     standard practice and avoids overfitting.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/features/cross_timeframe.py` — CTFFeature, load_ctf_features, write pattern
- `src/ta_lab2/analysis/feature_selection.py` — save_to_db TRUNCATE pattern, classify_feature_tier
- `src/ta_lab2/analysis/ic.py` — save_ic_results signature, batch_compute_ic contract
- `src/ta_lab2/scripts/features/base_feature.py` — scoped DELETE + INSERT + _get_table_columns
- `src/ta_lab2/scripts/features/microstructure_feature.py` — UPDATE pattern for supplemental columns
- `alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py` — dim_feature_selection schema
- `alembic/versions/l6m7n8o9p0q1_dim_ctf_feature_selection.py` — dim_ctf_feature_selection schema
- `alembic/versions/q1r2s3t4u5v6_phase97_crypto_macro_corr_schema.py` — latest revision (chain head)
- `src/ta_lab2/macro/cross_asset.py` — temp table + upsert pattern
- `src/ta_lab2/regimes/comovement.py` — lead_lag_max_corr function
- `configs/feature_selection.yaml` — YAML structure (first 100 lines)
- `configs/ctf_config.yaml` — timeframe pairs and indicator structure
- `.planning/phases/92-ctf-ic-analysis-feature-selection/92-RESEARCH.md` — Phase 92 research

### Secondary (MEDIUM confidence)
- `src/ta_lab2/scripts/analysis/run_ctf_ic_sweep.py` — IC sweep worker pattern (active script)
- `src/ta_lab2/scripts/analysis/run_ctf_feature_selection.py` — feature selection pipeline
- `src/ta_lab2/macro/lead_lag_analyzer.py` — macro lead-lag implementation to replicate

---

## Metadata

**Confidence breakdown:**
- CTF infrastructure (tables, scripts, data): HIGH — code read directly
- features table write pattern: HIGH — multiple scripts confirmed
- dim_feature_selection TRUNCATE hazard: HIGH — code read line 754
- dim_feature_selection_asset design: MEDIUM — design recommendation not yet validated against DB constraints
- BH FDR correction: HIGH — statsmodels documented API, confirmed available
- PCA sign correction: MEDIUM — common practice, Claude's Discretion per CONTEXT
- ctf_composites / lead_lag_ic schema: MEDIUM — proposed based on existing patterns

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (stable codebase, no fast-moving external dependencies)
