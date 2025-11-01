# 🧾 Changelog

All notable changes to **ta_lab2** will be documented here.

---

## [0.1.0] - 2025-11-01
### 🎯 Overview
First major update of `ta_lab2`: introduces a modular configuration system, full volatility suite, and technical indicator + correlation modules.

---

### ⚙️ Core Refactor
- Moved configuration logic from `src/ta_lab2/config.py` to top-level `config.py`.
- Added path resolution via `project_root()` for robust portability.
- Introduced root-level YAML file (`config/default.yaml`) for user settings.

### 📦 Packaging & CLI
- Added proper `pyproject.toml` build system (setuptools ≥ 68).
- Added `ta-lab2` command-line entry point via `[project.scripts]`.
- CLI now loads settings from root-level config and runs the BTC pipeline modularly.

### 📈 Features
- Introduced **technical indicators** (`rsi`, `macd`, `stoch_kd`, `bollinger`, `adx`, `obv`, `mfi`).
- Added **correlation utilities** (`acf`, `pacf_yw`, `rolling_autocorr`, `xcorr`).

### 📊 Volatility Module Overhaul
- Rewrote `vol.py` to include:
  - Parkinson, Rogers–Satchell, and Garman–Klass volatility estimators.
  - Rolling realized volatility (annualized and multi-window).
  - Rolling historical volatility from log or percent returns.
  - Unified `add_volatility_features()` orchestrator for one-call analysis.

### 🧠 Pipeline Improvements
- Simplified `run_btc_pipeline()` — removed hardcoded paths, made fully callable.
- Prepares project for composable feature + regime detection pipeline.

### 🧪 Developer Experience
- Added dev dependencies: `pytest`, `mypy`, `ruff`, `hypothesis`, `pytest-benchmark`.
- Normalized project structure for testing and CI/CD compatibility.

---

## [Unreleased]
- Add rolling correlation matrices
- Implement feature-store export
- Integrate regime clustering and labeling
- Add unit tests for volatility and indicator modules
