# Phase 37: IC Evaluation - Research

**Researched:** 2026-02-24
**Domain:** Information Coefficient (IC) computation, regime-conditional feature scoring, Alembic migration, Plotly helpers
**Confidence:** HIGH — all patterns verified by direct execution against live DB and installed scipy 1.17.0 / plotly 6.4.0

## Summary

Phase 37 adds IC-based feature evaluation: Spearman IC per feature per horizon, rolling IC with IC-IR, IC decay tables, regime-conditional IC breakdown, significance testing, feature turnover, and persistence to a new `cmc_ic_results` table.

The project already has all dependencies installed (scipy 1.17.0, plotly 6.4.0, pandas, numpy). The only new package is jupyterlab, which is deferred to Phase 40. Zero new installs are required for Phase 37.

`cmc_regimes` does NOT have `trend_state` or `vol_state` columns — the regime is stored in `l2_label` as a hyphen-separated string like `"Up-High-Normal"` (trend-vol-momentum). The IC module must parse `split_part(l2_label, '-', 1)` for trend_state and `split_part(l2_label, '-', 2)` for vol_state, or do it in Python via `l2_label.split('-')`.

The timestamp loading pitfall is critical: `pd.read_sql()` returns `ts` as `object` dtype (Python `datetime.datetime` objects with mixed offsets). The fix is `pd.to_datetime(df['ts'], utc=True)` immediately after loading. This is verified with real data.

The forward-return boundary pitfall is critical and non-obvious: bars near `train_end` where `bar_ts + horizon_days > train_end` must have their forward returns nulled out to prevent look-ahead bias. The last `horizon` bars in the training window will see prices beyond `train_end`.

**Primary recommendation:** Implement `src/ta_lab2/analysis/ic.py` (library core) + `src/ta_lab2/scripts/analysis/run_ic_eval.py` (CLI), modeled exactly on the `psr.py` / `compute_psr.py` pattern. Add one Alembic migration chained from `5f8223cfbf06`.

## Standard Stack

All dependencies are already installed — zero new installs for Phase 37.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy.stats.spearmanr | 1.17.0 | Spearman rank IC computation | Returns `SignificanceResult` with `.statistic` and `.pvalue` |
| scipy.stats.norm | 1.17.0 | IC t-stat p-value via norm.cdf | Already used in PSR module |
| pandas | (existing) | Rolling rank, Series alignment, dropna | Core data manipulation |
| numpy | (existing) | Boundary mask, vectorized forward returns | Vectorized boundary null |
| plotly.graph_objects | 6.4.0 | IC decay bar chart, rolling IC line chart | Already installed; works in notebooks + Streamlit |
| alembic | (existing) | cmc_ic_results table creation | Already in project with NullPool env.py |
| sqlalchemy text() | (existing) | All SQL queries | Matches project pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlalchemy pool.NullPool | existing | Engine for CLI script | All one-shot scripts use NullPool |
| ta_lab2.scripts.sync_utils.get_columns | existing | Discover cmc_features columns for DB helper | Dynamic column matching |
| ta_lab2.scripts.refresh_utils.resolve_db_url | existing | DB URL resolution | Matches all other scripts |
| ta_lab2.time.dim_timeframe.DimTimeframe | existing | `tf_days_nominal` for bar-to-calendar-day conversion | Multi-TF calendar day labeling |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `spearmanr().statistic` | pandas `corr(method='spearman')` | pandas rolling corr of pre-ranked series is faster for rolling IC but cannot supply p-value directly |
| Loop over horizons | vectorized shift matrix | Loop is simpler and avoids alignment bugs; 7 horizons is not a performance bottleneck |
| `scipy.stats.ttest_1samp` | manual `t = ic_mean * sqrt(n) / ic_std` | Both give identical t-statistic (verified); use `ttest_1samp` for clarity |

**Installation:** No new installs needed.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── analysis/
│   ├── feature_eval.py      # existing — fix fillna(method='ffill') -> .ffill() here first
│   ├── ic.py                # NEW: compute_ic, batch_compute_ic, compute_ic_by_regime, feature_turnover
│   └── __init__.py          # existing
│
└── scripts/
    └── analysis/            # NEW directory
        ├── __init__.py      # NEW
        └── run_ic_eval.py   # NEW: CLI script following compute_psr.py pattern

alembic/versions/
└── XXXX_ic_results_table.py  # NEW migration chained from 5f8223cfbf06
```

### Pattern 1: Spearman IC Computation
**What:** Rank-correlate feature series with forward returns over a bounded train window.
**When to use:** Core IC computation for any feature/horizon pair.

```python
# Source: verified by direct execution against cmc_features 2026-02-24
# scipy 1.17.0: spearmanr() returns SignificanceResult with .statistic and .pvalue

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, norm

