# Phase 84: Dashboard — Perps, Portfolio & Regimes - Research

**Researched:** 2026-03-23
**Domain:** Streamlit dashboard extension — Hyperliquid perps data, regime heatmap, AMA/EMA inspector, portfolio placeholder
**Confidence:** HIGH (all findings verified against live codebase and live DB)

---

## Summary

Phase 84 adds four new pages to the existing Streamlit dashboard established in Phase 83.
All infrastructure is in place and unchanged: the `queries/*.py` + `pages/*.py` pattern,
`@st.cache_data(ttl=...)` with `_engine` prefix, `@st.fragment(run_every=900)` for auto-refresh,
and `go.Figure` with `plotly_dark` template. No new packages are needed.

The four pages target distinct data domains, each with unique gotchas:

1. **Hyperliquid Perps** — `hyperliquid` schema (cross-schema queries, `interval='1d'` candles
   only, `hl_oi_snapshots` has only 3 timestamps of live snapshot data, funding data only goes
   to 2026-03-11, `asset_id` in HL schema is NOT the same as `id` in public schema).
2. **Portfolio Allocation** — Pure placeholder page. No BL tables exist yet (Phase 86).
3. **Regime Heatmap** — `regimes` table has NO `trend_state` column — it must be derived via
   `split_part(l2_label, '-', 1) AS trend_state`. `regime_comovement` has only 7 assets (21 rows,
   3 EMA pairs × 7 assets) — it is NOT a cross-asset correlation matrix but per-asset EMA
   correlation metrics. This is a significant design constraint.
4. **AMA/EMA Inspector** — `ama_multi_tf_u` has 170M rows across 18 indicator/param combos
   (DEMA, HMA, KAMA, TEMA × 5 variants). `er` column is NULL for DEMA/HMA/TEMA (only KAMA
   computes efficiency ratio). `dim_ama_params` maps `params_hash` to human labels.

**Primary recommendation:** Follow the established Phase 83 query-layer pattern exactly.
All four pages should be numbered 14-17 (continuing from 13_asset_hub.py). Query `hyperliquid`
schema directly with cross-schema notation (`hyperliquid.hl_*`). Derive `trend_state` via SQL
`split_part`. Join `dim_ama_params` for human-readable AMA labels. Build portfolio page as
structural placeholder with mock data.

---

## Standard Stack

### Core (all already installed — no new packages needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.44.0 | Page framework | Pinned in requirements-311.txt |
| plotly | 6.4.0 | All charts | go.Figure, make_subplots, go.Heatmap, go.Scatter |
| pandas | current | DataFrame ops | Used in all query layers |
| SQLAlchemy | current | DB queries | NullPool engine pattern in db.py |
| numpy | current | Numeric ops | Already used throughout |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `go.Heatmap` for regime heatmap | `px.imshow` | `go.Heatmap` is consistent with existing chart style; `px.imshow` wraps it but adds plotly.express dependency |
| Separate network graph library | `go.Scatter` with line traces | NetworkX + pyvis would need new package; `go.Scatter` traces can approximate network graph |

**Installation:** No new packages needed.

---

## Architecture Patterns

### Existing Page Layout (must follow exactly)

```
src/ta_lab2/dashboard/
├── app.py                   # Extend pages dict — add 4 new pages to "Analysis" group
├── db.py                    # Unchanged — get_engine() singleton
├── charts.py                # Extend with new chart builders for this phase
├── pages/
│   ├── 13_asset_hub.py      # Last Phase 83 page
│   ├── 14_perps.py          # NEW: Hyperliquid Perps page
│   ├── 15_portfolio.py      # NEW: Portfolio Allocation page (placeholder)
│   ├── 16_regime_heatmap.py # NEW: Regime Heatmap page
│   └── 17_ama_inspector.py  # NEW: AMA/EMA Inspector page
└── queries/
    ├── perps.py             # NEW: load_hl_* query functions
    ├── regimes.py           # NEW: load_regime_* query functions
    └── ama.py               # NEW: load_ama_* query functions
```

### Page Numbering

Pages 14-17 continue from 13_asset_hub.py. Streamlit reads pages directory in
numeric order. No gaps allowed in numbering — files must be `14_`, `15_`, `16_`, `17_`.

### New Page List for app.py

```python
# Extend "Analysis" group in app.py:
st.Page("pages/14_perps.py",          title="Perps",             icon=":material/currency_exchange:"),
st.Page("pages/15_portfolio.py",      title="Portfolio",         icon=":material/account_balance:"),
st.Page("pages/16_regime_heatmap.py", title="Regime Heatmap",    icon=":material/grid_view:"),
st.Page("pages/17_ama_inspector.py",  title="AMA Inspector",     icon=":material/ssid_chart:"),
```

### Pattern 1: Query Layer (established in Phase 83 — replicate exactly)

