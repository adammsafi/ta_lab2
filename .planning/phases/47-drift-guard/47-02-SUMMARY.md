---
phase: 47-drift-guard
plan: 02
subsystem: drift-monitoring
tags: [drift, tracking-error, sharpe, dataclass, numpy, pandas, unit-tests]

# Dependency graph
requires:
  - phase: 46-risk-controls
    provides: RiskEngine, KillSwitch, cmc_risk_events -- drift guard sits above risk layer
  - phase: 45-paper-trading
    provides: PaperExecutor, FillSimulator, ParityChecker -- drift compares paper fills to replay
  - phase: 47-drift-guard plan 01
    provides: cmc_drift_metrics DDL schema -- DriftMetrics fields align to this table
provides:
  - DriftMetrics frozen dataclass (22 fields matching cmc_drift_metrics columns)
  - compute_rolling_tracking_error: rolling std of paper-replay P&L diff via pd.Series.rolling
  - compute_sharpe: annualized Sharpe ratio (mean/std * sqrt(365))
  - compute_drift_metrics: full aggregation function producing DriftMetrics from arrays
  - collect_data_snapshot: MAX(ts) SQL queries for bars/features/EMA per asset
  - 11 passing unit tests covering correctness and edge cases
affects:
  - 47-drift-guard plan 03 (DriftMonitor will call compute_drift_metrics)
  - 47-drift-guard plan 04 (attribution engine uses DriftMetrics fields)
  - 52-operational-dashboard (DriftMetrics maps to cmc_drift_metrics columns)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure computation layer separated from DB/backtest dependencies for testability"
    - "Frozen dataclass for immutable drift measurement records"
    - "pd.Series.rolling(min_periods=window) for strict NaN semantics on insufficient data"
    - "Last non-NaN value extraction for tracking_error_5d / tracking_error_30d from rolling arrays"

key-files:
  created:
    - src/ta_lab2/drift/__init__.py
    - src/ta_lab2/drift/drift_metrics.py
    - src/ta_lab2/drift/data_snapshot.py
    - tests/drift/__init__.py
    - tests/drift/test_drift_metrics.py
  modified: []

key-decisions:
  - "DriftMetrics is frozen=True dataclass -- enforces immutability for a daily measurement record"
  - "compute_sharpe uses ddof=1 (sample std) matching pandas rolling().std() convention"
  - "tracking_error_5d/30d take last non-NaN from rolling array -- None when window not yet reached"
  - "collect_data_snapshot returns ISO strings (not datetime objects) for serialization safety"

patterns-established:
  - "drift package: pure computation module, no DB imports except data_snapshot.py"
  - "Rolling window tracking error: pd.Series.rolling(min_periods=window).std() -- strict NaN on insufficient data"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 47 Plan 02: Drift Metrics Computation Library Summary

**DriftMetrics frozen dataclass + rolling tracking error + Sharpe computation + PIT data snapshot -- pure computation layer with 11 passing unit tests, no DB dependency**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T19:11:06Z
- **Completed:** 2026-02-25T19:14:12Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- Created `src/ta_lab2/drift/` package with 3 modules and public `__init__.py` exporting 5 symbols
- `DriftMetrics` frozen dataclass with 22 fields matching `cmc_drift_metrics` table columns (metric_date through drift_pct_of_threshold)
- `compute_rolling_tracking_error` via `pd.Series.rolling(window, min_periods=window).std()` -- strict NaN semantics when data is insufficient
- `compute_drift_metrics` aggregates paper vs PIT/current replay arrays into a complete DriftMetrics object including cumulative P&L, tracking errors (5d/30d), Sharpe ratios, divergence, threshold breach flag
- `collect_data_snapshot` queries MAX(ts) from 3 tables per asset using sqlalchemy text() -- returns ISO timestamp strings
- 11 unit tests passing: tracking error correctness, Sharpe edge cases, breach detection, cumulative P&L math, data revision diff

## Task Commits

Each task was committed atomically:

1. **Task 1: Create drift package with DriftMetrics and computation functions** - `6da7bf4f` (feat)
2. **Task 2: Unit tests for drift metrics computation** - `ba9e1efd` (test)

## Files Created/Modified

- `src/ta_lab2/drift/__init__.py` - Package init, exports 5 public symbols
- `src/ta_lab2/drift/drift_metrics.py` - DriftMetrics dataclass + compute_rolling_tracking_error + compute_sharpe + compute_drift_metrics (247 lines)
- `src/ta_lab2/drift/data_snapshot.py` - collect_data_snapshot using sqlalchemy text() queries
- `tests/drift/__init__.py` - Empty package init for test discovery
- `tests/drift/test_drift_metrics.py` - 11 unit tests, pure computation, no DB/mock dependencies

## Decisions Made

- **Frozen dataclass**: `DriftMetrics` uses `frozen=True` to enforce immutability -- a daily measurement record should not be mutated after creation
- **Sample std (ddof=1)**: `compute_sharpe` uses `np.std(ddof=1)` and `pd.Series.rolling().std()` both use ddof=1 by default -- consistent with pandas convention
- **Last non-NaN extraction**: `tracking_error_5d` and `tracking_error_30d` take the last non-NaN value from their respective rolling arrays. This means both can be None when the full history has fewer than window days -- threshold_breach is then False
- **ISO strings in snapshot**: `collect_data_snapshot` converts datetime objects to `.isoformat()` strings to avoid tz-aware serialization pitfalls (documented in MEMORY.md)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hooks (ruff lint + mixed-line-ending) reformatted files on first commit attempt. Re-staged reformatted files for second commit. Standard Windows CRLF -> LF conversion.

## User Setup Required

None - no external service configuration required. All functions are pure computation or accept an existing SQLAlchemy connection.

## Next Phase Readiness

- `DriftMetrics` dataclass and all computation functions ready for Plan 03 (DriftMonitor)
- `collect_data_snapshot` ready to be called in executor loop to snapshot PIT data state
- `compute_drift_metrics` signature is the primary entry point DriftMonitor will call daily
- No blockers

---
*Phase: 47-drift-guard*
*Completed: 2026-02-25*
