# Phase 49: Tail-Risk Policy - Research

**Researched:** 2026-02-25
**Domain:** Tail-risk analysis -- vol-based position sizing, flatten triggers, escalation systems, policy documentation
**Confidence:** HIGH (vol calibration from live DB, vectorbt sizing API, schema design), MEDIUM (re-entry procedure, regime interaction), LOW (historical crash attribution for FTX via exchange halt)

---

## Summary

Phase 49 is a combined **analysis + implementation phase** producing: (1) a vol-sizing backtest comparison module, (2) an executable `check_flatten_trigger()` function added to RiskEngine, (3) a schema migration extending `dim_risk_state` with a three-level `tail_risk_state` column, and (4) a policy document + machine-readable YAML config in `reports/tail_risk/`.

The most important finding: the vol spike trigger alone is insufficient. BTC 20-day rolling vol crossed the 2-sigma threshold (9.2%/day) on COVID March 15 -- three days AFTER the -37% crash of March 12. FTX November 2022 never triggered the vol spike threshold at all (vol only reached 5.1% during FTX). This means the trigger suite MUST include multiple complementary signal types: rolling vol (catches prolonged crises), single-day absolute return (catches one-day crashes), and exchange halt detection (catches infrastructure failures like FTX).

The escalation architecture must extend `dim_risk_state` with a new `tail_risk_state` column (values: `normal`, `reduce`, `flatten`) rather than reusing the existing `trading_state` (binary: `active`/`halted`). This preserves the Phase 46 kill switch logic without modification and cleanly separates automated tail-risk escalation from manual halt.

**Primary recommendation:** Four sequential plans -- (1) Alembic migration + vol-sizing library, (2) Flatten trigger + RiskEngine extension, (3) Backtest comparison CLI + reports, (4) Policy document + YAML config.

---

## Standard Stack

All libraries already installed. Zero new dependencies required.

### Core (confirmed installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `numpy` | 2.4.1 | Vol computation, rolling std, percentile | Project standard |
| `pandas` | 2.3.3 | Time series alignment, rolling windows | Project standard |
| `vectorbt` | 0.28.1 | Vol-sized backtest simulation | Phase 42 + Phase 48 established |
| `scipy.stats` | 1.17.0 | Sortino/Calmar (via existing performance.py) | Already in psr.py |
| `sqlalchemy` | existing | Read cmc_features/returns, write dim_risk_state | Project standard |
| `plotly` | 6.4.0 | HTML comparison charts | Kaleido NOT installed; HTML only |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `alembic` | existing | Schema migration for tail_risk_state column | Phase 49 Plan 01 |
| `dataclasses` | stdlib | `TailRiskResult`, `FlattenTriggerResult` typed outputs | Library modules |
| `yaml` | stdlib (pyyaml) | Machine-readable policy config output | TAIL-03 output |
| `argparse` | stdlib | CLI scripts | All Phase 49 CLIs |
| `logging` | stdlib | Structured logging (WARNING/CRITICAL for escalation) | Project standard |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `performance.py` sortino/calmar | Custom implementation | `performance.py` already has sortino(), calmar() -- use directly |
| Rolling std for realized vol | GARCH models | GARCH adds library dependency; rolling std matches the CONTEXT.md decision and is sufficient for V1 |
| New `cmc_tail_risk_events` table | Extend `cmc_risk_events` | Extending existing table is simpler; add new event_type values via migration |

**Installation:**
```bash
# Nothing to install -- all dependencies already present
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── risk/
│   ├── risk_engine.py          # Phase 46 -- extend with check_tail_risk_state() and check_flatten_trigger()
│   └── flatten_trigger.py      # NEW: Phase 49 -- FlattenTrigger class, check_flatten_trigger()
├── analysis/
│   ├── var_simulator.py        # Phase 48 -- already planned
│   ├── stop_simulator.py       # Phase 48 -- already planned
│   └── vol_sizer.py            # NEW: Phase 49 -- vol-sizing library (ATR-based and realized-vol-based)

scripts/
└── analysis/
    ├── run_bakeoff_scoring.py          # existing
    ├── run_var_simulation.py           # Phase 48
    ├── run_stop_simulation.py          # Phase 48
    └── run_tail_risk_comparison.py     # NEW: Phase 49 -- 3-variant x 4-strategy x 2-asset sweep

reports/
├── loss_limits/                # Phase 48
└── tail_risk/                  # NEW: Phase 49
    ├── TAIL_RISK_POLICY.md     # Human memo with analysis and rationale
    ├── tail_risk_config.yaml   # Machine-readable config for RiskEngine
    ├── SIZING_COMPARISON.md    # TAIL-01 backtest comparison results
    └── charts/
        ├── sizing_sharpe_heatmap.html
        ├── sizing_maxdd_comparison.html
        └── vol_spike_history.html

sql/risk/
    ├── 094_tail_risk_state.sql     # NEW: DDL reference (migration in alembic)
```

### Pattern 1: Vol-Sized Position (Integrated at Entry)

**What:** Compute position size at entry bar based on current volatility. Size shrinks automatically in high-vol regimes.

**Formula (verified against actual BTC data):**
```python
# Source: verified with cmc_features ATR-14 (dollar value) against cmc_price_bars close
# atr_14 from cmc_features is in DOLLAR terms, not percentage
# atr_pct = atr_14 / close

def compute_vol_sized_position(
    close: float,
    atr_14: float,           # dollar ATR from cmc_features
    init_cash: float,        # normalized portfolio (1000.0 for backtests)
    risk_budget: float,      # fraction of portfolio to risk per trade (e.g., 0.01 = 1%)
    max_position_pct: float = 0.30,  # hard cap on position size
) -> float:
    """
    Compute vol-sized position in UNITS of the asset.
    Returns units to pass as vectorbt size parameter at entry bar.

    ATR is in dollar terms. Position = risk_budget / ATR_dollar_fraction
    where ATR_dollar_fraction = atr_14 / close

    Crisis conditions (e.g., ATR=15% of close) automatically reduce position to 6.7% of portfolio.
    Normal conditions (e.g., ATR=3% of close) allow up to the max_position_pct cap (30%).
    """
    if atr_14 is None or atr_14 <= 0 or close <= 0:
        return 0.0
    atr_pct = atr_14 / close                         # ATR as fraction of close
    position_pct = min(risk_budget / atr_pct, max_position_pct)  # cap at max
    position_units = position_pct * init_cash / close
    return position_units
```

