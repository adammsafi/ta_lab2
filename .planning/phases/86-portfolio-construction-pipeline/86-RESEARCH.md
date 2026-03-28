# Phase 86: Portfolio Construction Pipeline - Research

**Researched:** 2026-03-23
**Domain:** End-to-end portfolio construction: Black-Litterman with per-asset IC-IR, GARCH target-vol sizing, MAE/MFE stop calibration, parity-tested dry run
**Confidence:** HIGH (all modules verified from codebase; external patterns from Phase 81/82 research)

---

## Summary

Phase 86 wires together components that were built across Phases 58 (portfolio/), 45
(executor/), 81 (GARCH), and 82 (bake-off winners). The infrastructure is almost
entirely in place. The three critical gaps that Phase 86 must close:

1. **BL views currently use signal-type IC-IR (universal), not per-asset IC-IR.**
   The existing `BLAllocationBuilder.signals_to_mu()` and `build_views()` take
   `ic_ir: pd.Series` indexed by signal type (e.g. `{'rsi': 0.5, 'ema_cross': 0.3}`).
   Phase 86 must add a per-asset path: for each asset, look up its own IC-IR row from
   `ic_results` and pass a per-asset `ic_ir` Series to the BL builder. The function
   `load_per_asset_ic_weights()` in `bakeoff_orchestrator.py` already loads the
   right shape (DataFrame: asset_id x feature -> ic_ir). A new wrapper in the
   portfolio refresh script must pivot this into per-asset Series calls.

2. **GARCH-informed bet sizing does not exist yet in the executor path.**
   The existing `PositionSizer` uses `fixed_fraction`, `regime_adjusted`, or
   `signal_strength` sizing modes. None incorporate GARCH vol. The `garch_blend.py`
   module exposes `get_blended_vol(asset_id, venue_id, tf, engine)` which reads
   `garch_forecasts_latest`. Phase 86 must add a `target_vol` sizing mode: given
   a target annualized vol (stored in `dim_executor_config`), the position size is
   `target_vol / current_vol * reference_position`. The recommended approach is to
   add a `target_annual_vol NUMERIC DEFAULT NULL` column to `dim_executor_config`
   via a new Alembic migration, and extend `PositionSizer.compute_target_position()`
   with a `target_vol` branch.

3. **Stop ladder is config-driven (YAML) not calibrated from MAE/MFE data.**
   The existing `StopLadder` reads `sl_stops`/`tp_stops` from `portfolio.yaml`. Phase
   82 bake-off winners produced MAE/MFE data in `backtest_trades` (columns `mae`,
   `mfe` added in migration `b2c3d4e5f6a1`). A new `stop_calibrations` table and a
   calibration script must read percentiles from bake-off trade MAE/MFE per
   (asset_id, strategy) and write derived stop levels. The `StopLadder`'s
   `per_asset_overrides` dict can then be seeded from `stop_calibrations` at
   runtime rather than from YAML.

**Primary recommendation:** Build Phase 86 as four sequential tasks: (1) per-asset
IC-IR loader for BL, (2) target-vol sizing mode + `dim_executor_config` migration,
(3) MAE/MFE stop calibration table + seeding script, (4) parity dry-run wired to
bake-off winners. Each task is independently verifiable.

---

## Standard Stack

### Core (all already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pypfopt` | existing | Black-Litterman, EfficientFrontier | Already wired in `portfolio/black_litterman.py` + `optimizer.py` |
| `arch` | 8.0.0 | GARCH conditional vol forecasts | Phase 81 built `garch_engine.py`, `garch_blend.py` |
| `scipy.stats` | existing | `norm.cdf` for bet sizing | `bet_sizing.py` depends on it |
| `pandas` | existing | IC-IR matrix operations, stop calibration | Core everywhere |
| `numpy` | existing | Vol math, pct change | Core everywhere |
| `SQLAlchemy` | >=2.0 | All DB reads/writes | NullPool for batch scripts |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `PyYAML` | existing | `portfolio.yaml` config loading | `load_portfolio_config()` |
| `vectorbt` | 0.28.1 | Stop sweep simulation | `stop_simulator.py` uses for stop-level validation |
| `statsmodels` | existing | Ljung-Box diagnostics (GARCH quality gate) | Inherited from Phase 81 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Target-vol sizing in `PositionSizer` | Kelly-fraction sizing | Kelly requires win probability + payoff ratio per trade, which is not directly available from IC-IR scores. Target-vol is simpler and maps cleanly to GARCH conditional vol output. |
| Per-asset IC-IR from `ic_results` | Universal IC-IR from `feature_selection.yaml` | Universal is simpler but Phase 80 explicitly found per-asset variation matters; per-asset is the hard requirement. |
| `stop_calibrations` table | Update `portfolio.yaml` per-asset-overrides | YAML approach is not auditable and cannot be refreshed automatically from bake-off data. Table approach is auto-seeded and DB-native. |

