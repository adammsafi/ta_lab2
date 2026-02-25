# Phase 54: V1 Results Memo - Research

**Researched:** 2026-02-25
**Domain:** Document generation — Python-driven Markdown memo + Plotly HTML companion artifacts
**Confidence:** HIGH (all primary findings sourced directly from codebase and locked prior-phase artifacts)

---

## Summary

Phase 54 is a document-generation phase. The deliverable is a formal Markdown memo (`V1_MEMO.md`) with companion Plotly HTML charts and CSV data tables written to `reports/v1_memo/`. All primary data for the memo already exists: backtest results in `reports/bakeoff/` (CSVs + scorecard), policy documents in `reports/loss_limits/` and `reports/tail_risk/`, and DB tables (`cmc_backtest_runs`, `cmc_backtest_metrics`, `cmc_backtest_trades`, `cmc_drift_metrics`, `cmc_risk_events`, `cmc_executor_run_log`). The paper trading data from Phase 53 is the only runtime dependency.

The established generator pattern in this project is: a Python script reads from CSV files and the DB, builds section strings via `_section_*()` helpers, generates Plotly charts with HTML fallback, and writes a self-contained Markdown file with embedded chart links. This is the same pattern used by `generate_bakeoff_scorecard.py` (Phase 42-05) and `generate_tail_risk_policy.py` (Phase 49-04). Phase 54 should follow this exact pattern.

The memo has a dual purpose: (1) be self-contained for a quant-literate reader unfamiliar with the build, and (2) capture the AI-accelerated development narrative as a distinctive artifact. The generator script must handle graceful degradation when paper trading data (Phase 53) is not yet available — all sections sourced from backtest and policy artifacts can be generated immediately; paper vs backtest comparison sections should render placeholder text when DB tables are empty.

**Primary recommendation:** Build one Python generator script (`generate_v1_memo.py`) that writes all sections. Structure it with five major MEMO-XX tasks: (01) methodology, (02) results, (03) failure modes, (04) research track answers, (05) V2 roadmap. Use section-function decomposition matching the bakeoff scorecard pattern. Companion charts are HTML (no kaleido dependency risk).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| plotly.graph_objects | Already installed | Interactive HTML charts | Used across Phases 42, 47, 49, 53 |
| pandas | Already installed | DataFrame ops, CSV loading, metric computation | Project standard |
| sqlalchemy | Already installed | DB queries for paper trading and drift data | Project standard with NullPool pattern |
| pathlib.Path | stdlib | Output directory management | Project standard |
| argparse | stdlib | CLI entry point | Project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| yaml | Already installed | Read `tail_risk_config.yaml` for config facts | MEMO-04 tail risk section |
| json | stdlib | Parse fold_metrics_json from strategy_bakeoff_results | MEMO-02 results section |
| datetime | stdlib | Report timestamp, period formatting | Throughout |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure Python string building | Jinja2 templates | Jinja2 adds dependency; string functions are established project pattern |
| Plotly HTML | PNG via kaleido | kaleido has installation fragility on Windows (seen in scorecard); HTML is the reliable fallback already implemented |
| Jupyter notebook | Static Markdown | Notebook is a Phase 53 deliverable; memo is static self-contained document |

**Installation:** No new packages needed. All required libraries are already project dependencies.

---

## Architecture Patterns

### Recommended Project Structure
```
reports/v1_memo/
├── V1_MEMO.md               # Main memo document
├── charts/                  # Plotly HTML companion charts
│   ├── equity_curve_overlay.html
│   ├── drawdown_comparison.html
│   ├── per_fold_sharpe.html
│   ├── benchmark_comparison.html
│   ├── regime_breakdown.html
│   ├── stress_test_results.html
│   └── build_timeline.html
├── data/                    # CSV data tables (appendix artifacts)
│   ├── backtest_metrics.csv
│   ├── paper_metrics.csv
│   └── research_track_summary.csv
└── appendix/                # Supporting policy docs (symlink or copy)
    └── (references to reports/bakeoff/, reports/tail_risk/, etc.)

src/ta_lab2/scripts/analysis/
└── generate_v1_memo.py      # Single generator script
```

