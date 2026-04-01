---
phase: 106-custom-composite-indicators
plan: 01
subsystem: features
tags: [composite-indicators, ama, kama, efficiency-ratio, ctf, hyperliquid, open-interest, funding-rate, lead-lag, alembic, migration]

# Dependency graph
requires:
  - phase: 104-crypto-native-indicators
    provides: derivatives_input.py HL adapter patterns + hl_open_interest/hl_funding_rates tables
  - phase: 98-ctf-graduation
    provides: lead_lag_ic table + load_ctf_features() + ctf fact table
  - phase: 94-ama-multi-tf
    provides: ama_multi_tf table with indicator='KAMA' and er column

provides:
  - Alembic migration z9a0b1c2d3e4: source_type TEXT column + CHECK on dim_feature_registry; 6 FLOAT columns on features
  - composite_indicators.py: 6 proprietary compute functions + 7 input loaders + COMPOSITE_NAMES + ALL_COMPOSITES registry

affects:
  - 106-02 (composite refresh script that calls ALL_COMPOSITES)
  - 106-03 (validation + IC sweep of composites)
  - 107-pipeline (orchestrator may need to invoke composite refresh)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - rolling-rank-pct for ER regime quantile (er.rolling(60).rank(pct=True))
    - tanh continuous gating instead of binary volume regime threshold
    - IC-weighted cross-asset feature combination with lead-lag shift
    - CTF agreement as multiplicative gate on derived signals
    - Private _load_* helpers returning NaN-safe pd.Series with UTC DatetimeIndex

key-files:
  created:
    - alembic/versions/z9a0b1c2d3e4_phase106_composite_source_type.py
    - src/ta_lab2/features/composite_indicators.py
  modified: []

key-decisions:
  - "Revision ID z9a0b1c2d3e4 chains from y8z9a0b1c2d3 (Phase 105 actual head)"
  - "ADD COLUMN IF NOT EXISTS + DO $$ BLOCK for CHECK constraint: full idempotency on re-run"
  - "ALL_COMPOSITES assertion at module load: registry/COMPOSITE_NAMES mismatch raises AssertionError immediately"
  - "CTF agreement defaults to 1.0 (neutral gate) when ctf table has no rows: preserves OI divergence signal instead of returning all-NaN"
  - "HL funding aggregation done Python-side (resample('1D').sum()) not SQL-side: consistent with HyperliquidAdapter pattern"
  - "_TF_ALIGNMENT_PAIRS = [(1D,7D),(1D,14D),(1D,30D),(7D,30D)]: warns if <3 pairs available but still returns result"
  - "Volume gate uses tanh(vol_ratio) rescaled to [0,1]: trend is dampened in low-vol, never sign-flipped"
  - "Lead-lag composite uses asset_b_id=target_asset_id query: target is follower (asset_b), predictor is asset_a"

patterns-established:
  - "NaN-safe composite pattern: every compute_* catches Exception, logs, returns _empty Series"
  - "Input loaders return empty DataFrame/Series on any error, never raise"
  - "pd.to_datetime(utc=True) on all ts columns (never parse_dates)"
  - "sqlalchemy.text() for all SQL queries in input loaders"

# Metrics
duration: 6min
completed: 2026-04-01
---

# Phase 106 Plan 01: Custom Composite Indicators Summary

**Alembic migration adds 6 FLOAT columns + source_type to schema; composite_indicators.py implements all 6 proprietary formulas combining AMA ER, CTF agreement, HL OI/funding, cross-asset lead-lag, and volume gating**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-01T23:08:01Z
- **Completed:** 2026-04-01T23:14:17Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- Alembic migration z9a0b1c2d3e4 applied: 6 FLOAT NULL composite columns added to `public.features`, `source_type TEXT` + CHECK constraint added to `public.dim_feature_registry`; verified via information_schema query
- `composite_indicators.py` (600+ LOC) implements 6 proprietary formulas: AMA ER regime signal, OI-divergence x CTF agreement, funding-adjusted momentum (HL perp only), cross-asset lead-lag composite (IC-weighted), TF alignment score (4-pair average), volume-regime-gated trend (tanh continuous gate)
- 7 private input loaders isolate SQL access: `_load_ama_er`, `_load_price_bars`, `_resolve_hl_asset_id`, `_load_hl_oi`, `_load_hl_funding`, `_load_lead_lag_metadata`, `_load_ctf_agreement_col`
- `COMPOSITE_NAMES` list and `ALL_COMPOSITES` dict provide the registry for Plans 02-03

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration** - `a4678803` (feat)
2. **Task 2: composite_indicators.py** - `b861d16f` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `alembic/versions/z9a0b1c2d3e4_phase106_composite_source_type.py` - Migration: source_type + 6 composite columns
- `src/ta_lab2/features/composite_indicators.py` - 6 composite compute functions + input loaders + registry

## Decisions Made

- Revision ID z9a0b1c2d3e4 chains from y8z9a0b1c2d3 (Phase 105 actual head); plan spec listed u5v6w7x8y9z0 (stale per established precedent of using actual alembic heads output)
- DO $$ BLOCK for CHECK constraint idempotency: avoids hardcoded auto-generated constraint name
- CTF agreement defaults to 1.0 when absent: OI divergence signal preserved (neutral gate), not silently zeroed
- tanh volume gate rescaled to [0,1]: trend dampened in low-vol, not sign-flipped (continuous vs binary gate)
- Lead-lag composite: asset_b_id = target_asset_id (follower), asset_a_id = predictor; matches lead_lag_ic schema from Phase 98-04
- ALL_COMPOSITES assertion at module load catches registry/COMPOSITE_NAMES mismatch immediately

## Deviations from Plan

None - plan executed exactly as written. Migration revision ID updated per established project precedent (actual alembic heads, not plan spec).

## Issues Encountered

None.

## Next Phase Readiness

- Plan 02 (composite refresh script) can import ALL_COMPOSITES directly and call each function per asset/tf
- Plan 03 (validation + IC sweep) has the 6 columns in the features table ready to receive data
- HL-dependent composites (Composites 2 and 3) require `cmc_symbol` parameter; Plan 02 must resolve symbol from dim_listings

---
*Phase: 106-custom-composite-indicators*
*Completed: 2026-04-01*
