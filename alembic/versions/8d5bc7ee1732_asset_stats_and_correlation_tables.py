"""asset_stats_and_correlation_tables

Revision ID: 8d5bc7ee1732
Revises: 6f82e9117c58
Create Date: 2026-02-24 11:32:10.674795

Creates 5 objects for Phase 41 (Asset Descriptive Stats and Correlation):

cmc_asset_stats:
  Wide-format rolling statistics per (id, ts, tf). Computes mean_ret, std_ret,
  sharpe_raw, sharpe_ann, skew, kurt_fisher, kurt_pearson, max_dd_window for
  each of 4 rolling windows (30, 60, 90, 252). Also stores max_dd_from_ath
  and rf_rate as additional non-windowed columns.

cmc_cross_asset_corr:
  Long-format pairwise correlation per (id_a, id_b, ts, tf, window). Stores
  pearson_r, pearson_p, spearman_r, spearman_p, n_obs. CHECK constraint
  enforces id_a < id_b to canonicalize pair ordering and halve storage.

cmc_asset_stats_state:
  Watermark tracking for incremental refresh of cmc_asset_stats. One row per
  (id, tf) with last_timestamp of the most recently processed bar.

cmc_cross_asset_corr_state:
  Watermark tracking for incremental refresh of cmc_cross_asset_corr. One row
  per (id_a, id_b, tf) with last_timestamp of the most recently computed pair.

cmc_corr_latest (materialized view):
  DISTINCT ON (id_a, id_b, tf, window) ordered by ts DESC -- fast dashboard
  queries showing only the most recent correlation value per pair/window.

All tables use schema="public".
No UTF-8 box-drawing characters to avoid Windows cp1252 decode errors.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d5bc7ee1732"
down_revision: Union[str, Sequence[str], None] = "6f82e9117c58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Rolling windows used to generate per-window stat columns
_WINDOWS = (30, 60, 90, 252)

# Stat column base names for each window
_STAT_BASES = (
    "mean_ret",
    "std_ret",
    "sharpe_raw",
    "sharpe_ann",
    "skew",
    "kurt_fisher",
    "kurt_pearson",
    "max_dd_window",
)


def _window_stat_columns() -> list[sa.Column]:
    """Return 32 NUMERIC nullable columns: 8 stats x 4 windows."""
    cols = []
    for w in _WINDOWS:
        for base in _STAT_BASES:
            cols.append(sa.Column(f"{base}_{w}", sa.Numeric(), nullable=True))
    return cols


def upgrade() -> None:
    """Upgrade schema: create cmc_asset_stats, cmc_cross_asset_corr, state tables, and materialized view."""

    # ------------------------------------------------------------------
    # Table: cmc_asset_stats
    # Wide-format rolling stats per asset/timeframe.
    # PK: (id, ts, tf)
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_asset_stats",
        # Primary key columns
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        # Per-window stat columns: 8 stats x 4 windows = 32 columns
        *_window_stat_columns(),
        # Additional non-windowed columns
        sa.Column("max_dd_from_ath", sa.Numeric(), nullable=True),
        sa.Column("rf_rate", sa.Numeric(), nullable=True),
        # Audit timestamp
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id", "ts", "tf"),
        schema="public",
    )

    # Index optimized for time-series queries: id + tf range scans
    op.create_index(
        "idx_asset_stats_id_tf_ts",
        "cmc_asset_stats",
        ["id", "tf", "ts"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # Table: cmc_cross_asset_corr
    # Long-format pairwise correlation per asset pair/timeframe/window.
    # PK: (id_a, id_b, ts, tf, window) with CHECK(id_a < id_b)
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_cross_asset_corr",
        # Primary key columns
        sa.Column("id_a", sa.Integer(), nullable=False),
        sa.Column("id_b", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column("window", sa.Integer(), nullable=False),
        # Correlation metrics -- nullable because some windows may lack data
        sa.Column("pearson_r", sa.Numeric(), nullable=True),
        sa.Column("pearson_p", sa.Numeric(), nullable=True),
        sa.Column("spearman_r", sa.Numeric(), nullable=True),
        sa.Column("spearman_p", sa.Numeric(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        # Audit timestamp
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id_a", "id_b", "ts", "tf", "window"),
        sa.CheckConstraint("id_a < id_b", name="chk_corr_pair_order"),
        schema="public",
    )

    # Index for pair + window + time queries (dashboard and incremental refresh)
    op.create_index(
        "idx_corr_pair_tf_window_ts",
        "cmc_cross_asset_corr",
        ["id_a", "id_b", "tf", "window", "ts"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # Table: cmc_asset_stats_state
    # Watermark tracking for incremental cmc_asset_stats refresh.
    # PK: (id, tf)
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_asset_stats_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column("last_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "tf"),
        schema="public",
    )

    # ------------------------------------------------------------------
    # Table: cmc_cross_asset_corr_state
    # Watermark tracking for incremental cmc_cross_asset_corr refresh.
    # PK: (id_a, id_b, tf)
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_cross_asset_corr_state",
        sa.Column("id_a", sa.Integer(), nullable=False),
        sa.Column("id_b", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column("last_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id_a", "id_b", "tf"),
        schema="public",
    )

    # ------------------------------------------------------------------
    # Materialized view: cmc_corr_latest
    # Most recent correlation value per (id_a, id_b, tf, window).
    # Alembic has no native op for materialized views; use op.execute().
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW public.cmc_corr_latest AS
        SELECT DISTINCT ON (id_a, id_b, tf, "window")
            id_a, id_b, ts, tf, "window",
            pearson_r, pearson_p, spearman_r, spearman_p, n_obs
        FROM public.cmc_cross_asset_corr
        ORDER BY id_a, id_b, tf, "window", ts DESC
        """
    )

    # Unique index supports REFRESH MATERIALIZED VIEW CONCURRENTLY and fast lookups
    op.execute(
        """
        CREATE UNIQUE INDEX idx_corr_latest_pk
        ON public.cmc_corr_latest (id_a, id_b, tf, "window")
        """
    )


def downgrade() -> None:
    """Downgrade schema: drop all 5 objects in reverse order."""

    # Drop materialized view first (depends on cmc_cross_asset_corr)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS public.cmc_corr_latest")

    # Drop state tables
    op.drop_table("cmc_cross_asset_corr_state", schema="public")
    op.drop_table("cmc_asset_stats_state", schema="public")

    # Drop correlation table (indexes dropped automatically with table)
    op.drop_index(
        "idx_corr_pair_tf_window_ts",
        table_name="cmc_cross_asset_corr",
        schema="public",
    )
    op.drop_table("cmc_cross_asset_corr", schema="public")

    # Drop stats table (indexes dropped automatically with table)
    op.drop_index(
        "idx_asset_stats_id_tf_ts",
        table_name="cmc_asset_stats",
        schema="public",
    )
    op.drop_table("cmc_asset_stats", schema="public")
