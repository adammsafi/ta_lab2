# DB max_ts / row_count snapshot — 2025-11-24

**Trusted-through date:** 2025-11-24 19:00:00 (all tracked tables and ids)

Source workbook: `db_max_ts_rowcount_snapshot_2025-11-24.xlsx`  
Sheet(s): `max_ts_rowcount_table`, `max_ts_rowcount_id_table`

---

## 0. Purpose & usage

This file records a point-in-time **database health snapshot** for core OHLCV / EMA tables. It answers:

- “How far is the data loaded (max_ts)?”  
- “Roughly how big are these tables (row counts)?”  
- “Are key tables aligned on the same trusted-through timestamp?”

Use this document as the **authoritative cutoff reference** for:

- Backtests and research runs that assume data is complete through this date.  
- Verifying that new ingestion / refresh jobs did not drop rows or shift max_ts.  
- Comparing future snapshots to catch unexpected jumps in row counts or max_ts drift.

---

## 1. Snapshot overview (by table)

| table_name           | max_ts               | row_count_total |
|----------------------|----------------------|-----------------|
| cmc_price_histories7 | 2025-11-24 19:00:00  | 959,278         |
| cmc_ema_daily        | 2025-11-24 19:00:00  | 108,978         |
| cmc_ema_multi_tf     | 2025-11-24 19:00:00  | 1,349,726       |
| cmc_ema_multi_tf_cal | 2025-11-24 19:00:00  | 1,349,660       |

All tables are aligned on the same `max_ts` for the tracked asset ids.

---

## 2. Snapshot by id (per table)

### 2.1 `cmc_price_histories7`

| id    | max_ts               | row_count |
|-------|----------------------|-----------|
| 1     | 2025-11-24 19:00:00  | 5,614     |
| 52    | 2025-11-24 19:00:00  | 290,532   |
| 1027  | 2025-11-24 19:00:00  | 228,720   |
| 1839  | 2025-11-24 19:00:00  | 170,545   |
| 1975  | 2025-11-24 19:00:00  | 166,070   |
| 5426  | 2025-11-24 19:00:00  | 97,436    |
| 32196 | 2025-11-24 19:00:00  | 361       |

---

### 2.2 `cmc_ema_daily`

| id    | max_ts               | row_count |
|-------|----------------------|-----------|
| 1     | 2025-11-24 19:00:00  | 27,694    |
| 52    | 2025-11-24 19:00:00  | 22,104    |
| 1027  | 2025-11-24 19:00:00  | 18,439    |
| 1839  | 2025-11-24 19:00:00  | 14,849    |
| 1975  | 2025-11-24 19:00:00  | 14,564    |
| 5426  | 2025-11-24 19:00:00  | 9,899     |
| 32196 | 2025-11-24 19:00:00  | 1,429     |

---

### 2.3 `cmc_ema_multi_tf`

| id    | max_ts               | row_count |
|-------|----------------------|-----------|
| 1     | 2025-11-24 19:00:00  | 390,588   |
| 52    | 2025-11-24 19:00:00  | 290,766   |
| 1027  | 2025-11-24 19:00:00  | 228,752   |
| 1839  | 2025-11-24 19:00:00  | 170,560   |
| 1975  | 2025-11-24 19:00:00  | 166,037   |
| 5426  | 2025-11-24 19:00:00  | 97,436    |
| 32196 | 2025-11-24 19:00:00  | 5,587     |

---

### 2.4 `cmc_ema_multi_tf_cal`

| id    | max_ts               | row_count |
|-------|----------------------|-----------|
| 1     | 2025-11-24 19:00:00  | 390,589   |
| 52    | 2025-11-24 19:00:00  | 290,592   |
| 1027  | 2025-11-24 19:00:00  | 228,779   |
| 1839  | 2025-11-24 19:00:00  | 170,586   |
| 1975  | 2025-11-24 19:00:00  | 166,063   |
| 5426  | 2025-11-24 19:00:00  | 97,457    |
| 32196 | 2025-11-24 19:00:00  | 5,594     |

---

## 3. Notes

- All tables are current through the same `max_ts`, so this file can be used as a **trusted-through snapshot** for audits and pipeline validation.
- `cmc_ema_multi_tf` and `cmc_ema_multi_tf_cal` row counts will naturally differ slightly because they are built with different roll / calendar treatments, but their `max_ts` should remain aligned.
- If a future snapshot shows:
  - A **lower** `max_ts` than this file for any table/id, something has gone wrong (data loss or bad backfill).  
  - A **large unexpected jump** in row counts relative to price history growth, investigate schema changes, timeframe sets, or bugs in refresh scripts.

---

## 4. How to regenerate this snapshot

When you run a future refresh and want a new cutoff document:

1. Run the saved SQL files:
   - `max_ts_rowcount_by_table.sql`
   - `max_ts_rowcount_by_id_by_table.sql`
2. Export results to Excel as  
   `db_max_ts_rowcount_snapshot_YYYY-MM-DD.xlsx`  
   with sheets:
   - `max_ts_rowcount_table`
   - `max_ts_rowcount_id_table`
3. Create a new Markdown file alongside this one, named:  
   `db_trusted_through_YYYY-MM-DD.md`
4. Copy this structure, update:
   - Title date
   - Trusted-through timestamp
   - Table row counts and per-id tables
   - Any relevant notes about pipeline changes for that run.


## all_emas view (daily + multi_tf + multi_tf_cal)

- Source tables:
  - cmc_ema_daily
  - cmc_ema_multi_tf
  - cmc_ema_multi_tf_cal

- Unified schema:
  - id, ts, tf, tf_days, period, ema, d1, d2, d1_close, d2_close, roll

- Conventions:
  - d1, d2  = EMA deltas on the **canonical roll bars**
  - d1_close, d2_close = raw EMA deltas on the underlying close
  - roll = TRUE only on canonical bars for each (id, tf, period)
