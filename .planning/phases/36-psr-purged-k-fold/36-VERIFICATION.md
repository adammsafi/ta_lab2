---
phase: 36-psr-purged-k-fold
verified: 2026-02-24T00:24:25Z
status: passed
score: 22/22 must-haves verified
re_verification: false
---

# Phase 36: PSR + Purged K-Fold Verification Report

**Phase Goal:** Users can compute statistically sound Sharpe ratio estimates (PSR, DSR, MinTRL) and perform leakage-free cross-validation (PurgedKFold, CPCV) on any backtest result or feature set.
**Verified:** 2026-02-24T00:24:25Z
**Status:** passed
**Re-verification:** No - initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | alembic upgrade head adds psr_legacy and psr columns to cmc_backtest_metrics | VERIFIED | adf582a23467_psr_column_rename.py conditionally renames existing psr to psr_legacy then adds new nullable psr column |
| 2 | alembic upgrade head creates psr_results table with run_id FK and formula_version unique constraint | VERIFIED | 5f8223cfbf06_psr_results_table.py creates table with uq_psr_results_run_version and FK to cmc_backtest_runs |
| 3 | alembic downgrade reverses both revisions cleanly | VERIFIED | adf582a23467 downgrade drops psr and psr_legacy IF EXISTS; 5f8223cfbf06 downgrade drops psr_results table |
| 4 | Existing cmc_backtest_metrics rows are unaffected (no data loss) | VERIFIED | upgrade uses ALTER COLUMN rename only, not DROP; existing data preserved in psr_legacy |
| 5 | Downgrade drops both psr and psr_legacy unconditionally (IF EXISTS) | VERIFIED | downgrade uses DROP COLUMN IF EXISTS for both; does NOT rename back to avoid phantom column |
| 6 | compute_psr(returns, sr_star=0) returns float in [0, 1] for valid returns | VERIFIED | Full PSR formula with scipy norm.cdf; test_returns_float_in_unit_interval and test_strong_positive_returns_high_psr pass |
| 7 | compute_psr returns NaN when n < 30 and logs a warning | VERIFIED | psr.py lines 84-90: n < 30 guard warnings.warn then return float(nan); test_nan_when_n_lt_30 passes |
| 8 | compute_psr logs a warning when n < 100 | VERIFIED | psr.py lines 92-97: n < 100 guard warnings.warn; test_warning_when_n_lt_100 passes |
| 9 | compute_psr handles zero-std returns correctly | VERIFIED | psr.py lines 99-107: sr_star==0 returns 0.5, sr_star>0 returns 0.0, sr_star<0 returns 1.0; all 3 zero-std tests pass |
| 10 | compute_dsr with full SR list produces value <= raw best Sharpe PSR | VERIFIED | compute_dsr calls expected_max_sr(sr_estimates) as benchmark then compute_psr; test_exact_mode_less_than_raw_psr passes |
| 11 | compute_dsr with n_trials approximation produces value <= raw best Sharpe PSR | VERIFIED | n_trials path uses synthetic N(0,1) draws for expected_max_sr; test_approximate_mode_less_than_raw_psr passes |
| 12 | min_trl returns n_obs (bars) and calendar_days for valid strategies | VERIFIED | Returns dict with n_obs, calendar_days, sr_hat, target_psr; multiple tests pass |
| 13 | min_trl returns inf when sr_hat <= sr_star | VERIFIED | psr.py lines 262-264: if sr_hat <= sr_star return result_inf; test_inf_when_sr_hat_leq_sr_star passes |
| 14 | PSR variance formula uses Pearson kurtosis (fisher=False) | VERIFIED | psr.py line 112: kurtosis(arr, fisher=False); line 267 same; test_pearson_kurtosis_variance_formula passes explicitly |
| 15 | PurgedKFoldSplitter raises ValueError when t1_series is None | VERIFIED | cv.py lines 84-89: if t1_series is None raise ValueError; test_raises_value_error_when_t1_none and test_raises_value_error_no_t1_kwarg pass |
| 16 | PurgedKFoldSplitter removes training observations whose labels overlap the test period | VERIFIED | cv.py lines 177-178: purge_mask = (t1_complement <= test_start_ts); purge tests pass |
| 17 | PurgedKFoldSplitter applies embargo gap after each test fold | VERIFIED | cv.py embargo logic lines 183-190; test_embargo_removes_post_test_obs and test_zero_embargo_frac pass |
| 18 | PurgedKFoldSplitter works with sklearn cross_val_score | VERIFIED | test_cross_val_score_runs_without_error and test_cross_val_score_returns_array pass |
| 19 | CPCVSplitter generates C(N, n_test) combinations | VERIFIED | itertools.combinations(range(n_splits), n_test_splits); C(6,2)=15, C(10,2)=45, C(5,3)=10 all verified |
| 20 | CPCV paths cover the full sample without train-test contamination | VERIFIED | test_full_sample_covered_across_all_test_sets and no-overlap tests for C(6,2) and C(5,2) pass |
| 21 | No train-test index overlap in any fold for either splitter | VERIFIED | Overlap tests pass for PurgedKFoldSplitter (5 and 10 folds) and CPCVSplitter; all 64 tests pass |
| 22 | CV splitters are library-only - no pipeline integration in this phase | VERIFIED | cv.py docstring: This module is library-only. No pipeline integration or CLI wiring is included. |