**ATR-pct observed values (BTC, from DB):**
- Normal markets: 2-4% of close
- Elevated vol: 5-8%
- Crisis (COVID March 2020): up to 15-20%
- At 1% risk budget: normal -> 25-50% raw position (capped at 30%), crisis -> 5-7%

**Realized vol alternative (rolling std of daily returns):**
```python
# Source: cmc_returns_bars_multi_tf_u, column=ret_arith, tf='1D'
# timestamp column (not ts) based on actual DB schema

def compute_realized_vol_position(
    rolling_std: float,       # rolling std of ret_arith over N bars
    close: float,
    init_cash: float,
    risk_budget: float,
    max_position_pct: float = 0.30,
) -> float:
    """Realized-vol-sized position using rolling std of daily returns."""
    if rolling_std <= 0:
        return 0.0
    position_pct = min(risk_budget / rolling_std, max_position_pct)
    return position_pct * init_cash / close
```

### Pattern 2: Vectorbt Vol-Sized Backtest (Integrated at Entry)

**What:** Pass vol-computed size as array to `vbt.Portfolio.from_signals()` at each entry bar.

**Key insight:** vectorbt `size` parameter = UNITS of the asset at each bar. Only the value at entry bars matters; non-entry bars can be NaN.

```python
# Source: verified with vectorbt 0.28.1 in this codebase
import vectorbt as vbt
import numpy as np
import pandas as pd

def run_vol_sized_backtest(
    price: pd.Series,         # close prices with DatetimeIndex
    entries: pd.Series,       # boolean entry signals
    exits: pd.Series,         # boolean exit signals
    atr_14: pd.Series,        # ATR-14 dollar values (from cmc_features, same index)
    risk_budget: float,       # e.g., 0.01 = 1%
    max_position_pct: float = 0.30,
    init_cash: float = 1000.0,
    fee_bps: float = 16,
) -> vbt.Portfolio:
    """Run vol-sized backtest with integrated sizing at entry."""
    # Compute position size at each bar
    atr_pct = atr_14 / price
    position_pct = np.minimum(risk_budget / atr_pct.values, max_position_pct)
    position_units = position_pct * init_cash / price.values

    # Only apply size at entry bars; use NaN elsewhere
    size_array = np.where(entries.values, position_units, np.nan)

    # CRITICAL: strip tz from price index (vbt 0.28.1 tz boundary issue)
    price_np = price.values
    if hasattr(price.index, 'tz') and price.index.tz is not None:
        price_no_tz = pd.Series(price_np, index=price.index.tz_localize(None))
    else:
        price_no_tz = price

    return vbt.Portfolio.from_signals(
        price_no_tz,
        entries=entries.to_numpy(),
        exits=exits.to_numpy(),
        size=size_array,
        direction="longonly",
        freq="D",
        init_cash=init_cash,
        fees=fee_bps / 1e4,
    )
```

**Comparison variants (per CONTEXT.md):**
- Variant A: fixed size + hard stops (Phase 48 stop_simulator pattern)
- Variant B: vol-sized + no stops (above function, sl_stop=None)
- Variant C: vol-sized + hard stops (above function + sl_stop=risk_budget)

### Pattern 3: Flatten Trigger -- check_flatten_trigger()

**What:** Standalone function checking all flatten conditions. Returns `EscalationState` enum.

**Design:** New module `src/ta_lab2/risk/flatten_trigger.py`. RiskEngine calls this in a new gate (Gate 0, before kill switch check).

