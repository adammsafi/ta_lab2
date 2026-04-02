---
created: 2026-03-15T12:30
title: Build VWAP bars for all multi-venue assets and integrate into daily pipeline
area: data-pipeline
files:
  - src/ta_lab2/scripts/bars/refresh_vwap_bars_1d.py
  - src/ta_lab2/scripts/bars/run_all_bar_builders.py
  - src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py
priority: medium
---

# VWAP Consolidation for All Multi-Venue Assets + Daily Pipeline

## Problem

The VWAP bar builder (`refresh_vwap_bars_1d.py`) works for any asset with 2+
non-aggregate venues, but currently only CPOOL (id=12573) has data from multiple
exchange venues (BYBIT, GATE, KRAKEN).

Two equity assets — GOOGL (100002) and NVDA (100008) — also have data from two
venues (NASDAQ via TVC + HYPERLIQUID) but the VWAP script doesn't pick them up
because they use different venue text values than exchange venues.

As more assets are onboarded across venues, VWAP should build automatically.

## Current State

| Asset | ID | Venues | VWAP rows |
|-------|----|--------|-----------|
| CPOOL | 12573 | BYBIT, GATE, KRAKEN | 735 |
| GOOGL | 100002 | NASDAQ, HYPERLIQUID | 0 (not built) |
| NVDA | 100008 | NASDAQ, HYPERLIQUID | 0 (not built) |

## Tasks

### 1. Run VWAP for all qualifying assets now
The script already auto-detects multi-venue assets with `--ids all`.
Verify GOOGL and NVDA qualify (they should — both have 2 non-VWAP/non-CMC_AGG venues).
If the `EXCLUDED_VENUES` filter blocks them, update it.

### 2. Add VWAP to dim_venues
VWAP bars currently write with `venue_id=1` (CMC_AGG), which is incorrect.
Add VWAP as a proper venue in `dim_venues` and assign the correct venue_id.

### 3. Integrate into daily pipeline
Add `refresh_vwap_bars_1d --ids all` as a step in:
- `run_all_bar_builders.py` — after all per-venue 1D builders, before multi-TF
- `run_go_forward_daily_refresh.py` — if it orchestrates bar building

Order: per-venue 1D bars -> VWAP consolidation -> multi-TF aggregation

### 4. Automatic for new assets
No code changes needed — `--ids all` auto-detects any asset with 2+ venues.
As new per-venue bars are added, VWAP will pick them up on next run.

## Verification

```sql
-- After running, confirm VWAP bars exist for all multi-venue assets:
SELECT id, venue, COUNT(*) FROM price_bars_1d
WHERE venue = 'VWAP'
GROUP BY id, venue;

-- Confirm no single-venue assets got VWAP (HAVING COUNT >= 2 guard):
SELECT id, COUNT(DISTINCT venue) as n_venues
FROM price_bars_1d
WHERE venue NOT IN ('VWAP', 'CMC_AGG')
GROUP BY id
HAVING COUNT(DISTINCT venue) >= 2;
```
