# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - Unreleased

### Added
- **Feature Selection (Phase 80)**: IC-IR analysis of 107 candidate features; 20 promoted to active tier (IC-IR >= 1.0); AMA features dominate active tier (18/20); per-asset IC-IR variation analysis; concordance IC-IR vs MDA (rho=0.14); `dim_feature_selection` with quintile_monotonicity column; NON_STATIONARY features use 1.5x IC-IR cutoff (soft gate)
- **GARCH Volatility (Phase 81)**: 4-variant GARCH engine (GARCH, EGARCH, GJR-GARCH, FIGARCH); Student's t distribution for crypto heavy tails; blend forecasting with RMSE-weighted model selection; carry-forward fallback with 5-day exponential decay; `garch_forecasts` and `garch_diagnostics` tables; FIGARCH requires 200+ observations for fitting
- **Strategy Bake-Off (Phase 82)**: Multi-strategy evaluation with AMA features (KAMA, DEMA, TEMA, HMA); per-asset IC-IR weighting for Black-Litterman views; Hyperliquid cost scenarios (3/5/10 bps) vs Kraken (5/10/20 bps); CPCV and PKF cross-validation; `strategy_bakeoff_results` table; expression-based signal param grid
- **Dashboard Research Pages (Phase 83)**: Strategy-first view with bakeoff results; signal monitor with direction/strength heatmap; asset hub with candlestick charts and EMA overlays; regime overlays on charts; sidebar reorganized into 4 logical groups (Overview, Analysis, Operations, Monitor)
- **Dashboard Market Pages (Phase 84)**: Hyperliquid perps page with OI time series (hl_open_interest) and candles; AMA inspector with cross-asset comparison; regime dashboard with comovement; IC results landing widget; placeholder pages for Portfolio and Risk Tier
- **Dashboard Operations Pages (Phase 85)**: Stats monitoring with pass/warn/fail counts; drawdown tracking against starting_capital; operational health view with pipeline status; auto-discovery of stats tables via information_schema
- **Portfolio Pipeline (Phase 86)**: Stop calibration from MAE/MFE analysis (3-tier stop ladder, 2-tier TP); `stop_calibrations` table; Black-Litterman portfolio allocation with MV/CVaR/HRP methods; `portfolio_allocations` table; parity checker `--bakeoff-winners` mode (auto-discover strategies from strategy_bakeoff_results); GARCH vol integration into position sizing (sqrt(252) annualization)
- **Pipeline Alert Wiring (Phase 87)**: IC staleness monitor (returns 0/1/2 gate code); signal anomaly gate with z-score baseline check (exit 2 = blocked); `pipeline_run_log` dead-man switch (run audit per stage); Telegram alert integration for kill switch, drift pause, and IC decay; `pipeline_alert_log` unified throttle table; `signal_anomaly_log` audit table
- **Integration Testing (Phase 88)**: End-to-end smoke test CLI (`scripts/integration/smoke_test.py`, 26 checks across 9 stages); daily burn-in report CLI (`scripts/integration/daily_burn_in_report.py`, 8-metric ON TRACK/WARNING/STOP verdict); parity checker `--pnl-correlation-threshold` flag (default 0.99, burn-in uses 0.90); 7-day burn-in protocol documented
- **CTF Schema (Phase 89)**: Cross-timeframe feature dimension table (`dim_ctf_indicators`); fact table (`ctf`) with base_tf x ref_tf x indicator structure; `ctf_state` watermark table; YAML config with base_tfs (1D, 2D, 3D), ref_tfs (7D through 365D), and 9 indicator families
- **CTF Computation (Phase 90)**: Slope (linear regression coefficient), divergence (base vs ref difference), z-score (rolling normalization), agreement composites (directional alignment across timeframes); all computed from existing ta/vol/returns/features source tables
- **CTF Pipeline (Phase 91)**: Incremental refresh with ctf_state watermark tracking; `refresh_ctf_step` integrated as Phase 2c in `run_all_feature_refreshes` (after microstructure, before CS norms); `--full-refresh` deletes and rebuilds ctf rows; CTF failure is non-fatal (pipeline continues)
- **CTF Feature Selection (Phase 92)**: IC sweep for CTF features using same batch_compute_ic engine as Phase 80; `dim_ctf_feature_selection` table (active/watch/archive tiers, ic_ir_cutoff=0.5); CTF vs AMA redundancy check (Spearman rho=0.19, low -- CTF provides different signal); top features: macd_*_7d_agreement (IC-IR=1.29), close_fracdiff_7d (IC-IR=0.73)

