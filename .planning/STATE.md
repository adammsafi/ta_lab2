# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-05)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v0.7.0 Regime Integration & Signal Enhancement

## Current Position

Phase: 27 of 28 (Regime Integration)
Plan: 7 of 7 in current phase (Tasks 1-2 complete, awaiting checkpoint verification)
Status: Checkpoint reached — awaiting human verification of end-to-end pipeline
Next Phase: Phase 28 (Backtest Pipeline Fix)
Last activity: 2026-02-20 — Completed 27-07-PLAN.md Tasks 1-2 (Orchestrator integration + regime_inspect.py)

Progress: [##########] 100% v0.4.0 | [##########] 100% v0.5.0 | [##########] 100% v0.6.0 (7/7 phases) | [######----] ~50% v0.7.0 (7/14 plans)

## Performance Metrics

**Velocity:**
- Total plans completed: 142 (56 in v0.4.0, 56 in v0.5.0, 30 in v0.6.0)
- Average duration: 7 min
- Total execution time: ~28 hours

**By Phase (v0.4.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 01-foundation-quota-management | 3 | 23 min | 8 min | Complete |
| 02-memory-core-chromadb-integration | 5 | 29 min | 6 min | Complete |
| 03-memory-advanced-mem0-migration | 6 | 193 min | 32 min | Complete |
| 04-orchestrator-adapters | 4 | 61 min | 15 min | Complete |
| 05-orchestrator-coordination | 6 | 34 min | 6 min | Complete |
| 06-ta-lab2-time-model | 6 | 37 min | 6 min | Complete |
| 07-ta_lab2-feature-pipeline | 7 | 45 min | 6 min | Complete |
| 08-ta_lab2-signals | 6 | 49 min | 8 min | Complete |
| 09-integration-observability | 7 | 260 min | 37 min | Complete |
| 10-release-validation | 8 | 34 min | 4 min | Complete |

**By Phase (v0.5.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 11-memory-preparation | 5 | 46 min | 9 min | Complete |
| 12-archive-foundation | 3 | 11 min | 4 min | Complete |
| 13-documentation-consolidation | 7 | 30 min | 4 min | Complete |
| 14-tools-integration | 13 | 128 min | 10 min | Complete |
| 15-economic-data-strategy | 6 | 36 min | 6 min | Complete |
| 16-repository-cleanup | 7 | 226 min | 32 min | Complete |
| 17-verification-validation | 8 | 38 min | 5 min | Complete |
| 18-structure-documentation | 4 | 21 min | 5 min | Complete |
| 19-memory-validation-release | 6 | 90 min | 15 min | Complete |

**Recent Trend:**
- v0.4.0 complete: 10 phases, 56 plans, 12.55 hours total
- v0.5.0 complete: 9 phases, 56 plans, 9.85 hours total
- v0.6.0 complete: 7 phases, 30 plans, ~3.80 hours total

**By Phase (v0.6.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 20-historical-context | 3/3 | 17 min | 6 min | Complete |
| 21-comprehensive-review | 4/4 | 29 min | 7 min | Complete |
| 22-critical-data-quality-fixes | 6/6 | 82 min | 14 min | Complete |
| 23-reliable-incremental-refresh | 4/4 | 17 min | 4 min | Complete |
| 24-pattern-consistency | 4/4 | 40 min | 10 min | Complete |
| 25-baseline-capture | 2/2 | 11 min | 6 min | Complete |
| 26-validation | 3/3 | ~120 min | ~40 min | Complete |

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- **Review first, then fix** (v0.6.0): Complete ALL analysis before code changes
- **Keep all 6 EMA variants** (v0.6.0): They exist for legitimate reasons (calendar alignment, ISO vs US, anchoring)
- **Bars and EMAs separate** (v0.6.0): Modular design, not tightly coupled
- **Move quickly on data sources** (v0.6.0): Bar tables have better validation, switch over decisively
- **Whatever it takes timeline** (v0.6.0): Do it right, even if it takes 6-8 weeks
- **Leverage proven Phase 6-7 patterns** (Phase 20): dim_timeframe, unified EMA table, state management are working - extend to bars, don't rebuild
- **EMAs already use bar tables** (Phase 20): CRITICAL - All 6 EMA variants already migrated to validated bars. Phase 22 assumption invalid, requires re-scoping.
- **All 6 EMA variants exist for legitimate reasons** (Phase 21): 80%+ infrastructure shared (BaseEMARefresher, EMAStateManager, compute_ema) with 20% intentional differences (data source, calendar alignment, anchoring) - NOT code duplication
- **Gap severity framework established** (Phase 21-04): CRITICAL (data corruption), HIGH (error-prone), MEDIUM (workarounds), LOW (nice-to-have) - 15 gaps identified (4 CRITICAL, 5 HIGH, 4 MEDIUM, 2 LOW), prioritized for Phase 22-24
- **Asset onboarding documented** (Phase 21-04): 6-step checklist (dim_assets → 1D bars → multi-TF bars → EMAs → validate → verify incremental), 15-40 minutes per asset
- **Hybrid EMA validation** (Phase 22-02): Wide price bounds (0.5x-2x) catch corruption, narrow statistical bounds (3σ) catch drift - batched queries achieve <2% overhead
- **Warn and continue for EMA violations** (Phase 22-02): Write all EMAs even if invalid, log to both ema_rejects table and WARNING logs for maximum visibility
- **Derive multi-TF from 1D bars** (Phase 22-04/22-05): All 5 multi-TF builders support optional --from-1d derivation with calendar alignment - creates single source of truth for bar data quality
- **Reject tables dual purpose** (Phase 22-01): Multi-TF reject tables log OHLC repairs pre-derivation AND validate aggregation post-derivation - complete audit trail with violation_type + repair_action columns
- **Subprocess isolation for orchestrators** (Phase 23-01): EMA orchestrator refactored to use subprocess.run instead of runpy for process isolation, matching bar orchestrator pattern with dry-run and summary reporting
- **Unified daily refresh with state checking** (Phase 23-02): Single command for daily refresh (run_daily_refresh.py --all) with state-based bar freshness checking before EMAs - stale IDs are logged and skipped to prevent EMA computations on incomplete data
- **Makefile convenience layer** (Phase 23-03): make bars/emas/daily-refresh for common operations, Python-based date formatting for cross-platform compatibility
- **Daily log files with rotation** (Phase 23-03): .logs/refresh-YYYY-MM-DD.log for audit trail, automatic rotation (30 days default)
- **Severity-based Telegram alerting** (Phase 23-03): AlertSeverity enum filters alerts (default: ERROR+), send_critical_alert() for database/corruption errors
- **Preserve psycopg for SQL performance in 1D builder** (Phase 24-02): 1D bar builder uses large CTEs with complex aggregations - raw psycopg execution 2-3x faster than SQLAlchemy for this workload
- **Modernize CLI for BaseBarBuilder consistency** (Phase 24-02): Space-separated IDs, --full-rebuild flag for consistency across all bar builders using BaseBarBuilder
- **26.7% LOC reduction acceptable for SQL-based builders** (Phase 24-02): 1D builder achieved 260 lines saved (971→711) despite SQL-heavy implementation limiting code reuse with DataFrame-based base class
- **46% LOC reduction for calendar builders** (Phase 24-04): All 4 calendar builders refactored (5991→3230 lines), preserving calendar alignment (US Sunday vs ISO Monday) and anchor window logic despite complex semantics
- **tz column design documented (GAP-M03 closed)** (Phase 24-04): Calendar state tables use tz as metadata only, NOT in PRIMARY KEY - single timezone per run design is intentional, not a bug
- **NumPy allclose hybrid tolerance for baseline comparison** (Phase 25-01): Combine absolute (atol) + relative (rtol) tolerance to handle both small values near zero and large values correctly - avoids false positives/negatives from single epsilon threshold
- **Column-specific tolerances** (Phase 25-01): Price (1e-6/1e-5) vs volume (1e-2/1e-4) - different data types need different precision requirements
- **NaN == NaN is match** (Phase 25-01): Treat NaN == NaN as match using equal_nan=True to avoid SQL NULL semantics issues (NULL != NULL)
- **Git-based audit trail for baseline capture** (Phase 25-01): Capture git commit hash + timestamp + config in BaselineMetadata for full reproducibility 3 months later
- **Snapshot -> Truncate -> Rebuild -> Compare workflow** (Phase 25-02): Atomic validation pattern proves refactoring correctness by comparing identical input → output transformations
- **Intelligent sampling (beginning/end/random)** (Phase 25-02): 30 days beginning + 30 days end + 5% random interior balances speed and confidence - detects temporal drift while avoiding full table scans
- **Never fail early in baseline capture** (Phase 25-02): Always run to completion, report ALL issues - partial results hide systemic problems
- **Subprocess isolation for baseline workflow** (Phase 25-02): Run bar builders and EMA refreshers via subprocess.run matching Phase 23 patterns (run_daily_refresh.py)
- **cmc_regime_comovement PK includes computed_at** (Phase 27-01): Retains historical snapshots across refreshes - each refresh snapshot preserved for temporal analytics
- **regime_key nullable on signal tables** (Phase 27-01): Existing signals have NULL regime_key, backward-compatible, signal generators populate going forward
- **regime_enabled defaults TRUE on dim_signals** (Phase 27-01): All existing signals automatically participate in regime-aware execution, opt-out is explicit
- **int cast before period sort in pivot_emas_to_wide** (Phase 27-02): Cast period to int before sorting column names -- prevents alphabetic trap where '200' < '50'; ensures close_ema_20 < close_ema_50 < close_ema_200
- **aggfunc='first' in pivot_table for EMA deduplication** (Phase 27-02): Defensive choice; plain pivot() raises ValueError on duplicates, pivot_table silently takes first value -- safer for production pipeline
- **HysteresisTracker tightening via size_mult/stop_mult** (Phase 27-04): Tightening = new size < old OR new stop > old; uses public resolve_policy_from_table not private _match_policy to stay decoupled from resolver internals
- **Flip detection includes initial assignment (old=None)** (Phase 27-04): First regime seen per (id,tf,layer) is recorded as flip with old_regime=None for full audit trail
- **Comovement scoped DELETE removes all prior snapshots** (Phase 27-04): write_comovement_to_db deletes all rows for (ids,tf) before insert, so each refresh leaves exactly one snapshot -- prevents unbounded table growth
- **BTC (id=1) as market proxy, skipped for self** (Phase 27-03): When computing regimes for id=1, skip proxy loading to avoid circular self-reference; proxy only applies for other assets lacking L0/L1 history
- **regime_key fallback chain L2->L1->L0->Unknown** (Phase 27-03): "Unknown" sentinel avoids None in NOT NULL column; L2 (daily) is primary as it has most bars
- **Row-by-row policy resolution acceptable** (Phase 27-03): 5614 rows resolves in ~2.4s total (DB I/O dominates); vectorization not needed for daily refresh cadence
- **regime_enabled defaults True on signal generators** (Phase 27-06): Opt-out pattern means all existing refresh workflows become regime-aware automatically; --no-regime flag for explicit A/B comparison
- **Graceful fallback on empty cmc_regimes** (Phase 27-06): load_regime_context_batch wraps SQL in try/except; merge_regime_context with empty df adds NULL columns - signals generate as before when regime table is empty
- **RSI regime_key via post-transform merge** (Phase 27-06): RSI transform_signals_to_records uses mutable dict update-in-place pattern; regime_key attached after via (id, entry_ts) join rather than inline to avoid structural changes to the transform method
- **Per-asset hysteresis tracker reset** (Phase 27-05): tracker.reset() before each asset prevents prior asset state leaking into next; critical for correctness when processing --all
- **Returns fallback to NULL stats** (Phase 27-05): _load_returns_for_id wraps in try/except; DEBUG-level log avoids noise; avg_ret_1d/std_ret_1d are NULL until cmc_returns.ret_1d column populated
- **Reload daily_df for comovement** (Phase 27-05): Reload via load_regime_input_data rather than threading through compute_regimes_for_id return; cleaner separation of concerns
- **--regimes standalone flag plus --all inclusion** (Phase 27-07): Consistent with --bars/--emas pattern; --all becomes single command for bars->EMAs->regimes pipeline
- **EMA early-stop before regimes** (Phase 27-07): Added failure check before running regimes - regimes depend on fresh EMAs; propagates --dry-run to regime subprocess
- **regime_inspect default reads from DB** (Phase 27-07): Operational check should be fast; --live flag triggers compute_regimes_for_id for testing changes before write

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-02-20T19:54:22Z
Stopped at: 27-07-PLAN.md Tasks 1-2 complete — awaiting checkpoint verification (Task 3: human-verify end-to-end pipeline)
Resume file: None

---

## Milestone Context (v0.7.0)

**Goal:** Connect regime module to DB pipeline and fix backtest pipeline so strategies can be validated end-to-end

**Key Principles:**
- Leverage existing regime module (13 files, fully built) - integration, not greenfield
- Calendar-anchored weekly/monthly bars already exist - regime labelers just need column mapping
- Fix serialization bugs before adding features - backtest pipeline must work first
- Signal generators need regime awareness for position sizing/filtering

**Phase Summary:**
- Phase 27: Regime Integration (connect regime labels/policy to DB, wire into signals)
- Phase 28: Backtest Pipeline Fix (fix dict serialization bug, vectorbt timestamps, end-to-end validation)

### Roadmap Evolution
- Phase 27 added: Regime Integration - connect existing regime module to DB-backed feature pipeline
- Phase 28 added: Backtest Pipeline Fix - fix signal generators and backtest runner end-to-end

---
*Created: 2025-01-22*
*Last updated: 2026-02-20 (v0.7.0 started: Phases 27-28 added)*
