---
phase: 51-perps-readiness
plan: 02
subsystem: data-ingestion
tags: [perps, perpetuals, funding-rates, binance, hyperliquid, bybit, dydx, aevo, aster, requests, pandas, sqlalchemy, watermark, pagination]

requires:
  - phase: 51-perps-readiness
    plan: 01
    provides: cmc_funding_rates table with (venue,symbol,ts,tf) PK ready for ingestion

provides:
  - funding_fetchers.py: 7 per-venue fetch functions (6 active + Lighter stub) returning FundingRateRow
  - refresh_funding_rates.py: CLI refresh script with watermark-based incremental ingest
  - FundingRateRow dataclass: normalized funding rate record type
  - upsert_funding_rates: temp table + ON CONFLICT DO NOTHING upsert for cmc_funding_rates
  - get_watermark: SELECT MAX(ts) per venue/symbol/tf for incremental refresh
  - compute_daily_rollup: pandas resample 1D sum -> tf='1d' rollup
  - get_funding_rate_with_fallback: exact match then cross-venue avg +/-30min window

affects:
  - 51-04: FundingAdjuster for backtester will read from cmc_funding_rates populated here
  - future carry trade analysis: cmc_funding_rates is the data foundation

tech-stack:
  added: []
  patterns:
    - "Per-venue fetcher pattern: standalone function per exchange returning List[FundingRateRow], errors at WARNING level, never crash on individual venue failure"
    - "Watermark-based incremental refresh: get_watermark() returns None on first run (triggers full backfill), ms timestamp on subsequent runs (triggers forward-from-watermark)"
    - "Bybit both-or-neither constraint: endTime checked first, startTime only added when endTime also present"
    - "Aevo nanosecond pattern: divide by 1e9 (NOT 1e3); epoch constant stored as seconds * 1e9"
    - "dYdX v4 cursor backward pagination: effectiveBeforeOrAt cursor, stop at watermark or v4 epoch"
    - "Dry-run skips DB entirely: ingest_venue_full(engine=None, dry_run=True) uses epoch constants as start, logs what would be fetched, no fetcher calls"
    - "NullPool for one-shot scripts: create_engine(db_url, poolclass=NullPool) matches project pattern"

key-files:
  created:
    - src/ta_lab2/scripts/perps/__init__.py
    - src/ta_lab2/scripts/perps/funding_fetchers.py
    - src/ta_lab2/scripts/perps/refresh_funding_rates.py
  modified: []

key-decisions:
  - "Lighter stub returns [] + WARNING: lighter-python SDK integration deferred (REST endpoint unconfirmed as of 2026-02-25)"
  - "Bybit backward pagination: slide endTime backward from now, stop at watermark -- always provide both startTime+endTime"
  - "dYdX cursor pagination: backward from now using effectiveBeforeOrAt, filter rows < watermark, stop at v4 epoch (Oct 2023)"
  - "Aevo epoch constant: 1_693_526_400 * 1_000_000_000 = Sep 2023 launch in nanoseconds"
  - "Standalone only (not wired into run_daily_refresh.py): funding ingest comes from exchange APIs, not CMC; separate to avoid blocking main pipeline on exchange failures"
  - "Daily rollup opt-in via --rollup: default behavior does NOT compute rollup; must explicitly request it"
  - "requests.get/post with timeout=30: consistent across all 6 venue fetchers; errors caught at WARNING not raised"

patterns-established:
  - "scripts/perps/ directory for perpetual futures ingestion scripts"
  - "FundingRateRow dataclass as normalized cross-venue funding rate record"
  - "Per-venue dispatch pattern: ingest_venue_full dispatches to _ingest_{venue}() helper per venue"

duration: 5min
completed: 2026-02-25
---

# Phase 51 Plan 02: Funding Rate Ingestion Summary

