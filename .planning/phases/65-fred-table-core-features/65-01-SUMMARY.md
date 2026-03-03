---
phase: 65-fred-table-core-features
plan: 01
subsystem: database, macro
tags: [fred, alembic, macro, pandas, forward-fill, net-liquidity, vix-regime, rate-spreads]

# Dependency graph
requires:
  - phase: 63-tech-debt-cleanup
    provides: "dim_executor_config initial_capital column (current Alembic head a1b2c3d4e5f7)"
  - phase: 65-fred-table-core-features (context)
    provides: "fred.series_values raw FRED observations via sync_fred_from_vm.py"

provides:
  - "fred.fred_macro_features table DDL via Alembic migration (revision b3c4d5e6f7a8)"
  - "src/ta_lab2/macro/ package: load_series_wide, forward_fill_with_limits, compute_macro_features"
  - "FFILL_LIMITS: weekly=10, monthly=45, daily=5 day limits"
  - "ffill_with_source_date() provenance tracker for days_since_* columns"
  - "compute_derived_features() for net_liquidity, rate spreads, yc_slope, vix_regime, dollar strength"

affects:
  - 65-02: refresh_macro_features.py CLI uses compute_macro_features() directly
  - 65-03: run_daily_refresh.py --macro stage calls the CLI from 65-02
  - 67: macro regime classifier reads from fred.fred_macro_features
  - 71: risk gates join fred.fred_macro_features for macro context

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Compute-time forward-fill: raw fred.series_values stays sparse; ffill in Python at compute time"
    - "ffill_with_source_date(): track source observation date alongside filled values for provenance"
    - "Wide table in fred schema for derived/computed features (raw stays in series_values long format)"
    - "Missing series graceful degradation: log WARNING, set derived column to NaN, continue pipeline"
    - "pd.cut() for VIX regime binning (calm <15, elevated 15-25, crisis >25); replace 'nan' str with None"

key-files:
  created:
    - alembic/versions/a1b2c3d4e5f6_fred_macro_features.py
    - src/ta_lab2/macro/__init__.py
    - src/ta_lab2/macro/fred_reader.py
    - src/ta_lab2/macro/forward_fill.py
    - src/ta_lab2/macro/feature_computer.py
  modified: []

key-decisions:
  - "Alembic revision ID b3c4d5e6f7a8 (not a1b2c3d4e5f6 which was already taken by Phase 56 migration)"
  - "down_revision = a1b2c3d4e5f7 (actual head, not f6a7b8c9d0e1 as plan stated -- plan had stale head reference)"
  - "Calendar-daily reindex (freq='D') includes weekends -- correct for crypto 24/7 consumers"
  - "vix_regime: pd.cut() returns Categorical -> astype(str) -> replace 'nan' with None for DB NULL"
  - "type: ignore[arg-type] on pd.read_sql params -- mypy cannot verify dict[str, str | list[str]] against pandas overloaded type"

patterns-established:
  - "Pattern: macro module uses engine parameter (caller provides) not get_engine() inside module"
  - "Pattern: ingested_at excluded from compute output (DB server_default=now() handles it)"
  - "Pattern: uppercase FRED IDs inside computation, lowercase only at final rename step before DB write"

# Metrics
duration: 6min
completed: 2026-03-03
---

# Phase 65 Plan 01: FRED Macro Features -- Table DDL and Core Computation Module

**Alembic migration (b3c4d5e6f7a8) creating fred.fred_macro_features with 27 columns, plus Python macro package with per-frequency forward-fill and FRED-03 through FRED-07 derived feature computation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-03T01:28:26Z
- **Completed:** 2026-03-03T01:34:28Z
- **Tasks:** 2 of 2
- **Files modified:** 5 created, 0 modified

## Accomplishments

