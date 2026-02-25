# Phase 55: Feature & Signal Evaluation - Research

**Researched:** 2026-02-25
**Domain:** IC evaluation execution, feature registry expansion, adaptive RSI A/B, evaluation reporting
**Confidence:** HIGH — all findings sourced directly from codebase inspection

---

## Summary

Phase 55 closes the "evaluation gap" by running the already-built IC and experimentation
infrastructure on real data at full scope. The key insight from this research is that all
the required machinery already exists and has been exercised in Phase 42 — this phase is
primarily about expanding scope (all assets x all TFs instead of 5 TFs), expanding the
YAML registry (5 features to ~130+), running the adaptive RSI A/B comparison, and
producing formal evaluation artifacts.

The primary script is `run_ic_sweep.py` which already handles both cmc_features and AMA
table sources, accepts `--all` / `--assets` / `--tf` / `--regime` flags, and writes to
`cmc_ic_results` with upsert semantics. The `run_experiment.py` script drives the YAML
registry through `ExperimentRunner`, which persists to `cmc_feature_experiments`. Both
tables are what the dashboard and promoter pipeline read from.

The adaptive RSI variant already exists: `generate_signals_rsi.py` has `use_adaptive=True`
which computes per-asset rolling percentile thresholds (20th/80th by default over a 100-bar
window). The A/B comparison requires running IC eval on static vs. adaptive RSI signal
outputs, plus backtest Sharpe via `run_bakeoff.py`.

**Primary recommendation:** Structure the phase as: (1) methodology verification against
Phase 42 sample, (2) full IC sweep all assets x all 109 TFs with `--regime`, (3) AMA sweep
once cmc_ama_multi_tf_u is populated, (4) YAML registry expansion to ~130 features,
(5) ExperimentRunner sweep for all YAML features, (6) adaptive RSI A/B, (7) lifecycle
decisions + report generation.

---

## Standard Stack

### Core Scripts (already exist)

| Script | Module Path | Purpose |
|--------|-------------|---------|
| `run_ic_sweep.py` | `ta_lab2.scripts.analysis.run_ic_sweep` | Batch IC sweep: cmc_features + AMA across all assets x TFs |
| `run_ic_eval.py` | `ta_lab2.scripts.analysis.run_ic_eval` | Single-asset IC eval with `--all-features` or named features |
| `run_experiment.py` | `ta_lab2.scripts.experiments.run_experiment` | YAML registry experiment runner; writes to cmc_feature_experiments |
| `run_bakeoff.py` | `ta_lab2.scripts.backtests.run_bakeoff` | Walk-forward backtest with purged K-fold for Sharpe eval |
| `generate_bakeoff_scorecard.py` | `ta_lab2.scripts.analysis.generate_bakeoff_scorecard` | Markdown scorecard from CSV/DB data |

### Core Libraries (already exist)

| Library | Module Path | Purpose |
|---------|-------------|---------|
| `ic.py` | `ta_lab2.analysis.ic` | `compute_ic`, `batch_compute_ic`, `compute_ic_by_regime`, `save_ic_results`, `load_regimes_for_asset` |
| `runner.py` | `ta_lab2.experiments.runner` | `ExperimentRunner` — inline/dotpath compute, BH correction, scratch table |
| `registry.py` | `ta_lab2.experiments.registry` | `FeatureRegistry` — YAML load/validate/expand param sweeps |
| `promoter.py` | `ta_lab2.experiments.promoter` | `FeaturePromoter` — BH gate, dim_feature_registry write, migration stub |
| `ama_params.py` | `ta_lab2.features.ama.ama_params` | `ALL_AMA_PARAMS`, `AMAParamSet`, `compute_params_hash` |

### Supporting Libraries (already exist)

| Library | Purpose |
|---------|---------|
| `generate_signals_rsi.py` | `compute_adaptive_thresholds()`, `RSISignalGenerator(use_adaptive=True)` |
| `bakeoff_orchestrator.py` | `BakeoffOrchestrator`, `BakeoffConfig`, purged K-fold walk-forward |

**Installation:** No new libraries needed. All dependencies already in pyproject.toml.

---

## Architecture Patterns

### IC Sweep Invocation