### Changed
- Daily refresh pipeline expanded from 15 to 21 stages: added GARCH (Stage 11), Stop Calibration (Stage 13), Portfolio Allocation (Stage 14), IC Staleness Monitor, Signal Anomaly Gate, Pipeline Run Log, and completion alerts
- Parity checker now accepts configurable `--pnl-correlation-threshold` flag (default 0.99 preserved; burn-in phase uses 0.90)
- Operations manual updated for v1.2.0 pipeline: Part 2 (21-stage DAG, GARCH/stop/portfolio docs), Part 4 (parity threshold + signal anomaly gate), Part 7 (burn-in protocol + updated Gate 1 criteria)
- Dashboard reorganized into Analysis (Research + Markets) and Operations navigation groups; 4 sidebar groups (Overview, Analysis, Operations, Monitor)
- `run_all_feature_refreshes` extended with CTF computation as Phase 2c stage

## [1.0.0] - 2026-03-01

### Added
- **Strategy Bake-Off (Phase 42)**: IC/PSR/CV evaluation of existing signals; 2 strategies selected with walk-forward backtests (Sharpe >= 1.0, Max DD <= 15%)
- **Exchange Integration (Phase 43)**: Coinbase + Kraken APIs with paper order adapter and price feed comparison
- **Order & Fill Store (Phase 44)**: `orders`, `fills`, `positions` tables with FIFO matching and full audit trail
- **Paper-Trade Executor (Phase 45)**: Signal -> order -> fill -> position pipeline with backtest parity verification; DB-driven config via `dim_executor_config`
- **Risk Controls (Phase 46)**: RiskEngine with kill switch (`dim_risk_state`), position caps, daily loss stops, circuit breaker
- **Drift Guard (Phase 47)**: DriftMonitor with tracking error/slippage metrics, auto-pause on divergence, Telegram escalation
- **Loss Limits Policy (Phase 48)**: VaR simulation, intraday stop analysis, pool-level capital allocation
- **Tail-Risk Policy (Phase 49)**: Hard stops vs vol-sizing analysis, flatten triggers, policy document
- **Data Economics (Phase 50)**: Cost audit, build-vs-buy analysis, data trigger definitions
- **Perps Readiness (Phase 51)**: Funding rate ingestion, margin model, liquidation buffer, venue downtime playbook
- **Operational Dashboard (Phase 52)**: Streamlit dashboard with live PnL, exposure, drawdown, drift, risk status views
- **V1 Validation (Phase 53)**: Success criteria framework for paper trading validation
- **V1 Results Memo (Phase 54)**: Formal report with methodology, results, failure modes, research answers
- **Feature Evaluation (Phase 55)**: IC sweep across 109 TFs (82K+ rows in `ic_results`), BH-corrected promotion gate, 107 features promoted to `dim_feature_registry`, adaptive RSI A/B comparison
- **Factor Analytics (Phase 56)**: QuantStats tear sheets, IC decay/rank IC, quintile returns engine, cross-sectional normalization, MAE/MFE, Monte Carlo CI
- **Advanced Labeling (Phase 57)**: Triple barrier labeling, meta-labeling (RF + StandardScaler), CUSUM event filter, trend scanning labels
- **Portfolio Construction (Phase 58)**: PyPortfolioOpt integration, Black-Litterman with market cap prior, TopkDropout selector, BetSizer, StopLadder, TurnoverTracker
- **Microstructural Features (Phase 59)**: Fractional differentiation (FFD), Kyle/Amihud lambda, SADF bubble detection, Shannon/LZ entropy, pairwise codependence
- **ML Infrastructure (Phase 60)**: Expression engine for config-driven feature computation, RegimeRouter, DoubleEnsemble concept drift, Optuna TPE sweep, MDA/SFI/clustered feature importance, `ml_experiments` tracking

### Changed
- Daily refresh pipeline: bars -> EMAs -> AMAs -> regimes -> features -> signals -> executor -> drift -> stats
- Feature lifecycle: IC sweep -> `ic_results` -> FeaturePromoter (dual-source) -> BH gate -> `dim_feature_registry`
- Telegram notifications wired for kill switch, drift alerts, and daily digest
- `ExecutorConfig.initial_capital` loaded from DB with NULL fallback
- Drift monitor skip upgraded to `[WARN]` with actionable `--paper-start` guidance

## [0.9.0] - 2026-02-24

### Added
- **Adaptive Moving Averages (Phase 35)**: KAMA, DEMA, TEMA, HMA with full multi-TF parity, calendar variants, unified `_u` sync, z-scores, and daily refresh integration (~91M rows)
- **IC Evaluation Engine (Phase 37)**: Spearman IC, rolling IC, IC-IR, regime breakdown, significance testing; `ic_results` DB persistence
- **PSR/DSR/MinTRL (Phase 36)**: Full Lopez de Prado probabilistic Sharpe ratio formulas; PurgedKFoldSplitter + CPCVSplitter for leakage-free CV
- **Feature Experimentation (Phase 38)**: YAML registry, ExperimentRunner, BH-corrected promotion gate, `dim_feature_registry` + `feature_experiments` tables
- **Streamlit Dashboard (Phase 39)**: 5 pages (landing, pipeline monitor, research explorer, asset stats, experiments)
- **Polished Notebooks (Phase 40)**: `helpers.py` + 3 Jupyter notebooks (indicators, features, experiments)
- **Asset Stats & Correlation (Phase 41)**: Rolling descriptive stats in `asset_stats`; pairwise correlation in `cross_asset_corr`