**Per-venue funding rate fetchers for 6 exchanges (Binance, Hyperliquid, Bybit, dYdX, Aevo, Aster) with watermark-based incremental ingest, daily rollup, and cross-venue average fallback; Lighter stubbed pending SDK integration**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-25T23:33:56Z
- **Completed:** 2026-02-25T23:39:10Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- Created `src/ta_lab2/scripts/perps/` package with `FundingRateRow` dataclass and 7 fetch functions (6 active venues + Lighter stub)
- All fetch functions handle empty responses gracefully and log errors at WARNING level without crashing
- Implemented watermark-based incremental refresh with venue-specific pagination strategies (forward/backward) and venue-appropriate epoch constants
- CLI supports `--all`, `--venue`, `--symbol`, `--dry-run`, `--rollup`, `--no-rollup`; `--dry-run` requires no DB connection (skips watermark query, uses epoch 0 as start)

## Task Commits

Each task was committed atomically:

1. **Task 1: FundingRateRow dataclass + per-venue fetcher functions** - `78993076` (feat)
2. **Task 2: Refresh script with watermark pagination, daily rollup, and CLI** - `673e4ebe` (feat)

**Plan metadata:** (included in this SUMMARY commit)

## Files Created/Modified

- `src/ta_lab2/scripts/perps/__init__.py` - Package init with module docstring
- `src/ta_lab2/scripts/perps/funding_fetchers.py` - FundingRateRow dataclass + 7 fetch functions: fetch_binance_funding, fetch_hyperliquid_funding, fetch_bybit_funding, fetch_dydx_funding, fetch_aevo_funding, fetch_aster_funding, fetch_lighter_funding (stub)
- `src/ta_lab2/scripts/perps/refresh_funding_rates.py` - CLI script: upsert_funding_rates, get_watermark, ingest_venue_full, 6 per-venue ingest helpers, compute_daily_rollup, get_funding_rate_with_fallback, argparse main()

## Decisions Made

- **Lighter stub with WARNING**: lighter-python SDK integration deferred. REST endpoint returns 404 per research. fetch_lighter_funding() logs WARNING "Lighter funding rate API not confirmed; requires lighter-python SDK" and returns []. Stub is called in ingest_venue_full so the lighter path is exercised during --all runs.
- **Bybit backward pagination with both-or-neither constraint**: Bybit requires endTime when startTime provided. _ingest_bybit() slides backward from now, providing both startTime and endTime in a window of 200 x 8h = ~67 days. This satisfies the API constraint while enabling watermark-based stopping.
- **dYdX cursor-based backward pagination**: effectiveBeforeOrAt cursor advances to min(ts) of each batch. Stop conditions: (a) oldest ts <= watermark, or (b) cursor <= dYdX v4 epoch ISO string (Oct 2023).
- **Dry-run passes engine=None**: ingest_venue_full() and all _ingest_*() helpers have an early-return path for dry_run=True that logs what would be fetched without touching the engine. This enables `--dry-run` to run with no DB connection for the watermark query.
- **Daily rollup opt-in**: --rollup flag required to compute daily rollup; default behavior is to skip. Keeps ingest fast for incremental runs where rollup is not needed.

## Deviations from Plan

None - plan executed exactly as written.

The plan specified all requirements clearly (Bybit both-or-neither constraint, Aevo nanosecond timestamps, dYdX v4 indexer, dry-run without DB, Lighter stub). All implemented as specified.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted both files on first commit attempt for each task; required re-staging and re-committing. Standard Windows/git behavior, no code impact.

## User Setup Required

None - all scripts are standalone. No external service configuration required beyond exchange API public endpoints (no auth needed for any of the 6 active venues).

To run against live exchanges (all venues, BTC + ETH):
```bash
python -m ta_lab2.scripts.perps.refresh_funding_rates --all
```

To dry-run (no DB connection needed):
```bash
python -m ta_lab2.scripts.perps.refresh_funding_rates --dry-run --venue binance --symbol BTC
```

## Next Phase Readiness

- `cmc_funding_rates` table is now populated by `refresh_funding_rates.py --all` for Plan 04 (backtester extension / FundingAdjuster)
- `get_funding_rate_with_fallback()` is ready for use by FundingAdjuster in Plan 04
- `compute_daily_rollup()` produces `tf='1d'` rows for carry trade analysis queries
- No blockers for subsequent plans

---
*Phase: 51-perps-readiness*
*Completed: 2026-02-25*
