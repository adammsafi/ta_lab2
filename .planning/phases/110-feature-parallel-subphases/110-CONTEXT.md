# Phase 110: Feature Parallel Sub-Phase Optimization

**Goal:** Increase parallelism within the feature refresh by grouping independent sub-phases into parallel waves. Target: 100 min → 50-60 min when full recompute is needed.

## Problem

The feature refresh runs 8 sub-phases mostly sequentially. Currently only vol + ta run in parallel (Phase 1). The remaining 6 sub-phases run sequentially even though some are independent.

## Current Sub-Phase Structure

| Phase | Sub-phases | Parallel? | Dependencies |
|-------|-----------|-----------|-------------|
| Phase 1 | vol, ta, cycle_stats | vol+ta parallel, cycle sequential | None |
| Phase 2 | rolling_extremes | Sequential | Needs vol, ta |
| Phase 3 | microstructure | Sequential | Needs bars |
| Phase 4 | features (unified) | Sequential | Needs vol, ta |
| Phase 5 | CTF | Sequential | Needs all above |
| Phase 6 | CS norms | Sequential | Needs features |

## Proposed Parallel Structure

| Wave | Sub-phases | Time (current) | Time (parallel) |
|------|-----------|----------------|-----------------|
| Wave 1 | vol + ta + cycle_stats + microstructure | 53 min serial | ~17 min parallel |
| Wave 2 | rolling_extremes + features (unified) | 21 min serial | ~17 min parallel |
| Wave 3 | CTF | 21 min | 21 min |
| Wave 4 | CS norms | 6 min | 6 min |
| **Total** | | **101 min** | **~61 min** |

## Risks

- Memory pressure: 4 parallel pandas operations each loading 492 assets
- DB connection exhaustion: each sub-phase spawns workers
- Need to cap total worker count across all parallel sub-phases

## Dependencies

- Phase 109 (skip unchanged) should complete first — fewer assets = less memory pressure

## Success Criteria

- [ ] Feature sub-phases grouped into parallel waves
- [ ] Total feature refresh time < 70 min for full recompute
- [ ] No memory errors or DB connection exhaustion
- [ ] `--workers` flag controls total parallelism budget
