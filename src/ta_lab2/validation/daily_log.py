"""
daily_log.py
~~~~~~~~~~~~
DailyValidationLog -- generates a daily Markdown validation report during the
14-day V1 paper trading validation period (Phase 53).

Queries 7 data sections from the database and writes a structured Markdown file
to ``reports/validation/daily/validation_YYYY-MM-DD.md``.

Usage::

    from datetime import date
    from sqlalchemy import create_engine
    from ta_lab2.validation.daily_log import DailyValidationLog

    engine = create_engine(db_url)
    log = DailyValidationLog(engine)
    path = log.generate(
        log_date=date.today(),
        validation_start=date(2026, 3, 1),
    )
    print("Report written to:", path)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Signal table map (matches signal_reader.py SIGNAL_TABLE_MAP convention).
_SIGNAL_TABLE_MAP: dict[str, str] = {
    "ema_crossover": "signals_ema_crossover",
    "rsi_mean_reversion": "cmc_signals_rsi",
    "atr_breakout": "signals_atr_breakout",
}


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Convert DataFrame to GitHub-flavored Markdown table.

    Reuses the same helper pattern established in drift_report.py.
    Handles NaN values and formats floats to 4 decimal places.
    """
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    rows_str = []
    for _, row in df.iterrows():
        cells = []
        for val in row:
            if pd.isna(val) if not isinstance(val, (str, bool)) else False:
                cells.append("N/A")
            elif isinstance(val, float):
                cells.append(f"{val:.4f}")
            else:
                cells.append(str(val))
        rows_str.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep] + rows_str)


