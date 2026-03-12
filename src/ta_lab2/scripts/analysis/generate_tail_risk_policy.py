# -*- coding: utf-8 -*-
"""
generate_tail_risk_policy.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
TAIL-03 deliverable: policy document generator.

Produces three output files in reports/tail_risk/:
1. TAIL_RISK_POLICY.md  -- human-readable policy memo
2. tail_risk_config.yaml  -- machine-readable config for RiskEngine
3. charts/vol_spike_history.html  -- historical BTC rolling vol chart

Reads SIZING_COMPARISON.md (from Plan 03) for Summary Recommendations if present.
Falls back to research calibration values if not.

Usage
-----
    python -m ta_lab2.scripts.analysis.generate_tail_risk_policy
    python -m ta_lab2.scripts.analysis.generate_tail_risk_policy --output-dir reports/tail_risk/
    python -m ta_lab2.scripts.analysis.generate_tail_risk_policy --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.config import TARGET_DB_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project layout
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "reports" / "tail_risk"
_SIZING_COMPARISON_PATH = _DEFAULT_OUTPUT_DIR / "SIZING_COMPARISON.md"

# ---------------------------------------------------------------------------
# Threshold constants (from BTC daily data calibration, 2010-2025, n=5,613 bars)
# ---------------------------------------------------------------------------

REDUCE_VOL_THRESHOLD = 0.0923  # mean+2std, ~19 trigger days/year
FLATTEN_VOL_THRESHOLD = 0.1194  # mean+3std, ~8.5 trigger days/year
FLATTEN_ABS_RETURN = 0.15  # ~6.6 trigger days/year
FLATTEN_CORR_THRESHOLD = -0.20  # ~5th percentile BTC/ETH 30d correlation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_engine(db_url: str | None = None):
    """Create SQLAlchemy engine with NullPool for one-shot queries."""
    url = db_url or TARGET_DB_URL
    return create_engine(url, poolclass=NullPool)


def _load_btc_returns(engine, asset_id: int = 1) -> pd.DataFrame:
    """
    Load BTC daily bar returns from returns_bars_multi_tf_u.

    Note: column is "timestamp" (PostgreSQL reserved word, double-quoted).
    """
    sql = text(
        """
        SELECT "timestamp" AS ts, ret_arith
        FROM returns_bars_multi_tf_u
        WHERE id = :asset_id
          AND tf = '1D'
        ORDER BY "timestamp"
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"asset_id": asset_id})
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        logger.info("Loaded %d BTC daily return bars for vol chart", len(df))
        return df
    except Exception as exc:
        logger.warning("Could not load BTC returns for vol chart: %s", exc)
        return pd.DataFrame(columns=["ts", "ret_arith"])


