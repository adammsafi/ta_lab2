# Phase 46: Risk Controls - Research

**Researched:** 2026-02-24
**Domain:** Algorithmic trading risk controls — kill switch, position caps, daily loss stops, circuit breakers, discretionary overrides
**Confidence:** HIGH (architecture patterns, DB schema, kill switch mechanics, position cap enforcement), MEDIUM (circuit breaker trigger metrics, daily loss calculation), LOW (exact threshold defaults for crypto daily strategies)

---

## Summary

Phase 46 adds a safety net around the Phase 45 paper-trade executor: a `RiskEngine` class that runs pre-execution checks on every order before the executor places it, plus a `KillSwitch` that can halt the entire system. All five requirements (RISK-01 through RISK-05) are implementable with zero new dependencies — the project's existing PostgreSQL + SQLAlchemy + Telegram stack covers everything.

The dominant architecture question (library vs middleware) should resolve in favor of the **library pattern**: the executor calls `risk_engine.check_order(order)` before processing each signal, and the executor also calls `risk_engine.check_daily_loss()` at the start of each run. This is simpler than middleware: no wrapping, no monkey-patching, no interception layer, and it matches the project's existing "call the function" style. The risk engine is a pure stateless checker that reads state from the DB on each invocation. Kill switch state and circuit breaker counters live in `dim_risk_state` (a single-row table), so they survive restarts with no file-lock complexity.

The kill switch shutdown sequence should be: (1) atomically flip `is_halted=TRUE` in `dim_risk_state`, (2) cancel all pending orders in `cmc_orders` by updating status to `cancelled`, (3) log the event to `cmc_risk_events`, (4) send Telegram alert. Positions are left open (paper trading — no real money, no exchange to cancel on). Re-enable requires manual DB update or CLI command — never automatic, as automatic re-enable after an emergency halt is a known safety anti-pattern.

**Primary recommendation:** Build `RiskEngine` as a library class in `src/ta_lab2/risk/risk_engine.py`, reading its config from `dim_risk_limits` each call (hot-reload by default). Use a `dim_risk_state` table for kill switch + circuit breaker state. Use `cmc_risk_events` as the audit trail for all risk events. Wire the executor to call `risk_engine.check_order()` as the first step of its signal processing loop.

---

## Standard Stack

### Core (No New Dependencies)

| Library | Version | Purpose | Already Installed |
|---------|---------|---------|------------------|
| `sqlalchemy` | existing | `engine.begin()` transactions, `text()` queries for risk state | YES |
| `alembic` | existing | Schema migration for risk tables | YES |
| `decimal` | stdlib | Exact arithmetic for position value calculations | YES |
| `dataclasses` | stdlib | `RiskCheckResult`, `RiskEvent` data types | YES |
| `typing` | stdlib | Type hints | YES |
| `logging` | stdlib | Every check decision logged | YES |
| `argparse` | stdlib | CLI for kill switch and override commands | YES |
| `datetime` | stdlib | Event timestamps, daily loss reset boundary | YES |

No new packages required. The circuit breaker is a custom implementation tracking consecutive losses in `dim_risk_state`, not a generic library like `pybreaker` or `circuitbreaker` (those are for microservice HTTP failure patterns, not trading P&L tracking).

**Installation:**
```bash
# Nothing to install
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── risk/                            # NEW package for Phase 46
│   ├── __init__.py
│   ├── risk_engine.py               # RiskEngine class -- primary deliverable
│   ├── kill_switch.py               # KillSwitch operations (activate, re-enable, status)
│   └── override_manager.py         # DiscretionaryOverride CLI entry and persistence

scripts/
└── risk/                            # NEW scripts package
    ├── __init__.py
    ├── kill_switch_cli.py           # CLI: activate/status/re-enable kill switch
    └── override_cli.py             # CLI: create/list/revert overrides

sql/risk/                            # NEW reference DDL directory
├── 090_dim_risk_limits.sql          # Risk limit configuration table
├── 091_dim_risk_state.sql           # Kill switch + circuit breaker live state
└── 092_cmc_risk_events.sql          # Immutable audit log for all risk events
```

### Pattern 1: Library Pattern (executor calls risk engine)

**What:** The executor calls `risk_engine.check_order(order, portfolio)` before processing each signal. The risk engine returns a `RiskCheckResult` with `allowed: bool`, `adjusted_quantity: Decimal | None`, and `reason: str`. The executor applies the adjusted quantity or skips the order.

**When to use:** Every signal processing cycle, before any order is created.

