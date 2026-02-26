---
phase: 55-feature-signal-evaluation
plan: "02"
subsystem: experiments
tags: [yaml, feature-registry, ama, kama, dema, tema, hma, rsi, ic, evaluation]

# Dependency graph
requires:
  - phase: 55-01
    provides: FeatureRegistry class, ExperimentRunner, features.yaml scaffold, cmc_feature_experiments table
  - phase: 27
    provides: cmc_ama_multi_tf_u with indicator/params_hash/ama/d1/er columns
  - phase: 44
    provides: cmc_features with 112 bar-level feature columns (returns, vol, TA)
provides:
  - Expanded features.yaml with 91 experimental features (up from 7)
  - 53 canonical cmc_features entries covering returns, vol, and TA columns
  - 31 AMA variant entries for KAMA (3), DEMA (5), TEMA (5), HMA (5) -- all params verified
  - 1 adaptive RSI normalized feature (inline percentile expression)
  - Public features property on FeatureRegistry for clean validation API
  - Documented EMA crossover skip with architectural rationale
affects:
  - 55-03 (IC scoring sweep will read all 91 features from this registry)
  - 55-04 (ExperimentRunner enhancement for EMA crossovers deferred here)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Feature registry naming: ama_{indicator}_{label_slug}_{column} for AMA variants"
    - "Feature registry naming: canonical_{column} for cmc_features pass-through features"
    - "AMA filters: always specify both indicator AND params_hash to disambiguate period-identical hashes"

key-files:
  created: []
  modified:
    - configs/experiments/features.yaml
    - src/ta_lab2/experiments/registry.py

key-decisions:
  - "EMA crossovers skipped: Runner.dotpath calls fn(input_df) with no kwargs/conn; two cmc_ema_multi_tf_u inputs produce 'ema' column collision on merge. Deferred to 55-04 (ExperimentRunner enhancement)."
  - "KAMA hash bug fixed: original kama_er_signal and ama_ret_momentum used d47fe5cc (DEMA/TEMA/HMA period=21 MD5) instead of KAMA(10,2,30) canonical hash de1106d5."
  - "AMA indicator filter: cmc_ama_multi_tf_u rows must be filtered by BOTH indicator name AND params_hash because period-9 DEMA/TEMA/HMA all share hash 514ffe35."
  - "Outlier flag columns excluded from canonical features: boolean flags (ret_is_outlier, vol_*_is_outlier, ta_is_outlier) are quality metadata not IC-scorable features."
  - "DEMA(10) excluded: Only 9/21/50/200 included as canonical periods (10 is redundant with 9 for most TF contexts)."

patterns-established:
  - "canonical_ prefix distinguishes direct cmc_features pass-through features from engineered variants"
  - "ama_ prefix + indicator + period + column pattern for AMA variant naming"
  - "All AMA entries specify indicator (lowercase: kama/dema/tema/hma) + full 8-char params_hash prefix"

# Metrics
duration: 25min
completed: 2026-02-26
---

# Phase 55 Plan 02: Feature Registry Expansion Summary

**91-feature YAML registry: 53 canonical cmc_features columns, 31 AMA variants (KAMA/DEMA/TEMA/HMA), 1 adaptive RSI, with KAMA hash bug fixed and EMA crossovers architecturally deferred**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-02-26T14:45:00Z
- **Completed:** 2026-02-26T15:10:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Expanded features.yaml from 7 to 91 experimental feature entries (all passing FeatureRegistry.load())
- Fixed critical KAMA params_hash bug in two original entries (d47fe5cc was DEMA/TEMA/HMA period-21 hash; corrected to de1106d5 for KAMA(10,2,30))
- Added public `features` property to FeatureRegistry for clean validation access
- Verified all 18 AMA params_hash values against ama_params.py (9 unique hashes, 9 duplicates due to shared period-only dicts)
- Documented EMA crossover architectural limitation with concrete deferred path

## Task Commits

Each task was committed atomically:

1. **Task 1: Inspect schemas and derive feature entries** - `78adff2e` (feat)
   - Added public `features` property to FeatureRegistry
   - Confirmed EMA column name as `ema` from DDL
   - Verified all AMA params_hash values; found KAMA hash bug
   - Confirmed EMA crossover collision + dotpath kwargs limitation

