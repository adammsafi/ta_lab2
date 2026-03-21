# Phase 77: Direct-to-_u Remaining Families - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Migrate 5 remaining table families from siloed tables to direct _u writes, applying the validated Phase 76 pattern. Families: bar returns, EMA values, EMA returns, AMA values, AMA returns. Each family gets its own plan with redirect + verify + sync disable.

</domain>

<decisions>
## Implementation Decisions

### Rollout ordering
- One family at a time, fully verified before moving to next
- Order: bar returns -> EMA -> EMA returns -> AMA -> AMA returns
- Each return family follows its parent values family (EMA before EMA-ret, AMA before AMA-ret)
- Bar returns first since it's closest to the Phase 76 price bars pattern
- 5 separate plans, one per family

### State table strategy
- Claude decides per family: check if state table already has rows, bootstrap only if empty or stale
- Adaptive approach — use pg_index PK discovery (same as Phase 76) but skip bootstrap if watermarks are already correct
- EMA/AMA families may have extra columns (period, AMA params) — Claude handles schema differences without pausing

### Sync script handling
- Each family's plan includes disabling its own sync script after redirect + verify (per-family, not batched)
- Claude decides whether to use deprecation-notice pattern (like Phase 76) or delete immediately
- Claude investigates which orchestrators (run_daily_refresh, run_all_bar_builders) call sync scripts and handles references as part of each family's plan

### Verification scope
- Claude adapts row-count parity margins per family based on table size
- Claude decides whether additional spot-checks are warranted (e.g., period values for EMA/AMA)
- Claude decides artifact format (per-family files vs combined report)

### Claude's Discretion
- State table bootstrap: skip vs run per family based on current state
- Sync script pattern: deprecation no-op vs immediate delete
- Orchestrator reference cleanup: handle inline vs defer to Phase 78
- Verification margins and any extra spot-check queries
- Artifact file structure (separate vs combined)

</decisions>

<specifics>
## Specific Ideas

- Phase 76 pattern is the proven template: ALIGNMENT_SOURCE constant, valid_cols already has alignment_source, delete_bars_for_id_tf already has alignment_source param, conflict_cols tuple includes alignment_source
- EMA tables have `period` in PK — conflict_cols and state tables will differ from price bars
- AMA tables are the largest (~91M rows each) — bootstrap and verification may take longer
- Returns families are simpler (no _load_last_snapshot_info complexity, no from_1d paths)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 77-direct-to-u-remaining-families*
*Context gathered: 2026-03-20*
