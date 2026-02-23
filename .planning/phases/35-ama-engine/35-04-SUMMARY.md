---
phase: 35-ama-engine
plan: 04
subsystem: database
tags: [ama, kama, dema, tema, hma, sqlalchemy, pandas, incremental-refresh, template-method, multiprocessing, nullpool]

# Dependency graph
requires:
  - phase: 35-03
    provides: BaseAMAFeature abstract class, AMAStateManager, scripts/amas/ package
  - phase: 35-02
    provides: AMAParamSet, ALL_AMA_PARAMS, compute_params_hash, compute_ama() dispatcher
  - phase: 35-01
    provides: DDL for cmc_ama_multi_tf, cmc_ama_multi_tf_state, dim_ama_params
provides:
  - MultiTFAMAFeature concrete subclass loading bars from cmc_price_bars_multi_tf
  - populate_dim_ama_params() idempotent seeding function for dim_ama_params
  - BaseAMARefresher abstract orchestrator with CLI, multiprocessing, state management
  - AMAWorkerTask dataclass for passing param_sets + config to Pool workers
  - _ama_worker module-level function (NullPool, state watermarks, incremental refresh)
  - MultiTFAMARefresher concrete entry point script
affects:
  - 35-05 (AMA returns refresher will import MultiTFAMAFeature pattern)
  - Future calendar-aligned AMA refreshers (cal_us, cal_iso variants)
  - run_daily_refresh.py --all (will add --amas step)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AMAWorkerTask vs WorkerTask: AMA workers carry param_sets (list[AMAParamSet]) not periods (list[int]) — reflects different PK structure"
    - "NullPool in _ama_worker: create_engine(db_url, poolclass=NullPool) prevents connection exhaustion in multiprocessing.Pool"
    - "Minimum watermark strategy: start_ts = min(last_canonical_ts across all param_sets for a TF) — one stale param_set triggers full history for all"
    - "CAST(:params_json AS jsonb) pattern: avoids SQLAlchemy parameter conflict with Postgres ::jsonb syntax in text() queries"
    - "populate_dim_ama_params wraps in try/except: table may not exist on first-ever deploy; warning + continue is safe"
    - "BaseAMARefresher.run() mutually-exclusive --tf / --all-tfs args prevent invalid combinations at argparse level"

key-files:
  created:
    - src/ta_lab2/features/ama/ama_multi_timeframe.py
    - src/ta_lab2/scripts/amas/base_ama_refresher.py
    - src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf.py
  modified: []

key-decisions:
  - "populate_dim_ama_params uses CAST(:params_json AS jsonb) not :params_json::jsonb — SQLAlchemy text() bind params conflict with Postgres cast syntax"
  - "Minimum watermark strategy for incremental refresh: if ANY param_set for (asset_id, tf) has no state, start_ts=None (full history) for all param_sets in that batch"
  - "Sequential execution when num_processes==1 or single task: avoids Pool overhead for --ids 1 --tf 1D debugging workflow"
  - "BaseAMARefresher is NOT a subclass of BaseEMARefresher: AMA needs AMAWorkerTask not WorkerTask, AMAStateManager not EMAStateManager, param_sets not periods"

patterns-established:
  - "AMA refresher subclass pattern: override get_default_output_table/get_default_state_table/get_description + optionally get_bars_table/get_bars_schema"
  - "Workers import MultiTFAMAFeature inside the function body (not module-level): avoids circular import issues in multiprocessing fork context"

# Metrics
duration: 4min
completed: 2026-02-23
---

# Phase 35 Plan 04: AMA Multi-TF Refresher Summary

**MultiTFAMAFeature loading bars from cmc_price_bars_multi_tf, BaseAMARefresher with NullPool multiprocessing, and refresh_cmc_ama_multi_tf.py entry point enabling `python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf --ids 1 --tf 1D`**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-23T22:13:11Z
- **Completed:** 2026-02-23T22:17:01Z
- **Tasks:** 2
- **Files created:** 3

## Accomplishments

