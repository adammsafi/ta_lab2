# Phase 74: Foundation & Shared Infrastructure - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract shared utilities, create the SourceSpec registry, and define alignment_source constants. These are foundational pieces that Phase 75 (generalized 1D bar builder) and Phases 76-77 (direct-to-_u migration) build on. No existing behavior changes — purely additive.

</domain>

<decisions>
## Implementation Decisions

### SourceSpec Registry Design
- **Fully data-driven via `dim_data_sources` table** — not a Python dict or YAML config
- Config data (source name, source table, venue_id, ohlc_repair flag, etc.) stored as columns
- **SQL templates stored as text columns** in the dim table — the CTE/query logic per source lives in the DB, not Python
- Builder reads config + SQL from dim table, interpolates parameters, executes
- Adding a new data source = INSERT a row into dim_data_sources (no Python code changes)
- Alembic migration creates the table

### Module Organization
- Shared psycopg helpers (_connect, _exec, _fetchone, etc.) extracted to a single module — Claude decides location
- No Python-side CTE builder modules needed — SQL lives in dim table
- Dim table seeding approach (in migration vs separate script) — Claude decides based on existing Alembic patterns
- Testing approach (DB-backed tests vs Python fixtures) — Claude decides

### alignment_source Naming
- **Keep existing names exactly**: `multi_tf`, `multi_tf_cal_us`, `multi_tf_cal_iso`, `multi_tf_cal_anchor_us`, `multi_tf_cal_anchor_iso`
- No data migration needed — downstream consumers unaffected
- Where constants are defined (dim table column, separate dim table, or Python constants) — Claude decides appropriate normalization level

### CHECK Constraint Scope
- Claude decides timing: add CHECK constraints in Phase 74 (early safety net) or defer to Phases 76-77 (when touching _u tables)

### Claude's Discretion
- Shared helper module location (scripts/bars/ vs top-level db/ package)
- SourceSpec implementation pattern (flat dataclass + callables vs other)
- Alembic migration seeding strategy
- Testing approach for SQL templates
- CHECK constraint timing
- alignment_source constant storage location

</decisions>

<specifics>
## Specific Ideas

- The `dim_data_sources` table follows the existing dimension table pattern (`dim_venues`, `dim_timeframe`, `dim_sessions`)
- SQL templates in the dim table mean the Python builder is truly generic — it never needs to know source-specific SQL
- This is the key extensibility win: a new exchange = one DB row, not a 500-line Python script

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 74-foundation-shared-infrastructure*
*Context gathered: 2026-03-19*
