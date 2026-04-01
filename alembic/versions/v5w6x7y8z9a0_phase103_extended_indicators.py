"""phase103_extended_indicators

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-04-01

Phase 103 Plan 02: Traditional TA Expansion -- Extended Indicator Registry.

Two schema changes:

1. Seed dim_indicators with 20 new indicator rows (extended TA indicators).
   Each row provides indicator_type, indicator_name, params JSONB, is_active=TRUE.
   ON CONFLICT (indicator_name) DO UPDATE for idempotency.

2. ALTER TABLE ta ADD COLUMN IF NOT EXISTS for ~35 new output columns.
   All columns are DOUBLE PRECISION. Covers:
     ichimoku (5 cols), Williams %R (1), Keltner Channels (4), CCI (1),
     Elder Ray (2), Force Index (2), VWAP (2), CMF (1), Chaikin Osc (1),
     Hurst (1), VIDYA (1), FRAMA (1), Aroon (3), TRIX (2),
     Ultimate Osc (1), Vortex (2), EMV (2), Mass Index (1), KST (2),
     Coppock (1).

Note: All comments use ASCII only (Windows cp1252 compatibility).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "v5w6x7y8z9a0"
down_revision: str = "u4v5w6x7y8z9"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Indicator seed data
# ---------------------------------------------------------------------------

_INDICATOR_ROWS = [
    ("ichimoku", "ichimoku_9_26_52", '{"tenkan": 9, "kijun": 26, "senkou_b": 52}'),
    ("willr", "willr_14", '{"window": 14}'),
    (
        "keltner",
        "keltner_20_10",
        '{"ema_period": 20, "atr_period": 10, "multiplier": 2.0}',
    ),
    ("cci", "cci_20", '{"window": 20}'),
    ("elder_ray", "elder_ray_13", '{"period": 13}'),
    ("force_index", "force_index_13", '{"smooth": 13}'),
    ("vwap", "vwap_14", '{"window": 14}'),
    ("cmf", "cmf_20", '{"window": 20}'),
    ("chaikin_osc", "chaikin_osc_3_10", '{"fast": 3, "slow": 10}'),
    ("hurst", "hurst_100", '{"window": 100, "max_lag": 20}'),
    ("vidya", "vidya_9", '{"cmo_period": 9, "vidya_period": 9}'),
    ("frama", "frama_16", '{"period": 16}'),
    ("aroon", "aroon_25", '{"window": 25}'),
    ("trix", "trix_15", '{"period": 15, "signal_period": 9}'),
    ("ultimate_osc", "uo_7_14_28", '{"p1": 7, "p2": 14, "p3": 28}'),
    ("vortex", "vortex_14", '{"window": 14}'),
    ("emv", "emv_14", '{"window": 14}'),
    ("mass_index", "mass_idx_25", '{"ema_period": 9, "sum_period": 25}'),
    ("kst", "kst_default", "{}"),
    (
        "coppock",
        "coppock_default",
        '{"roc_long": 14, "roc_short": 11, "wma_period": 10}',
    ),
]

# indicator_name values for downgrade DELETE
_INDICATOR_NAMES = [row[1] for row in _INDICATOR_ROWS]

# ---------------------------------------------------------------------------
# New ta table columns (all DOUBLE PRECISION)
# ---------------------------------------------------------------------------

_NEW_COLUMNS = [
    # Ichimoku Cloud (5)
    "ichimoku_tenkan",
    "ichimoku_kijun",
    "ichimoku_span_a",
    "ichimoku_span_b",
    "ichimoku_chikou",
    # Williams %R (1)
    "willr_14",
    # Keltner Channels (4)
    "kc_mid_20",
    "kc_upper_20",
    "kc_lower_20",
    "kc_width_20",
    # CCI (1)
    "cci_20",
    # Elder Ray (2)
    "elder_bull_13",
    "elder_bear_13",
    # Force Index (2)
    "fi_1",
    "fi_13",
    # VWAP (2)
    "vwap_14",
    "vwap_dev_14",
    # Chaikin Money Flow (1)
    "cmf_20",
    # Chaikin Oscillator (1)
    "chaikin_osc",
    # Hurst Exponent (1)
    "hurst_100",
    # VIDYA (1)
    "vidya_9",
    # FRAMA (1)
    "frama_16",
    # Aroon (3)
    "aroon_up_25",
    "aroon_dn_25",
    "aroon_osc_25",
    # TRIX (2)
    "trix_15",
    "trix_signal_9",
    # Ultimate Oscillator (1)
    "uo_7_14_28",
    # Vortex (2)
    "vi_plus_14",
    "vi_minus_14",
    # EMV (2)
    "emv_1",
    "emv_14",
    # Mass Index (1)
    "mass_idx_25",
    # KST (2)
    "kst",
    "kst_signal",
    # Coppock Curve (1)
    "coppock",
]


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # Part A: Seed dim_indicators with 20 new indicator rows
    # ------------------------------------------------------------------
    for ind_type, ind_name, params_json in _INDICATOR_ROWS:
        conn.execute(
            text(
                """
                INSERT INTO public.dim_indicators
                    (indicator_type, indicator_name, params, is_active)
                VALUES
                    (:ind_type, :ind_name, :params::jsonb, TRUE)
                ON CONFLICT (indicator_name) DO UPDATE
                    SET is_active = TRUE,
                        params    = EXCLUDED.params
                """
            ),
            {
                "ind_type": ind_type,
                "ind_name": ind_name,
                "params": params_json,
            },
        )

    # ------------------------------------------------------------------
    # Part B: ALTER TABLE ta ADD COLUMN IF NOT EXISTS for each new column
    # ------------------------------------------------------------------
    for col_name in _NEW_COLUMNS:
        conn.execute(
            text(
                f"ALTER TABLE public.ta ADD COLUMN IF NOT EXISTS"
                f" {col_name} DOUBLE PRECISION"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove dim_indicators rows
    names_literal = ", ".join(f"'{n}'" for n in _INDICATOR_NAMES)
    conn.execute(
        text(
            f"DELETE FROM public.dim_indicators"
            f" WHERE indicator_name IN ({names_literal})"
        )
    )

    # Drop columns from ta table
    for col_name in _NEW_COLUMNS:
        conn.execute(text(f"ALTER TABLE public.ta DROP COLUMN IF EXISTS {col_name}"))
