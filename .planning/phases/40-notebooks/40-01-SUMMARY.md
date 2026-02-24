---
phase: 40
plan: 01
subsystem: notebooks
tags: [jupyter, plotly, ama, kama, dema, tema, hma, regime, helpers]

dependency-graph:
  requires:
    - 35-ama-engine  # compute_ama() library
    - 27-regime-integration  # cmc_regimes table
    - 37-ic-evaluation  # style_ic_table pattern
  provides:
    - notebooks/helpers.py  # shared DB + data loading + styling helpers
    - notebooks/01_explore_indicators.ipynb  # AMA exploration + regime detection
  affects:
    - 40-02  # 02_ic_analysis.ipynb will import helpers
    - 40-03  # 03_backtest.ipynb will import helpers

tech-stack:
  added:
    - jupyterlab>=4.5  # already in pyproject.toml optional[notebooks]
    - plotly  # interactive charts
    - matplotlib  # regime distribution bar chart
  patterns:
    - NullPool engine per notebook session (notebooks call get_engine() once)
    - pd.to_datetime(df["ts"], utc=True) after every pd.read_sql (Windows tz pitfall)
    - vrect grouping: consecutive same-label bars collapsed to single shape blocks
    - compute_ama() dispatcher for all 4 AMA types (no pre-computed table query)

file-tracking:
  created:
    - notebooks/helpers.py
    - notebooks/01_explore_indicators.ipynb
  modified: []

decisions:
  - id: helpers-nullpool
    description: NullPool engine in get_engine() matches Streamlit dashboard pattern and avoids connection leak in long-running notebook sessions
  - id: amas-on-the-fly
    description: AMAs computed in-notebook from price bars rather than queried from cmc_ama_multi_tf -- notebooks are exploratory, on-the-fly shows the math
  - id: vrect-block-grouping
    description: Consecutive same-label bars grouped into blocks before rendering vrects -- prevents Plotly performance issues with hundreds of individual vrect shapes

metrics:
  duration: "~4 minutes (233 seconds)"
  completed: "2026-02-24"
---

# Phase 40 Plan 01: Shared Helpers and Explore Indicators Notebook Summary

**One-liner:** NullPool helpers.py with 6 utility functions + 29-cell AMA/regime exploration notebook computing KAMA/DEMA/TEMA/HMA on-the-fly with Plotly regime vrect coloring.

## What Was Built

### `notebooks/helpers.py`

Shared utilities importable from any notebook in the `notebooks/` directory. Contains `sys.path` bootstrap so `ta_lab2` is importable without installation.

**Functions:**

| Function | Returns | Description |
|----------|---------|-------------|
| `get_engine()` | `Engine` | NullPool SQLAlchemy engine via `resolve_db_url()` |
| `load_features(engine, id, tf, start, end)` | `DataFrame` | Queries `cmc_features`, ts-indexed UTC |
| `load_price_bars(engine, id, tf, start, end)` | `DataFrame` | Queries `cmc_price_bars_multi_tf`, ts-indexed UTC |
| `load_regimes(engine, id, tf, start, end)` | `DataFrame` | Queries `cmc_regimes`, ts-indexed UTC |
| `validate_asset_data(engine, id, tf, min_days)` | `dict` | Queries `asset_data_coverage`, returns valid/n_days/first_ts/last_ts/message |
| `style_ic_table(df)` | `Styler` | RdYlGn gradient on ic, formats ic/p_value/n_obs |

### `notebooks/01_explore_indicators.ipynb`

29-cell tutorial notebook (17 markdown + 12 code).

**Cell structure:**

| # | Type | Content |
|---|------|---------|
| 1 | MD | Title, intro, table of contents |
| 2 | MD | Prerequisites (tables, packages, kernel registration) |
| 3 | Code | Setup — sys.path, imports, ta_lab2 version |
| 4 | Code | Parameters: ASSET_ID, TF, START_DATE, END_DATE |
| 5 | MD | Parameters section label |
| 6 | Code | DB connection + validation |
| 7 | MD | Load price bars section |
| 8 | Code | `helpers.load_price_bars()` |
| 9 | MD | What are AMAs? (KAMA, DEMA, TEMA, HMA table) |
| 10 | MD | Compute AMAs section |
| 11 | Code | `compute_ama()` for all 4 types, builds `ama_df` |
| 12 | MD | AMA comparison chart section |
| 13 | Code | Plotly: all AMAs vs close |
| 14 | MD | KAMA ER deep dive section + ER interpretation |
| 15 | Code | Plotly 2-row subplot: close+KAMA and ER area chart |
| 16 | MD | ER reading guide |
| 17 | MD | Regime detection section |
| 18 | Code | `helpers.load_regimes()` with graceful empty fallback |
| 19 | MD | Regime distribution section |
| 20 | Code | Matplotlib regime distribution bar chart |
| 21 | MD | Regime overlay section |
| 22 | Code | `build_regime_vrects()` + Plotly regime-colored chart |
| 23 | MD | Regime overlay reading guide |
| 24 | MD | AMA stats by regime section |
| 25 | Code | AMA deviation from close grouped by l2_label |
| 26 | MD | Multi-TF preview section |
| 27 | Code | Weekly bars + HMA(21) with data sufficiency check |
| 28 | MD | Summary and next steps + useful commands |

## Verification Results

| Check | Result |
|-------|--------|
| `helpers.py` imports cleanly | PASS — `Engine(postgresql+psycopg2://...)` |
| `get_engine()` returns NullPool engine | PASS |
| Notebook is valid JSON | PASS |
| Notebook has 25+ cells | PASS — 29 cells |
| Markdown narrative before major computations | PASS — 17/29 cells are markdown |
| Parameter cell defines ASSET_ID/TF/dates | PASS |
| AMAs computed via `compute_ama()` | PASS — no DB query for AMAs |
| Regime chart uses grouped vrects | PASS — `build_regime_vrects()` function |

## Deviations from Plan

None — plan executed exactly as written.

## Key Design Decisions

1. **NullPool in `get_engine()`** — Matches the Streamlit dashboard pattern established in Phase 39. Avoids connection leak across long-running notebook cells.

2. **AMAs on-the-fly** — The plan explicitly prohibits querying `cmc_ama_multi_tf`. `compute_ama()` is called directly in the notebook, which also demonstrates the library API to readers.

3. **vrect block grouping** — `build_regime_vrects()` converts the per-bar regime series into a list of `{x0, x1, label}` blocks before calling `fig.add_vrect()`. This prevents Plotly from rendering hundreds of individual shapes (performance issue with 1000+ bars).

4. **Graceful fallback on empty regimes** — `HAS_REGIMES` flag set after `load_regimes()` call; all regime-dependent cells check this flag and print actionable messages when no regime data exists.

5. **`display()` for regime stats** — Used as Jupyter built-in for rich table rendering of multi-level column groupby result. `# noqa: F821` suppresses ruff undefined-name warning.

## Next Phase Readiness

Phase 40 Plan 02 (`02_ic_analysis.ipynb`) can proceed immediately:
- `helpers.py` is available with `load_features()`, `load_regimes()`, `style_ic_table()`
- The IC evaluation infrastructure (Phase 37) is already in `ta_lab2.ic.*`
- No blockers
