---
phase: 51-perps-readiness
plan: "03"
subsystem: perps
tags: [perpetuals, venue-health, downtime-playbook, yaml-config, risk-operations]

# Dependency graph
requires:
  - phase: 46-risk-engine
    provides: "Kill switch CLI (kill_switch_cli.py) referenced in playbook"
  - phase: 48-loss-limits
    provides: "Risk event table (cmc_risk_events) used for incident logging"
  - phase: 51-01
    provides: "Reference DDL for cmc_perp_positions and cmc_funding_rates referenced in SQL queries"
provides:
  - "Venue downtime playbook (VENUE_DOWNTIME_PLAYBOOK.md) covering all 6 perps venues"
  - "Machine-readable health config YAML (venue_health_config.yaml) with endpoints, thresholds, escalation rules"
  - "Graduated health states: HEALTHY > DEGRADED > DOWN with transition triggers and response procedures"
  - "Hedge-on-alternate-venue manual procedure with 7 numbered steps and unwind procedure"
  - "Recovery procedure requiring 3 consecutive health checks before resuming"
  - "Daily monitoring checklist with SQL queries and curl health checks"
affects: [51-04, 51-05, 52-operational-dashboard, 53-paper-trading-v1]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-format documentation: human-readable Markdown + machine-readable YAML (following Phase 49 pattern)"
    - "Graduated health state machine: HEALTHY > DEGRADED > DOWN with explicit transition criteria"
    - "Venue priority list for alternate-venue hedge routing"
    - "3-consecutive-checks recovery gate before resuming normal operations"

key-files:
  created:
    - "reports/perps/venue_health_config.yaml — machine-readable health check config for all 6 venues"
    - "reports/perps/VENUE_DOWNTIME_PLAYBOOK.md — 435-line operational procedure document"
  modified: []

key-decisions:
  - "6 venues configured: Binance (8h), Hyperliquid (1h), Bybit (8h), dYdX (1h), Aevo (1h), Aster (8h) — settlement periods differ by venue type"
  - "V1 hedge procedure is manual: operator identifies positions via SQL, selects alternate venue from priority list, places opposing trade manually; automated routing deferred"
  - "Venue priority list [binance, bybit, hyperliquid]: Binance first for highest liquidity, on-chain DEXes as last resort"
  - "3-consecutive-checks recovery gate: prevents premature order resumption during intermittent recovery"
  - "Kill switch fires after 60 min sustained DOWN: consistent with risk engine escalation pattern from Phase 46"
  - "DEGRADED does not halt orders: monitoring increase only; full halt only on DOWN or DEGRADED > 30 min"
  - "dYdX max_latency_ms=4000, stale_orderbook_seconds=60: higher thresholds reflect on-chain indexer architecture"
  - "reports/ is gitignored: YAML and Markdown written to disk but not git-tracked, following Phase 42-05 convention"

patterns-established:
  - "Playbook references YAML by field name: thresholds are single source of truth in YAML, prose references field names not hardcoded values"
  - "SQL-first incident documentation: all recovery and hedge actions include INSERT into cmc_risk_events"

# Metrics
duration: 3min
completed: "2026-02-25"
---

# Phase 51 Plan 03: Venue Downtime Playbook Summary

**Venue downtime playbook (PERP-05): 435-line Markdown procedure + YAML health config for all 6 perps venues with graduated health states, 7-step hedge-on-alternate-venue procedure, and SQL-first incident documentation.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T23:26:26Z
- **Completed:** 2026-02-25T23:29:17Z
- **Tasks:** 2
- **Files modified:** 2 (both in gitignored reports/)

## Accomplishments

- Created `reports/perps/venue_health_config.yaml` — machine-readable configuration for all 6 venues (Binance, Hyperliquid, Bybit, dYdX, Aevo, Aster) with health endpoints, latency thresholds, settlement periods, alternate venue lists, health state definitions, escalation rules, hedge procedure, and recovery criteria
- Created `reports/perps/VENUE_DOWNTIME_PLAYBOOK.md` — 435-line operational procedure covering all 8 required sections: overview, health status definitions, downtime types table, immediate response procedures, hedge-on-alternate-venue (7 steps + unwind), recovery procedure, daily monitoring checklist, reference tables
- Covers all 6 downtime types: API failure, degraded performance, stale orderbook, scheduled maintenance, regulatory halt, unusual spread widening
- YAML validated via PyYAML (`yaml.safe_load()` succeeds); all verifications pass

## Task Commits

Both tasks produce files in gitignored `reports/` directory. No git commits made for task files per Phase 42-05 convention. Planning artifact commit below covers SUMMARY.md and STATE.md only.

1. **Task 1: Venue health config YAML** — `reports/perps/venue_health_config.yaml` written and YAML-validated
2. **Task 2: Venue downtime playbook Markdown** — `reports/perps/VENUE_DOWNTIME_PLAYBOOK.md` written, 435 lines, all sections verified

**Plan metadata:** (docs commit for SUMMARY.md + STATE.md)

## Files Created/Modified

- `reports/perps/venue_health_config.yaml` — Machine-readable health check configuration for all 6 perps venues (gitignored, written to disk)
- `reports/perps/VENUE_DOWNTIME_PLAYBOOK.md` — 435-line operational playbook covering all downtime scenarios (gitignored, written to disk)

## Decisions Made

- **6 venues with venue-specific thresholds**: CEX venues (Binance, Bybit) use 2000ms latency; DEXes use 3000-4000ms; dYdX has 60s stale orderbook vs 30s for others — reflects architectural reality of on-chain indexer
- **V1 hedge procedure is manual**: automated multi-venue order routing deferred; V1 requires operator to identify positions via SQL, check alternate venue health, and place opposing order manually — acceptable for paper trading phase
- **Venue priority [binance, bybit, hyperliquid]**: Binance first for liquidity depth; on-chain DEXes (Hyperliquid, dYdX, Aevo) deprioritized for emergency hedges due to on-chain settlement latency
- **3-consecutive-check recovery gate**: prevents false recovery declarations during intermittent outages (common with CEX maintenance windows that partially recover)
- **DEGRADED does not halt orders**: monitoring increase only; operators need runway to investigate before disrupting active positions; escalates to DOWN only after 30 min sustained degradation
- **SQL-first incident documentation**: all recovery and hedge actions include explicit SQL INSERT into `cmc_risk_events` — maintains audit trail for post-incident review

## Deviations from Plan

None — plan executed exactly as written. YAML structure matches plan specification with additions (recovery section, orderbook_endpoint, health_payload for orderbook checks) that extend completeness without changing scope.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. The playbook is a documentation and procedure artifact.

## Next Phase Readiness

- PERP-05 satisfied: venue downtime playbook + YAML config complete
- Playbook is ready for operator use during paper trading phase (Phase 53)
- venue_health_config.yaml can be consumed by future automated health monitoring scripts
- Hedge procedure documents the manual workflow; automated failover routing is a candidate for a future phase when live trading begins
- All 6 venue health endpoints confirmed valid (Binance, Hyperliquid, Bybit, dYdX, Aevo, Aster) with correct API signatures

---
*Phase: 51-perps-readiness*
*Completed: 2026-02-25*