### Changed
- `run_daily_refresh --all` includes AMA refresh and descriptive stats stages
- Cross-validation splitters built from scratch (mlfinlab discontinued)
- PSR column renamed via Alembic migration for Lopez de Prado formula

## [0.8.0] - 2026-02-22

### Added
- **Stats/QA Orchestration (Phase 29-30)**: `run_daily_refresh --all` now includes stats runners for bars/features; `audit_results` DB table tracks data quality checks
- **table_summary DB table**: `refresh_table_summary.py` provides row counts and metadata across all pipeline tables
- **CI docs job**: `mkdocs build --strict` gate added to GitHub Actions CI workflow
- **Documentation freshness pass**: Version strings updated to 0.8.0, stale references resolved, TODO placeholders removed
- **Runbooks (Phase 32)**: Operational runbooks for regime pipeline, backtest pipeline, new-asset onboarding SOP, and disaster recovery guide in `docs/operations/`
- **Alembic migrations (Phase 33)**: Alembic framework bootstrapped with `alembic/` directory, baseline no-op revision (`25f2b3c90f65`), legacy SQL migration catalog in `sql/migration/CATALOG.md`, and schema change workflow documented in CONTRIBUTING.md

### Changed
- Ruff lint blocking in CI; pre-commit hook updated; zero violations enforced
- mypy type checking scoped to `features/` and `regimes/` (non-blocking in CI)
- `--min-bars-l0/l1/l2` flags wired through to `assess_data_budget`

### Fixed
- Backtest pipeline end-to-end verification (Phase 28)
- EMA crossover, RSI mean-revert, and ATR breakout signal generators fully functional

## [0.7.0] - 2026-02-10

### Added
- **Regime pipeline (Phase 27)**: `refresh_regimes.py` reads bars+EMAs, runs L0-L2 labeling, resolves policy, writes to 4 tables (`regimes`, `regime_flips`, `regime_stats`, `regime_comovement`)
- **features redesign**: Comprehensive bar-level feature store, 112 columns; removed EMA columns, added 46 bar returns, 36 vol, 18 TA columns
- **Dynamic column matching**: DDL is contract, Python auto-discovers source→target via `get_columns()`
- **HysteresisTracker**: 3-bar hold for loosening, immediate accept for tightening
- **`--no-regime` flag**: A/B testing for signal generators
- **Orchestrator**: `run_daily_refresh.py --all` now runs bars→EMAs→regimes

### Changed
- All 3 signal generators accept `regime_enabled` param
- Signal generators query `ema_multi_tf_u` directly via LEFT JOINs (not features)
- All 109 TFs refreshed (~2.1M rows total in features)

### Deprecated
- `features` EMA columns (`ema_9/10/21/50/200`) — query `ema_multi_tf_u` directly

## [0.6.0] - 2026-02-07

### Added
- **Multi-TF feature pipeline**: All feature tables support multi-TF via (id, ts, tf) PK
- **Table families**: 24 tables = 4 families × 6 tables (price bars, bar returns, EMA values, EMA returns)
- **Unified _u tables**: Sync/union pattern with `alignment_source` watermark tracking
- **Z-scores on returns tables**: Multi-window z-scores (`_zscore_30`, `_zscore_90`, `_zscore_365`); adaptive window; `is_outlier` BOOLEAN

### Changed
- Orchestrator: `run_all_feature_refreshes --all --all-tfs`
- Feature refresh order: vol, ta (parallel) → features (depends on both)
- `BaseEMARefresher` hierarchy with 3 refresher scripts

## [0.5.0] - 2026-02-04

