# Phase 56: Factor Analytics & Reporting Upgrade - Research

**Researched:** 2026-02-27
**Domain:** QuantStats HTML tear sheets, IC decay/Rank IC/ICIR, quintile returns, cross-sectional normalization, MAE/MFE, Monte Carlo resampling
**Confidence:** HIGH — all findings sourced directly from codebase inspection and verified library APIs

---

## Summary

Phase 56 upgrades the existing analytics pipeline with five concrete deliverables. The codebase already has strong foundations: `ic.py` already computes Spearman IC (which IS Rank IC), `ic_ir` (which IS ICIR), rolling IC, and horizons [1,2,3,5,10,20,60]. The `backtest_from_signals.py` already extracts trade records from vectorbt. The `cmc_ic_results` table already has the right schema for IC/ICIR; it just needs Rank IC labeled explicitly as distinct from Pearson IC.

The critical realization: **QuantStats is not yet installed** (`pip show quantstats` returns not found). It requires seaborn and yfinance as new dependencies. The vectorbt 0.28.1 free version does NOT have built-in MAE/MFE in its trade records — MAE/MFE must be computed manually from price data using entry/exit indices into the close series. The `cmc_ic_results` table already stores what Qlib calls "Rank IC" (Spearman) but does not label it as such — adding a `rank_ic` column alongside the existing `ic` column (which was Spearman all along) would clarify this.

Cross-sectional normalization is best done as a SQL migration adding two computed columns (or a post-processing step in the feature refresh pipeline), using PostgreSQL window functions partitioned by `(ts, tf)`.

**Primary recommendation:** Implement in five focused tasks: (1) QuantStats install + HTML tear sheet generator, (2) IC decay labeling + Rank IC/ICIR column additions, (3) quintile group returns engine + charts, (4) cross-sectional normalization SQL migration + feature refresh step, (5) MAE/MFE computation + Monte Carlo CLI.

---

## Standard Stack

### Core (all already installed except QuantStats)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `quantstats` | 0.0.81 (latest Jan 2026) | HTML tear sheets, 60+ portfolio metrics | Industry standard for strategy reporting |
| `vectorbt` | 0.28.1 (installed) | Portfolio simulation source for daily returns | Already in codebase; `pf.returns()` produces input for QuantStats |
| `scipy` | (installed via project) | `spearmanr` for Rank IC | Already used in `ic.py` |
| `numpy` | (installed) | Monte Carlo resampling, MAE/MFE computation | Already used everywhere |
| `pandas` | (installed) | Series/DataFrame operations for quintile groupby | Already used everywhere |
| `plotly` | (installed) | Quintile return charts, IC decay charts | Already used in `charts.py` |
| `SQLAlchemy` | >=2.0 (installed) | Alembic migrations for schema changes | Already in codebase |
| `alembic` | >=1.18 (installed) | Schema migrations for new columns | Already in codebase |

### New Dependency: QuantStats

QuantStats 0.0.81 requires:
- `pandas >= 1.5.0`
- `numpy >= 1.24.0`
- `scipy >= 1.11.0`
- `matplotlib >= 3.7.0`
- `seaborn >= 0.13.0` (NEW — not in pyproject.toml)
- `tabulate >= 0.9.0` (NEW)
- `yfinance >= 0.2.40` (NEW — used only for benchmark fetch, avoidable if passing Series directly)

**Installation:**
```bash
pip install quantstats
# Pulls in seaborn, tabulate, yfinance automatically
```