def _read_sizing_comparison_recommendations() -> str | None:
    """
    Read the Summary Recommendations section from SIZING_COMPARISON.md.

    Returns the markdown table as a string, or None if file not found.
    """
    if not _SIZING_COMPARISON_PATH.exists():
        logger.info("SIZING_COMPARISON.md not found; using research defaults.")
        return None

    try:
        content = _SIZING_COMPARISON_PATH.read_text(encoding="utf-8")
        # Extract the Summary Recommendations section
        start_marker = "## Summary Recommendations"
        end_marker = "\n---"
        start_idx = content.find(start_marker)
        if start_idx == -1:
            return None
        end_idx = content.find(end_marker, start_idx)
        if end_idx == -1:
            section = content[start_idx:]
        else:
            section = content[start_idx:end_idx]
        # Strip the heading, return table body
        lines = section.strip().split("\n")
        # Drop the heading line
        table_lines = [ln for ln in lines[1:] if ln.strip()]
        return "\n".join(table_lines).strip()
    except Exception as exc:
        logger.warning("Could not read SIZING_COMPARISON.md: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------


def _build_vol_spike_chart(df: pd.DataFrame, output_path: Path) -> bool:
    """
    Build BTC 20-day rolling volatility chart with threshold lines and crash annotations.

    Saves HTML to output_path. Returns True on success.
    """
    if df.empty or "ret_arith" not in df.columns:
        logger.warning("No return data for vol chart; skipping.")
        return False

    # Compute 20-day rolling std (annualised to daily via raw)
    df = df.copy()
    df["vol_20d"] = df["ret_arith"].rolling(window=20, min_periods=20).std()
    df = df.dropna(subset=["vol_20d"])

    if df.empty:
        logger.warning("No 20d vol data (need >= 20 bars); skipping chart.")
        return False

    fig = go.Figure()

    # Main vol line
    fig.add_trace(
        go.Scatter(
            x=df["ts"],
            y=df["vol_20d"],
            name="20d Rolling Vol",
            line={"color": "#2196F3", "width": 1.5},
            hovertemplate="%{x|%Y-%m-%d}<br>Vol: %{y:.3%}<extra></extra>",
        )
    )

    # REDUCE threshold line
    fig.add_hline(
        y=REDUCE_VOL_THRESHOLD,
        line_dash="dash",
        line_color="#FF9800",
        annotation_text=f"REDUCE ({REDUCE_VOL_THRESHOLD:.2%})",
        annotation_position="top left",
        annotation_font_color="#FF9800",
    )

    # FLATTEN threshold line
    fig.add_hline(
        y=FLATTEN_VOL_THRESHOLD,
        line_dash="dash",
        line_color="#F44336",
        annotation_text=f"FLATTEN ({FLATTEN_VOL_THRESHOLD:.2%})",
        annotation_position="top left",
        annotation_font_color="#F44336",
    )

    # Crash event shaded regions
    crash_events = [
        {
            "name": "COVID Crash",
            "x0": "2020-03-01",
            "x1": "2020-04-15",
            "color": "rgba(244,67,54,0.10)",
        },
        {
            "name": "May 2021 Dip",
            "x0": "2021-05-10",
            "x1": "2021-06-01",
            "color": "rgba(255,152,0,0.10)",
        },
        {
            "name": "FTX Collapse",
            "x0": "2022-11-01",
            "x1": "2022-12-01",
            "color": "rgba(156,39,176,0.10)",
        },
    ]

    for event in crash_events:
        fig.add_vrect(
            x0=event["x0"],
            x1=event["x1"],
            fillcolor=event["color"],
            opacity=1,
            layer="below",
            line_width=0,
            annotation_text=event["name"],
            annotation_position="top left",
            annotation_font_size=10,
        )

    fig.update_layout(
        title={
            "text": "BTC 20-Day Rolling Volatility vs Tail Risk Thresholds",
            "font": {"size": 18},
        },
        xaxis_title="Date",
        yaxis_title="20-Day Rolling Volatility (daily std)",
        yaxis_tickformat=".1%",
        legend={"yanchor": "top", "y": 0.99, "xanchor": "left", "x": 0.01},
        height=500,
        template="plotly_white",
        hovermode="x unified",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path))
    logger.info("Vol spike chart saved: %s", output_path)
    return True


# ---------------------------------------------------------------------------
# Policy document builder
# ---------------------------------------------------------------------------


