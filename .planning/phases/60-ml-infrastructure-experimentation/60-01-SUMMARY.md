---
phase: 60-ml-infrastructure-experimentation
plan: 01
subsystem: ml
tags: [expression-engine, qlib, factor-definitions, yaml-registry, operator-registry, pandas]

# Dependency graph
requires:
  - phase: 55-feature-signal-evaluation
    provides: Feature experimentation framework (FeatureRegistry, features.yaml, ExperimentRunner)
  - phase: 38-feature-experimentation
    provides: Original YAML registry pattern and FeatureRegistry class
provides:
  - OPERATOR_REGISTRY with 16 Qlib-style operators (EMA, Ref, Delta, Mean, Std, WMA, Max, Min, Rank, Abs, Sign, Log, Corr, Slope, Skew, Kurt)
  - evaluate_expression(): evaluates $col-syntax expressions against DataFrame with restricted eval sandbox
  - validate_expression(): AST-based syntax validation + column allowlist checking
  - 5 expression-mode factor definitions in features.yaml (macd_signal, momentum_5d, vol_ratio_expr, mean_reversion_z, price_rank)
  - FeatureRegistry extended to accept 'expression' compute mode without ValueError
affects:
  - 60-02 through 60-06: subsequent ML infrastructure plans that build on expression engine
  - ExperimentRunner: can be extended to dispatch on compute.mode == 'expression'

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "$col syntax: $close -> _df_['close'] substitution via re.sub before eval()"
    - "Restricted eval sandbox: __builtins__={}, only np/pd/OPERATOR_REGISTRY exposed"
    - "expression compute mode: new YAML mode alongside inline and dotpath"
    - "OPERATOR_REGISTRY: dict of name->callable for operator extensibility"

key-files:
  created:
    - src/ta_lab2/ml/__init__.py
    - src/ta_lab2/ml/expression_engine.py
  modified:
    - configs/experiments/features.yaml
    - src/ta_lab2/experiments/registry.py

key-decisions:
  - "Used restricted eval sandbox (__builtins__={}) rather than AST interpreter for security + performance"
  - "Slope uses np.dot linear regression over rolling window (no scipy dependency)"
  - "WMA uses rolling().apply with raw=True for performance vs pure pandas"
  - "expression mode validated via $col->_placeholder_ substitution + ast.parse at load time"
  - "Updated FeatureRegistry._validate_compute_spec to accept 'expression' mode (blocking fix)"

patterns-established:
  - "expression mode: YAML compute.mode: expression with $col syntax, evaluated by expression_engine.py"
  - "OPERATOR_REGISTRY extensibility: add operators by inserting into dict, no class changes needed"

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 60 Plan 01: ML Package and Expression Engine Summary

**Qlib-style $col expression engine with 16 operators and 5 expression-mode factors in features.yaml, no Python changes per experiment**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-28T14:29:08Z
- **Completed:** 2026-02-28T14:32:05Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created `src/ta_lab2/ml/` package with expression engine implementing OPERATOR_REGISTRY (16 operators) and `evaluate_expression()` / `validate_expression()` functions
- Added 5 expression-mode factor definitions to `configs/experiments/features.yaml` using `$col` syntax (expands to 8 after param sweep on vol_ratio_expr)
- Extended `FeatureRegistry._validate_compute_spec` to accept `mode: expression` (blocking fix -- without it the YAML entries would raise ValueError on registry.load())

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ml package and expression engine module** - `bf7ab62e` (feat)
2. **Task 2: Add expression-mode factors to YAML registry** - `1bd37b54` (feat)

## Files Created/Modified
- `src/ta_lab2/ml/__init__.py` - ML package init (docstring only)
- `src/ta_lab2/ml/expression_engine.py` - OPERATOR_REGISTRY (16 operators), evaluate_expression(), validate_expression()
- `configs/experiments/features.yaml` - 5 new expression-mode factor definitions appended under Phase 60 comment header
- `src/ta_lab2/experiments/registry.py` - _validate_compute_spec extended to handle mode: expression

## Decisions Made
- **Restricted eval sandbox:** Used `__builtins__: {}` rather than an AST interpreter. Safer than full builtins, simpler than full AST evaluation, and sufficient since only OPERATOR_REGISTRY + np/pd are exposed.
- **Slope via np.dot:** Linear regression slope computed with explicit vectorized np.dot formula to avoid scipy dependency.
- **WMA via rolling().apply with raw=True:** Faster than manual iteration; raw=True passes numpy array to the apply function.
- **val_ratio_expr params:** Used `params: fast: [5, 10], slow: [20, 30]` to demonstrate param sweep expansion (produces 4 variants in registry).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Extended FeatureRegistry to accept 'expression' compute mode**
- **Found during:** Task 2 (before writing YAML entries)
- **Issue:** `FeatureRegistry._validate_compute_spec` raises `ValueError` for unknown compute modes. Without the fix, `registry.load()` would fail on the new expression-mode YAML entries with: "Unknown compute mode: 'expression'"
- **Fix:** Added `elif mode == "expression":` branch that substitutes params, replaces `$col` with `_placeholder_`, then calls `ast.parse(mode="eval")` to validate syntax at load time
- **Files modified:** `src/ta_lab2/experiments/registry.py`
- **Verification:** `FeatureRegistry('configs/experiments/features.yaml').load()` succeeds, returns 8 expression-mode features (5 base + 3 from param expansion)
- **Committed in:** `bf7ab62e` (Task 1 commit, bundled with ml package creation)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary for registry correctness. No scope creep.

## Issues Encountered
- Pre-commit hooks (ruff-format, mixed-line-ending) reformatted files on first commit attempt. Re-staged and committed successfully on second attempt. No code logic changes from reformatting.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Expression engine is ready for use by subsequent Phase 60 plans
- OPERATOR_REGISTRY is extensible: add operators by inserting into the dict
- ExperimentRunner can be extended to dispatch on `compute.mode == 'expression'` in a future plan
- FeatureRegistry now accepts all three compute modes: `inline`, `dotpath`, `expression`

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