### Pattern 1: Section-Function Decomposition (established project pattern)
**What:** Each logical section of the memo is a `_section_*()` function that returns a markdown string. The `build_memo()` function assembles them. Data loading is separate from rendering.
**When to use:** Always — this is the `generate_bakeoff_scorecard.py` pattern and must be followed for consistency.
**Example:**
```python
# Source: src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py

def _section_methodology(asset_id: int, tf: str) -> str:
    lines = ["## Section 1: Methodology", ""]
    lines.append("### Data Sources")
    # ...
    return "\n".join(lines)

def build_memo(
    output_path: Path,
    generate_charts: bool = True,
    db_url: str | None = None,
    charts_dir: Path = _CHARTS_DIR,
) -> str:
    # Load data
    bakeoff_df = load_bakeoff_results(engine)
    paper_df = load_paper_results(engine)

    # Generate charts
    chart_equity = generate_equity_curve_chart(paper_df, charts_dir=charts_dir)

    # Build sections
    lines = ["# V1 Results Memo", ""]
    lines.append(_section_methodology(...))
    lines.append(_section_results(bakeoff_df, paper_df, chart_equity))
    # ...

    content = "\n".join(lines)
    output_path.write_text(content, encoding="utf-8")
    return content
```

### Pattern 2: Graceful Degradation for Missing Paper Data
**What:** When Phase 53 paper trading data tables are empty, sections that need them render with a clear placeholder rather than crashing. Sections backed entirely by backtest/policy artifacts generate fully.
**When to use:** MEMO-02 (results), any section querying `cmc_executor_run_log`, `cmc_drift_metrics`, `cmc_fills`.
**Example:**
```python
# Source: generate_bakeoff_scorecard.py pattern (DB unavailable fallback)

def load_paper_metrics(engine) -> pd.DataFrame:
    try:
        df = pd.read_sql("SELECT * FROM cmc_executor_run_log ...", engine)
        return df
    except Exception as exc:
        logger.warning("Paper trading data not available: %s", exc)
        return pd.DataFrame()

def _section_results(paper_df: pd.DataFrame, ...) -> str:
    if paper_df.empty:
        return (
            "## Section 2: Results\n\n"
            "_Paper trading data not yet available (Phase 53 in progress)._\n"
            "_Backtest results shown below; paper comparison will be populated after validation._\n\n"
        )
    # ... full section
```

### Pattern 3: Chart with HTML Fallback
**What:** Try PNG via kaleido; fall back to HTML on any exception. Always return relative path string.
**When to use:** All chart generation functions.
**Example:**
```python
# Source: src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py _save_chart()

def _save_chart(fig: go.Figure, filename: str, charts_dir: Path) -> str:
    charts_dir.mkdir(parents=True, exist_ok=True)
    try:
        png_path = charts_dir / f"{filename}.png"
        fig.write_image(str(png_path), width=900, height=450, scale=1.5)
        return f"charts/{filename}.png"
    except Exception:
        html_path = charts_dir / f"{filename}.html"
        fig.write_html(str(html_path))
        return f"charts/{filename}.html"
```

### Pattern 4: Markdown Table Helpers
**What:** `_format_table_row()` and `_format_table()` helpers produce GitHub-flavored Markdown tables.
**When to use:** All tabular data in memo sections.
**Example:**
```python
# Source: generate_bakeoff_scorecard.py

def _format_table(headers: list[str], rows: list[list]) -> str:
    lines = [
        "| " + " | ".join(str(v) for v in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)
```

