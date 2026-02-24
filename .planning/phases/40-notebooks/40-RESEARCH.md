# Phase 40: Notebooks - Research

**Researched:** 2026-02-24
**Domain:** Jupyter notebooks consuming ta_lab2 analysis/ML infrastructure
**Confidence:** HIGH

---

## Summary

Phase 40 builds 3 polished Jupyter notebooks that are pure consumers of existing
infrastructure. All required Python modules, DB tables, and data are already in
place. The research focus was on exact import paths, live table/data state, known
Jupyter/SQLAlchemy pitfalls on Windows, and how to structure split visualizations
and regime A/B comparisons.

The standard Python environment (system Python 3.12 at `C:\Program Files\Python312`)
has all required libraries installed. The project venv at `.venv/` is empty (only
pip). Notebooks must use the system Python kernel or set `sys.path` to import
`ta_lab2` from `src/`.

Key constraint discovered: `cmc_ama_multi_tf` table does not yet exist in the
database (state table has 0 rows). Notebook 1 must compute AMA values from
`cmc_price_bars_multi_tf` directly using the computation functions, not query
from a pre-populated AMA table. The `cmc_features` table (5,614 rows for id=1,
1D) and `cmc_regimes` (5,614 rows) are fully populated and ready.

**Primary recommendation:** Place notebooks in `notebooks/` at project root,
with a shared `notebooks/helpers.py` module. Each notebook adds `src/` to
`sys.path` in the first setup cell rather than relying on the venv installation.

---

## Standard Stack

### Core (already installed, system Python 3.12)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.3.3 | DataFrames, Styler, timestamp handling | Core data layer |
| numpy | 2.4.1 | Arrays for AMA computation | Required by all |
| plotly | 6.4.0 | Interactive IC decay, rolling IC, regime charts | Already used in Phase 37 |
| matplotlib | 3.10.0 | Static split visualization, distributions | Best for grid/heatmap plots |
| scipy | 1.17.0 | Spearman IC, BH correction (used inside ic.py) | Already a dep |
| scikit-learn | 1.8.0 | BaseCrossValidator base (used inside cv.py) | Already a dep |
| vectorbt | 0.28.1 | Backtest execution for regime A/B | Already integrated |
| sqlalchemy | 2.x | DB connections via NullPool | Standard project pattern |
| streamlit | 1.44.0 | Dashboard launch cell in Notebook 3 | Already deployed |

### Not yet installed (needs adding to requirements or pip install cell)

| Library | Purpose | Install |
|---------|---------|---------|
| jupyter / jupyterlab | Run the notebooks | `pip install jupyterlab` |
| seaborn | Correlation heatmaps, distribution plots | `pip install seaborn` |
| ipykernel | Connect system Python to Jupyter | `pip install ipykernel` |

**Installation:**
```bash
pip install jupyterlab seaborn ipykernel
python -m ipykernel install --user --name ta_lab2 --display-name "ta_lab2"
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| matplotlib for split viz | plotly for split viz | matplotlib is simpler for the horizontal bar grid; plotly adds no value here |
| seaborn for heatmaps | plotly heatmaps | seaborn is cleaner for correlation matrices; plotly heatmaps are interactive but heavier |
| subprocess.Popen for Streamlit | os.system | Popen is non-blocking and returns a handle; os.system blocks the notebook |

---

## Architecture Patterns

### Recommended Project Structure
```
ta_lab2/
├── notebooks/
│   ├── helpers.py              # Shared DB connection, data loading, styling
│   ├── 01_explore_indicators.ipynb
│   ├── 02_evaluate_features.ipynb
│   └── 03_run_experiments.ipynb
└── configs/
    └── experiments/
        └── features.yaml       # Registry for Notebook 3
```

### Pattern 1: Notebook Setup Cell (first code cell in every notebook)

Every notebook's first code cell must establish the path before any ta_lab2
imports, because the package is not installed in the venv.

```python
# --- Setup (run this cell first) ---
import sys
from pathlib import Path

