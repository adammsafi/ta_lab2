---
phase: 35-ama-engine
plan: "02"
subsystem: features
tags: [kama, dema, tema, hma, ama, numpy, pandas, hashlib, md5, ewm, wma, warmup]

# Dependency graph
requires:
  - phase: 35-01
    provides: AMA DDL (cmc_ama_multi_tf tables, dim_ama_params) — params_hash PK design established

provides:
  - compute_params_hash() — deterministic MD5 hash of canonical params dict (sort_keys=True)
  - AMAParamSet frozen dataclass — indicator + params + hash + label + warmup descriptor
  - get_warmup() — warmup threshold calculator for all 4 indicator types
  - 18 module-level AMAParamSet constants — 3 KAMA + 5 DEMA + 5 TEMA + 5 HMA
  - ALL_AMA_PARAMS, ALL_KAMA_PARAMS, ALL_DEMA_PARAMS, ALL_TEMA_PARAMS, ALL_HMA_PARAMS collections
  - compute_kama() — numpy loop; returns (kama, er) arrays with NaN warmup guard
  - compute_dema() — ewm(alpha=2/(period+1), adjust=False); warmup=2p-1
  - compute_tema() — triple ewm composition; warmup=3p-1
  - compute_hma() — rolling WMA (NOT ewm); warmup from min_periods
  - compute_ama() — dispatcher returning (ama_values, er_or_none)
affects:
  - 35-03 (BaseAMAFeature write_to_db — imports AMAParamSet, compute_ama)
  - 35-04 (MultiTFAMAFeature — uses compute_kama, compute_dema etc. directly)
  - 35-05 (AMA refresher scripts — use ALL_AMA_PARAMS for worker task config)
  - 35-07 (IC evaluation — KAMA ER column queryable via params_hash)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "params_hash as frozen PK discriminator — MD5 of sort_keys=True JSON, never construct inline"
    - "AMAParamSet frozen dataclass with hash=False on mutable dict field"
    - "warmup guard via np.full(n, np.nan) init for KAMA; iloc[:warmup] = nan for DEMA/TEMA"
    - "WMA via rolling().apply(raw=True) — linear weights, NOT ewm(); critical for HMA correctness"
    - "alpha = 2/(period+1) with adjust=False — matches existing EMA infrastructure convention"
    - "compute_ama() dispatcher returns (Series, Series|None) — er is None for non-KAMA"

key-files:
  created:
    - src/ta_lab2/features/ama/__init__.py
    - src/ta_lab2/features/ama/ama_params.py
    - src/ta_lab2/features/ama/ama_computations.py
  modified: []

key-decisions:
  - "params_hash covers params dict only — indicator is separate PK column in DB table (so DEMA/TEMA/HMA share hash for same period, distinguished by indicator column)"
  - "18 total param sets: 3 KAMA (canonical/fast/slow) + 5 DEMA + 5 TEMA + 5 HMA (periods 9/10/21/50/200)"
  - "AMAParamSet.params field uses hash=False to allow frozen dataclass with mutable dict"
  - "HMA uses rolling WMA via rolling().apply(raw=True) NOT ewm() — mathematically distinct"

patterns-established:
  - "Pattern: All param dicts defined as module-level _INDICATOR_PARAMS_N constants — never inline at call sites"
  - "Pattern: compute_params_hash(params) for any dict — always sort_keys=True, separators=(',',':')"
  - "Pattern: get_warmup(indicator, params) as single source of truth for warmup thresholds"
  - "Pattern: compute_ama dispatcher as entry point — callers need not import individual functions"

# Metrics
duration: 3min
completed: "2026-02-23"
---

# Phase 35 Plan 02: AMA Computation Layer Summary

**Pure KAMA/DEMA/TEMA/HMA computation functions with MD5 params_hash parameter management — 18 frozen AMAParamSet constants and 4 indicator functions with correct warmup NaN guards**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-23T22:00:06Z
- **Completed:** 2026-02-23T22:03:35Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- `ama_params.py`: 18 AMAParamSet constants covering all 4 indicator types, with deterministic params_hash and correct warmup thresholds per indicator
- `ama_computations.py`: 4 pure computation functions (compute_kama, compute_dema, compute_tema, compute_hma) plus compute_ama dispatcher — all verified against plan formulas
- All warmup guards produce NaN for insufficient data rows; KAMA returns (kama, er) tuple as specified

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ama_params.py - Parameter management** - `ed33e817` (feat)
2. **Task 2: Create ama_computations.py - Pure indicator functions** - `d0a028c4` (feat)

**Plan metadata:** (created in this step — docs commit below)

## Files Created/Modified

- `src/ta_lab2/features/ama/__init__.py` - Package initializer with module docstring
- `src/ta_lab2/features/ama/ama_params.py` - AMAParamSet dataclass, compute_params_hash, get_warmup, 18 module-level constants, 5 collection lists
- `src/ta_lab2/features/ama/ama_computations.py` - compute_kama (numpy loop), compute_dema (ewm), compute_tema (ewm), compute_hma (WMA rolling), compute_ama dispatcher

## Decisions Made

- **params_hash covers params dict only**: The `indicator` field is a separate column in the DB PK. This means DEMA(21), TEMA(21), and HMA(21) share the same params_hash `d47fe5cc...` — they are distinguished by the `indicator` column. This is correct and intentional per the plan design.
- **AMAParamSet.params with hash=False**: Frozen dataclass cannot contain mutable dict fields unless `hash=False, compare=False` is applied. The field is still immutable in practice — it is never reassigned.
- **HMA WMA via rolling().apply(raw=True)**: Used `raw=True` for performance. The lambda receives a numpy array, avoiding Series overhead per window. The alternative (numpy loop in `_wma_numpy`) is held in reserve if rolling().apply() proves too slow on 109 TFs.
- **Warmup guard strategy**: KAMA uses `np.full(n, np.nan)` init (NaN by default, only valid rows get values). DEMA/TEMA use explicit `iloc[:warmup] = np.nan` after ewm computation (ewm has infinite impulse response — technically produces values from row 0, so guard is applied explicitly).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook `mixed-line-ending` triggered twice (Windows CRLF). Fixed automatically by the hook on second attempt in each case — staged the hook-reformatted files and committed successfully.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `ama_params.py` and `ama_computations.py` are fully ready for consumption by Plan 35-03 (BaseAMAFeature)
- compute_ama() dispatcher is the recommended entry point for BaseAMAFeature.compute()
- ALL_AMA_PARAMS provides the complete iteration list for refresher worker task configuration
- No blockers — pure computation layer has zero DB dependencies

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
