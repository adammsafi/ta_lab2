"""triple_barrier_meta_label_tables

Phase 57: Advanced Labeling & CV -- Wave 1 foundation tables.

Creates two tables:

1. cmc_triple_barrier_labels
   Stores triple barrier labels for each (asset_id, tf, t0) event.
   Each row captures the label start (t0), barrier hit time (t1),
   vol-scaled barrier parameters, actual return, and the outcome:
     bin = +1  (profit target hit first)
     bin = -1  (stop loss hit first)
     bin =  0  (vertical/timeout barrier hit first)
   Reference: AFML Ch.3 (Lopez de Prado, 2018)

2. cmc_meta_label_results
   Stores meta-label outcomes linking a primary signal's direction
   (primary_side) to a secondary model's trade decision (meta_label)
   and confidence (trade_probability).
   Reference: AFML Ch.10 (Lopez de Prado, 2018)

Both tables use a natural unique key for upsert semantics, enabling
recomputation with different barrier/model parameters.

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-02-28 07:04:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create cmc_triple_barrier_labels and cmc_meta_label_results."""

    # ------------------------------------------------------------------
    # Table 1: cmc_triple_barrier_labels
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_triple_barrier_labels",
        sa.Column(
            "label_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        # t0: event/label start timestamp (tz-aware)
        sa.Column("t0", sa.TIMESTAMP(timezone=True), nullable=False),
        # t1: barrier hit timestamp -- NULL if still open
        sa.Column("t1", sa.TIMESTAMP(timezone=True), nullable=True),
        # Barrier parameters
        sa.Column("pt_multiplier", sa.Numeric(), nullable=False),
        sa.Column("sl_multiplier", sa.Numeric(), nullable=False),
        sa.Column("vertical_bars", sa.Integer(), nullable=False),
        # Vol-scaling inputs and outputs
        sa.Column("daily_vol", sa.Numeric(), nullable=True),
        sa.Column("target", sa.Numeric(), nullable=True),
        sa.Column("ret", sa.Numeric(), nullable=True),
        # Label: +1 profit, -1 stop, 0 timeout
        sa.Column("bin", sa.SmallInteger(), nullable=True),
        # Which barrier was hit: 'pt', 'sl', 'vb'
        sa.Column("barrier_type", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("label_id"),
        sa.UniqueConstraint(
            "asset_id",
            "tf",
            "t0",
            "pt_multiplier",
            "sl_multiplier",
            "vertical_bars",
            name="uq_triple_barrier_key",
        ),
        schema="public",
    )

    # Index for fast lookup by asset + timeframe + event start
    op.create_index(
        "idx_triple_barrier_asset_tf_t0",
        "cmc_triple_barrier_labels",
        ["asset_id", "tf", "t0"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # Table 2: cmc_meta_label_results
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_meta_label_results",
        sa.Column(
            "result_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        # Signal type: 'ema_crossover', 'rsi_mean_revert', 'atr_breakout'
        sa.Column("signal_type", sa.Text(), nullable=False),
        # t0: signal timestamp (label start)
        sa.Column("t0", sa.TIMESTAMP(timezone=True), nullable=False),
        # t1_from_barrier: links to triple barrier label end
        sa.Column("t1_from_barrier", sa.TIMESTAMP(timezone=True), nullable=True),
        # Primary model direction: +1 long, -1 short
        sa.Column("primary_side", sa.SmallInteger(), nullable=False),
        # Meta-label: 0=skip trade, 1=take trade
        sa.Column("meta_label", sa.SmallInteger(), nullable=True),
        # RandomForest predict_proba output
        sa.Column("trade_probability", sa.Numeric(), nullable=True),
        # Model versioning: hash of training params + feature set
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("n_estimators", sa.Integer(), nullable=True),
        # Comma-separated feature names used in training
        sa.Column("feature_set", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint(
            "asset_id",
            "tf",
            "signal_type",
            "t0",
            "model_version",
            name="uq_meta_label_key",
        ),
        schema="public",
    )

    # Index for fast lookup by asset + timeframe + signal type + event start
    op.create_index(
        "idx_meta_label_asset_signal",
        "cmc_meta_label_results",
        ["asset_id", "tf", "signal_type", "t0"],
        schema="public",
    )


def downgrade() -> None:
    """Downgrade schema: drop cmc_meta_label_results and cmc_triple_barrier_labels."""

    # Drop meta label results first (created second)
    op.drop_index(
        "idx_meta_label_asset_signal",
        table_name="cmc_meta_label_results",
        schema="public",
    )
    op.drop_table("cmc_meta_label_results", schema="public")

    # Drop triple barrier labels
    op.drop_index(
        "idx_triple_barrier_asset_tf_t0",
        table_name="cmc_triple_barrier_labels",
        schema="public",
    )
    op.drop_table("cmc_triple_barrier_labels", schema="public")
