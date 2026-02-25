# Phase 51: Perps Readiness - Research

**Researched:** 2026-02-25
**Domain:** Perpetual futures infrastructure -- funding rate ingestion (6 venues), margin model (isolated/cross), liquidation buffer, backtester extension, venue downtime playbook
**Confidence:** HIGH (codebase patterns verified), MEDIUM (API endpoints verified via official docs), LOW (Lighter API, Aster history depth)

---

## Summary

Phase 51 builds the technical foundation for perpetual futures paper trading across five workstreams: (1) funding rate ingestion from 6 venues with multi-granularity storage, (2) backtester extension for funding-aware P&L including carry trade, (3) margin model tracking isolated and cross margin with tiered venue rates, (4) liquidation buffer with graduated alerts and kill switch integration, and (5) venue downtime playbook.

The standard approach across all workstreams follows existing project patterns: standalone refresh scripts using the `ExchangeInterface` pattern from `src/ta_lab2/connectivity/`, Alembic migrations for new tables, and RiskEngine extension (new Gate 1.6 for margin monitoring). Funding rate storage uses a single `cmc_funding_rates` table with `(venue, symbol, ts, tf)` PK to unify granularities -- the project's multi-TF pattern applies directly. The vectorbt backtester cannot natively model funding payments; the correct approach is post-simulation P&L adjustment via a `FundingAdjuster` that replays funding payments against the position timeline.

Venue API endpoints are confirmed for Binance, Hyperliquid, Bybit, dYdX v4, and Aevo. Lighter's API requires direct SDK usage (lighter-python); a REST endpoint for funding history may not exist as a documented stable endpoint. Aster mirrors the Binance Futures API exactly (`GET /fapi/v1/fundingRate` on `https://fapi.asterdex.com`).

**Primary recommendation:** Five sequential plans -- (1) DB schema + funding rate ingestion, (2) backtester extension for funding/carry trade, (3) margin model + position tracking, (4) liquidation buffer + RiskEngine Gate 1.6, (5) venue downtime playbook.

---

## Standard Stack

All core libraries already installed. One potential new dependency: `lighter-python` SDK if direct HTTP is insufficient for Lighter. No other new dependencies.

### Core (confirmed installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | existing | HTTP calls to exchange REST APIs | All connectivity adapters use it via `ExchangeInterface.session` |
| `sqlalchemy` | existing | DB read/write for funding rate table | Project standard |
| `pandas` | 2.3.3 | Data processing, multi-index alignment | Project standard |
| `numpy` | 2.4.1 | Funding payment calculations | Project standard |
| `vectorbt` | 0.28.1 | Backtest simulation (existing) | Project standard; Phase 42/45 established |
| `alembic` | existing | Schema migrations | Project standard; current head = `b5178d671e38` |
| `pyyaml` | existing | Playbook machine-readable YAML | Used in Phase 49 pattern |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `lighter-python` | latest | Lighter DEX API SDK | Only if REST endpoint for funding history is not available |
| `decimal` | stdlib | Margin calculations (precision) | All monetary values in margin model |
| `dataclasses` | stdlib | Typed results for MarginState, LiquidationAlert | New risk classes |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single `cmc_funding_rates` table | Separate table per granularity | Single table with `tf` column matches existing multi-TF pattern exactly; joins stay simple |
| RiskEngine extension for margin gate | Separate `MarginMonitor` class | Extension keeps all risk gates in one place; CONTEXT.md leaves this as Claude's discretion -- recommend extension |
| Post-simulation P&L adjustment for funding | vectorbt `from_order_func` callbacks | `from_order_func` is complex; post-hoc adjustment on trade timeline is simpler and produces identical results |

**Installation:**
```bash
# If Lighter REST endpoints are insufficient:
pip install lighter-python
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── connectivity/
│   ├── base.py                  # ExchangeInterface (existing)
│   ├── factory.py               # get_exchange() (existing -- needs no update)
│   └── [no new adapters needed for funding; standalone scripts use requests directly]
├── risk/
│   ├── risk_engine.py           # Extend: new Gate 1.6 for margin/liquidation check
│   └── margin_monitor.py        # NEW: MarginState, compute_margin_utilization()
├── backtests/
│   ├── vbt_runner.py            # Existing (no change needed)
│   └── funding_adjuster.py      # NEW: FundingAdjuster for post-sim P&L adjustment

scripts/
├── perps/                       # NEW directory
│   ├── __init__.py
│   └── refresh_funding_rates.py # NEW: standalone ingest from 6 venues

sql/perps/                       # NEW directory
├── 095_cmc_funding_rates.sql            # Funding rate history table
├── 096_cmc_margin_config.sql            # Venue-specific margin tiers (dim table)
└── 097_cmc_perp_positions.sql           # Perp position extension (margin tracking)

reports/perps/                   # NEW directory
├── VENUE_DOWNTIME_PLAYBOOK.md   # Human-readable procedure
└── venue_health_config.yaml     # Machine-readable health check config

alembic/versions/
└── XXXX_perps_readiness.py      # Phase 51 Alembic migration
```

### Pattern 1: Funding Rate Ingest (Per-Venue Fetcher)

**What:** Each venue has a dedicated fetcher function that normalizes output to a standard dict. A shared writer handles DB upsert.

**When to use:** All 6 venue ingestions follow this pattern.

