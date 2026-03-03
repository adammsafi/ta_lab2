# Phase 72: Macro Observability - Research

**Researched:** 2026-03-03
**Domain:** Streamlit dashboard extension, Plotly charting, Telegram alerting, DriftMonitor attribution
**Confidence:** HIGH (all findings from direct codebase inspection)

---

## Summary

Phase 72 adds macro observability on top of a well-established dashboard, alerting, and drift
infrastructure. The codebase already has complete implementations of every dependency: the
Streamlit multipage dashboard (pages 1-9), the Telegram alerting module, the DriftMonitor
6-source attribution, the traffic-light pipeline monitor, and the macro regime tables from
Phase 67. This research maps exactly how each existing system works so the planner can add
Phase 72's components without deviation from established patterns.

The work splits into four clearly bounded areas: (1) a new Streamlit page file
`pages/10_macro.py` registered in `app.py`, (2) a new `notifications/macro_alerts.py`
module called from a new `scripts/macro/run_macro_alerts.py` script, (3) an extension to
`drift/attribution.py` that adds a macro regime dimension comparison step, and (4) new
query functions under `dashboard/queries/macro.py` that feed all three display surfaces.
A new `dashboard/charts.py` chart function handles the stacked-band timeline.

**Primary recommendation:** Follow the existing Streamlit fragment + `@st.cache_data(ttl=300)`
+ NullPool engine singleton pattern exactly. Add a page 10 file; register it in the "Operations"
group in `app.py`. Build charts in `charts.py` using `go.Figure` + `plotly_dark` template.
Alert via `telegram.send_alert()` with throttle state persisted to a new
`cmc_macro_alert_log` table.

---

## Standard Stack

All libraries are already installed; no new dependencies required.

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | installed | Dashboard pages and fragments | Project standard, app.py entry point |
| plotly.graph_objects | installed | All dashboard charts | Project standard, `charts.py` uses go.Figure exclusively |
| plotly.subplots | installed | make_subplots for stacked panels | Already used in `build_pnl_drawdown_chart` |
| sqlalchemy | installed | DB queries with text() | Project standard |
| pandas | installed | DataFrames for all chart data | Project standard |

### Supporting (already in project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| ta_lab2.notifications.telegram | local | Send Telegram alerts | All macro transition alerts |
| ta_lab2.dashboard.db.get_engine | local | NullPool engine singleton | Every dashboard query module |
| ta_lab2.drift.attribution.DriftAttributor | local | Attribution engine to extend | Adding macro attribution source |

**Installation:** None required. All dependencies are already present.

---

## Architecture Patterns

### Dashboard Page Structure (exact pattern from existing pages)

```
src/ta_lab2/dashboard/
    app.py                    # Add new page registration here
    charts.py                 # Add new chart functions here
    pages/
        10_macro.py           # New page file (follows pages/8_drift_monitor.py pattern)
    queries/
        macro.py              # New query module (follows queries/drift.py pattern)
```

### app.py Registration Pattern

The existing `app.py` uses `st.navigation(pages)` with grouped pages. The new Macro page
joins the "Operations" group alongside Trading, Risk, Drift Monitor, and Executor Status.

```python
# Source: src/ta_lab2/dashboard/app.py (lines 49-70)
"Operations": [
    st.Page("pages/6_trading.py", title="Trading", icon=":material/candlestick_chart:"),
    st.Page("pages/7_risk_controls.py", title="Risk & Controls", icon=":material/security:"),
    st.Page("pages/8_drift_monitor.py", title="Drift Monitor", icon=":material/trending_up:"),
    st.Page("pages/9_executor_status.py", title="Executor Status", icon=":material/play_circle:"),
    # Add here:
    st.Page("pages/10_macro.py", title="Macro", icon=":material/public:"),
],
```

### Page File Pattern (from pages/8_drift_monitor.py)

