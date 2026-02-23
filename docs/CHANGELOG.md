# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- **Regime pipeline (Phase 27)**: `refresh_cmc_regimes.py` reads bars+EMAs, runs L0-L2 labeling, resolves policy, writes to 4 tables (`cmc_regimes`, `cmc_regime_flips`, `cmc_regime_stats`, `cmc_regime_comovement`)
- **cmc_features redesign**: Comprehensive bar-level feature store, 112 columns; removed EMA columns, added 46 bar returns, 36 vol, 18 TA columns
- **Dynamic column matching**: DDL is contract, Python auto-discovers source→target via `get_columns()`
- **HysteresisTracker**: 3-bar hold for loosening, immediate accept for tightening
- **`--no-regime` flag**: A/B testing for signal generators
- **Orchestrator**: `run_daily_refresh.py --all` now runs bars→EMAs→regimes

### Changed
- All 3 signal generators accept `regime_enabled` param
- Signal generators query `cmc_ema_multi_tf_u` directly via LEFT JOINs (not cmc_features)
- All 109 TFs refreshed (~2.1M rows total in cmc_features)

### Deprecated
- `cmc_features` EMA columns (`ema_9/10/21/50/200`) — query `cmc_ema_multi_tf_u` directly

## [0.6.0] - 2026-02-07

### Added
- **Multi-TF feature pipeline**: All feature tables support multi-TF via (id, ts, tf) PK
- **Table families**: 24 tables = 4 families × 6 tables (price bars, bar returns, EMA values, EMA returns)
- **Unified _u tables**: Sync/union pattern with `alignment_source` watermark tracking
- **Z-scores on returns tables**: Multi-window z-scores (`_zscore_30`, `_zscore_90`, `_zscore_365`); adaptive window; `is_outlier` BOOLEAN

### Changed
- Orchestrator: `run_all_feature_refreshes --all --all-tfs`
- Feature refresh order: vol, ta (parallel) → cmc_features (depends on both)
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

[Unreleased]: https://github.com/your-username/ta_lab2/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/your-username/ta_lab2/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/your-username/ta_lab2/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/your-username/ta_lab2/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/your-username/ta_lab2/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/your-username/ta_lab2/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/your-username/ta_lab2/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/your-username/ta_lab2/releases/tag/v0.3.0
