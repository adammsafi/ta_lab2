# Phase 71: Event Risk Gates - Research

**Researched:** 2026-03-03
**Domain:** Risk engine extension, macro event calendar, stress indicators, composite score, DB-configurable thresholds
**Confidence:** HIGH

---

## Summary

Phase 71 adds a second layer of macro-aware risk control on top of the existing tail-risk / kill-switch system. The architecture involves three independent subsystems: (1) a scheduled-event gate that reads `dim_macro_events` to detect proximity to FOMC/CPI/NFP releases; (2) real-time stress indicator gates (VIX, carry, credit) that read `fred.fred_macro_features`; and (3) a composite stress score table. All gates produce a `size_mult` and an optional FLATTEN signal. Gate stacking should follow tighten-only semantics (worst-of) matching the existing `_tighten()` pattern in `resolver.py`.

The existing risk infrastructure is well-suited for extension. `RiskEngine.check_order()` already has a Gate 1.5 that reads `tail_risk_state` from `dim_risk_state` and applies `size_mult`. The new macro gates are best implemented as Gate 1.6b (event gates), running after the existing tail risk check and before circuit breaker. The `check_tail_risk_state()` method can be generalized into a `check_all_macro_gates()` call that returns a composite `(state, size_mult)` pair.

Key FRED columns already exist in `fred.fred_macro_features`: `vixcls` (raw), `dexjpus_daily_zscore` (carry velocity), `hy_oas_30d_zscore` (credit stress), `nfci_level`, `us_jp_rate_spread`. CHF (DEXSZUS) and EUR (DEXUSEU) carry pairs are NOT currently synced from the VM -- these require a VM collection and sync extension.

**Primary recommendation:** Implement macro gates as a new `MacroGateEvaluator` class that reads `fred.fred_macro_features` and `dim_macro_events`. It outputs a `MacroGateResult(state, size_mult, active_gates: list)`. Wire it into `RiskEngine.check_order()` after Gate 1 (kill switch) and before Gate 2 (circuit breaker). Store per-gate state in a new `dim_macro_gate_state` table. Store composite score history in `cmc_macro_stress_history`.

---

## Standard Stack

All tools are existing project dependencies. No new packages needed.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlalchemy | 2.x | All DB reads/writes for gates, events, overrides | Project-wide convention |
| pandas | 2.x | DataFrame operations for composite score computation | All macro code uses pandas |
| alembic | installed | Schema migrations for new tables | All schema changes go through Alembic |
| pytz / datetime | stdlib | Timezone-aware event window arithmetic (ET timestamps) | FOMC announces at 2pm ET |
| requests | installed | Telegram alerts on gate transitions | Already used in kill_switch.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas.tseries.holiday | stdlib | US business day calendar for weekend-aware staleness | `pd.offsets.CustomBusinessDay(calendar=USFederalHolidayCalendar())` |
| numpy | installed | Percentile computation for VIX percentile in composite score | Already used throughout macro module |

**Installation:** No new packages needed.

---

## Architecture Patterns

### Existing Risk Gate Architecture (CONFIRMED)

The gate chain in `RiskEngine.check_order()` (`src/ta_lab2/risk/risk_engine.py` lines 240-397):

```
Gate 1:   Kill switch         -- _is_halted() -- block if trading halted
Gate 1.5: Tail risk state     -- check_tail_risk_state() -- reduce/flatten if vol spike
Gate 2:   Circuit breaker     -- _is_circuit_breaker_tripped()
Gate 3:   Per-asset position cap
Gate 4:   Portfolio utilization cap
Gate 1.6: Margin/liquidation  -- _check_margin_gate() -- perps only, buys only
Gate 5:   All pass
```

New macro gates slot in at **Gate 1.7** (after tail risk, before circuit breaker):
```python
# Gate 1.7: Macro event / stress gates
macro_state, macro_size_mult = self.check_macro_gates(asset_id, strategy_id)
if macro_state == "flatten":
    return RiskCheckResult(allowed=False, blocked_reason="Macro gate: FLATTEN state active")
if macro_state == "reduce" and order_side.lower() == "buy":
    order_qty = (order_qty * Decimal(str(macro_size_mult))).quantize(Decimal("0.00000001"))
    order_notional = order_qty * fill_price
```

The combined (tail_risk + macro_gate) `size_mult` uses worst-of semantics:
```python
effective_size_mult = min(tail_size_mult, macro_size_mult)
```

### dim_macro_events Table Design

New table for scheduled event calendar. Primary key is `(event_type, event_ts)`:

```sql
CREATE TABLE dim_macro_events (
    event_id     SERIAL PRIMARY KEY,
    event_type   TEXT NOT NULL,           -- 'fomc', 'cpi', 'nfp'
    event_ts     TIMESTAMPTZ NOT NULL,    -- exact announcement timestamp (ET -> UTC stored)
    data_period  TEXT NOT NULL,           -- e.g. '2026-01' for January 2026 data
    source       TEXT NOT NULL,           -- 'fed_gov', 'bls_gov', 'manual'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_macro_event UNIQUE (event_type, event_ts)
);
-- Index for gate window lookups
CREATE INDEX idx_macro_events_type_ts ON dim_macro_events (event_type, event_ts);
```