```bash
# Full sweep: all assets x all TFs x all cmc_features columns + AMA
python -m ta_lab2.scripts.analysis.run_ic_sweep --all --regime

# Targeted: verification against Phase 42 sample
python -m ta_lab2.scripts.analysis.run_ic_sweep --assets 1 1027 --tf 1D --regime

# Dry run to count qualifying pairs
python -m ta_lab2.scripts.analysis.run_ic_sweep --dry-run --min-bars 500

# Skip AMA if cmc_ama_multi_tf_u is not yet populated
python -m ta_lab2.scripts.analysis.run_ic_sweep --all --regime --skip-ama
```

### ExperimentRunner Invocation

```bash
# Run all experimental features from YAML
python -m ta_lab2.scripts.experiments.run_experiment --all-experimental \
    --train-start 2018-01-01 --train-end 2025-12-31 --yes

# Run single feature dry-run
python -m ta_lab2.scripts.experiments.run_experiment \
    --feature kama_er_signal --train-start 2018-01-01 --train-end 2025-12-31 --dry-run
```

### YAML Feature Registry Format

```yaml
features:
  feature_name:
    lifecycle: experimental          # experimental | promoted | deprecated
    description: "human readable"
    compute:
      mode: inline                   # or dotpath
      expression: "col_a / col_b"    # pandas expression; {param} placeholders for sweep
    params:                          # optional param sweep
      period: [5, 14, 21]            # expands to feature_name_period5/14/21
    inputs:
      - table: cmc_features          # must be in _ALLOWED_TABLES allowlist
        columns: [col_a, col_b]
        filters:                     # optional: for AMA table queries
          indicator: kama
          params_hash: d47fe5cc      # 8-char prefix of MD5 hash
    tags: [momentum, rsi]
```

The naming convention for param sweep variants is `{base}_{key}{val}` — e.g., `ret_vol_ratio_period5`.
The `_ALLOWED_TABLES` allowlist in `runner.py` currently includes 17 tables:
- All price bars, bar returns, EMA, EMA returns, AMA, AMA returns multi-TF tables
- `cmc_vol`, `cmc_ta_daily`, `cmc_features`, `cmc_regimes`

Tables WITHOUT `tf` column (filtered by `id + ts` only): `cmc_vol`, `cmc_ta_daily`.

### AMA Table Structure

From `ama_params.py`, the canonical parameter sets and their params_hash values:

**KAMA (3 variants):**
- `KAMA(10,2,30)` — er_period=10, fast_period=2, slow_period=30 — hash: `d47fe5cc...`
- `KAMA(5,2,15)` — er_period=5, fast_period=2, slow_period=15
- `KAMA(20,2,50)` — er_period=20, fast_period=2, slow_period=50

**DEMA, TEMA, HMA (5 variants each):** periods 9, 10, 21, 50, 200

AMA evaluatable columns from `cmc_ama_multi_tf_u`: `ama`, `d1`, `d2`, `d1_roll`, `d2_roll`, `er`
(where `er` is KAMA-only; null for DEMA/TEMA/HMA — the sweep skips all-null columns).
The IC sweep disambiguates via prefix: `{indicator}_{params_hash[:8]}_{col}`.

Filter in queries: `alignment_source = 'multi_tf'` and `roll = FALSE`.

### Adaptive RSI Investigation

"Adaptive RSI" in this codebase means **rolling percentile-based thresholds** on the
standard `rsi_14` column from `cmc_features`. It is NOT a different RSI calculation.

Location: `generate_signals_rsi.py`, function `compute_adaptive_thresholds()`:
```python
lower = rsi.rolling(window=lookback, min_periods=1).quantile(lower_pct / 100.0)
upper = rsi.rolling(window=lookback, min_periods=1).quantile(upper_pct / 100.0)
```
Default parameters: `lookback=100`, `lower_pct=20.0`, `upper_pct=80.0`.

**Critical gap found:** The current `use_adaptive=True` path in `generate_for_ids()` computes
per-asset thresholds but then falls back to global average thresholds (line 416-417) due to
`make_signals` not supporting per-row dynamic thresholds. There is a comment:
```
# Note: make_signals doesn't support dynamic thresholds per row
# For now, we use average adaptive thresholds as static override
# Future enhancement: modify make_signals to accept threshold series
```
The A/B comparison for Phase 55 should use the **global average** adaptive threshold path
(the one that currently works), not per-row thresholds. Alternatively, define adaptive RSI
as a YAML feature using `cmc_ta_daily` or `cmc_features` input with an inline rolling
percentile expression.

