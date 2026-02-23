---
phase: 35-ama-engine
plan: 07
subsystem: database
tags: [ama, sync, z-scores, unified-tables, returns, kama, dema, tema, hma, sqlalchemy]

# Dependency graph
requires:
  - phase: 35-01
    provides: DDL for cmc_ama_multi_tf_u and cmc_returns_ama_multi_tf_u with alignment_source in PK
  - phase: 35-05
    provides: AMAReturnsFeature and refresh_cmc_returns_ama.py populating 5 AMA returns tables
provides:
  - sync_cmc_ama_multi_tf_u.py: syncs 5 AMA value sources -> cmc_ama_multi_tf_u
  - sync_cmc_returns_ama_multi_tf_u.py: syncs 5 AMA returns sources -> cmc_returns_ama_multi_tf_u
  - refresh_returns_zscore.py extended with _AMA_TABLES (6 configs) and --tables amas support
affects:
  - Phase 36+ (signal generators can query cmc_ama_multi_tf_u via LEFT JOINs)
  - Phase 37 (IC evaluation reads from cmc_returns_ama_multi_tf_u for feature scoring)
  - Phase 38 (ExperimentRunner uses z-scored AMA returns for feature evaluation)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "sync_sources_to_unified() unmodified reuse: dynamic column discovery works for AMA tables without code changes"
    - "AMA PK includes indicator+params_hash: (id, ts, tf, indicator, params_hash, alignment_source) replaces (id, ts, tf, period, alignment_source)"
    - "Z-score key_cols include indicator+params_hash: prevents cross-param-set aggregation in rolling window calculation"
    - "4 z-score pairs for AMA (2 canonical + 2 roll) vs 8 for EMA: no _ema_bar column family in AMA returns"

key-files:
  created:
    - src/ta_lab2/scripts/amas/sync_cmc_ama_multi_tf_u.py
    - src/ta_lab2/scripts/amas/sync_cmc_returns_ama_multi_tf_u.py
  modified:
    - src/ta_lab2/scripts/returns/refresh_returns_zscore.py

key-decisions:
  - "sync_sources_to_unified() used without modification — dynamic column discovery via information_schema handles indicator+params_hash columns automatically"
  - "AMA_SOURCE_PREFIX='cmc_ama_' strips correctly to multi_tf, multi_tf_cal_us, etc. — same derivation logic as EMA and bar sync scripts"
  - "key_cols must include indicator+params_hash — z-scores computed per (id, tf, indicator, params_hash) group; omitting them would produce garbage by mixing KAMA(14) with HMA(200) windows"
  - "_u table for returns adds alignment_source to both pk_cols and key_cols — one z-score series per (id, tf, indicator, params_hash, alignment_source) combination"
  - "AMA temp table DDL reuses existing else-branch (text type) for indicator, params_hash, alignment_source columns — no changes needed to _process_key"

patterns-established:
  - "AMA sync follows identical pattern to bar/EMA sync scripts: resolve_db_url + create_engine + add_sync_cli_args + sync_sources_to_unified"
  - "--tables amas as standalone mode: enables targeted z-score refresh of AMA tables without reprocessing bars or EMAs"

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 35 Plan 07: AMA Sync Scripts and Z-Score Extension Summary

**_u sync scripts for AMA value and returns tables using sync_sources_to_unified() unmodified, plus refresh_returns_zscore.py extended with 6 AMA TableConfig objects (key_cols include indicator+params_hash for per-param-set grouping)**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-23T22:21:25Z
- **Completed:** 2026-02-23T22:23:36Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- sync_cmc_ama_multi_tf_u.py: resolves db_url via refresh_utils, calls sync_sources_to_unified() with 5 AMA value sources and AMA_PK_COLS including indicator+params_hash+alignment_source
- sync_cmc_returns_ama_multi_tf_u.py: same pattern for 5 AMA returns sources -> cmc_returns_ama_multi_tf_u
- refresh_returns_zscore.py: _AMA_TABLES adds 6 TableConfig objects; key_cols contain indicator+params_hash for correct per-param-set z-score grouping; "amas" added to --tables choices; "all" now processes 17 tables total (5 bars + 6 EMAs + 6 AMAs)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create _u table sync scripts** - `76e89a92` (feat)
2. **Task 2: Extend refresh_returns_zscore.py with AMA tables** - `a9c0e71a` (feat)

**Plan metadata:** (created below as docs commit)

## Files Created/Modified

- `src/ta_lab2/scripts/amas/sync_cmc_ama_multi_tf_u.py` - AMA value _u sync: resolve_db_url, create_engine, sync_sources_to_unified with AMA_SOURCES and AMA_PK_COLS
- `src/ta_lab2/scripts/amas/sync_cmc_returns_ama_multi_tf_u.py` - AMA returns _u sync: same pattern with AMA_RETURNS_SOURCES and AMA_RETURNS_PK_COLS
- `src/ta_lab2/scripts/returns/refresh_returns_zscore.py` - Extended with _AMA_CANONICAL_BASE, _AMA_ROLL_BASE, _AMA_TABLES (6 configs), "amas" CLI choice, "all" now includes AMAs

## Decisions Made

- `sync_sources_to_unified()` used without modification. The function discovers columns dynamically via `information_schema` so it handles `indicator`, `params_hash`, and `alignment_source` automatically without any custom logic.
- `key_cols` must include `indicator` and `params_hash` in _AMA_TABLES. Without these, rolling z-scores would aggregate across KAMA, DEMA, TEMA, and HMA rows for the same (id, tf) group — producing garbage values. Each AMA type with each param set gets its own z-score series.
- The existing temp table DDL in `_process_key` handles `indicator` and `params_hash` via the `else` branch which maps unknown columns to `text` type — correct for both columns.
- The `_u` table config for returns adds `alignment_source` to both `pk_cols` and `key_cols`, giving each (id, tf, indicator, params_hash, alignment_source) combination an independent z-score series.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Mixed line endings on newly created files (Windows CRLF)**

- **Found during:** Task 1 commit attempt
- **Issue:** Pre-commit mixed-line-ending hook failed on both new sync scripts — Windows writes CRLF but project uses LF
- **Fix:** Hook auto-fixed the files; re-staged and committed on second attempt
- **Files modified:** sync_cmc_ama_multi_tf_u.py, sync_cmc_returns_ama_multi_tf_u.py
- **Verification:** Pre-commit passed on second commit attempt
- **Committed in:** 76e89a92 (Task 1 commit, after re-stage)

---

**Total deviations:** 1 auto-fixed (1 formatting/line-ending — same Windows CRLF pattern as Plan 35-05)
**Impact on plan:** No logic change. Line-ending normalization only.

## Issues Encountered

None — both sync scripts used the canonical pattern exactly. Z-score extension was a straightforward addition following the _EMA_TABLES pattern with fewer column pairs.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Pipeline sequence for AMA data: refresh_cmc_ama_multi_tf.py (Plan 04) → sync_cmc_ama_multi_tf_u.py (this plan) → refresh_cmc_returns_ama.py (Plan 05) → sync_cmc_returns_ama_multi_tf_u.py (this plan) → refresh_returns_zscore.py --tables amas (this plan)
- All 6 AMA returns tables will have z-score columns after running `refresh_returns_zscore.py --tables amas`
- Signal generators can query `cmc_ama_multi_tf_u` via LEFT JOINs (same pattern as `cmc_ema_multi_tf_u`)
- Phase 37 IC evaluation can read from `cmc_returns_ama_multi_tf_u` for feature scoring

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