**Installation:** No new packages needed. All required dependencies already present.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
  portfolio/
    black_litterman.py        # EXTEND: add per-asset ic_ir dispatch path
    stop_ladder.py            # EXTEND: add seed_from_db() classmethod
  executor/
    position_sizer.py         # EXTEND: add target_vol sizing mode
  scripts/
    portfolio/
      refresh_portfolio_allocations.py  # EXTEND: per-asset IC-IR + GARCH vol
      calibrate_stops.py                # NEW: MAE/MFE -> stop_calibrations
    executor/
      run_paper_executor.py             # EXTEND: dry-run + parity report path
  analysis/
    stop_calibration.py       # NEW: MAE percentile -> stop level derivation

alembic/versions/
  l6m7n8o9p0q1_phase86_portfolio_pipeline.py  # NEW: target_annual_vol + stop_calibrations
```

### Pattern 1: Per-Asset IC-IR for Black-Litterman Views

**What:** Load per-asset IC-IR from `ic_results` and call `BLAllocationBuilder.build_views()`
once per asset (not once globally with universal weights).

**When to use:** Every portfolio rebalance when IC data is available.

**Design decision:** The existing `BLAllocationBuilder` takes `ic_ir: pd.Series`
indexed by signal_type. To support per-asset weights, the refresh script must load
the per-asset weight matrix (DataFrame: asset_id x feature), then for each asset
extract its IC-IR row and pass it as the `ic_ir` argument. The BL builder itself
does NOT need modification -- only the calling script changes.

**Key function (already built in Phase 82, verify it's in `bakeoff_orchestrator.py`):**

```python
# Source: src/ta_lab2/backtests/bakeoff_orchestrator.py (verified, line 765)
from ta_lab2.backtests.bakeoff_orchestrator import load_per_asset_ic_weights

# Returns DataFrame: index=asset_id, columns=feature_names, values=normalized ic_ir
ic_weight_matrix = load_per_asset_ic_weights(
    engine=engine,
    features=ACTIVE_FEATURE_NAMES,   # from configs/feature_selection.yaml
    tf="1D",
    horizon=1,
    return_type="arith",
)
# ic_weight_matrix.loc[asset_id] -> per-asset ic_ir Series
```

**Per-asset BL dispatch in refresh script:**

```python
# For each asset in the portfolio:
for asset_id in asset_ids:
    if asset_id in ic_weight_matrix.index:
        per_asset_ic_ir = ic_weight_matrix.loc[asset_id]  # pd.Series, index=feature
    else:
        # Fallback: universal IC-IR from feature_selection.yaml
        per_asset_ic_ir = universal_ic_ir  # pd.Series loaded from YAML

    # signal_scores for this asset: 1 row (single asset), columns=features
    asset_signal_scores = signal_score_matrix.loc[[asset_id]]

    bl_builder.build_views(asset_signal_scores, per_asset_ic_ir)
```

**CRITICAL NOTE:** The current `BLAllocationBuilder.run()` accepts a single `ic_ir`
Series used for ALL assets simultaneously (the signal_scores matrix has multiple
assets as rows). To properly use per-asset IC-IR, there are two approaches:
- (a) Run BL separately per asset -- less efficient but simpler; portfolio weights
  are then aggregated.
- (b) Extend `BLAllocationBuilder.run()` to accept a DataFrame ic_ir indexed by
  asset_id.

Recommended: approach (b). Add an optional `ic_ir_matrix: pd.DataFrame | None`
parameter to `BLAllocationBuilder.run()`. When provided, dispatch per-asset views
using each asset's row. When None, fall back to current signal-type behavior.

### Pattern 2: Target-Vol Sizing with GARCH Forecast

**What:** Position size = (target_annual_vol / current_garch_vol) * base_fraction.
This keeps expected portfolio vol near the target regardless of asset-level vol
regime.

**Schema change needed:**

```sql
-- New column in dim_executor_config
ALTER TABLE public.dim_executor_config
  ADD COLUMN target_annual_vol NUMERIC DEFAULT NULL;
-- NULL = disabled; non-null enables target-vol mode
-- Example: 1.20 = target 120% annualized vol (high-conviction, concentrated)
```

**PositionSizer extension:**

```python
# Source: src/ta_lab2/executor/position_sizer.py (extend compute_target_position)
# New sizing_mode = 'target_vol'

elif sizing_mode == "target_vol":
    target_ann_vol = getattr(config, "target_annual_vol", None)
    if target_ann_vol is None or target_ann_vol <= 0:
        # Fall through to fixed_fraction if target_vol not configured
        pass
    else:
        # Get GARCH blended vol for this asset
        garch_result = get_blended_vol(asset_id, venue_id=1, tf="1D", engine=conn_engine)
        if garch_result is not None:
            current_ann_vol = garch_result["blended_vol"] * (252 ** 0.5)  # daily -> annual
            if current_ann_vol > 1e-6:
                vol_scalar = target_ann_vol / current_ann_vol
                fraction = Decimal(str(config.position_fraction)) * Decimal(str(vol_scalar))
