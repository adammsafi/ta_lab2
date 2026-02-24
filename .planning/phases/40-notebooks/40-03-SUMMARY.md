---
phase: 40-notebooks
plan: 03
subsystem: notebooks
tags: [jupyter, experiments, feature-registry, ic, bh-correction, dag, streamlit]

# Dependency graph
requires:
  - phase: 40-01
    provides: helpers.py (get_engine, validate_asset_data, load_features, style_ic_table)
  - phase: 38
    provides: ta_lab2.experiments (FeatureRegistry, ExperimentRunner, FeaturePromoter, resolve_experiment_dag)
  - phase: 37
    provides: compute_ic() IC engine used by ExperimentRunner
provides:
  - notebooks/03_run_experiments.ipynb — Feature experimentation framework demo + dashboard launch
affects: [40-dashboard, future experiment notebooks]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tutorial notebook pattern: ~50/50 markdown/code with anchor-linked TOC"
    - "FeatureRegistry pattern: load YAML, inspect all_features dict, list_experimental()"
    - "Topological DAG visualization via pandas DataFrame with styled lifecycle column"
    - "Batch experiment loop: ordered_names from DAG, try/except per feature"
    - "IC heatmap: pivot_table (feature x horizon) with background_gradient Styler"
    - "Non-blocking dashboard launch: subprocess.Popen + proc.poll() liveness check"

key-files:
  created:
    - notebooks/03_run_experiments.ipynb
  modified: []

key-decisions:
  - "Use dry_run=True throughout notebook — no production table writes"
  - "BH gate demonstrated via FeaturePromoter.check_bh_gate() (not full promote_feature)"
  - "Batch runs ordered by resolve_experiment_dag() topological sort"
  - "IC heatmap uses arithmetic returns only for clarity (not log + arith both)"
  - "Dashboard stop cell included (separate from launch cell) to avoid orphan processes"

patterns-established:
  - "Experiment notebook pattern: registry -> DAG -> single run -> BH check -> batch -> persist query -> dashboard"

# Metrics
duration: 4min
completed: 2026-02-24
---

# Phase 40 Plan 03: Run Experiments Summary

**33-cell tutorial notebook covering the full feature experimentation workflow: YAML registry loading, topological DAG resolution, IC scoring with BH correction, batch IC heatmap, persisted results query, and non-blocking Streamlit dashboard launch.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-24T16:09:43Z
- **Completed:** 2026-02-24T16:13:59Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Created `notebooks/03_run_experiments.ipynb` with 33 cells (17 markdown, 16 code)
- Notebook covers full workflow: prerequisites, parameters, DB validation, registry inspection, DAG resolution, single experiment, BH promotion gate, batch experiments, IC heatmap, persisted results queries, Streamlit dashboard launch
- All 6 plan `must_haves.truths` satisfied: registry loads from YAML, ExperimentRunner.run() with dry_run=True, DAG visualization, dashboard subprocess launch, BH correction cells, parametrized by ASSET_ID/TF/START_DATE/END_DATE
- All 3 key_links verified: `import helpers`, `from ta_lab2.experiments import`, `FeatureRegistry(REGISTRY_PATH)`
- ta_lab2.experiments module confirmed present (registry.py, runner.py, dag.py, promoter.py)
- Pre-commit hooks passed (mixed line ending fix applied automatically)

## Commits

| Hash | Message |
|------|---------|
| 3cf08080 | feat(40-03): create run experiments notebook with registry, DAG, IC scoring, BH gate, and dashboard launch |

## Task Details

### Task 1: Create Notebook 03 — Run Experiments
- **Status:** Complete
- **Commit:** 3cf08080
- **Files created:** `notebooks/03_run_experiments.ipynb` (33 cells, 2271 lines JSON)
- **Key cells:**
  - Cell 9: `FeatureRegistry.load()` + `list_experimental()` + `list_all()`
  - Cell 14: `resolve_experiment_dag()` with dependency display
  - Cell 15: DAG table with lifecycle-colored Pandas Styler
  - Cell 18: `ExperimentRunner.run(dry_run=True)` single feature
  - Cell 22: `FeaturePromoter.check_bh_gate()` promotion check
  - Cell 24: Batch run loop in topological order with try/except
  - Cell 25: IC heatmap pivot_table with background_gradient
  - Cell 28: `cmc_feature_experiments` query
  - Cell 29: `dim_feature_registry` query
  - Cell 31: `subprocess.Popen` Streamlit launch + `proc.poll()` check
  - Cell 32: Dashboard stop cell

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

- Plan 40-03 complete. Phase 40 (Notebooks) has 3 plans: 40-01 (done), 40-02 (pending), 40-03 (done).
- No blockers for 40-02 (which covers `02_evaluate_features.ipynb`).
- ta_lab2.experiments module is stable and fully usable from notebooks.