Seed data (2026-2027) goes in migration. Auto-fetch updates the table via a refresh script.

### dim_macro_gate_state Table Design

Stores live gate state (one row per gate, like dim_risk_state pattern):

```sql
CREATE TABLE dim_macro_gate_state (
    gate_id          TEXT PRIMARY KEY,    -- 'fomc', 'cpi', 'nfp', 'vix', 'carry', 'credit', 'freshness'
    gate_state       TEXT NOT NULL DEFAULT 'normal',  -- 'normal', 'reduce', 'flatten'
    size_mult        NUMERIC NOT NULL DEFAULT 1.0,
    triggered_at     TIMESTAMPTZ,
    trigger_reason   TEXT,
    cleared_at       TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cooldown_ends_at TIMESTAMPTZ,         -- gate stays active until this timestamp
    CONSTRAINT chk_macro_gate_state CHECK (gate_state IN ('normal', 'reduce', 'flatten')),
    CONSTRAINT chk_macro_gate_size  CHECK (size_mult >= 0.0 AND size_mult <= 1.0)
);
```

### cmc_macro_stress_history Table Design

Stores composite score history for backtesting/analysis:

```sql
CREATE TABLE cmc_macro_stress_history (
    ts                   TIMESTAMPTZ NOT NULL,         -- computed timestamp
    composite_score      NUMERIC NOT NULL,             -- 0-100 weighted sum
    stress_tier          TEXT NOT NULL,                -- 'calm', 'elevated', 'stressed', 'crisis'
    vix_percentile       NUMERIC,                      -- VIX percentile component
    hy_oas_zscore        NUMERIC,                      -- HY OAS 30d z-score component
    carry_velocity_zscore NUMERIC,                     -- carry z-score component
    nfci_level           NUMERIC,                      -- NFCI level component
    vix_raw              NUMERIC,
    hy_oas_raw           NUMERIC,
    dexjpus_zscore_raw   NUMERIC,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ts)
);
```

### dim_macro_gate_overrides Table Design

Per-gate override with expiry (new dedicated table per CONTEXT.md):

```sql
CREATE TABLE dim_macro_gate_overrides (
    override_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gate_id       TEXT NOT NULL,              -- matches dim_macro_gate_state.gate_id
    operator      TEXT NOT NULL,
    reason        TEXT NOT NULL,
    override_type TEXT NOT NULL,              -- 'disable_gate', 'force_normal', 'force_reduce'
    expires_at    TIMESTAMPTZ NOT NULL,       -- gate override auto-expires
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reverted_at   TIMESTAMPTZ,
    revert_reason TEXT
);
CREATE INDEX idx_macro_gate_overrides_active ON dim_macro_gate_overrides (gate_id, expires_at)
    WHERE reverted_at IS NULL;
```

### MacroGateEvaluator Class Structure

```python
# src/ta_lab2/risk/macro_gate_evaluator.py

@dataclass
class MacroGateResult:
    state: str           # 'normal', 'reduce', 'flatten'
    size_mult: float     # 0.0 - 1.0
    active_gates: list   # list of gate_id strings that are firing
    details: str

class MacroGateEvaluator:
    """Evaluates all macro event and stress gates.

    Call evaluate() once per executor run cycle to refresh gate states.
    Call check_order_gates(asset_id) per order to get current gate state.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def evaluate(self) -> MacroGateResult:
        """Re-evaluate all gates from DB. Updates dim_macro_gate_state."""
        ...

    def check_order_gates(
        self, asset_id: Optional[int] = None
    ) -> tuple[str, float]:
        """Return (state, size_mult) from current dim_macro_gate_state.
        Applies per-asset beta adjustment if asset_id is provided.
        """
        ...

    def _check_event_gate(self, event_type: str, ...) -> tuple[str, float]: ...
    def _check_vix_gate(self, ...) -> tuple[str, float]: ...
    def _check_carry_gate(self, ...) -> tuple[str, float]: ...
    def _check_credit_gate(self, ...) -> tuple[str, float]: ...
    def _check_freshness_gate(self) -> tuple[str, float]: ...
    def _compute_composite_score(self, ...) -> float: ...
```

### Integration into RiskEngine

The `RiskEngine` gets a new optional `macro_gate_evaluator` parameter:

```python
class RiskEngine:
    def __init__(
        self,
        engine: Engine,
        macro_gate_evaluator: Optional[MacroGateEvaluator] = None,
    ) -> None:
        self._engine = engine
        self._macro_gate_evaluator = macro_gate_evaluator
```

When `macro_gate_evaluator is None`, Gate 1.7 is a no-op (backward compatible). The executor instantiates `MacroGateEvaluator` at startup and passes it.

### Event Calendar Auto-Fetch Pattern