# Add src/ to path so ta_lab2 package is importable
_ROOT = Path.cwd().parent  # assumes notebook is in notebooks/
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# Verify
import ta_lab2  # noqa
print(f"ta_lab2 loaded from: {ta_lab2.__file__}")
```

### Pattern 2: Shared Helpers Module (`notebooks/helpers.py`)

```python
# notebooks/helpers.py
"""Shared helpers for ta_lab2 research notebooks."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from ta_lab2.scripts.refresh_utils import resolve_db_url


def get_engine():
    """Return a NullPool SQLAlchemy engine. Call once per notebook."""
    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=NullPool)


def load_features(engine, asset_id: int, tf: str, start: str, end: str) -> pd.DataFrame:
    """Load cmc_features for an asset/TF window. Returns ts-indexed DataFrame."""
    sql = text("""
        SELECT *
        FROM public.cmc_features
        WHERE id = :id AND tf = :tf
          AND ts >= :start AND ts <= :end
        ORDER BY ts
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf,
                                             "start": start, "end": end})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)  # Windows tz fix
    return df.set_index("ts")


def load_price_bars(engine, asset_id: int, tf: str, start: str, end: str) -> pd.DataFrame:
    """Load OHLCV from cmc_price_bars_multi_tf."""
    sql = text("""
        SELECT ts, open, high, low, close, volume
        FROM public.cmc_price_bars_multi_tf
        WHERE id = :id AND tf = :tf
          AND ts >= :start AND ts <= :end
        ORDER BY ts
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf,
                                             "start": start, "end": end})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")


def validate_asset_data(engine, asset_id: int, tf: str, min_days: int = 365) -> dict:
    """
    Pre-validate that the asset has sufficient data in asset_data_coverage.
    Returns dict with keys: valid, n_days, first_ts, last_ts, message.
    """
    sql = text("""
        SELECT n_days, first_ts, last_ts
        FROM public.asset_data_coverage
        WHERE id = :id AND granularity = :tf
        LIMIT 1
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})
    if df.empty:
        return {"valid": False, "message": f"No coverage data for id={asset_id} tf={tf}"}
    row = df.iloc[0]
    valid = int(row["n_days"]) >= min_days
    return {
        "valid": valid,
        "n_days": int(row["n_days"]),
        "first_ts": row["first_ts"],
        "last_ts": row["last_ts"],
        "message": "OK" if valid else f"Only {row['n_days']} days (need {min_days})"
    }


