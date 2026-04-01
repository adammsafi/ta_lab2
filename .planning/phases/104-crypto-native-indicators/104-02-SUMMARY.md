---
phase: 104-crypto-native-indicators
plan: 02
subsystem: features
tags: [hyperliquid, derivatives, oi, funding-rate, indicators, feature-compute, base-feature]

# Dependency graph
requires:
  - phase: 104-01
    provides: HyperliquidAdapter, MockAdapter, DerivativesFrame schema, 8-column Alembic migration
  - phase: 103-ta-expansion
    provides: BaseFeature template method pattern, TAFeature model, indicators.py _ema helper
provides:
  - indicators_derivatives.py: 8 derivatives indicator functions (oi_momentum, oi_price_divergence,
    funding_zscore, funding_momentum, vol_oi_regime, force_index_deriv, oi_concentration_ratio,
    liquidation_pressure)
  - DerivativesFeature(BaseFeature): orchestrates load -> compute -> write pipeline
  - DerivativesConfig(FeatureConfig): configuration dataclass with venue_id=2 (HYPERLIQUID)
  - CLI entry point: python -m ta_lab2.scripts.features.derivatives_feature
affects:
  - 104-03 (feature refresh wiring and testing will import DerivativesFeature)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Per-asset groupby for single-asset indicators, full-frame pass for cross-asset indicators
    - Pre-flight migration check (information_schema) replaces _ensure_output_table CREATE TABLE
    - INT64 nullable integer regime via pd.array(..., dtype="Int64") for vol_oi_regime
    - fill_method=None in pct_change() to avoid deprecated default fill behavior

key-files:
  created:
    - src/ta_lab2/features/indicators_derivatives.py
    - src/ta_lab2/scripts/features/derivatives_feature.py
  modified: []

key-decisions:
  - "Per-asset groupby for indicators 1-6: sort by ts within each (id, venue_id) group before compute"
  - "oi_concentration_ratio called on full sorted frame (ts, id): cross-asset total_oi requires all assets at same ts"
  - "_ensure_output_table overridden to skip CREATE TABLE: public.features managed by Alembic; run pre-flight check instead"
  - "add_normalizations and add_outlier_flags no-ops: derivatives indicators do not get zscore/outlier columns"
  - "pct_change(fill_method=None) fixes FutureWarning: deprecated default fill_method='pad' removed"
  - "vol_oi_regime uses pd.array(..., dtype='Int64'): preserves nullable integer semantics; np.select default=0 maps to pd.NA"

patterns-established:
  - "Cross-asset pattern: compute per-asset groupby first, then concat full frame for cross-asset step, then composite"
  - "Pre-flight check pattern: information_schema.columns count > 0 before write; RuntimeError with alembic upgrade guidance"

# Metrics
duration: 8min
completed: 2026-04-01
---

# Phase 104 Plan 02: Crypto-Native Indicators Compute Layer Summary

**8 derivatives indicator functions (OI momentum, funding z-score, liquidation pressure, etc.) and DerivativesFeature orchestration class writing 2374 rows to public.features**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-01T22:06:40Z
- **Completed:** 2026-04-01T22:14:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Implemented all 8 derivatives indicator functions in `indicators_derivatives.py` following the `indicators.py` API convention (df, window/params, *, col_args, out_col, inplace)
- `vol_oi_regime` returns INTEGER 1-6 (nullable Int64) using `np.select` with Kaufman matrix classification; all 6 distinct values verified in DB
- `oi_concentration_ratio` is genuinely cross-asset: `groupby(ts)[oi].transform('sum')` computes total OI at each timestamp before per-asset rolling z-score
- `DerivativesFeature(BaseFeature)` orchestrates the 3-step pipeline: per-asset groupby (indicators 1-6), cross-asset full frame (7), composite (8)
- Pre-flight migration check replaces `_ensure_output_table` CREATE TABLE to prevent silent data loss when migration not applied
- Verified 2374 rows written to `public.features` for BTC and ETH with `oi_mom_14 NOT NULL`

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement 8 derivatives indicator functions** - `a529fa20` (feat)
2. **Task 2: DerivativesFeature class, CLI, and pct_change deprecation fix** - `38687f28` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/features/indicators_derivatives.py` - 8 indicator functions with `__all__` exports
- `src/ta_lab2/scripts/features/derivatives_feature.py` - DerivativesFeature, DerivativesConfig, CLI main()

## Decisions Made

- Per-asset groupby sorts by `ts` within each `(id, venue_id)` group before computing indicators 1-6; this is required for correct rolling window behavior when rows arrive unsorted.
- `oi_concentration_ratio` called on the full concatenated and sorted (by `ts, id`) frame after per-asset step completes. Cross-asset `total_oi` requires simultaneous presence of all asset rows at the same timestamp.
- `_ensure_output_table` overridden to skip CREATE TABLE: `public.features` is Alembic-managed. Pre-flight raises `RuntimeError` with exact `alembic upgrade head` guidance if migration absent.
- `add_normalizations` and `add_outlier_flags` are no-ops: derivatives indicators are raw signals; zscore and outlier columns are not in the migration DDL.
- `pct_change(fill_method=None)` applied to suppress FutureWarning from deprecated `fill_method='pad'` default. This was a Rule 1 auto-fix (bug: deprecated API that breaks in future pandas).
- `vol_oi_regime` uses `pd.array(..., dtype='Int64')` to store nullable integer (first bar is `pd.NA` since `diff(1)` produces NaN on row 0).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Suppressed deprecated pct_change fill_method FutureWarning**

- **Found during:** Task 2 (CLI end-to-end verification)
- **Issue:** `Series.pct_change()` without `fill_method=None` emits FutureWarning about removal of deprecated `fill_method='pad'` default
- **Fix:** Added `fill_method=None` to both `pct_change` calls in `oi_momentum` and `oi_price_divergence`
- **Files modified:** `src/ta_lab2/features/indicators_derivatives.py`
- **Verification:** Re-ran CLI, no FutureWarnings in output
- **Committed in:** `38687f28` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor fix; no scope creep. Prevents silent breakage in future pandas version.

## Issues Encountered

None.

## User Setup Required

Migration must be applied before running:
```bash
alembic upgrade head
```
(Migration `x7y8z9a0b1c2` adds the 8 nullable derivatives columns to `public.features`.)

## Next Phase Readiness

- `indicators_derivatives.py` exports all 8 functions; importable and verified.
- `DerivativesFeature` runs end-to-end and writes to `public.features`.
- Phase 104-03 can import `DerivativesFeature` and wire it into `run_all_feature_refreshes.py`.
- `MockAdapter` (from 104-01) can be injected as `adapter=MockAdapter()` for unit testing graceful degradation.

---
*Phase: 104-crypto-native-indicators*
*Completed: 2026-04-01*
