# Phase 52: Operational Dashboard - Research

**Researched:** 2026-02-25
**Domain:** Streamlit dashboard extension + operational paper trading views
**Confidence:** HIGH

## Summary

Phase 52 extends the existing Phase 39 Streamlit multipage app (`src/ta_lab2/dashboard/`) with
3-4 new operational pages. The codebase is already well-established: NullPool engine singleton in
`db.py`, `@st.cache_data(ttl=N)` query modules per page in `queries/`, Plotly `go.Figure` chart
builders in `charts.py`, and page registration via `st.navigation()` dict in `app.py`. The
operational data — positions, fills, risk state, drift metrics — all live in DB tables that were
built and migrated in Phases 44-47 and are fully live in the database.

The key discovery for auto-refresh: Streamlit 1.44.0 (installed version) supports
`@st.fragment(run_every=...)` natively. This lets a page section self-rerun on a timer without a
full-app rerun. No external `streamlit-autorefresh` package needed or installed. The correct
pattern is a module-level `AUTO_REFRESH_SECONDS = 900` constant (15 min = 900 s), passed as
`run_every=AUTO_REFRESH_SECONDS` to the fragment decorator.

The CONTEXT.md decisions are precise: 3 or 4 operational pages (Claude decides), separate page
per concern, drift gets its own page, kill switch / drift pause prominently bannered, position
table with 12 named columns, trade log (last 20 fills), stacked equity + drawdown panels, progress
bar proximity gauges, filterable risk event history.

**Primary recommendation:** 4 operational pages (Trading, Risk & Controls, Drift Monitor, Executor
Status), grouped under an "Operations" navigation header. Use `st.fragment(run_every=900)` for the
auto-refresh sections. Each page has a dedicated `queries/` module following the existing pattern.

## Standard Stack

The established libraries/tools for this domain:

### Core (all pre-installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.44.0 | Dashboard framework | Existing app foundation |
| plotly | (installed) | Interactive charts | Already used in charts.py |
| pandas | (installed) | DataFrame ops for query results | Already used everywhere |
| sqlalchemy | (installed) | DB queries via NullPool engine | db.py singleton already wired |

### Streamlit Features Used
| Feature | How Used | Notes |
|---------|----------|-------|
| `st.fragment(run_every=N)` | Auto-refresh sections every N seconds | Streamlit 1.44.0, no package needed |
| `@st.cache_data(ttl=N)` | Cache query results | Underscore-prefix engine param required |
| `st.cache_resource` | Engine singleton | Already in db.py |
| `st.navigation(pages_dict)` | Multipage routing | Already in app.py |
| `st.progress()` | Proximity gauges | For daily loss %, TE % of threshold |
| `st.metric()` | KPI cards | Already used in existing pages |

### No New Packages Needed
`streamlit-autorefresh` is NOT installed and NOT needed. `st.fragment(run_every=...)` provides
the same capability natively in Streamlit 1.44.0.

**Installation:** No new packages required.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/dashboard/
├── app.py                     # MODIFY: add Operations nav group + 4 new pages
├── db.py                      # No changes needed
├── charts.py                  # MODIFY: add ops chart builders
├── pages/
│   ├── 1_landing.py           # MODIFY: add operational health summary section
│   ├── 2_pipeline_monitor.py  # No changes
│   ├── 3_research_explorer.py # No changes
│   ├── 4_asset_stats.py       # No changes
│   ├── 5_experiments.py       # No changes
│   ├── 6_trading.py           # NEW: PnL, exposure, position table, trade log
│   ├── 7_risk_controls.py     # NEW: Kill switch status, limits, risk event history
│   ├── 8_drift_monitor.py     # NEW: Drift status, TE time series, equity overlay
│   └── 9_executor_status.py   # NEW: Executor run log, executor config summary
└── queries/
    ├── pipeline.py            # Existing
    ├── research.py            # Existing
    ├── asset_stats.py         # Existing
    ├── experiments.py         # Existing
    ├── trading.py             # NEW: positions, fills, pnl queries
    ├── risk.py                # NEW: dim_risk_state, dim_risk_limits, cmc_risk_events
    ├── drift.py               # NEW: cmc_drift_metrics, v_drift_summary
    └── executor.py            # NEW: cmc_executor_run_log, dim_executor_config
