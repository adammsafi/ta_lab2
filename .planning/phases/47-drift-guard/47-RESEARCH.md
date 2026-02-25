# Phase 47: Drift Guard - Research

**Researched:** 2026-02-25
**Domain:** Live/backtest drift detection, signal matching, kill switch integration, tracking error monitoring, P&L attribution decomposition, point-in-time data snapshots
**Confidence:** HIGH (architecture patterns, DB schema, kill switch integration, signal matching), MEDIUM (tracking error thresholds, attribution decomposition), LOW (exact threshold calibration for this specific 2-strategy system)

---

## Summary

Phase 47 adds continuous drift monitoring between the paper executor's realized fills and what the backtester would have predicted for the same date range. Three design problems were deferred to research: (1) how to match paper trades against backtest trades, (2) whether to integrate with Phase 46's kill switch or introduce a softer pause, and (3) what tracking error thresholds are defensible for this system.

The research findings are grounded in the existing codebase (Phases 28, 45, 46), QuantConnect's reconciliation documentation, quantitative trading literature on implementation shortfall, and project patterns.

**Signal matching recommendation:** Use position-state driven matching rather than strict timestamp alignment. For 1D EMA strategies, both the backtest and paper executor derive trades from the same signal table rows (`cmc_signals_ema_crossover`). Match at the signal level (signal table row by `(id, ts, signal_id)`) rather than at the fill timestamp level. This gives exact correspondence without tolerance windows.

**Kill switch integration recommendation:** Integrate Phase 46's existing `KillSwitch` as the terminal response (unified), but add a softer `drift_paused` state to `dim_risk_state` for the graduated warning phase. Three tiers: MONITOR (approaching threshold, Telegram WARNING) -> PAUSE (drift triggered, add `drift_paused` flag to stop new signal processing without full kill switch) -> KILL (if pause is ignored or drift accelerates, escalate to full kill switch). The drift pause preserves existing positions; the kill switch cancels pending orders.

**Tracking error threshold recommendation:** The DRIFT-03 requirement (5-day window, 1.5%) is reasonable for 1D crypto strategies. Research found no specific industry standard for crypto drift monitoring, but the 1.5% threshold for a 5-day rolling window on a strategy with typical volatility of 2-5% daily is defensible as approximately 0.5-sigma trigger. Recommend keeping the requirement as-is but making both the window and threshold configurable from `dim_risk_limits`.

**Primary recommendation:** Build `DriftMonitor` as a library class in `src/ta_lab2/drift/drift_monitor.py`. Use signal-state matching (not timestamp matching) to compare paper vs backtest trades. Add `drift_paused` field to `dim_risk_state`. Store metrics in `cmc_drift_metrics` table. Use sequential (not simultaneous) attribution decomposition — subtract one cost source at a time in a fixed, documented order.

---

## Standard Stack

### Core (No New Dependencies)

| Library | Version | Purpose | Already Installed |
|---------|---------|---------|------------------|
| `sqlalchemy` | existing | All DB reads/writes, transactions | YES |
| `alembic` | existing | Schema migrations for new tables | YES |
| `numpy` | existing | Rolling tracking error, correlation, Sharpe | YES |
| `pandas` | existing | Time-series alignment, rolling window computation | YES |
| `plotly` | existing | Equity curve overlay, tracking error series, attribution waterfall | YES (Phase 42 bakeoff) |
| `jinja2` | existing | Markdown report template rendering | LIKELY YES (check) |
| `argparse` | stdlib | CLI entry point | YES |
| `dataclasses` | stdlib | `DriftMetrics`, `AttributionResult` data types | YES |
| `decimal` | stdlib | Exact P&L arithmetic | YES |
| `logging` | stdlib | Decision logging | YES |

No new packages required. All infrastructure (alerting, kill switch, backtest results, executor fills) exists.

**Installation check:**
```bash
python -c "import jinja2; print('jinja2 available')"
# If missing: pip install jinja2
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── drift/                               # NEW package for Phase 47
│   ├── __init__.py
│   ├── drift_monitor.py                 # DriftMonitor class -- primary deliverable
│   ├── drift_metrics.py                 # DriftMetrics dataclass + computation
│   ├── attribution.py                   # DriftAttributor: 6-source sequential decomposition
│   └── drift_report.py                  # ReportGenerator: Markdown + Plotly charts

scripts/
└── drift/                               # NEW scripts package
    ├── __init__.py
    ├── run_drift_monitor.py             # CLI: run daily drift check
    └── run_drift_report.py             # CLI: generate weekly drift report

sql/drift/                               # NEW reference DDL
├── 094_cmc_drift_metrics.sql            # Raw drift metrics per strategy per day
└── 095_v_drift_summary.sql             # Materialized view for aggregated trends
```

### Pattern 1: Signal-State Matching (RECOMMENDED for this system)

**What:** Match paper executor trades against backtest trades by joining on the source signal row `(id, ts, signal_id)`, not by aligning fill timestamps. Both the paper executor and the backtester derive trades from the same `cmc_signals_ema_crossover` rows, so matching at the signal source is exact.

**Why this works:** The paper executor sets `executor_processed_at` on each signal row it processes (Phase 45 `mark_signals_processed`). The backtester loads signals via `load_signals_as_series()` which queries the same signal table for the same `(signal_id, asset_id, date_range)`. When the drift monitor runs a backtest replay on the same date range, it will process the same signal rows. The correspondence is 1:1 by signal row identity.

**When to use:** For all V1 EMA strategies (1D cadence, 4 signal paths). This approach is only valid when both systems use the same signal source table — which is true here.

**Matching algorithm:**
```python
# Source: derived from parity_checker.py (Phase 45) + backtest_from_signals.py (Phase 28)

def match_trades_to_signals(
    paper_fills: list[dict],      # from cmc_fills JOIN cmc_orders WHERE signal_id=X
    backtest_trades: list[dict],  # from cmc_backtest_trades JOIN cmc_backtest_runs
    signal_rows: list[dict],      # from cmc_signals_ema_crossover WHERE signal_id=X
) -> list[tuple[dict, dict]]:
    """
    Match paper fills to backtest trades via signal row identity.

    Strategy:
    1. For each signal row (entry_ts, id), find the paper fill at that entry_ts for that asset
    2. Find the backtest trade with matching entry_ts
    3. Return matched pairs; log unmatched entries as attribution gaps

    Why entry_ts matching works:
    - Both vectorbt and executor execute at next_bar_open after the signal ts
    - The signal entry_ts IS the canonical bar timestamp, same for both
    - Exit matching: match by exit_ts (vectorbt chooses same exit bar from same exit signal)
    """
    # Index by (asset_id, entry_ts) -- this is the canonical match key
    paper_index = {
        (f["asset_id"], normalize_ts(f["filled_at"])): f
        for f in paper_fills
    }
    bt_index = {
        (normalize_ts(t["entry_ts"])): t   # backtest doesn't have per-asset key at fill level
        for t in backtest_trades
    }

    matched = []
    for signal in signal_rows:
        asset_id = signal["id"]
        entry_ts = normalize_ts(signal["entry_ts"])
        paper_fill = paper_index.get((asset_id, entry_ts))
        bt_trade = bt_index.get(entry_ts)
        if paper_fill and bt_trade:
            matched.append((paper_fill, bt_trade))
    return matched
```

