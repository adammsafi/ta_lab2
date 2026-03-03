"""
ReportGenerator -- weekly drift report with Markdown + Plotly HTML charts.

Produces three charts per report:
  1. Equity curve overlay (paper vs replay P&L per config)
  2. Tracking error time series (5d + 30d rolling TE with threshold line)
  3. Attribution waterfall (attr_* deltas per config, opt-in via --with-attribution)

Output follows the gitignored ``reports/drift/`` pattern established in Phase 42
for bakeoff scorecard outputs.

Usage::

    from datetime import date
    from sqlalchemy import create_engine
    from ta_lab2.drift.drift_report import ReportGenerator

    engine = create_engine(db_url)
    reporter = ReportGenerator(engine)
    report_path = reporter.generate_weekly_report(
        week_start=date(2026, 2, 18),
        week_end=date(2026, 2, 25),
        output_dir="reports/drift",
    )
    print("Report written to:", report_path)
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _df_to_markdown(df: pd.DataFrame) -> str:
    """
    Convert a DataFrame to a GitHub-flavored Markdown table without requiring
    the ``tabulate`` optional dependency.

    Parameters
    ----------
    df:
        DataFrame to render.

    Returns
    -------
    Markdown table string.
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


# Attribution column names present in cmc_drift_metrics (added in Plan 47-01 DDL).
# attr_macro_regime_delta added in Phase 72 OBSV-04 (migration e6f7a8b9c0d1).
_ATTR_COLUMNS = [
    "attr_baseline_pnl",
    "attr_fee_delta",
    "attr_slippage_delta",
    "attr_timing_delta",
    "attr_data_revision_delta",
    "attr_sizing_delta",
    "attr_regime_delta",
    "attr_macro_regime_delta",  # Phase 72 OBSV-04
    "attr_unexplained",
]


