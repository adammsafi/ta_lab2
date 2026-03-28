# Phase 87: Live Pipeline & Alert Wiring - Research

**Researched:** 2026-03-24
**Domain:** Pipeline orchestration, IC staleness monitoring, signal anomaly detection, alert tiering, dead-man switch
**Confidence:** HIGH (all findings from direct codebase inspection)

## Summary

Phase 87 wires together existing components (signals, executor, drift, alerts) that already exist but are not fully plumbed into `run_daily_refresh.py`. The pipeline orchestration itself is mostly done — `run_daily_refresh.py` already contains `run_signal_refreshes()`, `run_paper_executor_stage()`, `run_drift_monitor_stage()`, and the macro alert stage. The four new capabilities are: (1) `--from-stage` partial-run flag, (2) IC staleness monitor as a daily pipeline stage, (3) signal validation gate between signals and executor, and (4) dead-man switch via a `pipeline_run_log` table.

The existing `MacroAlertManager` (Phase 72) is the canonical throttled-alert pattern to follow. It has per-type cooldown, DB-persisted alert log (`macro_alert_log`), and severity escalation — replicate this pattern for the new alert types. `compute_rolling_ic()` in `ta_lab2/analysis/ic.py` already computes rolling Spearman IC using the rank-correlate approach and returns IC-IR directly. The multi-window staleness check is not implemented anywhere yet; it needs a new class that runs `compute_rolling_ic()` at three lookback windows (30/63/126 bars) and compares short-window vs. long-window IC-IR to detect decay trend.

**Primary recommendation:** Extend `run_daily_refresh.py` by adding three new stage functions (`run_signal_validation_gate`, `run_ic_staleness_check`, `run_pipeline_completion_alert`) plus a new `pipeline_run_log` table migration. Reuse all existing patterns: `ComponentResult` dataclass, subprocess-per-stage, Telegram throttling via DB log.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ta_lab2.analysis.ic` | project | `compute_rolling_ic()`, `compute_forward_returns()` | Already used everywhere for IC computation |
| `ta_lab2.notifications.telegram` | project | `send_alert()`, `send_message()`, throttle logic | Phase 28 foundation; `AlertSeverity` enum present |
| `ta_lab2.notifications.macro_alerts` | project | `MacroAlertManager` — throttle + DB log pattern | Canonical alert pattern; use as template |
| `ta_lab2.analysis.feature_selection` | project | `load_ic_ranking()`, `classify_feature_tier()` | IC-IR cutoff thresholds defined here |
| `SQLAlchemy` | project | DB operations | Standard throughout codebase |
| `subprocess` | stdlib | Stage runner pattern | Used by every stage in `run_daily_refresh.py` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas` | project | IC series windowing, signal distribution stats | Rolling window comparisons |
| `scipy.stats.spearmanr` | project | Backing `compute_rolling_ic` | Indirectly via ic.py |
| `schtasks` | Windows OS | Windows Task Scheduler CLI | Setting up scheduled daily run |
| `cron` | Unix | Unix scheduling | Alternative to schtasks |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| DB-persisted alert log | In-memory cooldown | DB log provides audit trail; in-memory resets on restart — do not use |
| Subprocess stage runners | Inline function calls | Subprocess isolates failures; existing pattern; use subprocess |
| `compute_rolling_ic()` | Custom pandas rolling | Already vectorized, 30x faster than per-window spearmanr |

**Installation:**
No new dependencies. All required code is already installed in the project.

---

## Architecture Patterns

### Recommended Project Structure (new files only)
```
src/ta_lab2/
├── scripts/
│   ├── run_daily_refresh.py              # EXTEND: --from-stage, new stages
│   ├── signals/
│   │   └── validate_signal_anomalies.py  # NEW: SignalAnomalyGate
│   └── analysis/
│       └── run_ic_staleness_check.py     # NEW: ICStalenessMonitor
alembic/versions/
└── n8o9p0q1r2s3_phase87_pipeline_wiring.py  # NEW: pipeline_run_log + signal_anomaly_log tables
```

### Pattern 1: Stage Function in run_daily_refresh.py

Every new pipeline stage follows the existing `ComponentResult` pattern exactly.

**What:** Subprocess-based stage runner that returns `ComponentResult`.
**When to use:** For every new pipeline stage added to `run_daily_refresh.py`.