**Fallback for timestamp drift (alternative):** If exact timestamp matching fails (e.g., timezone handling issues), use a 2-bar window tolerance: match fills within +-2 calendar days of the signal timestamp. For 1D strategies, this handles any timezone normalization edge cases. This is the "time-window tolerance" approach from the context's options list — it should only be needed as a fallback.

### Pattern 2: Kill Switch Integration (Graduated / Tiered)

**Decision:** Three tiers that reuse Phase 46 infrastructure with a minimal extension.

**Tier 1 (MONITOR):** Tracking error between 75% and 100% of threshold (i.e., > 1.125% and <= 1.5%).
- Action: Log to `cmc_drift_metrics`, send Telegram WARNING severity.
- No trading impact.

**Tier 2 (PAUSE):** Tracking error > threshold for the first time.
- Action: Set `drift_paused = TRUE` in `dim_risk_state`. The executor checks this flag at startup and skips order generation (like kill switch, but positions are NOT cancelled). Send Telegram CRITICAL. Log to `cmc_risk_events` with `event_type = 'drift_pause_activated'`.
- Preserves existing open positions (paper trading — no need to flatten).
- Manual resume required: set `drift_paused = FALSE` via CLI.

**Tier 3 (ESCALATE):** If drift_paused is ignored for > 7 days (configurable), escalate to full kill switch.
- Action: Call Phase 46's `activate_kill_switch(engine, reason, trigger_source="drift_escalation")`.
- Same as kill switch activated by daily loss stop.

**Why NOT unified kill switch for initial trigger:** The existing kill switch in Phase 46 is designed for emergency halts (daily loss exceeded, circuit breaker). Drift is a monitoring concern, not an emergency. Introducing a softer `drift_paused` state allows the operator to acknowledge the drift, investigate, and re-enable without the full reset ceremony of a kill switch. Mixing drift pause and emergency halt in a single state creates ambiguity about the root cause.

**Why NOT a completely separate system:** The `dim_risk_state` and `cmc_risk_events` tables already exist and are the canonical record of trading system state. Extending `dim_risk_state` with a `drift_paused` BOOLEAN is minimal and keeps all system state in one place.

**Schema extension for dim_risk_state:**
```sql
-- Extend existing dim_risk_state (already created in Phase 46)
ALTER TABLE public.dim_risk_state
    ADD COLUMN IF NOT EXISTS drift_paused          BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS drift_paused_at       TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS drift_paused_reason   TEXT NULL,
    ADD COLUMN IF NOT EXISTS drift_auto_escalate_after_days INTEGER NOT NULL DEFAULT 7;

-- Extend cmc_risk_events allowed event_type CHECK constraint
-- (See pitfall section -- CHECK constraints require DROP + ADD on Postgres)
-- New event types to add: 'drift_pause_activated', 'drift_pause_disabled', 'drift_escalated'
```

**Executor check (add to start of PaperExecutor._run_strategy):**
```python
# Source: matches kill switch check pattern from Phase 46 RiskEngine._is_halted()

def _is_drift_paused(self, conn) -> bool:
    """Check drift_paused flag alongside kill switch at executor startup."""
    row = conn.execute(text("""
        SELECT trading_state, drift_paused
        FROM public.dim_risk_state
        WHERE state_id = 1
    """)).fetchone()
    if row is None:
        return False
    return row.trading_state == 'halted' or bool(row.drift_paused)
```

### Pattern 3: Daily Backtest Replay

**What:** After each executor cycle, run the backtester on the same signals for the full cumulative window (day 1 of paper trading through today). This is the DRIFT-01 parallel backtest runner.

**Data windows (two layers per CONTEXT.md decision):**
1. **Point-in-time (PIT) replay:** Use only price bars and features that existed at executor run time (captured via snapshot). Isolates execution drift.
2. **Current data replay:** Use today's latest bars and features. Gap between PIT and current quantifies data revision drift.

**Why cumulative (not incremental):** Rolling P&L drift compounds. A 1-day blip looks small; a cumulative 30-day drift that's been growing slowly is the real signal. Cumulative replay catches this. For 2 assets x 2 strategies at 1D cadence, a full cumulative replay from day 1 runs in ~1-5 minutes.

**Replay uses existing SignalBacktester (Phase 28):**
```python
# Source: backtest_from_signals.py SignalBacktester.run_backtest()

def run_pit_replay(
    engine: Engine,
    config: ExecutorConfig,
    paper_start_date: str,
    today: str,
    pit_snapshot_ts: datetime,  # latest bar ts visible at executor run time
) -> BacktestResult:
    """
    Run backtest replay for PIT comparison.

    Uses existing SignalBacktester -- cost_model forced to match executor's
    fill_price_mode (same fill_price_mode = executor's slippage_mode).
    """
    from ta_lab2.backtests.backtest_from_signals import SignalBacktester
    from ta_lab2.backtests.costs import CostModel

    # Force same cost model as paper executor for apples-to-apples comparison
    cost = CostModel(
        fee_bps=config.fee_bps,
        slippage_bps=config.slippage_base_bps if config.slippage_mode == "fixed" else 0,
        funding_bps_day=0,
    )

    backtester = SignalBacktester(engine=engine, cost_model=cost)
    return backtester.run_backtest(
        signal_type=config.signal_type,
        signal_id=config.signal_id,
        asset_id=config.asset_id,
        start_ts=pd.Timestamp(paper_start_date, tz="UTC"),
        end_ts=pd.Timestamp(today, tz="UTC"),
    )
```

### Pattern 4: Drift Metrics Computation

**Metrics per strategy per day (written to cmc_drift_metrics):**