For IC comparison, the simplest approach is:
- Static RSI: already in cmc_ic_results as `rsi_14` (IC computed in Phase 42)
- Adaptive RSI: define as YAML experimental feature with inline expression
  `(rsi_14 - rsi_14.rolling(100).quantile(0.20)) / (rsi_14.rolling(100).quantile(0.80) - rsi_14.rolling(100).quantile(0.20) + 1e-10)` sourced from `cmc_ta_daily`

For backtest Sharpe comparison, use `run_bakeoff.py` with static params vs adaptive params.

### Regime Breakdown Scope

Current code in `run_ic_sweep.py`:
```python
_REGIME_ASSET_IDS = frozenset([1, 1027])  # BTC and ETH
_REGIME_TF = "1D"
```
Regime breakdown only runs for BTC (id=1) and ETH (id=1027) on 1D TF. Per CONTEXT.md, the
full breakdown should run for ALL features. This is already what the current `--regime` flag
does — it runs both `trend_state` and `vol_state` breakdown for every feature column when
`asset_id in _REGIME_ASSET_IDS and tf == _REGIME_TF`. No code change needed.

### Phase 42 IC Results: What Exists

From `42-01-SUMMARY.md` and `reports/bakeoff/feature_ic_ranking.csv`:
- **47,614 IC rows** in `cmc_ic_results`
- **Scope:** 17 assets x 5 TFs (1D, 7D, 14D, 30D, 90D) x 97 feature columns
- **Duration:** 26 minutes (01:37 to 02:03 UTC)
- **Regime rows:** BTC + ETH 1D, trend_state and vol_state breakdowns
- **AMA rows:** 0 (cmc_ama_multi_tf_u not populated at time of Phase 42)
- **feature_ic_ranking.csv:** 97 features, already in `reports/bakeoff/`

**Methodology verification strategy:** Recompute IC for BTC 1D with a sample of 3-5
features (e.g., `rsi_14`, `ret_arith`, `bb_ma_20`) using `run_ic_eval.py --dry-run` and
compare to existing `cmc_ic_results` rows. If IC values match to 6+ decimal places, the
methodology is identical and existing rows are valid. If different, log a discrepancy
warning before proceeding.

### Dashboard Data Requirements

**Research Explorer (page 3):**
- Reads from `cmc_ic_results` via `load_ic_results(engine, asset_id, tf)`
- Shows IC decay chart, rolling IC chart, regime analysis
- Requires: rows in `cmc_ic_results` for selected (asset_id, tf)
- Currently shows "No IC features found" for any asset/TF combination not in Phase 42 scope

**Experiments (page 5):**
- Reads from `cmc_feature_experiments` via `load_experiment_summary()` and `load_experiment_results()`
- Shows summary table (feature_name, n_experiments, n_significant, mean_abs_ic)
- Requires: rows in `cmc_feature_experiments`
- Currently shows "No experiment results found" (table empty — Phase 38 infra built but never run)

To show non-empty results, Phase 55 must:
1. For Research Explorer: extend IC sweep to cover more TFs (or use existing 1D results — already present)
2. For Experiments: run `run_experiment.py` for at least some YAML features with `--yes`

### Walk-Forward Backtest for RSI A/B

`run_bakeoff.py` CLI uses `BakeoffOrchestrator` which runs purged K-fold (10 folds, 20-bar
embargo) via `PurgedKFoldSplitter`. The bakeoff param grid for `rsi_mean_revert` includes 3
static threshold configs:
- lower=30/upper=70, lower=25/upper=65, lower=35/upper=75

To add adaptive RSI as a 4th config for A/B comparison:
```python
{
    "rsi_col": "rsi_14",
    "lower": <adaptive_mean_lower>,
    "upper": <adaptive_mean_upper>,
    "use_adaptive": True,  # flag to trigger adaptive path
    ...
}
```
However, `run_bakeoff.py` does not currently pass `use_adaptive` to `RSISignalGenerator`.
A new bakeoff config or a thin wrapper script would be needed to compare static vs. adaptive.

