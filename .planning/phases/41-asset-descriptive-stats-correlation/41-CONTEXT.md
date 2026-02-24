# Phase 41: Asset Descriptive Statistics & Cross-Asset Correlation - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Rolling per-asset descriptive statistics (mean return, std dev, Sharpe, skewness, kurtosis, max drawdown) and cross-asset pairwise return correlation — persisted as full time-series tables with PK including window size. Refreshed daily via incremental append (full recompute on demand). Placed in the pipeline AFTER returns and BEFORE regimes so stats can feed into regime detection. Includes dashboard page, regime pipeline wiring, and a section in the Phase 40 "Explore Indicators" notebook.

Requirements: DESC-01, DESC-02, DESC-03, DESC-04, DESC-05, CORR-01, CORR-02, CORR-03

Does NOT include creating new regime detection algorithms (wiring existing stats as inputs only), equity curve analysis, or portfolio-level statistics.

</domain>

<decisions>
## Implementation Decisions

### Window Sizes & Stat Selection
- **All stats at all windows**: Full 6-stat x 4-window matrix (30, 60, 90, 252 bars). No selective pairing — downstream consumers decide what's useful.
- **NULL until full window**: Assets with fewer bars than window size get NULL stats. No partial windows or min_periods. Cleanest — no noisy short-window estimates.
- **Sharpe ratio**: Configurable Rf (default 0, column supports non-zero). Store BOTH raw (per-bar) Sharpe and annualized Sharpe for cross-TF comparison.
- **Annualization from dim_timeframe**: Factor = sqrt(365 / tf_days_nominal). Correct for all TFs, consistent with project patterns.
- **Max drawdown**: BOTH within-window max drawdown AND current drawdown from ATH stored as separate columns. Two complementary perspectives.
- **Kurtosis**: Store BOTH Pearson (normal=3, consistent with Phase 36 PSR) and Fisher/excess (normal=0). Research best practice during research phase to determine if both add value or one dominates.
- **Volatility**: Compute std(ret_arith) from cmc_returns_bars_multi_tf as the stat column. Note that Parkinson/GK vol is available separately in cmc_vol for comparison — do not duplicate cmc_vol data.

### Correlation Pair Scope
- **All pairs**: Complete N*(N-1)/2 pairwise correlation matrix. No filtering by market cap or BTC-anchor.
- **Same windows as stats**: 30, 60, 90, 252 bars. Include 30-bar despite potential noise — let users filter.
- **Intersection only**: Correlation computed only on bars where BOTH assets have returns. NULL if overlap < window size.
- **Canonical pair order**: Store id_a < id_b only. Half the rows. Downstream queries check both directions.
- **Pearson + Spearman**: Both correlation methods stored (research should validate whether Spearman adds meaningful value for crypto cross-asset analysis — if research says no, drop Spearman).
- **P-values stored**: Statistical significance for each correlation estimate at each point.
- **Materialized latest view**: Separate table or materialized view with just the latest correlation matrix for fast dashboard queries.

### Refresh & Pipeline Integration
- **Incremental by default, full on demand**: Daily refresh appends new bars only (watermark-based). --full-rebuild flag recomputes entire history.
- **Pipeline position: after returns, before regimes**: Critical ordering decision — these stats are intended as future regime detection inputs. Runs after cmc_returns_bars_multi_tf is fresh, before refresh_cmc_regimes.py.
- **Script split**: Claude's discretion — decide based on runtime analysis and natural separation of concerns.
- **Full CLI filter set**: --ids, --tf, --windows, --full-rebuild, --dry-run, --continue-on-error. Consistent with other refresh scripts.

### Downstream Consumption
- **Dashboard page**: Add new page to Streamlit dashboard showing asset stats table + correlation heatmap. Leverage existing dashboard infrastructure (db.py, queries/, charts.py patterns).
- **Notebook section**: Add desc stats + correlation heatmap section to Phase 40 "Explore Indicators" notebook (Notebook 1). Natural complement to AMA/regime exploration narrative.
- **Regime wiring**: Substantial integration — wire rolling stats (e.g., rolling std, Sharpe, drawdown) as optional inputs to the regime labeling pipeline. Not just "data available" — actual code changes to regime pipeline to consume these stats.
- **Quality checks**: Review existing stats runners, tests, and audits. Extend or reuse existing patterns — do NOT duplicate infrastructure. Match project conventions for new table families.

### Claude's Discretion
- Table format (long vs wide) — decide based on project conventions and query patterns
- Script split (single vs separate for stats/correlation)
- Exact columns and naming conventions for stat columns
- Materialized view refresh strategy (trigger vs scheduled vs on-demand)
- How to wire desc stats into regime pipeline (which stats, how they influence labeling)
- Quality check approach (extend existing runner vs new runner vs inline checks)
- Exact dashboard page layout and chart types for correlation heatmap
- Whether Spearman correlation adds value (pending research validation)

</decisions>

<specifics>
## Specific Ideas

- Pipeline order (after returns, before regimes) enables a future feedback loop: rolling stats → regime labels → regime-filtered IC scores
- Canonical pair ordering (id_a < id_b) with CHECK constraint prevents accidental double-storage
- cmc_returns_bars_multi_tf already has ret_arith column — direct source for all mean/std/Sharpe calculations
- scipy.stats.pearsonr / spearmanr provide both coefficient and p-value in one call
- NullPool pattern for DB connections, consistent with all other refresh scripts
- dim_timeframe.tf_days_nominal for annualization — already wrapped in DimTimeframe Python class
- Materialized latest correlation view enables sub-second dashboard queries vs scanning full time series
- Phase 36 PSR uses Pearson kurtosis (fisher=False) — consistency matters for downstream comparison

</specifics>

<deferred>
## Deferred Ideas

- Portfolio-level statistics (aggregate across assets) — separate from per-asset stats
- Correlation regime detection (e.g., "correlation breakdown" regime) — would need new regime type, not just wiring existing stats
- Rolling beta (vs market proxy) — related but distinct from pairwise correlation
- Time-varying covariance matrix estimation (DCC-GARCH, etc.) — academic enhancement, v2.0+
- Equity curve statistics — needs backtest results, not raw returns

</deferred>

---

*Phase: 41-asset-descriptive-stats-correlation*
*Context gathered: 2026-02-24*