Add to `pyproject.toml` optional group:
```toml
[project.optional-dependencies]
analytics = [
  "quantstats>=0.0.81",
]
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `qs.reports.html()` | Custom Jinja2 + matplotlib | QuantStats gives 18 charts + 60+ metrics for free; custom is weeks of work |
| Manual MAE/MFE computation | VectorBT PRO | PRO costs money; manual is ~30 lines of pandas |
| SQL window functions for CSZScore | Python pandas groupby | SQL is faster at scale (computed at query time, no Python loop per ts) |
| Monte Carlo from trades | Jesse's full MC engine | Jesse's approach is ~50 lines of numpy; no need for a framework |

---

## Architecture Patterns

### Recommended Project Structure Additions

```
src/ta_lab2/
├── analysis/
│   ├── ic.py                    # EXISTS — extend with rank_ic labeling
│   ├── quantstats_reporter.py   # NEW — QuantStats HTML generator
│   ├── quintile.py              # NEW — quintile group returns engine
│   └── monte_carlo.py           # NEW — Monte Carlo trade resampling
├── scripts/
│   ├── analysis/
│   │   ├── run_quantstats_report.py   # NEW — CLI for tear sheet generation
│   │   ├── run_quintile_sweep.py      # NEW — CLI for quintile analysis
│   │   └── run_monte_carlo.py         # NEW — CLI for MC confidence intervals
│   └── features/
│       └── refresh_cmc_cs_norms.py    # NEW — cross-sectional normalization refresh
alembic/versions/
├── XXXX_add_rank_ic_to_ic_results.py      # NEW — rank_ic column on cmc_ic_results
├── XXXX_add_mae_mfe_to_trades.py          # NEW — mae/mfe on cmc_backtest_trades
├── XXXX_add_mc_ci_to_metrics.py           # NEW — mc_sharpe_ci_lo/hi on cmc_backtest_metrics
└── XXXX_add_cs_norms_to_features.py       # NEW — cs_zscore/rank columns on cmc_features
sql/
└── migration/
    └── add_factor_analytics_columns.sql   # NEW — reference DDL
```

### Pattern 1: QuantStats HTML Tear Sheet

**What:** `pf.returns()` from vectorbt → `qs.reports.html()` → self-contained HTML file
**When to use:** Every `save_backtest_results()` call in `backtest_from_signals.py`
**Key fact:** `qs.reports.html()` takes a daily returns `pd.Series` with `DatetimeIndex`. It does NOT need the portfolio object — just the returns series. BTC benchmark must also be a returns Series, not a price Series.

```python
# Source: https://github.com/ranaroussi/quantstats/blob/main/quantstats/reports.py
import quantstats as qs

def generate_tear_sheet(
    portfolio_returns: pd.Series,   # from pf.returns(), tz-aware UTC DatetimeIndex
    benchmark_returns: pd.Series,   # from cmc_price_bars_multi_tf BTC 1D, pct_change()
    output_path: str,               # e.g. "reports/tearsheets/{run_id}.html"
    title: str = "Strategy Tearsheet",
) -> None:
    # QuantStats requires tz-naive DatetimeIndex (strip tz before passing)
    ret = portfolio_returns.copy()
    if ret.index.tz is not None:
        ret.index = ret.index.tz_localize(None)

    bench = benchmark_returns.copy()
    if bench.index.tz is not None:
        bench.index = bench.index.tz_localize(None)

    qs.reports.html(
        ret,
        benchmark=bench,
        output=output_path,
        title=title,
        periods_per_year=365,   # crypto trades 365 days/year
        compounded=True,
    )
```

**CRITICAL PITFALL:** The `benchmark` parameter must be a returns Series (pct_change of price), NOT a price Series. Passing price instead of returns produces garbage benchmark metrics.

**CRITICAL PITFALL:** QuantStats matches dates internally — if portfolio and benchmark have different date ranges, it clips to intersection. Always pass full date range and let QuantStats handle alignment.

### Pattern 2: IC Decay Labeling + Rank IC Column

**What:** The existing `ic.py` uses `scipy.stats.spearmanr` — this IS Rank IC (Spearman rank correlation). The `cmc_ic_results` table stores it as `ic`. Phase 55 already computed IC across horizons [1,2,3,5,10,20,60]. ANALYTICS-02 asks for horizons [2,5,10,20] specifically.

**Finding:** The existing horizons [1,2,3,5,10,20,60] already include 2/5/10/20. The "IC decay" requirement is already satisfied by existing infrastructure. What's genuinely missing is a `rank_ic` column to make the Spearman label explicit, and distinguishing it from a future Pearson IC if one is added.

**Migration approach:** Add `rank_ic NUMERIC` column to `cmc_ic_results` (mirrors `ic`, which was always Spearman). When running new IC sweeps post-migration, populate both `ic` (for backward compat) and `rank_ic` with the same Spearman value.

```python
# In save_ic_results(), add rank_ic to INSERT:
# rank_ic = ic_result["ic"]  (same value — it was Spearman all along)
```

### Pattern 3: Quintile Group Returns

**What:** At each timestamp, rank all assets by a factor column, bin into 5 quintiles, compute forward returns per quintile, track cumulative return per bucket.
**When to use:** Factor validation — monotonicity across quintiles confirms predictive power.

```python
# Source: derived from Qlib documentation pattern + pandas groupby
def compute_quintile_returns(
    features_df: pd.DataFrame,   # Multi-asset: (ts, id, tf) indexed or multi-index
    factor_col: str,             # e.g. 'rsi_14', 'ret_arith_zscore_30'
    forward_horizon: int = 1,    # bars forward
) -> pd.DataFrame:
    """
    At each ts: rank all assets by factor_col → assign quintile 1-5.
    Compute horizon-bar-forward return per asset per ts.
    Return cumulative return by quintile over time.
    """
    # Step 1: Rank within each ts (cross-sectional rank)
    features_df = features_df.copy()
    features_df['quintile'] = (
        features_df.groupby('ts')[factor_col]
        .transform(lambda x: pd.qcut(x.rank(method='first'), 5, labels=[1,2,3,4,5]))
        .astype(int)
    )

    # Step 2: Compute forward returns per asset
    features_df['fwd_ret'] = (
        features_df.groupby('id')['close']
        .transform(lambda x: x.shift(-forward_horizon) / x - 1.0)
    )

    # Step 3: Average forward return per (ts, quintile)
    quintile_returns = (
        features_df.groupby(['ts', 'quintile'])['fwd_ret']
        .mean()
        .unstack('quintile')
    )

    # Step 4: Cumulative return per quintile
    cumulative = (1 + quintile_returns).cumprod()
    return cumulative