class DailyValidationLog:
    """Generate a daily Markdown validation log from DB data.

    Queries 7 tables / sections and writes a structured report file.
    All file I/O uses ``encoding='utf-8'`` (Windows cp1252 safety).

    Args:
        engine: SQLAlchemy engine connected to the project database.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        log_date: date,
        validation_start: date,
        output_dir: str = "reports/validation/daily",
    ) -> str:
        """Generate the daily validation Markdown report.

        Args:
            log_date:         Date for which to generate the log.
            validation_start: First day of the 14-day validation window.
            output_dir:       Directory to write the report file.

        Returns:
            Absolute path to the written Markdown file.
        """
        os.makedirs(output_dir, exist_ok=True)

        day_n = (log_date - validation_start).days + 1
        generated_at = datetime.now(timezone.utc).isoformat()

        lines: list[str] = []

        # Header
        lines.append(f"# Daily Validation Log: {log_date}")
        lines.append("")
        lines.append(
            f"**Day {day_n} of 14 validation period** (started {validation_start})"
        )
        lines.append(f"**Generated:** {generated_at}")
        lines.append("")

        # Section 1: Pipeline Status
        lines += self._section_pipeline_status(log_date)

        # Section 2: Signals Generated
        lines += self._section_signals(log_date)

        # Section 3: Orders & Fills
        lines += self._section_orders_fills(log_date)

        # Section 4: Current Positions
        lines += self._section_positions()

        # Section 5: P&L Summary
        lines += self._section_pnl(log_date, validation_start)

        # Section 6: Drift Metrics
        lines += self._section_drift(log_date)

        # Section 7: Risk State
        lines += self._section_risk_state()

        # Section 8: Anomalies (placeholder)
        lines.append("## Anomalies")
        lines.append("")
        lines.append("See audit report for full gap detection.")
        lines.append("")

        # Section 9: Notes
        lines.append("## Notes")
        lines.append("")
        lines.append("[ ] Reviewed by: ___________ Date: ___________")
        lines.append("")

        content = "\n".join(lines)

        report_filename = f"validation_{log_date.isoformat()}.md"
        report_path = os.path.join(output_dir, report_filename)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        logger.info("Daily validation log written to: %s", report_path)
        return os.path.abspath(report_path)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _section_pipeline_status(self, log_date: date) -> list[str]:
        """Query executor_run_log for today's runs."""
        lines: list[str] = []
        lines.append("## 1. Pipeline Status")
        lines.append("")

        sql = text(
            """
            SELECT run_id, started_at, status, signals_read, orders_generated, fills_processed
            FROM executor_run_log
            WHERE started_at::date = :log_date
            ORDER BY started_at DESC
            LIMIT 5
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"log_date": log_date})

            if df.empty:
                lines.append("_No executor runs found for this date._")
            else:
                lines.append(_df_to_markdown(df))
        except Exception as exc:
            logger.warning("_section_pipeline_status failed: %s", exc)
            lines.append(f"_Query error: {exc}_")

        lines.append("")
        return lines

    def _section_signals(self, log_date: date) -> list[str]:
        """Query signal tables for today's signals."""
        lines: list[str] = []
        lines.append("## 2. Signals Generated")
        lines.append("")

        all_rows: list[dict[str, Any]] = []

        for strategy, table in _SIGNAL_TABLE_MAP.items():
            try:
                sql = text(
                    f"""
                    SELECT
                        :strategy AS strategy,
                        asset_id,
                        direction,
                        signal_ts
                    FROM {table}
                    WHERE generated_at::date = :log_date
                    ORDER BY signal_ts DESC
                    """
                )
                with self._engine.connect() as conn:
                    df = pd.read_sql(
                        sql, conn, params={"log_date": log_date, "strategy": strategy}
                    )
                if not df.empty:
                    all_rows.extend(df.to_dict("records"))
            except Exception as exc:
                logger.debug("Signal query skipped for %s: %s", table, exc)

        if all_rows:
            signals_df = pd.DataFrame(all_rows)
            lines.append(_df_to_markdown(signals_df))
        else:
            lines.append(
                "_No signals generated for this date (or signal tables absent)._"
            )

        lines.append("")
        return lines

    def _section_orders_fills(self, log_date: date) -> list[str]:
        """Query orders and fills for today with slippage calculation.

        Note: orders does NOT have a strategy_id column.
        Strategy attribution is only available via positions.
        """
        lines: list[str] = []
        lines.append("## 3. Orders & Fills")
        lines.append("")

        sql = text(
            """
            SELECT
                o.asset_id,
                f.side,
                f.fill_qty,
                f.fill_price,
                ABS(f.fill_price::float - COALESCE(pb.open::float, f.fill_price::float))
                    / NULLIF(COALESCE(pb.open::float, f.fill_price::float), 0)
                    * 10000 AS slippage_bps
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            LEFT JOIN price_bars_multi_tf pb
                ON pb.id = o.asset_id
                AND pb.tf = '1D'
                AND pb.ts::date = f.filled_at::date
            WHERE f.filled_at::date = :log_date
            ORDER BY f.filled_at DESC
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"log_date": log_date})

            if df.empty:
                lines.append("_No fills for this date._")
            else:
                lines.append(_df_to_markdown(df))
        except Exception as exc:
            logger.warning("_section_orders_fills failed: %s", exc)
            lines.append(f"_Query error: {exc}_")

        lines.append("")
        return lines

    def _section_positions(self) -> list[str]:
        """Query current open positions.

        Uses avg_cost_basis (correct column name, NOT avg_entry_price).
        strategy_id is part of the PK on positions.
        """
        lines: list[str] = []
        lines.append("## 4. Current Positions")
        lines.append("")

        sql = text(
            """
            SELECT asset_id, strategy_id, quantity, avg_cost_basis
            FROM positions
            WHERE quantity != 0
            ORDER BY asset_id, strategy_id
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn)

            if df.empty:
                lines.append("_No open positions._")
            else:
                # Rename column for display clarity
                df = df.rename(columns={"avg_cost_basis": "Avg Cost Basis"})
                lines.append(_df_to_markdown(df))
        except Exception as exc:
            logger.warning("_section_positions failed: %s", exc)
            lines.append(f"_Query error: {exc}_")

        lines.append("")
        return lines

    def _section_pnl(self, log_date: date, validation_start: date) -> list[str]:
        """P&L summary from fills (aggregate) plus per-strategy from positions.

        Aggregate daily/cumulative P&L is computed from fills + orders
        (which lack strategy_id).  Per-strategy realized P&L comes from positions.
        """
        lines: list[str] = []
        lines.append("## 5. P&L Summary")
        lines.append("")

        # Daily and cumulative aggregate P&L from fills
        sql_aggregate = text(
            """
            SELECT
                SUM(CASE WHEN f.side = 'sell'
                    THEN f.fill_price * f.fill_qty
                    ELSE -f.fill_price * f.fill_qty
                END) AS daily_pnl
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            WHERE f.filled_at::date = :log_date
            """
        )
        sql_cumulative = text(
            """
            SELECT
                SUM(CASE WHEN f.side = 'sell'
                    THEN f.fill_price * f.fill_qty
                    ELSE -f.fill_price * f.fill_qty
                END) AS cumulative_pnl
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            WHERE f.filled_at::date BETWEEN :start_date AND :log_date
            """
        )

        try:
            with self._engine.connect() as conn:
                row_daily = conn.execute(
                    sql_aggregate, {"log_date": log_date}
                ).fetchone()
                row_cum = conn.execute(
                    sql_cumulative,
                    {"start_date": validation_start, "log_date": log_date},
                ).fetchone()

            daily_pnl = (
                float(row_daily[0]) if row_daily and row_daily[0] is not None else 0.0
            )
            cum_pnl = float(row_cum[0]) if row_cum and row_cum[0] is not None else 0.0

            lines.append("### Aggregate P&L (from fills)")
            lines.append("")
            agg_df = pd.DataFrame(
                [
                    {"metric": "Daily P&L", "value": daily_pnl},
                    {
                        "metric": "Cumulative P&L (since validation start)",
                        "value": cum_pnl,
                    },
                ]
            )
            lines.append(_df_to_markdown(agg_df))
            lines.append("")
        except Exception as exc:
            logger.warning("_section_pnl aggregate failed: %s", exc)
            lines.append(f"_Aggregate P&L query error: {exc}_")
            lines.append("")

        # Per-strategy realized P&L from positions
        sql_strategy = text(
            """
            SELECT strategy_id, SUM(realized_pnl) AS realized_pnl
            FROM positions
            WHERE quantity != 0
            GROUP BY strategy_id
            ORDER BY strategy_id
            """
        )
        try:
            with self._engine.connect() as conn:
                df_strategy = pd.read_sql(sql_strategy, conn)

            lines.append("### Per-Strategy Realized P&L (from positions)")
            lines.append("")
            if df_strategy.empty:
                lines.append("_No open positions with realized P&L._")
            else:
                lines.append(_df_to_markdown(df_strategy))
            lines.append("")
        except Exception as exc:
            logger.warning("_section_pnl strategy failed: %s", exc)
            lines.append(f"_Per-strategy P&L query error: {exc}_")
            lines.append("")

        return lines

    def _section_drift(self, log_date: date) -> list[str]:
        """Query drift metrics for today."""
        lines: list[str] = []
        lines.append("## 6. Drift Metrics")
        lines.append("")

        sql = text(
            """
            SELECT config_id, tracking_error_5d, tracking_error_30d,
                   threshold_breach, paper_cumulative_pnl
            FROM drift_metrics
            WHERE metric_date = :log_date
            ORDER BY config_id
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"log_date": log_date})

            if df.empty:
                lines.append("_No drift metrics for this date._")
            else:
                lines.append(_df_to_markdown(df))
        except Exception as exc:
            logger.warning("_section_drift failed: %s", exc)
            lines.append(f"_Query error: {exc}_")

        lines.append("")
        return lines

    def _section_risk_state(self) -> list[str]:
        """Query dim_risk_state row 1."""
        lines: list[str] = []
        lines.append("## 7. Risk State")
        lines.append("")

        sql = text(
            """
            SELECT trading_state, halted_at, halted_reason, drift_paused, drift_paused_at
            FROM dim_risk_state
            WHERE state_id = 1
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn)

            if df.empty:
                lines.append("_No risk state row found (state_id=1)._")
            else:
                lines.append(_df_to_markdown(df))
        except Exception as exc:
            logger.warning("_section_risk_state failed: %s", exc)
            lines.append(f"_Query error: {exc}_")

        lines.append("")
        return lines
