---
phase: 59-microstructural-advanced-features
plan: 01
subsystem: database
tags: [postgres, migration, microstructure, codependence, schema]

# Dependency graph
requires:
  - phase: 27-regime-pipeline
    provides: "cmc_features table structure and feature store pattern"
  - phase: 33-cmc-features-redesign
    provides: "cmc_features 112-column bar-level feature store"
provides:
  - "9 microstructure columns in cmc_features (fracdiff, lambdas, SADF, entropy)"
  - "cmc_codependence table for pairwise asset dependency metrics"
affects:
  - 59-02 (fractional differencing computation)
  - 59-03 (market microstructure lambda computation)
  - 59-04 (SADF structural break detection)
  - 59-05 (entropy and codependence computation)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ADD COLUMN IF NOT EXISTS for idempotent schema migration"
    - "ASCII-only SQL comments for Windows cp1252 compatibility"

key-files:
  created:
    - sql/migration/add_microstructure_to_features.sql
    - sql/migration/create_cmc_codependence.sql
  modified: []

key-decisions:
  - "Grouped ALTER TABLE statements by MICRO requirement (01-04) for readability"
  - "cmc_codependence PK includes computed_at to retain historical snapshots across refreshes"
  - "Convention: id_a < id_b to avoid duplicate pairs in codependence table"

patterns-established:
  - "Microstructure column naming: close_fracdiff, kyle_lambda, sadf_stat, entropy_shannon"

# Metrics
duration: 2min
completed: 2026-02-28
---

# Phase 59 Plan 01: Schema Migrations Summary

**Added 9 microstructure columns to cmc_features and created cmc_codependence pairwise asset table**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-28T09:06:27Z
- **Completed:** 2026-02-28T09:08:52Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added 9 microstructure columns to cmc_features covering fractional differencing (2), price impact lambdas (3), SADF structural breaks (2), and entropy features (2)
- Created cmc_codependence table with PK (id_a, id_b, tf, window_bars, computed_at) for pairwise asset dependency metrics
- Both migrations verified idempotent (re-runnable without error)
- All SQL files use ASCII-only comments (no Windows cp1252 encoding issues)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create SQL migration for cmc_features microstructure columns** - `fbd9458e` (feat)
2. **Task 2: Create cmc_codependence table DDL and execute** - `3807cd34` (feat)

## Files Created/Modified
- `sql/migration/add_microstructure_to_features.sql` - ALTER TABLE adding 9 microstructure columns (fracdiff, lambdas, SADF, entropy)
- `sql/migration/create_cmc_codependence.sql` - CREATE TABLE for pairwise codependence metrics with indexes and comments

## Decisions Made
- Grouped ALTER TABLE statements by MICRO requirement (01-04) rather than a single long ALTER TABLE -- improves readability and maps columns to their source requirements
- cmc_codependence PK includes computed_at to retain historical snapshots, matching the pattern from cmc_regime_comovement
- Documented convention that id_a < id_b to avoid duplicate pairs

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-commit hooks fixed mixed line endings (CRLF/LF) on both SQL files -- auto-resolved by re-staging after hook correction

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Schema foundation complete for all MICRO-01 through MICRO-05 feature computation scripts
- Plans 59-02 through 59-05 can now write to the new columns/table
- No blockers or concerns

---
*Phase: 59-microstructural-advanced-features*
*Completed: 2026-02-28*