```python
# Source: parity_checker.py _compute_pnl_correlation + Phase 45 research

@dataclass
class DriftMetrics:
    """Daily drift metrics for one strategy on one asset."""
    metric_date: date
    config_id: int
    asset_id: int
    signal_type: str

    # Per-signal comparison
    paper_trade_count: int
    replay_trade_count: int
    unmatched_paper_fills: int
    unmatched_replay_trades: int

    # P&L comparison (cumulative from paper start through metric_date)
    paper_cumulative_pnl: float      # from cmc_fills aggregation
    replay_pit_cumulative_pnl: float  # from PIT replay backtest
    replay_current_cumulative_pnl: float  # from current-data replay
    absolute_pnl_diff: float         # abs(paper - replay_pit)

    # Rolling tracking error (5-day default, configurable)
    tracking_error_5d: float | None   # std(paper_daily_pnl - replay_daily_pnl), rolling 5-day
    tracking_error_30d: float | None  # rolling 30-day (context window)

    # Sharpe divergence
    paper_sharpe: float | None
    replay_sharpe: float | None
    sharpe_divergence: float | None   # abs(paper_sharpe - replay_sharpe)

    # Auto-pause trigger
    threshold_breach: bool            # tracking_error_5d > limit
    drift_pct_of_threshold: float     # tracking_error_5d / threshold * 100
```

**Tracking error formula:**
```python
import numpy as np

def compute_rolling_tracking_error(
    paper_daily_pnl: np.ndarray,   # daily P&L from cmc_fills
    replay_daily_pnl: np.ndarray,  # daily P&L from replay backtest
    window: int = 5,               # configurable, 5 per DRIFT-03
) -> np.ndarray:
    """
    Rolling tracking error = rolling std(paper_pnl - replay_pnl).

    Expressed as percentage of portfolio value to make it threshold-comparable.
    Note: for small windows (5 days), this is a noisy estimate.
    Use 30-day for trend, 5-day for breach detection.
    """
    diff = paper_daily_pnl - replay_daily_pnl
    # pandas rolling std (ddof=1) over the window
    return pd.Series(diff).rolling(window=window, min_periods=window).std().values
```

### Pattern 5: Point-in-Time Snapshot

**What to capture in the executor run snapshot:** At each executor run, record the state of input data that was visible. This enables faithful PIT replay: the drift monitor can re-run the backtest restricted to bars and features with `ts <= snapshot_bar_ts[asset_id]`.

**Recommended snapshot structure (extend cmc_executor_run_log):**
```sql
-- Extend cmc_executor_run_log with data snapshot columns
ALTER TABLE public.cmc_executor_run_log
    ADD COLUMN IF NOT EXISTS data_snapshot JSONB NULL;
    -- Format: {"asset_id": {"latest_bar_ts": "2025-01-15T00:00:00Z",
    --                        "latest_feature_ts": "2025-01-15T00:00:00Z",
    --                        "ema_latest_ts": "2025-01-15T00:00:00Z"}}
```

**What to snapshot (minimum viable for PIT replay):**
1. `latest_bar_ts` per asset_id: MAX(ts) from `cmc_price_bars_multi_tf` WHERE tf='1D' at run time
2. `latest_feature_ts` per asset_id: MAX(ts) from `cmc_features` WHERE tf='1D' at run time
3. `ema_latest_ts` per asset_id: MAX(ts) from `cmc_ema_multi_tf_u` WHERE tf='1D' at run time
4. `signal_latest_ts` per asset_id: MAX(ts) from the signal table for the strategy at run time

**Why this is sufficient:** The price bars and features for 1D strategies have `ts` as the canonical bar date. If a bar was revised after the executor ran (e.g., OHLCV update due to exchange correction), the PIT replay can filter `WHERE ts <= snapshot_bar_ts` to reconstruct what was visible. Data revisions in daily crypto bars are rare but do happen (exchange corrections up to 0.01%).

**Snapshot collection code:**
```python
# Source: pattern matches run_daily_refresh.py component data collection

def collect_data_snapshot(conn, asset_ids: list[int]) -> dict:
    """Collect latest bar/feature timestamps per asset for PIT tracking."""
    snapshot = {}
    for asset_id in asset_ids:
        row = conn.execute(text("""
            SELECT
                (SELECT MAX(ts) FROM cmc_price_bars_multi_tf WHERE id = :asset_id AND tf = '1D') AS bar_ts,
                (SELECT MAX(ts) FROM cmc_features WHERE id = :asset_id AND tf = '1D') AS feature_ts,
                (SELECT MAX(ts) FROM cmc_ema_multi_tf_u WHERE id = :asset_id AND tf = '1D') AS ema_ts
        """), {"asset_id": asset_id}).fetchone()
        snapshot[str(asset_id)] = {
            "latest_bar_ts": row.bar_ts.isoformat() if row.bar_ts else None,
            "latest_feature_ts": row.feature_ts.isoformat() if row.feature_ts else None,
            "ema_latest_ts": row.ema_ts.isoformat() if row.ema_ts else None,
        }
    return snapshot
```

### Pattern 6: Attribution Decomposition (Sequential, Fixed Order)

**Decision: Sequential (one-at-a-time), fixed order.** Rationale: The theoretically superior method (Average Sequential Updating / Shapley value decomposition) requires running 2^N replay simulations (N = number of attribution dimensions). For 6 dimensions that is 64 replays. For V1 with 4 signal paths at ~1-5 min per replay, this is 64-320 minutes — impractical daily. Sequential OAT (one-at-a-time) is fast (N+1 = 7 replays) and is standard in practice for implementation cost analysis. The order dependency is documented and fixed, which is honest about the limitation.

**Fixed decomposition order (matches independence hierarchy):**
1. **Baseline:** Full backtest replay with zero slippage and zero fees (clean signal P&L)
2. **Step 1: +Fee model delta** — Add backtest fees back. Delta = effect of fee model assumptions.
3. **Step 2: +Slippage delta** — Add realistic slippage to backtest. Delta = slippage simulation vs paper fill prices.
4. **Step 3: +Signal timing delta** — Use exact paper execution timestamps (day of fill) vs next-bar-open. Delta = timing/delay effect.
5. **Step 4: +Data revision delta** — Switch from PIT data to current data replay. Delta = what data revisions contributed.
6. **Step 5: +Position sizing drift** — Account for quantity rounding differences between executor and backtester (fractional shares, min order thresholds). Delta = sizing precision effect.
7. **Step 6: +Regime context delta** — Compare signals generated with vs without regime filtering. Delta = regime label changes between execution and replay time.

**Residual = paper_pnl - (baseline + sum of all deltas).** A non-zero residual means an unexplained source. Log residual as `unexplained_pnl` in `cmc_drift_metrics`.

**Implementation note:** For V1 (2 strategies, 2 assets, 1D, short paper trading history), steps 4-6 will often be zero or near-zero. The framework is built correctly so it can grow. Steps 1-3 (fees, slippage, timing) are the primary sources of expected drift.

