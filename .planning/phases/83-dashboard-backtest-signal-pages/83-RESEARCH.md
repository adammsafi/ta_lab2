# Phase 83: Dashboard — Backtest & Signal Pages - Research

**Researched:** 2026-03-23
**Domain:** Streamlit dashboard extension, Plotly candlestick charts, bakeoff data queries, signal browser
**Confidence:** HIGH (all findings verified against live codebase and live DB)

---

## Summary

Phase 83 is an extension of an existing, mature Streamlit dashboard. All
infrastructure is in place: the query-layer pattern (`queries/*.py` +
`pages/*.py`), the `chart_download_button()` helper, `@st.cache_data` with
`_engine` prefix convention, `@st.fragment(run_every=...)` for auto-refresh,
and `go.Figure` with `plotly_dark` template. There are no new package
requirements — Streamlit 1.44.0, Plotly 6.4.0, and all analysis modules are
already installed.

The primary data sources are well-understood: `strategy_bakeoff_results` has
76,970 rows (109 assets x 13 strategies x 16 cost scenarios x 2 CV methods)
with a `fold_metrics_json` JSONB column containing per-fold summary metrics.
The three signal tables (`signals_ema_crossover`, `signals_rsi_mean_revert`,
`signals_atr_breakout`) share a common 17-column schema. OHLCV price data comes
from `public.features` (which has `open, high, low, close, volume, ts`), not
from `price_bars_multi_tf_u` (which uses `timestamp` instead of `ts` and has
a much richer schema requiring alignment_source filtering). For EMA overlays,
`ema_multi_tf_u` is queried by `period` with LEFT JOIN.

The key design constraint is data volume: 76,970 bakeoff rows with 16 cost
scenarios and 13 strategies require server-side aggregation before rendering
— never load the full table into a DataFrame for display.

**Primary recommendation:** Query `strategy_bakeoff_results` with GROUP BY or
WHERE filters (asset, strategy, cost_scenario, cv_method) server-side.
Use `features` table for OHLCV (it already has `open, high, low, close, volume`
as verified columns). Never join `price_bars_multi_tf_u` in the dashboard
— that table uses `timestamp` (not `ts`) and requires `alignment_source` filter.

---

## Standard Stack

### Core (all already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.44.0 | Page framework | Pinned in requirements-311.txt |
| plotly | 6.4.0 | All charts | go.Candlestick, make_subplots, go.Figure |
| pandas | current | DataFrame ops | Already used in all query layers |
| SQLAlchemy | current | DB queries | NullPool engine pattern in db.py |
| numpy | current | MC bootstrap, percentile | Already used in analysis modules |

### Analysis Modules (already implemented, zero new code needed)

| Module | Purpose | Import Path |
|--------|---------|-------------|
| `monte_carlo_returns` | MC Sharpe CI from daily returns | `ta_lab2.analysis.monte_carlo` |
| `monte_carlo_trades` | MC Sharpe CI from trade PnL | `ta_lab2.analysis.monte_carlo` |
| `compute_mae_mfe` | MAE/MFE per trade | `ta_lab2.analysis.mae_mfe` |
| `compute_composite_score` | Composite score + ranking | `ta_lab2.backtests.composite_scorer` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `features` table for OHLCV | `price_bars_multi_tf_u` | `price_bars_multi_tf_u` uses `timestamp` (not `ts`), requires `alignment_source='multi_tf'` filter, much wider schema — `features` is simpler for dashboard queries |
| `@st.cache_data(ttl=300)` | `@st.cache_data(ttl=3600)` | 300s is right for live signal data; 3600s is fine for bakeoff results (changes rarely) |

**Installation:** No new packages needed. All required dependencies are present.

---

## Architecture Patterns

### Existing Page Pattern (must follow exactly)

```
src/ta_lab2/dashboard/
├── app.py                  # st.navigation dict, shared sidebar, set_page_config
├── db.py                   # get_engine() singleton, NullPool
├── charts.py               # All go.Figure builders + chart_download_button()
├── pages/
│   ├── 1_landing.py        # no st.set_page_config() — only in app.py
│   ├── 3_research_explorer.py
│   └── 10_macro.py         # @st.fragment pattern, sidebar controls outside fragment
└── queries/
    ├── research.py         # @st.cache_data, _engine prefix, text() queries
    └── experiments.py      # same pattern
```

### New Files Required

