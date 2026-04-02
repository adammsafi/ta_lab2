# Pipeline Contracts

> Satisfies PIPE-04: Pipeline handoff contracts documented.
>
> Last updated: 2026-04-02 (Phase 112)

---

## Overview

ta_lab2 runs five independent pipelines. Three execute locally on the developer machine
(Data, Features, Signals). Two run on the Oracle Singapore VM (Execution, Monitoring).
Signals are pushed from local to VM via SSH+psql COPY after each Signals run.

```
LOCAL MACHINE                          ORACLE VM (161.118.209.59)
─────────────────────────────────────  ─────────────────────────────────────
Data Pipeline                          Execution Pipeline  (polling loop)
   │                                       │
   ↓ (bars, returns_bars)                  │ reads signals_* from VM DB
Features Pipeline                      Monitoring Pipeline (external timer)
   │                                       │
   ↓ (features, regimes, ema/ama)          │ reads pipeline_run_log, drift_metrics
Signals Pipeline
   │
   ↓ (signals_*, portfolio_allocations)
sync_signals_to_vm ─────────────────→  VM DB (hyperliquid)
```

`run_full_chain.py` is the recommended daily driver. It calls Data → Features →
Signals → sync_signals_to_vm in subprocess sequence. Each pipeline is independently
invocable; the chain is additive, not required.

---

## 1. Data Pipeline

**Entry point:**
```
python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all
```

**Stages (in order):**

| # | Stage | Description | Blocking? |
|---|-------|-------------|-----------|
| 1 | `sync_fred_vm` | SSH sync FRED data from GCP VM | No (warn + continue) |
| 2 | `sync_hl_vm` | SSH sync Hyperliquid data from Singapore VM | No (warn + continue) |
| 3 | `sync_cmc_vm` | SSH sync CMC price data from Singapore VM | No (warn + continue) |
| 4 | `bars` | Build price bars for all sources (CMC, TVC, HL) | Yes |
| 5 | `returns_bars` | Compute bar returns (LAG-based incremental) | Yes |

**Key CLI args:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--ids` | (required) | Asset IDs: comma-separated ints or `all` |
| `--dry-run` | off | Preview without executing |
| `--no-sync-vms` | off | Skip stages 1-3 (use local data as-is) |
| `--source` | `all` | Filter bar source: `cmc`, `tvc`, `hl`, or `all` |
| `-n` / `--num-processes` | auto | Parallel processes for bar builders |
| `--chain` | off | Launch Features pipeline on success |
| `--continue-on-error` | off | Continue to next stage on failure |

**Reads:** GCP VM FRED tables, Oracle VM Hyperliquid tables, Oracle VM CMC price data

**Writes:**
- `price_bars_multi_tf` — OHLCV bars, all timeframes, all sources
- `returns_bars_multi_tf` — bar-level log and pct returns

**Trigger:** Manual or via `run_full_chain.py`

**Where it runs:** Local developer machine

---

## 2. Features Pipeline

**Entry point:**
```
python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all
```

**Stages (in order):**

| # | Stage | Description | Blocking? |
|---|-------|-------------|-----------|
| 1 | `emas` | EMA refreshers (multi-TF) | Yes |
| 2 | `returns_ema` | EMA returns (incremental watermark) | Yes |
| 3 | `amas` | AMA refreshers (multi-TF, all-tfs) | Yes |
| 4 | `returns_ama` | AMA returns (5 alignment sources) | Yes |
| 5 | `desc_stats` | Per-asset descriptive stats + rolling correlations | Yes |
| 6 | `macro_features` | FRED macro feature refresh | Yes |
| 7 | `macro_regimes` | 4-dimension macro regime classification | Yes |
| 8 | `macro_analytics` | HMM + lead-lag analytics | Yes |
| 9 | `cross_asset_agg` | BTC/ETH corr, funding z-scores, crypto-macro corr | Yes |
| 10 | `regimes` | Per-asset regime refresher (L0-L2 + hysteresis) | Yes |
| 11 | `features` | Feature store refresh (1D timeframe) | Yes |
| 12 | `garch` | GARCH conditional volatility forecasts | Yes |

**Key CLI args:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--ids` | (required) | Asset IDs: comma-separated ints or `all` |
| `--dry-run` | off | Preview without executing |
| `--from-stage` | first | Resume pipeline from named stage (e.g., `regimes`) |
| `--skip-stale-check` | off | Skip bar freshness gate before EMAs |
| `--chain` | off | Launch Signals pipeline on success |
| `--continue-on-error` | off | Continue to next stage on failure |

**Reads:**
- `price_bars_multi_tf`, `returns_bars_multi_tf` (from Data pipeline)
- FRED series (from GCP VM via sync_fred_vm)
- `hyperliquid.hl_funding_rates`, `hl_open_interest` (from Oracle VM via sync_hl_vm)