- MultiTFAMAFeature: concrete BaseAMAFeature subclass that loads bars from cmc_price_bars_multi_tf, resolves TFs from dim_timeframe using `tf_days_nominal` (not `tf_days`), and provides source table metadata
- populate_dim_ama_params(): idempotent seeder for dim_ama_params using CAST(:params_json AS jsonb); graceful warning+continue if table absent on first deploy
- BaseAMARefresher: abstract orchestrator with full CLI (--ids, --tf, --all-tfs, --indicators, --full-rebuild, --dry-run, --num-processes), multiprocessing via Pool.map(_ama_worker), incremental state watermarks via AMAStateManager
- _ama_worker: module-level NullPool worker that determines minimum watermark across param_sets per TF, calls compute_for_asset_tf+write_to_db+save_state
- MultiTFAMARefresher + refresh_cmc_ama_multi_tf.py: runnable script with --help, --dry-run verified working

## Task Commits

Each task was committed atomically:

1. **Task 1: MultiTFAMAFeature concrete class** - `40563bd4` (feat)
2. **Task 2: BaseAMARefresher + refresh_cmc_ama_multi_tf.py** - `0d559eac` (feat)

**Plan metadata:** (created below as docs commit)

## Files Created/Modified

- `src/ta_lab2/features/ama/ama_multi_timeframe.py` - MultiTFAMAFeature subclass: _load_bars from cmc_price_bars_multi_tf, _get_timeframes from dim_timeframe (tf_days_nominal), populate_dim_ama_params seeder
- `src/ta_lab2/scripts/amas/base_ama_refresher.py` - BaseAMARefresher orchestrator: AMAWorkerTask dataclass, _ama_worker NullPool function, CLI with mutually-exclusive --tf/--all-tfs, abstract methods for table names
- `src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf.py` - Entry point: MultiTFAMARefresher subclass wiring cmc_price_bars_multi_tf → cmc_ama_multi_tf

## Decisions Made

- `CAST(:params_json AS jsonb)` instead of `:params_json::jsonb` in `populate_dim_ama_params` — SQLAlchemy `text()` parameter binding uses `:name` syntax, and `::jsonb` Postgres cast suffix trips psycopg2's parser producing `SyntaxError: syntax error at or near ":"`. `CAST(... AS jsonb)` is standard SQL and works across all drivers.
- Minimum watermark strategy for start_ts: when computing start_ts for a (asset_id, tf) batch, take the minimum last_canonical_ts across all param_sets. If any param_set has no state (new indicator added), start_ts=None triggers full history for all param_sets in that TF batch. Ensures consistency: all param_sets in a batch cover the same bar range.
- Sequential execution path when num_processes==1 or len(tasks)==1: avoids multiprocessing.Pool overhead for the common `--ids 1 --tf 1D` debugging workflow.
- BaseAMARefresher does NOT inherit from BaseEMARefresher despite structural similarity. AMA requires AMAWorkerTask (not WorkerTask), AMAStateManager (not EMAStateManager), and param_sets (not periods). Inheriting would require overriding virtually every method.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed JSONB cast syntax error in populate_dim_ama_params**

- **Found during:** Task 2 verification (--dry-run test)
- **Issue:** `:params_json::jsonb` caused `SyntaxError: syntax error at or near ":"` with psycopg2. SQLAlchemy's text() binds parameters as `%(name)s` format and the `::jsonb` Postgres cast suffix conflicts with the colon-based bind syntax.
- **Fix:** Changed to `CAST(:params_json AS jsonb)` which is standard SQL and driver-agnostic.
- **Files modified:** `src/ta_lab2/features/ama/ama_multi_timeframe.py`
- **Verification:** `--dry-run` runs without SyntaxError; warning becomes expected `UndefinedTable` (dim_ama_params not yet deployed to test DB)
- **Committed in:** `0d559eac` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor SQL syntax fix. No logic or scope change.

## Issues Encountered

None — both tasks implemented cleanly after the JSONB cast fix.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf --ids 1 --tf 1D` is ready to run once DDL from Plan 35-01 is applied to the database
- Calendar-aligned AMA refreshers follow the same subclass pattern: extend BaseAMARefresher, override table names and get_bars_table()
- Plan 35-05 (AMA returns) can now import MultiTFAMAFeature as a reference pattern

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
