# Phase 7: ta_lab2 Feature Pipeline - Research

**Researched:** 2026-01-30
**Domain:** Quantitative trading feature engineering (returns, volatility, technical indicators)
**Confidence:** HIGH

## Summary

Phase 7 builds a production-grade feature pipeline for quantitative trading that calculates returns, volatility measures, and technical indicators from the unified time model established in Phase 6. The research reveals that modern quant feature pipelines require careful consideration of computation engine choice (SQL vs Python), null handling strategies, and incremental refresh patterns with state management.

**Key findings:**
- The codebase already has mature feature calculation modules (`returns.py`, `vol.py`, `indicators.py`) with pandas-based implementations that handle multiple parameter sets and backward compatibility
- The existing EMA infrastructure provides a proven template: `BaseEMAFeature` class, `EMAStateManager` for watermarking, and `BaseEMARefresher` for parallel execution orchestration
- Financial time series require domain-specific null handling - interpolation/forward-fill tradeoffs depend on feature type and market characteristics
- Modern tools (Polars, DuckDB) offer 5-50x performance improvements over pandas for large datasets, but pandas remains optimal for <10GB datasets due to ecosystem maturity

**Primary recommendation:** Extend the proven EMA architecture pattern (base class + state manager + refresher) to feature calculations, using SQL for simple aggregations and Python (pandas initially, with Polars path for future scale) for complex rolling window computations. Implement feature-specific null handling strategies configured via metadata tables.

## Standard Stack

The established libraries/tools for quantitative feature engineering:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.x | Feature computation engine | Mature ecosystem, proven in codebase (returns.py, vol.py, indicators.py) |
| NumPy | 1.26+ | Numerical operations | Foundation for pandas, optimized vectorization |
| SQLAlchemy | 2.x | Database abstraction | Already used throughout codebase for state management |
| PostgreSQL | 14+ | Feature storage | TIMESTAMPTZ support, proven for time series in Phase 6 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Polars | 0.20+ | High-performance DataFrames | Future optimization for datasets >10GB (5-50x faster) |
| DuckDB | 0.10+ | In-process SQL analytics | Complex SQL logic, aggregation-heavy workflows |
| scipy | 1.11+ | Statistical functions | Advanced volatility estimators (Yang-Zhang if needed) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pandas | Polars | 5-50x faster but less mature ecosystem, breaking API changes more frequent |
| Python rolling | SQL window functions | SQL faster for simple aggregations but less flexible for complex multi-step logic |
| Manual loops | NumPy vectorization | Always prefer vectorization - 10-100x faster |

**Installation:**
```bash
# Core already installed in ta_lab2
# Optional for future optimization:
pip install polars duckdb
```

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── features/
│   ├── returns.py           # Already exists - bar-to-bar returns
│   ├── vol.py               # Already exists - volatility estimators
│   ├── indicators.py        # Already exists - RSI, MACD, etc.
│   ├── feature_store/       # NEW - unified feature computation
│   │   ├── base_feature.py  # Abstract base (like BaseEMAFeature)
│   │   ├── returns_feature.py
│   │   ├── volatility_feature.py
│   │   ├── technical_feature.py
│   │   └── unified_features.py  # cmc_daily_features orchestrator
│   └── ensure.py            # Table creation utilities
├── scripts/
│   └── features/            # NEW - feature refresh scripts
│       ├── state_management.py  # FeatureStateManager
│       ├── base_feature_refresher.py  # Like BaseEMARefresher
│       ├── refresh_returns.py
│       ├── refresh_volatility.py
│       ├── refresh_technical.py
│       └── refresh_unified_features.py
└── time/
    └── dim_timeframe.py     # Already exists - lookback window source
```

### Pattern 1: Base Feature Class (Extend EMA Pattern)
**What:** Abstract base class for all feature computations, analogous to `BaseEMAFeature`
**When to use:** All feature types (returns, vol, TA) to ensure consistency
**Example:**
```python
# Adapted from src/ta_lab2/features/m_tf/base_ema_feature.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class FeatureConfig:
    """Configuration for feature computation."""
    output_schema: str
    output_table: str
    feature_type: str  # 'returns', 'volatility', 'technical'
    lookback_windows: list[int]  # From dim_timeframe_period