Every page follows this exact structure:
1. Module docstring with `# do NOT call st.set_page_config() here`
2. `from ta_lab2.dashboard.db import get_engine`
3. `from ta_lab2.dashboard.queries.<module> import ...`
4. `AUTO_REFRESH_SECONDS = 900` constant
5. Alert banners OUTSIDE fragment (always visible, no cache delay)
6. Sidebar controls OUTSIDE fragment (`st.sidebar` not allowed in fragments)
7. `@st.fragment(run_every=AUTO_REFRESH_SECONDS)` decorated function for all data content
8. Call the fragment function at end of file

```python
# Source: src/ta_lab2/dashboard/pages/8_drift_monitor.py (structure)
"""Macro page -- Macro Regime State, FRED Health, and Regime Timeline.

do NOT call st.set_page_config() here -- that is in app.py.
"""
from __future__ import annotations
import streamlit as st
from ta_lab2.dashboard.charts import (
    build_macro_regime_bands_chart,   # new function
    chart_download_button,
)
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.macro import (
    load_current_macro_regime,
    load_macro_regime_history,
    load_fred_freshness,
    load_portfolio_pnl_for_overlay,
)

AUTO_REFRESH_SECONDS = 900

st.header("Macro Regime")
st.caption("Current macro regime state, FRED data health, and regime timeline")

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# Alert banners (outside fragment -- no cache delay)
# ... regime state banners here ...

# Sidebar controls (outside fragment)
with st.sidebar:
    st.subheader("Controls")
    overlay_asset = st.selectbox("Timeline Overlay", ["Portfolio PnL", "BTC", "ETH"])
    history_days = st.select_slider("History (days)", options=[30, 90, 180, 365], value=90)

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _macro_content(_engine, overlay_asset, history_days):
    # All data content here

_macro_content(engine, overlay_asset, history_days)
```

### Query Module Pattern (from queries/pipeline.py)

```python
# Source: src/ta_lab2/dashboard/queries/pipeline.py (lines 27-57)
@st.cache_data(ttl=300)
def load_current_macro_regime(_engine) -> pd.DataFrame:
    """Load latest cmc_macro_regimes row for active profile.

    Columns: date, profile, monetary_policy, liquidity, risk_appetite,
             carry, regime_key, macro_state, ingested_at
    """
    sql = text(
        """
        SELECT date, profile, monetary_policy, liquidity,
               risk_appetite, carry, regime_key, macro_state, ingested_at
        FROM cmc_macro_regimes
        WHERE profile = 'default'
        ORDER BY date DESC
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df
```

### Plotly Chart Pattern (from charts.py)

All chart functions:
- Accept DataFrames and return `go.Figure`
- Apply `template="plotly_dark"` always
- Handle empty data with `fig.add_annotation(text="No data available", ...)`
- Use `go.Figure()` not `px.*` helpers
- Colors from established palette: green `rgb(0,200,100)`, red `rgb(220,50,50)`, grey `rgb(150,150,150)`, orange `rgb(255,165,0)`, blue `rgb(100,149,237)`

```python
# Source: src/ta_lab2/dashboard/charts.py (lines 32-43, 540-616)
# Existing regime color constants
REGIME_COLORS: dict[str, str] = {
    "Up": "rgba(0, 200, 100, 0.15)",
    "Down": "rgba(220, 50, 50, 0.15)",
    "Sideways": "rgba(150, 150, 150, 0.12)",
}

REGIME_BAR_COLORS: dict[str, str] = {
    "Up": "rgb(0, 200, 100)",
    "Down": "rgb(220, 50, 50)",
    "Sideways": "rgb(150, 150, 150)",
}
```

For the macro regime timeline with stacked per-dimension bands, `make_subplots` with
shared x-axis is the right approach (same pattern as `build_pnl_drawdown_chart`):

