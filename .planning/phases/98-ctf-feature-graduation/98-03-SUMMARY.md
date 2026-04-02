---
phase: 98-ctf-feature-graduation
plan: "03"
subsystem: features
tags: [ctf, cross-timeframe, composite, pca, sentiment, relative-value, leader-follower, ctf_composites, sklearn]

# Dependency graph
requires:
  - phase: 98-01-ctf-graduation-schema-etl
    provides: ctf_composites table (created in migration r2s3t4u5v6w7), ctf_promoted section in feature_selection.yaml with 401 features
  - phase: 89-ctf-infrastructure
    provides: public.ctf fact table, load_ctf_features() function
  - phase: 92-ctf-ic-analysis-feature-selection
    provides: ic_results table with CTF IC scores across tier-1 assets

provides:
  - refresh_ctf_composites.py CLI script computing 4 composite types
  - configs/ctf_composites_config.yaml with all composite thresholds
  - 8,074,644 rows in ctf_composites table (sentiment_mean + pca + relative_value + leader_follower)
  - Four methods: cross_asset_mean (1.43M rows), pca_1 (232K rows), cs_zscore (6.41M rows), lagged_corr (1.1K rows)

affects:
  - phase-98-04 (lead-lag IC matrix: share pivots/CTF data loading pattern)
  - phase-99-backtest-expansion (composites available for strategy signals)
  - phase-100-ml-expansion (sentiment/relative_value signals for ML features)

# Tech tracking
tech-stack:
  added:
    - sklearn.decomposition.PCA (PCA first component with sign correction)
    - sklearn.preprocessing.StandardScaler (standardize before PCA)
  patterns:
    - Vectorized pivot-based cross-asset computation (fast: no row iteration)
    - Chunked temp table + upsert persistence (50K rows per chunk, avoids large transactions)
    - PCA sign correction: dominant loading direction via argmax(|loadings|)
    - Config-driven composite selection via ctf_composites_config.yaml

key-files:
  created:
    - src/ta_lab2/scripts/features/refresh_ctf_composites.py
    - configs/ctf_composites_config.yaml
  modified: []

key-decisions:
  - "Vectorized pivot: build per-feature (ts x asset_id) DataFrames using pd.DataFrame(feat_series); avoid row iteration"
  - "Chunked persistence: 50K rows per temp table chunk; 1.43M sentiment_mean rows = 29 chunks @ ~20s each"
  - "Relative value uses per-asset composite_name suffix (relative_value_{feat}_{asset_id}) to preserve unique PK"
  - "Materialization to features skipped for cross-asset aggregates (no per-asset rows mapping); composites in ctf_composites only"
  - "numpy RuntimeWarning in leader_follower: divide-by-zero in np.corrcoef for constant series -- handled with isnan guard"
  - "Leader-follower uses last_ts of data window as snapshot timestamp (single row per asset per feature)"

patterns-established:
  - "Cross-asset pivot: dict[asset_id, pd.Series] -> pd.DataFrame for vectorized ts-level ops"
  - "Vectorized mean: pivot.mean(axis=1); vectorized std: pivot.std(axis=1, ddof=0) with notna mask"
  - "Chunked multi=True to_sql + ON CONFLICT upsert for large composite DataFrames"

# Metrics
duration: 177min
completed: 2026-03-31
---

# Phase 98 Plan 03: Cross-Asset CTF Composite Script Summary

**4-method cross-asset CTF composite pipeline: 8.07M rows spanning sentiment (mean + PCA), relative-value (cs_zscore), and leader-follower (lagged_corr) stored in ctf_composites table**

## Performance

- **Duration:** ~177 min (3h 0m — dominated by data loading and 6.4M row RV write)
- **Started:** 2026-03-31T14:16:52Z
- **Completed:** 2026-03-31T17:13:06Z
- **Tasks:** 2
- **Files modified:** 2 (1 created config + 1 created script)

## Accomplishments

- `ctf_composites_config.yaml` defines all 4 composite types with thresholds, min_assets, PCA variance, lag lists
- `refresh_ctf_composites.py` (1,215 lines) implements all composite computations via vectorized pandas operations
- 8,074,644 total rows in ctf_composites: 389 sentiment_mean composites (1.43M rows), 385 sentiment_pca composites (232K rows), 2,658 relative_value composites (6.41M rows per-asset z-scores), 1,129 leader_follower rows
- PCA sign correction applied: `dominant_sign = np.sign(loadings[abs(loadings).argmax()])`, ensures consistent direction across re-runs
- Chunked persistence (50K rows/chunk) prevents multi-hour single transactions; idempotent upsert (ON CONFLICT DO UPDATE) makes re-runs safe

## Task Commits

1. **Task 1: Create ctf_composites_config.yaml** - `83182220` (feat)
2. **Task 2: Build refresh_ctf_composites.py** - `73685686` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `configs/ctf_composites_config.yaml` - 4 composite definitions with min_assets, pca_variance_threshold, lags, top_n_leaders; materialize_to_features list
- `src/ta_lab2/scripts/features/refresh_ctf_composites.py` - Full composite pipeline: load promoted features from YAML, load 7 tier-1 assets CTF data, pivot per-feature, compute all 4 methods, chunk-persist to ctf_composites