### Anti-Patterns to Avoid
- **Hardcoding paper trading results:** Paper data must be read from DB at runtime. Phase 53 may not be complete when Phase 54 starts; the generator must work with partial data.
- **Single monolithic render function:** The scorecard pattern uses `_section_*()` functions. One giant `build_memo()` becomes unmaintainable for a document this large.
- **Skipping UTF-8 encoding on file writes:** Critical on Windows — MEMORY.md explicitly documents this pitfall. Always `open(path, "w", encoding="utf-8")` or `path.write_text(content, encoding="utf-8")`.
- **Encoding issues in SQL files:** If any SQL is needed, use `encoding='utf-8'` when opening (MEMORY.md pitfall).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown tables | Custom loop | `_format_table()` helper (copy from scorecard) | Already validated, handles edge cases |
| Chart saving with fallback | New logic | `_save_chart()` helper (copy from scorecard) | kaleido failure mode already handled |
| DB connection with NullPool | New pattern | `_get_engine()` helper (copy from any existing script) | NullPool required for scripts to avoid connection leaks |
| IC ranking data | Re-query DB | Load `reports/bakeoff/feature_ic_ranking.csv` directly | CSV already exists, no re-computation needed |
| Bakeoff walk-forward results | Re-compute | Load `reports/bakeoff/composite_scores.csv` + `sensitivity_analysis.csv` + `final_validation.csv` | CSVs are the canonical artifacts from Phase 42 |
| Tail risk policy facts | Re-derive | Read `reports/tail_risk/TAIL_RISK_POLICY.md` or `tail_risk_config.yaml` | Policy document is the source of truth |
| Loss limits policy facts | Re-derive | Read `reports/loss_limits/*.md` | Policy documents are the source of truth |

**Key insight:** The memo is an assembly document. All underlying data already exists in CSVs, policy Markdown files, and DB tables. The generator's job is to assemble and narrate, not to recompute.

---

## Common Pitfalls

### Pitfall 1: Plan Dependency on Phase 53 Completion
**What goes wrong:** Phase 54 plans assume paper trading data is available. If Phase 53 runs concurrently or finishes late, the generator crashes on empty tables.
**Why it happens:** Linear thinking about document generation vs actual execution order.
**How to avoid:** Every DB query that touches paper trading tables (`cmc_fills`, `cmc_positions`, `cmc_executor_run_log`, `cmc_drift_metrics`) must wrap in try/except with DataFrame empty return. Generator should be runnable with `--backtest-only` flag that skips all Phase 53 data sections.
**Warning signs:** Any DB query without a fallback empty DataFrame return.

### Pitfall 2: UTF-8 Encoding on Windows
**What goes wrong:** `UnicodeDecodeError` when reading SQL files or Markdown files that contain box-drawing characters (═══) or other UTF-8 characters outside cp1252.
**Why it happens:** Windows default encoding is cp1252, not UTF-8.
**How to avoid:** All file operations use `encoding="utf-8"` explicitly. This is documented in MEMORY.md as a known pitfall.
**Warning signs:** Any `open()` call without explicit encoding parameter.

### Pitfall 3: Build Timeline Accuracy
**What goes wrong:** Hardcoding milestone stats that are slightly wrong (e.g., claiming 242 plans when actual count at memo time may be 250+).
**Why it happens:** The context says "250+ plans" but milestone docs show earlier counts.
**How to avoid:** The plan count, execution time, and timeline data should be read from `.planning/MILESTONES.md` or computed from git log stats at generation time. Alternatively, make these constants with a clear comment that they must be verified before generation.
**Warning signs:** Any hardcoded "242 plans" or "28 hours" without a data source.

### Pitfall 4: Overly Ambitious Chart Scope
**What goes wrong:** Planning 10+ charts, building complex multi-asset equity curve overlays, then discovering the underlying data (paper equity curve per asset) isn't stored at the granularity needed.
**Why it happens:** The context mentions "overlaid equity curve charts" but `cmc_drift_metrics` stores cumulative P&L per config_id, not per asset independently.
**How to avoid:** Match charts to what the Phase 53 data model actually provides. `cmc_drift_metrics` has: `paper_cumulative_pnl`, `replay_cumulative_pnl`, `tracking_error_5d`, `tracking_error_30d`. Equity curve overlay is strategy-level, not asset-level breakdown. Per-asset breakdown requires `cmc_fills` + `cmc_positions` aggregation.
**Warning signs:** Charting designs that assume data granularity not verified against actual table schemas.