```python
# Source: existing run_daily_refresh.py ComponentResult pattern
def run_signal_validation_gate(args, db_url: str) -> ComponentResult:
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.signals.validate_signal_anomalies",
        "--db-url", db_url,
    ]
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    if getattr(args, "dry_run", False):
        return ComponentResult(component="signal_validation_gate", success=True,
                               duration_sec=0.0, returncode=0)
    start = time.perf_counter()
    try:
        result = subprocess.run(cmd, check=False, capture_output=True,
                                text=True, timeout=TIMEOUT_SIGNAL_GATE)
        duration = time.perf_counter() - start
        if result.returncode == 0:
            return ComponentResult(component="signal_validation_gate", success=True,
                                   duration_sec=duration, returncode=0)
        else:
            # Non-zero means anomalies detected — pipeline continues, gate blocks signals
            error_msg = f"Signal anomalies detected (code {result.returncode})"
            return ComponentResult(component="signal_validation_gate", success=False,
                                   duration_sec=duration, returncode=result.returncode,
                                   error_message=error_msg)
    except subprocess.TimeoutExpired:
        ...  # standard timeout pattern
```

### Pattern 2: --from-stage Flag

**What:** Named stage list with dependency skip logic.
**When to use:** When user wants to resume pipeline after a failed stage.

```python
# In run_daily_refresh.py argparse setup:
STAGE_ORDER = [
    "sync_vms", "bars", "emas", "amas", "desc_stats",
    "macro_features", "macro_regimes", "macro_analytics", "cross_asset_agg",
    "regimes", "features", "garch", "signals",
    "signal_validation_gate",   # NEW Phase 87
    "ic_staleness_check",       # NEW Phase 87
    "calibrate_stops", "portfolio", "executor", "drift_monitor",
    "pipeline_alerts",          # NEW Phase 87
    "stats"
]

# CLI argument:
p.add_argument(
    "--from-stage",
    metavar="STAGE",
    default=None,
    choices=STAGE_ORDER,
    help=(
        "Skip all stages before STAGE and run from STAGE onward. "
        "Use for re-runs after failures."
    ),
)

# In main():
from_stage = getattr(args, "from_stage", None)
if from_stage and args.all:
    skip_before = STAGE_ORDER.index(from_stage)
    # Disable stages before the named stage
    # e.g., if from_stage="signals", disable sync_vms through garch
```

### Pattern 3: IC Staleness Monitor — Multi-Window Comparison

**What:** Compare rolling IC-IR across 30/63/126 bar windows. Alert when short-window decays below threshold relative to long-window. This is the "multi-window best practice" the context requires.

**Decision basis:** Three-window comparison (short/medium/long) is standard practice for regime-aware alpha decay detection. The signal is: short-window IC-IR dropping meaningfully below long-window IC-IR indicates recent decay, not just noise. Using the IC-IR itself (not raw IC) because IC-IR normalizes by volatility of IC, making comparisons across time more stable.

**Method:** For each active-tier feature, compute IC-IR at 30-bar, 63-bar, and 126-bar windows. Flag decay when: (a) the 30-bar IC-IR drops below the staleness threshold (0.7) AND (b) 63-bar IC-IR also drops below 0.7 (confirming it is not a one-day spike). The 126-bar window serves as the "reference level" — alert is more severe when 126-bar IC-IR remains above 1.0 (feature historically good but recently weak).

```python
# Source: ta_lab2/analysis/ic.py compute_rolling_ic() pattern
from ta_lab2.analysis.ic import compute_rolling_ic, compute_forward_returns

IC_IR_STALENESS_THRESHOLD = 0.7   # per CONTEXT.md decision
IC_IR_ACTIVE_CUTOFF = 1.0         # Phase 80 active-tier cutoff

WINDOWS = {
    "short": 30,    # ~1 month of daily bars
    "medium": 63,   # ~1 quarter
    "long": 126,    # ~6 months
}

def compute_multi_window_ic_ir(
    feature: pd.Series,
    fwd_ret: pd.Series,
) -> dict[str, float]:
    """Compute IC-IR at three lookback windows. Returns dict of window->ic_ir."""
    results = {}
    for name, window in WINDOWS.items():
        _, ic_ir, _ = compute_rolling_ic(feature, fwd_ret, window=window)
        results[name] = ic_ir
    return results

def is_decaying(ic_irs: dict[str, float]) -> bool:
    """True when both short and medium windows are below staleness threshold."""
    short = ic_irs.get("short", float("nan"))
    medium = ic_irs.get("medium", float("nan"))
    import math
    if math.isnan(short) or math.isnan(medium):
        return False
    return short < IC_IR_STALENESS_THRESHOLD and medium < IC_IR_STALENESS_THRESHOLD
```