**Bar freshness gate:** Before `emas`, calls `get_fresh_ids()` to filter to assets with
updated bars since last EMA run. The same filtered ID list (`ids_for_emas`) is carried
through to AMAs. Pass `--skip-stale-check` to bypass.

**Writes:**
- `ema_multi_tf`, `returns_ema_multi_tf`
- `ama_multi_tf`, `returns_ama_multi_tf`
- `asset_stats`, `cross_asset_corr`
- `macro_features`, `macro_regimes`, `macro_analytics`
- `regimes`, `regime_flips`
- `features` (112 cols, bar-level feature store)
- `garch_forecasts`

**Trigger:** Manual or via Data pipeline `--chain` or `run_full_chain.py`

**Where it runs:** Local developer machine

---

## 3. Signals Pipeline

**Entry point:**
```
python -m ta_lab2.scripts.pipelines.run_signals_pipeline
```

**Stages (in order):**

| # | Stage | Description | Blocking? |
|---|-------|-------------|-----------|
| 1 | `macro_gates` | Pre-flight gate on macro conditions (VIX, carry, credit, FOMC) | Yes (exit 2 = gate blocked) |
| 2 | `macro_alerts` | Transition detection + Telegram | Yes |
| 3 | `signals` | All 7 signal types (EMA, RSI, ATR, MACD, AMA x3) | Yes |
| 4 | `signal_validation_gate` | Anomaly detection; exit code 2 sets `signal_gate_blocked` | No (informational) |
| 5 | `ic_staleness_check` | IC freshness check | No (warning only) |

**Signal gate blocked behavior:** When `signal_validation_gate` exits code 2, the
`signal_gate_blocked` flag is set. The pipeline returns 0 (not a failure). If `--chain`
is active, `sync_signals_to_vm` is NOT triggered — the VM executor sees no new signals
and waits for the next run.

**Key CLI args:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--dry-run` | off | Preview without executing |
| `--from-stage` | first | Resume from named stage |
| `--no-signal-gate` | off | Skip signal_validation_gate (testing/debug) |
| `--chain` | off | Trigger sync_signals_to_vm on success (if gate not blocked) |
| `--continue-on-error` | off | Continue to next stage on failure |

**Reads:**
- `features`, `regimes` (from Features pipeline)
- `macro_features`, `macro_regimes` (from Features pipeline)
- `ic_results` (for IC staleness check)

**Writes:**
- `signals_ema_crossover`
- `signals_rsi`
- `signals_atr_breakout`
- `signals_macd_crossover`
- `signals_ama_momentum`
- `signals_ama_mean_reversion`
- `signals_ama_regime_conditional`
- `portfolio_allocations`

**Trigger:** Manual or via Features pipeline `--chain` or `run_full_chain.py`

**Where it runs:** Local developer machine

---

## 4. sync_signals_to_vm

**Entry point:**
```
python -m ta_lab2.scripts.etl.sync_signals_to_vm
```

**Purpose:** Push signal and configuration tables to the Oracle Singapore VM via
SSH + psql COPY. Not a pipeline (no pipeline_run_log row), but part of the local chain.

**Sync modes:**

| Table type | Strategy | Tables |
|------------|----------|--------|
| Signal tables (8) | Incremental — watermark by `ts` | `signals_ema_crossover`, `signals_rsi`, `signals_atr_breakout`, `signals_macd_crossover`, `signals_ama_momentum`, `signals_ama_mean_reversion`, `signals_ama_regime_conditional`, `portfolio_allocations` |
| Config tables (3) | Full-replace — TRUNCATE + COPY all | `dim_executor_config`, `strategy_parity`, `risk_overrides` |

**Key CLI args:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--dry-run` | off | Report watermarks only (no SSH attempt, no VM connection) |
| `--full` | off | Push all rows (ignore watermark) |
| `--table` | all | Sync a single named table only |
| `--verbose` | off | Print row counts per table |

**Reads:** Local `signals_*`, `portfolio_allocations`, `dim_executor_config`,
`strategy_parity`, `risk_overrides` tables

**Writes (VM):** Same tables on Oracle VM `hyperliquid` DB

**Trigger:** Manual or via Signals pipeline `--chain` or `run_full_chain.py`

**Where it runs:** Local developer machine (SSH tunnel to Oracle VM)

> **Note:** VM tables are created in Phase 113 (VM Execution Deployment). Script handles
> missing VM tables gracefully (warns and continues to next table).

---

## 5. Execution Pipeline

**Entry point:**
```
python -m ta_lab2.scripts.pipelines.run_execution_pipeline  # single-shot
python -m ta_lab2.scripts.pipelines.run_execution_pipeline --loop  # VM deployment
```

**Stages (in order):**

