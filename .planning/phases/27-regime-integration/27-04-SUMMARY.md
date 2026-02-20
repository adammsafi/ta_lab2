---
phase: 27-regime-integration
plan: 04
subsystem: regimes
tags: [regimes, hysteresis, flips, stats, comovement, postgresql, python]

# Dependency graph
requires:
  - phase: 27-01
    provides: cmc_regime_flips, cmc_regime_stats, cmc_regime_comovement table DDL
  - phase: 27-02
    provides: regime_data_loader (load_and_pivot_emas) patterns used by comovement
affects:
  - 27-05 (regime refresh pipeline - uses HysteresisTracker to filter rapid flips)
  - 27-06 (regime inspect - reads from cmc_regime_flips, cmc_regime_stats)
  - 27-07 (signal integration - reads regime stats for position sizing)

provides:
  - HysteresisTracker class: stateful per-layer hysteresis, min_bars_hold=3, tightening bypass
  - is_tightening_change(): public API using resolve_policy_from_table to classify transitions
  - detect_regime_flips(): pure flip detection across composite + L0/L1/L2 layers
  - write_flips_to_db(): scoped DELETE + INSERT on cmc_regime_flips
  - compute_regime_stats(): per-regime n_bars, pct_of_history, avg_ret_1d, std_ret_1d
  - write_stats_to_db(): scoped DELETE + INSERT on cmc_regime_stats
  - compute_comovement_records(): EMA pair correlation/sign-agree/lead-lag via comovement.py
  - compute_and_write_comovement(): combined compute+write convenience wrapper
  - write_comovement_to_db(): scoped DELETE + INSERT on cmc_regime_comovement

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "HysteresisTracker uses per-layer dict state: _current, _pending, _pending_count for O(1) update"
    - "is_tightening_change uses public resolve_policy_from_table (not private _match_policy) to stay decoupled from resolver internals"
    - "Flip detection: shift(1) within each (id,tf,layer) group, first row always initial assignment (old=None)"
    - "Stats computation: auto-detect return column from candidate list (_RET_COL_CANDIDATES) for robustness"
    - "Comovement: extract correlation from matrix (.loc[ema_a, ema_b]), sign_agree from rows DataFrame"
    - "Scoped DELETE + INSERT pattern: same as feature write pattern (DELETE WHERE id=ANY(:ids) AND tf=:tf)"
    - "ON CONFLICT DO UPDATE used as safety net on top of scoped DELETE to handle any PK collisions"

key-files:
  created:
    - src/ta_lab2/regimes/hysteresis.py
    - src/ta_lab2/scripts/regimes/regime_flips.py
    - src/ta_lab2/scripts/regimes/regime_stats.py
    - src/ta_lab2/scripts/regimes/regime_comovement.py
  modified:
    - src/ta_lab2/regimes/__init__.py

key-decisions:
  - "HysteresisTracker default min_bars_hold=3: matches plan spec; enough to filter noise without sluggish response"
  - "Tightening detected via size_mult < old or stop_mult > old: both directions of tightening covered"
  - "Flip detection includes initial assignment row (old_regime=None) for audit completeness"
  - "Stats ddof=1 (sample std dev) matches pandas default and is appropriate for regime slice sizes"
  - "Comovement uses Spearman correlation (rank-based, robust to outliers) matching comovement.py default"
  - "write_comovement_to_db scoped DELETE removes all prior snapshots for (ids,tf) to prevent unbounded growth"

patterns-established:
  - "Layer column candidates: composite=['regime_key'], L0=['l0_trend','l0_key'], L1=['l1_trend','l1_vol','l1_key'], L2=['l2_vol','l2_liquidity','l2_key']"
  - "Return column auto-detection from candidate list before merge avoids hard-coding column names"
  - "compute_* functions are pure (no DB); write_*_to_db functions handle all DB I/O"
  - "compute_and_write_* wrappers combine both for pipeline convenience"

# Metrics
duration: 4min
completed: 2026-02-20
---

# Phase 27 Plan 04: Hysteresis, Flips, Stats, and Comovement Summary

**HysteresisTracker with tightening-bypass (min_bars_hold=3), DB-backed flip/stats/comovement writers using scoped DELETE + INSERT linking to comovement.py analytics**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-20T19:29:07Z
- **Completed:** 2026-02-20T19:33:45Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- HysteresisTracker: stateful per-layer hold filter; loosening changes held for min_bars_hold bars, tightening (via resolve_policy_from_table size_mult/stop_mult comparison) bypasses immediately
- Flip detection: pure function covering composite + L0/L1/L2 layers; initial assignment rows (old=None) preserved for audit; duration_bars computed per flip
- Regime stats: auto-detects return column from candidates list; handles missing returns gracefully with NaN; pct_of_history computed per (id,tf) total
- Comovement: bridges to comovement.py compute_ema_comovement_stats + lead_lag_max_corr; extracts correlation from matrix and sign_agree_rate from rows DataFrame

## Task Commits

Each task was committed atomically:

1. **Task 1: Create HysteresisTracker class** - `e442246d` (feat)
2. **Task 2: Create regime_flips, regime_stats, and regime_comovement** - `eb46b342` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/regimes/hysteresis.py` - HysteresisTracker class + is_tightening_change helper (240 lines)
- `src/ta_lab2/regimes/__init__.py` - Added HysteresisTracker + is_tightening_change exports under import-guard
- `src/ta_lab2/scripts/regimes/regime_flips.py` - detect_regime_flips + write_flips_to_db (240 lines)
- `src/ta_lab2/scripts/regimes/regime_stats.py` - compute_regime_stats + write_stats_to_db (260 lines)
- `src/ta_lab2/scripts/regimes/regime_comovement.py` - compute_comovement_records + compute_and_write_comovement + write_comovement_to_db (310 lines)

## Decisions Made

- **HysteresisTracker min_bars_hold=3 default**: Matches plan spec. Three bars is enough to filter single-bar noise while not being sluggish on genuine regime shifts.
- **Tightening via size_mult/stop_mult comparison**: Both directions covered - smaller size OR larger stop both constitute tightening. Uses public `resolve_policy_from_table` not private `_match_policy`.
- **Stats ddof=1**: Sample std dev appropriate for regime slice sizes; matches pandas default.
- **Comovement Spearman correlation**: Rank-based, robust to EMA outliers; matches `compute_ema_comovement_stats` default so results are consistent.
- **write_comovement_to_db scoped DELETE**: Removes all prior snapshots for (ids,tf) to prevent unbounded table growth. Each refresh produces exactly one snapshot.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hooks (ruff-format + mixed-line-ending) reformatted files on both commits. Required re-staging and re-committing after each hook run. Known Windows/git interaction on this machine.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- HysteresisTracker ready for use in regime refresh pipeline (Plan 27-05)
- flip/stats/comovement writers ready; require engine + regime_df from refresh pipeline
- Comovement writer requires wide-format EMA DataFrame (load_and_pivot_emas output)
- All 4 regime DB tables (cmc_regimes, cmc_regime_flips, cmc_regime_stats, cmc_regime_comovement) now have Python writers

---
*Phase: 27-regime-integration*
*Completed: 2026-02-20*
