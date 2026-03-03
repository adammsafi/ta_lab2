---
phase: 65-fred-table-core-features
plan: 02
subsystem: macro, scripts, pipeline
tags: [fred, macro, refresh, watermark, upsert, daily-refresh, pipeline, psycopg2]

# Dependency graph
requires:
  - phase: 65-fred-table-core-features
    plan: 01
    provides: "fred.fred_macro_features table DDL (Alembic b3c4d5e6f7a8) + compute_macro_features() in ta_lab2.macro"

provides:
  - "src/ta_lab2/scripts/macro/__init__.py: package init"
  - "src/ta_lab2/scripts/macro/refresh_macro_features.py: CLI entry point for incremental macro feature upsert"
  - "run_daily_refresh.py --macro / --no-macro flags and macro stage in pipeline (after desc_stats, before regimes)"
  - "WARMUP_DAYS=60 watermark logic ensuring rolling and ffill features are correct at boundary"
  - "check_fred_staleness(): warns at 48h threshold, never blocks (warn-and-continue)"
  - "upsert_macro_features(): temp table + ON CONFLICT (date) DO UPDATE pattern matching project conventions"

affects:
  - 65-03: will read fred.fred_macro_features populated by this CLI
  - 67: macro regime classifier reads from fred.fred_macro_features; pipeline order ensures macro runs before regimes
  - 71: risk gates join fred.fred_macro_features; populated by this refresher

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Watermark + warmup window: MAX(date) from target table - WARMUP_DAYS to ensure feature correctness at boundary"
    - "Warn-and-continue staleness check: log WARNING if FRED DFF data older than 48h, never raise"
    - "NaN->None via df.where(df.notna(), None) before psycopg2 binding (project-standard pattern)"
    - "numpy scalar safety: hasattr(v, 'item') check in _to_python() helper"
    - "Subprocess ComponentResult pattern: dry_run early return, verbose streaming vs capture_output, TIMEOUT constant"

key-files:
  created:
    - src/ta_lab2/scripts/macro/__init__.py
    - src/ta_lab2/scripts/macro/refresh_macro_features.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "WARMUP_DAYS=60: covers 45-day monthly ffill limit + 20-day rolling window (belt-and-suspenders)"
  - "Pipeline position: after desc_stats, before regimes -- macro is independent of bars/EMAs but must precede Phase 67 regime classifier"
  - "TIMEOUT_MACRO=300s: small FRED dataset (~26 years x ~11 series), fast computation"
  - "run_macro_features(args) signature: no db_url param (macro refresh derives its own engine from get_engine()) unlike other stages"
  - "Staleness check is advisory only: stale FRED data should warn but not block the pipeline for unrelated assets"

patterns-established:
  - "FRED refresh scripts live in src/ta_lab2/scripts/macro/ mirroring scripts/bars, scripts/emas, scripts/regimes"
  - "All pipeline stages return ComponentResult and obey continue_on_error flag"

# Metrics
duration: 5min
completed: 2026-03-03
---

# Phase 65 Plan 02: CLI Refresh Script & Daily Pipeline Integration Summary

**Incremental FRED macro feature refresh CLI with watermark+60d warmup, temp-table upsert, 48h staleness warning, and --macro stage wired into run_daily_refresh.py between desc_stats and regimes**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-03T01:39:48Z
- **Completed:** 2026-03-03T01:44:53Z
- **Tasks:** 2/2 complete
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- `refresh_macro_features.py` runs standalone with --dry-run, --full, --verbose, --start-date, --end-date
- Watermark query + 60-day warmup window ensures correct incremental computation at boundary
- Upsert uses project-standard temp table + ON CONFLICT (date) DO UPDATE pattern with NaN/numpy safety
- FRED staleness check warns at 48h but does not block (verified: DFF 121h old warns correctly)
- `run_daily_refresh.py` --macro triggers macro stage; --all includes macro; --no-macro skips it
- Macro stage correctly positioned after desc_stats, before regimes in pipeline

## Task Commits

Each task was committed atomically:

1. **Task 1: Incremental refresh script** - `9cd0e47c` (feat)
2. **Task 2: Wire --macro stage into run_daily_refresh.py** - `10db5fee` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/macro/__init__.py` - Package init for macro refresh scripts
- `src/ta_lab2/scripts/macro/refresh_macro_features.py` - CLI entry point: watermark computation, FRED staleness check, NaN-safe upsert, argparse with --dry-run/--full/--verbose/--start-date/--end-date
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added TIMEOUT_MACRO, run_macro_features(), --macro/--no-macro flags, validation check, run_macro logic, component display, pipeline insertion after desc_stats

## Decisions Made

- **WARMUP_DAYS=60:** Covers the 45-day monthly forward-fill limit plus 20-day rolling window with margin. On incremental runs, we recompute starting 60 days before the watermark to ensure features at the boundary are correct.
- **Pipeline position (after desc_stats, before regimes):** Macro features are independent of bars/EMAs/AMAs (they come from FRED, not market data). Placed before regimes so Phase 67 macro regime classifier can read macro context during regime computation.
- **TIMEOUT_MACRO=300s:** FRED dataset is small (~26 years, ~11 series, ~9,500 rows). 5 minutes is more than sufficient even with warmup recompute.
- **run_macro_features(args) signature (no db_url):** Unlike other stage functions that receive db_url and pass it to the subprocess via --db-url, the macro refresh derives its own engine from get_engine() (which reads from environment/config). This matches the pattern from refresh scripts that don't need per-asset ID filtering.
- **Staleness check is advisory:** Stale FRED data is a data freshness issue but does not indicate that the computation will fail. The pipeline should continue so other components (bars, EMAs, regimes) are not blocked by a FRED sync delay.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **ruff-format auto-correction on first commit attempt:** The pre-commit hook reformatted `refresh_macro_features.py` (multi-line string join compressed). Re-staged and committed on second attempt. No functional change.

## User Setup Required

None - no external service configuration required. The Alembic migration (b3c4d5e6f7a8) must be applied before the script can write to `fred.fred_macro_features`, but that was handled in Plan 65-01.

## Next Phase Readiness

- `refresh_macro_features.py` is ready to populate `fred.fred_macro_features` once migration b3c4d5e6f7a8 is applied (`alembic upgrade head`)
- Plan 65-03 (validation + monitoring for macro features) can proceed immediately
- Phase 67 macro regime classifier can consume `fred.fred_macro_features` once populated

---
*Phase: 65-fred-table-core-features*
*Completed: 2026-03-03*