```

### Pattern 1: Auto-Refresh Fragment
**What:** Wrap the auto-updating content section of a page in `@st.fragment(run_every=...)`.
**When to use:** Any section that should poll for new data without user interaction.
**Example:**
```python
# Source: Streamlit 1.44.0 official API (verified locally)
AUTO_REFRESH_SECONDS = 900  # 15 minutes -- change this constant to adjust

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _live_positions_section(_engine) -> None:
    """Reloads positions data every AUTO_REFRESH_SECONDS."""
    positions_df = load_positions(_engine)
    st.dataframe(positions_df, use_container_width=True)
    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} min")

_live_positions_section(engine)
```

**Fragment constraint:** `st.sidebar` calls are NOT allowed inside a fragment. Sidebar controls
must live outside the fragment. Fragment widgets are limited to the main body area.

### Pattern 2: Query Module with cache_data
**What:** Per-page query module with `@st.cache_data(ttl=N)`, engine as `_engine` param.
**When to use:** All DB queries in dashboard pages — without the underscore, SQLAlchemy engine
is unhashable and cache will raise TypeError.
```python
# Source: existing queries/pipeline.py, queries/research.py patterns
@st.cache_data(ttl=120)  # 2 min for live operational data
def load_risk_state(_engine) -> dict:
    sql = text("""
        SELECT trading_state, halted_at, halted_reason, halted_by,
               drift_paused, drift_paused_at, drift_paused_reason,
               day_open_portfolio_value, last_day_open_date,
               cb_consecutive_losses, cb_breaker_tripped_at
        FROM dim_risk_state WHERE state_id = 1
    """)
    with _engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    if row is None:
        return {}
    return dict(row._mapping)
```

### Pattern 3: Alert Banner for Active Kill Switch / Drift Pause
**What:** Prominent st.error / st.warning banner at the top of ops pages when kill switch or
drift pause is active.
```python
# Pattern derived from CONTEXT.md decisions (prominent, impossible to miss)
risk_state = load_risk_state(engine)
if risk_state.get("trading_state") == "halted":
    st.error(
        f"KILL SWITCH ACTIVE -- Trading halted by {risk_state['halted_by']} "
        f"at {risk_state['halted_at']}. Reason: {risk_state['halted_reason']}"
    )
if risk_state.get("drift_paused"):
    st.warning(
        f"DRIFT PAUSE ACTIVE -- Signal processing paused at {risk_state['drift_paused_at']}. "
        f"Reason: {risk_state['drift_paused_reason']}"
    )