```python
# Source: src/ta_lab2/dashboard/charts.py (lines 558-616) -- make_subplots pattern
from plotly.subplots import make_subplots

def build_macro_regime_bands_chart(
    regime_df: pd.DataFrame,    # cmc_macro_regimes history
    overlay_df: pd.DataFrame,   # PnL or price series
    overlay_label: str = "Portfolio PnL",
) -> go.Figure:
    """
    Build macro regime timeline with 4 stacked dimension bands + PnL overlay.

    5-panel layout (shared x-axis):
      Panel 1 (40%): PnL/price line (overlay_df)
      Panel 2 (15%): monetary_policy vrect bands
      Panel 3 (15%): liquidity vrect bands
      Panel 4 (15%): risk_appetite vrect bands
      Panel 5 (15%): carry vrect bands
    """
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        row_heights=[0.40, 0.15, 0.15, 0.15, 0.15],
        vertical_spacing=0.02,
        subplot_titles=["", "Monetary", "Liquidity", "Risk Appetite", "Carry"],
    )
    # ... build per vrect for each dimension using fig.add_vrect() ...
    fig.update_layout(template="plotly_dark", height=700)
    return fig
```

### Traffic-Light Pattern (from pipeline_monitor.py)

```python
# Source: src/ta_lab2/dashboard/pages/2_pipeline_monitor.py (lines 41-49)
def _traffic_light(staleness_hours: float | None) -> str:
    """Return a coloured circle string based on staleness thresholds."""
    if staleness_hours is None:
        return ":red_circle:"
    if staleness_hours < 24:
        return ":large_green_circle:"
    if staleness_hours < 72:
        return ":large_orange_circle:"
    return ":red_circle:"
```

For FRED freshness, thresholds must be per-frequency. The existing pattern uses a single
function. The FRED extension needs a `_fred_traffic_light(series_id, staleness_hours)` that
looks up the frequency for the series and applies frequency-specific thresholds.

### Telegram Alert Pattern (from telegram.py + risk_engine.py)

```python
# Source: src/ta_lab2/notifications/telegram.py (lines 93-115)
from ta_lab2.notifications.telegram import send_alert

send_alert(
    title="Macro Regime Transition",
    message="<b>Liquidity:</b> Contracting -> Strongly_Contracting\n\n"
            "<b>Composite:</b> Hiking-Strongly_Contracting-Neutral-Stable\n"
            "<b>Macro State:</b> cautious\n\n"
            "<b>Metrics:</b>\n"
            "  VIX: 28.4 | HY OAS z: +1.8 | Net Liq: -$180B",
    severity="warning",   # "critical" for risk-off/carry unwind
)
```

The `send_alert` function formats with emoji prefix (red circle for critical, yellow for
warning, blue for info) and wraps title in `<b>` tags. Parse mode is HTML.

Graceful degradation: every consumer wraps in `try/except` and checks `is_configured()`
before calling, exactly as `risk_engine.py` and `drift_pause.py` do.

### DriftAttributor Extension Pattern (from attribution.py)

The existing `DriftAttributor` has 7 sequential OAT steps (0-6). Step 6 is "regime_delta"
(crypto regime difference). Adding a 7th step (macro regime) extends the chain:

```python
# Source: src/ta_lab2/drift/attribution.py (lines 72-120, 299-310)
# AttributionResult dataclass has these fields:
# baseline_pnl, fee_delta, slippage_delta, timing_delta,
# data_revision_delta, sizing_delta, regime_delta, unexplained_residual,
# total_explained_pnl, paper_pnl

# Adding macro_regime_delta requires:
# 1. Add field to AttributionResult dataclass
# 2. Add Step 7 in run_attribution()
# 3. Update total_explained_pnl calculation
# 4. Update dashboard display in pages/8_drift_monitor.py
```

The macro drift attribution step compares the macro_state from cmc_macro_regimes for the
paper trading period against the macro_state for the backtest training period. If they
differ (e.g., paper was in "cautious" but backtest trained on "favorable"), that explains
part of the performance gap. This is a label comparison, not a replay, so it does not
require running the backtester.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telegram HTTP calls | Custom requests code | `telegram.send_alert()` | Already handles auth, formatting, graceful degradation, parse_mode |
| DB engine singleton | `create_engine()` in page | `get_engine()` from `dashboard.db` | NullPool + st.cache_resource already configured |
| Chart export | kaleido/png | `chart_download_button(fig, ...)` | Already writes HTML via fig.write_html(), CDN-hosted Plotly JS |
| Cache invalidation | Manual TTL logic | `@st.cache_data(ttl=300)` | Project standard, works with `_engine` underscore prefix |
| Staleness calculation | Manual datetime math | `pd.Timestamp.utcnow().tz_localize("UTC") - df["last_refresh"]` | Exact pattern from `queries/pipeline.py` |
| vrect bands for regimes | Custom shapes | `fig.add_vrect(x0, x1, fillcolor, ...)` | Already used in `build_regime_price_chart()` in charts.py |