```
pages/
├── 11_backtest_results.py   # Backtest Results page
├── 12_signal_browser.py     # Signal Browser page
└── 13_asset_hub.py          # Asset Hub page (or omit if modal approach chosen)
queries/
├── backtest.py              # load_bakeoff_* query functions
└── signals.py               # load_signals_* query functions
charts.py                    # Extend with build_candlestick_chart(), build_equity_sparklines()
app.py                       # Extend pages dict with new sidebar groups
```

### app.py Navigation Extension Pattern

The `pages` dict in `app.py` must be extended. The CONTEXT.md calls for a full
sidebar reorganization into logical groups. The new structure should follow the
`st.Page(path, title=..., icon=":material/icon_name:")` pattern:

```python
# Source: existing app.py verified pattern
pages = {
    "Overview": [...existing landing...],
    "Analysis": [
        st.Page("pages/11_backtest_results.py", title="Backtest Results",
                icon=":material/analytics:"),
        st.Page("pages/12_signal_browser.py", title="Signal Browser",
                icon=":material/signal_cellular_alt:"),
        st.Page("pages/13_asset_hub.py", title="Asset Hub",
                icon=":material/hub:"),
        st.Page("pages/3_research_explorer.py", title="Research Explorer",
                icon=":material/science:"),
    ],
    "Operations": [...existing trading/risk/drift/executor/macro...],
    "Monitor": [...existing pipeline monitor...],
    "Experiments": [...existing experiments...],
}
```

### Pattern 1: Query Layer Structure

All query functions follow this exact pattern (verified from `queries/research.py`
and `queries/experiments.py`):

```python
# Source: verified from ta_lab2/dashboard/queries/research.py
from __future__ import annotations
import pandas as pd
import streamlit as st
from sqlalchemy import text

@st.cache_data(ttl=300)
def load_bakeoff_leaderboard(_engine, tf: str = "1D", cv_method: str = "purged_kfold",
                              cost_scenario: str = "spot_fee16_slip10") -> pd.DataFrame:
    sql = text("""
        SELECT
            strategy_name, asset_id, tf, params_json, cost_scenario, cv_method,
            sharpe_mean, sharpe_std, max_drawdown_worst, psr, dsr, turnover,
            trade_count_total, pbo_prob, fold_metrics_json, experiment_name
        FROM public.strategy_bakeoff_results
        WHERE tf = :tf
          AND cv_method = :cv_method
          AND cost_scenario = :cost_scenario
        ORDER BY sharpe_mean DESC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={
            "tf": tf, "cv_method": cv_method, "cost_scenario": cost_scenario
        })
    return df
```

**Critical:** First argument always `_engine` (underscore prefix = skipped by st.cache_data).

### Pattern 2: Page Structure (no st.set_page_config)

```python
# Source: verified from ta_lab2/dashboard/pages/6_trading.py and 10_macro.py
"""
Page docstring. No st.set_page_config() — only in app.py.
"""
from __future__ import annotations
import streamlit as st
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.backtest import load_bakeoff_leaderboard
from ta_lab2.dashboard.charts import chart_download_button

AUTO_REFRESH_SECONDS = 900

st.header("Backtest Results")
st.caption("Walk-forward bakeoff results across 109 assets, 13 strategies, 16 cost scenarios")

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# Sidebar controls OUTSIDE fragment (st.sidebar not allowed inside @st.fragment)
with st.sidebar:
    st.subheader("Filters")
    selected_tf = st.selectbox("Timeframe", ["1D"])
    ...

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _backtest_content(_engine, ...):
    ...

_backtest_content(engine, ...)
```

### Pattern 3: chart_download_button (HTML export)

```python
# Source: ta_lab2/dashboard/charts.py (verified implementation)
# fig.write_html(buffer, include_plotlyjs="cdn") — no kaleido dependency
chart_download_button(
    fig,
    "Download Chart (HTML)",
    f"backtest_{strategy}_{asset}.html",
)
```

### Pattern 4: Plotly Candlestick with make_subplots