class BaseFeature(ABC):
    """Abstract base for feature computation modules."""

    def __init__(self, engine, config: FeatureConfig):
        self.engine = engine
        self.config = config

    @abstractmethod
    def load_source_data(self, ids, start, end) -> pd.DataFrame:
        """Load bar data for computation."""

    @abstractmethod
    def compute_features_for_id(self, df_source, id_, periods) -> pd.DataFrame:
        """Core computation logic - subclass implements."""

    def compute_for_ids(self, ids, start=None, end=None) -> int:
        """Template method - loads data, computes, writes."""
        df_source = self.load_source_data(ids, start, end)
        all_results = []
        for id_ in ids:
            df_id = df_source[df_source['id'] == id_]
            df_features = self.compute_features_for_id(df_id, id_, self.config.lookback_windows)
            all_results.append(df_features)
        df_final = pd.concat(all_results, ignore_index=True)
        return self.write_to_db(df_final)
```

### Pattern 2: State Management with Watermarking
**What:** Track computation state per (id, tf, period, feature_type) for incremental refresh
**When to use:** All feature tables to avoid full recomputation
**Example:**
```python
# Extend existing EMAStateManager pattern from src/ta_lab2/scripts/emas/state_management.py
@dataclass
class FeatureStateConfig:
    state_schema: str = "public"
    state_table: str = "cmc_features_state"  # Unified state table

class FeatureStateManager:
    """Manages feature computation state with watermarking."""

    def ensure_state_table(self):
        """Create state table if doesn't exist."""
        sql = """
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            id              INTEGER     NOT NULL,
            tf              TEXT        NOT NULL,
            feature_type    TEXT        NOT NULL,  -- 'returns', 'vol', 'ta'
            period          INTEGER     NULL,       -- NULL for non-period features
            last_date       TIMESTAMPTZ NOT NULL,
            rows_computed   INTEGER     NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf, feature_type, COALESCE(period, -1))
        );
        """

    def compute_dirty_window_start(self, ids, feature_type) -> pd.Timestamp:
        """Find minimum last_date for incremental refresh."""
        # Load state, find min(last_date) for selected ids/feature_type
        # Return dirty window start (subtract lookback buffer)
```

### Pattern 3: Lookback Windows from dim_timeframe
**What:** Query `dim_timeframe_period` for standardized lookback windows
**When to use:** All feature calculations requiring temporal aggregation
**Example:**
```python
# Query dim_timeframe_period for lookback windows
def get_lookback_windows(engine, tf='1D'):
    """Load lookback windows from dim_timeframe_period."""
    sql = """
    SELECT tf, period, span_days
    FROM dim_timeframe_period
    WHERE tf = %s
    ORDER BY period
    """
    df = pd.read_sql(sql, engine, params=[tf])
    return df['period'].tolist()  # e.g., [7, 14, 21, 30, 60, 90]

# Use in feature computation
def compute_returns_with_lookbacks(df, close_col='close'):
    """Compute returns for multiple lookback periods."""
    periods = get_lookback_windows(engine, tf='1D')
    for period in periods:
        df[f'return_{period}d'] = df[close_col].pct_change(period)
    return df
```

### Pattern 4: Hybrid SQL/Python Computation
**What:** Use SQL for simple aggregations, Python for complex rolling logic
**When to use:** Balance performance and maintainability
**Example:**
```python
# Simple aggregations in SQL (faster)
def compute_daily_summary_sql(engine, ids, start_date):
    """Compute simple daily aggregations in SQL."""
    sql = """
    SELECT
        id, time_close::date as date,
        AVG(close) as avg_close,
        STDDEV(close) as stddev_close,
        MAX(high) - MIN(low) as daily_range
    FROM cmc_price_bars_1d
    WHERE id = ANY(%s) AND time_close >= %s
    GROUP BY id, time_close::date
    """
    return pd.read_sql(sql, engine, params=[ids, start_date])