```python
# Source: ta_lab2/dashboard/queries/research.py (verified pattern)
from __future__ import annotations
import pandas as pd
import streamlit as st
from sqlalchemy import text

@st.cache_data(ttl=900)
def load_hl_top_perps(_engine, limit: int = 15) -> pd.DataFrame:
    """Load top perps by 24h notional volume from hl_assets."""
    sql = text("""
        SELECT asset_id, symbol, day_ntl_vlm, funding, open_interest, mark_px,
               oracle_px, premium, max_leverage
        FROM hyperliquid.hl_assets
        WHERE asset_type = 'perp'
        ORDER BY day_ntl_vlm DESC NULLS LAST
        LIMIT :limit
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"limit": limit})
    return df
```

**Critical:** `_engine` prefix (underscore) is mandatory — `st.cache_data` skips hashing it.

### Pattern 2: Cross-Schema Query (hyperliquid schema)

```python
# Source: verified from hyperliquid schema structure 2026-03-23
# Schema prefix is REQUIRED: hyperliquid.hl_assets, hyperliquid.hl_candles, etc.
# asset_id in hl_assets is SMALLINT, NOT the same as public.dim_assets.id
@st.cache_data(ttl=900)
def load_hl_funding_rates(_engine, asset_ids: list[int], days_back: int = 30) -> pd.DataFrame:
    sql = text("""
        SELECT f.asset_id, a.symbol, f.ts, f.funding_rate, f.premium
        FROM hyperliquid.hl_funding_rates f
        JOIN hyperliquid.hl_assets a ON a.asset_id = f.asset_id
        WHERE f.asset_id = ANY(:asset_ids)
          AND f.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY f.ts DESC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_ids": asset_ids, "days_back": days_back})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Pattern 3: Regime trend_state Derivation (NO trend_state column exists)

```python
# Source: verified from ta_lab2/dashboard/queries/research.py load_regimes()
# The regimes table has NO trend_state column. It must be derived from l2_label.
# l2_label format: "Up-Normal-Normal", "Down-High-Normal", "Sideways-Low-Normal|explosive"
# trend_state = split_part(l2_label, '-', 1)  --> "Up", "Down", "Sideways"
# vol_state   = split_part(l2_label, '-', 2)  --> "Normal", "High", "Low"

