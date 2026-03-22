# Phase 82: Signal Refinement & Walk-Forward Bake-off - Research

**Researched:** 2026-03-22
**Domain:** Expression engine signal construction, walk-forward CV, cost modeling, statistical gates, regime routing
**Confidence:** HIGH (codebase fully verified; external Hyperliquid fees from official docs)

---

## Summary

Phase 82 builds directly on top of a mature, working infrastructure. Every
component required already exists in the codebase — the expression engine
(`ml/expression_engine.py`), regime router (`ml/regime_router.py`), walk-forward
bake-off orchestrator (`backtests/bakeoff_orchestrator.py`), PSR/DSR gates
(`backtests/psr.py`), CPCV splitter (`backtests/cv.py`), and composite scorer
(`backtests/composite_scorer.py`) are all implemented and battle-tested from
Phase 42. The signal registry (`signals/registry.py`) exposes three signal
generators (ema_trend, rsi_mean_revert, breakout_atr).

The key gaps that Phase 82 must close:

1. The bakeoff_orchestrator's `load_strategy_data()` only queries the `features`
   table. The 20 active features from Phase 80 are 90% from `ama_multi_tf` — the
   data loader must be extended to join both sources.
2. The regime router's `run_regime_routing.py` also only loads from `features`. The
   same join-extension applies.
3. New YAML experiments targeting the 20 active features must be defined — the
   existing YAML in `configs/experiments/features.yaml` has no experiments that
   specifically use the Phase 80 selected features.
4. The Hyperliquid cost matrix does not exist yet — Kraken is the only matrix.
5. The bakeoff_orchestrator persists to `strategy_bakeoff_results`, not
   `backtest_metrics`. The planner must resolve whether to write to both or to
   add `experiment_lineage` columns.

**Primary recommendation:** Extend `load_strategy_data()` and the regime router
data loader to join `ama_multi_tf` columns by (id, venue_id, ts, tf, indicator,
params_hash), flatten AMA feature columns into the working DataFrame, then
proceed with existing bakeoff machinery unchanged.

---

## Standard Stack

### Core (all already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| vectorbt | 0.28.1 | Portfolio simulation per fold | Already wired in `_run_single_fold()` |
| scikit-learn | current | PurgedKFold, RegimeRouter cloning | `BaseCrossValidator`, `clone()` |
| lightgbm | current | RegimeRouter base model | Falls back to RandomForest if missing |
| scipy | current | PSR/DSR skew/kurtosis | `kurtosis(fisher=False)` is critical |
| pandas | current | Time-series ops | UTC-aware tz handling |
| SQLAlchemy | current | DB queries | NullPool for multiprocessing |
| PyYAML | current | YAML experiment configs | Existing config pattern |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| statsmodels | current | GARCH vol (Phase 81) | `arch` package actually used for GARCH |
| arch | current | GARCH engine (Phase 81) | `garch_engine.py` depends on this |
| numpy | current | Array ops, PSR math | Core everywhere |
| plotly | current | IC decay charts | `plot_ic_decay()` already in ic.py |

**Installation:** No new packages needed. All required dependencies are present.

---

## Architecture Patterns

### Pattern 1: Extended Data Loader for AMA Features

The critical Phase 82 gap. The existing `load_strategy_data()` in
`bakeoff_orchestrator.py` only queries `features`. The 18/20 active features are
in `ama_multi_tf` (with columns: `ama`, `er`, `d1`, `d1_roll`). The join must use
the exact `(indicator, params_hash)` pairs from `configs/feature_selection.yaml`.

```python
# Source: configs/feature_selection.yaml active tier, verified 2026-03-22
# The 20 active features are:
# AMA features (18) - from ama_multi_tf, keyed by (indicator, params_hash[:8]):
AMA_ACTIVE_FEATURES = [
    # name                    indicator  params_hash_prefix  column
    ("ret_is_outlier",        None,      None,               "features"),  # bar-level
    ("TEMA_0fca19a1_ama",     "TEMA",    "0fca19a1",         "ama"),
    ("DEMA_0fca19a1_ama",     "DEMA",    "0fca19a1",         "ama"),
    ("KAMA_987fc105_ama",     "KAMA",    "987fc105",         "ama"),
    ("HMA_514ffe35_ama",      "HMA",     "514ffe35",         "ama"),
    ("TEMA_514ffe35_ama",     "TEMA",    "514ffe35",         "ama"),
    ("TEMA_018899b6_ama",     "TEMA",    "018899b6",         "ama"),
    ("DEMA_514ffe35_ama",     "DEMA",    "514ffe35",         "ama"),
    ("HMA_018899b6_ama",      "HMA",     "018899b6",         "ama"),
    ("DEMA_d47fe5cc_ama",     "DEMA",    "d47fe5cc",         "ama"),
    ("DEMA_018899b6_ama",     "DEMA",    "018899b6",         "ama"),
    ("KAMA_de1106d5_ama",     "KAMA",    "de1106d5",         "ama"),
    ("DEMA_a4b71eb4_ama",     "DEMA",    "a4b71eb4",         "ama"),
    ("bb_ma_20",              None,      None,               "features"),  # bar-level
    ("TEMA_a4b71eb4_ama",     "TEMA",    "a4b71eb4",         "ama"),
    ("TEMA_d47fe5cc_ama",     "TEMA",    "d47fe5cc",         "ama"),
    ("KAMA_8545aeed_ama",     "KAMA",    "8545aeed",         "ama"),
    ("close_fracdiff",        None,      None,               "features"),  # bar-level
    ("HMA_d47fe5cc_ama",      "HMA",     "d47fe5cc",         "ama"),
    ("HMA_a4b71eb4_ama",      "HMA",     "a4b71eb4",         "ama"),
]
# Bar-level features (2): ret_is_outlier, bb_ma_20, close_fracdiff
# AMA features (18): all other entries above

# SQL pattern for loading AMA features:
AMA_JOIN_TEMPLATE = """
    SELECT a.ts,
           a.ama     AS {feature_col},
           a.d1      AS {feature_col}_d1
    FROM ama_multi_tf_u a
    WHERE a.id = :asset_id
      AND a.tf = :tf
      AND a.indicator = :indicator
      AND LEFT(a.params_hash, 8) = :params_hash_prefix
    ORDER BY a.ts
"""
```