### Pattern 4: MacroAlertManager as Throttle Template

Copy the exact throttle pattern from `ta_lab2/notifications/macro_alerts.py` for new alert types.

```python
# Source: ta_lab2/notifications/macro_alerts.py _is_throttled()
def _is_throttled(self, alert_type: str, key: str | None) -> bool:
    sql = text("""
        SELECT 1
        FROM pipeline_alert_log
        WHERE alert_type = :alert_type
          AND alert_key = :key
          AND sent_at > NOW() - (INTERVAL '1 hour' * :hours)
          AND throttled = FALSE
        LIMIT 1
    """)
    with self._engine.connect() as conn:
        row = conn.execute(sql, {"alert_type": alert_type,
                                 "key": key, "hours": self._cooldown_hours}).fetchone()
    return row is not None
```

### Pattern 5: Signal Anomaly Detection Baseline

**What:** Use rolling 90-day window of daily signal counts as historical baseline.
**Decision basis:** Backtest history (pre-live) is a poor baseline because regime mix differs. Rolling 90-day anchors to recent live behavior. If fewer than 30 days of live data are available, fall back to backtest history as initial baseline.

```python
# Recommended baseline approach:
# 1. Query signal count per day for each signal type from last 90 days
# 2. Compute mean and std of daily signal counts
# 3. Alert if today's count is outside mean +/- 2 sigma
# 4. For signal strength: compare today's feature_snapshot values
#    (e.g., rsi_14, atr_14) against 90-day rolling distribution

# Signal count anomaly:
def check_signal_count_anomaly(
    engine, signal_type: str, today_count: int, lookback_days: int = 90
) -> bool:
    # Query ic_results or signals table for historical daily counts
    sql = text("""
        SELECT DATE(ts) as day, COUNT(*) as cnt
        FROM signals_ema_crossover   -- repeated for all 3 tables
        WHERE ts >= NOW() - INTERVAL ':days days'
          AND position_state = 'open'
        GROUP BY DATE(ts)
        ORDER BY day
    """)
    # ... compute zscore and return abs(zscore) > 2.0

# Crowded signal detection (all tables combined):
# Alert when same asset+direction accounts for > N% of all open signals
# Recommended N = 40% (if >40% of signals all agree on same asset+direction,
# that's a crowded bet worth flagging)
CROWDED_SIGNAL_PCT = 0.40
```

### Pattern 6: Dead-Man Switch Timing

**What:** Crypto markets never close; UTC midnight daily close is the canonical boundary. Pipeline runs in the morning after UTC midnight bars close. Dead-man default: alert if daily pipeline has not completed by 06:00 UTC.

**Rationale:** CMC daily bars close at UTC midnight. The full pipeline including GARCH (30 min), features, signals, portfolio can realistically complete by 05:00 UTC. Buffer to 06:00 UTC gives 1 hour headroom. If the pipeline has not written a `pipeline_run_log` completion row by 06:00 UTC, the dead-man fires.

**Implementation:** Check `pipeline_run_log` table from a separate lightweight daily check script invoked by the scheduler 30 minutes after the expected completion time. Alternatively, the alert can be checked at the START of the next pipeline run — if previous day's completion row is missing, alert fires.

```python
# Dead-man check logic:
DEAD_MAN_CUTOFF_HOUR_UTC = 6   # 06:00 UTC

def check_dead_man(engine: Engine) -> bool:
    """Return True if yesterday's pipeline run is missing."""
    import datetime
    today_utc = datetime.datetime.now(datetime.timezone.utc).date()
    yesterday = today_utc - datetime.timedelta(days=1)
    sql = text("""
        SELECT 1 FROM pipeline_run_log
        WHERE DATE(completed_at AT TIME ZONE 'UTC') = :yesterday
          AND status = 'complete'
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(sql, {"yesterday": str(yesterday)}).fetchone()
    return row is None   # True = missed run, dead-man should fire
```