# Complex rolling windows in Python (more flexible)
def compute_rolling_features_python(df):
    """Compute complex rolling features in pandas."""
    # Parkinson volatility requires OHLC log ratios
    df['vol_parkinson_20'] = np.sqrt(
        (1 / (4 * np.log(2))) *
        (np.log(df['high'] / df['low']) ** 2).rolling(20).mean()
    )
    return df
```

### Pattern 5: Feature Store Table with Metadata
**What:** Store both raw and normalized features with quality metadata
**When to use:** `cmc_daily_features` view/table for unified feature access
**Example:**
```sql
-- Feature store table schema
CREATE TABLE cmc_daily_features (
    -- Identity
    id              INTEGER         NOT NULL,
    date            DATE            NOT NULL,
    tf              TEXT            NOT NULL DEFAULT '1D',

    -- Price features (from bars)
    close           DOUBLE PRECISION,
    volume          DOUBLE PRECISION,

    -- Returns (raw)
    return_1d       DOUBLE PRECISION,
    return_7d       DOUBLE PRECISION,
    return_30d      DOUBLE PRECISION,

    -- Returns (normalized z-score)
    return_1d_z     DOUBLE PRECISION,
    return_7d_z     DOUBLE PRECISION,

    -- Volatility
    vol_parkinson_20 DOUBLE PRECISION,
    vol_gk_20       DOUBLE PRECISION,

    -- Technical indicators
    rsi_14          DOUBLE PRECISION,
    macd_12_26      DOUBLE PRECISION,
    macd_signal_9   DOUBLE PRECISION,

    -- Quality metadata
    data_quality    JSONB,  -- {"missing_bars": 0, "outliers": [], "interpolated": false}
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (id, date, tf)
);
```

### Anti-Patterns to Avoid
- **Computing features in loops:** Always vectorize with pandas/NumPy - 10-100x faster
- **Full table recomputation:** Use incremental refresh with watermarking from day 1
- **Ignoring trading calendar:** Returns over weekends/holidays distort daily metrics - use dim_sessions
- **Single null handling strategy:** Forward-fill for prices, skip for returns, interpolate for vol - feature-dependent
- **Hardcoded lookback periods:** Use dim_timeframe_period for centralized configuration

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Volatility estimation | Custom OHLC variance | `vol.py` Parkinson/GK estimators | Edge cases: opening jumps, zero prices, annualization factors |
| RSI calculation | Manual gain/loss EMA | `indicators.py` rsi() | Wilder smoothing nuances, division by zero, first N values |
| MACD computation | Simple EMA difference | `indicators.py` macd() | Signal line, histogram, consistent EMA span interpretation |
| Bar-to-bar returns | df['close'].pct_change() | `returns.py` b2t_pct_delta() | Direction handling (newest_top), rounding, log vs pct |
| Missing data imputation | if pd.isna() forward fill | Research-driven strategy per feature type | Different strategies for returns/vol/prices |
| Corporate action adjustment | Manual split multiplication | QuantConnect/external service | Splits, dividends, mergers - complex edge cases |
| State table management | Custom watermark tracking | Extend `EMAStateManager` | Proven pattern, handles dirty windows, per-(id,tf,period) |
| Parallel execution | Raw multiprocessing | Extend `BaseEMARefresher` | NullPool connections, error handling, progress tracking |

**Key insight:** The codebase already has mature, tested implementations for core feature calculations. Extending existing patterns is faster and more reliable than reimplementing from scratch.

## Common Pitfalls

### Pitfall 1: Lookback Window Mismatch (Trading vs Calendar Days)
**What goes wrong:** Computing 7-day returns using calendar days includes weekends/holidays, inflating volatility estimates
**Why it happens:** Confusion between `tf_days` (calendar) and trading days available in dim_sessions
**How to avoid:**
- For crypto: Use calendar days (24/7 trading)
- For equities: Query dim_sessions to count actual trading days
- Store both in dim_timeframe_period: `span_days` (calendar) and `span_trading_days` (market-specific)
**Warning signs:** Returns show unexpected spikes on Mondays (3-day weekend effect), volatility estimates 40% higher than vendor data

### Pitfall 2: Forward-Fill Bias in Returns Calculation
**What goes wrong:** Forward-filling missing prices before computing returns creates artificial zero-return periods, biasing mean returns upward and volatility downward
**Why it happens:** Applying generic imputation strategy (forward-fill for prices) before feature calculation
**How to avoid:** Compute features on raw data with NULLs, then apply feature-specific null handling:
- Returns: Skip NULLs (don't forward-fill prices first)
- Volatility: Forward-fill OHLC (GK/Parkinson need complete bars)
- Indicators: Interpolate (RSI/MACD need continuous series)
**Warning signs:** Sharpe ratios too high (0.8+ for daily strategies), distributions show spike at exactly 0 return

### Pitfall 3: Insufficient Lookback Buffer for Incremental Refresh
**What goes wrong:** Incremental refresh recomputes from `last_date`, but rolling windows need prior data - results differ from full refresh
**Why it happens:** Not accounting for longest lookback period when determining dirty window start
**How to avoid:**
```python
def compute_dirty_window_start(last_date, max_period):
    """Subtract max lookback period + buffer."""
    buffer_days = max_period + 5  # +5 for weekends/holidays
    return last_date - pd.Timedelta(days=buffer_days)