| # | Stage | Description | Blocking? |
|---|-------|-------------|-----------|
| 1 | `calibrate_stops` | Compute stop levels for active positions | Yes |
| 2 | `portfolio` | Portfolio optimizer (BL weights, TopK selection) | Yes |
| 3 | `executor` | Paper executor (signal polling + order generation) | Yes |

**Key CLI args:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--dry-run` | off | Preview without executing |
| `--loop` | off | Enable polling loop mode (for VM deployment) |
| `--poll-interval` | 300 | Seconds between polls in loop mode |
| `--calibrate-only` | off | Run calibrate_stops only and exit |
| `--portfolio-only` | off | Run portfolio stage only and exit |

**Polling loop behavior:** `run_polling_loop()` is an importable, testable function.
It calls `_get_last_signal_ts()` (GREATEST MAX(ts) across all 7 signal tables) and
`_get_last_execution_ts()` to detect new signals. On 3 consecutive failures, the
loop sends a Telegram alert and exits code 1.

**Reads:**
- `signals_*` tables (from sync_signals_to_vm)
- `portfolio_allocations` (from sync_signals_to_vm)
- `dim_executor_config`, `strategy_parity`, `risk_overrides` (from sync_signals_to_vm)
- `positions`, `orders` (from previous executor runs)

**Writes:**
- `orders`, `fills`, `positions`
- `order_events`, `executor_run_log`

**Trigger:** Polling loop (always-on) or manual single-shot

**Where it runs:** Oracle Singapore VM (Phase 113 deploys as systemd service)

---

## 6. Monitoring Pipeline

**Entry point:**
```
python -m ta_lab2.scripts.pipelines.run_monitoring_pipeline
```

**Stages (in order):**

| # | Stage | Description | Blocking? |
|---|-------|-------------|-----------|
| 1 | `drift_monitor` | Drift attribution (requires `--paper-start`; silently skipped if absent) | Yes if present |
| 2 | `pipeline_alerts` | Telegram digest of pipeline health | No (failure never stops pipeline) |
| 3 | `stats` | Data quality gate | Yes (terminal) |

**Key CLI args:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--dry-run` | off | Preview without executing |
| `--paper-start` | (none) | Start date for drift monitor (ISO date, e.g., `2026-01-01`) |
| `--no-telegram` | off | Suppress Telegram alerts |
| `--stats-only` | off | Run stats stage only and exit |

**Reads:**
- `drift_metrics` (if `--paper-start` given)
- `pipeline_run_log`, `pipeline_stage_log` (pipeline health)
- `asset_stats`, `ic_results` (data quality)

**Writes:**
- `drift_metrics` (updated by drift_monitor)
- No DB writes for alerts/stats — read-only quality checks

**Trigger:** External timer (systemd timer or cron on VM — configured in Phase 113)

**Where it runs:** Oracle Singapore VM (Phase 113 deploys as systemd timer unit)

---

## Handoff Contracts

Each pipeline reads the output of the previous pipeline. These are the formal contracts:

### Contract 1: Data → Features

**Gate:** Features pipeline will check bar freshness before running EMAs.

**Required condition:**
- `price_bars_multi_tf` has rows with `ts` greater than last EMA run ts for requested IDs
- (Optional) `pipeline_run_log` has a row with `pipeline_name='data' AND status='complete'`

**Automatic handling:** `get_fresh_ids()` filters IDs with stale bars. Pass
`--skip-stale-check` to bypass when re-running Features independently.

---

### Contract 2: Features → Signals

**Gate:** Signals pipeline reads `features` and `regimes` tables.

**Required condition:**
- `features` table has rows updated in the current run (or recently)
- `regimes` table has current regime labels for active IDs
- (Optional) `pipeline_run_log` has `pipeline_name='features' AND status='complete'`

**Automatic handling:** Signals pipeline reads whatever is in `features` / `regimes`.
No hard gate — stale features produce stale signals, which the `signal_validation_gate`
stage may detect and set `signal_gate_blocked`.

---

### Contract 3: Signals → sync_signals_to_vm

**Gate:** Signal sync only runs if gate is not blocked.

**Required condition:**
- `signal_validation_gate` exited code 0 (no anomalies detected)
- If `signal_gate_blocked=True`, sync is skipped — VM executor sees no new signals

**Automatic handling:** `--chain` flag on Signals pipeline respects `signal_gate_blocked`.
`run_full_chain.py` always calls sync after Signals (non-fatal if sync fails).

---

### Contract 4: sync_signals_to_vm → Execution (VM)

**Gate:** Execution pipeline polls for signal freshness.

**Required condition:**
- VM `signals_*` tables have rows with `MAX(ts) > last executor run ts`
- `_get_last_signal_ts()` returns a timestamp newer than `_get_last_execution_ts()`

**Automatic handling:** Polling loop in `run_execution_pipeline --loop` checks freshness
every `--poll-interval` seconds. If no new signals, executor sleeps and retries.

