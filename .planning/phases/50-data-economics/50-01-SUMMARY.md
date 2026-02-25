---
phase: 50-data-economics
plan: 01
subsystem: database
tags: [postgresql, cost-audit, vendor-comparison, data-economics, coingecko, polygon, alpaca]

# Dependency graph
requires:
  - phase: 49-tail-risk-policy
    provides: Phase 49 complete; v1.0.0 data economics analysis now executing
provides:
  - reports/data-economics/cost-audit.md — actual DB size (46 GB measured), 171 tables, per-table breakdown, CMC process documented, free-tier register, monthly TCO range
  - reports/data-economics/vendor-comparison.md — 7 crypto vendor matrix, 5 equities vendor matrix, tiered recommendations by scale, risk assessment
affects:
  - 50-02 (TCO model will consume cost-audit.md and vendor-comparison.md as inputs)
  - any future vendor onboarding plans (CoinGecko, Alpaca, Polygon.io)
  - architecture ADR in docs/architecture/

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SQLAlchemy + pg_stat_user_tables for real DB size measurement (not estimates)"
    - "reports/data-economics/ gitignored directory for analysis documents (matches reports/bakeoff/ pattern)"

key-files:
  created:
    - reports/data-economics/cost-audit.md
    - reports/data-economics/vendor-comparison.md
  modified: []

key-decisions:
  - "DB is 46 GB not 8-12 GB: actual measurement 4x larger than research estimate, primarily due to index overhead on 171 tables and baseline snapshot tables"
  - "17 assets tracked (not 2 as assumed in research): includes BTC, ETH, 6 other crypto IDs, and 9 equities (FBTC, GOOGL, GS, IBIT, KO, MARA, MSTR, NVDA, WMT)"
  - "reports/ is gitignored by design: analysis documents follow established Phase 42 convention"
  - "Developer time is 99%+ of TCO: $200-800/month vs $0 API costs — optimizing API costs is a secondary concern"
  - "CoinGecko Analyst ($129/mo) is the recommended crypto upgrade path at 2x scale"
  - "Alpaca free tier is the recommended equities expansion path at 2x scale (already integrated for execution)"

patterns-established:
  - "Cost audit pattern: always measure with pg_database_size() + pg_total_relation_size(); never use estimates"
  - "TCO range pattern: present as min/max at $50/hr and $100/hr rates, not point estimates"
  - "Vendor comparison: research date + re-verify note mandatory for any document with vendor pricing"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 50 Plan 01: Data Economics Cost Audit and Vendor Comparison Summary

**Actual PostgreSQL DB measured at 46 GB across 171 tables with $0 API costs and $200-800/month developer time dominating TCO; CoinGecko Analyst + Alpaca recommended for 2x scale at $129/month**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T22:56:09Z
- **Completed:** 2026-02-25T23:02:00Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments

- Measured actual PostgreSQL database size at **46 GB** (vs 8-12 GB research pre-estimate — 4x larger, due to index overhead and baseline snapshot tables)
- Created `reports/data-economics/cost-audit.md` (360 lines) with real pg_database_size() measurements, 171-table breakdown, per-asset cost attribution (~2.7 GB/asset), CMC bulk download process documented, free-tier dependency register with 8 dependencies and paid fallbacks, and monthly TCO range ($200-805/month)
- Created `reports/data-economics/vendor-comparison.md` (285 lines) with 7-vendor crypto matrix, 5-vendor equities matrix, tiered scale recommendations (current/$0, 2x/$129/mo, 5x/$208+/mo), and 5-risk assessment
- Confirmed **17 assets** in dim_assets (not 2 as assumed in research — includes 8 crypto + 9 equities already onboarded)
- Documented that developer time is **99%+ of current TCO** ($200-800/month) vs $0 API costs

## Task Commits

Each task was committed atomically:

1. **Task 1: Measure actual DB sizes and write cost-audit.md** - reports/ is gitignored (matches Phase 42 established convention; files written to disk, not committed)
2. **Task 2: Write vendor-comparison.md** - reports/ is gitignored (same)

**Plan metadata:** committed as docs(50-01)

_Note: reports/ directory is in .gitignore per Phase 42-05 decision. Analysis documents are on disk at reports/data-economics/ but not tracked in git._

## Files Created/Modified