```
**Warning signs:** EMA/SMA values jump on first row after incremental refresh, integration tests fail but unit tests pass

### Pitfall 4: Ignoring Opening Jumps in Volatility Estimation
**What goes wrong:** Garman-Klass volatility assumes continuous diffusion (GBM), but crypto/equities have overnight gaps - volatility underestimated by 20-30%
**Why it happens:** Using GK estimator without considering its assumptions
**How to avoid:**
- For 24/7 crypto: GK/Parkinson work well (continuous trading)
- For equities with gaps: Use Yang-Zhang estimator (handles opening jumps) or close-to-close volatility
- Document assumption in `cmc_vol_daily.vol_method` column
**Warning signs:** Volatility estimates consistently 20-30% below market implied vol, poor VaR model performance

### Pitfall 5: RSI Divergence in Trending Markets
**What goes wrong:** RSI stays overbought (>70) for extended periods in strong trends, generating false reversal signals
**Why it happens:** RSI is mean-reversion indicator, not trend-following - using it standalone
**How to avoid:**
- Combine with trend filter (MACD, EMA crossover)
- Store multiple parameter sets (RSI_14, RSI_21) to detect parameter sensitivity
- Add `trend_regime` column to features (from ADX or EMA slope)
**Warning signs:** RSI signals have <50% win rate in backtests, losses cluster in trending periods

### Pitfall 6: Stale Feature Data After Upstream Bar Updates
**What goes wrong:** Bar corrections/late-arriving data update `cmc_price_bars_1d`, but features not recalculated - stale derived data
**Why it happens:** No dependency tracking between bars and features
**How to avoid:**
- Implement cascade refresh: bar updates trigger feature recalculation
- Track `source_bar_updated_at` in feature state
- Validation query: Compare feature last_date with bars max(updated_at)
```sql
-- Detect stale features
SELECT f.id, f.last_date, MAX(b.updated_at) as bar_updated
FROM cmc_features_state f
JOIN cmc_price_bars_1d b ON f.id = b.id
WHERE b.updated_at > f.updated_at
GROUP BY f.id, f.last_date
HAVING MAX(b.updated_at) > f.updated_at;
```
**Warning signs:** Features don't match manual recalculation, audits show discrepancies after bar refresh

### Pitfall 7: Null Handling Strategy Not Documented
**What goes wrong:** Team members use different imputation methods, features become non-reproducible
**Why it happens:** Null handling decisions made ad-hoc during implementation
**How to avoid:**
- Create `dim_features` metadata table documenting strategy per feature
- Store strategy in code comments AND database
- Validation tests check actual vs documented strategy
```sql
CREATE TABLE dim_features (
    feature_name TEXT PRIMARY KEY,
    feature_type TEXT,  -- 'returns', 'volatility', 'technical'
    null_strategy TEXT,  -- 'skip', 'forward_fill', 'interpolate', 'zero'
    min_non_null_pct FLOAT,  -- Minimum data quality threshold
    description TEXT
);
```
**Warning signs:** Code reviews reveal conflicting approaches, "works on my machine" issues

## Code Examples

Verified patterns from existing codebase:

### Returns Calculation (Bar-to-Bar)
```python
# Source: src/ta_lab2/features/returns.py
from ta_lab2.features.returns import b2t_pct_delta, b2t_log_delta

