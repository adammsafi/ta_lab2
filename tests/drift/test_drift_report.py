"""
Unit tests for ReportGenerator -- Markdown report + Plotly HTML charts.

DB queries are mocked.  File output uses pytest tmp_path fixture.
Plotly chart tests verify figure structure, not visual output.
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import plotly.graph_objects as go

from ta_lab2.drift.drift_report import ReportGenerator, _ATTR_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    """Return a minimal mock SQLAlchemy engine."""
    engine = MagicMock()
    conn_ctx = MagicMock()
    conn = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn_ctx
    return engine, conn


def _make_metrics_df(n_rows: int = 3) -> pd.DataFrame:
    """Build a minimal drift metrics DataFrame."""
    start = date(2026, 2, 18)
    rows = []
    for i in range(n_rows):
        rows.append(
            {
                "metric_date": date(2026, 2, 18 + i),
                "config_id": 1,
                "asset_id": 1,
                "signal_type": "ema_crossover",
                "paper_cumulative_pnl": 100.0 + i * 5,
                "replay_pit_cumulative_pnl": 95.0 + i * 5,
                "tracking_error_5d": 0.03 + i * 0.005,
                "tracking_error_30d": 0.025 + i * 0.002,
                "threshold_breach_5d": False,
                "drift_paused": False,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Test 1: generate_weekly_report -- no data path
# ---------------------------------------------------------------------------


class TestGenerateWeeklyReportNoData:
    def test_generate_weekly_report_no_data(self, tmp_path):
        """
        When the DB returns an empty DataFrame, a minimal report should be generated
        and the path returned should point to an existing .md file.
        """
        engine, conn = _make_engine()

        reporter = ReportGenerator(engine)

        # Patch _load_drift_metrics_df to return empty DataFrame.
        with patch.object(
            reporter, "_load_drift_metrics_df", return_value=pd.DataFrame()
        ):
            report_path = reporter.generate_weekly_report(
                week_start=date(2026, 2, 18),
                week_end=date(2026, 2, 25),
                output_dir=str(tmp_path),
            )

        assert os.path.isfile(report_path), f"Expected report file at {report_path}"
        content = open(report_path, encoding="utf-8").read()
        assert "No drift data available" in content
        assert "2026-02-18" in content
        assert "2026-02-25" in content


# ---------------------------------------------------------------------------
# Test 2: generate_weekly_report -- creates files
# ---------------------------------------------------------------------------


class TestGenerateWeeklyReportCreatesFiles:
    def test_generate_weekly_report_creates_files(self, tmp_path):
        """
        When the DB returns 3 rows, the generator should create:
          - A .md report file
          - equity_overlay.html
          - tracking_error.html
        (attribution waterfall is skipped because attr_* columns are absent.)
        """
        engine, conn = _make_engine()
        df = _make_metrics_df(n_rows=3)

        reporter = ReportGenerator(engine)

        # Patch data loading methods.
        with (
            patch.object(reporter, "_load_drift_metrics_df", return_value=df),
            patch.object(reporter, "_load_te_threshold", return_value=0.05),
        ):
            report_path = reporter.generate_weekly_report(
                week_start=date(2026, 2, 18),
                week_end=date(2026, 2, 25),
                output_dir=str(tmp_path),
            )

        # Report file exists and has expected name.
        assert os.path.isfile(report_path)
        assert report_path.endswith("drift_report_2026-02-25.md")

        # Charts subdirectory exists.
        charts_dir = os.path.join(str(tmp_path), "charts_2026-02-25")
        assert os.path.isdir(charts_dir)

        # Equity overlay chart exists.
        equity_path = os.path.join(charts_dir, "equity_overlay.html")
        assert os.path.isfile(equity_path), "equity_overlay.html not found"

        # Tracking error chart exists.
        te_path = os.path.join(charts_dir, "tracking_error.html")
        assert os.path.isfile(te_path), "tracking_error.html not found"


# ---------------------------------------------------------------------------
# Test 3: _plot_equity_overlay returns Figure
# ---------------------------------------------------------------------------


class TestPlotEquityOverlay:
    def test_plot_equity_overlay_returns_figure(self):
        """
        _plot_equity_overlay should return a go.Figure with at least 2 traces
        (one paper + one replay) when data contains a single config.
        """
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)
        df = _make_metrics_df(n_rows=3)

        fig = reporter._plot_equity_overlay(df)

        assert isinstance(fig, go.Figure)
        # Should have paper + replay traces for config_id=1
        assert len(fig.data) >= 2, f"Expected >= 2 traces, got {len(fig.data)}"

    def test_plot_equity_overlay_empty_df(self):
        """_plot_equity_overlay with empty DataFrame should return a Figure (no error)."""
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)

        fig = reporter._plot_equity_overlay(pd.DataFrame())
        assert isinstance(fig, go.Figure)


# ---------------------------------------------------------------------------
# Test 4: _plot_tracking_error has horizontal threshold line
# ---------------------------------------------------------------------------


class TestPlotTrackingError:
    def test_plot_tracking_error_includes_threshold_line(self):
        """
        _plot_tracking_error should include a horizontal line (shape) at the
        threshold value via fig.add_hline().  Plotly represents hline as a
        layout.shape or as a hline annotation depending on version.
        """
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)
        df = _make_metrics_df(n_rows=5)
        threshold = 0.05

        fig = reporter._plot_tracking_error(df, threshold)

        assert isinstance(fig, go.Figure)

        # add_hline stores shapes in layout.shapes or adds an annotation.
        # Check at least one of: shapes or annotations contains threshold reference.
        has_threshold = False

        # Check layout shapes (add_hline adds a shape of type "line" at y=threshold).
        for shape in fig.layout.shapes:
            y_val = getattr(shape, "y0", None) or getattr(shape, "y", None)
            if y_val == threshold:
                has_threshold = True
                break

        # Plotly may also encode hline via annotations.
        if not has_threshold:
            for annotation in fig.layout.annotations:
                text = getattr(annotation, "text", "")
                if str(threshold) in str(text) or "Threshold" in str(text):
                    has_threshold = True
                    break

        assert has_threshold, (
            f"Expected a threshold line at y={threshold} in figure shapes or annotations. "
            f"Shapes: {[s.to_plotly_json() for s in fig.layout.shapes]}"
        )

    def test_plot_tracking_error_returns_figure(self):
        """_plot_tracking_error must return a go.Figure instance."""
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)
        df = _make_metrics_df(n_rows=3)

        fig = reporter._plot_tracking_error(df, threshold=0.05)
        assert isinstance(fig, go.Figure)


# ---------------------------------------------------------------------------
# Test 5: _render_markdown contains required sections
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def test_render_markdown_contains_sections(self):
        """
        _render_markdown should produce a string containing:
        - Header with the date range
        - Summary section
        - Attribution section (with --with-attribution note since attr_* absent)
        - Charts section
        """
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)

        # Patch _load_te_threshold to avoid DB call.
        with patch.object(reporter, "_load_te_threshold", return_value=0.05):
            df = _make_metrics_df(n_rows=3)
            week_start = date(2026, 2, 18)
            week_end = date(2026, 2, 25)
            chart_paths = {
                "equity_overlay": "reports/drift/charts_2026-02-25/equity_overlay.html",
                "tracking_error": "reports/drift/charts_2026-02-25/tracking_error.html",
                "attribution_waterfall": None,
            }

            md = reporter._render_markdown(df, week_start, week_end, chart_paths)

        # Header
        assert "# Drift Guard Weekly Report" in md
        assert "2026-02-18" in md
        assert "2026-02-25" in md

        # Summary section
        assert "## Summary" in md

        # Attribution section -- should mention --with-attribution since no attr_* in df
        assert "## Attribution" in md
        assert "--with-attribution" in md

        # Charts section
        assert "## Charts" in md
        # equity_overlay chart should appear as a link
        assert "equity_overlay.html" in md or "Equity Curve Overlay" in md

    def test_render_markdown_attribution_section_when_data_present(self):
        """
        When attr_* columns are populated (non-NULL), the markdown should
        show attribution values rather than the --with-attribution note.
        """
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)

        df = _make_metrics_df(n_rows=2)
        # Add attribution columns with real values.
        df["attr_baseline_pnl"] = 100.0
        df["attr_fee_delta"] = -5.0
        df["attr_slippage_delta"] = -3.0
        df["attr_timing_delta"] = 0.0
        df["attr_data_revision_delta"] = 0.0
        df["attr_sizing_delta"] = 0.0
        df["attr_regime_delta"] = 1.0
        df["attr_unexplained_residual"] = -2.0

        with patch.object(reporter, "_load_te_threshold", return_value=0.05):
            md = reporter._render_markdown(
                df,
                date(2026, 2, 18),
                date(2026, 2, 25),
                {
                    "equity_overlay": None,
                    "tracking_error": None,
                    "attribution_waterfall": None,
                },
            )

        # Attribution section should contain actual delta table, not the placeholder note.
        assert "--with-attribution" not in md
        assert "Fee Delta" in md or "Fee" in md


# ---------------------------------------------------------------------------
# Test: attribution waterfall skipped when no attr_* data
# ---------------------------------------------------------------------------


class TestPlotAttributionWaterfall:
    def test_returns_none_when_no_attr_columns(self):
        """_plot_attribution_waterfall returns None when attr_* columns absent."""
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)
        df = _make_metrics_df(n_rows=3)  # no attr_* columns

        result = reporter._plot_attribution_waterfall(df)
        assert result is None

    def test_returns_none_when_all_attr_null(self):
        """_plot_attribution_waterfall returns None when all attr_* values are NULL."""
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)
        df = _make_metrics_df(n_rows=3)
        for col in _ATTR_COLUMNS:
            df[col] = None

        result = reporter._plot_attribution_waterfall(df)
        assert result is None

    def test_returns_figure_when_attr_data_present(self):
        """_plot_attribution_waterfall returns go.Figure when attr_* has values."""
        engine, _ = _make_engine()
        reporter = ReportGenerator(engine)
        df = _make_metrics_df(n_rows=3)
        df["attr_baseline_pnl"] = 100.0
        df["attr_fee_delta"] = -5.0
        df["attr_slippage_delta"] = -3.0
        df["attr_timing_delta"] = 0.0
        df["attr_data_revision_delta"] = 0.0
        df["attr_sizing_delta"] = 0.0
        df["attr_regime_delta"] = 1.5
        df["attr_unexplained_residual"] = -0.5

        result = reporter._plot_attribution_waterfall(df)
        assert isinstance(result, go.Figure)
