---
phase: 68-hmm-macro-analytics
plan: 02
subsystem: macro-analytics
tags: [hmm, hmmlearn, GaussianHMM, BIC, lead-lag, comovement, macro, sklearn, StandardScaler]

# Dependency graph
requires:
  - phase: 68-01-hmm-macro-analytics-foundation
    provides: cmc_hmm_regimes and cmc_macro_lead_lag_results tables; hmmlearn installed
  - phase: 66-fred-derived-features
    provides: fred.fred_macro_features with all 38 float feature columns
  - phase: 65-fred-pipeline
    provides: fred.fred_macro_features base + Phase 65 raw/derived columns
provides:
  - HMMClassifier class with fit_and_predict(), upsert_results(), compare_with_rule_based()
  - LeadLagAnalyzer class with scan_all(), upsert_results()
  - Updated ta_lab2.macro public API including both classes
affects:
  - 68-03 (transition probability writer depends on HMM state labels from cmc_hmm_regimes)
  - 69+ (HMM confirmation signal and lead-lag results available for downstream consumers)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GaussianHMM with covariance_type='diag' (safe default for 38 features): avoids O(n^2) parameter instability; 'full' is opt-in"
    - "10 random EM restarts to escape local optima -- BIC winner selected across all restarts"
    - "Expanding window: all history up to end_date used for fitting (no look-ahead)"
    - "Weekly refit cadence (_REFIT_INTERVAL_DAYS=7) -- prevents unnecessary daily refits"
    - "Bartlett significance threshold 2/sqrt(N): per-pair ~95% CI for cross-correlation"
    - "tz-aware/tz-naive normalization: macro DATE + returns TIMESTAMP WITH TZ both normalized to date-level before join"
    - "type: ignore[call-overload] for lead_lag_max_corr Dict[str, object] return type casts"

key-files:
  created:
    - "src/ta_lab2/macro/hmm_classifier.py -- HMMClassifier (802 lines)"
    - "src/ta_lab2/macro/lead_lag_analyzer.py -- LeadLagAnalyzer (523 lines)"
  modified:
    - "src/ta_lab2/macro/__init__.py -- Added HMMClassifier and LeadLagAnalyzer to public API"

key-decisions:
  - "Default covariance_type='diag': with 38 input features, 'full' covariance requires O(n^2) parameter estimation per state which is often numerically unstable. 'diag' is the safe default; 'full' requires explicit opt-in."
  - "Shared helpers (_to_python, _sanitize_dataframe, _get_table_columns) defined in hmm_classifier.py and imported by lead_lag_analyzer.py to avoid duplication"
  - "HMM state indices (0,1,2) have NO inherent semantic meaning -- state 0 is not 'favorable'. Regime association requires inspecting state_means_json post-fit."
  - "compare_with_rule_based uses Cohen's kappa for structural agreement -- HMM integer states vs rule-based string labels; sklearn handles mixed types correctly"
  - "LeadLagAnalyzer imports lead_lag_max_corr from ta_lab2.regimes.comovement -- no reimplementation"
  - "F401 noqa on _to_python import in lead_lag_analyzer.py: re-exported at package level for use by other modules without needing to import from hmm_classifier directly"

patterns-established:
  - "HMM on FRED features: always StandardScaler first; never fit on raw features"
  - "BIC comparison: lower BIC = better model; is_bic_winner flag stored in DB for fast filtered queries"
  - "corr_by_lag stored as JSON TEXT (not JSONB): portable across DB versions, parseable in Python"
  - "Asset return alignment: normalize both macro DATE and returns TIMESTAMP WITH TZ to tz-naive date-level before pd.DataFrame.join()"

# Metrics
duration: 7min
completed: 2026-03-03
---

# Phase 68 Plan 02: HMM Classifier + Lead-Lag Analyzer Summary

**GaussianHMM classifier (2-state/3-state, BIC selection, 10 restarts, expanding window) and macro-crypto lead-lag scanner (38 features x BTC/ETH, lags [-60..+60], Bartlett significance) -- both modules upsert to Phase 68-01 tables**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-03T11:03:23Z
- **Completed:** 2026-03-03T11:10:42Z
- **Tasks:** 2 of 2
- **Files modified:** 3

## Accomplishments

- HMMClassifier (802 lines): fits 2-state and 3-state GaussianHMM on 38 FRED float features, BIC winner selection, 10 EM restarts, StandardScaler normalization, weekly refit cadence, state_means_json for interpretability, compare_with_rule_based() via Cohen's kappa
- LeadLagAnalyzer (523 lines): scans all FRED float features vs BTC/ETH at lags [-60..+60], Bartlett significance threshold, full corr_by_lag JSON profile, ret_cc auto-discovery
- Both modules follow project upsert patterns (temp table + ON CONFLICT), use _to_python()/_sanitize_dataframe() for psycopg2 safety
- ta_lab2.macro.__init__.py updated with both classes in public API and __all__