# Compute percentage returns
df = b2t_pct_delta(
    df,
    cols=['close'],  # Primary column
    extra_cols=['open', 'high', 'low'],  # Additional columns
    direction='oldest_top',  # Chronological order
    round_places=6
)
# Creates: close_b2t_pct, open_b2t_pct, high_b2t_pct, low_b2t_pct

# Compute log returns
df = b2t_log_delta(
    df,
    cols=['close'],
    direction='oldest_top',
    round_places=6
)
# Creates: close_b2t_log
```

### Volatility Estimation (Multiple Estimators)
```python
# Source: src/ta_lab2/features/vol.py
from ta_lab2.features.vol import (
    add_parkinson_vol,
    add_garman_klass_vol,
    add_rogers_satchell_vol,
    add_rolling_realized_batch
)

# Parkinson (High-Low range)
df = add_parkinson_vol(
    df,
    high_col='high',
    low_col='low',
    windows=(20, 63, 126),  # Multiple lookbacks
    annualize=True,
    periods_per_year=252  # Equities: 252, Crypto: 365
)
# Creates: vol_parkinson_20, vol_parkinson_63, vol_parkinson_126

# Garman-Klass (OHLC)
df = add_garman_klass_vol(
    df,
    open_col='open',
    high_col='high',
    low_col='low',
    close_col='close',
    windows=(20, 63, 126),
    annualize=True,
    periods_per_year=252
)
# Creates: vol_gk_20, vol_gk_63, vol_gk_126

# Batch compute multiple estimators
df = add_rolling_realized_batch(
    df,
    windows=(20, 63, 126),
    which=('parkinson', 'rs', 'gk'),  # All three
    annualize=True,
    periods_per_year=365  # Crypto
)
```

### Technical Indicators (RSI, MACD)
```python
# Source: src/ta_lab2/features/indicators.py
from ta_lab2.features.indicators import rsi, macd

# RSI (single or multiple periods)
df['rsi_14'] = rsi(df, period=14, price_col='close', inplace=False)
df['rsi_21'] = rsi(df, period=21, price_col='close', inplace=False)

# MACD (returns DataFrame with 3 series)
macd_df = macd(
    df,
    price_col='close',
    fast=12,
    slow=26,
    signal=9,
    inplace=False
)
# macd_df contains: macd_12_26, macd_signal_9, macd_hist_12_26_9

# Combine MACD with original DataFrame
df = df.join(macd_df)
```

### Lookback Windows from dim_timeframe
```python
# Query dim_timeframe_period for standardized periods
from sqlalchemy import create_engine, text

engine = create_engine(db_url)