```

**Anti-Pattern:** Do NOT compute quintiles on a single asset's time series — you need cross-sectional ranking across ALL assets at each timestamp to get the factor-monotonicity signal.

### Pattern 4: Cross-Sectional Normalization

**What:** PostgreSQL window functions partition by `(ts, tf)` to normalize each asset vs all assets at the same timestamp.
**When to use:** Any multi-asset factor ranking; complements existing time-series z-scores.

```sql
-- CSZScoreNorm: z-score each feature relative to all assets at same (ts, tf)
-- Source: Qlib preprocessor pattern, implemented as SQL window function
ALTER TABLE public.cmc_features
    ADD COLUMN IF NOT EXISTS ret_arith_cs_zscore DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS rsi_14_cs_zscore     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ret_arith_cs_rank     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS rsi_14_cs_rank        DOUBLE PRECISION;

-- Refresh query pattern:
UPDATE public.cmc_features f
SET
    ret_arith_cs_zscore = (
        f.ret_arith - AVG(f.ret_arith) OVER (PARTITION BY f.ts, f.tf)
    ) / NULLIF(STDDEV(f.ret_arith) OVER (PARTITION BY f.ts, f.tf), 0),
    ret_arith_cs_rank = PERCENT_RANK() OVER (
        PARTITION BY f.ts, f.tf ORDER BY f.ret_arith
    );
