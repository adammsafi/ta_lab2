---
phase: 37-ic-evaluation
verified: 2026-02-24T02:25:57Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Phase 37: IC Evaluation Verification Report

**Phase Goal:** Users can score any feature column for predictive power across forward-return horizons, broken down by regime, with significance testing and results persisted to the database.
**Verified:** 2026-02-24T02:25:57Z
**Status:** passed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | compute_ic() raises TypeError when train_start/train_end omitted; boundary masking prevents look-ahead bias | VERIFIED | Lines 311-434 ic.py: required positional args; boundary_mask at L187-188 nulls bars where bar_ts + horizon_delta > train_end |
| 2 | compute_ic() with 7 horizons returns 14 rows (7x2 return types); all required columns present | VERIFIED | 14-row shape test test_ic.py L174-176; required columns test L178-196; rolling IC + IC-IR per horizon |
| 3 | Rolling IC (63-bar window) + IC-IR + IC-IR t-stat computed and match manual calculation | VERIFIED | compute_rolling_ic() L213-267 vectorized rank-then-correlate; IC-IR = mean/std at L264; t-stat = mean*sqrt(n)/std at L265; manual calc tests at L426-471 |
| 4 | compute_ic_by_regime() returns separate IC per regime label; empty/None regimes fall back to full-sample | VERIFIED | L442-615 ic.py: regime split L548-593; None/empty fallback L503-520; sparse guard min_obs_per_regime=30 at L565-572; all-sparse fallback L595-613 |
| 5 | IC t-stat + p-value attached to each row; turnover computed; results persisted to cmc_ic_results | VERIFIED | _ic_t_stat() L57-76 with 1e-15 guard; _ic_p_value() L79-92; compute_feature_turnover() L270-303; save_ic_results() L1006-1098 with ON CONFLICT DO NOTHING/UPDATE |

**Score:** 5/5 truths verified

---
### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/ta_lab2/analysis/ic.py | IC computation library | VERIFIED | 1098 lines; all 11 public functions present; no stubs or TODOs |
| tests/analysis/test_ic.py | 61-test suite | VERIFIED | 1006 lines; 61 test functions; 10 test classes covering all behaviors |
| tests/analysis/__init__.py | Package init | VERIFIED | Exists |
| src/ta_lab2/scripts/analysis/run_ic_eval.py | CLI script | VERIFIED | 434 lines; argparse, NullPool, engine.begin(), sys.exit() pattern |
| src/ta_lab2/scripts/analysis/__init__.py | Package init | VERIFIED | Exists |
| alembic/versions/c3b718c2d088_ic_results_table.py | Alembic migration | VERIFIED | 114 lines; cmc_ic_results UUID PK, 9-col UniqueConstraint, 2 indexes; chained from 5f8223cfbf06 |
| sql/features/080_cmc_ic_results.sql | Reference DDL | VERIFIED | Full DDL with comments, indexes, table COMMENT |
| src/ta_lab2/analysis/feature_eval.py | fillna fix applied | VERIFIED | No fillna(method=) pattern; only .ffill().fillna(0.0) at line 78 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| run_ic_eval.py | ic.py compute_ic | import L59, call L343 | VERIFIED | CLI imports and calls compute_ic with all required args |
| run_ic_eval.py | ic.py compute_ic_by_regime | import L60, call L322 | VERIFIED | Called in --regime mode for both trend_state and vol_state |
| run_ic_eval.py | ic.py load_feature_series | import L62, call L292 | VERIFIED | Loads feature+close from cmc_features with pd.to_datetime(utc=True) |
| run_ic_eval.py | ic.py load_regimes_for_asset | import L63, call L267 | VERIFIED | Uses split_part SQL, returns trend_state/vol_state columns |
| run_ic_eval.py | ic.py save_ic_results | import L64, call L414 | VERIFIED | Called with all_rows + overwrite flag; skipped in dry_run mode |
| ic.py load_regimes_for_asset | cmc_regimes.l2_label | split_part SQL L973-974 | VERIFIED | split_part(l2_label) used -- NOT trend_state/vol_state direct columns |
| ic.py load_feature_series | cmc_features | get_columns() validation + f-string SQL | VERIFIED | L901-906: lazy import, column validated before SQL injection |
| ic.py save_ic_results | cmc_ic_results | ON CONFLICT DO NOTHING/UPDATE | VERIFIED | L1032-1070: both overwrite modes with correct 9-col conflict target |
| alembic migration | cmc_ic_results table | create_table + UniqueConstraint + indexes | VERIFIED | 9-col unique key; idx_ic_results_asset_feature; idx_ic_results_computed_at |
| compute_ic_by_regime | compute_ic | call per regime label L579-593 | VERIFIED | Loops unique regime labels, calls compute_ic per subset |
| batch_compute_ic | compute_ic | call per feature column L678-691 | VERIFIED | Loops feature_cols, appends feature column, concatenates |

