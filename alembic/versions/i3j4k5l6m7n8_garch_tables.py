"""GARCH conditional volatility tables and materialized view

Creates two tables for storing GARCH model outputs and diagnostics,
plus a materialized view for fast latest-forecast lookups.

Tables created:
  garch_forecasts     - per-asset conditional volatility forecasts (1-day, 5-day)
  garch_diagnostics   - model fit diagnostics, convergence tracking, AIC/BIC

Materialized view:
  garch_forecasts_latest - latest forecast per (id, venue_id, tf, model_type, horizon)

Model types supported:
  garch_1_1       - Standard GARCH(1,1)
  gjr_garch_1_1   - GJR-GARCH(1,1) (asymmetric leverage)
  egarch_1_1      - EGARCH(1,1) (exponential GARCH)
  figarch_1_d_1   - FIGARCH(1,d,1) (fractionally integrated, 200-obs minimum)

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-03-22
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, Sequence[str], None] = "h2i3j4k5l6m7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. garch_diagnostics table (created first so garch_forecasts FK can ref it)
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.garch_diagnostics (
            run_id             BIGSERIAL PRIMARY KEY,
            id                 INTEGER NOT NULL,
            venue_id           SMALLINT NOT NULL
                               REFERENCES public.dim_venues(venue_id),
            ts                 TIMESTAMPTZ NOT NULL,
            tf                 TEXT NOT NULL,
            model_type         TEXT NOT NULL,
            converged          BOOLEAN NOT NULL,
            convergence_flag   SMALLINT,
            aic                NUMERIC,
            bic                NUMERIC,
            loglikelihood      NUMERIC,
            ljung_box_pvalue   NUMERIC,
            n_obs              INTEGER,
            refit_reason       TEXT,
            error_msg          TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_garch_diagnostics_lookup
            ON public.garch_diagnostics (id, venue_id, model_type, ts DESC)
        """)
    )

    # ------------------------------------------------------------------
    # 2. garch_forecasts table
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.garch_forecasts (
            id               INTEGER NOT NULL,
            venue_id         SMALLINT NOT NULL
                             REFERENCES public.dim_venues(venue_id),
            ts               TIMESTAMPTZ NOT NULL,
            tf               TEXT NOT NULL,
            model_type       TEXT NOT NULL
                             CONSTRAINT chk_garch_forecasts_model_type
                             CHECK (model_type IN (
                                 'garch_1_1',
                                 'gjr_garch_1_1',
                                 'egarch_1_1',
                                 'figarch_1_d_1'
                             )),
            horizon          SMALLINT NOT NULL
                             CONSTRAINT chk_garch_forecasts_horizon
                             CHECK (horizon IN (1, 5)),
            cond_vol         NUMERIC(18, 8) NOT NULL,
            forecast_source  TEXT NOT NULL DEFAULT 'garch'
                             CONSTRAINT chk_garch_forecasts_source
                             CHECK (forecast_source IN (
                                 'garch',
                                 'carry_forward',
                                 'fallback_gk',
                                 'fallback_parkinson'
                             )),
            model_run_id     BIGINT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, venue_id, ts, tf, model_type, horizon)
        )
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_garch_forecasts_ts
            ON public.garch_forecasts (ts DESC)
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_garch_forecasts_id_model
            ON public.garch_forecasts (id, venue_id, model_type, horizon, ts DESC)
        """)
    )

    # ------------------------------------------------------------------
    # 3. FK from garch_forecasts.model_run_id -> garch_diagnostics.run_id
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        ALTER TABLE public.garch_forecasts
            ADD CONSTRAINT fk_garch_forecasts_run_id
            FOREIGN KEY (model_run_id)
            REFERENCES public.garch_diagnostics(run_id)
            ON DELETE SET NULL
        """)
    )

    # ------------------------------------------------------------------
    # 4. garch_forecasts_latest materialized view
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS public.garch_forecasts_latest AS
        SELECT DISTINCT ON (id, venue_id, tf, model_type, horizon)
            id,
            venue_id,
            tf,
            model_type,
            horizon,
            cond_vol,
            forecast_source,
            ts
        FROM public.garch_forecasts
        ORDER BY id, venue_id, tf, model_type, horizon, ts DESC
        """)
    )

    conn.execute(
        text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_garch_forecasts_latest
            ON public.garch_forecasts_latest (id, venue_id, tf, model_type, horizon)
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop in reverse order: view first, then FK, then tables
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS public.garch_forecasts_latest"))

    conn.execute(
        text("""
        ALTER TABLE public.garch_forecasts
            DROP CONSTRAINT IF EXISTS fk_garch_forecasts_run_id
        """)
    )

    conn.execute(text("DROP TABLE IF EXISTS public.garch_forecasts"))
    conn.execute(text("DROP TABLE IF EXISTS public.garch_diagnostics"))