**Important:** The `ama_multi_tf_u` view unifies all `alignment_source` variants.
Use `ama_multi_tf_u`, not the raw `ama_multi_tf`. Column name in the DB is `ama`
(not `ama_value`). The `er` column (Efficiency Ratio) exists only for KAMA.
DEMA/TEMA/HMA have `d1` and `d1_roll` but no `er`.

### Pattern 2: Expression Engine YAML Experiments

The expression engine (`ml/expression_engine.py`) uses `$col` syntax evaluated
against a DataFrame. The engine has 16 operators: EMA, Ref, Delta, Mean, Std,
WMA, Max, Min, Rank, Abs, Sign, Log, Corr, Slope, Skew, Kurt.

**Operator note:** `Rank($col)` does cross-sectional rank (pct=True), useful for
normalization. For rolling rank, chain: `$col.rolling(N).rank()` is not an
operator — instead use `Ref($col, 0)` equivalents via `Mean`/`Std`.

```yaml
# configs/experiments/signals_phase82.yaml
# Expression engine experiment format (verified from configs/experiments/features.yaml)
experiments:

  # Experiment 1: IC-IR weighted AMA momentum composite (MOMENTUM archetype)
  ama_momentum_composite:
    description: "IC-IR weighted average of top-5 AMA values as momentum signal"
    compute:
      mode: expression
      expression: "EMA($TEMA_0fca19a1 + $KAMA_987fc105 + $HMA_514ffe35 + $TEMA_514ffe35 + $DEMA_0fca19a1, 5) / 5"
    inputs:
      - table: ama_multi_tf_u  # joined via loader
        columns: [TEMA_0fca19a1, KAMA_987fc105, HMA_514ffe35, TEMA_514ffe35, DEMA_0fca19a1]
    tags: [composite, momentum, ama]

  # Experiment 2: AMA crossover signal (MOMENTUM archetype)
  ama_fast_slow_crossover:
    description: "Fast AMA (KAMA 5,2,15) minus slow AMA (KAMA 20,2,50) crossover"
    compute:
      mode: expression
      expression: "$KAMA_987fc105 - $KAMA_8545aeed"
    inputs:
      - table: ama_multi_tf_u
        columns: [KAMA_987fc105, KAMA_8545aeed]
    tags: [crossover, momentum, ama, kama]

  # Experiment 3: Mean-reversion signal using AMA deviation
  ama_mean_reversion_zscore:
    description: "Z-score of close relative to KAMA(10,2,30): mean-reversion signal"
    compute:
      mode: expression
      expression: "($close - $KAMA_de1106d5) / (Std($close, 20) + 1e-10)"
    inputs:
      - table: price_bars_multi_tf_u
        columns: [close]
      - table: ama_multi_tf_u
        columns: [KAMA_de1106d5]
    tags: [mean_reversion, zscore, ama]
```

**Note on multi-table expression engine:** The current `evaluate_expression()`
accepts a single DataFrame. For experiments using both `price_bars_multi_tf_u` and
`ama_multi_tf_u`, the data loader must pre-join the tables into a unified DataFrame
before passing to `evaluate_expression()`. The expression engine itself does not
perform SQL joins.

### Pattern 3: Regime Router Architecture

**Architecture decision — verified by codebase:** The regime router (`RegimeRouter`
class) is an sklearn-compatible dispatcher, NOT a wrapper around the expression
engine. It wraps any ML classifier and dispatches fit/predict by L2 regime label.

Two valid architectures exist:
1. **Independent experiments:** Expression engine signal experiments run as
   separate YAML-driven strategies; regime router is a separate ML experiment using
   the 20 features as input to a LightGBM/RF classifier per regime.
2. **Unified wrapper:** Regime router wraps a signal-scoring function; each regime
   gets its own signal combination weights.

**Recommended architecture:** Run as **independent experiments** (Option 1). This
is how the codebase was designed — `run_bakeoff.py` evaluates named signal
functions, and `run_regime_routing.py` evaluates the ML regime router separately.
The comparison between them is explicit (the CLI prints a side-by-side table).
Mixing them would require a new hybrid class that doesn't exist.

**Regime router for conditional TA features:** The 160 conditional-tier features
(RSI, MACD, ADX, Bollinger) are the natural input for regime-conditional
sub-models. The global fallback model uses all 20 active features; regime sub-models
use regime-conditional features as specialists.

```python
# Source: src/ta_lab2/ml/regime_router.py (verified)
# RegimeRouter.fit() signature:
router = RegimeRouter(
    base_model=LGBMClassifier(n_estimators=100, num_leaves=31, verbose=-1),
    min_samples=30,       # regime must have >= 30 train bars for its own model
    regime_col="l2_label",
)
router.fit(X_train, y_train, regimes_series)   # MUST pass DataFrame, not numpy
preds = router.predict(X_test, regimes_test)    # returns numpy array
# router.get_regime_stats() -> dict of fitted_regimes, fallback_regimes, sample_counts
```

