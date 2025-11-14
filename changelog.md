# 🧾 Changelog

All notable changes to **ta_lab2** will be documented in this file.

A changelog is a human-readable history of releases. Each section below describes
what changed in that version so you (and future contributors) don’t need to
reverse-engineer it from git logs.

- When you cut a new version (e.g. `0.1.1`, `0.2.0`), add a new section.
- Keep entries focused on user-visible behaviour: features, fixes, breaking changes, and tooling that affects how the project is used or developed.

---

## [Unreleased]

Changes that have been merged into `main` but not yet released as a tagged version.

- (Add new changes here as you work on them.)

---

## [0.3.1] - 2025-11-13

> Initial structured release of **ta_lab2** as a real Python package with
> features → regimes → signals → pipelines → backtests → analysis/viz.

This release retroactively covers everything from the first commit to the point
where versioning (`0.1.0`) and release automation were introduced.

> 🔧 **Note:** If your project version is bumped (e.g. to `0.3.1`), you can rename this
> section header to match that version.

### 🎯 High-level

- Converted an ad-hoc BTC analysis notebook + scripts into a reusable **Python package**.
- Formalized the **package structure** under `src/ta_lab2` with clear layers:
  **features → regimes → signals → pipelines → backtests → analysis/viz → CLI**.
- Added configuration, tests, and GitHub workflows so the project behaves like a
  real library rather than a one-off experiment.

---

### 📦 Packaging & Configuration

- Added `pyproject.toml` using **setuptools** and a `src/` layout so `ta_lab2` can be installed with `pip`.
- Introduced a top-level `config.py` with:
  - `project_root()` to reliably resolve paths regardless of where the code is run.
  - A central `load_config()` wired to a new YAML file.
- Added `config/default.yaml` to hold runtime options (paths, assets, pipeline settings) in a single place.
- Created `.github/.release-please-manifest.json` and `release-please-config.json` to enable automated, tag-based releases.

---

### 🧱 Core Library Structure

- Created the main package under `src/ta_lab2/`, including:

  - `features/` – indicator & feature engineering:
    - **Price-based indicators**: EMA, MACD, RSI, stochastic, MFI, OBV, ADX, Bollinger bands.
    - **Returns & volatility**: arithmetic/log returns, Parkinson/Garman-Klass/Rogers-Satchell vols, ATR, rolling realized vol.
    - **Trend & segmentation**: basic trend labels and flip-segment builders.
    - **Calendar features**: day-of-week, week-of-year, month, etc.
    - **Feature packs**: helpers to attach a standard “core feature set” in one call.
    - **Ensure helpers**: `ensure_close`, `ensure_ema`, `ensure_rsi`, `ensure_adx`, `ensure_obv`, etc.

  - `regimes/` – regime and policy logic:
    - Multi-timeframe labelers (`label_layer_monthly`, `weekly`, `daily`, `intraday`).
    - EMA **comovement & alignment** stats for higher-order regime classification.
    - Flip-based regime labelling and regime statistics.
    - **Data budget** assessment to decide which layers are safe to compute.
    - Policy table loader (`policy_loader`) and resolver (`resolver`) that map
      regime keys → policy objects (size multipliers, stop multipliers, allowed order types).
    - Proxy inputs/outcomes for cycle/macro approximations, and telemetry
      helpers for logging regime snapshots.

  - `signals/` – trading signals and sizing:
    - Strategy families:
      - `breakout_atr` – ATR-based breakout strategy.
      - `ema_trend` – EMA trend-following entries/exits.
      - `rsi_mean_revert` – RSI mean-reversion signals.
    - `rules.py` with reusable filters (EMA crossovers, RSI filters, vol filters).
    - `position_sizing.py` with fixed-fractional, inverse-vol, and
      volatility-scaled sizing utilities.
    - `registry.py` to register and retrieve strategies by name.
    - `generator.py` to attach signals to a DataFrame based on configuration.

  - `pipelines/` – end-to-end workflows:
    - `btc_pipeline.py` which:
      - Loads BTC OHLCV data from CSV.
      - Attaches core features (returns, vol, indicators).
      - Applies regime logic (labels + policy).
      - Generates signals via the strategy registry.
      - Produces a summarized result suitable for analysis or backtests.

  - `backtests/` – performance and evaluation:
    - `btpy_runner` – a simple backtest loop.
    - `vbt_runner` – **vectorbt** integration with grid search/sweeps.
    - `splitters` – train/test and walk-forward splitting utilities.
    - `metrics` – core performance metrics: CAGR, max drawdown, Sharpe, Sortino, MAR, hit rate, etc.
    - `reports` – leaderboard tables and equity curve plots.
    - `costs` – cost models for slippage/fees.
    - `orchestrator` – multi-strategy backtest coordination and result bundling.

  - `analysis/` – evaluation helpers:
    - Performance decompositions, feature importance/redun­dancy tools, and
      parameter sweep utilities for quick research iterations.
    - Regime evaluation helpers to slice PnL by regime and inspect transitions.

  - `viz/`:
    - `viz/all_plots.py` providing a centralized place for Matplotlib-based
      plots (price + EMA overlays, regime visualizations, realized vol charts).

  - `research/queries/`:
    - Script-style modules for EMA optimizations, sensitivity studies, and walk-forward validation.
    - Kept intentionally separate from the main library to preserve a clean public API.