### Pattern 7: BL Weight Halving for Decayed Features

**What:** When IC staleness monitor flags a feature for a specific asset, halve that feature's weight in the per-asset IC-IR matrix stored in `dim_feature_selection` (or an override table). The BL dispatch already reads from `ic_results` via `load_per_asset_ic_weights()`. The simplest implementation is an override multiplier table.

**Decision basis:** `load_per_asset_ic_weights()` in `bakeoff_orchestrator.py` reads directly from `ic_results` and normalizes. To halve a weight without modifying `ic_results`, introduce a `dim_ic_weight_overrides` table with `(feature, asset_id, multiplier, reason, expires_at)`. The portfolio refresh script reads this table and applies multipliers before calling `build_ic_ir_dispatch_views()`.

```sql
-- New table (Phase 87 migration):
CREATE TABLE dim_ic_weight_overrides (
    override_id     SERIAL PRIMARY KEY,
    feature         TEXT NOT NULL,
    asset_id        INTEGER,        -- NULL = applies to all assets
    multiplier      NUMERIC NOT NULL DEFAULT 0.5,
    reason          TEXT,           -- e.g., 'IC decay: 30d IC-IR=0.45 < 0.70 threshold'
    created_at      TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ,    -- NULL = indefinite until manually cleared
    cleared_at      TIMESTAMPTZ,    -- NULL = active
    UNIQUE (feature, COALESCE(asset_id, -1))
);
```

### Anti-Patterns to Avoid
- **Raising an exception on signal anomaly:** Use return code 2 (anomaly detected) vs 0 (clean) vs 1 (gate check failed/error). The stage runner treats rc=2 as "anomalies detected, block signals" and continues the pipeline.
- **Running IC staleness on ALL features:** Only check active-tier features (from `feature_selection.yaml` or `dim_feature_selection`). Checking watch/archive tier wastes time and generates noise.
- **Building a separate daily_pipeline.py:** Do NOT create a parallel script. All new stages go into `run_daily_refresh.py` following the existing pattern.
- **Using the kill switch for signal anomaly blocks:** The kill switch (`dim_risk_state`) is a trading halt. Signal anomaly blocks are pre-execution gates — they should write to a `signal_anomaly_log` table, not trip the kill switch.
- **Single-window IC-IR check:** The context explicitly requires multi-window. Never collapse to one lookback window.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rolling Spearman IC | Custom pandas rolling | `compute_rolling_ic()` in `ta_lab2/analysis/ic.py` | Already vectorized, uses rank-then-correlate (30x faster) |
| Alert throttling | Time.time() + dict | `MacroAlertManager._is_throttled()` pattern + DB log | DB-persisted log survives restarts; pattern proven in Phase 72 |
| Telegram formatting | Custom string building | `telegram.send_alert(title, message, severity)` | Already handles severity emoji mapping |
| Signal history lookup | Raw SQL | `load_signal_history()` in `dashboard/queries/signals.py` | Already handles the 3-table UNION pattern |
| Per-asset IC weights | Custom SQL | `load_per_asset_ic_weights()` in `bakeoff_orchestrator.py` | Already handles normalization and universal fallback |

**Key insight:** The codebase already has all the building blocks. Phase 87 is primarily wiring, not building.

---

## Common Pitfalls

### Pitfall 1: `--from-stage` interaction with `--all`
**What goes wrong:** If `--from-stage signals` is used with `--all`, every stage before "signals" still runs because `--all` sets all `run_*` flags to True.
**Why it happens:** `run_daily_refresh.py` uses boolean flags (`run_bars = args.bars or args.all`). `--from-stage` must override those flags.
**How to avoid:** In `main()`, after parsing args but before the stage flags are computed, build a "skip_stages" set from `STAGE_ORDER[:STAGE_ORDER.index(from_stage)]` and apply it to override all `run_*` flags.
**Warning signs:** Running `--from-stage garch --all` still runs bars/EMAs in dry-run test.