```

**CRITICAL:** `get_blended_vol()` takes an SQLAlchemy Engine, not a connection.
The `PositionSizer` currently only receives a `conn` argument in static methods.
The cleanest solution is to pass the engine as a new optional parameter to
`compute_target_position()`, defaulting to None (disabling target_vol mode when
no engine is provided). Do NOT construct an engine inside the position sizer --
this violates the project pattern of passing connections from outside.

**Practical alternative (recommended for Phase 86):** Load GARCH vols in the
executor's `_process_asset_signal()` loop (where the engine is available) and pass
as `garch_vol_override` to `compute_target_position()`. This avoids modifying the
static method signature to accept an engine.

### Pattern 3: MAE/MFE Stop Calibration

**What:** Read `mae` and `mfe` from `backtest_trades` for each (asset_id, strategy),
compute percentile-based stop levels, write to a new `stop_calibrations` table,
then seed `StopLadder`'s per-asset-strategy overrides from that table at runtime.

**New table schema:**

```sql
CREATE TABLE public.stop_calibrations (
    id                  INTEGER NOT NULL,
    strategy            TEXT    NOT NULL,
    sl_p25              NUMERIC,   -- 25th percentile of |MAE|  (tight stop)
    sl_p50              NUMERIC,   -- 50th percentile of |MAE|  (medium stop)
    sl_p75              NUMERIC,   -- 75th percentile of |MAE|  (wide stop)
    tp_p50              NUMERIC,   -- 50th percentile of MFE    (conservative TP)
    tp_p75              NUMERIC,   -- 75th percentile of MFE    (aggressive TP)
    n_trades            INTEGER,
    calibrated_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, strategy)
);
```

**Calibration logic (new `analysis/stop_calibration.py`):**

```python
# Source: analysis/mae_mfe.py pattern (compute_mae_mfe already adds mae/mfe cols)
# Reads from backtest_trades (columns: mae, mfe already present from migration b2c3d4e5f6a1)

def calibrate_stops_from_mae_mfe(
    engine: Engine,
    asset_id: int,
    strategy: str,
    signal_id: int,
) -> dict:
    """
    Compute stop levels from MAE/MFE percentiles for a single (asset, strategy).

    Returns dict with sl_p25, sl_p50, sl_p75, tp_p50, tp_p75.
    Returns None if fewer than MIN_TRADES_FOR_CALIBRATION trades exist.
    """
    sql = text("""
        SELECT ABS(bt.mae) AS abs_mae, bt.mfe
        FROM public.backtest_trades bt
        JOIN public.backtest_runs br ON bt.run_id = br.run_id
        WHERE br.asset_id = :asset_id
          AND br.signal_id = :signal_id
          AND bt.mae IS NOT NULL
          AND bt.mfe IS NOT NULL
    """)
    # ... load, compute percentiles via np.nanpercentile
```

**Seeding `StopLadder` from DB at runtime:**

The existing `StopLadder` reads from YAML. Add a classmethod:

```python
# In stop_ladder.py
@classmethod
def from_db_calibrations(cls, engine: Engine, config: dict | None = None) -> "StopLadder":
    """Load stop ladder with per-asset overrides seeded from stop_calibrations table."""
    ladder = cls(config=config)
    # Query stop_calibrations
    # For each row, construct overrides in format {"{asset_id}:{strategy}": {...}}
    # Merge into ladder._per_asset
    return ladder
```

### Pattern 4: Dry Run Parity Test

**What:** Run `PaperExecutor` in `replay_historical=True` mode over the bake-off
date range, then run `ParityChecker.check()` to compare fills vs backtest trades.

**Parity definition (from CONTEXT.md):** Same trade direction and timing. Fill price
is secondary. The existing `ParityChecker._evaluate_parity()` with `slippage_mode='fixed'`
checks P&L correlation >= 0.99 -- this is appropriate for the phase.

**Date range for dry run:** Use the last OOS fold from the Phase 82 bake-off (most
recent ~4 months of data). The executor's `replay_start`/`replay_end` parameters
support this directly.

**The parity checker gap:** `ParityChecker._load_backtest_trades()` joins on
`br.signal_id` but Phase 82 bake-off results are in `strategy_bakeoff_results`
(not `backtest_trades`). The Phase 82 winners need to be linked to actual
`backtest_runs`/`backtest_trades` records. Verify that Phase 82's bake-off
orchestrator wrote to `backtest_trades` (via `_persist_results()`) -- if so,
`br.signal_id` should be set on those rows. If not, the parity checker may need
to use `strategy_bakeoff_results.strategy_name` for matching.

**Parity script call pattern:**

```python
# Source: src/ta_lab2/executor/parity_checker.py (verified, line 51)
from ta_lab2.executor.parity_checker import ParityChecker

