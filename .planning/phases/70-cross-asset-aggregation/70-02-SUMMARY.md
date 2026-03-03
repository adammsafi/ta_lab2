---
phase: 70-cross-asset-aggregation
plan: "02"
subsystem: macro
tags: [cross-asset, correlation, funding-rates, crypto-macro, rolling-corr, z-scores, sign-flip, pandas, sqlalchemy, cli, daily-refresh]

# Dependency graph
requires:
  - phase: 70-01
    provides: cmc_cross_asset_agg, cmc_funding_rate_agg, crypto_macro_corr_regimes tables + YAML config
  - phase: 67-macro-regime-classifier
    provides: cmc_macro_regimes table (crypto_macro_corr column added in 70-01)
  - phase: 65-macro-features
    provides: fred.fred_macro_features (VIX, DXY, HY OAS, net_liquidity columns)
provides:
  - cross_asset.py: 4 compute functions (XAGG-01 through XAGG-04) + 4 upsert functions
  - refresh_cross_asset_agg.py: CLI entry point with --dry-run/--full/--verbose/--skip-* flags
  - run_daily_refresh.py: cross-asset agg step after macro_analytics in --all pipeline
  - ROADMAP.md: success criterion 1 corrected to cmc_cross_asset_agg (not fred_macro_features)
affects:
  - 70-03: uses crypto_macro_corr from cross_asset.py for portfolio covariance override + Telegram alerts
  - Phase 71 (risk gates): reads high_corr_flag from cmc_cross_asset_agg
  - run_daily_refresh.py --all: now includes cross-asset aggregation step

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "XAGG rolling corr: pandas rolling(window).corr() for BTC/ETH pair; numpy upper-triangle mean for pairwise avg"
    - "Average pairwise correlation: window-slice per date + dropna(axis=1, how='any') + corr() + triu_indices"
    - "Funding rate z-scores: per-symbol groupby + rolling mean/std with ddof=1"
    - "Crypto-macro sign-flip: prev_corr = roll_corr.shift(1) + magnitude threshold check (both directions)"
    - "Daily aggregate regime: ANY sign_flip -> flipping, majority correlated -> correlated, else decorrelated"
    - "update_macro_regime_corr: batch parameterized UPDATE (not upsert) -- regime classifier owns row insertion"

key-files:
  created:
    - src/ta_lab2/macro/cross_asset.py
    - src/ta_lab2/scripts/macro/refresh_cross_asset_agg.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py
    - .planning/ROADMAP.md

key-decisions:
  - "TVC returns: load daily close from tvc_price_histories, compute pct_change() per asset -- include in pairwise corr matrix"
  - "TVC asset IDs prefixed with 'tvc_' to avoid collision with CMC integer IDs in pivot table"
  - "BTC/ETH IDs: DB lookup from cmc_price_histories7, fallback to hardcoded 1/52 on error"
  - "Pairwise corr: window-slice approach (not rolling().corr() full matrix) -- more memory-efficient for many assets"
  - "Funding rate update_macro_regime_corr: UPDATE (not upsert) because macro regime classifier owns row insertion"
  - "ROADMAP.md criterion 1 updated from fred_macro_features to cmc_cross_asset_agg per CONTEXT.md decision"

patterns-established:
  - "XAGG compute functions: engine + config + optional start/end date -> DataFrame pattern (same as regime_classifier)"
  - "XAGG upserts: temp table LIKE target INCLUDING DEFAULTS + to_sql + ON CONFLICT DO UPDATE SET"
  - "Daily refresh integration: run_cross_asset_agg() subprocess with TIMEOUT_CROSS_ASSET_AGG=600s"

# Metrics
duration: 8min
completed: "2026-03-03"
---

# Phase 70 Plan 02: Cross-Asset Aggregation Core Compute Summary

**4-function XAGG compute engine (BTC/ETH corr, pairwise corr with high_corr_flag, funding rate z-scores, crypto-macro sign-flip regime) with CLI script and daily refresh pipeline integration**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-03T13:18:31Z
- **Completed:** 2026-03-03T13:26:03Z
- **Tasks:** 3 (Tasks 1+2 share same file; Task 3 = CLI + wiring + ROADMAP)
- **Files modified:** 4

## Accomplishments

