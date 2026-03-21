"""Rename tooling for stripping cmc_ prefix and adding venue_id dimension.

Provides:
- TABLE_RENAME_MAP: old_table -> new_table for all ~80 tables
- VIEW_RENAME_MAP: views/matviews to drop+recreate
- FILE_RENAME_MAP: Python files to git mv
- VENUE_ID_TABLES: tables getting venue_id in PK
- EXCLUDED_TABLES: genuinely CMC-only, keep cmc_ prefix
- apply_renames_to_content(): longest-first string replacement
"""

from __future__ import annotations

from collections import OrderedDict

# ─────────────────────────────────────────────────────────────────────
# Tables EXCLUDED from rename (genuinely CMC-only)
# ─────────────────────────────────────────────────────────────────────
EXCLUDED_TABLES = frozenset(
    [
        "cmc_da_ids",
        "cmc_da_info",
        "cmc_exchange_map",
        "cmc_exchange_info",
        "cmc_price_histories7",
    ]
)

# ─────────────────────────────────────────────────────────────────────
# Directories to SKIP during bulk rename (historical, archived)
# ─────────────────────────────────────────────────────────────────────
SKIP_DIRS = frozenset(
    [
        "alembic/versions",
        "old",
        ".git",
        "__pycache__",
        ".planning",
    ]
)

