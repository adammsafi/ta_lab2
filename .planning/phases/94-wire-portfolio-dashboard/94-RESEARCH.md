# Phase 94: Wire Portfolio Dashboard to Live Data - Research

**Researched:** 2026-03-28
**Domain:** Streamlit dashboard page wiring, portfolio_allocations table, SQLAlchemy query patterns
**Confidence:** HIGH

## Summary

Phase 94 replaces all `numpy.random` mock data in `src/ta_lab2/dashboard/pages/15_portfolio.py`
with live queries against the `portfolio_allocations` table populated by the Phase 86 pipeline.
The page already has the complete UI layout (treemap, stacked bar, area chart, table, position
sizing section, exposure summary) — only the data source changes.

The `portfolio_allocations` table (renamed from `cmc_portfolio_allocations` in the
strip-cmc-prefix migration) has the schema: `(alloc_id UUID PK, ts TIMESTAMPTZ, optimizer TEXT,
is_active BOOLEAN, regime_label TEXT, asset_id INT, weight NUMERIC, final_weight NUMERIC,
signal_score NUMERIC, condition_number NUMERIC, config_snapshot JSONB, created_at TIMESTAMPTZ)`.
Unique constraint on `(ts, optimizer, asset_id)`. The refresh script writes optimizer values
`mv`, `cvar`, `hrp`, `bl`, and `{active}_sized`.

All 17 dashboard pages follow an identical engine init pattern: module-level
`try/except get_engine() + st.stop()`. Query functions live in `src/ta_lab2/dashboard/queries/`
using `@st.cache_data(ttl=N)` with `_engine` (underscore-prefix) as first argument.

**Primary recommendation:** Create `src/ta_lab2/dashboard/queries/portfolio.py` with three
query functions (`load_latest_allocations`, `load_allocation_history`, `load_available_optimizers`),
wire them into `15_portfolio.py` using the standard engine + fragment pattern, and preserve the
existing UI layout verbatim.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | project standard | DB engine + text() queries | All dashboard pages use this |
| pandas | project standard | pd.read_sql + DataFrame operations | All query functions return DataFrames |
| streamlit | project standard | st.cache_data, st.fragment, st.info | Dashboard framework |
| plotly.graph_objects | project standard | Treemap, Bar, Scatter charts | Already used in 15_portfolio.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ta_lab2.dashboard.db.get_engine` | internal | NullPool engine singleton | Always — single source of truth |
| `ta_lab2.dashboard.charts.chart_download_button` | internal | Download button for charts | Already called in 15_portfolio.py |

**Installation:** No new dependencies. All libraries already present.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/dashboard/
├── queries/
│   ├── portfolio.py        # NEW: load_latest_allocations, load_allocation_history, load_available_optimizers
│   └── [existing files]
└── pages/
    └── 15_portfolio.py     # MODIFY: wire engine + call query functions
```

### Pattern 1: Standard Engine Init (used by all 17 dashboard pages)
**What:** Module-level try/except block that calls get_engine() and halts page on failure.
**When to use:** Always, at module level (not inside fragment).
**Example:**
```python
# Source: src/ta_lab2/dashboard/pages/4_asset_stats.py lines 40-44
try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()
```

### Pattern 2: Cached Query Function with _engine prefix
**What:** `@st.cache_data(ttl=N)` functions accept `_engine` (underscore-prefix) as first arg so cache hashing is skipped.
**When to use:** All query functions in `dashboard/queries/`.
**Example:**
```python
# Source: src/ta_lab2/dashboard/queries/pipeline.py lines 15-34
@st.cache_data(ttl=300)
def load_stats_tables(_engine) -> list[str]:
    sql = text("SELECT ...")
    with _engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [row[0] for row in rows]
```

