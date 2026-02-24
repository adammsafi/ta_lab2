---
phase: 38-feature-experimentation
plan: "02"
subsystem: experimentation
tags: [yaml, registry, graphlib, ast, importlib, itertools, hashlib, feature-experimentation]

# Dependency graph
requires:
  - phase: 38-01
    provides: "Alembic migration creating dim_feature_registry and cmc_feature_experiments tables"

provides:
  - "FeatureRegistry class: YAML loader with lifecycle validation, parameter sweep expansion, expression/dotpath validation"
  - "resolve_experiment_dag function: topological ordering via graphlib.TopologicalSorter"
  - "src/ta_lab2/experiments/ subpackage with __init__.py, registry.py, dag.py"
  - "configs/experiments/features.yaml: sample registry with 3 features (5 total after sweep expansion)"

affects:
  - 38-03  # ExperimentRunner consumes FeatureRegistry
  - 38-04  # FeaturePromoter consumes FeatureRegistry
  - 38-05  # CLI scripts use FeatureRegistry

# Tech tracking
tech-stack:
  added: []  # No new installs -- all stdlib + PyYAML already present
  patterns:
    - "YAML feature registry with lifecycle states (experimental/promoted/deprecated)"
    - "Parameter sweep expansion via itertools.product with named variant convention {base}_{key}{val}"
    - "Dual compute mode: inline (ast.parse validation) vs dotpath (importlib validation)"
    - "SHA-256 yaml_digest on spec JSON for change detection across runs"
    - "graphlib.TopologicalSorter for DAG resolution with automatic CycleError"

key-files:
  created:
    - src/ta_lab2/experiments/__init__.py
    - src/ta_lab2/experiments/registry.py
    - src/ta_lab2/experiments/dag.py
    - configs/experiments/features.yaml
  modified: []

key-decisions:
  - "UTF-8 encoding enforced on YAML open (Windows pitfall with cp1252 default)"
  - "eval globals inject np+pd but restrict __builtins__ to {}: np.log(close) works, os.system() cannot"
  - "Dotpath validation at load time raises ValueError on missing module/function -- fail fast"
  - "External depends_on references (promoted/outside registry) silently filtered in DAG -- no error"
  - "validate_compute_spec validates one representative param combo for sweep entries, not all combos"
  - "yaml_digest computed on variant spec (post-expansion) so each variant has its own digest"

patterns-established:
  - "FeatureRegistry pattern: load() validates + expands YAML; get_feature() retrieves by expanded name"
  - "Sweep naming: {base_name}_{key1}{val1}_{key2}{val2} -- predictable, inspectable"
  - "Lifecycle gate: ValueError on invalid state at load time, not at run time"

# Metrics
duration: 3min
completed: 2026-02-24
---

# Phase 38 Plan 02: YAML Feature Registry and DAG Resolver Summary

**YAML-driven FeatureRegistry with lifecycle validation, itertools.product sweep expansion, ast.parse expression validation, and graphlib.TopologicalSorter DAG resolution -- the core data model consumed by ExperimentRunner and FeaturePromoter**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-24T12:18:44Z
- **Completed:** 2026-02-24T12:21:30Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Created `src/ta_lab2/experiments/` subpackage with FeatureRegistry, DAG resolver, and clean __init__ exports
- FeatureRegistry validates lifecycle states, expands parameter sweeps, validates inline expressions (ast.parse) and dotpath functions (importlib), computes yaml_digest via hashlib.sha256
- resolve_experiment_dag wraps graphlib.TopologicalSorter; raises CycleError on circular deps; silently filters external dependencies
- Created `configs/experiments/features.yaml` with 3 entries producing 5 experimental features (including 1 param sweep over period=[5,14,21])
- All verification checks pass: imports, sweep expansion, DAG ordering, duplicate detection, invalid lifecycle rejection, cycle detection

## Task Commits

Each task was committed atomically:

1. **Task 1: Create experiments subpackage with FeatureRegistry and DAG resolver** - `c887ad9e` (feat)
2. **Task 2: Create sample features.yaml with experimental feature definitions** - `2a18b847` (feat)

## Files Created/Modified

- `src/ta_lab2/experiments/__init__.py` - Package init exporting FeatureRegistry and resolve_experiment_dag
- `src/ta_lab2/experiments/registry.py` - FeatureRegistry class (load, get_feature, list_experimental, list_all, validate_expression, validate_dotpath, _expand_params, _digest)
- `src/ta_lab2/experiments/dag.py` - resolve_experiment_dag using graphlib.TopologicalSorter
- `configs/experiments/features.yaml` - Sample registry: vol_ratio_30_7, rsi_momentum, ret_vol_ratio (sweep x3)

## Decisions Made

- **eval globals scope**: Inject `{"np": numpy, "pd": pandas, "__builtins__": {}}` as documented in research open question 3 -- allows `np.log(close)` in inline expressions while blocking `os.system()`
- **Sweep validation**: Validate one representative combo during load() rather than all combos -- catches syntax errors without O(N) validation cost
- **External deps silently filtered**: `depends_on` references to features not in the registry (e.g., promoted features) are filtered out rather than raising -- allows gradual promotion without breaking existing YAML entries
- **yaml_digest on variant spec**: Each expanded variant gets its own digest (post-substitution) so digest changes when either the base spec or resolved params change

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hooks (ruff + mixed-line-ending) modified files on first commit attempt due to Windows CRLF. Re-staged and committed after hooks applied fixes. This is standard Windows git behavior, not a code issue.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `src/ta_lab2/experiments/` subpackage is ready for ExperimentRunner (Plan 03) to consume
- FeatureRegistry.load() + list_experimental() + get_feature() are the primary API surface
- resolve_experiment_dag() provides computation ordering for Plan 03's feature compute loop
- The sample features.yaml serves as the test fixture for Plan 03 integration tests
- No blockers for Plan 03

---
*Phase: 38-feature-experimentation*
*Completed: 2026-02-24*