**Example:**
```python
# Source: project pattern from paper_order_logger.py and position_math.py

@dataclass
class RiskCheckResult:
    allowed: bool
    adjusted_quantity: Decimal | None  # None = use original; set = scaled down
    blocked_reason: str | None         # None if allowed

class RiskEngine:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def check_order(
        self,
        order: CanonicalOrder,
        asset_id: int,
        strategy_id: int,
        portfolio_value: Decimal,
        current_position_value: Decimal,
    ) -> RiskCheckResult:
        # 1. Check kill switch first (fast exit)
        if self._is_halted():
            return RiskCheckResult(allowed=False, adjusted_quantity=None, blocked_reason="kill_switch_active")

        # 2. Check per-asset position cap
        limits = self._load_limits(asset_id, strategy_id)
        max_position_value = limits.max_position_pct * portfolio_value
        if current_position_value + (order.quantity * fill_price) > max_position_value:
            scaled_qty = max(Decimal("0"), (max_position_value - current_position_value) / fill_price)
            if scaled_qty == 0:
                return RiskCheckResult(allowed=False, adjusted_quantity=Decimal("0"), blocked_reason="position_cap_exhausted")
            return RiskCheckResult(allowed=True, adjusted_quantity=scaled_qty, blocked_reason=None)

        # 3. Check portfolio utilization cap
        # ...

        return RiskCheckResult(allowed=True, adjusted_quantity=None, blocked_reason=None)
```

### Pattern 2: Kill Switch State Machine (3-state, DB-persisted)

**What:** Three operational states modelled after NautilusTrader's trading_state: `active`, `reducing`, `halted`. For V1 paper trading, only `active` and `halted` are needed (skip `reducing`). State lives in a single-row `dim_risk_state` table.

**State transitions:**
- `active` -> `halted`: triggered by daily loss stop (auto) or CLI command (manual)
- `halted` -> `active`: triggered ONLY by explicit CLI/manual command, never automatically
- Re-enable requires writing a reason string — prevents accidental re-enable

**Shutdown sequence (atomic):**
```python
# Source: project pattern from engine.begin() transaction blocks

def activate_kill_switch(
    engine: Engine,
    reason: str,
    trigger_source: str,  # "manual" | "daily_loss_stop" | "circuit_breaker"
) -> None:
    with engine.begin() as conn:
        # 1. Flip state atomically
        conn.execute(text("""
            UPDATE public.dim_risk_state
            SET trading_state = 'halted',
                halted_at = now(),
                halted_reason = :reason,
                halted_by = :trigger_source,
                updated_at = now()
        """), {"reason": reason, "trigger_source": trigger_source})

        # 2. Cancel pending orders (cmc_orders status -> cancelled)
        conn.execute(text("""
            UPDATE public.cmc_orders
            SET status = 'cancelled', updated_at = now()
            WHERE status IN ('created', 'submitted')
        """))

        # 3. Write audit event
        conn.execute(text("""
            INSERT INTO public.cmc_risk_events
            (event_type, trigger_source, reason, event_ts)
            VALUES ('kill_switch_activated', :trigger_source, :reason, now())
        """), {"trigger_source": trigger_source, "reason": reason})

    # 4. Telegram alert (outside transaction -- fire and forget)
    send_critical_alert(
        "kill_switch",
        f"Kill switch activated: {reason}",
        {"trigger_source": trigger_source},
    )
```

**Re-enable (manual only, requires reason):**
```python
def re_enable_trading(engine: Engine, reason: str, operator: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE public.dim_risk_state
            SET trading_state = 'active',
                halted_at = NULL,
                halted_reason = NULL,
                updated_at = now()
        """))
        conn.execute(text("""
            INSERT INTO public.cmc_risk_events
            (event_type, trigger_source, reason, operator, event_ts)
            VALUES ('kill_switch_disabled', 'manual', :reason, :operator, now())
        """), {"reason": reason, "operator": operator})
```

### Pattern 3: Position Cap with Scale-Down

**What:** Orders exceeding the cap are scaled down to fit, not rejected outright. This preserves signal intent while respecting limits. The adjustment is logged in `cmc_risk_events`.

**Two cap levels:**
1. Per-asset cap: `max_position_pct` of portfolio value per asset (e.g., 15% — slightly above the 10% strategy default to allow for price drift)
2. Portfolio utilization cap: `max_portfolio_pct` total invested across all assets (e.g., 80% — keeps buffer for margin of safety)

**Relationship to Phase 42 10% position fraction:** The 10% fraction in `dim_executor_config` is the TARGET position size the executor shoots for. The risk cap is a CEILING that triggers only if the executor's sizing would exceed it. Set the per-asset cap to 15% (1.5x the 10% target) to catch drift situations where prices have moved the position above target without the executor rebalancing yet.

**Scale-down formula:**
```python
def scale_order_to_cap(
    order_qty: Decimal,
    fill_price: Decimal,
    current_position_value: Decimal,
    max_position_value: Decimal,
) -> Decimal:
    """Return the maximum quantity that fits within the cap."""
    headroom = max_position_value - current_position_value
    if headroom <= 0:
        return Decimal("0")
    return min(order_qty, headroom / fill_price)
```

