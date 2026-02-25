# Phase 48: Loss Limits Policy - Research

**Researched:** 2026-02-25
**Domain:** Quantitative risk analysis -- VaR simulation, stop-loss scenario analysis, pool-level cap derivation, override governance
**Confidence:** HIGH (VaR formulas, vectorbt stop params, project DB schema, backtest data), MEDIUM (Cornish-Fisher crypto-specific behavior, pool cap heuristics), LOW (override governance best practices for solo prop trading)

---

## Summary

Phase 48 is primarily an **analysis-and-configuration phase**, not an implementation phase. It produces: (1) a VaR simulation module, (2) a stop-loss scenario sweep, (3) pool cap definitions derived from actual backtest data, and (4) an override governance policy document with enforcement code. All outputs feed the already-planned `dim_risk_limits` table from Phase 46.

The standard stack requires zero new libraries. All necessary tools already exist: `numpy`/`scipy` for VaR computation, `vectorbt` 0.28.1 for stop-loss simulation with native `sl_stop`/`sl_trail` parameters, and the project's existing backtest infrastructure (`cmc_backtest_metrics`, `strategy_bakeoff_results`) for sourcing return data. The one non-obvious tool: time-stop simulation has no native vectorbt parameter -- it must be implemented via custom exit signal arrays (shift entry by N bars).

The most important finding for the planner: the bake-off results are already in the database (`strategy_bakeoff_results` table, all strategies). Phase 48 does NOT re-run backtests -- it queries existing results and simulates overlay policies on top. This dramatically narrows scope.

**Primary recommendation:** Structure as 4 sequential plans: (1) VaR simulation module + report, (2) stop-loss scenario sweep + dim_risk_limits write, (3) pool cap definitions + schema, (4) override governance policy document + OverrideManager validation code.

---

## Standard Stack

All libraries already installed. Zero new dependencies required.

### Core (confirmed installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `numpy` | 2.4.1 | VaR quantile computation, return arrays | Project standard |
| `scipy.stats` | 1.17.0 | `norm.ppf`, `skew`, `kurtosis` for Cornish-Fisher VaR | Already in `psr.py` |
| `pandas` | 2.3.3 | Return series manipulation, result DataFrames | Project standard |
| `vectorbt` | 0.28.1 | Stop-loss simulation sweep with `sl_stop`, `sl_trail` | Already wired in `vbt_runner.py` |
| `sqlalchemy` | existing | Read from `strategy_bakeoff_results`, write to `dim_risk_limits` | Project standard |
| `plotly` | 6.4.0 | HTML charts for VaR comparison and stop-loss heatmaps | Already used in bakeoff scorecard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `alembic` | existing | Migrate schema if pool cap storage requires new columns | Phase 48 may not need migration if pools stored in existing dim_risk_limits rows |
| `argparse` | stdlib | CLI entry for each simulation script | All Phase 48 scripts |
| `dataclasses` | stdlib | `VaRResult`, `StopScenarioResult`, `PoolCap` typed outputs | Type safety |
| `json` | stdlib | Policy document serialization | Override categories enum |
| `logging` | stdlib | Consistent logging for all scripts | Project standard |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `scipy.stats` for Cornish-Fisher | `pyfolio` or `empyrical` | pyfolio is Quantopian-era and inactive; scipy is already installed and the formula is 4 lines |
| vectorbt for stops | `backtesting.py` | btpy_runner.py already has btpy stop support, but vectorbt sweep is faster and already used for all bakeoff runs |
| Manual recovery time calculation | No shortcut | Recovery time after stop = bars until equity returns to pre-stop level; compute from equity curve |

**Installation:**
```bash
# Nothing to install -- all dependencies already present
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── risk/                            # Phase 46 created this package (may not exist yet if 46 not done)
│   ├── __init__.py
│   ├── risk_engine.py               # Phase 46 owns this
│   ├── kill_switch.py               # Phase 46 owns this
│   └── override_manager.py          # Phase 46 creates; Phase 48 VALIDATES/EXTENDS
│                                    # Phase 48 adds: reason category validation
├── analysis/                        # NEW subpackage for Phase 48 analysis modules
│   ├── __init__.py
│   ├── var_simulator.py             # VaR module: historical + Cornish-Fisher
│   └── stop_simulator.py            # Stop-loss sweep: hard/trailing/time-stop

scripts/
└── analysis/                        # Existing directory (bakeoff scripts live here)
    ├── generate_bakeoff_scorecard.py  # existing
    ├── run_bakeoff_scoring.py         # existing
    ├── run_var_simulation.py          # NEW: Phase 48, runs VaR and writes report
    ├── run_stop_simulation.py         # NEW: Phase 48, sweeps stop types and writes to dim_risk_limits
    ├── define_pool_caps.py            # NEW: Phase 48, derives pool caps and seeds dim_risk_limits
    └── validate_override_governance.py  # NEW: Phase 48, validates OverrideManager rules

sql/risk/                            # Phase 46 creates this directory
    ├── 090_dim_risk_limits.sql       # Phase 46 owns
    ├── 091_dim_risk_state.sql        # Phase 46 owns
    ├── 092_cmc_risk_events.sql       # Phase 46 owns
    └── 093_cmc_risk_overrides.sql    # Phase 46 owns
    # NOTE: Phase 48 does NOT create new tables; it seeds data into existing tables

reports/
├── bakeoff/                         # existing
└── loss_limits/                     # NEW: Phase 48 report directory
    ├── VAR_REPORT.md                # VaR analysis output
    ├── STOP_SIMULATION_REPORT.md    # Stop-loss sweep results
    ├── POOL_CAPS.md                 # Pool cap definitions
    ├── OVERRIDE_POLICY.md           # Override governance policy document
    └── charts/                      # Plotly HTML charts
        ├── var_comparison.html      # Hist vs CF VaR at 95%/99%
        └── stop_heatmap.html        # Stop type x threshold Sharpe/MaxDD heatmap
```