---

## Common Pitfalls

### Pitfall 1: st.set_page_config() in page files
**What goes wrong:** `StreamlitAPIException: set_page_config() can only be called once per app,
and must be called as the first Streamlit command in your script.`
**Why it happens:** The page file runs inside the app framework; app.py already called it.
**How to avoid:** Comment `# do NOT call st.set_page_config() here` at top of every page file.
Every existing page has this comment. Never add `st.set_page_config()` in a page.
**Warning signs:** Any page file that imports streamlit and calls `st.set_page_config`.

### Pitfall 2: st.sidebar inside @st.fragment
**What goes wrong:** `StreamlitAPIException: st.sidebar can't be used inside a fragment.`
**Why it happens:** Fragments cannot contain sidebar widgets.
**How to avoid:** All sidebar controls must be OUTSIDE the fragment function, exactly as in
`pages/8_drift_monitor.py` (lines 82-108) where sidebar controls precede the `@st.fragment`.
**Warning signs:** Any `st.sidebar.*` call inside an `@st.fragment` decorated function.

### Pitfall 3: Pandas tz-aware datetime .values pitfall
**What goes wrong:** `tz_localize` or tz-naive numpy causes Plotly to silently misalign x-axes.
**Why it happens:** `.values` on a tz-aware Series returns tz-naive numpy. Plotly treats it as UTC.
**How to avoid:** Always use `.tolist()` for datetime columns passed to Plotly x-axis, exactly as
`build_pnl_drawdown_chart` does (`x_dates = pnl_df["trade_date"].tolist()`).
**Warning signs:** Code doing `df["date"].values` before passing to go.Scatter x=.

### Pitfall 4: Hashing unhashable engine in cache
**What goes wrong:** `UnhashableTypeError` when st.cache_data tries to hash the SQLAlchemy engine.
**Why it happens:** Engines are not hashable. st.cache_data must skip them.
**How to avoid:** Always prefix engine parameter with underscore in query functions:
`def load_current_macro_regime(_engine) -> pd.DataFrame`. See all existing functions in
`queries/pipeline.py`, `queries/drift.py`, etc.
**Warning signs:** Query function whose first parameter is `engine` without underscore.

### Pitfall 5: Telegram alert spam on noisy transitions
**What goes wrong:** Multiple alerts fire per hour for regime states that oscillate.
**Why it happens:** Macro hysteresis filtering is at the classification layer, but if the
classifier runs frequently and the regime is near a threshold, transitions can still fire repeatedly.
**How to avoid:** Persist the last-alerted (dimension, label) pair with a timestamp in a
`cmc_macro_alert_log` table. Check this table before sending each alert. Only alert if:
(a) dimension label has actually changed, AND (b) at least N hours have passed since the
last alert for that dimension. Macro regimes are naturally sticky (hysteresis already applied),
so a 4-hour minimum between alerts per dimension is conservative enough.
**Warning signs:** Alert sending code that does not check a throttle store.

### Pitfall 6: fred.series_values query without schema prefix
**What goes wrong:** `relation "series_values" does not exist` because the table is in the
`fred` schema, not `public`.
**Why it happens:** SQLAlchemy text() queries against PostgreSQL default to the `public` schema.
**How to avoid:** Always use fully qualified `fred.series_values`, `fred.fred_macro_features`,
`fred.sync_log`. See `fred_reader.py` line 119: `FROM fred.series_values`.

### Pitfall 7: DriftAttributor AttributionResult is a frozen dataclass
**What goes wrong:** `dataclasses.FrozenInstanceError` when trying to add a field after creation.
**Why it happens:** `@dataclass(frozen=True)` is used (attribution.py line 72).
**How to avoid:** Adding `macro_regime_delta` requires updating the dataclass definition AND
all construction sites (`_zeros_with_paper_pnl`, `run_attribution` return statement). Check
all usages of `AttributionResult` before modifying. The dashboard display in
`pages/8_drift_monitor.py` also hard-codes the column names -- update that too.