### Pattern 4: Daily Loss Stop (check on each executor run)

**What:** At the start of each executor run, compute today's portfolio P&L from the day-open mark. If drawdown from day-open exceeds `daily_loss_pct_threshold`, activate the kill switch automatically.

**Day-open definition for 1D daily strategies:** The portfolio value at the start of the calendar day (UTC midnight). Store `day_open_portfolio_value` in `dim_risk_state`, updated at the start of each calendar day.

**Daily loss calculation:**
```python
def check_daily_loss(engine: Engine) -> bool:
    """Returns True if daily loss stop triggered. Activates kill switch if so."""
    with engine.connect() as conn:
        state = conn.execute(text("""
            SELECT day_open_portfolio_value, daily_loss_pct_threshold
            FROM public.dim_risk_state
        """)).fetchone()

        current_value = _compute_current_portfolio_value(conn)
        if state.day_open_portfolio_value and state.day_open_portfolio_value > 0:
            dd_pct = (current_value - state.day_open_portfolio_value) / state.day_open_portfolio_value
            if dd_pct < -state.daily_loss_pct_threshold:
                activate_kill_switch(
                    engine,
                    reason=f"Daily loss {dd_pct:.2%} exceeded threshold {-state.daily_loss_pct_threshold:.2%}",
                    trigger_source="daily_loss_stop",
                )
                return True
    return False
```

**Day-open reset:** At the start of each executor run, if `last_day_open_date < today_utc`, update `day_open_portfolio_value = current_portfolio_value` and `last_day_open_date = today_utc`.

### Pattern 5: Circuit Breaker (consecutive losses + portfolio return)

**What:** Two independent triggers, both tracked in `dim_risk_state`:
1. Per-strategy breaker: N consecutive losing fills for that strategy's orders
2. Portfolio-wide breaker: N consecutive days where daily portfolio return is negative (harder trigger — overrides per-strategy)

**Recommended defaults:** N=3 consecutive losses, loss threshold > 0 (any loss counts). Configurable via `dim_risk_limits`.

**Recommended reset:** Time-based cooldown (24 hours after breaker trips) + manual override. Rationale: manual-only for circuit breaker (vs manual-only for kill switch) is too strict — a daily strategy will naturally reset after one day, so a time-based reset makes operational sense. Manual re-enable is always available as an override.

**Loss tracking:** Track realized P&L on fills (not unrealized mark-to-market). A fill with negative realized PnL compared to entry cost counts as a loss. Use `cmc_fills` + `cmc_positions.realized_pnl` already tracked by Phase 44.

**Circuit breaker in dim_risk_state:**
```sql
-- Per-strategy breaker state (jsonb or separate rows)
cb_consecutive_losses_by_strategy  jsonb NOT NULL DEFAULT '{}'
cb_breaker_tripped_at_by_strategy  jsonb NOT NULL DEFAULT '{}'

-- Portfolio-wide breaker state
cb_portfolio_consecutive_losses    INTEGER NOT NULL DEFAULT 0
cb_portfolio_breaker_tripped_at    TIMESTAMPTZ NULL
```

**Notification:** Same `send_critical_alert()` pattern as kill switch, severity="critical".

### Pattern 6: Discretionary Override (sticky/non-sticky, full audit)

**What:** A manual position target that supersedes the system signal for one asset/strategy pair. Sticky overrides persist until explicitly reverted. Non-sticky overrides snap back after one signal cycle.

**Override table design:**
```sql
CREATE TABLE public.cmc_risk_overrides (
    override_id     UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    asset_id        INTEGER       NOT NULL,
    strategy_id     INTEGER       NOT NULL,
    operator        TEXT          NOT NULL,     -- who created it
    reason          TEXT          NOT NULL,     -- mandatory
    system_signal   TEXT          NOT NULL,     -- what system said (JSON or enum)
    override_action TEXT          NOT NULL,     -- "flat" | "long N%" | "short N%"
    sticky          BOOLEAN       NOT NULL DEFAULT FALSE,
    applied_at      TIMESTAMPTZ   NULL,         -- NULL = not yet applied
    reverted_at     TIMESTAMPTZ   NULL,         -- NULL = still active
    revert_reason   TEXT          NULL
);
```

**CLI usage pattern (matching project style):**
```bash
# Create a non-sticky override (snaps back after next signal cycle)
python -m ta_lab2.scripts.risk.override_cli create \
  --asset-id 1 --strategy-id 2 --action "flat" \
  --reason "BTC weekend liquidity concern" --operator "asafi"

# Create a sticky override (holds until reverted)
python -m ta_lab2.scripts.risk.override_cli create \
  --asset-id 1 --strategy-id 2 --action "flat" \
  --reason "Manual risk reduction" --operator "asafi" --sticky

# Revert a sticky override
python -m ta_lab2.scripts.risk.override_cli revert \
  --override-id <uuid> --reason "Risk concern resolved" --operator "asafi"

# List active overrides
python -m ta_lab2.scripts.risk.override_cli list
```