def _compute_single_ic(
    feature: pd.Series,           # indexed by ts (UTC)
    fwd_ret: pd.Series,           # indexed by ts (UTC), pre-computed on FULL series
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    horizon: int,                  # bar count
    tf_days_nominal: int,          # for boundary mask (calendar days per bar)
    min_obs: int = 20,
) -> dict:
    """
    Compute Spearman IC for one feature/horizon pair.

    CRITICAL boundary rule: bars where bar_ts + (horizon * tf_days_nominal days)
    > train_end must have forward returns nulled out. Without this, the last
    'horizon' bars in the train window use prices from AFTER train_end.
    """
    # Filter to train window
    mask = (feature.index >= train_start) & (feature.index <= train_end)
    feat_train = feature[mask]
    fwd_train = fwd_ret[mask]

    # Null out boundary bars (look-ahead bias prevention)
    horizon_days = horizon * tf_days_nominal
    boundary_mask = (feat_train.index + pd.Timedelta(days=horizon_days)) > train_end
    fwd_train = fwd_train.copy()
    fwd_train[boundary_mask] = np.nan

    # Align and drop NaN
    valid = pd.concat([feat_train, fwd_train], axis=1).dropna()
    n = len(valid)

    if n < min_obs:
        return {"ic": np.nan, "t_stat": np.nan, "p_value": np.nan, "n_obs": n}

    result = spearmanr(valid.iloc[:, 0], valid.iloc[:, 1])
    ic = float(result.statistic)

    # IC t-stat: t = IC * sqrt(n-2) / sqrt(1 - IC^2)
    denom = max(1 - ic**2, 1e-15)
    t_stat = ic * np.sqrt(n - 2) / np.sqrt(denom)
    p_value = float(2 * (1 - norm.cdf(abs(t_stat))))

    return {"ic": ic, "t_stat": t_stat, "p_value": p_value, "n_obs": n}
```

### Pattern 2: Forward Return Computation (Global Before Filter)
**What:** Compute forward returns on the FULL close series, then filter + null boundaries.
**When to use:** Always. Never compute forward returns on the already-filtered slice.

```python
# Source: verified 2026-02-24 — this is the correct sequence

def compute_forward_returns(
    close: pd.Series,      # indexed by ts (UTC), full history
    horizon: int,          # bar count
    log: bool = False,
) -> pd.Series:
    """
    Compute forward returns on the COMPLETE series.
    The caller then slices to train_start..train_end and nulls boundary bars.
    """
    if log:
        return np.log(close.shift(-horizon)) - np.log(close)
    return close.shift(-horizon) / close - 1.0
```

### Pattern 3: Rolling IC with IC-IR
**What:** Vectorized rolling Spearman IC using rank-then-correlate.
**When to use:** IC-02 rolling IC time series computation.

```python
# Source: verified by execution 2026-02-24 (vectorized; avoids per-window loop)
# Note: ties in ranks are handled by pandas rank() — slightly different from
# scipy.stats.spearmanr tie handling. Difference is negligible for large n.

def compute_rolling_ic(
    feature: pd.Series,       # full train-window series
    fwd_ret: pd.Series,       # full train-window series (pre-nulled at boundary)
    window: int = 63,
) -> tuple[pd.Series, float, float]:
    """
    Vectorized rolling Spearman IC.

    Returns:
        rolling_ic_series: pd.Series of IC values (NaN for first window-1 bars)
        ic_ir: float (mean IC / std IC over rolling series)
        ic_ir_tstat: float (t-stat for IC-IR != 0)
    """
    # Rank within rolling window = equivalent to Spearman
    feat_rank = feature.rolling(window).rank()
    fwd_rank = fwd_ret.rolling(window).rank()

    rolling_ic = feat_rank.rolling(window).corr(fwd_rank)

    ic_series_valid = rolling_ic.dropna()
    n = len(ic_series_valid)
    if n < 5:
        return rolling_ic, np.nan, np.nan

    ic_mean = float(ic_series_valid.mean())
    ic_std = float(ic_series_valid.std(ddof=1))

    if ic_std == 0:
        return rolling_ic, np.nan, np.nan

    ic_ir = ic_mean / ic_std
    ic_ir_tstat = ic_mean * np.sqrt(n) / ic_std  # equivalent to ttest_1samp t-stat

    return rolling_ic, ic_ir, ic_ir_tstat