```python
# Source: pattern derived from backtest_from_signals.py cost model switching

@dataclass
class AttributionResult:
    """Sequential attribution decomposition result."""
    baseline_pnl: float           # zero fees + zero slippage
    fee_delta: float              # step 1: fee model contribution
    slippage_delta: float         # step 2: slippage contribution
    timing_delta: float           # step 3: execution timing contribution
    data_revision_delta: float    # step 4: data revision contribution
    sizing_delta: float           # step 5: position sizing rounding
    regime_delta: float           # step 6: regime label at replay vs execution
    unexplained_residual: float   # paper_pnl - (baseline + all deltas)
    total_explained_pnl: float    # baseline + sum(deltas)
    paper_pnl: float              # actual paper executor P&L
```

### Anti-Patterns to Avoid

- **Timestamp-first matching:** Never match paper fills to backtest trades by fill timestamp as the primary key. Fill timestamps can differ by microseconds due to how vectorbt and the executor both shift signals by 1 bar. Signal-source matching (by signal row identity) is the correct approach.
- **Re-running fresh backtests without signal freeze:** The drift monitor's replay must use the same signal rows that existed when paper trading occurred. If signals are regenerated (e.g., re-run of signal refresher), the replay must still use the original signal values. Signals should be immutable once processed by the executor. (This is guaranteed by the existing `executor_processed_at` watermark system — processed signals are not re-generated.)
- **Materialized view with blocking refresh:** Use `REFRESH MATERIALIZED VIEW CONCURRENTLY` for `v_drift_summary`. Blocking refresh locks the view and prevents Phase 52 dashboard from querying during refresh. CONCURRENTLY requires a unique index on the view.
- **Mixing drift-pause and emergency kill switch state:** Drift pause is a monitoring response; kill switch is an emergency halt. Keep them as separate flags in `dim_risk_state`. Combining them creates diagnostic ambiguity (operator can't tell if system is paused for drift vs actual loss stop).
- **Fixed attribution order without documentation:** Sequential decomposition order is arbitrary and affects the size of each component (interaction effects absorbed differently by each ordering). Document the chosen order clearly. Never change the order without re-running historical attribution.

---

## Recommended DDL Schemas

### cmc_drift_metrics (raw daily drift measurements)

```sql
-- sql/drift/094_cmc_drift_metrics.sql
-- One row per (metric_date, config_id, asset_id) per day.
-- Written by drift monitor after daily replay.

CREATE TABLE IF NOT EXISTS public.cmc_drift_metrics (
    metric_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_date         DATE        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Scope
    config_id           INTEGER     NOT NULL,  -- FK to dim_executor_config
    asset_id            INTEGER     NOT NULL,  -- Asset tracked
    signal_type         TEXT        NOT NULL,  -- 'ema_crossover' | etc.

    -- Backtest replay references
    pit_replay_run_id   UUID        NULL,      -- FK to cmc_backtest_runs (PIT replay)
    cur_replay_run_id   UUID        NULL,      -- FK to cmc_backtest_runs (current data replay)

    -- Trade count comparison
    paper_trade_count   INTEGER     NOT NULL DEFAULT 0,
    replay_trade_count  INTEGER     NOT NULL DEFAULT 0,
    unmatched_paper     INTEGER     NOT NULL DEFAULT 0,
    unmatched_replay    INTEGER     NOT NULL DEFAULT 0,

    -- Cumulative P&L (from paper start through metric_date)
    paper_cumulative_pnl        NUMERIC     NULL,
    replay_pit_cumulative_pnl   NUMERIC     NULL,
    replay_cur_cumulative_pnl   NUMERIC     NULL,
    absolute_pnl_diff           NUMERIC     NULL,  -- abs(paper - replay_pit)
    data_revision_pnl_diff      NUMERIC     NULL,  -- abs(replay_pit - replay_cur)

    -- Rolling tracking error
    tracking_error_5d   NUMERIC     NULL,  -- rolling 5-day window, % of portfolio
    tracking_error_30d  NUMERIC     NULL,  -- rolling 30-day window, % of portfolio

    -- Sharpe divergence
    paper_sharpe        NUMERIC     NULL,
    replay_sharpe       NUMERIC     NULL,
    sharpe_divergence   NUMERIC     NULL,

    -- Threshold status
    threshold_breach    BOOLEAN     NOT NULL DEFAULT FALSE,
    drift_pct_of_threshold NUMERIC NULL,   -- tracking_error_5d / threshold * 100

    -- Attribution decomposition (all NULLable; populated by weekly report run)
    attr_baseline_pnl       NUMERIC NULL,
    attr_fee_delta          NUMERIC NULL,
    attr_slippage_delta     NUMERIC NULL,
    attr_timing_delta       NUMERIC NULL,
    attr_data_revision_delta NUMERIC NULL,
    attr_sizing_delta       NUMERIC NULL,
    attr_regime_delta       NUMERIC NULL,
    attr_unexplained        NUMERIC NULL,

    -- Composite uniqueness: one row per (date, config, asset)
    CONSTRAINT uq_drift_metrics_scope UNIQUE (metric_date, config_id, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_drift_metrics_date
    ON public.cmc_drift_metrics (metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_drift_metrics_config
    ON public.cmc_drift_metrics (config_id, metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_drift_metrics_breach
    ON public.cmc_drift_metrics (threshold_breach, metric_date DESC)
    WHERE threshold_breach = TRUE;
```

### v_drift_summary (materialized view for trend analysis)

```sql
-- sql/drift/095_v_drift_summary.sql
-- Aggregated drift trends for dashboard (Phase 52) and report generation.
-- Refreshed daily after drift monitor writes new metrics.

CREATE MATERIALIZED VIEW IF NOT EXISTS public.v_drift_summary AS
SELECT
    config_id,
    asset_id,
    signal_type,
    COUNT(*)                              AS days_monitored,
    COUNT(*) FILTER (WHERE threshold_breach)  AS breach_count,
    ROUND(AVG(tracking_error_5d)::NUMERIC, 4) AS avg_tracking_error_5d,
    ROUND(MAX(tracking_error_5d)::NUMERIC, 4) AS max_tracking_error_5d,
    ROUND(AVG(absolute_pnl_diff)::NUMERIC, 2) AS avg_absolute_pnl_diff,
    ROUND(AVG(sharpe_divergence)::NUMERIC, 4)  AS avg_sharpe_divergence,
    MAX(metric_date)                      AS last_metric_date,

    -- Latest day metrics for dashboard
    MAX(tracking_error_5d) FILTER (
        WHERE metric_date = (
            SELECT MAX(metric_date) FROM cmc_drift_metrics dm2
            WHERE dm2.config_id = dm.config_id AND dm2.asset_id = dm.asset_id
        )
    ) AS current_tracking_error_5d

FROM public.cmc_drift_metrics dm
GROUP BY config_id, asset_id, signal_type;

-- Required for REFRESH CONCURRENTLY (needs unique index)
CREATE UNIQUE INDEX IF NOT EXISTS uq_drift_summary
    ON public.v_drift_summary (config_id, asset_id);
```

**Refresh pattern (called after drift monitor writes metrics):**
```sql
-- Refresh concurrently to avoid locking Phase 52 dashboard reads
REFRESH MATERIALIZED VIEW CONCURRENTLY public.v_drift_summary;
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Backtest replay | Custom vectorbt runner | `SignalBacktester.run_backtest()` (Phase 28) | Full implementation exists; handles cost model, vectorbt version compat, trade extraction |
| Trade-level P&L extraction | Custom P&L accumulator | `cmc_backtest_trades` from replay run | Phase 28 already extracts all trade records; drift monitor queries them |
| Executor fill aggregation | Custom aggregation query | `cmc_fills JOIN cmc_orders` (Phase 44/45 schema) | Fill records are atomic, already stored with `signal_id` FK |
| Kill switch trigger | Custom halt mechanism | `activate_kill_switch()` (Phase 46) | Already handles atomic state flip, order cancel, Telegram alert in one call |
| Telegram alerting | Custom HTTP client | `send_critical_alert()`, `send_warning_alert()` (Phase 29) | Already implemented, handles missing config gracefully |
| Rolling std computation | Explicit loop | `pd.Series.rolling(window).std()` | Vectorized, handles NaN for min_periods, no bugs |
| Report file naming | Ad hoc string formatting | Pattern from Phase 42 bakeoff: `reports/drift/drift_report_YYYY-MM-DD.md` | Consistent with existing report directory convention |
| Signal matching state reconciliation | Custom state machine | Signal-source matching via `(id, ts, signal_id)` | All the state is already in the signal table rows; no separate reconciliation needed |

**Key insight:** Drift monitoring in this system is simpler than in general algo trading platforms because both the backtester and the paper executor use identical signal source tables. The hard matching problem (reconciling timestamps across different execution engines) doesn't exist here.

---

## Common Pitfalls

### Pitfall 1: CHECK Constraint Prevents Adding New Risk Event Types
**What goes wrong:** `cmc_risk_events.event_type` has a CHECK constraint listing all valid event types. Adding `'drift_pause_activated'` requires modifying the constraint, which means DROP + ADD (not ALTER) in PostgreSQL.
**Why it happens:** PostgreSQL CHECK constraints cannot be modified in place.
**How to avoid:** Migration must: (1) DROP CONSTRAINT `chk_risk_events_type`, (2) ADD CONSTRAINT with new list including `drift_pause_activated`, `drift_pause_disabled`, `drift_escalated`. Must be in single transaction.
**Warning signs:** `ERROR: new row for relation "cmc_risk_events" violates check constraint "chk_risk_events_type"` when inserting drift events.

```sql
-- Correct migration pattern for extending CHECK constraints
ALTER TABLE public.cmc_risk_events
    DROP CONSTRAINT chk_risk_events_type;

ALTER TABLE public.cmc_risk_events
    ADD CONSTRAINT chk_risk_events_type CHECK (
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
            'override_reverted',
            -- Phase 47 additions:
            'drift_pause_activated',
            'drift_pause_disabled',
            'drift_escalated'
        )
    );