Use FRED API `releases/dates` endpoint for CPI and employment (BLS via FRED):
- CPI release_id = 10 (`Consumer Price Index`)
- Employment Situation release_id = 50

FRED API call pattern:
```python
import requests

def fetch_cpi_release_dates(api_key: str, year: int) -> list[dict]:
    """Fetch CPI release dates from FRED API."""
    url = "https://api.stlouisfed.org/fred/release/dates"
    params = {
        "release_id": 10,
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": f"{year}-01-01",
        "realtime_end": f"{year}-12-31",
        "include_release_dates_with_no_data": "true",
        "sort_order": "asc",
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()["release_dates"]
```

FOMC dates must come from `federalreserve.gov` (no official machine-readable API). The practical approach is to seed 2026-2027 dates in the migration and write a refresh script that web-scrapes the Fed calendar page or uses the FRED releases endpoint for FOMC press releases (release_id = 101).

### Freshness Gate Pattern (Business-Day Aware)

```python
# Source: inspired by check_fred_staleness() in refresh_macro_features.py

from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

_US_BD = CustomBusinessDay(calendar=USFederalHolidayCalendar())

def _business_days_stale(last_date: date, today: date) -> int:
    """Count business days between last_date and today."""
    if last_date >= today:
        return 0
    return len(pd.bdate_range(start=last_date + timedelta(days=1), end=today,
                               freq=_US_BD))
```

A series is considered stale only if `business_days_stale > threshold` (e.g., 3 business days for daily series, 8 for weekly).

### Telegram Transition Alert Pattern

Follow the existing `_try_telegram_alert()` pattern from `paper_executor.py`:
```python
# Source: src/ta_lab2/executor/paper_executor.py lines 647-661

def _send_gate_transition_alert(
    old_state: str, new_state: str, gate_id: str, reason: str
) -> None:
    """Best-effort Telegram alert on gate state transitions."""
    try:
        from ta_lab2.notifications.telegram import send_alert
        severity = "critical" if new_state == "flatten" else "warning"
        send_alert(
            title=f"Macro Gate {gate_id.upper()}: {old_state.upper()} -> {new_state.upper()}",
            message=reason,
            severity=severity,
        )
    except Exception as exc:
        logger.warning("Gate transition alert failed: %s", exc)
```

Alert on ALL transitions (both escalation and de-escalation) per CONTEXT.md.

### Per-Asset Beta Adjustment

Higher-beta assets (altcoins) get more aggressive size_mult reduction. Use a per-asset `macro_beta` column in `dim_macro_gate_state` or apply a beta scale factor from a new column in `dim_risk_limits`:

```python
def _apply_asset_beta(size_mult: float, asset_id: int) -> float:
    """Scale size_mult down further for high-beta assets."""
    # BTC (id=1): beta_factor=1.0 (no additional reduction)
    # ETH (id=52): beta_factor=0.9 (10% more reduction)
    # Altcoins: beta_factor=0.75 (25% more reduction)
    beta_factor = _load_asset_beta_factor(asset_id)  # from dim_risk_limits or new table
    return max(0.0, size_mult * beta_factor)
```

Store `macro_beta_factor` per-asset in `dim_risk_limits` (using existing `asset_id` scoping).

### Composite Stress Score Computation

```python
# Source: informed by NFCI/VIX research

def compute_composite_stress_score(
    vixcls: float,         # raw VIX level
    hy_oas_zscore: float,  # hy_oas_30d_zscore from fred_macro_features
    carry_zscore: float,   # dexjpus_daily_zscore from fred_macro_features
    nfci_level: float,     # nfci_level from fred_macro_features
    vix_weight: float = 0.40,
    hy_weight: float = 0.25,
    carry_weight: float = 0.20,
    nfci_weight: float = 0.15,
) -> float:
    """Compute composite macro stress score 0-100.

    Components:
    - VIX percentile (0-100): based on VIX historical range [10, 80]
    - HY OAS z-score (0-100): map z-score range [-2, +4] to [0, 100]
    - Carry velocity z-score (0-100): map z-score range [-3, +3] to [0, 100]
    - NFCI level (0-100): map NFCI range [-1.5, +2.5] to [0, 100]
    """
    vix_component = min(100.0, max(0.0, (vixcls - 10.0) / 70.0 * 100.0))
    hy_component  = min(100.0, max(0.0, (hy_oas_zscore + 2.0) / 6.0 * 100.0))
    carry_component = min(100.0, max(0.0, (carry_zscore + 3.0) / 6.0 * 100.0))
    nfci_component  = min(100.0, max(0.0, (nfci_level + 1.5) / 4.0 * 100.0))

    return (
        vix_component * vix_weight
        + hy_component * hy_weight
        + carry_component * carry_weight
        + nfci_component * nfci_weight
    )

# Composite score tiers:
# 0-25:  calm     -> size_mult = 1.0
# 25-50: elevated -> size_mult = 0.8
# 50-75: stressed -> size_mult = 0.6
# 75+:   crisis   -> size_mult = 0.4
```

### Recommended Project Structure

