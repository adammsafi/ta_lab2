---
phase: 91-ctf-cli-pipeline-integration
plan: 02
subsystem: features
tags: [ctf, cross-timeframe, multiprocessing, tqdm, cli, incremental-state, NullPool]

# Dependency graph
requires:
  - phase: 91-01
    provides: ctf_state table, YAML expanded to 6 base TFs, tqdm in core deps
  - phase: 90
    provides: CTFFeature.compute_for_ids, CTFConfig, cross_timeframe.py engine
  - phase: 89
    provides: ctf fact table, dim_ctf_indicators, ctf_config.yaml structure

provides:
  - "refresh_ctf.py: standalone CLI with 10 flags for CTF feature refresh"
  - "CTFWorkerTask dataclass: frozen worker spec for multiprocessing"
  - "CTFRefreshResult dataclass: per-asset worker result"
  - "refresh_ctf_step(): callable for Plan 03 pipeline integration"
  - "Incremental skip: ctf_state watermark prevents redundant recomputation"
  - "_post_update_ctf_state: upserts ctf_state scopes after each compute"
  - "_delete_ctf_rows + _reset_ctf_state: --full-refresh support"
affects:
  - "91-03: uses refresh_ctf_step() for pipeline integration"
  - "run_daily_refresh: will add CTF as a pipeline step"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level worker function (not method) for multiprocessing pickle compatibility"
    - "NullPool engine created inside worker, disposed in finally block"
    - "Filtered temp YAML file for base_tf/ref_tf in-process filtering"
    - "_dim_indicators cache patching for indicator_filter (direct attribute override)"
    - "_post_update_ctf_state: aggregates ctf scopes after compute for watermark update"
    - "tqdm wraps both sequential (task list) and parallel (imap_unordered iter) modes"

key-files:
  created:
    - src/ta_lab2/scripts/features/refresh_ctf.py
  modified: []

key-decisions:
  - "Incremental skip at per-asset level (not per-scope): check MIN(ctf_state.updated_at) vs MAX(ctf.computed_at); simpler than per-indicator skip while still effective"
  - "base_tf/ref_tf filtering uses temp YAML file written from in-memory filtered config (not custom CTFConfig extension)"
  - "indicator_filter patches feature._dim_indicators directly after _load_dim_ctf_indicators() call"
  - "_post_update_ctf_state aggregates all scopes from ctf table after compute (not tracked during compute)"
  - "Summary note: --full-refresh deletes ALL ctf rows for IDs before rebuilding (not scoped by TF)"

patterns-established:
  - "CTFWorkerTask: frozen dataclass passed to module-level worker for full pickling safety"
  - "_execute_tasks(): shared helper for sequential (tqdm task list) and parallel (pool.imap_unordered) modes"
  - "refresh_ctf_step(): pipeline-callable wrapper returning RefreshResult for orchestrator compatibility"

# Metrics
duration: 43min
completed: 2026-03-23
---

# Phase 91 Plan 02: CTF CLI Summary

**Standalone CTF refresh CLI with multiprocessing, tqdm, incremental state watermarks, and all 10 CLI flags (--ids/--all, --base-tf, --ref-tfs, --indicators, --full-refresh, --workers, --dry-run, --venue-id, --log-level)**

## Performance

- **Duration:** 43 min
- **Started:** 2026-03-23T22:23:40Z
- **Completed:** 2026-03-23T23:06:42Z
- **Tasks:** 2 (Task 1: implementation, Task 2: verification)
- **Files modified:** 1 (refresh_ctf.py created, 884 lines)

## Accomplishments

- Created 884-line standalone CLI at `src/ta_lab2/scripts/features/refresh_ctf.py` with all 10 flags
- Verified single-asset run writes 741,036 CTF rows (1D x 6 ref_tfs x 22 indicators x ~5,614 bars/indicator)
- Incremental skip working: second run completes in 1.6s vs 911s first run (ctf_state watermark)
- `--full-refresh` correctly deletes 741,036 rows and resets 329 state rows before recomputing
- `--indicators rsi_14` filter correctly writes only 33,684 rows (6 TF pairs x 5,614 rows)
- `--ref-tfs 7D` filter correctly writes only 123,506 rows (22 indicators x 7D pair)
- Multi-asset `--ids 1,52 --workers 2` correctly processes both assets with tqdm showing 2/2
- `--dry-run` reports 6 TF pairs x 22 indicators = 132 combos in 0.3s without writing

## Task Commits

1. **Task 1: Create refresh_ctf.py standalone CLI** - `a7eedcdf` (feat)
2. **Task 2: Verify incremental refresh and multi-asset runs** - no additional code changes (verified via live runs)

## Files Created/Modified

- `src/ta_lab2/scripts/features/refresh_ctf.py` - 884-line standalone CTF refresh CLI with full multiprocessing, tqdm, incremental state, and `refresh_ctf_step()` pipeline callable

## Decisions Made

- **Incremental skip at per-asset level:** Check `MIN(ctf_state.updated_at) >= MAX(ctf.computed_at)` for the asset. If all state rows are newer than CTF data, skip. Simpler than per-scope (indicator/TF) skip while still providing meaningful incremental behavior.
- **base_tf/ref_tf filtering via temp YAML:** Load base YAML, filter `timeframe_pairs` in-memory, dump to `tempfile.NamedTemporaryFile(suffix='.yaml', delete=False)`, pass path to `CTFConfig(yaml_path=...)`, clean up in finally block.
- **indicator_filter via `_dim_indicators` cache patching:** Call `feature._load_dim_ctf_indicators()` then filter and reassign `feature._dim_indicators = [...]`. Avoids needing a new CTFConfig parameter for this use case.
- **_post_update_ctf_state aggregates from ctf table post-compute:** After `compute_for_ids()` returns, query `GROUP BY base_tf, ref_tf, indicator_id` to get `MAX(ts)` and `COUNT(*)` for all scopes, then upsert into `ctf_state`. Cleaner than tracking state during compute.
- **--full-refresh deletes ALL ctf rows for IDs:** Not scoped by base_tf or indicators filter. Ensures clean state for the full rebuild.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `n_skipped` variable causing ruff F841 lint error**

- **Found during:** Commit attempt for Task 1
- **Issue:** `n_skipped = sum(1 for t in tasks) - n_errors` was computed but never used in summary output. Ruff F841 lint error blocked pre-commit hook.
- **Fix:** Removed the dead assignment. The summary table reports assets processed, rows written, and errors without a separate skipped count (incremental skip is surfaced via the `rows=0` and `duration` values).
- **Files modified:** `src/ta_lab2/scripts/features/refresh_ctf.py`
- **Verification:** `ruff lint` passed on second commit attempt.
- **Committed in:** `a7eedcdf` (Task 1 commit after fix)

---

**Total deviations:** 1 auto-fixed (Rule 1 - dead variable lint error)
**Impact on plan:** No scope creep. Lint fix is cosmetic; no behavior change.

## Issues Encountered

- Ruff lint F841 on first commit attempt: `n_skipped` assigned but unused. Fixed by removing the dead assignment before recommitting.

## Next Phase Readiness

- `refresh_ctf_step()` function ready for Plan 03 pipeline integration
- `RefreshResult` dataclass exported for orchestrator compatibility
- Full CTF CLI validated for single-asset, multi-asset, incremental, and filtered runs
- ctf_state watermarks correctly track all 329 scopes (6 ref_tfs x 22 indicators + 1 per ref_tf scope) for asset 1

---
*Phase: 91-ctf-cli-pipeline-integration*
*Completed: 2026-03-23*
