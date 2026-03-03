---
phase: 67-macro-regime-classifier
plan: 02
subsystem: macro-regime
tags: [macro, regime-classifier, hysteresis, yaml-config, rule-based]

# Dependency graph
requires:
  - phase: 67-01
    provides: "cmc_macro_regimes + cmc_macro_hysteresis_state tables"
  - phase: 66-fred-derived-features
    provides: "fred.fred_macro_features with all FRED-03 through FRED-16 columns"
provides:
  - "MacroRegimeClassifier class: 4-dimension macro regime labeler with hysteresis"
  - "load_macro_regime_config(): YAML config loader for threshold profiles"
  - "configs/macro_regime_config.yaml: externalized thresholds, 3 named profiles"
affects:
  - 67-macro-regime-classifier (plan 03: CLI script + tests)
  - 68-l4-integration (macro regime labels for L4 policy resolver)
  - 71-risk-gates (macro_state for position sizing)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "All numeric thresholds externalized in YAML (MREG-08 compliance)"
    - "Named profiles (default/conservative/aggressive) for sensitivity tuning"
    - "Per-dimension hysteresis with DB persistence for incremental resume"
    - "Tighten-immediately / hold-on-loosening semantics per macro dimension"
    - "Adverse/cautious checked first in bucketing for conservative bias"

key-files:
  created:
    - "src/ta_lab2/macro/regime_classifier.py"
    - "configs/macro_regime_config.yaml"
  modified:
    - "src/ta_lab2/macro/__init__.py"

key-decisions:
  - "Per-dimension hysteresis (not composite-level) -- each dimension tracks independently"
  - "Tighten labels per dimension: RiskOff, Unwind/Stress, Hiking, Contracting variants"
  - "Macro state bucketing checks adverse/cautious FIRST for conservative bias"
  - "Prefix matching for macro_state_rules -- carry dimension is 4th and optional in rules"
  - "Config version hash (MD5 truncated to 8 chars) stored as regime_version_hash for provenance"
  - "60-day warmup window for incremental classification (vs 400 for feature computation)"

patterns-established:
  - "YAML config pattern: active_profile selector, profiles dict, hysteresis params"
  - "Dimension labeler pattern: _label_{dim}(row, thresholds) -> str | None"
  - "Macro tightening: transitioning TO a tighten_label is tightening (bypasses hold)"

# Metrics
duration: 5min
completed: 2026-03-03
---

# Phase 67 Plan 02: Macro Regime Classifier Core Summary

**Rule-based 4-dimension MacroRegimeClassifier with YAML-externalized thresholds, per-dimension hysteresis with DB persistence, composite key composition, and macro state bucketing into 5 graduated states**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-03T10:20:46Z
- **Completed:** 2026-03-03T10:25:20Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created YAML config with 3 named profiles (default/conservative/aggressive), all thresholds externalized (MREG-08)
- Built MacroRegimeClassifier with 4 dimension labelers: monetary_policy (Hiking/Holding/Cutting), liquidity (5 levels), risk_appetite (RiskOff/Neutral/RiskOn), carry (Unwind/Stress/Stable)
- Integrated HysteresisTracker with DB persistence (cmc_macro_hysteresis_state load/save) for incremental resume
- Composite key follows fixed order monetary-liquidity-risk-carry; bucketed macro_state maps to favorable/constructive/neutral/cautious/adverse
- Updated macro package exports with MacroRegimeClassifier and load_macro_regime_config

## Task Commits

Each task was committed atomically:

1. **Task 1: Create YAML config with named profiles and bucketing rules** - `d1fa83ab` (feat)
2. **Task 2: Build MacroRegimeClassifier module with full classify pipeline** - `deeb503e` (feat)

**Plan metadata:** (pending below)

## Files Created/Modified
- `configs/macro_regime_config.yaml` - All thresholds, 3 profiles, hysteresis params, tighten_labels, macro_state_rules with _default fallback
- `src/ta_lab2/macro/regime_classifier.py` - MacroRegimeClassifier class with dimension labelers, HysteresisTracker integration, DB persistence, composite key, macro state bucketing, upsert path
- `src/ta_lab2/macro/__init__.py` - Updated exports: MacroRegimeClassifier, load_macro_regime_config

## Decisions Made
- **Per-dimension hysteresis:** Each of the 4 dimensions has its own HysteresisTracker layer, enabling independent hold periods. This prevents one noisy dimension from blocking transitions in stable dimensions.
- **Tighten-immediately semantics:** Transitioning TO a risk-reducing label (e.g., Neutral -> RiskOff) bypasses the min_bars_hold. Transitioning FROM a risk-reducing label (e.g., RiskOff -> Neutral) requires the full hold period.
- **Prefix matching for bucketing:** Macro state rules specify 3-dimension prefixes (monetary-liquidity-risk). The 4th dimension (carry) is handled by the overall key but does not affect the bucketing lookup. This keeps the YAML rules manageable while still recording carry in the composite key.
- **Adverse/cautious checked first:** Bucketing priority order is adverse -> cautious -> favorable -> constructive -> neutral. This conservative bias ensures that ambiguous conditions default toward caution.
- **60-day warmup:** Shorter than the 400-day feature warmup because the classifier only needs enough history for the hysteresis hold period and a reasonable context window.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Ruff formatter modified regime_classifier.py on first commit attempt (pre-commit hook). Re-staged and committed successfully on second attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- MacroRegimeClassifier ready for Plan 03 (CLI script + integration tests)
- YAML config in place for threshold tuning
- Hysteresis state persistence ready for incremental runs
- No blockers

---
*Phase: 67-macro-regime-classifier*
*Completed: 2026-03-03*
