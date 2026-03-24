---
phase: 87-live-pipeline-alert-wiring
plan: "01"
subsystem: database
tags: [alembic, postgresql, ic, alpha-decay, telegram, black-litterman, pipeline-monitoring]

# Dependency graph
requires:
  - phase: 86-portfolio-pipeline
    provides: stop_calibrations, BL weights, GARCH vol infrastructure
  - phase: 80-feature-selection
    provides: feature_selection.yaml active-tier features, IC-IR methodology
  - phase: 72-macro-observability
    provides: macro_alerts.py throttle+log pattern for Telegram alerts

provides:
  - Alembic migration n8o9p0q1r2s3 creating 4 Phase 87 tables
  - pipeline_run_log: dead-man switch audit for daily pipeline runs
  - signal_anomaly_log: signal validation gate audit log
  - pipeline_alert_log: unified throttle log for all Phase 87 alert types
  - dim_ic_weight_overrides: BL weight halving dimension table for IC-decayed features
  - ICStalenessMonitor: multi-window (30/63/126-bar) IC-IR decay detection with throttled alerts

affects:
  - 87-02: signal anomaly gate uses signal_anomaly_log and pipeline_alert_log
  - 87-03: dead-man switch uses pipeline_run_log
  - 87-04: full pipeline wiring uses all 4 tables + IC staleness check as a stage
  - 86-portfolio-pipeline: dim_ic_weight_overrides feeds BL weight halving

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Multi-window IC-IR decay: compare short(30) AND medium(63) windows; NaN guard prevents false flags"
    - "Idempotent weight override: ON CONFLICT ON CONSTRAINT uq_ic_weight_overrides DO NOTHING"
    - "Throttled alert pattern: check pipeline_alert_log within cooldown window; log throttled=True/False always"
    - "UNIQUE INDEX on (feature, COALESCE(asset_id, -1)) for nullable FK deduplication"

key-files:
  created:
    - alembic/versions/n8o9p0q1r2s3_phase87_pipeline_wiring.py
    - src/ta_lab2/scripts/analysis/run_ic_staleness_check.py
  modified: []

key-decisions:
  - "down_revision=m7n8o9p0q1r2 (Phase 86 head); verified with alembic history before writing"
  - "dim_ic_weight_overrides UNIQUE INDEX on (feature, COALESCE(asset_id, -1)): handles nullable asset_id uniqueness correctly in PostgreSQL"
  - "ON CONFLICT ON CONSTRAINT uq_ic_weight_overrides DO NOTHING: prevents compound weight halving on repeated daily runs"
  - "NaN guard in _is_decaying(): insufficient data (NaN IC-IR) must NOT trigger decay flag; skips gracefully"
  - "AMA features skip gracefully: AMA columns (TEMA_*, DEMA_*, etc.) live in ama_multi_tf not features table; information_schema check prevents SQL errors"
  - "_FEATURE_SELECTION_YAML = Path(__file__).parents[4] / 'configs': 4 levels up from scripts/analysis/ reaches project root"
  - "ICStalenessMonitor returns 0 (no decay), 1 (error), 2 (decay detected): enables pipeline stage runner to gate on return code"
  - "COOLDOWN_HOURS_IC_DECAY=24: daily pipeline cadence; one alert per feature per day maximum"

patterns-established:
  - "pipeline_alert_log as unified throttle log: all Phase 87 alert types (ic_decay, signal_anomaly, dead_man) use same table with alert_type/alert_key discriminator"
  - "NullPool for CLI scripts: no persistent connection pool; each run creates fresh connections"
  - "venue_id=1 filter in features queries: prevents duplicate ts rows from multi-venue data"

# Metrics
duration: 6min
completed: 2026-03-24
---

# Phase 87 Plan 01: Foundation Tables + IC Staleness Monitor Summary

