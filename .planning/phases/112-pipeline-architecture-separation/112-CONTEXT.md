# Phase 112: Pipeline Architecture Separation - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Split the monolithic run_daily_refresh.py into 5 distinct pipelines with clear boundaries, triggers, and deployment topology. Define what runs locally vs on the Oracle VM, and how pipelines hand off to each other. This phase produces the architectural separation and entry points — VM deployment (Phase 113) and hosted dashboard (Phase 114) are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Pipeline Boundaries (5 pipelines)

| Pipeline | Stages | Changes when... |
|----------|--------|-----------------|
| **Data** | sync_vms, bars, returns_bars | New data sources added |
| **Features** | emas, returns_ema, amas, returns_ama, desc_stats, macro_features, macro_regimes, macro_analytics, cross_asset_agg, regimes, features, garch | Research produces new indicators/params |
| **Signals** | signals, signal_validation_gate, ic_staleness_check, macro_gates, macro_alerts | Strategy config changes |
| **Execution** | calibrate_stops, portfolio, executor | Tightest SLA, smallest blast radius |
| **Monitoring** | drift_monitor, pipeline_alerts, stats | Never blocks trading |

- Validation gates (signal_validation_gate, ic_staleness_check, macro_gates) belong inside the Signals pipeline — they are quality checks on signals, not a separate pipeline
- EMA/AMA in Features (not Data) because period parameters are research decisions
- Monitoring is fully independent — runs on its own cadence, never blocks other pipelines

### Trigger Mechanisms

| Pipeline | Trigger | Where |
|----------|---------|-------|
| Data → Features → Signals | Manual trigger, auto-chain | Local PC |
| Execution | Always-on service, polls for signals | Oracle VM |
| Monitoring | Always-on timer (every 15-30 min) | Oracle VM |

- Data is triggered manually (automated scheduling deferred to future phase)
- Data → Features → Signals auto-chains: triggering Data cascades through all three
- Execution runs as a persistent service on Oracle VM, polling for fresh signals on its own loop
- Monitoring runs independently on the VM on a 15-30 minute timer
- Latest signals are synced to VM after the Signals pipeline completes

### Local vs VM Topology

**Local PC runs:** Data, Features, Signals (the "think" pipelines), Research (ad-hoc)
**Oracle VM runs:** Execution (always-on), Monitoring (always-on timer), Dashboard (Phase 114)

**Sync to VM (push after Signals pipeline):**
- signals_* tables
- portfolio_allocations
- dim_executor_config
- strategy_parity
- risk_overrides

**VM already has price data:** HL candles, CMC, TVC — no price sync needed for executor. Venue routing and streaming/intraday data are future scope.

**Results sync:** VM is source of truth for execution data (fills, orders, positions). Local PC pulls on-demand via watermark-based incremental sync (same pattern as sync_hl_from_vm). Telegram alerts on fills for real-time notification.

### Handoff Contracts

- **Pipeline completion signal:** Each pipeline writes to `pipeline_run_log` with `status='complete'`. Next pipeline in the chain checks for this before starting. Already exists from Phase 87/107.
- **Failure handling:** If any pipeline in the chain fails, the chain halts. Stale signals from yesterday remain valid for the executor. Telegram alert sent on failure.
- **Signal sync to VM:** A `sync_signals_to_vm` step runs as the final step of the auto-chain, pushing signal rows + configs via SSH + psql COPY.

### Claude's Discretion

- Exact polling interval for executor signal check (suggested: every 5 minutes)
- Monitoring timer interval (suggested: 15-30 minutes)
- Internal structure of each pipeline entry point (single script vs module)
- Whether to keep run_daily_refresh.py as a backward-compatible wrapper that calls all 5 pipelines, or deprecate it

</decisions>

<specifics>
## Specific Ideas

- Pipeline structure follows the medallion architecture pattern: Data = Bronze/Silver, Features = Gold, Signals/Execution = action layer
- sync_signals_to_vm follows the same SSH + psql COPY pattern as existing sync_hl_from_vm and sync_fred_from_vm scripts
- Executor on VM should use the existing stale-signal guard to do nothing when signals haven't been updated
- VM dashboard (Phase 114) reads execution data directly from VM DB — no sync needed for that path

</specifics>

<deferred>
## Deferred Ideas

- Automated Data pipeline scheduling (Windows Task Scheduler or VM cron) — future phase after manual operation proves stable
- Venue routing for multi-exchange execution — noted for Phase 113 or later
- Streaming / intraday data pulls via exchange APIs — noted for future phase
- PostgreSQL logical replication as alternative to manual sync — evaluate after sync volume grows
- Moving Data+Features+Signals to VM (full VM-resident pipeline) — evaluate after VM specs confirmed

</deferred>

---

*Phase: 112-pipeline-architecture-separation*
*Context gathered: 2026-04-01*
