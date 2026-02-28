---
phase: 60-ml-infrastructure-experimentation
plan: 03
subsystem: ml
tags: [expression-engine, feature-registry, experiment-runner, yaml, factor-definitions]

# Dependency graph
requires:
  - phase: 60-01
    provides: expression_engine.py with evaluate_expression/validate_expression; FeatureRegistry expression mode validation in _validate_compute_spec
  - phase: 60-02
    provides: ExperimentRunner infrastructure with _compute_feature dispatch
provides:
  - FeatureRegistry._expand_params handles mode='expression' param substitution alongside 'inline'
  - ExperimentRunner._compute_feature dispatches mode='expression' to evaluate_expression()
  - Full end-to-end: YAML expression factor -> FeatureRegistry.load() -> ExperimentRunner.run() -> IC scoring
affects: [60-04, 60-05, 60-06, any plan using expression-mode features in features.yaml]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy import pattern: expression engine imported inside elif branch, not at module top level"
    - "Expression mode param substitution: same format(**variant_params) logic as inline mode in _expand_params"

key-files:
  created: []
  modified:
    - src/ta_lab2/experiments/registry.py
    - src/ta_lab2/experiments/runner.py

key-decisions:
  - "Lazy import of evaluate_expression inside elif branch rather than top-level import - keeps runner.py dependency-free when expression mode unused"
  - "_expand_params handles both 'inline' and 'expression' with same substitution logic - expression templates use {param} placeholders like inline"
  - "expression mode uses evaluate_expression(expression, input_df) directly - no index reset needed since runner uses ts-indexed DataFrames"

patterns-established:
  - "Expression mode wiring pattern: validate at load time (registry), dispatch at compute time (runner), lazy import"

# Metrics
duration: 2min
completed: 2026-02-28
---

# Phase 60 Plan 03: Expression Engine Wiring Summary

**expression mode wired end-to-end: FeatureRegistry._expand_params substitutes params + ExperimentRunner._compute_feature dispatches to evaluate_expression()**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-28T14:39:06Z
- **Completed:** 2026-02-28T14:40:41Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `_expand_params` in registry.py now substitutes `{param}` placeholders for `mode='expression'` features, producing expanded variant specs with the resolved expression string (same logic as inline mode)
- `_compute_feature` in runner.py has a new `elif mode == 'expression':` branch that calls `evaluate_expression(expression, input_df)` via lazy import from `ta_lab2.ml.expression_engine`
- The error message in the `else` branch updated to include 'expression' alongside 'inline' and 'dotpath'
- 143 features loaded successfully from `configs/experiments/features.yaml` with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add expression mode to FeatureRegistry** - `00b50a63` (feat)
2. **Task 2: Add expression mode to ExperimentRunner** - `a86dfe44` (feat)

## Files Created/Modified
- `src/ta_lab2/experiments/registry.py` - `_expand_params` now handles `mode='expression'` with same param substitution as inline
- `src/ta_lab2/experiments/runner.py` - `_compute_feature` dispatches expression mode to `evaluate_expression()`; error message updated

## Decisions Made
- Lazy import (`from ta_lab2.ml.expression_engine import evaluate_expression` inside the elif branch) keeps runner.py import-time dependency-free when expression mode is not used.
- `_expand_params` uses the same `format(**variant_params)` substitution for expression mode as for inline mode - expression YAML templates use `{window}`, `{period}` etc. placeholders just like inline.

## Deviations from Plan

### Observation
Task 1 note said "Plan 60-01 may have already added some expression support to _validate_compute_spec. Check the current state first." This was correct: the `_validate_compute_spec` expression branch AND the updated error message were already present from 60-01. Only `_expand_params` needed the expression mode addition. This is exactly what the plan anticipated.

None - plan executed as written. The pre-existing 60-01 work was correctly identified and only the missing piece (`_expand_params` param substitution) was added.

## Issues Encountered
None - both tasks completed cleanly on first attempt. All pre-commit hooks passed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- MLINFRA-01 expression engine is now fully wired: define expressions in YAML -> load via FeatureRegistry -> compute via ExperimentRunner -> IC score
- Expression-mode factors in `configs/experiments/features.yaml` are ready to be added and evaluated
- Wave 2 complete: 60-03 wires the final connector between the expression engine (60-01) and the experiment runner (60-02/60-04)
- Ready for 60-05 (regime routing) or 60-06 (Optuna optimization) which can now use expression-mode factors

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