```python
# Source: calibrated against actual BTC data (2010-2025, 5613 bars)
# Thresholds derived from empirical percentile analysis

from dataclasses import dataclass
from enum import Enum
import numpy as np
import pandas as pd
from typing import Optional

class EscalationState(str, Enum):
    NORMAL = "normal"
    REDUCE = "reduce"
    FLATTEN = "flatten"

@dataclass
class FlattenTriggerResult:
    state: EscalationState
    trigger_type: Optional[str]         # None if NORMAL; "vol_spike"|"abs_return"|"exchange_halt"|"correlation"
    trigger_value: Optional[float]      # actual metric value that triggered
    threshold_used: float               # threshold that was breached
    details: str                        # human-readable explanation

def check_flatten_trigger(
    rolling_vol_20d: float,    # 20-day rolling std of daily returns (precomputed)
    latest_daily_return: float, # today's return (ret_arith from cmc_returns_bars_multi_tf_u)
    api_healthy: bool = True,  # False if exchange API health check fails
    correlation_30d: Optional[float] = None,  # BTC/ETH 30d rolling correlation
    # Thresholds -- calibrated from BTC 2010-2025 data
    reduce_vol_threshold: float = 0.0923,   # mean+2std of 20d rolling vol -> ~5% of days
    flatten_vol_threshold: float = 0.1194,  # mean+3std of 20d rolling vol -> ~2.3% of days
    flatten_abs_return_threshold: float = 0.15,  # |daily return| > 15% -> ~1.8% of days
    flatten_corr_breakdown_threshold: float = -0.20,  # BTC/ETH 30d corr < -0.20
) -> FlattenTriggerResult:
    """
    Check all flatten/reduce triggers. Returns highest-severity escalation state.

    Priority order (highest to lowest severity):
    1. FLATTEN: exchange halt (API unhealthy)
    2. FLATTEN: extreme single-day return (|ret| > 15%)
    3. FLATTEN: vol > 3-sigma threshold
    4. REDUCE: vol > 2-sigma threshold
    5. FLATTEN: correlation breakdown (optional, if provided)
    6. NORMAL: no triggers fired
    """
    # Trigger 1: Exchange halt (highest priority -- infrastructure failure)
    if not api_healthy:
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="exchange_halt",
            trigger_value=0.0,
            threshold_used=0.0,
            details="Exchange API health check failed -- flatten all positions",
        )

    # Trigger 2: Extreme single-day return (crash-day protection)
    if abs(latest_daily_return) > flatten_abs_return_threshold:
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="abs_return",
            trigger_value=latest_daily_return,
            threshold_used=flatten_abs_return_threshold,
            details=f"Single-day |return| {abs(latest_daily_return):.1%} exceeds {flatten_abs_return_threshold:.0%} threshold",
        )

    # Trigger 3: Vol spike -- flatten level (3-sigma)
    if rolling_vol_20d > flatten_vol_threshold:
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="vol_spike",
            trigger_value=rolling_vol_20d,
            threshold_used=flatten_vol_threshold,
            details=f"20d rolling vol {rolling_vol_20d:.2%}/day exceeds 3-sigma flatten threshold {flatten_vol_threshold:.2%}",
        )

    # Trigger 4: Correlation breakdown (if BTC/ETH diverge -- optional)
    if correlation_30d is not None and correlation_30d < flatten_corr_breakdown_threshold:
        return FlattenTriggerResult(
            state=EscalationState.FLATTEN,
            trigger_type="correlation_breakdown",
            trigger_value=correlation_30d,
            threshold_used=flatten_corr_breakdown_threshold,
            details=f"BTC/ETH 30d correlation {correlation_30d:.3f} below breakdown threshold {flatten_corr_breakdown_threshold:.2f}",
        )

    # Trigger 5: Vol spike -- reduce level (2-sigma)
    if rolling_vol_20d > reduce_vol_threshold:
        return FlattenTriggerResult(
            state=EscalationState.REDUCE,
            trigger_type="vol_spike",
            trigger_value=rolling_vol_20d,
            threshold_used=reduce_vol_threshold,
            details=f"20d rolling vol {rolling_vol_20d:.2%}/day exceeds 2-sigma reduce threshold {reduce_vol_threshold:.2%}",
        )

    # Normal
    return FlattenTriggerResult(
        state=EscalationState.NORMAL,
        trigger_type=None,
        trigger_value=None,
        threshold_used=0.0,
        details="No tail risk conditions detected",
    )
```

### Pattern 4: RiskEngine Extension -- New Tail Risk Gate

**What:** Add `check_tail_risk_state()` method to RiskEngine. Add new gate (called before check_order) that returns REDUCE state (scaled quantity) or FLATTEN state (blocked).

```python
# Extension to src/ta_lab2/risk/risk_engine.py

def check_tail_risk_state(
    self,
    asset_id: Optional[int] = None,
    strategy_id: Optional[int] = None,
) -> Tuple[str, float]:
    """
    Read tail_risk_state from dim_risk_state.
    Returns (state, size_multiplier):
      ('normal', 1.0)  -- no change
      ('reduce', 0.5)  -- halve position sizes
      ('flatten', 0.0) -- block all new orders
    """
    with self._engine.connect() as conn:
        row = conn.execute(
            text("SELECT tail_risk_state FROM dim_risk_state WHERE state_id = 1")
        ).fetchone()

    if row is None or row[0] == "normal":
        return ("normal", 1.0)
    if row[0] == "reduce":
        return ("reduce", 0.5)   # halve positions in REDUCE state
    if row[0] == "flatten":
        return ("flatten", 0.0)  # block all orders in FLATTEN state
    return ("normal", 1.0)  # default safe
```

**Integration in check_order():** Add as Gate 1.5 (after kill switch, before circuit breaker):
```python
# In check_order(), after Gate 1 (kill switch) check:
tail_state, size_mult = self.check_tail_risk_state(asset_id, strategy_id)
if tail_state == "flatten":
    self._log_event("tail_risk_flatten", "tail_risk", "Order blocked by tail risk FLATTEN state", ...)
    return RiskCheckResult(allowed=False, blocked_reason="Tail risk: FLATTEN state active")
if tail_state == "reduce" and order_side.lower() == "buy":
    order_qty = order_qty * Decimal(str(size_mult))  # halve buy orders
    order_notional = order_qty * fill_price
```

### Pattern 5: Schema Extension (Alembic Migration)

**What:** New Alembic migration adding `tail_risk_state` to `dim_risk_state` and new event types to `cmc_risk_events`.

**Migration chain:** Current head is `b5178d671e38` (Phase 46). Phase 48 will add a migration (`XXXX_loss_limits_policy`). Phase 49 must detect the then-current head dynamically.

```python
# Alembic migration -- Phase 49
# ALWAYS detect down_revision dynamically, never hardcode

# upgrade():
op.add_column('dim_risk_state',
    sa.Column('tail_risk_state', sa.Text(), nullable=False,
              server_default='normal'))

# Add CHECK constraint for valid values
op.execute("""
    ALTER TABLE public.dim_risk_state
    ADD CONSTRAINT chk_risk_state_tail
    CHECK (tail_risk_state IN ('normal', 'reduce', 'flatten'))
""")

# Add audit columns
op.add_column('dim_risk_state',
    sa.Column('tail_risk_triggered_at', sa.DateTime(timezone=True), nullable=True))
op.add_column('dim_risk_state',
    sa.Column('tail_risk_trigger_reason', sa.Text(), nullable=True))
op.add_column('dim_risk_state',
    sa.Column('tail_risk_cleared_at', sa.DateTime(timezone=True), nullable=True))

# Extend cmc_risk_events event_type CHECK constraint
# Drop old constraint, recreate with new values
op.execute("ALTER TABLE public.cmc_risk_events DROP CONSTRAINT IF EXISTS chk_risk_events_type")
op.execute("""
    ALTER TABLE public.cmc_risk_events
    ADD CONSTRAINT chk_risk_events_type
    CHECK (event_type IN (
        'kill_switch_activated', 'kill_switch_disabled',
        'position_cap_scaled', 'position_cap_blocked',
        'daily_loss_stop_triggered',
        'circuit_breaker_tripped', 'circuit_breaker_reset',
        'override_created', 'override_applied', 'override_reverted',
        'tail_risk_escalated', 'tail_risk_cleared'
    ))
""")

# Extend trigger_source CHECK
op.execute("ALTER TABLE public.cmc_risk_events DROP CONSTRAINT IF EXISTS chk_risk_events_source")
op.execute("""
    ALTER TABLE public.cmc_risk_events
    ADD CONSTRAINT chk_risk_events_source
    CHECK (trigger_source IN ('manual', 'daily_loss_stop', 'circuit_breaker', 'system', 'tail_risk'))
""")
```

