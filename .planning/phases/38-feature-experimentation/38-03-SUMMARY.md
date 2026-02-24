---
phase: 38-feature-experimentation
plan: "03"
subsystem: experimentation
tags: [experiment-runner, ic-scoring, bh-correction, scipy, tracemalloc, sqlalchemy, temp-table, cli]

# Dependency graph
requires:
  - phase: 38-01
    provides: "Alembic migration creating dim_feature_registry and cmc_feature_experiments tables"
  - phase: 38-02
    provides: "FeatureRegistry class with YAML loading, lifecycle validation, parameter sweep expansion"
  - phase: 37
    provides: "compute_ic() with Spearman IC, rolling IC, IC-IR, boundary masking"

provides:
  - "ExperimentRunner class: loads inputs from declared source tables, computes feature via inline eval or dotpath, writes to temp scratch table, scores with compute_ic(), applies BH correction across all rows, returns DataFrame with cost metadata"
  - "run_experiment.py CLI: --feature/--all-experimental, --dry-run, --yes, --compare flags, save_experiment_results() with ON CONFLICT uq_feature_experiments_key DO UPDATE"
  - "src/ta_lab2/scripts/experiments/ subpackage with __init__.py and run_experiment.py"

affects:
  - 38-04  # FeaturePromoter reads results from cmc_feature_experiments written by this runner
  - 38-05  # CLI orchestration builds on run_experiment.py patterns

# Tech tracking
tech-stack:
  added: []  # No new installs -- scipy, tracemalloc, importlib all stdlib/existing
  patterns:
    - "Single-connection pattern: ExperimentRunner opens ONE connection for all assets to keep temp table alive"
    - "Table allowlist: _ALLOWED_TABLES frozenset prevents SQL injection from crafted YAML files"
    - "BH correction applied ONCE across all (asset x horizon x return_type) rows -- not per-asset"
    - "Cost tracking: tracemalloc.start/get_traced_memory + time.perf_counter for wall_clock + peak_memory"
    - "Inline eval security: __builtins__={} restricts to np/pd only; dotpath dispatches via importlib"

key-files:
  created:
    - src/ta_lab2/experiments/runner.py
    - src/ta_lab2/scripts/experiments/__init__.py
    - src/ta_lab2/scripts/experiments/run_experiment.py
  modified:
    - src/ta_lab2/experiments/__init__.py

key-decisions:
  - "Single connection block for all assets: temp tables are session-scoped in PostgreSQL; using with engine.connect() once prevents table dropping between assets"
  - "BH correction across all rows not per-asset: more conservative (more hypotheses = stricter correction), matches plan intent for 'single run'"
  - "Table allowlist in _ALLOWED_TABLES: validates at query time not at load time -- catches YAML edits after registry.load()"
  - "_TABLES_WITHOUT_TF frozenset handles cmc_vol + cmc_ta_daily which lack tf column"
  - "save_experiment_results() uses ON CONFLICT DO UPDATE -- overwrite semantics for CLI (re-running same experiment updates results)"
  - "NaN p-values filtered before false_discovery_control: scipy raises ValueError on NaN p-values"

patterns-established:
  - "ExperimentRunner pattern: registry.get_feature() -> _load_inputs() -> _compute_feature() -> compute_ic() -> _apply_bh_correction()"
  - "CLI pattern: mutually exclusive --feature/--all-experimental; --dry-run no-write; --yes no-prompt; --compare shows delta IC"
  - "_to_python() pattern reused from Phase 37 for numpy scalar normalization before SQL binding"

# Metrics
duration: 6min
completed: 2026-02-24
---

# Phase 38 Plan 03: ExperimentRunner and CLI Summary

**ExperimentRunner with single-connection temp scratch table, scipy BH correction across all hypotheses, tracemalloc cost tracking, and run_experiment.py CLI with --dry-run/--yes/--compare flags persisting to cmc_feature_experiments**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-24T12:25:20Z
- **Completed:** 2026-02-24T12:30:43Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Created ExperimentRunner class (719 lines) with run(), _load_inputs(), _compute_feature(), _write_to_scratch(), _apply_bh_correction() methods
- Single-connection pattern keeps temp scratch table alive across all assets in a run
- BH correction via scipy.stats.false_discovery_control applied ONCE across all (asset x horizon x return_type) rows
- Cost tracking captures wall_clock_seconds, peak_memory_mb, n_rows_computed via tracemalloc + time.perf_counter
- Created run_experiment.py CLI (518 lines) with all required flags: --dry-run, --yes, --compare, --all-experimental
- save_experiment_results() uses ON CONFLICT uq_feature_experiments_key DO UPDATE for idempotent writes

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ExperimentRunner class** - `4dcd5ced` (feat)
2. **Task 2: Create run_experiment.py CLI script** - `961fcacc` (feat)

## Files Created/Modified

- `src/ta_lab2/experiments/runner.py` - ExperimentRunner class with all required methods (719 lines)
- `src/ta_lab2/scripts/experiments/__init__.py` - Empty package init
- `src/ta_lab2/scripts/experiments/run_experiment.py` - CLI script with dry-run/yes/compare flags (518 lines)
- `src/ta_lab2/experiments/__init__.py` - Updated to export ExperimentRunner

## Decisions Made

- **Single connection block**: PostgreSQL temp tables are session-scoped. Opening a new connection per asset would drop the temp table. Using one `with engine.connect() as conn:` block for all assets ensures the scratch table persists across the entire run.
- **BH correction across all rows, not per-asset**: The plan spec says "BH correction is applied across ALL rows of a single run (all assets x horizons x return_types)." This is more conservative (more hypotheses = stricter alpha adjustment), which is correct behavior for multiple testing.
- **Table allowlist at query time**: `_ALLOWED_TABLES` frozenset validates table names at `_load_inputs()` call time rather than at `registry.load()` time. This catches YAML files that were edited after initial validation.
- **NaN p-value filtering before BH**: `scipy.stats.false_discovery_control` raises `ValueError` on NaN inputs. Filter valid p-values, apply BH, restore NaN for filtered rows.
- **`save_experiment_results()` uses DO UPDATE**: Re-running an experiment updates existing results rather than silently skipping. This is the correct behavior for an analysis workflow where you want to see fresh results.
- **`__builtins__: {}` in eval globals**: Inline expression security -- allows `np.log(close)` and `pd.Series(...)` but blocks `os.system()`, `import`, and other dangerous builtins.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) modified files on first commit attempt due to Windows CRLF. Re-staged and committed after hooks applied fixes. This is standard Windows git behavior, not a code issue.
- The `experiments/__init__.py` was modified by a background process to include `FeaturePromoter` imports (Plan 04 content). Investigation found `promoter.py` already exists, so imports work. The file was restored twice but was modified again; since it works and doesn't break Plan 03, it was left as-is.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ExperimentRunner is the core compute engine for Plan 04 (FeaturePromoter will read IC results from cmc_feature_experiments)
- run_experiment.py provides the ergonomics pattern for Plan 05 orchestration CLI
- BH correction logic is already established -- Plan 04 FeaturePromoter reuses the same threshold gate pattern
- No blockers for Plan 04

---
*Phase: 38-feature-experimentation*
*Completed: 2026-02-24*
