# Phase 85: Dashboard Cleanup & Polish - Research

**Researched:** 2026-03-23
**Domain:** Streamlit dashboard bug fixes and UI consistency
**Confidence:** HIGH

---

## Summary

Phase 85 is a pure polish-and-bugfix phase targeting four known deficiencies in the
ta_lab2 Streamlit dashboard. All four problems have been confirmed by direct code
inspection — no ambiguity about what is broken or where.

**Problem 1 (Cache TTL slider):** The sidebar slider in `app.py` writes to session
state key `cache_ttl_display` but that key is never read by any query function. All
17 query modules hardcode `@st.cache_data(ttl=N)` at decoration time. Streamlit's
`st.cache_data` TTL is a static decorator parameter — there is no mechanism to change
it per-call. The only feasible live-wire approach is: read `st.session_state["cache_ttl_display"]`
in each query function and call `st.cache_data.clear()` when it changes. The simpler
and less fragile approach is to remove the slider entirely (it is misleading in its
current form), keep the Refresh button, and add a caption explaining the hardcoded
tiers (300s pipeline, 3600s backtest/macro, 120s live trading).

**Problem 2 (Drawdown calculation):** `load_daily_pnl_series()` in
`queries/trading.py` computes `peak_equity` as `cumulative_pnl.cummax()`. When
`cumulative_pnl` starts at 0 (before any fills), `peak_equity` is 0 and the division
`(cumulative_pnl - peak_equity) / peak_equity` divides by zero. The fix requires a
starting capital denominator. `dim_executor_config.initial_capital` is the canonical
source — a new query function `load_starting_capital(_engine)` should fetch the sum
(or max) of `initial_capital` from the active executor configs. The drawdown
calculation becomes `(equity - peak_equity) / starting_capital` where
`equity = starting_capital + cumulative_pnl`. The drawdown KPI card in
`6_trading.py` must also display the dollar drawdown amount alongside the percentage.

**Problem 3 (Stats allowlist):** `_STATS_TABLES` in `queries/pipeline.py` lists 6
table names that match exactly what `scripts/stats/run_all_stats_runners.py`
defines. Auto-discovery from `information_schema.tables` is safe and eliminates the
dual-maintenance problem. The existing codebase already uses `information_schema`
extensively for column discovery — the pattern is well-established. Row counts per
stats table can be fetched with a single query rather than per-table loops.

**Problem 4 (Visual consistency):** Older pages (`1_landing.py`,
`2_pipeline_monitor.py`) lack the structural patterns established in Phase 83/84
pages: explicit `engine = get_engine()` with `st.stop()` on failure, sidebar
controls in `with st.sidebar:` blocks, `@st.fragment(run_every=...)` for
auto-refresh, and consistent `st.header` + `st.caption` headers. The color palette
is already unified (`plotly_dark` template, rgb(0,200,100)/rgb(220,50,50)/
rgb(150,150,150)/rgb(255,165,0)) across all chart builders — no changes needed there.

**Primary recommendation:** Fix the four bugs independently. Cache TTL: remove the
decorative slider, document the three hardcoded TTL tiers in a sidebar caption. All
other bugs have straightforward targeted fixes.

---

## Standard Stack

The full dashboard stack is already in place. No new libraries are needed.

### Core (already installed)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| streamlit | current | Dashboard framework | All pages use multipage nav via `st.navigation()` |
| plotly | current | Charts | All charts use `plotly_dark` template |
| pandas | current | Data manipulation | Standard project dependency |
| sqlalchemy | current | DB queries | NullPool engine via `db.py` singleton |

### No new installs needed
All fixes are code-only changes to existing files in `src/ta_lab2/dashboard/`.

---

## Architecture Patterns

### Current Page Structure (Phase 83/84 established)
```
pages/XX_pagename.py
    module-level: st.header + st.caption
    module-level: engine = get_engine() with st.error + st.stop on failure
    module-level: load dimension data needed by sidebar
    with st.sidebar: controls
    @st.fragment(run_every=AUTO_REFRESH_SECONDS): main content function
    bottom: invoke fragment
```

### Pattern 1: Engine initialization (established in Phase 83/84 pages)
**What:** Consistent pattern for engine creation with hard stop on DB failure.
**When to use:** All pages that query the database.
**Example:**
```python
# Source: pages/16_regime_heatmap.py, pages/8_drift_monitor.py
try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()
```
Older pages (1_landing.py, 2_pipeline_monitor.py) call `get_engine()` inside
individual `try/except` blocks scattered throughout the page — inconsistent with
newer pattern.

