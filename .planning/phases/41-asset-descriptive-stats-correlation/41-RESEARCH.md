# Phase 41: Asset Descriptive Statistics & Cross-Asset Correlation - Research

**Researched:** 2026-02-24
**Domain:** Rolling time-series statistics + pairwise correlation over cmc_returns_bars_multi_tf
**Confidence:** HIGH (codebase verified, scale measured against live DB, scipy/pandas APIs confirmed)

---

## Summary

This phase adds two new persisted time-series tables: `cmc_asset_stats` (rolling per-asset
descriptive statistics) and `cmc_cross_asset_corr` (pairwise rolling return correlation). Both
tables are computed from `cmc_returns_bars_multi_tf` (`ret_arith`, `roll=FALSE` rows), wired into
`run_daily_refresh.py --all` between the returns stage and the regimes stage.

**Scale (live DB):** 7 assets, 21 pairs, 109 TFs, ~71K total bar rows (roll=FALSE). `cmc_asset_stats`
will hold ~71K rows in wide format. `cmc_cross_asset_corr` will grow to ~6M rows across all TFs and
windows as data accumulates. Manageable with proper indexes and incremental refresh.

**Standard approach:** Pandas `groupby` + `rolling` with native `.mean()`, `.std()`, `.skew()` for
per-asset stats, and `scipy.stats.pearsonr` / `spearmanr` per pair+window for correlation (to get
p-values simultaneously). Rolling max drawdown uses `pandas.rolling.apply()` with a compact numpy
implementation. Alembic migration follows the `stamp-then-forward` pattern already established.

**Primary recommendation:** Wide-format for `cmc_asset_stats` (one row per id, ts, tf — all window
columns present), long-format for `cmc_cross_asset_corr` (PK includes window as a column). Use
pandas native rolling for all stats except max drawdown (requires custom apply) and correlation
p-values (requires scipy per-window call).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | project-installed | Rolling window computation, groupby, DataFrame I/O | Already used throughout |
| numpy | project-installed | Vectorized operations, max drawdown within-window | Already used throughout |
| scipy.stats | project-installed | `pearsonr`, `spearmanr`, `skew`, `kurtosis` | Already used in psr.py, ic.py |
| sqlalchemy | project-installed | DB reads/writes, NullPool engine | Project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| multiprocessing.Pool | stdlib | Parallel per-(id,tf) processing | For correlation computation (TF-level parallelism) |
| DimTimeframe | project | `tf_days_nominal` for annualization | All TF-aware calculations |

### No New Dependencies
Everything needed is already in the project. No additional pip installs required.

**Installation:** None required.

---

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/scripts/desc_stats/
    __init__.py
    refresh_cmc_asset_stats.py          # per-asset rolling stats
    refresh_cmc_cross_asset_corr.py     # pairwise rolling correlation
    run_all_desc_stats_refreshes.py     # orchestrator subprocess

alembic/versions/
    XXXXXXXX_asset_stats_tables.py      # migration for both tables

src/ta_lab2/dashboard/pages/
    4_asset_stats.py                    # new Streamlit page

src/ta_lab2/dashboard/queries/
    asset_stats.py                      # cached query functions