@st.cache_data(ttl=900)
def load_regimes_multi_asset(_engine, asset_ids: list[int], tf: str = "1D",
                              days_back: int = 365) -> pd.DataFrame:
    sql = text("""
        SELECT
            r.id, r.ts,
            r.l2_label,
            split_part(r.l2_label, '-', 1) AS trend_state,
            split_part(r.l2_label, '-', 2) AS vol_state,
            r.regime_key
        FROM public.regimes r
        WHERE r.id = ANY(:ids)
          AND r.tf = :tf
          AND r.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY r.id, r.ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ids": asset_ids, "tf": tf, "days_back": days_back})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Pattern 4: AMA Query with dim_ama_params Join

```python
# Source: verified from ama_multi_tf_u schema + dim_ama_params content 2026-03-23
# dim_ama_params maps params_hash -> human label (e.g. "KAMA(10,2,30)")
# er column is NULL for DEMA, HMA, TEMA — only KAMA computes efficiency ratio

@st.cache_data(ttl=900)
def load_ama_curves(_engine, asset_id: int, tf: str = "1D",
                    indicator: str = "KAMA", params_hash: str | None = None) -> pd.DataFrame:
    base_sql = """
        SELECT a.ts, p.label, a.indicator, a.ama, a.d1, a.d2,
               a.d1_roll, a.d2_roll, a.er, a.roll
        FROM public.ama_multi_tf_u a
        JOIN public.dim_ama_params p
          ON p.params_hash = a.params_hash AND p.indicator = a.indicator
        WHERE a.id = :id
          AND a.tf = :tf
          AND a.indicator = :indicator
          AND a.alignment_source = 'multi_tf'
          AND a.roll = false
    """
    params = {"id": asset_id, "tf": tf, "indicator": indicator}
    if params_hash:
        base_sql += " AND a.params_hash = :params_hash"
        params["params_hash"] = params_hash
    base_sql += " ORDER BY a.ts, p.label"
    with _engine.connect() as conn:
        df = pd.read_sql(text(base_sql), conn, params=params)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Pattern 5: Page Structure (no st.set_page_config)

```python
# Source: verified from pages/10_macro.py, pages/11_backtest_results.py (Phase 83)
from __future__ import annotations
import streamlit as st
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.perps import load_hl_top_perps
from ta_lab2.dashboard.charts import chart_download_button

AUTO_REFRESH_SECONDS = 900

st.header("Perps")
st.caption("Hyperliquid perpetuals: funding rates, open interest, candles")

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# Sidebar controls OUTSIDE fragment (st.sidebar not allowed inside @st.fragment)
with st.sidebar:
    st.subheader("Perps Filters")
    ...

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _perps_content(_engine, ...):
    ...

_perps_content(engine, ...)
```

### Anti-Patterns to Avoid

- **No `st.set_page_config()` in page files** — only in app.py.
- **No sidebar widgets inside `@st.fragment`** — raises `StreamlitAPIException`.
- **No `.values` on tz-aware datetime Series** — returns tz-naive numpy. Always use `.tolist()`.
- **No `xaxis_rangeslider_visible` default** on candlestick — set `rangeslider_visible=False`.
- **Do not confuse `hyperliquid.hl_assets.asset_id` with `public.dim_assets.id`** — they are
  completely separate PK spaces. HL asset_id=0 is BTC perp; public dim_assets id=1 is also BTC
  but from CMC data. There is no FK between them.
- **Do not query `ema_multi_tf_u` for d1/d2** — it has no d1/d2 columns. Only `ama_multi_tf_u`
  has d1, d2, d1_roll, d2_roll.
- **Do not use `regime_comovement` as an asset cross-correlation table** — it is per-asset EMA
  pair comovement (7 assets, 21 rows total). It is not a cross-asset matrix.
- **Do not filter `hl_oi_snapshots` by date range expecting time-series** — it has only 3 snapshot
  timestamps (all from 2026-03-11). It is a point-in-time snapshot of current live OI.
- **`er` is NULL for DEMA, HMA, TEMA indicators** — only KAMA computes Efficiency Ratio.
- **`hl_candles` only has `interval='1d'` for most assets** — `interval='1h'` has only 8,726 rows
  for 190 assets across 3 days. Do not promise hourly candle charts for all 190 perps.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTML chart download | Custom JS export | `chart_download_button()` in charts.py | Already implemented |
| DB engine | New create_engine | `from ta_lab2.dashboard.db import get_engine` | `@st.cache_resource` singleton |
| Plotly heatmap | Custom grid rendering | `go.Heatmap` with `colorscale="RdBu"` | Consistent with existing `build_correlation_heatmap()` pattern |
| AMA labels | Parse params_hash manually | JOIN `dim_ama_params` on indicator + params_hash | Label column already there |
| trend_state from regime_key | String parsing in Python | `split_part(l2_label, '-', 1)` in SQL | Already done in `queries/research.py:load_regimes()` |
| Cross-schema join | Separate queries + merge | Single SQL with `hyperliquid.hl_assets` prefix | PostgreSQL supports cross-schema queries natively |
| HL symbol lookup | Hardcoded dict | JOIN `hyperliquid.hl_assets` ON asset_id | 534 assets, join is cheap and correct |

**Key insight:** The query layer does the heavy lifting. Pages are rendering-only.

---

## Common Pitfalls

### Pitfall 1: `regimes` Table Has No `trend_state` Column

**What goes wrong:** Querying `SELECT trend_state FROM public.regimes` raises `UndefinedColumn`.

**Why it happens:** `trend_state` is a derived concept, not a stored column. The underlying data
is `l2_label` in format "Up-Normal-Normal", "Down-High-Normal", etc. `regime_key` equals `l2_label`
in the current data.

**How to avoid:** Always derive in SQL:
```sql
split_part(l2_label, '-', 1) AS trend_state   -- "Up", "Down", "Sideways"
split_part(l2_label, '-', 2) AS vol_state     -- "Normal", "High", "Low"
```
This pattern is already confirmed in `queries/research.py:load_regimes()`.

**Warning signs:** Error message "column trend_state does not exist".

### Pitfall 2: `regime_comovement` Is Not a Cross-Asset Matrix

**What goes wrong:** Trying to build a cross-asset regime correlation heatmap from
`regime_comovement` — there are only 21 rows total (7 assets × 3 EMA pairs), all for
individual assets, not cross-asset pairs.

**Why it happens:** `regime_comovement` tracks how `close_ema_20`, `close_ema_50`,
and `close_ema_100` co-move WITHIN a single asset. Columns `ema_a` and `ema_b` are
EMA names (e.g., `"close_ema_20"`, `"close_ema_50"`), not asset symbols.

**How to avoid:** The "cross-asset regime heatmap" must be built from `public.regimes`
directly — pivot assets as rows, time as columns, color by `trend_state`. Use
`regime_comovement` only for the per-asset EMA comovement tab.
```sql
-- Correct approach: multi-asset regime heatmap from regimes table
SELECT r.id, da.symbol,
       split_part(r.l2_label, '-', 1) AS trend_state,
       r.ts
FROM public.regimes r
JOIN public.dim_assets da ON da.id = r.id
WHERE r.tf = '1D'
ORDER BY r.id, r.ts
```

### Pitfall 3: HL `asset_id` vs public `id` Namespace Collision

**What goes wrong:** Using HL `asset_id` values (0=BTC, 1=ETH in HL) as `dim_assets.id`
(where id=1 is BTC in CMC).

**Why it happens:** Both namespaces use integer IDs but they are independent systems.
HL asset_id=0 is BTC. dim_assets id=1 is BTC. These are coincidentally close but NOT
interchangeable.

**How to avoid:** HL perps pages use ONLY `hyperliquid.*` tables. Never join HL tables to
`public.dim_assets`. The `hyperliquid.hl_assets` table is the authoritative symbol lookup
for all HL data.

### Pitfall 4: `hl_oi_snapshots` Has Only 3 Point-in-Time Snapshots

**What goes wrong:** Building an OI time series chart from `hl_oi_snapshots` — there are only 756
rows across 3 snapshot timestamps, all from 2026-03-11. This is NOT a time series.

**Why it happens:** `hl_oi_snapshots` is populated by a live OI fetch (from `metaAndAssetCtxs`)
that captures a snapshot. Only 3 syncs have happened.

**How to avoid:** For OI time series, use `hyperliquid.hl_open_interest` (82K rows, Coinalyze
source) or `hl_candles.open_oi`/`close_oi` columns (though `close_oi` is mostly NULL). For
current live OI, use `hl_assets.open_interest` or the most recent `hl_oi_snapshots` row.

### Pitfall 5: `er` (Efficiency Ratio) is NULL for DEMA, HMA, TEMA

**What goes wrong:** Plotting `er` column for all AMA indicators shows NULL for 15/18 variants.

**Why it happens:** Only KAMA (Kaufman Adaptive Moving Average) computes efficiency ratio. DEMA
(Double EMA), HMA (Hull MA), and TEMA (Triple EMA) are deterministic period-based AMAs that
do not use an ER.

**How to avoid:** In AMA Inspector, display `er` only when `indicator = 'KAMA'`. For DEMA/HMA/TEMA,
the adaptive behavior is implicit in d1/d2 curvature. Always check for NULL before plotting:
```sql
WHERE indicator = 'KAMA' AND er IS NOT NULL
```

### Pitfall 6: `hl_candles` Hourly Data is Very Limited

**What goes wrong:** Offering hourly candle chart selection for all 190 perps — most will return
no data.

**Why it happens:** `interval='1h'` has only 8,726 rows covering 190 assets across ~3 days
(2026-03-08 to 2026-03-10). Daily (`interval='1d'`) covers 483 assets with 237K rows going back
to 2023-01-01.

**How to avoid:** Default candlestick chart to `interval='1d'`. Do not offer hourly dropdown for
HL perps — or if offered, clearly label it as "limited data" and handle empty result gracefully.

### Pitfall 7: Multiple `st.plotly_chart` Without `key`

**What goes wrong:** Chart swapping or disappearing on rerun.

**How to avoid:** Always pass unique `key` string to every `st.plotly_chart()`:
```python
st.plotly_chart(fig_funding, theme=None, key="perps_funding_rate_chart")
st.plotly_chart(fig_oi, theme=None, key="perps_oi_chart")
```

### Pitfall 8: `ama_multi_tf_u` Is 170M Rows — Always Filter Aggressively

**What goes wrong:** Loading all AMA rows for an asset without indicator/params filter can
return 18 indicator combos × 6,781 bars = 122K rows, which is slow and wastes browser memory.

**Why it happens:** 18 combinations: 5×DEMA + 5×HMA + 3×KAMA + 5×TEMA = 18 param variants.

**How to avoid:** Always filter by `indicator` AND optionally `params_hash`. Default to one
indicator (KAMA) in the inspector UI. Let users toggle others.

---

## Code Examples

### Load Top Perps Landing View

```python
# Source: verified from hyperliquid.hl_assets schema 2026-03-23
@st.cache_data(ttl=900)
def load_hl_top_perps(_engine, limit: int = 15) -> pd.DataFrame:
    """Top perps by 24h notional volume.
    Columns: asset_id, symbol, day_ntl_vlm, funding, open_interest, mark_px,
             oracle_px, premium, max_leverage
    """
    sql = text("""
        SELECT asset_id, symbol, day_ntl_vlm, funding, open_interest, mark_px,
               oracle_px, premium, max_leverage
        FROM hyperliquid.hl_assets
        WHERE asset_type = 'perp'
          AND day_ntl_vlm IS NOT NULL
        ORDER BY day_ntl_vlm DESC
        LIMIT :limit
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"limit": limit})
    return df