### Pattern 7: Hot-Reload Config from DB

**Recommended approach:** Hot-reload on every executor cycle (not restart-required). The `dim_risk_limits` table is small (< 10 rows) and the executor reads it at most once per daily run. The overhead is negligible and the benefit — changing thresholds without restarts during the 2-week validation window — is high.

**Implementation:** `RiskEngine._load_limits()` runs a fresh DB query on each `check_order()` call. No in-memory caching. This matches the project's existing pattern (signal state manager, backtest state, regime policies all re-read from DB on each invocation rather than caching between runs).

### Anti-Patterns to Avoid

- **Automatic kill switch re-enable:** Never auto-re-enable after an emergency halt. The halt exists because something unexpected happened — the operator needs to investigate first.
- **File-lock for kill switch state:** A file lock on Windows is fragile (process crashes leave stale locks, filesystem permissions, antivirus interference). DB row is simpler, crash-safe (ACID), and queryable.
- **Reject instead of scale:** Rejecting orders when position cap is nearly full wastes signal intent for small violations. Scale to the cap boundary first, only reject if headroom is zero.
- **Per-fill circuit breaker (unrealized P&L):** Using unrealized mark-to-market to trigger the breaker creates false positives from intraday price swings. Track realized P&L from fills and daily return from `dim_risk_state.day_open_portfolio_value`.
- **YAML config for risk limits:** The context has locked this: use `dim_risk_limits` DB table. YAML is version-controlled but requires restart; DB allows live changes during the validation window.

---

## Recommended DDL Schemas

### dim_risk_limits (config table, runtime-editable)

```sql
CREATE TABLE public.dim_risk_limits (
    limit_id                    SERIAL          PRIMARY KEY,
    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Scope: NULL means "applies to all"
    asset_id                    INTEGER         NULL,   -- NULL = portfolio-wide
    strategy_id                 INTEGER         NULL,   -- NULL = all strategies

    -- Position caps
    max_position_pct            NUMERIC         NOT NULL DEFAULT 0.15,  -- 15% per asset
    max_portfolio_pct           NUMERIC         NOT NULL DEFAULT 0.80,  -- 80% total invested

    -- Daily loss stop
    daily_loss_pct_threshold    NUMERIC         NOT NULL DEFAULT 0.03,  -- 3% default (RISK-03)

    -- Circuit breaker
    cb_consecutive_losses_n     INTEGER         NOT NULL DEFAULT 3,     -- N consecutive losses
    cb_loss_threshold_pct       NUMERIC         NOT NULL DEFAULT 0.0,   -- any loss counts

    -- Override support
    allow_overrides             BOOLEAN         NOT NULL DEFAULT TRUE,

    CONSTRAINT chk_risk_limits_max_pos   CHECK (max_position_pct > 0 AND max_position_pct <= 1),
    CONSTRAINT chk_risk_limits_max_port  CHECK (max_portfolio_pct > 0 AND max_portfolio_pct <= 1),
    CONSTRAINT chk_risk_limits_daily     CHECK (daily_loss_pct_threshold > 0 AND daily_loss_pct_threshold <= 1),
    CONSTRAINT chk_risk_limits_n         CHECK (cb_consecutive_losses_n >= 1)
);
```

### dim_risk_state (single-row live state table)

```sql
CREATE TABLE public.dim_risk_state (
    state_id                        SERIAL          PRIMARY KEY,  -- always 1 row

    -- Kill switch state
    trading_state                   TEXT            NOT NULL DEFAULT 'active',
    halted_at                       TIMESTAMPTZ     NULL,
    halted_reason                   TEXT            NULL,
    halted_by                       TEXT            NULL,  -- "manual" | "daily_loss_stop" | "circuit_breaker"
    updated_at                      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Daily loss tracking
    day_open_portfolio_value        NUMERIC         NULL,
    last_day_open_date              DATE            NULL,

    -- Circuit breaker per-strategy (JSON: {strategy_id: consecutive_count})
    cb_consecutive_losses           TEXT            NOT NULL DEFAULT '{}',  -- JSON text
    cb_breaker_tripped_at           TEXT            NOT NULL DEFAULT '{}',  -- JSON text
    cb_breaker_cooldown_hours       NUMERIC         NOT NULL DEFAULT 24.0,

    -- Portfolio-wide circuit breaker
    cb_portfolio_consecutive_losses INTEGER         NOT NULL DEFAULT 0,
    cb_portfolio_breaker_tripped_at TIMESTAMPTZ     NULL,

    CONSTRAINT chk_risk_state_trading  CHECK (trading_state IN ('active', 'halted')),
    CONSTRAINT chk_risk_state_single   CHECK (state_id = 1)  -- enforce single-row
);

-- Seed the single row on first migration
INSERT INTO public.dim_risk_state (state_id) VALUES (1)
ON CONFLICT (state_id) DO NOTHING;
```