Alternatively, compute adaptive average thresholds on BTC 1D historical data, then include
them as a static entry in the bakeoff grid — this avoids modifying the orchestrator.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IC computation | Custom Spearman correlator | `batch_compute_ic()` in `ic.py` | Already handles boundary masking, rolling IC, IC-IR, t-stats, boundary leakage prevention |
| BH correction | Custom p-value adjustment | `FeaturePromoter.check_bh_gate()` or `scipy.stats.false_discovery_control` | Already integrated in runner.py and promoter.py |
| Feature param sweep | Manual variant generation | `FeatureRegistry._expand_params()` via YAML `params:` key | Already handles itertools.product, naming convention, digest tracking |
| Feature lifecycle tracking | Custom DB table | `dim_feature_registry` + `FeaturePromoter` | Already has BH gate, migration stub generation, lifecycle states |
| AMA param hash lookup | Computing MD5 inline | `AMAParamSet.params_hash` from `ama_params.py` | Pre-computed canonical hashes — changing them orphans historical rows |
| Walk-forward CV | Custom train/test splits | `PurgedKFoldSplitter` from `ta_lab2.backtests.cv` | Already has embargo period, implemented correctly |
| Report scorecard | Custom markdown builder | `generate_bakeoff_scorecard.py` pattern | Already generates 5-section Markdown scorecard with Plotly charts (PNG/HTML fallback) |

**Key insight:** The evaluation infrastructure is complete. Phase 55 is a data-generation
and documentation phase, not an infrastructure phase. Every helper function needed already
exists — the planner should build tasks that *invoke* these tools, not tasks that build them.

---

## Common Pitfalls

### Pitfall 1: cmc_ic_results Overwrite vs Preserve

**What goes wrong:** Running `run_ic_sweep.py --all --overwrite` on BTC 1D will overwrite
the Phase 42 results (47,614 rows) if methodology has drifted. The `--overwrite` flag uses
`ON CONFLICT DO UPDATE` which silently replaces existing rows.

**How to avoid:** Always run the methodology verification step first (recompute 3-5 features
on BTC 1D with `--dry-run`, compare manually). Use `--no-overwrite` (append-only semantics)
for new asset/TF combinations not in Phase 42. Only use `--overwrite` after confirming
methodology identity.

**Warning signs:** IC values differ by more than 1e-6 for the same feature/asset/tf/horizon.

### Pitfall 2: AMA Params Hash Hard-Coded in YAML

**What goes wrong:** The current `features.yaml` has `params_hash: d47fe5cc` hard-coded
for KAMA. This is the first 8 characters of the MD5 hash of
`{"er_period": 10, "fast_period": 2, "slow_period": 30}`. If any new YAML entries for
other AMA variants hard-code the wrong params_hash, the ExperimentRunner will return empty
results silently (the SQL filter `AND "params_hash" = :filter_params_hash` matches nothing).

**How to avoid:** Use `compute_params_hash()` from `ama_params.py` to derive hashes:
```python
from ta_lab2.features.ama.ama_params import compute_params_hash
h = compute_params_hash({"er_period": 10, "fast_period": 2, "slow_period": 30})
print(h[:8])  # d47fe5cc
```
Or import the pre-computed `AMAParamSet` objects from `ama_params.py`.

### Pitfall 3: YAML Lifecycle Validation Blocks Load

**What goes wrong:** `FeatureRegistry.load()` raises `ValueError` if any feature has an
invalid lifecycle. Adding ~130 canonical cmc_features columns as entries with a typo in
lifecycle (e.g., `"Experimental"` instead of `"experimental"`) will cause the entire
registry load to fail.

**Valid lifecycles:** `experimental`, `promoted`, `deprecated` (lowercase, exact match).
**How to avoid:** Validate with `registry.load()` on a test subset before adding all 130
entries. Use YAML lint in CI.

### Pitfall 4: ExperimentRunner Inline Expression Scope

**What goes wrong:** Inline expressions in YAML are `eval()`'d with a restricted namespace:
`{"np": numpy, "pd": pandas, "__builtins__": {}}` plus DataFrame column names. Python
built-ins like `abs()`, `sum()`, `range()` are not available.

**How to avoid:** Use `np.abs()`, `np.sum()`, `np.arange()`. For rolling operations, use
`pd.Series.rolling()` on the column series directly.

