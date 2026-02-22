# Phase 29: Stats/QA Orchestration - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the 5 existing stats runners into `run_daily_refresh.py` as the final pipeline stage (--stats flag, included in --all). Build a weekly QC digest that aggregates PASS/WARN/FAIL across all stats tables and sends via Telegram. Gate the pipeline on FAIL status. Add timeout= to all existing subprocess.run() calls across the codebase.

</domain>

<decisions>
## Implementation Decisions

### Pipeline failure behavior
- Run ALL stats runners to completion even if some FAIL — collect full picture first
- After all stats finish, if ANY returned FAIL: halt the pipeline, send Telegram alert with which runners failed and why
- WARN status: log the warning + send Telegram alert, but continue pipeline execution
- Stats runners are the LAST stage — pipeline order is bars -> EMAs -> regimes -> stats
- If stats FAIL, no downstream consumers should use the data (pipeline halts before returning success)

### Weekly QC digest format
- Include ALL detail levels: top-level summary (X pass / Y warn / Z fail), per-table breakdown, and per-test detail
- Show week-over-week deltas (e.g., "returns stats: PASS -> WARN" or "3 new FAILs since last week")
- Must be invocable BOTH ways: standalone script (`python -m ta_lab2.scripts.stats.weekly_digest`) AND via orchestrator flag (`--weekly-digest` or similar)
- Telegram delivery for the digest report

### Stats runner ordering and integration
- Wrap existing stats runner scripts — do NOT rewrite or replace them
- Existing runners: bars stats, 3x EMA stats (multi_tf, cal, cal_anchor), returns stats, features stats
- Integration point: new orchestrator module that calls existing runners, collects results, applies pass/fail logic
- The --stats flag follows the same CLI pattern as --bars, --emas, --regimes

### Subprocess timeout strategy
- Add timeout= parameter to ALL existing subprocess.run() calls across the entire codebase (not just stats)
- On timeout: log the error, send Telegram alert, continue with remaining pipeline steps (don't let one hung process block everything)
- Timeout prevents silent hangs — especially important on Windows where processes can hang indefinitely

### Claude's Discretion
- Specific timeout values for each subprocess call (profile actual runtimes to set reasonable values)
- Whether timeouts are tiered (short for quick scripts, long for heavy compute) or uniform
- Criticality tiers for stats tests (which FAILs are critical vs which are advisory)
- Recovery suggestions in failure messages
- Execution mode for stats runners (sequential vs parallel)
- Granularity of --stats flag (single flag vs per-runner flags)
- Weekly digest scheduling mechanism (cron hint vs manual)
- Exact Telegram message formatting

</decisions>

<specifics>
## Specific Ideas

- Existing stats runners already produce PASS/WARN/FAIL output — leverage this directly rather than inventing new status codes
- The `run_all_audits.py` pattern (orchestrates 17 audit scripts, writes to `audit_results` table) is a good reference for how to orchestrate multiple stats runners
- Existing Telegram module at `ta_lab2.notifications.telegram` with severity enum — reuse for all alerting
- Stats runners write to dedicated stats tables (e.g., `cmc_price_bars_stats`, `cmc_ema_multi_tf_stats`) — digest should query these tables

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 29-stats-qa-orchestration*
*Context gathered: 2026-02-22*