class ReportGenerator:
    """
    Weekly drift report generator.

    Loads drift metrics from ``cmc_drift_metrics``, generates Plotly HTML charts,
    and renders a Markdown report with summary tables, threshold status, and
    attribution section (when attr_* columns are populated).

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the project database.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_weekly_report(
        self,
        week_start: Optional[date] = None,
        week_end: Optional[date] = None,
        output_dir: str = "reports/drift",
    ) -> str:
        """
        Generate a weekly drift guard report.

        Parameters
        ----------
        week_start:
            Report window start.  Defaults to week_end - 7 days.
        week_end:
            Report window end.  Defaults to today.
        output_dir:
            Directory for report and chart files.  Created if absent.

        Returns
        -------
        Absolute path to the generated Markdown report file.
        """
        if week_end is None:
            week_end = date.today()
        if week_start is None:
            week_start = week_end - timedelta(days=7)

        os.makedirs(output_dir, exist_ok=True)

        charts_subdir = os.path.join(output_dir, f"charts_{week_end.isoformat()}")
        os.makedirs(charts_subdir, exist_ok=True)

        # Load drift metrics for the period.
        df = self._load_drift_metrics_df(week_start, week_end)

        if df.empty:
            logger.warning(
                "No drift metrics found for %s to %s -- generating minimal report",
                week_start,
                week_end,
            )
            return self._write_minimal_report(week_start, week_end, output_dir)

        # Determine default TE threshold (fall back to 0.015 if not in DB).
        threshold = self._load_te_threshold()

        # Generate charts.
        chart_paths: dict[str, Optional[str]] = {}

        fig_equity = self._plot_equity_overlay(df)
        equity_path = os.path.join(charts_subdir, "equity_overlay.html")
        fig_equity.write_html(equity_path)
        chart_paths["equity_overlay"] = equity_path

        fig_te = self._plot_tracking_error(df, threshold)
        te_path = os.path.join(charts_subdir, "tracking_error.html")
        fig_te.write_html(te_path)
        chart_paths["tracking_error"] = te_path

        fig_attr = self._plot_attribution_waterfall(df)
        if fig_attr is not None:
            attr_path = os.path.join(charts_subdir, "attribution_waterfall.html")
            fig_attr.write_html(attr_path)
            chart_paths["attribution_waterfall"] = attr_path
        else:
            chart_paths["attribution_waterfall"] = None

        # Render and write Markdown report.
        md_content = self._render_markdown(df, week_start, week_end, chart_paths)
        report_filename = f"drift_report_{week_end.isoformat()}.md"
        report_path = os.path.join(output_dir, report_filename)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(md_content)

        logger.info("Drift report written to: %s", report_path)
        return os.path.abspath(report_path)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_drift_metrics_df(self, start: date, end: date) -> pd.DataFrame:
        """
        Load drift metrics rows from cmc_drift_metrics for a date range.

        Parameters
        ----------
        start:
            Inclusive start date.
        end:
            Inclusive end date.

        Returns
        -------
        DataFrame with all cmc_drift_metrics columns, ordered by metric_date, config_id.
        Empty DataFrame when no rows are found or the table does not exist.
        """
        sql = text(
            """
            SELECT *
            FROM public.cmc_drift_metrics
            WHERE metric_date BETWEEN :start AND :end
            ORDER BY metric_date, config_id
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"start": start, "end": end})
        except Exception as exc:
            logger.warning(
                "_load_drift_metrics_df failed: %s -- returning empty DataFrame", exc
            )
            return pd.DataFrame()

        return df

    def _load_te_threshold(self) -> float:
        """
        Load the portfolio-wide tracking error threshold from dim_risk_limits.

        Returns 0.015 (1.5%) as a safe default when the table is absent or no row found.
        """
        sql = text(
            """
            SELECT drift_tracking_error_threshold_5d
            FROM public.dim_risk_limits
            WHERE asset_id IS NULL AND strategy_id IS NULL
            LIMIT 1
            """
        )
        try:
            with self._engine.connect() as conn:
                row = conn.execute(sql).fetchone()
            if row and row[0] is not None:
                return float(row[0])
        except Exception as exc:
            logger.debug("_load_te_threshold failed: %s -- using 0.015", exc)
        return 0.015

    # ------------------------------------------------------------------
    # Chart generation
    # ------------------------------------------------------------------

    def _plot_equity_overlay(self, df: pd.DataFrame) -> go.Figure:
        """
        Plot paper vs replay cumulative P&L per config_id.

        Parameters
        ----------
        df:
            DataFrame with columns: metric_date, config_id,
            paper_cumulative_pnl, replay_pit_cumulative_pnl.

        Returns
        -------
        Plotly Figure with one pair of traces per config_id.
        """
        fig = go.Figure()

        paper_col = "paper_cumulative_pnl"
        replay_col = "replay_pit_cumulative_pnl"

        config_ids = (
            sorted(df["config_id"].unique()) if "config_id" in df.columns else []
        )

        for config_id in config_ids:
            subset = df[df["config_id"] == config_id].sort_values("metric_date")
            x = (
                subset["metric_date"]
                if "metric_date" in subset.columns
                else subset.index
            )

            if paper_col in subset.columns:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=subset[paper_col],
                        name=f"Paper (config {config_id})",
                        line={"color": "blue", "width": 2},
                        mode="lines",
                    )
                )

            if replay_col in subset.columns:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=subset[replay_col],
                        name=f"Replay (config {config_id})",
                        line={"color": "orange", "width": 2, "dash": "dash"},
                        mode="lines",
                    )
                )

        fig.update_layout(
            title="Equity Curve Overlay: Paper vs Replay",
            xaxis_title="Date",
            yaxis_title="Cumulative P&L",
            legend={"orientation": "h"},
        )
        return fig

    def _plot_tracking_error(self, df: pd.DataFrame, threshold: float) -> go.Figure:
        """
        Plot rolling tracking error time series with a threshold line.

        Parameters
        ----------
        df:
            DataFrame with columns: metric_date, tracking_error_5d, tracking_error_30d.
        threshold:
            Horizontal threshold line value (e.g. 0.015 for 1.5%).

        Returns
        -------
        Plotly Figure with TE traces and a horizontal threshold shape.
        """
        fig = go.Figure()

        x_col = "metric_date"
        df_sorted = df.sort_values(x_col) if x_col in df.columns else df

        if "tracking_error_5d" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df_sorted[x_col],
                    y=df_sorted["tracking_error_5d"],
                    name="TE 5-day",
                    line={"color": "royalblue", "width": 2},
                    mode="lines",
                )
            )

        if "tracking_error_30d" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df_sorted[x_col],
                    y=df_sorted["tracking_error_30d"],
                    name="TE 30-day",
                    line={"color": "steelblue", "width": 2, "dash": "dot"},
                    mode="lines",
                )
            )

        # Add horizontal threshold line as a shape.
        fig.add_hline(
            y=threshold,
            line_dash="dash",
            line_color="red",
            annotation_text=f"Threshold ({threshold:.1%})",
            annotation_position="top right",
        )

        fig.update_layout(
            title="Tracking Error Time Series",
            xaxis_title="Date",
            yaxis_title="Tracking Error",
            legend={"orientation": "h"},
        )
        return fig

    def _plot_attribution_waterfall(self, df: pd.DataFrame) -> Optional[go.Figure]:
        """
        Generate attribution waterfall chart from attr_* columns.

        Returns None when all attr_* columns are NULL (attribution not yet run).

        Parameters
        ----------
        df:
            DataFrame containing cmc_drift_metrics rows, possibly with attr_* columns.

        Returns
        -------
        Plotly Figure or None.
        """
        # Check if any attr_* column is present AND non-null.
        available_attr_cols = [c for c in _ATTR_COLUMNS if c in df.columns]
        if not available_attr_cols:
            return None

        # Check if all values are null.
        attr_df = df[available_attr_cols]
        if attr_df.isnull().all().all():
            return None

        # Aggregate mean of each attribution delta across the period.
        delta_cols = [
            c
            for c in available_attr_cols
            if c != "attr_baseline_pnl" and c != "attr_unexplained"
        ]
        labels = []
        values = []
        for col in delta_cols:
            if col in df.columns:
                mean_val = df[col].mean(skipna=True)
                if pd.notna(mean_val):
                    label = col.replace("attr_", "").replace("_delta", "").title()
                    labels.append(label)
                    values.append(float(mean_val))

        if not labels:
            return None

        # Include baseline and residual as context bars.
        all_labels = []
        all_values = []
        all_measures = []

        if "attr_baseline_pnl" in df.columns:
            baseline_mean = df["attr_baseline_pnl"].mean(skipna=True)
            if pd.notna(baseline_mean):
                all_labels.append("Baseline")
                all_values.append(float(baseline_mean))
                all_measures.append("absolute")

        for label, value in zip(labels, values):
            all_labels.append(label)
            all_values.append(value)
            all_measures.append("relative")

        if "attr_unexplained" in df.columns:
            residual_mean = df["attr_unexplained"].mean(skipna=True)
            if pd.notna(residual_mean):
                all_labels.append("Unexplained")
                all_values.append(float(residual_mean))
                all_measures.append("relative")

        # Total bar.
        all_labels.append("Total")
        all_values.append(sum(all_values))
        all_measures.append("total")

        fig = go.Figure(
            go.Waterfall(
                name="Attribution",
                orientation="v",
                measure=all_measures,
                x=all_labels,
                y=all_values,
                connector={"line": {"color": "rgb(63, 63, 63)"}},
                textposition="outside",
                text=[f"{v:.4f}" for v in all_values],
            )
        )
        fig.update_layout(
            title="Drift Attribution Waterfall (mean over period)",
            yaxis_title="P&L Contribution",
            showlegend=False,
        )
        return fig

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def _render_markdown(
        self,
        df: pd.DataFrame,
        week_start: date,
        week_end: date,
        chart_paths: dict[str, Optional[str]],
    ) -> str:
        """
        Build the Markdown report string.

        Parameters
        ----------
        df:
            DataFrame with drift metrics rows.
        week_start:
            Report window start date.
        week_end:
            Report window end date.
        chart_paths:
            Dict mapping chart name to file path (or None when chart was skipped).

        Returns
        -------
        Complete Markdown report as a string.
        """
        from datetime import datetime, timezone

        lines: list[str] = []

        # Header
        lines.append(f"# Drift Guard Weekly Report: {week_start} to {week_end}")
        lines.append("")

        # Summary table
        lines.append("## Summary")
        lines.append("")

        summary_cols = [
            "config_id",
            "asset_id",
            "signal_type",
            "paper_cumulative_pnl",
            "replay_pit_cumulative_pnl",
            "tracking_error_5d",
        ]
        available_cols = [c for c in summary_cols if c in df.columns]

        if available_cols:
            # Build a de-duplicated summary: latest row per (config_id, asset_id).
            summary_df = df[available_cols].copy()
            if "config_id" in summary_df.columns:
                # Sort by metric_date descending and drop duplicates on config/asset
                sort_col = "metric_date" if "metric_date" in df.columns else None
                if sort_col:
                    summary_df = df.sort_values(sort_col, ascending=False)[
                        available_cols
                    ].drop_duplicates(
                        subset=[
                            c for c in ["config_id", "asset_id"] if c in available_cols
                        ]
                    )

            # Compute breach count per config
            breach_col = "threshold_breach"
            if breach_col in df.columns:
                breach_counts = (
                    df[df[breach_col]]
                    .groupby("config_id")
                    .size()
                    .rename("breach_count")
                )
                summary_df = summary_df.join(breach_counts, on="config_id", how="left")
                summary_df["breach_count"] = (
                    summary_df["breach_count"].fillna(0).astype(int)
                )

            lines.append(_df_to_markdown(summary_df))
        else:
            lines.append("_No summary data available._")

        lines.append("")

        # Threshold / pause status
        lines.append("## Threshold Status")
        lines.append("")
        threshold = self._load_te_threshold()
        lines.append(f"- **Tracking error threshold**: {threshold:.1%}")

        if "threshold_breach" in df.columns:
            total_breaches = int(df["threshold_breach"].sum())
            lines.append(f"- **Breaches this week**: {total_breaches}")

        lines.append("")

        # Attribution section
        lines.append("## Attribution")
        lines.append("")
        available_attr = [c for c in _ATTR_COLUMNS if c in df.columns]
        if available_attr and not df[available_attr].isnull().all().all():
            attr_summary = df[[c for c in available_attr if c in df.columns]].mean(
                skipna=True
            )
            lines.append("Attribution averages over the period (mean per config):")
            lines.append("")
            lines.append("| Source | Mean Delta |")
            lines.append("|--------|------------|")
            for col in available_attr:
                if col in attr_summary.index:
                    label = col.replace("attr_", "").replace("_", " ").title()
                    lines.append(f"| {label} | {attr_summary[col]:.6f} |")
        else:
            lines.append(
                "> Attribution not yet run -- use `--with-attribution` flag when running "
                "`run_drift_monitor.py` to populate `attr_*` columns."
            )

        lines.append("")

        # Chart links
        lines.append("## Charts")
        lines.append("")
        chart_labels = {
            "equity_overlay": "Equity Curve Overlay",
            "tracking_error": "Tracking Error Time Series",
            "attribution_waterfall": "Attribution Waterfall",
        }
        for key, label in chart_labels.items():
            path = chart_paths.get(key)
            if path:
                lines.append(f"- [{label}]({os.path.basename(path)})")
            else:
                lines.append(f"- {label}: _not generated (attribution not run)_")

        lines.append("")

        # Footer
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append("---")
        lines.append(f"*Generated at {generated_at} by DriftGuard ReportGenerator*")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Minimal report helpers
    # ------------------------------------------------------------------

    def _write_minimal_report(
        self,
        week_start: date,
        week_end: date,
        output_dir: str,
    ) -> str:
        """Write a minimal 'no data' report and return its path."""
        from datetime import datetime, timezone

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = (
            f"# Drift Guard Weekly Report: {week_start} to {week_end}\n\n"
            f"> **No drift data available** for this period.\n\n"
            f"No rows were found in `cmc_drift_metrics` between {week_start} and {week_end}.\n"
            f"Run the drift monitor first:\n\n"
            f"```bash\n"
            f"python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start {week_start}\n"
            f"```\n\n"
            f"---\n"
            f"*Generated at {generated_at} by DriftGuard ReportGenerator*\n"
        )
        report_filename = f"drift_report_{week_end.isoformat()}.md"
        report_path = os.path.join(output_dir, report_filename)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return os.path.abspath(report_path)