### Pattern 1: VaR Simulation Module

**What:** Load daily returns from `strategy_bakeoff_results` or `cmc_backtest_metrics`, compute VaR two ways (historical and Cornish-Fisher), compare to identify tail-risk divergence for crypto.

**When to use:** Once per Phase 48 run; results are stable (bakeoff data does not change).

**Key insight from bake-off data:** EMA 17/77 has OOS Sharpe 1.401 but worst-fold MaxDD of -75%. This means worst-fold daily returns include extreme left-tail events that Gaussian VaR will underestimate. The CF vs historical divergence at 99% is the key finding.

**Example:**
```python
# Source: verified against scipy 1.17.0, numpy 2.4.1 in this codebase
from scipy.stats import norm, skew, kurtosis as scipy_kurtosis
import numpy as np

def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Non-parametric VaR: empirical quantile of return distribution."""
    return float(np.percentile(returns, (1 - confidence) * 100))

def parametric_var_normal(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Gaussian VaR: assumes returns are normally distributed."""
    mu, sigma = returns.mean(), returns.std(ddof=1)
    z = norm.ppf(1 - confidence)
    return float(mu + z * sigma)

def parametric_var_cornish_fisher(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Modified VaR via Cornish-Fisher expansion (Zangari 1996, Favre & Galeano 2002).
    Adjusts the Gaussian quantile for skewness and excess kurtosis.
    Accurate when distribution is 'close-ish' to normal with fat tails.
    Warning: can produce non-monotonic VaR for extreme kurtosis (>10) -- verify.
    """
    mu, sigma = returns.mean(), returns.std(ddof=1)
    z = norm.ppf(1 - confidence)
    s = float(skew(returns))
    k = float(scipy_kurtosis(returns, fisher=True))  # Fisher/excess kurtosis (0 for normal)
    # Cornish-Fisher adjustment to z
    z_cf = (z
            + (z**2 - 1) * s / 6
            + (z**3 - 3*z) * k / 24
            - (2*z**3 - 5*z) * s**2 / 36)
    return float(mu + z_cf * sigma)

def cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Conditional VaR (Expected Shortfall): mean of returns below VaR."""
    var = historical_var(returns, confidence)
    return float(returns[returns <= var].mean())
```

### Pattern 2: VaR-to-Cap Translation

**What:** VaR result sets `daily_loss_pct_threshold` in `dim_risk_limits`. Two modes per CONTEXT.md: Mode 1 (auto, VaR-driven) and Mode 2 (manual override).

**Decision required:** Which VaR value to use as the cap (95% or 99%? Historical or CF?). Research recommendation below in Decisions section.

**dim_risk_limits write pattern:**
```python
# Source: Phase 46 RESEARCH.md hot-reload pattern + project engine.begin() pattern
from sqlalchemy import text
from decimal import Decimal

def write_var_to_risk_limits(
    engine,
    asset_id: int | None,
    strategy_id: int | None,
    daily_loss_threshold: float,
    source: str,  # "var_historical_95" | "var_cf_99" | "manual_override"
    override_value: float | None = None,
) -> None:
    """Write VaR-derived daily loss threshold to dim_risk_limits."""
    final_value = override_value if override_value is not None else daily_loss_threshold
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE public.dim_risk_limits
            SET daily_loss_pct_threshold = :value,
                updated_at = now()
            WHERE (asset_id = :asset_id OR (asset_id IS NULL AND :asset_id IS NULL))
              AND (strategy_id = :strategy_id OR (strategy_id IS NULL AND :strategy_id IS NULL))
        """), {
            "value": final_value,
            "asset_id": asset_id,
            "strategy_id": strategy_id,
        })
```

### Pattern 3: Stop-Loss Simulation (vectorbt sweep)

**What:** Replay each strategy's signals with each stop type at each threshold level. Compare full metrics suite.

**Three stop types -- confirmed working in vectorbt 0.28.1:**

