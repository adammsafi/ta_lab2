# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/your-username/ta_lab2/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/your-username/ta_lab2/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/your-username/ta_lab2/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/your-username/ta_lab2/releases/tag/v0.3.0