```

### Pitfall 2: Replay Backtest Uses Latest Signal Data (Not PIT)
**What goes wrong:** The drift monitor runs a backtest replay. Since the executor ran, the signal refresher has re-run and updated `cmc_signals_ema_crossover`. The replay now uses slightly different signal values than what the executor saw (signal values can change if the underlying feature computation changes). The drift appears large but is just due to signal regeneration, not execution drift.
**Why it happens:** `cmc_signals_ema_crossover` rows are updated in-place via `ON CONFLICT DO UPDATE` by the signal refresher.
**How to avoid:** The signal table has `executor_processed_at` marking which rows were executed. Replay must filter `WHERE executor_processed_at IS NOT NULL` (use only signals the executor already saw) to get PIT signal state. Current-data replay can use all signals.
**Warning signs:** Drift metrics show large jump the day after signal refresh, then return to normal.

### Pitfall 3: Tracking Error Denominator = 0 (No Positions)
**What goes wrong:** If paper trading just started (few fills), `paper_daily_pnl` and `replay_daily_pnl` are both zero for most days. Rolling std of zeros = 0. Tracking error shows 0%, appears fine. Then first real fills arrive and tracking error spikes from 0 to 3% in one day.
**Why it happens:** Rolling window requires `min_periods` matching window size. With only 2 fills in 30 days, most days have zero P&L and the rolling std is near zero.
**How to avoid:** Set `tracking_error_5d = NULL` when fewer than `window` trading days have fills. Check `paper_trade_count >= window` before reporting tracking error. Log count of active trading days in `cmc_drift_metrics`.
**Warning signs:** Tracking error reported as 0% for weeks, then spikes on first real trade.

### Pitfall 4: Backtest Replay Produces Different Trade Count Than Historical Backtest
**What goes wrong:** The drift monitor runs a replay backtest and gets 8 trades; the stored `cmc_backtest_trades` for the same signal/period has 11 trades. They don't match even in zero-slippage mode.
**Why it happens:** Signal tables may have been extended by the signal refresher since the original backtest was run. New signals (for dates after the original backtest end) are in the table. The replay query `WHERE entry_ts <= end_ts` may pick up different rows than the original.
**How to avoid:** Replay must use the SAME `signal_id` and SAME date range as the original backtest run. The backtest `cmc_backtest_runs.start_ts / end_ts` defines the canonical date range. Always query replay signals with `WHERE executor_processed_at IS NOT NULL` (signals the executor actually saw).
**Warning signs:** Replay trade count consistently higher than paper executor fill count for the same date range.

### Pitfall 5: Windows cp1252 Encoding When Opening SQL Attribution Files
**What goes wrong:** Attribution SQL files with UTF-8 characters (em dashes in comments) fail to open with `UnicodeDecodeError` on Windows.
**Why it happens:** Per project MEMORY.md: "Always use `encoding='utf-8'` when opening SQL files on Windows."
**How to avoid:** All file reads in drift module must use `open(path, encoding='utf-8')`. All SQL file comments must use ASCII only. No em dashes, no box-drawing chars.

### Pitfall 6: Materialized View Refresh Blocks Dashboard During Peak Hours
**What goes wrong:** `REFRESH MATERIALIZED VIEW v_drift_summary` (without CONCURRENTLY) takes an exclusive lock. Phase 52 dashboard queries are blocked for 2-10 seconds.
**Why it happens:** Default non-concurrent refresh holds ExclusiveLock.
**How to avoid:** Always use `REFRESH MATERIALIZED VIEW CONCURRENTLY`. Requires unique index (already specified in DDL above). If the view is newly created (no data yet), first refresh must be non-concurrent (CONCURRENTLY fails on empty view).
**Warning signs:** Dashboard timeouts after drift monitor runs.

### Pitfall 7: Drift Attribution Running on Insufficient History
**What goes wrong:** The weekly attribution report runs after only 3 days of paper trading. With 4 signal paths (2 strategies x 2 assets) at 1D cadence, 3 days = at most 4-8 fills total. Attribution decomposition over 3 fills is statistically meaningless.
**Why it happens:** The weekly report job has no guard for minimum history requirement.
**How to avoid:** Add guard: `if paper_trade_count < 10: skip attribution, log "Insufficient trade history (N={n}, minimum=10)"`. For the weekly report, require at least 2 calendar weeks of paper trading before running attribution.

---

## Code Examples

### Drift Monitor Main Loop

```python
# Source: pattern from run_daily_refresh.py component pattern + Phase 46 risk engine structure