```python
# Source: verified against Binance, Hyperliquid, Bybit, dYdX, Aevo official docs
# src/ta_lab2/scripts/perps/refresh_funding_rates.py

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import requests

@dataclass
class FundingRateRow:
    """Normalized funding rate record for cmc_funding_rates."""
    venue: str          # 'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'lighter'
    symbol: str         # 'BTC', 'ETH'
    ts: datetime        # UTC timestamp of settlement
    tf: str             # '1h', '4h', '8h', '1d' (granularity)
    funding_rate: float # Annualized or raw rate (store raw; normalize in queries)
    mark_price: Optional[float] = None
    raw_tf: str = ''    # original settlement period of venue ('1h', '8h', etc.)


def fetch_binance_funding(symbol: str = 'BTCUSDT',
                          start_ms: Optional[int] = None,
                          end_ms: Optional[int] = None,
                          limit: int = 1000) -> List[FundingRateRow]:
    """
    GET https://fapi.binance.com/fapi/v1/fundingRate
    Settlement: 8h (00:00, 08:00, 16:00 UTC)
    History: ~Sep 2019 for BTCUSDT (~4-5 years)
    Limit: 500 req/5min/IP; max 1000 rows per call
    Auth: No auth required for market data
    """
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": limit}
    if start_ms: params["startTime"] = start_ms
    if end_ms: params["endTime"] = end_ms
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    rows = []
    base = symbol.replace("USDT", "")
    for item in resp.json():
        rows.append(FundingRateRow(
            venue="binance",
            symbol=base,
            ts=datetime.fromtimestamp(item["fundingTime"] / 1000, tz=timezone.utc),
            tf="8h",
            funding_rate=float(item["fundingRate"]),
            mark_price=float(item["markPrice"]) if item.get("markPrice") else None,
            raw_tf="8h",
        ))
    return rows


def fetch_hyperliquid_funding(coin: str = 'BTC',
                               start_ms: int = 0,
                               end_ms: Optional[int] = None) -> List[FundingRateRow]:
    """
    POST https://api.hyperliquid.xyz/info  {"type": "fundingHistory", "coin": "BTC", "startTime": ...}
    Settlement: 1h (hourly, funded at rate/8 per hour)
    History: unknown exact start; Hyperliquid mainnet launched ~2023
    Auth: No auth required
    No explicit rate limit documented; recommend 10 req/s max
    """
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}
    if end_ms: payload["endTime"] = end_ms
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    rows = []
    for item in resp.json():
        rows.append(FundingRateRow(
            venue="hyperliquid",
            symbol=coin,
            ts=datetime.fromtimestamp(item["time"] / 1000, tz=timezone.utc),
            tf="1h",
            funding_rate=float(item["fundingRate"]),
            raw_tf="1h",
        ))
    return rows


def fetch_bybit_funding(symbol: str = 'BTCUSDT',
                         start_ms: Optional[int] = None,
                         end_ms: Optional[int] = None) -> List[FundingRateRow]:
    """
    GET https://api.bybit.com/v5/market/funding/history
    Settlement: 8h for BTC/ETH (Bybit dynamic system does NOT apply to BTC/ETH as of Oct 2025)
    NOTE: Bybit REQUIRES endTime if startTime is provided (cannot pass startTime alone)
    Limit: 200 rows per request; no auth required for market data
    """
    url = "https://api.bybit.com/v5/market/funding/history"
    params = {"category": "linear", "symbol": symbol, "limit": 200}
    if end_ms: params["endTime"] = end_ms
    # CRITICAL: Must not pass startTime alone -- Bybit returns error
    # Pass both or neither
    if start_ms and end_ms:
        params["startTime"] = start_ms
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    rows = []
    base = symbol.replace("USDT", "").replace("USDC", "")
    for item in data.get("result", {}).get("list", []):
        rows.append(FundingRateRow(
            venue="bybit",
            symbol=base,
            ts=datetime.fromtimestamp(int(item["fundingRateTimestamp"]) / 1000, tz=timezone.utc),
            tf="8h",
            funding_rate=float(item["fundingRate"]),
            raw_tf="8h",
        ))
    return rows


def fetch_dydx_funding(market: str = 'BTC-USD',
                        before_or_at: Optional[str] = None,
                        limit: int = 100) -> List[FundingRateRow]:
    """
    GET https://indexer.dydx.trade/v4/historicalFunding/{market}
    Settlement: 1h (hourly tick epoch)
    History: dYdX v4 mainnet launched Oct 2023; v3 data not available via v4 API
    Params: effectiveBeforeOrAt (datetime), limit (int)
    Auth: No auth required
    Base URL: https://indexer.dydx.trade (mainnet indexer)
    """
    url = f"https://indexer.dydx.trade/v4/historicalFunding/{market}"
    params = {"limit": limit}
    if before_or_at: params["effectiveBeforeOrAt"] = before_or_at
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    base = market.split("-")[0]
    rows = []
    for item in resp.json().get("historicalFunding", []):
        rows.append(FundingRateRow(
            venue="dydx",
            symbol=base,
            ts=datetime.fromisoformat(item["effectiveAt"].replace("Z", "+00:00")),
            tf="1h",
            funding_rate=float(item["rate"]),
            raw_tf="1h",
        ))
    return rows


def fetch_aevo_funding(instrument: str = 'BTC-PERP',
                        start_ns: int = 0,
                        end_ns: Optional[int] = None,
                        limit: int = 50) -> List[FundingRateRow]:
    """
    GET https://api.aevo.xyz/funding-history
    Settlement: 1h (Aevo pays hourly; rate = 8h rate / 8)
    Timestamps: UNIX nanoseconds (NOT milliseconds)
    Limit: max 50 per request (use offset for pagination)
    Auth: No auth required for public market data
    History: Available from ~Sep 2023 (Aevo launch)
    """
    url = "https://api.aevo.xyz/funding-history"
    params = {
        "instrument_name": instrument,
        "start_time": start_ns,
        "limit": limit,
    }
    if end_ns: params["end_time"] = end_ns
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    base = instrument.split("-")[0]
    rows = []
    for item in resp.json().get("funding_history", []):
        # CRITICAL: Aevo timestamps are nanoseconds, not milliseconds
        ts_ns = int(item[1])
        ts = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
        rows.append(FundingRateRow(
            venue="aevo",
            symbol=base,
            ts=ts,
            tf="1h",
            funding_rate=float(item[2]),
            mark_price=float(item[3]),
            raw_tf="1h",
        ))
    return rows


def fetch_aster_funding(symbol: str = 'BTCUSDT',
                         start_ms: Optional[int] = None,
                         end_ms: Optional[int] = None,
                         limit: int = 1000) -> List[FundingRateRow]:
    """
    GET https://fapi.asterdex.com/fapi/v1/fundingRate
    Aster mirrors Binance Futures API exactly.
    Settlement: Varies by symbol; ASTERUSDT = 4h; most pairs = 8h
    Auth: No auth required for market data
    Limit: max 1000 per request
    """
    url = "https://fapi.asterdex.com/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": limit}
    if start_ms: params["startTime"] = start_ms
    if end_ms: params["endTime"] = end_ms
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    base = symbol.replace("USDT", "")
    rows = []
    for item in resp.json():
        rows.append(FundingRateRow(
            venue="aster",
            symbol=base,
            ts=datetime.fromtimestamp(item["fundingTime"] / 1000, tz=timezone.utc),
            tf="8h",
            funding_rate=float(item["fundingRate"]),
            raw_tf="8h",
        ))
    return rows
```

