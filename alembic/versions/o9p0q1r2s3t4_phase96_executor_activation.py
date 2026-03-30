"""Phase 96 Executor Activation schema changes.

Creates:
  signals_macd_crossover          - MACD crossover signal table
  signals_ama_momentum            - AMA momentum signal table
  signals_ama_mean_reversion      - AMA mean-reversion signal table
  signals_ama_regime_conditional  - AMA regime-conditional signal table
  strategy_parity                 - Live vs backtest Sharpe ratio comparison
  pnl_attribution                 - Alpha/beta PnL decomposition

Widens CHECK constraints:
  chk_exec_config_signal_type   - adds macd_crossover, ama_momentum, ama_mean_reversion,
                                    ama_regime_conditional
  chk_exec_config_sizing_mode   - adds bl_weight
  chk_exec_run_status           - adds halted (bug fix)

Seeds dim_signals rows for 4 new signal types.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-03-30
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "o9p0q1r2s3t4"
down_revision: Union[str, Sequence[str], None] = "n8o9p0q1r2s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Widen chk_exec_config_signal_type on dim_executor_config
    #    Drop existing constraint and create new one with 7 allowed values.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            DROP CONSTRAINT IF EXISTS chk_exec_config_signal_type
        """)
    )
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            ADD CONSTRAINT chk_exec_config_signal_type
            CHECK (signal_type IN (
                'ema_crossover',
                'rsi_mean_revert',
                'atr_breakout',
                'macd_crossover',
                'ama_momentum',
                'ama_mean_reversion',
                'ama_regime_conditional'
            ))
        """)
    )

    # ------------------------------------------------------------------
    # 2. Widen chk_exec_config_sizing_mode on dim_executor_config
    #    Adds bl_weight to the allowed sizing modes.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            DROP CONSTRAINT IF EXISTS chk_exec_config_sizing_mode
        """)
    )
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            ADD CONSTRAINT chk_exec_config_sizing_mode
            CHECK (sizing_mode IN (
                'fixed_fraction',
                'regime_adjusted',
                'signal_strength',
                'target_vol',
                'bl_weight'
            ))
        """)
    )

    # ------------------------------------------------------------------
    # 3. Bug fix: widen chk_exec_run_status on executor_run_log
    #    Adds 'halted' to the allowed terminal states.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        ALTER TABLE public.executor_run_log
            DROP CONSTRAINT IF EXISTS chk_exec_run_status
        """)
    )
    conn.execute(
        text("""
        ALTER TABLE public.executor_run_log
            ADD CONSTRAINT chk_exec_run_status
            CHECK (status IN (
                'running',
                'success',
                'failed',
                'stale_signal',
                'no_signals',
                'halted'
            ))
        """)
    )

    # ------------------------------------------------------------------
    # 4. Seed dim_signals with rows for the 4 new signal types.
    #    CRITICAL: seed_executor_config.py resolves signal_name -> signal_id
    #    from dim_signals. Missing rows cause silent config skips.
    #    params is JSONB NOT NULL with no server default -- must be provided.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        INSERT INTO public.dim_signals (signal_type, signal_name, params, description)
        VALUES
            (
                'macd_crossover',
                'macd_12_26_9_long',
                '{"fast": 12, "slow": 26, "signal": 9, "direction": "long"}'::jsonb,
                'MACD(12,26,9) long crossover signal'
            ),
            (
                'ama_momentum',
                'ama_momentum_v1',
                '{"direction": "long"}'::jsonb,
                'AMA momentum trend-following signal v1'
            ),
            (
                'ama_mean_reversion',
                'ama_mean_reversion_v1',
                '{"direction": "long"}'::jsonb,
                'AMA mean-reversion signal v1'
            ),
            (
                'ama_regime_conditional',
                'ama_regime_conditional_v1',
                '{"direction": "long"}'::jsonb,
                'AMA regime-conditional signal v1'
            )
        ON CONFLICT (signal_name) DO NOTHING
        """)
    )

    # ------------------------------------------------------------------
    # 5a. signals_macd_crossover
    #     Same schema as signals_ema_crossover. executor_processed_at
    #     is required for replay guard (must be in table before executor starts).
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.signals_macd_crossover (
            id                      INTEGER         NOT NULL,
            ts                      TIMESTAMPTZ     NOT NULL,
            signal_id               INTEGER         NOT NULL,
            direction               TEXT            NOT NULL,
            position_state          TEXT            NOT NULL,
            entry_price             NUMERIC         NULL,
            entry_ts                TIMESTAMPTZ     NULL,
            exit_price              NUMERIC         NULL,
            exit_ts                 TIMESTAMPTZ     NULL,
            pnl_pct                 NUMERIC         NULL,
            feature_snapshot        JSONB           NULL,
            signal_version          TEXT            NULL,
            feature_version_hash    TEXT            NULL,
            params_hash             TEXT            NULL,
            executor_processed_at   TIMESTAMPTZ     NULL,
            created_at              TIMESTAMPTZ     DEFAULT now(),
            PRIMARY KEY (id, ts, signal_id),
            FOREIGN KEY (signal_id) REFERENCES public.dim_signals(signal_id)
        )
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_macd_xo_open_positions
            ON public.signals_macd_crossover (id, signal_id, position_state)
            WHERE position_state = 'open'
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_macd_xo_backtest
            ON public.signals_macd_crossover (signal_id, ts)
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_macd_xo_closed
            ON public.signals_macd_crossover (signal_id, position_state)
            WHERE position_state = 'closed'
        """)
    )

    # ------------------------------------------------------------------
    # 5b. signals_ama_momentum
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.signals_ama_momentum (
            id                      INTEGER         NOT NULL,
            ts                      TIMESTAMPTZ     NOT NULL,
            signal_id               INTEGER         NOT NULL,
            direction               TEXT            NOT NULL,
            position_state          TEXT            NOT NULL,
            entry_price             NUMERIC         NULL,
            entry_ts                TIMESTAMPTZ     NULL,
            exit_price              NUMERIC         NULL,
            exit_ts                 TIMESTAMPTZ     NULL,
            pnl_pct                 NUMERIC         NULL,
            feature_snapshot        JSONB           NULL,
            signal_version          TEXT            NULL,
            feature_version_hash    TEXT            NULL,
            params_hash             TEXT            NULL,
            executor_processed_at   TIMESTAMPTZ     NULL,
            created_at              TIMESTAMPTZ     DEFAULT now(),
            PRIMARY KEY (id, ts, signal_id),
            FOREIGN KEY (signal_id) REFERENCES public.dim_signals(signal_id)
        )
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_mom_open_positions
            ON public.signals_ama_momentum (id, signal_id, position_state)
            WHERE position_state = 'open'
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_mom_backtest
            ON public.signals_ama_momentum (signal_id, ts)
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_mom_closed
            ON public.signals_ama_momentum (signal_id, position_state)
            WHERE position_state = 'closed'
        """)
    )

    # ------------------------------------------------------------------
    # 5c. signals_ama_mean_reversion
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.signals_ama_mean_reversion (
            id                      INTEGER         NOT NULL,
            ts                      TIMESTAMPTZ     NOT NULL,
            signal_id               INTEGER         NOT NULL,
            direction               TEXT            NOT NULL,
            position_state          TEXT            NOT NULL,
            entry_price             NUMERIC         NULL,
            entry_ts                TIMESTAMPTZ     NULL,
            exit_price              NUMERIC         NULL,
            exit_ts                 TIMESTAMPTZ     NULL,
            pnl_pct                 NUMERIC         NULL,
            feature_snapshot        JSONB           NULL,
            signal_version          TEXT            NULL,
            feature_version_hash    TEXT            NULL,
            params_hash             TEXT            NULL,
            executor_processed_at   TIMESTAMPTZ     NULL,
            created_at              TIMESTAMPTZ     DEFAULT now(),
            PRIMARY KEY (id, ts, signal_id),
            FOREIGN KEY (signal_id) REFERENCES public.dim_signals(signal_id)
        )
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_mr_open_positions
            ON public.signals_ama_mean_reversion (id, signal_id, position_state)
            WHERE position_state = 'open'
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_mr_backtest
            ON public.signals_ama_mean_reversion (signal_id, ts)
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_mr_closed
            ON public.signals_ama_mean_reversion (signal_id, position_state)
            WHERE position_state = 'closed'
        """)
    )

    # ------------------------------------------------------------------
    # 5d. signals_ama_regime_conditional
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.signals_ama_regime_conditional (
            id                      INTEGER         NOT NULL,
            ts                      TIMESTAMPTZ     NOT NULL,
            signal_id               INTEGER         NOT NULL,
            direction               TEXT            NOT NULL,
            position_state          TEXT            NOT NULL,
            entry_price             NUMERIC         NULL,
            entry_ts                TIMESTAMPTZ     NULL,
            exit_price              NUMERIC         NULL,
            exit_ts                 TIMESTAMPTZ     NULL,
            pnl_pct                 NUMERIC         NULL,
            feature_snapshot        JSONB           NULL,
            signal_version          TEXT            NULL,
            feature_version_hash    TEXT            NULL,
            params_hash             TEXT            NULL,
            executor_processed_at   TIMESTAMPTZ     NULL,
            created_at              TIMESTAMPTZ     DEFAULT now(),
            PRIMARY KEY (id, ts, signal_id),
            FOREIGN KEY (signal_id) REFERENCES public.dim_signals(signal_id)
        )
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_rc_open_positions
            ON public.signals_ama_regime_conditional (id, signal_id, position_state)
            WHERE position_state = 'open'
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_rc_backtest
            ON public.signals_ama_regime_conditional (signal_id, ts)
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_signals_ama_rc_closed
            ON public.signals_ama_regime_conditional (signal_id, position_state)
            WHERE position_state = 'closed'
        """)
    )

    # ------------------------------------------------------------------
    # 6. strategy_parity
    #    Compares live executor Sharpe (fill-based and MTM) against
    #    backtest Sharpe. Ratios < 0.8 trigger investigation alerts.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.strategy_parity (
            parity_id       SERIAL          PRIMARY KEY,
            computed_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            strategy        TEXT            NOT NULL,
            window_days     INTEGER         NOT NULL,
            live_sharpe_fill    NUMERIC,
            live_sharpe_mtm     NUMERIC,
            bt_sharpe           NUMERIC,
            ratio_fill          NUMERIC,
            ratio_mtm           NUMERIC,
            n_fills             INTEGER,
            n_mtm_days          INTEGER
        )
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_strategy_parity_strategy_ts
            ON public.strategy_parity (strategy, computed_at DESC)
        """)
    )

    # ------------------------------------------------------------------
    # 7. pnl_attribution
    #    Alpha/beta decomposition of PnL against a chosen benchmark.
    #    asset_class: 'crypto', 'perp', 'all'
    #    benchmark: 'BTC', 'SPX', 'underlying', 'blended'
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.pnl_attribution (
            attr_id         SERIAL          PRIMARY KEY,
            computed_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            period_start    DATE            NOT NULL,
            period_end      DATE            NOT NULL,
            asset_class     TEXT            NOT NULL,
            benchmark       TEXT            NOT NULL,
            total_pnl       NUMERIC,
            beta_pnl        NUMERIC,
            alpha_pnl       NUMERIC,
            beta            NUMERIC,
            sharpe_alpha    NUMERIC,
            n_positions     INTEGER
        )
        """)
    )
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_pnl_attribution_period
            ON public.pnl_attribution (period_start, period_end, asset_class)
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop new reporting tables
    conn.execute(text("DROP INDEX IF EXISTS public.idx_pnl_attribution_period"))
    conn.execute(text("DROP TABLE IF EXISTS public.pnl_attribution"))
    conn.execute(text("DROP INDEX IF EXISTS public.idx_strategy_parity_strategy_ts"))
    conn.execute(text("DROP TABLE IF EXISTS public.strategy_parity"))

    # Drop new signal tables (indexes drop with tables)
    conn.execute(text("DROP TABLE IF EXISTS public.signals_ama_regime_conditional"))
    conn.execute(text("DROP TABLE IF EXISTS public.signals_ama_mean_reversion"))
    conn.execute(text("DROP TABLE IF EXISTS public.signals_ama_momentum"))
    conn.execute(text("DROP TABLE IF EXISTS public.signals_macd_crossover"))

    # Remove seeded dim_signals rows
    conn.execute(
        text("""
        DELETE FROM public.dim_signals
        WHERE signal_name IN (
            'macd_12_26_9_long',
            'ama_momentum_v1',
            'ama_mean_reversion_v1',
            'ama_regime_conditional_v1'
        )
        """)
    )

    # Restore original chk_exec_run_status (without 'halted')
    conn.execute(
        text("""
        ALTER TABLE public.executor_run_log
            DROP CONSTRAINT IF EXISTS chk_exec_run_status
        """)
    )
    conn.execute(
        text("""
        ALTER TABLE public.executor_run_log
            ADD CONSTRAINT chk_exec_run_status
            CHECK (status IN ('running', 'success', 'failed', 'stale_signal', 'no_signals'))
        """)
    )

    # Restore original chk_exec_config_sizing_mode (without 'target_vol', 'bl_weight')
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            DROP CONSTRAINT IF EXISTS chk_exec_config_sizing_mode
        """)
    )
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            ADD CONSTRAINT chk_exec_config_sizing_mode
            CHECK (sizing_mode IN ('fixed_fraction', 'regime_adjusted', 'signal_strength'))
        """)
    )

    # Restore original chk_exec_config_signal_type (3 types only)
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            DROP CONSTRAINT IF EXISTS chk_exec_config_signal_type
        """)
    )
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            ADD CONSTRAINT chk_exec_config_signal_type
            CHECK (signal_type IN ('ema_crossover', 'rsi_mean_revert', 'atr_breakout'))
        """)
    )
