---
phase: 87-live-pipeline-alert-wiring
verified: 2026-03-24T00:00:00Z
status: passed
score: 16/16 must-haves verified
re_verification: false
---

# Phase 87: Live Pipeline & Alert Wiring Verification Report

**Phase Goal:** Full daily pipeline runs autonomously: data -> features -> signals -> validation -> execution -> drift -> alerts
**Verified:** 2026-03-24
**Status:** PASSED
**Re-verification:** No - initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | IC staleness monitor computes IC-IR at 30/63/126 bar windows | VERIFIED | WINDOWS dict + _compute_multiwindow_ic_ir() at run_ic_staleness_check.py:177 |
| 2 | Decay flags when BOTH short AND medium IC-IR < 0.7 | VERIFIED | _is_decaying() line 228: short_ir < threshold and medium_ir < threshold |
| 3 | IC override writes use ON CONFLICT DO NOTHING (no compound halving) | VERIFIED | ON CONFLICT ON CONSTRAINT uq_ic_weight_overrides DO NOTHING at line 284 |
| 4 | Throttled Telegram alerts fire for IC decay with 24h cooldown | VERIFIED | COOLDOWN_HOURS_IC_DECAY = 24; _send_decay_alert() at lines 405-500 |
| 5 | Four new DB tables in migration | VERIFIED | pipeline_run_log, signal_anomaly_log, pipeline_alert_log, dim_ic_weight_overrides in n8o9p0q1r2s3 |
| 6 | Signal count anomalies checked at >2 sigma from 90-day baseline | VERIFIED | zscore_threshold=2.0, lookback_days=90, _check_one_table_count() at validate_signal_anomalies.py:313 |
| 7 | Crowded signals flagged at >40% agreement on same asset+direction | VERIFIED | crowded_pct=0.40 + SQL UNION ALL across 3 signal tables at validate_signal_anomalies.py:209 |
| 8 | Anomalous signals BLOCKED from executor (hard gate) | VERIFIED | signal_gate_blocked=True -> run_executor skipped, rc=2 at run_daily_refresh.py:3981 |
| 9 | Signal anomaly decisions logged to signal_anomaly_log | VERIFIED | _log_signal_anomaly() called for both anomaly types at validate_signal_anomalies.py:433 |
| 10 | Throttled CRITICAL Telegram alerts with 4h cooldown for signal gate | VERIFIED | cooldown_hours=4, _send_throttled_alert() -> send_alert severity=critical at line 558 |
| 11 | Baseline excludes today to avoid partial-day inflation | VERIFIED | WHERE ts < CURRENT_DATE in baseline_sql at validate_signal_anomalies.py:323 |
| 12 | --from-stage skips prior stages and implicitly enables --all | VERIFIED | args.all = True at run_daily_refresh.py:3515; skip_stages = set(STAGE_ORDER[:skip_idx]) at 3627 |
| 13 | STAGE_ORDER constant defines canonical stage ordering | VERIFIED | STAGE_ORDER with 23 entries at run_daily_refresh.py:120 including all Phase 87 stages |
| 14 | pipeline_run_log gets started_at on entry, completed_at on exit | VERIFIED | _start_pipeline_run() at 2952; _complete_pipeline_run() at 2988, called at 3732/4070 |
| 15 | Dead-man switch checks for previous day completion at pipeline start | VERIFIED | _check_dead_man() + _fire_dead_man_alert() called at lines 3734-3738 before any stage |
| 16 | Portfolio loads overrides: cleared_at IS NULL, expires_at filter, default 1.0 | VERIFIED | load_ic_weight_overrides() at refresh_portfolio_allocations.py:259; defaults to 1.0 |