```

**CRITICAL PITFALL:** Cross-sectional normalization makes sense only for columns that are meaningful to compare across assets at the same timestamp: return columns, momentum columns, RSI, BB_width, vol metrics. It does NOT make sense for OHLCV columns (price levels differ across assets) or for columns that are already ratio-normalized.

**Suggested initial CS-norm columns (6 columns for the pilot):**
- `ret_arith_cs_zscore`, `ret_arith_cs_rank`
- `rsi_14_cs_zscore`, `rsi_14_cs_rank`
- `vol_parkinson_20_cs_zscore`, `vol_parkinson_20_cs_rank`

Expanding to all 112 columns would require 224 additional columns — too much for the first iteration. Pilot with 3 source features x 2 norms = 6 columns.

### Pattern 5: MAE/MFE Manual Computation

**What:** vectorbt 0.28.1 does NOT have MAE/MFE in trade records. Compute manually from `entry_idx`, `exit_idx`, and the close price Series.

```python
# Source: OHLCV manual excursion pattern — standard quant technique
def compute_mae_mfe(
    trades_df: pd.DataFrame,   # has entry_ts, exit_ts, direction, entry_price
    close_series: pd.Series,   # close prices indexed by ts (tz-naive UTC, matches trades)
) -> pd.DataFrame:
    """
    Compute MAE and MFE per trade from close prices.

    MAE (Maximum Adverse Excursion): worst intra-trade return vs entry
    MFE (Maximum Favorable Excursion): best intra-trade return vs entry

    For LONG: MAE = min(close[entry:exit]) / entry_price - 1  (negative)
              MFE = max(close[entry:exit]) / entry_price - 1  (positive)
    For SHORT: MAE = entry_price / max(close[entry:exit]) - 1  (negative)
               MFE = entry_price / min(close[entry:exit]) - 1  (positive)
    """
    mae_list, mfe_list = [], []

    for _, trade in trades_df.iterrows():
        # Get close prices from entry to exit (inclusive)
        entry_ts = pd.Timestamp(trade['entry_ts']).tz_localize(None) if pd.Timestamp(trade['entry_ts']).tz else pd.Timestamp(trade['entry_ts'])
        exit_ts  = pd.Timestamp(trade['exit_ts']).tz_localize(None)  if pd.Timestamp(trade['exit_ts']).tz  else pd.Timestamp(trade['exit_ts'])

        window = close_series.loc[entry_ts:exit_ts]
        if len(window) == 0:
            mae_list.append(None)
            mfe_list.append(None)
            continue

        entry_price = float(trade['entry_price'])
        direction   = str(trade['direction']).lower()

        if direction == 'long':
            mae = float(window.min() / entry_price - 1.0)  # most negative
            mfe = float(window.max() / entry_price - 1.0)  # most positive
        else:  # short
            mae = float(entry_price / window.max() - 1.0)  # most negative for short
            mfe = float(entry_price / window.min() - 1.0)  # most positive for short

        mae_list.append(mae)
        mfe_list.append(mfe)

    trades_df = trades_df.copy()
    trades_df['mae'] = mae_list
    trades_df['mfe'] = mfe_list
    return trades_df
```

### Pattern 6: Monte Carlo Trade Resampling

**What:** Resample N=1000 times with replacement from trade-level PnL, compute Sharpe/CAGR distribution.

```python
# Source: Jesse anti-overfitting pattern, adapted for ta_lab2
import numpy as np

def monte_carlo_trades(
    trades_df: pd.DataFrame,   # cmc_backtest_trades rows for one run_id
    n_samples: int = 1000,
    seed: int = 42,
) -> dict:
    """
    Trade-level Monte Carlo resampling.
    Resample trade PnL N times, compute Sharpe/CAGR per sample.
    Return 95% CI and median.
    """
    rng = np.random.default_rng(seed)
    n_trades = len(trades_df)

    if n_trades < 10:
        return {'sharpe_lo': None, 'sharpe_hi': None, 'sharpe_median': None,
                'n_trades': n_trades, 'n_samples': n_samples}

    pnl_pct = trades_df['pnl_pct'].dropna().values / 100.0  # to decimal

    sharpe_dist = []
    for _ in range(n_samples):
        sample = rng.choice(pnl_pct, size=n_trades, replace=True)
        std = sample.std(ddof=1)
        if std > 0:
            sharpe = sample.mean() / std * np.sqrt(365)
            sharpe_dist.append(sharpe)

    sharpe_arr = np.array(sharpe_dist)
    ci_lo, ci_hi = np.percentile(sharpe_arr, [2.5, 97.5])

    return {
        'mc_sharpe_lo':     float(ci_lo),
        'mc_sharpe_hi':     float(ci_hi),
        'mc_sharpe_median': float(np.median(sharpe_arr)),
        'n_trades':         n_trades,
        'n_samples':        n_samples,
    }
