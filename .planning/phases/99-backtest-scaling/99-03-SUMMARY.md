---
phase: 99-backtest-scaling
plan: "03"
subsystem: backtests
tags: [bakeoff, orchestrator, mass-backtest, monte-carlo, ctf, resume, state-machine]

# Dependency graph
requires:
  - phase: 99-backtest-scaling plan 01
    provides: mass_backtest_state table schema, mc_sharpe_lo/hi/median columns on strategy_bakeoff_results
  - phase: 99-backtest-scaling plan 02
    provides: ctf_threshold signal registered, configs/mass_backtest_grids.yaml with 118 combos
  - phase: 98-ctf-feature-graduation
    provides: CTF features promoted to features table (Phase 98)

provides:
  - BakeoffOrchestrator.run() with data_loader_fn parameter for pluggable data loading
  - load_strategy_data_with_ctf() extending base loader with CTF feature columns
  - data_loader_type/data_loader_kwargs pattern for picklable parallel worker serialization
  - run_mass_backtest.py: resume-safe orchestrator wrapping BakeoffOrchestrator
  - backfill_mc_bands.py: MC Sharpe CI backfill from fold_metrics_json bootstrap

affects:
  - 99-04-PLAN: PSR/DSR analysis uses strategy_bakeoff_results populated by run_mass_backtest
  - 99-05-PLAN: Leaderboard dashboard reads mc_sharpe_lo/hi/median from strategy_bakeoff_results
  - 100 (ML): ML feature selection depends on backtest results from mass run

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "data_loader_fn parameter on BakeoffOrchestrator.run() overrides default loader in sequential mode"
    - "data_loader_type + data_loader_kwargs for picklable parallel worker descriptor (avoids partial() pickle issues)"
    - "mass_backtest_state ON CONFLICT DO UPDATE for idempotent resume state tracking"
    - "params_hash = MD5[:16] of json.dumps(params, sort_keys=True) for stable dedup key"
    - "bootstrap CI from fold-level Sharpes: rng.choice(sharpes, n_folds, replace=True).mean() x 1000"
    - "Pre-flight information_schema check before referencing new columns (migration guard)"

key-files:
  created:
    - src/ta_lab2/scripts/backtests/run_mass_backtest.py
    - src/ta_lab2/scripts/backtests/backfill_mc_bands.py
  modified:
    - src/ta_lab2/backtests/bakeoff_orchestrator.py

key-decisions:
  - "data_loader_fn used in sequential mode (workers=1); data_loader_type/kwargs used in parallel mode to avoid pickle failures"
  - "BakeoffAssetTask.data_loader_type='ctf' reconstructs load_strategy_data_with_ctf() inside worker process"
  - "mass_backtest_state tracks at (strategy, asset, params_hash) level; cost_bps=0.0 sentinel for 'all costs'"
  - "Pre-flight check in backfill_mc_bands.py raises RuntimeError with migration guidance if columns absent"
  - "load_strategy_data_with_ctf() validates columns via information_schema before SQL to avoid KeyError on absent CTF columns"

patterns-established:
  - "CTF data loader pattern: partial(load_strategy_data_with_ctf, ctf_cols=ctf_cols) + type descriptor for parallel"
  - "Bootstrap CI pattern: rng.choice(arr, n, replace=True).mean() x N_SAMPLES, percentile(5, 95), median"
  - "Resume-safe mass orchestration: load completed keys at startup, skip in loop, mark done/error after each run"

# Metrics
duration: 13min
completed: 2026-03-31
---

# Phase 99 Plan 03: Orchestrator Extensions and Mass Backtest Scripts Summary

**BakeoffOrchestrator extended with data_loader_fn parameter; run_mass_backtest.py with resume-safe state tracking; backfill_mc_bands.py bootstrapping fold-level Sharpe CIs from fold_metrics_json**

## Performance

- **Duration:** 13 min
- **Started:** 2026-03-31T20:42:44Z
- **Completed:** 2026-03-31T20:56:05Z
- **Tasks:** 3/3
- **Files modified:** 3 (1 modified, 2 created)

## Accomplishments

- Extended `BakeoffOrchestrator.run()` with `data_loader_fn` (sequential), `data_loader_type`, and `data_loader_kwargs` (parallel workers) parameters; CTF strategies pass `load_strategy_data_with_ctf()` via these
- Added `load_strategy_data_with_ctf()` to `bakeoff_orchestrator.py`: validates CTF column existence via `information_schema`, loads them from `features` table, left-joins onto base DataFrame
- Created `run_mass_backtest.py`: loads 118-combo YAML grids, resume from `mass_backtest_state`, auto-detects AMA/CTF loader by strategy type, `--dry-run` shows CTF/AMA loader annotations
- Created `backfill_mc_bands.py`: bootstraps 1000 resamples of fold Sharpe distribution, writes `mc_sharpe_lo/hi/median`, pre-flight migration check raises `RuntimeError` with actionable message

