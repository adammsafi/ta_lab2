---
phase: 41-asset-descriptive-stats-correlation
verified: 2026-02-24T17:10:28Z
status: passed
score: 6/6 must-haves verified
gaps: []
human_verification:
  - test: Open Streamlit dashboard and navigate to Asset Statistics and Correlation page
    expected: Stats table and correlation heatmap render without errors when data is present
    why_human: Cannot verify Streamlit visual rendering or interactive filter behavior programmatically
  - test: Run refresh_cmc_asset_stats twice to check incremental watermark
    expected: Second run writes 0 rows (watermark prevents re-processing)
    why_human: Requires live DB connection to verify watermark behavior end-to-end
  - test: Run refresh_cmc_cross_asset_corr and verify cmc_corr_latest is refreshed
    expected: cmc_corr_latest materialized view is populated with latest correlation per pair
    why_human: Requires live DB connection and materialized view refresh to confirm
---

# Phase 41: Asset Descriptive Stats and Correlation Verification Report

**Phase Goal:** Users can query rolling per-asset descriptive statistics (mean return, std dev, Sharpe, skewness, kurtosis, max drawdown) and cross-asset return correlation as persisted time-series tables -- tracked over time at every bar, not just latest snapshots -- refreshed daily and usable as future regime detection inputs.

**Verified:** 2026-02-24T17:10:28Z
**Status:** PASSED
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Rolling per-asset stats (mean, std, Sharpe, skew, kurtosis, max_dd) exist as persisted time-series table | VERIFIED | cmc_asset_stats table created in migration 8d5bc7ee1732 with PK (id, ts, tf), 32 windowed + 2 non-windowed stat columns |
| 2 | Cross-asset pairwise correlation exists as persisted time-series table with canonical pair ordering | VERIFIED | cmc_cross_asset_corr table with PK (id_a, id_b, ts, tf, window) and CHECK(id_a < id_b) confirmed in migration |
| 3 | Stats refresh pipeline correctly computes and stores rolling stats with NULL policy and watermarks | VERIFIED | refresh_cmc_asset_stats.py uses rolling(window=W, min_periods=W), watermark read/write via cmc_asset_stats_state, scoped DELETE+INSERT |
| 4 | Correlation refresh pipeline computes Pearson+Spearman rolling correlation and refreshes materialized view | VERIFIED | refresh_cmc_cross_asset_corr.py uses scipy.stats.pearsonr/spearmanr, .statistic/.pvalue named attributes, CONCURRENTLY refresh with fallback |
| 5 | Pipeline is wired into daily refresh orchestration at correct position (after AMAs, before regimes) | VERIFIED | run_daily_refresh.py has --desc-stats flag, run_desc_stats_refresher() function, TIMEOUT_DESC_STATS=3600, executes after AMAs block before regimes block |
| 6 | Regime pipeline and stats quality infrastructure consume desc stats output | VERIFIED | regime_data_loader.py has load_rolling_stats_for_asset(), refresh_cmc_regimes.py has --no-desc-stats flag + augmentation loop, run_all_stats_runners.py has check_desc_stats_quality() with 7 checks + FAIL/WARN integration |