```

### Load Funding Rate Time Series

```python
# Source: verified from hyperliquid.hl_funding_rates schema 2026-03-23
# Funding rate is 8-hourly (3x daily). 30 days = ~90 rows per asset.
@st.cache_data(ttl=900)
def load_hl_funding_history(_engine, asset_ids: list[int],
                             days_back: int = 30) -> pd.DataFrame:
    """Funding rate time series for selected perp assets.
    Columns: asset_id, symbol, ts (UTC), funding_rate, premium
    """
    sql = text("""
        SELECT f.asset_id, a.symbol, f.ts, f.funding_rate, f.premium
        FROM hyperliquid.hl_funding_rates f
        JOIN hyperliquid.hl_assets a ON a.asset_id = f.asset_id
        WHERE f.asset_id = ANY(:asset_ids)
          AND f.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY f.asset_id, f.ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_ids": asset_ids, "days_back": days_back})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Load HL Candles (Daily Only)

```python
# Source: verified from hyperliquid.hl_candles schema 2026-03-23
# IMPORTANT: Only use interval='1d' — hourly data is very sparse (3 days only)
@st.cache_data(ttl=900)
def load_hl_candles(_engine, asset_id: int, days_back: int = 90) -> pd.DataFrame:
    """Daily OHLCV candles for one HL perp asset.
    Columns: asset_id, symbol, ts (UTC), open, high, low, close, volume, open_oi
    """
    sql = text("""
        SELECT c.asset_id, a.symbol, c.ts, c.open, c.high, c.low, c.close,
               c.volume, c.open_oi
        FROM hyperliquid.hl_candles c
        JOIN hyperliquid.hl_assets a ON a.asset_id = c.asset_id
        WHERE c.asset_id = :asset_id
          AND c.interval = '1d'
          AND c.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY c.ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "days_back": days_back})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Load Funding Rate Heatmap (Assets × Time)