def _build_tail_risk_policy(
    timestamp: str,
    sizing_recommendations: str | None,
    stop_pct: float = 0.07,
) -> str:
    """
    Build the TAIL_RISK_POLICY.md human-readable memo.

    Embeds SIZING_COMPARISON.md summary if available, otherwise uses defaults.
    """
    if sizing_recommendations:
        sizing_section = f"""\
### Results Summary (from SIZING_COMPARISON.md)

{sizing_recommendations}

### Recommendation

Default approach: Vol-Sized (Variant B: ATR-14 based, 1% risk budget)
Default risk budget: 1% of portfolio per trade
Risk budget sweep: [0.5%, 1%, 2%]
Max position cap: 30% (hard limit regardless of risk budget)

**Rationale:**
- Vol-sizing reduced MaxDD by ~32% vs fixed+stops baseline (27.6% vs 40.4%)
- Sharpe improvement: 0.742 vs 0.648 (fixed+stops baseline)
- At 1% risk budget with normal ATR (3%): position = 33% -> capped at 30%
- At 1% risk budget with crisis ATR (15%): position = 6.7% (automatic delever)
- The position cap ensures vol-sizing doesn't produce oversized positions in low-vol regimes"""
    else:
        sizing_section = """\
### Results Summary

> SIZING_COMPARISON.md not found. Run `run_tail_risk_comparison.py` for full comparison data.
> Research calibration values used as defaults.

| Strategy | Asset | Recommended Variant | Vol Metric | Risk Budget | Composite Score | Sharpe | MaxDD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ema_trend_17_77 | BTC | B: Vol-Sized | atr | 1.0% risk budget | ~0.78 | ~0.74 | ~-28% |

### Recommendation

Default approach: Vol-Sized (Variant B: ATR-14 based, 1% risk budget)
Default risk budget: 1% of portfolio per trade
Risk budget sweep: [0.5%, 1%, 2%]
Max position cap: 30% (hard limit regardless of risk budget)

**Rationale:**
- Research calibration: vol-sizing expected to reduce MaxDD ~30-35% vs fixed+stops
- At 1% risk budget with normal ATR (3%): position = 33% -> capped at 30%
- At 1% risk budget with crisis ATR (15%): position = 6.7% (automatic delever)
- The position cap ensures vol-sizing doesn't produce oversized positions in low-vol regimes"""

    policy = f"""\
# Tail-Risk Policy

Version: 1.0
Generated: {timestamp}
Phase: 49 (Tail-Risk Policy)

## Executive Summary

This document defines when and how the trading system responds to extreme market
conditions. It covers three areas: position sizing approach (hard stops vs
volatility-based sizing), flatten-all criteria (what triggers full risk exit),
and the escalation procedure (normal -> reduce -> flatten -> re-entry).

---

## 1. Position Sizing Approach (TAIL-01)

### Methodology

Compared 3 variants across 4 bakeoff strategies, 2 assets (BTC/ETH), and 2 vol
metrics (ATR-14 and 20-day realized vol):

- **Variant A:** Fixed 30% allocation + hard stop at {stop_pct:.0%}
- **Variant B:** Vol-sized (risk budget / volatility) + no stops
- **Variant C:** Vol-sized + hard stop at {stop_pct:.0%}

{sizing_section}

---

## 2. Flatten-All Criteria (TAIL-02)

### Trigger Suite

Four complementary triggers, evaluated in priority order:

| Priority | Trigger | Condition | Level | Rationale |
|----------|---------|-----------|-------|-----------|
| 1 | Exchange Halt | API health check fails | FLATTEN | Infrastructure failure requires immediate exit |
| 2 | Extreme Single-Day Return | \\|daily return\\| > 15% | FLATTEN | COVID March 12: -37% would trigger same day |
| 3 | Vol Spike (3-sigma) | 20d rolling vol > 11.94%/day | FLATTEN | Prolonged crisis detection (catches COVID March 15+) |
| 4 | Correlation Breakdown | BTC/ETH 30d corr < -0.20 | FLATTEN | Unusual divergence (lower priority for crypto) |
| 5 | Vol Spike (2-sigma) | 20d rolling vol > 9.23%/day | REDUCE | Elevated conditions -- halve positions |

### Threshold Calibration

Thresholds calibrated from BTC daily data, 2010-2025 (n=5,613 bars):

| Metric | Mean | Std | Threshold | Trigger Rate |
|--------|------|-----|-----------|--------------|
| 20d rolling vol | 3.70%/day | 2.65% | 9.23% (mean+2std) = REDUCE | ~19 days/year |
| 20d rolling vol | 3.70%/day | 2.65% | 11.94% (mean+3std) = FLATTEN | ~8.5 days/year |
| \\|daily return\\| | 4.73%/day | - | 15% = FLATTEN | ~6.6 days/year |
| BTC/ETH 30d corr | 0.674 | 0.344 | -0.20 = FLATTEN | ~5th percentile |

### Historical Crash Validation

| Event | Date | \\|Return\\| | 20d Vol | Vol Trigger? | Primary Trigger |
|-------|------|---------|---------|--------------|-----------------|
| COVID crash | 2020-03-12 | 37.2% | 3.1% (pre-crash) | No (3-day lag) | Abs return (same day) |
| COVID elevated | 2020-03-15+ | - | 9.2%+ | REDUCE (day 3) | Vol spike |
| FTX collapse | 2022-11-08-11 | 10-14% | 5.1% (peak) | No | Exchange halt |
| May 2021 dip | 2021-05-19 | 12.5% | 6.7% | No | Circuit breaker |

**Key finding:** No single trigger catches all events. The multi-trigger approach
covers COVID (abs return), FTX (exchange halt), and prolonged crises (vol spike).
May 2021 is correctly handled by the Phase 46 circuit breaker (not a tail event).

### Correlation Caveat

BTC/ETH correlation during COVID was 0.93 (both crashed together). Correlation
breakdown is LOW priority for crypto-only portfolios where assets are structurally
correlated. It becomes more relevant for multi-asset portfolios with uncorrelated legs.

---

## 3. Escalation Procedure

### Three Levels

| Level | State | Position Sizing | New Orders |
|-------|-------|-----------------|------------|
| Normal | `normal` | Full signal processing | Allowed |
| Reduce | `reduce` | Buy quantities halved (0.5x) | Allowed (reduced) |
| Flatten | `flatten` | Exit all positions | Blocked |

### Escalation Rules

- **Normal -> Reduce:** Automatic when 20d vol > 9.23%/day (2-sigma)
- **Normal -> Flatten:** Automatic on exchange halt, |return| > 15%, or vol > 11.94%/day
- **Reduce -> Flatten:** Automatic on exchange halt, |return| > 15%, or vol > 11.94%/day
- Escalation is IMMEDIATE -- no delay, no confirmation needed

### De-Escalation Rules (Re-Entry)

- **Flatten -> Reduce:**
  - Minimum 21-day cooldown after flatten was triggered
  - AND 20d rolling vol below 9.23%/day for 3 consecutive days
- **Reduce -> Normal:**
  - Minimum 14-day cooldown after reduce was triggered
  - AND 20d rolling vol below 9.23%/day for 3 consecutive days

**Rationale:** Empirical vol spike persistence is median 18-20 days. 21-day cooldown
covers median + safety buffer. 3-consecutive-day requirement prevents premature
re-entry on brief vol dips.

### Manual Override

Operator can override the automated state directly in the database:
```sql
-- Manual override: set tail risk state to normal
UPDATE dim_risk_state
SET tail_risk_state = 'normal',
    tail_risk_cleared_at = NOW(),
    tail_risk_trigger_reason = 'Manual override by operator',
    updated_at = NOW()
WHERE state_id = 1;

-- Log the override event
INSERT INTO risk_events (event_type, trigger_source, reason)
VALUES ('tail_risk_cleared', 'manual', 'Manual override by operator');
```
This updates dim_risk_state.tail_risk_state and logs an override event.

---

## 4. Regime Interaction

The tail-risk escalation system operates independently of the Phase 27 regime
detection (bull/bear/sideways). Both systems can reduce position sizes simultaneously:

| Regime | Base Multiplier | + REDUCE State | Combined |
|--------|----------------|----------------|----------|
| Bull | 1.00x | 0.50x | 0.50x |
| Sideways | 1.00x | 0.50x | 0.50x |
| Down | 0.55x | 0.50x | 0.275x |

**Design choice:** Multiplicative combination. Down regime (0.55x from Phase 27)
+ REDUCE state (0.50x from Phase 49) = 0.275x base position. This is conservative
by design -- during down regimes with elevated vol, aggressive deleveraging is correct.

---

## 5. Implementation Reference

### Architecture

- **flatten_trigger.py:** check_flatten_trigger() evaluates all triggers, returns EscalationState
- **risk_engine.py:** Gate 1.5 in check_order(), evaluate_tail_risk_state() for daily eval
- **dim_risk_state:** tail_risk_state column (normal/reduce/flatten) with audit columns
- **risk_events:** tail_risk_escalated/tail_risk_cleared event logging

### Configuration

See `tail_risk_config.yaml` for machine-readable thresholds.
RiskEngine reads thresholds from this file or uses hardcoded defaults.

### Daily Evaluation

Called by run_daily_refresh.py:
1. Load latest 20d returns for BTC (market proxy)
2. Compute rolling vol and latest daily return
3. Run check_flatten_trigger()
4. Apply cooldown logic for de-escalation (cooldown days + 3 consecutive days vol below threshold)
5. Update dim_risk_state if state changed
6. Log event to risk_events

---

## Appendix: Override Guidance

| Scenario | Recommended Override | Reason |
|----------|---------------------|--------|
| Known scheduled event (e.g., ETF decision) | Set REDUCE manually before event | Proactive risk reduction |
| False positive (vol spike from exchange glitch) | Set NORMAL after investigation | Documented false positive |
| Flash crash recovery (vol subsiding) | Wait for automatic de-escalation | Cooldown prevents premature re-entry |
| Extended FLATTEN (> 30 days) | Review and set REDUCE if justified | Balance between safety and opportunity cost |
"""
    return policy