### Pitfall 2: IC staleness check hits zero rows for fresh features
**What goes wrong:** A newly activated feature may have only a few days of `ic_results` rows. `compute_rolling_ic` with a 30-bar window returns `nan` when `n < 5`.
**Why it happens:** `compute_rolling_ic()` returns `(rolling_ic_series, np.nan, np.nan)` when fewer than 5 valid values exist.
**How to avoid:** Guard `is_decaying()` with an explicit `not math.isnan(ic_ir)` check. If short-window ic_ir is NaN, skip that feature — do not alert.
**Warning signs:** IC staleness monitor fires alerts on every feature immediately after a fresh IC sweep.

### Pitfall 3: Signal count baseline uses future data
**What goes wrong:** If the baseline query includes today's signals before they are inserted, the mean/std includes the partial day, inflating the baseline.
**Why it happens:** `ts >= NOW() - INTERVAL '90 days'` includes today's partial data.
**How to avoid:** Filter baseline to `DATE(ts) < CURRENT_DATE` (yesterday and earlier). Count today's signals separately and compare against that baseline.
**Warning signs:** Signal count anomaly fires on normal days because today's partial count is included in the mean.

### Pitfall 4: Dead-man alert fires on first pipeline run
**What goes wrong:** On initial deployment, `pipeline_run_log` table is empty. The dead-man check sees no prior completion row and fires an alert.
**Why it happens:** No historical rows in the new table.
**How to avoid:** Dead-man check should only compare against the PREVIOUS day's row when today's pipeline is already running. The check runs at the START of the pipeline, not end-of-day.
**Warning signs:** Telegram fires dead-man alert on every fresh install.

### Pitfall 5: BL weight halving doubles down after next staleness check
**What goes wrong:** If IC staleness fires again tomorrow for the same feature, the script inserts another override row (or updates multiplier to 0.5 again), effectively halving an already-halved weight to 0.25.
**Why it happens:** The override logic doesn't check if an override already exists.
**How to avoid:** Use `INSERT ... ON CONFLICT DO NOTHING` with the unique constraint on `(feature, COALESCE(asset_id, -1))`. Only insert the first time. Manual clearing (`cleared_at`) is required to restore the weight.
**Warning signs:** After 3 days of IC decay, effective weight is 0.5^3 = 0.125.

### Pitfall 6: Crowded signal detection counts closed signals
**What goes wrong:** `position_state = 'closed'` rows outnumber open ones in the signal tables. Including them makes crowded signal detection always fire.
**Why it happens:** Signals accumulate historical open/closed rows. Only today's fresh signals matter.
**How to avoid:** Filter `WHERE ts >= CURRENT_DATE - INTERVAL '1 day' AND position_state = 'open'` when computing crowded signal percentages.
**Warning signs:** Crowded signal alert fires every run for every asset.

### Pitfall 7: `--from-stage` with a non-`--all` invocation
**What goes wrong:** User calls `python run_daily_refresh.py --from-stage signals` without `--all`. No stages run because no explicit stage flags are set.
**Why it happens:** `--from-stage` is a modifier, not a stage selector on its own.
**How to avoid:** `--from-stage` implicitly enables `--all` and then skips stages before the named stage. Document this clearly in the help text.

---

## Code Examples

Verified patterns from the codebase:

### Existing Alert DB Log Pattern (copy for pipeline_alert_log)
```python
# Source: ta_lab2/notifications/macro_alerts.py _log_alert()
def _log_alert(self, alert_type, dimension, old_label, new_label,
               regime_key, macro_state, throttled) -> None:
    sql = text("""
        INSERT INTO macro_alert_log
            (alert_type, dimension, old_label, new_label,
             regime_key, macro_state, throttled)
        VALUES
            (:alert_type, :dimension, :old_label, :new_label,
             :regime_key, :macro_state, :throttled)
    """)
    try:
        with self._engine.begin() as conn:
            conn.execute(sql, {...})
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("macro_alert_log not accessible: %s", exc)
```

### Loading Active-Tier Features for IC Staleness
```python
# Source: ta_lab2/analysis/feature_selection.py load_ic_ranking() + configs/feature_selection.yaml
import yaml
from pathlib import Path

def load_active_tier_features() -> list[str]:
    """Load active-tier feature names from feature_selection.yaml."""
    config_path = Path(__file__).parents[4] / "configs" / "feature_selection.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return [feat["name"] for feat in cfg.get("active", [])]
```