**Example of what works:**
```yaml
expression: "rsi_14 - 50"          # OK: column arithmetic
expression: "np.abs(rsi_14 - 50)"  # OK: numpy function
expression: "vol_30d / (vol_7d + 1e-10)"  # OK: column division
```

### Pitfall 5: EMA Crossover Features Not in cmc_features

**What goes wrong:** Phase 42 scorecard notes: "EMA crossover indicators are NOT in
cmc_features; evaluated directly through signal generator walk-forward." EMA crossover
features need to reference `cmc_ema_multi_tf_u` with period filters, not `cmc_features`.

**How to avoid:** EMA crossover YAML features should use `cmc_ema_multi_tf_u` as input
table with `filters: period: <N>` to load specific EMA periods, then compute crossover
inline (e.g., `ema_fast - ema_slow`). But `cmc_ema_multi_tf_u` does not have a `tf`
column — it has `(id, ts, tf, period)` as PK. The `tf` column IS present (in the PK),
so it is not in `_TABLES_WITHOUT_TF`.

Actually from MEMORY.md: `cmc_ema_multi_tf_u` PK is `(id, ts, tf, period)`, NOT
`alignment_source` in PK. The ExperimentRunner `_load_inputs` does filter by `tf`.
So EMA crossover features can use filters `period: 21` to load ema_21 and compute
`ema_21 - ema_50` inline. Requires two separate inputs, joined on ts.

### Pitfall 6: All-Assets Sweep Row Estimate

The Phase 42 five-TF sweep produced 47,614 rows in 26 minutes for 17 assets x 5 TFs x 97
features. Extrapolating:
- 109 TFs x 17 assets = ~1,853 pairs (vs 85 pairs Phase 42)
- Scale factor: ~22x
- Estimated time: ~22 x 26 min = ~9-10 hours for cmc_features sweep alone
- AMA sweep (18 param sets x same pairs) adds significantly more

**Practical approach:** The CONTEXT.md notes that the prior plan identified a two-phase
strategy. The Phase 55 scope says "IC evaluation covers ALL 109 timeframes" but the
CONTEXT also says "Claude's Discretion: Ordering/batching of evaluation run for practical
compute time." This means batching is acceptable (e.g., run in chunks by TF group,
overnight, etc.) as long as all pairs are eventually covered.

---

## Code Examples

### Pattern 1: Full IC Sweep with Regime Breakdown

```bash
# From project root, run full sweep
# Source: run_ic_sweep.py CLI
python -m ta_lab2.scripts.analysis.run_ic_sweep \
    --all \
    --regime \
    --output-dir reports/evaluation/ \
    --verbose
```

### Pattern 2: Methodology Verification Sample

```bash
# Source: run_ic_eval.py CLI
python -m ta_lab2.scripts.analysis.run_ic_eval \
    --asset-id 1 \
    --tf 1D \
    --feature rsi_14 ret_arith bb_ma_20 \
    --train-start 2014-01-01 \
    --train-end 2026-02-01 \
    --dry-run
```

### Pattern 3: YAML Feature Entry for AMA Variant

```yaml
# Source: configs/experiments/features.yaml pattern (from existing entries)
kama_canonical_er:
  lifecycle: experimental
  description: "KAMA(10,2,30) Efficiency Ratio — trending vs choppy market signal"
  compute:
    mode: inline
    expression: "er"
  inputs:
    - table: cmc_ama_multi_tf_u
      columns: [er]
      filters:
        indicator: kama
        params_hash: d47fe5cc48eae24b12bfe20c12dd73b7  # full 32-char MD5 for KAMA(10,2,30)
  tags: [ama, kama, momentum]
```

### Pattern 4: YAML Feature Entry for EMA Crossover

```yaml
# Inline expression for EMA 21 vs 50 crossover
ema_cross_21_50:
  lifecycle: experimental
  description: "EMA(21) minus EMA(50) normalized crossover"
  compute:
    mode: inline
    expression: "(ema_21 - ema_50) / (close + 1e-10)"
  inputs:
    - table: cmc_ema_multi_tf_u
      columns: [value]       # NOTE: investigate actual column name in cmc_ema_multi_tf_u
      filters:
        period: 21
    - table: cmc_price_bars_multi_tf_u
      columns: [close]
  tags: [ema, crossover, trend]
```