### Pitfall 5: Research Track Section Scope
**What goes wrong:** MEMO-04 requires covering all 6 research tracks. Some tracks (Phase 50 data economics, Phase 51 perps readiness) may be in-progress or plan-complete but not yet fully executed.
**Why it happens:** Phase 54 context notes "Phase 50 and Phase 51 may or may not be complete by Phase 54."
**How to avoid:** Each research track section reads from its canonical policy/output document if available, or from the phase context document if not. Design the section generator to accept a `status` parameter: `complete` (full analysis), `plan_complete` (findings documented, execution partial), `in_progress` (known scope, findings TBD).
**Warning signs:** Hard dependency on Phase 50 or Phase 51 DB output in MEMO-04.

### Pitfall 6: V2 Roadmap Without Phase Numbering
**What goes wrong:** MEMO-05 V2 roadmap says "detailed enough to seed phase numbering" but Phase 55 is already in v1.0.0 roadmap. V2 phases start at 56+ (or a new milestone).
**Why it happens:** Confusion about which phases are v1.0.0 vs v2.0.0.
**How to avoid:** V2 roadmap should reference the v1.0.0 milestone as complete and propose v2.0.0 milestone with new phase numbering starting at Phase 56 (or Phase 1 of a new roadmap section). The roadmap should be grounded in evidence from the 6 research track findings.
**Warning signs:** V2 roadmap that proposes phases already claimed by v1.0.0 or Phase 55.

---

## Code Examples

### DB Query Pattern for Paper Metrics
```python
# Source: Phase 53-04-PLAN.md (ValidationReportBuilder pattern)

def load_paper_metrics(engine, start_date, end_date) -> pd.DataFrame:
    """Load paper trading P&L from drift metrics table."""
    try:
        query = text("""
            SELECT
                metric_date,
                config_id,
                paper_cumulative_pnl,
                replay_cumulative_pnl,
                pnl_diff,
                tracking_error_5d,
                tracking_error_30d
            FROM cmc_drift_metrics
            WHERE metric_date BETWEEN :start AND :end
            ORDER BY metric_date, config_id
        """)
        return pd.read_sql(query, engine, params={"start": start_date, "end": end_date})
    except Exception as exc:
        logger.warning("Paper metrics not available: %s", exc)
        return pd.DataFrame()
```

### Loading Bakeoff CSV Data
```python
# Source: generate_bakeoff_scorecard.py load_* functions

_REPORTS_BAKEOFF = _PROJECT_ROOT / "reports" / "bakeoff"
_IC_RANKING_CSV = _REPORTS_BAKEOFF / "feature_ic_ranking.csv"
_COMPOSITE_CSV = _REPORTS_BAKEOFF / "composite_scores.csv"
_SENSITIVITY_CSV = _REPORTS_BAKEOFF / "sensitivity_analysis.csv"
_FINAL_VALIDATION_CSV = _REPORTS_BAKEOFF / "final_validation.csv"

def load_bakeoff_artifacts() -> dict:
    """Load all Phase 42 bakeoff CSVs."""
    return {
        "ic": pd.read_csv(_IC_RANKING_CSV) if _IC_RANKING_CSV.exists() else pd.DataFrame(),
        "composite": pd.read_csv(_COMPOSITE_CSV) if _COMPOSITE_CSV.exists() else pd.DataFrame(),
        "sensitivity": pd.read_csv(_SENSITIVITY_CSV) if _SENSITIVITY_CSV.exists() else pd.DataFrame(),
        "final_validation": pd.read_csv(_FINAL_VALIDATION_CSV) if _FINAL_VALIDATION_CSV.exists() else pd.DataFrame(),
    }
```