```
src/ta_lab2/risk/
    macro_gate_evaluator.py   # NEW: MacroGateEvaluator, MacroGateResult
    macro_gate_overrides.py   # NEW: GateOverrideManager (parallel to override_manager.py)
    risk_engine.py            # EXTEND: add Gate 1.7 call
    flatten_trigger.py        # UNCHANGED (per-asset vol-based gates stay separate)

src/ta_lab2/scripts/risk/
    seed_macro_events.py      # NEW: seed 2026-2027 event calendar
    refresh_macro_events.py   # NEW: auto-fetch upcoming FRED/Fed release dates
    evaluate_macro_gates.py   # NEW: CLI to run MacroGateEvaluator and log state
    macro_gate_cli.py         # NEW: override CLI (disable/enable gates)

alembic/versions/
    XX_event_risk_gates.py    # NEW: dim_macro_events, dim_macro_gate_state,
                              #      cmc_macro_stress_history, dim_macro_gate_overrides,
                              #      extend cmc_risk_events CHECK constraints
```

### Anti-Patterns to Avoid

- **Hardcoding FLATTEN at VIX > 40:** The CONTEXT.md explicitly says this needs configurable behavior (not hardcoded to most aggressive). Store the `vix_flatten_threshold` in DB as a nullable value; if NULL, VIX > 40 triggers REDUCE (not FLATTEN). Only override to FLATTEN if explicitly set in DB.
- **Aggregate freshness instead of per-series:** CONTEXT.md says per-series. Each gate (VIX, carry, credit) checks its own source series freshness independently.
- **Single dim_risk_state macro columns:** The existing `dim_risk_state` is a single-row table for the kill switch. Adding macro gate columns there would create a messy catch-all. Use the dedicated `dim_macro_gate_state` table with one row per gate.
- **Embedding event window logic in RiskEngine:** Keep the event proximity check in `MacroGateEvaluator._check_event_gate()`, not in `RiskEngine` directly. RiskEngine should only call `check_order_gates()` and act on the result.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Gate stacking (worst-of) | Custom multi-gate combiner | `min()` on all gate `size_mult` values -- same as `_tighten()` in resolver.py | Tighten-only semantics already proven in production |
| Telegram alert failure handling | try/except everywhere | `_send_gate_transition_alert()` pattern from `_try_telegram_alert()` | Alerting must never crash the gate evaluator |
| Business-day staleness | Custom calendar | `pandas.tseries.holiday.USFederalHolidayCalendar` + `pd.bdate_range` | Already available; handles US holidays |
| Event audit trail | New logging system | Write to `cmc_risk_events` (extend CHECK constraint with new event types) | Same table used by all existing gates |
| Override expiry tracking | Manual expiry check | Store `expires_at TIMESTAMPTZ` in `dim_macro_gate_overrides`; check `expires_at > now()` in query | Simple SQL WHERE clause handles expiry; no cron job needed |
| VIX percentile computation | Historical lookup table | Rolling percentile via `pd.Series.rolling(252).apply(scipy.stats.percentileofscore)` | Or approximate with linear mapping [10, 80] -> [0, 100] (simpler, no rolling needed) |
| FOMC date parsing from Fed website | HTML parser | Static seed in migration + annual update script | FOMC dates are announced a year in advance; 8 dates per year is trivial to maintain |

**Key insight:** The tighten-only worst-of semantics (`min(size_mult)`) is already battle-tested in `resolver.py`. Use exactly this pattern for combining gate size_mults.

---

## Common Pitfalls

### Pitfall 1: CHF and EUR Carry Series Not Synced

**What goes wrong:** CONTEXT.md requires multi-currency carry (CHF, EUR alongside JPY). `fred.series_values` only has `DEXJPUS`. `DEXSZUS` (USD/CHF) and `DEXUSEU` (USD/EUR) are not in `SERIES_TO_LOAD` and not synced from the VM.
**Why it happens:** Phase 65-66 only added the JPY carry pair.
**How to avoid:** The carry gate can be implemented with JPY only initially (DEXJPUS already has `dexjpus_daily_zscore`). Add CHF/EUR as a Phase 71 enhancement: extend `SERIES_TO_LOAD` in `fred_reader.py`, add VM collection for these series, add derived columns to `fred.fred_macro_features`.
**Warning signs:** `KeyError: 'DEXSZUS'` in feature_computer.py.

### Pitfall 2: VIX Levels vs. Percentile vs. Regime in fred_macro_features

**What goes wrong:** `fred_macro_features` stores `vixcls` (raw float) and `vix_regime` (TEXT: 'calm'/'elevated'/'crisis'). The gate requirements use thresholds of 30 and 40. The existing `vix_regime` uses 15/25 breakpoints (not 30/40). Reading `vix_regime` will NOT trigger the GATE-03 thresholds.
**Why it happens:** Phase 65 calibrated VIX regime for macro classification (15/25), not for risk gate triggers (30/40).
**How to avoid:** The VIX gate MUST read `vixcls` (raw float) and apply its own 30/40 thresholds. Do NOT use `vix_regime`. The gate logic lives in `MacroGateEvaluator._check_vix_gate()`, not in the feature table.