```

### Pattern 1: Wide-Format cmc_asset_stats Table

**What:** One row per `(id, ts, tf)`. All 6 stats x 4 windows stored as flat columns
(e.g., `mean_30`, `mean_60`, `mean_90`, `mean_252`, `std_30`, ...). Plus current-from-ATH
drawdown columns and Rf column.

**When to use:** When rows will be read one at a time per asset/timepoint (dashboard display,
regime feature joins). Wide format eliminates the need for pivots at query time.

**Column naming convention (verified against codebase):**
```
mean_ret_{W}          -- rolling arithmetic mean return, window W bars
std_ret_{W}           -- rolling std dev (ddof=1), window W bars
sharpe_raw_{W}        -- per-bar Sharpe = (mean - rf) / std
sharpe_ann_{W}        -- annualized: sharpe_raw * sqrt(365 / tf_days_nominal)
skew_{W}              -- rolling skewness (Fisher/bias-corrected, same as scipy.stats.skew)
kurt_pearson_{W}      -- rolling Pearson kurtosis (normal=3), scipy kurtosis(fisher=False)
kurt_fisher_{W}       -- rolling Fisher/excess kurtosis (normal=0), pandas .kurt() output
max_dd_window_{W}     -- worst peak-to-trough within trailing W bars
max_dd_from_ath       -- current drawdown from all-time-high up to this bar (not windowed)
rf_rate               -- risk-free rate used for Sharpe (default 0.0, configurable)
ingested_at           -- audit timestamp
```

Windows: 30, 60, 90, 252 bars. NULL when fewer bars than window size available.

**Example:**
```python
# Source: codebase patterns in refresh_returns_zscore.py + psr.py
import pandas as pd
import numpy as np
from scipy.stats import kurtosis, skew

def _rolling_max_drawdown(ret_series: pd.Series, window: int) -> pd.Series:
    """Within-window max drawdown: worst peak-to-trough in trailing W bars."""
    def _mdd(arr):
        if len(arr) < 2:
            return np.nan
        eq = np.cumprod(1 + arr)
        peak = np.maximum.accumulate(eq)
        dd = eq / peak - 1.0
        return dd.min()
    return ret_series.rolling(window=window, min_periods=window).apply(_mdd, raw=True)

def _current_drawdown_from_ath(ret_series: pd.Series) -> pd.Series:
    """Current drawdown from all-time-high up to each bar (expanding window)."""
    eq = (1 + ret_series.fillna(0)).cumprod()
    ath = eq.cummax()
    return eq / ath - 1.0

def compute_asset_stats(df: pd.DataFrame, tf_days: int, windows: list[int], rf: float = 0.0) -> pd.DataFrame:
    """Compute rolling stats for one (id, tf) group, ordered by timestamp."""
    ann_factor = np.sqrt(365.0 / tf_days)
    results = {}

    # Expanding ATH drawdown (not windowed)
    results["max_dd_from_ath"] = _current_drawdown_from_ath(df["ret_arith"])
    results["rf_rate"] = rf

    for w in windows:
        roll = df["ret_arith"].rolling(window=w, min_periods=w)
        mean_r = roll.mean()
        std_r = roll.std(ddof=1)
        excess = mean_r - rf
        sr_raw = excess / std_r.replace(0, np.nan)

        results[f"mean_ret_{w}"] = mean_r
        results[f"std_ret_{w}"] = std_r
        results[f"sharpe_raw_{w}"] = sr_raw
        results[f"sharpe_ann_{w}"] = sr_raw * ann_factor
        results[f"skew_{w}"] = roll.skew()  # pandas native, bias-corrected Fisher skewness
        # CRITICAL: pandas .kurt() returns Fisher/excess (normal=0)
        results[f"kurt_fisher_{w}"] = roll.kurt()
        # Pearson (normal=3) = Fisher + 3 -- derive from fisher to avoid double rolling.apply()
        results[f"kurt_pearson_{w}"] = results[f"kurt_fisher_{w}"] + 3.0
        results[f"max_dd_window_{w}"] = _rolling_max_drawdown(df["ret_arith"], w)

    return pd.DataFrame(results, index=df.index)
```

### Pattern 2: Long-Format cmc_cross_asset_corr Table

**What:** PK `(id_a, id_b, ts, tf, window)`. Each row is one pairwise correlation at one
timestamp for one window. Separate columns for Pearson r, Spearman r, and their p-values.
`id_a < id_b` enforced by CHECK constraint.

**Why long format for correlation:** The window dimension must be in the PK to support
time-series queries like "how has BTC-ETH 90-day correlation evolved?" A wide format would
require a composite PK of (id_a, id_b, ts, tf) and repeated columns per window, making
the CHECK constraint ambiguous and queries harder to filter.

**Example:**
```python
# Source: scipy.stats API + project patterns in ic.py
from scipy.stats import pearsonr, spearmanr
import numpy as np