### Pattern 2: Sidebar controls (established in Phase 83/84 pages)
**What:** All sidebar widgets live in a single `with st.sidebar:` block at
module level, OUTSIDE any `@st.fragment`.
**Why:** Streamlit prohibits sidebar widgets inside fragments.
**Example:**
```python
# Source: pages/16_regime_heatmap.py
with st.sidebar:
    st.subheader("Controls")
    selected_tf = st.selectbox("Timeframe", ["1D", "4H"], key="page_tf")
```

### Pattern 3: Cache TTL architecture (existing, hardcoded tiers)
Three TTL tiers are already in use across `queries/`:
- **120s**: Live trading data (`load_open_positions`, `load_recent_fills`, `load_risk_state`)
- **300s**: Pipeline/features/returns data (most query functions)
- **3600s**: Static backtest/macro/experiment results

These are correct for the data volatility of each tier. The hardcoded values
should be documented in a sidebar caption (see Anti-Patterns).

### Pattern 4: Drawdown with starting capital denominator
**What:** Calculate drawdown percentage as fraction of starting capital, not peak PnL.
**When to use:** Any equity curve / drawdown calculation.
**Example (corrected pattern):**
```python
# In load_daily_pnl_series():
starting_capital = load_starting_capital(_engine)  # new function

df["cumulative_pnl"] = df["daily_realized_pnl"].cumsum()
df["equity"] = starting_capital + df["cumulative_pnl"]
df["peak_equity"] = df["equity"].cummax()
# drawdown_pct is always well-defined: starting_capital > 0
df["drawdown_pct"] = (df["equity"] - df["peak_equity"]) / starting_capital
df["drawdown_usd"] = df["equity"] - df["peak_equity"]
```

### Pattern 5: information_schema stats table discovery
**What:** Query `information_schema.tables` to find all `*_stats` tables in
`public` schema, rather than maintaining a hardcoded list.
**Why:** Eliminates dual-maintenance when new stats tables are added.
**Example:**
```python
# Source pattern: existing usage in observability/health.py, analysis/ic.py
sql = text("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name LIKE '%\_stats'
      AND table_type = 'BASE TABLE'
    ORDER BY table_name
""")
```
**Security:** This is an internal allowlist derivation, not user input — no injection risk.
**Validation:** Filter result to only tables with a `status` column (via
`information_schema.columns`) to exclude `*_stats` tables that don't follow the
PASS/WARN/FAIL schema.

### Pattern 6: Stats table row count query
**What:** Fetch row counts alongside PASS/WARN/FAIL status using a single query.
**Current problem:** `load_stats_status()` makes N separate DB connections (one per
table in `_STATS_TABLES`). Row counts require another query.
**Recommended approach:**
```python
# One query per discovered stats table, return both counts and row count
sql = text(f"""
    SELECT
        status,
        COUNT(*) AS n,
        (SELECT COUNT(*) FROM public.{table}) AS total_rows
    FROM public.{table}
    WHERE checked_at >= NOW() - INTERVAL '24 hours'
    GROUP BY status
""")
```
The N-separate-connections pattern is already established — this extends it to
include `total_rows`.

### Recommended Project Structure (no changes)
```
src/ta_lab2/dashboard/
├── app.py              # Entry point, sidebar, nav groups (modify TTL caption)
├── db.py               # Engine singleton (no changes)
├── charts.py           # All chart builders (no changes)
├── queries/
│   ├── pipeline.py     # Fix: _STATS_TABLES -> information_schema, add row counts
│   ├── trading.py      # Fix: drawdown calculation, add load_starting_capital()
│   └── [others]        # No changes to other query modules
└── pages/
    ├── 1_landing.py    # Fix: engine init pattern, sidebar pattern
    ├── 2_pipeline_monitor.py  # Fix: engine init pattern, sidebar pattern
    ├── 6_trading.py    # Fix: drawdown KPI card (add $ amount)
    └── [others]        # Minor consistency polish
```

