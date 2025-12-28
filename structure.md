```text
├── -p
├── .benchmarks
├── .gitattributes
├── .github
│   ├── .release-please-manifest.json
│   ├── CODEOWNERS
│   │   └── CODEOWNERS.txt
│   ├── ISSUE_TEMPLATE
│   │   ├── bug_report.yml
│   │   ├── config.yml
│   │   ├── feature_request.yml
│   │   └── tech_task.yml
│   ├── pull_request_template.md
│   ├── release-please-config.json
│   └── workflows
│       ├── add-to-project.yml
│       ├── ci.yml
│       ├── publish-release.yml
│       └── release-please.yml
├── .gitignore
├── .pytest_cache
│   ├── .gitignore
│   ├── CACHEDIR.TAG
│   ├── README.md
│   └── v
│       └── cache
│           ├── lastfailed
│           └── nodeids
├── API_MAP.md
├── ARCHITECTURE.md
├── CONTRIBUTING.md
├── README.md
├── SECURITY.md
├── __pycache__
│   ├── __init__.cpython-312.pyc
│   ├── compare.cpython-312.pyc
│   ├── config.cpython-311.pyc
│   ├── config.cpython-312.pyc
│   ├── io.cpython-312.pyc
│   ├── resample.cpython-312.pyc
│   └── run_btc_pipeline.cpython-312.pyc
├── artifacts
│   ├── btc.parquet
│   ├── cache
│   ├── db_schema_snapshot.json
│   ├── db_schema_snapshot.md
│   ├── db_schema_snapshot_1.json
│   ├── db_schema_snapshot_20251226_002458.json
│   ├── db_schema_snapshot_20251226_002458.md
│   ├── db_schema_snapshot_20251226_125420.json
│   ├── db_schema_snapshot_20251226_125420.md
│   ├── db_schema_snapshot_20251226_132605.json
│   ├── db_schema_snapshot_20251226_132605.md
│   ├── db_schema_snapshot_latest.json
│   ├── db_schema_snapshot_latest.md
│   ├── frames
│   │   ├── 10D.parquet
│   │   ├── 25D.parquet
│   │   ├── 2D.parquet
│   │   ├── 2M.parquet
│   │   ├── 2W.parquet
│   │   ├── 3D.parquet
│   │   ├── 3M.parquet
│   │   ├── 3W.parquet
│   │   ├── 45D.parquet
│   │   ├── 4D.parquet
│   │   ├── 5D.parquet
│   │   ├── 6M.parquet
│   │   ├── A.parquet
│   │   ├── M.parquet
│   │   ├── W-FRI.parquet
│   │   └── W.parquet
│   ├── function_map.csv
│   ├── function_map_full_repo.csv
│   ├── function_map_ta_lab2.csv
│   ├── snapshot_diff.json
│   ├── snapshot_diff.md
│   ├── snapshot_diff_full.json
│   └── snapshot_diff_full.md
├── audits
│   └── returns
│       ├── audit_returns_bars_multi_tf_20251222_align.csv
│       ├── audit_returns_bars_multi_tf_20251222_coverage.csv
│       ├── audit_returns_bars_multi_tf_20251222_dups.csv
│       ├── audit_returns_bars_multi_tf_20251222_gap_anomalies.csv
│       ├── audit_returns_bars_multi_tf_20251222_gaps_summary.csv
│       ├── audit_returns_bars_multi_tf_20251222_nulls.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_iso_align.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_iso_coverage.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_iso_dups.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_iso_gap_anomalies.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_iso_gaps_summary.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_iso_nulls.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_us_align.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_us_coverage.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_us_dups.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_us_gap_anomalies.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_us_gaps_summary.csv
│       ├── audit_returns_bars_multi_tf_cal_anchor_us_nulls.csv
│       ├── audit_returns_bars_multi_tf_cal_iso_align.csv
│       ├── audit_returns_bars_multi_tf_cal_iso_coverage.csv
│       ├── audit_returns_bars_multi_tf_cal_iso_dups.csv
│       ├── audit_returns_bars_multi_tf_cal_iso_gap_anomalies.csv
│       ├── audit_returns_bars_multi_tf_cal_iso_gaps_summary.csv
│       ├── audit_returns_bars_multi_tf_cal_iso_nulls.csv
│       ├── audit_returns_bars_multi_tf_cal_us_align.csv
│       ├── audit_returns_bars_multi_tf_cal_us_coverage.csv
│       ├── audit_returns_bars_multi_tf_cal_us_dups.csv
│       ├── audit_returns_bars_multi_tf_cal_us_gap_anomalies.csv
│       ├── audit_returns_bars_multi_tf_cal_us_gaps_summary.csv
│       ├── audit_returns_bars_multi_tf_cal_us_nulls.csv
│       ├── audit_returns_ema_multi_tf_20251222_align.csv
│       ├── audit_returns_ema_multi_tf_20251222_coverage.csv
│       ├── audit_returns_ema_multi_tf_20251222_dups.csv
│       ├── audit_returns_ema_multi_tf_20251222_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_20251222_gaps_summary.csv
│       ├── audit_returns_ema_multi_tf_20251222_nulls.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_align.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_bar_align.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_bar_coverage.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_bar_dups.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_bar_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_bar_nulls.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_coverage.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_dups.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_iso_ema_nulls.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_align.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_bar_align.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_bar_coverage.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_bar_dups.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_bar_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_bar_nulls.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_coverage.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_dups.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_cal_20251222_us_ema_nulls.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_iso_align.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_iso_coverage.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_iso_dups.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_iso_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_iso_gaps_summary.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_iso_nulls.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_us_align.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_us_coverage.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_us_dups.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_us_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_us_gaps_summary.csv
│       ├── audit_returns_ema_multi_tf_cal_anchor_20251222_us_nulls.csv
│       ├── audit_returns_ema_multi_tf_u_20251222_align.csv
│       ├── audit_returns_ema_multi_tf_u_20251222_coverage.csv
│       ├── audit_returns_ema_multi_tf_u_20251222_coverage_bad.csv
│       ├── audit_returns_ema_multi_tf_u_20251222_dups.csv
│       ├── audit_returns_ema_multi_tf_u_20251222_ema_coverage_bad.csv
│       ├── audit_returns_ema_multi_tf_u_20251222_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_u_20251222_nulls.csv
│       ├── audit_returns_ema_multi_tf_v2_20251222_align.csv
│       ├── audit_returns_ema_multi_tf_v2_20251222_coverage.csv
│       ├── audit_returns_ema_multi_tf_v2_20251222_dups.csv
│       ├── audit_returns_ema_multi_tf_v2_20251222_gap_anomalies.csv
│       ├── audit_returns_ema_multi_tf_v2_20251222_gaps_summary.csv
│       └── audit_returns_ema_multi_tf_v2_20251222_nulls.csv
├── changelog.md
├── config.py
├── configs
│   ├── default.yaml
│   └── regime_policies.yaml
├── data
│   ├── Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv
│   ├── Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap_edit.csv
│   ├── btcusd.csv
│   └── ta_lab2_companion.xlsx
├── db_config.env
├── diff.txt
├── docs
│   ├── Data Pipeline.md
│   ├── cheatsheets
│   │   ├── postgres
│   │   │   └── postgres.md
│   │   ├── powershell
│   │   │   └── powershell.md
│   │   └── sql
│   │       └── sql.md
│   ├── dim_timeframe.md
│   ├── ops
│   │   ├── db_max_ts_rowcount_snapshot_2025-11-24.xlsx
│   │   ├── db_trusted_through_2025-11-24.md
│   │   └── update_price_histories_and_emas.md
│   ├── qa
│   │   └── 20251213__bars_cal_anchor_qa_summary.xlsx
│   └── time
│       ├── ARCHITECTURE1.md
│       ├── architecture_index.md
│       ├── data_lineage_time.md
│       ├── dim_timeframe.md
│       ├── dim_timeframe1.md
│       ├── ema_model.md
│       ├── regime_integration.md
│       ├── returns_volatility.md
│       ├── time_model_overview.md
│       ├── time_model_overview1.md
│       ├── trading_sessions.md
│       └── trading_sessions1.md
├── ema_audit.csv
├── ema_expected_coverage.csv
├── ema_samples.csv
├── full_diff.patch
├── full_git_log.txt
├── generate_structure_docs.py
├── github
│   └── workflows
│       └── ci.yml
├── openai_config.env
├── out
│   ├── alignment.parquet
│   ├── daily_en.parquet
│   ├── daily_regimes.parquet
│   ├── monthly_en.parquet
│   ├── regime_stats.csv
│   └── weekly_en.parquet
├── price_bars_audit.csv
├── price_bars_samples.csv
├── pyproject.toml
├── pytest.ini
├── requirements-311.txt
├── research
│   └── outputs
│       ├── opt_cf_ema_coarse.csv
│       ├── opt_cf_ema_refined.csv
│       ├── opt_cf_ema_sensitivity.csv
│       └── wf_ema_results.csv
├── run_btc.py
├── run_btc_genesis.py
├── run_spyder_menu.py
├── shorter_spyder_run_file_2025_11_02.py
├── spyder_run_file_2025_11_02.py
├── sql
│   ├── 001_check_out.sql
│   ├── 002_check_out.sql
│   ├── 003_create_snapshots.sql
│   ├── 004_compare_emas_to_snapshots_2.sql
│   ├── 005_create_snapshots_2.sql
│   ├── 006_check_out.sql
│   ├── 007_check_out.sql
│   ├── 009_create_ema_refresh_state.sql
│   ├── 010_alter_cmc_ema_multi_tf_u.sql
│   ├── 011_check_out.sql
│   ├── 012_check_out.sql
│   ├── 013_check_out.sql
│   ├── 014_check_out_dim_timeframe.sql
│   ├── 015_check_out.sql
│   ├── alter_dim_timeframe_check.sql
│   ├── any_non-canonical_tfs_in_ema_tables_check.sql
│   ├── checks
│   │   ├── 001_compare_emas_to_snapshots.sql
│   │   ├── 020_dim_timeframe_sanity.sql
│   │   ├── 030_cmc_ema_multi_tf_v2_stats.sql
│   │   ├── 031_cmc_ema_multi_tf_cal_anchor_stats_table.sql
│   │   ├── cmc_ema_multi_tf_u_fk_and_tf_audit.sql
│   │   ├── dim_timeframe_naming_checks.sql
│   │   ├── dst_session_instants_proof.sql
│   │   └── find_duplicate_indexes.sql
│   ├── cmc_ema_multi_tf_v2.sql
│   ├── current_insert_into_multi_tf_u.sql
│   ├── current_insert_into_multi_tf_u_2.sql
│   ├── ddl
│   │   ├── create_cmc_returns_ema_multi_tf.sql
│   │   ├── create_cmc_returns_ema_multi_tf_cal_anchor.sql
│   │   ├── create_cmc_returns_ema_multi_tf_cal_unified.sql
│   │   ├── create_cmc_returns_ema_multi_tf_u.sql
│   │   ├── create_returns_tables_20251221.sql
│   │   ├── ddl_cmc_returns_bars_multi_tf.sql
│   │   ├── ddl_cmc_returns_bars_multi_tf_cal_anchor_iso.sql
│   │   ├── ddl_cmc_returns_bars_multi_tf_cal_anchor_us.sql
│   │   ├── ddl_cmc_returns_bars_multi_tf_cal_iso.sql
│   │   ├── ddl_cmc_returns_bars_multi_tf_cal_us.sql
│   │   ├── indexes
│   │   │   └── create_unique_indexes_canonical_integrity.sql
│   │   └── price_bars__cmc_price_bars_multi_tf.sql
│   ├── dev
│   │   ├── ddl_extractors.sql
│   │   ├── rebuild_cmc_ema_multi_tf_u.sql
│   │   └── todo_6M&12M_multi_tf_cal_lineup.sql
│   ├── dim
│   │   ├── dim_session_instants_for_date.sql
│   │   ├── public.dim_timeframe.sql
│   │   ├── public.session_instants_for_date.sql
│   │   └── qa__dim_timeframe_calendar_filters.sql
│   ├── features
│   │   ├── 030_cmc_ema_multi_tf_u_create.sql
│   │   ├── 031_cmc_price_bars_multi_tf_cal_iso.sql
│   │   ├── 031_cmc_price_bars_multi_tf_cal_us.sql
│   │   ├── 033_cmc_price_bars_multi_tf_cal_anchor_us.sql
│   │   └── 034_cmc_price_bars_multi_tf_cal_anchor_iso.sql
│   ├── gates
│   │   └── gate_canonical_integrity.sql
│   ├── lookups
│   │   ├── 001_ema_alpha_lookup.sql
│   │   ├── 010_dim_timeframe_create.sql
│   │   ├── 011_dim_timeframe_insert_daily.sql
│   │   ├── 012_dim_timeframe_insert_weekly.sql
│   │   ├── 013_dim_timeframe_insert_monthly.sql
│   │   ├── 014_dim_timeframe_insert_yearly.sql
│   │   ├── 015_dim_period.sql
│   │   ├── 016_dim_timeframe_period.sql
│   │   ├── 017_ema_alpha_lookup.sql
│   │   ├── 018_migrate_ema_alpha_lut_to_view.sql
│   │   ├── 019_ema_alpha_lut_legacy_view.sql
│   │   ├── 021_ema_alpha_lut_diff.sql
│   │   ├── dim_timeframe_20251128.csv
│   │   └── ema_alpha_lookup.sql
│   ├── metrics
│   │   ├── cmc_price_ranges.sql
│   │   ├── current_vs_snapshot_rowcount_comparisson.sql
│   │   ├── id_tf_period_combo_change_tracker_mtf_mtfcal.sql
│   │   ├── max_ts_rowcount_by_id_by_table.sql
│   │   └── max_ts_rowcount_by_table.sql
│   ├── migration
│   │   ├── 016_dim_timeframe_partial_bounds_and_calendar_families.sql
│   │   └── rebuild_dim_timeframe_from_backup_20251218.sql
│   ├── qa
│   │   ├── 20251213__qa_cal_tables_vs_snapshots.sql
│   │   ├── 20251213__qa_multi_tf_vs_snapshot_tf_norm.sql
│   │   └── 20251213__qa_tf_presence_across_pipeline.sql
│   ├── snapshots
│   │   └── 20251213__bars_snapshots.sql
│   ├── sql_folder_structure.md
│   ├── templates
│   │   ├── schema_key_table_template.sql
│   │   ├── schema_table_template.sql
│   │   └── schema_views_template.sql
│   └── views
│       ├── create_alter_all_emas.sql
│       ├── create_alter_cmc_price_with_emas.sql
│       ├── create_alter_cmc_price_with_emas_d1d2.sql
│       └── see_views.sql
├── src
│   ├── ta_lab2
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   │   ├── __init__.cpython-311.pyc
│   │   │   ├── __init__.cpython-312.pyc
│   │   │   ├── cli.cpython-312.pyc
│   │   │   ├── compare.cpython-312.pyc
│   │   │   ├── config.cpython-311.pyc
│   │   │   ├── config.cpython-312.pyc
│   │   │   ├── io.cpython-312.pyc
│   │   │   └── resample.cpython-312.pyc
│   │   ├── analysis
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── feature_eval.cpython-312.pyc
│   │   │   │   ├── parameter_sweep.cpython-312.pyc
│   │   │   │   ├── performance.cpython-312.pyc
│   │   │   │   └── regime_eval.cpython-312.pyc
│   │   │   ├── feature_eval.py
│   │   │   ├── parameter_sweep.py
│   │   │   ├── performance.py
│   │   │   └── regime_eval.py
│   │   ├── backtests
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-311.pyc
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── btpy_runner.cpython-312.pyc
│   │   │   │   ├── costs.cpython-311.pyc
│   │   │   │   ├── costs.cpython-312.pyc
│   │   │   │   ├── metrics.cpython-312.pyc
│   │   │   │   ├── orchestrator.cpython-311.pyc
│   │   │   │   ├── orchestrator.cpython-312.pyc
│   │   │   │   ├── reports.cpython-312.pyc
│   │   │   │   ├── splitters.cpython-311.pyc
│   │   │   │   ├── splitters.cpython-312.pyc
│   │   │   │   ├── vbt_runner.cpython-311.pyc
│   │   │   │   └── vbt_runner.cpython-312.pyc
│   │   │   ├── btpy_runner.py
│   │   │   ├── costs.py
│   │   │   ├── metrics.py
│   │   │   ├── orchestrator.py
│   │   │   ├── reports.py
│   │   │   ├── splitters.py
│   │   │   └── vbt_runner.py
│   │   ├── cli.py
│   │   ├── compare.py
│   │   ├── config.py
│   │   ├── features
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-311.pyc
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── calendar.cpython-311.pyc
│   │   │   │   ├── calendar.cpython-312.pyc
│   │   │   │   ├── correlation.cpython-311.pyc
│   │   │   │   ├── correlation.cpython-312.pyc
│   │   │   │   ├── ema.cpython-311.pyc
│   │   │   │   ├── ema.cpython-312.pyc
│   │   │   │   ├── ensure.cpython-312.pyc
│   │   │   │   ├── feature_pack.cpython-312.pyc
│   │   │   │   ├── indicators.cpython-311.pyc
│   │   │   │   ├── indicators.cpython-312.pyc
│   │   │   │   ├── resample.cpython-312.pyc
│   │   │   │   ├── returns.cpython-311.pyc
│   │   │   │   ├── returns.cpython-312.pyc
│   │   │   │   ├── segments.cpython-311.pyc
│   │   │   │   ├── segments.cpython-312.pyc
│   │   │   │   ├── trend.cpython-311.pyc
│   │   │   │   ├── trend.cpython-312.pyc
│   │   │   │   ├── vol.cpython-311.pyc
│   │   │   │   └── vol.cpython-312.pyc
│   │   │   ├── calendar.py
│   │   │   ├── correlation.py
│   │   │   ├── ema.py
│   │   │   ├── ensure.py
│   │   │   ├── feature_pack.py
│   │   │   ├── indicators.py
│   │   │   ├── m_tf
│   │   │   │   ├── __init__.py
│   │   │   │   ├── __pycache__
│   │   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   │   ├── ema_multi_tf_cal.cpython-312.pyc
│   │   │   │   │   ├── ema_multi_tf_cal_anchor.cpython-312.pyc
│   │   │   │   │   ├── ema_multi_tf_v2.cpython-312.pyc
│   │   │   │   │   ├── ema_multi_timeframe.cpython-312.pyc
│   │   │   │   │   └── views.cpython-312.pyc
│   │   │   │   ├── ema_multi_tf_cal.py
│   │   │   │   ├── ema_multi_tf_cal_anchor.py
│   │   │   │   ├── ema_multi_tf_v2.py
│   │   │   │   ├── ema_multi_timeframe.py
│   │   │   │   ├── ema_research
│   │   │   │   │   ├── combos1.csv
│   │   │   │   │   └── mutli_tf_v1_vs_v2.py
│   │   │   │   └── views.py
│   │   │   ├── resample.py
│   │   │   ├── returns.py
│   │   │   ├── segments.py
│   │   │   ├── trend.py
│   │   │   └── vol.py
│   │   ├── io
│   │   ├── io.py
│   │   ├── live
│   │   ├── logging_setup.py
│   │   ├── pipelines
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-311.pyc
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── btc_pipeline.cpython-311.pyc
│   │   │   │   └── btc_pipeline.cpython-312.pyc
│   │   │   └── btc_pipeline.py
│   │   ├── regimes
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-311.pyc
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── comovement.cpython-311.pyc
│   │   │   │   ├── comovement.cpython-312.pyc
│   │   │   │   ├── data_budget.cpython-311.pyc
│   │   │   │   ├── data_budget.cpython-312.pyc
│   │   │   │   ├── feature_utils.cpython-311.pyc
│   │   │   │   ├── feature_utils.cpython-312.pyc
│   │   │   │   ├── flips.cpython-311.pyc
│   │   │   │   ├── flips.cpython-312.pyc
│   │   │   │   ├── labels.cpython-311.pyc
│   │   │   │   ├── labels.cpython-312.pyc
│   │   │   │   ├── policy_loader.cpython-311.pyc
│   │   │   │   ├── policy_loader.cpython-312.pyc
│   │   │   │   ├── proxies.cpython-311.pyc
│   │   │   │   ├── proxies.cpython-312.pyc
│   │   │   │   ├── regime_inspect.cpython-312.pyc
│   │   │   │   ├── resolver.cpython-311.pyc
│   │   │   │   ├── resolver.cpython-312.pyc
│   │   │   │   ├── run_btc_pipeline.cpython-312.pyc
│   │   │   │   ├── segments.cpython-311.pyc
│   │   │   │   ├── segments.cpython-312.pyc
│   │   │   │   └── telemetry.cpython-312.pyc
│   │   │   ├── comovement.py
│   │   │   ├── data_budget.py
│   │   │   ├── feature_utils.py
│   │   │   ├── flips.py
│   │   │   ├── labels.py
│   │   │   ├── old_run_btc_pipeline.py
│   │   │   ├── policy_loader.py
│   │   │   ├── proxies.py
│   │   │   ├── regime_inspect.py
│   │   │   ├── resolver.py
│   │   │   ├── run_btc_pipeline.py
│   │   │   ├── segments.py
│   │   │   └── telemetry.py
│   │   ├── resample.py
│   │   ├── scripts
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── refresh_cmc_emas.cpython-312.pyc
│   │   │   │   ├── refresh_ema_daily_stats.cpython-312.pyc
│   │   │   │   ├── refresh_ema_multi_tf_cal_stats.cpython-312.pyc
│   │   │   │   ├── refresh_ema_multi_tf_stats.cpython-312.pyc
│   │   │   │   ├── refresh_price_histories7_stats.cpython-312.pyc
│   │   │   │   ├── run_ema_refresh_examples.cpython-312.pyc
│   │   │   │   ├── run_refresh_ema_daily_stats.cpython-312.pyc
│   │   │   │   ├── run_refresh_ema_multi_tf_cal_stats.cpython-312.pyc
│   │   │   │   ├── run_refresh_ema_multi_tf_stats.cpython-312.pyc
│   │   │   │   └── run_refresh_price_histories7_stats.cpython-312.pyc
│   │   │   ├── bars
│   │   │   │   ├── audit_price_bars_integrity.py
│   │   │   │   ├── audit_price_bars_samples.py
│   │   │   │   ├── audit_price_bars_tables.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_anchor_iso_pre-partial-end.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_anchor_us.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_anchor_us_pre-partial-end.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_iso.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_iso_pre-partial-end.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_us.py
│   │   │   │   ├── refresh_cmc_price_bars_multi_tf_cal_us_pre-partial-end.py
│   │   │   │   └── refresh_cmc_price_bars_multi_tf_pre-partial-end.py
│   │   │   ├── emas
│   │   │   │   ├── __init__.py
│   │   │   │   ├── __pycache__
│   │   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   │   └── refresh_cmc_emas.cpython-312.pyc
│   │   │   │   ├── audit_ema_expected_coverage.py
│   │   │   │   ├── audit_ema_integrity.py
│   │   │   │   ├── audit_ema_samples.py
│   │   │   │   ├── audit_ema_tables.py
│   │   │   │   ├── refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py
│   │   │   │   ├── refresh_cmc_ema_multi_tf_cal_from_bars.py
│   │   │   │   ├── refresh_cmc_ema_multi_tf_from_bars.py
│   │   │   │   ├── refresh_cmc_ema_multi_tf_v2.py
│   │   │   │   ├── run_all_ema_refreshes.py
│   │   │   │   ├── stats
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── __pycache__
│   │   │   │   │   │   └── __init__.cpython-312.pyc
│   │   │   │   │   ├── daily
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── __pycache__
│   │   │   │   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   │   │   │   └── refresh_ema_daily_stats.cpython-312.pyc
│   │   │   │   │   │   ├── refresh_ema_daily_stats.py
│   │   │   │   │   │   └── run_refresh_ema_daily_stats.py
│   │   │   │   │   ├── multi_tf
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── __pycache__
│   │   │   │   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   │   │   │   └── refresh_ema_multi_tf_stats.cpython-312.pyc
│   │   │   │   │   │   └── refresh_ema_multi_tf_stats.py
│   │   │   │   │   ├── multi_tf_cal
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── __pycache__
│   │   │   │   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   │   │   │   └── refresh_ema_multi_tf_cal_stats.cpython-312.pyc
│   │   │   │   │   │   └── refresh_ema_multi_tf_cal_stats.py
│   │   │   │   │   ├── multi_tf_cal_anchor
│   │   │   │   │   │   ├── __pycache__
│   │   │   │   │   │   │   └── refresh_ema_multi_tf_cal_anchor_stats.cpython-312.pyc
│   │   │   │   │   │   └── refresh_ema_multi_tf_cal_anchor_stats.py
│   │   │   │   │   └── multi_tf_v2
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── __pycache__
│   │   │   │   │       │   └── refresh_ema_multi_tf_v2_stats.cpython-312.pyc
│   │   │   │   │       └── refresh_ema_multi_tf_v2_stats.py
│   │   │   │   └── sync_cmc_ema_multi_tf_u.py
│   │   │   ├── etl
│   │   │   │   ├── backfill_ema_diffs.py
│   │   │   │   └── update_cmc_history.py
│   │   │   ├── figure out.py
│   │   │   ├── open_ai_script.py
│   │   │   ├── pipeline
│   │   │   │   └── run_go_forward_daily_refresh.py
│   │   │   ├── prices
│   │   │   │   ├── __init__.py
│   │   │   │   ├── __pycache__
│   │   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   │   └── refresh_price_histories7_stats.cpython-312.pyc
│   │   │   │   ├── refresh_price_histories7_stats.py
│   │   │   │   └── run_refresh_price_histories7_stats.py
│   │   │   ├── research
│   │   │   │   ├── notebooks
│   │   │   │   └── queries
│   │   │   │       ├── __pycache__
│   │   │   │       │   ├── opt_cf_ema.cpython-311.pyc
│   │   │   │       │   ├── opt_cf_ema.cpython-312.pyc
│   │   │   │       │   ├── opt_cf_ema_refine.cpython-311.pyc
│   │   │   │       │   ├── opt_cf_ema_refine.cpython-312.pyc
│   │   │   │       │   ├── opt_cf_ema_sensitivity.cpython-311.pyc
│   │   │   │       │   ├── opt_cf_ema_sensitivity.cpython-312.pyc
│   │   │   │       │   ├── opt_cf_generic.cpython-311.pyc
│   │   │   │       │   ├── opt_cf_generic.cpython-312.pyc
│   │   │   │       │   ├── run_ema_50_100.cpython-311.pyc
│   │   │   │       │   ├── run_ema_50_100.cpython-312.pyc
│   │   │   │       │   ├── wf_validate_ema.cpython-311.pyc
│   │   │   │       │   └── wf_validate_ema.cpython-312.pyc
│   │   │   │       ├── opt_cf_ema.py
│   │   │   │       ├── opt_cf_ema_refine.py
│   │   │   │       ├── opt_cf_ema_sensitivity.py
│   │   │   │       ├── opt_cf_generic.py
│   │   │   │       ├── run_ema_50_100.py
│   │   │   │       └── wf_validate_ema.py
│   │   │   ├── returns
│   │   │   │   ├── audit_returns_bars_multi_tf_cal_anchor_iso_integrity.py
│   │   │   │   ├── audit_returns_bars_multi_tf_cal_anchor_us_integrity.py
│   │   │   │   ├── audit_returns_bars_multi_tf_cal_iso_integrity.py
│   │   │   │   ├── audit_returns_bars_multi_tf_cal_us_integrity.py
│   │   │   │   ├── audit_returns_bars_multi_tf_integrity.py
│   │   │   │   ├── audit_returns_d1_integrity.py
│   │   │   │   ├── audit_returns_ema_multi_tf_cal_anchor_integrity.py
│   │   │   │   ├── audit_returns_ema_multi_tf_cal_integrity.py
│   │   │   │   ├── audit_returns_ema_multi_tf_integrity.py
│   │   │   │   ├── audit_returns_ema_multi_tf_u_integrity.py
│   │   │   │   ├── audit_returns_ema_multi_tf_v2_integrity.py
│   │   │   │   ├── refresh_cmc_returns_bars_multi_tf.py
│   │   │   │   ├── refresh_cmc_returns_bars_multi_tf_cal_anchor_iso.py
│   │   │   │   ├── refresh_cmc_returns_bars_multi_tf_cal_anchor_us.py
│   │   │   │   ├── refresh_cmc_returns_bars_multi_tf_cal_iso.py
│   │   │   │   ├── refresh_cmc_returns_bars_multi_tf_cal_us.py
│   │   │   │   ├── refresh_cmc_returns_d1.py
│   │   │   │   ├── refresh_cmc_returns_ema_multi_tf.py
│   │   │   │   ├── refresh_cmc_returns_ema_multi_tf_cal.py
│   │   │   │   ├── refresh_cmc_returns_ema_multi_tf_cal_anchor.py
│   │   │   │   ├── refresh_cmc_returns_ema_multi_tf_u.py
│   │   │   │   └── refresh_cmc_returns_ema_multi_tf_v2.py
│   │   │   └── sandbox
│   │   ├── signals
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-311.pyc
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── breakout_atr.cpython-311.pyc
│   │   │   │   ├── breakout_atr.cpython-312.pyc
│   │   │   │   ├── ema_trend.cpython-311.pyc
│   │   │   │   ├── ema_trend.cpython-312.pyc
│   │   │   │   ├── generator.cpython-311.pyc
│   │   │   │   ├── generator.cpython-312.pyc
│   │   │   │   ├── position_sizing.cpython-311.pyc
│   │   │   │   ├── position_sizing.cpython-312.pyc
│   │   │   │   ├── registry.cpython-311.pyc
│   │   │   │   ├── registry.cpython-312.pyc
│   │   │   │   ├── rsi_mean_revert.cpython-311.pyc
│   │   │   │   ├── rsi_mean_revert.cpython-312.pyc
│   │   │   │   ├── rules.cpython-311.pyc
│   │   │   │   └── rules.cpython-312.pyc
│   │   │   ├── breakout_atr.py
│   │   │   ├── ema_trend.py
│   │   │   ├── generator.py
│   │   │   ├── position_sizing.py
│   │   │   ├── registry.py
│   │   │   ├── rsi_mean_revert.py
│   │   │   └── rules.py
│   │   ├── time
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── dim_sessions.cpython-312.pyc
│   │   │   │   └── dim_timeframe.cpython-312.pyc
│   │   │   ├── dim_sessions.py
│   │   │   ├── dim_timeframe.py
│   │   │   ├── qa.py
│   │   │   └── specs.py
│   │   ├── tools
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   │   ├── __init__.cpython-312.pyc
│   │   │   │   ├── dbtool.cpython-312.pyc
│   │   │   │   └── snapshot_diff.cpython-312.pyc
│   │   │   ├── dbtool.py
│   │   │   └── snapshot_diff.py
│   │   ├── utils
│   │   │   ├── __pycache__
│   │   │   │   └── cache.cpython-312.pyc
│   │   │   └── cache.py
│   │   └── viz
│   │       ├── __pycache__
│   │       │   └── all_plots.cpython-312.pyc
│   │       └── all_plots.py
│   └── ta_lab2.egg-info
│       ├── PKG-INFO
│       ├── SOURCES.txt
│       ├── dependency_links.txt
│       ├── entry_points.txt
│       ├── requires.txt
│       └── top_level.txt
├── src_structure.json
├── structure.csv
├── structure.json
├── structure.md
├── structure.txt
└── tests
    ├── .benchmarks
    ├── __pycache__
    │   ├── conftest.cpython-311-pytest-9.0.0.pyc
    │   ├── conftest.cpython-312-pytest-8.4.2.pyc
    │   ├── test_calendar.cpython-311-pytest-9.0.0.pyc
    │   ├── test_calendar.cpython-312-pytest-8.4.2.pyc
    │   ├── test_cli_paths.cpython-311-pytest-9.0.0.pyc
    │   ├── test_cli_paths.cpython-312-pytest-8.4.2.pyc
    │   ├── test_db_snapshot_check.cpython-312-pytest-8.4.2.pyc
    │   ├── test_db_snapshot_diff.cpython-312-pytest-8.4.2.pyc
    │   ├── test_features_ema.cpython-311-pytest-9.0.0.pyc
    │   ├── test_features_ema.cpython-312-pytest-8.4.2.pyc
    │   ├── test_pipeline.cpython-311-pytest-9.0.0.pyc
    │   ├── test_pipeline.cpython-312-pytest-8.4.2.pyc
    │   ├── test_regime_labelers_feature_utils_smoke.cpython-311-pytest-9.0.0.pyc
    │   ├── test_regime_labelers_feature_utils_smoke.cpython-312-pytest-8.4.2.pyc
    │   ├── test_regime_policy_resolution_tighten_only_and_hysteresis.cpython-311-pytest-9.0.0.pyc
    │   ├── test_regime_policy_resolution_tighten_only_and_hysteresis.cpython-312-pytest-8.4.2.pyc
    │   ├── test_smoke_imports.cpython-312-pytest-8.4.2.pyc
    │   ├── test_wireup_signals_backtests.cpython-311-pytest-9.0.0.pyc
    │   └── test_wireup_signals_backtests.cpython-312-pytest-8.4.2.pyc
    ├── conftest.py
    ├── fixtures
    │   └── db_schema_snapshot_min.json
    ├── test_calendar.py
    ├── test_cli_paths.py
    ├── test_db_snapshot_check.py
    ├── test_db_snapshot_diff.py
    ├── test_features_ema.py
    ├── test_pipeline.py
    ├── test_regime_labelers_feature_utils_smoke.py
    ├── test_regime_policy_resolution_tighten_only_and_hysteresis.py
    ├── test_sessions_dst.py
    ├── test_smoke_imports.py
    └── test_wireup_signals_backtests.py
```