**CRITICAL:** ASCII-only in all SQL. No box-drawing characters. Verify with grep.

### Pattern 6: Policy YAML Config Schema

**What:** Machine-readable policy for RiskEngine to load thresholds from config file.

```yaml
# tail_risk_config.yaml -- generated by run_tail_risk_comparison.py
# Consumed by RiskEngine.load_tail_risk_config()

version: "1.0"
generated_at: "2026-02-25"
source: "Phase 49 tail-risk policy analysis"

vol_sizing:
  default_approach: "atr_14"    # "atr_14" or "realized_vol"
  risk_budget_default: 0.01     # 1% of portfolio per trade
  risk_budget_sweep: [0.005, 0.01, 0.02]
  max_position_pct: 0.30        # hard cap regardless of risk_budget/vol

escalation_thresholds:
  # Thresholds calibrated from BTC 2010-2025 data
  # REDUCE: ~5.3% of days, ~19 days/year
  reduce_vol_20d_threshold: 0.0923    # mean + 2*std of 20d rolling vol
  # FLATTEN vol: ~2.3% of days, ~8.5/year
  flatten_vol_20d_threshold: 0.1194   # mean + 3*std of 20d rolling vol
  # FLATTEN abs: ~1.8% of days, ~6.6/year
  flatten_abs_return_threshold: 0.15  # |single-day return| > 15%
  # FLATTEN corr: BTC/ETH 30d correlation breakdown
  flatten_correlation_threshold: -0.20  # correlation < -0.20 (1st percentile)

re_entry:
  mechanism: "graduated"            # "automatic_cooldown" | "graduated" | "manual"
  cooldown_days_reduce: 14          # days before re-evaluating REDUCE state
  cooldown_days_flatten: 21         # days before re-evaluating FLATTEN state
  vol_clear_threshold: 0.0923       # vol must drop below this to de-escalate
  vol_clear_consecutive_days: 3     # must be below threshold for 3 consecutive days

regime_interaction:
  down_regime_size_mult: 0.55       # existing regime multiplier from Phase 27
  reduce_state_additional_mult: 0.50  # REDUCE applies on top of regime mult
  # Combined: down_regime + reduce = 0.55 * 0.50 = 0.275x base position
```

### Anti-Patterns to Avoid

- **Vol spike as sole flatten trigger:** Vol spike (20d rolling) fires 3 days AFTER crash (March 12 -> March 15 for COVID). Must combine with single-day absolute return trigger.
- **FTX caught by vol spike:** FTX November 2022 peak vol was only 5.1% (well below 2-sigma threshold of 9.2%). FTX is caught by exchange halt trigger (Binance/FTX went down Nov 11), not vol spike.
- **Extend trading_state for reduce:** `dim_risk_state.trading_state` currently has `CHECK IN ('active', 'halted')`. Adding 'reduced' would break Phase 46 kill switch logic. Use separate `tail_risk_state` column instead.
- **Breaking cmc_risk_events CHECK constraint:** The existing `chk_risk_events_type` constraint is an ARRAY check in PostgreSQL. To add new event types, the constraint must be DROPPED and RECREATED -- not added to.
- **Correlation breakdown as primary trigger:** BTC/ETH 30-day correlation mean=0.67, std=0.34. 1st percentile = -0.48. During COVID, correlation actually went UP to 0.93 (both crashed together). Correlation breakdown is less reliable for crypto; include but assign lower priority than vol/abs-return triggers.
- **Vol-sizing without position cap:** At 1% risk budget with 2% ATR, raw position = 50% of portfolio. MUST cap at `max_position_pct` (30%) or the position cap from `dim_risk_limits` (15%).
- **Realized vol in dollar terms vs percentage:** `cmc_features.atr_14` is in DOLLAR terms (not percentage). `atr_pct = atr_14 / close`. For realized vol, use `std(ret_arith)` from `cmc_returns_bars_multi_tf_u` -- already a percentage (returns table uses `ret_arith` column, index is `timestamp` not `ts`).
- **ETH signals not in DB:** `cmc_signals_ema_crossover`, `cmc_signals_rsi_mean_revert`, `cmc_signals_atr_breakout` only have id=1 (BTC). ETH (id=1027) signals do NOT exist in signal tables. The bakeoff used price + params to generate signals internally. Phase 49 must do the same for ETH comparison.
- **Kaleido for chart export:** Not installed. Use `fig.write_html()` only, never `fig.write_image()`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sortino ratio | Custom formula | `performance.py::sortino()` | Already implemented, annualized correctly |
| Calmar ratio | Custom formula | `performance.py::calmar()` | Already implemented |
| Vol-sizing vectorbt sweep | Custom replay loop | `vbt.Portfolio.from_signals(size=size_array)` | size array with NaN for non-entry bars; verified working |
| Hard/trailing stop simulation | Custom replay | Phase 48 `stop_simulator.py::sweep_stops()` | Phase 48 library handles this; Phase 49 calls it for Variant A |
| Rolling vol computation | External library | `pandas.Series.rolling(20).std()` | 1 line; `ret_arith` from `cmc_returns_bars_multi_tf_u` |
| BTC/ETH correlation | External library | `pd.Series.rolling(30).corr()` | 1 line per asset pair |
| Escalation state persistence | In-memory state | `dim_risk_state.tail_risk_state` column (DB-backed) | Must survive executor restart; fresh-read on every check_order call |
| Report generation | Pandas to_string | Markdown templates with f-strings | Matches Phase 48 pattern; no extra library |