### cmc_risk_events (immutable audit log)

```sql
CREATE TABLE public.cmc_risk_events (
    event_id        UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    event_ts        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    event_type      TEXT            NOT NULL,
    trigger_source  TEXT            NOT NULL,   -- "manual" | "daily_loss_stop" | "circuit_breaker"
    reason          TEXT            NOT NULL,
    operator        TEXT            NULL,       -- for manual events
    asset_id        INTEGER         NULL,       -- for per-asset events
    strategy_id     INTEGER         NULL,       -- for per-strategy events
    order_id        UUID            NULL,       -- FK-like ref to cmc_orders
    override_id     UUID            NULL,       -- FK-like ref to cmc_risk_overrides
    metadata        TEXT            NULL,       -- JSON text for additional context

    CONSTRAINT chk_risk_events_type CHECK (
        event_type IN (
            'kill_switch_activated',
            'kill_switch_disabled',
            'position_cap_scaled',
            'position_cap_blocked',
            'daily_loss_stop_triggered',
            'circuit_breaker_tripped',
            'circuit_breaker_reset',
            'override_created',
            'override_applied',
            'override_reverted'
        )
    ),
    CONSTRAINT chk_risk_events_source CHECK (
        trigger_source IN ('manual', 'daily_loss_stop', 'circuit_breaker', 'system')
    )
);

CREATE INDEX idx_risk_events_ts      ON public.cmc_risk_events (event_ts DESC);
CREATE INDEX idx_risk_events_type    ON public.cmc_risk_events (event_type, event_ts DESC);
CREATE INDEX idx_risk_events_asset   ON public.cmc_risk_events (asset_id, event_ts DESC)
    WHERE asset_id IS NOT NULL;
```

### cmc_risk_overrides (discretionary override store)

