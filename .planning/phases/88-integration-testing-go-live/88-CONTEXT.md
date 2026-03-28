# Phase 88: Integration Testing & Go-Live - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

End-to-end validation that the full v1.2.0 pipeline (data ingestion -> features -> signals -> calibrate_stops -> portfolio -> paper execution -> drift -> dashboard) works reliably. Includes a 1-week paper trading burn-in, backtest parity verification, runbook updates, and v1.2.0 tag. No new features -- this phase validates what's already built.

</domain>

<decisions>
## Implementation Decisions

### Smoke test scope
- Automated script (`python -m ta_lab2.scripts.integration.smoke_test` or similar) -- single command, pass/fail output, reusable
- Test against a small set of 3-5 assets (BTC + a few alts to catch edge cases)
- Uses live local DB with dry-run mode where possible -- reads real data, avoids writing test artifacts to production tables
- Verification at each pipeline stage: non-zero row counts AND value sanity checks (no NaN prices, signals in expected range, fills with valid timestamps)
- Pipeline stages to verify: bars -> EMAs -> features -> GARCH -> signals -> calibrate_stops -> portfolio -> executor -> drift

### Paper trading burn-in protocol
- Duration: 1 week of sustained daily pipeline runs against the full 99-asset universe
- Monitoring: Dashboard for deep dives + automated daily status report (PnL, drift metrics, fill count, anomalies) + Telegram alerts for critical events (kill switch trigger, drift pause)
- Early stop criteria: ONLY if the system's own safety mechanisms fire (kill switch or drift pause). Otherwise let it run the full week regardless of PnL.
- Success definition: No safety triggers (kill switch, drift pause) AND paper PnL not catastrophically negative (not -20% or worse). Pipeline ran every day without manual intervention.

### Parity check tolerance
- Verify: trade direction + timing + cumulative PnL correlation between paper fills and backtest replay
- PnL correlation threshold: r >= 0.90 (moderate -- allows slippage and timing differences, catches structural signal/sizing bugs)
- Strategies to verify: bakeoff winners only (from Phase 82 strategy_bakeoff_results)
- Failure handling: soft gate -- document which winners failed and why, proceed with v1.2.0 tag if majority (>50%) of bakeoff winners pass parity. Failed strategies excluded from live trading.
- Uses slippage_mode=fixed (already configured in Phase 86 parity check --bakeoff-winners)

### Runbook & release scope
- Two documents: update existing OPERATIONS_MANUAL.md + standalone v1.2.0 release notes
- Audience: a future collaborator with Python/DB skills could operate the system without the original author. Minimize assumed context.
- Coverage: full operational guide for each new v1.2.0 component -- CLI commands, flags, expected outputs, troubleshooting steps, when to intervene, escalation paths
- Components to document: GARCH refresh, stop calibration, portfolio allocations, parity check (--bakeoff-winners), new dashboard pages, Telegram alert tuning
- Release process: milestone audit (/gsd:audit-milestone) -> generate changelog from commit history -> tag v1.2.0 on main. Full ceremony.

### Claude's Discretion
- Exact smoke test assertions per pipeline stage (beyond the row count + sanity framework)
- Daily report format and content layout
- Changelog generation approach (git log parsing vs manual curation)
- Smoke test asset selection (which 3-5 assets beyond BTC)

</decisions>

<specifics>
## Specific Ideas

- Smoke test should use `--dry-run` flags already built into pipeline stages (calibrate_stops, executor) to avoid side effects
- Parity check tooling from Phase 86 (run_parity_check.py --bakeoff-winners) is the foundation -- extend it, don't rebuild
- Burn-in runs the full `run_daily_refresh.py --all` pipeline, not a subset
- The existing Telegram notification infrastructure (Phase 28) should be leveraged for burn-in alerts

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 88-integration-testing-go-live*
*Context gathered: 2026-03-24*
