---
phase: 89-ctf-schema-dimension-table
plan: 01
subsystem: database
tags: [alembic, postgresql, ctf, dimension-table, yaml-config, schema-migration]

# Dependency graph
requires:
  - phase: 81-garch-volatility
    provides: "Alembic migration pattern (i3j4k5l6m7n8_garch_tables.py) and garch_diagnostics/garch_forecasts table style"
  - phase: 80-feature-selection
    provides: "Confirmed indicator column names in ta/vol/features tables"
provides:
  - "dim_ctf_indicators dimension table (22 seeded indicators, SMALLSERIAL PK)"
  - "ctf fact table with 7-column composite PK and 6 value columns"
  - "ix_ctf_lookup and ix_ctf_indicator indexes"
  - "configs/ctf_config.yaml with 4 TF pair groups, 22 indicators, composite_params"
  - "Alembic chain extended: 440fdfb3e8e1 -> j4k5l6m7n8o9"
affects:
  - "90-ctf-computation-engine"
  - "91-ctf-disk-estimate"
  - "Any phase reading CTF features from the ctf table"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CTF dimension table pattern: SMALLSERIAL PK + UNIQUE indicator_name + source_table/source_column columns"
    - "CTF fact table PK pattern: (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)"
    - "YAML config returns section nests indicators: list under source_table + roll_filter metadata keys"

key-files:
  created:
    - alembic/versions/j4k5l6m7n8o9_ctf_schema.py
    - configs/ctf_config.yaml
  modified: []

key-decisions:
  - "down_revision=440fdfb3e8e1 (not i3j4k5l6m7n8 as research stated -- research predates the 440fdfb3e8e1 migration)"
  - "returns section uses nested indicators: key with source_table + roll_filter metadata; other sections (ta, vol, features) are flat lists"
  - "ctf computed_at column (not updated_at): derived fact table semantics, not incremental measurement"

patterns-established:
  - "CTF dimension table: SMALLSERIAL PK maps integer indicator_id to source_table + source_column for Phase 90 query generation"
  - "YAML CTF config: flat sections for simple source tables (ta/vol/features), nested indicators: for sources needing extra metadata (returns)"

# Metrics
duration: 2min
completed: 2026-03-23
---

# Phase 89 Plan 01: CTF Schema + Dimension Table Summary

**PostgreSQL schema foundation for CTF features: dim_ctf_indicators (22 seeded rows) + ctf fact table with composite PK, FKs to dim_venues/dim_ctf_indicators, two indexes, and ctf_config.yaml with 4 TF pair groups and 22 indicators.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-23T18:57:27Z
- **Completed:** 2026-03-23T18:59:48Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- dim_ctf_indicators dimension table created with SMALLSERIAL PK and 22 seeded indicator rows covering TA (11), volatility (7), returns (2), and features (2) source tables
- ctf fact table created with 7-column composite PK (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source), FK references to dim_venues and dim_ctf_indicators, and computed_at default
- configs/ctf_config.yaml validated with 4 TF pair groups (15 pairs total), 22 indicators, and composite_params (slope_window=5, divergence_zscore_window=63)

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration -- dim_ctf_indicators + ctf tables + seed data** - `f1913120` (feat)
2. **Task 2: Declarative YAML config for CTF feature computation** - `52c7b0ad` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `alembic/versions/j4k5l6m7n8o9_ctf_schema.py` - Alembic migration: dim_ctf_indicators, 22-row seed, ctf table, ix_ctf_lookup, ix_ctf_indicator; down_revision=440fdfb3e8e1
- `configs/ctf_config.yaml` - Declarative CTF config: 4 TF pair groups, 22 indicators across 4 source sections, composite_params

## Decisions Made
- **down_revision=440fdfb3e8e1:** The research document specified `i3j4k5l6m7n8` as down_revision but that was written before the `440fdfb3e8e1` migration was added. The plan explicitly called out the correct head.
- **returns section uses nested indicators: key:** YAML `returns:` section has extra metadata (`source_table: returns_bars_multi_tf_u`, `roll_filter: false`) that ta/vol/features sections do not need. Using nested `indicators:` list avoids YAML parsing ambiguity between scalar keys and list items at the same level.
- **computed_at (not updated_at):** The `ctf` table is a derived fact table, not a raw measurement. `computed_at` semantically distinguishes it from `updated_at` used by source tables.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. Migration runs via `alembic upgrade head`.

## Next Phase Readiness
- Phase 90 (CTF computation engine): both tables exist, config is loadable. Phase 90 can read `ctf_config.yaml` and write to `ctf` table using `indicator_id` FK from `dim_ctf_indicators`.
- Alembic chain: 440fdfb3e8e1 -> j4k5l6m7n8o9 (head). No blockers.
- Note for Phase 90: ta/vol tables have venue_id as column-only (not in PK) -- join on (id, ts, tf, alignment_source) only. The ctf fact table carries venue_id in its PK from the caller context.

---
*Phase: 89-ctf-schema-dimension-table*
*Completed: 2026-03-23*