# ─────────────────────────────────────────────────────────────────────
# TABLE_RENAME_MAP: old_name -> new_name (sorted longest-first)
# ─────────────────────────────────────────────────────────────────────
_RAW_TABLE_RENAME_MAP: dict[str, str] = {
    # --- Price Bars ---
    "cmc_price_bars_1d": "price_bars_1d",
    "cmc_price_bars_1d_state": "price_bars_1d_state",
    "cmc_price_bars_multi_tf": "price_bars_multi_tf",
    "cmc_price_bars_multi_tf_state": "price_bars_multi_tf_state",
    "cmc_price_bars_multi_tf_cal_iso": "price_bars_multi_tf_cal_iso",
    "cmc_price_bars_multi_tf_cal_iso_state": "price_bars_multi_tf_cal_iso_state",
    "cmc_price_bars_multi_tf_cal_us": "price_bars_multi_tf_cal_us",
    "cmc_price_bars_multi_tf_cal_us_state": "price_bars_multi_tf_cal_us_state",
    "cmc_price_bars_multi_tf_cal_anchor_iso": "price_bars_multi_tf_cal_anchor_iso",
    "cmc_price_bars_multi_tf_cal_anchor_iso_state": "price_bars_multi_tf_cal_anchor_iso_state",
    "cmc_price_bars_multi_tf_cal_anchor_us": "price_bars_multi_tf_cal_anchor_us",
    "cmc_price_bars_multi_tf_cal_anchor_us_state": "price_bars_multi_tf_cal_anchor_us_state",
    "cmc_price_bars_multi_tf_u": "price_bars_multi_tf_u",
    # --- EMAs ---
    "cmc_ema_multi_tf": "ema_multi_tf",
    "cmc_ema_multi_tf_state": "ema_multi_tf_state",
    "cmc_ema_multi_tf_cal_iso": "ema_multi_tf_cal_iso",
    "cmc_ema_multi_tf_cal_iso_state": "ema_multi_tf_cal_iso_state",
    "cmc_ema_multi_tf_cal_us": "ema_multi_tf_cal_us",
    "cmc_ema_multi_tf_cal_us_state": "ema_multi_tf_cal_us_state",
    "cmc_ema_multi_tf_cal_anchor_iso": "ema_multi_tf_cal_anchor_iso",
    "cmc_ema_multi_tf_cal_anchor_iso_state": "ema_multi_tf_cal_anchor_iso_state",
    "cmc_ema_multi_tf_cal_anchor_us": "ema_multi_tf_cal_anchor_us",
    "cmc_ema_multi_tf_cal_anchor_us_state": "ema_multi_tf_cal_anchor_us_state",
    "cmc_ema_multi_tf_u": "ema_multi_tf_u",
    # --- AMAs ---
    "cmc_ama_multi_tf": "ama_multi_tf",
    "cmc_ama_multi_tf_state": "ama_multi_tf_state",
    "cmc_ama_multi_tf_cal_iso": "ama_multi_tf_cal_iso",
    "cmc_ama_multi_tf_cal_iso_state": "ama_multi_tf_cal_iso_state",
    "cmc_ama_multi_tf_cal_us": "ama_multi_tf_cal_us",
    "cmc_ama_multi_tf_cal_us_state": "ama_multi_tf_cal_us_state",
    "cmc_ama_multi_tf_cal_anchor_iso": "ama_multi_tf_cal_anchor_iso",
    "cmc_ama_multi_tf_cal_anchor_iso_state": "ama_multi_tf_cal_anchor_iso_state",
    "cmc_ama_multi_tf_cal_anchor_us": "ama_multi_tf_cal_anchor_us",
    "cmc_ama_multi_tf_cal_anchor_us_state": "ama_multi_tf_cal_anchor_us_state",
    "cmc_ama_multi_tf_u": "ama_multi_tf_u",
    # --- Bar Returns ---
    "cmc_returns_bars_multi_tf": "returns_bars_multi_tf",
    "cmc_returns_bars_multi_tf_state": "returns_bars_multi_tf_state",
    "cmc_returns_bars_multi_tf_cal_iso": "returns_bars_multi_tf_cal_iso",
    "cmc_returns_bars_multi_tf_cal_iso_state": "returns_bars_multi_tf_cal_iso_state",
    "cmc_returns_bars_multi_tf_cal_us": "returns_bars_multi_tf_cal_us",
    "cmc_returns_bars_multi_tf_cal_us_state": "returns_bars_multi_tf_cal_us_state",
    "cmc_returns_bars_multi_tf_cal_anchor_iso": "returns_bars_multi_tf_cal_anchor_iso",
    "cmc_returns_bars_multi_tf_cal_anchor_iso_state": "returns_bars_multi_tf_cal_anchor_iso_state",
    "cmc_returns_bars_multi_tf_cal_anchor_us": "returns_bars_multi_tf_cal_anchor_us",
    "cmc_returns_bars_multi_tf_cal_anchor_us_state": "returns_bars_multi_tf_cal_anchor_us_state",
    "cmc_returns_bars_multi_tf_u": "returns_bars_multi_tf_u",
    # --- EMA Returns ---
    "cmc_returns_ema_multi_tf": "returns_ema_multi_tf",
    "cmc_returns_ema_multi_tf_state": "returns_ema_multi_tf_state",
    "cmc_returns_ema_multi_tf_cal_iso": "returns_ema_multi_tf_cal_iso",
    "cmc_returns_ema_multi_tf_cal_iso_state": "returns_ema_multi_tf_cal_iso_state",
    "cmc_returns_ema_multi_tf_cal_us": "returns_ema_multi_tf_cal_us",
    "cmc_returns_ema_multi_tf_cal_us_state": "returns_ema_multi_tf_cal_us_state",
    "cmc_returns_ema_multi_tf_cal_anchor_iso": "returns_ema_multi_tf_cal_anchor_iso",
    "cmc_returns_ema_multi_tf_cal_anchor_iso_state": "returns_ema_multi_tf_cal_anchor_iso_state",
    "cmc_returns_ema_multi_tf_cal_anchor_us": "returns_ema_multi_tf_cal_anchor_us",
    "cmc_returns_ema_multi_tf_cal_anchor_us_state": "returns_ema_multi_tf_cal_anchor_us_state",
    "cmc_returns_ema_multi_tf_u": "returns_ema_multi_tf_u",
    # --- AMA Returns ---
    "cmc_returns_ama_multi_tf": "returns_ama_multi_tf",
    "cmc_returns_ama_multi_tf_state": "returns_ama_multi_tf_state",
    "cmc_returns_ama_multi_tf_cal_iso": "returns_ama_multi_tf_cal_iso",
    "cmc_returns_ama_multi_tf_cal_iso_state": "returns_ama_multi_tf_cal_iso_state",
    "cmc_returns_ama_multi_tf_cal_us": "returns_ama_multi_tf_cal_us",
    "cmc_returns_ama_multi_tf_cal_us_state": "returns_ama_multi_tf_cal_us_state",
    "cmc_returns_ama_multi_tf_cal_anchor_iso": "returns_ama_multi_tf_cal_anchor_iso",
    "cmc_returns_ama_multi_tf_cal_anchor_iso_state": "returns_ama_multi_tf_cal_anchor_iso_state",
    "cmc_returns_ama_multi_tf_cal_anchor_us": "returns_ama_multi_tf_cal_anchor_us",
    "cmc_returns_ama_multi_tf_cal_anchor_us_state": "returns_ama_multi_tf_cal_anchor_us_state",
    "cmc_returns_ama_multi_tf_u": "returns_ama_multi_tf_u",
    # --- Features ---
    "cmc_features": "features",
    "cmc_feature_state": "feature_state",
    "cmc_ta": "ta",
    "cmc_vol": "vol",
    "cmc_ta_daily": "ta_daily",
    "cmc_vol_daily": "vol_daily",
    "cmc_returns_daily": "returns_daily",
    "cmc_cycle_stats": "cycle_stats",
    "cmc_rolling_extremes": "rolling_extremes",
    "cmc_cs_norms": "cs_norms",
    "cmc_features_stats": "features_stats",
    # --- Signals ---
    "cmc_signals_ema_crossover": "signals_ema_crossover",
    "cmc_signals_rsi_mean_revert": "signals_rsi_mean_revert",
    "cmc_signals_atr_breakout": "signals_atr_breakout",
    "cmc_signal_state": "signal_state",
    # --- Regimes ---
    "cmc_regimes": "regimes",
    "cmc_regime_flips": "regime_flips",
    "cmc_regime_stats": "regime_stats",
    "cmc_regime_comovement": "regime_comovement",
    # --- Backtests ---
    "cmc_backtest_runs": "backtest_runs",
    "cmc_backtest_trades": "backtest_trades",
    "cmc_backtest_metrics": "backtest_metrics",
    # --- Analysis ---
    "cmc_asset_stats": "asset_stats",
    "cmc_asset_stats_state": "asset_stats_state",
    "cmc_cross_asset_corr": "cross_asset_corr",
    "cmc_cross_asset_corr_state": "cross_asset_corr_state",
    "cmc_ic_results": "ic_results",
    "cmc_feature_experiments": "feature_experiments",
    "cmc_triple_barrier_labels": "triple_barrier_labels",
    "cmc_meta_label_results": "meta_label_results",
    # --- Trading/Execution ---
    "cmc_orders": "orders",
    "cmc_fills": "fills",
    "cmc_positions": "positions",
    "cmc_order_events": "order_events",
    "cmc_order_dead_letter": "order_dead_letter",
    "cmc_executor_run_log": "executor_run_log",
    "cmc_portfolio_allocations": "portfolio_allocations",
    # --- Risk ---
    "cmc_risk_events": "risk_events",
    "cmc_risk_overrides": "risk_overrides",
    # --- Drift ---
    "cmc_drift_metrics": "drift_metrics",
    # --- Macro ---
    "cmc_macro_regimes": "macro_regimes",
    "cmc_macro_hysteresis_state": "macro_hysteresis_state",
    "cmc_macro_lead_lag_results": "macro_lead_lag_results",
    "cmc_macro_transition_probs": "macro_transition_probs",
    "cmc_macro_stress_history": "macro_stress_history",
    "cmc_macro_alert_log": "macro_alert_log",
    "cmc_hmm_regimes": "hmm_regimes",
    # --- Cross-Asset ---
    "cmc_cross_asset_agg": "cross_asset_agg",
    "cmc_funding_rate_agg": "funding_rate_agg",
    "cmc_funding_rates": "funding_rates",
    "cmc_margin_config": "margin_config",
    "cmc_perp_positions": "perp_positions",
    # --- ML ---
    "cmc_ml_experiments": "ml_experiments",
}

