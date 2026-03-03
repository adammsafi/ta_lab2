# Phase 70: Cross-Asset Aggregation - Research

**Researched:** 2026-03-03
**Domain:** Cross-asset correlation, funding rate aggregation, crypto-macro regime detection
**Confidence:** HIGH

## Summary

Phase 70 builds cross-asset signals on top of well-established project infrastructure: the existing `cmc_cross_asset_corr` pairwise correlation engine (Phase 41), the `cmc_funding_rates` 6-venue funding rate store (Phase 51), the `fred.fred_macro_features` 52-column macro feature table (Phase 65-66), the `cmc_macro_regimes` 4-dimensional regime classifier (Phase 67), and the `PortfolioOptimizer` with PyPortfolioOpt (Phase 58).

The phase requires four deliverables: (1) BTC/ETH 30d rolling correlation stored in a new cross-asset table, (2) cross-asset correlation matrix with high-correlation flag (>0.7 threshold), (3) aggregate funding rate signal with z-scores across 6 venues, and (4) crypto-macro correlation regime detecting sign flips between crypto returns and macro variables (VIX, DXY, HY OAS, net liquidity).

All four deliverables follow established patterns in the codebase: Alembic migrations for DDL, watermark-based incremental refresh, temp table + ON CONFLICT upsert, YAML-configurable thresholds, and CLI scripts with --dry-run/--verbose/--full flags. The primary complexity is in the schema design decisions (Claude's discretion per CONTEXT.md) and wiring the diversification reduction into the existing PortfolioOptimizer.

**Primary recommendation:** Implement as 5-6 plans: (1) Alembic migration for 3 new tables, (2) cross-asset correlation compute module, (3) aggregate funding rate compute module, (4) crypto-macro correlation regime module with sign-flip detection, (5) portfolio optimizer diversification override integration, (6) CLI refresh scripts and YAML config.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | existing | Rolling correlation, z-score, resampling | Already used everywhere in the codebase |
| scipy.stats | existing | `pearsonr`, `spearmanr` for pairwise correlation | Already used in `refresh_cmc_cross_asset_corr.py` |
| SQLAlchemy | existing | DB engine, text SQL, temp table upsert | Project standard |
| Alembic | existing | DDL migrations | Project standard |
| PyYAML | existing | YAML threshold config (macro_regime_config.yaml pattern) | Already used for macro regime config |
| PyPortfolioOpt | existing | `CovarianceShrinkage`, `EfficientFrontier` | Already used in `portfolio/optimizer.py` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | existing | NaN handling, array operations | Rolling window computations |
| requests | existing | Telegram notification | Sign-flip alerts |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual rolling corr | pandas `.rolling().corr()` | Pandas rolling corr is simpler but `refresh_cmc_cross_asset_corr.py` uses manual loop with scipy for p-values; use the same pattern for consistency |
| New YAML file | Extend `macro_regime_config.yaml` | New YAML file is cleaner separation; Phase 70 thresholds are distinct from Phase 67's 4-dimension regime |

**Installation:**
No new dependencies required. All libraries are already in the project.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
  macro/
    cross_asset.py          # Core computation: correlation matrix, funding agg, crypto-macro corr
  scripts/
    macro/
      refresh_cross_asset_agg.py   # CLI: orchestrates all 4 XAGG requirements
  configs/
    cross_asset_config.yaml         # Thresholds: high_corr=0.7, sign_flip=0.3, windows, etc.
  portfolio/
    optimizer.py                    # MODIFY: add covariance override for high-corr regime
```

### Pattern 1: New Table Schema Design (Claude's Discretion)

**What:** Three new tables for the four XAGG requirements.

**Table 1: `cmc_cross_asset_agg`** (crypto-only pairwise, no FRED data)
- PK: `(date, pair_key)` where pair_key = 'BTC_ETH' or asset pair identifier
- Columns: `btc_eth_corr_30d`, `avg_pairwise_corr_30d`, `high_corr_flag`, `n_assets`, `ingested_at`
- Naming: `cmc_` prefix because assets come from cmc_price_histories7 and tvc_price_histories
- Note: The CONTEXT.md says BTC/ETH 30d correlation goes in cross-asset table, NOT fred_macro_features

**Table 2: `cmc_funding_rate_agg`** (aggregate funding rate signal)
- PK: `(date, symbol)` where symbol = 'BTC' or 'ETH'
- Columns: `avg_funding_rate` (simple), `vwap_funding_rate` (vol-weighted, nullable), `n_venues`, `zscore_30d`, `zscore_90d`, `venues_included` (text array or JSON), `ingested_at`
- Naming: `cmc_` prefix because funding rates are from cmc_funding_rates
- Separate table per CONTEXT.md decision (not columns in cmc_funding_rates)

**Table 3: `crypto_macro_corr_regimes`** (crypto-macro correlation regime)
- PK: `(date, asset_id, macro_var)` where macro_var = 'vix' | 'dxy' | 'hy_oas' | 'net_liquidity'
- Columns: `corr_60d`, `prev_corr_60d` (for sign-flip detection), `sign_flip_flag`, `corr_regime` (text: 'positive' | 'negative' | 'decorrelated'), `ingested_at`
- Naming: NO `cmc_` prefix per CONTEXT.md rule -- mixes crypto (from cmc_price_histories7) with macro (from FRED)
- Note: CONTEXT says compute for ALL tradeable assets, not just BTC

**Why this design:**
- Separate tables keep concerns clean and allow independent refresh cadences
- PKs are date-level (daily granularity) because FRED data and cross-asset signals are inherently daily
- The cross-asset corr table differs from existing `cmc_cross_asset_corr` (which is per-timeframe, per-pair) -- this new table stores AGGREGATE metrics (average pairwise corr, high-corr flag)

### Pattern 2: Watermark-Based Incremental Refresh
**What:** Same pattern as `refresh_macro_features.py` and `refresh_macro_regimes.py`.
**When to use:** For all three new tables.
**Example:**
```python
# Source: refresh_macro_regimes.py pattern
def _get_watermark(engine, table_name):
    sql = text(f"SELECT MAX(date) FROM {table_name}")
    with engine.connect() as conn:
        result = conn.execute(sql).scalar()
    return str(result) if result is not None else None
```

### Pattern 3: YAML Threshold Configuration
**What:** All thresholds in a YAML config file, consistent with `macro_regime_config.yaml`.
**When to use:** For high-corr threshold (0.7), sign-flip magnitude (0.3), window sizes, z-score windows.
**Example:**
```yaml
# configs/cross_asset_config.yaml
cross_asset:
  btc_eth_corr_window: 30
  avg_pairwise_corr_window: 30
  high_corr_threshold: 0.7

crypto_macro:
  corr_window: 60
  sign_flip_threshold: 0.3  # corr must cross from >0.3 to <-0.3
  macro_vars: [vix, dxy, hy_oas, net_liquidity]

funding_agg:
  zscore_windows: [30, 90]
  venues: [binance, hyperliquid, bybit, dydx, aevo, aster]
```

### Pattern 4: Portfolio Optimizer Covariance Override
**What:** When high_corr_flag is True, inflate the off-diagonal entries of the covariance matrix before passing to PyPortfolioOpt.
**When to use:** XAGG-02 integration with Phase 58 PortfolioOptimizer.
**Example:**
```python
# Approach: scale off-diagonal covariance entries toward 1.0 when high_corr_flag=True
# This reduces perceived diversification benefit
def adjust_covariance_for_high_corr(S: pd.DataFrame, high_corr_flag: bool,
                                     blend_factor: float = 0.3) -> pd.DataFrame:
    if not high_corr_flag:
        return S
    # Create a "fully correlated" covariance matrix from S's variances
    vols = np.sqrt(np.diag(S.values))
    full_corr_cov = np.outer(vols, vols)
    # Blend: S_adj = (1 - blend_factor) * S + blend_factor * full_corr_cov
    S_adj = (1 - blend_factor) * S.values + blend_factor * full_corr_cov
    return pd.DataFrame(S_adj, index=S.index, columns=S.columns)
```

### Pattern 5: Sign-Flip Detection with Telegram Alert
**What:** Detect when crypto-macro correlation crosses the magnitude threshold and send alert.
**When to use:** XAGG-04 crypto-macro correlation regime.
**Example:**
```python
# Source: CONTEXT.md decision -- sign flip = corr going from >0.3 to <-0.3 (or vice versa)
def detect_sign_flip(current_corr: float, prev_corr: float, threshold: float = 0.3) -> bool:
    if pd.isna(current_corr) or pd.isna(prev_corr):
        return False
    positive_to_negative = prev_corr > threshold and current_corr < -threshold
    negative_to_positive = prev_corr < -threshold and current_corr > threshold
    return positive_to_negative or negative_to_positive
```

### Anti-Patterns to Avoid
- **Don't compute crypto-macro correlations on sub-daily data:** FRED data is daily (some weekly/monthly). All crypto-macro correlations must use daily returns aligned to FRED observation dates.
- **Don't forward-fill crypto returns to fill FRED gaps:** FRED data already has forward-fill in `fred_macro_features`. Compute correlation on the intersection of dates where both crypto returns AND FRED values exist.
- **Don't use `cmc_cross_asset_corr` directly for XAGG-02:** That table stores per-pair, per-timeframe correlations. XAGG-02 needs the AVERAGE pairwise correlation across all assets -- a reduction/aggregation on top.
- **Don't modify `cmc_funding_rates` table schema:** CONTEXT.md explicitly says separate aggregate table.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pairwise rolling correlation | Custom loop from scratch | Reuse `compute_pairwise_rolling_corr()` from `refresh_cmc_cross_asset_corr.py` or pandas `.rolling().corr()` | Already tested, handles NaN, scipy p-values |
| Z-score computation | Custom z-score function | `(x - x.rolling(window).mean()) / x.rolling(window).std()` | Pandas built-in rolling mean/std handles edge cases |
| Regime label hysteresis | Custom state machine | `HysteresisTracker` from `ta_lab2.regimes.hysteresis` | Already used in macro regime classifier, handles tightening/loosening |
| Telegram alerts | Custom HTTP client | `ta_lab2.notifications.telegram.send_alert()` | Already implemented with severity levels, HTML formatting |
| DB connection | Direct psycopg2 | `ta_lab2.io.get_engine()` or `resolve_db_url()` + NullPool | Project standard |
| Config loading | Hardcoded thresholds | YAML config + `yaml.safe_load()` pattern from `load_macro_regime_config()` | Consistent with Phase 67, supports profile overrides |
| Numpy scalar safety | Raw float conversion | `_to_python()` helper (hasattr check) or `_to_none()` from corr script | Prevents psycopg2 binding errors on numpy scalars |

**Key insight:** Every computation pattern needed in Phase 70 has a direct analog already implemented in the codebase. The value is in orchestrating them together and designing the right schema, not in building new primitives.

## Common Pitfalls

### Pitfall 1: Mixed Settlement Frequencies in Funding Rate Aggregation
**What goes wrong:** Venues have different settlement frequencies (1h vs 8h). Simple averaging of raw rates is not comparable.
**Why it happens:** Binance/Bybit/Aster settle every 8h, Hyperliquid/dYdX/Aevo settle hourly. A "0.01%" rate at 1h vs 8h means different annualized costs.
**How to avoid:** Use the daily rollup (`tf='1d'`) from `compute_daily_rollup()` which already sums sub-day rates to daily totals. Average the DAILY rollup rates across venues, not the raw settlement rates.
**Warning signs:** Annualized funding rates that seem 8x too high/low for certain venues.

### Pitfall 2: Timezone Alignment Between Crypto and FRED Data
**What goes wrong:** Crypto data has UTC timestamps with sub-daily granularity. FRED data has date-only (no time) values. Joining on date can produce off-by-one errors.
**Why it happens:** `cmc_price_histories7.timeclose` is UTC timestamptz. `fred.fred_macro_features.date` is a plain DATE. Converting timestamptz to date in different timezones gives different results.
**How to avoid:** Always use UTC date extraction: `ts::date` in SQL or `pd.Timestamp.normalize()` in Python. Compute daily returns as close-to-close for crypto, align to FRED dates.
**Warning signs:** Missing correlation values on certain days, especially around month/year boundaries.

### Pitfall 3: Insufficient Data for Rolling Windows
**What goes wrong:** 60-day rolling correlation between BTC returns and VIX requires 60 overlapping observation dates. If FRED data has holidays/gaps, the effective window may be shorter.
**Why it happens:** FRED series like VIX (VIXCLS) don't publish on weekends/holidays. After forward-fill in `fred_macro_features`, weekend dates have the Friday value, but crypto returns on weekends are real. The correlation should only use dates where BOTH have genuine new data.
**How to avoid:** Two options: (a) use the forward-filled values and accept weekend auto-correlation (simpler, recommended), or (b) filter to business days only. Option (a) is consistent with how `fred_macro_features` already stores data.
**Warning signs:** Rolling windows that systematically produce NaN on Mondays.

### Pitfall 4: Sign-Flip False Positives Near Zero Correlation
**What goes wrong:** Correlation near zero (e.g., oscillating between +0.05 and -0.05) triggers false sign-flip alerts.
**Why it happens:** The magnitude threshold (0.3) is supposed to prevent this, but CONTEXT.md specifies it as "correlation going from >0.3 to <-0.3". If the threshold check is one-sided or uses absolute value incorrectly, false positives occur.
**How to avoid:** Both conditions must be met: previous corr > +threshold AND current corr < -threshold (or vice versa). The CONTEXT.md definition is correct -- implement it exactly.
**Warning signs:** Multiple sign-flip alerts in quick succession for the same asset/macro pair.

### Pitfall 5: cmc_cross_asset_corr vs New Cross-Asset Aggregate Table Confusion
**What goes wrong:** Developers might try to query `cmc_cross_asset_corr` for Phase 70 aggregates, or vice versa.
**Why it happens:** Both deal with "cross-asset correlation" but at different granularities. `cmc_cross_asset_corr` = per-pair, per-timeframe, per-window. New table = aggregate metrics per-date.
**How to avoid:** Clear table naming (`cmc_cross_asset_agg` vs `cmc_cross_asset_corr`) and documentation. The new table may READ from `cmc_cross_asset_corr` or recompute from returns directly.
**Warning signs:** Query returns millions of rows when you expected one row per date.

### Pitfall 6: Asset Scope Mismatch
**What goes wrong:** CONTEXT.md says "ALL assets from both cmc_price_histories7 AND tvc_price_histories" for the high-correlation flag. But `cmc_cross_asset_corr` only covers `cmc_price_histories7` assets.
**Why it happens:** Phase 41's correlation engine was built before TVC data was loaded. TVC assets (e.g., SPY, QQQ, Gold) are needed for crypto-to-macro correlation.
**How to avoid:** The new Phase 70 compute module must load returns from BOTH `cmc_price_histories7` (via `cmc_returns_bars_multi_tf`) AND `tvc_price_histories`. For TVC assets, compute daily returns inline since they may not be in the returns table.
**Warning signs:** Correlation matrix only shows crypto assets, missing traditional assets.

### Pitfall 7: Numpy Scalar / NaN Database Binding Errors
**What goes wrong:** psycopg2 cannot bind numpy float64 or numpy int64 directly. NaN values cause "can't adapt type" errors.
**Why it happens:** pandas operations return numpy scalars. The project has documented this in MEMORY.md as a critical gotcha.
**How to avoid:** Always use `_to_python()` helper (hasattr check) before DB binding. Use `_sanitize_dataframe()` from `regime_classifier.py` for bulk DataFrames.
**Warning signs:** `ProgrammingError: can't adapt type 'numpy.float64'` on upsert.

## Code Examples

### Computing Average Pairwise Correlation (XAGG-02)
```python
# Source: Pattern from refresh_cmc_cross_asset_corr.py, adapted for aggregate
def compute_avg_pairwise_corr(
    returns_wide: pd.DataFrame,  # DatetimeIndex x asset columns
    window: int = 30,
) -> pd.Series:
    """Compute average pairwise rolling correlation across all asset pairs.

    Returns: Series indexed by date with avg pairwise corr values.
    """
    # Use pandas rolling correlation matrix
    n_assets = returns_wide.shape[1]
    if n_assets < 2:
        return pd.Series(dtype=float)

    # Rolling pairwise correlation: for each date, compute corr matrix
    # then average off-diagonal entries
    avg_corrs = []
    dates = returns_wide.index

    for i in range(window - 1, len(dates)):
        window_data = returns_wide.iloc[i - window + 1 : i + 1]
        corr_matrix = window_data.corr()
        # Extract upper triangle (off-diagonal)
        mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
        off_diag = corr_matrix.values[mask]
        avg_corrs.append(np.nanmean(off_diag))

    return pd.Series(
        [np.nan] * (window - 1) + avg_corrs,
        index=dates,
        name="avg_pairwise_corr",
    )
```

### Aggregate Funding Rate with Z-Score (XAGG-03)
```python
# Source: Based on refresh_funding_rates.py data model, compute_daily_rollup pattern
def compute_funding_rate_agg(
    engine,
    symbol: str,
    venues: list[str],
) -> pd.DataFrame:
    """Compute daily aggregate funding rate across venues with z-scores."""
    # Load daily rollup rates per venue
    sql = text("""
        SELECT venue, ts::date as date, funding_rate
        FROM cmc_funding_rates
        WHERE symbol = :sym AND tf = '1d'
          AND venue = ANY(:venues)
        ORDER BY ts
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"sym": symbol, "venues": venues})

    if df.empty:
        return pd.DataFrame()

    # Simple average: NaN venues silently excluded
    daily_avg = df.groupby("date")["funding_rate"].agg(
        avg_funding_rate="mean",
        n_venues="count",
    ).reset_index()

    # Z-scores
    daily_avg["zscore_30d"] = (
        (daily_avg["avg_funding_rate"] - daily_avg["avg_funding_rate"].rolling(30).mean())
        / daily_avg["avg_funding_rate"].rolling(30).std()
    )
    daily_avg["zscore_90d"] = (
        (daily_avg["avg_funding_rate"] - daily_avg["avg_funding_rate"].rolling(90).mean())
        / daily_avg["avg_funding_rate"].rolling(90).std()
    )

    return daily_avg
```

### Crypto-Macro Correlation Sign Flip (XAGG-04)
```python
# Source: CONTEXT.md sign-flip definition + telegram.send_alert pattern
from ta_lab2.notifications.telegram import send_alert

def detect_and_alert_sign_flips(
    corr_df: pd.DataFrame,  # Columns: date, asset_id, macro_var, corr_60d
    threshold: float = 0.3,
) -> pd.DataFrame:
    """Detect sign flips and send Telegram alerts."""
    flips = []
    for (asset_id, macro_var), group in corr_df.groupby(["asset_id", "macro_var"]):
        group = group.sort_values("date")
        group["prev_corr"] = group["corr_60d"].shift(1)

        for _, row in group.iterrows():
            if pd.isna(row["corr_60d"]) or pd.isna(row["prev_corr"]):
                continue

            pos_to_neg = row["prev_corr"] > threshold and row["corr_60d"] < -threshold
            neg_to_pos = row["prev_corr"] < -threshold and row["corr_60d"] > threshold

            if pos_to_neg or neg_to_pos:
                flips.append({
                    "date": row["date"],
                    "asset_id": asset_id,
                    "macro_var": macro_var,
                    "prev_corr": row["prev_corr"],
                    "current_corr": row["corr_60d"],
                    "flip_direction": "pos_to_neg" if pos_to_neg else "neg_to_pos",
                })

                # Telegram alert
                direction = "DECORRELATED" if pos_to_neg else "RE-CORRELATED"
                send_alert(
                    title=f"Crypto-Macro Sign Flip: {asset_id} vs {macro_var}",
                    message=(
                        f"Asset {asset_id} vs {macro_var}: {direction}\n"
                        f"Correlation: {row['prev_corr']:.3f} -> {row['corr_60d']:.3f}\n"
                        f"Date: {row['date']}"
                    ),
                    severity="warning",
                )

    return pd.DataFrame(flips)
```

### Portfolio Optimizer Integration (XAGG-02 -> Phase 58)
```python
# Source: portfolio/optimizer.py, modify run_all() to accept high_corr_flag
# Minimal change: add optional parameter to PortfolioOptimizer.run_all()

# In portfolio/optimizer.py, add to run_all():
def run_all(
    self,
    prices: pd.DataFrame,
    regime_label: Optional[str] = None,
    tf: str = "1D",
    high_corr_override: bool = False,  # NEW: Phase 70 integration
) -> dict:
    # ... existing code up to covariance computation ...
    S: pd.DataFrame = risk_models.CovarianceShrinkage(prices_window).ledoit_wolf()

    # Phase 70: Inflate covariance when market is in high-correlation regime
    if high_corr_override:
        S = self._apply_high_corr_adjustment(S)

    # ... rest of existing code ...

def _apply_high_corr_adjustment(
    self,
    S: pd.DataFrame,
    blend_factor: float = 0.3,
) -> pd.DataFrame:
    """Blend covariance matrix toward full-correlation assumption."""
    vols = np.sqrt(np.diag(S.values))
    full_corr = np.outer(vols, vols)
    adjusted = (1 - blend_factor) * S.values + blend_factor * full_corr
    return pd.DataFrame(adjusted, index=S.index, columns=S.columns)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-pair correlation only (Phase 41) | Aggregate correlation + high-corr flag (Phase 70) | Phase 70 | Enables systemic risk detection |
| Per-venue funding rates (Phase 51) | Cross-venue aggregate with z-score signal (Phase 70) | Phase 70 | Enables sentiment proxy |
| Macro regime w/o crypto correlation (Phase 67) | Crypto-macro correlation as 5th regime dimension (Phase 70) | Phase 70 | Closes the loop between macro and crypto |
| Static covariance in optimizer (Phase 58) | Dynamic covariance override from high-corr flag (Phase 70) | Phase 70 | More realistic diversification estimates |

**Deprecated/outdated:**
- None. All existing infrastructure remains valid and is extended, not replaced.

## Schema Details

### Table: cmc_cross_asset_agg
```sql
CREATE TABLE cmc_cross_asset_agg (
    date          DATE NOT NULL,
    btc_eth_corr_30d  FLOAT,          -- XAGG-01
    avg_pairwise_corr_30d FLOAT,      -- XAGG-02
    high_corr_flag    BOOLEAN,         -- XAGG-02 (>0.7 threshold)
    n_assets          INTEGER,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date)
);
```
Rationale: One row per date because BTC/ETH correlation and avg pairwise correlation are market-wide metrics, not per-asset.

### Table: cmc_funding_rate_agg
```sql
CREATE TABLE cmc_funding_rate_agg (
    date              DATE NOT NULL,
    symbol            TEXT NOT NULL,       -- 'BTC' or 'ETH'
    avg_funding_rate  FLOAT,              -- Simple average across venues
    vwap_funding_rate FLOAT,              -- Volume-weighted, nullable
    n_venues          INTEGER,
    zscore_30d        FLOAT,              -- Primary signal
    zscore_90d        FLOAT,              -- Secondary
    venues_included   TEXT,               -- Comma-separated list of venues
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date, symbol)
);
```
Rationale: Per-symbol because BTC and ETH funding rates differ meaningfully.

### Table: crypto_macro_corr_regimes
```sql
CREATE TABLE crypto_macro_corr_regimes (
    date              DATE NOT NULL,
    asset_id          INTEGER NOT NULL,    -- CMC id from cmc_price_histories7
    macro_var         TEXT NOT NULL,        -- 'vix', 'dxy', 'hy_oas', 'net_liquidity'
    corr_60d          FLOAT,
    prev_corr_60d     FLOAT,               -- For sign-flip detection
    sign_flip_flag    BOOLEAN DEFAULT FALSE,
    corr_regime       TEXT,                 -- 'positive', 'negative', 'decorrelated'
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date, asset_id, macro_var)
);
```
Rationale: No `cmc_` prefix because this mixes crypto assets with macro variables. Per-asset per-macro-var because CONTEXT.md says compute for ALL tradeable assets.

### Modification: cmc_macro_regimes
Add new columns for crypto-macro correlation regime (CONTEXT.md: "stored as new columns in cmc_macro_regimes alongside monetary/liquidity/risk/carry"):
```sql
ALTER TABLE cmc_macro_regimes ADD COLUMN crypto_macro_corr TEXT;
-- Labels: 'correlated', 'decorrelated', 'flipping'
```

## Data Flow

```
fred.fred_macro_features (VIX, DXY, HY OAS, net_liquidity)
        |
        v
