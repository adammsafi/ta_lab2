# Legacy SQL Migration Catalog

These are historical migration files that have already been applied to the production database.
All future schema changes go through Alembic (`alembic/versions/`), not this directory.

**Do not apply these files to the production DB** — they have already been applied.
For new schema changes, use `alembic revision -m 'description'` instead.
See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full Alembic workflow.

---

## Catalog

All 17 files ordered by git creation date.

| # | Filename | Git Created | Purpose | Tables Affected |
|---|----------|-------------|---------|-----------------|
| 1 | `016_dim_timeframe_partial_bounds_and_calendar_families.sql` | 2025-12-20 | Add tf_days_min/max, allow_partial_start/end, calendar_scheme columns for variable-period TF support | `dim_timeframe` |
| 2 | `alter_cmc_ema_multi_tf_u_add_bar_cols.sql` | 2025-12-20 | Add ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar columns | `cmc_ema_multi_tf_u` |
| 3 | `alter_dim_timeframe_canonical_anchor_check.sql` | 2025-12-20 | Add is_canonical column; update calendar_anchor for ISO-WEEK TFs | `dim_timeframe` |
| 4 | `merge_cmc_ema_multi_tf_u_from_sources.sql` | 2025-12-20 | Data migration: populate cmc_ema_multi_tf_u from calendar and multi_tf source tables | `cmc_ema_multi_tf_u` |
| 5 | `rebuild_cmc_ema_multi_tf_u_from_sources.sql` | 2025-12-20 | Truncate + rebuild cmc_ema_multi_tf_u; restructure PK to include alignment_source | `cmc_ema_multi_tf_u` |
| 6 | `rebuild_dim_timeframe_from_backup_20251218.sql` | 2025-12-24 | Restore dim_timeframe from backup table after data loss | `dim_timeframe` |
| 7 | `rebuild_cmc_ema_multi_tf_u_from_all_sources.sql` | 2025-12-24 | Dynamic rebuild of EMA unified table from all source tables using pg catalog | `cmc_ema_multi_tf_u` |
| 8 | `017_alter_price_bars_anchor_add_offset.sql` | 2026-02-17 | Add bar_anchor_offset column + indexes to both anchor bar tables | `cmc_price_bars_multi_tf_cal_anchor_us`, `cmc_price_bars_multi_tf_cal_anchor_iso` |
| 9 | `018_refactor_dim_sessions.sql` | 2026-02-17 | Drop and recreate dim_sessions_pk constraint with new PK definition | `dim_sessions` |
| 10 | `019_unify_bar_table_schemas.sql` | 2026-02-17 | Unify all 6 bar tables to canonical PK=(id,tf,bar_seq,timestamp) + 37 base columns | All 6 `cmc_price_bars_*` tables |
| 11 | `020_add_bar_time_columns.sql` | 2026-02-17 | Add time_open_bar and time_close_bar columns to all 6 bar tables | All 6 `cmc_price_bars_*` tables |
| 12 | `021_reorder_bar_columns.sql` | 2026-02-17 | Drop all 6 bar tables for column reorder (data rebuilt via bar builders) | All 6 `cmc_price_bars_*` tables |
| 13 | `alter_cmc_ema_multi_tf_u_drop_derivatives.sql` | 2026-02-20 | Drop derivative columns (d1, d2, etc.) from EMA unified table; add is_partial_end | `cmc_ema_multi_tf_u` |
| 14 | `alter_cmc_features_redesign.sql` | 2026-02-20 | Major redesign: drop EMA + legacy return columns; add 46 bar returns + 36 vol + 18 TA columns | `cmc_features` |
| 15 | `alter_returns_tables_add_zscore.sql` | 2026-02-20 | Add z-score + is_outlier columns to all 11 returns tables (5 bar + 6 EMA) | All bar and EMA returns tables |
| 16 | `alter_returns_tables_multi_window_zscore.sql` | 2026-02-20 | Rename existing z-scores to _365 suffix; add _30 and _90 window variants | All bar and EMA returns tables |
| 17 | `alter_feature_tables_add_alignment_source.sql` | 2026-02-22 | Add alignment_source column to cmc_vol, cmc_ta, cmc_features for unified table sourcing | `cmc_vol`, `cmc_ta`, `cmc_features` |

---

## Notes

**Groupings by era:**
- Files 1–5 (2025-12-20): v0.6.0 multi-TF feature pipeline build-out.
- Files 6–7 (2025-12-24): Emergency data recovery scripts.
- Files 8–12 (2026-02-17): Phase 26 unified bar schema migration.
- Files 13–17 (2026-02-20 to 2026-02-22): v0.7.0 cmc_features redesign.

**Data migration files:** Files 4, 5, 6, 7 are data migration scripts (TRUNCATE + INSERT),
not pure schema changes. They are included because they changed the effective state of the DB
and would need to be re-run on a clean rebuild.

**Starting from 2026-02-23:** All new schema changes use Alembic. The current baseline revision is
`25f2b3c90f65` which represents the schema state after all 17 files above were applied.