---
### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|---------|
| IC-01: compute_ic raises TypeError on omission; future data beyond train_end nulled | SATISFIED | Positional required args (TypeError on omission); boundary_mask L187-188; tests L161-169 |
| IC-02: horizons [1,2,3,5,10,20,60] -> 14-row DataFrame; IC decay for predictive feature | SATISFIED | _DEFAULT_HORIZONS L48; 14-row shape test L174-176; positive IC test L212-233 |
| IC-03: Rolling IC (63-bar) and IC-IR match manual calculation | SATISFIED | compute_rolling_ic() L213-267; IC-IR = mean/std at L264; manual calc tests L426-471 |
| IC-04: compute_ic_by_regime returns IC per regime label; empty/None fallback to full-sample | SATISFIED | L442-615; None/empty fallback L503-520; regime-split loop L548-593; tests L636-793 |
| IC-05: IC t-stat + p-value per row; turnover stored alongside IC in cmc_ic_results | SATISFIED | _ic_t_stat() L57-76 with 1e-15 guard; _ic_p_value() L79-92; turnover at L429; save_ic_results() L1093 |

---

### Anti-Patterns Found

No TODOs, FIXMEs, placeholder text, empty returns, or stub handlers found in any phase 37 files.

---

### Human Verification Required

**1. End-to-end CLI invocation with live database**

Test: python -m ta_lab2.scripts.analysis.run_ic_eval --asset-id 1 --tf 1D --feature ret_arith --train-start 2020-01-01 --train-end 2024-01-01 --dry-run
Expected: Computes IC rows, logs top-5 features by |IC|, prints NOT writing to cmc_ic_results -- exits with code 0
Why human: Requires live database connection to cmc_features; verifies the full data load -> compute -> log pipeline.

**2. Alembic upgrade confirmation in environment**

Test: alembic upgrade head from clean baseline
Expected: cmc_ic_results table with UUID PK, uq_ic_results_key, and both indexes
Why human: Structural code verified correct; SUMMARY reports manual upgrade/downgrade round-trip confirmed. Cannot verify live DB state programmatically.

---

## Gaps Summary

No gaps found. All 5 observable truths are fully verified.

1. **IC-01 (boundary masking + TypeError):** compute_ic() enforces train_start/train_end as required positional args (Python TypeError on omission). Boundary masking logic at lines 185-188 nulls forward returns for bars where bar_ts + horizon_delta > train_end, preventing look-ahead bias.

2. **IC-02 (14-row output + IC decay):** Default horizons [1,2,3,5,10,20,60] x return_types produce exactly 14 rows. All 9 required columns present. Test suite verifies predictive feature produces positive IC at horizon=1.

3. **IC-03 (rolling IC + IC-IR):** Vectorized rolling IC uses rolling().rank() then rolling().corr() pattern (30x faster than per-window spearmanr). IC-IR = mean(rolling_ic)/std(rolling_ic) at L264. IC-IR t-stat = mean*sqrt(n)/std at L265. Manual calculation tests at L426-471 verify formula correctness.

4. **IC-04 (regime breakdown):** compute_ic_by_regime() properly splits data by regime label, skips sparse regimes (< 30 bars), and falls back to full-sample IC when regimes_df is None/empty or all regimes are sparse. l2_label parsing delegated to SQL split_part() in load_regimes_for_asset(), not trend_state/vol_state direct columns.

5. **IC-05 (significance + persistence):** _ic_t_stat() with 1e-15 denominator guard and _ic_p_value() via norm.cdf() are attached to each row. Turnover = 1 - spearmanr(lag-1 ranks). save_ic_results() persists all IC outputs to cmc_ic_results with ON CONFLICT DO NOTHING (append) or ON CONFLICT DO UPDATE (upsert) semantics.

---

_Verified: 2026-02-24T02:25:57Z_
_Verifier: Claude (gsd-verifier)_
