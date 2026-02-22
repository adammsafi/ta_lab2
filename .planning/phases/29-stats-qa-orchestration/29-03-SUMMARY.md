---
phase: 29-stats-qa-orchestration
plan: 03
subsystem: infra
tags: [stats, weekly-digest, telegram, data-quality, orchestration, subprocess]

# Dependency graph
requires:
  - phase: 29-02
    provides: run_all_stats_runners.py, TIMEOUT_STATS=3600, --stats pipeline stage -- weekly_digest reuses the same timeout tier and Telegram patterns
  - phase: 23-reliable-incremental-refresh
    provides: Telegram send_alert/send_message pattern -- weekly_digest uses same API

provides:
  - weekly_digest.py: Standalone weekly QC digest with PASS/WARN/FAIL across 7 tables + week-over-week delta
  - --weekly-digest flag on run_daily_refresh.py: Standalone reporting invocation
  - build_weekly_summary(): Returns per-table rows + aggregate totals for this week and last week
  - build_weekly_delta(): Week-over-week aggregate FAIL/WARN delta string
  - Telegram split/truncate logic: Primary summary + optional secondary breakdown (4000-char limit)
  - STAT-02 fully satisfied: proactive weekly QC visibility via Telegram + stdout

affects:
  - 30-code-quality-tooling: ruff will sweep weekly_digest.py and updated run_daily_refresh.py
  - 31-documentation-freshness: --weekly-digest flag should appear in pipeline docs/runbooks
  - 32-runbooks: weekly digest is a key operational command for quality monitoring

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Weekly digest pattern: query 7-day and 7-14-day windows, compare aggregate counts (NOT row-level -- delete-before-insert means last-week rows may be absent)"
    - "Telegram split pattern: try single message first, truncate to top-5 FAILs, then split into two messages as final fallback"
    - "Dry-run isolation: no DB engine created in --dry-run mode (print table list and exit 0 immediately)"
    - "--weekly-digest standalone: resolve DB URL before early exit so DB connection errors surface, but ID parsing is skipped"

key-files:
  created:
    - src/ta_lab2/scripts/stats/weekly_digest.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Aggregate comparison for delta (NOT row-level): delete-before-insert means last-week rows for un-impacted keys may not be present -- aggregate totals are the only reliable basis for week-over-week comparison"
  - "Dry-run exits before DB engine creation: weekly_digest.py --dry-run prints table list without creating SQLAlchemy engine -- safe for CI/verification where no DB is available"
  - "Weekly digest NOT in --all: digest is a reporting operation, not a pipeline stage -- --all runs bars+EMAs+regimes+stats; digest is a separate concern"
  - "Telegram message split strategy: try combined first (<4000 chars), then top-5-FAILs truncation, then two-message split -- handles large stats tables gracefully"

patterns-established:
  - "Standalone-then-exit: --weekly-digest resolves DB URL then calls run_weekly_digest() and returns immediately, bypassing all pipeline logic"
  - "7-day window: this week = last 7 days from today's midnight; last week = 7-14 days ago -- consistent anchor for reproducible comparisons"

# Metrics
duration: 3min
completed: 2026-02-22
---

# Phase 29 Plan 03: Weekly QC Digest Summary

**Weekly QC digest script (weekly_digest.py) with PASS/WARN/FAIL aggregation across 7 tables, week-over-week delta, Telegram delivery with split/truncate for 4096-char limit, and --weekly-digest flag on run_daily_refresh.py**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-22T22:10:15Z
- **Completed:** 2026-02-22T22:13:21Z
- **Tasks:** 2/2
- **Files created/modified:** 2

## Accomplishments
- New `src/ta_lab2/scripts/stats/weekly_digest.py` (500+ lines) with DIGEST_TABLES (7 tables), query_period_status(), build_weekly_summary(), build_weekly_delta(), format_digest(), send_digest(), and main()
- 7-day and 7-14-day window comparison using Python `timedelta` (not SQL INTERVAL, for cross-DB portability and parametrized safety)
- Week-over-week delta compares AGGREGATE FAIL/WARN totals (correct approach for delete-before-insert stats tables)
- Telegram delivery: single message if under 4000 chars, top-5-FAIL truncation if needed, two-message split as final fallback
- `run_daily_refresh.py --weekly-digest` invokes digest as standalone subprocess; exits immediately (not part of --all pipeline)
- `--dry-run` propagated from orchestrator to subprocess -- no live DB connection during CI/verification
- STAT-02 fully satisfied: weekly digest aggregates PASS/WARN/FAIL with Telegram delivery, proactive quality visibility

## Task Commits

Each task was committed atomically:

1. **Task 1: Create weekly QC digest script** - `a89b9699` (feat)
2. **Task 2: Wire --weekly-digest flag into run_daily_refresh.py** - `8b497b56` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/ta_lab2/scripts/stats/weekly_digest.py` - Weekly QC digest: 7-table query, delta comparison, Telegram delivery, dry-run mode
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added run_weekly_digest(), --weekly-digest argument, standalone-then-exit routing, updated docstring and help

## Decisions Made
- **Aggregate comparison for delta (NOT row-level):** The delete-before-insert pattern in stats runners means last week's rows for keys that weren't re-checked may not be present. Aggregate totals (sum of PASS/WARN/FAIL across all rows for the 7-day window) are the only reliable basis for week-over-week comparison. This matches the plan's explicit note.
- **Dry-run exits before DB engine creation:** `weekly_digest.py --dry-run` prints the table list and exits 0 without creating a SQLAlchemy engine. This is safer than creating an engine and not using it. The plan specified "skip DB queries AND skip Telegram delivery" -- engine creation is skipped entirely.
- **Weekly digest NOT included in --all:** Digest is a reporting operation that should be run on demand (e.g., Sundays), not as part of the daily pipeline. `--all` runs the data refresh pipeline (bars+EMAs+regimes+stats). Weekly digest is a separate concern invoked via `--weekly-digest`.
- **Telegram split strategy:** Try combined message first (most common path). If over 4000 chars, truncate to top-5-FAIL tables in a single message. If still over 4000, split into two messages (primary summary + secondary breakdown). Covers all realistic scales of the 7-table digest.

## Deviations from Plan

None - plan executed exactly as written. Pre-commit hooks reformatted Task 1 file (ruff format + mixed-line-ending fix); re-staged and committed successfully on second attempt as expected.

## Issues Encountered
- Pre-commit hooks reformatted `weekly_digest.py` on first commit attempt (ruff format for long lines, mixed-line-ending fix for Windows CRLF). Re-staged after auto-format, committed successfully on second attempt. Expected behavior from established pre-commit setup.

## User Setup Required
None - no external service configuration required. Telegram delivery is optional (graceful fallback when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured).

## Next Phase Readiness
- STAT-02 fully satisfied: weekly QC digest aggregates PASS/WARN/FAIL across 7 tables with week-over-week deltas and Telegram delivery
- Phase 29 (3/3 plans) complete -- all STAT objectives satisfied:
  - STAT-01: --stats wired into standalone + --all pipeline (29-02)
  - STAT-02: weekly digest with Telegram delivery (29-03)
  - STAT-03: FAIL halts pipeline, WARN continues with Telegram alert (29-02)
  - STAT-04: Subprocess timeouts on all existing calls (29-01)
- Phase 30 (Code Quality Tooling) is unblocked: ruff will sweep all new stats code
- Phase 32 (Runbooks) should document `python run_daily_refresh.py --weekly-digest` as the weekly quality check command

---
*Phase: 29-stats-qa-orchestration*
*Completed: 2026-02-22*