## Decisions Made

- **Vectorized pivots over row iteration:** Initial implementation iterated rows (375K features × timestamps), causing unacceptably slow run time. Replaced with `pivot.mean(axis=1)`, `pivot.notna().sum(axis=1)`, `pivot.std(axis=1, ddof=0)` for vectorized cross-asset computations.

- **Relative value uses asset-specific composite_name:** `relative_value_{feat_name}_{asset_id}` ensures unique (ts, tf, venue_id, composite_name, method) PK per-asset per-timestamp. Alternative (single composite_name per feature) would violate the PK and lose per-asset granularity.

- **Materialization to features skipped with clear log message:** Cross-asset composite aggregates (means, PCA scores) don't map to per-asset features rows. The composites are fully available in ctf_composites for query. This avoids a misleading "materialization complete" that would produce zero rows updated.

- **Leader-follower uses full-history window score:** Rather than per-timestamp scores (would require rolling pairwise correlations = prohibitively slow at 7 assets × 389 features), each asset gets one leader score = average best_corr across pairs where it leads. Stored at last_ts of the data window. This matches the intended "identify structural leaders" purpose.

- **Chunked 50K-row persistence:** 1.43M rows at 20s/chunk = 580s for sentiment_mean. 6.41M rows at 18s/chunk = 2300s for relative_value. Without chunking, single-transaction timeout would prevent any persistence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed row-iteration performance bottleneck in sentiment_mean and relative_value**
- **Found during:** Task 2 (first run timing: sentiment_mean computation timed out at 300s on the row iteration loop)
- **Issue:** Original implementation used `for ts, row in pivot.iterrows()` over 389 features × ~5,600 timestamps = 2.18M iterations, each doing Python-level dropna/mean. This caused timeout before any rows were produced.
- **Fix:** Replaced with vectorized `pivot.mean(axis=1)`, `pivot.notna().sum(axis=1)`, masking on `n_valid >= min_assets`. Sentiment_mean computation dropped from >5 min to ~5s.
- **Files modified:** src/ta_lab2/scripts/features/refresh_ctf_composites.py
- **Verification:** sentiment_mean computed 1,433,059 rows in ~5s in dry-run; relative_value computed 6,408,145 rows in ~16s
- **Committed in:** 73685686 (Task 2 commit)

**2. [Rule 1 - Bug] Removed unused datetime/timezone imports causing ruff F401 lint error**
- **Found during:** Task 2 (pre-commit ruff check)
- **Issue:** `from datetime import datetime, timezone` imported but not used
- **Fix:** Replaced with `import datetime  # noqa: F401` (reserved for future output timestamp formatting)
- **Files modified:** src/ta_lab2/scripts/features/refresh_ctf_composites.py
- **Verification:** `ruff check` passes, all pre-commit hooks pass
- **Committed in:** 73685686 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 performance bug fix, 1 lint fix)
**Impact on plan:** Vectorization was necessary for correctness (row iteration would never complete). Lint fix is trivial. No scope creep.

## Issues Encountered

- Data loading is the dominant cost: 7 assets × load_ctf_features() = ~2.5-3 min per run (loads full CTF history). This is a query cost in the ctf table (17M rows for 1D). For future optimization: cache loaded pivots to disk or restrict train_start window.
- numpy `RuntimeWarning: invalid value encountered in divide` during leader_follower pairwise correlation: triggered when a CTF feature is constant (zero variance) for a time series pair. These pairs return NaN correlations, correctly handled by the `if np.isnan(best_corr): continue` guard.
- Leader_follower run with `lags=[1,3,5]` produces `lag_range = range(-5, 6)` (min(lags)*-1 to max(lags)+1). The sign convention `best_lag < 0 means col_a leads col_b` is correctly applied.

## User Setup Required

None - no external service configuration required. Tables already created by Phase 98-01 migration. Run:

```bash
# Single composite types (faster, for targeted refresh)
python -m ta_lab2.scripts.features.refresh_ctf_composites --composite sentiment_mean
python -m ta_lab2.scripts.features.refresh_ctf_composites --composite sentiment_pca
python -m ta_lab2.scripts.features.refresh_ctf_composites --composite relative_value
python -m ta_lab2.scripts.features.refresh_ctf_composites --composite leader_follower

# Full run (all composites, ~60-90 min with RV write)
python -m ta_lab2.scripts.features.refresh_ctf_composites

# Dry run (verify shapes without writing)
python -m ta_lab2.scripts.features.refresh_ctf_composites --dry-run
```

## Next Phase Readiness

- Phase 98-04 (lead-lag IC matrix): ctf_composites populated; can share _load_multi_asset_pivot() pattern
- Phase 99 (backtest expansion): ctf_composites.composite_name query available for strategy signals
- Phase 100 (ML): sentiment_mean and relative_value composites for ML feature engineering
- ctf_composites upsert is idempotent; safe to re-run on schedule

---
*Phase: 98-ctf-feature-graduation*
*Completed: 2026-03-31*
