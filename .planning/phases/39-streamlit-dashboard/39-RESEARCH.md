# Phase 39: Streamlit Dashboard - Research

**Researched:** 2026-02-24
**Domain:** Streamlit 1.44.0 multipage app, Plotly 6.4.0 charts, SQLAlchemy 2.0 + NullPool, DB schema inspection
**Confidence:** HIGH (core Streamlit/SQLAlchemy patterns verified against official docs; project-specific DB schema verified against source code)

---

## Summary

Streamlit 1.44.0 is installed and ready. The preferred multipage pattern for 1.44+ is `st.navigation` + `st.Page` (not the older `pages/` directory), which gives a shared entrypoint file that acts as a "picture frame" — running on every rerun and enabling true shared sidebar state across pages via `st.session_state`.

The canonical SQLAlchemy pattern splits caching in two tiers: `@st.cache_resource` for the NullPool engine (singleton per session), and `@st.cache_data(ttl=N)` for each query function that returns a DataFrame. This avoids connection pool exhaustion because NullPool opens and closes connections per-use, while the engine object itself is reused across reruns via `cache_resource`.

Plotly 6.4.0 is installed. To use `plotly_dark` template in Streamlit, pass `theme=None` to `st.plotly_chart()` and set `fig.update_layout(template="plotly_dark")` on the figure before rendering. Kaleido is not installed and has known Windows compatibility bugs in v1.x; use `fig.to_html()` → `io.StringIO` → `.encode("utf-8")` as the chart download approach instead of PNG/SVG.

**Primary recommendation:** Use `st.navigation` with sections ("Monitor", "Research"), shared sidebar TTL slider in `app.py`, two-tier caching (`cache_resource` engine + `cache_data` queries), `plotly_dark` via `theme=None`, and HTML export for chart downloads.

---

## Standard Stack

All packages already installed in the project environment — zero new dependencies required.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.44.0 | App framework, multipage, widgets, caching | Project constraint — v0.9.0 decision, already installed |
| plotly | 6.4.0 | Interactive charts (IC decay, rolling IC, regime timeline) | Already used in ic.py plot helpers; project constraint |
| sqlalchemy | 2.0.46 | DB engine with NullPool | Project standard — NullPool pattern already established |
| pandas | (installed) | DataFrames for all query results | Project-wide standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| psycopg2-binary | (installed) | PostgreSQL driver for SQLAlchemy | All DB connections |
| narwhals | (installed, plotly dep) | Plotly 6 DataFrame compatibility | Automatic, no direct use |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| st.navigation | pages/ directory | pages/ auto-nav is simpler, but shared sidebar state is harder; st.navigation is the preferred/documented approach from Streamlit 1.36+ |
| HTML chart download | kaleido PNG export | kaleido has known Windows v1.x bugs (issue #402); HTML export is safe and retains interactivity |
| @st.cache_data | st.session_state manual caching | cache_data TTL is automatic and idiomatic; session_state requires manual invalidation logic |

**Installation:** No new packages required. All are installed.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/dashboard/
├── app.py                    # Entrypoint: st.navigation, shared sidebar TTL slider, DB engine init
├── pages/
│   ├── 1_landing.py          # Landing page: summary metrics from both modes
│   ├── 2_pipeline_monitor.py # Mode B: table freshness, stats PASS/FAIL, coverage grid
│   └── 3_research_explorer.py# Mode A: IC score table, IC decay chart, regime timeline
├── db.py                     # get_engine() with @st.cache_resource + NullPool
├── queries/
│   ├── pipeline.py           # @st.cache_data queries for pipeline monitor data
│   └── research.py           # @st.cache_data queries for IC results + regimes
└── charts.py                 # Plotly figure builders (wrap ic.py helpers + regime charts)

.streamlit/
└── config.toml               # fileWatcherType=poll, dark theme base
```

The `pages/` directory here is a Python package sub-directory, NOT Streamlit's legacy auto-nav pages folder. With `st.navigation`, Streamlit ignores any `pages/` folder — the pages are defined explicitly by `st.Page()` calls in `app.py`.

### Pattern 1: st.navigation Entrypoint with Shared State

**What:** `app.py` defines all pages, creates the NullPool engine, and renders a shared sidebar TTL slider. Every page accesses `st.session_state.cache_ttl` and `st.session_state.db_engine`.

**When to use:** Always — this is the entry point, run on every rerun.

```python
# Source: https://docs.streamlit.io/develop/api-reference/navigation/st.navigation
import streamlit as st
from ta_lab2.dashboard.db import get_engine

st.set_page_config(page_title="ta_lab2 Dashboard", layout="wide")

# Shared sidebar controls — state persists across page switches
with st.sidebar:
    st.title("ta_lab2")
    ttl = st.slider("Cache TTL (s)", min_value=30, max_value=3600,
                    value=300, step=30, key="cache_ttl")
    if st.button("Refresh Now"):
        st.cache_data.clear()

pages = {
    "Overview": [st.Page("pages/1_landing.py", title="Dashboard Home")],
    "Monitor": [st.Page("pages/2_pipeline_monitor.py", title="Pipeline Monitor")],
    "Research": [st.Page("pages/3_research_explorer.py", title="Research Explorer")],
}

pg = st.navigation(pages)
pg.run()
```

### Pattern 2: Two-Tier DB Caching (cache_resource + cache_data)

**What:** Engine is a singleton via `cache_resource`. Query results are DataFrames cached via `cache_data` with configurable TTL.

**When to use:** Every DB interaction in the dashboard.

```python
# Source: https://docs.streamlit.io/develop/concepts/architecture/caching
# db.py
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ta_lab2.scripts.refresh_utils import resolve_db_url

@st.cache_resource
def get_engine():
    """NullPool engine — opens/closes connection per query, no pool exhaustion."""
    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=NullPool)