---

## Code Examples

### Query: Current Macro Regime
```python
# Source: regime_classifier.py pattern applied to dashboard query
@st.cache_data(ttl=300)
def load_current_macro_regime(_engine) -> pd.DataFrame:
    sql = text(
        """
        SELECT date, profile, monetary_policy, liquidity,
               risk_appetite, carry, regime_key, macro_state, ingested_at
        FROM public.cmc_macro_regimes
        WHERE profile = 'default'
        ORDER BY date DESC
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        return pd.read_sql(sql, conn)
```

### Query: FRED Series Freshness (per-series, per-frequency)
```python
# Source: fred_reader.py SERIES_TO_LOAD list + pipeline.py staleness pattern
@st.cache_data(ttl=300)
def load_fred_freshness(_engine) -> pd.DataFrame:
    sql = text(
        """
        SELECT
            series_id,
            COUNT(*) AS n_rows,
            MAX(date)::text AS latest_date,
            CURRENT_DATE - MAX(date) AS days_stale
        FROM fred.series_values
        GROUP BY series_id
        ORDER BY series_id
        """
    )
    with _engine.connect() as conn:
        return pd.read_sql(sql, conn)
```

### Traffic Light for FRED (per-frequency thresholds)
```python
# FRED series frequencies (from fred_reader.py SERIES_TO_LOAD comments)
_FRED_FREQUENCY: dict[str, str] = {
    "WALCL": "weekly",     "WTREGEN": "weekly",   "NFCI": "weekly",
    "RRPONTSYD": "daily",  "DFF": "daily",         "DGS10": "daily",
    "T10Y2Y": "daily",     "VIXCLS": "daily",      "DTWEXBGS": "daily",
    "ECBDFR": "daily",     "BAMLH0A0HYM2": "daily","DEXJPUS": "daily",
    "DFEDTARU": "daily",   "DFEDTARL": "daily",
    "IRSTCI01JPM156N": "monthly", "IRLTLT01JPM156N": "monthly",
    "M2SL": "monthly",     "CPIAUCSL": "monthly",
}

# Stale threshold in days (beyond which traffic light turns red)
_FRESH_THRESHOLD_DAYS: dict[str, int] = {
    "daily": 3,      # Daily series: stale after 3 days (weekend buffer)
    "weekly": 10,    # Weekly series: stale after 10 days
    "monthly": 45,   # Monthly series: stale after 45 days
}

def _fred_traffic_light(series_id: str, days_stale: int | None) -> str:
    freq = _FRED_FREQUENCY.get(series_id, "daily")
    threshold = _FRESH_THRESHOLD_DAYS[freq]
    if days_stale is None:
        return ":red_circle:"
    if days_stale <= threshold:
        return ":large_green_circle:"
    if days_stale <= threshold * 2:
        return ":large_orange_circle:"
    return ":red_circle:"
```

### Telegram Macro Transition Alert
```python
# Source: telegram.py send_alert() pattern + drift_pause.py best-effort pattern
def send_macro_transition_alert(
    dimension: str,
    old_label: str,
    new_label: str,
    composite_key: str,
    macro_state: str,
    metrics: dict,
    engine,
) -> bool:
    """Send macro regime transition alert via Telegram (best-effort)."""
    try:
        from ta_lab2.notifications.telegram import send_alert, is_configured
        if not is_configured():
            return False

        # Emphasize risk-off and carry unwind transitions
        is_adverse = new_label in ("RiskOff", "Unwind", "Strongly_Contracting", "Hiking")
        severity = "critical" if is_adverse else "warning"

        dim_display = dimension.replace("_", " ").title()
        metric_lines = "\n".join(
            f"  {k}: {v}" for k, v in metrics.items() if v is not None
        )

        message = (
            f"<b>{dim_display}:</b> {old_label} -> <b>{new_label}</b>\n\n"
            f"<b>Composite Key:</b> {composite_key}\n"
            f"<b>Macro State:</b> {macro_state}\n\n"
            f"<b>Driving Metrics:</b>\n{metric_lines}"
        )

        return send_alert(
            title="Macro Regime Transition",
            message=message,
            severity=severity,
        )
    except Exception:
        return False
```