- All 4 XAGG computation functions implemented with watermark-based incremental refresh:
  - `compute_cross_asset_corr()`: BTC/ETH 30d rolling Pearson correlation (XAGG-01) + average pairwise correlation with `high_corr_flag` (XAGG-02), covering both CMC and TVC assets
  - `compute_funding_rate_agg()`: aggregate funding rate with 30d/90d rolling z-scores per symbol (XAGG-03)
  - `compute_crypto_macro_corr()`: 60d rolling crypto-macro Pearson correlation with sign-flip detection and regime labeling (XAGG-04), returns both per-asset detail and daily aggregate label
- 4 DB upsert functions following temp table + ON CONFLICT pattern from codebase conventions
- CLI script with --dry-run, --full, --verbose, --start-date/--end-date, --skip-corr/--skip-funding/--skip-macro-corr flags
- Pipeline integration: cross-asset agg step runs after macro_analytics and before per-asset regimes in `--all`
- ROADMAP.md success criterion 1 corrected per CONTEXT.md decision

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2: cross_asset.py with all 4 XAGG compute + upsert functions** - `51d43835` (feat)
2. **Task 3: CLI script + daily refresh wiring + ROADMAP fix** - `1de4623a` (feat)

**Plan metadata:** (see final docs commit)

## Files Created/Modified

- `src/ta_lab2/macro/cross_asset.py` - Core XAGG engine: `compute_cross_asset_corr`, `compute_funding_rate_agg`, `compute_crypto_macro_corr`, `upsert_cross_asset_agg`, `upsert_funding_rate_agg`, `upsert_crypto_macro_corr`, `update_macro_regime_corr`, `load_cross_asset_config`, `get_watermark`
- `src/ta_lab2/scripts/macro/refresh_cross_asset_agg.py` - CLI entry point for all 4 XAGG computations
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added `run_cross_asset_agg()`, `TIMEOUT_CROSS_ASSET_AGG=600`, `--cross-asset-agg`/`--no-cross-asset-agg` flags, pipeline wiring
- `.planning/ROADMAP.md` - Phase 70 success criterion 1 updated from `fred_macro_features` to `cmc_cross_asset_agg`

## Decisions Made

- **TVC assets in pairwise correlation:** Load TVC daily closes and compute `pct_change()` per asset, prefix IDs with `tvc_` to avoid collision with CMC integer IDs in the pivot table.
- **Average pairwise correlation approach:** Window-slice per date + `dropna(axis=1, how='any')` + `.corr()` + `numpy.triu_indices` rather than `rolling().corr()` full matrix -- more memory-efficient for many assets and avoids partial-window artifacts.
- **`update_macro_regime_corr` is UPDATE not upsert:** The macro regime classifier owns row insertion into `cmc_macro_regimes`; we only UPDATE the `crypto_macro_corr` column for dates that already exist. This prevents phantom rows.
- **BTC/ETH ID lookup:** DB lookup from `cmc_price_histories7` with fallback to hardcoded (1, 52) -- consistent with MEMORY.md gotchas about not hardcoding IDs when avoidable.
- **ROADMAP.md criterion corrected:** Plan said `fred_macro_features`, CONTEXT.md explicitly says BTC/ETH correlation belongs in the cross-asset table (not FRED table). Updated.

## Deviations from Plan

None -- plan executed exactly as written, with all 4 XAGG functions, all upserts, CLI script, pipeline wiring, and ROADMAP fix completed as specified.

## Issues Encountered

Pre-commit hook (ruff-format) reformatted the CLI script after first commit attempt. Re-staged and committed cleanly on the second attempt.

## User Setup Required

None - no external service configuration required. `alembic upgrade head` (from Plan 01) is the prerequisite.

## Next Phase Readiness

- **Plan 03 (portfolio optimizer covariance override + Telegram sign-flip alerts):** `high_corr_flag` is now populated daily in `cmc_cross_asset_agg`. `sign_flip_flag` is populated in `crypto_macro_corr_regimes`. Both are readable immediately after `refresh_cross_asset_agg --full` run against a populated DB.
- **Phase 71 (event risk gates):** `high_corr_flag` is available for the composite macro stress score.
- **Blocker:** None. Plans 01 and 02 both complete; Plan 03 is unblocked.

---
*Phase: 70-cross-asset-aggregation*
*Completed: 2026-03-03*