**Score:** 6/6 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/8d5bc7ee1732_asset_stats_and_correlation_tables.py | Migration creating 5 DB objects | VERIFIED | 241 lines; creates cmc_asset_stats, cmc_cross_asset_corr, 2 state tables, cmc_corr_latest materialized view; chains from 6f82e9117c58 |
| src/ta_lab2/scripts/desc_stats/__init__.py | Package marker | VERIFIED | Exists |
| src/ta_lab2/scripts/desc_stats/refresh_cmc_asset_stats.py | Rolling stats computation script | VERIFIED | 581 lines; computes 8 stats x 4 windows; watermark-based incremental; NullPool multiprocessing |
| src/ta_lab2/scripts/desc_stats/refresh_cmc_cross_asset_corr.py | Pairwise correlation computation script | VERIFIED | 790 lines; Pearson+Spearman via scipy; canonical pair ordering; CONCURRENTLY refresh |
| src/ta_lab2/scripts/desc_stats/run_all_desc_stats_refreshes.py | Orchestrator (asset_stats then correlation) | VERIFIED | 470 lines; sequential: asset_stats -> correlation; --continue-on-error; dry-run; --workers |
| src/ta_lab2/scripts/run_daily_refresh.py | Daily refresh with desc_stats stage | VERIFIED | Has TIMEOUT_DESC_STATS=3600, run_desc_stats_refresher(), --desc-stats flag, --no-desc-stats-in-regimes flag, correct position in --all pipeline |
| src/ta_lab2/dashboard/queries/asset_stats.py | 4 cached query functions | VERIFIED | 162 lines; load_asset_stats_latest (ttl=300), load_corr_latest (ttl=300), load_asset_stats_timeseries (ttl=300), load_asset_symbols (ttl=3600) |
| src/ta_lab2/dashboard/charts.py | build_correlation_heatmap + build_stat_timeseries_chart | VERIFIED | go.Heatmap with colorscale=RdBu, zmid=0, zmin=-1, zmax=1; symmetric mirror; diagonal=1.0 |
| src/ta_lab2/dashboard/pages/4_asset_stats.py | Streamlit page with stats table + correlation heatmap | VERIFIED | 280 lines; 3 sections; sidebar TF+window filters; Pearson/Spearman radio toggle; CSV download |
| src/ta_lab2/dashboard/app.py | Page registered in navigation | VERIFIED | Analytics group contains 4_asset_stats.py as Asset Statistics and Correlation |
| src/ta_lab2/scripts/regimes/regime_data_loader.py | load_rolling_stats_for_asset() function | VERIFIED | Lines 529-592; queries cmc_asset_stats; returns None on empty/error; indexed by ts UTC |
| src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py | --no-desc-stats flag + augmentation | VERIFIED | --no-desc-stats argparse flag; augmentation loop checks getattr(args, no_desc_stats, False); imports load_rolling_stats_for_asset |
| src/ta_lab2/scripts/stats/run_all_stats_runners.py | check_desc_stats_quality() with quality checks | VERIFIED | Lines 340-581; 7 checks across 2 tables; desc_fail/desc_warn variables integrate into overall PASS/WARN/FAIL |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| refresh_cmc_asset_stats.py | cmc_returns_bars_multi_tf | SELECT with timestamp double-quoted, roll=FALSE filter | VERIFIED | Correctly handles PostgreSQL reserved word timestamp; canonical bars only |
| refresh_cmc_asset_stats.py | cmc_asset_stats | Scoped DELETE + INSERT per (id, tf) | VERIFIED | DELETE WHERE ts >= first_ts then INSERT; watermark upsert ON CONFLICT DO UPDATE |
| refresh_cmc_cross_asset_corr.py | cmc_returns_bars_multi_tf | _load_returns_wide() wide pivot | VERIFIED | Pivots ret_arith to wide (ts x asset_id); double-quotes timestamp; tz-aware fix applied |
| refresh_cmc_cross_asset_corr.py | cmc_corr_latest | _refresh_materialized_view() at end of run | VERIFIED | CONCURRENTLY with non-concurrent fallback; called in main() unless --dry-run |
| run_all_desc_stats_refreshes.py | refresh_cmc_asset_stats.py | subprocess -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats | VERIFIED | build_asset_stats_command() builds correct -m invocation; Stage 1 |
| run_all_desc_stats_refreshes.py | refresh_cmc_cross_asset_corr.py | subprocess -m ta_lab2.scripts.desc_stats.refresh_cmc_cross_asset_corr | VERIFIED | build_correlation_command() builds correct -m invocation; Stage 2 after asset_stats |
| run_daily_refresh.py | run_all_desc_stats_refreshes.py | subprocess -m ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes | VERIFIED | run_desc_stats_refresher() wired after AMAs before regimes |
| run_daily_refresh.py | refresh_cmc_regimes.py | --no-desc-stats-in-regimes flag propagation | VERIFIED | run_regime_refresher() checks no_desc_stats_in_regimes and passes --no-desc-stats to subprocess |
| 4_asset_stats.py | load_asset_stats_latest() | import + call with engine and tf | VERIFIED | Imported from ta_lab2.dashboard.queries.asset_stats; drives Section 1 stats table |
| 4_asset_stats.py | load_corr_latest() | import + call with engine tf window | VERIFIED | Drives correlation heatmap; Pearson/Spearman radio switch selects metric_col |
| 4_asset_stats.py | build_correlation_heatmap() | import + call with corr_df metric | VERIFIED | Rendered via st.plotly_chart; HTML download button wired |
| regime_data_loader.py | cmc_asset_stats | SELECT 5 rolling stat columns indexed by ts | VERIFIED | Returns None gracefully on empty/error; caller left-joins into daily_df |
| refresh_cmc_regimes.py | load_rolling_stats_for_asset() | imported and called in per-asset main loop | VERIFIED | Import at line 61; called at line 850; left-join merge with daily_df |
| run_all_stats_runners.py | check_desc_stats_quality() | called in run_all_stats() | VERIFIED | Called at line 635; desc_fail/desc_warn at lines 643-644; integrated into overall_status |
---

### Schema Verification (Plan 41-01)