---

### 🖥️ CLI & IO

- Added `ta_lab2.cli`:
  - Top-level `main()` that builds an argument parser.
  - Subcommands for:
    - Running the BTC pipeline from the command line.
    - Inspecting regimes with convenient CSV/Parquet inputs.
  - Internal helpers for default config + feature attachment.

- Added `io.py` with simple `read_parquet` / `write_parquet` helpers as a stepping
  stone toward DB-backed IO.

- Introduced `resample.py` and `features.resample` for:
  - Calendar/timeframe resampling (e.g., D → W).
  - Seasonal binning and summary statistics over calendar buckets.

---

### 📚 Documentation & Introspection

- Added a richer `README.md`:
  - Project overview and goals.
  - Explanation of the layer stack (features → regimes → signals → pipelines → backtests).
  - Basic usage and CLI examples.

- Added `ARCHITECTURE.md` describing:
  - Each major subpackage and its responsibilities.
  - Typical data flows (e.g., CSV/DB → features → regimes → signals → backtests).

- Added helper tooling to introspect the codebase:
  - `tree_structure.py` generates:
    - `structure.txt` / `structure.md` / `structure.json` / `structure.csv` for directory trees.
    - `API_MAP.md` and `src_structure.json` for class/function listings via AST.
    - All scripts updated to ignore `.venv` / `.venv311`.
  - `generate_function_map_with_purpose.py` builds a CSV with:
    - Module path, qualified name, basic signature info.
    - First docstring line or inferred “purpose”.
    - A short code snippet for each function/method.

---

### ✅ Testing & CI

- Introduced a `tests/` suite with:
  - Calendar feature tests (e.g., quarter/week-of-year/day-of-year expansions).
  - A minimal **BTC pipeline smoke test** that exercises `run_btc_pipeline`
    on a tiny synthetic CSV and asserts basic output shape.
- Added a **smoke import test** (`tests/test_smoke_imports.py`) that imports:
  - `ta_lab2` and all major submodules (features, regimes, signals, pipelines,
    backtests, analysis, viz, research) as a packaging canary.
- Added a GitHub Actions **CI workflow** that:
  - Installs the package from `pyproject.toml`.
  - Runs `pytest` (skipping the heaviest backtest if needed).

---

### 🛠️ Repo Hygiene & Tooling

- Added/updated:
  - `.gitignore` to exclude virtualenvs (`.venv`, `.venv311`), build artifacts, and cache directories.
  - `.gitattributes` for consistent line endings and diff behaviour.
  - `.github/ISSUE_TEMPLATE` files for bugs and feature requests.
  - `.github/pull_request_template.md` with a checklist (tests/docs/CHANGELOG).
  - `CODEOWNERS` for default ownership.
  - `SECURITY.md` for responsible disclosure instructions.

- Improved developer tooling:
  - Added dev dependencies such as `pytest`, `mypy`, `ruff`, `hypothesis`, `pytest-benchmark`.
  - Normalized folder layout and entry points so local development, CI, and releases all use the same structure.

---