**CAUTION on EMA crossover inputs:** From MEMORY.md, `cmc_ema_multi_tf_u` columns are
`d1` (not `ema_d1`), `d2`, `d1_roll`, `d2_roll`. The EMA value column itself is... not
named `value`. The planner should verify the column name for the EMA value in `cmc_ema_multi_tf_u`
before writing YAML entries for EMA crossovers.

### Pattern 5: ExperimentRunner Direct Usage

```python
# Source: ta_lab2/experiments/runner.py docstring
from sqlalchemy import create_engine, pool
from ta_lab2.experiments import FeatureRegistry
from ta_lab2.experiments.runner import ExperimentRunner

registry = FeatureRegistry("configs/experiments/features.yaml")
registry.load()

engine = create_engine(db_url, poolclass=pool.NullPool)
runner = ExperimentRunner(registry, engine)

result_df = runner.run(
    "vol_ratio_30_7",
    asset_ids=[1, 1027],
    tf="1D",
    train_start=pd.Timestamp("2018-01-01", tz="UTC"),
    train_end=pd.Timestamp("2025-12-31", tz="UTC"),
)
# result_df contains: feature_name, asset_id, tf, horizon, return_type,
#                     ic, ic_p_value, ic_p_value_bh, ic_ir, ic_ir_t_stat,
#                     wall_clock_seconds, peak_memory_mb, n_rows_computed
```

### Pattern 6: AMA params_hash Derivation

```python
# Source: ta_lab2/features/ama/ama_params.py
from ta_lab2.features.ama.ama_params import (
    KAMA_CANONICAL, KAMA_FAST, KAMA_SLOW,
    DEMA_9, DEMA_21, DEMA_50,
    TEMA_21, TEMA_50,
    HMA_21, HMA_50,
    compute_params_hash
)

# Hash for KAMA(10,2,30):
print(KAMA_CANONICAL.params_hash)  # d47fe5cc48eae24b12bfe20c12dd73b7

# Filter to use in YAML (first 8 chars only for readability):
# params_hash: d47fe5cc
```

---

## State of the Art

| Area | Phase 42 State | Phase 55 Target | Change Required |
|------|---------------|-----------------|-----------------|
| IC sweep scope | 17 assets x 5 TFs = 47,614 rows | All assets x all 109 TFs | Run `--all` instead of `--tf 1D` etc. |
| Regime breakdown | BTC + ETH 1D only | All features, same BTC/ETH 1D scope (unchanged) | Already correct — `--regime` flag |
| AMA IC sweep | 0 rows (table not populated) | All populated AMA combos | Populate cmc_ama_multi_tf_u first; run without `--skip-ama` |
| YAML registry | 5 features | ~130 features (112 canonical + AMA variants + EMA crossovers) | Expand features.yaml |
| cmc_feature_experiments | Empty | All YAML features scored | Run `run_experiment.py --all-experimental --yes` |
| Adaptive RSI A/B | Not started | IC + Sharpe comparison, decision documented | New subtask |
| Reports location | `reports/bakeoff/` | `reports/evaluation/` | New directory, same pattern |
| Jupyter notebook | Not present | Exploration notebook with IC decay charts | New artifact |
| Feature lifecycle | All experimental (5 features) | Promotion/deprecation decisions for ~130 features | `FeaturePromoter.promote_feature()` |

---

## Open Questions

1. **EMA value column name in cmc_ema_multi_tf_u**
   - What we know: MEMORY.md says columns are `d1` (NOT `ema_d1`), `d2`, `d1_roll`, `d2_roll`
   - What's unclear: The EMA value itself (the actual moving average level) — is it named `ema`, `value`, or something else?
   - Recommendation: Inspect `cmc_ema_multi_tf_u` schema or the DDL SQL before writing EMA crossover YAML entries. The planner should add a schema inspection task before EMA crossover features are authored.

2. **AMA table population status**
   - What we know: Phase 42 found cmc_ama_multi_tf_u empty (0 AMA rows in IC sweep); Phase 35 built the AMA pipeline
   - What's unclear: Has anyone run the AMA refresh since Phase 42? What indicator/params combos exist in the DB?
   - Recommendation: Add a dry-run AMA discovery task early (`run_ic_sweep.py --dry-run --all`) to check actual AMA table state before planning AMA IC sweep duration estimates.