- `reports/data-economics/cost-audit.md` — Current state cost audit with real DB measurements (46 GB measured), per-table breakdown of top 30 tables, table family summary (12 families), per-asset cost attribution (~2.7 GB/asset), CMC bulk download process documentation, free-tier dependency register, monthly TCO range
- `reports/data-economics/vendor-comparison.md` — Crypto + equities vendor comparison matrices with pricing tiers, tiered recommendations by scale (current/2x/5x), risk assessment for 5 key dependencies

## Decisions Made

- **DB is 46 GB not 8-12 GB:** pg_database_size() returned 49,312,790,207 bytes (~46 GB). Research pre-estimate of 8-12 GB was based on raw row bytes only; actual size includes 47% index overhead (5,272 MB indexes on the largest table alone), baseline snapshot tables (_20260218 variants contributing ~1.5 GB), and the cross-asset correlation table (4.7 GB, not in original estimate).

- **17 assets, not 2:** dim_assets contains 17 rows: numeric IDs 1, 52, 1027, 1839, 1975, 5426, 32196 (crypto CMC IDs), CPOOL, and 9 equities (FBTC, GOOGL, GS, IBIT, KO, MARA, MSTR, NVDA, WMT). Per-asset storage is ~2.7 GB average, marginal cost of one more asset is approximately $0.06/month at AWS S3 pricing.

- **Developer time at 99%+ of TCO:** At current scale with $0 API costs, monthly TCO is purely developer time ($200-800/month). Adding CoinGecko at $129/month would add 16-65% to cash TCO — meaningful but still secondary to maintenance hours.

- **Alpaca is the natural equities path:** Already integrated for paper trading execution (Phase 45). Activating the Alpaca data API requires only a new ingestion script — no new vendor relationship or account needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DB size 4x larger than research estimate**
- **Found during:** Task 1 (DB size measurement)
- **Issue:** Research pre-estimated 8-12 GB; actual measurement is 46 GB. Not a pipeline bug — the larger size is explained by index overhead (47%), baseline snapshot tables, and cross-asset correlation table not in original count.
- **Fix:** Used real measured value throughout cost-audit.md with explicit disclaimer noting the discrepancy and explanation
- **Files modified:** reports/data-economics/cost-audit.md
- **Verification:** pg_database_size() returned 49,312,790,207 bytes = 46 GB

**2. [Rule 1 - Bug] 17 assets in dim_assets, not 2 as assumed in research**
- **Found during:** Task 1 (asset count query)
- **Issue:** Research assumed 2 assets (BTC + ETH based on project description); dim_assets has 17 rows including 9 equities added during Phase 45/43
- **Fix:** Used actual asset count (17) throughout cost-audit.md, updated per-asset calculations accordingly
- **Files modified:** reports/data-economics/cost-audit.md
- **Verification:** `SELECT id, symbol FROM dim_assets ORDER BY id` returned 17 rows

**3. [Rule 1 - Observation] reports/ directory is gitignored**
- **Found during:** Task 1 (git add attempt)
- **Issue:** `.gitignore` line 102: `reports/` — established convention from Phase 42-05 decision. Files cannot be committed.
- **Fix:** Files written to disk (reports/data-economics/ exists and is populated); git commits contain only planning artifacts
- **Impact:** Reports serve their purpose as analysis inputs to Plan 02; gitignore is intentional project convention

---

**Total deviations:** 3 observed (2 data corrections, 1 gitignore constraint — all handled per plan guidance)
**Impact on plan:** Data corrections improved accuracy; gitignore constraint follows established project convention. Both report files are complete and ready for Plan 02 consumption.

## Issues Encountered

- Windows cp1252 encoding error when opening markdown files in Python without explicit `encoding='utf-8'` — consistent with MEMORY.md "CRITICAL: SQL migration on Windows" pattern. Worked around by using `encoding='utf-8'` in file open calls.

## User Setup Required

None — no external service configuration required. Reports are analysis documents, not runnable code.

## Next Phase Readiness

- `reports/data-economics/cost-audit.md` is ready as input to Plan 02 (TCO model)
- `reports/data-economics/vendor-comparison.md` is ready as input to Plan 02 (build-vs-buy analysis)
- Key finding for Plan 02: PostgreSQL is at 46 GB (not 8-12 GB), which changes the scale-sensitivity of migration timing
- Key finding for Plan 02: 17 assets already tracked (not 2), which changes the "current baseline" and "2x scale" definitions
- **Blocker for vendor upgrade:** CMC bulk download process needs verification against current account tier before any vendor migration plan finalizes

---
*Phase: 50-data-economics*
*Completed: 2026-02-25*
