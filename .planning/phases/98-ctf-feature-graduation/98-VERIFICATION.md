---
phase: 98-ctf-feature-graduation
verified: 2026-03-31T17:22:51Z
status: passed
score: 4/4 must-haves verified
gaps: []
human_verification:
  - test: Run refresh_ctf_promoted.py against live DB and confirm rows updated
    expected: 22322+ rows updated with non-null CTF column values
    why_human: Cannot verify actual DB row counts without live DB connection
  - test: Query dim_feature_selection_asset and compare to dim_feature_selection global tier
    expected: dim_feature_selection_asset 10716 rows tier=asset_specific; dim_feature_selection 205 rows unchanged
    why_human: DB row counts require live DB
  - test: Query ctf_composites GROUP BY method and verify 4 distinct methods
    expected: cross_asset_mean ~1.43M, pca_1 ~232K, cs_zscore ~6.41M, lagged_corr ~1.1K
    why_human: Row counts in ctf_composites require live DB
  - test: Query COUNT and SUM of is_significant FROM lead_lag_ic
    expected: 48204 total rows, ~5087 significant at BH-corrected p < 0.05
    why_human: lead_lag_ic row counts require live DB
---

# Phase 98: CTF Feature Graduation Verification Report

**Phase Goal:** Top CTF features are materialized in the main features table and usable by downstream consumers (BL, signals, ML), with asset-specific selection, cross-asset composites, and lead-lag analysis.
**Verified:** 2026-03-31T17:22:51Z
**Status:** PASSED
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | refresh_ctf_promoted.py runs and writes CTF feature columns into the features table; feature_selection.yaml lists each promoted feature with IC threshold and source CTF config | VERIFIED | Script is 714 lines, fully implemented with UPDATE SQL to public.features, pre-flight column check, YAML append. feature_selection.yaml ctf_promoted section at line 1626 with 401 entries each having name, median_abs_ic, n_assets, source_ctf_config, base_tf; ic_threshold: 0.02 at section level |
| 2 | dim_feature_selection_asset contains rows with tier=asset_specific; query by asset_id returns a superset vs global tier; dim_feature_selection is NOT touched | VERIFIED | run_ctf_asset_selection.py (625 lines) uses INSERT ON CONFLICT DO UPDATE exclusively into dim_feature_selection_asset. All inserted rows have tier: asset_specific (line 335). Pre-flight guard raises RuntimeError if table missing. States DO NOT touch dim_feature_selection. Baseline count check of global table is implemented |
| 3 | A cross-asset CTF composite script produces sentiment, relative-value, and leader-follower aggregate columns stored in ctf_composites, runnable via CLI | VERIFIED | refresh_ctf_composites.py (1215 lines) implements all 4 composite types: compute_sentiment_mean, compute_sentiment_pca, compute_relative_value, compute_leader_follower. Persistence via chunked 50K-row temp-table upsert into ctf_composites (line 797). CLI main() at line 1096 with --composite, --base-tf, --dry-run flags. Config at configs/ctf_composites_config.yaml defines all 4 composites |
| 4 | A lead-lag IC matrix script outputs whether Asset A CTF features predict Asset B returns at horizons [1,3,5]; results persisted to lead_lag_ic table or CSV report | VERIFIED | run_ctf_lead_lag_ic.py (1012 lines) computes Spearman IC with default --horizons 1,3,5. BH FDR via statsmodels.stats.multitest.multipletests at line 381. Persistence to lead_lag_ic via temp-table INSERT ON CONFLICT (lines 454-471). CSV report at reports/ctf/lead_lag_ic_report.csv. Sequential and parallel paths both implemented |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/r2s3t4u5v6w7_phase98_ctf_graduation_schema.py | Alembic migration adding CTF cols + 3 new tables | VERIFIED | 302 lines; creates dim_feature_selection_asset, ctf_composites, lead_lag_ic; dynamic IC discovery from ic_results; idempotency guard via information_schema |
| src/ta_lab2/scripts/features/refresh_ctf_promoted.py | ETL script CTF fact table to features table UPDATE | VERIFIED | 714 lines; _update_features_for_scope() builds dynamic UPDATE SQL via _UPDATE_SQL_TEMPLATE targeting public.features; calls load_ctf_features() from ta_lab2.features.cross_timeframe; pre-flight check; YAML write; CLI main() |
| configs/feature_selection.yaml ctf_promoted section | 401 features with IC threshold and source config | VERIFIED | 401 feature entries under ctf_promoted: (lines 1626-3637); each entry: name, median_abs_ic, n_assets, source_ctf_config, base_tf; section: ic_threshold: 0.02, n_features: 401 |
| src/ta_lab2/scripts/analysis/run_ctf_asset_selection.py | Per-asset CTF selection writing to dim_feature_selection_asset | VERIFIED | 625 lines; queries ic_results per asset; asset-specific additions = per-asset passing minus global; upserts with tier=asset_specific; dim_feature_selection untouched |
| src/ta_lab2/scripts/features/refresh_ctf_composites.py | Cross-asset composite script with 4 composite types | VERIFIED | 1215 lines; all 4 functions implemented; vectorized pivot operations; chunked persistence to ctf_composites |
| configs/ctf_composites_config.yaml | Config for composite types with thresholds | VERIFIED | 40 lines; defines sentiment_mean, sentiment_pca, relative_value, leader_follower with min_assets, lags, pca_variance_threshold |
| src/ta_lab2/scripts/analysis/run_ctf_lead_lag_ic.py | Lead-lag IC matrix with BH FDR and horizons [1,3,5] | VERIFIED | 1012 lines; spearmanr from scipy; multipletests from statsmodels; default --horizons 1,3,5; persistence to lead_lag_ic; CSV report |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| refresh_ctf_promoted.py | public.features UPDATE | _UPDATE_SQL_TEMPLATE + _update_features_for_scope() | WIRED | Line 91: UPDATE public.features SET set_clauses WHERE id=:id AND ts=:ts; dynamically builds SET from promoted column list |
| refresh_ctf_promoted.py | load_ctf_features() | from ta_lab2.features.cross_timeframe import load_ctf_features | WIRED | Line 44 import; called at line 325 inside _update_features_for_scope() |
| refresh_ctf_promoted.py | configs/feature_selection.yaml | _update_feature_selection_yaml() | WIRED | Called at line 596; reads existing YAML, appends/overwrites ctf_promoted section |
| run_ctf_asset_selection.py | dim_feature_selection_asset | INSERT ON CONFLICT DO UPDATE upsert | WIRED | SQL at lines 140-157; tier=asset_specific hardcoded at line 335 |
| run_ctf_asset_selection.py | dim_feature_selection read-only | SELECT COUNT baseline check only | WIRED | Line 368 reads count; no writes; decoupled as intended |
| refresh_ctf_composites.py | ctf_composites | chunk.to_sql + INSERT ON CONFLICT upsert | WIRED | Lines 783-808: temp table _tmp_ctf_composites -> INSERT INTO public.ctf_composites ON CONFLICT DO UPDATE |
| refresh_ctf_composites.py | configs/ctf_composites_config.yaml | _load_composites_config() at line 97 | WIRED | Config drives composite selection, min_assets, PCA params, lags |
| run_ctf_lead_lag_ic.py | lead_lag_ic | _persist_to_lead_lag_ic() temp-table upsert | WIRED | Lines 454-471: INSERT ON CONFLICT (asset_a_id, asset_b_id, feature, horizon, tf, venue_id) |
| run_ctf_lead_lag_ic.py | feature_selection.yaml ctf_promoted | _load_promoted_features() at line 174 | WIRED | Queries ic_results DB for promoted features consistent with YAML-written set |
| run_ctf_lead_lag_ic.py | reports/ctf/lead_lag_ic_report.csv | _generate_csv_report() | WIRED | Line 510: df_sorted.to_csv(report_path, index=False) |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| SC1: refresh_ctf_promoted.py writes CTF columns to features; feature_selection.yaml has IC threshold + source CTF config | SATISFIED | 401 features promoted (exceeds stated 15-20 minimum -- plan decision was no artificial cap) |
| SC2: dim_feature_selection_asset has tier=asset_specific rows; superset relationship holds; dim_feature_selection NOT touched | SATISFIED | Script explicitly guards global table; upserts only to asset-specific table |
| SC3: Cross-asset composite script with sentiment/relative-value/leader-follower stored in ctf_composites, runnable via CLI | SATISFIED | 4 composite types implemented; python -m ta_lab2.scripts.features.refresh_ctf_composites invokable |
| SC4: Lead-lag IC matrix at horizons [1,3,5] persisted to lead_lag_ic or CSV | SATISFIED | Both DB table and CSV report implemented; default horizons are 1,3,5 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| refresh_ctf_promoted.py | 403 | placeholder in docstring | Info | Docstring explains why _get_feature_base_tf() returns a fixed string; intentional design note not an implementation gap |
| Multiple files | Various | return [] or return {} | Info | All are legitimate early-exit guards; none are implementation stubs |

