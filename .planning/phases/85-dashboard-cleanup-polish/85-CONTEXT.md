# Phase 85: Dashboard Cleanup & Polish - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix known dashboard bugs (non-functional TTL slider, hardcoded stats allowlist, incorrect drawdown calculation) and ensure visual consistency across all 17 pages. No new features — polish and bug fixes only.

Depends on Phase 83 (backtest/signal pages) and Phase 84 (perps/portfolio/regimes pages) being complete.

</domain>

<decisions>
## Implementation Decisions

### Cache TTL slider behavior
- Slider is currently decorative (caption says "300s fixed") — needs to actually control cache TTLs or be removed
- Claude's discretion on: whether to wire it live vs remove it, global vs tiered TTL, range, and whether Refresh button stays alongside
- Current state: hardcoded ttl=300 (pipeline queries), ttl=3600 (backtest/macro/experiment queries), ttl=900 (regime/perps queries)

### Drawdown calculation fix
- **Must use portfolio starting capital** as denominator, not zero-based cumulative PnL peak
- Starting capital sourced from `dim_risk_limits` or equivalent config table (not hardcoded)
- Display: **both % and $** — percentage in the drawdown chart, dollar amount in KPI metric card
- Current bug: `drawdown_pct = (cumulative_pnl - peak_equity) / peak_equity` divides by zero when peak_equity=0

### Visual consistency rules
- Pipeline Monitor and Landing page specifically called out as needing alignment with newer Phase 83/84 pages
- General polish across all 17 pages for cohesive feel
- Per-page layout flexibility (NOT enforcing a rigid header→metrics→chart→table template)
- Alert placement: critical warnings at top of page, contextual info messages inline near relevant sections
- Claude's discretion on: metric card styling (st.metric vs custom), color consolidation, spacing

### Stats table discovery
- Current: 6 hardcoded table names in `_STATS_TABLES` allowlist in `pipeline.py`
- Show pass/fail status **plus row counts** per table (not just pass/fail)
- Claude's discretion on: auto-discover from information_schema vs expanded allowlist, handling of empty/stale tables

</decisions>

<specifics>
## Specific Ideas

- Pipeline Monitor is one of the oldest pages — should feel as polished as the Phase 84 perps/regime pages
- Landing page needs work to be a proper "home" dashboard
- All charts already use `plotly_dark` template and consistent color palette (green=bullish, red=bearish, gray=neutral, orange=caution) — preserve this

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 85-dashboard-cleanup-polish*
*Context gathered: 2026-03-23*