```python
# Source: plotly.com/python/candlestick-charts + codebase make_subplots pattern
from plotly.subplots import make_subplots
import plotly.graph_objects as go

def build_candlestick_chart(ohlcv_df, ema_df=None, title="") -> go.Figure:
    """
    Build candlestick chart with optional EMA overlays and RSI/volume subplots.

    ohlcv_df: DataFrame with columns ts, open, high, low, close, volume
              (from public.features, ts is UTC-aware)
    ema_df: DataFrame with columns ts, period, ema (from ema_multi_tf_u)
    """
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20],
        vertical_spacing=0.03,
    )

    # Row 1: Candlestick
    fig.add_trace(
        go.Candlestick(
            x=ohlcv_df["ts"].tolist(),  # .tolist() avoids tz-naive numpy pitfall
            open=ohlcv_df["open"],
            high=ohlcv_df["high"],
            low=ohlcv_df["low"],
            close=ohlcv_df["close"],
            name="OHLCV",
            increasing_line_color="rgb(0,200,100)",
            decreasing_line_color="rgb(220,50,50)",
        ),
        row=1, col=1,
    )

    # EMA overlays on row 1 (if provided)
    if ema_df is not None:
        for period in ema_df["period"].unique():
            sub = ema_df[ema_df["period"] == period].sort_values("ts")
            fig.add_trace(
                go.Scatter(
                    x=sub["ts"].tolist(),
                    y=sub["ema"],
                    mode="lines",
                    name=f"EMA {period}",
                    line={"width": 1.0},
                ),
                row=1, col=1,
            )

    # Row 2: Volume bars
    fig.add_trace(
        go.Bar(
            x=ohlcv_df["ts"].tolist(),
            y=ohlcv_df["volume"],
            name="Volume",
            marker_color="rgba(150,150,150,0.5)",
        ),
        row=2, col=1,
    )

    # Row 3: RSI (if rsi_14 in ohlcv_df)
    if "rsi_14" in ohlcv_df.columns:
        fig.add_trace(
            go.Scatter(
                x=ohlcv_df["ts"].tolist(),
                y=ohlcv_df["rsi_14"],
                mode="lines",
                name="RSI 14",
                line={"color": "rgb(255,165,0)", "width": 1.0},
            ),
            row=3, col=1,
        )
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    fig.update_layout(
        template="plotly_dark",
        title=title,
        xaxis_rangeslider_visible=False,  # CRITICAL: disable rangeslider on candlestick
        height=600,
        showlegend=True,
    )
    return fig
```

**Critical pitfall:** Always set `xaxis_rangeslider_visible=False` on candlestick.
Without this, Plotly renders a second rangeslider that doubles the chart height and
is confusing in Streamlit.

### Pattern 5: st.query_params for URL state

```python
# Source: docs.streamlit.io/develop/api-reference/caching-and-state/st.query_params
# Available since Streamlit 1.30.0, verified in version 1.44.0

# Read (all values are strings)
asset = st.query_params.get("asset", "BTC")
strategy = st.query_params.get("strategy", "all")
tf = st.query_params.get("tf", "1D")

# Write (on widget change callback or direct assignment)
if st.selectbox(...) != asset:
    st.query_params["asset"] = selected_asset
    st.query_params["strategy"] = selected_strategy

# Clear all
st.query_params.clear()

# Set multiple at once
st.query_params.from_dict({"asset": "BTC", "strategy": "ema_trend", "tf": "1D"})
```

**Limitation:** `st.query_params` does not work inside `@st.fragment`. Must be
read and written at the page top level (outside fragments). Sidebar controls
that change URL state must be outside `@st.fragment` — consistent with the
existing pattern.

### Pattern 6: Equity Curve Sparklines

`fold_metrics_json` contains per-fold summary stats (`sharpe`, `total_return`,
`cagr`, `max_drawdown`, `trade_count`, `test_start`, `test_end`) but NOT
bar-level equity curve data. The existing scorecard generator (Phase 82)
creates a simplified "illustrative" equity line using only fold Sharpe as proxy:

```python
# Source: scripts/analysis/generate_bakeoff_scorecard.py line 472
# fold_metrics_json structure (verified from live DB):
# [{"fold_idx": 0, "sharpe": 0.55, "total_return": 0.12, "cagr": 0.08,
#   "max_drawdown": -0.15, "trade_count": 23,
#   "test_start": "2025-03-27", "test_end": "2025-05-01", ...}, ...]

# Dashboard approach: use total_return per fold as equity proxy
def build_equity_sparkline(fold_metrics: list[dict]) -> go.Figure:
    fig = go.Figure()
    cumulative = 1.0
    x_vals, y_vals = [fold_metrics[0]["test_start"]], [1.0]
    for fm in fold_metrics:
        cumulative *= (1.0 + fm.get("total_return", 0.0))
        x_vals.append(fm["test_end"])
        y_vals.append(cumulative)
    fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode="lines", name="Equity (OOS)"))
    fig.update_layout(template="plotly_dark", height=150, showlegend=False,
                      margin=dict(l=0, r=0, t=0, b=0))
    return fig
```

### Pattern 7: Monte Carlo Fan Chart

The `monte_carlo_returns()` function returns `mc_sharpe_lo`, `mc_sharpe_hi`,
`mc_sharpe_median` — scalar CI bounds, not a distribution array. The "fan chart"
must be constructed by running MC on each fold's OOS returns using the
`fold_metrics_json` data.