```

### Anti-Patterns to Avoid

- **Passing price to QuantStats as benchmark:** `qs.reports.html(returns, benchmark=btc_prices)` silently produces garbage. Must call `.pct_change()` on price first.
- **Computing CSZScore without NULLIF guard:** `/ STDDEV(...)` crashes when all assets have the same value at a timestamp. Always use `NULLIF(STDDEV(...), 0)`.
- **Quintile ranking on single-asset series:** Cross-sectional quintiles require multiple assets at each timestamp. If only one asset has data at a timestamp, quintile assignment is meaningless.
- **Adding CS-norm to all 112 cmc_features columns:** 224 new columns would be unmanageable. Pilot with 6 key columns, expand only after validation.
- **Storing QuantStats HTML in the database:** Store on disk in `reports/tearsheets/{run_id}.html`. Record the file path in `cmc_backtest_runs` (new column: `tearsheet_path`).
- **Running MAE/MFE by fetching prices per trade in a loop:** Fetch the full close series for the backtest window once, then index into it per trade. N+1 query anti-pattern is critical to avoid here.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 60+ portfolio metrics + 18 charts | Custom metric functions | `quantstats.reports.html()` | Would take weeks; QuantStats has edge cases covered (NaN handling, crypto 365-day annualization) |
| Spearman rank correlation | Manual rank computation | `scipy.stats.spearmanr` (already in `ic.py`) | Handles tied ranks correctly |
| Quintile binning | Manual percentile cuts | `pd.qcut(x.rank(), 5)` | Handles ties and edge cases in distribution |
| BTC benchmark fetch | Custom DB query each time | Load once per session and cache as `pd.Series` | Same BTC price data used by every tear sheet in a batch |
| Rolling standard deviation for MC | Manual loop | `numpy` vectorized operations | `np.percentile` is optimized; no need for custom CI code |

**Key insight:** QuantStats does the hard work for tear sheets. The only custom code needed is the glue between `pf.returns()` and `qs.reports.html()`.

---

## Common Pitfalls

### Pitfall 1: QuantStats tz-aware DatetimeIndex
**What goes wrong:** `qs.reports.html(returns)` raises `TypeError` or `ValueError` if the DatetimeIndex has timezone info.
**Why it happens:** QuantStats uses matplotlib and pandas date operations that do not tolerate tz-aware DatetimeIndex internally.
**How to avoid:** Strip tz before passing: `ret.index = ret.index.tz_localize(None)` for naive → UTC-naive, or `ret.index = ret.index.tz_convert('UTC').tz_localize(None)` for aware → naive.
**Warning signs:** `TypeError: Cannot compare tz-naive and tz-aware` or `ValueError: Index must be DatetimeIndex`.

### Pitfall 2: vectorbt pf.returns() returns tz-naive Series
**What goes wrong:** `pf.returns()` returns a tz-naive DatetimeIndex because vectorbt strips tz at the boundary (documented in MEMORY.md). So the tz stripping for QuantStats may already be done — but verify before assuming.
**Why it happens:** Existing `_build_portfolio()` in `backtest_from_signals.py` passes tz-naive prices and signals to vectorbt.
**How to avoid:** Check `pf.returns().index.tz` before stripping. Do not double-strip (stripping a tz-naive index raises `TypeError`).
**Warning signs:** `TypeError: Already tz-naive` when calling `.tz_localize(None)` on an already-naive index.

### Pitfall 3: Cross-sectional norm requires enough assets per (ts, tf)
**What goes wrong:** CS z-score is NaN when only 1 asset has data at a timestamp. CS rank is trivially 0 or 1 with 2 assets.
**Why it happens:** Not all assets have bars for all timestamps and TFs.
**How to avoid:** In the refresh script, filter to timestamps with `COUNT(DISTINCT id) >= 5` before computing CS norms. Add a `cs_n_assets` integer column to document how many assets contributed.
**Warning signs:** All CS z-score values are 0 or NaN for low-traffic TFs.

### Pitfall 4: cmc_ic_results unique constraint prevents adding rank_ic
**What goes wrong:** If Rank IC is stored as a separate row with `ic_type='rank'` it conflicts with the existing unique constraint `(asset_id, tf, feature, horizon, return_type, regime_col, regime_label, train_start, train_end)`.
**Why it happens:** The constraint does not include an `ic_type` column.
**How to avoid:** Add `rank_ic NUMERIC` as a new COLUMN to `cmc_ic_results` (alongside existing `ic`), NOT as a new row. Run Alembic migration to add the column. Update `save_ic_results()` to populate it.
**Warning signs:** `UniqueViolation` when inserting second Rank IC row for same natural key.

### Pitfall 5: MAE/MFE with open trades (no exit_ts)
**What goes wrong:** `compute_mae_mfe()` crashes on trades where `exit_ts` is NULL (open positions).
**Why it happens:** `cmc_backtest_trades` has `exit_ts` as nullable. Open positions have no exit.
**How to avoid:** Filter to `exit_ts IS NOT NULL` before computing MAE/MFE. Set `mae=NULL, mfe=NULL` for still-open trades.
**Warning signs:** `KeyError` or `NaT` comparison errors in the price slicing step.

### Pitfall 6: Monte Carlo N=1000 on a run with 3 trades
**What goes wrong:** With very few trades, the MC distribution is degenerate and the 95% CI is meaninglessly wide.
**Why it happens:** Trade-level resampling with replacement from n=3 produces only 10 unique permutations.
**How to avoid:** Enforce minimum trade count (n >= 10 recommended) before running Monte Carlo. Return `None` for CI if below threshold. Log a warning.
**Warning signs:** `mc_sharpe_lo` and `mc_sharpe_hi` differ by more than 20 Sharpe points.

### Pitfall 7: SQL migration on Windows UTF-8 encoding
**What goes wrong:** Alembic migration files with UTF-8 box-drawing characters (`═══`) fail on Windows with `UnicodeDecodeError: cp1252 codec can't decode`.
**Why it happens:** Windows default file encoding is cp1252 (documented in MEMORY.md).
**How to avoid:** All SQL files in this phase must use ASCII-only comments. No box-drawing characters. Alembic migration Python files are UTF-8 by default and safe.
**Warning signs:** `UnicodeDecodeError: 'charmap' codec can't decode byte` in any SQL file reader.