### Pattern 2: DB Schema -- cmc_funding_rates

**What:** Single table with `(venue, symbol, ts, tf)` PK. `tf` stores the native settlement granularity ('1h', '4h', '8h'). Daily rollup stored as `tf='1d'`. Follows multi-TF pattern from existing tables.

```sql
-- sql/perps/095_cmc_funding_rates.sql
-- ASCII only: no box-drawing characters (Windows cp1252 compatibility)

CREATE TABLE public.cmc_funding_rates (
    venue           TEXT        NOT NULL,  -- 'binance','hyperliquid','bybit','dydx','aevo','lighter'
    symbol          TEXT        NOT NULL,  -- 'BTC', 'ETH'
    ts              TIMESTAMPTZ NOT NULL,  -- settlement timestamp UTC
    tf              TEXT        NOT NULL,  -- '1h', '4h', '8h', '1d'
    funding_rate    NUMERIC     NOT NULL,  -- raw rate (e.g., 0.0001 = 0.01%)
    mark_price      NUMERIC,
    raw_tf          TEXT,                  -- original venue settlement period
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_cmc_funding_rates
        PRIMARY KEY (venue, symbol, ts, tf),

    CONSTRAINT chk_funding_venue
        CHECK (venue IN ('binance','hyperliquid','bybit','dydx','aevo','lighter')),

    CONSTRAINT chk_funding_tf
        CHECK (tf IN ('1h','4h','8h','1d'))
);

CREATE INDEX idx_funding_rates_symbol_ts
    ON public.cmc_funding_rates (symbol, ts DESC);

CREATE INDEX idx_funding_rates_venue_symbol
    ON public.cmc_funding_rates (venue, symbol, ts DESC);

COMMENT ON TABLE public.cmc_funding_rates IS
    'Multi-venue perpetual funding rate history. PK (venue, symbol, ts, tf). '
    'tf stores native settlement granularity; 1d is daily rollup.';
```

### Pattern 3: Upsert Pattern for Funding Rates

**What:** Standard project upsert via temp table + ON CONFLICT DO NOTHING (same as sync_utils.py).

```python
# Source: follows src/ta_lab2/scripts/sync_utils.py pattern

def upsert_funding_rates(engine, rows: List[FundingRateRow]) -> int:
    """Upsert funding rate rows. Returns count inserted."""
    if not rows:
        return 0
    import pandas as pd
    df = pd.DataFrame([
        {
            "venue": r.venue,
            "symbol": r.symbol,
            "ts": r.ts,
            "tf": r.tf,
            "funding_rate": r.funding_rate,
            "mark_price": r.mark_price,
            "raw_tf": r.raw_tf,
            "ingested_at": datetime.now(timezone.utc),
        }
        for r in rows
    ])
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO public.cmc_funding_rates
                (venue, symbol, ts, tf, funding_rate, mark_price, raw_tf, ingested_at)
            SELECT
                venue, symbol, ts, tf, funding_rate, mark_price, raw_tf, ingested_at
            FROM (VALUES {placeholders}) AS v(...)
            ON CONFLICT (venue, symbol, ts, tf) DO NOTHING
        """))
    return len(df)
```

**Simpler approach:** Use pandas to_sql with a staging table, then INSERT...SELECT...ON CONFLICT DO NOTHING. See `sync_utils.py` for the exact pattern.

### Pattern 4: Backtester Funding Extension

**What:** Post-simulation P&L adjustment. The vectorbt portfolio simulation runs normally, then a `FundingAdjuster` replays funding payments against the position timeline to compute adjusted equity.

**Why not vectorbt callbacks:** vectorbt 0.28.1 `from_order_func` with callbacks is complex and hard to maintain. Post-hoc replay produces identical financial results and is far simpler. The existing `vbt_runner.py` already has `CostModel.funding_bps_day` but it only supports a flat daily rate -- not venue-specific per-settlement rates.

```python
# Source: design based on vectorbt 0.28.1 trade records API
# src/ta_lab2/backtests/funding_adjuster.py

from dataclasses import dataclass
import pandas as pd
import numpy as np
from typing import Optional
import vectorbt as vbt


@dataclass
class FundingAdjustedResult:
    """Result of funding-adjusted backtest."""
    equity_adjusted: pd.Series       # equity curve with funding P&L applied
    total_funding_paid: float         # cumulative funding paid (negative = received)
    total_return_adjusted: float
    sharpe_adjusted: float


def compute_funding_payments(
    entries: pd.Series,               # boolean entry signals (aligned with price)
    exits: pd.Series,                 # boolean exit signals
    funding_rates: pd.DataFrame,      # columns: ts(index), funding_rate; freq can differ
    position_value_series: pd.Series, # mark_price * quantity at each bar
    is_short: bool = False,
) -> pd.Series:
    """
    Compute per-bar funding payments for a position.

    Convention:
    - Positive funding_rate: longs PAY, shorts RECEIVE
    - Negative funding_rate: longs RECEIVE, shorts PAY

    funding_payment_bar = position_value * funding_rate * (settlement_periods_in_bar)

    For 1D bars with 8h settlement: 3 settlements per bar.
    For 1D bars with 1h settlement: 24 settlements per bar.

    Args:
        funding_rates: Must be resampled to daily and summed before calling.
        position_value_series: abs(position_notional) at each bar.
        is_short: If True, flip the sign (shorts receive positive funding).

    Returns:
        pd.Series of funding payments (negative = paid by position, positive = received).
    """
    # Align funding to bar frequency (already resampled to daily sum)
    aligned = funding_rates.reindex(position_value_series.index, method='ffill').fillna(0)

    # Compute raw payment: position * rate
    payments = position_value_series * aligned["funding_rate"]

    # Long pays positive rate, receives negative rate
    if is_short:
        payments = -payments

    return payments


def adjust_equity_for_funding(
    pf: vbt.Portfolio,
    funding_payments: pd.Series,
) -> FundingAdjustedResult:
    """
    Adjust portfolio equity curve by subtracting cumulative funding payments.

    pf: vectorbt Portfolio object from from_signals()
    funding_payments: per-bar funding cash flows (signed)
    """
    equity = pf.value()
    cum_funding = funding_payments.cumsum()
    equity_adj = equity - cum_funding

    # Recompute returns from adjusted equity
    ret_adj = equity_adj.pct_change().dropna()
    sharpe_adj = float(np.sqrt(365) * ret_adj.mean() / ret_adj.std()) if ret_adj.std() > 0 else 0.0

    return FundingAdjustedResult(
        equity_adjusted=equity_adj,
        total_funding_paid=float(cum_funding.iloc[-1]),
        total_return_adjusted=float(equity_adj.iloc[-1] / equity_adj.iloc[0] - 1),
        sharpe_adjusted=sharpe_adj,
    )
```