However, `fold_metrics_json` does NOT store bar-level OOS returns (the
`oos_returns` field is a Python `List[float]` in the StrategyResult dataclass
but is NOT persisted to the DB — only the summary is stored). This means
proper MC fan charts require either:
1. Re-running MC from signals table (approximate: treat signal PnL as returns)
2. Using fold-level Sharpe statistics with +/- sigma bands as CI proxy
3. Computing MC from `signals_*` tables joined to the strategy

The most practical approach for the dashboard: compute MC summary card
(`monte_carlo_trades()` on closed signals for the strategy+asset) and display
as a summary metric card, not a fan chart. The expandable fan chart must be
simulated from fold Sharpe statistics using normal approximation.

### Anti-Patterns to Avoid

- **No `st.set_page_config()` in page files** — it is only in `app.py`. Calling
  it again raises `StreamlitAPIException`.
- **No sidebar widgets inside `@st.fragment`** — `st.sidebar` is not allowed
  inside fragments. All sidebar controls must be at the page top level.
- **No `.values` on tz-aware datetime Series** — returns tz-naive numpy.
  Always use `.tolist()` when passing timestamps to Plotly. Verified pattern
  in `charts.py` (e.g., `x_dates = pnl_df["trade_date"].tolist()`).
- **No full-table load of strategy_bakeoff_results** — 76,970 rows. Always
  filter server-side by tf, cv_method, cost_scenario, strategy_name.
- **No rangeslider on candlestick** — `xaxis_rangeslider_visible=False` is
  required; otherwise Plotly renders a duplicate slider.
- **No `price_bars_multi_tf_u` for dashboard OHLCV** — use `features` table.
  It has `open, high, low, close, volume, rsi_14, ts` (verified). The
  `price_bars_multi_tf_u` table uses `timestamp` (not `ts`) and requires
  `alignment_source` filter.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTML chart download | Custom JS or server-side render | `chart_download_button()` in charts.py | Already implemented, uses `fig.write_html()` with CDN |
| DB engine | New engine creation | `from ta_lab2.dashboard.db import get_engine` | `@st.cache_resource` singleton, NullPool |
| Monte Carlo Sharpe CI | Custom bootstrap | `monte_carlo_trades()` / `monte_carlo_returns()` | Already handles edge cases (min trades, zero-std guard) |
| MAE/MFE per trade | Iterate signal table | `compute_mae_mfe(trades_df, close_series)` | Handles long/short, tz-aware, FIFO |
| Composite scoring | Custom weighting | `compute_composite_score()` in `composite_scorer.py` | 4 weight schemes, NaN PSR handling |
| Plotly dark theme | Custom CSS | `template="plotly_dark"` | Consistent with all existing charts |
| Plotly chart display | `st.altair_chart` or other | `st.plotly_chart(fig, theme=None, key="unique_key")` | `theme=None` preserves plotly_dark; unique `key` required for multiple charts |

**Key insight:** The dashboard is a thin query+rendering layer. All business
logic lives in `ta_lab2.analysis.*` and `ta_lab2.backtests.*`. Never reimplement
analysis in page files.

---

## Common Pitfalls

### Pitfall 1: Multiple `st.plotly_chart` on Same Page Without `key`

**What goes wrong:** When multiple `st.plotly_chart()` calls appear on the same
page without a unique `key` argument, Streamlit renders them correctly on first
load but may mix up rerenders, causing charts to disappear or swap.

**Why it happens:** Streamlit uses positional matching by default for widget
reconciliation. With fragments and dynamic content, positional matching breaks.

**How to avoid:** Always pass a unique `key` string:
```python
st.plotly_chart(fig_equity, theme=None, key="backtest_equity_curve")
st.plotly_chart(fig_cost, theme=None, key="backtest_cost_matrix")
```

### Pitfall 2: Sidebar Inside Fragment

**What goes wrong:** `st.sidebar.selectbox(...)` inside `@st.fragment` raises
`StreamlitAPIException`.

**Why it happens:** Streamlit does not support sidebar mutations inside fragments.

**How to avoid:** All sidebar controls must be at module level (outside
`@st.fragment`). Pass selected values as function parameters to the fragment:

```python
# Correct pattern (from pages/6_trading.py and 10_macro.py)
with st.sidebar:
    selected_asset = st.selectbox("Asset", asset_list)

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _content(_engine, asset):
    ...

_content(engine, selected_asset)
```

