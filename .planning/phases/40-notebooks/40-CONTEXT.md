# Phase 40: Notebooks - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

3 polished Jupyter notebooks demonstrating the full v0.9.0 research cycle — from AMA exploration through IC evaluation, purged CV demo, feature experimentation, and regime-filtered backtesting. Each notebook passes "Restart and Run All" cleanly, is parameterized, and reads from existing DB tables. A shared helpers module provides common DB/loading functions.

Requirements: NOTE-01, NOTE-02, NOTE-03

Does NOT include creating new pipeline capabilities, modifying existing tables, or building new analytical features. Notebooks are consumers of existing infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Notebook Topics & Structure
- **3 notebooks** following a story arc:
  1. **Explore Indicators** — AMA values (KAMA, DEMA, TEMA, HMA), regime detection, regime-colored price charts
  2. **Evaluate Features** — IC scores, IC decay charts, purged K-fold CV demo, regime A/B backtest walkthrough (full: signal → filter → vectorbt → PnL comparison)
  3. **Run Experiments** — Feature experimentation framework demo + Streamlit dashboard launch cell
- **Shared helpers module** (`notebook_helpers.py` or similar) for DB connection, common data loading, shared styling. Notebooks import from it.
- **Dashboard launch cell**: Final notebook includes a cell that launches the Streamlit dashboard in a subprocess for users who want the interactive version.

### Narrative Style & Audience
- **Audience**: General technical — someone who knows development but not necessarily this codebase or quant concepts. Explain both ta_lab2 patterns and finance concepts (IC, Sharpe, K-fold, etc.).
- **Prose density**: Tutorial-style — ~50/50 markdown/code. Detailed explanations, context for every computation, interpretation of results.
- **Interpretation cells**: Yes — include "what to look for" markdown cells after key outputs (e.g., "An IC above 0.05 is considered meaningful", "Notice the decay flattens after lag 5").
- **Prerequisites section**: Full setup section at top of each notebook listing required tables, CLI commands to refresh them, and expected data state.
- **Table of contents**: Yes — markdown cell with clickable section links at the top of each notebook.

### Data & Parameterization
- **Default asset**: BTC (id=1) as primary, ETH (id=2) mentioned as alternate. Parameter cell has `ASSET_ID = 1` with a comment suggesting `id = 2`.
- **Default timeframe**: 1D as primary, 1W demonstrated as secondary to show multi-TF design.
- **Date range**: Default to fixed dates (e.g., `START_DATE = '2024-01-01'`, `END_DATE = '2025-12-31'`), with a commented-out "latest N bars" alternative in the parameter cell.
- **Missing data handling**: Pre-validate in setup — setup section queries available assets with sufficient history, user picks from validated list. Fail fast with clear message if selected asset lacks data.

### Visual Polish & Output
- **Chart library**: Mixed — Plotly for interactive charts (IC decay, regime overlay, rolling IC) reusing existing helpers; matplotlib/seaborn for static plots (distributions, heatmaps, correlation matrices). Best tool per chart.
- **Output verbosity**: Verbose for learning — keep logs visible so reader can see DB queries, row counts, and what's happening under the hood. Show the machinery.
- **Table styling**: Styled with Pandas Styler for "hero" tables (IC scores, backtest metrics, regime stats) — color gradients, conditional red/green, formatted decimals. Intermediate DataFrames can be plain with `.round()`.
- **Navigation**: Full table of contents cell at top of each notebook with clickable section links.

### Claude's Discretion
- Exact notebook filenames and numbering convention
- Shared helpers module name and location (e.g., `notebooks/helpers.py` vs `src/ta_lab2/notebooks/notebook_helpers.py`)
- Which specific AMA types to highlight in Notebook 1 (all 4 or pick 2-3)
- Exact fixed date range values for parameter defaults
- matplotlib vs seaborn choice for specific static plots
- How much SQLAlchemy/pandas log verbosity to keep vs suppress
- Pandas Styler color palette choices
- How to structure the "pre-validate available assets" logic
- Dashboard subprocess launch pattern (subprocess.Popen vs os.system)

</decisions>

<specifics>
## Specific Ideas

- Reuse Phase 37 Plotly helpers (`plot_ic_decay`, `plot_rolling_ic`) directly — no duplicate chart code
- Reuse Phase 38 feature experimentation framework classes for Notebook 3
- Regime A/B backtest can use existing signal generators with `regime_enabled=True/False` parameter
- `asset_data_coverage` table already tracks per-asset data availability — perfect for pre-validation
- NullPool pattern already standard; shared helpers module should follow same DB connection pattern
- Plotly charts in notebooks need `fig.show()` not `st.plotly_chart()` — different rendering context
- `dim_timeframe` has `tf_days_nominal` for ordering timeframes in selection UIs

</specifics>

<deferred>
## Deferred Ideas

- Interactive notebook widgets (ipywidgets) for parameter selection — adds complexity, parameterized cells are sufficient for v0.9.0
- Notebook-to-HTML export pipeline — useful but not core; Jupyter's built-in export works
- Video walkthrough or animated GIF generation from notebook outputs
- Additional notebooks for v1.0.0 capabilities (paper trading, strategy bake-off) — add when those phases ship

</deferred>

---

*Phase: 40-notebooks*
*Context gathered: 2026-02-24*
