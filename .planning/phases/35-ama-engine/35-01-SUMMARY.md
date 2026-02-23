---
phase: 35-ama-engine
plan: 01
subsystem: database
tags: [postgres, ddl, ama, kama, dema, tema, hma, schema, indicator]

# Dependency graph
requires:
  - phase: 24-pattern-consistency
    provides: EMA table family DDL patterns (multi_tf, cal, cal_anchor, _u, state tables)
  - phase: 33-alembic-migrations
    provides: Alembic migration infrastructure for future AMA migration script

provides:
  - 6 AMA value tables: cmc_ama_multi_tf + 4 calendar variants + _u unified
  - 6 AMA returns tables: cmc_returns_ama_multi_tf + 4 calendar variants + _u unified
  - 12 AMA state tables (one per value + returns table)
  - 1 dim_ama_params lookup table for human-readable parameter resolution
  - 9 DDL files covering all AMA schema objects

affects:
  - 35-02 (AMA refresher Python: needs these tables to exist)
  - 35-03 (AMA sync utilities: needs _u tables)
  - 35-04 (daily refresh wiring: tables must exist before CLI flags added)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AMA table PK pattern: (id, ts, tf, indicator, params_hash) replaces (id, ts, tf, period)"
    - "_u table includes alignment_source in PK: (id, ts, tf, indicator, params_hash, alignment_source)"
    - "dim_ama_params lookup table: (indicator, params_hash) -> params_json JSONB + label TEXT"
    - "er column on value tables: stores KAMA Efficiency Ratio, NULL for non-KAMA indicators"
    - "AMA returns have no _ama_bar columns (unlike EMA returns which have _ema_bar)"
    - "12 z-score columns per returns table: 4 base x 3 windows (30/90/365)"

key-files:
  created:
    - sql/ddl/create_cmc_ama_multi_tf.sql
    - sql/ddl/create_cmc_ama_multi_tf_cal.sql
    - sql/ddl/create_cmc_ama_multi_tf_cal_anchor.sql
    - sql/ddl/create_cmc_ama_multi_tf_u.sql
    - sql/ddl/create_cmc_returns_ama_multi_tf.sql
    - sql/ddl/create_cmc_returns_ama_multi_tf_cal.sql
    - sql/ddl/create_cmc_returns_ama_multi_tf_cal_anchor.sql
    - sql/ddl/create_cmc_returns_ama_multi_tf_u.sql
    - sql/ddl/create_dim_ama_params.sql
  modified: []

key-decisions:
  - "Single cmc_ama_multi_tf table for all indicator types (KAMA/DEMA/TEMA/HMA) distinguished by indicator column"
  - "dim_ama_params lookup table created to map params_hash to human-readable values + JSONB params"
  - "AMA returns have no _ama_bar column family (AMA has no bar-space variant, unlike EMA)"
  - "er column present on all AMA value tables, NULL for non-KAMA indicators (DEMA/TEMA/HMA)"
  - "_u state tables created for both value and returns _u tables (2 extra state tables vs plan minimum)"

patterns-established:
  - "AMA PK pattern: (id, ts, tf, indicator, params_hash) -- used in all 5 base tables + state tables"
  - "_u PK pattern: (id, ts, tf, indicator, params_hash, alignment_source) -- alignment_source ALWAYS in _u PK"
  - "12 z-score columns: ret_arith_ama_zscore_{30,90,365} + ret_log_ama_zscore_{30,90,365} + _roll variants"

# Metrics
duration: 3min
completed: 2026-02-23
---

# Phase 35 Plan 01: AMA DDL Summary

**Full AMA table family DDL: 6 value tables + 6 returns tables + 12 state tables + dim_ama_params, using (indicator, params_hash) PK replacing the EMA period-based PK**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-23T21:59:20Z
- **Completed:** 2026-02-23T22:02:55Z
- **Tasks:** 2
- **Files modified:** 9 created

## Accomplishments
- Created complete AMA table family with full calendar parity (5 alignment variants x 2 table families = 10 base tables + 2 unified _u tables = 12 tables)
- Established (indicator, params_hash) PK pattern for all AMA tables, replacing EMA's period-based PK
- Created dim_ama_params lookup table enabling human-readable queries across KAMA/DEMA/TEMA/HMA parameter sets
- All returns tables include 12 z-score columns (4 base x 3 windows) ready for refresh_returns_zscore.py
- No _ama_bar column family (AMA simplified vs EMA: no bar-space variant needed)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create AMA value table DDL (4 files)** - `2a5c0c41` (feat)
2. **Task 2: Create AMA returns table DDL + dim_ama_params (5 files)** - `19b986c4` (feat)

