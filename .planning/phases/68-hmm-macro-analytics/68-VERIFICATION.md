---
phase: 68-hmm-macro-analytics
verified: 2026-03-03T11:27:27Z
status: passed
score: 15/15 must-haves verified
re_verification: false
---

# Phase 68: HMM and Macro Analytics Verification Report

**Phase Goal:** Secondary analytical tools -- HMM regime confirmation, macro-crypto lead-lag quantification, and regime transition probabilities -- provide deeper insight into macro regime quality and predictive power.
**Verified:** 2026-03-03T11:27:27Z
**Status:** passed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 2-3 state GaussianHMM trained on all FRED float features (covariance_type="diag" default) produces state labels comparable to rule-based labels | VERIFIED | hmm_classifier.py: _N_STATES_OPTIONS=[2,3], GaussianHMM with covariance_type=self.covariance_type, default "diag", BIC selection, compare_with_rule_based via Cohen kappa |
| 2 | Lead-lag analysis using lead_lag_max_corr quantifies predictive lag of each macro feature on BTC/ETH returns at lags [-60..+60] days | VERIFIED | lead_lag_analyzer.py: imports lead_lag_max_corr from ta_lab2.regimes.comovement, _DEFAULT_LAG_RANGE=range(-60,61), Bartlett threshold 2.0/sqrt(n_obs), scans all FRED float features vs BTC and ETH (asset IDs 1 and 2) |
| 3 | Regime transition probability matrix is computed from historical macro regime sequences and queryable for any regime-to-regime pair | VERIFIED | transition_probs.py: compute_static, compute_rolling 252-day window, row-normalized with 0.0 for zero-count rows, get_transition_prob module-level wrapper with scoped MAX subquery |

**Score:** 3/3 truths verified

---
## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/e0d8f7aec87a_hmm_macro_analytics_tables.py | Alembic migration for 3 Phase 68 tables | VERIFIED | 297 lines; creates cmc_hmm_regimes PK(date,n_states,model_run_date), cmc_macro_lead_lag_results PK(macro_feature,asset_col,computed_at), cmc_macro_transition_probs PK(regime_source,window_type,window_end_date,from_state,to_state); down_revision chains from Phase 67 head d5e6f7a8b9c0 |
| src/ta_lab2/macro/hmm_classifier.py | HMMClassifier module | VERIFIED | 802 lines; GaussianHMM covariance_type=diag default, _N_RESTARTS=10, StandardScaler normalization, dropna before fit, _N_STATES_OPTIONS=[2,3], BIC selection, expanding window, weekly refit cadence, upsert_results via temp table + ON CONFLICT, compare_with_rule_based via Cohen kappa |
| src/ta_lab2/macro/lead_lag_analyzer.py | LeadLagAnalyzer module | VERIFIED | 523 lines; imports lead_lag_max_corr from ta_lab2.regimes.comovement at line 57; called at line 370; _DEFAULT_LAG_RANGE=range(-60,61); Bartlett threshold 2.0/sqrt(n_obs) at line 384; upsert_results via temp table + ON CONFLICT |
| src/ta_lab2/macro/transition_probs.py | TransitionProbMatrix module | VERIFIED | 716 lines; ROLLING_WINDOW_DAYS=252; compute_static, compute_rolling, compute_all; row-normalized with 0.0 for zero-count rows; DISTINCT ON deduplication for HMM; get_transition_prob wrapper; upsert_results via temp table + ON CONFLICT |
| src/ta_lab2/macro/__init__.py | Public API exports | VERIFIED | 40 lines; HMMClassifier, LeadLagAnalyzer, TransitionProbMatrix, get_transition_prob all imported and in __all__ |
| src/ta_lab2/scripts/macro/refresh_macro_analytics.py | Unified CLI | VERIFIED | 313 lines; --hmm-only, --lead-lag-only, --transition-only, --dry-run, --full, --force-refit, --covariance-type flags; per-tool try/except isolation |
| src/ta_lab2/scripts/run_daily_refresh.py | Pipeline wiring | VERIFIED | run_macro_analytics at line 1867; TIMEOUT_MACRO_ANALYTICS=900s; ordered after macro_regimes and before per-asset regimes at lines 2499-2510; --all includes stage |
| pyproject.toml | hmmlearn in optional-dependencies | VERIFIED | macro_analytics group with hmmlearn>=0.3.3 at lines 101-102 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| HMMClassifier.fit_and_predict | fred.fred_macro_features | _load_features SQL query | WIRED | SELECT col_list FROM fred.fred_macro_features WHERE date <= end_date ORDER BY date ASC |
| HMMClassifier | cmc_hmm_regimes | upsert_results temp table + ON CONFLICT | WIRED | ON CONFLICT (date, n_states, model_run_date) DO UPDATE SET at line 677 |
| LeadLagAnalyzer.scan_all | lead_lag_max_corr | import from ta_lab2.regimes.comovement | WIRED | Imported at line 57; called with col_a=macro_col, col_b=asset_col at line 370 |
| LeadLagAnalyzer | cmc_macro_lead_lag_results | upsert_results temp table + ON CONFLICT | WIRED | ON CONFLICT (macro_feature, asset_col, computed_at) DO UPDATE SET at line 514 |
| TransitionProbMatrix._load_hmm_regimes | cmc_hmm_regimes | DISTINCT ON (date) ORDER BY date, model_run_date DESC | WIRED | Deduplicates expanding-window HMM refits; BIC winner path at lines 131-135 |
| TransitionProbMatrix._load_rule_based_regimes | cmc_macro_regimes | SQL query filtered to profile=default | WIRED | Returns macro_state column; graceful fallback if table empty |
| TransitionProbMatrix | cmc_macro_transition_probs | upsert_results temp table + ON CONFLICT | WIRED | ON CONFLICT (regime_source, window_type, window_end_date, from_state, to_state) DO UPDATE SET at line 605 |
| get_transition_prob | cmc_macro_transition_probs | SQL COALESCE with scoped MAX subquery | WIRED | MAX scoped per regime_source+window_type lines 685-688; prevents cross-source contamination; returns float or None |
| refresh_macro_analytics.py | HMMClassifier, LeadLagAnalyzer, TransitionProbMatrix | Direct imports | WIRED | Lines 52-54 import all three classes; instantiated and called in main |
| run_daily_refresh.py --all | refresh_macro_analytics | subprocess.run via run_macro_analytics | WIRED | Pipeline block at lines 2499-2505; after macro_regimes, before per-asset regimes |
| hmmlearn.hmm.GaussianHMM | installed package | pyproject.toml + runtime import | WIRED | hmmlearn==0.3.3 importable; declared in [project.optional-dependencies.macro_analytics] |