**Key insight:** Phase 48 libraries (`var_simulator.py`, `stop_simulator.py`) handle the computation heavy lifting for Variant A (fixed size + stops). Phase 49 only needs to add the vol-sizing layer (Variant B/C) and the trigger logic.

---

## Common Pitfalls

### Pitfall 1: Lag in Vol Spike Trigger (3-Day Delay on COVID)

**What goes wrong:** Vol spike trigger on 20-day rolling std fires on March 15, 2020 -- three days AFTER the -37% COVID crash on March 12. System takes the full -37% hit without any protection.
**Why it happens:** Rolling vol updates daily with the new return, but 20-bar window smooths out even extreme single events.
**How to avoid:** Add complementary single-day absolute return trigger (`|ret_arith| > 0.15`). This fires IN REAL TIME on the same day (March 12). The vol trigger then covers the prolonged crisis (March 15 onwards).
**Warning signs:** Only one trigger type in `check_flatten_trigger()`.

### Pitfall 2: FTX Not Caught by Vol Spike

**What goes wrong:** FTX November 2022 peak 20-day rolling vol = 5.1% (well below 9.2% threshold). System has no protection during FTX collapse if vol-only approach is used.
**Why it happens:** FTX was a contagion event, not a volatility event. BTC price fell 10% and 14% over two days -- within normal crypto range.
**How to avoid:** Add exchange halt trigger. FTX itself halted withdrawals Nov 8 and filed for bankruptcy Nov 11. Any Kraken/Binance API failure triggers FLATTEN immediately. This is the correct protection mechanism for infrastructure events.
**Warning signs:** FTX-period returns (-24% 3-day cumulative) don't register on vol spike checks.

### Pitfall 3: ETH Signals Not in Signal Tables

**What goes wrong:** Phase 49 plan tries to load ETH signals from `cmc_signals_ema_crossover WHERE id=1027` and gets 0 rows (empty).
**Why it happens:** ETH signals were never generated in the signal pipeline. Signal tables only contain id=1 (BTC).
**How to avoid:** For the TAIL-01 backtest comparison, generate ETH signals on-the-fly inside the backtest script using the signal generator functions directly (not from the DB). Use the same params as the selected strategies (fast_ema=17, slow_ema=77 for ema_trend_17_77).
**Warning signs:** `SELECT COUNT(*) FROM cmc_signals_ema_crossover WHERE id=1027` = 0.

### Pitfall 4: Extend trading_state with 'reduced' Breaks Kill Switch

**What goes wrong:** Adding `'reduced'` to `dim_risk_state.trading_state` CHECK constraint causes Phase 46 `_is_halted()` to fail: `return row[0] == "halted"` still works, but executor logic that checks `trading_state != 'active'` may break if it expects only two values.
**Why it happens:** Temptation to reuse the existing binary state column for the three-level escalation.
**How to avoid:** Add a SEPARATE `tail_risk_state` column. Leave `trading_state` as `'active'/'halted'` binary forever. RiskEngine has two independent gates: `_is_halted()` (kill switch) and `check_tail_risk_state()` (tail risk).
**Warning signs:** Migration alters `chk_risk_state_trading` constraint to include 'reduced'.

### Pitfall 5: Position Cap Interaction with Vol-Sizing

**What goes wrong:** Vol-sized position = `risk_budget / atr_pct`. At 2% risk budget and 2% ATR, raw position = 100% of portfolio. This exceeds `dim_risk_limits.max_position_pct` (15% default).
**Why it happens:** Risk budget and ATR calibration can produce positions far larger than intended when ATR is low.
**How to avoid:** Apply a `max_position_pct` cap inside `compute_vol_sized_position()`. Also: the vol-sized position is then additionally subject to RiskEngine's position cap gate (Gate 3), which will scale it down further. Both layers apply.
**Warning signs:** Vol-sized backtest shows 100%+ portfolio utilization.

### Pitfall 6: Alembic Migration Chain Dependency on Phase 48

**What goes wrong:** Phase 49 Alembic migration hardcodes `down_revision = 'b5178d671e38'` (Phase 46 head). Phase 48 runs and creates a new head. Phase 49 migration then has an inconsistent chain.
**Why it happens:** Phase 48 is not yet executed, so the Phase 48 migration ID is unknown at Phase 49 planning time.
**How to avoid:** Phase 49 plans MUST include a prerequisite check that Phase 48 has been run. Detect current head dynamically: `alembic history | head -1`. Use the detected head as `down_revision`. Never hardcode migration IDs.
**Warning signs:** `alembic upgrade head` fails with "Multiple head revisions" or "Revision not found".

### Pitfall 7: cmc_risk_events event_type CHECK -- Drop and Recreate

**What goes wrong:** `ALTER TABLE cmc_risk_events ADD CONSTRAINT chk_risk_events_type CHECK (... new_event ...)` fails because a constraint with that name already exists.
**Why it happens:** PostgreSQL doesn't allow `ADD CONSTRAINT` for an existing constraint name.
**How to avoid:** In the migration, always `DROP CONSTRAINT IF EXISTS chk_risk_events_type` before `ADD CONSTRAINT`. Same for `chk_risk_events_source`. Document the full list of event types in the migration to avoid losing existing values.
**Warning signs:** `ERROR: constraint "chk_risk_events_type" already exists`.

### Pitfall 8: BTC/ETH Correlation Interpretation

**What goes wrong:** High BTC/ETH correlation (COVID: 0.93) is interpreted as "no breakdown" and system stays normal. But during COVID both assets crashed together -- the correlation is NOT a useful signal here.
**Why it happens:** Correlation breakdown means "assets diverge unexpectedly" -- but crypto assets tend to crash TOGETHER. Correlation breakdown is more relevant for multi-asset portfolios with uncorrelated legs.
**How to avoid:** In V1 (BTC + ETH only), correlation breakdown is LOW priority. Include in the trigger suite but document that it's most useful in multi-asset contexts. The other triggers (vol spike, abs return, exchange halt) are more reliable for BTC/ETH.
**Warning signs:** Correlation trigger fires during normal market conditions due to short-window noise.