# Sort longest-first to prevent partial matches
TABLE_RENAME_MAP: OrderedDict[str, str] = OrderedDict(
    sorted(_RAW_TABLE_RENAME_MAP.items(), key=lambda kv: -len(kv[0]))
)

# ─────────────────────────────────────────────────────────────────────
# VIEW_RENAME_MAP: old_view -> new_view
# ─────────────────────────────────────────────────────────────────────
VIEW_RENAME_MAP: dict[str, str] = {
    # Regular views
    "cmc_price_with_emas": "price_with_emas",
    "cmc_price_with_emas_d1d2": "price_with_emas_d1d2",
    "v_cmc_positions_agg": "v_positions_agg",
    # all_emas: keep name, just update refs inside
    # price_histories_u: keep name, just update refs inside
}

# Materialized views (must DROP + CREATE, not ALTER RENAME)
MATVIEW_RENAME_MAP: dict[str, str] = {
    "cmc_corr_latest": "corr_latest",
    # v_drift_summary: keep name, just update refs inside
}

# ─────────────────────────────────────────────────────────────────────
# VENUE_ID_TABLES: tables getting venue_id added to PK
# Maps new_table_name -> (old_pk_cols, new_pk_cols_with_venue_id)
# ─────────────────────────────────────────────────────────────────────
VENUE_ID_TABLES: dict[str, tuple[list[str], list[str]]] = {
    # --- Price Bars (use bar_seq not ts) ---
    "price_bars_multi_tf": (
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    "price_bars_multi_tf_cal_iso": (
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    "price_bars_multi_tf_cal_us": (
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    "price_bars_multi_tf_cal_anchor_iso": (
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    "price_bars_multi_tf_cal_anchor_us": (
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    "price_bars_multi_tf_u": (
        ["id", "tf", "bar_seq", "alignment_source"],
        ["id", "venue_id", "tf", "bar_seq", "alignment_source"],
    ),
    # --- Bar Returns (use timestamp) ---
    "returns_bars_multi_tf": (
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    "returns_bars_multi_tf_cal_iso": (
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    "returns_bars_multi_tf_cal_us": (
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    "returns_bars_multi_tf_cal_anchor_iso": (
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    "returns_bars_multi_tf_cal_anchor_us": (
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    "returns_bars_multi_tf_u": (
        ["id", "timestamp", "tf", "alignment_source"],
        ["id", "venue_id", "timestamp", "tf", "alignment_source"],
    ),
    # --- EMAs ---
    "ema_multi_tf": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "ema_multi_tf_cal_iso": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "ema_multi_tf_cal_us": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "ema_multi_tf_cal_anchor_iso": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "ema_multi_tf_cal_anchor_us": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "ema_multi_tf_u": (
        ["id", "ts", "tf", "period", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "period", "alignment_source"],
    ),
    # --- EMA Returns ---
    "returns_ema_multi_tf": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "returns_ema_multi_tf_cal_iso": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "returns_ema_multi_tf_cal_us": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "returns_ema_multi_tf_cal_anchor_iso": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "returns_ema_multi_tf_cal_anchor_us": (
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    "returns_ema_multi_tf_u": (
        ["id", "ts", "tf", "period", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "period", "alignment_source"],
    ),
    # --- AMAs ---
    "ama_multi_tf": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "ama_multi_tf_cal_iso": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "ama_multi_tf_cal_us": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "ama_multi_tf_cal_anchor_iso": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "ama_multi_tf_cal_anchor_us": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "ama_multi_tf_u": (
        ["id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
    ),
    # --- AMA Returns ---
    "returns_ama_multi_tf": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "returns_ama_multi_tf_cal_iso": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "returns_ama_multi_tf_cal_us": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "returns_ama_multi_tf_cal_anchor_iso": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "returns_ama_multi_tf_cal_anchor_us": (
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    "returns_ama_multi_tf_u": (
        ["id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
    ),
    # --- Features ---
    "features": (
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    # --- Signals ---
    "signals_ema_crossover": (
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    "signals_rsi_mean_revert": (
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    "signals_atr_breakout": (
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    # --- Regimes ---
    "regimes": (
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    # --- Analysis ---
    "asset_stats": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "cross_asset_corr": (
        ["id_a", "id_b", "tf"],
        ["id_a", "id_b", "venue_id", "tf"],
    ),
    # --- State tables ---
    "price_bars_multi_tf_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "price_bars_multi_tf_cal_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "price_bars_multi_tf_cal_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "price_bars_multi_tf_cal_anchor_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "price_bars_multi_tf_cal_anchor_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_bars_multi_tf_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_bars_multi_tf_cal_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_bars_multi_tf_cal_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_bars_multi_tf_cal_anchor_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_bars_multi_tf_cal_anchor_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ema_multi_tf_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ema_multi_tf_cal_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ema_multi_tf_cal_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ema_multi_tf_cal_anchor_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ema_multi_tf_cal_anchor_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ema_multi_tf_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ema_multi_tf_cal_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ema_multi_tf_cal_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ema_multi_tf_cal_anchor_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ema_multi_tf_cal_anchor_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ama_multi_tf_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ama_multi_tf_cal_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ama_multi_tf_cal_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ama_multi_tf_cal_anchor_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "ama_multi_tf_cal_anchor_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ama_multi_tf_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ama_multi_tf_cal_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ama_multi_tf_cal_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ama_multi_tf_cal_anchor_iso_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "returns_ama_multi_tf_cal_anchor_us_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "feature_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "signal_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "asset_stats_state": (
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    "cross_asset_corr_state": (
        ["id_a", "id_b", "tf"],
        ["id_a", "id_b", "venue_id", "tf"],
    ),
}

# ─────────────────────────────────────────────────────────────────────
# FILE_RENAME_MAP: old_path -> new_path (relative to src/ta_lab2/)
# ─────────────────────────────────────────────────────────────────────
FILE_RENAME_MAP: dict[str, str] = {
    # --- Bars ---
    "scripts/bars/refresh_cmc_price_bars_1d.py": "scripts/bars/refresh_price_bars_1d.py",
    "scripts/bars/refresh_cmc_price_bars_multi_tf.py": "scripts/bars/refresh_price_bars_multi_tf.py",
    "scripts/bars/refresh_cmc_price_bars_multi_tf_cal_iso.py": "scripts/bars/refresh_price_bars_multi_tf_cal_iso.py",
    "scripts/bars/refresh_cmc_price_bars_multi_tf_cal_us.py": "scripts/bars/refresh_price_bars_multi_tf_cal_us.py",
    "scripts/bars/refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py": "scripts/bars/refresh_price_bars_multi_tf_cal_anchor_iso.py",
    "scripts/bars/refresh_cmc_price_bars_multi_tf_cal_anchor_us.py": "scripts/bars/refresh_price_bars_multi_tf_cal_anchor_us.py",
    "scripts/bars/sync_cmc_price_bars_multi_tf_u.py": "scripts/bars/sync_price_bars_multi_tf_u.py",
    # --- EMAs ---
    "scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py": "scripts/emas/refresh_ema_multi_tf_from_bars.py",
    "scripts/emas/refresh_cmc_ema_multi_tf_cal_from_bars.py": "scripts/emas/refresh_ema_multi_tf_cal_from_bars.py",
    "scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py": "scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py",
    "scripts/emas/sync_cmc_ema_multi_tf_u.py": "scripts/emas/sync_ema_multi_tf_u.py",
    # --- AMAs ---
    "scripts/amas/refresh_cmc_ama_multi_tf.py": "scripts/amas/refresh_ama_multi_tf.py",
    "scripts/amas/refresh_cmc_ama_multi_tf_cal_from_bars.py": "scripts/amas/refresh_ama_multi_tf_cal_from_bars.py",
    "scripts/amas/refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py": "scripts/amas/refresh_ama_multi_tf_cal_anchor_from_bars.py",
    "scripts/amas/refresh_cmc_returns_ama.py": "scripts/amas/refresh_returns_ama.py",
    "scripts/amas/sync_cmc_ama_multi_tf_u.py": "scripts/amas/sync_ama_multi_tf_u.py",
    "scripts/amas/sync_cmc_returns_ama_multi_tf_u.py": "scripts/amas/sync_returns_ama_multi_tf_u.py",
    # --- Returns ---
    "scripts/returns/refresh_cmc_returns_bars_multi_tf.py": "scripts/returns/refresh_returns_bars_multi_tf.py",
    "scripts/returns/refresh_cmc_returns_bars_multi_tf_cal_iso.py": "scripts/returns/refresh_returns_bars_multi_tf_cal_iso.py",
    "scripts/returns/refresh_cmc_returns_bars_multi_tf_cal_us.py": "scripts/returns/refresh_returns_bars_multi_tf_cal_us.py",
    "scripts/returns/refresh_cmc_returns_bars_multi_tf_cal_anchor_iso.py": "scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_iso.py",
    "scripts/returns/refresh_cmc_returns_bars_multi_tf_cal_anchor_us.py": "scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_us.py",
    "scripts/returns/refresh_cmc_returns_ema_multi_tf.py": "scripts/returns/refresh_returns_ema_multi_tf.py",
    "scripts/returns/refresh_cmc_returns_ema_multi_tf_cal.py": "scripts/returns/refresh_returns_ema_multi_tf_cal.py",
    "scripts/returns/refresh_cmc_returns_ema_multi_tf_cal_anchor.py": "scripts/returns/refresh_returns_ema_multi_tf_cal_anchor.py",
    "scripts/returns/refresh_cmc_returns_d1.py": "scripts/returns/refresh_returns_d1.py",
    "scripts/returns/sync_cmc_returns_bars_multi_tf_u.py": "scripts/returns/sync_returns_bars_multi_tf_u.py",
    "scripts/returns/sync_cmc_returns_ema_multi_tf_u.py": "scripts/returns/sync_returns_ema_multi_tf_u.py",
    # --- Features ---
    "scripts/features/refresh_cmc_vol_daily.py": "scripts/features/refresh_vol_daily.py",
    "scripts/features/refresh_cmc_ta_daily.py": "scripts/features/refresh_ta_daily.py",
    "scripts/features/refresh_cmc_returns_daily.py": "scripts/features/refresh_returns_daily.py",
    "scripts/features/refresh_cmc_daily_features.py": "scripts/features/refresh_daily_features.py",
    "scripts/features/refresh_cmc_cs_norms.py": "scripts/features/refresh_cs_norms.py",
    "scripts/features/refresh_cmc_features_stats.py": "scripts/features/refresh_features_stats.py",
    # --- Signals ---
    "scripts/signals/refresh_cmc_signals_ema_crossover.py": "scripts/signals/refresh_signals_ema_crossover.py",
    "scripts/signals/refresh_cmc_signals_rsi_mean_revert.py": "scripts/signals/refresh_signals_rsi_mean_revert.py",
    "scripts/signals/refresh_cmc_signals_atr_breakout.py": "scripts/signals/refresh_signals_atr_breakout.py",
    # --- Desc Stats ---
    "scripts/desc_stats/refresh_cmc_asset_stats.py": "scripts/desc_stats/refresh_asset_stats.py",
    "scripts/desc_stats/refresh_cmc_cross_asset_corr.py": "scripts/desc_stats/refresh_cross_asset_corr.py",
    # --- Regimes ---
    "scripts/regimes/refresh_cmc_regimes.py": "scripts/regimes/refresh_regimes.py",
    # --- ETL ---
    "scripts/etl/update_cmc_history.py": "scripts/etl/update_history.py",
}


def apply_renames_to_content(content: str) -> str:
    """Apply TABLE_RENAME_MAP to content, longest-first to prevent partial matches."""
    for old, new in TABLE_RENAME_MAP.items():
        content = content.replace(old, new)
    # Also apply view renames
    for old, new in VIEW_RENAME_MAP.items():
        content = content.replace(old, new)
    for old, new in MATVIEW_RENAME_MAP.items():
        content = content.replace(old, new)
    return content


def should_skip_path(path: str) -> bool:
    """Check if a path should be skipped during bulk renaming."""
    parts = path.replace("\\", "/").split("/")
    for skip in SKIP_DIRS:
        if skip in parts:
            return True
    return False
