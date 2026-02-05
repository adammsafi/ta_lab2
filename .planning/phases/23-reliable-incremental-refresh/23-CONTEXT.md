# Phase 23: Reliable Incremental Refresh - Context

**Gathered:** 2026-02-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Create unified orchestration for daily bar and EMA refresh with clear visibility into what happened. Users should have one command that "just works" for daily refresh, with fine-grained control for troubleshooting/partial refreshes. Phase delivers reliable orchestration, not new data processing capabilities.

</domain>

<decisions>
## Implementation Decisions

### Orchestration Invocation Strategy

**Multiple entry points for different use cases:**

1. **Unified Python script** (`run_daily_refresh.py`):
   - Primary entry point for daily refresh workflow
   - **Requires explicit targets** (--bars, --emas, or --all)
   - No default behavior - user must specify what to run (intentional, prevents accidents)
   - Coordinates bars → EMAs dependency with state-based checking

2. **Enhanced separate scripts**:
   - Keep `run_all_bar_builders.py` (already well-structured)
   - **Enhance `run_all_ema_refreshes.py`** to match bar orchestrator quality:
     - Use subprocess instead of runpy (better isolation)
     - Add dry-run, verbose control, better error handling
     - Match bar orchestrator's CLI structure and summary reporting

3. **Makefile targets** (convenience layer):
   - `make bars` - Run all bar builders
   - `make emas` - Run all EMA refreshers
   - `make daily-refresh` - Full bars + EMAs workflow
   - `make validate` - Run validation/checks after refresh
   - `make dry-run` - Show what would execute without running

### Modular Separation (Bars ↔ EMAs)

**Coordination strategy:**
- Support **both sequential and separate invocation** based on arguments:
  - `--all` → sequential (bars first, then EMAs)
  - `--bars` or `--emas` → separate invocation (user controls order)
- Default to sequential for safety, allow separate for power users

**Interface contract:**
- **State-based check** before EMAs run:
  - EMAs query bar state tables to verify bars are up-to-date
  - Check: `SELECT id, last_src_ts FROM cmc_price_bars_1d_state` and compare to source
  - Proceed only if bars are fresh (no lag > threshold, e.g., 1 day)

**Partial failure handling:**
- **Skip failed IDs only** (don't fail entire EMA run):
  - If bars failed for ID 825, run EMAs for ID 1 and 52 only
  - Log skipped IDs clearly: "Skipping ID 825 EMAs (bars failed)"
  - Partial refresh better than no refresh

### Execution Control

**Supported filters** (fine-grained control for targeted refreshes):
- `--ids X,Y,Z` (already supported) - specific assets only
- `--tfs 1d,7d` (new) - specific timeframes only, skip others
- `--periods 10,20,50` (new) - specific EMA periods only
- `--tf-period-combos 7d:10,7d:20` (new) - specific TF+period pairs
- `--resume` (new) - continue from where last run failed

**Resume mechanism:**
- Track progress via **database state tables** (source of truth):
  - Query `last_src_ts` from state tables to determine what's already fresh
  - No separate state file - DB state is authoritative
  - Resume = skip IDs where `last_src_ts` is current

**Execution priority:**
- **No prioritization** - current order is fine:
  - Bars: 1d → multi_tf → cal_us → cal_iso → cal_anchor_us → cal_anchor_iso
  - EMAs: multi_tf → cal → cal_anchor → v2
  - This order has proven reliable in Phases 6-7

### Visibility and Reporting

**Logging style:**
- **Verbose by default** with summary at end:
  - Show progress during run: "Processing ID 1... 245 bars written (3.2s)"
  - Final summary with all metrics
- **--quiet flag** for minimal output (cron-friendly):
  - Only show summary at end, suppress streaming progress
  - Errors still logged even in quiet mode

**Summary metrics** (what users need to know):
- **Counts**: X bars written, Y EMAs written, Z rows processed
- **Time per component**: "1d bars: 23s, multi_tf bars: 145s, multi_tf EMAs: 67s"
- **Gaps flagged**: Count of is_missing_days, backfills detected, quality flags
- **Errors/rejects**: OHLC repairs logged, EMA violations, NULL rejections
- **Progress tracking**: "3/6 builders complete, ~8 minutes remaining"
- **What's remaining**: List pending builders/IDs with estimated time

**Log destinations:**
- **Both stdout + daily log files**:
  - Console output for interactive monitoring
  - Persistent logs: `.logs/refresh-YYYY-MM-DD.log` for audit trail
  - Rotate daily, keep last 30 days

**Alerting:**
- **Extend existing Telegram alerting** (from run_all_ema_refreshes.py):
  - Alert on validation failures (gaps, duplicates, missing data)
  - Alert on critical errors (database connection, OHLC corruption thresholds)
  - Configurable via --alert-on-error flag
  - Build on existing is_configured() pattern

### Claude's Discretion

**Implementation details left to planning:**
- Exact subprocess vs threading strategy for parallel execution
- State staleness threshold (1 day? 2 days? configurable?)
- Progress estimation algorithm (linear? historical average?)
- Error retry logic (how many retries, backoff strategy)
- Log rotation implementation (built-in or external tool)
- Telegram alert message format and severity levels

</decisions>

<specifics>
## Specific Ideas

**Existing patterns to preserve:**
- Bar orchestrator subprocess isolation (works well)
- Bar orchestrator's BuilderConfig pattern (clean abstraction)
- Bar orchestrator's summary report format (clear, informative)
- EMA orchestrator's validation integration (--validate flag)

**Existing patterns to improve:**
- EMA orchestrator uses runpy (switch to subprocess for consistency)
- EMA orchestrator lacks dry-run and verbose control (add these)
- No unified bars+EMAs script yet (create this)

**From Phase 6-7 proven patterns:**
- State management with last_src_ts watermarking (works reliably)
- Incremental refresh with lookback window (handles late-arriving data)
- Quality flags (is_missing_days, is_partial_end) for diagnostics

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope (orchestration, state, visibility). All enhancements fit cleanly within "reliable incremental refresh" domain.

</deferred>

---

*Phase: 23-reliable-incremental-refresh*
*Context gathered: 2026-02-05*
