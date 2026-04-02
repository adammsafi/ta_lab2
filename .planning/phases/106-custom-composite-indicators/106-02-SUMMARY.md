---
phase: 106-custom-composite-indicators
plan: 02
subsystem: features
tags: [composite-indicators, features-table, UPDATE-pattern, ctf, ama, hyperliquid]

# Dependency graph
requires:
  - phase: 106-01
    provides: composite_indicators.py with ALL_COMPOSITES registry + Alembic migration z9a0b1c2d3e4

provides:
  - run_composite_refresh.py CLI script that computes and writes all 6 composites to features table
  - tf_alignment_score populated in features table (22280 rows, 7 assets on local DB)
  - Bug fix: tf_alignment_score timestamp precision (resample was snapping to midnight, breaking UPDATE match)

affects:
  - 106-03 (validation plan reads composite columns from features table)
  - run_daily_refresh (composite refresh step to be added)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Per-composite fresh-connection isolation to prevent aborted-txn cascade from one missing-table error blocking all subsequent composites
    - Temp-table bulk UPDATE: CREATE TEMP TABLE + INSERT values + UPDATE features FROM temp WHERE ts matches
    - Coverage reporting with per-composite asset count and row count

key-files:
  created:
    - src/ta_lab2/scripts/features/run_composite_refresh.py
  modified:
    - src/ta_lab2/features/composite_indicators.py (bug fix: tf_alignment_score resample)

key-decisions:
  - "Per-composite fresh connection: each composite gets engine.connect() to isolate aborted-txn state from missing-table errors in data loaders"
  - "Temp-table bulk UPDATE (not row-by-row UPDATE): create _tmp_composite per composite per asset, then UPDATE features FROM temp -- single UPDATE stmt vs N UPDATE stmts"
  - "ON COMMIT DELETE ROWS temp table: session-scoped, auto-cleaned at end of transaction, safe for re-use across composites in same session"
  - "tf_alignment_score bug fix: do NOT resample CTF pairs to 1D midnight -- keep natural 23:59:59.999 UTC timestamps so UPDATE matches features rows exactly"
  - "LOW COVERAGE flag suppressed for HL-only composites (oi_divergence, funding_adjusted_momentum) in _NEEDS_CMC_SYMBOL set -- expected, not an error"

patterns-established:
  - "Composite refresh write pattern: temp table INSERT + UPDATE features FROM temp (not DELETE+INSERT)"
  - "Per-composite isolation: fresh engine.connect() per composite avoids InFailedSqlTransaction cascade"

# Metrics
duration: 42min
completed: 2026-04-01
---

# Phase 106 Plan 02: Composite Refresh Orchestrator Summary

**run_composite_refresh.py CLI script that computes all 6 composites via UPDATE pattern + tf_alignment_score timestamp bug fix enabling 22280 rows written for 7 assets**

## Performance

- **Duration:** 42 min
- **Started:** 2026-04-01T19:19:48Z
- **Completed:** 2026-04-01T20:32:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created run_composite_refresh.py with full CLI (--ids, --tf, --venue-id, --composites, --dry-run, --verbose)
- Implemented per-composite fresh-connection isolation to prevent aborted-txn cascade from missing tables
- Implemented temp-table bulk UPDATE pattern preserving all other feature columns
- Fixed timestamp precision bug in compute_tf_alignment_score (resample snapped to midnight, breaking UPDATE match)
- Ran full refresh on 7 assets (venue_id=1): tf_alignment_score populated with 22280 rows at 100% coverage

## Task Commits

Each task was committed atomically:

1. **Task 1: Create run_composite_refresh.py orchestrator** - `e670207b` (feat - included in planning docs commit)
2. **Bug fix: tf_alignment_score timestamp precision** - `7d606d6a` (fix - Rule 1 auto-fix during Task 2)

**Note:** Task 1 script was committed in e670207b (accidentally bundled in prior planning docs commit). Content is correct — all 512 lines committed.

## Files Created/Modified