### Equity Curve Overlay Chart
```python
# Source: Phase 53-04-PLAN.md ValidationReportBuilder _build_equity_curve pattern

def generate_equity_curve_chart(
    paper_df: pd.DataFrame,  # from cmc_drift_metrics
    charts_dir: Path,
) -> str:
    """Overlay paper P&L vs replay P&L per strategy config."""
    if paper_df.empty:
        return ""

    fig = go.Figure()
    for config_id, grp in paper_df.groupby("config_id"):
        fig.add_trace(go.Scatter(
            x=grp["metric_date"],
            y=grp["paper_cumulative_pnl"],
            name=f"Paper (config {config_id})",
            mode="lines",
            line=dict(width=2),
        ))
        fig.add_trace(go.Scatter(
            x=grp["metric_date"],
            y=grp["replay_cumulative_pnl"],
            name=f"Backtest Replay (config {config_id})",
            mode="lines",
            line=dict(width=2, dash="dash"),
        ))

    fig.update_layout(
        title="Paper Trading vs Backtest Replay: Cumulative P&L",
        xaxis_title="Date",
        yaxis_title="Cumulative P&L (USD)",
        template="plotly_white",
        height=450,
    )
    return _save_chart(fig, "equity_curve_overlay", charts_dir)
```

### Benchmark Comparison for MEMO-02
```python
# Benchmark data: buy-and-hold BTC/ETH + 50/50 index from cmc_price_bars_multi_tf_u

def load_benchmark_returns(engine, start_date, end_date) -> pd.DataFrame:
    """Load BTC/ETH daily returns for benchmark computation."""
    try:
        query = text("""
            SELECT p.id, "timestamp" AS ts, p.close
            FROM cmc_price_bars_multi_tf_u p
            WHERE p.tf = '1D'
              AND p.id IN (1, 2)  -- BTC=1, ETH=2
              AND "timestamp" BETWEEN :start AND :end
            ORDER BY p.id, "timestamp"
        """)
        return pd.read_sql(query, engine, params={"start": start_date, "end": end_date})
    except Exception as exc:
        logger.warning("Benchmark data not available: %s", exc)
        return pd.DataFrame()
```

### Section Function Template for Build Timeline
```python
def _section_build_narrative(milestone_data: dict) -> str:
    """
    Build narrative section: AI-accelerated development story.
    milestone_data: loaded from .planning/MILESTONES.md or hardcoded constants
    verified against actual data.
    """
    lines = ["## Build Narrative", ""]
    lines.append(
        "This platform was built using an AI-accelerated development workflow "
        "(GSD: Get Shit Done), coordinating Claude as a planning and execution engine "
        "across 250+ individual task plans spanning 7 milestones."
    )
    lines.append("")
    lines.append("### Milestone Timeline")
    lines.append("")
    # Hardcoded from MILESTONES.md (verified 2026-02-25)
    milestones = [
        ["v0.4.0", "2026-02-01", "10 phases, 56 plans", "Memory infra, orchestrator, ta_lab2 foundation"],
        ["v0.5.0", "2026-02-04", "9 phases, 56 plans", "Ecosystem reorganization"],
        ["v0.6.0", "2026-02-17", "7 phases, 30 plans", "EMA/bars architecture"],
        ["v0.7.0", "2026-02-20", "2 phases, 10 plans", "Regime integration"],
        ["v0.8.0", "2026-02-23", "6 phases, 13 plans", "Code quality, runbooks"],
        ["v0.9.0", "2026-02-24", "8 phases, 38 plans", "IC/PSR/CV, AMA, experiments"],
        ["v1.0.0", "TBD",        "14 phases, ~55 plans", "V1 paper trading & validation"],
    ]
    lines.append(_format_table(
        ["Milestone", "Shipped", "Phases / Plans", "Key Deliverables"],
        milestones
    ))
    return "\n".join(lines)
```

---

## Data Sources Inventory

### Available Now (High Confidence — Already Generated)