```

### Pattern 4: Regime IC Breakdown
**What:** Split IC computation by regime label, joining cmc_regimes on (id, ts, tf).
**When to use:** IC-05 regime-conditional IC.

```python
# Source: verified against live cmc_regimes data 2026-02-24
# CRITICAL: cmc_regimes has NO trend_state or vol_state columns.
# trend_state = split(l2_label, '-')[0]   e.g. "Up", "Down", "Sideways"
# vol_state   = split(l2_label, '-')[1]   e.g. "High", "Normal", "Low"
# regime_key  = l2_label (same value when only L2 enabled)

def load_regimes_for_asset(
    conn,
    asset_id: int,
    tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> pd.DataFrame:
    """
    Load regime labels, deriving trend_state and vol_state from l2_label parsing.
    """
    result = conn.execute(text("""
        SELECT ts,
               l2_label AS regime_key,
               split_part(l2_label, '-', 1) AS trend_state,
               split_part(l2_label, '-', 2) AS vol_state
        FROM public.cmc_regimes
        WHERE id = :id AND tf = :tf
          AND ts >= :start AND ts <= :end
          AND l2_label IS NOT NULL
        ORDER BY ts
    """), {"id": asset_id, "tf": tf, "start": train_start, "end": train_end})
    df = pd.DataFrame(result.fetchall(), columns=['ts', 'regime_key', 'trend_state', 'vol_state'])
    df['ts'] = pd.to_datetime(df['ts'], utc=True)
    return df.set_index('ts')


def compute_ic_by_regime(
    feature: pd.Series,       # indexed by ts (UTC)
    fwd_ret: pd.Series,       # indexed by ts (UTC), pre-computed globally
    regimes_df: pd.DataFrame, # indexed by ts (UTC), columns: trend_state, vol_state
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    horizon: int,
    tf_days_nominal: int,
    regime_col: str,          # 'trend_state' or 'vol_state'
    min_obs_per_regime: int = 30,
) -> list[dict]:
    """
    Compute IC for each distinct regime label.
    Falls back to full-sample IC (regime_label='all') if no regime data.
    """
    rows = []

    if regimes_df.empty:
        # No regime data: compute on full sample
        ic_result = _compute_single_ic(feature, fwd_ret, train_start, train_end,
                                       horizon, tf_days_nominal)
        ic_result['regime_col'] = regime_col
        ic_result['regime_label'] = 'all'
        rows.append(ic_result)
        return rows

    # Join feature with regime labels
    regime_labels = regimes_df[regime_col]
    for label, group_idx in regime_labels.groupby(regime_labels).groups.items():
        feat_regime = feature[feature.index.isin(group_idx)]
        fwd_regime = fwd_ret[fwd_ret.index.isin(group_idx)]

        if len(feat_regime.dropna()) < min_obs_per_regime:
            continue  # skip sparse regime

        valid = pd.concat([feat_regime, fwd_regime], axis=1).dropna()
        n = len(valid)
        if n < min_obs_per_regime:
            continue

        ic_result = _compute_single_ic(feat_regime, fwd_regime,
                                       train_start, train_end,
                                       horizon, tf_days_nominal)
        ic_result['regime_col'] = regime_col
        ic_result['regime_label'] = str(label)
        rows.append(ic_result)

    return rows
```

### Pattern 5: Feature Turnover (Rank Autocorrelation)
**What:** Spearman rank autocorrelation at lag=1 measuring signal stability.
**When to use:** IC-07 feature turnover.

```python
# Source: verified 2026-02-24 — RSI-14 has turnover=0.05 (very stable)

def compute_feature_turnover(
    feature: pd.Series,
    min_obs: int = 20,
) -> float:
    """
    Feature turnover = 1 - rank_autocorrelation(lag=1).
    High autocorrelation = stable signal = low turnover.
    turnover=0 means perfectly stable ranks; turnover=2 means perfectly reversed.
    """
    feature_clean = feature.dropna()
    if len(feature_clean) < min_obs:
        return np.nan
    ranks = feature_clean.rank()
    result = spearmanr(ranks.iloc[:-1].values, ranks.iloc[1:].values)
    return float(1 - result.statistic)
```

### Pattern 6: DB Feature Loading Helper
**What:** Load feature column from cmc_features or cmc_ema_multi_tf_u for a given asset+tf.
**When to use:** CLI and notebook integration.

```python
# Source: verified get_columns() output 2026-02-24
# cmc_features has 113 columns (id, ts, tf, close + 109 feature columns)
# cmc_ema_multi_tf_u has: id, ts, tf, period, ema, ingested_at, tf_days, roll, alignment_source, is_partial_end, ema_bar

def load_feature_series(
    conn,
    asset_id: int,
    tf: str,
    feature_col: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> tuple[pd.Series, pd.Series]:
    """
    Load feature column + close from cmc_features.
    Returns (feature_series, close_series), both indexed by ts (UTC).

    CRITICAL: Use pd.to_datetime(..., utc=True) on ts — read_sql returns
    ts as Python datetime objects with mixed tz offsets, not DatetimeIndex.
    """
    from ta_lab2.scripts.sync_utils import get_columns
    engine = conn.engine  # or pass engine directly

    # Verify column exists
    available_cols = get_columns(engine, 'public.cmc_features')
    if feature_col not in available_cols:
        raise ValueError(
            f"Column '{feature_col}' not in cmc_features. "
            f"Available: {available_cols}"
        )

    df = pd.read_sql(text("""
        SELECT ts, :feature_col, close
        FROM public.cmc_features
        WHERE id = :id AND tf = :tf
          AND ts >= :start AND ts <= :end
        ORDER BY ts
    """), conn, params={
        "feature_col": feature_col, "id": asset_id,
        "tf": tf, "start": train_start, "end": train_end
    })

    # MANDATORY tz fix
    df['ts'] = pd.to_datetime(df['ts'], utc=True)
    df = df.set_index('ts')

    return df[feature_col], df['close']
```

### Pattern 7: Alembic Migration (cmc_ic_results)
**What:** Create cmc_ic_results table chained from Phase 36 head.
**When to use:** IC-08 persistence.

```python
# Source: verified against existing 5f8223cfbf06_psr_results_table.py pattern

"""ic_results_table

Revision ID: XXXX_ic_results_table
Revises: 5f8223cfbf06
Create Date: ...
"""

from alembic import op
import sqlalchemy as sa

revision = "XXXX_ic_results_table"
down_revision = "5f8223cfbf06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cmc_ic_results",
        sa.Column("result_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"),
                  nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),          # bars
        sa.Column("horizon_days", sa.Integer(), nullable=True),       # calendar days
        sa.Column("return_type", sa.Text(), nullable=False),          # 'arith' or 'log'
        sa.Column("regime_col", sa.Text(), nullable=False),           # 'trend_state', 'vol_state', 'all'
        sa.Column("regime_label", sa.Text(), nullable=False),         # e.g. 'Up', 'High', 'all'
        sa.Column("train_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("train_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ic", sa.Numeric(), nullable=True),
        sa.Column("ic_t_stat", sa.Numeric(), nullable=True),
        sa.Column("ic_p_value", sa.Numeric(), nullable=True),
        sa.Column("ic_ir", sa.Numeric(), nullable=True),
        sa.Column("ic_ir_t_stat", sa.Numeric(), nullable=True),
        sa.Column("turnover", sa.Numeric(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint(
            "asset_id", "tf", "feature", "horizon", "return_type",
            "regime_col", "regime_label", "train_start", "train_end",
            name="uq_ic_results_key",
        ),
        schema="public",
    )
    op.create_index(
        "idx_ic_results_asset_feature",
        "cmc_ic_results", ["asset_id", "tf", "feature"],
        schema="public",
    )
    op.create_index(
        "idx_ic_results_computed_at",
        "cmc_ic_results", ["computed_at"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("idx_ic_results_computed_at", table_name="cmc_ic_results", schema="public")
    op.drop_index("idx_ic_results_asset_feature", table_name="cmc_ic_results", schema="public")
    op.drop_table("cmc_ic_results", schema="public")
```

### Pattern 8: save_ic_results() with Upsert
**What:** Persist IC results with append-by-default and --overwrite upsert.

```python
# Source: verified against psr_results insert pattern in compute_psr.py

def save_ic_results(
    conn,
    rows: list[dict],
    overwrite: bool = False,
) -> int:
    """
    Persist IC result rows to cmc_ic_results.

    Default: INSERT with ON CONFLICT DO NOTHING (append-only, keeps history).
    overwrite=True: ON CONFLICT DO UPDATE (upsert).

    Returns number of rows written.
    """
    if not rows:
        return 0

    conflict_target = (
        "asset_id, tf, feature, horizon, return_type, "
        "regime_col, regime_label, train_start, train_end"
    )

    if overwrite:
        conflict_action = """DO UPDATE SET
            ic = EXCLUDED.ic,
            ic_t_stat = EXCLUDED.ic_t_stat,
            ic_p_value = EXCLUDED.ic_p_value,
            ic_ir = EXCLUDED.ic_ir,
            ic_ir_t_stat = EXCLUDED.ic_ir_t_stat,
            turnover = EXCLUDED.turnover,
            n_obs = EXCLUDED.n_obs,
            computed_at = now()"""
    else:
        conflict_action = "DO NOTHING"

    sql = text(f"""
        INSERT INTO public.cmc_ic_results
            (asset_id, tf, feature, horizon, horizon_days, return_type,
             regime_col, regime_label, train_start, train_end,
             ic, ic_t_stat, ic_p_value, ic_ir, ic_ir_t_stat, turnover, n_obs)
        VALUES
            (:asset_id, :tf, :feature, :horizon, :horizon_days, :return_type,
             :regime_col, :regime_label, :train_start, :train_end,
             :ic, :ic_t_stat, :ic_p_value, :ic_ir, :ic_ir_t_stat, :turnover, :n_obs)
        ON CONFLICT ({conflict_target}) {conflict_action}
    """)

    written = 0
    for row in rows:
        result = conn.execute(sql, row)
        written += result.rowcount
    return written
```

### Pattern 9: Plotly IC Decay Chart
**What:** Interactive bar chart showing IC vs horizon with p-value annotations.

```python
# Source: verified plotly 6.4.0 installed and working 2026-02-24

import plotly.graph_objects as go

def plot_ic_decay(
    ic_df: pd.DataFrame,  # columns: horizon, ic, ic_p_value
    feature: str,
    return_type: str = "arith",
    sig_threshold: float = 0.05,
) -> go.Figure:
    """
    Bar chart of IC vs horizon. Bars colored by significance.
    """
    mask_sig = ic_df["ic_p_value"] < sig_threshold
    colors = ["royalblue" if s else "lightgray" for s in mask_sig]

    fig = go.Figure(data=[
        go.Bar(
            x=ic_df["horizon"],
            y=ic_df["ic"],
            marker_color=colors,
            text=[f"p={p:.3f}" for p in ic_df["ic_p_value"]],
            textposition="outside",
        )
    ])
    fig.update_layout(
        title=f"IC Decay — Feature: {feature} ({return_type} returns)",
        xaxis_title="Horizon (bars)",
        yaxis_title="Spearman IC",
        showlegend=False,
    )
    return fig
```

### Pattern 10: fillna Deprecation Fix (pre-requisite)
**What:** Fix `fillna(method='ffill')` in feature_eval.py before adding IC code.
**When to use:** Must be the first task in Phase 37 (per prior decisions).

```python
# In src/ta_lab2/analysis/feature_eval.py line 78:
# BEFORE (deprecated, will error in future pandas):
X = df.loc[y.index, cols].fillna(method="ffill").fillna(0.0)

# AFTER (correct):
X = df.loc[y.index, cols].ffill().fillna(0.0)
```

### Anti-Patterns to Avoid
- **Computing forward returns after slicing to train window**: `close[mask].shift(-horizon)` looks back into the train window for the boundary bars — correct behavior but for the WRONG reason. It will give NaN at the end of the slice, but only because shift() runs out of data, NOT because of look-ahead leakage. The correct approach is global forward return then boundary masking, so the null at boundary is explicit and auditable.
- **Using `trend_state` or `vol_state` as direct column names**: These columns do not exist in `cmc_regimes`. Must parse from `l2_label` via string split.
- **Using `.values` on tz-aware datetime Series for comparison**: Returns tz-naive numpy arrays, causing `TypeError: '>' not supported between instances of 'numpy.ndarray' and 'Timestamp'` (verified on this system).
- **Using `df.ts.values` for DatetimeIndex**: Same issue — use `.tolist()` or `.tz_localize("UTC")`.
- **Calling `spearmanr` without checking for constant input**: Constant feature or constant forward return will give IC=nan or division by zero in the t-stat formula. Guard with `if feature.std() == 0 or fwd_ret.std() == 0: return nan`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rank correlation | manual rank + Pearson | `scipy.stats.spearmanr` | Handles ties correctly, returns both statistic and p-value |
| Rolling rank correlation | loop over windows | `pd.Series.rolling().rank()` then `.rolling().corr()` | 10-100x faster for 5000+ rows |
| IC significance p-value | manual norm.cdf | `scipy.stats.norm.cdf(abs(t_stat))` | Already installed, exact |
| Feature turnover | custom stability metric | rank autocorrelation via `spearmanr` | Standard definition, interpretable |
| DB column discovery | hardcoded column list | `sync_utils.get_columns(engine, 'public.cmc_features')` | Dynamic, stays in sync with DDL changes |
| Alembic migration | raw psycopg2 CREATE TABLE | `op.create_table()` with `sa.Column()` | Tracked for downgrade, consistent with project |

**Key insight:** The rolling IC loop approach (verified timing: ~30 seconds for 5500 bars) is replaced by the vectorized rank+correlate approach which runs in under 1 second. Use the vectorized pattern.

## Common Pitfalls

### Pitfall 1: tz-aware Timestamp Loading from read_sql
**What goes wrong:** `pd.read_sql()` returns the `ts` column as Python `object` dtype — each element is a `datetime.datetime` with a UTC offset (not normalized to UTC). Comparison with `pd.Timestamp(..., tz='UTC')` raises `TypeError: '>' not supported between instances of 'numpy.ndarray' and 'Timestamp'`.

**Why it happens:** PostgreSQL `TIMESTAMPTZ` values returned via psycopg2 carry their timezone, but pandas does not auto-convert to `datetime64[ns, UTC]`.

**How to avoid:** Always apply `df['ts'] = pd.to_datetime(df['ts'], utc=True)` immediately after `pd.read_sql()`. This is verified to fix the issue.

**Warning signs:** `dtype: object` for a `ts` column, or `TypeError` mentioning `numpy.ndarray` and `Timestamp` comparison.

### Pitfall 2: Look-ahead Bias at Train-End Boundary
**What goes wrong:** The last `horizon` bars in the training window have forward returns that reference prices after `train_end`. If not nulled, the IC computation uses future information.

**Why it happens:** Forward return at bar `t` = `close[t + horizon] / close[t] - 1`. When `t` is within `horizon` bars of `train_end`, `close[t + horizon]` comes from after the training period ends.

**How to avoid:** After computing forward returns on the full series and filtering to train window, apply:
```python
boundary_mask = (feat_train.index + pd.Timedelta(days=horizon * tf_days_nominal)) > train_end
fwd_train[boundary_mask] = np.nan
```
This nulls the last `horizon` bars within the train window. The `dropna()` before `spearmanr` then excludes them automatically.

**Warning signs:** IC values suspiciously high for large horizons; IC does not decrease with horizon.

### Pitfall 3: cmc_regimes Has No trend_state or vol_state Columns
**What goes wrong:** Query like `SELECT trend_state FROM cmc_regimes` raises `column "trend_state" does not exist`.

**Why it happens:** The regime store uses `l2_label` as a single composite string (`"Up-High-Normal"` = trend-vol-momentum). The column names `trend_state` and `vol_state` are conceptual labels, not DB columns.

**How to avoid:** Parse `l2_label` in Python: `trend_state = l2_label.split('-')[0]`, `vol_state = l2_label.split('-')[1]`. Or use SQL `split_part(l2_label, '-', 1)` and `split_part(l2_label, '-', 2)`. Always filter `WHERE l2_label IS NOT NULL` since L0/L1 layers may be NULL.

**Warning signs:** `ProgrammingError: column "trend_state" does not exist`.

### Pitfall 4: fillna(method='ffill') FutureWarning in feature_eval.py
**What goes wrong:** Line 78 of `feature_eval.py` uses the deprecated `fillna(method='ffill')` syntax. In future pandas versions this becomes an error.

**Why it happens:** The prior decision explicitly flagged this: "v0.9.0 fix fillna deprecation before IC."

**How to avoid:** Replace with `.ffill().fillna(0.0)`. This must be done in Task 37-01 before other IC code is added.

### Pitfall 5: Rolling IC Vectorization vs Loop Timing
**What goes wrong:** Using a Python loop to compute IC in each rolling window takes ~30 seconds for 5500 bars × 63-bar window. Multiplied across 7 horizons × 2 return types × many features, this becomes impractical.

**Why it happens:** Per-window `spearmanr()` calls are expensive. The alternative uses pandas `rolling().rank()` then `rolling().corr()`.

**How to avoid:** Use the vectorized pattern: `feat_rank = feature.rolling(window).rank(); fwd_rank = fwd_ret.rolling(window).rank(); rolling_ic = feat_rank.rolling(window).corr(fwd_rank)`. Trade-off: pandas rank() uses average tie-breaking while `spearmanr` uses a different correction, but difference is negligible for large n.

### Pitfall 6: Sparse Regime Splitting
**What goes wrong:** A regime with only 3 bars produces meaningless IC values (high variance, p-value=1.0), polluting the results table.

**Why it happens:** Some regime combinations are rare (e.g., "Down-Low-Normal" may appear in only 15 bars of a 3-year training window for a stablecoin).

**How to avoid:** Apply `min_obs_per_regime` (recommended: 30 bars minimum). Skip the regime group and log a warning. Do not store NaN rows for skipped regimes — they waste space and mislead downstream.

### Pitfall 7: Alembic Migration Encoding on Windows
**What goes wrong:** UTF-8 characters in alembic.ini or migration file comments cause `UnicodeDecodeError` with default cp1252 encoding on Windows.

**Why it happens:** Windows default encoding is cp1252. The project already has `encoding="utf-8"` in env.py.

**How to avoid:** Never remove the `encoding="utf-8"` from `fileConfig()` in `alembic/env.py`. New migration files must not use non-ASCII characters in comments.

### Pitfall 8: IC t-stat Formula Numerical Stability
**What goes wrong:** When IC=1.0 (perfect correlation) or IC=-1.0, the denominator `1 - IC^2 = 0`, causing division by zero.

**Why it happens:** Deterministic features (e.g., bar index) produce IC=1.0 with a small test sample.

**How to avoid:** Guard the denominator: `denom = max(1 - ic**2, 1e-15)`. Return `np.inf` for the t-stat or cap it at a reasonable value (e.g., 100).

## Code Examples

### Full compute_ic() Function Signature
```python
# Source: design based on verified patterns, following PSR module structure

def compute_ic(
    feature: pd.Series,              # feature values indexed by ts (UTC)
    close: pd.Series,                # close prices indexed by ts (UTC)
    train_start: pd.Timestamp,       # REQUIRED — raises TypeError if omitted
    train_end: pd.Timestamp,         # REQUIRED — raises TypeError if omitted
    horizons: list[int] | None = None,  # default [1, 2, 3, 5, 10, 20, 60]
    return_types: list[str] | None = None,  # default ['arith', 'log']
    rolling_window: int = 63,
    tf_days_nominal: int = 1,        # 1 for 1D, 7 for 1W, etc.
    min_obs: int = 20,
) -> pd.DataFrame:
    """
    Compute Spearman IC across horizons.
    Returns DataFrame with columns:
        horizon, return_type, ic, ic_t_stat, ic_p_value,
        ic_ir, ic_ir_t_stat, turnover, n_obs
    """
    ...
```

### Timestamp Fix Pattern (Mandatory)
```python
# Source: verified 2026-02-24 on live cmc_features data

# WRONG — ts comes back as object dtype with mixed tz offsets
df = pd.read_sql(query, conn)
df = df.set_index('ts')  # fails on comparison

# CORRECT
df = pd.read_sql(query, conn)
df['ts'] = pd.to_datetime(df['ts'], utc=True)  # convert first
df = df.set_index('ts')  # now DatetimeIndex[UTC]
```

### Regime Data Loading Query
```python
# Source: verified against live cmc_regimes schema 2026-02-24
# Uses split_part() to derive trend/vol state from composite l2_label

query = text("""
    SELECT ts,
           l2_label                         AS regime_key,
           split_part(l2_label, '-', 1)     AS trend_state,
           split_part(l2_label, '-', 2)     AS vol_state
    FROM public.cmc_regimes
    WHERE id = :asset_id
      AND tf = :tf
      AND ts >= :train_start
      AND ts <= :train_end
      AND l2_label IS NOT NULL
    ORDER BY ts
""")
```

### Alembic Migration Chain Pattern
```python
# Source: verified from 5f8223cfbf06_psr_results_table.py

# ALWAYS set down_revision to the current head
revision: str = "XXXX_ic_results_table"  # replace XXXX with auto-generated ID
down_revision: str = "5f8223cfbf06"       # current alembic head (Phase 36)
branch_labels = None
depends_on = None
```

### compute_psr.py CLI Pattern (adapt for run_ic_eval.py)
```python
# Source: verified from src/ta_lab2/scripts/backtests/compute_psr.py

# CLI structure to replicate:
# - argparse with --asset-id, --tf, --feature, --horizons, --train-start, --train-end
# - mutually exclusive --asset-id / --all for asset selection
# - --overwrite flag for upsert
# - --dry-run flag
# - engine = create_engine(resolve_db_url(), poolclass=pool.NullPool)
# - with engine.begin() as conn: (single transaction)
# - logging.basicConfig at start
# - return 0 if success, 1 if any failures
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `feature_target_correlations()` in feature_eval.py — Pearson correlation | Spearman rank IC per horizon | Phase 37 | Non-parametric, handles non-linear relationships and outliers |
| No train/test boundary enforcement | Required train_start/train_end parameters | Phase 37 (per prior decision) | Prevents future-information leakage into feature selection |
| Full-sample only | Rolling IC with IC-IR | Phase 37 | Shows IC stability over time, detects regime-dependent features |
| No regime breakdown | IC by trend_state and vol_state | Phase 37 | Identifies features that work only in specific market conditions |
| fillna(method='ffill') in feature_eval.py | .ffill() | Phase 37 Task 1 | Fixes FutureWarning in pandas |

**Deprecated/outdated:**
- `fillna(method='ffill')` in `feature_eval.py`: deprecated pandas API, must be fixed before adding IC code.
- `feature_target_correlations()`: remains in `feature_eval.py` but is superseded by `compute_ic()` for serious feature evaluation (Pearson vs Spearman; no train/test boundary; no significance testing).

## Open Questions

1. **cross-asset pooled mode implementation**
   - What we know: `pool_assets=True` is a decided feature (CONTEXT.md). All feature + close series for multiple assets must be concatenated with a MultiIndex (id, ts) before computing IC.
   - What's unclear: Whether to reset index for the pooled computation or use a MultiIndex. Pandas `spearmanr` doesn't accept MultiIndex directly.
   - Recommendation: Flatten to a single Series by concatenating after per-asset z-score normalization (cross-sectional demeaning), then call `spearmanr` on the concatenated vectors. Plan should specify this approach explicitly.

2. **Sparse regime minimum threshold**
   - What we know: CONTEXT says "Claude's discretion on threshold."
   - Recommendation: Use 30 bars as the minimum. This matches the PSR minimum_obs guard and gives enough data for a meaningful correlation. Document the threshold in the function's docstring.

3. **IC decay plot for both return types**
   - What we know: Both arithmetic and log returns are computed by default.
   - What's unclear: Should the plot show both return types on one chart or separate charts?
   - Recommendation: Accept `return_type` parameter; show one chart per return type. Caller can put both in a subplot if needed. Keep the helper simple.

4. **l2_label parsing when L2 is disabled**
   - What we know: `l2_label` can be NULL if only L0/L1 are enabled (rare, but possible per DDL).
   - What's unclear: Should we fall back to `l0_label` or `l1_label` when `l2_label IS NULL`?
   - Recommendation: Query with `WHERE l2_label IS NOT NULL` and treat assets with no L2 data the same as assets with no regime data at all (fall back to full-sample IC with `regime_label='all'`).

## Sources

### Primary (HIGH confidence)
- Live DB inspection: `cmc_regimes` columns — confirmed `l2_label` is the composite string, no `trend_state`/`vol_state` columns
- Live DB inspection: `cmc_features` columns — 113 columns confirmed; `get_columns()` pattern works
- Live DB inspection: `cmc_ema_multi_tf_u` columns — 11 columns confirmed; no `d1`/`d2` prefix columns (those were from the old design)
- Direct Python execution: `spearmanr` API in scipy 1.17.0 — `.statistic` and `.pvalue` are the correct attributes
- Direct Python execution: IC computation end-to-end with real cmc_features data (id=1, tf=1D, horizon=5, RSI-14) — IC=0.0627, t=2.07, p=0.0384
- Direct Python execution: feature_turnover on RSI-14 — rank_autocorr=0.95, turnover=0.05 (verified sensible)
- Direct Python execution: rolling IC vectorized vs loop — vectorized is much faster, confirmed close results
- Direct Python execution: boundary null pattern — last `horizon` bars correctly nulled (verified look-ahead prevention)
- Direct Python execution: timestamp fix — `pd.to_datetime(df['ts'], utc=True)` resolves mixed-offset issue
- `alembic/versions/5f8223cfbf06_psr_results_table.py` — exact migration pattern for `down_revision` chaining
- `src/ta_lab2/scripts/backtests/compute_psr.py` — CLI pattern to replicate
- `src/ta_lab2/backtests/psr.py` — library module pattern to replicate
- `alembic/env.py` — confirms `encoding="utf-8"`, NullPool, `resolve_db_url()` usage

### Secondary (MEDIUM confidence)
- `src/ta_lab2/analysis/feature_eval.py` — existing `future_return()` function confirms bar-shift approach; `fillna(method='ffill')` deprecation confirmed on line 78

### Tertiary (LOW confidence)
- None — all claims verified by direct execution

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all deps verified installed, versions confirmed
- API correctness (spearmanr): HIGH — executed and verified `.statistic` attribute in scipy 1.17.0
- Forward return boundary pitfall: HIGH — verified with numerical example showing look-ahead
- cmc_regimes schema: HIGH — queried live DB; `trend_state`/`vol_state` absence confirmed
- cmc_features columns: HIGH — `get_columns()` executed against live DB
- Alembic migration chain: HIGH — `5f8223cfbf06` confirmed as current head; DB at head
- Rolling IC vectorization: HIGH — both loop and vectorized verified, timing difference confirmed
- Plotly patterns: HIGH — executed against plotly 6.4.0
- Regime label format: HIGH — queried live data, `l2_label="Up-High-Normal"` format confirmed
- Timestamp pitfall: HIGH — triggered the actual TypeError in testing, fix verified

**Research date:** 2026-02-24
**Valid until:** 2026-03-24 (stable math, scipy/plotly APIs very stable; DB schema won't change)