**Data loading for regime router:** Currently `run_regime_routing.py` loads only
from `features`. Must extend to join `ama_multi_tf_u` columns. The feature matrix X
will have the 20 active feature columns after the join. Use `_EXCLUDE_COLS` to
remove non-numeric columns.

### Pattern 4: Walk-Forward Configuration

The existing `BakeoffConfig` default is: 10 folds, 20-bar embargo, 365 freq/year.
With ~1,095 bars (3 years x 365), this gives:
- 10-fold: ~109 bars/fold (~4 months per fold)
- CPCV: C(10,2) = 45 combinations for PBO
- Embargo: 20 bars (1 month) — appropriate for swing trading

**Expanding vs rolling recommendation:** The existing `splitters.py` has both
`expanding_walk_forward()` and `fixed_date_splits()` but the `bakeoff_orchestrator`
uses `PurgedKFoldSplitter` which is fixed-parameter (not re-optimizing). For Phase
82's requirement to compare expanding vs rolling: implement as a `BakeoffConfig`
flag that switches between sequential K-fold (simulates expanding) and a rolling
K-fold variant.

**Fold count recommendation for 3 years of daily crypto:**
- 10 folds = ~109 bars each (~4 months) — RECOMMENDED. Matches existing default.
  Sufficient OOS bars per fold for statistical significance (PSR needs n >= 30).
- 6 folds = ~182 bars each (~6 months) — Alternative for more bars per fold.
  Lower PBO power (C(6,2) = 15 combos vs 45).
- 12 folds = ~91 bars each (~3 months) — Too small for reliable Sharpe estimation.