---
## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| MREG-10: HMM secondary classifier (2-3 state GaussianHMM, covariance_type=diag default) as optional confirmation signal | SATISFIED | None |
| MREG-11: Macro-crypto lead-lag analysis using existing lead_lag_max_corr pattern at lags [-60..+60] days | SATISFIED | None |
| MREG-12: Regime transition probability matrix from historical macro regime sequences | SATISFIED | None |

---

## Anti-Patterns Found

No blockers or warnings found across the four core Phase 68 files.

Patterns investigated and cleared:

- return None in hmm_classifier.py lines 119 and 125: legitimate null-handling in _to_python helper for NaN/None psycopg2 safety, not stubs
- pass in hmm_classifier.py line 142: broad exception handler in _sanitize_dataframe column-type loop, deliberate defensive pattern, not a stub
- return None in transition_probs.py lines 711 and 714: guard returns in get_transition_prob for DB failure and no-match cases, correct behavior

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | No anti-patterns found |

---

## Human Verification Required

The following items cannot be verified programmatically and require a human to confirm once the Phase 68 Alembic migration has been applied to a live database.

### 1. Migration applies cleanly

**Test:** Run alembic upgrade head against the marketdata database
**Expected:** Three tables created (cmc_hmm_regimes, cmc_macro_lead_lag_results, cmc_macro_transition_probs) with all columns and indexes as specified
**Why human:** Alembic dry-run (--sql) fails on a pre-existing migration (adf582a23467) that uses a conditional _column_exists helper requiring a live DB connection. Pre-existing limitation documented in 68-01-SUMMARY.md, not caused by Phase 68.

### 2. HMMClassifier produces meaningful state labels on real FRED data

**Test:** Run: python -m ta_lab2.scripts.macro.refresh_macro_analytics --hmm-only --verbose
**Expected:** 2-state and 3-state GaussianHMM both fit without ConvergenceWarning on the full FRED feature set; BIC winner selected; rows upserted to cmc_hmm_regimes
**Why human:** Requires live FRED data populated by Phase 65/66 (minimum 504 rows post-dropna); HMM EM convergence cannot be verified by static code inspection

### 3. Lead-lag scan completes in reasonable time

**Test:** Run: python -m ta_lab2.scripts.macro.refresh_macro_analytics --lead-lag-only
**Expected:** All FRED float features scanned against BTC and ETH across lags [-60..+60]; significant pairs logged; rows upserted to cmc_macro_lead_lag_results; runtime under 5 minutes
**Why human:** Performance depends on DB query latency and actual data volume (38 features x 2 assets x 121 lags = 9,196 correlation computations)