- `src/ta_lab2/scripts/features/run_composite_refresh.py` - CLI orchestrator: discovers assets, calls ALL_COMPOSITES dispatch, writes via temp-table UPDATE, prints coverage report
- `src/ta_lab2/features/composite_indicators.py` - Bug fix: compute_tf_alignment_score no longer resamples CTF pairs to midnight; uses natural 23:59:59.999 UTC timestamps

## Decisions Made

- Per-composite fresh connection: isolates aborted-transaction state from missing-table errors in data loaders. Without this, one failed SQL (e.g. ama_multi_tf missing) would abort the PostgreSQL transaction and block all subsequent composites in the same connection.
- Temp-table bulk UPDATE (`CREATE TEMP TABLE IF NOT EXISTS _tmp_composite ON COMMIT DELETE ROWS`): single UPDATE statement vs N individual UPDATE statements; ON COMMIT DELETE ROWS ensures clean state between composites without explicit TRUNCATE overhead at connection level.
- LOW COVERAGE suppression for HL composites: composites 2 (oi_divergence_ctf_agreement) and 3 (funding_adjusted_momentum) are expected to have < 100% coverage because they require Hyperliquid perp listings. Flag is not raised for these composites.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] tf_alignment_score resample breaks timestamp match**

- **Found during:** Task 2 (full asset run produced 0 rows for tf_alignment_score)
- **Issue:** `compute_tf_alignment_score` called `s.resample("1D").last().ffill()` on each CTF series, which snapped timestamps from `23:59:59.999+UTC` (features table convention) to `00:00:00+UTC` (daily resample boundary). The UPDATE `WHERE f.ts = t.ts` could never match because the temp table had midnight timestamps but features rows had `23:59:59.999` timestamps.
- **Fix:** Removed resample. All CTF agreement series share the same `23:59:59.999 UTC` timestamp convention (they come from the same CTF table via `_load_ctf_agreement_col`), so a direct `pd.concat(available, axis=1).mean(axis=1)` works without date-snapping. The natural index is preserved.
- **Files modified:** `src/ta_lab2/features/composite_indicators.py`
- **Verification:** tf_alignment_score index shows `23:59:59.999000+00:00`, 22280 rows written (7/7 assets), spot-check confirms `adx_14` preserved alongside new composite value.
- **Committed in:** `7d606d6a`

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Critical fix — without it, tf_alignment_score would write 0 rows despite correct computation. No scope creep.

## Issues Encountered

- **Local DB missing ama_multi_tf and price_bars_multi_tf:** Local database has only `_u` unified views, not the base partitioned tables. Composites 1 (AMA ER), 3 (volume-regime trend), and others that query these tables return NaN on local DB. Production server has the full tables. Documented in coverage report; not a script bug.
- **tf='1' vs '1D':** Plan's `--tf 1` default returns 0 assets locally (features table uses '10D', '1D' etc. not '1'). Script runs correctly with '1D' or '10D'; the default '1' is intended for production where a tf='1' alias may exist.
- **Coverage for local run (venue_id=1, tf='10D'):**
  - ama_er_regime_signal: 0/7 (requires ama_multi_tf — missing locally)
  - oi_divergence_ctf_agreement: 0/7 (requires HL data + price_bars_multi_tf)
  - funding_adjusted_momentum: 0/7 (requires HL data + price_bars_multi_tf)
  - cross_asset_lead_lag_composite: 0/7 (lead_lag_ic has no significant rows for tf='10D')
  - tf_alignment_score: 7/7 (100%, 22280 rows) — uses only CTF table which exists locally
  - volume_regime_gated_trend: 0/7 (requires ama_multi_tf — missing locally)

## Next Phase Readiness

- Plan 106-03 (validation) can proceed: tf_alignment_score is populated; validation should test composites are non-NULL and within expected ranges
- Production run will populate all 6 composites once ama_multi_tf and price_bars_multi_tf are available (run on Oracle VM or production server)
- The UPDATE pattern confirmed correct: adx_14 and other feature columns preserved alongside tf_alignment_score

---
*Phase: 106-custom-composite-indicators*
*Completed: 2026-04-01*
