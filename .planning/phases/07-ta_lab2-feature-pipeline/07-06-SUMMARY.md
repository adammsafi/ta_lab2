---
phase: 07-ta_lab2-feature-pipeline
plan: 06
subsystem: features
tags: [feature-store, materialized-view, join, sql, incremental-refresh, ml-pipeline]

# Dependency graph
requires:
  - phase: 07-03
    provides: Returns features in cmc_returns_daily
  - phase: 07-04
    provides: Volatility features in cmc_vol_daily
  - phase: 07-05
    provides: Technical indicators in cmc_ta_daily
  - phase: 06-ta_lab2-time-model
    provides: dim_timeframe and dim_sessions for metadata
provides:
  - cmc_daily_features unified feature store table
  - DailyFeaturesStore class for incremental refresh
  - refresh_cmc_daily_features CLI script
  - Single-table access to all daily features for ML pipelines
  - Graceful degradation when source tables missing
  - 18 comprehensive tests (all passing)
affects: [08-signal-generation, ml-training, feature-engineering]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Feature store pattern with materialized table (not view)"
    - "Source watermark tracking for dirty window computation"
    - "LEFT JOINs for graceful degradation when sources missing"
    - "EMA pivot from long to wide format for specific periods"

key-files:
  created:
    - sql/views/050_cmc_daily_features.sql
    - src/ta_lab2/scripts/features/daily_features_view.py
    - src/ta_lab2/scripts/features/refresh_cmc_daily_features.py
    - tests/features/test_daily_features_view.py
  modified: []

key-decisions:
  - "Materialized table (not view): Too slow for ML queries, needs incremental refresh for performance"
  - "Source watermark tracking: MIN of all source table watermarks determines dirty window start"
  - "LEFT JOINs for all optional sources: Returns NULL columns when source missing, never fails entire refresh"
  - "EMA pivot for 1D timeframe: Select specific periods (9, 10, 21, 50, 200) from long format cmc_ema_multi_tf_u"
  - "Asset class from dim_sessions: Enables filtering by market type (crypto, equity) in ML queries"
  - "Data quality flags union: has_price_gap from returns, has_outlier OR across returns/vol/TA"

patterns-established:
  - "DailyFeaturesStore.check_source_tables_exist(): Graceful degradation - log warnings, continue with available sources"
  - "DailyFeaturesStore.get_source_watermarks(): Query FeatureStateManager for each feature_type, return MIN timestamp"
  - "DailyFeaturesStore.compute_dirty_window(): Conservative approach - start from MIN of all source watermarks"
  - "DailyFeaturesStore._build_join_query(): Dynamic SQL generation based on sources_available dict"
  - "refresh_daily_features() convenience function: Creates state manager, delegates to store for simpler CLI usage"

# Metrics
duration: 7min
completed: 2026-01-30
---

# Phase 7 Plan 06: Daily Features Store Summary

**Unified cmc_daily_features materialized table joining prices, EMAs, returns, volatility, and TA indicators with incremental refresh via source watermark tracking - 18 tests passing**

## Performance

- **Duration:** 7 min
- **Started:** 2026-01-30T17:57:23Z
- **Completed:** 2026-01-30T18:04:35Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Created cmc_daily_features table DDL with 70+ columns from all feature sources
- Implemented DailyFeaturesStore with source watermark tracking and dirty window computation
- Built refresh_cmc_daily_features CLI with --ids, --all, --start, --full-refresh options
- Achieved 18/18 tests passing covering all refresh scenarios and graceful degradation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create cmc_daily_features DDL** - `d1902a2` (feat)
2. **Task 2: Create DailyFeaturesStore class** - `433b2d3` (feat)
3. **Task 3: Create refresh script and tests** - `772c23a` (feat)

## Files Created/Modified

- `sql/views/050_cmc_daily_features.sql` - Unified feature store DDL with OHLCV, EMAs, returns, volatility, TA indicators, asset_class metadata, and data quality flags
- `src/ta_lab2/scripts/features/daily_features_view.py` - DailyFeaturesStore class managing incremental refresh with source watermark tracking, dirty window computation, and graceful degradation
- `src/ta_lab2/scripts/features/refresh_cmc_daily_features.py` - CLI refresh script with ID selection (--ids/--all), date range, full refresh, and dry-run modes
- `tests/features/test_daily_features_view.py` - 18 comprehensive tests covering source checking, watermarks, dirty windows, JOIN queries, NULL handling, incremental/full refresh, graceful degradation