def style_ic_table(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """Apply color gradient to IC column in a results table."""
    return (
        df.style
        .background_gradient(cmap="RdYlGn", subset=["ic"], vmin=-0.1, vmax=0.1)
        .format({"ic": "{:.4f}", "ic_p_value": "{:.4f}", "n_obs": "{:,d}"})
    )
```

### Pattern 3: Parameter Cell (second cell, one per notebook)

```python
# --- Parameters (change these to explore different assets/timeframes) ---
ASSET_ID = 1       # BTC; try 2 for ETH
TF = "1D"          # Primary timeframe; try "1W" for weekly
START_DATE = "2021-01-01"
END_DATE = "2025-12-31"

# Alternative: latest N bars
# import pandas as pd
# END_DATE = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
# START_DATE = (pd.Timestamp.utcnow() - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
```

### Pattern 4: AMA Computation from Scratch (Notebook 1)

`cmc_ama_multi_tf` does NOT exist in the database. Compute AMAs on-the-fly from
price bars using the computation functions directly.

```python
# Source: ta_lab2/features/ama/ama_computations.py
from ta_lab2.features.ama.ama_computations import compute_ama

# Load price bars first
bars = load_price_bars(engine, ASSET_ID, TF, START_DATE, END_DATE)
close = bars["close"]

# Compute all 4 AMA types
kama, er = compute_ama(close, "KAMA", {"er_period": 10, "fast_period": 2, "slow_period": 30})
dema, _  = compute_ama(close, "DEMA", {"period": 21})
tema, _  = compute_ama(close, "TEMA", {"period": 21})
hma,  _  = compute_ama(close, "HMA",  {"period": 21})

# Build a combined DataFrame for charting
ama_df = pd.DataFrame({
    "close": close,
    "KAMA(10,2,30)": kama,
    "DEMA(21)": dema,
    "TEMA(21)": tema,
    "HMA(21)": hma,
})
```

### Pattern 5: IC Evaluation (Notebook 2)

```python
# Source: ta_lab2/analysis/ic.py
from ta_lab2.analysis.ic import (
    compute_ic, batch_compute_ic, compute_rolling_ic,
    load_feature_series, load_regimes_for_asset,
    plot_ic_decay, plot_rolling_ic
)

train_start = pd.Timestamp(START_DATE, tz="UTC")
train_end   = pd.Timestamp(END_DATE,   tz="UTC")

# Single feature
with engine.connect() as conn:
    feature, close = load_feature_series(
        conn, ASSET_ID, TF, "rsi_14", train_start, train_end
    )

ic_df = compute_ic(
    feature, close, train_start, train_end,
    horizons=[1, 2, 3, 5, 10, 20, 60],
    return_types=["arith", "log"],
    tf_days_nominal=1,
)

# IC decay chart (Plotly)
fig = plot_ic_decay(ic_df, "rsi_14", return_type="arith", sig_threshold=0.05)
fig.show()

# Rolling IC
rolling_ic, ic_ir, ic_ir_tstat = compute_rolling_ic(
    feature, compute_forward_returns(close, horizon=5), window=63
)
fig2 = plot_rolling_ic(rolling_ic, "rsi_14", horizon=5, return_type="arith")
fig2.show()
```

### Pattern 6: Purged K-Fold Visualization (Notebook 2)

The split visualization uses matplotlib horizontal bars. Each row is a fold;
color shows test/purged/embargo regions; white is train.

```python
# Source: ta_lab2/backtests/cv.py
from ta_lab2.backtests.cv import PurgedKFoldSplitter
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# Build t1 series: label_start -> label_end (5-bar forward return horizon)
HORIZON = 5
t1 = pd.Series(
    feature.index + pd.Timedelta(days=HORIZON),
    index=feature.index
)
t1 = t1[t1.index.is_monotonic_increasing]

N_SPLITS = 5
splitter = PurgedKFoldSplitter(n_splits=N_SPLITS, t1_series=t1, embargo_frac=0.01)
X = feature.values.reshape(-1, 1)

fig, ax = plt.subplots(figsize=(14, 4))
FOLD_COLORS = ["#1976D2", "#388E3C", "#F57C00", "#D32F2F", "#7B1FA2"]

for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X)):
    n = len(feature)
    all_idx = set(range(n))
    test_set = set(test_idx.tolist())
    train_set = set(train_idx.tolist())
    purged_set = all_idx - test_set - train_set

    for idx in test_idx:
        ax.barh(fold_idx, 1, left=idx, height=0.5,
                color=FOLD_COLORS[fold_idx], alpha=0.9)
    for idx in purged_set:
        ax.barh(fold_idx, 1, left=idx, height=0.5, color="#EF9A9A", alpha=0.7)

ax.set_yticks(range(N_SPLITS))
ax.set_yticklabels([f"Fold {i}" for i in range(N_SPLITS)])
ax.set_xlabel("Bar Index")
ax.set_title("Purged K-Fold Split — test (colored), purged/embargo (red), train (white)")
legend_patches = [
    mpatches.Patch(color=c, label=f"Fold {i} test") for i, c in enumerate(FOLD_COLORS)
] + [mpatches.Patch(color="#EF9A9A", label="Purged/Embargo")]
ax.legend(handles=legend_patches, loc="upper right", ncol=3, fontsize=8)
plt.tight_layout()
plt.show()
```

### Pattern 7: Regime A/B Backtest Comparison (Notebook 2)

Use existing signal generators with regime context. The `regime_enabled` flag
controls whether `load_regime_context_batch` merges regime policy into the
feature DataFrame before signal generation.

```python
# Source: ta_lab2/scripts/signals/generate_signals_ema.py
# Source: ta_lab2/scripts/signals/regime_utils.py
from ta_lab2.scripts.signals.regime_utils import load_regime_context_batch, merge_regime_context
from ta_lab2.signals.ema_trend import make_signals as ema_make_signals
from ta_lab2.backtests.vbt_runner import run_vbt_on_split, CostModel, Split

