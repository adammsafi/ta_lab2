---
phase: 113
plan: "03"
name: "Signal and Config Push to VM"
subsystem: etl-sync
tags: [vm, ssh, signals, config, sync, daily-refresh]
status: complete

dependency-graph:
  requires: ["113-01"]
  provides: ["sync_signals_to_vm", "sync_config_to_vm", "daily-refresh-vm-push"]
  affects: ["113-04", "113-05", "113-06", "113-07"]

tech-stack:
  added: []
  patterns:
    - "reversed SSH+COPY pattern (local → VM vs VM → local in sync_hl_from_vm.py)"
    - "lazy import + try/except non-blocking integration in daily refresh pipeline"
    - "watermark-based incremental push for signal tables"
    - "full-replace (TRUNCATE + COPY) for small stateless config tables"

key-files:
  created:
    - src/ta_lab2/scripts/etl/sync_signals_to_vm.py
    - src/ta_lab2/scripts/etl/sync_config_to_vm.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

decisions:
  - "sync_signals_to_vm.py updated from pre-existing stub: fixed signals_rsi -> signals_rsi_mean_revert to match signal_reader.py SIGNAL_TABLE_MAP; added sync_signals() programmatic function; corrected config tables to dim_executor_config/dim_risk_limits/dim_risk_state per plan"
  - "sync_config_to_vm.py new file: full-replace strategy (TRUNCATE + COPY all rows) because config tables are small (<100 rows) and stateless — simpler and safer than incremental"
  - "Signal push wired as non-blocking in run_daily_refresh.py: lazy import + try/except with [WARN] means VM connectivity issues never block local pipeline"
  - "sync_signals() auto-calls sync_config() at the end to keep config tables current after every daily refresh"

metrics:
  tasks-completed: 3
  tasks-total: 3
  duration: "4 min"
  completed: "2026-04-02"
---

# Phase 113 Plan 03: Signal and Config Push to VM Summary

**One-liner:** Local-to-VM signal push via watermark-based SSH+COPY with full-replace config sync, wired non-blocking into daily refresh.

## What Was Built

### sync_signals_to_vm.py (updated)

Pre-existing stub updated with:
- Corrected `signals_rsi` -> `signals_rsi_mean_revert` (matches `signal_reader.py` SIGNAL_TABLE_MAP)
- All 7 signal tables from plan: ema_crossover, rsi_mean_revert, atr_breakout, macd_crossover, ama_momentum, ama_mean_reversion, ama_regime_conditional
- Config tables corrected to: dim_executor_config, dim_risk_limits, dim_risk_state
- Added `sync_signals()` programmatic function (required by run_daily_refresh.py integration)
- `sync_signals()` auto-calls `sync_config()` after signal push

Core sync flow per signal table:
1. Query VM `MAX(ts)` for watermark
2. Local `COPY ({table} WHERE ts > watermark) TO STDOUT WITH CSV HEADER`
3. SSH pipe to VM `COPY {table} FROM STDIN WITH CSV HEADER`
4. Watermark advances to new VM MAX(ts) automatically

### sync_config_to_vm.py (new)

Full-replace strategy for small stateless config tables:
1. `COPY {table} TO STDOUT WITH CSV HEADER` from local
2. SSH `TRUNCATE TABLE {table}` on VM
3. SSH `COPY {table} FROM STDIN WITH CSV HEADER` to VM

Both scripts handle missing VM tables gracefully (warn + skip, not error) so they work before Phase 113 VM table setup completes.

### run_daily_refresh.py (modified)

After signal generation succeeds, a non-blocking VM push fires:

```python
if signal_result.success and not args.dry_run:
    try:
        from ta_lab2.scripts.etl.sync_signals_to_vm import sync_signals
        print("\n[SYNC] Pushing signals to VM...")
        sync_signals(dry_run=False)
        print("[SYNC] Signal push to VM complete")
    except Exception as exc:
        print(f"\n[WARN] Signal push to VM failed: {exc}")
```

VM connectivity issues log a warning and never block downstream stages (validation gate, executor, drift monitor).

## Decisions Made

1. **Pre-existing stub fixed, not replaced** — sync_signals_to_vm.py existed as a stub with wrong table names and no programmatic API. Updated in-place rather than replacing to preserve git history.

2. **sync_config() auto-called by sync_signals()** — config tables are always pushed alongside signals so the VM executor always has current risk limits and executor config after daily refresh.

3. **Non-blocking integration** — VM push failure must never stop local pipeline stages. lazy import + try/except ensures this.

4. **Full-replace for config tables** — TRUNCATE + COPY is simpler, safer, and fast enough for <100 row tables. No need for watermark complexity.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed signal table name mismatch**

- **Found during:** Task 1
- **Issue:** Pre-existing sync_signals_to_vm.py used `signals_rsi` but the actual table is `signals_rsi_mean_revert` (confirmed in signal_reader.py, refresh scripts, and alembic migrations)
- **Fix:** Updated TableSpec list to use `signals_rsi_mean_revert`
- **Files modified:** src/ta_lab2/scripts/etl/sync_signals_to_vm.py
- **Commit:** 77fdf664

**2. [Rule 2 - Missing Critical] Added sync_signals() programmatic function**

- **Found during:** Task 1
- **Issue:** Pre-existing stub had only a `main()` CLI function; run_daily_refresh.py integration requires a `sync_signals()` function
- **Fix:** Added `sync_signals()` with dry_run/full/table/sync_config parameters
- **Files modified:** src/ta_lab2/scripts/etl/sync_signals_to_vm.py
- **Commit:** 77fdf664

**3. [Rule 1 - Bug] Corrected config table list**

- **Found during:** Task 1
- **Issue:** Pre-existing stub included `strategy_parity` and `risk_overrides` as config tables but the plan specifies `dim_executor_config`, `dim_risk_limits`, `dim_risk_state`
- **Fix:** Updated _CONFIG_TABLES to match plan specification
- **Files modified:** src/ta_lab2/scripts/etl/sync_signals_to_vm.py
- **Commit:** 77fdf664

## Verification

```bash
python -c "from ta_lab2.scripts.etl.sync_signals_to_vm import main; print('import OK')"
# import OK

python -c "from ta_lab2.scripts.etl.sync_config_to_vm import sync_config; print('import OK')"
# import OK

grep -n "sync_signals_to_vm" src/ta_lab2/scripts/run_daily_refresh.py
# 3998:  from ta_lab2.scripts.etl.sync_signals_to_vm import sync_signals
```

## Next Phase Readiness

- Phase 113-04 (VM table setup / Alembic migration) can now create the target tables on the VM
- Phase 113-05 (executor service deployment) will consume signals via the tables populated by this plan
- `sync_signals()` and `sync_config()` are importable and ready for programmatic use
