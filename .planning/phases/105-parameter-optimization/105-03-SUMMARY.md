---
phase: 105-parameter-optimization
plan: 03
subsystem: analysis
tags: [optuna, parameter-sweep, ic-optimization, indicators, argparse, sqlalchemy]

# Dependency graph
requires:
  - phase: 105-02
    provides: plateau_score, rolling_stability_test, compute_dsr_over_sweep, select_best_from_sweep in param_optimizer.py
  - phase: 103-ta-expansion
    provides: 18 traditional TA indicators (indicators.py, indicators_extended.py)
  - phase: 104-crypto-native-indicators
    provides: 8 crypto-native indicators (indicators_derivatives.py)
provides:
  - "run_param_sweep.py CLI runner for Phase 105 parameter sweeps"
  - "PARAM_SPACE_REGISTRY mapping 22 indicators to param spaces and feature function paths"
  - "_resolve_feature_fn for dynamic indicator function import"
  - "_load_survivors querying dim_feature_registry for FDR passers"
  - "_load_data_for_asset loading OHLCV + fwd_ret from price_bars_multi_tf_u + returns_bars_multi_tf_u"
  - "Full CLI with --indicator, --asset-id, --tf, --dry-run, --top-n, --tpe-trials, --skip-stability, --skip-dsr"
affects:
  - phase: 105-04
  - "future param sweep execution runs"
  - "trial_registry population"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PARAM_SPACE_REGISTRY pattern: module-level dict mapping indicator -> fn_path + param_space_def + constraints"
    - "importlib dynamic function resolution with graceful fallback on ImportError"
    - "_crypto_native flag to guard Phase 104 indicators requiring oi/funding_rate columns"
    - "Graceful fallback chain: dim_feature_registry -> trial_registry -> log + exit 0"
    - "NullPool engine per connection block (project convention for scripts)"

key-files:
  created:
    - "src/ta_lab2/scripts/analysis/run_param_sweep.py"
  modified: []

key-decisions:
  - "Parameter names match actual function signatures: rsi(window), stoch_kd(k, d), bollinger(window, n_sigma), elder_ray(period), force_index(smooth), keltner(ema_period, atr_period), ichimoku(tenkan, kijun, senkou_b)"
  - "Crypto-native indicators (vol_oi_regime, liquidation_pressure) have empty param_space_def; guarded by _crypto_native flag to skip in sweep loop"
  - "Both tasks implemented in single commit since they modify the same file and the full CLI was written atomically"
  - "train_end = max(ts) - tf_days_nominal days: prevents lookahead leakage at boundary consistent with _make_ic_objective boundary masking"
  - "fwd_ret = ret_arith.shift(-1): forward returns from returns_bars_multi_tf_u shifted by 1 bar"
  - "Asset universe fallback: ic_results LIMIT 20 -> price_bars_multi_tf_u LIMIT 20 -> error"

patterns-established:
  - "PARAM_SPACE_REGISTRY: central registry pattern for indicator metadata, extensible for Phase 106+"
  - "Dry-run table format: indicator / grid_size / sampler / param space display"
  - "Sweep result logging: IC, plateau_score, DSR all logged per (indicator, asset, tf)"

# Metrics
duration: 4min
completed: 2026-04-01
---

# Phase 105 Plan 03: Parameter Sweep CLI Summary