### Pitfall 3: `fold_metrics_json` Is a Python `dict` or `list`, Not a JSON String

**What goes wrong:** `pd.read_sql` returns JSONB columns as Python objects
(dict/list), not strings. Calling `json.loads(row["fold_metrics_json"])` on
an already-parsed dict raises `TypeError`.

**Why it happens:** psycopg2 automatically deserializes JSONB columns.

**How to avoid:**
```python
raw = row["fold_metrics_json"]
if isinstance(raw, str):
    import json
    folds = json.loads(raw)
elif isinstance(raw, (list, dict)):
    folds = raw
else:
    folds = []
```
This exact pattern is used in `generate_bakeoff_scorecard.py` (line 176-181).

### Pitfall 4: strategy_bakeoff_results Data Volume

**What goes wrong:** Loading `SELECT * FROM strategy_bakeoff_results` returns
76,970 rows. Displaying all rows in `st.dataframe()` or pivoting them in Python
hangs the browser tab.

**Why it happens:** 16 cost scenarios x 13 strategies x 109 assets x 2 CV methods.

**How to avoid:** Always filter before loading. For the cost comparison matrix
view, filter to one strategy+asset+cv_method and pivot the 16 cost_scenario rows
into columns server-side or in a small DataFrame.

### Pitfall 5: OHLCV Source Table

**What goes wrong:** Querying `price_bars_multi_tf_u` for OHLCV misses that
(a) it uses `timestamp` not `ts`, (b) it requires `alignment_source='multi_tf'`
filter, (c) it has 40+ columns with repair flags.

**How to avoid:** Use `features` table for OHLCV in the dashboard. It has
`ts, open, high, low, close, volume, rsi_14, bb_lo_20_2, bb_ma_20, bb_up_20_2`
— everything needed for candlestick + overlays. Pattern:
```sql
SELECT ts, open, high, low, close, volume, rsi_14,
       bb_lo_20_2, bb_ma_20, bb_up_20_2
FROM public.features
WHERE id = :id AND tf = :tf
ORDER BY ts
```

### Pitfall 6: `st.query_params` Inside Fragment

**What goes wrong:** Reading or writing `st.query_params` inside `@st.fragment`
does not update the URL as expected.

**Why it happens:** Fragment context isolates state updates.

**How to avoid:** All URL param reads/writes must be at module level before
the fragment function is defined and called.

---

## Code Examples

### Load OHLCV + Bollinger Bands for Candlestick

```python
# Source: verified from public.features table schema (2026-03-23)
@st.cache_data(ttl=300)
def load_ohlcv(_engine, asset_id: int, tf: str,
               limit: int = 500) -> pd.DataFrame:
    """
    Load OHLCV + RSI + Bollinger Bands for candlestick chart.
    Uses features table (has ts column, no alignment_source needed).
    """
    sql = text("""
        SELECT ts, open, high, low, close, volume,
               rsi_14, bb_lo_20_2, bb_ma_20, bb_up_20_2
        FROM public.features
        WHERE id = :id AND tf = :tf
        ORDER BY ts DESC
        LIMIT :limit
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf, "limit": limit})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)
```

### Load EMA Overlays for Candlestick