# Load features (must include EMA columns from cmc_ema_multi_tf_u via LEFT JOIN)
features_df = load_features(engine, ASSET_ID, TF, START_DATE, END_DATE)

# Run WITHOUT regime filter
entries_base, exits_base, size_base = ema_make_signals(
    features_df,
    fast_ema="close_ema_9",   # from cmc_ema_multi_tf_u joined into features
    slow_ema="close_ema_21",
)

# Run WITH regime filter (manually merge, then gate on orders != 'none')
regime_df = load_regime_context_batch(engine, [ASSET_ID], tf=TF)
features_regime = merge_regime_context(features_df.reset_index(), regime_df)
features_regime = features_regime.set_index("ts")

# Apply regime gate: block entries where orders = 'none'
entries_regime = entries_base & (features_regime["orders"].fillna("mixed") != "none")

# Run both backtests
cost = CostModel(fee_bps=5, slippage_bps=5)
split = Split("full", pd.Timestamp(START_DATE, tz="UTC"), pd.Timestamp(END_DATE, tz="UTC"))

result_base   = run_vbt_on_split(features_df, entries_base,   exits_base, size_base,   cost, split)
result_regime = run_vbt_on_split(features_df, entries_regime, exits_base, size_base, cost, split)

# Compare
comparison = pd.DataFrame([
    {"strategy": "No Regime Filter", "sharpe": result_base.sharpe,   "mdd": result_base.mdd,   "trades": result_base.trades},
    {"strategy": "Regime Filter",    "sharpe": result_regime.sharpe, "mdd": result_regime.mdd, "trades": result_regime.trades},
])
```

### Pattern 8: Feature Experimentation (Notebook 3)

```python
# Source: ta_lab2/experiments/__init__.py
# Source: ta_lab2/experiments/runner.py
from ta_lab2.experiments import FeatureRegistry, ExperimentRunner, resolve_experiment_dag

REGISTRY_PATH = "../configs/experiments/features.yaml"  # relative to notebooks/

registry = FeatureRegistry(REGISTRY_PATH)
registry.load()

# Show all experimental features
experimental = registry.list_experimental()
print(f"Experimental features: {experimental}")

# Resolve DAG order
ordered = resolve_experiment_dag(registry.list_all())
print(f"Computation order: {ordered}")

# Run one experiment
runner = ExperimentRunner(registry, engine)  # engine is NullPool engine
result_df = runner.run(
    "vol_ratio_30_7",
    asset_ids=[ASSET_ID],
    tf=TF,
    train_start=pd.Timestamp(START_DATE, tz="UTC"),
    train_end=pd.Timestamp(END_DATE,     tz="UTC"),
    horizons=[1, 5, 20],
    dry_run=True,  # True in demo: no scratch table writes
)
```

### Pattern 9: Streamlit Dashboard Launch (Notebook 3)

```python
import subprocess, sys, os, time

# Launch Streamlit in background subprocess
proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run",
     str(Path.cwd().parent / "src" / "ta_lab2" / "dashboard" / "app.py"),
     "--server.headless", "true"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(Path.cwd().parent),  # run from project root
)
time.sleep(2)

if proc.poll() is None:
    print("Dashboard launched at http://localhost:8501")
    print("To stop: proc.terminate()")
else:
    print("ERROR: Dashboard failed to start")
    print(proc.stderr.read().decode())