checker = ParityChecker(engine)

# Step 1: replay executor over bake-off OOS window
executor = PaperExecutor(engine)
executor.run(
    dry_run=False,                     # write fills to DB for comparison
    replay_historical=True,
    replay_start="2025-09-01",         # last 6 months of bake-off
    replay_end="2025-12-31",
)

# Step 2: check parity per signal_id (bake-off winner)
for signal_id in bakeoff_winner_signal_ids:
    report = checker.check(
        config_id=None,
        signal_id=signal_id,
        start_date="2025-09-01",
        end_date="2025-12-31",
        slippage_mode="fixed",    # tolerates fill price divergence
    )
    print(checker.format_report(report))
    # parity_pass=True requires pnl_correlation >= 0.99
```

### Recommended Project Structure (full)

```
src/ta_lab2/
  analysis/
    stop_calibration.py              # NEW: MAE percentile -> stop level derivation
  portfolio/
    black_litterman.py               # EXTEND: ic_ir_matrix parameter in run()
    stop_ladder.py                   # EXTEND: from_db_calibrations() classmethod
  executor/
    position_sizer.py                # EXTEND: target_vol sizing mode
  scripts/
    portfolio/
      refresh_portfolio_allocations.py  # EXTEND: per-asset IC-IR + GARCH vol injection
      calibrate_stops.py               # NEW: reads bake-off MAE/MFE, writes stop_calibrations
    executor/
      run_parity_check.py              # EXTEND: add --bakeoff-winners flag

alembic/versions/
  l6m7n8o9p0q1_phase86_portfolio_pipeline.py
    # Creates stop_calibrations table
    # Adds target_annual_vol NUMERIC DEFAULT NULL to dim_executor_config
    # Adds CHECK constraint: target_annual_vol > 0 when not NULL