---

### Contract 5: Monitoring (independent)

**Gate:** Monitoring pipeline is fully independent — reads pipeline_run_log + data tables.

**Required condition:** None (can run anytime, reads whatever is in the DB)

**Automatic handling:** `drift_monitor` stage silently skipped when `--paper-start` absent.

---

## Chain Mechanism

`run_full_chain.py` is the recommended daily driver, replacing `run_daily_refresh.py --all`:

```
Data pipeline
   └── success → Features pipeline
                    └── success → Signals pipeline
                                     └── success + gate not blocked → sync_signals_to_vm
```

**Halt behavior:**
- Any pipeline failure halts the chain (subsequent pipelines not started)
- `sync_signals_to_vm` failure is **non-fatal** (local pipeline is complete; VM sync is best-effort)
- Telegram alert sent on chain halt (best-effort, never crashes chain script)

**Individual pipeline chaining:** Each pipeline also supports `--chain` flag for
pairwise chaining (Data --chain → Features --chain → Signals --chain → sync).
This is equivalent to running `run_full_chain.py` with the same args.

**Kill switch:** A `.pipeline_kill` file stops the current pipeline at the next
stage boundary. The run is logged as `status='killed'` in `pipeline_run_log`.

---

## Failure Modes

| Scenario | Behavior |
|----------|----------|
| Pipeline stage failure | Chain halts; `pipeline_run_log` row set to `status='failed'`; Telegram alert |
| VM sync unreachable (Data) | Stages 1-3 warn and continue; bars run on local data |
| VM sync unreachable (signals push) | Chain continues; executor runs on last-known signals until connectivity restored |
| Signal validation anomaly | `signal_gate_blocked=True`; Signals pipeline returns 0; sync skipped |
| Kill switch (`.pipeline_kill`) | Current pipeline stops; logged as `killed`; Telegram alert |
| Execution polling — 3 consecutive failures | Loop exits code 1; Telegram alert |
| Monitoring stats failure | Terminal — `status='failed'` in run log; data quality gate |
| Monitoring drift absent `--paper-start` | Silently skipped; continues to alerts+stats |

---

## Quick Reference

```bash
# ── Full daily chain (replaces run_daily_refresh.py --all) ──────────────────
python -m ta_lab2.scripts.pipelines.run_full_chain --ids all
python -m ta_lab2.scripts.pipelines.run_full_chain --ids all --dry-run

# ── Individual pipelines ────────────────────────────────────────────────────
python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all
python -m ta_lab2.scripts.pipelines.run_data_pipeline --ids all --no-sync-vms
python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all
python -m ta_lab2.scripts.pipelines.run_features_pipeline --ids all --from-stage regimes
python -m ta_lab2.scripts.pipelines.run_signals_pipeline
python -m ta_lab2.scripts.pipelines.run_signals_pipeline --no-signal-gate
python -m ta_lab2.scripts.pipelines.run_execution_pipeline
python -m ta_lab2.scripts.pipelines.run_monitoring_pipeline --paper-start 2026-01-01

# ── Sync signals after ad-hoc Signals run ───────────────────────────────────
python -m ta_lab2.scripts.etl.sync_signals_to_vm
python -m ta_lab2.scripts.etl.sync_signals_to_vm --dry-run

# ── VM services (Phase 113 deploys these) ───────────────────────────────────
python -m ta_lab2.scripts.pipelines.run_execution_pipeline --loop --poll-interval 300
python -m ta_lab2.scripts.pipelines.run_monitoring_pipeline --paper-start 2026-01-01

# ── Legacy (deprecated — still works, shows deprecation notice on --all) ────
python -m ta_lab2.scripts.run_daily_refresh --all --ids all
python -m ta_lab2.scripts.run_daily_refresh --bars --ids 1 --dry-run

# ── Alembic ─────────────────────────────────────────────────────────────────
python -m alembic heads                  # expect single head b1c2d3e4f5a6
python -m alembic upgrade head           # apply pipeline_name migration
```

---

## Alembic Migration

Phase 112 added migration `b1c2d3e4f5a6` (`phase112_pipeline_name`):

- Adds `pipeline_name VARCHAR(30) NOT NULL DEFAULT 'daily'` to `pipeline_run_log`
- Adds nullable `pipeline_name VARCHAR(30)` to `pipeline_stage_log`
- Adds composite index `ix_pipeline_run_log_name_ts` on `(pipeline_name, started_at)`

Apply with `python -m alembic upgrade head` before running new pipeline scripts.
The scripts include backward-compatibility fallback for pre-migration deployments.

---

*Established: Phase 112 (2026-04-02)*
*Source: `src/ta_lab2/scripts/pipelines/`, `src/ta_lab2/scripts/etl/sync_signals_to_vm.py`*