## Task Commits

Each task was committed atomically:

1. **Task 1: Build HMMClassifier module** - `a8fc680d` (feat)
2. **Task 2: Build LeadLagAnalyzer module and update __init__.py** - `a690e076` (feat)

## Files Created/Modified

- `src/ta_lab2/macro/hmm_classifier.py` -- HMMClassifier: GaussianHMM 2/3-state, BIC selection, expanding window, 10 restarts, weekly cadence, StandardScaler, state_means_json, compare_with_rule_based
- `src/ta_lab2/macro/lead_lag_analyzer.py` -- LeadLagAnalyzer: scans 38 FRED features x BTC/ETH at [-60..+60] lags, Bartlett significance, full JSON profile, upsert to cmc_macro_lead_lag_results
- `src/ta_lab2/macro/__init__.py` -- Extended public API with HMMClassifier and LeadLagAnalyzer

## Decisions Made

- **Default covariance_type="diag":** With 38 input features, "full" covariance requires O(38^2) = 1,444 parameters per state, which typically leads to numerical instability with limited training data. "diag" is safe and performant; "full" requires explicit opt-in via constructor parameter.
- **Shared helpers in hmm_classifier.py:** _to_python, _sanitize_dataframe, and _get_table_columns are defined once in hmm_classifier.py and imported by lead_lag_analyzer.py. Avoids code duplication without introducing a separate _helpers.py (YAGNI).
- **type: ignore annotations for lead_lag_max_corr:** The function's return type is `Dict[str, object]` in comovement.py. Explicit casts (`int(result["best_lag"])`) get `call-overload` mypy errors. Used targeted `# type: ignore[call-overload]` and `# type: ignore[assignment]` comments rather than weakening the comovement.py type signature (which is used by other code).
- **_HMM_CANDIDATE_COLUMNS shared via import:** LeadLagAnalyzer imports the column list from hmm_classifier to avoid duplication. If the feature set diverges between HMM and lead-lag use cases in the future, each can define its own list.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed unused variable `today_str` in fit_and_predict()**
- **Found during:** Task 1 verification (ruff check)
- **Issue:** `today_str = model_run_date.isoformat()` assigned but never used
- **Fix:** Removed the unused variable assignment
- **Files modified:** src/ta_lab2/macro/hmm_classifier.py
- **Verification:** ruff check All checks passed
- **Committed in:** a8fc680d (Task 1 commit)

**2. [Rule 1 - Bug] Fixed mypy type error in _sanitize_dataframe -- `df.where(notna(), None)`**
- **Found during:** Task 1 verification (mypy check)
- **Issue:** `df.where(df.notna(), None)` triggers mypy arg-type error -- None not in the union expected by pandas stubs
- **Fix:** Added `# type: ignore[arg-type]` comment (same pattern used in refresh_macro_features.py reference file, which has the identical pattern)
- **Files modified:** src/ta_lab2/macro/hmm_classifier.py
- **Verification:** mypy Success: no issues
- **Committed in:** a8fc680d (Task 1 commit)

**3. [Rule 1 - Bug] Fixed mypy type errors from lead_lag_max_corr Dict[str, object] return type**
- **Found during:** Task 2 verification (mypy check)
- **Issue:** lead_lag_max_corr returns `Dict[str, object]`; using `int(result["best_lag"])` triggers `call-overload` error because mypy sees `int(object)` as ambiguous
- **Fix:** Added targeted `# type: ignore[call-overload]` and `# type: ignore[assignment]` comments at the 3 cast sites in lead_lag_analyzer.py
- **Files modified:** src/ta_lab2/macro/lead_lag_analyzer.py
- **Verification:** mypy Success: no issues
- **Committed in:** a690e076 (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 1 -- type/lint correctness)
**Impact on plan:** All auto-fixes were lint/type safety corrections. No scope changes, no architectural impact.

## Issues Encountered

- ruff-format reformatted both files after initial commit attempts (pre-commit hook). Required re-staging reformatted files before commit could succeed. This is normal pre-commit hook behavior, not a code issue.
- mypy `# type: ignore` comment on a Python comment line (containing the text "type: ignore") was inadvertently interpreted as a suppress directive. Fixed by rephrasing the comment to not contain that exact text.

## User Setup Required

None - no external service configuration required. Both modules require only an SQLAlchemy engine connected to the marketdata database (same as all other ta_lab2 modules).

## Next Phase Readiness

- Phase 68-03 (Transition Probability Writer): Can read HMM state labels from cmc_hmm_regimes (after first fit_and_predict() + upsert_results() run). Rule-based labels from cmc_macro_regimes (Phase 67) are already available.
- Both HMMClassifier and LeadLagAnalyzer are importable from `ta_lab2.macro` -- ready for script integration in daily refresh pipeline.
- No blockers.

---
*Phase: 68-hmm-macro-analytics*
*Completed: 2026-03-03*