```sql
CREATE TABLE public.cmc_risk_overrides (
    override_id     UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    asset_id        INTEGER         NOT NULL,
    strategy_id     INTEGER         NOT NULL,
    operator        TEXT            NOT NULL,
    reason          TEXT            NOT NULL,
    system_signal   TEXT            NOT NULL,   -- JSON snapshot of system signal at override time
    override_action TEXT            NOT NULL,   -- "flat" | "long_N_pct" | "short_N_pct"
    sticky          BOOLEAN         NOT NULL DEFAULT FALSE,
    applied_at      TIMESTAMPTZ     NULL,
    reverted_at     TIMESTAMPTZ     NULL,
    revert_reason   TEXT            NULL,

    CONSTRAINT chk_overrides_action CHECK (
        override_action IN ('flat', 'long_10_pct', 'long_5_pct', 'short_10_pct', 'short_5_pct')
        -- expand as needed; or use TEXT with application-level validation
    )
);

CREATE INDEX idx_overrides_active ON public.cmc_risk_overrides (asset_id, strategy_id)
    WHERE reverted_at IS NULL;
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Kill switch state persistence | File lock (.lock file) | DB row in `dim_risk_state` | File locks are fragile on Windows, not crash-safe, not queryable |
| Circuit breaker for HTTP services | Custom consecutive-loss tracker | Generic `pybreaker` / `circuitbreaker` libs | Those libs are for HTTP 5xx failure patterns, not P&L tracking |
| Kill switch Telegram notification | Custom HTTP client | Existing `send_critical_alert()` | Already wired, tested, handles missing config gracefully |
| Atomic kill switch + cancel orders | Two separate DB calls | Single `engine.begin()` transaction | Must be atomic — partial state (halted but orders still pending) is dangerous |
| Override audit | Application-level logging only | `cmc_risk_events` insert + `cmc_risk_overrides` table | Logs can be lost on process crash; DB survives |
| Daily loss reset trigger | Cron job | Check at start of each executor run | Executor runs daily anyway; a cron is more moving parts |

**Key insight:** Risk controls in paper trading (no real money at stake) are primarily about correctness of simulation and building operational habits — not preventing financial catastrophe. The implementation can be simpler and more conservative (fail-safe, halt on ambiguity) than a production system.

---

## Common Pitfalls

### Pitfall 1: Kill Switch Re-Enable Race Condition
**What goes wrong:** Two processes check kill switch simultaneously, both see `active`, both proceed. Then kill switch activates mid-flight.
**Why it happens:** Check-then-act is not atomic across the check and the order creation.
**How to avoid:** The executor checks kill switch at the start of the run (not per-order). For a daily batch executor, one check per run is sufficient — the run is serial. If multiple strategies run concurrently in future, use `SELECT FOR UPDATE` on `dim_risk_state`.
**Warning signs:** Logs showing orders placed after kill switch timestamp.

### Pitfall 2: Daily Loss Calculation Using Unrealized P&L
**What goes wrong:** Unrealized P&L swings wildly intraday even for paper positions. A 3% intraday drawdown on volatile crypto triggers the kill switch unnecessarily.
**Why it happens:** Marking positions to current price (unrealized) captures noise. The intent of a daily stop is cumulative executed-trade losses, not price fluctuations.
**How to avoid:** Use `realized_pnl` from `cmc_positions` for the loss calculation (fills that closed positions). For the day-open baseline, snapshot portfolio value at day open using last fill prices, not live marks.
**Warning signs:** Kill switch triggering multiple times per week on low-conviction signals.

### Pitfall 3: Circuit Breaker Counts Signal Reverts as Losses
**What goes wrong:** If the executor generates a new order that partially offsets the previous position (rebalance-to-target), the partial close might realize a small loss even when the trade is still open and profitable in aggregate.
**Why it happens:** Partial fills realize P&L on the closed portion using `compute_position_update()`. A rebalance-down can show negative realized PnL even though the strategy is up overall.
**How to avoid:** Track circuit breaker losses at the trade level (full position open+close cycle), not at the fill level. Use `cmc_order_events` to identify full position cycles (flat -> long -> flat). Alternatively, only count losses when a position closes completely (quantity reaches 0).
**Warning signs:** Circuit breaker tripping after every rebalance cycle.

### Pitfall 4: Position Cap Applied After Sizing Already Decided
**What goes wrong:** Executor computes target quantity using 10% sizing, THEN risk engine scales it down to 8% due to cap. Executor updates its watermark/state as if the full 10% was executed, leading to drift where the system thinks it's at 10% but it's at 8%.
**Why it happens:** The executor's position size state and the risk engine's cap adjustment are separate.
**How to avoid:** Risk engine returns `adjusted_quantity` which the executor MUST use as the actual fill quantity when updating `dim_executor_config.last_processed_signal_ts` and position state. The executor must not assume its computed quantity was filled.
**Warning signs:** Cumulative position drift between cmc_positions and executor's expected state.

### Pitfall 5: Override Applied but Not Logged Before Executor Runs
**What goes wrong:** A non-sticky override is applied, the executor processes it, then the log entry fails. Now the override has been applied but there is no audit record.
**Why it happens:** Log insert is separate from override application.
**How to avoid:** Use a single transaction: apply override (update cmc_risk_overrides.applied_at) AND insert cmc_risk_events row in one `engine.begin()` block.
**Warning signs:** Overrides shown as applied but no corresponding risk_events row.

### Pitfall 6: Windows UTF-8 / Encoding Pitfall in SQL Files
**What goes wrong:** Adding box-drawing chars or non-ASCII in SQL comments causes `UnicodeDecodeError` when the SQL file is read with the default `cp1252` encoding.
**Why it happens:** Windows default codec is cp1252, not UTF-8.
**How to avoid:** Per project MEMORY.md: always use `encoding='utf-8'` when reading SQL files. Use ASCII-only characters in all SQL comments. No em-dashes, no box-drawing.
**Warning signs:** UnicodeDecodeError when running migrations.

---

## Code Examples

Verified patterns from project codebase:

### Hot-Reload Config Pattern (matching project conventions)

```python
# Source: matches paper_order_logger.py PaperOrderLogger pattern

class RiskEngine:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine  # NullPool for CLI scripts, shared pool for long-running

    def _load_limits(self, asset_id: int | None, strategy_id: int | None) -> RiskLimits:
        """Load current limits from dim_risk_limits. Always queries DB (hot-reload)."""
        with self._engine.connect() as conn:
            row = conn.execute(text("""
                SELECT max_position_pct, max_portfolio_pct,
                       daily_loss_pct_threshold,
                       cb_consecutive_losses_n, cb_loss_threshold_pct,
                       allow_overrides
                FROM public.dim_risk_limits
                WHERE (asset_id = :asset_id OR asset_id IS NULL)
                  AND (strategy_id = :strategy_id OR strategy_id IS NULL)
                ORDER BY asset_id NULLS LAST, strategy_id NULLS LAST
                LIMIT 1
            """), {"asset_id": asset_id, "strategy_id": strategy_id}).fetchone()
        return RiskLimits(**dict(row._mapping)) if row else RiskLimits()  # defaults
```

### Kill Switch CLI Pattern (matching run_daily_refresh.py pattern)

```python
# Source: run_daily_refresh.py argparse pattern