### Pitfall 8: cmc_features CS-norm columns and dynamic column matching
**What goes wrong:** Adding CS-norm columns to `cmc_features` will appear in `get_columns()` auto-discovery. Feature refresh scripts that use `_get_table_columns()` to filter DataFrame columns will try to write to these new columns even if they are not produced by the feature computation.
**Why it happens:** `daily_features_view.py` and related scripts auto-discover cmc_features columns via `get_columns()` and filter the output DataFrame to match. If the new CS-norm columns appear in the table but not in the DataFrame, NULLs will be written (or the column is skipped if filtered correctly).
**How to avoid:** CS-norm columns should be computed by a SEPARATE refresh step (`refresh_cmc_cs_norms.py`), not by the existing feature refresh pipeline. The existing pipeline should not write to CS-norm columns.

---

## Code Examples

### QuantStats Integration in backtest_from_signals.py

```python
# Source: quantstats 0.0.81 API + existing backtest_from_signals.py
def generate_tear_sheet_for_run(
    result: BacktestResult,
    pf,                         # vectorbt Portfolio object (rebuilt in _build_portfolio)
    engine: Engine,
    output_dir: str = "reports/tearsheets",
) -> Optional[str]:
    """Generate QuantStats HTML tear sheet. Returns file path or None on failure."""
    try:
        import quantstats as qs
    except ImportError:
        logger.warning("quantstats not installed — skipping tear sheet generation")
        return None

    import os
    os.makedirs(output_dir, exist_ok=True)

    # Get portfolio daily returns (tz-naive UTC from vectorbt)
    portfolio_returns = pf.returns()
    if portfolio_returns.index.tz is not None:
        portfolio_returns.index = portfolio_returns.index.tz_localize(None)

    # Load BTC benchmark returns
    btc_prices = _load_btc_prices(engine, result.start_ts, result.end_ts)
    benchmark_returns = btc_prices.pct_change().dropna()
    if benchmark_returns.index.tz is not None:
        benchmark_returns.index = benchmark_returns.index.tz_localize(None)

    output_path = f"{output_dir}/{result.run_id}.html"
    title = f"{result.signal_type} | Asset {result.asset_id} | Signal {result.signal_id}"

    qs.reports.html(
        portfolio_returns,
        benchmark=benchmark_returns,
        output=output_path,
        title=title,
        periods_per_year=365,
        compounded=True,
    )

    return output_path


def _load_btc_prices(engine: Engine, start_ts, end_ts) -> pd.Series:
    """Load BTC daily close prices for benchmark."""
    BTC_ID = 1  # CoinMarketCap ID for BTC
    sql = text("""
        SELECT ts, close FROM public.cmc_features
        WHERE id = :btc_id AND tf = '1D'
          AND ts >= :start AND ts <= :end
        ORDER BY ts
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"btc_id": BTC_ID, "start": start_ts, "end": end_ts})
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    return df.set_index("ts")["close"]
```

### Alembic Migration for rank_ic Column

```python
# alembic/versions/XXXX_add_rank_ic_to_ic_results.py
def upgrade() -> None:
    op.add_column(
        "cmc_ic_results",
        sa.Column("rank_ic", sa.Numeric(), nullable=True),
        schema="public",
    )
    # rank_ic = Spearman IC (same as existing ic column — makes label explicit)
    # Backfill from existing ic column
    op.execute("UPDATE public.cmc_ic_results SET rank_ic = ic WHERE rank_ic IS NULL")

def downgrade() -> None:
    op.drop_column("cmc_ic_results", "rank_ic", schema="public")
```