## Task Commits

Each task was committed atomically:

1. **Task 1: Add data_loader_fn to BakeoffOrchestrator and load_strategy_data_with_ctf()** - `916dd3df` (feat)
2. **Task 2: Create run_mass_backtest.py orchestrator** - `4d3a48f7` (feat)
3. **Task 3: Create backfill_mc_bands.py MC bands script** - `53d21f1a` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/backtests/bakeoff_orchestrator.py` - Added `data_loader_fn`, `data_loader_type`, `data_loader_kwargs` to `run()` and `_run_parallel()`; added `load_strategy_data_with_ctf()`; updated `BakeoffAssetTask` and `_bakeoff_asset_worker` for CTF loader deserialization
- `src/ta_lab2/scripts/backtests/run_mass_backtest.py` - Resume-safe mass orchestrator: YAML grid loading, state table interaction, CTF/AMA loader detection, --dry-run, --resume, --workers, --strategies flags
- `src/ta_lab2/scripts/backtests/backfill_mc_bands.py` - MC CI backfill: fold_metrics_json bootstrap, batch UPDATE, pre-flight migration check, --dry-run, --batch-size, --n-samples flags

## Decisions Made

- **data_loader_fn (sequential) vs data_loader_type/kwargs (parallel):** `functools.partial` cannot be pickled reliably across process boundaries on Windows. Sequential mode uses the callable directly; parallel mode uses a type string descriptor ("ctf") + kwargs dict that workers reconstruct. Both paths produce identical DataFrames.
- **mass_backtest_state tracks at (strategy, asset, params_hash) level:** Finer-grained tracking would be (strategy, asset, params_hash, tf, cost_bps) but orchestrator runs all costs in one BakeoffOrchestrator.run() call. Using cost_bps=0.0 as sentinel to represent "all costs for this params combo" avoids N×cost_matrix separate state rows while still enabling per-asset resumability.
- **Pre-flight check in backfill_mc_bands.py:** Raises RuntimeError with migration guidance if mc_sharpe_lo/hi/median columns are absent. Preferable to a silent crash on UndefinedColumn. Confirmed required -- DB is on revision r2s3t4u5v6w7, migration s3t4u5v6w7x8 not yet applied.
- **load_strategy_data_with_ctf() uses information_schema validation:** Checks which CTF columns actually exist before building the SELECT, logs missing columns as warnings. Prevents KeyError when column hasn't been promoted yet.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added pre-flight migration check to backfill_mc_bands.py**

- **Found during:** Task 3 (backfill_mc_bands.py verification)
- **Issue:** `--dry-run` crashed with `psycopg2.errors.UndefinedColumn` because the mc_sharpe_lo/hi/median columns don't exist in the local DB yet (migration s3t4u5v6w7x8 not applied). Traceback was unhelpful.
- **Fix:** Added `_check_mc_columns_exist()` function using `information_schema.columns`; raises `RuntimeError` with explicit message "Run 'alembic upgrade head' to apply migration s3t4u5v6w7x8 first."
- **Files modified:** `src/ta_lab2/scripts/backtests/backfill_mc_bands.py`
- **Verification:** `--dry-run` now produces clear `RuntimeError` with actionable message instead of cryptic SQL exception.
- **Committed in:** `53d21f1a` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential correctness fix. The plan's verification criterion "reports NULL count without error" is conditional on the migration being applied; the pre-flight check makes this explicit and actionable.

## Issues Encountered

- `ruff-format` reformatted both new scripts and `bakeoff_orchestrator.py` on first commit attempt each time; restaged the formatted versions. No logic changes in any case.
- `no-root-py-files` hook passed cleanly (run_claude.py was not present in project root for Tasks 2-3; Task 1 required the standard temporary-move workaround from Plans 99-01/99-02).

## User Setup Required

Before running `backfill_mc_bands.py`, apply the Phase 99 schema migration:
```bash
alembic upgrade head
```
This adds `mc_sharpe_lo`, `mc_sharpe_hi`, `mc_sharpe_median` to `strategy_bakeoff_results`.

## Next Phase Readiness

- `run_mass_backtest.py` is executable: `--dry-run` confirmed with 8,496 planned rows across 8 strategies x 2 assets x 18 costs x 2 CV methods
- `backfill_mc_bands.py` is ready to run after `alembic upgrade head` applies migration s3t4u5v6w7x8
- `BakeoffOrchestrator.run()` accepts `data_loader_fn` for pluggable loading; CTF strategies have a working path
- Phase 99-04 (PSR/DSR analysis) can reference `strategy_bakeoff_results` as populated by this orchestrator
- Phase 99-05 (leaderboard dashboard) can read `mc_sharpe_lo/hi/median` after backfill runs

---
*Phase: 99-backtest-scaling*
*Completed: 2026-03-31*