# queries/pipeline.py
@st.cache_data(ttl=300)  # TTL overridden per call or from session state
def load_asset_coverage(_engine) -> pd.DataFrame:
    """Underscore prefix on _engine tells cache_data to NOT hash it (unhashable)."""
    with _engine.connect() as conn:
        return pd.read_sql(
            "SELECT id, source_table, granularity, n_rows, last_ts, updated_at "
            "FROM public.asset_data_coverage ORDER BY source_table, id",
            conn
        )
```

**CRITICAL:** Prefix the engine parameter with underscore (`_engine`) in all `@st.cache_data` functions. This tells Streamlit to skip hashing it — SQLAlchemy engines are not hashable and will cause a TypeError if Streamlit tries to hash them.

### Pattern 3: Dynamic TTL from Session State

Since `@st.cache_data(ttl=N)` requires a static TTL at decoration time, implement dynamic TTL by calling `st.cache_data.clear()` on the "Refresh Now" button and accepting the sidebar slider as a documentation UX only, OR by wrapping queries in a helper that rebuilds cached functions with the current TTL:

```python
# Simpler approach: fixed TTL=300 with manual Refresh button
# The slider controls displayed TTL info, the button clears cache
@st.cache_data(ttl=300)
def load_ic_results(_engine, asset_id: int, tf: str) -> pd.DataFrame:
    ...

# In the page:
if st.session_state.get("cache_ttl", 300) != 300:
    st.info(f"Cache TTL: {st.session_state.cache_ttl}s — use Refresh to apply")
```

Alternative: pass TTL as a parameter and let Streamlit cache per TTL value (creates many cache entries). The manual Refresh button approach is simpler and recommended.

### Pattern 4: Traffic Light Badges with st.badge (NEW in 1.44.0)

**What:** `st.badge` was added in Streamlit 1.44.0 with green/yellow/red/orange colors and Material Symbols icons.

```python
# Source: https://docs.streamlit.io/develop/api-reference/text/st.badge
def freshness_badge(staleness_hours: float | None) -> None:
    """Render a traffic light badge for data freshness."""
    if staleness_hours is None:
        st.badge("No data", color="gray", icon=":material/remove:")
    elif staleness_hours < 24:
        st.badge("Fresh", color="green", icon=":material/check_circle:",
                 help=f"{staleness_hours:.1f}h ago")
    elif staleness_hours < 72:
        st.badge("Stale", color="yellow", icon=":material/warning:",
                 help=f"{staleness_hours:.1f}h ago")
    else:
        st.badge("Very Stale", color="red", icon=":material/error:",
                 help=f"{staleness_hours:.1f}h ago")