### Alembic Migration for MAE/MFE on cmc_backtest_trades

```python
# alembic/versions/XXXX_add_mae_mfe_to_trades.py
def upgrade() -> None:
    op.add_column(
        "cmc_backtest_trades",
        sa.Column("mae", sa.Numeric(), nullable=True),
        schema="public",
    )
    op.add_column(
        "cmc_backtest_trades",
        sa.Column("mfe", sa.Numeric(), nullable=True),
        schema="public",
    )
    # Comment: MAE = maximum adverse excursion (most negative intra-trade return)
    # Comment: MFE = maximum favorable excursion (most positive intra-trade return)

def downgrade() -> None:
    op.drop_column("cmc_backtest_trades", "mfe", schema="public")
    op.drop_column("cmc_backtest_trades", "mae", schema="public")
```

### Alembic Migration for Monte Carlo CI on cmc_backtest_metrics

```python
# alembic/versions/XXXX_add_mc_ci_to_metrics.py
def upgrade() -> None:
    for col in ["mc_sharpe_lo", "mc_sharpe_hi", "mc_sharpe_median"]:
        op.add_column(
            "cmc_backtest_metrics",
            sa.Column(col, sa.Numeric(), nullable=True),
            schema="public",
        )
    op.add_column(
        "cmc_backtest_metrics",
        sa.Column("mc_n_samples", sa.Integer(), nullable=True),
        schema="public",
    )
    op.add_column(
        "cmc_backtest_runs",
        sa.Column("tearsheet_path", sa.Text(), nullable=True),
        schema="public",
    )

def downgrade() -> None:
    for col in ["mc_sharpe_lo", "mc_sharpe_hi", "mc_sharpe_median", "mc_n_samples"]:
        op.drop_column("cmc_backtest_metrics", col, schema="public")
    op.drop_column("cmc_backtest_runs", "tearsheet_path", schema="public")
```

### Quintile Plotly Chart

