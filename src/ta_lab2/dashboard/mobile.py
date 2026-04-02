"""
Mobile responsive CSS injection for the ta_lab2 Streamlit dashboard.

Call inject_mobile_css() once in app.py after st.set_page_config() to
apply responsive styles for mobile viewports (<= 768px wide).
"""

import streamlit as st


def inject_mobile_css() -> None:
    """Inject responsive CSS rules for mobile viewports and general table improvements.

    Applies @media (max-width: 768px) rules that make the dashboard usable on
    phones and narrow screens. Also applies general improvements (e.g. table
    cell no-wrap) that apply at all viewport widths.

    Must be called after st.set_page_config() and before any sidebar or page
    content is rendered.
    """
    st.markdown(
        """
<style>
/* ------------------------------------------------------------------ */
/* General improvements (all viewport widths)                          */
/* ------------------------------------------------------------------ */

/* Prevent table cell text from wrapping — makes column headers scannable */
.stDataFrame td,
.stDataFrame th {
    white-space: nowrap;
}

/* ------------------------------------------------------------------ */
/* Mobile responsive rules (max-width: 768px)                          */
/* ------------------------------------------------------------------ */
@media (max-width: 768px) {

    /* Stack Streamlit columns vertically on narrow screens */
    .stHorizontalBlock {
        flex-direction: column !important;
    }

    /* Smaller body text in markdown blocks */
    .stMarkdown {
        font-size: 14px;
    }

    /* Smaller metric labels so they fit on one line */
    .stMetric label {
        font-size: 12px;
    }

    /* Metric values — slightly reduced but still prominent */
    .stMetric [data-testid="stMetricValue"] {
        font-size: 1.2rem;
    }

    /* Charts fill the full width and allow horizontal scroll if needed */
    .stPlotlyChart,
    .stVegaLiteChart {
        width: 100% !important;
        overflow-x: auto;
    }

    /* DataFrames scroll horizontally rather than overflowing */
    .stDataFrame {
        overflow-x: auto;
    }

    /* Reduce page padding to reclaim screen real estate */
    .block-container {
        padding: 0.5rem 1rem !important;
    }
}
</style>
""",
        unsafe_allow_html=True,
    )
