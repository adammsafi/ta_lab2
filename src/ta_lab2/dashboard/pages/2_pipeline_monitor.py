"""
Pipeline Monitor page.

Displays 4 sections:
  1. Data Freshness -- traffic light badges + expandable table families
  2. Stats Runner Status -- PASS/WARN/FAIL counts per stats table
  3. Asset Coverage Grid -- pivot matrix (symbol x table family)
  4. Alert History -- recent FAIL/WARN from stats tables

do NOT call st.set_page_config() here -- that is in app.py.
"""

from __future__ import annotations

import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.macro import load_fred_freshness
from ta_lab2.dashboard.queries.pipeline import (
    load_alert_history,
    load_asset_coverage,
    load_stats_status,
    load_table_freshness,
)

# ---------------------------------------------------------------------------
# Table family prefix map (display name -> source_table prefix)
# ---------------------------------------------------------------------------
TABLE_FAMILIES: dict[str, str] = {
    "Price Bars": "cmc_price_bars",
    "Bar Returns": "cmc_returns_bars",
    "EMA Values": "cmc_ema",
    "EMA Returns": "cmc_returns_ema",
    "AMA Values": "cmc_ama",
    "Volatility": "vol",
    "TA Indicators": "ta",
    "Regimes": "cmc_regime",
    "Features": "features",
}


def _traffic_light(staleness_hours: float | None) -> str:
    """Return a coloured circle string based on staleness thresholds."""
    if staleness_hours is None:
        return ":red_circle:"
    if staleness_hours < 24:
        return ":large_green_circle:"
    if staleness_hours < 72:
        return ":large_orange_circle:"
    return ":red_circle:"


st.header("Pipeline Monitor")

# ===========================================================================
# Section 1: Data Freshness
# ===========================================================================
st.subheader("Data Freshness")

try:
    engine = get_engine()
    freshness_df = load_table_freshness(engine)

    if freshness_df.empty:
        st.info("No data found in asset_data_coverage.")
    else:
        for family_name, prefix in TABLE_FAMILIES.items():
            # Filter rows that start with the prefix
            mask = freshness_df["source_table"].str.startswith(prefix)
            family_rows = freshness_df[mask].copy()

            if family_rows.empty:
                continue

            # Compute worst-case staleness for the expander label indicator
            max_staleness = family_rows["staleness_hours"].max()
            indicator = _traffic_light(
                None if __import__("math").isnan(max_staleness) else max_staleness
            )

            label = f"{indicator}  {family_name} ({len(family_rows)} table(s))"
            with st.expander(label, expanded=False):
                display_cols = [
                    "source_table",
                    "n_assets",
                    "latest_data_ts",
                    "last_refresh",
                    "staleness_hours",
                ]
                available_cols = [c for c in display_cols if c in family_rows.columns]
                st.dataframe(
                    family_rows[available_cols].reset_index(drop=True),
                    use_container_width=True,
                )

except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load Data Freshness: {exc}")

st.divider()

# ===========================================================================
# Section 2: Stats Runner Status
# ===========================================================================
st.subheader("Stats Runner Status")

try:
    engine = get_engine()
    stats_data = load_stats_status(engine)

    non_empty = {k: v for k, v in stats_data.items() if v}

    if not non_empty:
        st.info("No stats data in the last 24 hours.")
    else:
        tables = list(non_empty.keys())
        # Display in rows of 3 columns
        for row_start in range(0, len(tables), 3):
            row_tables = tables[row_start : row_start + 3]
            cols = st.columns(3)
            for col, table_name in zip(cols, row_tables):
                counts = non_empty[table_name]
                total_pass = counts.get("PASS", 0)
                total_warn = counts.get("WARN", 0)
                total_fail = counts.get("FAIL", 0)

                # Clean display name (strip leading "cmc_" or suffix "_stats")
                display_name = table_name.replace("_stats", "").replace("cmc_", "")

                with col:
                    st.markdown(f"**{display_name}**")
                    sub1, sub2, sub3 = st.columns(3)
                    sub1.metric("PASS", total_pass)
                    sub2.metric("WARN", total_warn)
                    sub3.metric(
                        "FAIL",
                        total_fail,
                        delta=-total_fail if total_fail > 0 else None,
                        delta_color="inverse",
                    )

except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load Stats Runner Status: {exc}")

st.divider()

# ===========================================================================
# Section 3: Asset Coverage Grid
# ===========================================================================
st.subheader("Asset Coverage")

try:
    engine = get_engine()
    coverage_df = load_asset_coverage(engine)

    if coverage_df.empty:
        st.info("No asset coverage data available.")
    else:
        # Map source_table to family name for pivot column labels
        def _family_for_table(source_table: str) -> str:
            for family_name, prefix in TABLE_FAMILIES.items():
                if source_table.startswith(prefix):
                    return family_name
            return source_table

        coverage_df = coverage_df.copy()
        coverage_df["family"] = coverage_df["source_table"].apply(_family_for_table)

        # Pivot: rows = symbol, columns = family, values = n_rows (sum)
        pivot = (
            coverage_df.groupby(["symbol", "family"])["n_rows"]
            .sum()
            .unstack(fill_value=0)
        )
        pivot = pivot.reset_index()

        st.dataframe(pivot, use_container_width=True)

        # CSV download
        csv_bytes = pivot.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name="asset_coverage.csv",
            mime="text/csv",
        )

except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load Asset Coverage: {exc}")

st.divider()

# ===========================================================================
# Section 4: Alert History
# ===========================================================================
st.subheader("Recent Alerts")

try:
    engine = get_engine()
    alerts_df = load_alert_history(engine)

    if alerts_df.empty:
        st.success("No FAIL or WARN alerts in the last 7 days.")
    else:
        display_cols = [
            c
            for c in ["stats_table", "status", "checked_at", "check_name"]
            if c in alerts_df.columns
        ]
        st.dataframe(
            alerts_df[display_cols].reset_index(drop=True),
            use_container_width=True,
        )

except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load Alert History: {exc}")

st.divider()

# ===========================================================================
# Section 5: FRED Data Freshness (OBSV-03)
# ===========================================================================
st.subheader("FRED Data Freshness")

try:
    engine = get_engine()
    fred_freshness = load_fred_freshness(engine)

    if fred_freshness.empty:
        st.info("No FRED data found in fred.series_values.")
    else:
        # Summary row with traffic lights
        n_green = (fred_freshness["status"] == "green").sum()
        n_orange = (fred_freshness["status"] == "orange").sum()
        n_red = (fred_freshness["status"] == "red").sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Series", len(fred_freshness))
        c2.metric(":large_green_circle: Fresh", int(n_green))
        c3.metric(":large_orange_circle: Stale", int(n_orange))
        c4.metric(":red_circle: Critical", int(n_red))

        # Expandable detail table
        with st.expander("FRED Series Detail", expanded=False):
            display_df = fred_freshness[
                ["series_id", "latest_date", "staleness_days", "frequency", "status"]
            ].copy()
            display_df["indicator"] = display_df["status"].apply(
                lambda s: ":large_green_circle:"
                if s == "green"
                else ":large_orange_circle:"
                if s == "orange"
                else ":red_circle:"
            )
            st.dataframe(
                display_df[
                    [
                        "indicator",
                        "series_id",
                        "latest_date",
                        "staleness_days",
                        "frequency",
                    ]
                ].reset_index(drop=True),
                use_container_width=True,
            )

except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load FRED Data Freshness: {exc}")
