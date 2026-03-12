"""strip_cmc_prefix_add_venue_id

Combined migration:
1. Create dim_venues reference table with 9 seed venues
2. Drop views/matviews that depend on tables being renamed
3. Rename ~80 tables (strip cmc_ prefix)
4. Add venue_id SMALLINT NOT NULL DEFAULT 1 to analytics tables
5. Drop old PKs, add new PKs with venue_id
6. Add venue_id FK to dim_venues
7. Add venue_id to dim_listings
8. Recreate views/matviews with updated references

PK index rebuilds on large tables (~91M AMA, ~14M EMA) are the slow part.
Estimated total: 2-3 hours on local dev. No data recomputation.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: a0b1c2d3e4f5
Revises: f7a8b9c0d1e2
Create Date: 2026-03-12
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Table rename map: old_name -> new_name
# Only tables that actually have the cmc_ prefix get renamed.
# Excluded (genuinely CMC-only): cmc_da_ids, cmc_da_info, cmc_exchange_map,
#   cmc_exchange_info, cmc_price_histories7
# ---------------------------------------------------------------------------
TABLE_RENAMES: list[tuple[str, str]] = [
    # --- Price Bars ---
    ("cmc_price_bars_1d", "price_bars_1d"),
    ("cmc_price_bars_1d_state", "price_bars_1d_state"),
    ("cmc_price_bars_multi_tf", "price_bars_multi_tf"),
    ("cmc_price_bars_multi_tf_state", "price_bars_multi_tf_state"),
    ("cmc_price_bars_multi_tf_cal_iso", "price_bars_multi_tf_cal_iso"),
    ("cmc_price_bars_multi_tf_cal_iso_state", "price_bars_multi_tf_cal_iso_state"),
    ("cmc_price_bars_multi_tf_cal_us", "price_bars_multi_tf_cal_us"),
    ("cmc_price_bars_multi_tf_cal_us_state", "price_bars_multi_tf_cal_us_state"),
    ("cmc_price_bars_multi_tf_cal_anchor_iso", "price_bars_multi_tf_cal_anchor_iso"),
    (
        "cmc_price_bars_multi_tf_cal_anchor_iso_state",
        "price_bars_multi_tf_cal_anchor_iso_state",
    ),
    ("cmc_price_bars_multi_tf_cal_anchor_us", "price_bars_multi_tf_cal_anchor_us"),
    (
        "cmc_price_bars_multi_tf_cal_anchor_us_state",
        "price_bars_multi_tf_cal_anchor_us_state",
    ),
    ("cmc_price_bars_multi_tf_u", "price_bars_multi_tf_u"),
    # --- EMAs ---
    ("cmc_ema_multi_tf", "ema_multi_tf"),
    ("cmc_ema_multi_tf_state", "ema_multi_tf_state"),
    ("cmc_ema_multi_tf_cal_iso", "ema_multi_tf_cal_iso"),
    ("cmc_ema_multi_tf_cal_iso_state", "ema_multi_tf_cal_iso_state"),
    ("cmc_ema_multi_tf_cal_us", "ema_multi_tf_cal_us"),
    ("cmc_ema_multi_tf_cal_us_state", "ema_multi_tf_cal_us_state"),
    ("cmc_ema_multi_tf_cal_anchor_iso", "ema_multi_tf_cal_anchor_iso"),
    ("cmc_ema_multi_tf_cal_anchor_iso_state", "ema_multi_tf_cal_anchor_iso_state"),
    ("cmc_ema_multi_tf_cal_anchor_us", "ema_multi_tf_cal_anchor_us"),
    ("cmc_ema_multi_tf_cal_anchor_us_state", "ema_multi_tf_cal_anchor_us_state"),
    ("cmc_ema_multi_tf_u", "ema_multi_tf_u"),
    # --- AMAs ---
    ("cmc_ama_multi_tf", "ama_multi_tf"),
    ("cmc_ama_multi_tf_state", "ama_multi_tf_state"),
    ("cmc_ama_multi_tf_cal_iso", "ama_multi_tf_cal_iso"),
    ("cmc_ama_multi_tf_cal_iso_state", "ama_multi_tf_cal_iso_state"),
    ("cmc_ama_multi_tf_cal_us", "ama_multi_tf_cal_us"),
    ("cmc_ama_multi_tf_cal_us_state", "ama_multi_tf_cal_us_state"),
    ("cmc_ama_multi_tf_cal_anchor_iso", "ama_multi_tf_cal_anchor_iso"),
    ("cmc_ama_multi_tf_cal_anchor_iso_state", "ama_multi_tf_cal_anchor_iso_state"),
    ("cmc_ama_multi_tf_cal_anchor_us", "ama_multi_tf_cal_anchor_us"),
    ("cmc_ama_multi_tf_cal_anchor_us_state", "ama_multi_tf_cal_anchor_us_state"),
    ("cmc_ama_multi_tf_u", "ama_multi_tf_u"),
    # --- Bar Returns ---
    ("cmc_returns_bars_multi_tf", "returns_bars_multi_tf"),
    ("cmc_returns_bars_multi_tf_state", "returns_bars_multi_tf_state"),
    ("cmc_returns_bars_multi_tf_cal_iso", "returns_bars_multi_tf_cal_iso"),
    ("cmc_returns_bars_multi_tf_cal_iso_state", "returns_bars_multi_tf_cal_iso_state"),
    ("cmc_returns_bars_multi_tf_cal_us", "returns_bars_multi_tf_cal_us"),
    ("cmc_returns_bars_multi_tf_cal_us_state", "returns_bars_multi_tf_cal_us_state"),
    (
        "cmc_returns_bars_multi_tf_cal_anchor_iso",
        "returns_bars_multi_tf_cal_anchor_iso",
    ),
    (
        "cmc_returns_bars_multi_tf_cal_anchor_iso_state",
        "returns_bars_multi_tf_cal_anchor_iso_state",
    ),
    ("cmc_returns_bars_multi_tf_cal_anchor_us", "returns_bars_multi_tf_cal_anchor_us"),
    (
        "cmc_returns_bars_multi_tf_cal_anchor_us_state",
        "returns_bars_multi_tf_cal_anchor_us_state",
    ),
    ("cmc_returns_bars_multi_tf_u", "returns_bars_multi_tf_u"),
    # --- EMA Returns ---
    ("cmc_returns_ema_multi_tf", "returns_ema_multi_tf"),
    ("cmc_returns_ema_multi_tf_state", "returns_ema_multi_tf_state"),
    ("cmc_returns_ema_multi_tf_cal_iso", "returns_ema_multi_tf_cal_iso"),
    ("cmc_returns_ema_multi_tf_cal_iso_state", "returns_ema_multi_tf_cal_iso_state"),
    ("cmc_returns_ema_multi_tf_cal_us", "returns_ema_multi_tf_cal_us"),
    ("cmc_returns_ema_multi_tf_cal_us_state", "returns_ema_multi_tf_cal_us_state"),
    ("cmc_returns_ema_multi_tf_cal_anchor_iso", "returns_ema_multi_tf_cal_anchor_iso"),
    (
        "cmc_returns_ema_multi_tf_cal_anchor_iso_state",
        "returns_ema_multi_tf_cal_anchor_iso_state",
    ),
    ("cmc_returns_ema_multi_tf_cal_anchor_us", "returns_ema_multi_tf_cal_anchor_us"),
    (
        "cmc_returns_ema_multi_tf_cal_anchor_us_state",
        "returns_ema_multi_tf_cal_anchor_us_state",
    ),
    ("cmc_returns_ema_multi_tf_u", "returns_ema_multi_tf_u"),
    # --- AMA Returns ---
    ("cmc_returns_ama_multi_tf", "returns_ama_multi_tf"),
    ("cmc_returns_ama_multi_tf_state", "returns_ama_multi_tf_state"),
    ("cmc_returns_ama_multi_tf_cal_iso", "returns_ama_multi_tf_cal_iso"),
    ("cmc_returns_ama_multi_tf_cal_iso_state", "returns_ama_multi_tf_cal_iso_state"),
    ("cmc_returns_ama_multi_tf_cal_us", "returns_ama_multi_tf_cal_us"),
    ("cmc_returns_ama_multi_tf_cal_us_state", "returns_ama_multi_tf_cal_us_state"),
    ("cmc_returns_ama_multi_tf_cal_anchor_iso", "returns_ama_multi_tf_cal_anchor_iso"),
    (
        "cmc_returns_ama_multi_tf_cal_anchor_iso_state",
        "returns_ama_multi_tf_cal_anchor_iso_state",
    ),
    ("cmc_returns_ama_multi_tf_cal_anchor_us", "returns_ama_multi_tf_cal_anchor_us"),
    (
        "cmc_returns_ama_multi_tf_cal_anchor_us_state",
        "returns_ama_multi_tf_cal_anchor_us_state",
    ),
    ("cmc_returns_ama_multi_tf_u", "returns_ama_multi_tf_u"),
    # --- Features ---
    ("cmc_features", "features"),
    ("cmc_feature_state", "feature_state"),
    ("cmc_ta", "ta"),
    ("cmc_vol", "vol"),
    ("cmc_ta_daily", "ta_daily"),
    ("cmc_vol_daily", "vol_daily"),
    ("cmc_returns_daily", "returns_daily"),
    ("cmc_cycle_stats", "cycle_stats"),
    ("cmc_rolling_extremes", "rolling_extremes"),
    ("cmc_cs_norms", "cs_norms"),
    ("cmc_features_stats", "features_stats"),
    # --- Signals ---
    ("cmc_signals_ema_crossover", "signals_ema_crossover"),
    ("cmc_signals_rsi_mean_revert", "signals_rsi_mean_revert"),
    ("cmc_signals_atr_breakout", "signals_atr_breakout"),
    ("cmc_signal_state", "signal_state"),
    # --- Regimes ---
    ("cmc_regimes", "regimes"),
    ("cmc_regime_flips", "regime_flips"),
    ("cmc_regime_stats", "regime_stats"),
    ("cmc_regime_comovement", "regime_comovement"),
    # --- Backtests ---
    ("cmc_backtest_runs", "backtest_runs"),
    ("cmc_backtest_trades", "backtest_trades"),
    ("cmc_backtest_metrics", "backtest_metrics"),
    # --- Analysis ---
    ("cmc_asset_stats", "asset_stats"),
    ("cmc_asset_stats_state", "asset_stats_state"),
    ("cmc_cross_asset_corr", "cross_asset_corr"),
    ("cmc_cross_asset_corr_state", "cross_asset_corr_state"),
    ("cmc_ic_results", "ic_results"),
    ("cmc_feature_experiments", "feature_experiments"),
    ("cmc_triple_barrier_labels", "triple_barrier_labels"),
    ("cmc_meta_label_results", "meta_label_results"),
    # --- Trading/Execution ---
    ("cmc_orders", "orders"),
    ("cmc_fills", "fills"),
    ("cmc_positions", "positions"),
    ("cmc_order_events", "order_events"),
    ("cmc_order_dead_letter", "order_dead_letter"),
    ("cmc_executor_run_log", "executor_run_log"),
    ("cmc_portfolio_allocations", "portfolio_allocations"),
    # --- Risk ---
    ("cmc_risk_events", "risk_events"),
    ("cmc_risk_overrides", "risk_overrides"),
    # --- Drift ---
    ("cmc_drift_metrics", "drift_metrics"),
    # --- Macro ---
    ("cmc_macro_regimes", "macro_regimes"),
    ("cmc_macro_hysteresis_state", "macro_hysteresis_state"),
    ("cmc_macro_lead_lag_results", "macro_lead_lag_results"),
    ("cmc_macro_transition_probs", "macro_transition_probs"),
    ("cmc_macro_stress_history", "macro_stress_history"),
    ("cmc_macro_alert_log", "macro_alert_log"),
    ("cmc_hmm_regimes", "hmm_regimes"),
    # --- Cross-Asset ---
    ("cmc_cross_asset_agg", "cross_asset_agg"),
    ("cmc_funding_rate_agg", "funding_rate_agg"),
    ("cmc_funding_rates", "funding_rates"),
    ("cmc_margin_config", "margin_config"),
    ("cmc_perp_positions", "perp_positions"),
    # --- ML ---
    ("cmc_ml_experiments", "ml_experiments"),
]


# ---------------------------------------------------------------------------
# Tables that get venue_id added to their PK.
# Format: (new_table_name, old_pk_constraint_name, old_pk_cols, new_pk_cols)
#
# old_pk_constraint_name: PostgreSQL auto-generates as {original_tablename}_pkey
# unless an explicit name was given in the CREATE TABLE.
# After ALTER TABLE RENAME, constraint names are NOT renamed automatically.
# ---------------------------------------------------------------------------
VENUE_ID_PK_CHANGES: list[tuple[str, str, list[str], list[str]]] = [
    # --- Price Bars (bar_seq based PKs) ---
    (
        "price_bars_multi_tf",
        "cmc_price_bars_multi_tf_pkey",
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    (
        "price_bars_multi_tf_cal_iso",
        "cmc_price_bars_multi_tf_cal_iso_pkey",
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    (
        "price_bars_multi_tf_cal_us",
        "cmc_price_bars_multi_tf_cal_us_pkey",
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    (
        "price_bars_multi_tf_cal_anchor_iso",
        "cmc_price_bars_multi_tf_cal_anchor_iso_pkey",
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    (
        "price_bars_multi_tf_cal_anchor_us",
        "cmc_price_bars_multi_tf_cal_anchor_us_pkey",
        ["id", "tf", "bar_seq"],
        ["id", "venue_id", "tf", "bar_seq"],
    ),
    (
        "price_bars_multi_tf_u",
        "cmc_price_bars_multi_tf_u_pkey",
        ["id", "tf", "bar_seq", "alignment_source"],
        ["id", "venue_id", "tf", "bar_seq", "alignment_source"],
    ),
    # --- Bar Returns (timestamp based PKs) ---
    (
        "returns_bars_multi_tf",
        "cmc_returns_bars_multi_tf_pkey",
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_iso",
        "cmc_returns_bars_multi_tf_cal_iso_pkey",
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_us",
        "cmc_returns_bars_multi_tf_cal_us_pkey",
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_anchor_iso",
        "cmc_returns_bars_multi_tf_cal_anchor_iso_pkey",
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_anchor_us",
        "cmc_returns_bars_multi_tf_cal_anchor_us_pkey",
        ["id", "timestamp", "tf"],
        ["id", "venue_id", "timestamp", "tf"],
    ),
    (
        "returns_bars_multi_tf_u",
        "cmc_returns_bars_multi_tf_u_pkey",
        ["id", "timestamp", "tf", "alignment_source"],
        ["id", "venue_id", "timestamp", "tf", "alignment_source"],
    ),
    # --- EMAs ---
    (
        "ema_multi_tf",
        "cmc_ema_multi_tf_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "ema_multi_tf_cal_iso",
        "cmc_ema_multi_tf_cal_iso_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "ema_multi_tf_cal_us",
        "cmc_ema_multi_tf_cal_us_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "ema_multi_tf_cal_anchor_iso",
        "cmc_ema_multi_tf_cal_anchor_iso_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "ema_multi_tf_cal_anchor_us",
        "cmc_ema_multi_tf_cal_anchor_us_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "ema_multi_tf_u",
        "cmc_ema_multi_tf_u_pkey",
        ["id", "ts", "tf", "period", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "period", "alignment_source"],
    ),
    # --- EMA Returns ---
    (
        "returns_ema_multi_tf",
        "cmc_returns_ema_multi_tf_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "returns_ema_multi_tf_cal_iso",
        "cmc_returns_ema_multi_tf_cal_iso_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "returns_ema_multi_tf_cal_us",
        "cmc_returns_ema_multi_tf_cal_us_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "returns_ema_multi_tf_cal_anchor_iso",
        "cmc_returns_ema_multi_tf_cal_anchor_iso_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "returns_ema_multi_tf_cal_anchor_us",
        "cmc_returns_ema_multi_tf_cal_anchor_us_pkey",
        ["id", "ts", "tf", "period"],
        ["id", "venue_id", "ts", "tf", "period"],
    ),
    (
        "returns_ema_multi_tf_u",
        "cmc_returns_ema_multi_tf_u_pkey",
        ["id", "ts", "tf", "period", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "period", "alignment_source"],
    ),
    # --- AMAs ---
    (
        "ama_multi_tf",
        "cmc_ama_multi_tf_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "ama_multi_tf_cal_iso",
        "cmc_ama_multi_tf_cal_iso_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "ama_multi_tf_cal_us",
        "cmc_ama_multi_tf_cal_us_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "ama_multi_tf_cal_anchor_iso",
        "cmc_ama_multi_tf_cal_anchor_iso_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "ama_multi_tf_cal_anchor_us",
        "cmc_ama_multi_tf_cal_anchor_us_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "ama_multi_tf_u",
        "cmc_ama_multi_tf_u_pkey",
        ["id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
    ),
    # --- AMA Returns ---
    (
        "returns_ama_multi_tf",
        "cmc_returns_ama_multi_tf_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "returns_ama_multi_tf_cal_iso",
        "cmc_returns_ama_multi_tf_cal_iso_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "returns_ama_multi_tf_cal_us",
        "cmc_returns_ama_multi_tf_cal_us_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "returns_ama_multi_tf_cal_anchor_iso",
        "cmc_returns_ama_multi_tf_cal_anchor_iso_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "returns_ama_multi_tf_cal_anchor_us",
        "cmc_returns_ama_multi_tf_cal_anchor_us_pkey",
        ["id", "ts", "tf", "indicator", "params_hash"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash"],
    ),
    (
        "returns_ama_multi_tf_u",
        "cmc_returns_ama_multi_tf_u_pkey",
        ["id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
        ["id", "venue_id", "ts", "tf", "indicator", "params_hash", "alignment_source"],
    ),
    # --- Features ---
    (
        "features",
        "cmc_features_pkey",
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    # --- Signals ---
    (
        "signals_ema_crossover",
        "cmc_signals_ema_crossover_pkey",
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    (
        "signals_rsi_mean_revert",
        "cmc_signals_rsi_mean_revert_pkey",
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    (
        "signals_atr_breakout",
        "cmc_signals_atr_breakout_pkey",
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    # --- Regimes ---
    ("regimes", "cmc_regimes_pkey", ["id", "ts", "tf"], ["id", "venue_id", "ts", "tf"]),
    # --- Analysis ---
    (
        "asset_stats",
        "cmc_asset_stats_pkey",
        ["id", "ts", "tf"],
        ["id", "venue_id", "ts", "tf"],
    ),
    (
        "cross_asset_corr",
        "cmc_cross_asset_corr_pkey",
        ["id_a", "id_b", "ts", "tf", "window"],
        ["id_a", "id_b", "venue_id", "ts", "tf", "window"],
    ),
    # --- State tables ---
    (
        "price_bars_multi_tf_state",
        "cmc_price_bars_multi_tf_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "price_bars_multi_tf_cal_iso_state",
        "cmc_price_bars_multi_tf_cal_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "price_bars_multi_tf_cal_us_state",
        "cmc_price_bars_multi_tf_cal_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "price_bars_multi_tf_cal_anchor_iso_state",
        "cmc_price_bars_multi_tf_cal_anchor_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "price_bars_multi_tf_cal_anchor_us_state",
        "cmc_price_bars_multi_tf_cal_anchor_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_bars_multi_tf_state",
        "cmc_returns_bars_multi_tf_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_iso_state",
        "cmc_returns_bars_multi_tf_cal_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_us_state",
        "cmc_returns_bars_multi_tf_cal_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_anchor_iso_state",
        "cmc_returns_bars_multi_tf_cal_anchor_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_bars_multi_tf_cal_anchor_us_state",
        "cmc_returns_bars_multi_tf_cal_anchor_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ema_multi_tf_state",
        "cmc_ema_multi_tf_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ema_multi_tf_cal_iso_state",
        "cmc_ema_multi_tf_cal_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ema_multi_tf_cal_us_state",
        "cmc_ema_multi_tf_cal_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ema_multi_tf_cal_anchor_iso_state",
        "cmc_ema_multi_tf_cal_anchor_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ema_multi_tf_cal_anchor_us_state",
        "cmc_ema_multi_tf_cal_anchor_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ema_multi_tf_state",
        "cmc_returns_ema_multi_tf_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ema_multi_tf_cal_iso_state",
        "cmc_returns_ema_multi_tf_cal_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ema_multi_tf_cal_us_state",
        "cmc_returns_ema_multi_tf_cal_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ema_multi_tf_cal_anchor_iso_state",
        "cmc_returns_ema_multi_tf_cal_anchor_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ema_multi_tf_cal_anchor_us_state",
        "cmc_returns_ema_multi_tf_cal_anchor_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ama_multi_tf_state",
        "cmc_ama_multi_tf_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ama_multi_tf_cal_iso_state",
        "cmc_ama_multi_tf_cal_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ama_multi_tf_cal_us_state",
        "cmc_ama_multi_tf_cal_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ama_multi_tf_cal_anchor_iso_state",
        "cmc_ama_multi_tf_cal_anchor_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "ama_multi_tf_cal_anchor_us_state",
        "cmc_ama_multi_tf_cal_anchor_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ama_multi_tf_state",
        "cmc_returns_ama_multi_tf_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ama_multi_tf_cal_iso_state",
        "cmc_returns_ama_multi_tf_cal_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ama_multi_tf_cal_us_state",
        "cmc_returns_ama_multi_tf_cal_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ama_multi_tf_cal_anchor_iso_state",
        "cmc_returns_ama_multi_tf_cal_anchor_iso_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "returns_ama_multi_tf_cal_anchor_us_state",
        "cmc_returns_ama_multi_tf_cal_anchor_us_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    ("feature_state", "cmc_feature_state_pkey", ["id", "tf"], ["id", "venue_id", "tf"]),
    ("signal_state", "cmc_signal_state_pkey", ["id", "tf"], ["id", "venue_id", "tf"]),
    (
        "asset_stats_state",
        "cmc_asset_stats_state_pkey",
        ["id", "tf"],
        ["id", "venue_id", "tf"],
    ),
    (
        "cross_asset_corr_state",
        "cmc_cross_asset_corr_state_pkey",
        ["id_a", "id_b", "tf"],
        ["id_a", "id_b", "venue_id", "tf"],
    ),
]

# Tables that get venue_id column but NOT a PK change (non-analytics tables)
VENUE_ID_COLUMN_ONLY: list[str] = [
    "price_bars_1d",
    "price_bars_1d_state",
    "ta",
    "vol",
    "ta_daily",
    "vol_daily",
    "returns_daily",
    "cycle_stats",
    "rolling_extremes",
    "cs_norms",
    "features_stats",
    "regime_flips",
    "regime_stats",
    "regime_comovement",
    "backtest_runs",
    "backtest_trades",
    "backtest_metrics",
    "ic_results",
    "feature_experiments",
    "triple_barrier_labels",
    "meta_label_results",
    "drift_metrics",
    "macro_regimes",
    "macro_hysteresis_state",
    "macro_lead_lag_results",
    "macro_transition_probs",
    "macro_stress_history",
    "macro_alert_log",
    "hmm_regimes",
    "cross_asset_agg",
    "funding_rate_agg",
    "funding_rates",
    "margin_config",
    "perp_positions",
    "ml_experiments",
    "orders",
    "fills",
    "positions",
    "order_events",
    "order_dead_letter",
    "executor_run_log",
    "portfolio_allocations",
    "risk_events",
    "risk_overrides",
]


def upgrade() -> None:
    """Upgrade: create dim_venues, rename tables, add venue_id, rebuild PKs."""

    # ==================================================================
    # Step 1: Create dim_venues reference table
    # ==================================================================
    op.execute(
        text("""
        CREATE TABLE public.dim_venues (
            venue_id    SMALLINT PRIMARY KEY,
            venue       TEXT NOT NULL UNIQUE,
            description TEXT
        )
    """)
    )
    op.execute(
        text("""
        INSERT INTO public.dim_venues (venue_id, venue, description) VALUES
            (1, 'CMC_AGG',      'CoinMarketCap aggregate'),
            (2, 'HYPERLIQUID',  'Hyperliquid DEX'),
            (3, 'BYBIT',        'Bybit exchange'),
            (4, 'KRAKEN',       'Kraken exchange'),
            (5, 'GATE',         'Gate.io exchange'),
            (6, 'COINBASE',     'Coinbase exchange'),
            (7, 'OKX',          'OKX exchange'),
            (8, 'BATS',         'BATS/Cboe BZX exchange'),
            (9, 'NASDAQ',       'NASDAQ exchange'),
            (10, 'NYSE',        'New York Stock Exchange')
    """)
    )

    # ==================================================================
    # Step 2: Drop views/matviews that reference tables being renamed
    # ==================================================================
    op.execute(text("DROP MATERIALIZED VIEW IF EXISTS public.cmc_corr_latest"))
    op.execute(text("DROP MATERIALIZED VIEW IF EXISTS public.v_drift_summary"))
    op.execute(text("DROP VIEW IF EXISTS public.v_cmc_positions_agg"))
    op.execute(text("DROP VIEW IF EXISTS public.cmc_price_with_emas_d1d2"))
    op.execute(text("DROP VIEW IF EXISTS public.cmc_price_with_emas"))
    op.execute(text("DROP VIEW IF EXISTS public.all_emas"))
    op.execute(text("DROP VIEW IF EXISTS public.price_histories_u"))

    # ==================================================================
    # Step 3: Rename all tables (instant -- PostgreSQL tracks by OID)
    # ==================================================================
    for old_name, new_name in TABLE_RENAMES:
        op.execute(
            text(f"ALTER TABLE IF EXISTS public.{old_name} RENAME TO {new_name}")
        )

    # ==================================================================
    # Step 4: Add venue_id column to analytics tables (PK change tables)
    # Instant in PG 11+ when adding with DEFAULT (no table rewrite)
    # ==================================================================
    all_venue_tables = set()
    for new_name, _, _, _ in VENUE_ID_PK_CHANGES:
        all_venue_tables.add(new_name)
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"ADD COLUMN IF NOT EXISTS venue_id SMALLINT NOT NULL DEFAULT 1"
            )
        )

    # Add venue_id to non-PK-change tables too
    for new_name in VENUE_ID_COLUMN_ONLY:
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"ADD COLUMN IF NOT EXISTS venue_id SMALLINT NOT NULL DEFAULT 1"
            )
        )

    # ==================================================================
    # Step 5: Drop old PKs and add new PKs with venue_id
    # This is the SLOW part -- index rebuild on large tables
    # ==================================================================
    for new_name, old_pk_name, old_pk_cols, new_pk_cols in VENUE_ID_PK_CHANGES:
        pk_cols_str = ", ".join(new_pk_cols)
        new_pk_name = f"{new_name}_pkey"
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"DROP CONSTRAINT IF EXISTS {old_pk_name} CASCADE"
            )
        )
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"ADD CONSTRAINT {new_pk_name} PRIMARY KEY ({pk_cols_str})"
            )
        )

    # ==================================================================
    # Step 6: Add FK constraints to dim_venues
    # ==================================================================
    for new_name, _, _, _ in VENUE_ID_PK_CHANGES:
        fk_name = f"fk_{new_name}_venue"
        # Truncate FK name if > 63 chars (PG identifier limit)
        if len(fk_name) > 63:
            fk_name = fk_name[:63]
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY (venue_id) REFERENCES public.dim_venues(venue_id)"
            )
        )

    for new_name in VENUE_ID_COLUMN_ONLY:
        fk_name = f"fk_{new_name}_venue"
        if len(fk_name) > 63:
            fk_name = fk_name[:63]
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY (venue_id) REFERENCES public.dim_venues(venue_id)"
            )
        )

    # ==================================================================
    # Step 7: Add venue_id FK to dim_listings
    # ==================================================================
    op.execute(
        text("""
        ALTER TABLE public.dim_listings
        ADD COLUMN IF NOT EXISTS venue_id SMALLINT
    """)
    )
    op.execute(
        text("""
        UPDATE public.dim_listings SET venue_id = dv.venue_id
        FROM public.dim_venues dv
        WHERE dim_listings.venue = dv.venue
    """)
    )
    op.execute(
        text("""
        ALTER TABLE public.dim_listings
        ADD CONSTRAINT fk_listings_venue
        FOREIGN KEY (venue_id) REFERENCES public.dim_venues(venue_id)
    """)
    )

    # ==================================================================
    # Step 7b: Set venue_id from existing venue TEXT column
    # 41 tables already have a venue TEXT column with the actual exchange
    # name (e.g., 'GATE', 'BYBIT', 'CMC_AGG'). Use that to set venue_id
    # per row via JOIN to dim_venues, rather than blanket per-asset.
    # Tables without a venue column keep venue_id=1 (CMC_AGG default).
    # ==================================================================

    # Tables that have a venue TEXT column (after rename)
    _TABLES_WITH_VENUE_COL = [
        # Price bars
        "price_bars_1d",
        "price_bars_multi_tf",
        "price_bars_multi_tf_cal_iso",
        "price_bars_multi_tf_cal_us",
        "price_bars_multi_tf_cal_anchor_iso",
        "price_bars_multi_tf_cal_anchor_us",
        "price_bars_multi_tf_u",
        # Price bar state
        "price_bars_multi_tf_state",
        "price_bars_multi_tf_cal_iso_state",
        "price_bars_multi_tf_cal_us_state",
        "price_bars_multi_tf_cal_anchor_iso_state",
        "price_bars_multi_tf_cal_anchor_us_state",
        # Bar returns
        "returns_bars_multi_tf",
        "returns_bars_multi_tf_cal_iso",
        "returns_bars_multi_tf_cal_us",
        "returns_bars_multi_tf_cal_anchor_iso",
        "returns_bars_multi_tf_cal_anchor_us",
        "returns_bars_multi_tf_u",
        # Bar returns state
        "returns_bars_multi_tf_state",
        "returns_bars_multi_tf_cal_iso_state",
        "returns_bars_multi_tf_cal_us_state",
        "returns_bars_multi_tf_cal_anchor_iso_state",
        "returns_bars_multi_tf_cal_anchor_us_state",
        # EMA
        "ema_multi_tf_cal_iso",
        "ema_multi_tf_cal_us",
        "ema_multi_tf_u",
        # EMA returns
        "returns_ema_multi_tf",
        "returns_ema_multi_tf_cal_iso",
        "returns_ema_multi_tf_cal_us",
        "returns_ema_multi_tf_cal_anchor_iso",
        "returns_ema_multi_tf_cal_anchor_us",
        "returns_ema_multi_tf_u",
        "returns_ema_multi_tf_state",
        # Features
        "features",
        "ta",
        "vol",
        "cycle_stats",
        "rolling_extremes",
        # Perps (already venue-based)
        "funding_rates",
        "margin_config",
        "perp_positions",
    ]

    for tbl in _TABLES_WITH_VENUE_COL:
        op.execute(
            text(
                f"UPDATE public.{tbl} t SET venue_id = dv.venue_id "
                f"FROM public.dim_venues dv "
                f"WHERE t.venue = dv.venue AND t.venue_id = 1 AND t.venue != 'CMC_AGG'"
            )
        )

    # For equities with venue='BATS', map to actual listing exchange.
    # BATS is a secondary exchange; the real primary is NYSE or NASDAQ.
    # FBTC (100001) is actually BATS-listed (Cboe BZX ETF).
    _EQUITY_VENUE_MAP = [
        # (venue_id, asset_ids)
        (
            9,
            [100002, 100004, 100006, 100007, 100008],
        ),  # NASDAQ: GOOGL, IBIT, MARA, MSTR, NVDA
        (10, [100003, 100005, 100009]),  # NYSE: GS, KO, WMT
        # FBTC (100001) stays BATS (venue_id=8) -- correct
    ]
    for vid, ids in _EQUITY_VENUE_MAP:
        id_list = ", ".join(str(i) for i in ids)
        for tbl in _TABLES_WITH_VENUE_COL:
            op.execute(
                text(
                    f"UPDATE public.{tbl} SET venue_id = {vid} "
                    f"WHERE id IN ({id_list}) AND venue = 'BATS'"
                )
            )

    # ==================================================================
    # Step 8: Recreate views/matviews with new table names
    # ==================================================================

    # all_emas: references ema_multi_tf (was cmc_ema_multi_tf)
    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.all_emas AS
        SELECT id, ts, tf, tf_days, period, ema, roll
        FROM public.ema_multi_tf
    """)
    )

    # price_with_emas: refs cmc_price_histories7 (KEPT!) + all_emas
    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.price_with_emas AS
        SELECT
            p.*,
            e.tf,
            e.tf_days,
            e.period,
            e.ema,
            e.roll
        FROM public.cmc_price_histories7 p
        LEFT JOIN public.all_emas e
          ON e.id = p.id
         AND e.ts = p."timestamp"
    """)
    )

    # price_with_emas_d1d2: alias of price_with_emas
    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.price_with_emas_d1d2 AS
        SELECT * FROM public.price_with_emas
    """)
    )

    # v_positions_agg: refs positions (was cmc_positions)
    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.v_positions_agg AS
        SELECT
            asset_id,
            'aggregate'::TEXT AS exchange,
            SUM(quantity) AS quantity,
            CASE
                WHEN SUM(ABS(quantity)) = 0 THEN 0
                ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
            END AS avg_cost_basis,
            SUM(realized_pnl) AS realized_pnl,
            SUM(COALESCE(unrealized_pnl, 0)) AS unrealized_pnl,
            MAX(last_mark_price) AS last_mark_price,
            MAX(last_updated) AS last_updated
        FROM public.positions
        WHERE exchange != 'aggregate'
        GROUP BY asset_id
    """)
    )

    # price_histories_u: refs cmc_price_histories7 (KEPT!) + tvc_price_histories
    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.price_histories_u AS
        SELECT id, "timestamp", open, high, low, close, volume, market_cap,
               'cmc' AS source
        FROM public.cmc_price_histories7
        UNION ALL
        SELECT id, "timestamp", open, high, low, close, volume, NULL AS market_cap,
               'tvc' AS source
        FROM public.tvc_price_histories
    """)
    )

    # corr_latest materialized view: refs cross_asset_corr
    op.execute(
        text("""
        CREATE MATERIALIZED VIEW public.corr_latest AS
        SELECT DISTINCT ON (id_a, id_b, tf, "window")
            id_a, id_b, ts, tf, "window",
            pearson_r, pearson_p, spearman_r, spearman_p, n_obs
        FROM public.cross_asset_corr
        ORDER BY id_a, id_b, tf, "window", ts DESC
    """)
    )
    op.execute(
        text("""
        CREATE UNIQUE INDEX idx_corr_latest_pk
        ON public.corr_latest (id_a, id_b, tf, "window")
    """)
    )

    # v_drift_summary materialized view: refs drift_metrics
    op.execute(
        text("""
        CREATE MATERIALIZED VIEW public.v_drift_summary AS
        SELECT DISTINCT ON (config_id, asset_id, signal_type)
            metric_id, metric_date, config_id, asset_id, signal_type,
            tracking_error_5d, tracking_error_30d, threshold_breached,
            attr_fill_timing, attr_fee_drag, attr_signal_staleness,
            attr_regime_shift, attr_position_rounding, attr_execution_delay,
            attr_data_divergence, attr_residual
        FROM public.drift_metrics
        ORDER BY config_id, asset_id, signal_type, metric_date DESC
    """)
    )
    op.execute(
        text("""
        CREATE UNIQUE INDEX idx_drift_summary_pk
        ON public.v_drift_summary (config_id, asset_id, signal_type)
    """)
    )