### Querying ic_results for Rolling IC-IR at Multiple Windows
```python
# Source: ta_lab2/analysis/ic.py compute_rolling_ic() + ta_lab2/analysis/ic.py load_feature_series()
from ta_lab2.analysis.ic import compute_rolling_ic, compute_forward_returns, load_feature_series

def compute_feature_staleness(
    engine, asset_id: int, feature_name: str, tf: str = "1D"
) -> dict[str, float]:
    """Return IC-IR at 30/63/126 bar windows for one feature+asset."""
    feat_series, close_series = load_feature_series(engine, asset_id, feature_name, tf)
    if feat_series is None or len(feat_series) < 130:
        return {}
    fwd_ret = compute_forward_returns(close_series, horizon=1)
    results = {}
    for label, window in [("short", 30), ("medium", 63), ("long", 126)]:
        _, ic_ir, _ = compute_rolling_ic(feat_series, fwd_ret, window=window)
        results[label] = float(ic_ir) if not math.isnan(ic_ir) else float("nan")
    return results
```

### Windows Task Scheduler Setup (CLI pattern)
```batch
:: Create daily task at 00:30 UTC (adjust for local timezone offset)
:: Equivalent: run 30 minutes after UTC midnight daily bar close
schtasks /Create /TN "ta_lab2_daily_refresh" /TR "python -m ta_lab2.scripts.run_daily_refresh --all --paper-start 2025-01-01" /SC DAILY /ST 00:30 /RU SYSTEM /F

:: Query status
schtasks /Query /TN "ta_lab2_daily_refresh" /FO LIST

:: Run manually
schtasks /Run /TN "ta_lab2_daily_refresh"
```

### New DB Tables (Migration schema)
```python
# New tables needed in Phase 87 Alembic migration:

# pipeline_run_log: one row per pipeline run for dead-man switch
# Columns: run_id (UUID), started_at, completed_at, status (running/complete/failed),
#          stages_completed (JSONB list), total_duration_sec, error_message

# signal_anomaly_log: audit log for signal gate decisions
# Columns: check_id (UUID), checked_at, signal_type, anomaly_type
#          (count_anomaly/strength_anomaly/crowded_signal), severity,
#          count_today, count_mean, count_zscore, blocked (bool), notes

# pipeline_alert_log: throttle log for all Phase 87 alert types
# Columns: alert_id (UUID), alert_type, alert_key, severity, message_preview,
#          sent_at, throttled (bool)

# dim_ic_weight_overrides: BL weight halving for decayed features
# Columns: override_id, feature, asset_id (nullable), multiplier,
#          reason, created_at, expires_at (nullable), cleared_at (nullable)
#          UNIQUE (feature, COALESCE(asset_id, -1))
```

---

## Alert Tier Classification

Based on codebase patterns and crypto market cadence:

| Alert Event | Tier | Cooldown | Rationale |
|-------------|------|----------|-----------|
| Kill switch triggered | CRITICAL | 6h | Trading halt — immediate action needed |
| Drift pause activated | CRITICAL | 6h | P&L deviation — needs immediate review |
| Signal anomaly gate blocked | CRITICAL | 4h | Pre-execution block — needs manual approval |
| IC decay detected (feature halved) | WARNING | 24h | Alpha decay — next day review is fine |
| Dead-man switch (missed pipeline) | CRITICAL | 12h | Pipeline down — immediate action |
| Regime change | WARNING | 6h | Existing MacroAlertManager handles this |
| Drawdown > threshold | WARNING | 12h | Daily review cadence is appropriate |
| Pipeline complete daily digest | INFO | 20h | Once per day, batched |
| New signal fires | INFO | batched daily | High-volume; batching avoids noise |

**Telegram emoji headers (from CONTEXT.md decisions):**
- `🟢 Pipeline Complete` — INFO daily digest
- `🟡 IC Decay Warning` — WARNING
- `🔴 Kill Switch / Signal Gate Blocked / Dead-Man` — CRITICAL
- `🟠 Drift Pause / Drawdown Warning` — WARNING

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual pipeline invocation only | Scheduled via Windows Task Scheduler | Phase 87 | Autonomous daily operation |
| No signal anomaly detection | Signal validation gate blocking executor | Phase 87 | Pre-execution safety gate |
| Single-window IC-IR check | Multi-window (30/63/126 bar) IC-IR comparison | Phase 87 | More robust alpha decay detection |
| Ad-hoc Telegram sends | Throttled, tiered, DB-logged alerts | Phase 72 (macro) → Phase 87 (expanded) | Unified alert infrastructure |
| Executor runs on all signals | Gate-filtered signals only | Phase 87 | Blocks anomalous signals |