```python
# Source: verified via python -c invocation against vbt 0.28.1 in this codebase

import vectorbt as vbt
import numpy as np
import pandas as pd

def simulate_hard_stop(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    sl_pct: float,  # e.g., 0.05 for 5%
    fee_bps: float = 16,
) -> vbt.Portfolio:
    """Hard stop: exit when price drops sl_pct% from entry."""
    return vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        sl_stop=sl_pct,        # absolute % from entry price
        sl_trail=False,        # NOT trailing
        direction="longonly",
        freq="D",
        init_cash=1_000.0,
        fees=fee_bps / 1e4,
    )

def simulate_trailing_stop(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    sl_pct: float,
    fee_bps: float = 16,
) -> vbt.Portfolio:
    """Trailing stop: exit when price drops sl_pct% from peak-since-entry."""
    return vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        sl_stop=sl_pct,
        sl_trail=True,         # trailing
        direction="longonly",
        freq="D",
        init_cash=1_000.0,
        fees=fee_bps / 1e4,
    )

def simulate_time_stop(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    n_bars: int,               # exit after N bars regardless of price
    fee_bps: float = 16,
) -> vbt.Portfolio:
    """Time-stop: vectorbt has no native bar-count exit; compute custom exits."""
    # Build custom time-based exit signal
    custom_exits = exits.copy()
    for entry_ts in entries[entries].index:
        entry_idx = price.index.get_loc(entry_ts)
        exit_idx = min(entry_idx + n_bars, len(price) - 1)
        custom_exits.iloc[exit_idx] = True
    return vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=custom_exits,
        direction="longonly",
        freq="D",
        init_cash=1_000.0,
        fees=fee_bps / 1e4,
    )
```

**Sweep structure:**
```python
# Threshold sweep per CONTEXT.md: [0.01, 0.03, 0.05, 0.07, 0.10, 0.15]
STOP_THRESHOLDS = [0.01, 0.03, 0.05, 0.07, 0.10, 0.15]
TIME_STOP_BARS = [5, 10, 20, 30]  # bars (daily bars, so 5=1week, 10=2weeks, etc.)
STRATEGIES = ["ema_trend_17_77", "ema_trend_21_50", "rsi", "atr_breakout"]  # all 4
```

**Recovery time metric (custom computation):**
```python
def recovery_time_bars(equity: pd.Series) -> float:
    """Average bars from a stop-exit trough to return to pre-stop equity level.
    Returns np.nan if no recovery occurs (strategy never re-enters or time runs out).
    """
    # Find all local troughs (potential stop exit points)
    peak = equity.cummax()
    in_drawdown = equity < peak
    recovery_bars = []
    # ... detect trough -> recovery pairs; compute bar count
    # Implementation: scan for equity dip below prior peak, then scan forward
    # for recovery. Average across all occurrences.
    return float(np.mean(recovery_bars)) if recovery_bars else float("nan")
```

### Pattern 4: Pool Cap Derivation from Backtest Data

**What:** Derive Conservative/Core/Opportunistic pool caps from the actual bake-off `max_drawdown_worst` values. Adjust Vision Draft targets based on empirical findings.

**Empirical data from bake-off (from strategy_bakeoff_results / STRATEGY_SELECTION.md):**

| Strategy | OOS Sharpe (mean) | MaxDD Mean | MaxDD Worst | V1 Gate |
|----------|-------------------|------------|-------------|---------|
| ema_trend(17,77) | 1.401 | -38.6% | -75.0% | FAIL |
| ema_trend(21,50) | 1.397 | -38.7% | -70.1% | FAIL |
| breakout_atr variants | 0.75-0.77 | ~-50% | -49-50% | FAIL |
| rsi_mean_revert (best) | 0.163 | -8.8% | n/a | FAIL (Sharpe) |

**Cap derivation formula:**
```
pool_dd_cap = strategy_MaxDD_mean * sizing_fraction * pool_scaling_factor
```

Where:
- `strategy_MaxDD_mean` = OOS mean max drawdown (~38-39% for EMA strategies)
- `sizing_fraction` = 0.10 (V1 reduced position size)
- `pool_scaling_factor` = 1.0..1.5 (buffer for regime uncertainty)

Applied:
- 38.5% MaxDD mean * 10% sizing = ~3.85% expected portfolio DD at V1 sizing
- With 2x safety buffer: set pool caps at 7-8% for Conservative, 15-20% for Core
- Vision Draft targets (C <= 10-12%, Core <= 20%) are conservative relative to V1 sizing -- keep them as-is but document the derivation

### Pattern 5: Pool Cap Storage (Claude's Discretion -- decided here)

**Decision: Store pool caps as named rows in `dim_risk_limits`, not a separate `dim_pools` table.**

Rationale:
- `dim_risk_limits` already has `asset_id` and `strategy_id` as scope columns (both nullable). Adding a third nullable `pool_name` column accommodates pool-level rows.
- Adding a separate `dim_pools` table adds a JOIN everywhere pool limits are read. For V1 single-portfolio, this complexity is not earned.
- Phase 46 plans already show `dim_risk_limits` as the single-source-of-truth for risk parameters.

**Schema extension required (new column on dim_risk_limits):**
```sql
-- Alembic migration: add pool_name column to dim_risk_limits
ALTER TABLE public.dim_risk_limits
    ADD COLUMN pool_name TEXT NULL DEFAULT NULL;

-- Check constraint for valid pool names
ALTER TABLE public.dim_risk_limits
    ADD CONSTRAINT chk_risk_limits_pool
    CHECK (pool_name IS NULL OR pool_name IN ('conservative', 'core', 'opportunistic', 'aggregate'));
```

