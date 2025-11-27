# SQL Directory Structure & Categorization

This document describes the purpose of each SQL subfolder and how files should be organized.

## 1. `sql/templates/`

**Purpose:**  
Reusable SQL templates for tables and views (e.g., generic DDL skeletons).

**What belongs here:**  
- Parameterized or copy‑paste templates that are not tied to a single concrete object.  
- Files like `schema_table_template.sql`, `schema_key_table_template.sql`, `schema_views_template.sql`.

## 2. `sql/views/`

**Purpose:**  
Authoritative DDL for materialized views or logical views that are part of the core schema.

**What belongs here:**  
- `CREATE VIEW` / `CREATE MATERIALIZED VIEW` / `CREATE OR REPLACE VIEW` scripts.  
- Any view-related helper such as simple introspection scripts (e.g., `see_views.sql`).  
- Files like `create_alter_all_emas.sql`, `create_alter_cmc_price_with_emas.sql`, `create_alter_cmc_price_with_emas_d1d2.sql`.

## 3. `sql/lookups/`

**Purpose:**  
Definition and seeding of small reference / lookup tables used across the system.

**What belongs here:**  
- DDL + inserts for small, mostly-static tables (e.g., alpha lookup, code lists).  
- Files like `001_ema_alpha_lookup.sql`.

## 4. `sql/metrics/`

**Purpose:**  
Data quality, coverage, and healthcheck queries.

**What belongs here:**  
- Range checks, freshness checks, row-count comparisons.  
- Schema/lineup validation queries (e.g., comparing `_cal` vs main tables).  
- Files like `cmc_price_ranges.sql`, `max_ts_rowcount_by_table.sql`, `max_ts_rowcount_by_id_by_table.sql`, `current_vs_snapshot_rowcount_comparisson.sql`, `id_tf_period_combo_change_tracker_mtf_mtfcal.sql`.

## 5. `sql/dev/` (or `sql/scratch/`)

**Purpose:**  
Ad-hoc, experimental, or temporary queries that support current development work.

**What belongs here:**  
- TODO helpers, one-off analyses, or WIP alignment scripts.  
- Files like `todo_6M&12M_multi_tf_cal_lineup.sql`.  
- Anything that may eventually be promoted to `views/` or `metrics/` once it stabilizes.

---

## Categorization Methodology

1. **Is this a reusable skeleton?**  
   - Yes → `sql/templates/`  
   - No → continue.

2. **Does this define a stable view that is part of the schema?**  
   - Yes → `sql/views/`  
   - No → continue.

3. **Does this define/seed a small, mostly-static lookup table?**  
   - Yes → `sql/lookups/`  
   - No → continue.

4. **Is this a healthcheck, coverage, or validation query?**  
   - Yes → `sql/metrics/`  
   - No → continue.

5. **Is this an ad-hoc or WIP query that may change or be deleted later?**  
   - Yes → `sql/dev/`  
   - If none of the above fit, default to `sql/dev/` until its role is clearer.