```

### Anti-Patterns to Avoid

- **Anti-pattern -- universal IC-IR as BL views:** The current `refresh_portfolio_allocations.py`
  passes `ic_ir = pd.Series({"rsi": 0.0})` as a stub. This must be replaced with real
  per-asset IC-IR from `ic_results`. Using zero IC-IR causes BL to return prior-only
  weights (bypasses the entire signal-driven allocation).

- **Anti-pattern -- target_vol sizing without GARCH fallback:** If `garch_forecasts_latest`
  has no rows for an asset (e.g., convergence failures, new assets), the target_vol
  sizing must fall back gracefully to `fixed_fraction`. Never raise or return zero
  position because GARCH is unavailable.

- **Anti-pattern -- constructing Engine inside PositionSizer:** The sizer receives a
  `conn` argument from outside. Adding `create_engine()` inside a static method
  creates per-call connections (connection leak). Pass engine as a top-level parameter
  from `_process_asset_signal()`.

- **Anti-pattern -- stop calibration with < 30 trades:** MAE percentiles are noisy
  with few trades. Gate calibration at `MIN_TRADES_FOR_CALIBRATION = 30`. For assets
  with fewer trades, use the global defaults from `portfolio.yaml`.

- **Anti-pattern -- using signal_scores of shape (1, n_features) for BL run():**
  The `BLAllocationBuilder.run()` currently expects `signal_scores` with multiple
  assets as index. When called per-asset with a single-row DataFrame, the
  cross-sectional z-score in `signals_to_mu()` will be degenerate (zero variance).
  Handle by passing all assets at once with the per-asset IC-IR matrix.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GARCH conditional vol | Custom EWMA vol estimator | `get_blended_vol()` from `garch_blend.py` | Phase 81 built multi-variant GARCH with inverse-RMSE blending; already handles convergence failures |
| BL optimization | Custom weighted average | `BLAllocationBuilder.run()` | PyPortfolioOpt's BlackLittermanModel + EfficientFrontier handles posterior math |
| Per-asset IC-IR loading | Custom SQL pivot | `load_per_asset_ic_weights()` from `bakeoff_orchestrator.py` | Already handles fallback to universal weights, handles NaN |
| Stop level calibration math | Custom percentile logic | `np.nanpercentile` + MAE/MFE cols from `backtest_trades` | Straightforward; the data structure is already there |
| Parity comparison | Custom fill diff logic | `ParityChecker.check()` | Handles zero/fixed/lognormal slippage modes with proper PnL correlation |
| Portfolio optimizer | Custom MV | `PortfolioOptimizer.run_all()` | HRP fallback when covariance is ill-conditioned; regime routing already wired |

**Key insight:** Every algorithmic component for Phase 86 is already implemented. The
work is wiring (data flow between existing modules) and schema extension, not
new algorithm development.

---

## Common Pitfalls

### Pitfall 1: BL Build-Views Called with Signal-Type IC-IR Instead of Per-Asset

**What goes wrong:** BL posterior returns are heavily influenced by signal-type
IC-IR (e.g., RSI IC-IR = 0.8 means all RSI signals dominate BL views for all
assets). Phase 80 showed per-asset variation is real and material.

**Why it happens:** The stub in `refresh_portfolio_allocations.py` (line 526) passes
`ic_ir = pd.Series({"rsi": 0.0})` -- this was a placeholder from Phase 58. It was
never replaced with real data.

**How to avoid:** Replace the stub with the real `load_per_asset_ic_weights()` call.
The feature names must match what's in `ic_results` -- use the 20 active features
from `configs/feature_selection.yaml`.

**Warning signs:** `BLAllocationBuilder.run()` logs "no views passed the IC-IR
threshold; returning prior-only EfficientFrontier weights." This means ic_ir values
are all <= `_MIN_IC_IR_FOR_VIEW = 0.1`.

### Pitfall 2: GARCH Vol Not Annualized Correctly

**What goes wrong:** `garch_forecasts_latest.cond_vol` is per-bar conditional
volatility (daily decimal). Sizing with it directly without annualizing yields
positions ~15x too large.

**Why it happens:** `cond_vol` from `arch` is the conditional standard deviation of
returns over one bar. For 1D bars: annualized = `cond_vol * sqrt(252)`.

**How to avoid:** Always multiply `blended_vol` from `get_blended_vol()` by
`sqrt(252)` before computing the vol scalar for target_vol sizing.

**Warning signs:** Target sizes enormously larger than expected; portfolio gross
exposure crashes into `max_gross_exposure` cap on every bar.

### Pitfall 3: PaperExecutor Replay Overwrites Watermark

**What goes wrong:** Running `PaperExecutor.run(replay_historical=True)` in
production mode (not dry_run) advances `last_processed_signal_ts` in
`dim_executor_config` to the end of the replay period. This causes the live executor
to skip real-time signals after the replay.

**Why it happens:** The watermark update in `_run_strategy()` runs unconditionally
when `dry_run=False`.

**How to avoid:** Always run historical replay with `dry_run=False` only in a
separate test config_id (not the production `is_active=True` config). Add a
`--config-id` CLI flag to `run_paper_executor.py` to target a specific config.
Alternatively, snapshot the watermark before replay and restore it after.

**Warning signs:** After parity replay, live executor reports zero signals to process
for several days.

### Pitfall 4: price_bars_multi_tf_u Uses 'timestamp' Not 'ts'

**What goes wrong:** `pd.read_sql()` on `price_bars_multi_tf_u` fails to find
column `ts` -- queries return empty or error.

**Why it happens:** This table uses `timestamp` as the datetime column name (see
CRITICAL comment in `refresh_portfolio_allocations.py`, line 8). All other tables
use `ts`.

**How to avoid:** Always use `timestamp` when querying `price_bars_multi_tf_u`.
This is already handled correctly in the existing `_load_price_matrix()` function.

**Warning signs:** `KeyError: 'ts'` when pivoting the price matrix.

### Pitfall 5: StopLadder Per-Asset Overrides Key Format

**What goes wrong:** Stop overrides loaded from `stop_calibrations` table don't
match the expected key format and are silently ignored.

**Why it happens:** `StopLadder.get_tiers()` looks up `per_asset_overrides` using
key `str(asset_id)` for asset-only override and `f"{asset_id}:{strategy}"` for
combined key. If the calibration script writes keys in wrong format (e.g., using
symbol instead of integer id), overrides are never applied.

**How to avoid:** Always store keys in `stop_calibrations` as integer `id` matching
`dim_assets.id`. When seeding `_per_asset`, build keys as `str(id)` and
`f"{id}:{strategy}"`.

**Warning signs:** All assets use default stop levels despite `stop_calibrations`
having rows. Verify by calling `ladder.get_tiers(asset_id, strategy)` and
checking which override layer was applied.

### Pitfall 6: ic_results Feature Names Must Match AMA Column Naming Convention

**What goes wrong:** `load_per_asset_ic_weights(features=["TEMA_0fca19a1_ama", ...])`
returns an empty DataFrame because `ic_results.feature` stores bare names without
the `_ama` suffix (e.g., `"TEMA_0fca19a1"`) -- or vice versa.

**Why it happens:** Phase 80 IC analysis named features based on the column alias
used during feature loading. The exact naming depends on whether `_ama` suffix was
included during IC computation.

**How to avoid:** Before calling `load_per_asset_ic_weights()`, run a verification
query: `SELECT DISTINCT feature FROM ic_results WHERE feature LIKE 'TEMA%' LIMIT 5`
to confirm the naming convention. The planner should create a verification step.

---

## Code Examples

### Per-Asset IC-IR BL Integration (in refresh_portfolio_allocations.py)

```python
# Source: bakeoff_orchestrator.py load_per_asset_ic_weights (verified, line 765)
# Replace the stub in refresh_portfolio_allocations.py