| Source | Location | What It Provides | Section |
|--------|----------|-----------------|---------|
| `feature_ic_ranking.csv` | `reports/bakeoff/` | IC-IR for 97 features | MEMO-01 methodology, MEMO-04 track 1 |
| `composite_scores.csv` | `reports/bakeoff/` | 4-scheme rankings for 10 strategies | MEMO-01 methodology |
| `sensitivity_analysis.csv` | `reports/bakeoff/` | Cross-scheme robustness | MEMO-02 results |
| `final_validation.csv` | `reports/bakeoff/` | Full-sample backtest validation | MEMO-02 results |
| `BAKEOFF_SCORECARD.md` | `reports/bakeoff/` | Complete Phase 42 artifact | Reference |
| `STRATEGY_SELECTION.md` | `reports/bakeoff/` | Strategy selection rationale | MEMO-01, MEMO-03 |
| `STOP_SIMULATION_REPORT.md` | `reports/loss_limits/` | Intraday stop analysis | MEMO-03, MEMO-04 track 2 |
| `VAR_REPORT.md` | `reports/loss_limits/` | VaR simulation results | MEMO-03, MEMO-04 track 2 |
| `POOL_CAPS.md` | `reports/loss_limits/` | Pool-level cap definitions | MEMO-04 track 2 |
| `OVERRIDE_POLICY.md` | `reports/loss_limits/` | Override governance rules | MEMO-04 track 2 |
| `TAIL_RISK_POLICY.md` | `reports/tail_risk/` | Flatten triggers, escalation | MEMO-04 track 3 |
| `SIZING_COMPARISON.md` | `reports/tail_risk/` | Vol-sizing vs hard stops | MEMO-04 track 3 |
| `tail_risk_config.yaml` | `reports/tail_risk/` | Machine-readable thresholds | MEMO-04 track 3 |
| `strategy_bakeoff_results` (DB) | PostgreSQL | Walk-forward fold detail | MEMO-02 backtest results |
| `cmc_backtest_runs` (DB) | PostgreSQL | Backtest run metadata | MEMO-02 backtest results |
| `cmc_backtest_metrics` (DB) | PostgreSQL | Full metrics per run | MEMO-02 backtest results |
| `cmc_backtest_trades` (DB) | PostgreSQL | Trade-level detail | MEMO-02 trade stats |
| `cmc_ic_results` (DB) | PostgreSQL | IC evaluation results | MEMO-04 track 1 |
| `.planning/MILESTONES.md` | `.planning/` | Milestone dates and plan counts | Build narrative |

### Requires Phase 53 Completion (Runtime Data)

| Source | Location | What It Provides | Section |
|--------|----------|-----------------|---------|
| `cmc_executor_run_log` (DB) | PostgreSQL | Daily paper execution log | MEMO-02 paper results |
| `cmc_drift_metrics` (DB) | PostgreSQL | Paper vs backtest drift | MEMO-02 paper results, MEMO-04 track 4 |
| `cmc_fills` (DB) | PostgreSQL | Trade-level paper fills | MEMO-02 paper trade stats |
| `cmc_positions` (DB) | PostgreSQL | Position history | MEMO-02 paper exposure |
| `cmc_risk_events` (DB) | PostgreSQL | Kill switch + circuit breaker events | MEMO-03 failure modes |
| `reports/validation/V1_VALIDATION_REPORT.md` | `reports/validation/` | Phase 53 end-of-period report | Reference, MEMO-02 |

### May Require Phase 50/51 Completion (Research Track Data)

| Source | Location | What It Provides | Section |
|--------|----------|-----------------|---------|
| `reports/data-economics/` | `reports/` | Build-vs-buy analysis | MEMO-04 track 5 |
| `cmc_funding_rates` (DB) | PostgreSQL | Perps funding rate data | MEMO-04 track 6 |
| Phase 50/51 policy docs | `reports/` or `docs/` | Architecture decision records | MEMO-04 tracks 5-6 |

---

## Memo Document Architecture

Based on the CONTEXT.md decisions, the memo requires these top-level sections in order:

```
# V1 Results Memo
## Executive Summary (Claude's discretion: yes — given full narrative arc)
## 1. Build Narrative (milestone timeline, AI-accelerated story, key decisions)
## 2. Methodology (MEMO-01)
   ### Data Sources (CMC API, BTC/ETH spot, 2010-2025)
   ### Strategy Descriptions (ema_trend 17/77 and 21/50)
   ### Parameter Selection Process (IC sweep → walk-forward bake-off → composite scoring)
   ### Fee and Slippage Assumptions (16 bps maker + 10 bps slippage baseline; 12-scenario matrix)
## 3. Results (MEMO-02)
   ### Backtest Results (strategy-level: Sharpe, MaxDD, MAR, win rate, turnover)
   ### Per-Asset Breakdown (BTC, ETH if available)
   ### Per-Regime Breakdown (bull/bear/sideways)
   ### Benchmark Comparison (buy-hold BTC, buy-hold ETH, 50/50, risk-free)
   ### Paper Trading Results (Phase 53 data — graceful degradation if incomplete)
   ### Backtest vs Paper Comparison (overlaid charts + side-by-side tables)
   ### Trade-Level Statistics (win rate, avg winner/loser, max consecutive losses, holding period)
## 4. Failure Modes (MEMO-03)
   ### MaxDD Gate Failure (root cause analysis: what failed, why, what we tried)
   ### Ensemble Blend Failure (why majority-vote didn't solve drawdown)
   ### Stress Tests (2018 crash, 2022 bear, COVID + synthetic scenarios)
   ### Drift Analysis (depth based on actual Phase 53 drift severity)
   ### Risk Events (circuit breaker triggers, kill switch exercises)
## 5. Research Track Answers (MEMO-04)
   ### Track 1: Core Edge Selection (IC findings, walk-forward, strategy selection)
   ### Track 2: Loss Limits & Kill-Switch Policy (VaR, stop simulation, pool caps)
   ### Track 3: Tail-Risk Policy (vol-sizing vs hard stops, flatten triggers)
   ### Track 4: Live/Backtest Drift Guard (drift metrics, auto-pause, attribution)
   ### Track 5: Data Economics (build-vs-buy, trigger definition)
   ### Track 6: Perps Readiness (funding rates, margin model, venue playbook)
## 6. Key Takeaways (consolidated lessons learned summary box)
## 7. V2 Roadmap (MEMO-05)
   ### V2 Priorities (grounded in V1 findings)
   ### Go/No-Go Triggers (quantitative where V1 supports them)
   ### Effort Estimates (phase counts + duration ranges from V1 velocity data)
## Appendix A: Methodology Detail
## Appendix B: Data Sources and Schema
## Appendix C: Glossary
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single equity curve per strategy | Overlaid equity curves with benchmark comparison | Phase 54 decision | Reader can immediately compare strategies vs buy-hold |
| One-paragraph research track summaries (MEMO-04 original requirement) | Full subsection per track with methodology, findings, remaining questions | CONTEXT.md decision | Substantially more material per track — plan for ~1-2 pages per track |
| Binary PASS/FAIL gate reporting | PASS/CONDITIONAL/FAIL (3-tier, from Phase 53 research) | Phase 53 CONTEXT.md | MaxDD gate failure is CONDITIONAL (known mitigation in place) not hard FAIL |
| V2 wish list | Evidence-grounded V2 roadmap with effort estimates | CONTEXT.md decision | Requires synthesizing findings from all 6 tracks before writing |

---

## Open Questions

1. **Phase 53 completion state at planning time**
   - What we know: Phase 53 plans are written and implemented (53-01 through 53-04 all have PLAN.md files). Whether 14-day validation has actually run is unknown from the planning materials.
   - What's unclear: Will Phase 54 plans execute while Phase 53 paper trading is still running, or after it completes?
   - Recommendation: Plans must design for both scenarios. The generator script must produce a valid (partial) memo from backtest data alone.

2. **Phase 50/51 completion state**
   - What we know: Both have CONTEXT.md and RESEARCH.md and multiple PLAN.md files. Phase 50 has 2 plans, Phase 51 has 5 plans.
   - What's unclear: Whether output reports/data have been generated.
   - Recommendation: MEMO-04 Track 5 and Track 6 plans should read from the phase CONTEXT.md scope descriptions as a fallback if the actual output documents don't exist yet. The generator should look for `reports/data-economics/` and `reports/perps-readiness/` (or similar) and fall back to synthesizing from CONTEXT.md.

3. **Stress test data availability**
   - What we know: Historical crash dates are known (2018, 2022, COVID March 2020). BTC price data exists in `cmc_price_bars_multi_tf_u` back to 2010. Stop simulation and VaR reports exist in `reports/loss_limits/`.
   - What's unclear: Whether Phase 48's STOP_SIMULATION_REPORT.md includes per-crash-event backtest results or only aggregate stats.
   - Recommendation: Stress test section in MEMO-03 can be computed on-the-fly from price data + strategy signals for the known crash dates. This is a DB query against existing backtest infrastructure.

4. **Exact plan count for build timeline**
   - What we know: MILESTONES.md shows 203 plans through v0.9.0 (56+56+30+10+13+38). Phase 54 context says 250+ plans total. The exact current count is between these bounds.
   - What's unclear: The v1.0.0 plan count is not finalized (phases 42-54 are still executing).
   - Recommendation: Compute plan count from git log or from counting PLAN.md files at generation time. Do not hardcode.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py` — definitive generator pattern, all helpers
