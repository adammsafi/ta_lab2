"""
generate_validation_report.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
CLI entry point for end-of-period V1 validation report generation.

Generates:
  - reports/validation/V1_VALIDATION_REPORT.md -- Markdown report with gate
    scorecard, per-VAL sections, 5 Plotly charts, methodology and data sources.
  - reports/validation/V1_VALIDATION_REPORT.ipynb -- Jupyter notebook with
    executable cells that re-query the DB and reproduce charts interactively.

Usage::

    # Full report (Markdown + charts + notebook):
    python -m ta_lab2.scripts.validation.generate_validation_report \\
        --start-date 2026-03-01 --end-date 2026-03-14

    # Skip notebook:
    python -m ta_lab2.scripts.validation.generate_validation_report \\
        --start-date 2026-03-01 --end-date 2026-03-14 --no-notebook

    # Skip charts (text-only Markdown):
    python -m ta_lab2.scripts.validation.generate_validation_report \\
        --start-date 2026-03-01 --end-date 2026-03-14 --no-charts

    # Custom output directory:
    python -m ta_lab2.scripts.validation.generate_validation_report \\
        --start-date 2026-03-01 --end-date 2026-03-14 \\
        --output-dir reports/validation/v1_run1
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root: scripts/validation/ -> scripts/ -> ta_lab2/ -> src/ -> project_root
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Notebook generation
# ---------------------------------------------------------------------------


def _generate_notebook(
    start_date: date,
    end_date: date,
    output_dir: str | Path,
) -> str | None:
    """Generate a Jupyter notebook for interactive validation exploration.

    Tries to import nbformat. If not installed, prints a warning and returns None.

    Args:
        start_date:  Validation period start.
        end_date:    Validation period end.
        output_dir:  Directory to write the .ipynb file.

    Returns:
        Absolute path to the written .ipynb file, or None if nbformat is absent.
    """
    try:
        import nbformat
        import nbformat.v4 as nbv4
    except ImportError:
        print(
            "WARNING: nbformat not installed -- skipping notebook generation. "
            "Install with: pip install nbformat"
        )
        return None

    nb = nbv4.new_notebook()

    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    # ------------------------------------------------------------------
    # Cell 1 (code): Setup -- imports, engine, date params
    # ------------------------------------------------------------------
    cell1_source = f"""\
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from ta_lab2.db.config import resolve_db_url
from IPython.display import display
import pandas as pd
import plotly.graph_objects as go

engine = create_engine(resolve_db_url(), poolclass=NullPool)
START = '{start_str}'
END = '{end_str}'
print(f"Connected. Validation period: {{START}} to {{END}}")
"""
    nb.cells.append(nbv4.new_code_cell(cell1_source))

    # ------------------------------------------------------------------
    # Cell 2 (markdown): Gate Assessment header
    # ------------------------------------------------------------------
    nb.cells.append(nbv4.new_markdown_cell("## V1 Gate Assessment"))

    # ------------------------------------------------------------------
    # Cell 3 (code): Gate scorecard
    # ------------------------------------------------------------------
    cell3_source = """\
from ta_lab2.validation.gate_framework import build_gate_scorecard
from datetime import date

gates = build_gate_scorecard(engine, date.fromisoformat(START), date.fromisoformat(END))
gate_df = pd.DataFrame([{
    'Gate': g.gate_id,
    'Name': g.gate_name,
    'Threshold': g.threshold,
    'Measured': g.measured_value,
    'Status': g.status.value,
} for g in gates])
display(gate_df)
"""
    nb.cells.append(nbv4.new_code_cell(cell3_source))

    # ------------------------------------------------------------------
    # Cell 4 (markdown): Equity Curve header
    # ------------------------------------------------------------------
    nb.cells.append(nbv4.new_markdown_cell("## Equity Curve"))

    # ------------------------------------------------------------------
    # Cell 5 (code): Equity curve query + chart
    # ------------------------------------------------------------------
    cell5_source = """\