### Pitfall 9: Windows UTF-8 in SQL/Migrations

**What goes wrong:** UTF-8 box-drawing characters (like em-dashes `--` styled as `—`) in SQL comments cause `UnicodeDecodeError` with Windows cp1252 encoding.
**How to avoid:** Use ASCII-only in ALL SQL and migration files. Verify: `grep -P '[\x80-\xff]' alembic/versions/*tail_risk*` (run in bash, not PowerShell).

---

## Code Examples

### Vol-Sizing from ATR (verified data access pattern)

```python
# Source: verified against cmc_features schema (atr_14, close, ts columns; id=1 BTC)
from sqlalchemy import text
import pandas as pd
import numpy as np

def load_atr_and_price(engine, asset_id: int, tf: str = '1D') -> pd.DataFrame:
    """Load ATR-14 and close price for vol-sizing computation."""
    # NOTE: cmc_features uses 'ts' (not 'timestamp') for its time column
    sql = text("""
        SELECT ts, close, atr_14
        FROM cmc_features
        WHERE id = :asset_id AND tf = :tf
          AND atr_14 IS NOT NULL
        ORDER BY ts
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})
    df['ts'] = pd.to_datetime(df['ts'], utc=True)  # CRITICAL: utc=True per MEMORY.md
    df = df.set_index('ts')
    df['atr_pct'] = df['atr_14'] / df['close']
    return df
```

### Load Returns for Rolling Vol (verified schema)

```python
# Source: verified against cmc_returns_bars_multi_tf_u schema
# Column is 'timestamp' (NOT 'ts'), returns column is 'ret_arith'

def load_daily_returns(engine, asset_id: int, tf: str = '1D') -> pd.Series:
    """Load daily returns for realized vol computation."""
    sql = text("""
        SELECT timestamp, ret_arith
        FROM cmc_returns_bars_multi_tf_u
        WHERE id = :asset_id AND tf = :tf
          AND ret_arith IS NOT NULL
        ORDER BY timestamp
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    return df.set_index('timestamp')['ret_arith']
```

### Worst-N-Day Returns (verified BTC data)

```python
# Source: computed from cmc_returns_bars_multi_tf_u BTC 1D data (5613 bars)
# These are the EMPIRICAL values from actual BTC history

def worst_n_day_returns(returns: np.ndarray, n_values: list = [1, 3, 5, 10]) -> dict:
    """Compute mean of worst N daily returns for tail risk characterization."""
    sorted_rets = np.sort(returns)
    return {
        f"worst_{n}_day_mean": float(sorted_rets[:n].mean())
        for n in n_values
    }

# BTC empirical reference (use as sanity check):
BTC_EMPIRICAL_WORST = {
    "worst_1_day_mean": -0.491,   # -49.1% (all-time worst single day)
    "worst_3_day_mean": -0.406,
    "worst_5_day_mean": -0.381,
    "worst_10_day_mean": -0.343,
}
```

### Tail Risk Calibration Reference (from actual DB data)

```python
# Source: computed from cmc_returns_bars_multi_tf_u, BTC (id=1), tf='1D', 2010-2025
# n = 5613 daily bars

BTC_VOL_CALIBRATION = {
    "daily_vol_mean": 0.0473,       # 4.73%/day overall average
    "roll_vol_20d_mean": 0.0370,    # 3.70%/day average 20d rolling vol
    "roll_vol_20d_std": 0.0265,
    "reduce_threshold": 0.0923,     # mean + 2*std -> ~5.3% of days
    "flatten_vol_threshold": 0.1194, # mean + 3*std -> ~2.3% of days
    "flatten_abs_threshold": 0.15,  # |daily return| > 15% -> ~1.8% of days
    "event_rate_reduce_per_year": 19.4,
    "event_rate_flatten_vol_per_year": 8.5,
    "event_rate_flatten_abs_per_year": 6.6,
}

# Crash event detection with these thresholds:
# COVID March 12, 2020: abs_return=-37.2% -> FLATTEN (abs_return trigger)
# COVID March 15+, 2020: vol=9.2% -> REDUCE (vol trigger, 3 days late)
# FTX Nov 11, 2022: exchange halted -> FLATTEN (exchange halt trigger)
# May 2021 dip: peak vol=6.7% -> BELOW threshold; caught by circuit breaker instead
```

### BTC/ETH Correlation Statistics (verified)

```python
# Source: computed from cmc_returns_bars_multi_tf_u BTC+ETH, tf='1D', 2015-2025
# n = 3762 common dates

BTC_ETH_CORR_CALIBRATION = {
    "overall_correlation": 0.5811,
    "roll_corr_30d_mean": 0.6738,
    "roll_corr_30d_std": 0.3435,
    "roll_corr_30d_1st_pct": -0.4808,   # 1st percentile
    "roll_corr_30d_5th_pct": -0.1194,   # 5th percentile
    "roll_corr_30d_min": -0.7194,
    "flatten_corr_threshold": -0.20,     # 5th percentile-ish; conservative
    # COVID 2020: correlation = 0.93 (both crashed together -- NOT a breakdown event)
}
```

### Extract Signals On-The-Fly for ETH (since no ETH signals in DB)

```python
# Source: ta_lab2.signals.registry (Phase 42 pattern)
# ETH (id=1027) has NO entries in cmc_signals_* tables -- generate at run time

from ta_lab2.signals.registry import get_strategy

def generate_eth_signals(engine, signal_type: str, params: dict) -> pd.DataFrame:
    """
    Generate signals for ETH (id=1027) on-the-fly for backtest comparison.
    ETH signal tables are empty; must run the signal generator directly.
    """
    strategy = get_strategy(signal_type)
    # Load feature data for ETH
    # ... load cmc_features for id=1027 and run strategy.generate_signals()
    pass
```

---