```

### Pattern 4: Stacked Two-Panel Plotly Chart (Equity + Drawdown)
**What:** Two subplots sharing x-axis -- cumulative PnL on top, drawdown on bottom.
```python
# Source: Plotly shared-x-axis subplot pattern, charts.py dark template established pattern
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def build_pnl_drawdown_chart(pnl_df: pd.DataFrame) -> go.Figure:
    """Two-panel equity + drawdown chart."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.65, 0.35], vertical_spacing=0.05)
    fig.add_trace(
        go.Scatter(x=pnl_df["ts"], y=pnl_df["cumulative_pnl"],
                   name="Cumulative PnL", line={"color": "rgb(0,200,100)"}),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(x=pnl_df["ts"], y=pnl_df["drawdown_pct"],
                   name="Drawdown %", fill="tozeroy",
                   line={"color": "rgb(220,50,50)"}),
        row=2, col=1
    )
    fig.update_layout(template="plotly_dark", ...)
    return fig
```

### Pattern 5: Progress Bar Proximity Gauge
**What:** st.progress() with labeled context for limit proximity.
```python
# Source: Streamlit API + CONTEXT.md requirements
daily_loss_consumed = 0.015   # from DB
daily_loss_cap = 0.030        # from dim_risk_limits
pct = min(daily_loss_consumed / daily_loss_cap, 1.0)
color = "normal" if pct < 0.7 else ("off" if pct < 0.9 else "normal")
st.progress(pct, text=f"Daily loss: {daily_loss_consumed:.1%} / {daily_loss_cap:.1%} cap")
```

### Navigation Pattern (app.py extension)
```python
# Source: existing app.py pattern -- extend the pages dict with Operations group
pages = {
    "Overview": [...],   # existing
    "Operations": [      # NEW group
        st.Page("pages/6_trading.py", title="Trading", icon=":material/candlestick_chart:"),
        st.Page("pages/7_risk_controls.py", title="Risk & Controls", icon=":material/security:"),
        st.Page("pages/8_drift_monitor.py", title="Drift Monitor", icon=":material/trending_up:"),
        st.Page("pages/9_executor_status.py", title="Executor Status", icon=":material/play_circle:"),
    ],
    "Monitor": [...],    # existing
    "Research": [...],   # existing
    "Analytics": [...],  # existing
    "Experiments": [...],# existing
}
```

### Anti-Patterns to Avoid
- **Calling `st.set_page_config()` in page files:** Only allowed once, only in `app.py`. All existing pages include `# do NOT call st.set_page_config() here` comments.
- **Passing engine without underscore to `@st.cache_data`:** Engine is unhashable. Always use `_engine` as param name.
- **Using `series.values` on tz-aware timestamps:** Returns tz-naive numpy datetime64. Use `.tolist()` or `.tz_localize("UTC")` on DatetimeIndex. (CRITICAL from MEMORY.md)
- **Calling `st.sidebar` inside `@st.fragment`:** Fragment constraint -- sidebar calls not supported inside fragments.
- **`st.rerun(scope="fragment")` during full-app rerun:** Raises StreamlitAPIException. The `run_every` param on `@st.fragment` handles periodic refresh without explicit `st.rerun()` calls.
- **Hardcoding 15-min refresh as a magic number:** Always define `AUTO_REFRESH_SECONDS = 900` at module level so it is one change to adjust.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB engine | New create_engine() calls | `from ta_lab2.dashboard.db import get_engine` | NullPool, connection URL already wired |
| Kill switch status read | Custom SQL | `from ta_lab2.risk.kill_switch import get_kill_switch_status` | Returns `KillSwitchStatus` dataclass, handles missing row |
| Risk limits load | Custom SQL | `RiskEngine._load_limits()` pattern or direct SQL on `dim_risk_limits` | Specificity ordering already implemented |
| Auto-refresh | `streamlit-autorefresh` package | `@st.fragment(run_every=N)` | Built into Streamlit 1.44.0, no extra dep |
| Chart dark theme | Custom layout | `fig.update_layout(template="plotly_dark")` | Established in charts.py for all figures |
| Chart download | Custom HTML export | `chart_download_button(fig, label, filename)` | Already in charts.py |
| Asset symbol lookup | New query | `from ta_lab2.dashboard.queries.research import load_asset_list` | Already cached at ttl=3600 |

**Key insight:** The risk and drift Python modules already implement the read logic
(`get_kill_switch_status`, `RiskEngine`, `DriftMetrics`). The dashboard queries should write
clean SQL directly (not import the heavy operational classes) but can reference the modules to
understand the exact column names and query patterns.

## DB Schema Reference

Exact column names for dashboard queries:

### cmc_positions (PK: asset_id, exchange, strategy_id -- Phase 45 migration extended PK)
```
asset_id, exchange, strategy_id,
quantity, avg_cost_basis,
realized_pnl, unrealized_pnl, unrealized_pnl_pct,
last_mark_price, last_mark_ts,
last_fill_id, last_updated, created_at
```
Note: `status` column does NOT exist in cmc_positions. Filter open positions by `quantity != 0`.
The `strategy_id` column was added by Phase 45 migration (default 0). The PK is
`(asset_id, exchange, strategy_id)`.

### v_cmc_positions_agg (view, updated in Phase 45 migration)
```
asset_id, exchange (='aggregate'), strategy_id (=0),
quantity, avg_cost_basis,
realized_pnl, unrealized_pnl,
last_mark_price, last_updated
```

### cmc_fills
```
fill_id (UUID PK), filled_at, created_at,
order_id (FK -> cmc_orders),
fill_qty, fill_price,
fee_amount, fee_currency,
side, exchange,
exchange_fill_id, lot_id
```

### cmc_orders
```
order_id (UUID PK), created_at, updated_at,
paper_order_uuid, signal_id,
asset_id, pair, exchange,
side, order_type, quantity, limit_price, stop_price,
time_in_force, expires_at,
status, filled_qty, remaining_qty, avg_fill_price,
environment, client_order_id, exchange_order_id
```
Status values: 'created', 'submitted', 'partial_fill', 'filled', 'cancelled', 'rejected', 'expired'

### dim_risk_state (single row, state_id=1)
```
state_id (=1),
trading_state ('active' | 'halted'),
halted_at, halted_reason, halted_by,
updated_at,
day_open_portfolio_value, last_day_open_date,
cb_consecutive_losses (TEXT JSON: {"asset_id:strategy_id": count}),
cb_breaker_tripped_at (TEXT JSON: {"asset_id:strategy_id": "iso-timestamp"}),
cb_portfolio_consecutive_losses, cb_portfolio_breaker_tripped_at,
-- Phase 47 additions:
drift_paused (BOOLEAN, DEFAULT FALSE),
drift_paused_at (TIMESTAMPTZ NULL),
drift_paused_reason (TEXT NULL),
drift_auto_escalate_after_days (INTEGER, DEFAULT 7)
```

### dim_risk_limits (portfolio-wide row: asset_id IS NULL AND strategy_id IS NULL)
```
limit_id, created_at, updated_at,
asset_id (NULL = portfolio-wide), strategy_id (NULL = all strategies),
max_position_pct (DEFAULT 0.15), max_portfolio_pct (DEFAULT 0.80),
daily_loss_pct_threshold (DEFAULT 0.03),
cb_consecutive_losses_n (DEFAULT 3), cb_loss_threshold_pct (DEFAULT 0.0),
cb_cooldown_hours (DEFAULT 24.0),
allow_overrides (DEFAULT TRUE),
-- Phase 47 additions:
drift_tracking_error_threshold_5d (DEFAULT 0.015),
drift_tracking_error_threshold_30d (DEFAULT 0.005),
drift_window_days (DEFAULT 5)
```

### cmc_risk_events (immutable audit log)
```
event_id (UUID PK), event_ts,
event_type (see CHECK constraint),
trigger_source ('manual' | 'daily_loss_stop' | 'circuit_breaker' | 'system' | 'drift_monitor'),
reason, operator,
asset_id (NULL = portfolio-wide), strategy_id,
order_id, override_id,
metadata (TEXT JSON)
```
event_type values: 'kill_switch_activated', 'kill_switch_disabled', 'position_cap_scaled',
'position_cap_blocked', 'daily_loss_stop_triggered', 'circuit_breaker_tripped',
'circuit_breaker_reset', 'override_created', 'override_applied', 'override_reverted',
'drift_pause_activated', 'drift_pause_disabled', 'drift_escalated'

### cmc_drift_metrics
```
metric_id (UUID PK), metric_date (DATE), created_at,
config_id, asset_id, signal_type,
pit_replay_run_id, cur_replay_run_id,
paper_trade_count, replay_trade_count, unmatched_paper, unmatched_replay,
paper_cumulative_pnl, replay_pit_cumulative_pnl, replay_cur_cumulative_pnl,
absolute_pnl_diff, data_revision_pnl_diff,
tracking_error_5d, tracking_error_30d,
paper_sharpe, replay_sharpe, sharpe_divergence,
threshold_breach (BOOLEAN), drift_pct_of_threshold,
attr_baseline_pnl, attr_fee_delta, attr_slippage_delta, attr_timing_delta,
attr_data_revision_delta, attr_sizing_delta, attr_regime_delta, attr_unexplained
```
UNIQUE constraint: (metric_date, config_id, asset_id)

### v_drift_summary (materialized view)
```
config_id, asset_id, signal_type,
days_monitored, breach_count,
avg_tracking_error_5d, max_tracking_error_5d,
avg_tracking_error_30d, max_tracking_error_30d,
avg_absolute_pnl_diff, avg_sharpe_divergence,
last_metric_date,
current_tracking_error_5d  -- from subquery on most recent row
```
UNIQUE INDEX: (config_id, asset_id, signal_type). Refresh with:
`REFRESH MATERIALIZED VIEW CONCURRENTLY public.v_drift_summary`

### dim_executor_config
```
config_id (SERIAL PK), created_at, updated_at,
config_name (UNIQUE), signal_type, signal_id,
is_active (BOOLEAN),
exchange, environment,
sizing_mode, position_fraction, max_position_fraction,
fill_price_mode, slippage_mode, slippage_base_bps, slippage_noise_sigma, volume_impact_factor,
rejection_rate, partial_fill_rate, execution_delay_bars,
last_processed_signal_ts,
cadence_hours,
-- Phase 47 addition:
fee_bps (NUMERIC, DEFAULT 0)
```

### cmc_executor_run_log
```
run_id (UUID PK), started_at, finished_at (NULL while running),
config_ids (TEXT JSON array, e.g. "[1,2]"),
dry_run (BOOLEAN), replay_historical (BOOLEAN),
status ('running' | 'success' | 'failed' | 'stale_signal'),
signals_read, orders_generated, fills_processed, skipped_no_delta,
error_message,
-- Phase 47 addition:
data_snapshot (JSONB NULL)
```

### dim_assets
```
id, symbol  (and more -- use for asset name lookup)
```

### cmc_price_bars_multi_tf
```
id, ts, tf, open, high, low, close, volume, ...
```
Use WHERE tf = '1D' AND id = :asset_id ORDER BY ts DESC LIMIT 1 for current price.

## Common Pitfalls

### Pitfall 1: cmc_positions has no `status` column
**What goes wrong:** Querying `WHERE status = 'open'` raises column-not-found error.
**Why it happens:** The reference DDL does not include a status column. Open positions are
identified by `quantity != 0`.
**How to avoid:** Filter with `WHERE quantity != 0` for active positions.
**Warning signs:** The `risk_engine._compute_portfolio_value()` method incorrectly uses
`WHERE status = 'open'` -- this is a bug in the risk engine, not a valid query pattern for
the dashboard.

### Pitfall 2: tz-aware timestamp .values returns tz-naive numpy datetime64
**What goes wrong:** `df["ts"].values` strips timezone. Plotly renders timestamps incorrectly.
**Why it happens:** Windows-specific pandas behavior (documented in MEMORY.md).
**How to avoid:** Use `df["ts"].tolist()` for Plotly x-axis, or ensure `pd.to_datetime(utc=True)`
when loading from DB.
**Warning signs:** Chart x-axis dates off by hours or showing "1970" values.

### Pitfall 3: st.fragment cannot write to st.sidebar
**What goes wrong:** `StreamlitAPIException: Calling st.sidebar is not supported in a fragment.`
**Why it happens:** Fragment restriction in Streamlit 1.44.0.
**How to avoid:** Put all sidebar widgets outside the `@st.fragment` decorated function.
Pass sidebar selections as parameters into the fragment function.

### Pitfall 4: Cache with non-underscore engine param raises TypeError
**What goes wrong:** `TypeError: unhashable type: 'sqlalchemy.engine.base.Engine'`
**Why it happens:** `@st.cache_data` tries to hash all arguments. Engine is unhashable.
**How to avoid:** Always name the engine parameter `_engine` (underscore prefix tells
`st.cache_data` to skip hashing it). This pattern is established in all existing query modules.

### Pitfall 5: v_drift_summary is a MATERIALIZED VIEW, not a regular view
**What goes wrong:** Querying v_drift_summary returns stale data if not refreshed.
**Why it happens:** Materialized views do not auto-refresh. Must run
`REFRESH MATERIALIZED VIEW CONCURRENTLY public.v_drift_summary` after DriftMonitor writes.
**How to avoid:** Dashboard should show `last_metric_date` to indicate data freshness. Add a
caption "Data as of {last_metric_date}" so users know when drift was last computed.

### Pitfall 6: cb_consecutive_losses and cb_breaker_tripped_at are TEXT JSON columns
**What goes wrong:** Treating them as integers/timestamps directly raises errors.
**Why it happens:** Stored as `TEXT` JSON objects `{"asset_id:strategy_id": value}` per
`risk_engine.py` design.
**How to avoid:** Parse with `json.loads(row["cb_consecutive_losses"] or "{}")` in queries.
For dashboard display, check if any value > 0 for summary status, or show raw JSON in expander.

### Pitfall 7: SQL files on Windows with UTF-8 box-drawing chars
**What goes wrong:** `UnicodeDecodeError: 'cp1252' codec can't decode byte`
**Why it happens:** SQL files use ASCII-only comments (per Phase 47 convention) but any future
SQL written on Windows may accidentally include UTF-8 box chars.
**How to avoid:** All reference SQL in this codebase uses `encoding='utf-8'` when opened.
Dashboard query modules use `text()` with inline strings -- no file reading needed.

### Pitfall 8: drift_paused is added by Phase 47 migration (not in original DDL file)
**What goes wrong:** Querying `drift_paused` fails if running against a database that has only
run up to Phase 46 migration.
**Why it happens:** Phase 47 migration `ac4cf1223ec7` adds the drift columns to `dim_risk_state`.
**How to avoid:** Dashboard queries that read `drift_paused` should handle `column not found`
gracefully if Phase 47 migration hasn't run. In practice, Phase 52 depends on Phase 47,
so this should not occur in the target environment.

## Code Examples

Verified patterns from existing codebase:

### Load Current Risk State
```python
# Source: kill_switch.py get_kill_switch_status() + dim_risk_state DDL
@st.cache_data(ttl=60)  # 60s -- risk state changes infrequently
def load_risk_state(_engine) -> dict:
    sql = text("""
        SELECT
            trading_state, halted_at, halted_reason, halted_by,
            drift_paused, drift_paused_at, drift_paused_reason,
            drift_auto_escalate_after_days,
            day_open_portfolio_value, last_day_open_date,
            cb_consecutive_losses, cb_breaker_tripped_at,
            updated_at
        FROM public.dim_risk_state
        WHERE state_id = 1
    """)
    with _engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    if row is None:
        return {}
    return dict(row._mapping)
```

### Load Portfolio-Wide Risk Limits
```python
# Source: dim_risk_limits DDL + risk_engine._load_limits() pattern
@st.cache_data(ttl=300)
def load_risk_limits(_engine) -> dict:
    sql = text("""
        SELECT
            max_position_pct, max_portfolio_pct,
            daily_loss_pct_threshold,
            cb_consecutive_losses_n, cb_cooldown_hours,
            drift_tracking_error_threshold_5d,
            drift_tracking_error_threshold_30d
        FROM public.dim_risk_limits
        WHERE asset_id IS NULL AND strategy_id IS NULL
        LIMIT 1
    """)
    with _engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    if row is None:
        return {}
    return dict(row._mapping)
```

### Load Open Positions with Asset Names
```python
# Source: cmc_positions DDL (quantity != 0 = open), dim_assets for names
@st.cache_data(ttl=120)
def load_open_positions(_engine) -> pd.DataFrame:
    """Returns positions where quantity != 0, joined to asset symbols and executor config."""
    sql = text("""
        SELECT
            a.symbol,
            p.asset_id,
            p.exchange,
            p.strategy_id,
            ec.config_name,
            ec.signal_type,
            p.quantity,
            p.avg_cost_basis,
            p.last_mark_price,
            p.unrealized_pnl,
            p.unrealized_pnl_pct,
            p.realized_pnl,
            p.last_updated,
            p.created_at AS entry_date
        FROM public.cmc_positions p
        JOIN public.dim_assets a ON a.id = p.asset_id
        LEFT JOIN public.dim_executor_config ec ON ec.config_id = p.strategy_id
        WHERE p.quantity != 0
          AND p.exchange = 'paper'
        ORDER BY a.symbol, p.strategy_id
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return df
    df["last_updated"] = pd.to_datetime(df["last_updated"], utc=True)
    df["entry_date"] = pd.to_datetime(df["entry_date"], utc=True)
    return df