3. **Full sweep timing at 109 TFs**
   - What we know: 5-TF sweep took 26 min for 17 assets; 109 TFs = ~22x more pairs
   - What's unclear: How many (asset, tf) pairs actually qualify (>= 500 bars) at non-daily TFs? Wide TFs (1Y, etc.) may have very few qualifying pairs.
   - Recommendation: Run `--dry-run --all --min-bars 500` to count qualifying pairs before estimating wall-clock time. Plan for overnight batch execution if >500 pairs qualify.

4. **Per-row adaptive RSI feasibility**
   - What we know: Current `use_adaptive=True` falls back to global average (code comment says full per-row requires `make_signals` enhancement)
   - What's unclear: Is the global-average comparison a fair A/B? Or should per-row adaptive be implemented first?
   - Recommendation: Use the YAML inline expression approach for IC comparison (defines adaptive RSI as a normalized signal, no changes to make_signals needed). For backtest Sharpe, compute time-averaged thresholds for BTC 1D historical data and use those as static override — avoids code changes while still testing the adaptive concept.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` — IC sweep CLI, all flags, data sources, timing
- `src/ta_lab2/scripts/experiments/run_experiment.py` — ExperimentRunner CLI, asset discovery, save to cmc_feature_experiments
- `src/ta_lab2/experiments/runner.py` — ExperimentRunner API, compute modes, BH correction, scratch table
- `src/ta_lab2/experiments/registry.py` — FeatureRegistry YAML loading, expansion, lifecycle validation
- `src/ta_lab2/experiments/promoter.py` — FeaturePromoter BH gate, dim_feature_registry writes, migration stub
- `src/ta_lab2/analysis/ic.py` — IC library: compute_ic, batch_compute_ic, compute_ic_by_regime, save_ic_results, _NON_FEATURE_COLS
- `src/ta_lab2/features/ama/ama_params.py` — ALL_AMA_PARAMS, all 18 AMAParamSet instances, params_hash values
- `configs/experiments/features.yaml` — Current 5-feature registry structure and examples
- `src/ta_lab2/dashboard/pages/3_research_explorer.py` — Research Explorer page data requirements
- `src/ta_lab2/dashboard/pages/5_experiments.py` — Experiments page data requirements
- `src/ta_lab2/dashboard/queries/research.py` — `load_ic_results`, `load_feature_names` SQL
- `src/ta_lab2/dashboard/queries/experiments.py` — `load_experiment_summary`, `load_experiment_results` SQL
- `src/ta_lab2/scripts/signals/generate_signals_rsi.py` — `compute_adaptive_thresholds`, `use_adaptive` flag, current limitation
- `src/ta_lab2/scripts/backtests/run_bakeoff.py` — Walk-forward bakeoff CLI, RSI param grids
- `reports/bakeoff/feature_ic_ranking.csv` — 97 features ranked, Phase 42 scope: 5 TFs x 17 assets
- `.planning/phases/42-strategy-bake-off/42-01-SUMMARY.md` — Phase 42 IC sweep timing (26 min), decisions, scope

### Secondary (MEDIUM confidence)
- `alembic/versions/6f82e9117c58_feature_experiment_tables.py` — cmc_feature_experiments and dim_feature_registry DDL
- `sql/features/080_cmc_ic_results.sql` — cmc_ic_results DDL (reference, actual in Alembic)
- `src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py` — Report generation pattern, CSV data sources, chart generation

---

## Metadata

**Confidence breakdown:**
- IC sweep infrastructure: HIGH — read actual source code
- ExperimentRunner/Registry/Promoter: HIGH — read actual source code
- AMA parameter sets and hashes: HIGH — read ama_params.py directly
- Adaptive RSI mechanism: HIGH — read generate_signals_rsi.py; found existing limitation
- Phase 42 scope and timing: HIGH — read 42-01-SUMMARY.md with exact timestamps
- Dashboard data requirements: HIGH — read both query modules and page modules
- Full sweep timing estimate: MEDIUM — extrapolation from Phase 42 data (22x factor)
- AMA table current population: LOW — table was empty in Phase 42; current state unknown

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable codebase; re-verify if AMA refresh runs change table schema)