### Macro Drift Attribution Step (extends DriftAttributor)
```python
# Source: drift/attribution.py Step 6 (regime_delta) pattern -- adding Step 7
def _compute_macro_regime_delta(
    self,
    paper_start: str,
    paper_end: str,
) -> tuple[str | None, str | None]:
    """
    Compare macro regime (macro_state) for paper period vs backtest period.

    Returns (paper_state, backtest_state). Both None if data unavailable.
    This is a LABEL comparison, not a replay -- no SignalBacktester needed.
    """
    sql = text(
        """
        SELECT
            (SELECT macro_state FROM cmc_macro_regimes
             WHERE date BETWEEN :start AND :end
             AND profile = 'default'
             GROUP BY macro_state ORDER BY COUNT(*) DESC LIMIT 1) AS paper_state,
            (SELECT macro_state FROM cmc_macro_regimes
             WHERE date < :start
             AND profile = 'default'
             ORDER BY date DESC LIMIT 1) AS backtest_state
        """
    )
    # Returns the modal macro_state during the paper period
    # vs the state immediately before the paper period (backtest context)
    with self._engine.connect() as conn:
        row = conn.execute(sql, {"start": paper_start, "end": paper_end}).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]
```

### Pipeline Monitor FRED Row Addition
```python
# Extend pages/2_pipeline_monitor.py TABLE_FAMILIES dict with FRED entry
# Source: pages/2_pipeline_monitor.py lines 28-38 (TABLE_FAMILIES pattern)

# In the FRED freshness section, add a single summary row:
fred_max_stale = fred_freshness_df["days_stale"].max()
fred_indicator = _traffic_light(
    fred_max_stale * 24 if fred_max_stale is not None else None
)
label = f"{fred_indicator}  FRED Series ({len(fred_freshness_df)} series)"
with st.expander(label, expanded=False):
    st.dataframe(fred_freshness_df, use_container_width=True)
```

---

## Data Schema Reference

### cmc_macro_regimes (Phase 67)
```
PK: (date DATE, profile TEXT default 'default')
Columns:
  monetary_policy  TEXT  -- Hiking / Holding / Cutting
  liquidity        TEXT  -- Strongly_Expanding / Expanding / Neutral /
                           Contracting / Strongly_Contracting
  risk_appetite    TEXT  -- RiskOff / Neutral / RiskOn
  carry            TEXT  -- Unwind / Stress / Stable
  regime_key       TEXT  -- "Cutting-Expanding-RiskOn-Stable" (dash-joined)
  macro_state      TEXT  -- favorable / constructive / neutral / cautious / adverse
  regime_version_hash TEXT
  ingested_at      TIMESTAMPTZ
Indexes:
  idx_cmc_macro_regimes_date (date DESC)
  idx_cmc_macro_regimes_state (macro_state)
```

### cmc_macro_hysteresis_state (Phase 67)
```
PK: (profile TEXT, dimension TEXT)
  dimension values: monetary_policy, liquidity, risk_appetite, carry
  current_label TEXT, pending_label TEXT, pending_count INT, updated_at TIMESTAMPTZ
```

### fred.fred_macro_features (Phase 65 + 66)
```
PK: (date DATE) in fred schema
Raw columns (18 series, forward-filled):
  walcl, wtregen, rrpontsyd, dff, dgs10, t10y2y, vixcls, dtwexbgs,
  ecbdfr, irstci01jpm156n, irltlt01jpm156n,
  bamlh0a0hym2, nfci, m2sl, dexjpus, dfedtaru, dfedtarl, cpiaucsl
Derived columns:
  net_liquidity, us_jp_rate_spread, us_ecb_rate_spread, us_jp_10y_spread,
  yc_slope_change_5d, vix_regime, dtwexbgs_5d_change, dtwexbgs_20d_change,
  hy_oas_level, hy_oas_5d_change, hy_oas_30d_zscore, nfci_level, nfci_4wk_direction,
  m2_yoy_pct, dexjpus_level, dexjpus_5d_pct_change, dexjpus_20d_vol,
  dexjpus_daily_zscore, net_liquidity_365d_zscore, net_liquidity_trend,
  dfedtaru, dfedtarl, fed_regime_structure, fed_regime_trajectory,
  carry_momentum, cpi_surprise_proxy, target_mid, target_spread
Staleness tracking:
  days_since_walcl INT, days_since_wtregen INT
```