```

### Load Last 20 Fills (Trade Log)
```python
# Source: cmc_fills + cmc_orders DDL, idx_fills_filled_at DESC index
@st.cache_data(ttl=120)
def load_recent_fills(_engine, limit: int = 20) -> pd.DataFrame:
    sql = text("""
        SELECT
            f.filled_at,
            a.symbol,
            f.side,
            f.fill_qty,
            f.fill_price,
            f.fee_amount,
            o.avg_fill_price AS order_avg_price,
            o.signal_id
        FROM public.cmc_fills f
        JOIN public.cmc_orders o ON o.order_id = f.order_id
        JOIN public.dim_assets a ON a.id = o.asset_id
        WHERE o.exchange = 'paper'
        ORDER BY f.filled_at DESC
        LIMIT :limit
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"limit": limit})
    if df.empty:
        return df
    df["filled_at"] = pd.to_datetime(df["filled_at"], utc=True)
    return df
```

### Load Drift Time Series for Chart
```python
# Source: cmc_drift_metrics DDL, idx_drift_metrics_config index
@st.cache_data(ttl=300)
def load_drift_timeseries(_engine, config_id: int, days: int = 30) -> pd.DataFrame:
    sql = text("""
        SELECT
            metric_date,
            tracking_error_5d,
            tracking_error_30d,
            paper_cumulative_pnl,
            replay_pit_cumulative_pnl,
            threshold_breach,
            drift_pct_of_threshold
        FROM public.cmc_drift_metrics
        WHERE config_id = :config_id
          AND metric_date >= CURRENT_DATE - :days
        ORDER BY metric_date ASC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"config_id": config_id, "days": days})
    if df.empty:
        return df
    df["metric_date"] = pd.to_datetime(df["metric_date"])
    return df