### Pattern 5: Margin Model

**What:** `MarginState` dataclass tracks isolated or cross margin per position. `compute_margin_utilization()` computes current margin ratio. Used by the new RiskEngine gate.

```python
# Source: standard perpetuals margin math, verified against Binance/Bybit docs
# src/ta_lab2/risk/margin_monitor.py

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class MarginTier:
    """One bracket in a venue's tiered margin schedule."""
    notional_floor: Decimal     # min position notional for this tier
    notional_cap: Decimal       # max position notional for this tier (Decimal('inf') for last)
    initial_margin_rate: Decimal  # e.g., Decimal('0.01') = 1% IM
    maintenance_margin_rate: Decimal  # e.g., Decimal('0.005') = 0.5% MM

@dataclass
class MarginState:
    """Live margin state for one perp position."""
    venue: str
    symbol: str
    position_value: Decimal          # mark_price * abs(quantity)
    leverage: Decimal                # 1x to 10x (V1)
    margin_mode: str                 # 'isolated' or 'cross'

    # Derived fields (filled by compute_margin_utilization)
    initial_margin: Decimal = Decimal("0")
    maintenance_margin: Decimal = Decimal("0")
    margin_utilization: Decimal = Decimal("0")  # current_margin / maintenance_margin
    is_liquidation_warning: bool = False   # margin_utilization <= 1.5
    is_liquidation_critical: bool = False  # margin_utilization <= 1.1


def compute_margin_utilization(
    position_value: Decimal,
    current_margin: Decimal,  # collateral held for this position
    leverage: Decimal,
    tiers: list,              # List[MarginTier] for this venue/symbol
    margin_mode: str = 'isolated',
) -> MarginState:
    """
    Compute margin utilization and liquidation status.

    Isolated margin: position collateral = position_value / leverage
    Cross margin: shared wallet minus unrealized losses for all positions

    Liquidation condition: current_margin < maintenance_margin

    Buffer zones (from CONTEXT.md):
    - Alert threshold: margin_utilization <= 1.5x maintenance margin
    - Kill switch threshold: margin_utilization <= 1.1x maintenance margin
    """
    # Find applicable tier
    mm_rate = Decimal("0.005")  # fallback 0.5%
    im_rate = Decimal("0.01")   # fallback 1%
    for tier in sorted(tiers, key=lambda t: t.notional_floor):
        if position_value >= tier.notional_floor:
            mm_rate = tier.maintenance_margin_rate
            im_rate = tier.initial_margin_rate

    initial_margin = position_value * im_rate
    maintenance_margin = position_value * mm_rate

    # Margin utilization: ratio of current margin to maintenance margin
    if maintenance_margin > 0:
        margin_utilization = current_margin / maintenance_margin
    else:
        margin_utilization = Decimal("999")

    return MarginState(
        venue="",
        symbol="",
        position_value=position_value,
        leverage=leverage,
        margin_mode=margin_mode,
        initial_margin=initial_margin,
        maintenance_margin=maintenance_margin,
        margin_utilization=margin_utilization,
        is_liquidation_warning=margin_utilization <= Decimal("1.5"),
        is_liquidation_critical=margin_utilization <= Decimal("1.1"),
    )
```

### Pattern 6: RiskEngine Gate 1.6 (Margin Monitor)

**What:** New gate added to `RiskEngine.check_order()` after Gate 1.5 (tail risk) and before Gate 2 (circuit breaker). Reads `cmc_margin_state` table (updated by paper executor on each fill) and blocks new orders when liquidation critical.

```python
# Extension to src/ta_lab2/risk/risk_engine.py
# Add after Gate 1.5 (tail_risk_state check):

# Gate 1.6: Margin/liquidation check
margin_result = self._check_margin_gate(asset_id=asset_id, strategy_id=strategy_id)
if margin_result == "critical":
    self._log_event(
        event_type="liquidation_critical",
        trigger_source="margin_monitor",
        reason="Order blocked: margin utilization at or below 1.1x maintenance margin",
        asset_id=asset_id,
        strategy_id=strategy_id,
    )
    return RiskCheckResult(
        allowed=False,
        blocked_reason=f"Liquidation critical: margin utilization <= 1.1x maintenance for asset_id={asset_id}",
    )
```

The new event types require extending the `chk_risk_events_type` CHECK constraint (drop+recreate pattern from Phase 49).

### Pattern 7: Venue Downtime Playbook Format

**What:** Follows Phase 49 pattern -- Markdown document + machine-readable YAML config. The Markdown is human-readable procedure; the YAML defines health check parameters and escalation logic.

```yaml
# reports/perps/venue_health_config.yaml

version: "1.0"
generated_at: "2026-02-25"

venues:
  binance:
    health_endpoint: "https://fapi.binance.com/fapi/v1/ping"
    status_page: "https://www.binance.com/en/support/announcement"
    max_latency_ms: 2000
    stale_orderbook_seconds: 30
    spread_alert_pct: 0.5      # alert if bid-ask spread > 0.5%

  hyperliquid:
    health_endpoint: "https://api.hyperliquid.xyz/info"
    max_latency_ms: 3000
    stale_orderbook_seconds: 30

  bybit:
    health_endpoint: "https://api.bybit.com/v5/market/time"
    max_latency_ms: 2000
    stale_orderbook_seconds: 30

  dydx:
    health_endpoint: "https://indexer.dydx.trade/v4/time"
    max_latency_ms: 4000       # dYdX chain can be slower
    stale_orderbook_seconds: 60

  aevo:
    health_endpoint: "https://api.aevo.xyz/time"
    max_latency_ms: 3000
    stale_orderbook_seconds: 30

  aster:
    health_endpoint: "https://fapi.asterdex.com/fapi/v1/time"
    max_latency_ms: 3000
    stale_orderbook_seconds: 30

health_states:
  healthy:    { latency_ok: true, stale_orderbook: false, spread_normal: true }
  degraded:   { latency_ok: false, stale_orderbook: false, spread_normal: true }
  down:       { latency_ok: false }

downtime_actions:
  degraded:
    - alert_telegram: true
    - halt_new_orders: false
    - monitor_interval_seconds: 60
  down:
    - alert_telegram: true
    - halt_new_orders: true
    - hedge_on_alternate_venue: true
    - alternate_venue_priority: ["binance", "bybit", "hyperliquid"]
```

