---
phase: 38-feature-experimentation
plan: "05"
subsystem: testing
tags: [pytest, experiments, bh-gate, feature-registry, dag, unit-tests]

# Dependency graph
requires:
  - phase: 38-02
    provides: FeatureRegistry (YAML loading, param expansion, validation, digest)
  - phase: 38-02
    provides: resolve_experiment_dag (topological sort, cycle detection)
  - phase: 38-03
    provides: ExperimentRunner._compute_feature (inline eval, dotpath dispatch)
  - phase: 38-04
    provides: FeaturePromoter.check_bh_gate (BH correction, NaN handling, min_pass_rate)
  - phase: 38-04
    provides: PromotionRejectedError (reason attribute, bh_results attribute)
provides:
  - 39 unit tests for the full Phase 38 experiments subpackage
  - No-DB test coverage of FeatureRegistry, DAG, BH gate, compute dispatch, CLI --help
  - Structural E2E verification of Alembic migration chain + all imports
affects:
  - Future phases using ta_lab2.experiments (regression guard)
  - Phase 38 completion (this is the final plan)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mock-based testing: ExperimentRunner and FeaturePromoter tested with MagicMock engine (no DB)"
    - "tmp_path YAML fixtures: FeatureRegistry tests write minimal YAML to tmp_path for isolation"
    - "pytest.raises for exception verification with match= patterns"
    - "subprocess.run for CLI --help integration tests without spawning live DB"

key-files:
  created:
    - tests/test_experiments.py
  modified: []

key-decisions:
  - "Duplicate detection test uses base-name + expanded variant collision (rsi_sweep_period5 + explicit rsi_sweep_period5), not same base name twice"
  - "dotpath test patches importlib.import_module to return a MagicMock module -- no real module import needed"
  - "BH gate min_pass_rate test uses [0.0001, 0.4, 0.5] -- only 1/3 pass BH at alpha=0.05"

patterns-established:
  - "Inline expression test pattern: build DataFrame with relevant columns, construct spec dict, call _compute_feature directly"
  - "BH gate test pattern: build ic_results_df with ic_p_value column, instantiate promoter with mock engine, call check_bh_gate"

# Metrics
duration: 4min
completed: 2026-02-24
---

# Phase 38 Plan 05: Unit Tests and E2E Verification Summary

**39 pytest unit tests covering FeatureRegistry YAML loading/expansion/validation, DAG topological sort, BH gate noise/signal/NaN handling, ExperimentRunner inline/dotpath dispatch, PromotionRejectedError attributes, and all 3 CLI --help endpoints -- all passing without DB connection**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-24T12:35:08Z
- **Completed:** 2026-02-24T12:39:35Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- 39 unit tests written and passing, covering all critical paths in the Phase 38 experiments subpackage
- All tests run without a live database connection (mocked engine via MagicMock)
- E2E structural verification confirmed: Alembic chain intact (c3b718c2d088 -> 6f82e9117c58), registry loads features.yaml (5 experimental features including 3 expanded variants), all 3 CLI scripts accept --help with exit 0

## Task Commits

Each task was committed atomically:

1. **Task 1: Write unit tests for feature experimentation framework** - `15be065b` (test)
2. **Task 2: End-to-end CLI verification** - no code changes needed; all verification commands passed

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `tests/test_experiments.py` - 39 unit tests organized in 6 test classes: TestFeatureRegistryLoad (10 tests), TestResolveExperimentDag (5 tests), TestBhGate (6 tests), TestComputeFeature (4 tests), TestPromotionRejectedError (5 tests), TestCliHelp (3 tests), TestFeatureRegistryEdgeCases (6 tests)

## Decisions Made

- Duplicate detection test requires a specific YAML pattern: a sweep feature (e.g., `rsi_sweep` with `params.period=[5]`) that expands to `rsi_sweep_period5`, combined with an explicitly-defined feature named `rsi_sweep_period5`. Simply naming two features the same doesn't work because YAML keys must be unique -- the collision must arise from expansion.
- Dotpath compute dispatch test patches `importlib.import_module` at the import site (`ta_lab2.experiments.runner`) to return a MagicMock with the expected function, avoiding any real module dependency.
- BH min_pass_rate=0.5 test with p-values `[0.0001, 0.4, 0.5]`: scipy's `false_discovery_control` adjusts the 0.0001 p-value upward but it remains below 0.05, while the other two do not pass. This gives exactly 1/3 pass rate, below the 0.5 threshold.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_duplicate_names_raise YAML construction**

- **Found during:** Task 1 (initial test run)
- **Issue:** The original YAML tried to use `dup_feature_period5` as a base name with `params.period=[5]`, which expands to `dup_feature_period5_period5` -- no collision with the explicit `dup_feature` entry. Test did not raise.
- **Fix:** Changed YAML to use `rsi_sweep` (with `params.period=[5]`, expanding to `rsi_sweep_period5`) alongside an explicit `rsi_sweep_period5` entry -- this triggers the duplicate detection in `FeatureRegistry.load()`.
- **Files modified:** tests/test_experiments.py
- **Verification:** Test passes after fix (`pytest tests/test_experiments.py::TestFeatureRegistryLoad::test_duplicate_names_raise` green)
- **Committed in:** 15be065b (Task 1 commit, after pre-commit re-stage)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test YAML construction)
**Impact on plan:** Minor fix to test YAML; no production code changes. All 39 tests pass.

## Issues Encountered

- Pre-commit hooks (ruff lint/format + mixed line endings) modified the file after the first `git add`. Required re-staging and re-committing. This is standard workflow behavior -- no impact on correctness.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 38 (Feature Experimentation Framework) is now complete:
- Plan 38-01: Alembic migration (dim_feature_registry + cmc_feature_experiments)
- Plan 38-02: FeatureRegistry + resolve_experiment_dag + features.yaml
- Plan 38-03: ExperimentRunner + run_experiment.py CLI
- Plan 38-04: FeaturePromoter + promote_feature.py + purge_experiment.py CLIs
- Plan 38-05: 39 unit tests, all passing

Ready for the next phase. No blockers.

---
*Phase: 38-feature-experimentation*
*Completed: 2026-02-24*
