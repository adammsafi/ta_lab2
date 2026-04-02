# TVC Pipeline Issues

**Filed:** 2026-04-01
**Priority:** Medium
**Scope:** TVC data source → price_bars_1d

## Issue 1: Venue Mapping Incorrect

Assets from `tvc_price_histories` get wrong venue_id in `price_bars_1d`:
- CPOOL (id=12573): Has listings on BYBIT(3), KRAKEN(4), GATE(5) but stored as venue_id=11 (TVC)
- id=100005: Source has `venue=BATS` but stored as venue_id=10 (NYSE)

The TVC 1D builder's CTE template resolves venue_id via dim_listings JOIN, but the mapping is wrong or falling back to incorrect defaults.

**Fix:** Investigate `dim_data_sources.src_cte_template` for TVC — check the venue_id resolution logic.

## Issue 2: Row Count Mismatch (History Truncation)

`tvc_price_histories` has significantly more rows than `price_bars_1d` for every TVC asset:
- id=100005: 16,167 TVC rows (1962-2026) → only 1,714 bars (2019-2026)
- id=100002: 5,437 TVC rows → 1,710 bars
- id=12573: 2,978 TVC rows → 1,581 bars

The 1D builder is truncating history — only processing from ~2019 onward.

**Likely cause:** State table watermark, CTE date filter, or id_loader_sql restriction.
**Fix:** Check `price_bars_1d_state` for these IDs, review TVC CTE template date handling.

## Issue 3: TVC Sync Not in Pipeline

`sync_tvc_from_vm.py` exists but is not wired into `run_daily_refresh.py` sync_vms stage. TVC raw data hasn't been refreshed since 2026-02-23.

**Fix:** Wire into sync_vms stage (same as CMC sync was added).
