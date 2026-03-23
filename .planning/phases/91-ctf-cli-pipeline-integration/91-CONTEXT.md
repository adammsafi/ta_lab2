# Phase 91: CTF CLI & Pipeline Integration - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the Phase 90 CTF computation engine into the daily refresh pipeline with a standalone CLI script (`refresh_ctf.py`), Phase 1b integration into `run_all_feature_refreshes.py`, and incremental refresh via a state table. The core computation module (cross_timeframe.py) is complete -- this phase is about CLI invocation, parallelization, pipeline ordering, and incremental logic.

</domain>

<decisions>
## Implementation Decisions

### CLI flag design
- `--all` is default behavior (compute all 109 assets). `--ids 1 2 3` narrows scope.
- `--base-tf` defaults to ALL configured TFs from ctf_config.yaml. User wants MORE than the current 4 base TFs -- expand YAML config to include additional base TFs.
- `--indicators rsi_14 macd_12_26` filter supported. Default = all active from dim_ctf_indicators.
- `--full-refresh` recomputes everything from scratch, deleting existing ctf rows and resetting state table.
- `--workers N` controls parallelism level.

### Incremental refresh logic
- Dedicated state table via Alembic migration (not CREATE TABLE IF NOT EXISTS). Consistent with project conventions.
- State table granularity: Claude's discretion (per id/base_tf/ref_tf or per id/base_tf/ref_tf/indicator_id).
- `--full-refresh` ignores state table, recomputes all, and resets state for affected scopes.
- Incremental logic: compare state table watermarks against source table freshness. Skip scopes with no new data.

### Pipeline ordering & parallelism
- Phase 1b placement in run_all_feature_refreshes.py: Claude decides based on actual source table dependencies.
- CTF must be fully optimized with multiprocessing support. Allow parallel execution across asset batches, source tables, or TF pairs (Claude designs the strategy).
- `--workers N` flag for controlling parallelism. Default to a sensible auto-detected value.
- CTF failure handling in pipeline: Claude decides based on Phase 2 dependency analysis.

### Logging & progress
- Per-indicator detail logging: "rsi_14 1D->7D: 2,847 rows (3.2s)" for each indicator completion.
- tqdm-style progress bar for long runs with elapsed time and ETA.
- Per-asset error handling: Claude decides (log-and-continue vs abort).

### Claude's Discretion
- `--dry-run` flag inclusion (whether the complexity is worth it)
- State table granularity level
- Phase 1b ordering (after vol+ta only, or after all Phase 1)
- CTF failure: fatal vs non-fatal for pipeline continuation
- Final summary disk usage stats
- Error handling strategy (log-and-continue vs abort)
- Parallelization strategy (by asset batch, by source table, by TF pair, or hybrid)

</decisions>

<specifics>
## Specific Ideas

- User wants more than 4 base TFs in ctf_config.yaml -- expand the timeframe_pairs section during this phase.
- Multiprocessing must be fully optimized, not just bolted on. Consider NullPool pattern (already used in existing workers).
- tqdm is the progress bar library of choice (already a project dependency for other scripts).

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 91-ctf-cli-pipeline-integration*
*Context gathered: 2026-03-23*
