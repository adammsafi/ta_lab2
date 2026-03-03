---
phase: 65-fred-table-core-features
plan: 03
subsystem: macro, pipeline, vm
tags: [fred, wtregen, vm, verification, e2e, migration, incremental]

# Dependency graph
requires:
  - phase: 65-fred-table-core-features
    plan: 01
    provides: "fred.fred_macro_features table DDL (Alembic b3c4d5e6f7a8) + compute_macro_features() in ta_lab2.macro"
  - phase: 65-fred-table-core-features
    plan: 02
    provides: "refresh_macro_features.py CLI + daily pipeline wiring"

provides:
  - "WTREGEN (Treasury General Account) data in fred.series_values: 2095 rows from 1986-01-08 to 2026-02-25"
  - "fred.fred_macro_features populated: 9558 rows, 25 columns, 2000-01-01 to 2026-03-02"
  - "All FRED-01 through FRED-07 requirements verified against live data"
  - "Incremental refresh verified: 61 rows in 0.3s (watermark + 60d warmup)"
  - "Idempotent upsert verified: row count unchanged on re-run (9558)"

affects:
  - 66: derived features (FRED-08 through FRED-17) build on this populated table
  - 67: macro regime classifier reads from fred.fred_macro_features
  - 71: risk gates join fred.fred_macro_features for VIX/carry/credit data

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "VM SSH automation: orchestrator SSHs into GCP VM to add FRED series and run backfill"
    - "sync_fred_from_vm.py: SSH COPY from VM PostgreSQL to local marketdata"
    - "Python-based DB verification: SQLAlchemy queries instead of psql CLI (Windows compatibility)"

key-files:
  created: []
  modified:
    - src/ta_lab2/macro/feature_computer.py

key-decisions:
  - "Orchestrator SSHed into VM directly (user requested) instead of asking user to run commands manually"
  - "WTREGEN added to ~/.fred.env (40th series), not ~/fred/.env as plan assumed"
  - "Verification via Python/SQLAlchemy instead of psql CLI (psql hangs on Windows, likely password prompt)"
  - "Bug fix: days_since computation changed from .days to .dt.days (Series vs TimedeltaIndex)"

patterns-established:
  - "VM FRED series addition: edit ~/.fred.env, run fred_pull.py, sync locally"
  - "E2E pipeline verification: Python queries with SQLAlchemy, not psql CLI on Windows"

# Metrics
duration: ~20min
completed: 2026-03-03
---

# Phase 65 Plan 03: WTREGEN VM Addition & E2E Verification Summary

**Added WTREGEN to VM FRED collection (40th series), ran full pipeline end-to-end, fixed days_since bug, verified all FRED-01 through FRED-07 requirements against live data**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-03-03
- **Completed:** 2026-03-03
- **Tasks:** 2/2 complete (1 human checkpoint + 1 auto verification)
- **Files modified:** 1 (bug fix in feature_computer.py)

## Accomplishments

- WTREGEN added to VM `~/.fred.env` (40 series total), backfilled 2095 rows (1986-01-08 to 2026-02-25)
- Synced to local marketdata: 210,236 total FRED rows across 40 series
- Alembic migration applied (`alembic upgrade head`): fred.fred_macro_features table created
- Full pipeline run: 9,558 rows computed and upserted in 8.4s
- Fixed bug: `(df_derived.index - src).days` → `df_derived.index.to_series() - src` then `.dt.days`
- All 7 FRED requirements verified via Python/SQLAlchemy queries:
  - FRED-01: 9,558 rows, PK(date), 2000-01-01 to 2026-03-02
  - FRED-02: Weekend rows forward-filled with source_freq="weekly", days_since_walcl=3-4
  - FRED-03: net_liquidity = WALCL - WTREGEN - RRPONTSYD (exact match verified)
  - FRED-04: Rate spreads populated (us_jp=2.912, us_ecb=1.64, us_jp_10y=1.8)
  - FRED-05: t10y2y=0.59, yc_slope_change_5d=-0.01
  - FRED-06: VIX regime distribution: elevated=4652, calm=3095, crisis=1808
  - FRED-07: dtwexbgs=117.99 with 5d and 20d changes populated
- Incremental refresh: 61 rows in 0.3s (watermark + 60d warmup)
- Idempotency: row count unchanged after re-run (9558)

## Task Commits

1. **Task 1: WTREGEN VM addition** — Human checkpoint resolved by orchestrator SSH
2. **Task 2: E2E verification + bug fix** — `6d9866f8` (fix)

## Files Created/Modified

- `src/ta_lab2/macro/feature_computer.py` — Bug fix: days_since computation using `.dt.days` on Series instead of `.days` (which only works on TimedeltaIndex)

## Decisions Made

- **Orchestrator SSH into VM:** User asked "can you not just connect to the vm?" — orchestrator SSHed directly to add WTREGEN and run backfill, avoiding manual user steps.
- **~/.fred.env location:** Plan assumed `~/fred/.env` but systemd service uses `EnvironmentFile=/home/adammsafi_gmail_com/.fred.env`. Found via `systemctl cat` investigation.
- **Python verification instead of psql:** psql commands hung on Windows (password prompt). Switched to SQLAlchemy-based verification queries — more reliable on Windows.
- **Bug fix committed separately:** The `.days` → `.dt.days` fix was committed as its own atomic `fix(65-03)` commit before verification.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] days_since computation AttributeError**
- **Found during:** Task 2 (first full pipeline run)
- **Issue:** `(df_derived.index - src).days` fails because DatetimeIndex minus Series produces a Series of Timedeltas, not a TimedeltaIndex. `.days` is a property of TimedeltaIndex only.
- **Fix:** Changed to `delta = df_derived.index.to_series() - src` then `days = delta.dt.days`
- **Files modified:** src/ta_lab2/macro/feature_computer.py
- **Verification:** Full pipeline run succeeds, days_since_walcl values are correct (0-10 range for weekly series)
- **Committed in:** 6d9866f8

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: Series vs TimedeltaIndex .days accessor)
**Impact on plan:** Bug discovered during E2E verification, fixed immediately.

## Issues Encountered

- **psql hangs on Windows:** `psql -d marketdata` hung, likely due to password prompt in non-interactive shell. Switched to Python-based verification using SQLAlchemy `get_engine()`.
- **VM .fred.env location mismatch:** Plan said `~/fred/.env` but actual location was `~/.fred.env`. Found via `systemctl cat fred-daily-pull.service`.

## User Setup Required

None — WTREGEN was added to VM by orchestrator during this plan execution. The systemd timer will automatically pull WTREGEN going forward.

## Next Phase Readiness

- fred.fred_macro_features is populated with all Phase 65 features (FRED-01 through FRED-07)
- Phase 66 (FRED-08 through FRED-17: credit stress, financial conditions, carry trade, fed regime, CPI proxy) can proceed
- Phase 67 (macro regime classifier) can consume fred.fred_macro_features
- Incremental refresh is operational and wired into run_daily_refresh.py

---
*Phase: 65-fred-table-core-features*
*Completed: 2026-03-03*