**Score:** 22/22 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `alembic/versions/adf582a23467_psr_column_rename.py` | PSR column rename migration | VERIFIED | 85 lines; information_schema.columns check; conditional rename; IF EXISTS downgrade |
| `alembic/versions/5f8223cfbf06_psr_results_table.py` | psr_results table creation | VERIFIED | 90 lines; psr_results with run_id FK and uq_psr_results_run_version unique constraint |
| `sql/backtests/073_psr_results.sql` | Reference DDL for psr_results | VERIFIED | 86 lines; CREATE TABLE with all required columns and documentation |
| `src/ta_lab2/backtests/psr.py` | PSR/DSR/MinTRL formulas | VERIFIED | 293 lines (min 120 required); exports compute_psr, compute_dsr, min_trl, expected_max_sr; scipy.stats; fisher=False |
| `tests/backtests/test_psr.py` | PSR tests | VERIFIED | 359 lines (min 80 required); 31 tests all pass; Pearson kurtosis trap test included |
| `src/ta_lab2/backtests/cv.py` | PurgedKFoldSplitter + CPCVSplitter | VERIFIED | 384 lines (min 120 required); both classes inherit BaseCrossValidator; t1_series guard on both |
| `tests/backtests/test_cv.py` | CV splitter tests | VERIFIED | 471 lines (min 100 required); 33 tests all pass |
| `src/ta_lab2/scripts/backtests/backtest_from_signals.py` | PSR wiring in backtest pipeline | VERIFIED | imports compute_psr; calls on pf.returns(); writes to psr_results with formula_version, return_source, skewness, kurtosis_pearson, n_obs |
| `src/ta_lab2/scripts/backtests/compute_psr.py` | PSR recompute CLI | VERIFIED | 431 lines (min 80 required); argparse --run-id/--all/--recompute/--sr-star/--dry-run; queries cmc_backtest_trades |
| `src/ta_lab2/scripts/alembic_utils.py` | Alembic migration check utilities | VERIFIED | 164 lines (min 30 required); exports is_alembic_head and check_migration_status; MigrationContext + ScriptDirectory; NullPool |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `adf582a23467_psr_column_rename.py` | `25f2b3c90f65` (prior revision) | down_revision = "25f2b3c90f65" | WIRED | Correct chain from prior head revision |
| `5f8223cfbf06_psr_results_table.py` | `adf582a23467_psr_column_rename.py` | down_revision = "adf582a23467" | WIRED | Second migration chains from first |
| `psr.py` | `scipy.stats` | from scipy.stats import kurtosis, norm, skew | WIRED | All three functions imported and used in PSR formula |
| `psr.py` | Pearson kurtosis | fisher=False in kurtosis() calls | WIRED | Two call sites: compute_psr line 112, min_trl line 267 |
| `cv.py` | `BaseCrossValidator` | class PurgedKFoldSplitter(BaseCrossValidator) | WIRED | Both classes inherit; get_n_splits and _iter_test_masks implemented |
| `cv.py` | t1_series guard | if t1_series is None: raise ValueError | WIRED | Both PurgedKFoldSplitter and CPCVSplitter guard at construction |
| `backtest_from_signals.py` | `ta_lab2.backtests.psr` | from ta_lab2.backtests.psr import compute_psr, min_trl | WIRED | Line 28; compute_psr called line 650, min_trl called line 661 |
| `backtest_from_signals.py` | `psr_results` table | INSERT INTO public.psr_results | WIRED | Lines 818-846; formula_version, return_source, skewness, kurtosis_pearson, n_obs all written |
| `compute_psr.py` | `ta_lab2.backtests.psr` | from ta_lab2.backtests.psr import compute_psr, min_trl | WIRED | Line 39; used in compute_psr_for_run() |
| `compute_psr.py` | `cmc_backtest_trades` | SELECT entry_ts, exit_ts, pnl_pct FROM public.cmc_backtest_trades | WIRED | Lines 178-186 in compute_psr_for_run() |
| `run_daily_refresh.py` | `ta_lab2.scripts.alembic_utils` | from ta_lab2.scripts.alembic_utils import check_migration_status | WIRED | Line 46; called line 989 in main(); warn-only, no auto-upgrade |
| `alembic_utils.py` | alembic | from alembic.runtime.migration import MigrationContext + ScriptDirectory | WIRED | Both functions import and use MigrationContext and ScriptDirectory; NullPool connections |

