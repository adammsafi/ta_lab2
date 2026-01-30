# Phase 9: Integration & Observability - Context

**Gathered:** 2026-01-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Cross-system validation proving memory + orchestrator + ta_lab2 work together through end-to-end workflows, comprehensive observability infrastructure, and alignment/gap testing. Validates three parallel tracks (memory, orchestrator, ta_lab2) integrate correctly with proper monitoring to detect issues.

Scope: Integration tests, observability implementation, workflow validation, gap/alignment testing. Performance optimization and production deployment are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Test Infrastructure and Scope

**Integration test levels:**
- **Both component and E2E** — Start with component pairs (memory↔orchestrator, orchestrator↔ta_lab2), build up to full workflows
- Component tests validate pairs work correctly
- E2E tests validate complete user request → orchestrator → memory → ta_lab2 → results flow

**External dependency handling:**
- **Three-tier approach** based on test type:
  1. **Real components (database, Qdrant, OpenAI)** — Integration tests require actual infrastructure, skip if not available
  2. **Mix: real database/Qdrant, mock AI APIs** — Core infra real, expensive APIs mocked to control costs
  3. **Fully mocked for CI/CD** — All external deps mocked for fast feedback, tests run anywhere
- Test annotations indicate which tier they belong to

**Test data strategy:**
- **Combination approach:**
  - **Fixtures** for unit/component tests — Small datasets (10-20 assets, 100 bars), fast, deterministic
  - **Synthetic data** for E2E tests — Programmatic generation, flexible, covers various scenarios
  - **Production samples** for edge cases — Real data subset for realistic validation (requires production access)

**Test failure reporting:**
- **Claude's discretion** — Choose appropriate reporting for different test types
- Likely: pytest output for unit tests, detailed logs + artifacts for integration, HTML reports for E2E

### Observability Implementation

**Observability dimensions (all four):**
- **Logging** — Structured logs with correlation IDs across systems
- **Metrics** — Counters, gauges, histograms for performance and health
- **Traces** — Distributed tracing across orchestrator → memory → ta_lab2
- **Health checks** — Liveness/readiness endpoints for each component

**Observability storage:**
- **Database tables** — Store in PostgreSQL for queryable observability data with SQL
- Integrated with existing data infrastructure
- Enables historical analysis and correlation with business metrics

**Alert thresholds (all four):**
- **Integration failures** — Alert when orchestrator → memory or orchestrator → ta_lab2 flow breaks
- **Performance degradation** — Alert when task execution >2x baseline duration
- **Data quality issues** — Alert on gap detection, alignment failures, reproducibility mismatches
- **Resource exhaustion** — Alert on quota limits, memory usage, database connections

**Alert delivery:**
- **Telegram (existing integration) + logs** — Leverage existing FeatureValidator Telegram alerts from Phase 7
- Critical alerts via Telegram (immediate notification)
- All alerts logged to database table (manual checking, historical tracking)

### Cross-System Coordination Validation

**Workflow validation approach:**
- **Both execution and inspection:**
  - **E2E execution tests** for happy path — Submit task, verify orchestrator routes, memory retrieves context, ta_lab2 executes, results stored
  - **State inspection tests** for edge cases — Pause at each transition, inspect state, verify handoff correctness

**Failure scenarios to test (all four):**
- **Component unavailable** — Memory down, ta_lab2 refresh fails, orchestrator unreachable
- **Partial failures** — Task succeeds but memory write fails, or results compute but storage fails
- **Timeout/latency issues** — Memory search too slow, ta_lab2 refresh takes too long
- **Invalid state transitions** — Task submitted without memory context, or context pointer invalid

**Workflow state tracking:**
- **Both correlation IDs and state table:**
  - **Correlation IDs** — Generate UUID per request, propagate through orchestrator → memory → ta_lab2
  - **Workflow state table** — Database table tracking workflow_id, phase, status, timestamps
  - IDs for tracing, table for querying workflow history

**Issue handling:**
- **Configurable (--fail-fast flag):**
  - Default: continue execution, collect all issues, report summary at end
  - `--fail-fast`: strict mode stops on first failure, reports error immediately

### Gap Tests and Alignment Validation

**Timeframe alignment scenarios (all four):**
- **Standard timeframes (1D, 7D, 30D)** — Basic daily, weekly, monthly calculations align correctly
- **Calendar boundaries (month/year rolls)** — 1M/3M/1Y calculations handle month-end, year-end correctly
- **Trading session boundaries** — Equity market hours, weekends, holidays handled correctly
- **Edge cases (DST, leap years, partial periods)** — Daylight saving time, Feb 29, incomplete final periods

**Gap detection validation:**
- **Both schedule-based and statistical:**
  - **Schedule-based** — Generate expected dates from dim_timeframe.tf_days, compare actual vs expected
  - **Statistical anomaly detection** — Flag unusually large gaps (>2x normal spacing)
  - Schedule for known patterns (equity trading days), statistical for unknowns (data issues)

**Rowcount validation tolerance:**
- **Strict (0% tolerance):**
  - Actual must exactly match expected — any difference fails
  - Crypto assets have continuous data, equity assets have session-based data
  - Both should match expected counts from dim_timeframe exactly

**Alignment reporting:**
- **Detailed listings:**
  - Every gap date with context (asset, timeframe, expected vs actual)
  - Every misalignment with calculation details
  - Not just summary counts — full diagnostic information for investigation

### Claude's Discretion

- Test failure reporting implementation (pytest output vs logs vs HTML)
- Exact observability schema design (table structures for logs, metrics, traces)
- Correlation ID format and propagation mechanism
- Gap detection statistical algorithm (threshold for "unusually large" gaps)
- Health check endpoint implementation details

</decisions>

<specifics>
## Specific Ideas

- "Leverage existing Telegram integration from Phase 7 (FeatureValidator) — don't rebuild alert infrastructure"
- "Database tables for observability — we already have PostgreSQL, keep data queryable with SQL"
- "Strict rowcount validation — if crypto should have 24/7 data, any missing row is a real issue"
- "Detailed alignment reporting — need full diagnostic info to investigate misalignments, not just counts"
- "Combination test data approach — fixtures for speed, synthetic for coverage, prod samples for realism"

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 09-integration-observability*
*Context gathered: 2026-01-30*