## Files Created/Modified
- `sql/ddl/create_cmc_ama_multi_tf.sql` - Main AMA value table + state, PK (id,ts,tf,indicator,params_hash)
- `sql/ddl/create_cmc_ama_multi_tf_cal.sql` - cal_us + cal_iso value tables + state tables
- `sql/ddl/create_cmc_ama_multi_tf_cal_anchor.sql` - cal_anchor_us + cal_anchor_iso value tables + state
- `sql/ddl/create_cmc_ama_multi_tf_u.sql` - Unified table, alignment_source in PK
- `sql/ddl/create_cmc_returns_ama_multi_tf.sql` - Main returns + state, 12 z-score columns
- `sql/ddl/create_cmc_returns_ama_multi_tf_cal.sql` - cal_us + cal_iso returns + state tables
- `sql/ddl/create_cmc_returns_ama_multi_tf_cal_anchor.sql` - cal_anchor_us + cal_anchor_iso returns + state
- `sql/ddl/create_cmc_returns_ama_multi_tf_u.sql` - Unified returns, alignment_source in PK
- `sql/ddl/create_dim_ama_params.sql` - Parameter lookup: (indicator, params_hash) -> params_json + label

## Decisions Made
- **Single indicator column approach**: All 4 AMA types (KAMA/DEMA/TEMA/HMA) share one table family distinguished by `indicator TEXT` column. Avoids 4x table proliferation while keeping type-safe queries via indicator filter.
- **dim_ama_params lookup table**: Created at Claude's discretion (plan listed this as a Claude decision). Maps `(indicator, params_hash)` to `params_json JSONB` + human-readable `label TEXT`. Enables queries like `SELECT label FROM dim_ama_params WHERE indicator='KAMA' AND params_hash='kama_10_2_30'` without decoding hashes.
- **No _ama_bar column family**: AMA returns tables omit the bar-space variant entirely (EMA returns have `_ema` + `_ema_bar` column families). AMAs are computed on canonical bar closes only, no intra-bar snapshot needed. This simplifies DDL and reduces column count.
- **er column on all tables**: KAMA's Efficiency Ratio stored inline on value tables (NULL for DEMA/TEMA/HMA). Queryable as standalone signal candidate for IC evaluation without separate join.
- **_u state tables created**: Both `cmc_ama_multi_tf_u_state` and `cmc_returns_ama_multi_tf_u_state` created, giving 12 state tables vs plan's stated 10 minimum. Matches actual EMA _u pattern which also has _u_state tables.

## Deviations from Plan

None - plan executed exactly as written. The 12 state tables vs 10 in the plan's success criteria is not a deviation; the plan's count was a minimum estimate (5 value + 5 returns state tables) and the _u state tables are required by the sync pattern.

## Issues Encountered
- Pre-commit hook (mixed-line-ending) fixed line endings on all 9 SQL files. Required two commit attempts per task (hook runs, fixes files, then second attempt succeeds). No content changes, pure CRLF normalization.

## User Setup Required

None - DDL files must be applied to the database. This will be handled by an Alembic migration in a future plan.

**To apply manually (development):**
```bash
psql $DATABASE_URL -f sql/ddl/create_cmc_ama_multi_tf.sql
psql $DATABASE_URL -f sql/ddl/create_cmc_ama_multi_tf_cal.sql
psql $DATABASE_URL -f sql/ddl/create_cmc_ama_multi_tf_cal_anchor.sql
psql $DATABASE_URL -f sql/ddl/create_cmc_ama_multi_tf_u.sql
psql $DATABASE_URL -f sql/ddl/create_cmc_returns_ama_multi_tf.sql
psql $DATABASE_URL -f sql/ddl/create_cmc_returns_ama_multi_tf_cal.sql
psql $DATABASE_URL -f sql/ddl/create_cmc_returns_ama_multi_tf_cal_anchor.sql
psql $DATABASE_URL -f sql/ddl/create_cmc_returns_ama_multi_tf_u.sql
psql $DATABASE_URL -f sql/ddl/create_dim_ama_params.sql
```

## Next Phase Readiness
- Schema foundation complete for Phase 35-02 (AMA refresher Python implementation)
- dim_ama_params seeding can happen in 35-02 when KAMA/DEMA/TEMA/HMA param sets are defined
- All tables use IF NOT EXISTS, safe to run DDL multiple times
- Alembic migration for these 25 objects should be added in a future plan

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