### Anti-Patterns to Avoid
- **Dynamic TTL via session_state workaround:** Reading `st.session_state["cache_ttl_display"]` inside a cached function and calling `st.cache_data.clear()` when it changes would create a cache-busting loop — every call would clear all caches if the slider was ever touched. Remove the slider instead.
- **Division by zero in drawdown:** Never use `peak_equity` (which can be 0) as the denominator. Use `starting_capital` from `dim_executor_config`.
- **String table names in SQL f-strings from user input:** The `information_schema` discovery is safe because it returns table names from system catalog — not user input. Maintain this pattern.
- **Multiple engine calls per page:** Older pages call `get_engine()` inside each `try:` block. This creates multiple cache lookups even though `get_engine()` is `@st.cache_resource`. Use a single module-level `engine = get_engine()` with hard stop.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| User-adjustable TTL | Dynamic decorator patching | `st.cache_data.clear()` via Refresh button | Decorator TTL is static; patching is fragile |
| Starting capital | Query `dim_risk_limits` alone | Query `dim_executor_config.initial_capital` | `dim_risk_limits` has no `initial_capital` column; executor config does |
| Stats table discovery | Manual list maintenance | `information_schema.tables` WHERE `table_name LIKE '%\_stats'` | Pattern already used in 10+ places in codebase |
| Row counts per stats table | Separate `COUNT(*)` query after `load_stats_status` | Include `total_rows` in existing per-table loop | Already in N-connection pattern; just extend the SELECT |

**Key insight:** The dashboard already has all the patterns needed. Phase 85 is
applying established patterns to the files that predate them.

---

## Common Pitfalls

### Pitfall 1: Cache TTL slider creates false expectation
**What goes wrong:** User moves the slider, nothing changes. The caption "Cache TTL: 300s (fixed)" is the only honest statement on the page but is buried below the slider.
**Why it happens:** The slider was added as a placeholder — the dynamic TTL wiring was deferred and never done.
**How to avoid:** Remove the slider widget entirely. Replace the caption with factual TTL tiers: "Pipeline: 5min | Backtest/Macro: 60min | Live: 2min. Use Refresh to clear all."
**Warning signs:** Any `st.session_state["cache_ttl_display"]` references that are never consumed.