```

### Pattern 5: Plotly Charts with plotly_dark

**What:** Set `theme=None` on `st.plotly_chart()` to let the figure's own template take precedence. Apply `plotly_dark` in `fig.update_layout()`.

```python
# Source: https://discuss.streamlit.io/t/plotly_chart-theme/36476
# Verified against: Streamlit docs (theme=None uses Plotly native template)
import streamlit as st
from ta_lab2.analysis.ic import plot_ic_decay, plot_rolling_ic

def render_ic_decay_chart(ic_df, feature: str) -> None:
    fig = plot_ic_decay(ic_df, feature)
    fig.update_layout(template="plotly_dark")
    st.plotly_chart(fig, theme=None, width="stretch")
```

### Pattern 6: Regime Timeline with Colored Bands

**What:** Price chart with colored background bands for each regime period. Uses Plotly `add_vrect()` for shaded regions.

```python
# Source: plotly.com/python/shapes/
import plotly.graph_objects as go

REGIME_COLORS = {
    "Up": "rgba(0, 200, 100, 0.15)",    # green, low opacity
    "Down": "rgba(220, 50, 50, 0.15)",  # red, low opacity
    "Sideways": "rgba(150, 150, 150, 0.12)",  # gray, low opacity
}

def build_regime_price_chart(close_series: pd.Series,
                              regimes_df: pd.DataFrame) -> go.Figure:
    """Price line with colored regime background bands."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=close_series.index, y=close_series.values,
        mode="lines", name="Close", line=dict(color="white", width=1.5)
    ))

    # Add colored bands per regime period
    for ts, row in regimes_df.iterrows():
        trend = row.get("trend_state", "Sideways")
        color = REGIME_COLORS.get(trend, REGIME_COLORS["Sideways"])
        # Find end of this regime's period
        # (iterate or use next ts as end)
        fig.add_vrect(
            x0=ts, x1=ts + pd.Timedelta(days=1),  # replaced with actual end
            fillcolor=color, opacity=1, layer="below", line_width=0
        )
    fig.update_layout(template="plotly_dark")
    return fig
```

**NOTE:** For the regime timeline bar chart (standalone), use Plotly `go.Bar` with `orientation="h"` and color-coded bars per regime label.

### Pattern 7: Chart Download via HTML (No kaleido)

**What:** Export interactive Plotly chart as HTML bytes. Works without kaleido.

```python
# Verified: fig.to_html() works on this system (kaleido not installed)
import io

def download_chart_button(fig, label: str, filename: str) -> None:
    buffer = io.StringIO()
    fig.write_html(buffer, include_plotlyjs="cdn")
    html_bytes = buffer.getvalue().encode("utf-8")
    st.download_button(
        label=label,
        data=html_bytes,
        file_name=filename,
        mime="text/html",
    )
```

### Anti-Patterns to Avoid

- **Passing SQLAlchemy engine directly to `@st.cache_data`:** Will throw TypeError because engines are not hashable. Always prefix with underscore: `_engine`.
- **Calling `st.navigation` after rendering widgets:** `st.navigation` must be called, then `pg.run()` — do not split them or render content between them in app.py.
- **Using `pages/` directory for page files:** With `st.navigation`, Streamlit ignores the `pages/` folder. Pages are defined by `st.Page()` calls. The `pages/` package directory in `src/ta_lab2/dashboard/pages/` is a Python package, not Streamlit's legacy auto-nav folder.
- **Calling `set_page_config` in sub-pages:** Only call `st.set_page_config()` in `app.py` (the entrypoint). Calling it in sub-page files throws a StreamlitAPIException.
- **Using `use_container_width=True`:** Deprecated in Streamlit 1.44+. Use `width="stretch"` instead.

---

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB freshness tracking | Custom "last updated" table | Query `asset_data_coverage.last_ts` + `updated_at` directly | Table already exists, tracks per-table freshness |
| Stats PASS/FAIL display | Custom status tracking table | Query `price_bars_multi_tf_stats`, `ema_multi_tf_stats`, etc. with `status` column | Stats tables already have PASS/WARN/FAIL rows with `checked_at` |
| Asset list with symbols | Custom asset registry | `SELECT id, symbol FROM dim_assets ORDER BY symbol` | `dim_assets` is the authoritative asset registry (id + symbol) |
| Available timeframes | Custom TF list | `SELECT tf FROM dim_timeframe ORDER BY tf_days_nominal` | `dim_timeframe` with `tf_days_nominal` column |
| IC score loading | Custom IC query | `load_regimes_for_asset()` and `load_feature_series()` from `ta_lab2.analysis.ic` | Already implemented, tested, handles the tz-aware pitfall |
| IC decay charts | Custom Plotly code | `plot_ic_decay()`, `plot_rolling_ic()` from `ta_lab2.analysis.ic` | Already implemented Phase 37, just add `template="plotly_dark"` |
| DB URL resolution | Custom env-var reading | `resolve_db_url()` from `ta_lab2.scripts.refresh_utils` | Already handles db_config.env + TARGET_DB_URL + MARKETDATA_DB_URL |
| Traffic light badges | Custom HTML/markdown | `st.badge(color="green"/"yellow"/"red")` | New in Streamlit 1.44.0, exact match for the requirement |
| Asset coverage matrix | Custom tracking query | `SELECT * FROM asset_data_coverage` | Table already populated by bar builder, has n_rows + last_ts |
| Feature name autocomplete | Custom search box | `st.text_input` + filtering a list loaded from `DISTINCT feature FROM cmc_ic_results` | Simple pattern; no extra library needed |

**Key insight:** The project already has all query helpers, chart helpers, and DB tables needed. The dashboard is primarily wiring, not building.

---

## Common Pitfalls

### Pitfall 1: Hashing SQLAlchemy Engine in cache_data

**What goes wrong:** `TypeError: unhashable type: 'Engine'` when passing an engine as a regular argument to a `@st.cache_data` function.

**Why it happens:** `@st.cache_data` tries to hash all function arguments to build the cache key. SQLAlchemy Engine objects are not hashable.

**How to avoid:** Prefix the engine parameter with an underscore: `def load_data(_engine, ...)`. Streamlit skips hashing underscore-prefixed parameters.

**Warning signs:** TypeError on first query function call.

### Pitfall 2: st.set_page_config Called Multiple Times

**What goes wrong:** `StreamlitAPIException: set_page_config() can only be called once per app page`.

**Why it happens:** If any imported module or sub-page file calls `st.set_page_config()`, it conflicts with the call in `app.py`.

**How to avoid:** Call `st.set_page_config()` only in `app.py`, never in page files.

**Warning signs:** Exception on app startup.

### Pitfall 3: Streamlit Theme Overriding plotly_dark

**What goes wrong:** Charts rendered in Streamlit's default theme (white/blue) instead of dark mode, even when `template="plotly_dark"` is set on the figure.

**Why it happens:** `st.plotly_chart()` defaults to `theme="streamlit"`, which overrides the figure's own template.

**How to avoid:** Pass `theme=None` to `st.plotly_chart()`. This instructs Streamlit to use the figure's native Plotly template.

**Warning signs:** Charts look light-themed despite dark app theme.

### Pitfall 4: Windows tz-aware Timestamp Pitfall

**What goes wrong:** Timestamps loaded via `pd.read_sql()` have inconsistent timezone offsets on Windows, producing object-dtype columns instead of DatetimeTZDtype.

**Why it happens:** psycopg2 returns timezone-aware datetime objects with varying UTC offset representations on Windows.

**How to avoid:** Always apply `df["ts"] = pd.to_datetime(df["ts"], utc=True)` after `pd.read_sql()` for any timestamp column. The existing `load_regimes_for_asset()` already does this — replicate the pattern.

**Warning signs:** `df["ts"].dtype == object` instead of `datetime64[ns, UTC]`.

### Pitfall 5: st.navigation Ignoring pages/ Directory

**What goes wrong:** Page files in `src/ta_lab2/dashboard/pages/` are not discovered by Streamlit.

**Why it happens:** With `st.navigation` called in `app.py`, Streamlit completely ignores any `pages/` folder. Pages must be registered with `st.Page()`.

**How to avoid:** Always use `st.Page("pages/filename.py", title="...")` in `app.py`. Never rely on auto-discovery.

**Warning signs:** Page files exist but sidebar shows nothing.

### Pitfall 6: kaleido Not Installed — PNG Export Fails

**What goes wrong:** `fig.to_image(format="png")` raises "kaleido package required" error.

**Why it happens:** Kaleido is not installed (`pip show kaleido` returns nothing). Even if installed, kaleido v1.x has confirmed Windows compatibility bugs.

**How to avoid:** Use `fig.to_html()` + `io.StringIO` for chart downloads. This is verified to work on this system. Skip PNG/SVG export entirely.

**Warning signs:** ImportError or RuntimeError on `to_image()` calls.

### Pitfall 7: cmc_regimes l2_label Parsing

**What goes wrong:** Code attempts to read `trend_state` or `vol_state` columns from `cmc_regimes` — they don't exist.

**Why it happens:** `cmc_regimes` only has `l2_label` (format: "Up-Low-Normal"). trend_state and vol_state must be derived via `split_part(l2_label, '-', 1)` and `split_part(l2_label, '-', 2)` in SQL.

**How to avoid:** Use the existing `load_regimes_for_asset()` function which already handles this correctly. Or replicate its SQL pattern.

**Warning signs:** `sqlalchemy.exc.UndefinedColumn` for `trend_state` or `vol_state`.

---

## Code Examples

Verified patterns from official sources and project codebase:

### .streamlit/config.toml (Windows-compatible dark theme)
```toml
# Source: https://docs.streamlit.io/develop/api-reference/configuration/config.toml
[server]
fileWatcherType = "poll"

[theme]
base = "dark"
```

### Engine Initialization (cache_resource + NullPool)
```python
# Source: official Streamlit caching docs + project NullPool pattern
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ta_lab2.scripts.refresh_utils import resolve_db_url

@st.cache_resource
def get_engine():
    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=NullPool)
```

### Pipeline Monitor: Stats PASS/FAIL Query
```python
# Source: run_all_stats_runners.py query_stats_status() — adapted for dashboard
@st.cache_data(ttl=300)
def load_stats_status(_engine, window_hours: int = 24) -> dict[str, dict[str, int]]:
    """Load PASS/WARN/FAIL counts from all stats tables."""
    stats_tables = [
        "price_bars_multi_tf_stats",
        "ema_multi_tf_stats",
        "ema_multi_tf_cal_stats",
        "ema_multi_tf_cal_anchor_stats",
        "returns_ema_stats",
        "cmc_features_stats",
    ]
    result = {}
    with _engine.connect() as conn:
        for table in stats_tables:
            try:
                rows = conn.execute(
                    text(f"SELECT status, COUNT(*) AS n FROM public.{table} "
                         f"WHERE checked_at >= NOW() - INTERVAL :w GROUP BY status"),
                    {"w": f"{window_hours} hours"}
                ).fetchall()
                result[table] = {row[0]: int(row[1]) for row in rows}
            except Exception:
                result[table] = {}
    return result
```

### Pipeline Monitor: Asset Coverage Grid
```python
# Source: sql/ddl/create_asset_data_coverage.sql — columns: id, source_table, granularity, n_rows, last_ts
@st.cache_data(ttl=300)
def load_asset_coverage(_engine) -> pd.DataFrame:
    with _engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT id, source_table, granularity, n_rows, last_ts, updated_at "
                 "FROM public.asset_data_coverage ORDER BY source_table, id"),
            conn
        )
    df["staleness_hours"] = (pd.Timestamp.utcnow() - pd.to_datetime(df["updated_at"], utc=True)) \
                              .dt.total_seconds() / 3600
    return df

# Pivot for coverage matrix
def build_coverage_matrix(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(
        index="id", columns="source_table", values="n_rows", aggfunc="sum"
    ).fillna(0)
```

### Research Explorer: Asset + TF Selection
```python
# Source: sql/ddl/create_dim_assets.sql — columns: id, symbol
@st.cache_data(ttl=3600)
def load_asset_list(_engine) -> pd.DataFrame:
    with _engine.connect() as conn:
        return pd.read_sql(
            text("SELECT id, symbol FROM public.dim_assets ORDER BY symbol"),
            conn
        )

@st.cache_data(ttl=3600)
def load_tf_list(_engine) -> list[str]:
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tf FROM public.dim_timeframe "
                 "ORDER BY tf_days_nominal")  # CRITICAL: tf_days_nominal not tf_days
        ).fetchall()
    return [r[0] for r in rows]

# In page:
assets_df = load_asset_list(get_engine())
asset_options = dict(zip(assets_df["symbol"], assets_df["id"]))
selected_symbol = st.selectbox("Asset", list(asset_options.keys()))
selected_id = asset_options[selected_symbol]
```

### Research Explorer: IC Results Table
```python
# Source: sql/features/080_cmc_ic_results.sql
# Columns: asset_id, tf, feature, horizon, return_type, regime_col, regime_label,
#          ic, ic_t_stat, ic_p_value, ic_ir, turnover, n_obs, computed_at
@st.cache_data(ttl=300)
def load_ic_results(_engine, asset_id: int, tf: str) -> pd.DataFrame:
    with _engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT feature, horizon, return_type, regime_col, regime_label, "
                 "ic, ic_p_value, ic_ir, n_obs, computed_at "
                 "FROM public.cmc_ic_results "
                 "WHERE asset_id = :id AND tf = :tf "
                 "ORDER BY feature, horizon, return_type"),
            conn, params={"id": asset_id, "tf": tf}
        )
    return df
```

### Research Explorer: Feature Search with Autocomplete
```python
@st.cache_data(ttl=600)
def load_feature_names(_engine, asset_id: int, tf: str) -> list[str]:
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT feature FROM public.cmc_ic_results "
                 "WHERE asset_id = :id AND tf = :tf ORDER BY feature"),
            {"id": asset_id, "tf": tf}
        ).fetchall()
    return [r[0] for r in rows]

# In page — text search autocomplete pattern:
feature_names = load_feature_names(get_engine(), selected_id, selected_tf)
search_query = st.text_input("Search features", "")
filtered = [f for f in feature_names if search_query.lower() in f.lower()]
selected_feature = st.selectbox("Select feature", filtered) if filtered else None
```

### CSV Download Button
```python
# Source: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button
@st.cache_data
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

st.download_button(
    label="Download CSV",
    data=to_csv_bytes(ic_df),
    file_name="ic_results.csv",
    mime="text/csv",
)
```

### Chart Download (HTML, no kaleido)
```python
# Verified: fig.to_html() works on this system (kaleido NOT installed)
import io

def chart_download_button(fig, filename: str) -> None:
    buffer = io.StringIO()
    fig.write_html(buffer, include_plotlyjs="cdn")
    html_bytes = buffer.getvalue().encode("utf-8")
    st.download_button(
        label="Download chart (HTML)",
        data=html_bytes,
        file_name=filename,
        mime="text/html",
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pages/` directory multipage | `st.navigation` + `st.Page` | Streamlit ~1.36 | `st.navigation` is now preferred/documented as the primary method |
| `use_container_width=True` | `width="stretch"` | Streamlit 1.44 | Old parameter deprecated; use `width` parameter |
| `st.cache` (old) | `st.cache_data` + `st.cache_resource` | Streamlit 1.18 | Split caching model; old `st.cache` removed |
| Custom badge markdown | `st.badge(color=...)` | Streamlit 1.44.0 | New built-in element with green/yellow/red support |
| Plotly engine='kaleido' | No engine param (auto) | Plotly 6.2 | `engine` arg deprecated; kaleido used automatically if installed |
| `plotly_dark` via template | `theme=None` in `st.plotly_chart` | Streamlit 1.16+ | Streamlit theme (`theme="streamlit"`) overrides figure template; use `theme=None` |

**Deprecated/outdated:**
- `st.cache`: Removed. Use `st.cache_data` or `st.cache_resource`.
- `use_container_width` on charts: Deprecated since 1.44. Use `width="stretch"`.
- `fig.to_image(engine="kaleido")`: `engine` arg deprecated since Plotly 6.2.

---

## Open Questions

1. **Table-family freshness query source**
   - What we know: `asset_data_coverage` tracks `last_ts` and `updated_at` per (id, source_table, granularity). The stats tables track `checked_at`.
   - What's unclear: Whether `updated_at` from `asset_data_coverage` or `MAX(ts)` from each table itself is the right freshness signal for the Pipeline Monitor "traffic light" per table family.
   - Recommendation: Use `asset_data_coverage.updated_at` for the coverage grid (already computed), and `MAX(checked_at)` from stats tables for the stats runner PASS/FAIL panel. Planner should decide which source drives the "data freshness per table family" column.

2. **Alert history panel availability**
   - What we know: Stats tables have `checked_at` and `status` columns. The `weekly_digest.py` script exists but its output format is unclear.
   - What's unclear: Whether a useful "alert history" can be built from existing stats rows without a dedicated alert log table.
   - Recommendation: Build alert history by querying recent FAIL/WARN rows from `price_bars_multi_tf_stats` and other stats tables, filtered to `status IN ('FAIL', 'WARN')` and `checked_at > NOW() - interval '7 days'`. No new table needed.

3. **Configurable TTL implementation**
   - What we know: `@st.cache_data(ttl=N)` requires a static value at decoration time. Dynamic TTL from a sidebar slider cannot be directly passed to the decorator.
   - What's unclear: The CONTEXT.md says "configurable via sidebar slider (default 300s)" — this needs a specific implementation strategy.
   - Recommendation: Use `st.cache_data(ttl=300)` as fixed default. The "Refresh Now" button calls `st.cache_data.clear()`. The sidebar slider only sets `st.session_state.cache_ttl` for documentation display. If true per-TTL caching is needed, use `st.cache_data.clear()` when the slider changes value.

---

## Sources

### Primary (HIGH confidence)
- Streamlit official docs — st.navigation: https://docs.streamlit.io/develop/api-reference/navigation/st.navigation
- Streamlit official docs — pages/ directory: https://docs.streamlit.io/develop/concepts/multipage-apps/pages-directory
- Streamlit official docs — st.cache_data: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data
- Streamlit official docs — caching overview: https://docs.streamlit.io/develop/concepts/architecture/caching
- Streamlit official docs — st.badge: https://docs.streamlit.io/develop/api-reference/text/st.badge
- Streamlit official docs — st.plotly_chart: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart
- Streamlit official docs — st.download_button: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button
- Streamlit official docs — config.toml: https://docs.streamlit.io/develop/api-reference/configuration/config.toml
- Streamlit 2025 release notes: https://docs.streamlit.io/develop/quick-reference/release-notes/2025
- Plotly static image export: https://plotly.com/python/static-image-export/
- Project source — ic.py (plot_ic_decay, plot_rolling_ic, load_regimes_for_asset): src/ta_lab2/analysis/ic.py
- Project source — cmc_ic_results DDL: sql/features/080_cmc_ic_results.sql
- Project source — cmc_regimes DDL: sql/regimes/080_cmc_regimes.sql
- Project source — asset_data_coverage DDL: sql/ddl/create_asset_data_coverage.sql
- Project source — dim_assets DDL: sql/ddl/create_dim_assets.sql
- Project source — stats tables schema: src/ta_lab2/scripts/bars/stats/refresh_price_bars_stats.py
- Project source — resolve_db_url: src/ta_lab2/scripts/refresh_utils.py

### Secondary (MEDIUM confidence)
- Streamlit multipage overview (verified with official navigation docs): https://docs.streamlit.io/develop/concepts/multipage-apps/overview
- Plotly dark theme with theme=None (multiple community sources + official docs consistent): https://discuss.streamlit.io/t/plotly_chart-theme

### Tertiary (LOW confidence)
- kaleido Windows v1.x bug: https://github.com/plotly/Kaleido/issues/402 — single GitHub issue report but consistent with local verification (kaleido not installed, PNG export fails)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified with `pip show`; versions confirmed locally
- Architecture: HIGH — `st.navigation` pattern verified against official docs; two-tier caching verified against official caching docs
- st.badge traffic light: HIGH — verified against official st.badge docs; new in 1.44.0 (same version installed)
- Plotly chart export: HIGH — local test confirmed kaleido not installed; HTML export confirmed working
- Pitfalls: HIGH — underscore-prefix for cache_data, tz-aware timestamp pattern documented in project MEMORY.md
- Stats table schema: HIGH — read directly from source scripts

**Research date:** 2026-02-24
**Valid until:** 2026-03-31 (Streamlit releases frequently; check release notes for anything above 1.44.0)