### fred.series_values (raw FRED data)
```
PK: (series_id TEXT, date DATE)
  value FLOAT
18 series from SERIES_TO_LOAD in fred_reader.py
Frequencies (from SERIES_TO_LOAD comments):
  Daily: RRPONTSYD, DFF, DGS10, T10Y2Y, VIXCLS, DTWEXBGS, ECBDFR,
         BAMLH0A0HYM2, DEXJPUS, DFEDTARU, DFEDTARL
  Weekly: WALCL, WTREGEN, NFCI
  Monthly: IRSTCI01JPM156N, IRLTLT01JPM156N, M2SL, CPIAUCSL
```

### cmc_drift_metrics (existing, for attribution extension)
```
PK: (metric_date DATE, config_id INT, asset_id INT)
Attribution columns already present:
  attr_fee_delta, attr_slippage_delta, attr_timing_delta,
  attr_data_revision_delta, attr_sizing_delta, attr_regime_delta,
  attr_unexplained_delta
-- Adding: attr_macro_regime_delta (requires Alembic migration)
```

### Attribution Result (existing dataclass, must extend)
```python
# Source: drift/attribution.py lines 72-120
# frozen=True -- all fields must be declared in the dataclass definition
# Current fields: baseline_pnl, fee_delta, slippage_delta, timing_delta,
#                 data_revision_delta, sizing_delta, regime_delta,
#                 unexplained_residual, total_explained_pnl, paper_pnl
# Must add: macro_regime_delta (str comparison result stored separately)
```

---

## Existing Color Scheme for Macro State Risk Levels

The dashboard's existing REGIME_COLORS and REGIME_BAR_COLORS map three crypto regime states.
For macro's five states (favorable/constructive/neutral/cautious/adverse), extend this palette:

```python
# Proposed macro state colors -- follows existing green/grey/red pattern
MACRO_STATE_COLORS: dict[str, str] = {
    "favorable":    "rgba(0, 200, 100, 0.20)",   # bright green -- matches Up regime
    "constructive": "rgba(100, 200, 100, 0.15)",  # softer green
    "neutral":      "rgba(150, 150, 150, 0.12)",  # grey -- matches Sideways
    "cautious":     "rgba(255, 165, 0, 0.15)",    # orange -- matches TE 5d line color
    "adverse":      "rgba(220, 50, 50, 0.20)",    # red -- matches Down regime
}

MACRO_STATE_SOLID: dict[str, str] = {
    "favorable":    "rgb(0, 200, 100)",
    "constructive": "rgb(100, 200, 100)",
    "neutral":      "rgb(150, 150, 150)",
    "cautious":     "rgb(255, 165, 0)",
    "adverse":      "rgb(220, 50, 50)",
}
```

For per-dimension labels, a separate color map per dimension works best (4 color families,
one per dimension). Use the same green/grey/orange/red scale within each family.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No macro observability | Phase 72 adds it | Phase 72 | First macro visibility layer |
| 6-source drift attribution | 7-source (adding macro) | Phase 72 | Explains macro-driven drift |
| Crypto-only pipeline monitor | FRED freshness added | Phase 72 | Unified data health view |
| Single-composite regime band | 4-layer stacked dimension bands | Phase 72 | More granular timeline |

**Deprecated/outdated:**
- The `run_attribution()` call signature in `DriftAttributor` will gain a new macro comparison
  step but is NOT a breaking change to callers if added as a separate helper method called
  inside `run_attribution()` rather than as a new parameter.

---

## Open Questions