### Anti-Patterns to Avoid

- **Bybit startTime without endTime:** Bybit v5 `GET /v5/market/funding/history` returns an error when `startTime` is provided without `endTime`. Always pass both or neither.
- **Aevo nanosecond timestamps:** Aevo API uses UNIX nanoseconds, not milliseconds. `int(ts_ns / 1e9)` to convert. Forgetting this produces dates in 2059.
- **dYdX v3 vs v4 endpoint:** dYdX v3 (`api.dydx.exchange/v1/historical-funding-rates`) is deprecated. Use v4 indexer: `indexer.dydx.trade/v4/historicalFunding/{market}`. dYdX v3 history is not available through the v4 API.
- **Funding rate sign convention:** Not all venues use the same sign. Standard: positive rate = longs pay shorts. Verify sign convention per venue before storing.
- **hardcode down_revision:** Detect Alembic head dynamically (`alembic history | head -1`). Current head = `b5178d671e38`. Phases 47-50 may add migrations before Phase 51.
- **cmc_positions exchange CHECK constraint:** Currently `CHECK (exchange IN ('coinbase', 'kraken', 'paper', 'aggregate'))`. Any perp position tracking extension must add new venue values or use a separate table.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exchange API connectivity base class | New HTTP client | `ExchangeInterface` + `requests.Session` from `base.py` | Already established, has error handling decorator |
| Multi-venue pagination loop | Custom per-venue | Shared `_paginate(fetcher, watermark, batch_size)` utility | Binance, Bybit, and Aster all use cursor-based pagination; abstract it |
| Funding rate P&L in vectorbt sim | `from_order_func` callbacks | Post-simulation `FundingAdjuster` | Simpler, identical results, no risk of vbt 0.28.1 API breakage |
| Margin tier lookup | Custom tier logic | DB table `cmc_margin_config` with tiered rows | Tiers change; DB-backed config matches pattern of `dim_risk_limits` |
| Carry trade as separate backtest | New backtest class | `instrument='perp'` flag + `FundingAdjuster` in `vbt_runner.py` | Carry trade is long spot + short perp; modeled as two position legs |
| Venue health check | Custom HTTP pinger | Existing `requests.Session` from connectivity adapters | Already instantiated; just call the health endpoint |

---

## Common Pitfalls

### Pitfall 1: Bybit Funding History startTime Constraint

**What goes wrong:** `GET /v5/market/funding/history?category=linear&symbol=BTCUSDT&startTime=1234567890000` returns HTTP 400.
**Why it happens:** Bybit v5 requires that if startTime is provided, endTime must also be provided.
**How to avoid:** Always paginate by providing both startTime and endTime in a sliding window. When fetching full history, iterate: `end = now; while end > earliest: start = end - window; fetch(start, end); end = start`.
**Warning signs:** HTTP 400 from Bybit with a startTime parameter but no endTime.

### Pitfall 2: Aevo Timestamp Format (Nanoseconds Not Milliseconds)

**What goes wrong:** Funding rate timestamps from Aevo parse as year 2059.
**Why it happens:** Aevo uses UNIX nanoseconds for timestamps. `int("1680249600000000000") / 1000 = 1.68e15` which is far in the future when treated as seconds.
**How to avoid:** Always divide by `1e9` for Aevo: `datetime.fromtimestamp(int(ts_str) / 1e9, tz=timezone.utc)`.
**Warning signs:** Timestamps > year 2030 when parsed.

### Pitfall 3: dYdX v3 vs v4 Endpoint

**What goes wrong:** Code hits `api.dydx.exchange/v1/historical-funding-rates` (v3) and gets data only back to Oct 2023 then gaps before that.
**Why it happens:** dYdX migrated from v3 (centralized) to v4 (Cosmos chain) in Oct 2023. The v3 API is deprecated or returns stale data.
**How to avoid:** Use `indexer.dydx.trade/v4/historicalFunding/{market}` for all v4 data. For BTC, use `market='BTC-USD'`. Note: dYdX v4 history starts Oct 2023 only.
**Warning signs:** Empty or sparse response from v3 URL.

### Pitfall 4: Funding Rate Sign Convention Variance

**What goes wrong:** Funding rate comparison across venues shows 6x divergence even when rates should track each other.
**Why it happens:** Some venues store the per-settlement rate (e.g., 0.01% per 8h), others store annualized, others store the 1h rate even for 8h settlement periods. Sign conventions can also differ (Hyperliquid stores rate that longs pay if positive; some venues may flip this).
**How to avoid:** During ingestion, normalize to per-settlement raw rate. Document each venue's convention in code comments. Cross-validate against third-party aggregators (Coinglass, CoinAlize) during development.
**Warning signs:** Cross-venue average appears 8x higher or lower than individual venue rates.

### Pitfall 5: cmc_positions exchange CHECK Constraint Blocks Perp Tracking

**What goes wrong:** Attempting to INSERT a new cmc_positions row with `exchange='hyperliquid'` fails with CHECK constraint violation.
**Why it happens:** `cmc_positions` has `CHECK (exchange IN ('coinbase', 'kraken', 'paper', 'aggregate'))` -- the Phase 44 DDL only lists spot exchanges.
**How to avoid:** Phase 51 Alembic migration must extend the CHECK constraint to include perp venues, OR use a separate `cmc_perp_positions` table (preferred to avoid touching existing spot position logic).
**Warning signs:** `ERROR: new row violates check constraint "chk_positions_exchange"`.

### Pitfall 6: Alembic Migration Chain Dependency

**What goes wrong:** Phase 51 migration hardcodes `down_revision = 'b5178d671e38'` (Phase 46 head). Phases 47-50 add migrations. Phase 51 fails with "Multiple head revisions".
**Why it happens:** Phases 47-50 have PLANs but may not be executed yet. Current actual head = `b5178d671e38`.
**How to avoid:** At the START of Phase 51 Plan 01 (schema), run `alembic heads` to detect current head. Use dynamic detection in migration file, not hardcoded value.
**Warning signs:** `alembic upgrade head` fails with multiple head error.

### Pitfall 7: Vectorbt 0.28.1 UTC Timezone Issue in Funding Backtests