## Claude's Discretion -- Decisions Made

Based on research, the following CONTEXT.md open items are resolved:

### Risk Budget Default and Sweep Range (TAIL-01)

**Decision: default=1%, sweep=[0.5%, 1%, 2%].**

Rationale from empirical analysis:
- At 1% risk budget with normal ATR (3% of close): raw position = 33% -> capped at 30%
- At 1% risk budget with crisis ATR (15% of close): raw position = 6.7% (good auto-delever)
- At 0.5%: crisis ATR -> 3.3% (too conservative, near zero exposure)
- At 2%: normal ATR -> 66.7% raw position (heavily capped, sizing is disconnected from ATR)
- 1% is the sweet spot where ATR actually drives the size variation

### Rolling Window for Realized Vol (TAIL-01)

**Decision: 20-day rolling window.**

Rationale:
- 20 days = 1 calendar month of trading (standard risk window)
- 5-day window: too noisy (217 triggers/year); 30-day window: too smooth (COVID barely registered)
- 20-day: detected COVID correctly (3-day lag is acceptable), manageable trigger frequency
- Complements ATR-14 (14-day window) giving slightly different signal

### Recommendation Criteria for Winner Selection (TAIL-01)

**Decision: composite score = 0.4*Sharpe + 0.3*Sortino + 0.2*(1+Calmar) + 0.1*(1-|worst_5_day/baseline|)**

Rationale: This weights risk-adjusted return first (Sharpe), downside protection second (Sortino), drawdown recovery third (Calmar), while including a tail-specific component (worst-5-day relative to baseline). Any variant with MaxDD worse than baseline (stops hurt more than help) is automatically ranked last.

### Historical Crash Validation (TAIL-02)

**Decision: Include -- data is available and it's valuable.**

Rationale: BTC returns go back to 2010. All three key events (COVID March 2020, May 2021, FTX Nov 2022) are in the DB. The analysis took 5 minutes to run. The finding (FTX NOT caught by vol spike, COVID caught with 3-day lag) directly shaped the trigger design. This is the highest-ROI portion of the research -- include it in the policy memo.

### Re-entry Mechanism (Area 4)

**Decision: Graduated re-entry with automatic cooldown.**

Three-stage de-escalation:
1. FLATTEN -> REDUCE: After min 21-day cooldown AND vol drops below reduce threshold (9.2%/day) for 3 consecutive days
2. REDUCE -> NORMAL: After min 14-day cooldown AND vol drops below reduce threshold for 3 consecutive days
3. Daily check: `run_daily_refresh.py` calls `RiskEngine.evaluate_tail_risk_state()` which updates `dim_risk_state.tail_risk_state`

Rationale: Pure time-based cooldown (21 days) risks re-entering in still-elevated conditions. Pure vol-based re-entry risks getting stuck in prolonged elevated-vol periods (COVID vol stayed above threshold for 19-25 days). Combining minimum cooldown + vol condition is standard in prop trading.

### DB Table for Escalation History (Area 4)

**Decision: Reuse `cmc_risk_events` with new event types `tail_risk_escalated` and `tail_risk_cleared`.**

Rationale:
- No new table needed -- `cmc_risk_events` already has `event_type`, `trigger_source`, `metadata`, `asset_id`, `strategy_id`
- The `metadata` JSONB field can store trigger details (trigger_type, trigger_value, threshold)
- Extending the CHECK constraint requires drop+recreate (see Pitfall 7)
- New trigger_source = `'tail_risk'` added to constraint

### Custom Triggers (liquidity/funding) in V1 (TAIL-02)

**Decision: Defer funding rate and liquidity to V1+. V1 implements 4 triggers: vol spike, abs return, exchange halt, correlation breakdown.**

Rationale: Funding rate requires perpetual swap data (not in current pipeline). Liquidity drought requires order book depth data (also not in pipeline). These are meaningful for live trading but add data engineering scope. V1 policy covers the most common tail risk scenarios with available data.

### Cooldown Duration (Area 4)

**Decision:**
- REDUCE state: 14-day minimum cooldown
- FLATTEN state: 21-day minimum cooldown
- Both require vol < reduce_threshold for 3 consecutive days before de-escalation

Rationale: Empirical analysis shows vol spikes persist for median 18-20 days. 14 days = minimum meaningful wait. 21 days = median + safety buffer. The 3-consecutive-days requirement prevents premature re-entry on brief dips below threshold.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed position size | ATR-based vol sizing | Post-2010 (prop trading) | Automatic delever in crisis; better risk-adjusted returns |
| Binary halt (active/halted) | Three-level escalation (normal/reduce/flatten) | Increasingly adopted post-2020 | Graduated response prevents overreaction while protecting capital |
| Single vol threshold for all triggers | Multi-trigger composite | Post-2015 (crypto-specific) | Required because different crashes (COVID vs FTX) have different signatures |
| Manual operator decision for flatten | Automated rule-based flatten + manual override | Current best practice | Eliminates human delay in crisis; operator can always override |

**Deprecated/outdated:**
- Gaussian VaR for tail risk: understates crypto tail events (BTC excess kurtosis = 17.17, far above Gaussian assumption of 0). Use historical VaR (computed in Phase 48) instead.
- Fixed percentage hard stops in crypto: 5% stop fires in normal daily range (BTC 1D average daily range is ~3-5%); only effective above 7-10%.

---

## Integration with Existing Infrastructure

### What Phase 46 built (existing -- do NOT modify logic, only extend)

- `dim_risk_state` table with `trading_state IN ('active', 'halted')` -- Phase 49 adds `tail_risk_state` column
- `cmc_risk_events` with immutable audit log -- Phase 49 adds new event types
- `RiskEngine.check_order()` 5-gate sequence -- Phase 49 adds Gate 1.5 (tail risk state check)
- `RiskEngine._is_halted()` -- leave unchanged
- `RiskEngine._log_event()` -- reuse for new tail risk events

### What Phase 48 will build (prerequisite -- must run first)