**Score:** 16/16 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/n8o9p0q1r2s3_phase87_pipeline_wiring.py | 4-table schema migration | VERIFIED | 151 lines, all 4 tables + indexes, proper downgrade |
| src/ta_lab2/scripts/analysis/run_ic_staleness_check.py | IC staleness monitor with multi-window IC-IR | VERIFIED | 759 lines, ICStalenessMonitor class, CLI, no stubs |
| src/ta_lab2/scripts/signals/validate_signal_anomalies.py | Signal anomaly gate | VERIFIED | 790 lines, SignalAnomalyGate class, CLI, no stubs |
| src/ta_lab2/scripts/run_daily_refresh.py | Extended pipeline orchestrator | VERIFIED | 4086 lines, 23-stage STAGE_ORDER, all Phase 87 logic wired |
| src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py | Portfolio with IC override loading | VERIFIED | 884 lines, load_ic_weight_overrides + apply_ic_weight_overrides |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| ICStalenessMonitor | dim_ic_weight_overrides | _write_weight_override() INSERT | WIRED | ON CONFLICT DO NOTHING; constraint name uq_ic_weight_overrides matches migration |
| ICStalenessMonitor | pipeline_alert_log | _log_alert() + _is_alert_throttled() | WIRED | 24h cooldown per feature, alert_type=ic_decay |
| ICStalenessMonitor | telegram.send_alert() | _send_decay_alert() | WIRED | is_configured() guard, severity=warning |
| SignalAnomalyGate | signal_anomaly_log | _log_signal_anomaly() INSERT | WIRED | Called for count_anomaly and crowded_signal |
| SignalAnomalyGate | pipeline_alert_log | _log_pipeline_alert() + throttle | WIRED | 4h cooldown per signal_type |
| SignalAnomalyGate | telegram.send_alert() | _send_throttled_alert() | WIRED | severity=critical, is_configured() guard |
| run_daily_refresh.py gate result | executor skip | signal_gate_blocked flag | WIRED | rc==2 -> blocked=True -> executor skipped at line 3981 |
| run_daily_refresh.py | pipeline_run_log | _start_pipeline_run / _complete_pipeline_run | WIRED | Called at lines 3732 and 4070; run_id propagated |
| run_daily_refresh.py | dead-man switch | _check_dead_man -> _fire_dead_man_alert | WIRED | Called at lines 3734-3738 before any stage runs |
| run_daily_refresh.py | pipeline completion alert | run_pipeline_completion_alert | WIRED | Called at line 4050 after stats stage |
| refresh_portfolio_allocations.py | dim_ic_weight_overrides | load_ic_weight_overrides() SELECT | WIRED | cleared_at IS NULL, expires_at > now() filter; loaded at line 623 |
| refresh_portfolio_allocations.py | ic_ir_matrix BL dispatch | col_multipliers column-wise application | WIRED | ic_ir_matrix[feat] *= mult at lines 665-670 when ic_overrides non-empty |
| n8o9p0q1r2s3 migration | m7n8o9p0q1r2 prior migration | down_revision chain | WIRED | m7n8o9p0q1r2_phase86_portfolio_pipeline.py exists |

---

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| run_daily_refresh.py extended with full autonomous pipeline stages | SATISFIED | 23-stage STAGE_ORDER; all Phase 87 stages wired and called in correct order |
| IC staleness monitor: periodic re-sweep, alerts on alpha decay | SATISFIED | 30/63/126 windows, threshold=0.7, throttled Telegram, writes dim_ic_weight_overrides |
| Telegram alerts tuned with severity tiers and cooldowns | SATISFIED | IC decay (warning/24h), signal gate (critical/4h), pipeline digest (info|warning/20h) |
| Signal validation gate: >2 sigma and crowded signal flagged before execution | SATISFIED | Both checks BLOCK executor when anomaly detected; all anomalies logged |
| Dead-man switch: alert fires if pipeline has not completed | SATISFIED | _check_dead_man() checks yesterday UTC date; fires alert if no completion row (12h CD) |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py | 681 | TODO: Wire real feature values as signal_scores (Phase 87 future work) | Warning | signal_scores uses uniform 1.0; IC overrides ARE applied to ic_ir_matrix correctly |

The TODO at line 681 is an explicitly scoped future enhancement for a fully live signal-weighted BL.
IC weight overrides ARE applied to ic_ir_matrix column-wise before BL dispatch (the Plan 04 must-have is met).
The TODO only affects signal_scores magnitudes (view confidence), not the override multiplier application.
This is a warning-level incomplete enhancement, not a blocker for phase goal achievement.

---

## Human Verification Required

None required for goal achievement determination. Items requiring a live environment to fully exercise:

1. **Telegram delivery** - is_configured() + send_alert() are fully wired; actual delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.
2. **Dead-man switch scheduling** - Logic checks CURRENT_DATE - 1 day in UTC; effectiveness depends on daily scheduling.
3. **IC decay detection in practice** - threshold=0.7 coded correctly; real-world detection quality depends on live feature data.

---

## Gaps Summary

No gaps found. All 16 must-haves from Plans 01-04 are verified at all three levels (exists, substantive, wired).

**Plan 01 (IC Staleness):** ICStalenessMonitor with 30/63/126 windows, ON CONFLICT DO NOTHING override write using correct
constraint name (uq_ic_weight_overrides), 24h throttled Telegram, all 4 DB tables in migration n8o9p0q1r2s3.

**Plan 02 (Signal Gate):** SignalAnomalyGate with count anomaly (>2sigma, 90-day baseline excluding DATE(ts) < CURRENT_DATE)
and crowded signal (>40%), BLOCKED exit code 2, anomaly logged to signal_anomaly_log, 4h throttled CRITICAL Telegram.

**Plan 03 (Pipeline Wiring):** STAGE_ORDER with 23 stages including all Phase 87 stages; --from-stage sets args.all=True
and skips via STAGE_ORDER[:skip_idx]; gate blocks executor when signal_gate_blocked=True; IC staleness non-blocking;
pipeline_alerts fires after stats; dead-man switch at entry; pipeline_run_log started_at/completed_at/stages_completed JSONB.

**Plan 04 (Portfolio Overrides):** load_ic_weight_overrides() excludes cleared_at IS NOT NULL and expires_at < now();
missing overrides default to multiplier=1.0 (no effect); column-wise application on ic_ir_matrix before BL dispatch.

---

_Verified: 2026-03-24_
_Verifier: Claude (gsd-verifier)_