```

### Anti-Patterns to Avoid

- **Importing from venv without sys.path fix:** The venv only has pip; import
  will fail. Always set `sys.path` in the first cell.
- **Querying cmc_ama_multi_tf:** Table does not exist in DB. Compute AMAs from
  `cmc_price_bars_multi_tf` using `compute_ama()`.
- **Using `series.values` on tz-aware timestamps:** Returns tz-naive numpy on
  Windows. Use `.tolist()` or pandas operations for tz-aware datetime work.
- **Setting `pio.renderers.default` globally:** Not needed in Jupyter; plotly
  auto-detects. Only set if charts fail to render.
- **Using connection pooling (default pool):** Always use `NullPool` in notebooks,
  same as scripts. SQLAlchemy default pool causes "too many clients" in
  multiprocessing contexts and leaks connections.
- **Not calling `conn.commit()` after ExperimentRunner.run():** The runner commits
  its own scratch table writes, but if notebooks do manual INSERT/UPDATE they must
  commit explicitly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| AMA computation | Custom KAMA/DEMA/TEMA/HMA functions | `ta_lab2.features.ama.ama_computations.compute_ama()` | Already correct with warmup guards and alpha conventions |
| IC calculation | Custom Spearman + boundary masking | `ta_lab2.analysis.ic.compute_ic()` | Handles look-ahead bias, boundary masking, IC-IR, turnover |
| IC decay chart | Custom plotly bar chart | `ta_lab2.analysis.ic.plot_ic_decay()` | Significance coloring, p-value annotations built in |
| Rolling IC chart | Custom plotly line chart | `ta_lab2.analysis.ic.plot_rolling_ic()` | Zero reference line, proper formatting |
| Purged K-fold splits | Custom purge/embargo logic | `ta_lab2.backtests.cv.PurgedKFoldSplitter` | Correctly handles tz-aware timestamps, purge, embargo |
| DB URL resolution | Custom env parsing | `ta_lab2.scripts.refresh_utils.resolve_db_url()` | Searches db_config.env + env vars in correct priority order |
| Regime loading | Custom SQL for l2_label | `ta_lab2.analysis.ic.load_regimes_for_asset()` | Handles split_part() parsing of trend_state/vol_state |
| Feature experiment run | Custom IC + BH correction | `ta_lab2.experiments.ExperimentRunner.run()` | BH correction across all hypotheses simultaneously |

**Key insight:** Every analytical primitive is already implemented. Notebooks
are wiring code + narrative, not computation code.

---

## Common Pitfalls

### Pitfall 1: Missing Jupyter/seaborn in project venv

**What goes wrong:** Notebooks cannot run because `jupyter`, `seaborn`,
`ipykernel` are not installed in the project venv (`.venv/` has only pip).
**Why it happens:** pyproject.toml does not list notebook dependencies.
**How to avoid:** Add a `notebooks` optional group to pyproject.toml:
```toml
[project.optional-dependencies]
notebooks = [
  "jupyterlab>=4.0",
  "seaborn>=0.13",
  "ipykernel>=6.0",
]
```
Or document `pip install jupyterlab seaborn ipykernel` in the Prerequisites
section of each notebook.
**Warning signs:** `ModuleNotFoundError: No module named 'jupyter'` when running
`jupyter lab`.

### Pitfall 2: cmc_ama_multi_tf Does Not Exist

**What goes wrong:** Any query against `public.cmc_ama_multi_tf` raises
`UndefinedTable` error.
**Why it happens:** Phase 35 created the schema (DDL + state table) but the
AMA refresh scripts have never been run.
**How to avoid:** Notebook 1 must compute AMAs on-the-fly using `compute_ama()`.
The Prerequisites section must state: "AMAs are computed in-notebook. The
`cmc_ama_multi_tf` table is defined but not yet populated."
**Warning signs:** `sqlalchemy.exc.ProgrammingError: relation "public.cmc_ama_multi_tf" does not exist`

### Pitfall 3: sys.path Not Set Before ta_lab2 Imports

**What goes wrong:** `ModuleNotFoundError: No module named 'ta_lab2'` on
any import from the package.
**Why it happens:** ta_lab2 is not installed in the kernel's site-packages.
**How to avoid:** The first code cell must do `sys.path.insert(0, str(ROOT / "src"))`.
The helpers.py module does this automatically on import if placed in `notebooks/`.
**Warning signs:** Import error on any `from ta_lab2.xxx import yyy` line.

### Pitfall 4: Plotly Charts Not Rendering in Classic Jupyter Notebook

**What goes wrong:** `fig.show()` opens a browser tab or shows nothing instead
of rendering inline.
**Why it happens:** plotly 5+ changed default renderer detection. In classic
Jupyter (not JupyterLab), the `notebook` renderer must be set.
**How to avoid:** Add a renderer detection cell to each notebook:
```python
import plotly.io as pio
# In JupyterLab: 'jupyterlab' is auto-detected
# In classic Jupyter: set explicitly
# pio.renderers.default = "notebook"  # uncomment if charts don't show
```
**Warning signs:** Charts open browser tabs instead of rendering in cell output.

### Pitfall 5: tz-Aware Timestamp Pitfalls on Windows

**What goes wrong:** Code that calls `.values` on a tz-aware datetime Series
gets tz-naive `numpy.datetime64`, causing TypeError in comparisons.
**Why it happens:** Windows-specific pandas behaviour documented in MEMORY.md.
**How to avoid:** Always use `pd.to_datetime(df["ts"], utc=True)` after
`pd.read_sql()`. Never call `.values` on tz-aware datetime columns — use
`.tolist()` or pandas index/Series operations instead.
**Warning signs:** `TypeError: Cannot compare tz-naive and tz-aware timestamps`

### Pitfall 6: compute_ic() Requires train_start/train_end

**What goes wrong:** Calling `compute_ic(feature, close)` without the required
timestamp bounds raises `TypeError: compute_ic() missing required keyword-only
arguments`.
**Why it happens:** train_start and train_end have NO defaults (by design, to
prevent future-information leakage).
**How to avoid:** Always pass both:
```python
ic_df = compute_ic(
    feature, close,
    train_start=pd.Timestamp(START_DATE, tz="UTC"),
    train_end=pd.Timestamp(END_DATE, tz="UTC"),
)
```

### Pitfall 7: ExperimentRunner Requires registry.load() First

**What goes wrong:** `ValueError: FeatureRegistry is empty. Call registry.load()`
**Why it happens:** `FeatureRegistry.__init__()` does not call `load()`.
**How to avoid:** Always call `registry.load()` before passing to `ExperimentRunner`.

### Pitfall 8: EMA Columns Not in cmc_features (per MEMORY.md)

**What goes wrong:** Queries for `ema_9`, `ema_21`, etc. return column-not-found
errors against `cmc_features`.
**Why it happens:** EMA columns were removed from `cmc_features` in the v0.7.0
redesign. EMAs have (id, ts, tf, period) granularity and must be queried from
`cmc_ema_multi_tf_u` directly via LEFT JOIN.
**How to avoid:** For Notebook 2's regime A/B backtest, load EMA data with a
separate query:
```sql
SELECT e.ts, e.ama as close_ema_9
FROM public.cmc_ema_multi_tf_u e
WHERE e.id = :id AND e.tf = :tf AND e.period = 9 AND e.roll = FALSE
ORDER BY e.ts
```
Or use `cmc_features.close` as the price signal and skip EMA crossover in
favor of RSI signals which are already in `cmc_features` (`rsi_14`, `rsi_7`).

---

## Code Examples

Verified patterns from source code and live DB:

### DB Connection (NullPool — use in every notebook)
```python
# Source: verified working pattern in ta_lab2 codebase
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ta_lab2.scripts.refresh_utils import resolve_db_url

