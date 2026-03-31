# Phase 107: Pipeline Operations Dashboard

**Goal:** Add a Streamlit operations page for triggering, monitoring, and managing the daily refresh pipeline with real-time progress tracking and run history.

## Motivation

The daily refresh pipeline (`run_daily_refresh.py --all`) runs 26 stages over ~4-6 hours. Currently there is no UI to trigger, monitor, or kill a run. Monitoring requires ad-hoc DB queries against `pipeline_run_log` and `ingested_at` columns. This phase adds a dedicated Streamlit page for pipeline operations.

## Requirements

### Pipeline Script Changes (Backend)

1. **`pipeline_stage_log` table**: New table with columns:
   - `run_id` (FK to pipeline_run_log)
   - `stage_name`, `started_at`, `completed_at`, `status` (pending/running/done/failed)
   - `rows_affected`, `duration_sec`, `error_msg`
   - INSERT at stage start, UPDATE at stage end

2. **Per-stage logging in `run_daily_refresh.py`**:
   - Before each stage: INSERT into pipeline_stage_log (status='running')
   - After each stage: UPDATE with completed_at, status, rows_affected
   - This replaces the in-memory `results` list with DB-persisted state

3. **Kill switch**:
   - Check for `.pipeline_kill` file between stages
   - If found: log "killed by operator", set run status='killed', delete kill file, exit
   - Dashboard writes this file on Kill button click

### Streamlit Dashboard Page

4. **Active Run Monitor** (auto-refresh 90s):
   - Current run_id, started_at, elapsed time
   - Stage list with status indicators (pending/running/done/failed)
   - Per-stage progress bar (estimated % based on historical avg duration)
   - Overall progress bar (completed stages / total stages)
   - Kill button (writes `.pipeline_kill` file)

5. **Run History** (last 10 runs):
   - Start time, end time, total duration, status
   - Per-stage timing breakdown (expandable)
   - Sparkline or bar chart of stage durations

6. **Operations Panel** (trigger):
   - "Run Full Refresh" button (spawns detached subprocess)
   - "Run From Stage" dropdown + Go button
   - Quick actions: "Sync VMs Only", "Bars + EMAs Only"
   - Shows command that would be run before confirming

## Dependencies

- `pipeline_run_log` table (exists, Phase 87)
- Streamlit dashboard infrastructure (exists, Phases 83-85)
- `run_daily_refresh.py` stages (all working as of this session)

## Estimated Effort

- Pipeline script changes: ~100 LOC (stage logging + kill check)
- Alembic migration for pipeline_stage_log: ~30 LOC
- Streamlit page: ~300-400 LOC
- Total: ~2-3 plans

## Success Criteria

- [ ] `pipeline_stage_log` populated during every `--all` run
- [ ] Streamlit page shows real-time stage progress for active run
- [ ] Kill button stops pipeline between stages within 30s
- [ ] Run history shows last 10 runs with per-stage timing
- [ ] "Run Full Refresh" button successfully triggers pipeline