### Pitfall 3: FOMC Event Window Uses Announcement Time, Not Meeting Start

**What goes wrong:** FOMC meetings run for 2 days (e.g., Jan 27-28). The +/-24h gate window applies around the ANNOUNCEMENT (2pm ET on day 2), not the meeting start. Using the meeting start date gives a 24h early trigger.
**Why it happens:** `dim_macro_events.event_ts` stores a timestamp. If seeded with the first day of the meeting, the gate fires 24h too early.
**How to avoid:** Seed `dim_macro_events.event_ts` with the announcement timestamp: `FOMC decision = 2pm ET on the second meeting day`. Convert to UTC (19:00 UTC in winter, 18:00 UTC during EDT). Example: Jan 28 2026 14:00 ET = Jan 28 2026 19:00 UTC.

### Pitfall 4: cmc_risk_events CHECK Constraint Must Be Extended

**What goes wrong:** Inserting macro gate events into `cmc_risk_events` fails because the `event_type` CHECK constraint (from Phase 46 and 49 migrations) does not include macro gate types.
**Why it happens:** The constraint explicitly enumerates all valid event types.
**How to avoid:** The Phase 71 Alembic migration MUST drop and recreate `chk_risk_events_type` and `chk_risk_events_source` to include new types. Pattern: same as Phase 49 (`a9ec3c00a54a_tail_risk_policy.py` lines 65-94). New types: `'macro_event_gate_triggered'`, `'macro_stress_gate_triggered'`, `'macro_gate_cleared'`, `'macro_gate_override_created'`, `'macro_gate_override_expired'`. New source: `'macro_gate'`.

### Pitfall 5: Cooldown Logic Requires Updated_At Comparison, Not Triggered_At

**What goes wrong:** A gate clears when the stress condition drops below threshold. Without cooldown, the gate oscillates on/off every evaluation cycle during borderline conditions.
**Why it happens:** VIX oscillating around 30 causes rapid gate state flips.
**How to avoid:** Store `cooldown_ends_at = triggered_at + cooldown_interval` in `dim_macro_gate_state`. When evaluating, if the stress condition is gone but `now() < cooldown_ends_at`, keep the gate in its reduced state. Clear only when `now() >= cooldown_ends_at AND condition_below_threshold`.

### Pitfall 6: DEXJPUS Z-Score Direction Convention

**What goes wrong:** `dexjpus_daily_zscore` represents the daily return z-score of USD/JPY. A positive z-score means JPY is weakening (carry trade risk OFF). A negative z-score means JPY is strengthening (carry unwind risk ON). The GATE-04 condition "z-score > 2.0 with positive rate spread" needs clarification.
**Why it happens:** DEXJPUS is quoted as JPY per USD. A higher value = weaker JPY = carry flowing out = no unwind risk. A negative z-score (JPY strengthening sharply) = carry unwind.
**How to avoid:** The carry gate should trigger on `dexjpus_daily_zscore < -2.0` (JPY strengthening, carry unwind), NOT `> 2.0`. The GATE-04 requirement text uses `> 2.0 with positive rate spread` -- this likely means the absolute value condition `abs(zscore) > 2.0` when in a carry unwind direction. Verify the sign convention when implementing.

### Pitfall 7: Weekend/Holiday FRED Data Gaps

**What goes wrong:** The freshness gate fails to detect genuine staleness because FRED data is sparse on weekends and holidays. Friday VIX data is not updated Saturday -- this is normal, not staleness.
**Why it happens:** `vixcls` updates on US trading days only. Max(date) stays at Friday through Monday.
**How to avoid:** Use `_business_days_stale()` (business-day calendar). Treat stale as: `business_days_since_last_observation > 3` for daily series (not calendar days). This allows weekends + holidays without false alarms.

### Pitfall 8: Composite Score Normalization Requires Calibration

**What goes wrong:** The linear mapping [10, 80] for VIX, [-2, +4] for HY OAS z-score, etc. are arbitrary ranges. If VIX hits 90 (rare but possible), the VIX component exceeds 100 before clamping.
**Why it happens:** Normalization ranges need to be calibrated to historical data.
**How to avoid:** Use `max(0.0, min(100.0, ...))` clamping on each component. The composite score can reach 100 but never exceeds it. Store the normalization parameters as DB-configurable constants alongside the tier thresholds.

---

## Code Examples

### Existing Check Constraint Extension Pattern (for cmc_risk_events)