- `src/ta_lab2/scripts/analysis/generate_tail_risk_policy.py` — secondary generator pattern
- `src/ta_lab2/drift/drift_report.py` — `_df_to_markdown()` and `_save_chart()` helpers
- `reports/bakeoff/BAKEOFF_SCORECARD.md` — complete Phase 42 data, verified artifacts
- `reports/bakeoff/STRATEGY_SELECTION.md` — strategy selection rationale and deployment config
- `reports/tail_risk/TAIL_RISK_POLICY.md` — Phase 49 policy document, all calibration data
- `.planning/milestones/v1.0.0-REQUIREMENTS.md` — MEMO-01 through MEMO-05 specifications
- `.planning/milestones/v1.0.0-ROADMAP.md` — phase dependencies and execution order
- `.planning/MILESTONES.md` — milestone dates, plan counts, velocity data
- `.planning/phases/54-v1-results-memo/54-CONTEXT.md` — locked decisions for this phase
- `.planning/phases/53-v1-validation/53-CONTEXT.md` — Phase 53 scope, data produced
- `.planning/phases/53-v1-validation/53-04-PLAN.md` — ValidationReportBuilder chart patterns

### Secondary (MEDIUM confidence)
- `.planning/phases/46-risk-controls/46-CONTEXT.md` — risk controls scope (DB tables available)
- `.planning/phases/47-drift-guard/47-CONTEXT.md` — drift guard data model (cmc_drift_metrics)
- `.planning/phases/48-loss-limits-policy/48-CONTEXT.md` — loss limits policy outputs
- `.planning/phases/50-data-economics/50-CONTEXT.md` — data economics scope and outputs
- `.planning/phases/51-perps-readiness/51-CONTEXT.md` — perps readiness scope and outputs

### Tertiary (LOW confidence — based on plan structure only, execution not verified)
- Phase 50/51 output report existence: plans are written, execution state unknown

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project, no new dependencies
- Architecture patterns: HIGH — directly extracted from `generate_bakeoff_scorecard.py` and `generate_tail_risk_policy.py` which are the canonical patterns
- Data sources: HIGH for Phase 42/48/49 artifacts (verified to exist in filesystem), MEDIUM for Phase 53 (plans exist, execution state unknown), LOW for Phase 50/51 outputs
- Pitfalls: HIGH — sourced from MEMORY.md documented issues and actual codebase inspection
- Memo content: HIGH for backtest-backed sections (all data available), MEDIUM for paper comparison sections (depends on Phase 53 completion)

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable domain — document generation pattern doesn't change; data sources are locked artifacts)