### Added
- **Memory Preparation (Phase 11)**: Pre-reorganization memory snapshots with codebase, external directories, and conversation history indexing
- **Archive Foundation (Phase 12)**: Category-based .archive/ structure with manifest tracking, SHA256 checksums, and git history preservation
- **Documentation Consolidation (Phase 13)**: ProjectTT DOCX/Excel to Markdown conversion with pypandoc+markdownify, organized docs/ structure with index
- **Tools Integration (Phase 14)**: Data_Tools migration to ta_lab2.tools.data_tools with 6 functional categories (analysis, processing, memory, export, context, generators)
- **Economic Data Strategy (Phase 15)**: Production-ready ta_lab2.integrations.economic with FredProvider, rate limiting (120/min), TTL caching, circuit breaker, data quality validation
- **Repository Cleanup (Phase 16)**: Root directory cleanup, temp file archiving, *_refactored.py resolution, duplicate detection with SHA256
- **Verification & Validation (Phase 17)**: Dynamic import validation, import-linter for circular dependency detection, pre-commit hooks with Ruff
- **Structure Documentation (Phase 18)**: decisions.json manifest with JSON Schema, before/after directory diagrams, REORGANIZATION.md migration guide
- **Memory Validation (Phase 19)**: AST-based function extraction (indexing.py), relationship linking (contains/calls/imports/moved_to/similar_to), three-tier duplicate detection (95%+/85-95%/70-85%), memory graph validation

### Changed
- pyproject.toml updated with [fred], [fed], [economic] optional dependency extras for economic data integration
- Memory infrastructure enhanced with function-level granularity and relationship graph
- Archive manifest schema versioned with $schema URLs for forward compatibility
- CI workflow enhanced with import validation and circular dependency checks

### Fixed
- Module docstrings positioned before imports for proper __doc__ detection
- Relative imports converted to absolute imports in migrated scripts
- Graceful handling of optional dependencies (fredapi, pandas) with helpful error messages

### Deprecated
- fredtools2 and fedtools2 packages (archived with ALTERNATIVES.md migration guidance)

## [0.4.0] - 2026-02-01

### Added
- **Time Model**: Unified dim_timeframe (199 TFs) and dim_sessions tables for multi-timeframe architecture
- **Feature Pipeline**: Returns (1D-365D), volatility (Parkinson, GK, RS), technical indicators (RSI, MACD, BB, ATR, ADX, Stochastic)
- **Signal System**: EMA crossover, RSI mean reversion, ATR breakout signal generation with database-driven configuration (dim_signals)
- **Backtest Integration**: SignalBacktester with triple-layer reproducibility validation (deterministic queries, feature hashing, version tracking)
- **Memory System**: Mem0 + Qdrant integration with 3,763+ memories, LLM-powered conflict detection, health monitoring, staleness tracking
- **AI Orchestrator**: Multi-platform coordination (Claude, ChatGPT, Gemini) with cost-optimized routing and quota management
- **Observability**: PostgreSQL-backed metrics, distributed tracing, health checks (liveness/readiness/startup), alert infrastructure with Telegram integration
- **Validation Gates**: CI blockers for time alignment, data consistency (zero-tolerance for duplicates/orphans), backtest reproducibility
- **Documentation**: DESIGN.md (system overview), deployment.md (full deployment guide), tiered README with quick-start, expanded ARCHITECTURE.md (1,233 lines)

### Changed
- EMA tables unified under time model with dim_timeframe foreign key references
- Test infrastructure upgraded to three-tier pattern (real_deps, mixed_deps, mocked_deps) with pytest markers
- Quota management enhanced with reservation system, auto-release on usage, and 50%/80%/90% alert thresholds
- README restructured with tiered quick-start-first approach and 6 collapsible component sections

### Fixed
- EMA calculation edge cases in multi-timeframe scenarios with calendar alignment
- Memory embedding dimension validation (1536-dim) prevents corruption before ChromaDB/Qdrant insertion
- Database connection handling improvements with graceful degradation patterns

## [0.3.1] - 2025-11-13

### Added
- Initial EMA multi-timeframe support
- Basic CLI for pipeline execution
- Package structure under src/ta_lab2 with features, regimes, signals, pipelines, backtests
- Core library modules: features, regimes, signals, pipelines, backtests, analysis, viz
- Price-based indicators: EMA, MACD, RSI, Stochastic, MFI, OBV, ADX, Bollinger Bands
- Returns and volatility calculations: arithmetic/log returns, Parkinson/Garman-Klass/Rogers-Satchell volatility, ATR
- Configuration system with config.py and YAML-based runtime options
- Testing infrastructure with pytest and GitHub Actions CI workflow
- Documentation: README.md with layer stack overview, ARCHITECTURE.md with data flows

### Fixed
- Database connection handling improvements

## [0.3.0] - 2025-12-XX

### Added
- Core ta_lab2 package structure
- Regime detection framework
- Basic EMA calculations

[Unreleased]: https://github.com/adammsafi/ta_lab2/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/adammsafi/ta_lab2/compare/v1.0.0...v1.2.0
[1.0.0]: https://github.com/adammsafi/ta_lab2/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/adammsafi/ta_lab2/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/adammsafi/ta_lab2/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/adammsafi/ta_lab2/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/adammsafi/ta_lab2/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/adammsafi/ta_lab2/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/adammsafi/ta_lab2/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/adammsafi/ta_lab2/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/adammsafi/ta_lab2/releases/tag/v0.3.0