### Pattern 3: Empty DataFrame Graceful Fallback
**What:** Query functions return empty DataFrame on no data; page renders `st.info()` instead of crashing.
**When to use:** Any section that may have no data (portfolio_allocations empty when Phase 86 hasn't run).
**Example:**
```python
# Source: src/ta_lab2/dashboard/pages/4_asset_stats.py lines 78-81
if stats_df is None or stats_df.empty:
    st.info(
        "No asset statistics found. Run the daily refresh to populate data."
    )
```

### Pattern 4: Fragment with engine passed as argument
**What:** `@st.fragment(run_every=N)` function receives `_engine` as parameter (not captured from outer scope).
**When to use:** Auto-refreshing content blocks.
**Example from 6_trading.py:**
```python
# Source: src/ta_lab2/dashboard/pages/6_trading.py line 83
@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _trading_content(_engine, show_per_strategy: bool) -> None:
    ...
# Invocation:
_trading_content(_engine=engine, show_per_strategy=show_per_strategy)
```

### Pattern 5: dim_assets join for asset symbol lookup
**What:** `portfolio_allocations` stores `asset_id` (INT). Join `dim_assets` to get `symbol` for display.
**When to use:** Any query on portfolio_allocations that needs human-readable asset names.
**Example:**
```python
# Source: src/ta_lab2/dashboard/queries/trading.py lines 27-28, 43
SELECT a.symbol, p.asset_id, ...
FROM public.positions p
JOIN public.dim_assets a ON a.id = p.asset_id
```

### Anti-Patterns to Avoid
- **Calling get_engine() inside @st.fragment:** Fragment re-runs do not re-create the engine; pass engine as arg.
- **Passing engine without underscore prefix to @st.cache_data functions:** Cache hashing fails on SQLAlchemy engine. Must use `_engine`.
- **Hardcoded asset list like current mock:** The live query returns only assets actually present in `portfolio_allocations`. Do not assume a fixed set of 10 assets.
- **Using `st.set_page_config()` in a page file:** Called only in `app.py` entry point, not in page files.
- **Widgets inside @st.fragment:** Sidebar controls and date pickers must remain outside the fragment.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Asset ID to symbol mapping | Custom dict or separate query per asset | Single JOIN to `dim_assets` in SQL | Single round-trip, consistent with all other pages |
| TTL caching | Manual timestamp comparison | `@st.cache_data(ttl=N)` | Already the project standard |
| DB URL resolution | Custom file parser | `ta_lab2.dashboard.db.get_engine` (uses `resolve_db_url` internally) | Handles env vars, db_config.env fallback |
| Graceful empty state | Custom error handler | `if df is None or df.empty: st.info(...)` | Simple, matches project pattern |

**Key insight:** The entire infrastructure (engine, caching, query separation) is already in place. This phase is purely data wiring, not infrastructure work.

## Common Pitfalls

### Pitfall 1: portfolio_allocations table name confusion
**What goes wrong:** Using `cmc_portfolio_allocations` (old name) in SQL.
**Why it happens:** The alembic migration `f6a7b8c9d0e1_portfolio_tables.py` created it as `cmc_portfolio_allocations`. The strip-cmc-prefix migration `a0b1c2d3e4f5` renamed it to `portfolio_allocations`.
**How to avoid:** Always use `public.portfolio_allocations` in queries. The refresh script `refresh_portfolio_allocations.py` already uses the new name.
**Warning signs:** `psycopg2.errors.UndefinedTable` or `relation "cmc_portfolio_allocations" does not exist`.

### Pitfall 2: Hardcoded asset list from mock
**What goes wrong:** Keeping `_ASSETS`, `_STRATEGIES`, `_ASSET_STRATEGY` at module level and indexing live data against them.
**Why it happens:** Mock data was built around a fixed 10-asset list. Live data has whatever assets the optimizer ran on.
**How to avoid:** Derive asset list from query results. The strategy grouping column does not exist in `portfolio_allocations` — omit it or derive from a join with another table (e.g., `dim_executor_config` or regime data). Simpler: remove strategy-based grouping for the initial wiring.
**Warning signs:** KeyError on `_ASSET_STRATEGY[a]`, index-out-of-bounds on weight history numpy array slices.

### Pitfall 3: Weight history — portfolio_allocations has no daily snapshots yet
**What goes wrong:** Querying 30-day weight history from `portfolio_allocations` returns sparse data (only timestamps when the refresh script ran).
**Why it happens:** `portfolio_allocations` stores one row per optimizer run per asset, not daily cadence. In the absence of regular runs, the history may have only a handful of timestamps.
**How to avoid:** Load all historical rows ordered by `ts`, pivot to wide format (asset_id columns), and display whatever is there. If only one timestamp exists, the area chart should show a single point gracefully. Do not assert `>= 30` rows.
**Warning signs:** Empty `weight_history` DataFrame crashes numpy-based chart code.

### Pitfall 4: optimizer selector — multiple optimizer types coexist
**What goes wrong:** Loading all rows without filtering by optimizer returns mixed weights (mv + hrp + bl in same DataFrame).
**Why it happens:** The refresh script writes rows for `mv`, `cvar`, `hrp`, `bl`, and `{active}_sized`. Without a filter the weights double/triple-count.
**How to avoid:** Add an optimizer selector to the sidebar (default: `hrp` as the most common active optimizer, or whichever is latest `is_active=true`). Filter query by selected optimizer.
**Warning signs:** Weights sum to 200%+ because multiple optimizer rows exist for the same `ts`.

### Pitfall 5: st.info() banner removal
**What goes wrong:** Leaving the existing `st.info("This page uses mock data...")` banner after wiring live data.
**Why it happens:** Easy to forget during a refactor.
**How to avoid:** Remove the mock-data banner. Replace with a conditional: show informational message only when `portfolio_allocations` is empty.

### Pitfall 6: numpy indexing on live data
**What goes wrong:** The mock data section uses `asset_indices = [_ASSETS.index(a) for a in filtered_assets]` and `weight_history[:, asset_indices]` — this will crash with live data since `_ASSETS` may not contain live asset symbols.
**Why it happens:** All numpy array slicing in the current weight history section assumes the fixed 10-asset list.
**How to avoid:** Convert live data to a pandas DataFrame early and use `.loc`/column-name indexing throughout.

## Code Examples

Verified patterns from official sources (project codebase):

### Query Function Template for portfolio.py
```python
# Source: pattern from src/ta_lab2/dashboard/queries/trading.py
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=300)
def load_latest_allocations(_engine, optimizer: str = "hrp") -> pd.DataFrame:
    """Return the most recent allocation row per asset for the given optimizer.

    Columns: symbol, asset_id, ts, optimizer, weight, final_weight,
             regime_label, condition_number
    """
    sql = text(
        """
        SELECT
            a.symbol,
            pa.asset_id,
            pa.ts,
            pa.optimizer,
            CAST(pa.weight AS FLOAT)       AS weight,
            CAST(pa.final_weight AS FLOAT)  AS final_weight,
            pa.regime_label,
            CAST(pa.condition_number AS FLOAT) AS condition_number
        FROM (
            SELECT DISTINCT ON (asset_id) *
            FROM public.portfolio_allocations
            WHERE optimizer = :optimizer
            ORDER BY asset_id, ts DESC
        ) pa
        JOIN public.dim_assets a ON a.id = pa.asset_id
        ORDER BY a.symbol
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"optimizer": optimizer})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_allocation_history(_engine, optimizer: str = "hrp", days: int = 30) -> pd.DataFrame:
    """Return allocation rows for the last N days, pivoted wide (assets as columns).

    Returns DataFrame with DatetimeIndex (ts) and float columns per asset symbol.
    """
    sql = text(
        """
        SELECT
            a.symbol,
            pa.ts,
            CAST(pa.weight AS FLOAT) AS weight
        FROM public.portfolio_allocations pa
        JOIN public.dim_assets a ON a.id = pa.asset_id
        WHERE pa.optimizer = :optimizer
          AND pa.ts >= NOW() - (:days * INTERVAL '1 day')
        ORDER BY pa.ts, a.symbol
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"optimizer": optimizer, "days": days})

    if df.empty:
        return pd.DataFrame()

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    pivoted = df.pivot(index="ts", columns="symbol", values="weight")
    pivoted.index.name = "ts"
    return pivoted


@st.cache_data(ttl=300)
def load_available_optimizers(_engine) -> list[str]:
    """Return distinct optimizer names present in portfolio_allocations."""
    sql = text(
        "SELECT DISTINCT optimizer FROM public.portfolio_allocations ORDER BY optimizer"
    )
    with _engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [row[0] for row in rows]
```

### Engine Init Pattern (module level in 15_portfolio.py)
```python
# Source: src/ta_lab2/dashboard/pages/4_asset_stats.py lines 40-44
try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()
```

### Empty State Handling
```python
# Source: pattern from src/ta_lab2/dashboard/pages/4_asset_stats.py lines 78-81
alloc_df = load_latest_allocations(engine, optimizer=selected_optimizer)
if alloc_df.empty:
    st.info(
        "No portfolio allocations found. Run the portfolio refresh script to populate data: "
        "`python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids all --tf 1D`"
    )
    return  # early exit from fragment
```

### Passing engine to fragment
```python
# Source: src/ta_lab2/dashboard/pages/6_trading.py line 83 (adapted)
@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _portfolio_content(
    _engine,
    as_of_date: datetime.date,
    strategy_filter: list[str],
    selected_optimizer: str,
) -> None:
    ...

_portfolio_content(
    _engine=engine,
    as_of_date=as_of_date,
    strategy_filter=strategy_filter,
    selected_optimizer=selected_optimizer,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `cmc_portfolio_allocations` table name | `portfolio_allocations` | Phase 93 (strip-cmc-prefix migration `a0b1c2d3e4f5`) | All SQL must use new name |
| Mock numpy.random data in 15_portfolio.py | Live queries from `portfolio_allocations` | This phase (Phase 94) | Closes Break 2 from v1.2.0 audit |
| `get_engine` import with `# noqa: F401` | Full import + usage | This phase | Remove noqa comment, use engine |

**Deprecated/outdated in 15_portfolio.py after this phase:**
- `_ASSETS` constant list: replaced by dynamic asset list from query results
- `_STRATEGIES` / `_ASSET_STRATEGY` mapping: not present in `portfolio_allocations` schema, remove unless joined from elsewhere
- `rng = np.random.default_rng(42)` block: fully replaced
- `import numpy as np`: may be removable if no numpy needed after wiring (plotly handles lists natively)
- `# TODO(Phase-86):` comments: all three TODOs resolved
- `st.info("This page uses mock data...")` banner: remove, replace with empty-state conditional

## Open Questions

1. **Strategy column mapping**
   - What we know: `portfolio_allocations` has no `strategy` column. The mock used `_ASSET_STRATEGY` to group assets into `momentum/mean_reversion/trend_following`.
   - What's unclear: The Phase 86 pipeline doesn't persist strategy labels. The grouped treemap/stacked bar views by strategy cannot be reproduced from `portfolio_allocations` alone without a separate mapping.
   - Recommendation: Remove strategy-based grouping for Phase 94 (simplest correct approach). The treemap can use asset symbols as both labels and top-level parents (flat layout). The stacked bar can show a single "Portfolio" group. Alternatively, add a static symbol->strategy mapping if user wants the grouping — but this is discretionary.

2. **Position sizing section (Section 3) with live data**
   - What we know: `portfolio_allocations` has `weight` and `final_weight`. `bet_size_usd` was `weight_pct / 100 * portfolio_nav`. `portfolio_nav` was hardcoded at $100,000 in mock.
   - What's unclear: The live NAV is not in `portfolio_allocations`. It may be in `dim_executor_config.initial_capital` or in `risk_state`.
   - Recommendation: Use `load_starting_capital(_engine)` from `dashboard/queries/trading.py` to fetch real NAV from `dim_executor_config`. If that returns 0 or table is empty, fall back to a hardcoded default with `st.caption()` disclosure.

3. **Risk budget columns**
   - What we know: `portfolio_allocations` has no `risk_budget_pct` or `max_position_pct` columns. These were entirely mocked.
   - What's unclear: These may exist in `dim_risk_limits` or portfolio config.
   - Recommendation: For Phase 94, simplify Section 3 to show bet sizes only (drop risk budget progress bars), or derive budget from `weight * max_concentration_limit` from `config_snapshot` JSONB column. This is planner discretion.

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/dashboard/pages/15_portfolio.py` — full current mock implementation (read directly)
- `src/ta_lab2/dashboard/db.py` — get_engine pattern (read directly)
- `src/ta_lab2/dashboard/queries/pipeline.py` — canonical query function pattern (read directly)
- `src/ta_lab2/dashboard/queries/trading.py` — live page query pattern with dim_assets join (read directly)
- `src/ta_lab2/dashboard/queries/asset_stats.py` — empty DataFrame fallback pattern (read directly)
- `src/ta_lab2/dashboard/pages/4_asset_stats.py` — engine init + empty state pattern (read directly)
- `src/ta_lab2/dashboard/pages/6_trading.py` — fragment + engine argument pattern (read directly)
- `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` — exact table schema, optimizer names, upsert SQL (read directly)
- `alembic/versions/f6a7b8c9d0e1_portfolio_tables.py` — original `cmc_portfolio_allocations` DDL (read directly)
- `alembic/versions/a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` — confirmed rename to `portfolio_allocations` (grep verified)

### Secondary (MEDIUM confidence)
- `src/ta_lab2/dashboard/pages/3_research_explorer.py` — corroborates engine init pattern (grep verified)
- `src/ta_lab2/dashboard/pages/10_macro.py` — corroborates Phase 85 consistent pattern (grep verified)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries visible in existing page files
- Architecture: HIGH — patterns extracted directly from 4+ existing wired pages
- Table schema: HIGH — DDL in migration + persist function in refresh script both read directly
- Pitfalls: HIGH — derived from concrete code analysis (mock array indexing, optimizer multiplicity, name confusion)

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable codebase, no planned schema changes to portfolio_allocations)