def main(argv=None):
    p = argparse.ArgumentParser(description="Kill switch controls")
    sub = p.add_subparsers(dest="command", required=True)

    activate = sub.add_parser("activate", help="Activate kill switch")
    activate.add_argument("--reason", required=True)
    activate.add_argument("--db-url")

    disable = sub.add_parser("disable", help="Re-enable trading (manual only)")
    disable.add_argument("--reason", required=True)
    disable.add_argument("--operator", required=True)
    disable.add_argument("--db-url")

    status = sub.add_parser("status", help="Show current kill switch state")
    status.add_argument("--db-url")

    args = p.parse_args(argv)
    db_url = resolve_db_url(args.db_url)
    engine = create_engine(db_url, poolclass=NullPool)

    if args.command == "activate":
        activate_kill_switch(engine, args.reason, trigger_source="manual")
        print(f"[OK] Kill switch activated: {args.reason}")
    elif args.command == "disable":
        re_enable_trading(engine, args.reason, args.operator)
        print(f"[OK] Trading re-enabled by {args.operator}: {args.reason}")
    elif args.command == "status":
        print_kill_switch_status(engine)
```

### Executor Integration Point

```python
# Source: pattern matches how executor should wire in risk engine
# In paper_executor.py PaperExecutor.run():

def _process_signal(self, signal: dict, risk_engine: RiskEngine) -> None:
    """Process one signal through risk checks, then execute."""
    # 1. Build proposed order
    order = self._build_order(signal)

    # 2. Risk check BEFORE any DB writes
    portfolio_value = self._compute_portfolio_value()
    current_pos_value = self._get_position_value(signal["asset_id"], signal["strategy_id"])
    fill_price = self._estimate_fill_price(signal)

    check = risk_engine.check_order(
        order=order,
        asset_id=signal["asset_id"],
        strategy_id=signal["strategy_id"],
        portfolio_value=portfolio_value,
        current_position_value=current_pos_value,
    )

    if not check.allowed and check.adjusted_quantity == Decimal("0"):
        logger.info("Order blocked by risk engine: %s", check.blocked_reason)
        return  # skip, don't create order at all

    if check.adjusted_quantity is not None:
        # Scale down to cap
        order = replace(order, quantity=float(check.adjusted_quantity))
        logger.info("Order scaled by risk engine: %s -> %s", original_qty, check.adjusted_quantity)

    # 3. Execute order (Phase 45 flow)
    self._execute_order(order, signal)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| File-lock kill switch | DB-row kill switch | Standard since ~2015 | Crash-safe, queryable, no Windows file locking issues |
| Hard reject on cap breach | Scale-down to cap | Current best practice | Preserves signal intent for near-boundary situations |
| Manual-only circuit breaker | Configurable N + time-based reset | Modern algo systems | Reduces operational burden for daily strategies |
| Generic pybreaker for loss tracking | Custom domain-specific tracker | This project | pybreaker counts HTTP failures, not realized P&L |

**Deprecated/outdated:**
- File-lock state persistence: fragile on Windows, not crash-safe (use DB row)
- Automatic kill switch re-enable after cooldown: considered unsafe best practice in production algo trading (FIA best practices 2024)

---

## Decisions Made (Claude's Discretion)

The following open questions from CONTEXT.md are resolved here based on research:

### Kill Switch Shutdown Sequence
**Decision:** halt + cancel pending orders (not gradual). Rationale: paper trading has no real exchange impact from abrupt halt. Safety > elegance. Positions are left open (no flattening) because paper trading has no real exposure and flattening would add complexity without benefit for simulation purposes.

### Kill Switch Re-Enable Mechanism
**Decision:** Manual-only, requires reason string. No cooldown timer. Rationale: FIA best practices state kill switch re-enable should require human judgment. Automatic re-enable after cooldown creates false safety (a bad strategy will keep losing after the cooldown). For the 2-week validation window, manual re-enable is the right call.

### Kill Switch State Persistence
**Decision:** DB row in `dim_risk_state`. Single-row table, always state_id=1. Rationale: DB is crash-safe (ACID), queryable, no Windows file-lock issues, consistent with all other project state tables. File lock is rejected per project MEMORY.md patterns.

### 10% Position Fraction vs Hard Cap
**Decision:** 10% in `dim_executor_config` is the TARGET (executor's job). 15% per-asset cap in `dim_risk_limits` is the CEILING (risk engine's job). This separation of concerns is clean: executor shoots for 10%, risk engine catches anything that drifts to 15% before it goes higher. No conflict.

### Circuit Breaker Loss Metric
**Decision:** Track REALIZED P&L per fill cycle (position open -> close). Not unrealized mark-to-market. Portfolio-wide daily return also tracked (from `day_open_portfolio_value`) but triggers a separate counter. Both trigger independently; both can pause signal processing.