def compute_pairwise_rolling_corr(
    ret_a: pd.Series,
    ret_b: pd.Series,
    window: int,
    ts_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Compute rolling Pearson + Spearman correlation with p-values.

    Returns DataFrame with columns: pearson_r, pearson_p, spearman_r, spearman_p, n_obs
    NULL when overlap < window.
    """
    results = []
    for i in range(len(ts_index)):
        if i < window - 1:
            results.append((np.nan, np.nan, np.nan, np.nan, np.nan))
            continue
        # Intersection: both must be non-null in this window
        a_slice = ret_a.iloc[i - window + 1 : i + 1]
        b_slice = ret_b.iloc[i - window + 1 : i + 1]
        mask = a_slice.notna() & b_slice.notna()
        a_vals = a_slice[mask].values
        b_vals = b_slice[mask].values
        n = len(a_vals)
        if n < window:  # intersection < full window -> NULL
            results.append((np.nan, np.nan, np.nan, np.nan, n))
            continue
        pr, pp = pearsonr(a_vals, b_vals)
        sr_result = spearmanr(a_vals, b_vals)
        results.append((pr, pp, sr_result.statistic, sr_result.pvalue, n))

    cols = ["pearson_r", "pearson_p", "spearman_r", "spearman_p", "n_obs"]
    return pd.DataFrame(results, index=ts_index, columns=cols)
```

**Performance note:** With 7 assets = 21 pairs, 109 TFs, 4 windows — this is 21 * 109 * 4 = 9,156
combinations. Each combination iterates over ~650 timestamps on average. Total per-row scipy calls
will be large (~6M) but manageable with TF-level multiprocessing. The per-row scipy call in the
inner loop IS the bottleneck — pre-pivot aligned DataFrames and use numpy `corrcoef` for pure
Pearson if p-values are not needed inline.

### Pattern 3: Watermark-Based Incremental Refresh

**What:** State table per script tracks last processed timestamp per (id, tf). On each run:
1. Query state table for last_ts per (id, tf)
2. Load only new rows from cmc_returns_bars_multi_tf where timestamp > last_ts
3. Extend window by loading lookback_bars (max_window=252) before last_ts
4. Recompute from lookback_start onwards
5. DELETE existing rows in that extended range, then INSERT new

**Example state table (follow cmc_returns_bars_multi_tf_state pattern):**
```sql
-- Source: sql/ddl/ddl_cmc_returns_bars_multi_tf.sql
CREATE TABLE public.cmc_asset_stats_state (
    id              integer     NOT NULL,
    tf              text        NOT NULL,
    last_timestamp  timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cmc_asset_stats_state_pk PRIMARY KEY (id, tf)
);
```

### Anti-Patterns to Avoid
- **Full recompute on every run:** Use watermarks. With 71K rows today and growing, full recompute
  could be slow when data accumulates.
- **Long format for asset stats:** Wide format eliminates a 4x row explosion and avoids pivot
  queries in regime pipeline joins.
- **Storing Pearson kurtosis by calling scipy.stats.kurtosis separately in rolling.apply():**
  pandas .kurt() gives Fisher; add 3.0 for Pearson. Do NOT use rolling.apply(scipy.stats.kurtosis)
  -- it's 50-100x slower than the native rolling method.
- **Using `df.rolling().corr(pairwise=True)` for correlation with p-values:** pandas rolling.corr
  does NOT provide p-values. Must use scipy per-window for p-values (the requirement says store them).
- **Mixing NULL policy:** For stats, NULL until full window (no min_periods < window). For
  correlation, NULL when intersection count < window size.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rolling skewness | Custom rolling skew | `pandas.Series.rolling(w).skew()` | Vectorized C extension, matches scipy output |
| Fisher kurtosis | Custom rolling kurt | `pandas.Series.rolling(w).kurt()` | Native, bias-corrected, matches scipy kurtosis(fisher=True, bias=False) |
| Pearson kurtosis from scratch | Custom roll.apply(kurtosis) | `.kurt() + 3.0` | 50-100x faster; mathematically identical |
| DB column discovery | Hard-coded column lists | `sync_utils.get_columns()` | Already handles schema drift, used throughout project |
| DB URL resolution | Custom config reading | `refresh_utils.resolve_db_url()` | Project standard |
| TF days lookup | Direct SQL query each time | `get_tf_days(tf, db_url)` from `dim_timeframe.py` | Caches dim_timeframe per process |
| NullPool engine | Custom connection pool | `create_engine(url, poolclass=NullPool)` | Required for multiprocessing workers |
| Alembic migration boilerplate | Custom schema management | Existing alembic pattern (see versions/) | Project standard, handles stamp-then-forward |

**Key insight:** The kurtosis calculation is the most common performance trap. `rolling.apply()`
with scipy breaks vectorization; native `.kurt()` is orders of magnitude faster. Store Fisher from
native rolling, derive Pearson by adding 3.0.

---

## Common Pitfalls

### Pitfall 1: pandas rolling.kurt() Definition (Fisher, not Pearson)
**What goes wrong:** Developer stores `rolling.kurt()` output thinking it is Pearson kurtosis
(normal=3). It is Fisher/excess kurtosis (normal=0). Phase 36 PSR uses Pearson (`fisher=False`
in scipy). If both tables use different conventions without labeling, downstream comparisons break.

**Why it happens:** The docstring says "Fisher's definition without bias" which is ambiguous to
those unfamiliar with the convention difference.

**How to avoid:** Store BOTH as decided. Column names make it explicit:
- `kurt_fisher_{W}` = pandas rolling.kurt() output (normal=0)
- `kurt_pearson_{W}` = kurt_fisher_{W} + 3.0 (normal=3, consistent with psr.py)

**Warning signs:** Values near 0 for normal-looking data (Fisher) vs values near 3 (Pearson).

### Pitfall 2: Correlation Window Intersection NULL Policy
**What goes wrong:** Computing correlation on windows where one asset has gaps (NULL ret_arith).
The pandas rolling approach masks this issue; scipy pearsonr on arrays with NaN returns NaN.

**Why it happens:** Not all assets have the same trading history. BTC has 5613 1D bars; a newer
asset might have 500. Cross-asset correlation computed before both assets have data is meaningless.

**How to avoid:** For each rolling window, count non-null intersection. If count < window, output NULL.
Set `pearson_r = spearman_r = pearson_p = spearman_p = NULL, n_obs = actual_intersection_count`.

**Warning signs:** Correlation values with n_obs < window stored as non-NULL.

### Pitfall 3: Max Drawdown Direction Convention
**What goes wrong:** Max drawdown stored as positive number (percentage decline) vs negative number
(fraction below peak). The existing `performance.py` function returns a negative fraction.

**Why it happens:** Different financial libraries use different sign conventions.

**How to avoid:** Follow existing project convention from `performance.py::max_drawdown()` which
returns negative fractions (`dd = e / peak - 1.0`). Both `max_dd_window_{W}` and `max_dd_from_ath`
should be negative numbers (or NULL). Document in DDL comment.

### Pitfall 4: Annualization Factor Source
**What goes wrong:** Using `tf_days` column from `cmc_returns_bars_multi_tf` (integer, actual
bar length) instead of `tf_days_nominal` from `dim_timeframe`. Actual bar lengths vary; nominal is
the canonical annualization basis.

**Why it happens:** The returns table has a `tf_days` column that looks authoritative.

**How to avoid:** Always use `DimTimeframe.tf_days()` which returns `tf_days_nominal`. The project
MEMORY.md explicitly flags this: "Column is `tf_days_nominal` (NOT `tf_days`)".

**Code:** `ann_factor = np.sqrt(365.0 / get_tf_days(tf, db_url))`

### Pitfall 5: Canonical Pair Ordering in Correlation Table
**What goes wrong:** Both (id_a=1, id_b=52) and (id_a=52, id_b=1) rows stored, doubling the table
and causing JOIN ambiguity in dashboard queries.

**Why it happens:** Without enforcement, whatever order assets are iterated produces both.

**How to avoid:** Add CHECK constraint: `CONSTRAINT chk_pair_order CHECK (id_a < id_b)`. Enforce
in Python: `id_a, id_b = min(a_id, b_id), max(a_id, b_id)` before INSERT. Dashboard queries
must check both directions with `WHERE (id_a = :x AND id_b = :y) OR (id_a = :y AND id_b = :x)`.

### Pitfall 6: run_daily_refresh.py Stage Position
**What goes wrong:** Adding desc stats AFTER regimes instead of BEFORE. Regimes are intended to
consume rolling stats as inputs in future enhancement.

**Why it happens:** Looking at existing pipeline order (bars -> EMAs -> AMAs -> regimes -> stats)
and placing desc stats at the end with "stats".

**How to avoid:** Insert desc stats as a new stage BETWEEN AMAs and regimes. The `--all` flow
becomes: bars -> EMAs -> AMAs -> desc_stats -> regimes -> stats. The `--desc-stats` flag is
separate from `--stats` (which runs data quality checks).

### Pitfall 7: Table Format Decision for Correlation
**What goes wrong:** Choosing wide format (columns: `pearson_r_30`, `pearson_r_60`, etc.) for
correlation, forcing `(id_a, id_b, ts, tf)` as PK. This makes windowed time-series queries
harder and prevents adding new windows without ALTER TABLE.

**Why it happens:** Wide format seems natural coming from asset_stats design.

**How to avoid:** Use long format for correlation with `window` as PK column. This enables:
- `WHERE window = 90` for dashboard filtering
- Adding windows later without schema change
- Clean indexing on `(id_a, id_b, tf, window)` for time-series queries

### Pitfall 8: Windows vs Bash on Windows for Path Handling
**What goes wrong:** SQL migration files with UTF-8 characters fail on Windows with cp1252 encoding.

**Why it happens:** Project MEMORY.md explicitly flags: "UTF-8 box-drawing chars (===) in SQL
comments cause UnicodeDecodeError with default cp1252 encoding."

**How to avoid:** Use `open(file, encoding='utf-8')` when reading SQL files. Keep Alembic
migrations as Python files (not raw SQL files) to avoid this entirely -- the existing migration
pattern uses `op.create_table()` in Python, which is already the correct approach.

---

## Code Examples

### Alembic Migration Pattern (verified against existing versions/)
```python
# Source: alembic/versions/c3b718c2d088_ic_results_table.py + 5f8223cfbf06_psr_results_table.py
from alembic import op
import sqlalchemy as sa

revision: str = "XXXXXXXX"  # generated by `alembic revision`
down_revision = "6f82e9117c58"  # current head

def upgrade() -> None:
    op.create_table(
        "cmc_asset_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        # Stats columns: 6 stats x 4 windows = 24 stat columns + 4 Sharpe ann columns
        # + 2 drawdown columns + rf_rate + ingested_at
        sa.Column("rf_rate", sa.Numeric(), nullable=True),
        # Window 30
        sa.Column("mean_ret_30", sa.Numeric(), nullable=True),
        sa.Column("std_ret_30", sa.Numeric(), nullable=True),
        sa.Column("sharpe_raw_30", sa.Numeric(), nullable=True),
        sa.Column("sharpe_ann_30", sa.Numeric(), nullable=True),
        sa.Column("skew_30", sa.Numeric(), nullable=True),
        sa.Column("kurt_fisher_30", sa.Numeric(), nullable=True),
        sa.Column("kurt_pearson_30", sa.Numeric(), nullable=True),
        sa.Column("max_dd_window_30", sa.Numeric(), nullable=True),
        # ... repeat for 60, 90, 252 ...
        sa.Column("max_dd_from_ath", sa.Numeric(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "ts", "tf", name="cmc_asset_stats_pk"),
        schema="public",
    )
    op.create_index(
        "idx_asset_stats_id_tf_ts",
        "cmc_asset_stats",
        ["id", "tf", "ts"],
        schema="public",
    )

    op.create_table(
        "cmc_cross_asset_corr",
        sa.Column("id_a", sa.Integer(), nullable=False),
        sa.Column("id_b", sa.Integer(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("pearson_r", sa.Numeric(), nullable=True),
        sa.Column("pearson_p", sa.Numeric(), nullable=True),
        sa.Column("spearman_r", sa.Numeric(), nullable=True),
        sa.Column("spearman_p", sa.Numeric(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id_a", "id_b", "ts", "tf", "window",
                                name="cmc_cross_asset_corr_pk"),
        sa.CheckConstraint("id_a < id_b", name="chk_corr_pair_order"),
        schema="public",
    )
    op.create_index(
        "idx_corr_pair_tf_window_ts",
        "cmc_cross_asset_corr",
        ["id_a", "id_b", "tf", "window", "ts"],
        schema="public",
    )
```

### run_daily_refresh.py Integration Pattern
```python
# Source: run_daily_refresh.py structure (existing pattern)
# New stage: desc_stats runs AFTER AMAs, BEFORE regimes

# In pipeline flow (after AMAs, before regimes):
if run_desc_stats:
    desc_result = run_desc_stats_refresher(args, db_url, parsed_ids)
    results.append(("desc_stats", desc_result))
    if not desc_result.success and not args.continue_on_error:
        return 1

if run_regimes:
    regime_result = run_regime_refresher(args, db_url, parsed_ids)
    ...

# New CLI flags (add to argparse):
p.add_argument("--desc-stats", action="store_true",
               help="Run desc stats refresh only")
# In --all: run_desc_stats = args.desc_stats or args.all
```

### Materialized Latest Correlation View
```sql
-- Latest correlation snapshot for dashboard fast queries
-- Refresh daily after cmc_cross_asset_corr insert completes
CREATE MATERIALIZED VIEW public.cmc_corr_latest AS
SELECT DISTINCT ON (id_a, id_b, tf, window)
    id_a, id_b, ts, tf, window,
    pearson_r, pearson_p, spearman_r, spearman_p, n_obs
FROM public.cmc_cross_asset_corr
ORDER BY id_a, id_b, tf, window, ts DESC;

CREATE UNIQUE INDEX ON public.cmc_corr_latest (id_a, id_b, tf, window);
-- Refresh: REFRESH MATERIALIZED VIEW CONCURRENTLY public.cmc_corr_latest;
```

### Dashboard Heatmap Pattern
```python
# Source: dashboard patterns in charts.py + research.py
import plotly.graph_objects as go
import pandas as pd

def build_correlation_heatmap(corr_df: pd.DataFrame, symbols: list[str]) -> go.Figure:
    """Build correlation heatmap from latest correlation snapshot."""
    # Pivot to N x N matrix (fill diagonal with 1.0)
    n = len(symbols)
    mat = pd.DataFrame(1.0, index=symbols, columns=symbols)
    for _, row in corr_df.iterrows():
        sym_a = symbols[row["id_a"]]
        sym_b = symbols[row["id_b"]]
        mat.loc[sym_a, sym_b] = float(row["pearson_r"])
        mat.loc[sym_b, sym_a] = float(row["pearson_r"])  # symmetric

    fig = go.Figure(go.Heatmap(
        z=mat.values,
        x=mat.columns.tolist(),
        y=mat.index.tolist(),
        colorscale="RdBu",
        zmid=0,
        zmin=-1, zmax=1,
        text=mat.round(2).values,
        texttemplate="%{text}",
    ))
    fig.update_layout(template="plotly_dark", title="Cross-Asset Correlation")
    return fig
```

### Regime Wiring Pattern
```python
# Source: refresh_cmc_regimes.py + regime_data_loader.py pattern
# Wire rolling stats as optional inputs to regime labeling

def load_rolling_stats_for_asset(
    engine, asset_id: int, tf: str
) -> pd.DataFrame | None:
    """Load latest rolling stats for regime feature augmentation."""
    sql = text("""
        SELECT ts, std_ret_30, std_ret_90, sharpe_ann_90, max_dd_from_ath
        FROM public.cmc_asset_stats
        WHERE id = :id AND tf = :tf
        ORDER BY ts
    """)
    with engine.begin() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")
```

---

## Table Design Decisions (Claude's Discretion Areas Resolved)

### Table Format: Wide for Asset Stats, Long for Correlation

**cmc_asset_stats: WIDE** (one row per id, ts, tf)
- Rationale: Regime pipeline joins will read one stat row per bar. Wide format avoids groupby/pivot.
- With 6 stats x 4 windows = ~28 columns total (plus 2 drawdown, rf_rate, ingested_at), the
  table is wide but not extreme. PostgreSQL handles 50+ columns fine.
- Query pattern: `SELECT std_ret_90, sharpe_ann_90 FROM cmc_asset_stats WHERE id=1 AND tf='1D'`

**cmc_cross_asset_corr: LONG** (one row per id_a, id_b, ts, tf, window)
- Rationale: Window is a filter dimension, not just a data dimension. Long enables `WHERE window=90`.
- Scale is manageable: ~6M rows across all TFs, grows incrementally.

### Script Split: Two Separate Scripts

**Use separate scripts** for asset stats and correlation:
1. `refresh_cmc_asset_stats.py` - per-asset computation, parallelizable by (id, tf)
2. `refresh_cmc_cross_asset_corr.py` - pairwise computation, parallelizable by tf

Reasons:
- Fundamentally different data shapes (per-asset vs per-pair)
- Independent failure domains (stats failing shouldn't block correlation)
- Different watermark state tables
- Correlation depends on asset stats being fresh (natural sequencing)

Both are orchestrated by `run_all_desc_stats_refreshes.py`.

### Spearman Validation

**Decision: Keep Spearman.** Evidence:
- Crypto returns are fat-tailed (kurtosis well above 3), violating Pearson's normality assumptions
- Spearman is rank-based and robust to extreme outlier returns
- The cost is 2x scipy calls per window but scipy.stats.spearmanr is fast
- Storing both gives analysts the choice; p-values for both are meaningful
- Phase 36 PSR already uses scipy for moments — precedent for scipy in this codebase

### Quality Check Approach

**Extend existing stats runner infrastructure** (`src/ta_lab2/scripts/stats/`). Add:
- `src/ta_lab2/scripts/stats/run_desc_stats_checks.py` - quality checks for new tables
- Register new tables in `run_all_stats_runners.py::STATS_TABLES`

Checks to implement:
- PK uniqueness on both tables
- NULL fraction per window (warm-up rows should be NULL, mature rows should not)
- Mean return plausibility (|mean_ret_252| < 0.1 for most crypto assets)
- Pair order check (id_a < id_b, 0 violations expected)
- Correlation bounds check (-1 <= pearson_r <= 1)

### Materialized View Refresh Strategy

**On-demand refresh at end of correlation script run.** Call:
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY public.cmc_corr_latest;
```
at the end of `refresh_cmc_cross_asset_corr.py` after INSERT completes. No trigger, no scheduled
job. This matches project simplicity — scripts know when their data is fresh.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| scipy.stats.kurtosis in rolling.apply() | pandas .kurt() + 3.0 | Always was faster | 50-100x speedup |
| pandas rolling.corr(pairwise=True) | scipy.stats.pearsonr per window | N/A | Required for p-values |
| Wide correlation table | Long correlation with window column | Design decision | Easier window filtering |
| Full recompute daily | Watermark-based incremental | Project pattern | Scales with data growth |

**Deprecated/outdated:**
- `pandas.rolling.corr()` for this use case: No p-values, can't be filtered by window without pivot.
  Use scipy per-window instead.

---

## Open Questions

1. **Spearman for short-window correlation (30-bar)**
   - What we know: 30 bars is the minimum; Spearman is rank-based so less sensitive to outliers
   - What's unclear: Whether 30-bar Spearman is stable enough to store meaningfully
   - Recommendation: Store it with `n_obs` so downstream consumers can filter to n_obs >= 30

2. **Regime wiring specifics**
   - What we know: Context says "substantial integration" — actual code changes to regime pipeline
   - What's unclear: Which rolling stats are most relevant (std_ret as vol proxy? sharpe_ann?)
   - Recommendation: Plan task to add `load_rolling_stats_for_asset()` in regime_data_loader.py,
     then wire as optional augmentation columns in `label_layer_daily()` inputs. Flag `regime_stats_enabled`

3. **Correlation for short-lived assets (< window bars)**
   - What we know: NULL until intersection >= window
   - What's unclear: Should state table track per-(id_a, id_b, tf) watermarks?
   - Recommendation: Use per-(id_a, id_b, tf) watermarks — same pattern as asset stats state table

4. **Current DB head: 6f82e9117c58 (feature_experiment_tables)**
   - Phase 41 migration chains from this head
   - Migration creates both cmc_asset_stats and cmc_cross_asset_corr in one revision
     (and associated state tables + materialized view)

---

## Sources

### Primary (HIGH confidence)
- Codebase: `src/ta_lab2/scripts/returns/refresh_returns_zscore.py` - rolling pattern, NullPool, watermark
- Codebase: `src/ta_lab2/backtests/psr.py` - Pearson vs Fisher kurtosis convention (fisher=False)
- Codebase: `src/ta_lab2/analysis/ic.py` - scipy.stats.spearmanr usage with p-values
- Codebase: `src/ta_lab2/scripts/run_daily_refresh.py` - subprocess pattern, stage insertion
- Codebase: `alembic/versions/c3b718c2d088_ic_results_table.py` - Alembic migration pattern
- Codebase: `src/ta_lab2/time/dim_timeframe.py` - tf_days_nominal lookup
- Codebase: `sql/ddl/ddl_cmc_returns_bars_multi_tf.sql` - source table schema
- Live DB: 7 assets, 21 pairs, 109 TFs, 71,017 bar rows (roll=FALSE) - scale verified
- Live DB: Alembic current head = `6f82e9117c58`
- scipy.stats.pearsonr docs: Returns PearsonRResult with .statistic and .pvalue
- scipy.stats.spearmanr docs: Returns SignificanceResult with .statistic and .pvalue

### Secondary (MEDIUM confidence)
- WebSearch verified with pandas docs: pandas rolling.kurt() uses Fisher definition (normal=0)
- WebSearch verified: pandas native rolling.skew()/.kurt() faster than rolling.apply(scipy_fn)
- pandas docs: rolling.corr() lacks p-values — confirmed scipy required

### Tertiary (LOW confidence)
- WebSearch (single source): Spearman more appropriate for multiplicative crypto returns
  than Pearson -- plausible but not authoritatively verified for this specific dataset

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in project, APIs verified
- Table schemas: HIGH - scale measured against live DB, DDL patterns from codebase
- Architecture: HIGH - patterns directly from existing scripts
- Statistical formulas: HIGH - verified against psr.py, ic.py, and scipy docs
- Pitfalls: HIGH - kurtosis convention verified against docs and psr.py comment, others from code

**Research date:** 2026-02-24
**Valid until:** 2026-03-24 (stable domain; pandas/scipy APIs do not change frequently)