**Alembic migration n8o9p0q1r2s3 creates 4 Phase 87 tables; ICStalenessMonitor detects alpha decay via 30/63/126-bar IC-IR comparison with idempotent BL weight halving and 24h-throttled Telegram alerts**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-24T13:11:20Z
- **Completed:** 2026-03-24T13:17:21Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created Alembic migration (revision n8o9p0q1r2s3, down_revision m7n8o9p0q1r2) for 4 tables: pipeline_run_log, signal_anomaly_log, pipeline_alert_log, dim_ic_weight_overrides
- Implemented ICStalenessMonitor with multi-window IC-IR at 3 windows (short=30, medium=63, long=126 bars) for active-tier features from feature_selection.yaml
- Decay detection compound condition (short AND medium < 0.7) with NaN guard prevents false positives on insufficient data
- Idempotent dim_ic_weight_overrides inserts via ON CONFLICT ON CONSTRAINT uq_ic_weight_overrides DO NOTHING -- no compound halving
- Throttled Telegram alerts with 24h cooldown queried from pipeline_alert_log; all alerts logged regardless of throttle state

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration for Phase 87 tables** - `ef6ad2fe` (feat)
2. **Task 2: IC Staleness Monitor script** - `0393d9c0` (feat)

**Plan metadata:** `(pending)` (docs: complete plan)

## Files Created/Modified

- `alembic/versions/n8o9p0q1r2s3_phase87_pipeline_wiring.py` -- Migration creating 4 tables with appropriate constraints and indexes
- `src/ta_lab2/scripts/analysis/run_ic_staleness_check.py` -- ICStalenessMonitor class + CLI with 0/1/2 return codes

## Decisions Made

- `down_revision=m7n8o9p0q1r2`: verified via `alembic history` before writing migration; confirmed current head
- `UNIQUE INDEX on (feature, COALESCE(asset_id, -1))`: standard PostgreSQL pattern for unique index on nullable column -- NULL = global override applying to all assets
- `ON CONFLICT ON CONSTRAINT uq_ic_weight_overrides DO NOTHING`: idempotent pattern prevents compound weight halving when the same decay is detected on consecutive daily runs
- NaN guard in `_is_decaying()`: `math.isnan(short_ir) or math.isnan(medium_ir)` returns False -- insufficient data must NOT be misclassified as decay
- AMA features (`TEMA_*`, `DEMA_*`, `KAMA_*`, `HMA_*`) live in `ama_multi_tf` not `features` table -- information_schema check gracefully skips absent columns with DEBUG log
- `Path(__file__).parents[4]`: 4 levels up from `src/ta_lab2/scripts/analysis/` reaches project root `ta_lab2/`
- `COOLDOWN_HOURS_IC_DECAY=24`: matches daily pipeline cadence; prevents alert spam while ensuring daily awareness of persistent decay
- `ICStalenessMonitor.run()` returns 0/1/2: enables downstream pipeline stage runner to branch on decay presence (return 2)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect YAML path depth (parents[5] -> parents[4])**

- **Found during:** Task 2 verification run
- **Issue:** `Path(__file__).parents[5]` resolved to `C:\Users\asafi\Downloads\configs\` (one level above the project) -- YAML not found, script returned exit code 1
- **Fix:** Changed to `parents[4]` which correctly resolves to project root `ta_lab2/configs/feature_selection.yaml`
- **Files modified:** `src/ta_lab2/scripts/analysis/run_ic_staleness_check.py`
- **Verification:** Dry-run completed successfully, loaded 10 active features
- **Committed in:** `0393d9c0` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** Single path calculation error; fixed inline before commit. No scope creep.

## Issues Encountered

- ruff-format reformatted `run_ic_staleness_check.py` (multi-line string expressions, function call wrapping) -- standard pattern; re-staged and committed clean after format pass

## User Setup Required

None - no external service configuration required for the tables or CLI script. Telegram alerts use existing `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` env vars and gracefully degrade if not configured.

## Next Phase Readiness

- All 4 Phase 87 tables in DB (verified queryable with COUNT(*) = 0)
- pipeline_alert_log ready for Plans 02-04 throttle queries
- dim_ic_weight_overrides ready for BL weight halving consumer in Phase 86 portfolio pipeline
- ICStalenessMonitor CLI ready for integration as `ic_staleness` stage in Plan 04 pipeline orchestration
- AMA feature coverage gap: top-10 active features are mostly AMA columns absent from `features` table; full coverage requires AMA-aware data loader (deferred to Plan 04 or future phase)

---
*Phase: 87-live-pipeline-alert-wiring*
*Completed: 2026-03-24*