```python
# Source: alembic/versions/a9ec3c00a54a_tail_risk_policy.py lines 65-94

def upgrade() -> None:
    # Drop existing CHECK constraints
    op.execute(
        "ALTER TABLE public.cmc_risk_events "
        "DROP CONSTRAINT IF EXISTS chk_risk_events_type"
    )
    # Recreate with new event types added
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_type
        CHECK (event_type IN (
            'kill_switch_activated', 'kill_switch_disabled',
            'position_cap_scaled', 'position_cap_blocked',
            'daily_loss_stop_triggered',
            'circuit_breaker_tripped', 'circuit_breaker_reset',
            'override_created', 'override_applied', 'override_reverted',
            'tail_risk_escalated', 'tail_risk_cleared',
            -- Phase 71 additions:
            'macro_event_gate_triggered', 'macro_stress_gate_triggered',
            'macro_gate_cleared', 'macro_gate_override_created',
            'macro_gate_override_expired'
        ))
        """
    )
    # Also extend trigger_source
    op.execute(
        "ALTER TABLE public.cmc_risk_events "
        "DROP CONSTRAINT IF EXISTS chk_risk_events_source"
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_source
        CHECK (trigger_source IN (
            'manual', 'daily_loss_stop', 'circuit_breaker',
            'system', 'tail_risk', 'macro_gate'
        ))
        """
    )
```

### MacroGateEvaluator._check_vix_gate() Core Logic

```python
# Source: informed by check_flatten_trigger() in flatten_trigger.py

def _check_vix_gate(self, vixcls: Optional[float]) -> tuple[str, float]:
    """Evaluate VIX gate. Returns (state, size_mult)."""
    if vixcls is None:
        logger.debug("VIX gate: no data, returning normal")
        return "normal", 1.0

    # Load thresholds from DB (dim_macro_gate_state or dim_risk_limits)
    vix_reduce_threshold = self._load_gate_param("vix_reduce_threshold", default=30.0)
    vix_flatten_threshold = self._load_gate_param("vix_flatten_threshold", default=None)  # None = disabled
    vix_reduce_mult = self._load_gate_param("vix_reduce_mult", default=0.5)

    if vix_flatten_threshold is not None and vixcls >= vix_flatten_threshold:
        return "flatten", 0.0

    if vixcls >= vix_reduce_threshold:
        return "reduce", float(vix_reduce_mult)

    return "normal", 1.0
```

### MacroGateEvaluator._check_event_gate() Core Logic

```python
def _check_event_gate(
    self, event_type: str, size_mult: float, window_hours: float = 24.0
) -> tuple[str, float]:
    """Return (state, size_mult) if within +/- window_hours of event."""
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=window_hours)
    window_end = now_utc + timedelta(hours=window_hours)

    with self._engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT event_ts FROM dim_macro_events
                WHERE event_type = :event_type
                  AND event_ts BETWEEN :start AND :end
                ORDER BY event_ts ASC
                LIMIT 1
            """),
            {"event_type": event_type, "start": window_start, "end": window_end},
        ).fetchone()

    if row is not None:
        hours_to_event = (row[0] - now_utc).total_seconds() / 3600.0
        logger.info(
            "Event gate %s: firing (event in %.1fh, size_mult=%.2f)",
            event_type, hours_to_event, size_mult
        )
        return "reduce", size_mult

    return "normal", 1.0
```

### Gate State Update with Cooldown

```python
def _update_gate_state(
    self,
    gate_id: str,
    new_state: str,
    new_size_mult: float,
    reason: str,
    cooldown_hours: float = 4.0,
) -> None:
    """Update dim_macro_gate_state and log transition event."""
    now_utc = datetime.now(timezone.utc)

    with self._engine.begin() as conn:
        existing = conn.execute(
            text("SELECT gate_state FROM dim_macro_gate_state WHERE gate_id = :id"),
            {"id": gate_id},
        ).fetchone()

        old_state = existing[0] if existing else "normal"

        cooldown_ends_at = (
            now_utc + timedelta(hours=cooldown_hours)
            if new_state != "normal"
            else None
        )

        conn.execute(
            text("""
                INSERT INTO dim_macro_gate_state
                    (gate_id, gate_state, size_mult, triggered_at,
                     trigger_reason, updated_at, cooldown_ends_at)
                VALUES
                    (:id, :state, :mult, :now, :reason, :now, :cooldown_ends)
                ON CONFLICT (gate_id) DO UPDATE
                SET gate_state = EXCLUDED.gate_state,
                    size_mult = EXCLUDED.size_mult,
                    triggered_at = CASE
                        WHEN EXCLUDED.gate_state != 'normal' THEN :now
                        ELSE dim_macro_gate_state.triggered_at
                    END,
                    cleared_at = CASE
                        WHEN EXCLUDED.gate_state = 'normal' THEN :now
                        ELSE dim_macro_gate_state.cleared_at
                    END,
                    trigger_reason = EXCLUDED.trigger_reason,
                    updated_at = :now,
                    cooldown_ends_at = EXCLUDED.cooldown_ends_at
            """),
            {
                "id": gate_id, "state": new_state, "mult": new_size_mult,
                "now": now_utc, "reason": reason, "cooldown_ends": cooldown_ends_at,
            },
        )

    # Send Telegram on transitions
    if old_state != new_state:
        _send_gate_transition_alert(old_state, new_state, gate_id, reason)
        self._log_risk_event(
            event_type="macro_stress_gate_triggered" if new_state != "normal"
                       else "macro_gate_cleared",
            gate_id=gate_id, reason=reason,
        )
```