### Circuit Breaker Reset Mechanism
**Decision:** Time-based cooldown (24 hours by default, configurable in `dim_risk_limits`) PLUS manual override available. Rationale: daily 1D strategies naturally reset after one trading day; a 24-hour cooldown is the minimal operationally sensible period that aligns with the strategy cadence.

### Hot-Reload vs Restart
**Decision:** Hot-reload on every executor run. `dim_risk_limits` is read fresh on each `check_order()` call. No caching between invocations. The overhead is negligible (< 1 ms for a single SELECT) and the benefit is substantial during the 2-week validation window where thresholds may need tuning.

### Risk Engine Architecture
**Decision:** Library pattern (executor calls `risk_engine.check_order()`). Not middleware/interceptor. Rationale: middleware adds indirection that makes testing and debugging harder. The library pattern is explicit, testable in isolation, and matches the project's existing call-the-function style.

---

## Open Questions

1. **Phase 45 completion status**
   - What we know: Phase 45 plans exist (45-01 through 45-04) but no SUMMARYs found for 45-01
   - What is unclear: Whether `cmc_orders`, `cmc_positions`, `cmc_fills`, `dim_executor_config` tables actually exist in DB
   - Recommendation: Phase 46 plan should include a PREREQUISITE CHECK step that verifies these tables exist before any migration runs

2. **Portfolio value computation source**
   - What we know: `cmc_positions` tracks position quantity and `last_mark_price`. `v_cmc_positions_agg` aggregates across strategies.
   - What is unclear: Whether `last_mark_price` on `cmc_positions` is reliably populated by Phase 45 executor before Phase 46 risk checks run
   - Recommendation: Risk engine should use `SUM(ABS(quantity) * COALESCE(last_mark_price, avg_cost_basis))` from `cmc_positions` as the portfolio value estimate. Fallback to avg_cost_basis when mark price is NULL.

3. **Phase 45 executor interface for risk engine hook-in**
   - What we know: Phase 45 plan describes `PaperExecutor` class in `src/ta_lab2/executor/paper_executor.py`
   - What is unclear: Exact method signature where risk check should be inserted
   - Recommendation: Phase 46 plan should describe where in `PaperExecutor._process_signal()` to wire in `risk_engine.check_order()`. The executor plan (45-02 or 45-03) likely has this defined; verify during execution.

---

## Sources

### Primary (HIGH confidence)
- Project codebase: `src/ta_lab2/notifications/telegram.py` — `send_critical_alert()`, `AlertSeverity` confirmed
- Project codebase: `src/ta_lab2/paper_trading/canonical_order.py` — `CanonicalOrder` interface
- Project codebase: `src/ta_lab2/paper_trading/paper_order_logger.py` — engine.begin() + NullPool pattern
- Project codebase: `src/ta_lab2/trading/position_math.py` — realized PnL computation, NautilusTrader netting model
- Project codebase: `.planning/phases/44-order-fill-store/44-01-PLAN.md` — confirmed table schemas (cmc_orders, cmc_positions, cmc_fills)
- Project codebase: `.planning/phases/45-paper-trade-executor/45-CONTEXT.md` — executor interface and dim_executor_config
- NautilusTrader docs: https://nautilustrader.io/docs/latest/api_reference/risk/ — 3-state trading_state (active/reducing/halted) confirmed HIGH

### Secondary (MEDIUM confidence)
- FIA 2024 best practices summary: https://www.fia.org/fia/articles/fia-releases-best-practices-automated-trading-risk-controls-and-system-safeguards — kill switch definition, manual-only re-enable pattern confirmed
- Trading Technologies risk limits overview: https://library.tradingtechnologies.com/user-setup/rl-overview.html — per-account + parent-account hierarchy, daily credit limits confirmed

### Tertiary (LOW confidence)
- WebSearch results: "algorithmic trading risk controls position limits daily loss stop Python 2025" — general patterns, not project-specific; used only for defaults verification
- WebSearch results: "daily loss limit portfolio drawdown day open reset daily" — confirmed 3% daily loss is common default for retail algo systems

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; all existing project stack
- Architecture (library vs middleware): HIGH — library pattern matches all existing project code
- Kill switch mechanics: HIGH — DB-row pattern is standard; NautilusTrader confirms 3-state model
- Position cap enforcement: HIGH — scale-down is confirmed CONTEXT.md decision; math is trivial
- Daily loss calculation: MEDIUM — realized P&L approach is sound but exact day-open boundary is project-specific
- Circuit breaker: MEDIUM — consecutive loss tracking approach is sound; exact defaults for crypto daily are LOW confidence
- DDL schemas: HIGH — follow exact same patterns as Phase 44 schemas (verified from 44-01-PLAN.md)
- Discretionary override: HIGH — CONTEXT.md fully specifies the behavior; implementation is mechanical

**Research date:** 2026-02-24
**Valid until:** 2026-03-25 (30 days; stable domain — risk control patterns change slowly)