class DriftMonitor:
    """
    Daily drift comparison between paper executor and backtest replay.

    Usage (called from run_drift_monitor.py after executor cycle):
        monitor = DriftMonitor(engine)
        results = monitor.run(paper_start_date='2025-01-01')
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._backtester = SignalBacktester(
            engine=engine,
            cost_model=CostModel()  # cost model overridden per strategy
        )

    def run(self, paper_start_date: str) -> list[DriftMetrics]:
        """Run daily drift check for all active strategies."""
        today = datetime.now(timezone.utc).date().isoformat()
        configs = self._load_active_executor_configs()
        results = []

        for config in configs:
            try:
                metrics = self._check_strategy_drift(config, paper_start_date, today)
                self._write_metrics(metrics)
                if metrics.threshold_breach:
                    self._trigger_pause(metrics)
                results.append(metrics)
            except Exception as exc:
                logger.exception("DriftMonitor failed for config=%s", config.config_id)

        self._refresh_summary_view()
        return results

    def _check_strategy_drift(
        self,
        config: ExecutorConfig,
        paper_start: str,
        today: str,
    ) -> DriftMetrics:
        """
        Run replay and compute drift metrics for one strategy/asset pair.
        """
        # 1. Run PIT replay (with same cost model as paper executor)
        pit_result = self._run_pit_replay(config, paper_start, today)

        # 2. Run current-data replay (same but no PIT filter)
        cur_result = self._run_current_replay(config, paper_start, today)

        # 3. Load paper fills (from cmc_fills)
        paper_fills = self._load_paper_fills(config, paper_start, today)

        # 4. Compute drift metrics
        return compute_drift_metrics(
            config=config,
            metric_date=today,
            paper_fills=paper_fills,
            pit_replay=pit_result,
            cur_replay=cur_result,
        )
```

### Drift Pause Activation

```python
# Source: mirrors activate_kill_switch() pattern from Phase 46 kill_switch.py

def activate_drift_pause(
    engine: Engine,
    reason: str,
    tracking_error: float,
    config_id: int,
) -> None:
    """Activate drift pause -- softer than kill switch, does NOT cancel orders."""
    with engine.begin() as conn:
        # 1. Set drift_paused flag
        conn.execute(text("""
            UPDATE public.dim_risk_state
            SET drift_paused = TRUE,
                drift_paused_at = now(),
                drift_paused_reason = :reason,
                updated_at = now()
            WHERE state_id = 1
        """), {"reason": reason})

        # 2. Write audit event to cmc_risk_events
        conn.execute(text("""
            INSERT INTO public.cmc_risk_events
            (event_type, trigger_source, reason, metadata)
            VALUES ('drift_pause_activated', 'drift_monitor', :reason, :metadata)
        """), {
            "reason": reason,
            "metadata": json.dumps({
                "tracking_error_pct": round(tracking_error, 4),
                "config_id": config_id,
            })
        })

    # 3. Telegram CRITICAL alert (outside transaction)
    send_critical_alert(
        "drift_pause",
        f"Drift pause activated: {reason} (tracking error = {tracking_error:.2%})",
        {"config_id": config_id, "tracking_error": tracking_error},
    )
```

### Tracking Error Threshold Check

```python
# Source: pattern from Phase 46 daily_loss_stop check

def check_drift_threshold(
    engine: Engine,
    metrics: DriftMetrics,
) -> bool:
    """
    Returns True if drift threshold is breached. Activates pause if so.
    Sends Telegram WARNING if approaching (>75% of threshold).
    """
    # Load threshold from dim_risk_limits (hot-reload pattern)
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
                COALESCE(
                    (SELECT limit_value FROM dim_risk_limits
                     WHERE limit_name = 'drift_tracking_error_threshold'),
                    0.015  -- default 1.5% per DRIFT-03
                ) AS threshold,
                COALESCE(
                    (SELECT limit_value FROM dim_risk_limits
                     WHERE limit_name = 'drift_window_days'),
                    5.0    -- default 5 days per DRIFT-03
                ) AS window_days
        """)).fetchone()

    threshold = float(row.threshold)
    te = metrics.tracking_error_5d

    if te is None:
        return False  # Insufficient history -- skip check

    # Tier 1: WARNING at 75% of threshold
    if te > threshold * 0.75:
        send_warning_alert(
            "drift_approaching",
            f"Drift approaching threshold: TE={te:.2%} ({te/threshold*100:.0f}% of {threshold:.2%} limit)",
            {"config_id": metrics.config_id, "asset_id": metrics.asset_id},
        )

    # Tier 2: PAUSE at 100% of threshold
    if te > threshold:
        activate_drift_pause(
            engine,
            reason=f"5-day tracking error {te:.2%} exceeds threshold {threshold:.2%}",
            tracking_error=te,
            config_id=metrics.config_id,
        )
        return True

    return False
```

### Weekly Report Structure

```python
# Source: pattern from Phase 42 bakeoff report generator