engine = create_engine(resolve_db_url(), poolclass=NullPool)

# Usage: always use context manager
with engine.connect() as conn:
    df = pd.read_sql(text("SELECT ..."), conn, params={...})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)  # ALWAYS fix tz after read_sql
```

### Pre-Validation Query (asset_data_coverage)
```python
# Source: live DB confirmed — table exists with columns: id, source_table, granularity, n_days
with engine.connect() as conn:
    coverage = pd.read_sql(text("""
        SELECT id, n_days, first_ts, last_ts
        FROM public.asset_data_coverage
        WHERE granularity = :tf AND n_days >= :min_days
        ORDER BY n_days DESC
    """), conn, params={"tf": TF, "min_days": 365})
print(f"Assets with 365+ days of {TF} data:")
print(coverage[["id", "n_days", "first_ts", "last_ts"]].to_string(index=False))
```

### AMA Regime Overlay Chart (Plotly)
```python
# Source: ta_lab2/features/ama/ama_computations.py + plotly
import plotly.graph_objects as go

fig = go.Figure()
fig.add_trace(go.Scatter(x=ama_df.index, y=ama_df["close"], name="Close", line=dict(color="black", width=1)))
fig.add_trace(go.Scatter(x=ama_df.index, y=ama_df["KAMA(10,2,30)"], name="KAMA", line=dict(color="blue")))
fig.add_trace(go.Scatter(x=ama_df.index, y=ama_df["HMA(21)"], name="HMA", line=dict(color="orange")))

