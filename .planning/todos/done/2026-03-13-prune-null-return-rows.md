---
created: 2026-03-13T22:00
title: Investigate and optionally prune all-NULL first-observation rows in returns tables
area: data-quality
tables:
  - returns_ama_multi_tf
  - returns_ama_multi_tf_u
  - returns_bars_multi_tf
  - returns_ema_multi_tf
---

## Problem

`returns_ama_multi_tf` has the exact same row count as `ama_multi_tf` (57,128,562).
The returns script inserts a row for every AMA observation, including the first one
per series where there's no prior value — those rows have all return columns NULL.

- **2.3M rows** (4%) have ALL return columns NULL (first-observation dead weight)
- **55.1M rows** have NULL in non-rolling columns but populated rolling columns
- Same pattern likely applies to `returns_bars_multi_tf` and `returns_ema_multi_tf`

## Options

1. **Skip first-observation inserts** in the returns scripts (saves 2.3M rows in AMA alone)
2. **DELETE WHERE all return cols NULL** as a one-time cleanup + adjust scripts
3. **Keep as-is** — NULLs simplify 1:1 JOINs with base tables via shared PK

## Impact

~4% row reduction per returns table. On `_u` variants (93.7M rows) the savings
are proportionally larger. No downstream consumers rely on these NULL rows.