def generate_weekly_drift_report(
    engine: Engine,
    output_dir: str = "reports/drift",
) -> str:
    """
    Generate weekly drift attribution report as Markdown + Plotly HTML.

    Returns path to generated .md report file.
    """
    week_end = datetime.now(timezone.utc).date()
    week_start = week_end - timedelta(days=7)
    report_path = f"{output_dir}/drift_report_{week_end.isoformat()}.md"

    # Load this week's drift metrics
    metrics_df = _load_drift_metrics_df(engine, week_start, week_end)

    # Generate Plotly charts
    equity_chart = _plot_equity_curve_overlay(metrics_df)    # paper vs replay P&L
    tracking_chart = _plot_tracking_error_series(metrics_df)  # TE over time
    waterfall_chart = _plot_attribution_waterfall(metrics_df) # 6-source decomposition

    # Save charts as HTML
    charts_dir = f"{output_dir}/charts_{week_end.isoformat()}"
    os.makedirs(charts_dir, exist_ok=True)
    equity_chart.write_html(f"{charts_dir}/equity_overlay.html")
    tracking_chart.write_html(f"{charts_dir}/tracking_error.html")
    waterfall_chart.write_html(f"{charts_dir}/attribution_waterfall.html")

    # Render Markdown report using template
    report_md = _render_report_template(metrics_df, week_start, week_end, charts_dir)

    os.makedirs(output_dir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return report_path
```

---

## Tracking Error Threshold Analysis

### Is 5-day window, 1.5% tracking error defensible?

**Research finding (MEDIUM confidence):** No industry-specific standard for crypto daily strategy tracking error was found. The 1.5% threshold must be calibrated relative to the strategy's own volatility.

**Calibration for V1 system:**
- V1 EMA strategies: typical daily P&L vol ~1-3% (crypto 1D strategy at 10% position fraction)
- Rolling 5-day std of (paper_pnl - replay_pnl) for a strategy with no structural drift should be near 0% (both use same signals, same fill prices after rounding)
- With lognormal slippage (sigma=0.5, base=3bps), expected per-fill divergence: 1-5 bps per fill
- For a 5-day window with ~1 fill every 5-10 days (1D trend following trades infrequently): tracking error is dominated by rare fills, making the 5-day window noisy

**Recommendation:** Keep 1.5% for 5-day tracking error as DRIFT-03 specifies, but also monitor 30-day tracking error as the primary trend indicator. The 5-day window is a trip-wire; the 30-day is the indicator of systematic drift. Store both in `cmc_drift_metrics`. Add a second threshold for the 30-day window (0.5%) to catch slow drift before it trips the 5-day threshold.

**Why 1.5% is reasonable for V1:**
- With 4 signal paths, ~0-2 fills per week expected
- Most weeks: 0 fills -> tracking error = 0% (NaN logged, not a false positive)
- A 5-day tracking error of 1.5% means ~$15 divergence per $1000 portfolio per day — significant enough to indicate systematic mis-modeling
- If slippage model is correct (3 bps base), expected tracking error is < 0.2%; 1.5% is a 7.5x signal

**Both thresholds configurable from `dim_risk_limits`** (per the hot-reload pattern in Phase 46). Do not hardcode.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual weekly equity curve comparison | Automated daily drift metrics | Became standard in systematic funds ~2018 | No more "surprise" divergence discovered at month-end |
| Timestamp-based trade matching | Signal-source-based matching (when same signal table) | This project's architecture advantage | Exact 1:1 correspondence, no tolerance windows needed |
| Unified kill switch for all halt causes | Tiered response (monitor -> pause -> kill) | Emerging best practice 2022+ | Preserves diagnostic information; pause ≠ emergency |
| Brinson equity attribution (sector allocation/selection) | Execution cost decomposition (fees, slippage, timing) | Already standard in TCA (Transaction Cost Analysis) since 2015 | Correctly identifies execution quality as source of drift |
| Sequential OAT decomposition | Shapley value / ASU decomposition | Theoretically superior 2021+ | For V1 (few trades), OAT is adequate; Shapley is deferred |

**Deprecated/outdated:**
- Tracking error computed against external benchmark: For drift monitoring, the "benchmark" is the backtester's own prediction. No external index needed.
- Global fixed threshold regardless of strategy volatility: Should be calibrated per-strategy in production; V1 uses a single configurable threshold as a pragmatic simplification.

---

## Decisions Made (Claude's Discretion)

### Signal Matching Algorithm
**Decision: Signal-source matching (1:1 via signal row identity).**
Both paper executor and backtester query the same `cmc_signals_ema_crossover` rows. Match by `(asset_id, entry_ts)` from the signal table as the canonical key. Fall back to 2-bar time-window tolerance only if exact matching fails. Do NOT use position-state machine matching (too complex for 4 signal paths).

### Kill Switch Integration
**Decision: Tiered graduated response.** Add `drift_paused` BOOLEAN to `dim_risk_state`. Three tiers: WARNING (75% of threshold) -> PAUSE (drift_paused = TRUE, manual resume) -> ESCALATE (call Phase 46 `activate_kill_switch()` after configurable days). This preserves Phase 46's kill switch for its intended purpose (emergency halt) while giving drift monitoring its own softer response.

### Drift Metrics Table DDL
**Decision: `cmc_drift_metrics` with schema as specified above.** One row per (metric_date, config_id, asset_id). Attribution columns nullable (populated only during weekly report). Composite unique constraint prevents duplicate metric ingestion.

### Materialized View
**Decision: `v_drift_summary` as a materialized view.** Refresh with `CONCURRENTLY` after each drift monitor run. Unique index on (config_id, asset_id) required. First refresh must be non-concurrent (view initially empty).

### Tracking Error Thresholds
**Decision: 5-day window = 1.5% (as DRIFT-03 specifies). Add 30-day window = 0.5% as secondary indicator. Both configurable in `dim_risk_limits`.** The 5-day is the breach trigger; the 30-day is the trend monitor. Do not hard-code thresholds.

### Attribution Decomposition Algorithm
**Decision: Sequential OAT (one-at-a-time), fixed order: fees -> slippage -> timing -> data_revision -> sizing -> regime.** Document residual as `unexplained_pnl`. Shapley value decomposition is deferred to future enhancement (too compute-intensive for daily runs with 4 signal paths).

### Report Generation CLI Design
**Decision: Two CLI scripts.** `run_drift_monitor.py` for daily metrics computation (called from `run_daily_refresh.py`); `run_drift_report.py` for weekly report generation with Plotly charts (called manually or from cron). Both accept `--db-url` and `--verbose`. Dry-run mode on drift monitor (skips writes but runs replay). Report output to `reports/drift/` (gitignored).

---

## Open Questions

1. **dim_risk_limits table for drift threshold storage**
   - What we know: Phase 46 created `dim_risk_limits` with columns: `max_position_pct`, `max_portfolio_pct`, `daily_loss_pct_threshold`, `cb_consecutive_losses_n`, etc. It uses a schema with `asset_id` and `strategy_id` scope columns.
   - What's unclear: Does the existing `dim_risk_limits` DDL support arbitrary limit names (e.g., `drift_tracking_error_threshold`) or only the fixed Phase 46 columns? Adding new columns would require a migration. Alternatively, drift-specific thresholds could live in a new `dim_drift_limits` table to avoid touching Phase 46's schema.
   - Recommendation: Add new columns to `dim_risk_limits` via Alembic migration: `drift_tracking_error_threshold_5d NUMERIC NULL`, `drift_tracking_error_threshold_30d NUMERIC NULL`, `drift_window_days INTEGER NULL`. This keeps all thresholds in one hot-reloadable table.

2. **Phase 45 executor run log data_snapshot extension**
   - What we know: `cmc_executor_run_log` exists with `run_id`, `started_at`, `finished_at`, `config_ids`, etc. Adding a `data_snapshot JSONB` column requires migration.
   - What's unclear: Phase 45 plans may or may not have implemented the executor run log extension for data snapshots. The CONTEXT.md says "stored in cmc_executor_run_log or dedicated snapshot structure" — implementation may have chosen a different approach.
   - Recommendation: Phase 47 plan-01 should check current `cmc_executor_run_log` schema and add `data_snapshot` column if not present. If paper trading start date is before Phase 47 is deployed, initial PIT snapshot data will be missing for early dates — use current-data replay only for dates before snapshot column was added.

3. **Plotly availability in project**
   - What we know: Phase 42 bakeoff uses Plotly HTML charts (confirmed in MEMORY.md and bakeoff reports).
   - What's unclear: Whether `plotly` is in `pyproject.toml` as a direct dependency or only as a transitive dependency.
   - Recommendation: Phase 47 plan should verify plotly is available: `python -c "import plotly; print(plotly.__version__)"`. If missing, add to pyproject.toml.

4. **Signal_id tracking in cmc_drift_metrics: strategy granularity**
   - What we know: `dim_executor_config` has `config_id` (unique per strategy configuration) and `signal_id` (links to `dim_signals`).
   - What's unclear: The drift monitor compares per `(config_id, asset_id)`. But the backtester runs per `(signal_id, asset_id)`. These need to be mapped consistently. V1 has 2 executor configs, each with one signal_id, on 2 assets = 4 signal paths.
   - Recommendation: Store `config_id` as the primary scope key in `cmc_drift_metrics` (the executor is the source of truth for paper trading). The replay backtest is looked up via `config.signal_id`. Keep `signal_type` denormalized in the drift metrics table for query convenience.

---

## Sources

### Primary (HIGH confidence)
- Project codebase: `src/ta_lab2/scripts/backtests/backtest_from_signals.py` — `SignalBacktester.run_backtest()`, `load_signals_as_series()`, trade extraction schema
- Project codebase: `src/ta_lab2/executor/parity_checker.py` — existing `ParityChecker`: signal-source matching pattern, tracking_error_pct formula, P&L correlation
- Project codebase: `src/ta_lab2/executor/paper_executor.py` — `PaperExecutor` structure, run log writing, executor config loading
- Project codebase: `src/ta_lab2/executor/signal_reader.py` — `mark_signals_processed()` pattern, `executor_processed_at IS NULL` filter
- Project codebase: `src/ta_lab2/executor/fill_simulator.py` — `FillSimulatorConfig.slippage_mode`, seed-based RNG
- Project codebase: `sql/backtests/070-072_cmc_backtest_*.sql` — confirmed `run_id`, `signal_id`, `entry_ts`, `exit_ts` schema
- Project codebase: `sql/executor/089_cmc_executor_run_log.sql` — confirmed run log schema with no data_snapshot column (needs extension)
- Project codebase: `sql/risk/092_cmc_risk_events.sql` — confirmed CHECK constraint on event_type (needs DROP+ADD for new types)
- `.planning/phases/46-risk-controls/46-RESEARCH.md` — Phase 46 `activate_kill_switch()` API, `dim_risk_state` schema, `dim_risk_limits` schema
- `.planning/phases/45-paper-trade-executor/45-RESEARCH.md` — `ExecutorConfig` fields, fill simulation, parity checker architecture
- PostgreSQL official docs — REFRESH MATERIALIZED VIEW CONCURRENTLY requirements, unique index necessity

### Secondary (MEDIUM confidence)
- QuantConnect reconciliation docs: https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/reconciliation — OOS backtest parallel comparison approach, 4 divergence source categories
- Portfolio Optimizer blog: https://portfoliooptimizer.io/blog/trading-strategy-monitoring-modeling-the-pnl-as-a-geometric-brownian-motion/ — Probabilistic monitoring approach (normalized drawdown depth vs GBM confidence interval)
- WebSearch: "live vs backtest performance monitoring" — StrategyQuant: "if real performance is 30% of backtest, investigate"; general threshold guidance
- arxiv P&L decomposition papers: "Profit and loss decomposition in continuous time" — ASU/Shapley vs OAT comparison, order-dependency of sequential approaches

### Tertiary (LOW confidence)
- WebSearch: "tracking error threshold crypto 1.5% 5-day" — no specific industry standard found; 1.5% assessment is based on strategy volatility calibration reasoning, not published benchmarks
- WebSearch: "drift graduated response kill switch algo trading 2025" — general references to FSI AI kill switch debates; no specific standard for drift-vs-emergency differentiation
- FMSB Model Risk paper (2025): general model risk governance framework; not crypto-specific

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; all libraries exist in project
- Signal matching algorithm: HIGH — signal-source matching is a direct consequence of the system's architecture (same signal tables for both sides); confirmed by examining actual Phase 45 and 28 code
- Kill switch integration (tiered): HIGH — Phase 46 `dim_risk_state` + `cmc_risk_events` schemas confirmed; extension is minimal (one BOOLEAN column); pattern matches existing kill switch code exactly
- DDL schema design: HIGH — follows exact patterns of existing Phase 44/45/46 schemas; reviewed actual SQL files
- Tracking error formula: HIGH — pd.Series.rolling(window).std() is standard; formula matches parity_checker.py existing `tracking_error_pct`
- Tracking error thresholds (1.5%, 5-day): MEDIUM — defensible but not calibrated against real fills; no published standard for crypto drift monitoring; both thresholds made configurable
- Attribution decomposition (sequential OAT): MEDIUM — mathematically correct for fixed-order documentation; theoretically inferior to Shapley (ASU) but practical for V1; order documented
- Point-in-time snapshot design: MEDIUM — standard data versioning practice; specific columns (bar_ts, feature_ts, ema_ts) are project-specific and not verified against actual data revision frequency in crypto bars
- Jinja2 availability: LOW — used in Phase 42 bakeoff likely, but not verified from pyproject.toml

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (30 days; stable domain — drift monitoring patterns change slowly; re-verify if Phase 45 or 46 implementations deviate from their plans)