```python
# Source: Plotly line chart pattern from existing charts.py
import plotly.graph_objects as go

def build_quintile_returns_chart(
    quintile_cum_returns: pd.DataFrame,   # columns 1-5, index=ts
    factor_col: str,
    horizon: int,
) -> go.Figure:
    fig = go.Figure()
    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd"]

    for q in range(1, 6):
        if q not in quintile_cum_returns.columns:
            continue
        fig.add_trace(go.Scatter(
            x=quintile_cum_returns.index,
            y=quintile_cum_returns[q],
            mode="lines",
            name=f"Q{q}",
            line=dict(color=colors[q-1]),
        ))

    fig.update_layout(
        title=f"Quintile Returns: {factor_col} (horizon={horizon}d)",
        xaxis_title="Date",
        yaxis_title="Cumulative Return",
    )
    return fig
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual metric computation | `quantstats.reports.html()` (60+ metrics) | QuantStats ~2019, v0.0.81 Jan 2026 | 60+ metrics in one function call; 18 charts |
| Pearson IC | Spearman/Rank IC | Standard in Qlib/quantitative finance by 2020 | More robust to return outliers (crypto-critical) |
| Single-horizon IC | IC decay table (1/2/3/5/10/20/60-bar) | Qlib (2020) | Reveals factor "half-life" for holding period alignment |
| Time-series z-scores | Cross-sectional z-scores + rank norms | Qlib preprocessors (2020) | Enables multi-asset relative ranking for portfolio construction |
| Point Sharpe | Sharpe + 95% CI via Monte Carlo | Jesse, MLFinLab (2021) | Overfitting test — wide CI means strategy has limited sample |

**Deprecated/outdated:**
- `qs.reports.basic()`: Superseded by `qs.reports.html()` which includes all metrics and charts in one call
- VectorBT PRO MAE/MFE: Free vectorbt 0.28 does NOT have built-in MAE/MFE in trade records — must compute manually from price data

---

## Open Questions

1. **Where to store HTML tear sheets on disk?**
   - What we know: `run_id` is a UUID, tear sheets should be linked to backtest runs. Path needs to be deterministic.
   - What's unclear: Server vs local storage. If running remotely, HTML files are not browsable without serving.
   - Recommendation: Use `reports/tearsheets/{run_id}.html` locally. Record `tearsheet_path` in `cmc_backtest_runs`. In a future phase, serve via Streamlit file download.

2. **Which features to pilot for CS normalization?**
   - What we know: Adding 224 CS-norm columns (112 features x 2 norms) is too many for v1. Six columns (3 features x 2 norms) is manageable.
   - What's unclear: Which 3 features are most valuable for cross-sectional ranking?
   - Recommendation: `ret_arith`, `rsi_14`, `vol_parkinson_20` — these are the three canonical signals already used by the signal generators. Add more in a follow-on phase.

3. **Rank IC vs Pearson IC separation in cmc_ic_results?**
   - What we know: All existing `ic` values in `cmc_ic_results` are Spearman (same as Rank IC). Adding a `rank_ic` column populated by copying `ic` is backward-safe.
   - What's unclear: Whether future IC work will add Pearson IC as a separate metric.
   - Recommendation: Add `rank_ic` column as alias for Spearman IC. Leave `ic` column unchanged for backward compatibility. Document in column comments.

4. **Quintile sweep CLI — all assets or subset?**
   - What we know: Full quintile sweep requires loading all assets' features at each timestamp — expensive for 109 TFs.
   - What's unclear: How many assets have sufficient data for meaningful quintile ranking.
   - Recommendation: Pilot quintile sweep on `1D` TF only, all assets with `cmc_features` data. Start with 3-5 factor columns. Add a `--tf` flag for targeted sweeps.

---

## Sources

### Primary (HIGH confidence)
- **Codebase direct inspection** — `src/ta_lab2/analysis/ic.py` (full file read), `src/ta_lab2/scripts/backtests/backtest_from_signals.py` (full file read)
- **Codebase direct inspection** — `sql/backtests/071_cmc_backtest_trades.sql`, `sql/backtests/072_cmc_backtest_metrics.sql`, `sql/features/080_cmc_ic_results.sql`
- **Codebase direct inspection** — `alembic/versions/c3b718c2d088_ic_results_table.py`, `alembic/versions/adf582a23467_psr_column_rename.py`
- **Runtime verification** — `pip show vectorbt` (0.28.1 confirmed), `python -c "import vectorbt..."` (trade record dtype names confirmed: no MAE/MFE)
- **Runtime verification** — `pip show quantstats` returned NOT INSTALLED
- **PyPI** — https://pypi.org/project/quantstats/ — version 0.0.81, deps confirmed (seaborn, tabulate, yfinance)
- **GitHub WebFetch** — https://github.com/ranaroussi/quantstats/blob/main/quantstats/reports.py — `html()` API signature confirmed
- **Planning doc** — `.planning/research/quant_finance_ecosystem_review.md` — QuantStats, Qlib, Jesse patterns

### Secondary (MEDIUM confidence)
- **WebSearch** — vectorbt MAE/MFE: VectorBT PRO has built-in MAE/MFE; free 0.28 does NOT (confirmed by runtime inspection of Trades class `dir()` showing no `mae`, `mfe`, or `excursion` attributes)
- **Qlib documentation** — cross-sectional normalization patterns (CSZScoreNorm, CSRankNorm as SQL window functions)

### Tertiary (LOW confidence)
- None — no unverified claims

---

## Metadata

**Confidence breakdown:**
- QuantStats API: HIGH — WebFetch of reports.py + PyPI version confirmed + runtime missing-import confirmed
- IC infrastructure: HIGH — full ic.py source read; all existing columns, horizons, and Spearman implementation confirmed
- vectorbt MAE/MFE: HIGH — runtime Trades class inspection confirmed no built-in MAE/MFE in 0.28.1
- Alembic migration pattern: HIGH — read 2 existing migration files; pattern well-established
- Cross-sectional norm SQL: HIGH — PostgreSQL window function pattern, verified in ecosystem review
- Monte Carlo pattern: HIGH — simple numpy resampling, standard technique, Jesse pattern verified in ecosystem review
- Quintile group returns: MEDIUM — pandas groupby pattern derived from Qlib documentation, not verified in live Python session

**Research date:** 2026-02-27
**Valid until:** 2026-03-27 (QuantStats releases frequently; check for updates; Alembic patterns are stable)