**Seed data for 3 pools + aggregate:**
```sql
-- Conservative pool
INSERT INTO public.dim_risk_limits (pool_name, daily_loss_pct_threshold, max_position_pct, max_portfolio_pct)
VALUES ('conservative', 0.08, 0.10, 0.40);

-- Core pool
INSERT INTO public.dim_risk_limits (pool_name, daily_loss_pct_threshold, max_position_pct, max_portfolio_pct)
VALUES ('core', 0.15, 0.20, 0.60);

-- Opportunistic pool
INSERT INTO public.dim_risk_limits (pool_name, daily_loss_pct_threshold, max_position_pct, max_portfolio_pct)
VALUES ('opportunistic', 0.20, 0.40, 0.80);

-- Aggregate (V1 single-portfolio: this is the ENFORCED cap)
INSERT INTO public.dim_risk_limits (pool_name, daily_loss_pct_threshold, max_position_pct, max_portfolio_pct)
VALUES ('aggregate', 0.15, 0.15, 0.80);
```

**V1 enforcement behavior (Claude's Discretion -- decided here):**
- The `aggregate` row is enforced by Phase 46 RiskEngine during V1.
- Pool-specific rows (conservative/core/opportunistic) are DEFINED but NOT actively enforced during V1 (V1 is single-portfolio; pool-level enforcement is post-V1).
- Document this clearly in POOL_CAPS.md so Phase 46 RiskEngine doesn't accidentally read pool rows as active limits.
- RiskEngine reads `dim_risk_limits WHERE pool_name IS NULL OR pool_name = 'aggregate'` to avoid picking up pool-specific rows unintentionally.

### Pattern 6: Override Governance (Claude's Discretion resolved)

**Decision: Time-limited auto-expiry with manual extension option.**

Rationale: A solo prop trader WILL forget active overrides. Auto-expiry prevents stale overrides from running indefinitely. The right default for safety is 24 hours (aligns with the daily strategy cadence -- one trading day). If the operator needs longer, they extend explicitly.

Implementation in OverrideManager (Phase 46 code, extended by Phase 48):
```python
# Phase 48 adds these constraints to OverrideManager

OVERRIDE_EXPIRY_HOURS_DEFAULT = 24      # auto-expire after 24 hours
OVERRIDE_EXPIRY_HOURS_MAX = 168         # max 7 days; operator must extend beyond this
OVERRIDE_REASON_CATEGORIES = [
    "market_condition",     # "BTC weekend illiquidity", "crypto event risk"
    "strategy_review",      # "pausing strategy for parameter review"
    "technical_issue",      # "exchange connectivity concern"
    "manual_risk_reduction", # "reducing exposure before earnings/event"
    "testing",              # "testing executor behavior"
]
# Categories enforce audit trail usefulness without being too restrictive.
# Free text alone has low audit value -- 6 months later "misc" is meaningless.
# Predefined + free text comment gives best of both.
```

**Override schema extension (adds expiry to cmc_risk_overrides from Phase 46):**
```sql
-- Phase 48 extends cmc_risk_overrides with expiry columns
ALTER TABLE public.cmc_risk_overrides
    ADD COLUMN reason_category TEXT NULL,
    ADD COLUMN expires_at TIMESTAMPTZ NULL,  -- NULL = no auto-expiry (manual-only)
    ADD COLUMN extended_at TIMESTAMPTZ NULL;  -- timestamp of last manual extension

ALTER TABLE public.cmc_risk_overrides
    ADD CONSTRAINT chk_overrides_reason_cat CHECK (
        reason_category IS NULL OR reason_category IN (
            'market_condition', 'strategy_review', 'technical_issue',
            'manual_risk_reduction', 'testing'
        )
    );
```

**OverrideManager validation code (Phase 48 adds unit tests):**
```python
# validate_override_governance.py: runs rules check against OverrideManager

def test_override_expiry():
    """Verify that overrides auto-expire after OVERRIDE_EXPIRY_HOURS_DEFAULT."""
    ...

def test_override_category_required():
    """Verify that creating an override without reason_category raises ValueError."""
    ...

def test_override_max_duration():
    """Verify that expires_at > now() + 168 hours is rejected."""
    ...
```

### Anti-Patterns to Avoid

- **Re-running bake-off to get return data:** `strategy_bakeoff_results` already has all OOS return metrics including `max_drawdown_worst`. Query the DB, don't re-run backtests.
- **VaR on equity curve instead of returns:** VaR must be computed on DAILY RETURNS (percentage changes), not on the equity curve level. Equity is non-stationary; returns are stationary.
- **Using in-sample data for VaR:** Use only OOS fold returns from `strategy_bakeoff_results`. In-sample VaR is over-optimistic.
- **Setting daily_loss_pct_threshold = VaR at 99%:** 99% historical VaR for BTC strategies is large (15-20%+ for worst folds). Starting from 95% historical VaR and verifying it's operationally sensible is safer.
- **Enforcing pool caps on V1 single-portfolio:** V1 runs one aggregate portfolio. Pool caps are defined for future multi-pool but should not interfere with V1 risk enforcement. Clearly separate in schema via `pool_name` column.
- **Time-stop via vectorbt's built-in parameters:** vectorbt 0.28.1 has NO native time-stop parameter. It must be built with custom exit signal arrays. Searching `vectorbt` docs for `time_stop`, `bar_stop`, or `duration_stop` will find nothing.
- **Cornish-Fisher VaR for extreme kurtosis:** CF VaR is only accurate for distributions "close to" normal. Crypto daily returns in bear market folds can have excess kurtosis > 15. For kurtosis > 10, historical simulation VaR is MORE reliable. Report both and flag the divergence as the key finding.
- **Kaleido for charts:** MEMORY.md confirms kaleido is not installed. Use Plotly HTML output only (`fig.write_html()`), not `fig.write_image()`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| VaR computation | Custom statistical library | `numpy.percentile` + `scipy.stats` | 3-line implementation; same libs as existing `psr.py` |
| Stop-loss simulation | Custom bar-by-bar replay loop | `vectorbt.Portfolio.from_signals(sl_stop=, sl_trail=)` | vectorbt handles all edge cases (open/close timing, partial fills, cost application) |
| Return data extraction | Re-run full backtest pipeline | Query `strategy_bakeoff_results` table directly | All 10+ strategies already computed; bake-off took hours; don't repeat |
| Recovery time | External library | Custom computation from equity curve | No standard library does this; 10-line numpy implementation is sufficient |
| Override expiry check | Cron job | Query `cmc_risk_overrides WHERE expires_at < now()` at executor startup | Executor already runs daily; checking expired overrides is a 1-line SQL extension |
| Pool storage | Separate `dim_pools` table | Extra rows in `dim_risk_limits` with `pool_name` column | Avoids JOIN complexity; Phase 46 schema already covers the use case |

**Key insight:** The analysis is lightweight because Phase 42 did the heavy lifting. Phase 48 is a policy derivation phase that reads existing results and translates them into configuration. The actual computation is minutes, not hours.

---

## Common Pitfalls

### Pitfall 1: VaR on Aggregate Returns, Not Per-Strategy
**What goes wrong:** Computing VaR on the concatenated returns of all folds treats different regime periods as IID (independent and identically distributed). Fold-level MaxDD variance (EMA 17/77: best fold Sharpe=2.72, worst=-0.018) shows these are NOT IID.
**Why it happens:** Simple concatenation is the path of least resistance.
**How to avoid:** Compute VaR SEPARATELY for each OOS fold, then report the distribution. Report per-strategy VaR-at-95% range (e.g., "VaR ranges from X% to Y% across folds").
**Warning signs:** VaR result that looks more optimistic than the bake-off mean MaxDD.

### Pitfall 2: Tight Stops Cause Whipsaw on 1D Crypto Bars
**What goes wrong:** A 3% stop on a daily BTC strategy exits immediately during normal intraday volatility, adding ~2x-3x the trades with much worse fill timing.
**Why it happens:** BTC 1D bars have average daily range of 3-5%, so a 3% stop will be hit nearly every day in normal conditions.
**How to avoid:** The threshold sweep 1%-15% is specifically designed to reveal this. Expected finding: stops below ~7-10% will dramatically increase turnover and reduce Sharpe. Document this as the key stop simulation insight.
**Warning signs:** Stop scenario at 1-3% shows trade count 10x higher than baseline with worse Sharpe.

### Pitfall 3: Time-Stop in vectorbt Requires Custom Exit Arrays
**What goes wrong:** Searching vectorbt docs for `time_stop`, `bar_stop`, or `n_bars` finds nothing. Implementer concludes vectorbt can't do time-stops.
**Why it happens:** vectorbt has no native time-stop parameter (confirmed by inspecting `from_signals` signature).
**How to avoid:** Implement time-stop by building a custom boolean exit Series: for each entry bar, set `exits.iloc[entry_idx + n_bars] = True`. Pass this as the `exits` argument. Confirmed working in vbt 0.28.1 in this codebase.
**Warning signs:** Implementation uses a bar-by-bar Python loop and runs slowly -- vectorize the exit array construction.

### Pitfall 4: pool_name Column Breaks Phase 46 RiskEngine Queries
**What goes wrong:** After adding `pool_name` to `dim_risk_limits` and inserting pool rows, the Phase 46 RiskEngine's `_load_limits()` query (which does `WHERE (asset_id IS NULL AND strategy_id IS NULL) LIMIT 1`) accidentally picks up a pool row instead of the aggregate default.
**Why it happens:** The Phase 46 RiskEngine was designed without the pool_name column. The query `WHERE asset_id IS NULL AND strategy_id IS NULL` now matches both the aggregate row AND the pool rows.
**How to avoid:** Add `AND pool_name IS NULL` to Phase 46 RiskEngine's `_load_limits()` query when picking up the default. Alternatively, document the aggregate row explicitly as `pool_name = 'aggregate'` and filter: `WHERE pool_name = 'aggregate'`.
**Warning signs:** Risk engine applies pool-specific caps to V1 portfolio during paper trading.

### Pitfall 5: VaR Written to dim_risk_limits Without Sanity Check
**What goes wrong:** VaR-to-cap auto-write inserts `daily_loss_pct_threshold = 0.75` (75% worst-fold MaxDD divided by days). This is non-sensical as a daily cap.
**Why it happens:** VaR computed on fold-level returns (multi-day positions treated as single bars) inflates the per-day figure.
**How to avoid:** Always compute VaR on DAILY returns (1-day P&L percentage changes), not position-level returns. Add a sanity check: if computed daily VaR > 15%, cap at 15% and log a warning. The daily stop should never exceed 15% for a single-asset 1D strategy.
**Warning signs:** `daily_loss_pct_threshold` value exceeds 0.15 in dim_risk_limits.

### Pitfall 6: Override Expiry Not Checked at Executor Startup
**What goes wrong:** An override created 48 hours ago (auto-expiry = 24h) is still active because the executor never checked for expired overrides.
**Why it happens:** Phase 46 OverrideManager creates overrides but may not have expiry checking wired into the executor startup flow.
**How to avoid:** Phase 48 `validate_override_governance.py` should verify that the OverrideManager's `check_and_expire()` method (or equivalent) exists and is called at executor startup. If not, Phase 48 adds this call.
**Warning signs:** `cmc_risk_overrides` table has rows where `expires_at < now()` and `reverted_at IS NULL`.

### Pitfall 7: Cornish-Fisher Non-Monotonicity for Extreme Kurtosis
**What goes wrong:** CF VaR at 99% is LESS extreme than CF VaR at 95% (negative monotonicity), which means the 99% VaR is actually reporting a LESS severe loss.
**Why it happens:** CF expansion breaks down when excess kurtosis exceeds ~8-10. The expansion is a Taylor series approximation that diverges for heavy-tailed distributions.
**How to avoid:** Before using CF VaR, check excess kurtosis. If `scipy_kurtosis(returns, fisher=True) > 8`, fall back to historical simulation for the 99% level. Log a warning. This will happen for the worst-fold returns of EMA strategies in bear markets.
**Warning signs:** CF 99% VaR is numerically less negative than CF 95% VaR.

### Pitfall 8: Windows UTF-8 in SQL Comments
**What goes wrong:** Box-drawing characters or em-dashes in SQL migration comments cause `UnicodeDecodeError` with default Windows `cp1252` encoding.
**Why it happens:** Windows default codec is cp1252, not UTF-8. (See project MEMORY.md.)
**How to avoid:** Use ASCII-only characters in all SQL comments. Open all SQL files with `encoding='utf-8'`. This applies to any new Alembic migration in Phase 48.
**Warning signs:** `UnicodeDecodeError: 'charmap' codec can't decode byte`.

---

## Code Examples

### Historical Simulation VaR (verified formula)
```python
# Source: verified against numpy 2.4.1 in this codebase
import numpy as np

def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Historical simulation VaR at given confidence level.
    Returns: negative float (e.g., -0.05 = 5% loss)
    """
    return float(np.percentile(returns, (1 - confidence) * 100))

def historical_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Conditional VaR / Expected Shortfall: mean of returns below VaR."""
    var = historical_var(returns, confidence)
    tail = returns[returns <= var]
    return float(tail.mean()) if len(tail) > 0 else var
```

### Cornish-Fisher Modified VaR (verified formula)
```python
# Source: Zangari (1996), Favre & Galeano (2002)
# Verified: scipy 1.17.0, numpy 2.4.1 -- works correctly for crypto-like distributions
from scipy.stats import norm, skew, kurtosis

def cornish_fisher_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Modified VaR using Cornish-Fisher expansion.
    CAUTION: Use historical_var instead if excess kurtosis > 8.
    """
    mu = float(returns.mean())
    sigma = float(returns.std(ddof=1))
    z = norm.ppf(1 - confidence)
    s = float(skew(returns))
    k = float(kurtosis(returns, fisher=True))  # excess kurtosis

    # Warn if expansion may be unreliable
    if abs(k) > 8:
        import warnings
        warnings.warn(
            f"Cornish-Fisher VaR: excess kurtosis={k:.1f} > 8. "
            "CF expansion may be non-monotonic. Verify against historical VaR.",
            UserWarning
        )

    z_cf = (z
            + (z**2 - 1) * s / 6
            + (z**3 - 3*z) * k / 24
            - (2*z**3 - 5*z) * s**2 / 36)
    return float(mu + z_cf * sigma)
```

### Stop Simulation Sweep (vectorbt 0.28.1)
```python
# Source: verified via vectorbt 0.28.1 inspection in this codebase

def sweep_stops(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    thresholds: list[float],
    fee_bps: float = 16,
) -> pd.DataFrame:
    """Sweep hard, trailing, and time stops across threshold range."""
    results = []
    for pct in thresholds:
        for stop_type in ["hard", "trailing"]:
            pf = vbt.Portfolio.from_signals(
                price, entries=entries, exits=exits,
                sl_stop=pct,
                sl_trail=(stop_type == "trailing"),
                direction="longonly", freq="D",
                init_cash=1000.0, fees=fee_bps / 1e4,
            )
            results.append({
                "stop_type": stop_type,
                "threshold_pct": pct,
                "sharpe": pf.sharpe_ratio(freq=365),
                "max_dd": float(pf.max_drawdown()),
                "total_return": float(pf.total_return()),
                "trades": int(pf.trades.count()),
                "win_rate": float(pf.trades.win_rate()),
            })
    return pd.DataFrame(results)
```

### Query bake-off data for VaR inputs
```python
# Source: matches composite_scorer.load_bakeoff_metrics() pattern
from sqlalchemy import text

def load_oos_returns_for_var(engine, strategy_name: str, asset_id: int) -> np.ndarray:
    """Load OOS fold returns from strategy_bakeoff_results for VaR computation.
    NOTE: Each row in strategy_bakeoff_results is a fold; metrics are fold-level.
    For VaR we need daily returns, which must come from cmc_backtest_trades.
    """
    sql = text("""
        SELECT bt.return_pct
        FROM public.cmc_backtest_trades bt
        JOIN public.cmc_backtest_runs r ON bt.run_id = r.run_id
        WHERE r.signal_type = :signal_type AND r.asset_id = :asset_id
        ORDER BY bt.exit_ts
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"signal_type": strategy_name, "asset_id": asset_id})
    return df["return_pct"].to_numpy()
```

---

## Claude's Discretion -- Decisions Made

The following open questions from CONTEXT.md are resolved based on research:

### Pool Cap Storage Approach
**Decision: `pool_name TEXT NULL` column added to `dim_risk_limits`.**
Phase 48 adds one `ALTER TABLE` migration to add `pool_name` to `dim_risk_limits`. Pool-specific rows use this column. Phase 46 RiskEngine queries filter `WHERE pool_name IS NULL` or `WHERE pool_name = 'aggregate'` to avoid picking up pool rows. No separate `dim_pools` table needed.

### V1 Enforcement of Pool Caps
**Decision: Pool caps are DEFINED but NOT enforced during V1. Only the `aggregate` row is enforced.**
V1 runs a single portfolio. Pool-level enforcement is deferred per CONTEXT.md Deferred section ("Multi-pool enforcement during paper trading"). Phase 48 documents pool caps in POOL_CAPS.md and seeds them in `dim_risk_limits`, but Phase 46 RiskEngine only reads the `aggregate` row. The pool rows are ready for multi-pool when it comes.

### Override Auto-Expiry Duration
**Decision: 24-hour default expiry, 7-day maximum, manual extension supported.**
- `expires_at = now() + 24 hours` on override creation (default)
- Operator can set `expires_at` explicitly up to 7 days (168 hours)
- Beyond 7 days: not allowed; operator must re-create
- Rationale: aligns with daily strategy cadence; prevents forgotten overrides from running indefinitely; 24h is the minimum meaningful unit for a 1D strategy

### Override Reason Categories
**Decision: Predefined enum + optional free-text comment.**
6 categories: `market_condition`, `strategy_review`, `technical_issue`, `manual_risk_reduction`, `testing`, `other`. The `reason` TEXT field (from Phase 46) remains as free-text comment. The new `reason_category` column is the structured enum. This gives both audit-trail usefulness (queryable categories) and flexibility (free-text explanation).

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Gaussian VaR only | Cornish-Fisher VaR alongside historical | ~2002 (Favre & Galeano) | Captures fat tails; gap between methods reveals tail risk magnitude |
| Fixed-% stop losses | Empirical sweep over wide range | Standard practice post-2010 | Stop effectiveness is strategy- and volatility-regime-specific |
| Separate risk pools with complex allocation rules | `dim_risk_limits` pool_name rows + single-portfolio enforcement | This project's V1 design | Simple, extensible, avoids premature pool complexity |
| Free-text override reasons | Predefined categories + free text | Best practice in audit trails | Queryable categories + flexibility; avoids meaningless audit log |

**Deprecated/outdated:**
- Gaussian VaR without fat-tail adjustment: understates tail risk for crypto by 30-50% at 99% confidence level.
- Manual-only override expiry (no auto-expire): creates silent risk from forgotten overrides; time-limited expiry is the safety-first default.

---

## Integration with Phase 46

### What Phase 46 already defines (do NOT re-create)
- `dim_risk_limits` table schema (46-01-PLAN.md, 46-RESEARCH.md)
- `cmc_risk_overrides` table schema
- `OverrideManager` class in `src/ta_lab2/risk/override_manager.py`
- `RiskEngine._load_limits()` reading pattern (hot-reload from DB)

### What Phase 48 adds to Phase 46 infrastructure
- `ALTER TABLE dim_risk_limits ADD COLUMN pool_name TEXT` (new Alembic migration)
- `ALTER TABLE cmc_risk_overrides ADD COLUMN reason_category TEXT, expires_at TIMESTAMPTZ, extended_at TIMESTAMPTZ` (new Alembic migration)
- Pool cap rows seeded into `dim_risk_limits`
- VaR-derived `daily_loss_pct_threshold` written to aggregate row via `define_pool_caps.py`
- Stop-derived optimal parameters written to `dim_risk_limits` via `run_stop_simulation.py`
- Unit tests validating `OverrideManager` respects new expiry and category constraints

### Migration chain dependency
Phase 48 Alembic migration `down_revision` must point to Phase 46 migration.
Phase 46 migration file name is TBD (XXXX_risk_controls.py); Phase 48 must detect current head at execution time, not hardcode it.

---

## Open Questions

1. **Phase 46 completion status**
   - What we know: Phase 46 has 4 plans (46-01 through 46-04) but no SUMMARY files found. Plans exist, execution status unknown.
   - What is unclear: Whether `dim_risk_limits`, `cmc_risk_overrides`, `dim_risk_state` tables exist in DB yet, and whether `src/ta_lab2/risk/` package exists.
   - Recommendation: Phase 48 plans must include a PREREQUISITE CHECK step. If Phase 46 is not done, Phase 48 runs after it.

2. **Return data source for VaR**
   - What we know: `cmc_backtest_metrics` has `var_95` and `expected_shortfall` columns already (see 072_cmc_backtest_metrics.sql). These may already contain pre-computed VaR values.
   - What is unclear: Whether these columns are populated from the Phase 42 bake-off runs, or are NULL. If populated, Phase 48 can skip re-computation and just read them.
   - Recommendation: Phase 48 plan should check `SELECT var_95, expected_shortfall FROM cmc_backtest_metrics LIMIT 5` first. If populated, use directly. If NULL, compute from `cmc_backtest_trades.return_pct`.

3. **Trade-level vs aggregate returns for VaR**
   - What we know: `cmc_backtest_trades` stores trade-level data; VaR should be on daily returns.
   - What is unclear: Whether `cmc_backtest_trades` has sufficient resolution to reconstruct daily P&L, or whether we need bar-by-bar equity curves from the original vectorbt runs.
   - Recommendation: If VaR columns in `cmc_backtest_metrics` are NULL, use `cmc_backtest_metrics.total_return` + `max_drawdown` per fold to estimate range, OR re-run the bakeoff with `collect_equity=True` to get bar-by-bar equity. The latter is the accurate approach but requires re-running part of Phase 42.

---

## Sources

### Primary (HIGH confidence)
- Project codebase: `src/ta_lab2/backtests/psr.py` -- confirmed `scipy.stats.kurtosis(fisher=False)` for Pearson kurtosis in PSR; same pattern applies to CF VaR which needs `fisher=True`
- Project codebase: `src/ta_lab2/backtests/vbt_runner.py` -- confirmed vectorbt 0.28.1 integration patterns
- Project codebase: `sql/backtests/072_cmc_backtest_metrics.sql` -- confirmed `var_95` and `expected_shortfall` columns exist in schema
- Project codebase: `reports/bakeoff/STRATEGY_SELECTION.md` -- confirmed empirical MaxDD values (EMA17/77: -75% worst, -38.6% mean; EMA21/50: -70.1% worst, -38.7% mean)
- Direct verification: `python -c "import vectorbt as vbt; ..."` -- confirmed `sl_stop`, `sl_trail` params in `Portfolio.from_signals()` for vbt 0.28.1
- Direct verification: `python -c "from scipy.stats import norm, skew, kurtosis; ..."` -- confirmed Cornish-Fisher formula produces correct results
- Direct verification: `python -c "import vectorbt as vbt; ..."` -- confirmed time-stop requires custom exit arrays (no native param)
- Project codebase: `.planning/phases/46-risk-controls/46-RESEARCH.md` -- confirmed dim_risk_limits schema, OverrideManager design, cmc_risk_overrides schema

### Secondary (MEDIUM confidence)
- WebSearch + QuantStart: VaR methodology (historical simulation + Cornish-Fisher) confirmed as standard approach for crypto/fat-tail assets
- WebSearch + vectorbt GitHub discussions #338: `sl_stop` as % of entry price (0.01 = 1%), `sl_trail=True` for trailing stop -- confirmed
- Favre & Galeano (2002) "Modified Sharpe Ratios in Alternative Investments" -- Cornish-Fisher VaR formula source; confirmed as standard reference for mVaR

### Tertiary (LOW confidence)
- WebSearch "pool drawdown cap conservative core opportunistic 2025" -- Conservative: 10-15% MaxDD typical, Core: 15-25%, Aggressive: 25-40% from general asset management literature. Not crypto-specific. Used as reference only; actual caps derived from empirical bakeoff data.
- WebSearch "override governance trading risk management solo operator 2025" -- No specific guidance for solo prop trading operators; enterprise GRC frameworks not applicable. Decision based on safety reasoning only.

---

## Metadata

**Confidence breakdown:**
- VaR methodology (formulas, Python implementation): HIGH -- formula verified in code; scipy confirmed correct
- vectorbt stop simulation (hard/trailing): HIGH -- parameter names and behavior confirmed by direct code inspection
- vectorbt time-stop (custom exits): HIGH -- confirmed no native param; custom exit array approach verified
- Pool cap derivation from bakeoff data: HIGH -- empirical data from STRATEGY_SELECTION.md is definitive
- Pool cap storage (pool_name column): HIGH -- design decision is clear and consistent with existing schema
- Override expiry/categories (Claude's Discretion): MEDIUM -- safety reasoning is sound but no external precedent for solo prop trading; may need tuning
- Phase 46 completion status: LOW -- plans exist but execution status unknown; prerequisite check required in Phase 48

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (30 days; vectorbt 0.28.1 API is stable; scipy formulas are mathematical constants)