- Created Alembic migration (revision b3c4d5e6f7a8) for fred.fred_macro_features with all 27 columns in fred schema, symmetric downgrade, and date DESC index
- Built src/ta_lab2/macro/ package with fred_reader, forward_fill, feature_computer modules
- Implemented frequency-aware forward-fill: weekly series limit=10, monthly limit=45, daily limit=5
- Added ffill_with_source_date() provenance tracker enabling days_since_walcl and days_since_wtregen columns
- Implemented all FRED-03 through FRED-07 derived features: net_liquidity, 3 rate spreads, yc_slope_change_5d, vix_regime (calm/elevated/crisis), dtwexbgs 5d and 20d changes
- Missing WTREGEN handled gracefully: WARNING logged, net_liquidity set to NaN, pipeline continues

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration for fred.fred_macro_features** - `b046496a` (feat)
2. **Task 2: Core macro computation module** - `db75aa6a` (feat)

**Plan metadata:** (see docs commit below)

## Files Created/Modified

- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` -- Alembic migration: CREATE SCHEMA IF NOT EXISTS fred; CREATE TABLE fred.fred_macro_features with 27 columns, PK(date), index
- `src/ta_lab2/macro/__init__.py` -- Package init, re-exports load_series_wide, forward_fill_with_limits, compute_macro_features
- `src/ta_lab2/macro/fred_reader.py` -- SERIES_TO_LOAD (11 series), load_series_wide() reads fred.series_values, pivots to wide, reindexes to calendar-daily
- `src/ta_lab2/macro/forward_fill.py` -- FFILL_LIMITS dict, SOURCE_FREQ dict, ffill_with_source_date(), forward_fill_with_limits()
- `src/ta_lab2/macro/feature_computer.py` -- compute_derived_features(), compute_macro_features() full pipeline orchestrator

## Decisions Made

- **Revision ID collision:** Plan specified revision ID `a1b2c3d4e5f6` but that ID was already used by Phase 56 migration (add_rank_ic_to_ic_results.py). Used `b3c4d5e6f7a8` instead.
- **Stale down_revision in plan:** Plan said `down_revision = "f6a7b8c9d0e1"` (portfolio_tables) but the actual Alembic head was `a1b2c3d4e5f7` (add_initial_capital_to_executor_config). Used correct head.
- **Calendar-daily reindex (freq='D'):** Includes weekends and holidays. Correct choice because downstream crypto consumers (regime classifier, risk gates, dashboard) operate 24/7.
- **vix_regime None handling:** pd.cut() on NaN VIXCLS returns NaN; astype(str) converts to "nan" string. Added explicit mask to replace with None for DB NULL.
- **type: ignore[arg-type] on pd.read_sql:** pandas read_sql params type overloads do not accept dict[str, str | list[str]] in mypy strict mode. Added targeted ignore comment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Collision on Alembic revision ID a1b2c3d4e5f6**
- **Found during:** Task 1 (Alembic migration creation)
- **Issue:** Plan specified revision ID `a1b2c3d4e5f6` but this ID already exists in `a1b2c3d4e5f6_add_rank_ic_to_ic_results.py` (Phase 56). Alembic raised CycleDetected error.
- **Fix:** Used revision ID `b3c4d5e6f7a8` and corrected down_revision to actual head `a1b2c3d4e5f7`
- **Files modified:** alembic/versions/a1b2c3d4e5f6_fred_macro_features.py
- **Verification:** `alembic heads` returns `b3c4d5e6f7a8 (head)` (single head)
- **Committed in:** b046496a

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: stale/colliding revision ID in plan)
**Impact on plan:** Necessary fix for correct Alembic chain. No scope creep.

## Issues Encountered

- ruff format reformatted 3 of 4 files after initial commit attempt (inline comments on list items). Re-staged and committed successfully.

## User Setup Required

None - no external service configuration required for this plan. WTREGEN VM addition (add to FRED series list, backfill, sync) is a manual pre-step needed before refresh_macro_features.py can compute full net_liquidity. Documented as WARNING in compute_derived_features().

## Next Phase Readiness

- fred.fred_macro_features DDL is ready for `alembic upgrade head`
- src/ta_lab2/macro.compute_macro_features() is the callable the 65-02 CLI script needs
- 65-02 (refresh_macro_features.py) can now be built: import compute_macro_features, add upsert logic, add watermark incremental logic
- WTREGEN VM addition remains a manual step (SSH into VM, add to series list, backfill, sync locally)
- Blocker for full net_liquidity: WTREGEN must be in fred.series_values before refresh produces non-NaN net_liquidity

---
*Phase: 65-fred-table-core-features*
*Completed: 2026-03-03*
