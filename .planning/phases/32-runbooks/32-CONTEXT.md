# Phase 32: Runbooks - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Write 4 operational runbooks so that any operator (primarily future-self) can pick up a workflow cold and execute it without reading code. Covers: regime pipeline, backtest pipeline, new-asset onboarding, and disaster recovery. Add runbooks to mkdocs nav under an Operations section.

</domain>

<decisions>
## Implementation Decisions

### Audience & depth
- Primary reader: "future me in 3 months" — knows the system conceptually but forgot exact commands and gotchas
- Tone: commands + brief 'why' per section (1-2 sentences of context) + links to design docs for background. All three layers.
- Expected output: include for non-obvious steps only. Skip for simple commands.

### Section structure
- Per-workflow tailoring — each runbook gets sections that fit its workflow (not a rigid shared template)
- DAILY_REFRESH.md is inspiration, not a rigid skeleton
- Every runbook includes explicit Prerequisites section (DB up, env vars, bars fresh, etc.)
- Troubleshooting format: Claude's discretion per runbook (table vs. inline vs. narrative)
- All 4 runbooks added to mkdocs nav under an "Operations" section group

### Disaster recovery scope
- Two scenarios in priority order: (1) DB loss/corruption, (2) full environment rebuild from zero
- No automated backup exists yet — DR guide documents manual pg_dump/pg_restore procedure and recommends automation
- "Rebuild from scratch" means re-ingest from CoinMarketCap source (the nuclear option: create tables via DDL, ingest price_histories7, build bars, compute EMAs, features, regimes, etc.)
- Recovery time estimates: Claude's discretion — include where meaningful, omit where too variable

### Onboarding detail level
- Full end-to-end walkthrough using ETH (id=2) as the example asset
- Each step has exact command + verification query to confirm success
- Include timing estimates per step (e.g., "Build multi-TF bars: ~5 min")
- Include brief "Removing an asset" section at the end (just the DELETE queries)

### Claude's Discretion
- Best tone per runbook (reference-first vs. tutorial-first) based on workflow complexity
- Troubleshooting format per runbook (table vs. narrative)
- Recovery time estimates where meaningful
- Exact section ordering within each runbook

</decisions>

<specifics>
## Specific Ideas

- Follow the spirit of DAILY_REFRESH.md — Quick Start with copy-paste commands up front
- Regime runbook should include `regime_inspect` usage for debugging
- Backtest runbook should cover how to re-run a specific signal type and interpret backtest_metrics
- Onboarding walkthrough uses ETH (id=2) with real expected row counts
- DR "rebuild from scratch" is the full pipeline in order: DDL -> price_histories7 -> bars -> EMAs -> features -> regimes -> signals -> backtest

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 32-runbooks*
*Context gathered: 2026-02-23*