**Refit policy:** The existing orchestrator is fixed-parameter (documented
intentionally in the bakeoff_orchestrator header: "expanding-window
re-optimization is DELIBERATELY DEFERRED"). The comparison of refit-per-fold vs
train-once requires a new boolean flag in `BakeoffConfig` and a parameter sweep
loop in `run_bakeoff.py`.

### Pattern 5: Signal Functions for Bake-off

Signal functions must match the signature: `(df, **params) -> (entries, exits, size)`.
For AMA-based composite signals, a new `ama_composite.py` signal generator is
needed alongside the existing three signal generators.

```python
# Pattern verified from src/ta_lab2/signals/ema_trend.py pattern
def make_signals(
    df: pd.DataFrame,
    feature_col: str = "KAMA_de1106d5",  # AMA feature col in df
    threshold: float = 0.0,
    holding_bars: int = 10,  # swing trading: 10-day default
    **kwargs,
) -> tuple[pd.Series, pd.Series, None]:
    """AMA momentum signal: enter when feature > threshold, hold N bars."""
    signal = df[feature_col].fillna(0.0)
    entries = signal > threshold
    exits = signal < -threshold
    # Or use rolling max exit: exit when signal drops below N-bar high
    return entries, exits, None
```

### Recommended Project Structure

```
configs/experiments/
  features.yaml           # existing (do not modify active experiments)
  signals_phase82.yaml    # NEW: Phase 82 signal experiments (3+ YAML experiments)

src/ta_lab2/
  signals/
    ema_trend.py          # existing
    rsi_mean_revert.py    # existing
    breakout_atr.py       # existing
    ama_composite.py      # NEW: AMA-based signal generators
  backtests/
    bakeoff_orchestrator.py  # MODIFY: extend load_strategy_data()
    costs.py              # MODIFY: add HYPERLIQUID_COST_MATRIX
  scripts/
    backtests/
      run_bakeoff.py      # MODIFY: add HL cost matrix, per-asset IC weights, rolling flag
    ml/
      run_regime_routing.py  # MODIFY: extend data loader for ama_multi_tf_u

reports/
  bakeoff/
    phase82_results.md    # NEW: selection report

configs/
  feature_selection.yaml  # existing (read-only for Phase 82)
```

### Anti-Patterns to Avoid

- **Anti-pattern — load ama_multi_tf directly:** Always use `ama_multi_tf_u`
  (the unified `_u` view). Raw `ama_multi_tf` requires specifying `alignment_source`
  which varies per asset. The `_u` table unifies this.
- **Anti-pattern — use .values on tz-aware Series:** Returns tz-naive numpy. Use
  `.tolist()` or `.tz_localize("UTC")`. Critical for t1_series construction in CV.
- **Anti-pattern — pass numpy arrays to LightGBM:** Always pass DataFrame slices
  with column names. `RegimeRouter.fit()` enforces this with `hasattr(X, 'iloc')`.
- **Anti-pattern — using Fisher kurtosis in PSR:** The PSR formula expects Pearson
  kurtosis (fisher=False). The existing `compute_psr()` correctly uses
  `kurtosis(arr, fisher=False)`. Do NOT change this.
- **Anti-pattern — multiprocessing without NullPool:** Use
  `create_engine(url, poolclass=NullPool)` for any subprocess. Existing code
  already does this correctly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Walk-forward CV | Custom train/test splitter | `PurgedKFoldSplitter` from `backtests/cv.py` | Purge + embargo already implemented, tested |
| CPCV / PBO | Custom combo loop | `CPCVSplitter` from `backtests/cv.py` | C(10,2)=45 combos with proper purge |
| PSR / DSR | Custom Sharpe stats | `compute_psr`, `compute_dsr` from `backtests/psr.py` | Pearson kurtosis convention critical |
| Portfolio simulation | Custom P&L loop | `vectorbt.Portfolio.from_signals()` | Handles fees, slippage, sizing |
| Expression parsing | ast.parse custom | `evaluate_expression()` from `ml/expression_engine.py` | $col syntax, 16 operators, restricted eval |
| Composite scoring | Custom rank/weight | `composite_scorer.py` | 4 weight schemes, sensitivity analysis |
| Regime dispatch | If-else per regime | `RegimeRouter` from `ml/regime_router.py` | Global fallback, min_samples guard |
| AMA data access | Direct SQL per feature | Join via `ama_multi_tf_u` with `(indicator, params_hash)` | Unified alignment_source |

**Key insight:** Every algorithmic component needed for Phase 82 already exists.
The work is plumbing (data loader extension) and configuration (new YAML experiments
and Hyperliquid cost matrix), not new algorithm development.

---

## Hyperliquid Cost Matrix

**Source:** https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees (fetched 2026-03-22)

### Hyperliquid Perps Fee Tiers (14-day volume, USDC)

| Tier | Taker Fee | Maker Fee | 14D Volume |
|------|-----------|-----------|------------|
| Base (Tier 0) | 0.045% (4.5 bps) | 0.015% (1.5 bps) | < $5M |
| Tier 1 | ~0.040% | ~0.010% | $5M+ |
| Tier 2-6 | decreasing | can be 0% | $25M-$7B+ |
| Wood (highest) | 0.024% | 0% or rebate | $7B+ |

**Maker rebates:** High-volume makers can receive negative fees (rebates) up to
-0.003% (-0.3 bps). For Phase 82, ignore rebates — use conservative base fees.

**HIP-3 Growth Mode:** New markets get 90% fee reduction (taker as low as
0.0045%). Do NOT apply to standard BTC/ETH/SOL perps. Growth mode applies only
to newly launched permissionless markets.

**Staking discounts:** HYPE staking gives 5-40% discounts. Ignore for baseline
cost matrix — these are user-specific.

**Funding rates (BTC perps on HL, Q3 2025):**
- Average funding: ~0.0097% per 8h = 0.0291%/day = 2.91 bps/day
- Positive 92%+ of the time (long bias)
- ETH funding: ~0.0131% per 8h = 0.039%/day = 3.9 bps/day

### Hyperliquid Cost Matrix Definition (6 scenarios)

```python
# src/ta_lab2/backtests/costs.py — add to existing module
_HL_SLIPPAGE_LEVELS = [3.0, 5.0, 10.0]  # bps — HL is a CLOB, tighter spreads than CEX
_HL_TAKER_FEE_BPS = 4.5   # Base tier taker
_HL_MAKER_FEE_BPS = 1.5   # Base tier maker
_HL_FUNDING_BPS_DAY = 2.91  # BTC average (Q3 2025, Coinalyze data)

HYPERLIQUID_COST_MATRIX: List[CostModel] = (
    # Perps maker scenarios (3): HL maker 1.5 bps + funding x slippage 3/5/10
    [CostModel(fee_bps=_HL_MAKER_FEE_BPS, slippage_bps=slip,
               funding_bps_day=_HL_FUNDING_BPS_DAY)
     for slip in _HL_SLIPPAGE_LEVELS]
    +
    # Perps taker scenarios (3): HL taker 4.5 bps + funding x slippage 3/5/10
    [CostModel(fee_bps=_HL_TAKER_FEE_BPS, slippage_bps=slip,
               funding_bps_day=_HL_FUNDING_BPS_DAY)
     for slip in _HL_SLIPPAGE_LEVELS]
)
```

**Note:** Hyperliquid is a CLOB perpetuals DEX — bid-ask spreads are tighter than
Kraken CEX. 3 bps slippage is realistic for liquid markets (BTC, ETH, SOL).
10 bps is conservative/stress scenario.

### Cost Matrix Framework Design

For future exchange addition, define a `cost_matrix_registry` dict:

```python
# In bakeoff_orchestrator.py or costs.py
COST_MATRIX_REGISTRY = {
    "kraken": KRAKEN_COST_MATRIX,
    "hyperliquid": HYPERLIQUID_COST_MATRIX,
}
```

Add a `--exchange` CLI flag to `run_bakeoff.py` that selects the matrix. Combined
multi-exchange runs: iterate over `COST_MATRIX_REGISTRY.values()`.

---

## Common Pitfalls

### Pitfall 1: ama_multi_tf Column Name Collision on Multi-Indicator Join

**What goes wrong:** If you join multiple AMA variants (e.g., KAMA and DEMA both
have an `ama` column), the joined DataFrame has duplicate column names → expression
engine eval fails.

**Why it happens:** Each AMA variant in `ama_multi_tf_u` has the same column names
(`ama`, `d1`, `er`). A naive wide join produces `ama_x`, `ama_y` etc., or silently
overwrites.

**How to avoid:** Rename columns during the join using the `{indicator}_{params_hash_prefix}`
pattern from `feature_selection.yaml`. Example: `KAMA_de1106d5_ama`, `DEMA_514ffe35_ama`.
This is already the naming convention used in `configs/experiments/features.yaml`.

**Warning signs:** `ValueError: Expression references disallowed column(s)` from
`validate_expression()` or duplicate column index after merge.

### Pitfall 2: PSR Returns NaN with Small Fold Size

**What goes wrong:** PSR returns NaN for folds with fewer than 30 OOS bars.

**Why it happens:** `compute_psr()` enforces `n < 30 → return NaN`. At 10 folds
over 1,095 bars, fold size is ~109 bars — this is fine. But if running on assets
with < 300 bars total, fold sizes may fall below 30.

**How to avoid:** The existing `BakeoffConfig.min_bars = 300` gate already guards
this. Do not lower `min_bars` below 300 for daily crypto.

**Warning signs:** Many NaN in `psr` column of `strategy_bakeoff_results`.
Check `psr_n_obs` column — should be > 100 for reliable estimates.

### Pitfall 3: DSR Requires Cross-Strategy SR Pool

**What goes wrong:** Computing DSR on each strategy independently (passing only
that strategy's OOS returns) — this gives PSR(sr_star=0), not DSR. DSR requires
the pool of ALL strategy Sharpe estimates to compute `expected_max_sr`.

**Why it happens:** DSR corrects for "trying many strategies and picking the best."
If you have 30 parameter combinations across 3 archetypes, the expected max SR
across 30 trials is the DSR benchmark.

**How to avoid:** The existing `_compute_and_attach_dsr()` in `bakeoff_orchestrator.py`
already groups by `(asset_id, tf, cost_scenario, cv_method)` and computes
`expected_max_sr(sr_estimates_perbar)` across the whole group. Do not bypass
this — run all strategies together, not one at a time.

**Warning signs:** DSR values equal to PSR values, or DSR > 0.99 for all
strategies (would mean sr_star ≈ 0, i.e., only one strategy was evaluated).

### Pitfall 4: Per-Asset IC Weights Leading to Overfitting

**What goes wrong:** Fitting asset-specific IC-IR weights on the same data used
for bake-off evaluation inflates apparent performance.

**Why it happens:** IC-IR computed over the full historical window is in-sample
to the bake-off period. Using it to weight signals before walk-forward evaluation
constitutes look-ahead.

**How to avoid:** Two valid approaches:
- (a) Compute per-asset IC-IR weights on a held-out pre-bakeoff period (e.g., first
  year of data) and apply fixed weights during bake-off.
- (b) Re-compute IC-IR weights within each fold's training window (proper walk-
  forward). This is more correct but adds complexity.
For Phase 82: use approach (a) as baseline, (b) as a secondary experiment.

**Warning signs:** Significantly better OOS performance with per-asset weights
than universal weights — likely overfitting if the gap is large.

### Pitfall 5: Funding Cost Double-Counting

**What goes wrong:** `CostModel.to_vbt_kwargs()` passes `fees` and `slippage` to
vectorbt but NOT `funding_bps_day`. The funding deduction happens in a separate
post-hoc adjustment in `_run_single_fold()`.

**Why it happens:** vectorbt's `Portfolio.from_signals()` doesn't have a
`funding_rate` parameter. The existing code deducts funding via:
```python
if cost.funding_bps_day > 0:
    position_open = e_in.cumsum() > e_out.cumsum()
    funding_adj[position_open] -= funding_daily
```

**How to avoid:** Do NOT also pass `funding_bps_day` to `to_vbt_kwargs()`. The
`CostModel.to_vbt_kwargs()` correctly omits it (only returns `fees` and
`slippage`). The post-hoc deduction is the right approach.

**Warning signs:** Perp performance materially worse than expected vs spot.
Verify by running `spot_only=True` and comparing to perp results manually.

### Pitfall 6: Signal Function Lookback Contaminating Folds

**What goes wrong:** AMA values computed locally in the signal function using
pandas rolling ops look back beyond the fold boundary.

**Why it happens:** AMA values in `ama_multi_tf` were computed over the full
historical window. If you re-compute AMA locally from `close` within a fold,
you introduce warmup effects.

**How to avoid:** Load pre-computed AMA values from `ama_multi_tf_u` — these are
already computed over the full history and stored in DB. Do NOT re-compute AMA
locally. The signal function should read `df[ama_col]` where `ama_col` was loaded
from DB.

---

## Code Examples

### Extended Data Loader

```python
# Source: bakeoff_orchestrator.py (current), extending to add AMA join
# Verified pattern from load_strategy_data()

def load_strategy_data_with_ama(
    engine: Engine,
    asset_id: int,
    tf: str,
    ama_features: list[dict],  # from feature_selection.yaml active tier
) -> pd.DataFrame:
    """Load features + selected AMA columns for strategy evaluation."""

    # Base query — existing features table
    sql_features = text("""
        SELECT ts, open, high, low, close, volume, rsi_14, bb_ma_20,
               close_fracdiff, ret_is_outlier, ta_is_outlier
        FROM public.features
        WHERE id = :asset_id AND tf = :tf
        ORDER BY ts
    """)

    with engine.connect() as conn:
        df = pd.read_sql(sql_features, conn, params={"asset_id": asset_id, "tf": tf})

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()

    # AMA join — one query per unique (indicator, params_hash_prefix)
    for feat in ama_features:
        if feat["source"] != "ama_multi_tf_u":
            continue
        indicator = feat["indicator"]
        ph_prefix = feat["params_hash"][:8]  # first 8 chars
        col_name = feat["name"]  # e.g. "KAMA_de1106d5_ama"

        sql_ama = text("""
            SELECT ts, ama AS val
            FROM public.ama_multi_tf_u
            WHERE id = :asset_id
              AND tf = :tf
              AND venue_id = 1
              AND indicator = :indicator
              AND LEFT(params_hash, 8) = :ph_prefix
            ORDER BY ts
        """)
        with engine.connect() as conn:
            ama_df = pd.read_sql(
                sql_ama, conn,
                params={"asset_id": asset_id, "tf": tf,
                        "indicator": indicator, "ph_prefix": ph_prefix}
            )
        if ama_df.empty:
            continue
        ama_df["ts"] = pd.to_datetime(ama_df["ts"], utc=True)
        ama_df = ama_df.set_index("ts")
        df[col_name] = ama_df["val"]

    return df
```

### YAML Experiment Template (Signal Construction)

```yaml
# configs/experiments/signals_phase82.yaml
# Three minimum experiments required (CONTEXT.md: "at least 3")
# Source: pattern from configs/experiments/features.yaml (expression mode section)

experiments:

  # ARCHETYPE 1: Momentum — IC-IR weighted AMA value composite
  ama_momentum_weighted:
    lifecycle: experimental
    description: "IC-IR weighted sum of top-3 AMA values: TEMA200 + KAMA_fast + HMA_fast"
    compute:
      mode: expression
      # IC-IR weights from feature_selection.yaml (normalized):
      # TEMA_0fca19a1: 1.433, KAMA_987fc105: 1.291, HMA_514ffe35: 1.271 -> sum=3.995
      expression: "($TEMA_0fca19a1 * 1.433 + $KAMA_987fc105 * 1.291 + $HMA_514ffe35 * 1.271) / 3.995"
    inputs:
      - table: ama_multi_tf_u_joined  # pre-joined by loader
        columns: [TEMA_0fca19a1, KAMA_987fc105, HMA_514ffe35]
    tags: [composite, momentum, ama, ic_ir_weighted]

  # ARCHETYPE 2: Mean-reversion — AMA spread z-score
  ama_spread_reversion:
    lifecycle: experimental
    description: "Z-score of close vs KAMA(10,2,30): mean-reversion signal"
    compute:
      mode: expression
      expression: "($close - $KAMA_de1106d5) / (Std($close, 20) + 1e-10)"
    inputs:
      - table: joined
        columns: [close, KAMA_de1106d5]
    tags: [mean_reversion, zscore, ama, kama]

  # ARCHETYPE 3: Regime-conditional — AMA momentum with ADX filter
  ama_trend_adx_conditional:
    lifecycle: experimental
    description: "AMA momentum signal conditioned on ADX trend strength (regime-conditional)"
    compute:
      mode: expression
      expression: "Sign($DEMA_d47fe5cc) * ($adx_14 - 20) / 20"
    inputs:
      - table: joined
        columns: [DEMA_d47fe5cc, adx_14]
    tags: [regime_conditional, trend, ama, adx]
```

### Per-Asset IC Weight Computation

```python
# Source: analysis/ic.py pattern (load_ic_ranking verified in feature_selection.py)
# Query per-asset IC-IR from ic_results (already populated by Phase 80)

def load_per_asset_ic_weights(engine, features: list[str], tf: str = "1D",
                               horizon: int = 1, return_type: str = "arith") -> pd.DataFrame:
    """Load per-asset IC-IR weights from ic_results.

    Returns DataFrame: index=asset_id, columns=feature_names, values=ic_ir.
    Normalizes so weights sum to 1.0 per asset.
    Falls back to universal weights where per-asset data is missing.
    """
    sql = text("""
        SELECT asset_id, feature, ic_ir
        FROM public.ic_results
        WHERE feature = ANY(CAST(:features AS TEXT[]))
          AND tf = :tf
          AND horizon = :horizon
          AND return_type = :return_type
          AND regime_col = 'all'
          AND regime_label = 'all'
        ORDER BY asset_id, feature
    """)
    # ... pivot to wide format, normalize per asset
    # ic_results has asset_id column (verified from run_ic_sweep.py)
```

### DSR Gate Application

```python
# Source: bakeoff_orchestrator.py _compute_and_attach_dsr() (verified)
# DSR threshold calibration:
# With 10 folds x 3 strategies x 3 param sets = 90 trials per asset,
# expected_max_sr(sr_estimates) will be non-trivial.
# DSR > 0.95 means: "Given the number of strategies we tried, the best one
# is still likely to be genuinely good (95% confidence)"

DSR_GATE = 0.95   # CONTEXT.md default; adjust based on distribution
PBO_GATE = 0.50   # PBO < 0.50 means strategy beats median more than half the time

def apply_statistical_gates(results: List[StrategyResult],
                            dsr_gate: float = 0.95,
                            pbo_gate: float = 0.50) -> List[StrategyResult]:
    """Return strategies passing DSR > gate AND PBO < gate."""
    return [
        sr for sr in results
        if (not math.isnan(sr.dsr) and sr.dsr > dsr_gate)
        and (math.isnan(sr.pbo_prob) or sr.pbo_prob < pbo_gate)
    ]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single Sharpe gate | DSR (corrects for N trials) | Phase 42 (CPCV) | Survivors are genuinely not overfitted |
| Load only `features` table | Join `features` + `ama_multi_tf_u` | Phase 82 (NEW) | 18/20 active features accessible |
| Universal IC weights | Per-asset IC-IR weights | Phase 82 (NEW) | Captures per-asset signal heterogeneity |
| Kraken-only cost matrix | Kraken + Hyperliquid matrices | Phase 82 (NEW) | Directly comparable to live trading venue |
| Fixed-parameter walk-forward | Compare fixed vs refit-per-fold | Phase 82 (NEW) | Measures value of online parameter updating |

**Deprecated/outdated:**
- The `load_strategy_data()` loads `ema_*` columns computed locally (not from
  `ema_multi_tf_u`). For Phase 82 AMA-based strategies, use DB-sourced AMA values
  only (not local recomputation).
- The Phase 42 bakeoff only ran on BTC (asset_id=1) and ETH (asset_id=1027). Phase
  82 runs on all 99 assets — the `--all-assets` flag in `run_bakeoff.py` already
  supports this.

---

## Walk-Forward Methodology Decision

### Data Depth Analysis (3 years daily crypto)

- Total bars: ~1,095 (3 x 365)
- 10-fold purged K-fold: ~109 bars/fold (~4 months each)
- CPCV: C(10,2) = 45 combinations
- 20-bar embargo: 20 days between train and test (sufficient for 1D features)
- Min train set at fold 1: ~984 bars (9 folds)

**Verdict on 10 folds:** APPROPRIATE. Each fold has sufficient bars for PSR
(n >= 30). CPCV has 45 combinations for robust PBO estimate.

### Expanding vs Rolling Recommendation

For crypto (~3 years of data) with the Phase 82 objective of strategy selection:
- **Expanding window** is preferred as the primary test. Crypto regime shifts mean
  earlier data is less relevant, but expanding windows give maximum train data
  at each fold and avoid the "regime change cutoff" problem.
- **Rolling window** (e.g., 2-year IS, 1-year OOS) should be the secondary test.
  For 3-year data, this gives only 2-3 non-overlapping test periods — limited PBO power.
- **Practical recommendation:** Use the existing 10-fold purged K-fold as the
  primary expanding test. Add a rolling-window experiment as a secondary
  sensitivity check using `splitters.expanding_walk_forward()`.

### Refit Policy Recommendation

- **Train-once-evaluate-forward** is the existing behavior. This is the correct
  baseline for Phase 82 because signals are composite rules (not ML models with
  hyperparameters to re-tune).
- **Refit-at-each-fold** makes sense only if there are parameters to optimize.
  For IC-IR weighted composites, re-compute IC-IR weights on training fold data.
  For expression engine rule-based signals, refit is not meaningful.
- **Practical recommendation:** Test refit only for per-asset IC-IR weight
  computation (recalculate weights within each fold's train window). Keep signal
  thresholds fixed.

---

## Per-Asset Feature Weighting

### IC-IR Variation from Phase 80

Phase 80 found significant per-asset IC-IR variation for AMA features (this is
inherent to adaptive MAs — they perform differently across trending vs mean-
reverting assets). The `ic_results` table has per-asset rows (keyed by `asset_id`).

### Overfitting Risk Assessment

Using IC-IR weights from the full history as a signal weight is in-sample. To
compare fairly:

1. **Universal baseline:** Same IC-IR weights (from `feature_selection.yaml`) for
   all assets. IC-IR values: TEMA_0fca19a1=1.433, DEMA_0fca19a1=1.376, etc.
2. **Per-asset weights (held-out):** Compute IC-IR for each asset on data prior
   to the bake-off window (e.g., year 1), then apply fixed per-asset weights for
   years 2-3 bake-off.
3. **Per-asset weights (walk-forward):** Within each fold, compute IC-IR on the
   fold's training window. Apply to test window. This is leakage-free but adds
   complexity.

**Recommendation for Phase 82:** Run (1) universal and (3) walk-forward per-asset
as the two primary experiments. Compare OOS performance. If walk-forward per-asset
outperforms by > 10% Sharpe, adopt it. If not, universal weights are simpler and
more robust.

### Handling Assets with Insufficient History

The Phase 80 IC analysis flagged many assets as `INSUFFICIENT_DATA`. For walk-forward,
apply the existing `min_bars=300` guard per asset. Assets with < 300 bars in
`ama_multi_tf` for the given (indicator, params_hash) are skipped.

---

## Swing Trading Holding Period Optimization

### IC Decay Analysis (from ic.py, Phase 80 infrastructure)

The existing IC evaluation uses horizons `[1, 2, 3, 5, 10, 20, 60]` bars. For
AMA features (adaptive MAs), the IC typically peaks at horizon 3-10 bars for
daily crypto and decays at longer horizons (AMA captures medium-term momentum).

**Practical holding period guidance:**
- AMA value features (TEMA, DEMA, HMA, KAMA ama column): IC peaks at ~5-10 bars
  → optimal swing holding: 5-10 days
- AMA derivative features (d1 column): IC peaks at 1-3 bars → short-term momentum
- bar-level features (bb_ma_20, close_fracdiff): check IC decay per feature

**Implementation:** In `build_t1_series(holding_bars=N)`, set N based on the
dominant feature's IC decay peak. For AMA momentum strategies: N=5 to N=10.
The `BakeoffOrchestrator.run()` calls `build_t1_series(holding_bars=1)` by default
— this should be parameterized.

**Holding period parameter in bake-off:** Add `holding_bars` to the param grid
for AMA-based signal functions. This lets the walk-forward select the optimal
holding period per asset per strategy.

---

## Statistical Gates Calibration

### DSR Threshold Analysis

The DSR threshold of 0.95 (CONTEXT.md default) means: "95% probability that the
best strategy's true Sharpe > E[max_SR across all trials]."

**Calibration for Phase 82:**
- Estimated number of strategy trials: 3 archetypes x ~4 param sets x 2 window
  types = ~24 trials per asset, plus regime router experiments = ~30-40 total.
- At 30-40 trials, `expected_max_sr()` raises the bar significantly.
- DSR 0.95 is appropriate. Lowering to 0.90 is acceptable if no strategies pass
  (let data decide, per CONTEXT.md).

**Practical guidance:** Run all experiments, compute DSR across the pool, then
check the distribution. If 0 strategies pass DSR > 0.95, check:
- Is the strategy pool genuine (30+ trials)?
- Is there sufficient OOS data (n_obs > 300)?
- If both yes: DSR correctly filtering poor results. Consider ensemble.

### PBO Gate

PBO < 0.50 means the strategy beats the median more than 50% of CPCV combinations.
This is the existing gate. The `run_cpcv_backtest()` computes a simplified PBO as:
`n_folds_below_median / total_folds`. The full PBO path-matrix construction is not
implemented (noted as DEFERRED in bakeoff_orchestrator docstring).

**Additional gates to consider:**
- **Min trade count:** At least 50 trades total across all folds. Low trade count
  inflates Sharpe noise.
- **Max drawdown cap:** Existing V1 gate is -15%. Keep this for Phase 82.
- **Turnover reasonableness:** Flag if `turnover` (trades/bar) > 0.5 for daily
  swing trading (that's mean-reversion frequency, not swing).

---

## Experiment Lineage in backtest_metrics

Phase 82 CONTEXT.md requires: "persisted to backtest_metrics with experiment
lineage." The existing `bakeoff_orchestrator._persist_results()` writes to
`strategy_bakeoff_results` (NOT `backtest_metrics`). Two options:

1. **Write to `strategy_bakeoff_results` (existing)** and add a linkage column
   `experiment_name` (VARCHAR) to track which YAML experiment generated the run.
2. **Write summary to `backtest_metrics`** after bake-off completion, linking
   `backtest_run_id` → `strategy_bakeoff_results` row.

**Recommendation:** Option 1 is simpler. Add an `experiment_name` VARCHAR column
to `strategy_bakeoff_results` via Alembic migration. The planner should create a
migration task for this.

---

## Open Questions

1. **Holding period parameter in BakeoffConfig**
   - What we know: `build_t1_series(holding_bars=1)` is hardcoded in
     `BakeoffOrchestrator.run()`.
   - What's unclear: Whether to add `holding_bars` to `BakeoffConfig` or to the
     per-strategy param grid.
   - Recommendation: Add to per-strategy param grid (`{"holding_bars": 5}` etc.).
     This allows per-strategy optimization within the existing loop.

2. **`experiment_name` migration for strategy_bakeoff_results**
   - What we know: The table exists and has a fixed schema.
   - What's unclear: Whether a migration is safe given existing Phase 42 data.
   - Recommendation: Use `ALTER TABLE ... ADD COLUMN experiment_name VARCHAR(100)
     DEFAULT NULL` — safe, no existing data lost.

3. **IC decay peak for AMA features in this dataset**
   - What we know: IC horizons [1,2,3,5,10,20,60] are computed. Phase 80 did not
     surface the peak horizon for AMA features specifically.
   - What's unclear: Whether 5-day or 10-day holding is empirically better.
   - Recommendation: Run `run_ic_decay.py` for `TEMA_0fca19a1_ama` and
     `KAMA_de1106d5_ama` before fixing holding period. This takes <10 minutes.

4. **Per-asset IC-IR query performance**
   - What we know: `ic_results` has ~99 assets x 20 features x 7 horizons x 2
     return types = ~27,720 rows. Loading all is fast.
   - What's unclear: Whether `ic_results` has an index on `(asset_id, feature, tf)`.
   - Recommendation: Planner should add a verification task to check/add index.

---

## Sources

### Primary (HIGH confidence)

- Codebase: `src/ta_lab2/backtests/bakeoff_orchestrator.py` — full bakeoff implementation, Kraken cost matrix, BakeoffConfig defaults
- Codebase: `src/ta_lab2/ml/expression_engine.py` — OPERATOR_REGISTRY, evaluate_expression()
- Codebase: `src/ta_lab2/ml/regime_router.py` — RegimeRouter, TRA pattern, Qlib reference
- Codebase: `src/ta_lab2/backtests/psr.py` — compute_psr, compute_dsr, Pearson kurtosis convention
- Codebase: `src/ta_lab2/backtests/cv.py` — PurgedKFoldSplitter, CPCVSplitter
- Codebase: `src/ta_lab2/backtests/costs.py` — CostModel dataclass
- Codebase: `src/ta_lab2/scripts/backtests/run_bakeoff.py` — CLI, param grids, strategy registry
- Codebase: `src/ta_lab2/scripts/ml/run_regime_routing.py` — regime router CLI, features-only loading gap
- Codebase: `configs/feature_selection.yaml` — 20 active features with IC-IR values
- Codebase: `configs/experiments/features.yaml` — YAML experiment pattern with AMA params_hash map
- Official docs: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees — Hyperliquid fee tiers (fetched 2026-03-22)

### Secondary (MEDIUM confidence)

- WebSearch verified with official source: Hyperliquid BTC funding rate ~0.0097%/8h (Q3 2025, Coinalyze/Pandabull data)
- Phase 80 research: `.planning/phases/80-ic-analysis-feature-selection/80-RESEARCH.md` — IC infrastructure details

### Tertiary (LOW confidence)

- WebSearch: Walk-forward expanding vs rolling best practices — general quant literature; apply critically to this specific dataset

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in codebase, no new dependencies needed
- Architecture: HIGH — all patterns verified from running code
- Hyperliquid cost matrix: HIGH (fee structure) / MEDIUM (funding rate from Q3 2025 Coinalyze data)
- Pitfalls: HIGH — verified from codebase inspection of existing implementation
- Walk-forward methodology: MEDIUM — general quant practice, validated against data depth calculations

**Research date:** 2026-03-22
**Valid until:** 2026-06-22 (stable; Hyperliquid fee tiers may change on HL governance vote)