### Pitfall 2: Drawdown divide-by-zero on first run
**What goes wrong:** `load_daily_pnl_series()` returns `drawdown_pct = NaN` or `inf` when cumulative PnL starts at 0 (before any fills). The `.where(df["peak_equity"] != 0, 1)` guard in the current code substitutes 1 as denominator when `peak_equity == 0`, which produces `drawdown_pct = 0 - 0 / 1 = 0` — numerically safe but semantically wrong (it hides drawdown when cumulative PnL is negative and peak hasn't risen above 0).
**Why it happens:** The equity baseline was treated as the PnL curve starting from 0 rather than from starting capital.
**How to avoid:** Use `starting_capital` from `dim_executor_config.initial_capital`. If no active executor config exists, default to `100000.0` (matches the existing `PositionSizer` default in `position_sizer.py`).
**Warning signs:** Drawdown KPI shows 0% when portfolio is clearly underwater.

### Pitfall 3: `load_starting_capital` caching
**What goes wrong:** If `load_starting_capital` is called inside `load_daily_pnl_series` (which is `@st.cache_data`), the inner call to another cached function may not be hashed correctly.
**Why it happens:** `@st.cache_data` hashes all parameters; calling a cached function inside another cached function can lead to unexpected behavior.
**How to avoid:** Make `load_starting_capital(_engine)` a separate `@st.cache_data(ttl=3600)` function. Call it separately in the page, pass the result as a parameter to the drawdown computation, or call it within `load_daily_pnl_series` but understand the cache layer interaction. Simplest: call it in the page's fragment alongside the PnL load.

### Pitfall 4: information_schema discovery returns unexpected tables
**What goes wrong:** Tables like `ema_multi_tf_cal_anchor_stats_state` (the watermark state table, not a stats table) match the `%\_stats` pattern.
**Why it happens:** State tables are named `*_stats_state`. The `LIKE '%\_stats'` pattern with `\_` (escaped underscore) ending anchors the match to tables whose name ends exactly in `_stats`.
**How to avoid:** Use `table_name LIKE '%\_stats'` (underscore escaped in SQL LIKE) to match tables ending in exactly `_stats` — this excludes `*_stats_state` variants.
**Warning signs:** Stats table count in discovery query returns more than expected; entries for `_state` tables appear in the display.

### Pitfall 5: Stats table `status` column assumption
**What goes wrong:** Not all tables ending in `_stats` follow the PASS/WARN/FAIL schema (e.g., `asset_stats` is a wide-format rolling stats table with no `status` column).
**Why it happens:** The `_stats` suffix is used for two different table families in this codebase.
**How to avoid:** After `information_schema.tables` discovery, filter to only tables that have a `status` column via a second `information_schema.columns` check. Alternatively, use the explicit prefix pattern: tables in `run_all_stats_runners.STATS_TABLES` all contain `multi_tf_stats`, `returns_ema_stats`, or `features_stats` — a tighter LIKE pattern (`%multi\_tf\_stats` OR `%returns\_ema\_stats` OR `features\_stats`) avoids the `asset_stats` false positive.

### Pitfall 6: Landing page `get_engine()` inside try blocks
**What goes wrong:** `1_landing.py` calls `get_engine()` 4-5 times in separate `try:` blocks. If the DB is down, each section independently fails with separate error messages rather than a single clear "DB unavailable" stop.
**Why it happens:** The landing page was built before the Phase 83/84 pattern was established.
**How to avoid:** Single `engine = get_engine()` at module level with `st.error + st.stop()` guard, then pass `engine` to each section.

---

## Code Examples

### Corrected drawdown calculation
```python
# Source: queries/trading.py (new load_starting_capital + updated load_daily_pnl_series)

@st.cache_data(ttl=3600)
def load_starting_capital(_engine) -> float:
    """Return sum of initial_capital from active executor configs.

    Falls back to 100_000.0 if no active configs found (matches PositionSizer default).
    """
    sql = text(
        """
        SELECT COALESCE(SUM(initial_capital), 100000.0) AS starting_capital
        FROM public.dim_executor_config
        WHERE is_active = TRUE
          AND initial_capital IS NOT NULL
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    if row is None:
        return 100_000.0
    return float(row[0])


@st.cache_data(ttl=300)
def load_daily_pnl_series(_engine) -> pd.DataFrame:
    """Return daily realized P&L with corrected drawdown calculation.

    Columns: trade_date, daily_realized_pnl, cumulative_pnl,
             equity, peak_equity, drawdown_pct, drawdown_usd
    """
    # [existing SQL unchanged] ...
    starting_capital = load_starting_capital(_engine)

    df["cumulative_pnl"] = df["daily_realized_pnl"].cumsum()
    df["equity"] = starting_capital + df["cumulative_pnl"]
    df["peak_equity"] = df["equity"].cummax()
    # Denominator is always starting_capital > 0 -- no divide-by-zero
    df["drawdown_pct"] = (df["equity"] - df["peak_equity"]) / starting_capital
    df["drawdown_usd"] = df["equity"] - df["peak_equity"]
    return df
```

### information_schema stats table discovery (safe pattern)
```python
# Source: existing pattern in observability/health.py + analysis/ic.py

@st.cache_data(ttl=300)
def load_stats_tables(_engine) -> list[str]:
    """Discover all *_stats tables in public schema that have a status column."""
    discovery_sql = text(
        """
        SELECT t.table_name
        FROM information_schema.tables t
        JOIN information_schema.columns c
            ON c.table_schema = t.table_schema
            AND c.table_name = t.table_name
            AND c.column_name = 'status'
        WHERE t.table_schema = 'public'
          AND t.table_name LIKE '%\_stats'
          AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name
        """
    )
    with _engine.connect() as conn:
        rows = conn.execute(discovery_sql).fetchall()
    return [row[0] for row in rows]
```

### Drawdown KPI card with both % and $
```python
# Source: pages/6_trading.py (in _trading_content fragment)

if _pnl_series is not None and not _pnl_series.empty:
    _peak = float(_pnl_series["peak_equity"].max())
    _current_dd_pct = float(_pnl_series["drawdown_pct"].iloc[-1])
    _max_dd_pct = float(_pnl_series["drawdown_pct"].min())
    _current_dd_usd = float(_pnl_series["drawdown_usd"].iloc[-1])
    _max_dd_usd = float(_pnl_series["drawdown_usd"].min())

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Peak Equity", f"${_peak:,.2f}")
    d2.metric(
        "Current Drawdown",
        f"{_current_dd_pct:.1%}",
        delta=f"${_current_dd_usd:,.0f}",
        delta_color="inverse" if _current_dd_usd < 0 else "off",
    )
    d3.metric(
        "Max Historical Drawdown",
        f"{_max_dd_pct:.1%}",
        delta=f"${_max_dd_usd:,.0f}",
        delta_color="inverse",
    )
    d4.metric("Starting Capital", f"${_starting_capital:,.0f}")
```

### Cache TTL sidebar replacement (simplified)
```python
# Source: app.py sidebar (replaces current slider + misleading caption)

with st.sidebar:
    st.title("ta_lab2")
    st.caption("Analysis + Operations + Monitoring")
    st.divider()
    if st.button("Refresh Now", type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "Cache tiers: Live trading 2min · Pipeline 5min · "
        "Research/Backtest 60min"
    )
    st.divider()
```

### Engine init pattern (Phase 83/84 standard)
```python
# Source: pages/16_regime_heatmap.py, pages/8_drift_monitor.py

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-section `get_engine()` calls | Single module-level engine + `st.stop()` | Phase 83/84 | Cleaner failure mode; single error message |
| Inline chart building in pages | `charts.py` builder functions | Phase 52 | Reusable chart builders across pages |
| `ttl=300` uniform across all queries | Three-tier TTL (120/300/3600) | Phase 63+ | Appropriate cache lifetimes per data volatility |

**Deprecated/outdated in this codebase:**
- Decorative slider with caption "300s (fixed)": remove, replace with descriptive caption.
- `cmc_` prefix stripping in `2_pipeline_monitor.py` display name logic (`display_name.replace("cmc_", "")`): already unnecessary since tables were renamed to drop `cmc_` prefix in Phase 75+.

---

## Open Questions

1. **Starting capital for multi-strategy setups**
   - What we know: `dim_executor_config.initial_capital` stores per-strategy starting capital. Multiple active strategies may have different values.
   - What's unclear: Should drawdown use SUM of all active `initial_capital` values, or MAX, or the single strategy with most capital? Current trading page shows aggregate positions.
   - Recommendation: Use SUM of active configs for portfolio-level drawdown (consistent with how `_total_portfolio_value` is calculated on the trading page as `day_open_portfolio_value + unrealized_pnl`). If no active configs, default to 100,000 (matches `PositionSizer` default).

2. **Stats table row count display in Pipeline Monitor**
   - What we know: Current `load_stats_status` returns PASS/WARN/FAIL counts from last 24h. Row counts require a separate `COUNT(*)` query per table.
   - What's unclear: Whether total rows (all-time) or recent rows (24h) is more useful.
   - Recommendation: Show total rows alongside status counts — it gives operators a quick sense of whether the stats runner has been populating the table at all. The N-connections pattern is already established so adding `total_rows` per table is low risk.

3. **Navigation group reorganization**
   - What we know: Current groups are Overview (1 page), Analysis (10 pages), Operations (5 pages), Monitor (1 page). The context says groups need to "reflect new page categories."
   - What's unclear: What the intended new grouping is — the context only says "updated to reflect new page categories."
   - Recommendation: Treat this as Claude's discretion. Logical split: Overview (Landing), Research (Asset Hub, Backtest, Signals, Research Explorer, Experiments, Asset Stats), Adaptive MAs (Perps, Portfolio, Regime Heatmap, AMA Inspector), Operations (Trading, Risk, Drift, Executor, Macro), Monitor (Pipeline Monitor).

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `src/ta_lab2/dashboard/` — all findings are from current source
- `queries/trading.py` lines 106-142: confirmed drawdown bug
- `queries/pipeline.py` lines 17-24: confirmed hardcoded `_STATS_TABLES`
- `app.py` lines 24-36: confirmed decorative slider
- `pages/16_regime_heatmap.py`: established Phase 84 pattern (engine init, sidebar, fragment)
- Alembic `a1b2c3d4e5f7_add_initial_capital_to_executor_config.py`: confirms `initial_capital` column in `dim_executor_config`
- `scripts/stats/run_all_stats_runners.py` lines 51-58: confirmed STATS_TABLES matches pipeline.py allowlist exactly

### Secondary (MEDIUM confidence)
- [Streamlit st.cache_data docs](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data): TTL is static decorator parameter, not callable — confirmed dynamic TTL is not natively supported
- Existing `information_schema` usage in `observability/health.py`, `analysis/ic.py`, `features/ama/base_ama_feature.py`: pattern is established and safe

### Tertiary (LOW confidence)
- None — all findings are directly verifiable from the codebase

---

## Metadata

**Confidence breakdown:**
- Bug identification: HIGH — all four bugs confirmed by direct code inspection
- Fix approach for TTL: HIGH — official Streamlit docs confirm TTL is static; removal is unambiguous
- Fix approach for drawdown: HIGH — `dim_executor_config.initial_capital` column confirmed via migration
- Fix approach for stats discovery: HIGH — `information_schema` pattern in 10+ existing files
- Visual consistency scope: MEDIUM — "consistent with Phase 83/84 pages" is somewhat subjective; concrete pattern checklist provided

**Research date:** 2026-03-23
**Valid until:** Stable — dashboard framework and DB schema won't change in this phase window
