# Phase 45: Paper-Trade Executor - Research

**Researched:** 2026-02-24
**Domain:** Paper trading execution engine, slippage simulation, position sizing, backtest parity verification, pipeline integration
**Confidence:** HIGH (architecture, pipeline patterns, position sizing math) | MEDIUM (slippage distribution) | LOW (exact slippage bps benchmarks for this project's order sizes)

---

## Summary

Phase 45 builds the paper-trade executor: an engine that reads from `cmc_signals_*` tables,
translates signals into paper orders via Phase 43's `CanonicalOrder` + `PaperOrderLogger`, promotes
those orders into Phase 44's `cmc_orders`/`cmc_fills`/`cmc_positions` lifecycle, and tracks per-strategy
positions independently. The executor runs daily (wired into `run_daily_refresh.py --all`) and supports
on-demand standalone invocation.

The primary engineering challenge is not performance (volumes are tiny -- 2 V1 strategies, ~100
assets) but correctness: signal deduplication, stale-signal detection, backtest parity under zero
noise, and clean separation of strategy-scoped positions. All infrastructure (order lifecycle, position
math, atomic transactions) exists from Phase 44; Phase 45 is the consumer of that infrastructure.

The slippage simulation model uses a **volume-adaptive log-normal noise** approach: a deterministic
base slippage (proportional to volatility * sqrt(order_size/ADV)) plus multiplicative log-normal
noise drawn from N(0, sigma^2) in log space. This mirrors the Talos Market Impact Model's empirical
finding that real crypto slippage is right-skewed (most fills near 0, occasional spikes). For 1D
daily strategies at 10% position fraction on liquid pairs (BTC/USD, ETH/USD), realistic base slippage
is 2-8 bps with noise sigma of 0.5 in log space.

**Primary recommendation:** Build the executor as a single `PaperExecutor` class in
`src/ta_lab2/executor/paper_executor.py`, driven by a DB-backed `dim_executor_config` table seeded
from YAML. The executor reads new signals via watermark, generates orders for delta between current
and target positions, simulates fills immediately (two-phase: paper -> cmc_orders -> fill), and
writes results atomically via Phase 44's `OrderManager`.

---

## Standard Stack

### Core (No New Dependencies)

| Library | Version | Purpose | Already Installed |
|---------|---------|---------|------------------|
| `sqlalchemy` | existing | `engine.begin()` transactions, `text()` queries | YES |
| `alembic` | existing | Schema migration for `dim_executor_config` | YES |
| `numpy` | existing | Log-normal random draws for slippage noise | YES |
| `dataclasses` | stdlib | `ExecutorConfig`, `FillResult`, `ExecutionDecision` dataclasses | YES |
| `decimal` | stdlib | Exact arithmetic for position sizing and cost basis | YES |
| `typing` | stdlib | Type hints | YES |
| `logging` | stdlib | Decision logging (every order, every skip, every fill) | YES |
| `argparse` | stdlib | CLI entry point | YES |
| `yaml` | existing | YAML seed for executor config | LIKELY YES (check PyYAML) |

No new packages needed. Phase 45 uses the project's existing stack exclusively.

**Installation:**
```bash
# Verify PyYAML is available (check pyproject.toml / requirements)
python -c "import yaml; print('PyYAML available')"
# If missing: pip install pyyaml
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── executor/                        # NEW package for Phase 45
│   ├── __init__.py
│   ├── paper_executor.py            # PaperExecutor class -- primary deliverable
│   ├── fill_simulator.py            # FillSimulator: slippage model, delay, partial fills
│   ├── position_sizer.py            # PositionSizer: fixed fraction, regime-adjusted, signal-strength
│   ├── signal_reader.py             # SignalReader: watermark query, stale-signal guard
│   └── parity_checker.py            # ParityChecker: replay historical, compare vs backtest DB
│
├── trading/                         # EXISTS from Phase 44
│   ├── order_manager.py             # OrderManager.process_fill() -- consume this
│   └── position_math.py             # compute_position_update() -- consume this
│
└── paper_trading/                   # EXISTS from Phase 43
    ├── canonical_order.py           # CanonicalOrder -- consume this
    └── paper_order_logger.py        # PaperOrderLogger -- consume this

scripts/
├── executor/                        # NEW scripts package
│   ├── __init__.py
│   ├── run_paper_executor.py        # CLI entry point (standalone)
│   └── run_parity_check.py         # Dedicated parity report script

sql/executor/                        # NEW reference DDL
├── 088_dim_executor_config.sql      # Executor config table DDL
└── 089_cmc_executor_run_log.sql     # Run log for audit and stale-signal detection

config/
└── executor_config_seed.yaml        # Version-controlled YAML defaults for V1
```

### Pattern 1: Signal Reader with Watermark + Status Flag Deduplication

**What:** Belt-and-suspenders signal deduplication. Watermark (last processed timestamp) for query
efficiency; `executed` status flag on signals for correctness guard.

**CRITICAL:** The signal tables (`cmc_signals_ema_crossover`, etc.) have PK `(id, ts, signal_id)`.
The executor's watermark tracks the last `ts` it processed per `(strategy_id, signal_type)`. The
status flag tracks individual signal rows already processed.

**Note on signal table schema:** The existing signal tables do NOT have an `executed` boolean flag or
`executor_status` column. Phase 45 must either (a) add this column via migration or (b) track
processed signals in a separate `dim_executor_config` watermark. Given the CONTEXT.md decision for
"belt-and-suspenders", option (a) -- adding `executor_processed_at TIMESTAMPTZ NULL` to each signal
table via migration -- is cleaner than a separate tracking table.

```python
# Source: project pattern from signal_state_manager.py (watermark queries)
# and backtest_from_signals.py (signal reads)

def read_unprocessed_signals(
    conn,
    signal_table: str,    # e.g. 'cmc_signals_ema_crossover'
    signal_id: int,
    last_watermark_ts,    # last processed ts, or None for full history
) -> list[dict]:
    """
    Read signals not yet processed by executor.
    Uses watermark for efficiency + executor_processed_at IS NULL for correctness.
    """
    watermark_clause = "AND ts > :watermark_ts" if last_watermark_ts else ""
    sql = text(f"""
        SELECT id, ts, signal_id, direction, position_state,
               entry_price, entry_ts, exit_price, exit_ts,
               feature_snapshot, params_hash
        FROM public.{signal_table}
        WHERE signal_id = :signal_id
          AND executor_processed_at IS NULL
          {watermark_clause}
        ORDER BY ts ASC
    """)
    params = {"signal_id": signal_id}
    if last_watermark_ts:
        params["watermark_ts"] = last_watermark_ts
    return [dict(row._mapping) for row in conn.execute(sql, params)]
```

### Pattern 2: Stale Signal Guard

**What:** Check that the latest signal timestamp for each active strategy is not older than `cadence_hours`
(default 26 hours for 1D strategies -- 24h cadence + 2h grace). If stale, raise and alert via Telegram.

**Why:** CONTEXT.md decision: "Strict: no stale execution ever." A 1D strategy running on signals
from two days ago could generate deeply wrong orders (wrong direction relative to current market).

```python
# Source: pattern from run_daily_refresh.py (component dependency checks)

def check_signal_freshness(conn, signal_table: str, signal_id: int, cadence_hours: float = 26.0) -> None:
    """
    Raise StaleSignalError if latest signal is older than cadence_hours.
    Called before any order generation.
    """
    row = conn.execute(text(f"""
        SELECT MAX(ts) AS latest_ts
        FROM public.{signal_table}
        WHERE signal_id = :signal_id
    """), {"signal_id": signal_id}).fetchone()

    if row is None or row.latest_ts is None:
        raise StaleSignalError(f"No signals found in {signal_table} for signal_id={signal_id}")

    age_hours = (datetime.now(timezone.utc) - row.latest_ts).total_seconds() / 3600
    if age_hours > cadence_hours:
        raise StaleSignalError(
            f"Signal {signal_id} in {signal_table} is {age_hours:.1f}h old "
            f"(threshold: {cadence_hours}h). Refusing to execute stale signals."
        )
```

### Pattern 3: cmc_positions Strategy Extension

**What:** Phase 44's `cmc_positions` PK is `(asset_id, exchange)`. Phase 45 requires
`(asset_id, exchange, strategy_id)` granularity for independent strategy positions. This requires a
migration to alter the PK.

**Migration approach:** Since `cmc_positions` is created in Phase 44 but may have data by the time
Phase 45 runs, the migration should:
1. Add `strategy_id INTEGER NOT NULL DEFAULT 0` column (DEFAULT 0 = aggregate/legacy)
2. Drop the old PK constraint
3. Add new PK `(asset_id, exchange, strategy_id)`
4. Update `v_cmc_positions_agg` view to aggregate across strategy_id too

**The `strategy_id` column** maps to the `executor_config_id` or `signal_id` of the strategy. Use
`executor_config_id` (FK to `dim_executor_config`) to track strategy identity, not `signal_id`
(which varies per signal row). This matches the CONTEXT.md note: "positions tracked per strategy
independently."

```sql
-- Migration: extend cmc_positions PK for multi-strategy
ALTER TABLE public.cmc_positions
    ADD COLUMN IF NOT EXISTS strategy_id INTEGER NOT NULL DEFAULT 0;

ALTER TABLE public.cmc_positions
    DROP CONSTRAINT cmc_positions_pkey;

ALTER TABLE public.cmc_positions
    ADD PRIMARY KEY (asset_id, exchange, strategy_id);

-- strategy_id = 0 means "aggregate / unattributed" (Phase 44 legacy rows)
```

### Pattern 4: Signal-to-Order Translation (Rebalance-to-Target)

**What:** On every run, compute TARGET position from signal + sizing model. Compare to CURRENT position.
Generate orders for the delta. This is the "rebalance-to-target" model from CONTEXT.md.

**Key insight:** For EMA trend strategies, signals are `position_state = 'open'` (hold long/short) or
`position_state = 'closed'` (flat). The executor maps:
- Latest signal for asset is `open, direction=long` -> target_qty = +fraction * portfolio_value / price
- Latest signal for asset is `open, direction=short` -> target_qty = -fraction * portfolio_value / price
- Latest signal for asset is `closed` or no signal -> target_qty = 0

The delta = target_qty - current_qty determines the order side/size.

```python
# Source: vectorbt pattern (entry/exit signal logic), adapted for database signals

def compute_target_position(
    latest_signal: dict | None,
    portfolio_value: Decimal,
    current_price: Decimal,
    config: ExecutorConfig,
) -> Decimal:
    """
    Compute target signed quantity for an asset.

    Returns positive (long), negative (short), or zero (flat).
    """
    if latest_signal is None or latest_signal["position_state"] == "closed":
        return Decimal("0")

    direction = latest_signal["direction"]  # "long" or "short"
    fraction = config.position_fraction      # e.g., Decimal("0.10") for 10%

    # Apply regime adjustment if enabled
    if config.sizing_mode == "regime_adjusted" and latest_signal.get("regime_context"):
        fraction = _apply_regime_adjustment(fraction, latest_signal["regime_context"], config)

    # Quantity = (portfolio * fraction) / price
    notional = portfolio_value * fraction
    qty = notional / current_price

    return qty if direction == "long" else -qty


def compute_order_delta(current_qty: Decimal, target_qty: Decimal) -> Decimal:
    """Returns signed delta: positive = need to buy, negative = need to sell."""
    return target_qty - current_qty
```

### Pattern 5: Two-Phase Fill Simulation (paper_orders -> cmc_orders -> fill)

**What:** Phase 44 designed a two-phase simulation:
1. Log canonical order to `paper_orders` via `PaperOrderLogger` (status='paper')
2. Promote to `cmc_orders` via `OrderManager.promote_paper_order()` (status='created' -> 'submitted')
3. Simulate fill immediately via `FillSimulator.simulate_fill()` + `OrderManager.process_fill()`

For daily paper trading, there is no reason to defer step 3 -- the fill simulator runs in the same
executor invocation immediately after promotion. The two-phase design is preserved for Phase 46
(where risk controls may reject step 3) and Phase 47 (where delay simulation occurs between 2 and 3).

```python
# Pattern: immediate two-phase fill for paper trading
# Source: Phase 44 OrderManager API design

def execute_order(engine, canonical_order: CanonicalOrder, config: ExecutorConfig) -> str:
    """
    Execute a single paper order: log -> promote -> simulate fill -> process fill.
    Returns fill_id.
    """
    # Phase 1: Log to paper_orders (Phase 43 infrastructure)
    logger_obj = PaperOrderLogger(engine=engine)
    paper_uuid = logger_obj.log_order(canonical_order, exchange=config.exchange)

    # Phase 2a: Promote paper order to cmc_orders (Phase 44)
    order_id = OrderManager.promote_paper_order(engine, paper_uuid)

    # Phase 2b: Move order to 'submitted' status
    OrderManager.update_order_status(engine, order_id, "submitted")

    # Phase 3: Simulate fill (configurable slippage, delay, rejection)
    fill_data = FillSimulator.simulate(
        order_id=order_id,
        base_price=config.fill_price,  # next-bar open or exchange mid
        config=config,
    )

    if fill_data is None:
        # Simulated rejection -- mark order as rejected
        OrderManager.update_order_status(engine, order_id, "rejected", reason="simulated_rejection")
        return None

    # Phase 4: Process fill atomically (Phase 44 OrderManager)
    fill_id = OrderManager.process_fill(engine, fill_data)
    return fill_id
```

### Pattern 6: Pipeline Integration (run_daily_refresh.py)

**What:** Add an `--execute` flag and a `run_paper_executor()` function following the exact pattern
of every other component in `run_daily_refresh.py`. The executor runs AFTER signals (which are not
yet in run_daily_refresh.py but will be added first). The `--no-execute` flag skips this stage.

**IMPORTANT FINDING:** The current `run_daily_refresh.py --all` pipeline does NOT include signal
generation or execution. Phase 45 must also add signal generation to the pipeline. Signals run after
regimes (signals need regime context) and before the executor. The pipeline sequence becomes:

```
bars -> EMAs -> AMAs -> desc_stats -> regimes -> [signals] -> [executor] -> stats
```

Where `[signals]` is Phase 35's signal pipeline (already exists as a standalone script) and
`[executor]` is Phase 45.

```python
# Source: run_daily_refresh.py component pattern (e.g., run_regime_refresher)

TIMEOUT_EXECUTOR = 300  # 5 minutes -- daily executor is fast

def run_paper_executor(args, db_url: str) -> ComponentResult:
    """Run paper executor via subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.executor.run_paper_executor",
    ]
    cmd.extend(["--db-url", db_url])

    if args.verbose:
        cmd.append("--verbose")
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    # Print section header (matches all other components)
    print(f"\n{'=' * 70}")
    print("RUNNING PAPER EXECUTOR")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY RUN] Would execute paper executor")
        return ComponentResult("execute", True, 0.0, 0)

    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=TIMEOUT_EXECUTOR
        )
        duration = time.perf_counter() - start

        if result.returncode != 0:
            print(f"\n[ERROR] Paper executor failed with code {result.returncode}")
            if result.stdout:
                print(f"\nSTDOUT:\n{result.stdout}")
            if result.stderr:
                print(f"\nSTDERR:\n{result.stderr}")
            return ComponentResult("execute", False, duration, result.returncode,
                                   f"Exited with code {result.returncode}")

        print(f"\n[OK] Paper executor completed in {duration:.1f}s")
        return ComponentResult("execute", True, duration, result.returncode)

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        return ComponentResult("execute", False, duration, -1,
                               f"Timed out after {TIMEOUT_EXECUTOR}s")
```

### Anti-Patterns to Avoid

- **Running executor before signal freshness check:** Always call `check_signal_freshness()` before
  generating any orders. Never assume signals are fresh just because the signal refresher ran.
- **Using float for position sizing quantities:** Use `Decimal` throughout. Multiply `Decimal * Decimal`.
  Cast DB numeric columns to `Decimal(str(row.quantity))`.
- **Sharing strategy positions in cmc_positions without strategy_id column:** Without the strategy_id
  PK extension, two strategies holding BTC would clobber each other's position rows.
- **Querying `cmc_signals_*` without signal_id filter:** Each signal table holds data for ALL
  dim_signals entries of that type. Always filter by `signal_id = :signal_id`.
- **Skipping the paper_orders step:** Phase 43's `paper_orders` table is the audit trail. Don't
  call `OrderManager.promote_paper_order()` without first logging to `paper_orders`. The two-phase
  flow is required for traceability.
- **Adding signals to the --all pipeline before the executor:** Signals must run first. If signals
  fail, executor must not run (dependency respected by sequential ordering in main()).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic fill processing | Custom multi-step DB writes | `OrderManager.process_fill()` (Phase 44) | Already handles 5-table atomic write with pessimistic lock and dead letter |
| Weighted avg cost basis | Custom position math | `compute_position_update()` (Phase 44) | Handles all cases: new, add, partial close, full close, flip |
| Order lifecycle validation | Ad hoc status checks | `VALID_TRANSITIONS` dict (Phase 44) | 7-state machine already defined |
| Signal reading/watermark | Custom query builder | Extend `SignalStateManager` pattern (existing) | Same watermark architecture used by signal generators |
| Paper order logging | Direct INSERT to cmc_orders | `PaperOrderLogger.log_order()` (Phase 43) | Phase 43 infrastructure handles validation, payload serialization |
| Order canonical format | Exchange-specific dicts | `CanonicalOrder.from_signal()` (Phase 43) | Handles side/direction normalization, validate() |
| Log-normal noise draws | Gaussian approximation | `numpy.random.lognormal()` | Correct right-skewed distribution for slippage |
| Portfolio value calculation | Custom NAV query | Query `v_cmc_positions_agg` + `exchange_price_feed` | View exists from Phase 44; price feed from Phase 43 |

**Key insight:** Phase 45 is primarily a consumer of Phase 43 and Phase 44 infrastructure. The
"hard" problems (atomicity, position math, order lifecycle) are solved. Phase 45's novelty is
the slippage model, position sizing, signal-to-order translation, and the scheduling/pipeline wiring.

---

## Slippage Distribution Research

### What the Literature Says

Empirical research on crypto spot market slippage (2024-2025):

1. **Right-skewed, not symmetric:** Most fills on BTC/USD at $10k-$100k order sizes land within
   0-5 bps of the arrival price (Talos TMI model: "over 26% of samples in 0-5 bps range"). But
   occasional spikes to 20-50 bps occur during volatile sessions. This is a right-skewed distribution.

2. **Volatility is the dominant driver:** "The volatility of the asset is the main driver of
   slippage." Correlation between slippage and volatility is 0.73+ (Amberdata research). Volume
   correlation is surprisingly weak (0.43) for small orders.

3. **Square-root-of-participation-rate formula:** The Talos Market Impact Model (calibrated on
   50,000+ institutional orders) uses: `impact = sigma * sqrt(Q/VT) * sigmoid_adjustment`.
   For small orders (participation rate < 0.5%), the base slippage is 2-8 bps on BTC/USD.

4. **Log-normal noise is the right model:** Since slippage cannot be negative and is right-skewed,
   log-normal is the correct distribution for additive noise. A log-normal with mu=0, sigma=0.5
   produces: median multiplier 1.0x, 90th percentile 1.9x, 99th percentile 4.9x -- matching
   observed spike behavior in crypto fills.

5. **Typical BTC/USD retail order sizes (10% of $100k portfolio = $10k):**
   - Base slippage: 2-5 bps (well inside top-of-book liquidity)
   - With log-normal noise (sigma=0.5): 90th percentile 4-10 bps
   - Maximum realistic (99th pct): 10-25 bps
   - Exchange fee: 5-25 bps (taker) depending on exchange tier

### Recommended Slippage Model

```python
# Source: Talos TMI formula adapted for paper simulation.
# Log-normal noise verified against crypto microstructure literature.
# Confidence: MEDIUM -- formula structure verified, parameters estimated for project's order sizes.

import numpy as np
from decimal import Decimal

def compute_fill_price(
    base_price: Decimal,       # next-bar open or exchange mid
    side: str,                 # 'buy' or 'sell'
    config: FillSimulatorConfig,
    rng: np.random.Generator,  # seeded for reproducibility in parity mode
) -> Decimal:
    """
    Compute fill price with volume-adaptive base slippage + log-normal noise.

    Formula:
        base_slippage_bps = slippage_base_bps * (1 + volume_impact_factor * order_fraction)
        noise_multiplier  = lognormal(mu=0, sigma=config.slippage_noise_sigma)
        total_slippage_bps = base_slippage_bps * noise_multiplier
        fill_offset       = base_price * (total_slippage_bps / 10000)

    Buy orders fill at base_price + offset (adverse).
    Sell orders fill at base_price - offset (adverse).

    Config parameters (stored in dim_executor_config):
        slippage_base_bps: float     # default 3.0 (conservative for BTC/USD retail)
        slippage_noise_sigma: float  # default 0.5 (log-space sigma)
        volume_impact_factor: float  # default 0.1 (small orders -> minimal impact)
        order_fraction: float        # order_notional / avg_daily_volume
    """
    if config.slippage_mode == "zero":
        # Parity mode: no slippage (matches vectorbt backtest with slippage_bps=0)
        return base_price

    # Base slippage scaled by order size relative to daily volume
    base_bps = config.slippage_base_bps * (
        1.0 + config.volume_impact_factor * config.order_fraction
    )

    # Log-normal noise: always >= 0, right-skewed, median=1.0
    noise = rng.lognormal(mean=0.0, sigma=config.slippage_noise_sigma)
    total_bps = base_bps * noise

    offset = float(base_price) * (total_bps / 10_000)

    if side == "buy":
        fill = float(base_price) + offset   # adverse for buyer
    else:
        fill = float(base_price) - offset   # adverse for seller

    return Decimal(str(round(fill, 8)))     # round to 8 decimal places (crypto convention)
```

### Slippage Mode: "zero" for Parity Mode

When running `--replay-historical` for backtest parity verification, set `slippage_mode = "zero"`.
This makes fills at exactly next-bar open price, matching vectorbt's convention when `slippage_bps=0`.
If vectorbt used non-zero slippage in the stored backtest, set `slippage_mode = "fixed"` with
`slippage_base_bps = {the same value used in the backtest}`.

---

## dim_executor_config Table Design

### Recommended DDL

```sql
-- sql/executor/088_dim_executor_config.sql
-- One row per active strategy configuration.
-- Seeded from YAML (config/executor_config_seed.yaml) on first deployment.
-- Changeable without redeployment: UPDATE dim_executor_config SET position_fraction = 0.08.

CREATE TABLE IF NOT EXISTS public.dim_executor_config (
    -- Primary key
    config_id               SERIAL PRIMARY KEY,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Strategy identity
    config_name             TEXT NOT NULL UNIQUE,     -- 'ema_trend_17_77', 'ema_trend_21_50'
    signal_type             TEXT NOT NULL,            -- 'ema_crossover' | 'rsi_mean_revert' | 'atr_breakout'
    signal_id               INTEGER NOT NULL,         -- FK to dim_signals (the specific config)
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,

    -- Execution parameters
    exchange                TEXT NOT NULL DEFAULT 'paper',   -- 'paper' | 'coinbase' | 'kraken'
    environment             TEXT NOT NULL DEFAULT 'sandbox', -- 'sandbox' | 'production'

    -- Position sizing
    sizing_mode             TEXT NOT NULL DEFAULT 'fixed_fraction',
    position_fraction       NUMERIC NOT NULL DEFAULT 0.10,   -- 10% of portfolio per position
    max_position_fraction   NUMERIC NOT NULL DEFAULT 0.20,   -- hard cap

    -- Fill simulation
    fill_price_mode         TEXT NOT NULL DEFAULT 'next_bar_open',  -- 'next_bar_open' | 'exchange_mid'
    slippage_mode           TEXT NOT NULL DEFAULT 'lognormal',      -- 'zero' | 'fixed' | 'lognormal'
    slippage_base_bps       NUMERIC NOT NULL DEFAULT 3.0,
    slippage_noise_sigma    NUMERIC NOT NULL DEFAULT 0.5,           -- log-space sigma
    volume_impact_factor    NUMERIC NOT NULL DEFAULT 0.1,
    rejection_rate          NUMERIC NOT NULL DEFAULT 0.0,           -- 0.0 = no rejections
    partial_fill_rate       NUMERIC NOT NULL DEFAULT 0.0,           -- 0.0 = always full fill
    execution_delay_bars    INTEGER NOT NULL DEFAULT 0,             -- 0 = same bar

    -- Deduplication watermark (updated after each run)
    last_processed_signal_ts TIMESTAMPTZ NULL,

    -- Stale signal guard
    cadence_hours           NUMERIC NOT NULL DEFAULT 26.0,   -- 26h = 24h cadence + 2h grace

    -- Constraints
    CONSTRAINT chk_exec_signal_type CHECK (signal_type IN ('ema_crossover', 'rsi_mean_revert', 'atr_breakout')),
    CONSTRAINT chk_exec_exchange    CHECK (exchange IN ('paper', 'coinbase', 'kraken')),
    CONSTRAINT chk_exec_environment CHECK (environment IN ('sandbox', 'production')),
    CONSTRAINT chk_exec_sizing_mode CHECK (sizing_mode IN ('fixed_fraction', 'regime_adjusted', 'signal_strength')),
    CONSTRAINT chk_exec_fill_mode   CHECK (fill_price_mode IN ('next_bar_open', 'exchange_mid')),
    CONSTRAINT chk_exec_slip_mode   CHECK (slippage_mode IN ('zero', 'fixed', 'lognormal')),
    CONSTRAINT chk_exec_fraction    CHECK (position_fraction > 0 AND position_fraction <= 1),
    CONSTRAINT chk_exec_rejection   CHECK (rejection_rate >= 0 AND rejection_rate <= 1),
    CONSTRAINT chk_exec_partial     CHECK (partial_fill_rate >= 0 AND partial_fill_rate <= 1)
);

CREATE INDEX IF NOT EXISTS idx_exec_config_active
    ON public.dim_executor_config (is_active, signal_type)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_exec_config_signal
    ON public.dim_executor_config (signal_id);
```

### YAML Seed File for V1

```yaml
# config/executor_config_seed.yaml
# Seeds dim_executor_config for V1 deployment.
# Applied by: python -m ta_lab2.scripts.executor.seed_executor_config
# Safe to re-run (INSERT ... ON CONFLICT DO NOTHING).

strategies:
  - config_name: "ema_trend_17_77"
    signal_type: "ema_crossover"
    signal_name: "ema_17_77_long"    # must exist in dim_signals
    is_active: true
    exchange: "paper"
    environment: "sandbox"
    sizing_mode: "fixed_fraction"
    position_fraction: 0.10
    max_position_fraction: 0.20
    fill_price_mode: "next_bar_open"
    slippage_mode: "lognormal"
    slippage_base_bps: 3.0
    slippage_noise_sigma: 0.5
    volume_impact_factor: 0.1
    rejection_rate: 0.0
    partial_fill_rate: 0.0
    execution_delay_bars: 0
    cadence_hours: 26.0

  - config_name: "ema_trend_21_50"
    signal_type: "ema_crossover"
    signal_name: "ema_21_50_long"    # must exist in dim_signals
    is_active: true
    exchange: "paper"
    environment: "sandbox"
    sizing_mode: "fixed_fraction"
    position_fraction: 0.10
    max_position_fraction: 0.20
    fill_price_mode: "next_bar_open"
    slippage_mode: "lognormal"
    slippage_base_bps: 3.0
    slippage_noise_sigma: 0.5
    volume_impact_factor: 0.1
    rejection_rate: 0.0
    partial_fill_rate: 0.0
    execution_delay_bars: 0
    cadence_hours: 26.0
```

### YAML Seed Pattern

The seeder reads the YAML file and does `INSERT INTO dim_executor_config (...) ON CONFLICT (config_name) DO NOTHING`.
This makes it safe to run repeatedly. DB can be updated directly (`UPDATE dim_executor_config SET ...`)
for operational changes without changing the YAML. YAML is version-controlled defaults only.

---

## cmc_executor_run_log Table Design

```sql
-- sql/executor/089_cmc_executor_run_log.sql
-- One row per executor invocation. Used for audit, monitoring, and Telegram alert context.

CREATE TABLE IF NOT EXISTS public.cmc_executor_run_log (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ NULL,

    -- Configuration
    config_ids          INTEGER[]   NOT NULL,  -- list of dim_executor_config IDs processed
    dry_run             BOOLEAN     NOT NULL DEFAULT FALSE,
    replay_historical   BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Outcome
    status              TEXT        NOT NULL DEFAULT 'running',  -- 'running' | 'success' | 'failed' | 'stale_signal'
    signals_read        INTEGER     NOT NULL DEFAULT 0,
    orders_generated    INTEGER     NOT NULL DEFAULT 0,
    fills_processed     INTEGER     NOT NULL DEFAULT 0,
    skipped_no_delta    INTEGER     NOT NULL DEFAULT 0,

    -- Error context
    error_message       TEXT        NULL,

    CONSTRAINT chk_run_log_status CHECK (status IN ('running', 'success', 'failed', 'stale_signal'))
);

CREATE INDEX IF NOT EXISTS idx_exec_run_log_ts
    ON public.cmc_executor_run_log (started_at DESC);
```

---

## Position Sizing Implementations

### Mode 1: Fixed Fraction (V1 Default)

```python
# Source: standard fractional position sizing (Kelly fraction / 2 is common in practice)

def size_fixed_fraction(
    portfolio_value: Decimal,
    price: Decimal,
    config: ExecutorConfig,
) -> Decimal:
    """
    Returns target signed quantity for the asset.
    position_fraction is read from dim_executor_config.
    """
    notional = portfolio_value * config.position_fraction
    return notional / price
```

### Mode 2: Regime-Adjusted (Phase 45 V1)

```python
# Source: project regime pipeline (cmc_regimes table, regime_context in signals)
# Regime context is already stored in feature_snapshot or can be looked up from cmc_regimes.

def size_regime_adjusted(
    portfolio_value: Decimal,
    price: Decimal,
    regime_label: str | None,
    config: ExecutorConfig,
) -> Decimal:
    """
    Adjusts base fraction based on regime label from cmc_regimes.

    Regime label -> size multiplier:
    - 'bull_low_vol'    -> 1.0x (full size)
    - 'bull_high_vol'   -> 0.7x (reduced)
    - 'ranging'         -> 0.5x (half size)
    - 'bear_low_vol'    -> 0.3x (minimal)
    - 'bear_high_vol'   -> 0.0x (flat -- don't trade)
    - None              -> 1.0x (no regime context, use full fraction)
    """
    REGIME_MULTIPLIERS = {
        "bull_low_vol":  Decimal("1.0"),
        "bull_high_vol": Decimal("0.7"),
        "ranging":       Decimal("0.5"),
        "bear_low_vol":  Decimal("0.3"),
        "bear_high_vol": Decimal("0.0"),
    }
    multiplier = REGIME_MULTIPLIERS.get(regime_label, Decimal("1.0"))
    base_qty = size_fixed_fraction(portfolio_value, price, config)
    return base_qty * multiplier
```

### Mode 3: Signal-Strength Scaled

```python
def size_signal_strength(
    portfolio_value: Decimal,
    price: Decimal,
    signal_confidence: float,   # from feature_snapshot or signal metadata, 0.0-1.0
    config: ExecutorConfig,
) -> Decimal:
    """
    Scale position by signal confidence score.
    confidence=1.0 -> full fraction; confidence=0.5 -> half fraction.
    Minimum 10% of base fraction to avoid tiny uneconomic orders.
    """
    scale = max(Decimal(str(signal_confidence)), Decimal("0.10"))
    base_qty = size_fixed_fraction(portfolio_value, price, config)
    return base_qty * scale
```

---

## Short Selling Simulation

### Research Finding

Short selling in a paper trading context on spot crypto is a simplified simulation, not real margin
borrowing. Key simplifications appropriate for Phase 45:

1. **No borrow fee tracking:** Real crypto borrow fees range from 2-195% annualized and vary daily.
   Phase 45 treats shorts as "inverse positions" with no borrow cost. Phase 46 (risk controls) or
   later phases can add a configurable `borrow_fee_bps_day` to the fill simulator.

2. **Signed quantity in cmc_positions:** The existing `position_math.py` from Phase 44 already
   handles negative quantities (shorts) via signed arithmetic. No new math is needed.

3. **Short sell order = "sell" side on a currently-flat or long position:** When target_qty is
   negative and current_qty >= 0, generate a `sell` order for `abs(target_qty - current_qty)` units.
   The position flips negative via Phase 44's `compute_position_update()`.

4. **Unrealized PnL for shorts:** The existing `v_cmc_positions_agg` view must handle negative
   quantity correctly. When `quantity < 0`: `unrealized_pnl = (avg_cost_basis - mark_price) * abs(quantity)`.

**Implementation recommendation:** For Phase 45, treat shorts as signed positions with no borrow fee.
Log "SHORT_POSITION_SIMULATED (no borrow fee)" in the run log for auditability. Document this
limitation in the executor's SUMMARY.

```python
# Short position in cmc_positions: quantity = -5.0 BTC
# avg_cost_basis = 50000 (price at which we "sold" to open short)
# If price moves to 48000:
#   unrealized_pnl = (50000 - 48000) * 5.0 = +$10,000 (profit on short)
# This matches Phase 44's compute_position_update() signed arithmetic.
```

---

## Backtest Parity Verification

### Research Finding

NautilusTrader achieves parity between backtesting and live execution by using "the same code for
both." This project's vectorbt backtester operates on `cmc_signals_*` + `cmc_features` tables and
fills at next-bar open with configurable slippage. The paper executor operates on the same signal
tables and fills at next-bar open. When `slippage_mode = "zero"`, fills should be identical.

### Parity Mode Design

```
Parity mode (--replay-historical):
1. Read historical signals from cmc_signals_* for a date range
2. Set slippage_mode = "zero", rejection_rate = 0, execution_delay_bars = 0
3. Use numpy seed (fixed) so any random calls are deterministic
4. Run fills using next-bar open price from cmc_price_bars_multi_tf (NOT exchange_price_feed)
5. Compare resulting position P&L curve against cmc_backtest_runs / cmc_backtest_trades

Parity tolerance:
- Mode: slippage_mode="zero" -> expect EXACT match (identical fill prices, same qty)
- Mode: slippage_mode="lognormal" -> expect STATISTICAL match (correlation >= 0.99)
```

### What to Compare Against

**Recommendation:** Compare against existing `cmc_backtest_runs` DB results, NOT re-running the
backtester from scratch. Re-running would need to reproduce the exact vectorbt state, which is
fragile. Instead:

1. Load `cmc_backtest_trades` for the same `(signal_id, asset_id, start_ts, end_ts)` range
2. Load `cmc_fills` for the same range from the executor's replay run
3. Compare: trade count, total P&L, per-trade entry/exit prices (exact when slippage=0)

**Parity tolerances (Claude's discretion):**
- `slippage_mode="zero"`: exact match on fill_price (within float precision = 1e-8), exact trade count
- `slippage_mode="lognormal"`: Pearson correlation of daily P&L >= 0.99, tracking error < 0.5%

```python
# Parity report output (pass/fail + detail on --verbose)
{
    "slippage_mode": "zero",
    "date_range": "2024-01-01 to 2025-01-01",
    "signal_id": 1,
    "asset_id": 1,
    "backtest_trade_count": 47,
    "executor_fill_count": 47,
    "trade_count_match": True,
    "pnl_correlation": 1.0,
    "max_price_divergence_bps": 0.0,
    "parity_pass": True
}
```

---

## Common Pitfalls

### Pitfall 1: Signal Table Lacks executor_processed_at Column

**What goes wrong:** Phase 45 assumes it can mark signals as processed. The existing signal tables
(`cmc_signals_ema_crossover`, `cmc_signals_rsi_mean_revert`, `cmc_signals_atr_breakout`) have no
`executor_processed_at` column. The status flag approach requires this column.

**Why it happens:** Phase 35 (signal generation) created the tables without anticipating the
executor's needs.

**How to avoid:** Phase 45's migration must `ALTER TABLE cmc_signals_ema_crossover ADD COLUMN IF NOT
EXISTS executor_processed_at TIMESTAMPTZ NULL`. Same for rsi and atr signal tables. This migration
must run before the executor uses these tables.

**Warning signs:** `sqlalchemy.exc.ProgrammingError: column "executor_processed_at" of relation
"cmc_signals_ema_crossover" does not exist`

### Pitfall 2: cmc_positions PK Conflict for Multi-Strategy

**What goes wrong:** Two strategies both hold BTC on "paper" exchange. Both try to UPSERT into
`cmc_positions (asset_id=1, exchange='paper')`. One's position overwrites the other. Position
quantities are wrong.

**Why it happens:** Phase 44's PK is `(asset_id, exchange)` without `strategy_id`. Phase 45 adds
`strategy_id` via migration but forgets to update the `ON CONFLICT` target in `OrderManager.process_fill()`.

**How to avoid:** The Phase 44 `OrderManager.process_fill()` code has a hardcoded `ON CONFLICT
(asset_id, exchange)` clause. After adding `strategy_id` to the PK, update the conflict target to
`(asset_id, exchange, strategy_id)`. Phase 45 must also pass `strategy_id` into `process_fill()`.

**Warning signs:** Two strategies show identical positions; UPSERT silently merges them.

### Pitfall 3: Stale Signal Guard Fires at First Run (No Signals Yet)

**What goes wrong:** The first time the executor runs (fresh deployment), `cmc_signals_ema_crossover`
may be empty or the last signal timestamp is from before the deployment date. The stale signal guard
raises `StaleSignalError` and the executor aborts.

**Why it happens:** The signal table may have historical signals from before deployment, but the latest
signal `ts` is old (signals haven't been refreshed yet in the new deployment).

**How to avoid:** Check stale signal guard ONLY if signals exist AND the executor has previously
run (i.e., `last_processed_signal_ts IS NOT NULL` in `dim_executor_config`). On first run
(watermark is NULL), skip the stale check and treat it as a full-history backfill.

**Warning signs:** `StaleSignalError` on every first run after deployment.

### Pitfall 4: Log-Normal Noise Not Seeded -> Non-Reproducible Fills

**What goes wrong:** Parity mode runs the executor twice. Log-normal noise draws differ between runs.
Fill prices differ. Parity fails even though slippage_mode should be "zero" for parity.

**Why it happens:** Parity mode must set `slippage_mode = "zero"` to disable noise entirely. If
parity mode accidentally enables noise (bug in config loading), the randomness from `numpy.random`
is unseeded.

**How to avoid:** In parity mode (`--replay-historical`), explicitly verify `slippage_mode == "zero"`
before proceeding. Log "PARITY MODE: slippage disabled" at INFO level. Use a fixed numpy seed for any
simulation runs that DO use noise (enables exact replay via `numpy.random.default_rng(seed=42)`).

### Pitfall 5: Portfolio Value Lookup Returns Stale Data

**What goes wrong:** Position sizer queries `v_cmc_positions_agg` and `exchange_price_feed` for
portfolio value. The mark price in `exchange_price_feed` is 8 hours old. Portfolio value is
significantly wrong. Position sizing generates too large or too small an order.

**Why it happens:** `exchange_price_feed` is only populated when `run_daily_refresh --exchange-prices`
runs (not in `--all`). If this hasn't run today, prices are stale.

**How to avoid:** Position sizer should fall back to the most recent bar close from
`cmc_price_bars_multi_tf` (tf='1D') when `exchange_price_feed` data is older than 24 hours. Log
which price source was used (bar close vs live price) for every sizing decision.

### Pitfall 6: run_daily_refresh --all Does Not Include Signal Generation

**What goes wrong:** Executor runs after regimes but signals were not refreshed. The executor reads
old signals (from yesterday) and generates wrong orders.

**Why it happens:** Signal generation (`run_all_signal_refreshes.py`) is NOT currently in
`run_daily_refresh.py --all`. It runs standalone.

**How to avoid:** Phase 45 must add signal generation to `run_daily_refresh.py` as the stage before
the executor. Add `--signals` flag and `run_signal_refreshes()` function. Add to `--all` pipeline
AFTER regimes and BEFORE executor.

### Pitfall 7: EMA Signals for 17/77 and 21/50 Not in dim_signals

**What goes wrong:** V1 deploys ema_trend(17,77) and ema_trend(21,50). The existing `dim_signals`
seed data has ema_9_21, ema_21_50, and ema_50_200 -- but NOT ema_17_77. The executor config
references a signal that doesn't exist.

**Why it happens:** The bake-off selected new configurations not in the original seed data.

**How to avoid:** Phase 45's migration must INSERT the V1 strategy signal configurations into
`dim_signals` if they don't exist. The YAML seed for executor config should reference signal_names
that Phase 45 inserts. The Plan must verify the signal chain: `dim_signals -> cmc_signals_ema_crossover
-> dim_executor_config` is consistent.

**Warning signs:** `dim_executor_config.signal_id` FK fails because the signal doesn't exist in `dim_signals`.

---

## Code Examples

### PaperExecutor Main Loop

```python
# Source: patterns from run_all_signal_refreshes.py + OrderManager (Phase 44)

class PaperExecutor:
    """
    Reads signals, generates paper orders, simulates fills, updates positions.

    Per strategy (from dim_executor_config where is_active=True):
    1. Load config from DB
    2. Check signal freshness (stale guard)
    3. Read unprocessed signals via watermark + status flag
    4. For each asset with signals: compute target vs current position
    5. Generate CanonicalOrder for delta
    6. Simulate fill via FillSimulator
    7. Process fill via OrderManager.process_fill()
    8. Mark signal as processed (update executor_processed_at)
    9. Update watermark in dim_executor_config
    10. Write run log entry
    """

    def run(self, dry_run: bool = False) -> None:
        configs = self._load_active_configs()

        for config in configs:
            try:
                self._run_strategy(config, dry_run=dry_run)
            except StaleSignalError as e:
                logger.error("STALE SIGNAL: %s", e)
                self._send_telegram_alert(f"STALE SIGNAL for {config.config_name}: {e}")
                self._write_run_log(config, status="stale_signal", error=str(e))
            except Exception as e:
                logger.exception("Executor failed for %s: %s", config.config_name, e)
                self._write_run_log(config, status="failed", error=str(e))

    def _run_strategy(self, config: ExecutorConfig, dry_run: bool) -> None:
        with self.engine.connect() as conn:
            # Step 1: Stale signal guard
            if config.last_processed_signal_ts is not None:
                check_signal_freshness(conn, config.signal_table, config.signal_id, config.cadence_hours)

            # Step 2: Load unprocessed signals
            signals = read_unprocessed_signals(
                conn, config.signal_table, config.signal_id, config.last_processed_signal_ts
            )

        if not signals:
            logger.info("No new signals for %s", config.config_name)
            return

        # Step 3: Group by asset_id -- get latest signal per asset
        latest_by_asset = {s["id"]: s for s in signals}  # last signal wins per asset

        for asset_id, signal in latest_by_asset.items():
            self._process_asset_signal(asset_id, signal, config, dry_run)

        # Step 4: Update watermark
        max_ts = max(s["ts"] for s in signals)
        self._update_watermark(config.config_id, max_ts)
```

### Parity Check Against Existing Backtest Results

```python
# Source: project's validate_reproducibility.py pattern, extended for paper executor

def check_backtest_parity(
    engine,
    config: ExecutorConfig,
    replay_start: str,
    replay_end: str,
) -> dict:
    """
    Compare paper executor replay fills against stored cmc_backtest_trades.
    Returns parity report dict.
    """
    # Load backtest trades for this (signal_id, date range)
    bt_trades = _load_backtest_trades(engine, config.signal_id, replay_start, replay_end)

    # Load executor fills for same range (replay run just completed)
    exec_fills = _load_executor_fills(engine, config.config_id, replay_start, replay_end)

    report = {
        "config_name": config.config_name,
        "date_range": f"{replay_start} to {replay_end}",
        "backtest_trade_count": len(bt_trades),
        "executor_fill_count": len(exec_fills),
        "trade_count_match": len(bt_trades) == len(exec_fills),
        "pnl_correlation": None,
        "max_price_divergence_bps": None,
        "parity_pass": False,
    }

    if report["trade_count_match"]:
        # Compare fill prices (should be identical in zero-slippage mode)
        price_divergences = [
            abs(float(e["fill_price"]) - float(b["entry_price"])) / float(b["entry_price"]) * 10000
            for e, b in zip(exec_fills, bt_trades)
        ]
        report["max_price_divergence_bps"] = max(price_divergences) if price_divergences else 0.0
        report["parity_pass"] = report["max_price_divergence_bps"] < 1.0  # 1 bps tolerance
    else:
        report["parity_pass"] = False

    return report
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Paper trading = manual spreadsheet | DB-backed with full order lifecycle | Industry shift 2015-2020 | Automated audit trail, reproducibility |
| Backtest != paper trade (different code paths) | Same signal tables for both | NautilusTrader pattern 2021+ | True parity verification possible |
| Fixed slippage in bps (scalar) | Volume-adaptive + log-normal noise | TCA research 2022-2024 | More realistic simulation of fill variability |
| Per-exchange positions only | Per-strategy positions (multi-strategy isolation) | Multi-strategy OMS design 2020+ | Clean P&L attribution per strategy |
| Batch signal processing (all or nothing) | Watermark + status flag (incremental) | Streaming systems pattern | Efficient daily runs, no reprocessing old signals |

**Deprecated/outdated:**
- Fixed 50% position fraction from bake-off: Reduced to 10% for V1 deployment (CONTEXT.md)
- Single position table without strategy_id: Must be extended for multi-strategy isolation

---

## Open Questions

1. **Signal generation pipeline wiring into run_daily_refresh.py**
   - What we know: `run_all_signal_refreshes.py` exists as standalone. Not in `--all` pipeline.
   - What's unclear: Does Phase 45 add signal generation to the pipeline, or is that a separate
     phase? The CONTEXT.md says executor is "a stage in `run_daily_refresh.py` (after signals)".
     This implies signals must already be in the pipeline.
   - Recommendation: Phase 45 plan should include adding signal generation to `run_daily_refresh.py`
     as a prerequisite task (plan-01). If signals stage fails, executor stage must not run.

2. **dim_signals entries for ema_trend(17,77)**
   - What we know: The bake-off selected ema_trend(17,77) but `dim_signals` only has ema_9_21,
     ema_21_50, ema_50_200.
   - What's unclear: Were ema_17_77 entries added during the bake-off phase (Phase 42)? Need to
     verify current DB state.
   - Recommendation: Phase 45 plan-01 should verify dim_signals contents and add any missing V1
     signal configurations before creating the executor config.

3. **Portfolio value calculation source**
   - What we know: Position sizer needs total portfolio value (NAV) to compute fractional sizes.
     `v_cmc_positions_agg` has positions; `exchange_price_feed` has live prices.
   - What's unclear: When exchange_price_feed is stale (not populated today), what's the fallback?
   - Recommendation: Fallback to most recent `cmc_price_bars_multi_tf` close for each position's
     mark price. Log which source was used. Never abort sizing due to stale prices -- use last known.

4. **Exact V1 signal_id values in dim_signals**
   - What we know: V1 uses ema_trend(17,77) and ema_trend(21,50). Both are EMA crossover type.
   - What's unclear: The signal_id integers won't be known until the DB is queried.
   - Recommendation: All references in dim_executor_config use `signal_name` (unique text) for seed
     lookup, then resolve to `signal_id` at seed time. Never hardcode integer signal_id in YAML.

---

## Sources

### Primary (HIGH confidence)
- Existing project code: `src/ta_lab2/paper_trading/canonical_order.py` -- CanonicalOrder API (Phase 43)
- Existing project code: `src/ta_lab2/paper_trading/paper_order_logger.py` -- PaperOrderLogger (Phase 43)
- Existing project code: `.planning/phases/44-order-fill-store/44-RESEARCH.md` -- OrderManager, FillData, position_math, VALID_TRANSITIONS
- Existing project code: `src/ta_lab2/scripts/signals/signal_state_manager.py` -- watermark pattern
- Existing project code: `src/ta_lab2/scripts/signals/signal_utils.py` -- load_active_signals, feature hashing
- Existing project code: `src/ta_lab2/scripts/run_daily_refresh.py` -- ComponentResult, subprocess pattern
- Existing project code: `sql/signals/060_cmc_signals_ema_crossover.sql` -- signal table schema
- Existing project code: `sql/lookups/030_dim_signals.sql` -- dim_signals seed pattern
- `.planning/phases/45-paper-trade-executor/45-CONTEXT.md` -- all locked decisions

### Secondary (MEDIUM confidence)
- Talos Market Impact Model: https://www.talos.com/insights/understanding-market-impact-in-crypto-trading-the-talos-model-for-estimating-execution-costs
  -- Sigmoid-adjusted square-root formula, 50,000+ institutional orders calibration, 26%+ fills in 0-5 bps range
- NautilusTrader FillModel docs: https://nautilustrader.io/docs/latest/concepts/backtesting/
  -- `prob_slippage` parameter, bar-based execution mode (Open->High->Low->Close), parity design
- Amberdata orderbook slippage research: https://blog.amberdata.io/identifying-crypto-market-trends-using-orderbook-slippage-metrics
  -- Volatility correlation 0.73+ dominates volume correlation 0.43 for slippage

### Tertiary (LOW confidence)
- WebSearch: "crypto spot slippage lognormal distribution simulation" -- no single authoritative source
  explicitly recommends log-normal for crypto paper trading noise; this is an inference from the
  right-skewed empirical observation + log-normal as canonical right-skewed distribution choice
- WebSearch: "position sizing regime adjusted crypto" -- Kelly vs fixed fraction discussion; regime
  multiplier table is empirically-motivated but not precisely calibrated to this project's signals
- WebSearch: "short selling simulation paper trading spot simplified" -- confirms borrow fee
  simplification is standard in paper trading platforms; no authoritative source for exact approach

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all libraries exist in project
- Pipeline integration: HIGH -- run_daily_refresh.py pattern is clear and consistent; executor adds one more component
- Signal reader / deduplication: HIGH -- existing signal_state_manager.py watermark pattern directly applicable
- cmc_positions strategy_id extension: HIGH -- SQL migration pattern is straightforward; impact on OrderManager known
- dim_executor_config DDL: HIGH -- follows dim_signals design pattern; all columns motivated by CONTEXT.md decisions
- Fill simulation (two-phase): HIGH -- Phase 44 designed this explicitly; executor is the consumer
- Position sizing math: HIGH -- fixed fraction / regime-adjusted are standard, well-understood
- Slippage distribution (log-normal): MEDIUM -- empirically motivated but parameters (sigma=0.5, base=3 bps) are estimates
- Short selling simulation: MEDIUM -- simplified approach is standard for paper trading; confirmed by research
- Backtest parity tolerance: MEDIUM -- 1 bps tolerance for zero-slippage mode is reasonable but untested against actual vectorbt output
- dim_signals V1 entries (17/77): LOW -- requires DB verification; cannot be confirmed from research alone

**Research date:** 2026-02-24
**Valid until:** 2026-04-24 (stable patterns; re-verify slippage parameters if real fills become available for calibration)
