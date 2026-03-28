---
phase: 84-dashboard-perps-portfolio-regimes
plan: 05
status: complete
started: 2026-03-23T13:30:00Z
completed: 2026-03-23T14:20:00Z
commits:
  - hash: 3d999c60
    message: "feat(84-05): register 4 new dashboard pages in app.py navigation"
  - hash: 3d14d7a1
    message: "fix(84-05): address dashboard verification feedback"
  - hash: 358af3a2
    message: "fix(84-05): proper symbols via cmc_da_info JOIN + volume comma"
  - hash: 6421b703
    message: "fix(84-05): move asset selectors inline on perps page"
  - hash: 4dd5eb3f
    message: "fix(84-05): inline selectors per section + landing page fixes"
---

## Summary

Registered all 4 new dashboard pages (Perps, Portfolio, Regime Heatmap, AMA Inspector) in app.py navigation. Human verification revealed multiple issues across all pages which were fixed iteratively.

## What was built

- 4 new pages registered in Analysis sidebar group in app.py
- All pages accessible and rendering correctly after fixes

## Verification fixes applied

1. **Funding heatmap SQL GroupingError** -- `ORDER BY MAX(a.day_ntl_vlm)` (was bare column outside GROUP BY)
2. **OI formatting** -- Added `oi_base` (commas) and `oi_usd` (mark_px * OI) columns to top perps table
3. **Default asset "0G"** -- All dropdowns default to BTC instead of first alphabetical asset
4. **Portfolio chart_download_button** -- Fixed wrong args `(fig, filename, key=...)` to `(fig, label, filename)`
5. **Regime heatmap timezone warning** -- `tz_localize(None)` before `to_period("W")`
6. **dim_assets.symbol stores CMC IDs** -- All queries (load_asset_list, 4 regime queries) now JOIN cmc_da_info via `COALESCE(ci.symbol, da.symbol)` for proper tickers (BTC, ETH, SOL not 1, 1027, 5426)
7. **Volume comma formatting** -- Metric cards now show `$2,633.6M` not `$2633.6M`
8. **Inline asset selectors** -- Funding rate dropdowns placed below "Funding Rate Analysis" header, candle dropdown below "Daily Candles + OI" header (split into 3 fragments)
9. **Landing page freshness** -- `pd.Timestamp.now("UTC")` replaces deprecated `utcnow().tz_localize("UTC")`
10. **Landing page IC results** -- Queries BTC (asset_id=1) directly instead of first alphabetical asset; shortened timestamp format to prevent cutoff

## Decisions

- dim_assets.symbol stores CMC IDs (e.g., "1" for Bitcoin) -- all dashboard queries must JOIN cmc_da_info for real tickers
- Perps page uses 3 separate @st.fragment functions (top perps, funding+heatmap, candles) so selectors can be placed between sections
- EMA comovement limited to 7 assets (21 rows) by design in regime_comovement table -- not a bug
- IC results landing widget hardcodes BTC (asset_id=1) as most representative asset