def downgrade() -> None:
    """Downgrade: reverse everything -- drop venue_id, rename tables back."""

    # ==================================================================
    # Step 1: Drop views/matviews (recreated with new names)
    # ==================================================================
    op.execute(text("DROP MATERIALIZED VIEW IF EXISTS public.v_drift_summary"))
    op.execute(text("DROP MATERIALIZED VIEW IF EXISTS public.corr_latest"))
    op.execute(text("DROP VIEW IF EXISTS public.price_histories_u"))
    op.execute(text("DROP VIEW IF EXISTS public.v_positions_agg"))
    op.execute(text("DROP VIEW IF EXISTS public.price_with_emas_d1d2"))
    op.execute(text("DROP VIEW IF EXISTS public.price_with_emas"))
    op.execute(text("DROP VIEW IF EXISTS public.all_emas"))

    # ==================================================================
    # Step 2: Remove venue_id FK from dim_listings
    # ==================================================================
    op.execute(
        text(
            "ALTER TABLE public.dim_listings "
            "DROP CONSTRAINT IF EXISTS fk_listings_venue"
        )
    )
    op.execute(text("ALTER TABLE public.dim_listings DROP COLUMN IF EXISTS venue_id"))

    # ==================================================================
    # Step 3: Drop venue_id FKs from all tables
    # ==================================================================
    for new_name, _, _, _ in VENUE_ID_PK_CHANGES:
        fk_name = f"fk_{new_name}_venue"
        if len(fk_name) > 63:
            fk_name = fk_name[:63]
        op.execute(
            text(f"ALTER TABLE public.{new_name} DROP CONSTRAINT IF EXISTS {fk_name}")
        )

    for new_name in VENUE_ID_COLUMN_ONLY:
        fk_name = f"fk_{new_name}_venue"
        if len(fk_name) > 63:
            fk_name = fk_name[:63]
        op.execute(
            text(f"ALTER TABLE public.{new_name} DROP CONSTRAINT IF EXISTS {fk_name}")
        )

    # ==================================================================
    # Step 4: Restore old PKs (drop new PK, add old PK without venue_id)
    # ==================================================================
    for new_name, old_pk_name, old_pk_cols, new_pk_cols in VENUE_ID_PK_CHANGES:
        new_pk_name = f"{new_name}_pkey"
        old_pk_cols_str = ", ".join(old_pk_cols)
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"DROP CONSTRAINT IF EXISTS {new_pk_name} CASCADE"
            )
        )
        op.execute(
            text(
                f"ALTER TABLE public.{new_name} "
                f"ADD CONSTRAINT {old_pk_name} PRIMARY KEY ({old_pk_cols_str})"
            )
        )

    # ==================================================================
    # Step 5: Drop venue_id column from all tables
    # ==================================================================
    for new_name, _, _, _ in VENUE_ID_PK_CHANGES:
        op.execute(
            text(f"ALTER TABLE public.{new_name} DROP COLUMN IF EXISTS venue_id")
        )

    for new_name in VENUE_ID_COLUMN_ONLY:
        op.execute(
            text(f"ALTER TABLE public.{new_name} DROP COLUMN IF EXISTS venue_id")
        )

    # ==================================================================
    # Step 6: Rename tables back (reverse order)
    # ==================================================================
    for old_name, new_name in reversed(TABLE_RENAMES):
        op.execute(
            text(f"ALTER TABLE IF EXISTS public.{new_name} RENAME TO {old_name}")
        )

    # ==================================================================
    # Step 7: Recreate original views/matviews with old table names
    # ==================================================================

    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.all_emas AS
        SELECT id, ts, tf, tf_days, period, ema, roll
        FROM public.cmc_ema_multi_tf
    """)
    )

    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.cmc_price_with_emas AS
        SELECT
            p.*,
            e.tf,
            e.tf_days,
            e.period,
            e.ema,
            e.roll
        FROM public.cmc_price_histories7 p
        LEFT JOIN public.all_emas e
          ON e.id = p.id
         AND e.ts = p."timestamp"
    """)
    )

    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.cmc_price_with_emas_d1d2 AS
        SELECT * FROM public.cmc_price_with_emas
    """)
    )

    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.v_cmc_positions_agg AS
        SELECT
            asset_id,
            'aggregate'::TEXT AS exchange,
            SUM(quantity) AS quantity,
            CASE
                WHEN SUM(ABS(quantity)) = 0 THEN 0
                ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
            END AS avg_cost_basis,
            SUM(realized_pnl) AS realized_pnl,
            SUM(COALESCE(unrealized_pnl, 0)) AS unrealized_pnl,
            MAX(last_mark_price) AS last_mark_price,
            MAX(last_updated) AS last_updated
        FROM public.cmc_positions
        WHERE exchange != 'aggregate'
        GROUP BY asset_id
    """)
    )

    op.execute(
        text("""
        CREATE OR REPLACE VIEW public.price_histories_u AS
        SELECT id, "timestamp", open, high, low, close, volume, market_cap,
               'cmc' AS source
        FROM public.cmc_price_histories7
        UNION ALL
        SELECT id, "timestamp", open, high, low, close, volume, NULL AS market_cap,
               'tvc' AS source
        FROM public.tvc_price_histories
    """)
    )

    op.execute(
        text("""
        CREATE MATERIALIZED VIEW public.cmc_corr_latest AS
        SELECT DISTINCT ON (id_a, id_b, tf, "window")
            id_a, id_b, ts, tf, "window",
            pearson_r, pearson_p, spearman_r, spearman_p, n_obs
        FROM public.cmc_cross_asset_corr
        ORDER BY id_a, id_b, tf, "window", ts DESC
    """)
    )
    op.execute(
        text("""
        CREATE UNIQUE INDEX idx_corr_latest_pk
        ON public.cmc_corr_latest (id_a, id_b, tf, "window")
    """)
    )

    op.execute(
        text("""
        CREATE MATERIALIZED VIEW public.v_drift_summary AS
        SELECT DISTINCT ON (config_id, asset_id, signal_type)
            metric_id, metric_date, config_id, asset_id, signal_type,
            tracking_error_5d, tracking_error_30d, threshold_breached,
            attr_fill_timing, attr_fee_drag, attr_signal_staleness,
            attr_regime_shift, attr_position_rounding, attr_execution_delay,
            attr_data_divergence, attr_residual
        FROM public.cmc_drift_metrics
        ORDER BY config_id, asset_id, signal_type, metric_date DESC
    """)
    )
    op.execute(
        text("""
        CREATE UNIQUE INDEX idx_drift_summary_pk
        ON public.v_drift_summary (config_id, asset_id, signal_type)
    """)
    )

    # ==================================================================
    # Step 8: Drop dim_venues table
    # ==================================================================
    op.execute(text("DROP TABLE IF EXISTS public.dim_venues CASCADE"))