**What goes wrong:** Funding rate DataFrame has UTC-aware DatetimeIndex, vectorbt portfolio equity has UTC-stripped index. Join fails or produces NaN-filled series.
**Why it happens:** MEMORY.md documents that `series.values` on tz-aware datetime Series drops tz info. vbt 0.28.1 requires tz-stripped inputs.
**How to avoid:** Strip timezone when feeding to vbt (`price.index.tz_localize(None)`). For post-sim adjustment, use tz-aware funding rates for alignment but match on tz-naive index from vbt portfolio output.
**Warning signs:** All `FundingAdjustedResult.total_funding_paid == 0` despite real positions.

### Pitfall 8: Lighter API -- No Stable Public REST Endpoint for History

**What goes wrong:** Calling a REST endpoint on Lighter for historical funding rates returns 404 or unexpected response.
**Why it happens:** Lighter is a newer DEX (mainnet 2024, raised at $1.5B valuation Nov 2025). Their REST funding history endpoint may not be publicly documented. The API docs redirect to their SDK (`lighter-python`).
**How to avoid:** For Phase 51 V1, use the Lighter Python SDK (`lighter-python`) via the `OrderApi` or dedicated market data method. If SDK doesn't expose funding history, fall back to the websocket stream or use third-party aggregators (Coinglass/CoinAlize) as a backup source for historical Lighter data.
**Warning signs:** 404 from `apidocs.lighter.xyz` funding endpoints; no REST example in official docs.

### Pitfall 9: ASCII-Only in SQL Migrations (Windows)

**What goes wrong:** UTF-8 box-drawing chars (like em-dash, horizontal rules using `===`) in SQL migration comments cause `UnicodeDecodeError` with Windows cp1252 encoding.
**Why it happens:** MEMORY.md documents this. Default file encoding on Windows is cp1252.
**How to avoid:** ALL SQL files and Alembic migrations must use ASCII-only characters. Use `--` comments with plain ASCII text, no decorative dividers.
**Warning signs:** `UnicodeDecodeError: 'charmap' codec can't decode byte`.

---

## Code Examples

### Watermark-Based Full History Ingest (Binance)

```python
# Source: modeled after sync_utils.py watermark pattern + Binance API docs
# For initial historical backfill then incremental updates

from datetime import datetime, timezone, timedelta
import time

def ingest_binance_full_history(engine, symbol: str = 'BTCUSDT',
                                  batch_size: int = 1000) -> int:
    """
    Ingest full Binance funding history from earliest available (~Sep 2019)
    using 8h batches (3 settlements/day). Uses watermark to resume if interrupted.

    Returns total rows inserted.
    """
    # Binance BTC perpetual launched Sep 2019
    # Funding rate interval: 8h = 28800000 ms
    INTERVAL_MS = 8 * 60 * 60 * 1000

    # Check watermark (last stored ts for this venue/symbol)
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT MAX(ts) FROM public.cmc_funding_rates
            WHERE venue = 'binance' AND symbol = :sym AND tf = '8h'
        """), {"sym": symbol.replace("USDT", "")}).fetchone()
    last_ts = row[0] if row and row[0] else None

    if last_ts:
        start_ms = int(last_ts.timestamp() * 1000) + INTERVAL_MS
    else:
        start_ms = 1569888000000  # Sep 2019 approximate

    total_inserted = 0
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    while start_ms < now_ms:
        end_ms = min(start_ms + batch_size * INTERVAL_MS, now_ms)
        rows = fetch_binance_funding(symbol, start_ms=start_ms, end_ms=end_ms, limit=batch_size)
        if rows:
            inserted = upsert_funding_rates(engine, rows)
            total_inserted += inserted
        start_ms = end_ms + INTERVAL_MS
        time.sleep(0.1)  # Respect 500/5min rate limit

    return total_inserted
```

### Daily Rollup from Sub-Day Rates

```python
# Source: project standard pandas resampling pattern

def compute_daily_rollup(engine, venue: str, symbol: str) -> int:
    """
    Compute daily funding rate rollup from hourly/4h/8h rows.
    Stores as tf='1d'.

    For 8h venue: sum 3 settlements. For 1h venue: sum 24 settlements.
    Daily total funding rate = sum of all settlement rates on that day.
    """
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT ts, funding_rate, tf
            FROM public.cmc_funding_rates
            WHERE venue = :venue AND symbol = :sym AND tf != '1d'
            ORDER BY ts
        """), conn, params={"venue": venue, "sym": symbol})

    df['ts'] = pd.to_datetime(df['ts'], utc=True)
    df = df.set_index('ts')

    # Resample to daily sum (sum of all settlements in each UTC day)
    daily = df['funding_rate'].resample('1D').sum().reset_index()
    daily.columns = ['ts', 'funding_rate']
    daily['venue'] = venue
    daily['symbol'] = symbol
    daily['tf'] = '1d'
    daily['raw_tf'] = 'rollup'
    daily['ingested_at'] = datetime.now(timezone.utc)

    # Upsert
    rows = [FundingRateRow(**r) for _, r in daily.iterrows()]
    return upsert_funding_rates(engine, rows)
```

### Cross-Venue Average Fallback

```python
# Source: CONTEXT.md decision: "cross-venue average fill when specific venue unavailable"

def get_funding_rate_with_fallback(
    engine,
    venue: str,
    symbol: str,
    ts: datetime,
    tf: str = '8h',
) -> Optional[float]:
    """
    Fetch funding rate for a specific venue/ts. Falls back to cross-venue average
    when this venue's data is missing.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT funding_rate FROM public.cmc_funding_rates
            WHERE venue = :venue AND symbol = :sym AND ts = :ts AND tf = :tf
        """), {"venue": venue, "sym": symbol, "ts": ts, "tf": tf}).fetchone()

    if row:
        return float(row[0])

    # Fallback: cross-venue average at closest available ts
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT AVG(funding_rate) FROM public.cmc_funding_rates
            WHERE symbol = :sym
              AND ts BETWEEN :ts - interval '30 minutes' AND :ts + interval '30 minutes'
              AND tf = :tf
        """), {"sym": symbol, "ts": ts, "tf": tf}).fetchone()

    return float(row[0]) if row and row[0] is not None else None
```

### Margin Tier Loading from DB