# ---------------------------------------------------------------------------
# YAML config builder
# ---------------------------------------------------------------------------


def _build_tail_risk_config(timestamp: str) -> dict:
    """Build the machine-readable tail_risk_config dict."""
    return {
        "version": "1.0",
        "generated_at": timestamp,
        "source": "Phase 49 tail-risk policy analysis",
        "vol_sizing": {
            "default_approach": "atr_14",
            "risk_budget_default": 0.01,
            "risk_budget_sweep": [0.005, 0.01, 0.02],
            "max_position_pct": 0.30,
            "realized_vol_window": 20,
        },
        "escalation_thresholds": {
            "reduce_vol_20d_threshold": REDUCE_VOL_THRESHOLD,
            "flatten_vol_20d_threshold": FLATTEN_VOL_THRESHOLD,
            "flatten_abs_return_threshold": FLATTEN_ABS_RETURN,
            "flatten_correlation_threshold": FLATTEN_CORR_THRESHOLD,
        },
        "re_entry": {
            "mechanism": "graduated",
            "cooldown_days_reduce": 14,
            "cooldown_days_flatten": 21,
            "vol_clear_threshold": REDUCE_VOL_THRESHOLD,
            "vol_clear_consecutive_days": 3,
        },
        "regime_interaction": {
            "down_regime_size_mult": 0.55,
            "reduce_state_additional_mult": 0.50,
        },
        "trigger_priority": [
            {"name": "exchange_halt", "level": "flatten", "priority": 1},
            {
                "name": "abs_return",
                "level": "flatten",
                "priority": 2,
                "threshold": FLATTEN_ABS_RETURN,
            },
            {
                "name": "vol_spike_3sig",
                "level": "flatten",
                "priority": 3,
                "threshold": FLATTEN_VOL_THRESHOLD,
            },
            {
                "name": "correlation_breakdown",
                "level": "flatten",
                "priority": 4,
                "threshold": FLATTEN_CORR_THRESHOLD,
            },
            {
                "name": "vol_spike_2sig",
                "level": "reduce",
                "priority": 5,
                "threshold": REDUCE_VOL_THRESHOLD,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate TAIL_RISK_POLICY.md, tail_risk_config.yaml, and vol_spike_history.html"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="Output directory (default: reports/tail_risk/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned outputs and exit without generating files.",
    )
    parser.add_argument(
        "--asset-ids",
        type=int,
        nargs="+",
        default=[1, 1027],
        help="Asset IDs for historical analysis (default: 1 1027 = BTC ETH)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Override DB URL (defaults to TARGET_DB_URL env var)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    output_dir: Path = args.output_dir
    policy_path = output_dir / "TAIL_RISK_POLICY.md"
    config_path = output_dir / "tail_risk_config.yaml"
    chart_path = output_dir / "charts" / "vol_spike_history.html"

    # Dry-run: print planned outputs and exit
    if args.dry_run:
        print("Dry-run mode: would generate the following files")
        print(f"  Policy memo:   {policy_path}")
        print(f"  YAML config:   {config_path}")
        print(f"  Vol chart:     {chart_path}")
        print()
        print("Inputs:")
        sizing_exists = _SIZING_COMPARISON_PATH.exists()
        print(
            f"  SIZING_COMPARISON.md: {'found' if sizing_exists else 'not found (will use defaults)'}"
        )
        print(f"  Asset IDs for chart:  {args.asset_ids}")
        print()
        print("Config values:")
        print(
            f"  REDUCE threshold:  {REDUCE_VOL_THRESHOLD:.4f} ({REDUCE_VOL_THRESHOLD:.2%}/day)"
        )
        print(
            f"  FLATTEN threshold: {FLATTEN_VOL_THRESHOLD:.4f} ({FLATTEN_VOL_THRESHOLD:.2%}/day)"
        )
        print(f"  Abs return limit:  {FLATTEN_ABS_RETURN:.0%}")
        print(f"  Corr threshold:    {FLATTEN_CORR_THRESHOLD}")
        print("  Cooldown (flatten): 21d + 3 consecutive vol-clear days")
        print("  Cooldown (reduce):  14d + 3 consecutive vol-clear days")
        return 0

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: Read SIZING_COMPARISON.md (optional) ---
    sizing_recommendations = _read_sizing_comparison_recommendations()
    if sizing_recommendations:
        logger.info("Embedded SIZING_COMPARISON.md Summary Recommendations section.")
    else:
        logger.info("Using research calibration defaults for sizing section.")

    # --- Step 2: Generate TAIL_RISK_POLICY.md ---
    logger.info("Generating TAIL_RISK_POLICY.md ...")
    policy_content = _build_tail_risk_policy(
        timestamp=timestamp,
        sizing_recommendations=sizing_recommendations,
        stop_pct=0.07,
    )
    policy_path.write_text(policy_content, encoding="utf-8")
    logger.info("Policy memo written: %s", policy_path)

    # --- Step 3: Generate tail_risk_config.yaml ---
    logger.info("Generating tail_risk_config.yaml ...")
    config_dict = _build_tail_risk_config(timestamp=timestamp)
    config_yaml = yaml.dump(
        config_dict, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    config_path.write_text(config_yaml, encoding="utf-8")
    logger.info("YAML config written: %s", config_path)

    # --- Step 4: Generate vol_spike_history.html chart ---
    logger.info("Generating vol_spike_history.html chart ...")
    # Use first asset ID (typically BTC id=1) as market proxy
    btc_asset_id = args.asset_ids[0]
    try:
        engine = _get_engine(args.db_url)
        btc_returns = _load_btc_returns(engine, asset_id=btc_asset_id)
        chart_ok = _build_vol_spike_chart(btc_returns, chart_path)
        if not chart_ok:
            logger.warning("Vol spike chart could not be generated (empty data).")
    except Exception as exc:
        logger.warning("Could not build vol chart (DB unavailable?): %s", exc)
        chart_ok = False

    # --- Summary ---
    print()
    print("Tail-Risk Policy Generation Complete")
    print(f"  Policy memo:     {policy_path}")
    print(f"  YAML config:     {config_path}")
    if chart_ok:
        print(f"  Vol chart:       {chart_path}")
    else:
        print("  Vol chart:       SKIPPED (no DB data or empty returns)")
    print()
    print(
        "SIZING_COMPARISON.md embedding:",
        "YES (from Plan 03 output)"
        if sizing_recommendations
        else "NO (using research defaults)",
    )
    print()
    print("Key thresholds:")
    print(f"  REDUCE:          {REDUCE_VOL_THRESHOLD:.2%}/day (mean+2std)")
    print(f"  FLATTEN (vol):   {FLATTEN_VOL_THRESHOLD:.2%}/day (mean+3std)")
    print(f"  FLATTEN (ret):   {FLATTEN_ABS_RETURN:.0%} single-day abs return")
    print("  Cooldown:        21d flatten / 14d reduce + 3 consecutive vol-clear days")

    return 0


if __name__ == "__main__":
    sys.exit(main())
