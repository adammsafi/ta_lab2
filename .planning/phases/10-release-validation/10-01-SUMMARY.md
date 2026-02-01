---
phase: 10-release-validation
plan: 01
subsystem: testing
tags: [github-actions, postgresql, pytest, coverage, ci-cd]

# Dependency graph
requires:
  - phase: 09-integration-observability
    provides: Three-tier test pattern (real_deps/mixed_deps/mocked_deps)
provides:
  - Validation CI workflow with PostgreSQL service container
  - Database fixtures for validation tests (db_engine, db_session, ensure_schema)
  - Coverage configuration (70% threshold) with JSON and markdown reports
affects: [10-02, 10-03, 10-04]

# Tech tracking
tech-stack:
  added: [pytest-cov, pytest-json-report, GitHub Actions PostgreSQL service]
  patterns: [CI validation gates with real database, session-scoped database fixtures]

key-files:
  created:
    - .github/workflows/validation.yml
  modified:
    - tests/validation/conftest.py
    - pyproject.toml

key-decisions:
  - "PostgreSQL 16 service container for CI validation (no mock mode)"
  - "Coverage threshold 70% for release quality gate"
  - "Session-scoped db_engine, function-scoped db_session with rollback for test isolation"
  - "ensure_schema fixture calls ensure_dim_tables for automatic schema setup"

patterns-established:
  - "CI validation gates require real database (TARGET_DB_URL)"
  - "Dual coverage reports: JSON for metrics, markdown for human review"
  - "Validation tests skip gracefully without database (pytest.skip pattern)"

# Metrics
duration: 3min
completed: 2026-02-01
---

# Phase 10 Plan 01: CI Validation Infrastructure Summary

**GitHub Actions validation workflow with PostgreSQL service, database fixtures, and coverage reporting for automated quality gates**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-01T17:33:45Z
- **Completed:** 2026-02-01T17:37:03Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Created validation.yml workflow with PostgreSQL 16 service container and health checks
- Added database fixtures (db_engine, db_session, ensure_schema) for validation tests
- Configured coverage with 70% threshold, JSON and markdown reports
- Integrated pytest-cov and pytest-json-report for comprehensive test reporting

## Task Commits

Each task was committed atomically:

1. **Task 1: Create validation CI workflow with PostgreSQL** - `7dff638` (feat)
2. **Task 2: Create validation test fixtures and package** - `2041a00` (feat)
3. **Task 3: Update pyproject.toml with validation markers and coverage config** - `12bf72e` (feat)

## Files Created/Modified
- `.github/workflows/validation.yml` - CI workflow with PostgreSQL service, pytest validation, coverage reporting
- `tests/validation/conftest.py` - Database fixtures: db_engine (session-scoped), db_session (function-scoped with rollback), ensure_schema (auto-creates dim tables)
- `pyproject.toml` - Added pytest-cov, pytest-json-report deps; validation_gate marker; coverage config (source=src, 70% threshold)

## Decisions Made

**PostgreSQL 16 service container for CI**
- Health checks: pg_isready with 10s interval, 5s timeout, 5 retries
- Database: ta_lab2_validation (isolated from production)
- Rationale: All three validation types require real database per CONTEXT.md (no mock mode)

**Coverage threshold 70%**
- Fail build if coverage drops below 70%
- Balances quality bar with pragmatic testing for v0.4.0 release
- Can be raised in future releases as test coverage improves

**Session-scoped db_engine, function-scoped db_session**
- db_engine created once per test session for efficiency
- db_session provides transaction rollback for test isolation
- Follows Phase 09 three-tier test pattern

**ensure_schema fixture for automatic setup**
- Checks for dim_timeframe and dim_sessions tables
- Calls ensure_dim_tables if missing
- Reduces test setup friction in CI environment

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - workflow, fixtures, and configuration all created successfully on first attempt.

## User Setup Required

None - no external service configuration required. CI workflow automatically provisions PostgreSQL service container.

## Next Phase Readiness

**Ready for Plan 10-02 (Time Alignment Validation Tests):**
- Database fixtures available for validation tests
- PostgreSQL service configured in CI
- Coverage reporting configured
- Validation test directory structure in place

**Ready for Plan 10-03 (Data Consistency Validation Tests):**
- db_session with transaction rollback ensures test isolation
- ensure_schema fixture provides required dim tables

**Ready for Plan 10-04 (Backtest Reproducibility Validation):**
- Coverage reports (JSON/markdown) for release documentation
- validation_gate marker for categorizing critical CI tests

**No blockers or concerns** - validation infrastructure complete and verified.

---
*Phase: 10-release-validation*
*Completed: 2026-02-01*