# Regime-color background shading
with engine.connect() as conn:
    regimes = load_regimes_for_asset(conn, ASSET_ID, TF, train_start, train_end)
for ts, row in regimes.iterrows():
    color = "#c8e6c9" if row["trend_state"] == "Up" else "#ffcdd2" if row["trend_state"] == "Down" else "#fff9c4"
    fig.add_vrect(x0=ts, x1=ts + pd.Timedelta(days=1), fillcolor=color, opacity=0.15, line_width=0)

fig.update_layout(title=f"BTC {TF} — AMA Comparison with Regime Overlay", height=500)
fig.show()
```

### IC Results Styled Table (Pandas Styler)
```python
# Source: pandas.io.formats.style — verified working on pandas 2.3.3
display_cols = ["feature", "horizon", "ic", "ic_p_value", "ic_ir", "n_obs"]
styled = (
    ic_df[display_cols]
    .sort_values("horizon")
    .style
    .background_gradient(cmap="RdYlGn", subset=["ic"], vmin=-0.15, vmax=0.15)
    .applymap(lambda v: "color: green" if v < 0.05 else "color: gray",
              subset=["ic_p_value"])
    .format({"ic": "{:.4f}", "ic_p_value": "{:.4f}", "ic_ir": "{:.3f}", "n_obs": "{:,d}"})
)
display(styled)
```

### Batch IC Across Multiple Features
```python
# Source: ta_lab2/analysis/ic.py — batch_compute_ic()
from ta_lab2.analysis.ic import batch_compute_ic

feature_cols = ["rsi_14", "vol_parkinson_20", "atr_14", "macd_hist_12_26_9"]
features_df = load_features(engine, ASSET_ID, TF, START_DATE, END_DATE)
close = features_df["close"]

