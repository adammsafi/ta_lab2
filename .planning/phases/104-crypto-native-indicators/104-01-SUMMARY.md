---
phase: 104-crypto-native-indicators
plan: 01
subsystem: features
tags: [hyperliquid, derivatives, oi, funding-rate, alembic, migration, adapter-pattern]

# Dependency graph
requires:
  - phase: 103-ta-expansion
    provides: extended indicator column patterns in features table
  - phase: 109-feature-skip-unchanged
    provides: feature_refresh_state table (actual alembic head u5v6w7x8y9z0)
provides:
  - HyperliquidAdapter: venue-agnostic normalized input layer for derivatives data
  - MockAdapter: graceful degradation / test double with correct schema
  - _get_hl_to_cmc_id_map: HL asset_id -> CMC id resolution via dim_listings JOIN
  - Alembic migration x7y8z9a0b1c2: 8 nullable columns added to public.features
affects:
  - 104-02 (derivatives indicator compute layer will import HyperliquidAdapter)
  - 104-03 (feature refresh wiring will import MockAdapter for testing)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Venue-agnostic adapter pattern (HyperliquidAdapter/MockAdapter share DerivativesFrame schema)
    - HL-to-CMC ID resolution via dim_listings JOIN (same approach as seed_hl_assets.py)
    - ADD COLUMN IF NOT EXISTS for idempotent Alembic migrations

key-files:
  created:
    - src/ta_lab2/features/derivatives_input.py
    - alembic/versions/x7y8z9a0b1c2_phase104_derivatives_features.py
  modified: []

key-decisions:
  - "dim_listings JOIN (not cmc_da_ids): resolves HL asset_id -> CMC id using ticker_on_venue=symbol AND venue='HYPERLIQUID'"
  - "km assets excluded via asset_id < 20000 filter: km perps have no CMC match; consistent with seed_hl_assets.py reclassification"
  - "COALESCE(hl_candles.close_oi, hl_open_interest.close) for OI: primary source is candles (daily), gap-fill from hl_open_interest"
  - "funding_rate is daily SUM not AVG: hourly funding compounds per day; SUM preserves economic interpretation"
  - "mark_px from hl_oi_snapshots via DISTINCT ON (asset_id, day) ORDER BY ts DESC: latest intraday snapshot"
  - "down_revision = u5v6w7x8y9z0 (actual head): phase 109 added that migration after 107; use actual head per project precedent"

patterns-established:
  - "DerivativesFrame schema: [id, venue_id, ts, oi, funding_rate, volume, close, mark_px] -- canonical 8-column contract"
  - "Adapter pattern: VENUE_ID class attribute + load(cmc_ids, start, end, tf) interface for venue-agnostic data access"

# Metrics
duration: 8min
completed: 2026-04-01
---

# Phase 104 Plan 01: Crypto-Native Indicators Input Layer Summary

**HyperliquidAdapter + MockAdapter with DerivativesFrame schema, Alembic migration adding 8 derivatives indicator columns to public.features**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-01T00:00:00Z
- **Completed:** 2026-04-01T00:08:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Implemented `HyperliquidAdapter` that resolves HL asset_id to CMC id via `dim_listings` JOIN, then queries `hl_candles`, `hl_funding_rates`, `hl_open_interest`, and `hl_oi_snapshots` into a unified daily DataFrame keyed on CMC id
- Implemented `MockAdapter` returning an empty DataFrame with the correct 8-column schema for testing and graceful degradation
- Created Alembic migration `x7y8z9a0b1c2` adding 8 nullable derivatives indicator columns (`oi_mom_14`, `oi_price_div_z`, `funding_z_14`, `funding_mom_14`, `vol_oi_regime`, `force_idx_deriv_13`, `oi_conc_ratio`, `liq_pressure`) to `public.features`

## Task Commits

Each task was committed atomically:

1. **Task 1: HyperliquidAdapter, MockAdapter, ID mapping** - `bacd01ff` (feat)
2. **Task 2: Alembic migration for derivatives columns** - `6beb1eb8` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/features/derivatives_input.py` - HyperliquidAdapter, MockAdapter, _get_hl_to_cmc_id_map
- `alembic/versions/x7y8z9a0b1c2_phase104_derivatives_features.py` - Adds 8 nullable columns to public.features

## Decisions Made

- `dim_listings JOIN` (not `cmc_da_ids`): resolves HL asset_id to CMC id using `ticker_on_venue=symbol AND venue='HYPERLIQUID'`. This is the seeded mapping from `seed_hl_assets.py`, not a raw CMC symbol lookup.
- km assets excluded via `asset_id < 20000` filter: km perps (indices, commodities, FX, equities) have no CMC id and should not appear in the derivatives frame.
- `COALESCE(hl_candles.close_oi, hl_open_interest.close)` for OI: candles are primary (daily resolution), `hl_open_interest` provides gap fill for days when candle OI is NULL.
- `funding_rate` aggregated via `SUM` not `AVG`: hourly funding compounds per day; SUM preserves economic interpretation (total daily funding cost).
- `mark_px` from `hl_oi_snapshots` via `DISTINCT ON (asset_id, day) ORDER BY ts DESC`: latest intraday snapshot per day, not the stale value from `hl_assets`.
- `down_revision = u5v6w7x8y9z0`: actual head after phases 100, 102, 103, 109 all added migrations post-phase 107. Uses actual head per established project precedent.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Ruff reformatted `derivatives_input.py` (dict comprehension wrapped across lines) on first commit attempt. Restaged and recommitted cleanly.
- Ruff removed unused `import sqlalchemy as sa` from migration file. Restaged and recommitted cleanly.

## User Setup Required

None - no external service configuration required. Run `alembic upgrade head` to apply the migration.

## Next Phase Readiness

- `HyperliquidAdapter` and `MockAdapter` are importable and tested.
- Alembic migration chains correctly from `u5v6w7x8y9z0` to `x7y8z9a0b1c2`.
- Phase 104-02 can import `HyperliquidAdapter` from `ta_lab2.features.derivatives_input` and begin implementing indicator compute functions.
- Run `alembic upgrade head` before Phase 104-02 to add the 8 columns to the live database.

---
*Phase: 104-crypto-native-indicators*
*Completed: 2026-04-01*