**Deprecated/outdated in Phase 87 context:**
- Single `--all` flag without stage resume: augmented with `--from-stage` for re-run capability
- No pipeline health visibility: `pipeline_run_log` table provides completion audit trail

---

## Open Questions

1. **Where does the IC staleness check load feature time series from?**
   - What we know: `load_feature_series()` in `ta_lab2/analysis/ic.py` loads from the `features` table. The function signature is `load_feature_series(engine, asset_id, feature, tf)`.
   - What's unclear: For the ~99 assets in the pipeline, running staleness checks for all active-tier features (dozens) at three windows each is potentially 99 x N_features x 3 rolling IC computations. Runtime needs bounding.
   - Recommendation: Limit staleness check to top 10 active-tier features by IC-IR mean, applied only to "representative" assets (BTC id=1, ETH id=1027) initially. Expand later.

2. **How does the BL weight halving interact with the portfolio refresh script?**
   - What we know: `refresh_portfolio_allocations.py` calls `load_per_asset_ic_weights()` which reads `ic_results` directly.
   - What's unclear: The new `dim_ic_weight_overrides` table needs to be read by `refresh_portfolio_allocations.py` and applied as multipliers. This is a Phase 87 extension to that script.
   - Recommendation: Add a `load_ic_weight_overrides(engine)` helper called in `refresh_portfolio_allocations.py` before the BL dispatch call.

3. **Crowded signal threshold value**
   - What we know: CONTEXT.md defers this to research.
   - What's unclear: No empirical data on historical signal concentration in this system.
   - Recommendation: Use 40% as the initial crowded signal threshold. At any given time, if more than 40% of active open signals agree on the same asset+direction combination, that is likely non-independent. Tune post-deployment.

---

## Sources

### Primary (HIGH confidence)
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/run_daily_refresh.py` — current stage structure, 18+ stages already implemented
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/notifications/telegram.py` — AlertSeverity enum, send_alert(), throttle-free implementation
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/notifications/macro_alerts.py` — DB-persisted throttle pattern (MacroAlertManager)
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/analysis/ic.py` — compute_rolling_ic(), compute_forward_returns(), multi-window capability confirmed
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/analysis/feature_selection.py` — load_ic_ranking(), classify_feature_tier(), IC-IR cutoff=0.3 for active tier
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/configs/feature_selection.yaml` — active-tier features confirmed (AMA variants dominant; IC-IR > 1.0 for top features)
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/backtests/bakeoff_orchestrator.py` — load_per_asset_ic_weights() function signature and behavior
- Direct inspection: `C:/Users/asafi/Downloads/ta_lab2/alembic/versions/m7n8o9p0q1r2_phase86_portfolio_pipeline.py` — most recent migration (Phase 86), confirms stop_calibrations and target_annual_vol

### Secondary (MEDIUM confidence)
- Context from CONTEXT.md Phase 87 decisions — locked user decisions incorporated directly
- Context from MEMORY.md — Phase 80 IC-IR cutoffs (active-tier = 1.0), project structure

### Tertiary (LOW confidence)
- Dead-man switch UTC timing (06:00 UTC) based on crypto market structure reasoning, not empirical measurement of pipeline runtime. Validate after first full run.
- Crowded signal threshold (40%) is a reasoned estimate, not empirically derived from this system's signal distribution.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all from direct file inspection
- Architecture patterns: HIGH — pattern-matched to existing codebase patterns
- New tables needed: HIGH — list is complete and consistent with existing migrations
- Multi-window IC methodology: MEDIUM — standard practice reasoning + codebase capability verified; specific thresholds are reasonable estimates
- Dead-man timing: MEDIUM — crypto market cadence reasoning is sound, exact timing requires empirical validation
- Crowded signal threshold: LOW — no empirical baseline available

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable codebase; pipeline structure unlikely to change in 30 days)
