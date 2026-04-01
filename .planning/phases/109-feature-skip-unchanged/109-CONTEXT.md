# Phase 109: Feature Skip-Unchanged Optimization

**Goal:** Add watermark-based skip logic to the feature refresh pipeline so assets with no new bar data since last computation are skipped entirely. Target: 100 min → 10-15 min for typical daily refresh.

## Problem

The feature refresh processes all 492 assets regardless of whether they have new data. For a daily refresh with 4 new HL rows, 488 of 492 assets have zero new bars — but all 492 go through vol, ta, cycle_stats, rolling_extremes, microstructure, unified features, CTF, and CS norms computation.

## Approach

1. **New state table** `feature_refresh_state` with PK `(id, tf, alignment_source)`:
   - `last_bar_ts` — max timestamp of source bars when features were last computed
   - `last_refresh_ts` — when the feature refresh ran
   - `rows_written` — how many feature rows were written

2. **Pre-refresh check**: Before processing, query source bar max timestamps per ID. Compare against state. Build two lists:
   - `changed_ids` — source has new bars since last refresh (process these)
   - `unchanged_ids` — no new data (skip entirely)

3. **Per-sub-phase scoping**: Each sub-phase (vol, ta, etc.) only processes `changed_ids`. The scoped DELETE + INSERT pattern already works per-ID batch — just pass the filtered ID list.

4. **State update after refresh**: After all sub-phases complete, update state with new max bar timestamps.

## Dependencies

- None (feature scripts are self-contained)
- Phase 108 (batch performance) should complete first to establish the pattern

## Success Criteria

- [ ] `feature_refresh_state` table created via alembic migration
- [ ] Daily refresh with 4 new rows processes only ~4-10 assets (not 492)
- [ ] Feature data identical for unchanged assets (no re-computation)
- [ ] `--full-rebuild` bypasses skip logic
- [ ] Log shows "Skipping N unchanged assets" message