def get_lookback_periods(engine, tf='1D', max_span_days=365):
    """Load lookback periods from dim_timeframe_period."""
    query = text("""
        SELECT period, span_days
        FROM dim_timeframe_period
        WHERE tf = :tf AND span_days <= :max_span
        ORDER BY period
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {'tf': tf, 'max_span': max_span_days})
        return [(row.period, row.span_days) for row in result]

# Use in feature computation
periods = get_lookback_periods(engine, tf='1D', max_span_days=365)
# Returns: [(7, 7), (14, 14), (21, 21), (30, 30), (60, 60), (90, 90), ...]

for period, span_days in periods:
    df[f'return_{period}d'] = df['close'].pct_change(period)
    df[f'vol_{period}d'] = df['close'].pct_change().rolling(period).std()
```

### State Management for Incremental Refresh
```python
# Source: Adapted from src/ta_lab2/scripts/emas/state_management.py
from ta_lab2.scripts.emas.ema_state_manager import EMAStateManager, EMAStateConfig

# Configure state manager
config = EMAStateConfig(
    state_schema='public',
    state_table='cmc_features_state',
    ts_column='date',
    use_canonical_ts=True
)

manager = EMAStateManager(engine, config)

# Create state table
manager.ensure_state_table()

# Load existing state
state_df = manager.load_state()
# Columns: id, tf, period, daily_min_seen, daily_max_seen, last_time_close, updated_at

# Compute dirty window start for incremental refresh
dirty_starts = manager.compute_dirty_window_starts(
    ids=[1, 2, 3],
    max_period=90,  # Longest lookback period
    buffer_days=5
)
# Returns dict: {1: '2025-10-01', 2: '2025-10-15', 3: '2025-09-20'}

# Update state after computation
manager.update_state_from_output(
    output_table='cmc_returns_daily',
    output_schema='public'
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pandas for all datasets | Polars for >10GB datasets | 2024-2025 | 5-50x faster feature engineering at scale |
| Forward-fill all missing data | Feature-specific null strategies | 2023-2024 | Eliminates look-ahead bias, realistic backtests |
| Full table recomputation | Incremental refresh with watermarking | 2020-2022 | 90% reduction in compute time for daily updates |
| Manual parameter tuning | Multiple parameter sets in metadata table | 2022-2023 | Parameter sensitivity analysis, robustness |
| Single volatility estimator | Multiple estimators (Parkinson, GK, RS, YZ) | 2021-2022 | Robust estimates across market regimes |
| Python loops for rolling windows | NumPy/pandas vectorization | 2018-2020 | 10-100x faster, core best practice |
| Separate state tables per feature | Unified state table with feature_type | 2025-2026 | Simplified monitoring, consistent patterns |

**Deprecated/outdated:**
- **Close-to-close volatility only:** Inefficient estimator (β far from 1) - use Parkinson/GK which use full OHLC data
- **Single-threaded feature computation:** Modern CPUs have 8-32 cores - parallel by asset/tf for 5-10x speedup
- **Hardcoded lookback periods:** Centralize in dim_timeframe_period for consistency across features
- **df.iterrows() for feature calculation:** Deprecated in pandas 2.0+ - use vectorization or apply()

## Open Questions

Things that couldn't be fully resolved:

1. **Corporate Actions Adjustment Strategy**
   - What we know: QuantConnect adjusts prices backward for splits/dividends to maintain return continuity
   - What's unclear: Whether ta_lab2 data sources (CMC) provide pre-adjusted data or require manual adjustment
   - Recommendation: Validate with sample split event (e.g., recent tech stock split), compare vendor data with adjusted prices. If unadjusted, implement adjustment service or use external provider.

2. **Optimal Dirty Window Buffer**
   - What we know: Need `max_period + buffer` for incremental refresh to match full refresh
   - What's unclear: Exact buffer size for crypto (24/7) vs equities (weekends/holidays)
   - Recommendation: Start with `max_period * 1.2` (20% buffer), run A/B test comparing incremental vs full refresh results, adjust based on discrepancies.

3. **Feature Normalization Strategy**
   - What we know: Z-scores useful for ML, but require rolling window for online calculation (avoid look-ahead)
   - What's unclear: Whether to store raw+normalized (doubles storage) or compute normalized on-the-fly (query time overhead)
   - Recommendation: Store both for critical features (returns, vol), compute on-the-fly for less-used features. Monitor query performance.

4. **Intraday Feature Support Timing**
   - What we know: Schema should support intraday from start (CONTEXT.md decision)
   - What's unclear: Whether to implement 1H/4H computation logic now or defer until needed
   - Recommendation: Design schema and base classes to support intraday (tf='1H'), but only implement daily (tf='1D') calculations in Phase 7. Add intraday when first strategy requires it.

5. **Feature Dependency Graph Complexity**
   - What we know: Returns depend on bars, volatility depends on returns, unified view depends on all
   - What's unclear: Whether to implement full DAG execution engine or simple sequential refresh
   - Recommendation: Start with simple ordered execution (bars → returns → vol → TA → unified), add dependency tracking if circular dependencies or complex schedules emerge.

## Sources

### Primary (HIGH confidence)
- **Codebase Analysis:**
  - `src/ta_lab2/features/returns.py` - Bar-to-bar returns implementation with direction handling
  - `src/ta_lab2/features/vol.py` - Parkinson, GK, RS, ATR volatility estimators
  - `src/ta_lab2/features/indicators.py` - RSI, MACD, Stochastic, Bollinger, ADX, OBV, MFI
  - `src/ta_lab2/features/m_tf/base_ema_feature.py` - Base class pattern for feature modules
  - `src/ta_lab2/scripts/emas/state_management.py` - EMAStateManager watermarking pattern
  - `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_v2.py` - BaseEMARefresher parallel execution
  - `sql/lookups/010_dim_timeframe_create.sql` - Timeframe metadata structure
  - `sql/lookups/016_dim_timeframe_period.sql` - Period lookback mapping

### Secondary (MEDIUM confidence)
- [From Deep Learning to LLMs: A survey of AI in Quantitative Investment](https://arxiv.org/html/2503.21422v1) - MLOps pipelines, feature stores eliminate training-serving skew
- [Quant 2.0 Architecture: Rewiring the Trading Stack for the AI Era](https://altstreet.investments/blog/quant-2-architecture-modern-trading-stack-ai-mlops) - Buy commodity infrastructure, build alpha logic
- [Range-Based Volatility Estimators: Overview and Examples of Usage](https://portfoliooptimizer.io/blog/range-based-volatility-estimators-overview-and-examples-of-usage/) - Parkinson, GK efficiency vs close-to-close
- [Garman-Klass Volatility Calculation](https://derivvaluation.medium.com/garman-klass-volatility-calculation-volatility-analysis-in-python-333ca1d17376) - GK assumes continuous diffusion, not robust for opening jumps
- [How to Use Technical Indicators MACD, RSI, and KDJ for Crypto Trading in 2026](https://web3.gate.com/crypto-wiki/article/how-to-use-technical-indicators-macd-rsi-and-kdj-for-crypto-trading-in-2026-20260125) - Avoid over-reliance on single indicators, lagging nature
- [Preprocessing and Data Exploration for Time Series — Handling Missing Values](https://medium.com/@datasciencewizards/preprocessing-and-data-exploration-for-time-series-handling-missing-values-e5c507f6c71c) - Forward fill vs interpolation tradeoffs
- [Feature Store Design Patterns for Small Data Teams](https://mljourney.com/feature-store-design-patterns-for-small-data-teams/) - dbt-native incremental features with is_incremental() checks
- [Pandas2 and Polars for Feature Engineering](https://www.hopsworks.ai/post/pandas2-and-polars-for-feature-engineering) - Polars 5.61x faster than pandas for feature engineering
- [SQL vs. Python: A Comparative Analysis for Data](https://airbyte.com/data-engineering-resources/sql-vs-python-data-analysis) - Use SQL unless it doesn't suit the task
- [Corporate Actions - Documentation QuantConnect.com](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions) - Backtest with ADJUSTED or TOTAL_RETURN data normalization

### Tertiary (LOW confidence)
- General web search results on feature engineering best practices - patterns confirmed with codebase analysis

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pandas/NumPy/SQLAlchemy already proven in codebase, Polars well-documented for scale
- Architecture: HIGH - BaseEMAFeature pattern directly applicable, proven in Phase 6
- Volatility estimators: HIGH - Existing vol.py implementation verified, academic papers confirm limitations
- Technical indicators: HIGH - Existing indicators.py with RSI/MACD/etc. implementations
- Null handling: MEDIUM - Research shows tradeoffs, but optimal strategy depends on asset class/market regime (needs validation)
- Corporate actions: LOW - Vendor data adjustment status unclear, requires validation with actual data

**Research date:** 2026-01-30
**Valid until:** 2026-03-01 (30 days - stable domain, pandas/NumPy APIs stable)

**Key validation needed before planning:**
- Verify CMC data provides adjusted prices (splits/dividends) or requires manual adjustment
- Test dirty window buffer size (max_period * 1.2) produces identical results to full refresh
- Validate crypto uses calendar days, equities use trading days from dim_sessions for lookback windows