# Fills-based cumulative P&L
fills_sql = text(\"\"\"
    SELECT
        f.filled_at::date AS trade_date,
        SUM(
            CASE
                WHEN f.side = 'sell' THEN  f.fill_price * f.fill_qty
                ELSE                       -f.fill_price * f.fill_qty
            END
        ) AS daily_pnl
    FROM cmc_fills f
    JOIN cmc_orders o ON f.order_id = o.order_id
    WHERE f.filled_at::date BETWEEN :s AND :e
    GROUP BY f.filled_at::date
    ORDER BY f.filled_at::date
\"\"\")
# Drift replay P&L
drift_sql = text(\"\"\"
    SELECT metric_date, config_id, paper_cumulative_pnl
    FROM cmc_drift_metrics
    WHERE metric_date BETWEEN :s AND :e
      AND paper_cumulative_pnl IS NOT NULL
    ORDER BY config_id, metric_date
\"\"\")
params = {'s': START, 'e': END}
with engine.connect() as conn:
    fills_df = pd.read_sql(fills_sql, conn, params=params)
    drift_df = pd.read_sql(drift_sql, conn, params=params)

fig = go.Figure()
if not fills_df.empty:
    fills_df['trade_date'] = pd.to_datetime(fills_df['trade_date'])
    fills_df['cumulative_pnl'] = fills_df['daily_pnl'].cumsum()
    fig.add_trace(go.Scatter(
        x=fills_df['trade_date'], y=fills_df['cumulative_pnl'],
        mode='lines+markers', name='Paper Fills P&L',
        line=dict(color='#2563eb', width=2),
    ))
if not drift_df.empty:
    drift_df['metric_date'] = pd.to_datetime(drift_df['metric_date'])
    colors = ['#16a34a', '#dc2626', '#9333ea', '#ca8a04']
    for i, cid in enumerate(drift_df['config_id'].unique()):
        sub = drift_df[drift_df['config_id'] == cid].sort_values('metric_date')
        fig.add_trace(go.Scatter(
            x=sub['metric_date'], y=sub['paper_cumulative_pnl'],
            mode='lines', name=f'Drift Replay config_id={cid}',
            line=dict(color=colors[i % len(colors)], dash='dash'),
        ))
fig.update_layout(
    title='Equity Curve Overlay',
    xaxis_title='Date', yaxis_title='Cumulative P&L (USD)',
    template='plotly_white',
)
fig.show()
"""
    nb.cells.append(nbv4.new_code_cell(cell5_source))

    # ------------------------------------------------------------------
    # Cell 6 (markdown): Slippage Distribution header
    # ------------------------------------------------------------------
    nb.cells.append(nbv4.new_markdown_cell("## Slippage Distribution"))

    # ------------------------------------------------------------------
    # Cell 7 (code): Slippage query + histogram
    # ------------------------------------------------------------------
    cell7_source = """\
slip_sql = text(\"\"\"
    SELECT
        ABS(f.fill_price::float - pb.open::float)
            / NULLIF(pb.open::float, 0) * 10000 AS slippage_bps
    FROM cmc_fills f
    JOIN cmc_orders o ON f.order_id = o.order_id
    JOIN cmc_price_bars_multi_tf pb
        ON  pb.id   = o.asset_id
        AND pb.tf   = '1D'
        AND pb.ts::date = f.filled_at::date
    WHERE f.filled_at::date BETWEEN :s AND :e
      AND pb.open IS NOT NULL AND pb.open::float > 0
\"\"\")
with engine.connect() as conn:
    slip_df = pd.read_sql(slip_sql, conn, params={'s': START, 'e': END})

fig2 = go.Figure()
if not slip_df.empty and slip_df['slippage_bps'].notna().any():
    fig2.add_trace(go.Histogram(
        x=slip_df['slippage_bps'].dropna().tolist(),
        name='Slippage (bps)',
        marker_color='#2563eb',
        nbinsx=30,
    ))
    fig2.add_vline(x=50, line=dict(color='#dc2626', dash='dot'),
                   annotation_text='50 bps threshold')
fig2.update_layout(
    title='Slippage Distribution (VAL-03)',
    xaxis_title='Slippage (bps)', yaxis_title='Count',
    template='plotly_white',
)
fig2.show()
"""
    nb.cells.append(nbv4.new_code_cell(cell7_source))

    # ------------------------------------------------------------------
    # Cell 8 (markdown): Tracking Error header
    # ------------------------------------------------------------------
    nb.cells.append(nbv4.new_markdown_cell("## Tracking Error"))

    # ------------------------------------------------------------------
    # Cell 9 (code): Tracking error query + chart
    # ------------------------------------------------------------------
    cell9_source = """\
te_sql = text(\"\"\"
    SELECT metric_date, tracking_error_5d, tracking_error_30d
    FROM cmc_drift_metrics
    WHERE metric_date BETWEEN :s AND :e
    ORDER BY metric_date
\"\"\")
with engine.connect() as conn:
    te_df = pd.read_sql(te_sql, conn, params={'s': START, 'e': END})

fig3 = go.Figure()
if not te_df.empty:
    te_df['metric_date'] = pd.to_datetime(te_df['metric_date'])
    if te_df['tracking_error_5d'].notna().any():
        fig3.add_trace(go.Scatter(
            x=te_df['metric_date'], y=te_df['tracking_error_5d'] * 100,
            mode='lines+markers', name='Tracking Error 5d (%)',
            line=dict(color='#2563eb', width=2),
        ))
    if te_df['tracking_error_30d'].notna().any():
        fig3.add_trace(go.Scatter(
            x=te_df['metric_date'], y=te_df['tracking_error_30d'] * 100,
            mode='lines+markers', name='Tracking Error 30d (%)',
            line=dict(color='#9333ea', dash='dash'),
        ))
    fig3.add_hline(y=1.0, line=dict(color='#dc2626', dash='dot'),
                   annotation_text='1% threshold (VAL-02)')
fig3.update_layout(
    title='Tracking Error vs Backtest (VAL-02)',
    xaxis_title='Date', yaxis_title='Tracking Error (%)',
    template='plotly_white',
)
fig3.show()
"""
    nb.cells.append(nbv4.new_code_cell(cell9_source))

    # ------------------------------------------------------------------
    # Cell 10 (markdown): Audit Summary header
    # ------------------------------------------------------------------
    nb.cells.append(nbv4.new_markdown_cell("## Audit Summary"))

    # ------------------------------------------------------------------
    # Cell 11 (code): AuditChecker run + display
    # ------------------------------------------------------------------
    cell11_source = """\
from ta_lab2.validation.audit_checker import AuditChecker

checker = AuditChecker(engine)
findings, summary = checker.run_audit(
    date.fromisoformat(START),
    date.fromisoformat(END),
)

print(f"Anomalies detected: {summary.n_anomalies}")
print(f"Signed off: {summary.n_signed_off}")
print(f"Overall: {'PASS' if summary.all_signed_off else 'FAIL'}")
print()

audit_df = pd.DataFrame([{
    'Check': f.check_name,
    'Status': f.status,
    'Anomaly Count': f.count,
} for f in findings])
display(audit_df)
"""
    nb.cells.append(nbv4.new_code_cell(cell11_source))

    # Write notebook
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = _PROJECT_ROOT / output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    nb_path = output_path / "V1_VALIDATION_REPORT.ipynb"
    with open(nb_path, "w", encoding="utf-8") as fh:
        nbformat.write(nb, fh)

    logger.info("Notebook written to: %s", nb_path)
    return str(nb_path.resolve())


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: generate_validation_report."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate the end-of-period V1 validation report "
            "(Markdown + Plotly charts + Jupyter notebook)."
        )
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Validation period start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="Validation period end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/validation",
        help="Output directory for report and charts (default: reports/validation)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override DB URL (default: from db_config.env)",
    )
    parser.add_argument(
        "--no-notebook",
        action="store_true",
        help="Skip Jupyter notebook generation",
    )
    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="Skip Plotly chart generation (text-only Markdown report)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    # Parse dates
    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    except ValueError as exc:
        logger.error("Invalid date format: %s", exc)
        return 1

    if start_date > end_date:
        logger.error("--start-date must be before --end-date")
        return 1

    # Create engine
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        from ta_lab2.db.config import resolve_db_url

        db_url = args.db_url or resolve_db_url()
        engine = create_engine(db_url, poolclass=NullPool)
    except Exception as exc:
        logger.error("Failed to create DB engine: %s", exc)
        return 1

    # Generate report (Markdown + charts)
    try:
        from ta_lab2.validation.report_builder import ValidationReportBuilder

        builder = ValidationReportBuilder(engine)
        report_path = builder.generate_report(
            start_date=start_date,
            end_date=end_date,
            output_dir=args.output_dir,
            generate_charts=not args.no_charts,
        )
        print(f"\nMarkdown report: {report_path}")
    except Exception as exc:
        logger.error("Report generation failed: %s", exc)
        return 1

    # Generate notebook
    if not args.no_notebook:
        try:
            nb_path = _generate_notebook(start_date, end_date, args.output_dir)
            if nb_path:
                print(f"Jupyter notebook: {nb_path}")
        except Exception as exc:
            logger.warning("Notebook generation failed: %s", exc)

    print(f"\nOutput directory: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
