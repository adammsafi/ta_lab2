# Phase 87: Live Pipeline & Alert Wiring - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the full daily autonomous pipeline end-to-end: data → features → signals → validation → execution → drift → alerts. Add IC staleness monitoring for alpha decay detection, signal anomaly gates before execution, dead-man switch for pipeline health, and tuned Telegram alerts with severity tiers. Scheduling via Windows Task Scheduler or cron.

</domain>

<decisions>
## Implementation Decisions

### Pipeline orchestration
- Extend existing `run_daily_refresh.py` with new stages (signals → validation → executor → drift) — no separate script
- Add `--from-stage <name>` flag for partial runs / re-runs after failures
- Failure mode: skip and continue — failed stage logs warning, skips dependent stages, pipeline continues to alerts/monitoring
- Scheduling: both manual invocation AND scheduled daily run (Windows Task Scheduler / cron)
- Stage order: bars → EMAs → GARCH → features → signals → signal validation gate → executor → drift → alerts

### Alert tuning & channels
- Claude groups alert events into critical/warning/info tiers — critical fires immediately to Telegram, non-critical batched into daily digest
- Throttling: critical alerts fire immediately with per-event cooldown (same alert type suppressed for N hours); non-critical alerts batched into single daily digest message
- Dead-man switch: Claude picks sensible default time based on crypto market cadence (likely relative to UTC midnight daily close)
- Telegram format: structured with emoji headers (🟢 Pipeline Complete / 🟡 IC Decay Warning / 🔴 Kill Switch) — scan-friendly

### IC staleness & alpha decay
- Checked every pipeline run (not weekly) — compute rolling IC-IR as part of daily pipeline
- Multi-window comparison is mandatory — compare across multiple lookback windows (e.g., 30d/60d/90d); exact methodology deferred to research (best practice), but single-window is not acceptable
- IC-IR staleness threshold: 0.7 (lower buffer below the 1.0 active-tier cutoff from Phase 80 — avoids noise from short-term dips)
- Decay action: alert fires AND feature's weight in BL views is auto-halved until manually reviewed (not full demotion, not alert-only)

### Signal validation gate
- Anomaly action: BLOCK execution — signal held back from executor, alert fires, requires manual approval to proceed
- Check both signal count anomalies AND signal strength anomalies
- Crowded signal detection: alert when >N% of signals agree on same asset+direction — could indicate regime shift or data issue
- Historical baseline: Claude's discretion on rolling vs full history

### Claude's Discretion
- Exact dead-man switch timing
- Historical baseline definition for signal anomaly detection (rolling window vs backtest history)
- Multi-window IC comparison methodology (short-vs-long divergence, multiple thresholds, or trend detection — research decides)
- Alert tier classification (which events are critical vs warning vs info)
- Cooldown durations per alert type
- Crowded signal threshold (the N% value)

</decisions>

<specifics>
## Specific Ideas

- IC staleness: user explicitly wants multi-window comparison, not single lookback — "do some research to decide based on best practice"
- Signal gate is a hard block, not a soft warning — this is a safety gate
- Crowded signals flagged separately from individual anomalies — treats simultaneous agreement as a distinct risk signal
- Phase 86 provides GARCH vol and BL weights that this phase wires into the live loop
- Existing `run_daily_refresh.py` already has bars → EMAs → regimes → stats stages that must be preserved

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 87-live-pipeline-alert-wiring*
*Context gathered: 2026-03-23*
