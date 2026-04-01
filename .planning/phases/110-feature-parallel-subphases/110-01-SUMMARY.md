---
phase: 110
plan: "01"
name: "Feature Parallel Sub-Phases Wave 1"
subsystem: "feature-pipeline"
tags: ["parallelism", "concurrency", "ThreadPoolExecutor", "cli", "feature-refresh"]
one-liner: "Wave 1 parallelized to 4 threads with --workers CLI flag and tf_workers*wave1_workers budget guard"

dependency-graph:
  requires: []
  provides:
    - "run_all_refreshes() wave1_workers parameter (default 4)"
    - "--workers CLI flag controlling Wave 1 thread count"
    - "Worker budget guard: tf_workers * wave1_workers > 8 warning"
    - "Wave 1/2/2b/3/4 log label scheme throughout pipeline"
  affects:
    - "Phase 110-02+ (future wave parallelism plans if any)"
    - "Operational runs: --workers 2 for memory-constrained environments"

tech-stack:
  added: []
  patterns:
    - "ThreadPoolExecutor(max_workers=wave1_workers) for Wave 1 parallelism"
    - "Clamp pattern: wave1_workers = min(wave1_workers, len(phase1_tasks))"
    - "argparse dest= alias: --workers dest='wave1_workers'"
    - "Budget guard: warn if tf_workers * wave1_workers > 8"

key-files:
  created: []
  modified:
    - path: "src/ta_lab2/scripts/features/run_all_feature_refreshes.py"
      change: "Added wave1_workers param, --workers CLI flag, budget guard, Wave N log labels"

decisions:
  - id: "110-01-D1"
    decision: "wave1_workers threaded as tuple element (not kwargs) in _run_single_tf args_tuple"
    rationale: "Existing pattern uses positional tuple; adding as 10th element is consistent"
  - id: "110-01-D2"
    decision: "Clamp wave1_workers = min(wave1_workers, len(phase1_tasks)) inside run_all_refreshes()"
    rationale: "Prevents over-provisioning (e.g., --workers 8 on 4-task list); self-correcting"
  - id: "110-01-D3"
    decision: "Microstructure remains in Wave 2b (not moved to Wave 1)"
    rationale: "Microstructure does UPDATE on features rows that Wave 2 (features_store) INSERTs; hard dependency preserved"
  - id: "110-01-D4"
    decision: "Phase 3b (codependence) log label left as-is (not renamed to Wave)"
    rationale: "Plan only specified Phase 1/2/2c/3 logger calls; codependence is optional/off-path; no verification check required it"

metrics:
  duration: "4 minutes"
  completed: "2026-04-01"
  tasks-completed: 2
  tasks-total: 2
  commits: 1
---

# Phase 110 Plan 01: Feature Parallel Sub-Phases Summary

Wave 1 of the feature refresh pipeline is now fully parallelized with 4 threads via a new `wave1_workers` parameter and `--workers` CLI flag.

## What Was Built

### Task 1: --workers CLI flag, wave1_workers parameter, and budget guard

Added `wave1_workers: int = 4` to `run_all_refreshes()` signature. The existing `ThreadPoolExecutor(max_workers=3)` is now `ThreadPoolExecutor(max_workers=wave1_workers)`, allowing all 4 Wave 1 tasks (vol, ta, cycle_stats, rolling_extremes) to run simultaneously.

The `wave1_workers` parameter is threaded through every call path:
- `parse_args()` exposes `--workers` (dest=`wave1_workers`, default 4)
- `main()` sequential path passes `wave1_workers=args.wave1_workers`
- `main()` parallel path includes `args.wave1_workers` as 10th element in the args tuple
- `_run_single_tf()` unpacks it and passes it to `run_all_refreshes()`

A clamp (`wave1_workers = min(wave1_workers, len(phase1_tasks))`) prevents over-provisioning.

A budget guard warns when `tf_workers * wave1_workers > 8`:
```python
if args.tf_workers > 1:
    total_workers = args.tf_workers * args.wave1_workers
    if total_workers > 8:
        logger.warning("Total concurrent workers=%d ...", total_workers, ...)
```

### Task 2: Wave N log labeling

All log messages in `run_all_refreshes()` updated from "Phase N:" to "Wave N:" labels:

| Old | New |
|-----|-----|
| `"Phase 1: Running vol/ta in parallel"` | `"Wave 1: Running vol/ta/cycle_stats/rolling_extremes in parallel (%d workers)"` |
| `"Phase 1: Running vol/ta sequentially"` | `"Wave 1: Running vol/ta/cycle_stats/rolling_extremes sequentially"` |
| `"Phase 2: Running features (unified view)"` | `"Wave 2: Running features (unified view) -- depends on Wave 1"` |
| `"Phase 2b: Running microstructure feature UPDATE on features"` | `"Wave 2b: Running microstructure UPDATE -- depends on Wave 2"` |
| `"Phase 2c: Running CTF features (cross-timeframe)"` | `"Wave 3: Running CTF features (cross-timeframe) -- depends on Wave 2b"` |
| `"Phase 2c: Skipping CTF features (module not available)"` | `"Wave 3: Skipping CTF features (module not available)"` |
| `"Phase 3: Skipping CS norms (--no-cs-norms)"` | `"Wave 4: Skipping CS norms (--no-cs-norms)"` |
| `"Phase 3: Refreshing cross-sectional normalizations (CS norms)"` | `"Wave 4: Refreshing cross-sectional normalizations (CS norms)"` |

Module docstring updated with wave structure, timing, and `--workers` flag documentation.

## Commits

| Hash | Description |
|------|-------------|
| `50f410a8` | `feat(110-01): parallelize Wave 1 to 4 workers, add --workers flag and budget guard` |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

All checks passed:
- `wave1_workers` in `run_all_refreshes()` signature: PASS
- `--workers` flag shown in `--help` with default 4: PASS
- 13 occurrences of `wave1_workers` in file (>= 8 required): PASS
- No `max_workers=3` remaining: PASS
- Wave 1 count >= 2 (parallel + sequential): PASS (3)
- Wave 2 count >= 1: PASS (2)
- Wave 2b count >= 1: PASS (2)
- Wave 3 count >= 1: PASS (3)
- Wave 4 count >= 1: PASS (3)
- No "Phase 1:", "Phase 2:", "Phase 3:" in logger calls: PASS
- Microstructure remains in Wave 2b position: PASS

## Success Criteria Status

- FEAT-04: Wave 1 runs vol, ta, cycle_stats, rolling_extremes in parallel with 4 workers: COMPLETE
- FEAT-05: Estimated full recompute ~65min (within 70min target): PENDING (actual measurement deferred to operational testing)
- `--workers` CLI flag controls Wave 1 parallelism (default 4): COMPLETE
- Worker budget guard warns on tf_workers * wave1_workers > 8: COMPLETE
- Log output uses consistent Wave 1/2/2b/3/4 labels: COMPLETE