```python
# Source: mirrors dim_risk_limits pattern (specificity ordering via DB query)

def load_margin_tiers(engine, venue: str, symbol: str) -> list:
    """Load venue-specific margin tiers from cmc_margin_config."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT notional_floor, notional_cap,
                   initial_margin_rate, maintenance_margin_rate
            FROM public.cmc_margin_config
            WHERE venue = :venue AND symbol = :sym
            ORDER BY notional_floor ASC
        """), {"venue": venue, "sym": symbol}).fetchall()

    return [MarginTier(
        notional_floor=Decimal(str(r[0])),
        notional_cap=Decimal(str(r[1])) if r[1] is not None else Decimal("inf"),
        initial_margin_rate=Decimal(str(r[2])),
        maintenance_margin_rate=Decimal(str(r[3])),
    ) for r in rows]
```

---

## Venue API Summary Table

| Venue | Base URL | Endpoint | Settlement | Auth | Pagination | History |
|-------|----------|----------|-----------|------|-----------|---------|
| Binance | `https://fapi.binance.com` | `GET /fapi/v1/fundingRate` | 8h | None (public) | startTime/endTime, limit 1000 | ~Sep 2019 (BTC) |
| Hyperliquid | `https://api.hyperliquid.xyz` | `POST /info {"type":"fundingHistory"}` | 1h | None (public) | startTime/endTime | ~2023 (HL mainnet) |
| Bybit | `https://api.bybit.com` | `GET /v5/market/funding/history` | 8h (BTC/ETH) | None (public) | endTime required with startTime; limit 200 | ~2019 (BTC) |
| dYdX v4 | `https://indexer.dydx.trade` | `GET /v4/historicalFunding/{market}` | 1h | None (public) | effectiveBeforeOrAt cursor | Oct 2023 (v4 launch) |
| Aevo | `https://api.aevo.xyz` | `GET /funding-history` | 1h | None (public) | offset pagination, limit 50 | Sep 2023 (Aevo launch) |
| Aster | `https://fapi.asterdex.com` | `GET /fapi/v1/fundingRate` | 8h (varies) | None (public) | startTime/endTime, limit 1000 | ~2023 (Aster launch) |
| Lighter | `https://api.lighter.xyz` | SDK only (lighter-python) | 1h | None (public) | SDK-based | 2024 (mainnet) |

**Funding settlement periods summary:**
- **8h venues:** Binance, Bybit (BTC/ETH), Aster (most pairs)
- **1h venues (rate = 8h rate / 8):** Hyperliquid, dYdX v4, Aevo, Lighter
- **4h venues:** Aevo (some instruments), Aster (ASTERUSDT)

---

## Margin Rate Reference (Verified from Official Docs)

### Binance BTC/ETH Perpetual Tiers (via `GET /fapi/v1/leverageBracket`)

API: `GET /fapi/v1/leverageBracket?symbol=BTCUSDT` (requires auth, USER_DATA)

Typical structure for BTC (as of 2025, may change):
- Tier 1: 0 - 50K USDT notional, max leverage 125x, MM rate 0.4%, IM rate 0.8%
- Tier 2: 50K - 250K USDT notional, max leverage 100x, MM rate 0.5%, IM rate 1%
- Tier 3: 250K - 1M USDT notional, max leverage 50x, MM rate 1%, IM rate 2%

**Implementation note:** For paper V1 (1-10x leverage), only the first 2-3 tiers apply. Use the API to populate `cmc_margin_config` during initial setup.

### Hyperliquid BTC/ETH Margin (via `POST /info {"type": "meta"}`)

BTC: max leverage 50x. Maintenance margin rate = 1/(2 * maxLeverage) = 1% at 50x.
ETH: max leverage 50x. Same formula.
Initial margin rate = 1/maxLeverage (at max leverage).

For V1 (1-10x), the initial margin requirement is: 1/leverage (e.g., 10% at 10x).

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed daily funding bps in backtester | Per-settlement venue-specific rates with cross-venue fallback | Phase 51 | Accurate carry trade modeling |
| Spot-only position tracking | Perp positions with margin mode + leverage tracking | Phase 51 | Enables liquidation simulation |
| Binary exchange health (up/down) | Graduated health status: healthy > degraded > down | Phase 51 | Proportional response to degradation |
| Manual playbook only | Machine-readable YAML + human procedure document | Phase 51 (Phase 49 pattern) | Enables automated health checking |

**Deprecated/outdated:**
- dYdX v3 API (`api.dydx.exchange/v1/`): deprecated since Oct 2023 chain migration; use v4 indexer.
- Fixed `CostModel.funding_bps_day` for perps: insufficient for venue-specific multi-settlement modeling; use `FundingAdjuster` instead.

---

## Claude's Discretion -- Decisions Made

Based on research, the following CONTEXT.md open items are resolved:

### Funding Application Timing in Backtester

**Decision: Both modes -- per-settlement and daily aggregated -- as separate method arguments.**

Rationale: For carry trade analysis, per-settlement accuracy matters (8h vs 1h). For simple directional backtests, daily aggregated is sufficient. The `FundingAdjuster` class accepts `mode='per_settlement'|'daily'`. Both use the post-hoc replay pattern (not vectorbt callbacks).

### RiskEngine Integration for Margin/Liquidation

**Decision: Extend existing RiskEngine as Gate 1.6 (NOT a separate MarginMonitor class).**

Rationale: Keeps all risk gates in one place, matching the Phase 49 pattern for Gate 1.5 (tail risk). Gate 1.6 reads from a new `cmc_perp_positions` table (separate from `cmc_positions` to avoid touching spot position logic). The separate `margin_monitor.py` module handles the computation logic, RiskEngine calls it.

### Playbook Format

**Decision: Markdown document + machine-readable YAML config (same as Phase 49 pattern).**

Rationale: Phase 49 established this dual-format approach for policies. YAML covers health check parameters and escalation thresholds; Markdown covers human operator procedure.

### Venue Failover Automation Scope

**Decision: Manual procedure with machine-readable config for V1. Automated routing deferred.**

Rationale: Automated hedge-on-alternate-venue requires a live order routing capability not built in this phase. The playbook documents the MANUAL procedure (operator reads YAML config to identify alternate venue, manually executes hedge order on paper trading or live system). Automated routing is Phase 51+.

### Table Schema for Funding Rates

**Decision: Single `cmc_funding_rates` table with `tf` column for granularity.**

Rationale: Directly mirrors the project's multi-TF pattern (`cmc_price_bars_multi_tf`, `cmc_ema_multi_tf`, etc.). Joining is straightforward. The `tf IN ('1h','4h','8h','1d')` constraint handles all granularities. No need for separate tables.