2. **Task 2: Write expanded features.yaml and validate** - `737f8bf0` (feat)
   - Wrote 91-feature YAML covering canonical, AMA, adaptive RSI
   - Fixed KAMA hash bug in kama_er_signal and ama_ret_momentum
   - Documented EMA crossover skip with architectural rationale
   - Validated via FeatureRegistry.load() -- 91 features, 0 ValueError

## Files Created/Modified
- `configs/experiments/features.yaml` - Expanded from 5 base entries (7 after sweep expansion) to 91 entries across 4 categories
- `src/ta_lab2/experiments/registry.py` - Added `features` public property (read-only view of `_features`)

## Decisions Made

1. **EMA crossovers skipped** (not dotpath): ExperimentRunner's `_compute_feature` for dotpath calls `fn(input_df)` with no kwargs and no DB connection. Two `cmc_ema_multi_tf_u` inputs with different period filters both produce an `ema` column that collides on inner join. Resolution deferred to 55-04 (ExperimentRunner enhancement to support column renaming or multi-query dotpath).

2. **DEMA(10) excluded**: Only periods 9/21/50/200 for DEMA/TEMA/HMA to avoid redundancy with period-9 entries and keep total under 150.

3. **Outlier flags excluded**: Boolean columns (ret_is_outlier, vol_*_is_outlier, ta_is_outlier) are data quality metadata, not IC-scorable predictive features.

4. **AMA filter requires both indicator AND params_hash**: Period-only AMAs (DEMA/TEMA/HMA) share identical MD5 hashes when period is the same (e.g., period=9 gives `514ffe35` for all three). Filter `indicator: dema` plus `params_hash: 514ffe35` is unambiguous.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed KAMA params_hash in two original features**
- **Found during:** Task 1 (schema inspection and AMA params verification)
- **Issue:** Both `kama_er_signal` and `ama_ret_momentum` used `d47fe5cc` which is the MD5 for `{"period": 21}` (shared by DEMA(21)/TEMA(21)/HMA(21)), not KAMA(10,2,30). KAMA canonical hash is `de1106d5`.
- **Fix:** Corrected params_hash to `de1106d5` in both entries; added comments explaining the fix
- **Files modified:** configs/experiments/features.yaml
- **Verification:** `python -c "from ta_lab2.features.ama.ama_params import KAMA_CANONICAL; print(KAMA_CANONICAL.params_hash[:8])"` prints `de1106d5`
- **Committed in:** `737f8bf0` (Task 2 commit)

**2. [Rule 2 - Missing Critical] Added public `features` property to FeatureRegistry**
- **Found during:** Task 2 (validation command `r.features.keys()` fails without it)
- **Issue:** Plan's verification command `r.features.keys()` assumed a public property but FeatureRegistry only exposes `r._features` (private)
- **Fix:** Added `@property def features(self) -> dict[str, dict[str, Any]]` as read-only view of `_features`
- **Files modified:** src/ta_lab2/experiments/registry.py
- **Verification:** `r.features.keys()` works; `r.list_all()` still works (backward compat)
- **Committed in:** `78adff2e` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 bug fix, 1 missing critical)
**Impact on plan:** Both essential for correctness (wrong KAMA data would silently load wrong indicators) and plan validation (missing property would fail verification commands). No scope creep.

## Issues Encountered

- **Dry-run requires live DB**: `run_experiment --dry-run` still connects to DB for tf_days_nominal lookup and cmc_price_bars_multi_tf_u close query. The local test environment has a password auth failure. Pure registry validation (`FeatureRegistry.load()`) is the correct dry-run proxy and passes cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **features.yaml complete**: 91 experimental features ready for IC scoring sweep in Plan 03
- **EVAL-02 prerequisite satisfied**: AMA variants defined with correct params_hash values
- **EMA crossovers deferred**: Plan 04 should extend ExperimentRunner to support column renaming on multi-source merge (or add a multi-period EMA join helper)
- **No blockers** for Plan 03 (IC sweep)

---
*Phase: 55-feature-signal-evaluation*
*Completed: 2026-02-26*