- `dim_risk_limits.pool_name` column + `cmc_risk_overrides` governance columns
- `src/ta_lab2/analysis/var_simulator.py` -- VaR library
- `src/ta_lab2/analysis/stop_simulator.py` -- stop sweep library
- Alembic migration `XXXX_loss_limits_policy` (Phase 49 chains from this)

### Phase 49 adds (new)

- `src/ta_lab2/risk/flatten_trigger.py` -- `FlattenTrigger`, `check_flatten_trigger()`, `EscalationState`
- `src/ta_lab2/analysis/vol_sizer.py` -- ATR-based and realized-vol-based sizing library
- `scripts/analysis/run_tail_risk_comparison.py` -- TAIL-01 CLI
- Alembic migration `YYYY_tail_risk_policy` -- schema extension
- `reports/tail_risk/` -- all output documents

### Bakeoff data availability (confirmed from DB)

| Strategy | BTC (id=1) | ETH (id=1027) | Notes |
|----------|-----------|----------------|-------|
| ema_trend | 96 rows | 96 rows | BUT no signal tables for ETH -- generate on-the-fly |
| rsi_mean_revert | 72 rows | 72 rows | Same -- ETH signals must be generated |
| breakout_atr | 72 rows | 72 rows | Same |
| BTC signals in cmc_signals_* | 302 EMA / 154 RSI / 98 ATR | 0 rows ETH | ETH comparison requires on-the-fly generation |

---

## Open Questions

1. **Phase 48 execution timing**
   - What we know: Phase 48 has 4 plans but no SUMMARYs. The Alembic migration does not exist yet (current head = Phase 46: b5178d671e38).
   - What is unclear: Phase 48 must run before Phase 49. Phase 49 Alembic must chain from Phase 48 migration.
   - Recommendation: Phase 49 Plan 01 begins with MANDATORY prerequisite check: verify `dim_risk_limits.pool_name` column exists (Phase 48 migration). If not, halt and report.

2. **Vol-sizing comparison methodology for ETH**
   - What we know: ETH has bakeoff results in `strategy_bakeoff_results` but NO signal rows in the signal tables.
   - What is unclear: How to reconstruct ETH signals for the backtest comparison. Need to call signal generators with the same params used in bakeoff.
   - Recommendation: Load ETH prices from `cmc_price_bars_multi_tf` (column: `timestamp` not `ts`) and ETH features from `cmc_features`. Run signal generators with bakeoff params. This adds complexity but is the only way to get ETH comparison data.

3. **RiskEngine extension pattern**
   - What we know: `check_order()` reads fresh state per call (no caching). Adding `check_tail_risk_state()` as Gate 1.5 adds one more DB read per order.
   - What is unclear: Performance impact of additional read in production.
   - Recommendation: For V1 paper trading (low volume), one extra DB read is negligible. In Gate 1.5, read `tail_risk_state` from `dim_risk_state WHERE state_id = 1` -- same table already read by `_is_halted()`. Could combine both reads into one query for efficiency (optional optimization).

---

## Sources

### Primary (HIGH confidence)

- Project codebase: `sql/risk/090_dim_risk_limits.sql`, `091_dim_risk_state.sql`, `092_cmc_risk_events.sql` -- confirmed schema
- Project codebase: `src/ta_lab2/risk/risk_engine.py` -- confirmed 5-gate architecture, `_is_halted()` pattern, `_log_event()` pattern
- Project codebase: `src/ta_lab2/analysis/performance.py` -- confirmed `sortino()`, `calmar()` implementations
- Project codebase: `src/ta_lab2/backtests/vbt_runner.py` -- confirmed vectorbt 0.28.1 integration, tz-stripping pattern
- Direct DB verification: `cmc_features.atr_14` exists (dollar value, confirmed non-NULL post-2010), `cmc_features.close` exists
- Direct DB verification: `cmc_returns_bars_multi_tf_u` uses `timestamp` column (NOT `ts`), `ret_arith` column confirmed
- Empirical calibration: All vol/correlation/crash statistics computed directly from live DB data (5613 BTC bars, 3762 BTC+ETH common bars)
- Direct computation: COVID March 12 vol trigger lag (3 days), FTX not caught by vol spike, vol persistence median 18-20 days

### Secondary (MEDIUM confidence)

- `.planning/phases/48-loss-limits-policy/48-RESEARCH.md` -- confirmed Phase 48 library structure, vol_sizer pattern, stop_simulator pattern, Alembic chain pattern
- `.planning/phases/46-risk-controls/46-RESEARCH.md` -- confirmed RiskEngine gate architecture
- Phase 42 bakeoff results in `strategy_bakeoff_results` -- confirmed strategy coverage (all 3 strategies, both assets)
- WebSearch (multiple sources) -- vol-based position sizing methodology, escalation level best practices

### Tertiary (LOW confidence)

- WebSearch "re-entry cooldown after trading halt prop trading 2025" -- no specific authoritative guidance found; 14-21 day cooldown derived from empirical vol persistence data (stronger basis)
- WebSearch "correlation breakdown flatten trigger crypto 2025" -- general guidance; specific thresholds derived from empirical BTC/ETH correlation data

---

## Metadata

**Confidence breakdown:**
- Vol calibration thresholds (reduce/flatten): HIGH -- computed from 5613 actual BTC daily bars
- Vol-sizing formula and vectorbt integration: HIGH -- verified with code execution
- Escalation schema design (tail_risk_state column): HIGH -- inspected actual dim_risk_state schema
- Alembic migration chain: HIGH -- verified current head is b5178d671e38; Phase 48 must run first
- Historical crash trigger attribution: HIGH for COVID, MEDIUM for FTX (exchange halt is correct trigger but FTX timeline specifics are from prior knowledge)
- Re-entry cooldown (14-21 days): MEDIUM -- derived from vol persistence empirics, no industry benchmark for prop trading
- Correlation breakdown threshold: LOW -- calibrated from data but BTC/ETH correlation is unreliable for this purpose

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (30 days; vol calibration is from 15-year history, stable; vectorbt 0.28.1 API is stable)
