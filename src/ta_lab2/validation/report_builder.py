"""
report_builder.py
~~~~~~~~~~~~~~~~~
ValidationReportBuilder -- generates the end-of-period V1 validation report.

Produces:
  - A comprehensive Markdown report (V1_VALIDATION_REPORT.md) with:
      - Gate scorecard (all 7 gates: BT-01, BT-02, VAL-01..VAL-05)
      - Per-VAL section narratives with evidence
      - Links to generated Plotly charts
      - Methodology and data sources appendix
  - 5 Plotly HTML/PNG charts:
      1. Equity curve overlay (fills-based vs drift replay)
      2. Drawdown chart
      3. Tracking error time series
      4. Slippage distribution histogram
      5. Kill switch event timeline

Usage::

    from datetime import date
    from sqlalchemy import create_engine
    from ta_lab2.validation.report_builder import ValidationReportBuilder

    engine = create_engine(db_url)
    builder = ValidationReportBuilder(engine)
    report_path = builder.generate_report(
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
        output_dir="reports/validation",
    )
    print("Report written to:", report_path)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.validation.gate_framework import (
    GateResult,
    GateStatus,
    build_gate_scorecard,
)

logger = logging.getLogger(__name__)

# Project root: validation/ -> ta_lab2/ -> src/ -> project_root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Engine helper
# ---------------------------------------------------------------------------


def _get_engine(db_url: str | None = None) -> Engine:
    """Create SQLAlchemy engine with NullPool (same pattern as scorecard)."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.db.config import resolve_db_url

    url = db_url or resolve_db_url()
    return create_engine(url, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Convert DataFrame to GitHub-flavored Markdown table."""
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


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------


def _save_chart(fig: go.Figure, filename: str, charts_dir: Path) -> str:
    """Save Plotly figure as PNG (via kaleido) or HTML fallback.

    Returns path relative to charts_dir's parent (output_dir) for
    Markdown embedding.
    """
    charts_dir.mkdir(parents=True, exist_ok=True)
    png_path = charts_dir / f"{filename}.png"
    html_path = charts_dir / f"{filename}.html"

    try:
        fig.write_image(str(png_path), width=900, height=450, scale=1.5)
        rel = f"charts/{filename}.png"
        logger.info("Saved chart: %s", png_path)
        return rel
    except Exception as exc:
        logger.warning(
            "kaleido PNG export failed (%s) -- falling back to HTML: %s",
            type(exc).__name__,
            exc,
        )
        fig.write_html(str(html_path))
        rel = f"charts/{filename}.html"
        logger.info("Saved chart (HTML fallback): %s", html_path)
        return rel


def _embed_chart(rel_path: str, alt_text: str) -> str:
    """Return Markdown snippet to embed chart (img tag or link)."""
    if rel_path.endswith(".png"):
        return f"![{alt_text}]({rel_path})"
    return f"[{alt_text}]({rel_path})"


# ---------------------------------------------------------------------------
# ValidationReportBuilder
# ---------------------------------------------------------------------------


class ValidationReportBuilder:
    """Generates the end-of-period V1 validation report.

    Assembles evidence from the gate framework, daily logs, audit checker,
    and kill switch exercise into a single Markdown + Plotly deliverable.

    Args:
        engine: SQLAlchemy Engine connected to the project database.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_report(
        self,
        start_date: date,
        end_date: date,
        output_dir: str = "reports/validation",
        generate_charts: bool = True,
    ) -> str:
        """Generate the comprehensive V1 validation Markdown report.

        Steps:
          1. Creates output_dir and charts/ subdirectory.
          2. Runs build_gate_scorecard() to score all 7 gates.
          3. Generates 5 Plotly charts (gracefully None when no data).
          4. Assembles and writes V1_VALIDATION_REPORT.md.

        Args:
            start_date:      Inclusive start of the validation period.
            end_date:        Inclusive end of the validation period.
            output_dir:      Directory to write the report and charts.
            generate_charts: Set to False to skip chart generation.

        Returns:
            Absolute path to the written V1_VALIDATION_REPORT.md file.
        """
        output_path = Path(output_dir)
        if not output_path.is_absolute():
            output_path = _PROJECT_ROOT / output_dir
        output_path.mkdir(parents=True, exist_ok=True)
        charts_dir = output_path / "charts"

        generated_at = datetime.now(timezone.utc).isoformat()
        duration_days = (end_date - start_date).days + 1

        # Step 1: Run gate scorecard
        logger.info("Running gate scorecard for %s to %s ...", start_date, end_date)
        gates = build_gate_scorecard(self._engine, start_date, end_date)

        # Step 2: Generate charts (each returns relative path or None)
        chart_equity: Optional[str] = None
        chart_drawdown: Optional[str] = None
        chart_te: Optional[str] = None
        chart_slippage: Optional[str] = None
        chart_ks: Optional[str] = None

        if generate_charts:
            logger.info("Generating charts...")
            chart_equity = self._build_equity_curve(start_date, end_date, charts_dir)
            chart_drawdown = self._build_drawdown_chart(
                start_date, end_date, charts_dir
            )
            chart_te = self._build_tracking_error_chart(
                start_date, end_date, charts_dir
            )
            chart_slippage = self._build_slippage_chart(
                start_date, end_date, charts_dir
            )
            chart_ks = self._build_kill_switch_timeline(
                start_date, end_date, charts_dir
            )

        # Step 3: Assemble Markdown
        logger.info("Assembling Markdown report...")
        content = self._assemble_report(
            start_date=start_date,
            end_date=end_date,
            generated_at=generated_at,
            duration_days=duration_days,
            gates=gates,
            chart_equity=chart_equity,
            chart_drawdown=chart_drawdown,
            chart_te=chart_te,
            chart_slippage=chart_slippage,
            chart_ks=chart_ks,
        )

        # Step 4: Write report
        report_path = output_path / "V1_VALIDATION_REPORT.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        logger.info("V1 validation report written to: %s", report_path)
        return str(report_path.resolve())

    # ------------------------------------------------------------------
    # Chart generators
    # ------------------------------------------------------------------

    def _build_equity_curve(
        self, start_date: date, end_date: date, charts_dir: Path
    ) -> Optional[str]:
        """Chart 1: Equity curve overlay (fills-based + drift replay P&L).

        Sign convention note:
          - Fills-based P&L sums signed cash flows (buy=negative, sell=positive).
          - Drift replay P&L (paper_cumulative_pnl) tracks mark-to-market.
          Divergence is expected for open positions.
        """
        # Query fills-based daily P&L
        fills_sql = text(
            """
            SELECT
                f.filled_at::date AS trade_date,
                SUM(
                    CASE
                        WHEN f.side = 'sell' THEN  f.fill_price * f.fill_qty
                        ELSE                       -f.fill_price * f.fill_qty
                    END
                ) AS daily_pnl
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            WHERE f.filled_at::date BETWEEN :start_date AND :end_date
            GROUP BY f.filled_at::date
            ORDER BY f.filled_at::date
            """
        )
        # Query drift replay P&L per config
        drift_sql = text(
            """
            SELECT metric_date, config_id, paper_cumulative_pnl
            FROM drift_metrics
            WHERE metric_date BETWEEN :start_date AND :end_date
              AND paper_cumulative_pnl IS NOT NULL
            ORDER BY config_id, metric_date
            """
        )
        try:
            params = {"start_date": start_date, "end_date": end_date}
            with self._engine.connect() as conn:
                fills_df = pd.read_sql(fills_sql, conn, params=params)
                drift_df = pd.read_sql(drift_sql, conn, params=params)
        except Exception as exc:
            logger.warning("_build_equity_curve query failed: %s", exc)
            return None

        if fills_df.empty and drift_df.empty:
            logger.info("No fills or drift data -- skipping equity curve chart")
            return None

        fig = go.Figure()

        if not fills_df.empty:
            fills_df["trade_date"] = pd.to_datetime(fills_df["trade_date"])
            fills_df = fills_df.sort_values("trade_date")
            fills_df["cumulative_pnl"] = fills_df["daily_pnl"].cumsum()
            fig.add_trace(
                go.Scatter(
                    x=fills_df["trade_date"],
                    y=fills_df["cumulative_pnl"],
                    mode="lines+markers",
                    name="Paper Fills P&L",
                    line=dict(color="#2563eb", width=2),
                    marker=dict(size=6),
                )
            )

        if not drift_df.empty:
            drift_df["metric_date"] = pd.to_datetime(drift_df["metric_date"])
            colors = ["#16a34a", "#dc2626", "#9333ea", "#ca8a04"]
            for i, config_id in enumerate(drift_df["config_id"].unique()):
                sub = drift_df[drift_df["config_id"] == config_id].sort_values(
                    "metric_date"
                )
                fig.add_trace(
                    go.Scatter(
                        x=sub["metric_date"],
                        y=sub["paper_cumulative_pnl"],
                        mode="lines",
                        name=f"Drift Replay P&L config_id={config_id}",
                        line=dict(
                            color=colors[i % len(colors)], width=1.5, dash="dash"
                        ),
                    )
                )

        fig.update_layout(
            title="V1 Validation: Equity Curve Overlay",
            xaxis_title="Date",
            yaxis_title="Cumulative P&L (USD)",
            template="plotly_white",
            legend=dict(x=0.01, y=0.99),
            margin=dict(l=60, r=20, t=80, b=60),
            height=450,
            annotations=[
                dict(
                    text=(
                        "Note: Fills P&L = realized cash flow; "
                        "Drift Replay P&L = mark-to-market. "
                        "Divergence is expected for open positions."
                    ),
                    xref="paper",
                    yref="paper",
                    x=0,
                    y=-0.18,
                    showarrow=False,
                    font=dict(size=10, color="gray"),
                    align="left",
                )
            ],
        )
        return _save_chart(fig, "equity_curve", charts_dir)

    def _build_drawdown_chart(
        self, start_date: date, end_date: date, charts_dir: Path
    ) -> Optional[str]:
        """Chart 2: Drawdown chart from fills-based equity curve."""
        fills_sql = text(
            """
            SELECT
                f.filled_at::date AS trade_date,
                SUM(
                    CASE
                        WHEN f.side = 'sell' THEN  f.fill_price * f.fill_qty
                        ELSE                       -f.fill_price * f.fill_qty
                    END
                ) AS daily_pnl
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            WHERE f.filled_at::date BETWEEN :start_date AND :end_date
            GROUP BY f.filled_at::date
            ORDER BY f.filled_at::date
            """
        )
        try:
            params = {"start_date": start_date, "end_date": end_date}
            with self._engine.connect() as conn:
                fills_df = pd.read_sql(fills_sql, conn, params=params)
        except Exception as exc:
            logger.warning("_build_drawdown_chart query failed: %s", exc)
            return None

        if fills_df.empty:
            logger.info("No fills data -- skipping drawdown chart")
            return None

        fills_df["trade_date"] = pd.to_datetime(fills_df["trade_date"])
        fills_df = fills_df.sort_values("trade_date")
        fills_df["cumulative_pnl"] = fills_df["daily_pnl"].cumsum()

        # Compute drawdown: (cum_pnl - running_peak) / |running_peak|
        cum_pnl = fills_df["cumulative_pnl"]
        running_peak = cum_pnl.cummax()
        # Only compute where running peak > 0 to avoid division issues
        drawdown = pd.Series(index=fills_df.index, dtype=float)
        mask = running_peak > 0
        drawdown[mask] = (cum_pnl[mask] - running_peak[mask]) / running_peak[mask].abs()
        drawdown[~mask] = 0.0

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=fills_df["trade_date"],
                y=drawdown * 100,  # convert to percent
                mode="lines",
                fill="tozeroy",
                name="Drawdown (%)",
                line=dict(color="#dc2626", width=1.5),
                fillcolor="rgba(220,38,38,0.2)",
            )
        )
        fig.update_layout(
            title="V1 Validation: Drawdown from Peak (Fills-Based P&L)",
            xaxis_title="Date",
            yaxis_title="Drawdown (%)",
            template="plotly_white",
            margin=dict(l=60, r=20, t=60, b=60),
            height=400,
        )
        return _save_chart(fig, "drawdown", charts_dir)

    def _build_tracking_error_chart(
        self, start_date: date, end_date: date, charts_dir: Path
    ) -> Optional[str]:
        """Chart 3: Tracking error time series (5d and 30d)."""
        sql = text(
            """
            SELECT metric_date, tracking_error_5d, tracking_error_30d
            FROM drift_metrics
            WHERE metric_date BETWEEN :start_date AND :end_date
            ORDER BY metric_date
            """
        )
        try:
            params = {"start_date": start_date, "end_date": end_date}
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning("_build_tracking_error_chart query failed: %s", exc)
            return None

        if df.empty:
            logger.info("No drift metrics data -- skipping tracking error chart")
            return None

        df["metric_date"] = pd.to_datetime(df["metric_date"])
        df = df.sort_values("metric_date")

        fig = go.Figure()
        if "tracking_error_5d" in df.columns and df["tracking_error_5d"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df["metric_date"],
                    y=df["tracking_error_5d"] * 100,
                    mode="lines+markers",
                    name="Tracking Error 5d (%)",
                    line=dict(color="#2563eb", width=2),
                    marker=dict(size=5),
                )
            )
        if (
            "tracking_error_30d" in df.columns
            and df["tracking_error_30d"].notna().any()
        ):
            fig.add_trace(
                go.Scatter(
                    x=df["metric_date"],
                    y=df["tracking_error_30d"] * 100,
                    mode="lines+markers",
                    name="Tracking Error 30d (%)",
                    line=dict(color="#9333ea", width=2, dash="dash"),
                    marker=dict(size=5),
                )
            )
        # Threshold line at 1%
        fig.add_hline(
            y=1.0,
            line=dict(color="#dc2626", width=1.5, dash="dot"),
            annotation_text="1% threshold (VAL-02 gate)",
            annotation_position="top right",
        )
        fig.update_layout(
            title="V1 Validation: Tracking Error vs Backtest (VAL-02)",
            xaxis_title="Date",
            yaxis_title="Tracking Error (%)",
            template="plotly_white",
            legend=dict(x=0.01, y=0.99),
            margin=dict(l=60, r=20, t=60, b=60),
            height=420,
        )
        return _save_chart(fig, "tracking_error", charts_dir)

    def _build_slippage_chart(
        self, start_date: date, end_date: date, charts_dir: Path
    ) -> Optional[str]:
        """Chart 4: Slippage distribution histogram (fill vs bar open, in bps)."""
        sql = text(
            """
            SELECT
                ABS(f.fill_price::float - pb.open::float)
                    / NULLIF(pb.open::float, 0) * 10000 AS slippage_bps
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            JOIN price_bars_multi_tf_u pb
                ON  pb.id   = o.asset_id
                AND pb.tf   = '1D'
            AND pb.venue_id = 1
            AND pb.alignment_source = 'multi_tf'
                AND pb.ts::date = f.filled_at::date
            WHERE f.filled_at::date BETWEEN :start_date AND :end_date
              AND pb.open IS NOT NULL
              AND pb.open::float > 0
            """
        )
        try:
            params = {"start_date": start_date, "end_date": end_date}
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning("_build_slippage_chart query failed: %s", exc)
            return None

        if df.empty or df["slippage_bps"].dropna().empty:
            logger.info("No fills data -- skipping slippage chart")
            return None

        bps_values = df["slippage_bps"].dropna().tolist()

        fig = go.Figure()
        fig.add_trace(
            go.Histogram(
                x=bps_values,
                name="Slippage (bps)",
                marker_color="#2563eb",
                opacity=0.75,
                nbinsx=30,
            )
        )
        # Threshold line at 50 bps
        fig.add_vline(
            x=50,
            line=dict(color="#dc2626", width=2, dash="dot"),
            annotation_text="50 bps threshold (VAL-03 gate)",
            annotation_position="top right",
        )
        fig.update_layout(
            title="V1 Validation: Slippage Distribution (VAL-03)",
            xaxis_title="Slippage (bps)",
            yaxis_title="Count",
            template="plotly_white",
            margin=dict(l=60, r=20, t=60, b=60),
            height=420,
        )
        return _save_chart(fig, "slippage_distribution", charts_dir)

    def _build_kill_switch_timeline(
        self, start_date: date, end_date: date, charts_dir: Path
    ) -> Optional[str]:
        """Chart 5: Kill switch event timeline (real and exercise events)."""
        sql = text(
            """
            SELECT event_id, event_ts, event_type, trigger_source, reason, operator
            FROM risk_events
            WHERE event_type LIKE 'kill_switch%'
              AND event_ts BETWEEN :start_ts AND :end_ts
            ORDER BY event_ts
            """
        )
        try:
            params = {
                "start_ts": datetime.combine(start_date, datetime.min.time()),
                "end_ts": datetime.combine(end_date, datetime.max.time()),
            }
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning("_build_kill_switch_timeline query failed: %s", exc)
            return None

        if df.empty:
            logger.info("No kill switch events -- skipping timeline chart")
            return None

        df["event_ts"] = pd.to_datetime(df["event_ts"])

        # Classify events
        def _classify(row) -> str:
            reason = str(row.get("reason") or "")
            if "V1 EXERCISE" in reason:
                return "Exercise"
            event_type = str(row.get("event_type") or "")
            if "activated" in event_type or "triggered" in event_type:
                return "Real Activated"
            return "Real Disabled"

        df["category"] = df.apply(_classify, axis=1)

        color_map = {
            "Exercise": "#ca8a04",
            "Real Activated": "#dc2626",
            "Real Disabled": "#16a34a",
        }

        fig = go.Figure()
        for category, color in color_map.items():
            sub = df[df["category"] == category]
            if sub.empty:
                continue
            hover_text = (
                sub["event_type"].astype(str)
                + " | "
                + sub["trigger_source"].fillna("unknown").astype(str)
                + "<br>"
                + sub["reason"].fillna("").astype(str)
            )
            fig.add_trace(
                go.Scatter(
                    x=sub["event_ts"],
                    y=[category] * len(sub),
                    mode="markers",
                    name=category,
                    marker=dict(
                        color=color,
                        size=14,
                        symbol="diamond",
                        line=dict(width=1, color="white"),
                    ),
                    text=hover_text,
                    hovertemplate="%{text}<extra></extra>",
                )
            )

        fig.update_layout(
            title="V1 Validation: Kill Switch Event Timeline (VAL-04)",
            xaxis_title="Date / Time",
            yaxis_title="Event Category",
            template="plotly_white",
            legend=dict(x=0.01, y=0.99),
            margin=dict(l=120, r=20, t=60, b=60),
            height=380,
        )
        return _save_chart(fig, "kill_switch_timeline", charts_dir)

    # ------------------------------------------------------------------
    # Report assembly
    # ------------------------------------------------------------------

    def _assemble_report(
        self,
        start_date: date,
        end_date: date,
        generated_at: str,
        duration_days: int,
        gates: list[GateResult],
        chart_equity: Optional[str],
        chart_drawdown: Optional[str],
        chart_te: Optional[str],
        chart_slippage: Optional[str],
        chart_ks: Optional[str],
    ) -> str:
        """Assemble the full Markdown report content."""
        lines: list[str] = []

        # Header
        lines.append("# V1 Validation Report")
        lines.append("")
        lines.append(f"**Period:** {start_date} to {end_date}")
        lines.append(f"**Generated:** {generated_at}")
        lines.append(f"**Duration:** {duration_days} calendar days")
        lines.append("")

        # Executive summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(self._build_executive_summary(gates))
        lines.append("")

        # Gate assessment table
        lines.append("## Gate Assessment")
        lines.append("")
        lines.append("| Gate | Criterion | Threshold | Measured | Status | Notes |")
        lines.append("|------|-----------|-----------|----------|--------|-------|")
        for gate in gates:
            status_badge = self._status_badge(gate.status)
            notes = gate.notes or (gate.mitigation or "")
            notes_short = (notes[:80] + "...") if len(notes) > 80 else notes
            lines.append(
                f"| {gate.gate_id} "
                f"| {gate.gate_name} "
                f"| {gate.threshold} "
                f"| {gate.measured_value} "
                f"| {status_badge} "
                f"| {notes_short} |"
            )
        lines.append("")

        # Per-VAL sections
        gate_map = {g.gate_id: g for g in gates}

        lines.append("## VAL-01: Paper Trading Duration")
        lines.append("")
        lines.append(self._section_val01(gate_map.get("VAL-01")))
        lines.append("")

        lines.append("## VAL-02: Tracking Error")
        lines.append("")
        lines.append(self._section_val02(gate_map.get("VAL-02"), chart_te))
        lines.append("")

        lines.append("## VAL-03: Slippage")
        lines.append("")
        lines.append(self._section_val03(gate_map.get("VAL-03"), chart_slippage))
        lines.append("")

        lines.append("## VAL-04: Kill Switch")
        lines.append("")
        lines.append(self._section_val04(gate_map.get("VAL-04"), chart_ks))
        lines.append("")

        lines.append("## VAL-05: Log Audit")
        lines.append("")
        lines.append(self._section_val05(gate_map.get("VAL-05")))
        lines.append("")

        # Backtest gates
        lines.append("## Backtest Gates (from Phase 42)")
        lines.append("")
        lines.append(self._section_backtest_gates(gate_map))
        lines.append("")

        # Charts
        charts_available = [
            (chart_equity, "Equity Curve Overlay", "equity_curve"),
            (chart_drawdown, "Drawdown Chart", "drawdown"),
            (chart_te, "Tracking Error Time Series", "tracking_error"),
            (chart_slippage, "Slippage Distribution", "slippage_distribution"),
            (chart_ks, "Kill Switch Event Timeline", "kill_switch_timeline"),
        ]
        has_charts = any(c[0] for c in charts_available)
        if has_charts:
            lines.append("## Charts")
            lines.append("")
            for rel_path, alt_text, _ in charts_available:
                if rel_path:
                    lines.append(_embed_chart(rel_path, alt_text))
                    lines.append("")

        # Methodology
        lines.append("## Methodology")
        lines.append("")
        lines.append("- Validation period: 14 calendar days, crypto 24/7 markets")
        lines.append("- Both strategies active simultaneously from day 1")
        lines.append("- Gate framework: PASS/CONDITIONAL/FAIL (3-tier)")
        lines.append("- Kill switch tested manually and via engineered auto-trigger")
        lines.append("- Audit: automated gap detection + human sign-off")
        lines.append(
            "- **P&L reconciliation note:** Fills-based P&L (cash flow) and drift replay "
            "P&L (mark-to-market) use different methodologies. "
            "Divergence is expected when open positions exist."
        )
        lines.append("")

        # Data sources appendix
        lines.append("## Appendix: Data Sources")
        lines.append("")
        lines.append(self._section_data_sources(start_date, end_date))
        lines.append("")

        lines.append("---")
        lines.append("*Generated by ValidationReportBuilder (V1 Validation Phase 53)*")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_executive_summary(self, gates: list[GateResult]) -> str:
        n_pass = sum(1 for g in gates if g.status == GateStatus.PASS)
        n_conditional = sum(1 for g in gates if g.status == GateStatus.CONDITIONAL)
        n_fail = sum(1 for g in gates if g.status == GateStatus.FAIL)
        total = len(gates)

        verdict_parts = []
        if n_pass > 0:
            verdict_parts.append(f"{n_pass}/{total} gates PASS")
        if n_conditional > 0:
            verdict_parts.append(
                f"{n_conditional}/{total} CONDITIONAL (mitigations documented)"
            )
        if n_fail > 0:
            verdict_parts.append(f"{n_fail}/{total} FAIL (require resolution)")

        if n_fail == 0 and n_conditional == 0:
            overall = "V1 paper trading validation PASSED all gates."
        elif n_fail == 0:
            overall = (
                "V1 paper trading validation passed hard gates; "
                "CONDITIONAL gates have documented mitigations."
            )
        else:
            overall = (
                "V1 paper trading validation has outstanding FAIL gates "
                "requiring resolution before V1 certification."
            )

        return (
            f"{overall} "
            f"Assessment summary: {', '.join(verdict_parts)}. "
            "See Gate Assessment table and per-VAL sections for full evidence."
        )

    @staticmethod
    def _status_badge(status: GateStatus) -> str:
        mapping = {
            GateStatus.PASS: "PASS",
            GateStatus.CONDITIONAL: "CONDITIONAL",
            GateStatus.FAIL: "FAIL",
        }
        return mapping.get(status, str(status))

    def _section_val01(self, gate: Optional[GateResult]) -> str:
        lines = []
        lines.append(
            "**Criterion:** Both strategies must run daily for 14 consecutive calendar days."
        )
        lines.append("")
        lines.append(
            "**Evidence source:** `executor_run_log` -- distinct successful run dates."
        )
        if gate:
            lines.append("")
            lines.append(f"**Measured:** {gate.measured_value}")
            lines.append(f"**Status:** {self._status_badge(gate.status)}")
            if gate.notes:
                lines.append(f"**Notes:** {gate.notes}")
        return "\n".join(lines)

    def _section_val02(
        self, gate: Optional[GateResult], chart_te: Optional[str]
    ) -> str:
        lines = []
        lines.append(
            "**Criterion:** Max 5-day rolling tracking error vs backtest < 1%."
        )
        lines.append("")
        lines.append(
            "Tracking error measures how closely paper trading execution tracks the "
            "backtest signal -- deviations indicate fill model divergence or data gaps."
        )
        lines.append("")
        lines.append("**Evidence source:** `drift_metrics.tracking_error_5d`")
        if gate:
            lines.append("")
            lines.append(f"**Measured:** {gate.measured_value}")
            lines.append(f"**Status:** {self._status_badge(gate.status)}")
            if gate.mitigation:
                lines.append(f"**Mitigation:** {gate.mitigation}")
        if chart_te:
            lines.append("")
            lines.append(_embed_chart(chart_te, "Tracking Error Time Series"))
        return "\n".join(lines)

    def _section_val03(
        self, gate: Optional[GateResult], chart_slippage: Optional[str]
    ) -> str:
        lines = []
        lines.append(
            "**Criterion:** Mean absolute slippage < 50 bps (fill price vs bar open)."
        )
        lines.append("")
        lines.append(
            "Slippage is measured as the absolute deviation between the paper fill price "
            "and the opening bar price on the fill date. For a paper trader at market open "
            "prices, this should be minimal."
        )
        lines.append("")
        lines.append("**Evidence source:** `fills` JOIN `price_bars_multi_tf_u` (tf=1D)")
        if gate:
            lines.append("")
            lines.append(f"**Measured:** {gate.measured_value}")
            lines.append(f"**Status:** {self._status_badge(gate.status)}")
            if gate.mitigation:
                lines.append(f"**Mitigation:** {gate.mitigation}")
        if chart_slippage:
            lines.append("")
            lines.append(_embed_chart(chart_slippage, "Slippage Distribution"))
        return "\n".join(lines)

    def _section_val04(
        self, gate: Optional[GateResult], chart_ks: Optional[str]
    ) -> str:
        lines = []
        lines.append(
            "**Criterion:** Kill switch triggered both manually AND automatically "
            "during the validation period."
        )
        lines.append("")
        lines.append(
            "The kill switch exercise (Plan 03) requires at least one manual trigger "
            "(operator action) and at least one automatic trigger (daily loss stop or "
            "portfolio circuit breaker). Exercise events (tagged V1 EXERCISE) are "
            "tracked separately from real incidents."
        )
        lines.append("")
        lines.append(
            "**Evidence source:** `risk_events` + "
            "`reports/validation/kill_switch_exercise/`"
        )
        if gate:
            lines.append("")
            lines.append(f"**Measured:** {gate.measured_value}")
            lines.append(f"**Status:** {self._status_badge(gate.status)}")
        if chart_ks:
            lines.append("")
            lines.append(_embed_chart(chart_ks, "Kill Switch Event Timeline"))
        return "\n".join(lines)

    def _section_val05(self, gate: Optional[GateResult]) -> str:
        lines = []
        lines.append(
            "**Criterion:** No unexplained gaps, no silent failures, "
            "full order/fill audit trail."
        )
        lines.append("")
        lines.append(
            "Automated gap detection (AuditChecker) runs 6 checks: missing executor run "
            "days, error runs, orphaned orders, position/fill consistency, stale price "
            "data, and drift metric gaps. All anomalies must be signed off by a human "
            "operator before PASS status is granted."
        )
        lines.append("")
        lines.append(
            "**Evidence source:** `executor_run_log`, `orders`, `fills`, "
            "`reports/validation/audit/`"
        )
        if gate:
            lines.append("")
            lines.append(f"**Measured:** {gate.measured_value}")
            lines.append(f"**Status:** {self._status_badge(gate.status)}")
        return "\n".join(lines)

    def _section_backtest_gates(self, gate_map: dict) -> str:
        lines = []
        lines.append(
            "Backtest gates are pre-computed from the Phase 42 strategy bake-off. "
            "They are fixed and not re-evaluated during the validation period."
        )
        lines.append("")

        bt01 = gate_map.get("BT-01")
        bt02 = gate_map.get("BT-02")

        if bt01:
            lines.append(f"**BT-01 ({bt01.gate_name}):** {bt01.threshold}")
            lines.append(f"- Measured: {bt01.measured_value}")
            lines.append(f"- Status: {self._status_badge(bt01.status)}")
            lines.append(f"- Evidence: {', '.join(bt01.evidence_sources)}")
            lines.append("")
        if bt02:
            lines.append(f"**BT-02 ({bt02.gate_name}):** {bt02.threshold}")
            lines.append(f"- Measured: {bt02.measured_value}")
            lines.append(f"- Status: {self._status_badge(bt02.status)}")
            if bt02.mitigation:
                lines.append(f"- Mitigation: {bt02.mitigation}")
            lines.append(f"- Evidence: {', '.join(bt02.evidence_sources)}")
        return "\n".join(lines)

    def _section_data_sources(self, start_date: date, end_date: date) -> str:
        """Query row counts from key tables and format as Markdown table."""
        tables = [
            ("executor_run_log", "started_at::date", "Executor run log"),
            ("fills", "filled_at::date", "Paper trade fills"),
            ("orders", "created_at::date", "Paper trade orders"),
            ("drift_metrics", "metric_date", "Drift monitor metrics"),
            ("risk_events", "event_ts::date", "Risk events (incl. kill switch)"),
        ]

        lines = [
            "| Table | Purpose | Rows in Period |",
            "|-------|---------|----------------|",
        ]

        for table, date_col, purpose in tables:
            try:
                sql = text(
                    f"SELECT COUNT(*) FROM {table} "  # noqa: S608
                    f"WHERE {date_col} BETWEEN :s AND :e"
                )
                with self._engine.connect() as conn:
                    row = conn.execute(sql, {"s": start_date, "e": end_date}).fetchone()
                count = int(row[0]) if row else 0
            except Exception:
                count = "N/A"
            lines.append(f"| `{table}` | {purpose} | {count} |")

        return "\n".join(lines)
