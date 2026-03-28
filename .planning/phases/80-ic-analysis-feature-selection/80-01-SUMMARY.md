---
phase: 80-ic-analysis-feature-selection
plan: "01"
subsystem: database
tags: [statsmodels, alembic, postgres, feature-selection, ic-analysis, stationarity]

# Dependency graph
requires:
  - phase: 74-02
    provides: "dim_data_sources and alignment_source CHECK constraints (latest alembic head g1h2i3j4k5l6)"
provides:
  - "statsmodels>=0.14.0 installed and importable (adfuller, kpss, acorr_ljungbox)"
  - "dim_feature_selection table in PostgreSQL with 12 columns, PK, and CHECK constraints"
  - "[analysis] optional dependency group in pyproject.toml"
  - "Alembic migration h2i3j4k5l6m7 extending from g1h2i3j4k5l6"
affects:
  - "80-ic-analysis-feature-selection plans 02-05 (IC computation, stationarity tests, feature tiering)"
  - "Any script importing statsmodels.tsa.stattools or statsmodels.stats.diagnostic"

# Tech tracking
tech-stack:
  added: ["statsmodels==0.14.6", "patsy==1.0.2 (statsmodels dependency)"]
  patterns:
    - "Optional dependency group [analysis] for statistical analysis libraries"
    - "Alembic migration using op.execute(text(...)) for complex DDL with CHECK constraints"

key-files:
  created:
    - "alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py"
  modified:
    - "pyproject.toml"

key-decisions:
  - "Named optional group [analysis] (not [stats] or [quant]) to match phase 80 IC analysis purpose"
  - "quintile_monotonicity NUMERIC column added (Spearman Q1-Q5 terminal returns) beyond RESEARCH.md schema"
  - "CHECK constraints use named constraints (chk_dim_feature_selection_tier, chk_dim_feature_selection_stationarity) for clarity in pg_constraint queries"
  - "stationarity values use uppercase enum strings (STATIONARY, NON_STATIONARY, etc.) for clear status signaling"

patterns-established:
  - "Pattern: New statistical/analysis libraries go in [analysis] optional group, also added to [all]"
  - "Pattern: dim_* dimension tables use PK + CHECK constraints for categorical columns"

# Metrics
duration: 3min
completed: 2026-03-22
---

# Phase 80 Plan 01: statsmodels + dim_feature_selection Foundation Summary

**statsmodels 0.14.6 installed with ADF/KPSS/Ljung-Box imports verified, and dim_feature_selection PostgreSQL table created via Alembic migration h2i3j4k5l6m7 with 12 columns, PK on feature_name, and CHECK constraints on tier and stationarity**

## Performance

- **Duration:** 3min
- **Started:** 2026-03-22T03:01:23Z
- **Completed:** 2026-03-22T03:04:31Z
- **Tasks:** 2
- **Files modified:** 2 (pyproject.toml, new migration file)

## Accomplishments

- Added `[analysis]` optional dependency group to pyproject.toml with `statsmodels>=0.14.0`; installed version 0.14.6
- Verified all three key IC-analysis imports: `adfuller`, `kpss` (stationarity tests), `acorr_ljungbox` (autocorrelation)
- Created `dim_feature_selection` table via Alembic migration h2i3j4k5l6m7 with all 12 columns, PK, and two CHECK constraints
- Verified CHECK constraints are enforced: invalid tier value rejected, valid tier accepted

## Task Commits

Each task was committed atomically:

1. **Task 1: Add statsmodels to pyproject.toml and install** - `02a7c959` (chore)
2. **Task 2: Create Alembic migration for dim_feature_selection table** - `40c7ce2d` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `pyproject.toml` - Added `[analysis]` optional group with `statsmodels>=0.14.0`; added `statsmodels>=0.14.0` to `[all]` group
- `alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py` - Migration creating `dim_feature_selection` with 12 columns, PK, tier and stationarity CHECK constraints

## Decisions Made

- Named the optional group `[analysis]` to align semantically with the phase purpose (IC analysis / feature selection)
- Added `quintile_monotonicity NUMERIC` column beyond the RESEARCH.md schema to store Spearman correlation of Q1-Q5 terminal returns -- needed for monotonicity scoring in plans 02-04
- Used named CHECK constraints (`chk_dim_feature_selection_tier`, `chk_dim_feature_selection_stationarity`) so they are identifiable in `pg_constraint` queries
- Used uppercase enum strings for `stationarity` column (`STATIONARY`, `NON_STATIONARY`, `AMBIGUOUS`, `INSUFFICIENT_DATA`) for unambiguous status display

## Deviations from Plan

None - plan executed exactly as written. The `quintile_monotonicity` column was specified in the plan task (noted as "not in RESEARCH.md but needed") and was included per plan instructions.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. statsmodels installs from PyPI; migration runs against local PostgreSQL.

## Next Phase Readiness

- statsmodels is unblocked: all IC analysis scripts in plans 02-05 can now `from statsmodels.tsa.stattools import adfuller, kpss`
- `dim_feature_selection` table is empty and ready to receive rows from the feature tiering pipeline (plan 04)
- Alembic history is clean: single chain `a0b1c2d3e4f5 -> g1h2i3j4k5l6 -> h2i3j4k5l6m7 (head)`

---
*Phase: 80-ic-analysis-feature-selection*
*Completed: 2026-03-22*