[crypto_macro_corr_regimes]  <-- cmc_price_histories7 returns
        |
        v
cmc_macro_regimes (new crypto_macro_corr column)
        |
        v
Telegram alerts (on sign flip)

cmc_funding_rates (6 venues, daily rollup)
        |
        v
[cmc_funding_rate_agg] (avg, vwap, z-scores)

cmc_returns_bars_multi_tf + tvc_price_histories
        |
        v
[cmc_cross_asset_agg] (BTC/ETH corr, avg pairwise, high_corr_flag)
        |
        v
PortfolioOptimizer (covariance override when high_corr_flag=True)
```

## Open Questions

Things that could not be fully resolved:

1. **TVC asset returns table**
   - What we know: `tvc_price_histories` exists with daily OHLC data. The bar builder (`refresh_tvc_price_bars_1d.py`) writes bars. But returns may not be in `cmc_returns_bars_multi_tf` (that table is CMC-sourced).
   - What's unclear: Whether TVC asset returns need to be computed on-the-fly or are already in a returns table.
   - Recommendation: Compute daily returns from `tvc_price_histories` directly in the Phase 70 module. Simple: `(close[t] - close[t-1]) / close[t-1]`.

2. **Volume-weighted average funding rate data availability**
   - What we know: CONTEXT.md says store BOTH simple average (primary) and volume-weighted (secondary, when volume data exists). The `FundingRateRow` dataclass has `mark_price` but not `volume`.
   - What's unclear: Whether venue funding rate APIs return volume data alongside rates.
   - Recommendation: Start with simple average only (always available). Add `vwap_funding_rate` column as nullable. Populate when volume data becomes available in a future phase.

3. **Blend factor for covariance override**
   - What we know: The high-corr flag should "reduce diversification benefit assumption in portfolio optimizer (increase correlation estimate in covariance matrix)".
   - What's unclear: What the optimal blend factor should be (0.1? 0.3? 0.5?).
   - Recommendation: Make it YAML-configurable (default 0.3), run backtests to calibrate. The blend factor is a policy choice, not a research question.

4. **Refresh frequency for cross-asset aggregation**
   - What we know: FRED data updates daily (some weekly). Funding rates update at settlement times (1h/8h). Price bars are daily.
   - What's unclear: Whether to refresh all three tables in one script run or separate scripts.
   - Recommendation: Single CLI script (`refresh_cross_asset_agg.py`) that runs all four XAGG computations in sequence, with flags to run individually. Daily refresh cadence (after FRED and funding rate ingestion).

5. **How the sign-flip feeds into cmc_macro_regimes**
   - What we know: CONTEXT.md says "feed into macro regime as a dimension in cmc_macro_regimes". The table currently has 4 dimensions: monetary_policy, liquidity, risk_appetite, carry.
   - What's unclear: Whether to add a 5th dimension column directly or aggregate sign-flip state across all assets/macro pairs into a single label.
   - Recommendation: Add a `crypto_macro_corr` TEXT column to cmc_macro_regimes. The label is derived from the most adverse sign-flip state across all tracked assets (e.g., if ANY asset has a sign flip, label = 'flipping'; else use majority correlation direction).

## Sources

### Primary (HIGH confidence)
- `alembic/versions/8d5bc7ee1732_asset_stats_and_correlation_tables.py` -- Phase 41 correlation table schema
- `alembic/versions/30eac3660488_perps_readiness.py` -- Phase 51 funding rates table schema
- `alembic/versions/d5e6f7a8b9c0_macro_regime_tables.py` -- Phase 67 macro regime table schema
- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` + `c4d5e6f7a8b9_fred_phase66_derived_columns.py` -- FRED features schema (52 columns)
- `src/ta_lab2/scripts/desc_stats/refresh_cmc_cross_asset_corr.py` -- Existing correlation computation pattern
- `src/ta_lab2/scripts/perps/refresh_funding_rates.py` -- Existing funding rate ingestion pattern
- `src/ta_lab2/macro/regime_classifier.py` -- Macro regime classification pattern
- `src/ta_lab2/portfolio/optimizer.py` -- Portfolio optimizer integration point
- `src/ta_lab2/notifications/telegram.py` -- Telegram alert API
- `configs/macro_regime_config.yaml` -- YAML threshold config pattern
- `configs/portfolio.yaml` -- Portfolio config structure

### Secondary (MEDIUM confidence)
- Phase 70 CONTEXT.md decisions -- All schema and behavior constraints

### Tertiary (LOW confidence)
- Volume-weighted funding rate feasibility (depends on venue API capabilities not yet investigated)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All libraries already in use, no new dependencies
- Architecture: HIGH -- All patterns directly reuse existing Phase 41/51/58/65-67 infrastructure
- Schema design: MEDIUM -- Claude's discretion per CONTEXT.md; recommended design follows project conventions but may need adjustment based on query patterns
- Pitfalls: HIGH -- Based on direct codebase inspection and documented gotchas in MEMORY.md
- Portfolio optimizer integration: MEDIUM -- The covariance blend approach is sound but the blend factor is a tuning parameter

**Research date:** 2026-03-03
**Valid until:** 2026-04-03 (stable -- no fast-moving external dependencies)