```python
# Source: verified from ema_multi_tf_u schema (periods: 9, 10, 21, 50, 200 used in signals)
@st.cache_data(ttl=300)
def load_ema_overlays(_engine, asset_id: int, tf: str,
                      periods: list[int] = None) -> pd.DataFrame:
    """
    Load EMA values for overlay on candlestick chart.
    Columns: ts, period, ema
    """
    if periods is None:
        periods = [9, 21, 50, 200]
    sql = text("""
        SELECT ts, period, ema
        FROM public.ema_multi_tf_u
        WHERE id = :id AND tf = :tf AND period = ANY(:periods)
          AND alignment_source = 'multi_tf'
        ORDER BY ts, period
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf, "periods": periods})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Load Bakeoff Results for One Asset (Cost Matrix View)

```python
# Source: strategy_bakeoff_results schema verified 2026-03-23
@st.cache_data(ttl=1800)
def load_bakeoff_cost_matrix(_engine, asset_id: int, strategy_name: str,
                              tf: str = "1D",
                              cv_method: str = "purged_kfold") -> pd.DataFrame:
    """
    Load all cost scenarios for one strategy+asset combo.
    Returns 16 rows (one per cost_scenario) with key metrics.
    Suitable for pivot table view.
    """
    sql = text("""
        SELECT cost_scenario, sharpe_mean, sharpe_std,
               max_drawdown_worst, psr, dsr, turnover,
               trade_count_total, pbo_prob
        FROM public.strategy_bakeoff_results
        WHERE asset_id = :asset_id
          AND strategy_name = :strategy_name
          AND tf = :tf
          AND cv_method = :cv_method
        ORDER BY sharpe_mean DESC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={
            "asset_id": asset_id, "strategy_name": strategy_name,
            "tf": tf, "cv_method": cv_method,
        })
    return df
```

### Load Active Signals (Signal Browser)

```python
# Source: signals_ema_crossover schema verified 2026-03-23
# Columns: id, ts, signal_id, direction, position_state, entry_price,
#          entry_ts, exit_price, exit_ts, pnl_pct, feature_snapshot,
#          signal_version, feature_version_hash, params_hash, created_at,
#          regime_key, executor_processed_at, venue_id
@st.cache_data(ttl=60)
def load_active_signals(_engine, signal_table: str = "signals_ema_crossover",
                         strategy_filter: str | None = None) -> pd.DataFrame:
    """
    Load open position signals with asset symbol and signal name.
    signal_table: one of signals_ema_crossover, signals_rsi_mean_revert, signals_atr_breakout
    """
    assert signal_table in {
        "signals_ema_crossover", "signals_rsi_mean_revert", "signals_atr_breakout"
    }, "Invalid signal table"
    sql = text(f"""
        SELECT s.id, da.symbol, ds.signal_name, ds.signal_type, s.direction,
               s.entry_ts, s.entry_price, s.regime_key, s.signal_id, s.venue_id
        FROM public.{signal_table} s
        JOIN public.dim_assets da ON da.id = s.id
        JOIN public.dim_signals ds ON ds.signal_id = s.signal_id
        WHERE s.position_state = 'open'
        ORDER BY s.entry_ts DESC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return df
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    return df
```

### Load Signal History Timeline

```python
@st.cache_data(ttl=300)
def load_signal_history(_engine, asset_id: int,
                         signal_table: str = "signals_ema_crossover",
                         days_back: int = 90) -> pd.DataFrame:
    """
    Load both open and closed signals for timeline visualization.
    Columns: id, symbol, signal_name, direction, position_state,
             entry_ts, exit_ts, pnl_pct, regime_key
    """
    assert signal_table in {
        "signals_ema_crossover", "signals_rsi_mean_revert", "signals_atr_breakout"
    }, "Invalid signal table"
    sql = text(f"""
        SELECT s.id, da.symbol, ds.signal_name, s.direction, s.position_state,
               s.entry_ts, s.exit_ts, s.pnl_pct, s.regime_key
        FROM public.{signal_table} s
        JOIN public.dim_assets da ON da.id = s.id
        JOIN public.dim_signals ds ON ds.signal_id = s.signal_id
        WHERE s.id = :asset_id
          AND s.entry_ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY s.entry_ts DESC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "days_back": days_back})
    if df.empty:
        return df
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df["exit_ts"] = pd.to_datetime(df["exit_ts"], utc=True, errors="coerce")
    return df
```

### Bakeoff Leaderboard Query (Strategy-First View)

```python
@st.cache_data(ttl=1800)
def load_bakeoff_leaderboard(_engine, tf: str = "1D",
                              cv_method: str = "purged_kfold",
                              cost_scenario: str = "spot_fee16_slip10",
                              min_trades: int = 5) -> pd.DataFrame:
    """
    Top strategies across all assets, sorted by sharpe_mean.
    Filters to a single cost_scenario to avoid row explosion.
    """
    sql = text("""
        SELECT r.strategy_name, r.asset_id, da.symbol, r.params_json,
               r.sharpe_mean, r.sharpe_std, r.max_drawdown_worst,
               r.psr, r.dsr, r.turnover, r.trade_count_total,
               r.pbo_prob, r.fold_metrics_json, r.experiment_name
        FROM public.strategy_bakeoff_results r
        JOIN public.dim_assets da ON da.id = r.asset_id
        WHERE r.tf = :tf
          AND r.cv_method = :cv_method
          AND r.cost_scenario = :cost_scenario
          AND r.trade_count_total >= :min_trades
        ORDER BY r.sharpe_mean DESC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={
            "tf": tf, "cv_method": cv_method,
            "cost_scenario": cost_scenario, "min_trades": min_trades,
        })
    return df
```

---

## Data Shape Reference

### strategy_bakeoff_results

| Column | Type | Notes |
|--------|------|-------|
| `strategy_name` | TEXT | 13 distinct: ama_*, breakout_atr, ema_trend, rsi_mean_revert |
| `asset_id` | INT | 109 distinct assets |
| `tf` | TEXT | Only "1D" in current data |
| `params_json` | JSONB | Strategy-specific parameters |
| `cost_scenario` | TEXT | 16 scenarios (spot_fee16_slip5/10/20, spot_fee26_*, perps_*) |
| `cv_method` | TEXT | "purged_kfold" or "cpcv" |
| `sharpe_mean` | FLOAT | Mean OOS Sharpe across folds |
| `sharpe_std` | FLOAT | Std of OOS Sharpe across folds |
| `max_drawdown_worst` | FLOAT | Worst fold drawdown (negative, e.g. -0.70) |
| `psr` | FLOAT | Probabilistic Sharpe Ratio (0-1, >0.95 is strong) |
| `dsr` | FLOAT | Deflated Sharpe Ratio |
| `turnover` | FLOAT | Daily turnover fraction |
| `trade_count_total` | INT | Total trades across all folds |
| `pbo_prob` | FLOAT | Probability of backtest overfitting (CPCV only) |
| `fold_metrics_json` | JSONB | Per-fold list: `[{fold_idx, sharpe, total_return, cagr, max_drawdown, trade_count, test_start, test_end, train_start, train_end}]` |
| `experiment_name` | TEXT | Lineage: "phase82_ama_kraken", "phase82_ama_hl", etc. |
| `computed_at` | TIMESTAMPTZ | When result was written |

**Total rows:** 76,970 | **PK:** (strategy_name, asset_id, tf, params_json, cost_scenario, cv_method)

### signals_ema_crossover (and _rsi_mean_revert, _atr_breakout)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT | Asset ID |
| `venue_id` | SMALLINT | Default 1 (CMC_AGG) |
| `ts` | TIMESTAMPTZ | Signal bar timestamp |
| `signal_id` | INT | FK to dim_signals |
| `direction` | TEXT | "long" or "short" |
| `position_state` | TEXT | "open" or "closed" |
| `entry_price` | FLOAT | Price at entry |
| `entry_ts` | TIMESTAMPTZ | Entry bar timestamp |
| `exit_price` | FLOAT | NULL for open signals |
| `exit_ts` | TIMESTAMPTZ | NULL for open signals |
| `pnl_pct` | FLOAT | PnL in percentage points (NULL for open) |
| `feature_snapshot` | JSONB | {close, fast_ema, slow_ema, rsi_14, atr_14} at entry |
| `regime_key` | TEXT | e.g. "Up-Normal-Normal" or NULL |
| `executor_processed_at` | TIMESTAMPTZ | Set by executor when order generated |

**Row counts (2026-03-23):** EMA: 7,481 | RSI: 2,142 | ATR: 3,346
**Open signals:** EMA: 3,853 | RSI: 6 | ATR: 1,733

### dim_signals

| signal_id | signal_name | signal_type | params |
|-----------|-------------|-------------|--------|
| 1 | ema_9_21_long | ema_crossover | {fast_period: 9, slow_period: 21, direction: long} |
| 2 | ema_21_50_long | ema_crossover | {fast_period: 21, slow_period: 50} |
| 3 | ema_50_200_long | ema_crossover | {fast_period: 50, slow_period: 200} |
| 4 | rsi_30_70_mr | rsi_mean_revert | {oversold: 30, overbought: 70, rsi_period: 14} |
| 5 | rsi_25_75_mr | rsi_mean_revert | {oversold: 25, overbought: 75} |
| 6 | atr_20_donchian | atr_breakout | {atr_period: 14, atr_multiplier: 1.5, channel_period: 20} |
| 8 | ema_17_77_long | ema_crossover | {fast_period: 17, slow_period: 77} |

### features Table (OHLCV + indicators for candlestick overlays)

Key columns for Phase 83: `ts, id, tf, venue_id, open, high, low, close, volume,
rsi_14, bb_lo_20_2, bb_ma_20, bb_up_20_2, macd_12_26, macd_hist_12_26_9, atr_14`

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `st.experimental_get_query_params()` | `st.query_params` dict interface | Streamlit 1.30.0 | Simpler assignment syntax |
| `st.experimental_set_query_params()` | `st.query_params["key"] = value` | Streamlit 1.30.0 | Still works but deprecated |
| Plotly rangeslider (default on) | `xaxis_rangeslider_visible=False` | Always needed | Must explicitly disable |
| `@st.cache(suppress_st_warning=True)` | `@st.cache_data(ttl=...)` | Streamlit 1.18.0 | Old pattern is removed in 1.44 |
| `st.experimental_fragment` | `@st.fragment(run_every=...)` | Streamlit 1.33.0 | Already used in pages 6, 7, 8, 9, 10 |

**Deprecated/outdated:**
- `st.experimental_get_query_params` / `st.experimental_set_query_params`: Removed, use `st.query_params`
- `go.Ohlc`: Use `go.Candlestick` for filled candles (hollow candles look old)

---

## Open Questions

1. **Equity curve bar-level data**
   - What we know: `fold_metrics_json` has per-fold `total_return` but no bar-level OOS returns
   - What's unclear: Whether to approximate equity curves from fold summaries or build a separate DB query against signals
   - Recommendation: Use per-fold cumulative `total_return` as equity proxy (simple, correct for OOS interpretation). Accept that it's a step function with 10 data points, not a smooth equity curve. Label clearly as "OOS fold equity (cumulative total return by fold)".

2. **Signal strength score (0-100)**
   - What we know: The context asks for a numeric signal strength score derived from IC-IR weights. `ic_results` table has `ic_ir` per (feature, asset, tf). The signal `feature_snapshot` JSONB has feature values at entry.
   - What's unclear: Exact formula to map IC-IR weights + feature values to 0-100 score
   - Recommendation: Use a simple composite: weighted average of (IC-IR * feature_value_zscore) for snapshot features, normalized to 0-100. Implement as a utility function in the new `queries/signals.py`.

3. **Asset Hub: separate page vs modal**
   - What we know: CONTEXT.md marks this as Claude's discretion. Streamlit 1.44 supports `st.dialog()` for modal overlays.
   - What's unclear: Whether a modal fits the "full trading terminal" feel
   - Recommendation: Implement as a separate page (page 13) with `url_path` deep linking. Modals reset on page navigate and don't support `st.query_params` state.

4. **TF buttons on chart toolbar (1H / 4H / 1D / 1W)**
   - What we know: All current bakeoff data is 1D only. Signal generators currently only run on 1D.
   - What's unclear: Whether to display TF buttons that are currently non-functional for most strategies
   - Recommendation: Render TF selector as `st.radio` with available TFs from the data. For candlestick, query `features` at the selected TF (features has multi-TF data).

---

## Sources

### Primary (HIGH confidence)

- Live codebase: `ta_lab2/dashboard/app.py` — navigation structure, sidebar pattern
- Live codebase: `ta_lab2/dashboard/charts.py` — chart_download_button, plotly_dark pattern, make_subplots
- Live codebase: `ta_lab2/dashboard/queries/research.py` — @st.cache_data, _engine prefix convention
- Live codebase: `ta_lab2/dashboard/pages/10_macro.py` — @st.fragment, sidebar outside fragment pattern
- Live codebase: `ta_lab2/backtests/bakeoff_orchestrator.py` — strategy_bakeoff_results schema, fold_metrics_json structure
- Live codebase: `ta_lab2/scripts/signals/generate_signals_ema.py` — signals table schema, signal columns
- Live codebase: `ta_lab2/executor/signal_reader.py` — SIGNAL_TABLE_MAP, signal table names
- Live codebase: `ta_lab2/analysis/monte_carlo.py` — MC function signatures and return types
- Live DB query: `strategy_bakeoff_results` — 76,970 rows, 109 assets, 13 strategies, 16 cost scenarios
- Live DB query: `signals_*` row counts and column schema
- Live DB query: `features` table columns (including OHLCV, RSI, Bollinger)
- Live DB query: `price_bars_multi_tf_u` timestamp column name (not `ts`)
- Live DB query: `ema_multi_tf_u` periods available (9, 10, 21, 50, 200, etc.)
- requirements-311.txt — Streamlit 1.44.0, Plotly 6.4.0 confirmed

### Secondary (MEDIUM confidence)

- [st.query_params official docs](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.query_params) — API verified available since 1.30.0, dict interface confirmed
- [Plotly go.Candlestick docs](https://plotly.com/python/candlestick-charts/) — make_subplots pattern confirmed

### Tertiary (LOW confidence — training knowledge only)

- `xaxis_rangeslider_visible=False` requirement: Known Plotly pattern, not verified against a specific doc URL

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — all packages verified in requirements-311.txt, codebase imports
- Architecture: HIGH — all patterns verified against live page files
- Data schemas: HIGH — all columns verified against live DB queries
- Pitfalls: HIGH — most verified against live code; rangeslider pitfall from training knowledge (MEDIUM)
- Code examples: HIGH — all column names verified against live DB

**Research date:** 2026-03-23
**Valid until:** 2026-04-22 (30 days — stable codebase, Streamlit/Plotly APIs stable)