## Decisions Made

**Materialized table (not view):**
- ML queries on view would be too slow (join 5 tables on every SELECT)
- Materialized table enables single-table access with sub-second query times
- Trade-off: Requires incremental refresh logic vs view auto-updates

**Source watermark tracking:**
- Query FeatureStateManager for each feature_type (price_bars, ema_multi_tf, returns, vol, ta)
- Dirty window starts from MIN of all source watermarks (most conservative)
- Ensures no data missed when one source lags behind others

**LEFT JOINs for graceful degradation:**
- All optional sources (emas, returns, vol, ta) use LEFT JOIN
- Missing source results in NULL columns, not query failure
- Enables phased rollout (e.g., populate prices first, add features incrementally)

**EMA pivot from long to wide:**
- cmc_ema_multi_tf_u stores EMAs in long format (one row per period/tf combination)
- Feature store pivots to wide format for 1D timeframe (ema_9, ema_21, etc.)
- Simplifies ML queries: SELECT ema_21 vs JOIN WHERE period=21

**Asset class from dim_sessions:**
- Includes asset_class column (crypto, equity) via LEFT JOIN to dim_sessions
- Enables market-type filtering in ML queries: WHERE asset_class='crypto'
- Critical for strategy deployment (different markets need different models)

**Data quality flags union:**
- has_price_gap: TRUE when returns.gap_days > 1 (missing bars detected)
- has_outlier: OR across returns.is_outlier, vol.*_is_outlier, ta.is_outlier
- Single flag simplifies filtering: WHERE NOT has_outlier

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**Test failures on first run:**
- Problem 1: test_graceful_missing_source_table tried to access sources_available as keyword arg (KeyError)
- Solution: Changed to positional arg access (call_args[0][3]) since _build_join_query uses positional args
- Problem 2: test_refresh_daily_features_creates_components mocked wrong import path for FeatureStateManager
- Solution: Changed patch path from daily_features_view to feature_state_manager (where it's imported from)
- Resolution: All 18 tests passing

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for ML training (Phase 8+):**
- Single-table access to all daily features via cmc_daily_features
- Asset class filtering enables market-specific models
- Data quality flags enable robust dataset filtering
- Incremental refresh keeps features fresh without full recomputation

**Ready for signal generation:**
- Combined price/EMA/returns/vol/TA features enable multi-indicator strategies
- Z-score normalized features ready for threshold-based signals
- Outlier flags enable robust backtesting (exclude anomalies)

**Ready for production:**
- Graceful degradation handles missing source tables
- Incremental refresh minimizes computation time
- State tracking enables resume after interruption

**No blockers** - unified feature store complete and tested.

## Technical Notes

**Feature store refresh flow:**
1. Check which source tables exist and have data (check_source_tables_exist)
2. Query watermarks for each source from FeatureStateManager (get_source_watermarks)
3. Compute dirty window: start=MIN(watermarks), end=now() (compute_dirty_window)
4. Delete existing rows in dirty window
5. Build dynamic JOIN query based on sources_available (_build_join_query)
6. Execute INSERT from JOIN query
7. Update state with new watermark (_update_state)

**Graceful degradation strategy:**
- Required source: price_bars (fail if missing)
- Optional sources: emas, returns, vol, ta (NULL columns if missing)
- Log warnings for missing sources but continue refresh
- Enables phased rollout and partial functionality during outages

**Source watermark MIN rationale:**
- Most conservative approach: refresh from earliest source watermark
- Ensures no data missed when one source lags (e.g., vol refresh delayed)
- Alternative (MAX) would miss rows where only one source has new data
- Trade-off: May recompute more rows than strictly necessary, but guarantees correctness

**EMA pivot implementation:**
- Multiple LEFT JOINs to cmc_ema_multi_tf_u filtered by period and tf='1D'
- One subquery per period: e9 (period=9), e10 (period=10), etc.
- Selects ema and ema_d1 (first derivative) for each period
- Efficient for small set of periods, would need dynamic approach for many periods

---
*Phase: 07-ta_lab2-feature-pipeline*
*Completed: 2026-01-30*