### FOMC Date Seed Data (2026-2027)

```python
# Announcement time: 2pm ET = 19:00 UTC (winter) / 18:00 UTC (summer)
FOMC_2026 = [
    # (date, UTC hour) -- day 2 of meeting, 2pm ET
    ("2026-01-28", 19),  # Jan 27-28, winter (EST)
    ("2026-03-18", 18),  # Mar 17-18, spring (EDT begins Mar 8)
    ("2026-04-29", 18),  # Apr 28-29, EDT
    ("2026-06-17", 18),  # Jun 16-17, EDT
    ("2026-07-29", 18),  # Jul 28-29, EDT
    ("2026-09-16", 18),  # Sep 15-16, EDT
    ("2026-10-28", 18),  # Oct 27-28, EDT (ends Nov 1)
    ("2026-12-09", 19),  # Dec 8-9, EST
]
FOMC_2027 = [
    ("2027-01-27", 19), ("2027-03-17", 18), ("2027-04-28", 18),
    ("2027-06-09", 18), ("2027-07-28", 18), ("2027-09-15", 18),
    ("2027-10-27", 18), ("2027-12-08", 19),
]
```

CPI 2026 release dates at 8:30 ET (confirmed: Jan data on Feb 11, Feb data on Mar 11):
- Standard pattern: data released ~10th-15th of following month, Wednesday, 8:30am ET (13:30 UTC winter, 12:30 UTC summer)

NFP 2026: first Friday of each month at 8:30am ET, unless government shutdown delays.

---

## FRED Data Availability Verified

| Gate | FRED Series | Column in fred_macro_features | Status |
|------|------------|------------------------------|--------|
| VIX gate | VIXCLS | `vixcls` (raw float) | EXISTS - Phase 65 |
| Carry gate (JPY) | DEXJPUS | `dexjpus_daily_zscore` | EXISTS - Phase 66 |
| Carry gate (CHF) | DEXSZUS | NOT in schema | MISSING - needs VM + sync extension |
| Carry gate (EUR) | DEXUSEU | NOT in schema | MISSING - needs VM + sync extension |
| Credit gate | BAMLH0A0HYM2 | `hy_oas_30d_zscore` | EXISTS - Phase 66 |
| Composite (NFCI) | NFCI | `nfci_level` | EXISTS - Phase 66 |
| Carry rate spread | DFF, IRSTCI01JPM156N | `us_jp_rate_spread` | EXISTS - Phase 65 |

**CHF/EUR carry is a new data addition.** The carry gate can be implemented initially with JPY only, and extended to multi-currency in a follow-up. CONTEXT.md says "include CHF and EUR alongside JPY" -- this requires extending `SERIES_TO_LOAD` in `fred_reader.py`, adding VM collection for DEXSZUS and DEXUSEU, and new derived columns in `fred_macro_features`.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No macro event awareness | dim_macro_events + event gate window | Phase 71 | Position sizing reduces around FOMC/CPI/NFP |
| VIX gate only via vol (flatten_trigger.py) | VIX raw level gate + existing vol gate | Phase 71 | Two independent VIX checks; raw level gate at 30/40, vol gate at 0.0923/0.1194 |
| Manual tail risk state only | Automated stress gates + composite score | Phase 71 | System reduces exposure automatically on macro stress |
| No event calendar | dim_macro_events with FRED API auto-refresh | Phase 71 | Self-updating calendar |

**Deprecated/outdated (do not confuse):**
- The existing `tail_risk_state` in `dim_risk_state` and `flatten_trigger.py` are SEPARATE from the new macro gates. They operate on asset-level vol; the new gates operate on macro indicators. Both run in parallel; their size_mults combine via worst-of.

---

## Open Questions

1. **DEXJPUS z-score sign convention for carry unwind**
   - What we know: `dexjpus_daily_zscore` is USD/JPY daily return z-score. DEXJPUS = JPY per USD. JPY strengthening = lower DEXJPUS = negative return = negative z-score.
   - What's unclear: GATE-04 says "z-score > 2.0 triggers REDUCE" -- this would be a JPY weakening signal, not a carry UNWIND signal. Carry unwinds cause JPY to strengthen (negative z-score).
   - Recommendation: Implement as `abs(dexjpus_daily_zscore) > 2.0 AND (rate_spread < 0 OR carry_direction == 'unwind')`. Document the sign convention clearly in code comments. Confirm with backtesting.

2. **VIX > 40 FLATTEN behavior (OPEN QUESTION from CONTEXT.md)**
   - What we know: User explicitly flagged this as needing backtesting study. Current instruction: implement as configurable.
   - What's unclear: Default behavior when `vix_flatten_threshold IS NULL` in DB.
   - Recommendation: Default `vix_flatten_threshold = NULL` (disabled). The system only flattens when explicitly configured. REDUCE is the default at VIX > 30. Operators can enable FLATTEN by setting the threshold in DB.