batch_ic = batch_compute_ic(
    features_df,
    close,
    train_start=pd.Timestamp(START_DATE, tz="UTC"),
    train_end=pd.Timestamp(END_DATE,     tz="UTC"),
    feature_cols=feature_cols,
    horizons=[1, 5, 20],
    return_types=["arith"],
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| EMAs in cmc_features | EMAs queried from cmc_ema_multi_tf_u | v0.7.0 | Notebooks cannot SELECT ema_9 from cmc_features |
| Fixed cmc_returns table | cmc_returns_bars_multi_tf | v0.6.0 | Notebooks use ret_arith/ret_log from cmc_features |
| AMA in separate table | AMA computed on-the-fly (table not populated) | Phase 35 shipped DDL, data not yet refreshed | Notebook 1 must use compute_ama() directly |

**Deprecated/outdated:**
- `cmc_returns` / `cmc_returns_daily`: Use `cmc_features.ret_arith` / `ret_log` instead
- EMA columns in `cmc_features` (ema_9, ema_21, etc.): Removed in v0.7.0; query `cmc_ema_multi_tf_u`
- `returns_feature.py`: Deleted; logic lives in `cmc_features` directly

---

## Open Questions

1. **Jupyter kernel configuration**
   - What we know: System Python 3.12 has all libraries; venv has only pip
   - What's unclear: Whether the user's Jupyter installation (if any) already
     has a kernel that can find system Python packages
   - Recommendation: Planner should include a task to add `notebooks` optional
     dep group to pyproject.toml and document kernel registration

2. **cmc_ama_multi_tf table population timing**
   - What we know: Table schema exists (DDL in place), state table empty, data
     refresh scripts exist but have never been run
   - What's unclear: Whether notebooks should trigger AMA refresh before running
     (adds 3-5 min) or always compute on-the-fly (simpler but loses the "use DB"
     pattern the other notebooks demonstrate)
   - Recommendation: Compute on-the-fly in Notebook 1. Add a note: "When
     cmc_ama_multi_tf is populated, switch to DB query for consistency."

3. **EMA columns for Notebook 2 regime A/B backtest**
   - What we know: `ema_21`, `ema_50` not in `cmc_features`; need separate
     query from `cmc_ema_multi_tf_u`
   - What's unclear: Which EMA periods to use for the crossover demo
   - Recommendation: Use RSI signals for regime A/B backtest (rsi_14 is in
     cmc_features directly). Avoids the JOIN complexity for the demo.

4. **Plotly rendering environment**
   - What we know: Default renderer is `browser` in system Python; Jupyter
     auto-detects in JupyterLab/classic Notebook
   - What's unclear: What Jupyter interface the user will use (Lab vs classic vs VS Code)
   - Recommendation: Add a commented renderer override in each notebook's setup
     cell with explanation

---

## Sources

### Primary (HIGH confidence)
- Direct source code reading: `ta_lab2/analysis/ic.py` — all IC function signatures verified
- Direct source code reading: `ta_lab2/backtests/cv.py` — PurgedKFoldSplitter and CPCVSplitter APIs
- Direct source code reading: `ta_lab2/experiments/registry.py`, `runner.py` — FeatureRegistry and ExperimentRunner APIs
- Direct source code reading: `ta_lab2/features/ama/ama_computations.py` — compute_ama() dispatcher verified
- Direct source code reading: `ta_lab2/scripts/refresh_utils.py` — resolve_db_url() signature
- Live DB queries: table existence, row counts, column schemas for cmc_features, cmc_regimes, cmc_ic_results, asset_data_coverage
- `pip list` output: verified plotly 6.4.0, scipy 1.17.0, vectorbt 0.28.1, matplotlib 3.10.0, scikit-learn 1.8.0, streamlit 1.44.0, pandas 2.3.3, numpy 2.4.1
- Python execution: all major import paths tested and confirmed working

### Secondary (MEDIUM confidence)
- `pyproject.toml` optional deps: confirmed seaborn and jupyter are NOT in any dep group
- `alembic/versions/6f82e9117c58_feature_experiment_tables.py`: confirmed dim_feature_registry and cmc_feature_experiments column schemas
- `configs/experiments/features.yaml`: confirmed registry format and 5 experimental features

### Tertiary (LOW confidence)
- Plotly renderer auto-detection in Jupyter: stated behavior from plotly docs and known patterns; not tested in live Jupyter session

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pip list confirmed all library versions
- Architecture patterns: HIGH — all code paths imported and executed successfully
- DB table availability: HIGH — live queries confirmed which tables exist and have data
- Pitfalls: HIGH — MEMORY.md documents Windows-specific issues; AMA table absence confirmed by live query
- Plotly rendering in Jupyter: MEDIUM — auto-detection behavior documented but not tested in Jupyter session

**Research date:** 2026-02-24
**Valid until:** 2026-04-01 (stable domain; only invalidated if schema changes or new phases modify tables)
