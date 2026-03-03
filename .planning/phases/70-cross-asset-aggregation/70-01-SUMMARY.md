---
phase: 70-cross-asset-aggregation
plan: "01"
subsystem: database
tags: [alembic, postgresql, cross-asset, funding-rates, crypto-macro, correlation, yaml-config]

# Dependency graph
requires:
  - phase: 67-macro-regime-classifier
    provides: cmc_macro_regimes table (ALTER TABLE adds crypto_macro_corr column)
  - phase: 69-l4-resolver-integration
    provides: f1a2b3c4d5e6 alembic head (down_revision for this migration)
provides:
  - cmc_cross_asset_agg table (PK: date) for daily crypto-wide correlation metrics
  - cmc_funding_rate_agg table (PK: date, symbol) for aggregate funding rate signals
  - crypto_macro_corr_regimes table (PK: date, asset_id, macro_var) for crypto-macro correlation
  - crypto_macro_corr TEXT column added to cmc_macro_regimes
  - configs/cross_asset_config.yaml with all XAGG thresholds
affects:
  - 70-02: needs cmc_cross_asset_agg and cmc_funding_rate_agg to write into
  - 70-03: needs crypto_macro_corr_regimes and crypto_macro_corr column in cmc_macro_regimes
  - Phase 71 (risk gates): reads high_corr_flag from cmc_cross_asset_agg

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Alembic migration uses down_revision = actual head (not plan-doc hardcoded value)"
    - "Partial index on boolean flag column for fast sign-flip queries"
    - "No cmc_ prefix for tables mixing crypto + non-crypto (macro) data"

key-files:
  created:
    - alembic/versions/e1f2a3b4c5d6_cross_asset_aggregation_tables.py
    - configs/cross_asset_config.yaml
  modified: []

key-decisions:
  - "down_revision = f1a2b3c4d5e6 (Phase 69 head) not d5e6f7a8b9c0 (Phase 67) -- plan doc was stale"
  - "crypto_macro_corr_regimes drops cmc_ prefix: mixes crypto with FRED macro data per CONTEXT.md rule"
  - "sign_flip_flag gets partial index WHERE sign_flip_flag = TRUE for fast alert queries"
  - "vwap_funding_rate is nullable -- requires volume data that may not always be available"

patterns-established:
  - "Cross-asset config: 5 top-level sections (cross_asset, crypto_macro, funding_agg, portfolio_override, telegram)"
  - "Macro var column mapping stored in YAML (macro_var_columns dict) -- no hardcoding in compute scripts"

# Metrics
duration: 11min
completed: "2026-03-03"
---

# Phase 70 Plan 01: Cross-Asset Aggregation Tables Summary

**Alembic migration e1f2a3b4c5d6 creates 3 cross-asset tables + ALTER TABLE on cmc_macro_regimes, with full YAML threshold config for XAGG-01 through XAGG-04**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-03T12:53:43Z
- **Completed:** 2026-03-03T13:05:11Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Alembic migration with 3 new tables and ALTER TABLE, chaining from actual Phase 69 head (`f1a2b3c4d5e6`), not the stale plan-doc value `d5e6f7a8b9c0`
- All 5 required indexes created including a partial index on `sign_flip_flag = TRUE` for fast sign-flip alert queries
- YAML config with all thresholds for Plans 02 and 03: 30d/60d correlation windows, 0.7 high-corr threshold, 0.3 sign-flip threshold, 6 venues, 4 macro vars with column mapping

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration for 3 new tables + ALTER TABLE** - `9340394a` (feat)
2. **Task 2: YAML configuration for cross-asset thresholds** - `757dc837` (feat)

**Plan metadata:** (see final docs commit)

## Files Created/Modified

- `alembic/versions/e1f2a3b4c5d6_cross_asset_aggregation_tables.py` - DDL for cmc_cross_asset_agg, cmc_funding_rate_agg, crypto_macro_corr_regimes, ALTER TABLE cmc_macro_regimes
- `configs/cross_asset_config.yaml` - All XAGG thresholds: correlation windows, high_corr_threshold=0.7, sign_flip_threshold=0.3, 6 venues, 4 macro vars

## Decisions Made

- **down_revision corrected:** Plan doc specified `d5e6f7a8b9c0` (Phase 67 head) but the actual current head was `f1a2b3c4d5e6` (Phase 69). Used actual head to prevent alembic branch conflicts.
- **No cmc_ prefix on crypto_macro_corr_regimes:** Per CONTEXT.md naming rule, tables mixing crypto and non-crypto (FRED macro) data drop the `cmc_` prefix.
- **vwap_funding_rate nullable:** Volume data from all venues is not guaranteed; VWAP silently omitted when volume unavailable (consistent with CONTEXT.md NaN-exclusion decision).
- **Partial index for sign flips:** `WHERE sign_flip_flag = TRUE` partial index added for Phase 70-03 Telegram alert queries -- only a small fraction of rows will have this flag set.

## Deviations from Plan

None -- plan executed exactly as written, with one anticipated correction (down_revision discovery) explicitly called out in the task specification.

## Issues Encountered

None. ruff-format reformatted one long line in the migration file during pre-commit hook; re-staged and committed cleanly.

## User Setup Required

None - no external service configuration required. Tables deployable via `alembic upgrade head`.

## Next Phase Readiness

- **Plan 02 (cross-asset compute scripts):** All 3 tables ready. `cmc_cross_asset_agg` and `cmc_funding_rate_agg` accept writes immediately after `alembic upgrade head`.
- **Plan 03 (crypto-macro correlation writer):** `crypto_macro_corr_regimes` table ready. `crypto_macro_corr` column added to `cmc_macro_regimes`.
- **Blocker:** None -- Plans 02 and 03 are unblocked by this foundation.

---
*Phase: 70-cross-asset-aggregation*
*Completed: 2026-03-03*