3. **CHF/EUR carry: Phase 71 scope vs. follow-up**
   - What we know: DEXSZUS and DEXUSEU are not synced. Adding them requires VM-side collection changes.
   - What's unclear: Whether Phase 71 should block on multi-currency carry or implement with JPY only.
   - Recommendation: Implement carry gate with JPY only (already has all derived columns). Add a `TODO: extend to CHF/EUR` comment. Document CHF/EUR as a follow-up task.

4. **Gate stacking: worst-of vs multiplicative**
   - What we know: CONTEXT.md says "Claude's discretion." Existing resolver uses tighten-only worst-of (`min(size_mult)`).
   - What's unclear: Whether multiplicative (`0.5 * 0.7 = 0.35`) is better than worst-of (`min(0.5, 0.7) = 0.5`).
   - Recommendation: Use worst-of (`min(size_mult)`) for consistency with the existing resolver chain. This is the established pattern in this codebase. Multiplicative is more aggressive and would compound silently.

5. **dim_macro_gate_state seeding**
   - What we know: Must be seeded with 7 rows (one per gate: fomc, cpi, nfp, vix, carry, credit, freshness).
   - What's unclear: Whether to seed in migration or in a separate seed script.
   - Recommendation: Seed in migration upgrade() to match dim_risk_state pattern.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/risk/risk_engine.py` -- Full gate chain, check_tail_risk_state(), Gate 1.5 pattern
- `src/ta_lab2/risk/flatten_trigger.py` -- EscalationState enum, FlattenTriggerResult dataclass, pure evaluation pattern
- `src/ta_lab2/risk/override_manager.py` -- Override CRUD pattern for dim_macro_gate_overrides design
- `src/ta_lab2/risk/kill_switch.py` -- activate_kill_switch() Telegram best-effort pattern
- `alembic/versions/b5178d671e38_risk_controls.py` -- dim_risk_limits, dim_risk_state, cmc_risk_events schema
- `alembic/versions/a9ec3c00a54a_tail_risk_policy.py` -- CHECK constraint extension pattern (drop+recreate)
- `alembic/versions/ac4cf1223ec7_drift_guard.py` -- Pattern for extending dim_risk_state and dim_risk_limits
- `src/ta_lab2/macro/feature_computer.py` -- All derived FRED column names, computation patterns
- `src/ta_lab2/macro/fred_reader.py` -- SERIES_TO_LOAD list (confirms CHF/EUR not present)
- `src/ta_lab2/notifications/telegram.py` -- send_alert(), send_critical_alert() signatures
- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` -- fred_macro_features schema (vixcls, ingested_at columns)
- `alembic/versions/c4d5e6f7a8b9_fred_phase66_derived_columns.py` -- Phase 66 derived columns (dexjpus_daily_zscore, hy_oas_30d_zscore, nfci_level)
- `src/ta_lab2/regimes/resolver.py` -- _tighten() worst-of semantics, TightenOnlyPolicy
- `src/ta_lab2/scripts/macro/refresh_macro_features.py` -- check_fred_staleness() pattern, FRED_STALENESS_WARN_HOURS
- federalreserve.gov/monetarypolicy/fomccalendars.htm -- All 2026 and 2027 FOMC meeting dates (HIGH)
- fred.stlouisfed.org/docs/api/fred/release_dates.html -- FRED releases/dates API (release_id=10 CPI, release_id=50 Employment)

### Secondary (MEDIUM confidence)
- bls.gov -- CPI release dates: Jan data Feb 11 2026, Feb data Mar 11 2026 (confirmed); remaining months estimated at ~10th-14th
- WebSearch: VIX 30/40 as reduce/flatten thresholds are common practice in quantitative risk management
- WebSearch: NFCI/VIX/HY OAS correlation confirmed (71% monthly correlation per LCD search result)

### Tertiary (LOW confidence)
- NFP 2026 dates: estimated as first Friday of each month at 8:30am ET; BLS direct access blocked (403)
- CHF/EUR carry: DEXSZUS and DEXUSEU confirmed as FRED series IDs but not verified as available in project's VM-synced dataset

---

## Metadata

**Confidence breakdown:**
- Risk engine gate chain structure: HIGH -- read source
- FRED data availability (VIX, carry, credit): HIGH -- confirmed in feature_computer.py and migration files
- CHF/EUR carry gap: HIGH -- confirmed absent from SERIES_TO_LOAD
- cmc_risk_events CHECK extension pattern: HIGH -- confirmed from Phase 49 migration
- FOMC 2026-2027 dates: HIGH -- fetched from federalreserve.gov directly
- CPI 2026 release dates: MEDIUM -- Jan/Feb confirmed, remainder pattern-estimated
- NFP 2026 dates: MEDIUM -- BLS blocked, known to be first Friday of month

**Research date:** 2026-03-03
**Valid until:** 2026-04-03 (stable codebase; re-verify CHF/EUR series before adding carry gate extension)