1. **Does Phase 71 (risk gates) add any DB columns that Phase 72 needs to read?**
   - What we know: Phase 71 integrates macro risk gates. It may add a `macro_gate_active` flag
     to `dim_risk_state` or similar.
   - What's unclear: Phase 71 plans were not present in the planning directory at research time.
   - Recommendation: Before writing the alert banners in `10_macro.py`, check whether
     `dim_risk_state` has a macro gate column. If so, show it as a banner (same pattern as
     drift_paused and trading_state in existing pages).

2. **Does `cmc_drift_metrics` have an `attr_macro_regime_delta` column?**
   - What we know: The column is not present in the Phase 47 migration. Must be added.
   - What's unclear: Whether Phase 71 already added it as part of risk gate integration.
   - Recommendation: Check Alembic head before writing the migration for Phase 72.

3. **FRED sync_log table schema for freshness monitoring**
   - What we know: `fred.sync_log` exists (referenced in sync_fred_from_vm.py constants).
   - What's unclear: Exact columns. The script uses it but no migration was found during research.
   - Recommendation: Query `information_schema.columns WHERE table_schema='fred' AND table_name='sync_log'`
     to confirm columns before writing the freshness query. May be simpler to query `fred.series_values`
     directly with `MAX(date)` per series (which works without sync_log).

---

## Sources

### Primary (HIGH confidence -- direct file inspection)
- `src/ta_lab2/dashboard/app.py` -- page registration pattern, navigation groups
- `src/ta_lab2/dashboard/pages/8_drift_monitor.py` -- fragment pattern, sidebar placement
- `src/ta_lab2/dashboard/pages/2_pipeline_monitor.py` -- traffic-light pattern, TABLE_FAMILIES
- `src/ta_lab2/dashboard/charts.py` -- all chart functions, color constants, make_subplots
- `src/ta_lab2/dashboard/db.py` -- NullPool engine singleton
- `src/ta_lab2/dashboard/queries/pipeline.py` -- cache_data(ttl=300) + underscore engine pattern
- `src/ta_lab2/notifications/telegram.py` -- send_alert, send_message, AlertSeverity enum
- `src/ta_lab2/drift/attribution.py` -- AttributionResult dataclass, 6-step OAT, regime_delta
- `src/ta_lab2/drift/drift_monitor.py` -- DriftMonitor structure, _write_metrics, cmc_drift_metrics
- `src/ta_lab2/drift/drift_pause.py` -- Telegram best-effort pattern, try/except around alerts
- `src/ta_lab2/macro/regime_classifier.py` -- MacroRegimeClassifier, dimension labels, hysteresis
- `src/ta_lab2/macro/fred_reader.py` -- SERIES_TO_LOAD with 18 series + frequency comments
- `alembic/versions/d5e6f7a8b9c0_macro_regime_tables.py` -- cmc_macro_regimes exact schema
- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` -- fred.fred_macro_features exact schema
- `alembic/versions/c4d5e6f7a8b9_fred_phase66_derived_columns.py` -- 25 derived columns
- `.planning/phases/72-macro-observability/72-CONTEXT.md` -- user decisions and constraints

### Secondary (MEDIUM confidence)
- `.planning/phases/67-macro-regime-classifier/67-01-SUMMARY.md` -- confirms tables in public schema
- `.planning/phases/69-l4-resolver-integration/69-03-PLAN.md` -- confirms L4 integration approach

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed, found in existing imports
- cmc_macro_regimes schema: HIGH -- read directly from Alembic migration file
- fred.fred_macro_features schema: HIGH -- read directly from two Alembic migration files
- Dashboard patterns: HIGH -- read directly from 4 existing page files
- Telegram pattern: HIGH -- read directly from telegram.py and 2 consumers
- Attribution extension: HIGH -- read directly from attribution.py dataclass definition
- Traffic-light pattern: HIGH -- read directly from pipeline_monitor.py
- FRED frequency map: HIGH -- read directly from fred_reader.py comments
- Phase 71 columns: LOW -- Phase 71 plans not present at research time

**Research date:** 2026-03-03
**Valid until:** 2026-04-03 (stable patterns; only Phase 71 schema question is time-sensitive)
