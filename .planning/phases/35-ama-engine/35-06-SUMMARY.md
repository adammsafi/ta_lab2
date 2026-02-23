---
phase: 35-ama-engine
plan: "06"
subsystem: features
tags: [ama, calendar, multi-tf, postgresql, pandas, sqlalchemy, kama, dema, tema, hma]

# Dependency graph
requires:
  - phase: 35-04
    provides: BaseAMAFeature, BaseAMARefresher, MultiTFAMAFeature, AMAWorkerTask, _ama_worker infrastructure

provides:
  - CalUSAMAFeature: AMA feature class loading from cmc_price_bars_multi_tf_cal_us
  - CalISOAMAFeature: AMA feature class loading from cmc_price_bars_multi_tf_cal_iso
  - CalAnchorUSAMAFeature: AMA feature class loading from cmc_price_bars_multi_tf_cal_anchor_us
  - CalAnchorISOAMAFeature: AMA feature class loading from cmc_price_bars_multi_tf_cal_anchor_iso
  - refresh_cmc_ama_multi_tf_cal_from_bars.py: calendar AMA refresher with --scheme us/iso/both
  - refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py: calendar anchor AMA refresher with --scheme us/iso/both

affects:
  - 35-07 (AMA _u sync tables consume all 5 AMA value table variants)
  - run_daily_refresh.py orchestration (will add calendar AMA variants)
  - AMA returns pipeline (Phase 35-05 refresher targets all AMA table families)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SCHEME_MAP routing: maps scheme key to feature_class, bars_table, output_table, state_table"
    - "Scheme-specific module-level worker: _cal_ama_worker / _cal_anchor_ama_worker — picklable for multiprocessing"
    - "Parameterised _run_for_scheme: single method handles full refresh lifecycle per scheme"
    - "TF universe from dim_timeframe with scheme-specific WHERE clause (calendar_scheme / roll_policy)"

key-files:
  created:
    - src/ta_lab2/features/ama/ama_multi_tf_cal.py
    - src/ta_lab2/features/ama/ama_multi_tf_cal_anchor.py
    - src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf_cal_from_bars.py
    - src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py
  modified: []

key-decisions:
  - "Custom _cal_ama_worker / _cal_anchor_ama_worker functions (not reusing _ama_worker): base worker hardcodes MultiTFAMAFeature; calendar variants need CalUSAMAFeature/CalISOAMAFeature with scheme-aware instantiation"
  - "SCHEME_MAP pattern (same as EMA cal refreshers): single data structure routes scheme to feature_class, tables, and state_table — avoids scattered if/else"
  - "_run_for_scheme method instead of overriding BaseAMARefresher.run(): scheme selection happens at orchestration level, not inside base class; two scheme passes share one argparse namespace"
  - "No-arg constructor on CalAMARefresher/CalAnchorAMARefresher: required because BaseAMARefresher.create_argument_parser() calls cls() to access get_description() before scheme is known"
  - "dim_timeframe TF queries identical to EMA calendar equivalents: same SQL WHERE clauses for cal_us/cal_iso (alignment_type + base_unit patterns) and cal_anchor (roll_policy='calendar_anchor')"

patterns-established:
  - "Calendar AMA feature class pattern: extend BaseAMAFeature, override _load_bars/_get_timeframes/_get_source_table_info, default config points to scheme-specific output table"
  - "Calendar AMA refresher pattern: SCHEME_MAP + main_for_schemes + _run_for_scheme; inherits CLI args from BaseAMARefresher + adds --scheme/--out-us/--out-iso"

# Metrics
duration: 6min
completed: 2026-02-23
---

# Phase 35 Plan 06: Calendar AMA Feature Classes and Refreshers Summary

**4 calendar AMA feature classes (CalUSAMAFeature, CalISOAMAFeature, CalAnchorUSAMAFeature, CalAnchorISOAMAFeature) + 2 refresher scripts completing 5-variant AMA value table coverage**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-23T22:20:20Z
- **Completed:** 2026-02-23T22:26:12Z
- **Tasks:** 2
- **Files modified:** 4 (all created)

## Accomplishments

- Created CalUSAMAFeature and CalISOAMAFeature extending BaseAMAFeature, loading from cal_us/cal_iso bar tables
- Created CalAnchorUSAMAFeature and CalAnchorISOAMAFeature extending BaseAMAFeature, loading from cal_anchor_us/cal_anchor_iso bar tables
- Created refresh_cmc_ama_multi_tf_cal_from_bars.py with --scheme us/iso/both, parallel workers, scheme routing
- Created refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py with matching pattern for anchor variants
- Full 5-variant AMA value table coverage achieved: multi_tf + cal_us + cal_iso + cal_anchor_us + cal_anchor_iso

## Task Commits

Each task was committed atomically:

1. **Task 1: Calendar AMA feature classes + refresher** - `fefc660a` (feat)
2. **Task 2: Calendar anchor AMA feature classes + refresher** - `11241117` (feat)

## Files Created/Modified

- `src/ta_lab2/features/ama/ama_multi_tf_cal.py` - CalUSAMAFeature and CalISOAMAFeature; TF universe from dim_timeframe cal scheme queries
- `src/ta_lab2/features/ama/ama_multi_tf_cal_anchor.py` - CalAnchorUSAMAFeature and CalAnchorISOAMAFeature; TF universe from dim_timeframe anchor scheme queries
- `src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf_cal_from_bars.py` - SCHEME_MAP, _cal_ama_worker, CalAMARefresher with --scheme us/iso/both
- `src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py` - SCHEME_MAP, _cal_anchor_ama_worker, CalAnchorAMARefresher with --scheme us/iso/both

## Decisions Made

- Custom module-level worker functions (_cal_ama_worker, _cal_anchor_ama_worker) rather than reusing base _ama_worker: base worker hardcodes MultiTFAMAFeature instantiation, calendar variants need scheme-aware feature class selection
- SCHEME_MAP data structure: mirrors EMA calendar refresher pattern, avoids scattered if/else for routing feature_class/bars_table/output_table/state_table per scheme
- _run_for_scheme instead of overriding BaseAMARefresher.run(): lets both schemes share one argparse namespace while keeping scheme-specific logic isolated
- No-arg constructors required: BaseAMARefresher.create_argument_parser() calls cls() to get description before scheme argument is parsed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hooks (ruff + mixed line endings) reformatted files on first commit attempt; re-staged reformatted versions for final commit. No logic changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 5 AMA value table variants have refresher scripts
- Ready for AMA sync (_u tables) in Plan 07 (already complete per STATE.md)
- Calendar AMA tables ready to be populated once bars data exists in cal_us/cal_iso/cal_anchor_us/cal_anchor_iso tables
- Command examples:
  - `python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf_cal_from_bars --ids 1 --all-tfs --scheme us`
  - `python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf_cal_anchor_from_bars --ids all --all-tfs --scheme both`

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