```python
# Source: verified schema 2026-03-23
# For heatmap: pivot assets as rows, date as columns, funding_rate as values
@st.cache_data(ttl=900)
def load_hl_funding_heatmap(_engine, days_back: int = 30,
                             top_n: int = 20) -> pd.DataFrame:
    """Daily average funding rate per asset for heatmap pivot.
    Returns DataFrame with asset_id, symbol, date, avg_funding_rate.
    """
    sql = text("""
        SELECT f.asset_id, a.symbol,
               DATE(f.ts AT TIME ZONE 'UTC') AS date,
               AVG(f.funding_rate) AS avg_funding_rate
        FROM hyperliquid.hl_funding_rates f
        JOIN hyperliquid.hl_assets a ON a.asset_id = f.asset_id
        WHERE f.ts >= NOW() - (:days_back || ' days')::interval
          AND a.asset_type = 'perp'
          AND a.day_ntl_vlm IS NOT NULL
          AND a.asset_id = ANY(
              SELECT asset_id FROM hyperliquid.hl_assets
              WHERE asset_type = 'perp'
              ORDER BY day_ntl_vlm DESC NULLS LAST
              LIMIT :top_n
          )
        GROUP BY f.asset_id, a.symbol, DATE(f.ts AT TIME ZONE 'UTC')
        ORDER BY a.day_ntl_vlm DESC, date
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"days_back": days_back, "top_n": top_n})
    return df
```

### Load Regime Timeline for All Assets (Heatmap)

```python
# Source: verified from regimes schema and existing load_regimes() 2026-03-23
# CRITICAL: trend_state derived via split_part — NOT a column
@st.cache_data(ttl=900)
def load_regime_all_assets(_engine, tf: str = "1D",
                            days_back: int = 365) -> pd.DataFrame:
    """Regime states for ALL assets for regime heatmap.
    Columns: id, symbol, ts (UTC), trend_state, vol_state, regime_key
    Uses split_part on l2_label to extract trend/vol state.
    """
    sql = text("""
        SELECT r.id, da.symbol, r.ts,
               split_part(r.l2_label, '-', 1) AS trend_state,
               split_part(r.l2_label, '-', 2) AS vol_state,
               r.regime_key
        FROM public.regimes r
        JOIN public.dim_assets da ON da.id = r.id
        WHERE r.tf = :tf
          AND r.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY r.id, r.ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf, "days_back": days_back})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Load Regime Stats Summary

```python
# Source: verified from regime_stats schema 2026-03-23
@st.cache_data(ttl=900)
def load_regime_stats_summary(_engine, tf: str = "1D") -> pd.DataFrame:
    """Per-asset regime stats: regime_key distribution, bar counts.
    Columns: id, symbol, regime_key, n_bars, pct_of_history
    NOTE: avg_ret_1d is NULL for all rows in current data.
    """
    sql = text("""
        SELECT rs.id, da.symbol, rs.regime_key, rs.n_bars, rs.pct_of_history
        FROM public.regime_stats rs
        JOIN public.dim_assets da ON da.id = rs.id
        WHERE rs.tf = :tf
        ORDER BY rs.id, rs.n_bars DESC
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf})
    return df
```

### Load AMA Curves with Labels

```python
# Source: verified from ama_multi_tf_u + dim_ama_params schema 2026-03-23
@st.cache_data(ttl=900)
def load_ama_curves(_engine, asset_id: int, tf: str = "1D",
                    indicator: str = "KAMA",
                    days_back: int = 365) -> pd.DataFrame:
    """AMA curves for one asset with human-readable labels.
    Columns: ts (UTC), label, indicator, ama, d1, d2, d1_roll, d2_roll, er, roll
    NOTE: er is NULL for DEMA/HMA/TEMA, only populated for KAMA.
    """
    sql = text("""
        SELECT a.ts, p.label, a.indicator, a.ama, a.d1, a.d2,
               a.d1_roll, a.d2_roll, a.er, a.roll
        FROM public.ama_multi_tf_u a
        JOIN public.dim_ama_params p
          ON p.params_hash = a.params_hash AND p.indicator = a.indicator
        WHERE a.id = :id
          AND a.tf = :tf
          AND a.indicator = :indicator
          AND a.alignment_source = 'multi_tf'
          AND a.roll = false
          AND a.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY a.ts, p.label
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={
            "id": asset_id, "tf": tf, "indicator": indicator, "days_back": days_back
        })
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Load EMA for AMA Comparison