**CLI runner `run_param_sweep.py` with 22-indicator PARAM_SPACE_REGISTRY, dynamic function resolution, FDR survivor discovery, and full Optuna sweep orchestration via run_sweep + select_best_from_sweep**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-01T22:52:58Z
- **Completed:** 2026-04-01T22:56:18Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- PARAM_SPACE_REGISTRY with 22 indicators: 7 from indicators.py (rsi, macd, stochastic, bbands, atr, adx, mfi), 11 from indicators_extended.py (williams_pct_r, cci, elder_ray, force_index, vwap_ratio, cmf, chaikin_oscillator, hurst, vidya, frama, keltner_channel, ichimoku), 4 Phase 104 crypto-native (volume_oi_regime, oi_zscore, liquidation_pressure; vol_oi_regime with placeholder)
- Parameter names verified against actual function signatures (e.g., stoch_kd uses `k`/`d` not `k_period`/`d_period`, elder_ray uses `period` not `ema_period`, force_index uses `smooth` not `smooth_period`)
- Full CLI with `--dry-run` listing 22 indicators with grid sizes (Grid vs TPE sampler selection) and parameter spaces
- Graceful survivor fallback chain: dim_feature_registry promoted rows → trial_registry fallback → exit 0 with message

## Task Commits

Each task was committed atomically:

1. **Task 1: Parameter space registry mapping** - `81eae279` (feat) — full file created containing both Task 1 and Task 2 code (single file, both tasks committed together)
2. **Task 2: CLI main loop and argparse** — included in `81eae279` (same file, written atomically)

**Plan metadata:** (pending docs commit)

## Files Created/Modified
- `src/ta_lab2/scripts/analysis/run_param_sweep.py` - Full CLI runner: PARAM_SPACE_REGISTRY (22 indicators), _resolve_feature_fn, _load_survivors, _load_data_for_asset, _get_tf_days_nominal, _query_asset_ids, main() with argparse, _print_dry_run_table, _print_summary

## Decisions Made

- **stoch_kd param names are `k` and `d`** (not `k_period`/`d_period` as the plan suggested): verified against actual signature. This matters for param injection into the Optuna objective.
- **elder_ray param name is `period`** (not `ema_period`): function uses `period` for the EMA span.
- **force_index param name is `smooth`** (not `smooth_period`): function uses `smooth` for EMA period.
- **keltner param names are `ema_period` and `atr_period`**: matches function signature.
- **ichimoku param names are `tenkan`, `kijun`, `senkou_b`**: matches function signature.
- **Crypto-native indicators with empty param_space_def skip the sweep loop** via `_crypto_native` flag check, avoiding division-by-zero in grid size computation.
- **Both tasks committed in single commit**: Tasks 1 and 2 both modify the same file; the full script was written atomically to avoid a half-baked intermediate state.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected function parameter names from plan spec to actual signatures**
- **Found during:** Task 1 (reading actual source files before writing registry)
- **Issue:** Plan text said "k_period/d_period" for stochastic, "smooth_period" for force_index — actual signatures use `k`/`d` and `smooth` respectively
- **Fix:** Read all three indicator files before writing PARAM_SPACE_REGISTRY; used actual parameter names
- **Files modified:** src/ta_lab2/scripts/analysis/run_param_sweep.py
- **Verification:** `_resolve_feature_fn` test passes; dry-run shows correct param names
- **Committed in:** 81eae279

---

**Total deviations:** 1 auto-fixed (Rule 1 — parameter name mismatch between plan spec and actual code)
**Impact on plan:** Essential correctness fix; wrong param names would cause TypeError in Optuna objective.

## Issues Encountered
- Ruff format reformatted the file on first commit attempt; re-staged and re-committed successfully (standard pre-commit flow).

## Next Phase Readiness
- run_param_sweep.py is ready for Phase 105-04 (bulk execution / scheduling)
- `--dry-run` confirmed: 22 indicators, grid sizes from 1 (placeholder) to 5740 (MACD)
- MACD (5740), ichimoku (3780), keltner_channel (336), vidya (256), bbands (414) use TPESampler; all others use GridSampler
- To sweep a real indicator: `python -m ta_lab2.scripts.analysis.run_param_sweep --indicator rsi --asset-id 1 --tf 1D`
- Phase 103/104 FDR sweeps must run before `--all` mode (survivor lookup) is useful

---
*Phase: 105-parameter-optimization*
*Completed: 2026-04-01*