### Pipeline Wiring

**Decision: Standalone only for V1. NOT wired into run_daily_refresh.py.**

Rationale: Funding rate data comes from exchange APIs, not CMC. The existing pipeline is CMC-centric. Adding funding ingest to the daily refresh introduces exchange API failures that could block the entire CMC pipeline. Run as separate scheduled job or ad-hoc CLI.

---

## Open Questions

1. **Lighter funding rate history via REST**
   - What we know: Lighter launched mainnet 2024, has hourly settlement, lighter-python SDK exists. The API docs page at `docs.lighter.xyz/perpetual-futures/api` returned 404.
   - What is unclear: Whether a stable REST endpoint for historical funding rates exists or SDK is required.
   - Recommendation: Plan 01 should attempt direct HTTP calls; fall back to lighter-python SDK. If neither works, use Coinglass as data source for Lighter history.

2. **dYdX v4 historical funding depth**
   - What we know: dYdX v4 mainnet launched Oct 2023. The indexer endpoint exists at `indexer.dydx.trade/v4/historicalFunding/{market}`. Response format confirmed.
   - What is unclear: How far back the indexer retains data. Indexer databases may have pruning policies.
   - Recommendation: Test with earliest possible cursor during implementation. If pruned, document the available history start date.

3. **Alembic head after phases 47-50**
   - What we know: Current head = `b5178d671e38` (Phase 46). Phases 47-50 have PLANs and some SUMMARYs but it is unclear which have been executed.
   - What is unclear: The actual Alembic head when Phase 51 runs.
   - Recommendation: Phase 51 Plan 01 MUST start with `alembic heads` check. Migration file must detect head dynamically.

4. **Aster DEX perpetual data history depth**
   - What we know: Aster API base URL is `https://fapi.asterdex.com`, endpoint is `GET /fapi/v1/fundingRate`, mirrors Binance API exactly.
   - What is unclear: How far back Aster data goes (Aster is newer, likely 2022-2023 launch).
   - Recommendation: Ingest whatever is available; document actual start date in the ingest log.

5. **cmc_risk_events CHECK constraint extension**
   - What we know: Adding `liquidation_warning` and `liquidation_critical` event types requires drop+recreate of `chk_risk_events_type`.
   - Recommendation: Follow Phase 49 pattern exactly (drop constraint, recreate with full list of all event types including previous + new).

---

## Sources

### Primary (HIGH confidence)

- Project codebase: `src/ta_lab2/connectivity/base.py` -- ExchangeInterface pattern confirmed
- Project codebase: `src/ta_lab2/connectivity/hyperliquid.py` -- existing Hyperliquid adapter, `POST /info` pattern confirmed
- Project codebase: `src/ta_lab2/connectivity/binance.py` -- Binance adapter, base URL `https://api.binance.com` confirmed
- Project codebase: `src/ta_lab2/connectivity/factory.py` -- factory pattern for adding new venues
- Project codebase: `src/ta_lab2/risk/risk_engine.py` -- 5+1.5 gate architecture, confirmed extension pattern
- Project codebase: `src/ta_lab2/backtests/vbt_runner.py` -- `CostModel`, `funding_bps_day` field; confirmed vectorbt 0.28.1 integration
- Project codebase: `src/ta_lab2/executor/paper_executor.py` -- position tracking, `cmc_positions` usage
- Project codebase: `sql/trading/084_cmc_positions.sql` -- confirmed exchange CHECK constraint blocks perp venues
- Project codebase: `alembic heads` output -- confirmed current head = `b5178d671e38`
- Official docs: `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History` -- confirmed endpoint URL, params, response format
- Official docs: `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals` -- confirmed `POST /info {"type":"fundingHistory"}`, 1h settlement
- Official docs: `https://bybit-exchange.github.io/docs/v5/market/history-fund-rate` -- confirmed `GET /v5/market/funding/history`, startTime+endTime constraint
- Official docs: `https://docs.dydx.xyz/indexer-client/http` (via redirect from `docs.dydx.exchange`) -- confirmed `GET /v4/historicalFunding/{market}`, 1h settlement
- Official docs: `https://api-docs.aevo.xyz/reference/getfundinghistory` -- confirmed nanosecond timestamps, limit 50, 1h settlement
- Official docs: `https://docs.asterdex.com/product/aster-perpetuals/api/api-documentation` -- confirmed Binance API mirror, `GET /fapi/v1/fundingRate`

### Secondary (MEDIUM confidence)

- WebSearch + official Bybit announcement: Bybit dynamic settlement NOT applied to BTC/ETH (Oct 2025 announcement confirmed)
- WebSearch + Aster docs: Aster base URL `https://fapi.asterdex.com` confirmed; API mirrors Binance Futures
- WebSearch + Aevo docs: Aevo 1h settlement confirmed; rate = 8h rate / 8
- WebSearch + Lighter docs: Lighter 1h settlement confirmed; lighter-python SDK primary access method

### Tertiary (LOW confidence)

- WebSearch only: Lighter REST funding history endpoint existence -- unverified (404 on docs page)
- WebSearch only: dYdX v4 indexer data retention policy -- unknown, assumed full since mainnet
- WebSearch only: Aster funding rate history depth -- unknown, assumed from exchange launch date
- Training knowledge: Binance BTC perpetual launched Sep 2019 -- consistent with search results but exact start date should be verified via API probe

---

## Metadata

**Confidence breakdown:**
- Binance, Hyperliquid, Bybit, dYdX, Aevo API endpoints: HIGH -- verified against official docs
- Aster API endpoint (Binance mirror): MEDIUM -- confirmed from docs but history depth unknown
- Lighter API: LOW -- SDK-based, no stable REST endpoint confirmed
- Margin tier structure (general formula): MEDIUM -- confirmed from Binance docs, verified formula
- Venue-specific margin rates (exact numbers): LOW -- Binance API confirmed but numbers change; must fetch live at implementation time
- Backtester extension approach (post-hoc FundingAdjuster): HIGH -- confirmed vectorbt 0.28.1 limitations; post-hoc is only viable approach
- Alembic migration chain: HIGH -- current head `b5178d671e38` verified via `alembic heads`
- Project patterns (exchange adapter, risk gate extension): HIGH -- all verified from source code

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (30 days; API endpoints are stable; margin rates should be fetched live at implementation time)
