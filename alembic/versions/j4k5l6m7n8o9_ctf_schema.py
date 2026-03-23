"""CTF schema -- dim_ctf_indicators dimension table and ctf fact table

Creates:
  dim_ctf_indicators  - dimension table mapping indicator_id to source table/column
  ctf                 - fact table storing cross-timeframe computed values

Seed data:
  22 indicators seeded into dim_ctf_indicators covering:
  - 11 TA indicators (RSI, MACD, ADX, Bollinger, Stochastic, ATR)
  - 7 volatility indicators (Parkinson, Garman-Klass, Rogers-Satchell, log-roll)
  - 2 returns indicators (arithmetic, log)
  - 2 feature indicators (fracdiff, SADF)

Indexes:
  ix_ctf_lookup     - (id, base_tf, ref_tf, indicator_id, ts)
  ix_ctf_indicator  - (indicator_id, base_tf)

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: j4k5l6m7n8o9
Revises: 440fdfb3e8e1
Create Date: 2026-03-23
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "440fdfb3e8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. dim_ctf_indicators dimension table
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.dim_ctf_indicators (
            indicator_id    SMALLSERIAL PRIMARY KEY,
            indicator_name  TEXT NOT NULL UNIQUE,
            source_table    TEXT NOT NULL,
            source_column   TEXT NOT NULL,
            is_directional  BOOLEAN NOT NULL DEFAULT TRUE,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            description     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
    )

    # ------------------------------------------------------------------
    # 2. Seed dim_ctf_indicators with 22 indicators
    #    Sources: ta (11), vol (7), returns_bars_multi_tf_u (2), features (2)
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        INSERT INTO public.dim_ctf_indicators
            (indicator_name, source_table, source_column, is_directional, description)
        VALUES
            ('rsi_14',             'ta',                     'rsi_14',             FALSE, 'RSI 14-period'),
            ('rsi_7',              'ta',                     'rsi_7',              FALSE, 'RSI 7-period'),
            ('rsi_21',             'ta',                     'rsi_21',             FALSE, 'RSI 21-period'),
            ('macd_12_26',         'ta',                     'macd_12_26',         TRUE,  'MACD line 12/26'),
            ('macd_hist_12_26_9',  'ta',                     'macd_hist_12_26_9',  TRUE,  'MACD histogram 12/26/9'),
            ('macd_8_17',          'ta',                     'macd_8_17',          TRUE,  'MACD line 8/17'),
            ('macd_hist_8_17_9',   'ta',                     'macd_hist_8_17_9',   TRUE,  'MACD histogram 8/17/9'),
            ('adx_14',             'ta',                     'adx_14',             FALSE, 'ADX 14-period'),
            ('bb_width_20',        'ta',                     'bb_width_20',        FALSE, 'Bollinger width 20-period'),
            ('stoch_k_14',         'ta',                     'stoch_k_14',         FALSE, 'Stochastic K 14-period'),
            ('atr_14',             'ta',                     'atr_14',             FALSE, 'ATR 14-period'),
            ('vol_parkinson_20',   'vol',                    'vol_parkinson_20',   FALSE, 'Parkinson vol 20-bar'),
            ('vol_gk_20',          'vol',                    'vol_gk_20',          FALSE, 'Garman-Klass vol 20-bar'),
            ('vol_rs_20',          'vol',                    'vol_rs_20',          FALSE, 'Rogers-Satchell vol 20-bar'),
            ('vol_log_roll_20',    'vol',                    'vol_log_roll_20',    FALSE, 'Log-return vol 20-bar'),
            ('vol_parkinson_63',   'vol',                    'vol_parkinson_63',   FALSE, 'Parkinson vol 63-bar'),
            ('vol_gk_63',          'vol',                    'vol_gk_63',          FALSE, 'Garman-Klass vol 63-bar'),
            ('vol_log_roll_63',    'vol',                    'vol_log_roll_63',    FALSE, 'Log-return vol 63-bar'),
            ('ret_arith',          'returns_bars_multi_tf_u','ret_arith',          TRUE,  'Arithmetic return'),
            ('ret_log',            'returns_bars_multi_tf_u','ret_log',            TRUE,  'Log return'),
            ('close_fracdiff',     'features',               'close_fracdiff',     TRUE,  'Fractional diff close'),
            ('sadf_stat',          'features',               'sadf_stat',          FALSE, 'SADF structural break stat')
        ON CONFLICT (indicator_name) DO NOTHING
        """)
    )

    # ------------------------------------------------------------------
    # 3. ctf fact table
    #    PK: (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)
    #    FK: venue_id -> dim_venues, indicator_id -> dim_ctf_indicators
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.ctf (
            id               INTEGER NOT NULL,
            venue_id         SMALLINT NOT NULL
                             REFERENCES public.dim_venues(venue_id),
            ts               TIMESTAMPTZ NOT NULL,
            base_tf          TEXT NOT NULL,
            ref_tf           TEXT NOT NULL,
            indicator_id     SMALLINT NOT NULL
                             REFERENCES public.dim_ctf_indicators(indicator_id),
            alignment_source TEXT NOT NULL,
            ref_value        DOUBLE PRECISION,
            base_value       DOUBLE PRECISION,
            slope            DOUBLE PRECISION,
            divergence       DOUBLE PRECISION,
            agreement        DOUBLE PRECISION,
            crossover        DOUBLE PRECISION,
            computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)
        )
        """)
    )

    # ------------------------------------------------------------------
    # 4. Indexes on ctf
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_ctf_lookup
            ON public.ctf (id, base_tf, ref_tf, indicator_id, ts)
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_ctf_indicator
            ON public.ctf (indicator_id, base_tf)
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop fact table first (has FK to dim_ctf_indicators)
    conn.execute(text("DROP TABLE IF EXISTS public.ctf"))
    conn.execute(text("DROP TABLE IF EXISTS public.dim_ctf_indicators"))