---

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| PSR-01: Alembic migration renaming psr to psr_legacy | SATISFIED | None |
| PSR-02: Full Lopez de Prado PSR formula with n, skewness, kurtosis via scipy | SATISFIED | None |
| PSR-03: Minimum sample guard (NaN when n<30, warn when n<100) + configurable sr_star | SATISFIED | None |
| PSR-04: DSR for multiple-testing correction | SATISFIED | None |
| PSR-05: MinTRL inverse of PSR, reports n_obs and calendar_days | SATISFIED | None |
| CV-01: PurgedKFoldSplitter with t1_series required, sklearn compatible | SATISFIED | None |
| CV-02: Embargo gap parameterized, with fold validation assertions | SATISFIED | None |
| CV-03: CPCV generating C(N, n_test) combinations for PBO analysis | SATISFIED | None |

---

## Anti-Patterns Found

No anti-patterns found. No TODO, FIXME, placeholder, return null, or stub patterns in any implementation file.

Note: The sklearn integration tests emit UserWarning from DummyClassifier when the purged training set is empty for aggressive purge+embargo configurations. This is expected behavior from sklearn internals and does not indicate a defect in cv.py. All 64 tests pass with PASSED status.

---

## Human Verification Required

### 1. Alembic Upgrade on Live DB

**Test:** Run alembic upgrade head against a DB that has the old psr column in cmc_backtest_metrics, then inspect schema with information_schema.columns.
**Expected:** psr_legacy column holds old values intact, new nullable psr column added, psr_results table created with FK and unique constraint.
**Why human:** Requires live PostgreSQL connection; the information_schema conditional logic runs at migration time only.

### 2. Alembic Downgrade on Live DB

**Test:** Run alembic downgrade -1 twice on an upgraded DB.
**Expected:** psr_results table dropped cleanly, then both psr and psr_legacy columns dropped; no phantom columns remain.
**Why human:** Requires live PostgreSQL; IF EXISTS behavior is structurally verified only.

### 3. PSR Auto-Compute in Backtest Pipeline

**Test:** Run backtest_from_signals.py end-to-end, then query psr_results WHERE return_source = portfolio.
**Expected:** Row with formula_version=lopez_de_prado_v1, non-null psr, skewness, kurtosis_pearson, n_obs values.
**Why human:** Requires live DB with signal + price data; wiring verified structurally.

### 4. compute_psr CLI on Historical Runs

**Test:** Run python -m ta_lab2.scripts.backtests.compute_psr --all --dry-run then without --dry-run.
**Expected:** Dry-run logs PSR values without writes; without dry-run writes psr_results rows with return_source=trade_reconstruction.
**Why human:** Requires live DB with cmc_backtest_trades data.

### 5. Migration Status Check on Startup

**Test:** Run python -m ta_lab2.scripts.run_daily_refresh --all against a DB behind alembic head.
**Expected:** Prints migration warning then continues without aborting and without auto-upgrading.
**Why human:** Requires live DB in a behind-head state.

---

## Summary

All 22 must-haves are verified at all three levels (exists, substantive, wired). The full test suite passes 64/64 tests with zero failures. Phase 36 goal is fully achieved: users can compute PSR/DSR/MinTRL via the formula library and CLI, and perform leakage-free cross-validation with PurgedKFold and CPCV. Five items require live-database verification.

---

_Verified: 2026-02-24T00:24:25Z_
_Verifier: Claude (gsd-verifier)_
