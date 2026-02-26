---
phase: 53-v1-validation
plan: "04"
subsystem: validation
tags: [plotly, nbformat, jupyter, markdown, report-builder, validation, gate-framework]

# Dependency graph
requires:
  - phase: 53-v1-validation/53-01
    provides: gate framework (GateStatus, GateResult, build_gate_scorecard, AuditSummary)
  - phase: 53-v1-validation/53-02
    provides: AuditChecker (6-check gap detection), DailyValidationLog

provides:
  - ValidationReportBuilder class: comprehensive Markdown + 5 Plotly charts capstone report
  - generate_validation_report.py CLI: --start-date, --end-date, --no-notebook, --no-charts flags
  - Jupyter notebook (11 cells): executable re-query cells for gate scorecard, equity curve, slippage, tracking error, audit
  - nbformat>=5.0 in pyproject.toml optional-dependencies (validation + all groups)
  - validation/__init__.py: complete package exports with try/except graceful degradation

affects:
  - phase: 54-v1-results-memo (reads V1_VALIDATION_REPORT.md as primary input)
  - phase: 55-feature-evaluation (references Phase 53 methodology)

# Tech tracking
tech-stack:
  added: [nbformat>=5.0 (declared, not yet installed)]
  patterns:
    - Graceful chart skip pattern (return None from chart builder when no data)
    - Notebook generation with try/except ImportError for optional nbformat dep
    - Sign convention documentation in equity curve chart (fills-based vs mark-to-market)

key-files:
  created:
    - src/ta_lab2/validation/report_builder.py
    - src/ta_lab2/scripts/validation/generate_validation_report.py
  modified:
    - src/ta_lab2/validation/__init__.py
    - pyproject.toml

key-decisions:
  - "ValidationReportBuilder.generate_report() returns absolute path string for CLI consumption"
  - "5 chart builders each return Optional[str] -- gracefully None when no data (no fills/drift/risk events)"
  - "Equity curve chart includes subtitle note on sign convention: fills P&L = realized cash flow; drift replay = mark-to-market"
  - "Notebook generation is a standalone function _generate_notebook() with try/except ImportError on nbformat"
  - "validation/__init__.py uses try/except ImportError for non-core imports (only gate_framework is required)"
  - "nbformat in both 'validation' group (targeted install) and 'all' group (full install)"

patterns-established:
  - "Chart builder pattern: query -> check empty -> build Plotly fig -> _save_chart() -> return rel path or None"
  - "CLI pattern: argparse + create_engine + instantiate builder + call generate_report + optional notebook"

# Metrics
duration: 6min
completed: 2026-02-26
---

# Phase 53 Plan 04: Validation Report Builder Summary

**ValidationReportBuilder capstone: Markdown report + 5 Plotly charts (graceful None when no data) + Jupyter notebook with 11 executable cells; nbformat dep and complete package exports**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-26T18:37:41Z
- **Completed:** 2026-02-26T18:43:10Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `ValidationReportBuilder` class: `generate_report()` assembles comprehensive Markdown from gate scorecard + 5 chart types + per-VAL narratives + methodology + data sources appendix
- 5 Plotly chart builders: equity curve overlay (fills vs drift replay with sign convention note), drawdown, tracking error (5d/30d with 1% threshold line), slippage histogram (50 bps threshold), kill switch event timeline (color-coded by exercise/real)
- `generate_validation_report.py` CLI: `--start-date`, `--end-date`, `--output-dir`, `--db-url`, `--no-notebook`, `--no-charts`
- Jupyter notebook generation: 11 cells (5 code + 6 markdown), includes `from IPython.display import display` in setup cell; gracefully skips if nbformat not installed
- `nbformat>=5.0` added to `validation` and `all` optional-dependency groups in `pyproject.toml`
- `validation/__init__.py` updated to export all 9 public symbols with try/except graceful degradation

## Task Commits

1. **Task 1: Report builder library + charts** - `f39ab4eb` (feat)
2. **Task 2: CLI + Jupyter notebook + nbformat dep + package exports** - `92e9e747` (feat)

**Plan metadata:** See docs commit below

## Files Created/Modified

- `src/ta_lab2/validation/report_builder.py` (created, 1003 lines) -- ValidationReportBuilder with 5 chart generators, _df_to_markdown(), _save_chart(), _embed_chart() helpers
- `src/ta_lab2/scripts/validation/generate_validation_report.py` (created) -- CLI + _generate_notebook() function
- `src/ta_lab2/validation/__init__.py` (modified) -- complete exports with try/except pattern
- `pyproject.toml` (modified) -- nbformat in validation + all groups

## Decisions Made

- Used `Optional[str]` return type for chart builders: `None` means no data (skip chart), path string means chart saved. This avoids errors during the 14-day window when fills/drift data may be sparse.
- Sign convention divergence explicitly documented in equity curve chart subtitle and Methodology section: fills P&L = realized cash flow; drift replay P&L = mark-to-market. Divergence is expected for open positions.
- Notebook is generated as a standalone function `_generate_notebook()` separate from `ValidationReportBuilder`, so it can be called independently or skipped via `--no-notebook`.
- `validation/__init__.py` uses `try/except ImportError` for all non-gate-framework imports. The gate framework is the only hard dependency; audit_checker, daily_log, and report_builder are all optional (allows partial package use if some deps missing).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hooks (ruff + mixed-line-ending) auto-fixed CRLF line endings and 3 ruff style issues on first commit attempt. Re-staged and committed successfully on second attempt.

## User Setup Required

None - no external service configuration required. nbformat must be installed separately (`pip install nbformat`) for notebook generation; CLI handles missing nbformat gracefully with a printed warning.

## Next Phase Readiness

- Phase 53 is now fully complete (all 4 plans: 53-01 gate framework, 53-02 daily log + audit, 53-03 kill switch exercise, 53-04 report builder)
- Phase 54 (V1 Results Memo) can use `generate_validation_report --start-date ... --end-date ...` to generate the V1_VALIDATION_REPORT.md input document
- All 9 public symbols exported from `ta_lab2.validation` package
- To generate a report: `python -m ta_lab2.scripts.validation.generate_validation_report --start-date 2026-03-01 --end-date 2026-03-14`

---
*Phase: 53-v1-validation*
*Completed: 2026-02-26*
