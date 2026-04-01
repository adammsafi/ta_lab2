---
phase: 111-feature-polars-migration
plan: 04
subsystem: features
tags: [polars, performance, migration, microstructure, orchestrator, cli]

dependency_graph:
  requires:
    - phase: 111-01
      provides: polars_feature_ops.py, polars_sorted_groupby, use_polars in FeatureConfig
    - phase: 111-02
      provides: vol polars path pattern
    - phase: 111-03
      provides: ta polars path pattern, established closure/groupby convention
  provides:
    - MicrostructureFeature polars outer loop via polars_sorted_groupby
    - _compute_micro_single_group closure (numba/numpy kernels unchanged)
    - --use-polars CLI flag in microstructure_feature.py
    - --use-polars CLI flag in run_all_feature_refreshes.py (orchestrator)
    - use_polars propagation to all 5 computation sub-phases (vol, ta, cycle_stats, rolling_extremes, microstructure)
    - daily_features_view.py confirmed no-op (pure SQL)
  affects:
    - plan 111-05 (CTF polars migration -- only remaining sub-phase)
    - production feature refresh runs (opt-in --use-polars flag)

tech-stack:
  added: []
  patterns:
    - "_compute_*_single_group closure pattern: all per-group computation extracted to method; polars path calls via polars_sorted_groupby, pandas path loops manually"
    - "use_polars propagation: refresh_fn(engine, ids, start, end, tf, alignment_source, venue_id, use_polars) signature for all Wave 1 refresh functions"
    - "_run_single_tf worker tuple: use_polars appended as last element (positional tuple must match exactly in both construction and unpacking)"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/features/microstructure_feature.py
    - src/ta_lab2/scripts/features/run_all_feature_refreshes.py

key-decisions:
  - "_compute_micro_single_group bound method (not closure): self.micro_config accessed inside for ffd_threshold, liquidity_window, adf_window, entropy_window, entropy_bins -- bound method is cleaner than capturing self in a closure"
  - "daily_features_view.py confirmed no-op: pure SQL INSERT INTO features SELECT ... JOIN price_bars/returns/vol/ta; no Python groupby loop to migrate"
  - "CS norms unaffected: PARTITION BY window functions in SQL; no Python loop"
  - "CTF deferred to Plan 05: separate concern with own complexity; deferred per plan spec"
  - "_run_single_tf tuple extended by 1 element (use_polars): both construction in main() and unpacking in worker must match; use getattr(args, 'use_polars', False) for safe access"

patterns-established:
  - "All Wave 1 refresh functions (refresh_vol, refresh_ta, refresh_cycle_stats, refresh_rolling_extremes, refresh_microstructure) accept use_polars kwarg and pass to config"
  - "run_all_refreshes() has use_polars=False default: zero behavior change for existing callers"

metrics:
  tasks_completed: 2
  tasks_total: 2
  duration: 5 min
  completed: "2026-04-01"
---

# Phase 111 Plan 04: Feature Polars Migration - Microstructure + Orchestrator Summary

**MicrostructureFeature polars outer loop via polars_sorted_groupby with numba/numpy kernels unchanged, plus --use-polars CLI flag wired through orchestrator to all 5 computation sub-phases.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-01T23:48:45Z
- **Completed:** 2026-04-01T23:53:58Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `_compute_micro_single_group()` method extracted -- contains the full MICRO-01 through MICRO-04 per-group body; numba kernels (find_min_d, frac_diff_ffd, kyle_lambda, amihud_lambda, hasbrouck_lambda, rolling_adf, rolling_entropy) unchanged
- `MicrostructureFeature.compute_features()` branches on `use_polars`: polars path uses `polars_sorted_groupby`; pandas path retains original loop calling same method
- `--use-polars` CLI flag added to `microstructure_feature.py` and passed to `MicrostructureConfig`
- `--use-polars` flag added to `run_all_feature_refreshes.py` orchestrator with startup log line "Polars acceleration: enabled/disabled"
- `use_polars` propagated to all 5 computation refresh functions (refresh_vol, refresh_ta, refresh_cycle_stats, refresh_rolling_extremes, refresh_microstructure)
- Both sequential and parallel Wave 1 execution paths propagate the flag
- `_run_single_tf` worker tuple extended to include `use_polars` (positional tuple, parallel TF workers)
- `daily_features_view.py` confirmed as no-op: pure SQL `INSERT INTO features SELECT ... JOIN`, zero Python compute loops

## Task Commits

1. **Task 1: Migrate microstructure outer loop to polars** - `d854d395` (feat)
2. **Task 2: Wire --use-polars into run_all_feature_refreshes orchestrator** - `c45a4b44` (feat)

**Plan metadata:** see below (docs commit)

## Files Created/Modified

- `src/ta_lab2/scripts/features/microstructure_feature.py` - Added `_compute_micro_single_group()` method; added polars path in `compute_features()`; added `--use-polars` CLI flag; passes `use_polars` to `MicrostructureConfig`
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` - Added `--use-polars` CLI arg; added `use_polars` param to all 5 refresh functions + `run_all_refreshes()` + `_run_single_tf`; startup log line; `getattr(args, 'use_polars', False)` safe access in both sequential and parallel paths

## Decisions Made

**`_compute_micro_single_group` as bound method (not lambda/closure):**
- The per-group body needs `self.micro_config` for 5 config values (ffd_threshold, liquidity_window, adf_window, entropy_window, entropy_bins)
- Extracting as `self._compute_micro_single_group` is the cleanest pattern -- no captured variables, directly testable, consistent with how polars_sorted_groupby receives callables

**`daily_features_view.py` confirmed no-op:**
- File is a pure SQL assembler: `INSERT INTO features SELECT bars.*, returns.*, vol.*, ta.* FROM price_bars JOIN returns JOIN vol JOIN ta ON (id, venue_id, ts, tf)`
- No Python groupby loop, no pandas rolling, no numba -- nothing to migrate
- Documented here as the definitive confirmation

**`_run_single_tf` worker tuple with `use_polars` appended:**
- Worker function receives a positional tuple (not kwargs) for pickle-safe multiprocessing
- Adding `use_polars` as position 11 (0-indexed 10) required updating both construction in `main()` and unpacking in `_run_single_tf`
- `getattr(args, 'use_polars', False)` used in `main()` for defensive access

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**ruff-format on multi-arg function calls:** Two commits required per task because ruff-format reformatted multi-line function call argument lists (trailing commas, line length). Standard pre-commit hook behavior -- re-staged and committed on second attempt.

## Next Phase Readiness

Phase 111 Plan 05 (CTF polars migration) can proceed:
- Infrastructure, patterns, and orchestrator flag all in place
- 5 of 6 computation sub-phases migrated (cycle_stats, rolling_extremes, vol, ta, microstructure; unified assembly confirmed no-op)
- Only CTF (cross-timeframe features) remains
- `--use-polars` flag will pass through automatically when Plan 05 adds CTF support

No blockers.

---
*Phase: 111-feature-polars-migration*
*Completed: 2026-04-01*