```python
# Source: verified from ema_multi_tf_u schema 2026-03-23
# EMA column name is 'ema' (NOT 'ema_value' in the table — aliased in queries/research.py)
@st.cache_data(ttl=900)
def load_ema_for_comparison(_engine, asset_id: int, tf: str = "1D",
                             periods: list[int] | None = None,
                             days_back: int = 365) -> pd.DataFrame:
    """EMA values for AMA vs EMA comparison.
    Columns: ts (UTC), period, ema
    alignment_source = 'multi_tf' is the canonical EMA source.
    """
    periods = periods or [9, 21, 50, 200]
    sql = text("""
        SELECT ts, period, ema
        FROM public.ema_multi_tf_u
        WHERE id = :id
          AND tf = :tf
          AND alignment_source = 'multi_tf'
          AND period = ANY(:periods)
          AND ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY period, ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={
            "id": asset_id, "tf": tf, "periods": periods, "days_back": days_back
        })
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Load AMA Params Catalogue

```python
# Source: verified from dim_ama_params schema 2026-03-23
@st.cache_data(ttl=3600)
def load_ama_params_catalogue(_engine) -> pd.DataFrame:
    """All AMA indicator/param combinations for UI selector.
    Columns: indicator, params_hash, label, params_json
    """
    sql = text("""
        SELECT indicator, params_hash, label, params_json
        FROM public.dim_ama_params
        ORDER BY indicator, label
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df
```

---

## Data Shape Reference

### hyperliquid.hl_assets

| Column | Type | Notes |
|--------|------|-------|
| `asset_id` | SMALLINT PK | 0=BTC, 1=ETH (HL-specific, NOT dim_assets.id) |
| `symbol` | TEXT | Ticker symbol (BTC, ETH, SOL...) |
| `asset_type` | TEXT | "perp", "spot", "km" |
| `day_ntl_vlm` | NUMERIC | 24h notional volume (for ranking) |
| `funding` | NUMERIC | Current 8-hour funding rate |
| `open_interest` | NUMERIC | Current OI in base asset units |
| `mark_px` | NUMERIC | Current mark price |
| `oracle_px` | NUMERIC | Oracle price |
| `premium` | NUMERIC | Mark-oracle premium |
| `max_leverage` | SMALLINT | Max allowed leverage |
| `updated_at` | TIMESTAMPTZ | Last update time |

**Row counts:** 534 total (252 perp, remainder spot/km)

### hyperliquid.hl_candles

| Column | Type | Notes |
|--------|------|-------|
| `asset_id` | SMALLINT | FK to hl_assets |
| `interval` | TEXT | '1d' (483 assets, 237K rows) or '1h' (190 assets, 8K rows, 3 days only) |
| `ts` | TIMESTAMPTZ | Bar close timestamp |
| `open`, `high`, `low`, `close`, `volume` | NUMERIC | Standard OHLCV |
| `open_oi` | NUMERIC | OI at bar open (mostly populated) |
| `close_oi` | NUMERIC | OI at bar close (mostly NULL) |

**Row counts:** 246,180 total. Daily back to 2023-01-01 for major assets.

### hyperliquid.hl_funding_rates

| Column | Type | Notes |
|--------|------|-------|
| `asset_id` | SMALLINT | FK to hl_assets |
| `ts` | TIMESTAMPTZ | 8-hourly timestamp |
| `funding_rate` | NUMERIC | 8-hour funding rate (e.g., -0.0000188 = -0.00188% per 8h) |
| `premium` | NUMERIC | Mark-oracle spread at settlement |

**Row counts:** 2.87M. Date range: 2023-05-11 to 2026-03-11. 208 distinct assets.

### hyperliquid.hl_oi_snapshots

| Column | Type | Notes |
|--------|------|-------|
| `asset_id` | SMALLINT | FK to hl_assets |
| `ts` | TIMESTAMPTZ | Snapshot timestamp |
| `open_interest` | NUMERIC | OI in base asset |
| `mark_px` | NUMERIC | Mark price at snapshot |

**Row counts:** 756 (252 assets × 3 timestamps, all from 2026-03-11). NOT a time series — use
for current-state display only.

### hyperliquid.hl_open_interest

| Column | Type | Notes |
|--------|------|-------|
| `asset_id` | SMALLINT | FK to hl_assets |
| `ts` | TIMESTAMPTZ | Daily bar timestamp |
| `open`, `high`, `low`, `close` | NUMERIC | Daily OI OHLC (from Coinalyze) |

**Row counts:** 82,268. Good for OI time-series charts (daily resolution, major assets).

### public.regimes

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT | Asset ID (FK to dim_assets) |
| `ts` | TIMESTAMPTZ | Bar timestamp |
| `tf` | TEXT | Timeframe (only '1D' in current data) |
| `l0_label` | TEXT | NULL for all current rows |
| `l1_label` | TEXT | NULL for all current rows |
| `l2_label` | TEXT | "Up-Normal-Normal", "Down-High-Normal", etc. (ACTIVE column) |
| `l3_label` | TEXT | NULL for all current rows |
| `l4_label` | TEXT | NULL for all current rows |
| `regime_key` | TEXT | = l2_label in current data (composite) |
| `size_mult` | FLOAT | Position sizing multiplier |
| `stop_mult` | FLOAT | Stop distance multiplier |
| `orders` | TEXT | e.g., "long_only" |

**Row counts:** 134,980. Only `l2_label` is populated (L0/L1/L3/L4 are all NULL).
**Assets:** 158 distinct assets, all at tf='1D'.
**trend_state:** Derived as `split_part(l2_label, '-', 1)` → "Up", "Down", "Sideways".
**Distinct regime_keys (19):** Up/Down/Sideways × Normal/High/Low × Normal, plus `|explosive` suffix variants, plus "Unknown".

### public.regime_flips

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT | Asset ID |
| `ts` | TIMESTAMPTZ | Flip timestamp |
| `tf` | TEXT | Timeframe |
| `layer` | TEXT | "composite" (always) |
| `old_regime` | TEXT | Previous regime_key |
| `new_regime` | TEXT | New regime_key |
| `duration_bars` | INT | Bars spent in old regime before flip |

**Row counts:** 8,163 total.

### public.regime_stats

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT | Asset ID |
| `tf` | TEXT | Timeframe |
| `regime_key` | TEXT | Regime label |
| `n_bars` | INT | Bar count in this regime |
| `pct_of_history` | FLOAT | Fraction of total history |
| `avg_ret_1d` | FLOAT | NULL for all rows in current data |

**Row counts:** 993 (158 assets × avg 6 distinct regimes each).

### public.regime_comovement

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT | Asset ID (only 7 assets have data) |
| `tf` | TEXT | Timeframe |
| `ema_a` | TEXT | EMA indicator name (e.g., "close_ema_20") |
| `ema_b` | TEXT | EMA indicator name (e.g., "close_ema_50") |
| `correlation` | FLOAT | EMA value correlation |
| `sign_agree_rate` | FLOAT | Pct of bars where ema_a and ema_b agree in direction |
| `best_lead_lag` | INT | Best lead-lag offset (always -7 to -10 in current data) |
| `best_lead_lag_corr` | FLOAT | Correlation at best lag |
| `n_obs` | INT | Observation count |

**Row counts:** 21 (7 assets × 3 EMA pairs: close_ema_20/50, 20/100, 50/100).
**WARNING:** NOT a cross-asset correlation matrix. This is per-asset EMA indicator comovement.

### public.ama_multi_tf_u

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT | Asset ID |
| `ts` | TIMESTAMPTZ | Bar timestamp |
| `tf` | TEXT | Timeframe |
| `indicator` | TEXT | "KAMA", "DEMA", "HMA", "TEMA" |
| `params_hash` | TEXT | MD5 of params — join to `dim_ama_params` for label |
| `alignment_source` | TEXT | 'multi_tf' is canonical |
| `roll` | BOOLEAN | false = non-rolling, true = rolling variant |
| `ama` | FLOAT | AMA value (price level) |
| `d1` | FLOAT | First derivative |
| `d2` | FLOAT | Second derivative |
| `d1_roll` | FLOAT | Rolling d1 |
| `d2_roll` | FLOAT | Rolling d2 |
| `er` | FLOAT | Efficiency Ratio (NULL for DEMA/HMA/TEMA, populated for KAMA) |

**Row counts:** 170M total (18 variants × 158 assets × 6,781 bars at 1D).
**Available indicators:** DEMA(9/10/21/50/200), HMA(9/10/21/50/200), KAMA(5,2,15), KAMA(10,2,30),
KAMA(20,2,50), TEMA(9/10/21/50/200).

### public.dim_ama_params

| Column | Type | Notes |
|--------|------|-------|
| `indicator` | TEXT | "KAMA", "DEMA", "HMA", "TEMA" |
| `params_hash` | TEXT | MD5 of params_json |
| `params_json` | JSONB | {"period": 9} or {"er_period": 10, "fast_period": 2, "slow_period": 30} |
| `label` | TEXT | Human-readable: "KAMA(10,2,30)", "DEMA(9)", "HMA(21)" |
| `warmup` | INT | Warmup bars needed |

**18 rows total:** 5 DEMA + 5 HMA + 3 KAMA + 5 TEMA.

### public.ema_multi_tf_u

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT | Asset ID |
| `ts` | TIMESTAMPTZ | Bar timestamp |
| `tf` | TEXT | Timeframe |
| `period` | INT | EMA period |
| `ema` | FLOAT | EMA value (use `alignment_source='multi_tf'`) |
| `ema_bar` | FLOAT | Bar-level (unsmoothed) EMA variant |
| `alignment_source` | TEXT | 'multi_tf' is canonical |
| `roll` | BOOLEAN | false = non-rolling |
| `d1` / `d2` | — | **NOT PRESENT** — EMA table has no d1/d2 |

**Periods available:** 6, 9, 10, 14, 17, 21, 50, 77, 100, 200, and many more (multi-TF range).
**Row counts:** 55.8M.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `st.experimental_fragment` | `@st.fragment(run_every=...)` | Streamlit 1.33 | Already in all Phase 83 pages |
| `st.experimental_get_query_params()` | `st.query_params` | Streamlit 1.30 | Dict-style access |
| `go.Ohlc` | `go.Candlestick` | Always preferred | Filled candles look modern |
| No rangeslider disable | `xaxis_rangeslider_visible=False` | Always needed | Required on every candlestick |

**Deprecated:**
- `regime_key` as-is for heatmap colors: Use `split_part(l2_label, '-', 1)` to get "Up/Down/Sideways",
  then apply `REGIME_COLORS`/`REGIME_BAR_COLORS` from `charts.py`.

---

## Open Questions

1. **`hl_oi_snapshots` Freshness**
   - What we know: Only 3 snapshot timestamps, all from 2026-03-11. Data is stale.
   - What's unclear: Whether new snapshots will be available at dashboard runtime.
   - Recommendation: Display `hl_oi_snapshots` as "Current OI" with a staleness warning if
     latest snapshot is more than 24h old. Fall back to `hl_assets.open_interest` if snapshots
     are stale.

2. **regime_comovement Cross-Asset Visualization**
   - What we know: Only 7 assets have data, 21 rows total. The table tracks EMA-pair comovement
     WITHIN an asset, not cross-asset correlation.
   - What's unclear: Whether a meaningful "comovement visualization" can be built from 7 data points.
   - Recommendation: Build the regime heatmap from `public.regimes` (158 assets). Use
     `regime_comovement` for a small "EMA Comovement" section showing the 7-asset data as a table
     + simple bar chart. The "network graph" described in CONTEXT.md is not feasible from this data.
     Document this as a known limitation; the table can grow if `refresh_regimes` runs on more assets.

3. **AMA Efficiency Ratio Display**
   - What we know: `er` is NULL for DEMA/HMA/TEMA. Only KAMA has it.
   - Recommendation: Default the AMA Inspector to KAMA to enable ER display. Add toggle for
     other indicators but suppress ER chart when indicator != KAMA.

4. **hl_candles Volume Units**
   - What we know: BTC volume on 2026-03-12 was 2.66003 (units unknown), but 2026-03-11 was 6052.86.
     The dramatic difference suggests the most recent bar may be partial.
   - Recommendation: Add `is_partial_end` note or filter last candle with caution. The very small
     volume on the last day suggests it was synced mid-day.

---

## Sources

### Primary (HIGH confidence)

- Live DB query: `hyperliquid.*` all column schemas and row counts — 2026-03-23
- Live DB query: `public.regimes` — confirmed no trend_state column, l2_label is active column
- Live DB query: `public.regime_comovement` — all 21 rows verified, only 7 assets
- Live DB query: `public.ama_multi_tf_u` — 170M rows, er NULL for DEMA/HMA/TEMA
- Live DB query: `public.dim_ama_params` — 18 rows, confirmed labels
- Live DB query: `public.ema_multi_tf_u` — no d1/d2 columns confirmed
- Live codebase: `ta_lab2/dashboard/queries/research.py` — `load_regimes()` verified split_part pattern
- Live codebase: `ta_lab2/dashboard/charts.py` — REGIME_COLORS, REGIME_BAR_COLORS, chart_download_button
- Live codebase: `ta_lab2/dashboard/app.py` — page numbering, navigation dict structure
- Live codebase: `ta_lab2/dashboard/db.py` — NullPool engine, get_engine()
- requirements-311.txt — Streamlit 1.44.0, Plotly 6.4.0 confirmed

### Secondary (MEDIUM confidence)

- Phase 83 RESEARCH.md — established patterns (all verified in live codebase)
- `ta_lab2/dashboard/pages/11_backtest_results.py` — fragment, sidebar outside fragment pattern

---

## Metadata

**Confidence breakdown:**
- Hyperliquid schema: HIGH — all columns and row counts verified from live DB
- Regime table schemas: HIGH — all columns verified, trend_state gotcha confirmed
- AMA/EMA schemas: HIGH — all columns verified, er NULL behavior confirmed
- Architecture patterns: HIGH — verified against live Phase 83 pages
- Portfolio placeholder: HIGH — no DB tables exist, pure mock confirmed

**Research date:** 2026-03-23
**Valid until:** 2026-04-22 (30 days — stable codebase, schemas do not change frequently)
