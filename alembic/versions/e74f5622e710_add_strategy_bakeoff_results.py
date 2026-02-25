"""add strategy_bakeoff_results

Revision ID: e74f5622e710
Revises: 8d5bc7ee1732
Create Date: 2026-02-24 21:01:06.018287

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e74f5622e710"
down_revision: Union[str, Sequence[str], None] = "8d5bc7ee1732"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.strategy_bakeoff_results (
            id SERIAL PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            asset_id INTEGER NOT NULL,
            tf TEXT NOT NULL,
            params_json JSONB,
            cost_scenario TEXT NOT NULL,
            cv_method TEXT NOT NULL,
            n_folds INTEGER NOT NULL,
            embargo_bars INTEGER NOT NULL,
            sharpe_mean DOUBLE PRECISION,
            sharpe_std DOUBLE PRECISION,
            max_drawdown_mean DOUBLE PRECISION,
            max_drawdown_worst DOUBLE PRECISION,
            total_return_mean DOUBLE PRECISION,
            cagr_mean DOUBLE PRECISION,
            trade_count_total INTEGER,
            turnover DOUBLE PRECISION,
            psr DOUBLE PRECISION,
            dsr DOUBLE PRECISION,
            psr_n_obs INTEGER,
            pbo_prob DOUBLE PRECISION,
            fold_metrics_json JSONB,
            computed_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(strategy_name, asset_id, tf, params_json, cost_scenario, cv_method)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bakeoff_strategy
            ON public.strategy_bakeoff_results (strategy_name, asset_id, tf);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS public.idx_bakeoff_strategy;")
    op.execute("DROP TABLE IF EXISTS public.strategy_bakeoff_results;")