```

### Load Risk Events (Filterable)
```python
# Source: cmc_risk_events DDL, idx_risk_events_ts index
@st.cache_data(ttl=120)
def load_risk_events(_engine, days: int = 30,
                     event_type: str | None = None) -> pd.DataFrame:
    base_sql = """
        SELECT event_id, event_ts, event_type, trigger_source,
               reason, operator, asset_id, strategy_id, metadata
        FROM public.cmc_risk_events
        WHERE event_ts >= NOW() - INTERVAL :interval
    """
    params: dict = {"interval": f"{days} days"}
    if event_type:
        base_sql += " AND event_type = :event_type"
        params["event_type"] = event_type
    base_sql += " ORDER BY event_ts DESC LIMIT 200"
    with _engine.connect() as conn:
        df = pd.read_sql(text(base_sql), conn, params=params)
    if df.empty:
        return df
    df["event_ts"] = pd.to_datetime(df["event_ts"], utc=True)
    return df
```

### Compute Daily PnL from Fills (for Equity Curve)
```python
# Pattern: aggregate fills by day for portfolio P&L time series
# No cmc_pnl_daily table exists -- compute from fills or positions history
@st.cache_data(ttl=300)
def load_daily_pnl_series(_engine) -> pd.DataFrame:
    """Approximates daily P&L from fills (fill_qty * fill_price signed by side)."""
    sql = text("""
        SELECT
            DATE(f.filled_at AT TIME ZONE 'UTC') AS trade_date,
            SUM(
                CASE f.side
                    WHEN 'sell' THEN f.fill_qty * f.fill_price - f.fee_amount
                    WHEN 'buy'  THEN -(f.fill_qty * f.fill_price + f.fee_amount)
                END
            ) AS daily_realized_pnl
        FROM public.cmc_fills f
        JOIN public.cmc_orders o ON o.order_id = f.order_id
        WHERE o.exchange = 'paper'
        GROUP BY DATE(f.filled_at AT TIME ZONE 'UTC')
        ORDER BY trade_date ASC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["cumulative_pnl"] = df["daily_realized_pnl"].cumsum()
    return df
```

### Auto-Refresh Fragment Pattern (Complete)
```python
# Source: Streamlit 1.44.0 fragment API (verified locally)
AUTO_REFRESH_SECONDS = 900  # Module-level constant -- change here to adjust

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _positions_fragment(_engine) -> None:
    st.subheader("Current Positions")
    try:
        df = load_open_positions(_engine)
        if df.empty:
            st.info("No open positions.")
        else:
            st.dataframe(df, use_container_width=True)
        st.caption(
            f"Last updated: {pd.Timestamp.utcnow().strftime('%H:%M UTC')} | "
            f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} min"
        )
    except Exception as exc:
        st.error(f"Failed to load positions: {exc}")
```

## Cache TTL Recommendations

| Data | Recommended TTL | Reason |
|------|----------------|--------|
| Risk state (kill switch, drift pause) | 60s | Safety-critical; must see changes promptly |
| Positions (open + PnL) | 120s | Updates on each executor run (~daily) |
| Recent fills (trade log) | 120s | Same cadence as positions |
| Risk events table | 120s | Audit events are infrequent |
| Risk limits | 300s | Config changes rarely |
| Drift time series | 300s | Written daily by DriftMonitor |
| v_drift_summary | 300s | Materialized, refreshed daily |
| Executor run log | 120s | Updated each executor run |
| Executor config | 300s | Config changes rarely |
| Asset list / symbols | 3600s | Stable reference data |

## Landing Page Operational Health Summary

The existing landing page (`1_landing.py`) shows Pipeline Health and Research Highlights.
Add a third section "Operational Health" with traffic-light indicators for:

| Indicator | Green | Yellow | Red |
|-----------|-------|--------|-----|
| Kill Switch | trading_state='active' | N/A | trading_state='halted' |
| Drift Pause | drift_paused=FALSE | drift_paused=TRUE, < 3 days | drift_paused=TRUE, >= 3 days |
| Executor Last Run | finished_at < 26h ago | 26-48h ago | > 48h ago |
| Circuit Breaker | no active keys in cb_breaker_tripped_at | N/A | any key tripped |

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `streamlit-autorefresh` package | `@st.fragment(run_every=N)` | Native in Streamlit 1.33+, 1.44 installed |
| Separate Streamlit app for ops | Extend existing app.py | CONTEXT.md decision: one app, one place |

## Open Questions

1. **No cmc_pnl_daily table exists**
   - What we know: No dedicated daily PnL table. Unrealized PnL is in cmc_positions (mark-to-market).
   - What's unclear: The `last_mark_price` in cmc_positions may not be fresh (depends on mark-to-market running). For a daily dashboard this is acceptable, but the planner should note the limitation.
   - Recommendation: Use cmc_positions.unrealized_pnl + cmc_positions.realized_pnl for current PnL snapshot. Compute historical daily PnL from fills aggregation (see code example). Add a note in the UI about data freshness.

2. **Position table's "Regime Label" column**
   - What we know: CONTEXT.md specifies showing "Regime Label" in the position table. No regime_label column exists in cmc_positions or cmc_fills.
   - What's unclear: How to map a position's entry date to the regime label at that date.
   - Recommendation: JOIN cmc_positions to cmc_regimes on (asset_id, ts nearest entry_date, tf='1D') to get l2_label. This is a LEFT JOIN and may return NULL if regime data is absent. Show NULL as "N/A".

3. **Per-strategy PnL toggle**
   - What we know: CONTEXT.md says "portfolio aggregate default with toggle/expander to see per-strategy breakdown." strategy_id in cmc_positions maps to config_id in dim_executor_config.
   - What's unclear: Whether slippage calculation is correct for the daily PnL from fills.
   - Recommendation: Use `st.expander("Per-Strategy Breakdown")` to avoid extra page complexity.

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `src/ta_lab2/dashboard/` -- app.py, db.py, charts.py, all 5 pages, all 4 query modules
- SQL DDL: `sql/trading/082-085.sql`, `sql/risk/090-092.sql`, `sql/executor/088-089.sql`, `sql/drift/094-095.sql`
- Alembic migrations: `225bf8646f03_paper_trade_executor.py` (strategy_id in cmc_positions PK)
- Phase 47 SUMMARY (47-01): Confirms all 8 schema changes applied including drift_paused columns
- Python source: `src/ta_lab2/risk/kill_switch.py`, `src/ta_lab2/risk/risk_engine.py`, `src/ta_lab2/drift/drift_metrics.py`
- Streamlit 1.44.0 (installed, verified): `st.fragment(run_every=...)` with `func` and `run_every` params

### Secondary (MEDIUM confidence)
- `.streamlit/config.toml`: `fileWatcherType = "poll"` (Windows requirement), `base = "dark"` theme

### Tertiary (LOW confidence)
- Daily PnL from fills aggregation pattern: computed from schema analysis; no existing query to validate against

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all verified from installed packages and existing code
- DB schema: HIGH -- read directly from DDL files and verified against migration summaries
- Architecture: HIGH -- derived from existing codebase patterns
- Pitfalls: HIGH -- documented bugs in code (cmc_positions status column) and MEMORY.md warnings
- Auto-refresh pattern: HIGH -- verified st.fragment API locally on installed Streamlit 1.44.0

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable stack, 30 days)