### 4. Transition matrix rows sum to 1.0 in the actual DB

**Test:** After running refresh_macro_analytics.py, execute:

```sql
SELECT regime_source, window_type, window_end_date, from_state, SUM(probability) AS row_sum
FROM cmc_macro_transition_probs
GROUP BY 1, 2, 3, 4
HAVING ABS(SUM(probability) - 1.0) > 0.001;
```


**Expected:** Zero rows returned (all from-state rows sum to within floating-point tolerance of 1.0)
**Why human:** Row-normalization logic verified in code but actual DB values require a running database to confirm

---
## Must-Have Checklist (15/15)

| # | Must-Have | Status | Evidence |
|---|-----------|--------|---------|
| 1 | cmc_hmm_regimes table with PK (date, n_states, model_run_date) | VERIFIED | Migration line 113: PrimaryKeyConstraint(date, n_states, model_run_date) |
| 2 | cmc_macro_lead_lag_results table with PK (macro_feature, asset_col, computed_at) | VERIFIED | Migration line 198: PrimaryKeyConstraint(macro_feature, asset_col, computed_at) |
| 3 | cmc_macro_transition_probs table with PK (regime_source, window_type, window_end_date, from_state, to_state) | VERIFIED | Migration lines 272-278: five-column PK confirmed |
| 4 | Alembic migration chains from actual current head (d5e6f7a8b9c0, Phase 67) | VERIFIED | down_revision = d5e6f7a8b9c0 confirmed; Phase 67 migration file exists at alembic/versions/d5e6f7a8b9c0_macro_regime_tables.py; e0d8f7 is the current head |
| 5 | hmmlearn>=0.3.3 installed and importable | VERIFIED | hmmlearn==0.3.3 importable in environment; declared in pyproject.toml [project.optional-dependencies.macro_analytics] |
| 6 | HMMClassifier fits 2-state and 3-state GaussianHMM, picks BIC winner, upserts to cmc_hmm_regimes | VERIFIED | _N_STATES_OPTIONS=[2,3]; BIC comparison lines 554-576; upsert_results at line 611 |
| 7 | HMM input features StandardScaler-normalized, NaN rows dropped before fit, 10 random restarts | VERIFIED | StandardScaler().fit_transform(df_clean.values) lines 470-471; dropna(how=any) line 445; _N_RESTARTS=10 |
| 8 | LeadLagAnalyzer scans all FRED float features against BTC/ETH at lags [-60,+60], Bartlett significance, upserts | VERIFIED | range(-60,61); _DEFAULT_ASSET_IDS=[1,2]; bartlett_threshold=2.0/sqrt(n_obs) line 384; upsert_results at line 451 |
| 9 | Both modules importable from ta_lab2.macro and follow existing upsert patterns | VERIFIED | __init__.py imports and __all__ include both; temp table + ON CONFLICT confirmed in both modules |
| 10 | TransitionProbMatrix computes static and rolling matrices from both rule-based and HMM sources | VERIFIED | compute_static and compute_rolling for both rule_based and hmm via _load_labels dispatcher at line 616 |
| 11 | Rolling window uses 252 days (1 trading year), static uses full history | VERIFIED | ROLLING_WINDOW_DAYS=252 constant; static loads all labels from _load_labels without date filtering |
| 12 | Transition matrices are row-normalized (each row sums to 1.0) | VERIFIED | row_sums check in _compute_transition_matrix and _build_count_matrix: if row_sums[state] > 0 then divide else 0.0 |
| 13 | get_transition_prob wrapper makes any regime-to-regime probability trivially queryable | VERIFIED | Module-level function at line 632; scoped MAX subquery for window_end_date=None case; returns float or None |
| 14 | refresh_macro_analytics.py CLI runs all three Phase 68 tools with shared flags | VERIFIED | 313 lines; orchestrates HMM -> LeadLag -> Transition with per-tool flags and independent try/except |
| 15 | run_daily_refresh.py --all includes macro-analytics stage after macro-regimes and before per-asset regimes | VERIFIED | Pipeline block lines 2499-2510; TIMEOUT_MACRO_ANALYTICS=900s; correct ordering confirmed |

---

## Gaps Summary

No gaps found. All 15 must-haves are verified. Phase goal is achieved structurally.

Four human verification items are flagged for runtime confirmation (live database required), but these are behavioral confirmations of code that has been verified structurally -- not missing implementations.

---

_Verified: 2026-03-03T11:27:27Z_
_Verifier: Claude (gsd-verifier)_
