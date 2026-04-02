# Phase 111: Feature Polars Migration

**Goal:** Migrate feature computation sub-phases from pandas to polars for 2-5x performance improvement on rolling operations, groupby, and joins. Target: 60 min → 20-30 min for full recompute.

## Problem

Feature computation uses pandas throughout — `df.rolling()`, `df.groupby()`, `df.apply()` for vol, ta, cycle stats, etc. Polars is 2-5x faster for these operations and already proven in the bar builders.

## Regression Risk — Critical Section

**This is the highest-risk optimization in the pipeline.** Downstream consumers (IC analysis, signals, backtests, portfolio allocation) were all calibrated against pandas-computed feature values. Even tiny systematic differences will shift signal thresholds, IC scores, and backtest results.

### Specific Regression Vectors

1. **Float ordering with NaN**: pandas sorts NaN-last, polars NaN-first. Rolling windows hitting NaN produce different boundary calculations.

2. **Rolling window edge behavior**: pandas `rolling(30).mean()` returns NaN for first 29 rows (min_periods=30 default). Polars `roll_mean(30)` may differ in partial window handling.

3. **Timezone precision**: pandas `datetime64[ns, UTC]` vs polars `Datetime('us', 'UTC')`. Nanosecond vs microsecond can cause JOIN mismatches or off-by-one-microsecond issues in merge_asof operations.

4. **GroupBy ordering**: pandas preserves input order within groups, polars doesn't guarantee it. Feature computations depending on row order need explicit `sort()`.

5. **Float precision accumulation**: IEEE 754 operations in different order (pandas uses numpy, polars uses Arrow/Rust) can produce ~1e-15 differences that accumulate in long rolling windows.

### Mitigation Strategy

Each sub-phase migration MUST follow this protocol:

1. **Snapshot before**: For test assets (id=1, 1027, 5426), capture full feature output (all columns, all TFs) as a baseline CSV.

2. **Migrate one sub-phase at a time**: Never convert more than one sub-phase per plan. If vol breaks, we know exactly where.

3. **Compare after**: Run migrated sub-phase, capture output, diff against baseline:
   - Exact match for integer/boolean columns
   - Within 1e-10 relative tolerance for float columns
   - NaN positions must match exactly
   - Row counts must match exactly

4. **IC regression test**: After each sub-phase migration, run IC analysis on test assets. IC-IR values must be within 1% of pre-migration values. If >1% drift, the migration introduced meaningful numeric differences.

5. **Signal regression test**: After ALL sub-phases migrated, run signal generation and compare signal counts and directions. Any signal flip (long→short or vice versa) on test assets is a blocker.

6. **Backtest regression test**: Run bakeoff strategies on test assets. Sharpe ratios must be within 5% of pre-migration values.

7. **Rollback plan**: Each sub-phase keeps the pandas implementation as `_compute_vol_pandas()` alongside the new `_compute_vol_polars()`, controlled by a `--use-polars` flag. Default remains pandas until all regression tests pass. Then flip default and deprecate pandas path.

## Sub-Phase Migration Order (safest first)

| Order | Sub-phase | Risk | Reason |
|-------|-----------|------|--------|
| 1 | CS norms | Low | Simple cross-sectional z-scores, no rolling windows |
| 2 | cycle_stats | Low | Bar counting, no complex rolling |
| 3 | rolling_extremes | Medium | Rolling min/max — NaN handling matters |
| 4 | vol | Medium | Rolling std/var — float precision matters |
| 5 | ta | Medium-High | RSI, ATR, EMA — complex stateful indicators |
| 6 | microstructure | Medium | Depends on vol output |
| 7 | features (unified) | Low | Assembly/join, not computation |
| 8 | CTF | High | merge_asof + cross-TF joins — timezone precision critical |

## Dependencies

- Phase 109 (skip unchanged) — reduces test surface
- Phase 110 (parallel sub-phases) — establishes wave structure that polars fits into
- Should be LAST feature optimization phase

## Success Criteria

- [ ] All 8 sub-phases have polars implementations
- [ ] IC-IR regression < 1% for test assets on every sub-phase
- [ ] Signal count regression = 0 (no signal flips)
- [ ] Backtest Sharpe regression < 5% for bakeoff strategies
- [ ] `--use-polars` flag controls migration (default: polars after validation)
- [ ] `--use-pandas` fallback preserved for debugging
- [ ] Feature refresh full recompute < 30 min
