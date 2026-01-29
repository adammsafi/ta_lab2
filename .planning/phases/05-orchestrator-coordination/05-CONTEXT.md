# Phase 5: Orchestrator Coordination - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Build intelligent task routing and coordination across Claude Code, ChatGPT, and Gemini platforms. The orchestrator routes tasks to the most cost-effective platform while considering platform hints, executes independent tasks in parallel, enables task-to-task handoffs through memory, and tracks costs at multiple granularities. Phase 4 provided the adapters; this phase connects them with routing logic, parallel execution, handoff mechanisms, and cost tracking.

</domain>

<decisions>
## Implementation Decisions

### Routing Strategy
- **Cost vs capability:** Hybrid approach — default to cost-optimized routing (Gemini free tier first), but respect task-level platform hints when specified
- **Gemini quota handling:** Warn and ask when approaching 90% of 1500 req/day limit — notify user, let them decide whether to continue with paid platforms
- **Task affinity:** No affinity enforcement — each task routed independently for maximum cost savings, even if in a sequence
- **Platform hints:** Advisory (fallback allowed) — try preferred platform first, but fall back to alternatives if unavailable or quota exhausted

### Parallel Execution
- **Dependency detection:** Claude's discretion — choose between explicit dependency graph vs auto-detection based on safety vs convenience trade-off
- **Concurrency limits:** Adaptive (based on resources) — scale concurrent tasks based on available quota and rate limits
- **Failure handling:** Claude's discretion — decide whether to fail-fast (cancel all) or fail-independent (let others finish) based on typical use cases
- **Context sharing:** Shared context pool — parallel tasks can read/write common memory (enables collaboration, requires coordination/locking)

### Handoff Mechanism
- **Context passing:** Hybrid (pointer + summary) — Task A includes small summary inline for quick reference, full context stored in memory with pointer
- **Memory lookup failure:** Fail Task B immediately — if context can't be retrieved from memory, task cannot proceed
- **Chain tracking:** Yes, explicit chain tracking — orchestrator maintains task genealogy (Task A → B → C) for debugging, visualization, and cost attribution
- **Fan-out:** Claude's discretion — decide if Task A can spawn multiple children (B and C in parallel) based on Phase 5 scope needs

### Cost Tracking
- **Granularity:** All levels — track per-task costs, per-platform totals, per-workflow chains, and session totals
- **Cost estimation:** Estimate for expensive only — estimate cost when prompt > threshold (e.g., 10k tokens), otherwise just record actual
- **Budget limits:** Soft warnings only — warn when approaching limits, but allow user override (user stays in control)
- **Persistence:** Database table — use SQLite or Postgres for cost data (better for queries and analytics vs JSON file)

### Claude's Discretion
- Dependency detection approach (explicit graph vs auto-detect)
- Failure handling in parallel batches (fail-fast vs fail-independent)
- Fan-out support (whether Task A can spawn multiple children)
- Specific concurrency scaling algorithm
- Exact token threshold for cost estimation
- Database schema for cost tracking table

</decisions>

<specifics>
## Specific Ideas

- Routing should respect the cost-first priority from ROADMAP success criteria #1 ("Gemini CLI free tier first, then subscriptions, then paid APIs")
- Gemini's 1500 req/day limit is the key constraint that makes cost optimization critical
- Shared context for parallel tasks builds on Phase 2-3 memory architecture (ChromaDB + Mem0)
- Chain tracking enables workflow-level cost attribution (know that "data pipeline workflow" cost $2.50 total)
- Adaptive concurrency should consider both quota limits (from Phase 1) and rate limits (from adapter retry logic in Phase 4)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-orchestrator-coordination*
*Context gathered: 2026-01-29*