from ta_lab2.backtests.bakeoff_orchestrator import load_per_asset_ic_weights
from ta_lab2.portfolio import BLAllocationBuilder

# Load the 20 active feature names from feature_selection.yaml
ACTIVE_FEATURES = [
    "TEMA_0fca19a1_ama", "DEMA_0fca19a1_ama", "KAMA_987fc105_ama",
    "HMA_514ffe35_ama",  "TEMA_514ffe35_ama", "TEMA_018899b6_ama",
    "DEMA_514ffe35_ama", "HMA_018899b6_ama",  "DEMA_d47fe5cc_ama",
    "DEMA_018899b6_ama", "KAMA_de1106d5_ama", "DEMA_a4b71eb4_ama",
    "TEMA_a4b71eb4_ama", "TEMA_d47fe5cc_ama", "KAMA_8545aeed_ama",
    "HMA_d47fe5cc_ama",  "HMA_a4b71eb4_ama",
    "ret_is_outlier", "bb_ma_20", "close_fracdiff",
]

# Load per-asset IC-IR matrix
ic_weight_matrix = load_per_asset_ic_weights(
    engine=engine,
    features=ACTIVE_FEATURES,
    tf="1D",
    horizon=1,
    return_type="arith",
)
# ic_weight_matrix: DataFrame, index=asset_id, cols=features, values=normalized ic_ir

# Add ic_ir_matrix parameter to BLAllocationBuilder.run()
bl_builder = BLAllocationBuilder(config=config)
bl_result = bl_builder.run(
    prices=prices,
    market_caps=market_caps,
    signal_scores=signal_scores,         # asset_id x feature matrix
    ic_ir=ic_weight_matrix,              # CHANGED: now passes DataFrame not Series
    base_vol=base_vol,
    S=result.get("S"),
    tf=tf,
)
```

### GARCH Target-Vol Sizing Mode

```python
# Source: vol_sizer.compute_realized_vol_position pattern (verified)
# New branch in position_sizer.py compute_target_position()

elif sizing_mode == "target_vol":
    target_ann_vol = getattr(config, "target_annual_vol", None)
    garch_vol_override = kwargs.get("garch_vol")  # passed from _process_asset_signal
    if target_ann_vol and target_ann_vol > 0 and garch_vol_override:
        # garch_vol_override is daily decimal vol from get_blended_vol()
        current_ann_vol = float(garch_vol_override) * (252 ** 0.5)
        vol_scalar = float(target_ann_vol) / max(current_ann_vol, 1e-6)
        fraction = Decimal(str(config.position_fraction)) * Decimal(str(vol_scalar))
        # Clamp to max_fraction
        if fraction > max_fraction:
            fraction = max_fraction
    else:
        # Fallback: fixed_fraction behavior
        fraction = Decimal(str(config.position_fraction))
```

### MAE/MFE Stop Calibration

```python
# Source: analysis/mae_mfe.py pattern (verified), backtest_trades.mae/mfe columns exist
# New file: analysis/stop_calibration.py

import numpy as np
from sqlalchemy import text

MIN_TRADES_FOR_CALIBRATION = 30