No blocker anti-patterns found.

### Human Verification Required

The following items cannot be verified programmatically because they depend on live DB state:

#### 1. features table CTF column writes

**Test:** Run python -m ta_lab2.scripts.features.refresh_ctf_promoted --base-tf 1D and verify row counts.
**Expected:** Script exits without RuntimeError; logs show rows_updated=22322+; spot-check SELECT ret_arith_365d_divergence FROM features WHERE id=1 LIMIT 5 returns non-null floats.
**Why human:** Requires live DB connection; Alembic migration must have been applied first.

#### 2. dim_feature_selection_asset row counts and tier

**Test:** SELECT COUNT(*), tier FROM dim_feature_selection_asset GROUP BY tier and SELECT COUNT(*) FROM dim_feature_selection.
**Expected:** dim_feature_selection_asset: 10,716 rows all with tier=asset_specific; dim_feature_selection: 205 rows unchanged.
**Why human:** Live DB state cannot be read without DB connection.

#### 3. ctf_composites table population

**Test:** SELECT method, COUNT(*) FROM ctf_composites GROUP BY method ORDER BY method.
**Expected:** 4 rows: cross_asset_mean ~1.43M, pca_1 ~232K, cs_zscore ~6.41M, lagged_corr ~1.1K.
**Why human:** 8.07M row table requires live DB.

#### 4. lead_lag_ic FDR-corrected results

**Test:** SELECT COUNT(*), SUM(CASE WHEN is_significant THEN 1 ELSE 0 END) FROM lead_lag_ic.
**Expected:** 48,204 total rows; ~5,087 significant pairs; top: LINK -> HYPE, adx_14_365d_divergence, horizon=5, IC=0.66.
**Why human:** Live DB required; CSV report is gitignored so cannot read from disk.

### Gaps Summary

No gaps. All four observable truths are structurally verified. All required artifacts exist, are substantive (714-1215 lines each), and are wired to their respective data stores. Key links are present at both the SQL and Python import levels. Human verification is required only for live DB row count confirmation, which is expected for any DB-write pipeline.

Notable finding on SC1 feature count: The success criterion states writes 15-20 CTF feature columns but the implementation promotes 401 features (all that pass IC > 0.02 cross-asset median). This is consistent with the plan decision all passing features -- no artificial cap. The goal is satisfied and then some.

---

_Verified: 2026-03-31T17:22:51Z_
_Verifier: Claude (gsd-verifier)_