| Object | Expected | Status | Details |
|--------|----------|--------|---------|
| cmc_asset_stats PK | (id, ts, tf) | VERIFIED | sa.PrimaryKeyConstraint(id, ts, tf) |
| cmc_asset_stats stat columns | 33+ columns | VERIFIED | 8 stats x 4 windows = 32 windowed + max_dd_from_ath + rf_rate = 34 total stat columns |
| cmc_cross_asset_corr PK | (id_a, id_b, ts, tf, window) | VERIFIED | sa.PrimaryKeyConstraint(id_a, id_b, ts, tf, window) |
| cmc_cross_asset_corr CHECK | id_a < id_b | VERIFIED | sa.CheckConstraint(id_a < id_b, name=chk_corr_pair_order) |
| cmc_corr_latest | DISTINCT ON (id_a, id_b, tf, window) ordered ts DESC | VERIFIED | CREATE MATERIALIZED VIEW with double-quoted window reserved word |
| cmc_corr_latest unique index | Supports CONCURRENTLY refresh | VERIFIED | CREATE UNIQUE INDEX idx_corr_latest_pk ON (id_a, id_b, tf, window) |
| Alembic chain | Revises 6f82e9117c58 | VERIFIED | down_revision = 6f82e9117c58; parent file confirmed present at alembic/versions/ |

---

### Computational Correctness Checks (Plans 41-02, 41-03)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| kurt_fisher = pandas .kurt() (normal=0) | VERIFIED | roll.kurt() with comment: pandas .kurt() = Fisher (normal=0) |
| kurt_pearson = kurt_fisher + 3.0 | VERIFIED | result[f_kurt_pearson_{w}] = result[f_kurt_fisher_{w}] + 3.0 |
| NULL for first (window-1) bars | VERIFIED | rolling(window=w, min_periods=w) enforces strict NULL policy across all stat columns |
| max_dd_from_ath uses expanding window | VERIFIED | _current_drawdown_from_ath() uses eq.cummax() -- expanding ATH |
| max_dd_window uses rolling window | VERIFIED | _rolling_max_drawdown() uses rolling(window=window, min_periods=window) |
| sharpe_ann = sharpe_raw * sqrt(365/tf_days) | VERIFIED | ann_factor = math.sqrt(365.0 / tf_days); sharpe_ann = sharpe_raw * ann_factor |
| Pearson/Spearman via scipy named tuple attributes | VERIFIED | pr_result.statistic, pr_result.pvalue, sr_result.statistic, sr_result.pvalue |
| Canonical pair ordering (id_a < id_b) | VERIFIED | [(a, b) for a in ids for b in ids if a < b] in _process_tf() |
| Incremental watermark-based refresh (asset stats) | VERIFIED | cmc_asset_stats_state read/write; ON CONFLICT DO UPDATE upsert |
| Incremental watermark-based refresh (correlation) | VERIFIED | _load_all_watermarks() bulk load; _update_state() ON CONFLICT DO UPDATE |

Note on n_obs NULL policy: The plan spec states n_obs is always populated but n_obs is None for the
first (window-1) rows where insufficient history exists, consistent with all other NULL-policy columns.
When sufficient history exists (i >= window-1), n_obs is always populated even when correlation values
are NULL due to insufficient valid intersection. This is semantically correct behavior.

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| None | No stubs, TODO/FIXME, placeholder returns, or empty handlers found | N/A | None |

All Phase 41 files contain real implementation logic. No stub patterns detected.

---

### Human Verification Required

#### 1. Dashboard Visual Rendering

**Test:** Start the Streamlit app and navigate to Asset Statistics and Correlation page. Select TF=1D, window=90 bars.
**Expected:** Stats table displays asset rows with 252-window stats preselected; correlation heatmap renders as symmetric RdBu grid; Pearson/Spearman radio switch updates the heatmap; CSV and HTML download buttons work.
**Why human:** Cannot verify Plotly rendering, interactive filter reactivity, or visual layout programmatically.

#### 2. Watermark Incremental Refresh (Asset Stats)

**Test:** Run python -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats --ids 1 --tf 1D, then run the same command again.
**Expected:** First run writes N rows and updates watermark; second run writes 0 rows (up to date).
**Why human:** Requires live DB connection to observe watermark state update and incremental behavior end-to-end.

#### 3. Materialized View Refresh (Correlation)

**Test:** Run python -m ta_lab2.scripts.desc_stats.refresh_cmc_cross_asset_corr --ids 1,52 --tf 1D, then query cmc_corr_latest.
**Expected:** cmc_corr_latest has rows for (id_a=1, id_b=52, tf=1D) with all 4 windows; CONCURRENTLY refresh log line appears.
**Why human:** Requires live DB to confirm materialized view population and refresh mechanism.

---

*Verified: 2026-02-24T17:10:28Z*
*Verifier: Claude (gsd-verifier)*