def calibrate_stops_from_mae_mfe(
    engine,
    asset_id: int,
    strategy: str,
    signal_id: int,
) -> dict | None:
    """Read backtest_trades MAE/MFE for (asset_id, signal_id), return stop levels."""
    sql = text("""
        SELECT ABS(bt.mae) AS abs_mae, bt.mfe
        FROM public.backtest_trades bt
        JOIN public.backtest_runs br ON bt.run_id = br.run_id
        WHERE br.asset_id   = :asset_id
          AND br.signal_id  = :signal_id
          AND bt.mae IS NOT NULL
          AND bt.mfe IS NOT NULL
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"asset_id": asset_id, "signal_id": signal_id}).fetchall()

    if len(rows) < MIN_TRADES_FOR_CALIBRATION:
        return None

    abs_mae = np.array([float(r[0]) for r in rows])
    mfe = np.array([float(r[1]) for r in rows])

    return {
        "sl_p25": float(np.nanpercentile(abs_mae, 25)),  # tight stop
        "sl_p50": float(np.nanpercentile(abs_mae, 50)),  # medium stop
        "sl_p75": float(np.nanpercentile(abs_mae, 75)),  # wide stop
        "tp_p50": float(np.nanpercentile(mfe, 50)),      # conservative TP
        "tp_p75": float(np.nanpercentile(mfe, 75)),      # aggressive TP
        "n_trades": len(rows),
    }
```

### Parity Dry Run

```python
# Source: executor/parity_checker.py (verified, full API described above)
# New CLI script: scripts/executor/run_parity_check.py

from ta_lab2.executor.paper_executor import PaperExecutor
from ta_lab2.executor.parity_checker import ParityChecker

# Step 1: Historical replay (use a test config_id separate from production)
executor = PaperExecutor(engine)
summary = executor.run(
    dry_run=False,
    replay_historical=True,
    replay_start="2025-09-01",
    replay_end="2026-01-01",
)

# Step 2: Parity check per bake-off winner
checker = ParityChecker(engine)
for signal_id in bakeoff_winners:
    report = checker.check(
        config_id=test_config_id,
        signal_id=signal_id,
        start_date="2025-09-01",
        end_date="2026-01-01",
        slippage_mode="fixed",   # tolerates fill price differences, checks P&L corr
    )
    print(checker.format_report(report))
    assert report["parity_pass"], f"Parity FAIL for signal_id={signal_id}"
```

---

## Critical Gaps: What Phase 86 Must Build vs What Already Exists

| Component | Status | Gap |
|-----------|--------|-----|
| `BLAllocationBuilder` (core math) | EXISTS | Add `ic_ir_matrix` DataFrame parameter for per-asset dispatch |
| Per-asset IC-IR loader | EXISTS in `bakeoff_orchestrator.py` | Wire into `refresh_portfolio_allocations.py` (replace stub) |
| GARCH vol lookup | EXISTS via `get_blended_vol()` | Add `target_vol` sizing mode to `PositionSizer` + GARCH vol injection in executor |
| `dim_executor_config.target_annual_vol` | MISSING | New Alembic migration |
| `stop_calibrations` table | MISSING | New Alembic migration + calibration script |
| `stop_ladder.from_db_calibrations()` | MISSING | New classmethod in `stop_ladder.py` |
| `StopLadder` config seeding from DB | MISSING | Seed at startup in `refresh_portfolio_allocations.py` |
| `PaperExecutor` replay + parity | EXISTS (both functions) | Wire into a single `run_parity_check.py` script with bake-off winner signal IDs |
| Daily pipeline wiring | PARTIAL | `run_portfolio_refresh_stage` exists; `calibrate_stops.py` needs to be added before it |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Universal IC-IR for BL views | Per-asset IC-IR from `ic_results` | Phase 86 (NEW) | Captures per-asset signal heterogeneity (Phase 80 finding) |
| Fixed-stop YAML configuration | MAE/MFE-calibrated per-asset stops | Phase 86 (NEW) | Stops match actual trade behavior instead of guesses |
| GARCH vol as advisory (sizing_only mode) | Target-vol as primary sizing mode | Phase 86 (NEW) | Consistent portfolio vol regardless of crypto regime |
| Stub zero IC-IR in BL | Real signal scores + IC-IR weights | Phase 86 (NEW) | BL actually uses signals instead of falling back to prior |

**Deprecated/outdated:**
- The `ic_ir = pd.Series({"rsi": 0.0})` stub in `refresh_portfolio_allocations.py`
  (line 526) -- this placeholder must be replaced with real IC-IR data.
- Using `position_fraction` alone for sizing when `target_annual_vol` is configured --
  the `target_vol` mode supersedes `fixed_fraction` for concentrated high-conviction portfolios.

---

## Open Questions

1. **Feature name format in ic_results vs AMA convention**
   - What we know: `ic_results.feature` is populated by Phase 80 IC sweeps. AMA
     features in the active tier use names like `TEMA_0fca19a1_ama`.
   - What's unclear: Whether the `_ama` suffix was included during Phase 80 IC
     computation (the IC sweep may have stripped suffixes for cleanliness).
   - Recommendation: Run `SELECT DISTINCT feature FROM ic_results WHERE feature LIKE
     'TEMA%' LIMIT 5` before coding the feature name list. The planner should add
     this as a verification task in Plan 01.

2. **Phase 82 backtest_trades linkage for parity check**
   - What we know: `ParityChecker` joins `backtest_trades` via `br.signal_id`. Phase
     82 bake-off results are in `strategy_bakeoff_results`. Whether Phase 82 also
     wrote to `backtest_runs`/`backtest_trades` depends on which persistence path was
     used.
   - What's unclear: Whether `_persist_results()` in `bakeoff_orchestrator.py` writes
     to `backtest_trades` or only to `strategy_bakeoff_results`.
   - Recommendation: Check `bakeoff_orchestrator._persist_results()` to see if it
     writes backtest_trades. If not, the parity checker either needs a new query
     path or Phase 82 needs to be re-run with `backtest_trades` persistence.

3. **`BLAllocationBuilder.run()` with per-asset ic_ir -- degenerate z-score**
   - What we know: `signals_to_mu()` computes cross-sectional z-score across all
     assets. If called with a single-asset DataFrame, std is 0 and z is undefined.
   - What's unclear: Whether to call BL once for all assets with the ic_ir_matrix or
     once per asset.
   - Recommendation: Call BL once for all assets. Extend `run()` to accept
     `ic_ir_matrix: DataFrame | None`. When provided, for each asset, the view
     confidence is derived from its row in `ic_ir_matrix`. The cross-sectional
     z-score still uses all assets together (single call).

4. **target_annual_vol value for concentrated portfolio**
   - What we know: CONTEXT.md says "annualized vol can exceed 100%" and "70% max
     single-position concentration".
   - What's unclear: What specific target_annual_vol value to seed in
     `dim_executor_config` for the Phase 86 test config.
   - Recommendation: Start with `target_annual_vol = 0.80` (80% annualized). With
     GARCH daily vol of ~3% for BTC (typical), this gives a 0.80 / (0.03 * sqrt(252))
     = 1.68x leverage factor on the base position_fraction. Monitor and adjust.

---

## Daily Pipeline Wiring

The existing `run_daily_refresh.py` pipeline order (verified at lines 3141-3197):

```
features -> GARCH forecasts -> regimes -> signals -> portfolio -> executor -> drift
```

Phase 86 additions:
- `calibrate_stops.py` runs AFTER signals and BEFORE portfolio refresh (must have
  latest bake-off trades to calibrate from).
- `refresh_portfolio_allocations.py` already exists in the pipeline; extend it to
  load per-asset IC-IR and inject GARCH vol.
- No new pipeline stage needed for parity check -- it's a one-time verification
  step, not a daily operation.

---

## Sources

### Primary (HIGH confidence)

- Codebase: `src/ta_lab2/portfolio/black_litterman.py` -- BLAllocationBuilder full API; ic_ir parameter semantics
- Codebase: `src/ta_lab2/portfolio/bet_sizing.py` -- BetSizer, probability_bet_size
- Codebase: `src/ta_lab2/portfolio/stop_ladder.py` -- StopLadder, get_tiers(), compute_exit_schedule()
- Codebase: `src/ta_lab2/portfolio/optimizer.py` -- PortfolioOptimizer.run_all(), regime routing
- Codebase: `src/ta_lab2/executor/paper_executor.py` -- PaperExecutor full flow, replay_historical params
- Codebase: `src/ta_lab2/executor/parity_checker.py` -- ParityChecker.check(), _evaluate_parity(), slippage modes
- Codebase: `src/ta_lab2/executor/position_sizer.py` -- ExecutorConfig, sizing_mode values, PositionSizer methods
- Codebase: `src/ta_lab2/analysis/garch_blend.py` -- get_blended_vol() API, garch_forecasts_latest query
- Codebase: `src/ta_lab2/analysis/vol_sizer.py` -- compute_realized_vol_position, GARCH blend modes
- Codebase: `src/ta_lab2/analysis/mae_mfe.py` -- compute_mae_mfe(), MAE/MFE column semantics
- Codebase: `src/ta_lab2/backtests/bakeoff_orchestrator.py` -- load_per_asset_ic_weights() API (line 765)
- Codebase: `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` -- full pipeline script, price_bars column = 'timestamp'
- Codebase: `src/ta_lab2/scripts/run_daily_refresh.py` -- pipeline stage ordering
- Codebase: `configs/portfolio.yaml` -- portfolio.yaml structure; stop_laddering.defaults
- Alembic: `b2c3d4e5f6a1` -- mae/mfe columns in backtest_trades
- Alembic: `i3j4k5l6m7n8` -- garch_forecasts_latest materialized view
- Alembic: `225bf8646f03` -- dim_executor_config schema (no target_annual_vol yet)
- Phase 82 Research: `.planning/phases/82-signal-refinement-walk-forward-bakeoff/82-RESEARCH.md` -- AMA feature names, load_per_asset pattern
- Phase 81 Research: `.planning/phases/81-garch-conditional-volatility/81-RESEARCH.md` -- GARCH stack, blending methodology

### Secondary (MEDIUM confidence)

- Codebase: `ic_results` schema verified from `c3b718c2d088` migration and `ic.py` save function -- `asset_id, feature, ic_ir` columns confirmed

### Tertiary (LOW confidence)

- Target vol value (80%) is a heuristic estimate based on BTC typical daily vol of ~3%. Verify empirically once GARCH forecasts are populated.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified in running codebase, no new dependencies
- Architecture patterns: HIGH -- all verified from existing module APIs
- Critical gaps: HIGH -- confirmed by direct code inspection (stub in line 526, missing target_annual_vol column, no stop_calibrations table)
- Parity test linkage: MEDIUM -- depends on whether Phase 82 wrote to backtest_trades (unverified)
- Target vol value: LOW -- heuristic; needs empirical calibration

**Research date:** 2026-03-23
**Valid until:** 2026-05-23 (stable codebase; no fast-moving external dependencies)
