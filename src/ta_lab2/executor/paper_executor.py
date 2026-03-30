"""PaperExecutor: Orchestrates the signal-to-fill pipeline for paper trading.

Ties together SignalReader, PositionSizer, FillSimulator, CanonicalOrder,
PaperOrderLogger, and OrderManager into the main execution loop.

Execution flow per strategy (dim_executor_config WHERE is_active=TRUE):
1. Load config from DB
2. Check signal freshness (stale guard -- skip if first run)
3. Read unprocessed signals via watermark + executor_processed_at IS NULL
4. For each asset: compute target vs current position
5. Generate CanonicalOrder for delta (signal_id set BEFORE logging)
6. Log to paper_orders via PaperOrderLogger
7. Promote to orders via OrderManager.promote_paper_order
8. Simulate fill via FillSimulator
9. Process fill via OrderManager.process_fill (strategy_id for isolation)
10. Mark signals as processed, update watermark
11. Write run log entry to executor_run_log
"""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.analysis.garch_blend import get_blended_vol
from ta_lab2.executor.fill_simulator import FillSimulator, FillSimulatorConfig
from ta_lab2.executor.position_sizer import (
    ExecutorConfig,
    PositionSizer,
    compute_order_delta,
)
from ta_lab2.executor.signal_reader import (
    SIGNAL_TABLE_MAP,
    SignalReader,
    StaleSignalError,
)
from ta_lab2.paper_trading.canonical_order import CanonicalOrder
from ta_lab2.paper_trading.paper_order_logger import PaperOrderLogger
from ta_lab2.risk.macro_gate_evaluator import MacroGateEvaluator
from ta_lab2.risk.risk_engine import RiskEngine
from ta_lab2.trading.order_manager import FillData, OrderManager

logger = logging.getLogger(__name__)

# Minimum order delta threshold -- deltas smaller than this are skipped.
# 0.00001 = 1 satoshi at $100K BTC price ~ $1 minimum order.
_MIN_ORDER_THRESHOLD = Decimal("0.00001")


# ---------------------------------------------------------------------------
# PaperExecutor
# ---------------------------------------------------------------------------


class PaperExecutor:
    """
    Reads signals, generates paper orders, simulates fills, updates positions.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        Database engine. Used for all DB reads and writes.

    Usage
    -----
    executor = PaperExecutor(engine)
    summary = executor.run(dry_run=False)
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.signal_reader = SignalReader(engine)
        self._macro_gate_evaluator = MacroGateEvaluator(engine)
        self.risk_engine = RiskEngine(
            engine, macro_gate_evaluator=self._macro_gate_evaluator
        )
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        dry_run: bool = False,
        replay_historical: bool = False,
        replay_start: str | None = None,
        replay_end: str | None = None,
    ) -> dict:
        """
        Execute paper trading for all active strategies. Returns run summary.

        Parameters
        ----------
        dry_run : bool
            If True, log decisions but do not write to DB (no orders, fills,
            or position updates). Run log is still written for audit purposes.
        replay_historical : bool
            If True, skip the freshness check and process all unprocessed signals
            regardless of age. Useful for backtesting signal processing logic.
        replay_start : str | None
            ISO timestamp string. When set, only process signals >= this timestamp.
        replay_end : str | None
            ISO timestamp string. When set, only process signals <= this timestamp.

        Returns
        -------
        dict
            Summary dict with keys: status, strategies_processed, total_signals,
            total_orders, total_fills, total_skipped, errors.
        """
        configs = self._load_active_configs()
        if not configs:
            self.logger.info("PaperExecutor: no active executor configs found")
            return {"status": "no_configs", "strategies_processed": 0}

        summary: dict = {
            "status": "success",
            "strategies_processed": 0,
            "total_signals": 0,
            "total_orders": 0,
            "total_fills": 0,
            "total_skipped": 0,
            "errors": [],
        }

        # Load L4 macro regime once for run-level audit (asset_id=1 is representative
        # since L4 is a global macro regime -- same label applies to all assets).
        self._current_l4_label: Optional[str] = None
        self._current_l4_size_mult: Optional[float] = None
        try:
            with self.engine.connect() as conn:
                regime_info = self._load_regime_for_asset(conn, 1)
                if regime_info["l4_label"] is not None:
                    self._current_l4_label = regime_info["l4_label"]
                    self._current_l4_size_mult = regime_info["size_mult"]
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("PaperExecutor: L4 regime query failed: %s", exc)

        for config in configs:
            try:
                result = self._run_strategy(
                    config,
                    dry_run=dry_run,
                    replay_historical=replay_historical,
                    replay_start=replay_start,
                    replay_end=replay_end,
                )
                summary["strategies_processed"] += 1
                summary["total_signals"] += result.get("signals_read", 0)
                summary["total_orders"] += result.get("orders_generated", 0)
                summary["total_fills"] += result.get("fills_processed", 0)
                summary["total_skipped"] += result.get("skipped_no_delta", 0)
            except StaleSignalError as exc:
                self.logger.error(
                    "PaperExecutor: STALE SIGNAL for config=%s: %s",
                    config.config_name,
                    exc,
                )
                self._try_telegram_alert(
                    f"STALE SIGNAL for {config.config_name}: {exc}"
                )
                self._write_run_log(
                    config,
                    status="stale_signal",
                    error=str(exc),
                )
                summary["errors"].append(
                    {"config": config.config_name, "error": str(exc)}
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.exception(
                    "PaperExecutor: strategy execution failed for config=%s",
                    config.config_name,
                )
                self._write_run_log(config, status="failed", error=str(exc))
                summary["errors"].append(
                    {"config": config.config_name, "error": str(exc)}
                )
                summary["status"] = "partial_failure"

        if summary["errors"] and summary["strategies_processed"] == 0:
            summary["status"] = "failed"

        return summary

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_active_configs(self) -> list[ExecutorConfig]:
        """
        Query dim_executor_config WHERE is_active = TRUE.

        Returns a list of ExecutorConfig dataclasses, one per active row.
        Returns an empty list if no active configs exist.
        """
        sql = text(
            """
            SELECT config_id, config_name, signal_type, signal_id,
                   exchange, environment, sizing_mode, position_fraction,
                   max_position_fraction, fill_price_mode, cadence_hours,
                   last_processed_signal_ts, slippage_mode, slippage_base_bps,
                   slippage_noise_sigma, volume_impact_factor,
                   rejection_rate, partial_fill_rate, execution_delay_bars,
                   initial_capital
            FROM public.dim_executor_config
            WHERE is_active = TRUE
            ORDER BY config_id
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql).fetchall()

        configs = []
        for row in rows:
            cfg = ExecutorConfig(
                config_id=row.config_id,
                config_name=row.config_name,
                signal_type=row.signal_type,
                signal_id=row.signal_id,
                exchange=row.exchange,
                sizing_mode=row.sizing_mode,
                position_fraction=float(row.position_fraction),
                max_position_fraction=float(row.max_position_fraction),
                fill_price_mode=row.fill_price_mode,
                cadence_hours=float(row.cadence_hours),
                last_processed_signal_ts=row.last_processed_signal_ts,
                initial_capital=(
                    Decimal(str(row.initial_capital))
                    if row.initial_capital is not None
                    else Decimal("100000")
                ),
            )
            # Attach extra fields used during execution (not in dataclass)
            cfg._environment = row.environment  # type: ignore[attr-defined]
            cfg._slippage_mode = row.slippage_mode  # type: ignore[attr-defined]
            cfg._slippage_base_bps = float(row.slippage_base_bps)  # type: ignore[attr-defined]
            cfg._slippage_noise_sigma = float(row.slippage_noise_sigma)  # type: ignore[attr-defined]
            cfg._volume_impact_factor = float(row.volume_impact_factor)  # type: ignore[attr-defined]
            cfg._rejection_rate = float(row.rejection_rate)  # type: ignore[attr-defined]
            cfg._partial_fill_rate = float(row.partial_fill_rate)  # type: ignore[attr-defined]
            cfg._execution_delay_bars = int(row.execution_delay_bars)  # type: ignore[attr-defined]
            configs.append(cfg)

        self.logger.info("PaperExecutor: loaded %d active configs", len(configs))
        return configs

    # ------------------------------------------------------------------
    # Regime loading
    # ------------------------------------------------------------------

    def _load_regime_for_asset(self, conn, asset_id: int) -> dict:
        """Read the latest regime row from regimes for the given asset.

        Returns a dict with l0_label, l1_label, l2_label, l4_label,
        gross_cap, and size_mult. Defaults to gross_cap=1.0 / size_mult=1.0
        if the table is missing, the row is absent, or any column is NULL.
        Never raises -- failure always returns defaults.
        """
        defaults = {
            "l0_label": None,
            "l1_label": None,
            "l2_label": None,
            "l4_label": None,
            "gross_cap": 1.0,
            "size_mult": 1.0,
        }
        try:
            row = conn.execute(
                text("""
                SELECT l0_label, l1_label, l2_label, l4_label, gross_cap, size_mult
                FROM public.regimes WHERE id = :asset_id AND tf = '1D'
                ORDER BY ts DESC LIMIT 1
            """),
                {"asset_id": asset_id},
            ).fetchone()
        except Exception as exc:
            self.logger.debug(
                "_load_regime_for_asset: query failed for asset_id=%d: %s",
                asset_id,
                exc,
            )
            return defaults
        if row is None:
            return defaults
        return {
            "l0_label": row.l0_label,
            "l1_label": row.l1_label,
            "l2_label": row.l2_label,
            "l4_label": row.l4_label,
            "gross_cap": float(row.gross_cap) if row.gross_cap is not None else 1.0,
            "size_mult": float(row.size_mult) if row.size_mult is not None else 1.0,
        }

    # ------------------------------------------------------------------
    # Per-strategy execution
    # ------------------------------------------------------------------

    def _run_strategy(
        self,
        config: ExecutorConfig,
        dry_run: bool,
        replay_historical: bool,
        replay_start: str | None,
        replay_end: str | None,
    ) -> dict:
        """
        Execute the full signal-to-fill pipeline for a single strategy config.

        Returns a counts dict: signals_read, orders_generated, fills_processed,
        skipped_no_delta, skipped_rejected.
        """
        # Risk gate: check if trading is halted
        if self.risk_engine._is_halted():
            self.logger.warning(
                "PaperExecutor: trading halted for config=%s -- skipping",
                config.config_name,
            )
            self._write_run_log(config, status="halted")
            return {
                "signals_read": 0,
                "orders_generated": 0,
                "fills_processed": 0,
                "skipped_no_delta": 0,
                "skipped_rejected": 0,
            }

        # Risk gate: check daily loss and trigger kill switch if exceeded
        if self.risk_engine.check_daily_loss():
            self.logger.warning(
                "PaperExecutor: daily loss limit triggered for config=%s -- halting",
                config.config_name,
            )
            self._try_telegram_alert(
                f"DAILY LOSS LIMIT triggered for {config.config_name}"
            )
            self._write_run_log(config, status="halted", error="daily_loss_limit")
            return {
                "signals_read": 0,
                "orders_generated": 0,
                "fills_processed": 0,
                "skipped_no_delta": 0,
                "skipped_rejected": 0,
            }

        signal_table = SIGNAL_TABLE_MAP.get(config.signal_type)
        if signal_table is None:
            raise ValueError(
                f"Unknown signal_type={config.signal_type!r} for config_id={config.config_id}"
            )

        counts: dict = {
            "signals_read": 0,
            "orders_generated": 0,
            "fills_processed": 0,
            "skipped_no_delta": 0,
            "skipped_rejected": 0,
        }

        with self.engine.connect() as conn:
            # Step 1: freshness check (skip on first run or replay mode)
            if not replay_historical:
                self.signal_reader.check_signal_freshness(
                    conn=conn,
                    signal_table=signal_table,
                    signal_id=config.signal_id,
                    cadence_hours=config.cadence_hours,
                    last_watermark_ts=config.last_processed_signal_ts,
                )

            # Step 2: read unprocessed signals
            signals = self.signal_reader.read_unprocessed_signals(
                conn=conn,
                signal_table=signal_table,
                signal_id=config.signal_id,
                last_watermark_ts=config.last_processed_signal_ts,
            )

        if not signals:
            self.logger.info(
                "PaperExecutor: no unprocessed signals for config=%s (signal_id=%d)",
                config.config_name,
                config.signal_id,
            )
            self._write_run_log(config, status="no_signals")
            return counts

        counts["signals_read"] = len(signals)

        # Step 3: get latest signal per asset
        latest_per_asset = SignalReader.get_latest_signal_per_asset(signals)

        with self.engine.connect() as conn:
            for asset_id, signal in latest_per_asset.items():
                result = self._process_asset_signal(
                    conn=conn,
                    asset_id=asset_id,
                    signal=signal,
                    config=config,
                    dry_run=dry_run,
                )
                if result.get("skipped_no_delta"):
                    counts["skipped_no_delta"] += 1
                elif result.get("rejected"):
                    counts["skipped_rejected"] += 1
                elif result.get("order_generated"):
                    counts["orders_generated"] += 1
                if result.get("fill_processed"):
                    counts["fills_processed"] += 1

            if not dry_run:
                # Update watermark to latest signal ts
                max_ts = max(s["ts"] for s in signals)
                conn.execute(
                    text(
                        """
                        UPDATE public.dim_executor_config
                        SET last_processed_signal_ts = :max_ts
                        WHERE config_id = :config_id
                        """
                    ),
                    {"max_ts": max_ts, "config_id": config.config_id},
                )

                # Mark signals as processed
                id_ts_pairs = [(s["id"], s["ts"]) for s in signals]
                self.signal_reader.mark_signals_processed(
                    conn=conn,
                    signal_table=signal_table,
                    signal_ids_and_timestamps=id_ts_pairs,
                )

                conn.commit()

        # Write run log
        self._write_run_log(
            config,
            status="success",
            signals_read=counts["signals_read"],
            orders=counts["orders_generated"],
            fills=counts["fills_processed"],
            skipped=counts["skipped_no_delta"],
        )

        self.logger.info(
            "PaperExecutor: strategy=%s done -- signals=%d orders=%d fills=%d skipped=%d",
            config.config_name,
            counts["signals_read"],
            counts["orders_generated"],
            counts["fills_processed"],
            counts["skipped_no_delta"],
        )
        return counts

    # ------------------------------------------------------------------
    # Per-asset signal processing
    # ------------------------------------------------------------------

    def _process_asset_signal(
        self,
        conn,
        asset_id: int,
        signal: dict,
        config: ExecutorConfig,
        dry_run: bool,
    ) -> dict:
        """
        Signal -> CanonicalOrder -> paper_orders -> orders -> fill -> position.

        Returns a result dict with keys: skipped_no_delta, rejected,
        order_generated, fill_processed.
        """
        # --- price and portfolio value ---
        try:
            current_price = PositionSizer.get_current_price(conn, asset_id)
        except ValueError:
            self.logger.warning(
                "_process_asset_signal: no price for asset_id=%d, skipping", asset_id
            )
            return {"skipped_no_delta": True}

        portfolio_value = PositionSizer.get_portfolio_value(
            conn, config.config_id, config.initial_capital
        )

        # --- GARCH vol for target_vol sizing ---
        garch_vol = None
        if getattr(config, "target_annual_vol", None):
            try:
                blend_result = get_blended_vol(
                    asset_id=asset_id,
                    venue_id=1,  # CMC_AGG default
                    tf="1D",
                    engine=self.engine,
                )
                if blend_result is not None:
                    garch_vol = blend_result["blended_vol"]
                    self.logger.debug(
                        "_process_asset_signal: asset_id=%d garch_vol=%.6f",
                        asset_id,
                        garch_vol,
                    )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "_process_asset_signal: get_blended_vol failed for asset_id=%d: %s",
                    asset_id,
                    exc,
                )

        # --- target position ---
        target_qty = PositionSizer.compute_target_position(
            latest_signal=signal,
            portfolio_value=portfolio_value,
            current_price=current_price,
            config=config,
            garch_vol=garch_vol,
            conn=conn,  # needed for bl_weight BL lookup
            asset_id=asset_id,  # needed for bl_weight BL lookup
        )

        # --- L4 gross_cap scaling (BEFORE RiskEngine gate) ---
        regime_info = self._load_regime_for_asset(conn, asset_id)
        l4_gross_cap = regime_info["gross_cap"]
        if l4_gross_cap < 1.0:
            original_target = target_qty
            target_qty = target_qty * Decimal(str(l4_gross_cap))
            self.logger.info(
                "_process_asset_signal: asset_id=%d L4 gross_cap=%.2f scaling "
                "target_qty %.6f -> %.6f (l4=%s)",
                asset_id,
                l4_gross_cap,
                float(original_target),
                float(target_qty),
                regime_info["l4_label"],
            )

        # --- current position ---
        pos_row = conn.execute(
            text(
                """
                SELECT quantity
                FROM public.positions
                WHERE asset_id = :asset_id
                  AND exchange = :exchange
                  AND strategy_id = :strategy_id
                """
            ),
            {
                "asset_id": asset_id,
                "exchange": config.exchange,
                "strategy_id": config.config_id,
            },
        ).fetchone()
        current_qty = Decimal(str(pos_row.quantity)) if pos_row else Decimal("0")

        # --- delta ---
        delta = compute_order_delta(current_qty, target_qty)

        self.logger.debug(
            "_process_asset_signal: asset_id=%d target=%.6f current=%.6f delta=%.6f",
            asset_id,
            float(target_qty),
            float(current_qty),
            float(delta),
        )

        if abs(delta) < _MIN_ORDER_THRESHOLD:
            self.logger.debug(
                "_process_asset_signal: delta too small (%.8f), skipping asset_id=%d",
                float(delta),
                asset_id,
            )
            return {"skipped_no_delta": True}

        # Risk gate: check order through RiskEngine
        side_for_risk: str = "buy" if delta > 0 else "sell"
        current_position_value = current_qty * current_price
        risk_result = self.risk_engine.check_order(
            order_qty=abs(delta),
            order_side=side_for_risk,
            fill_price=current_price,
            asset_id=asset_id,
            strategy_id=config.config_id,
            current_position_value=current_position_value,
            portfolio_value=portfolio_value,
        )
        if not risk_result.allowed:
            self.logger.info(
                "_process_asset_signal: risk gate blocked order for asset_id=%d: %s",
                asset_id,
                risk_result.blocked_reason,
            )
            return {"skipped_no_delta": True}
        # Use adjusted quantity from risk engine (may be scaled down)
        delta = (
            risk_result.adjusted_quantity
            if delta > 0
            else -risk_result.adjusted_quantity
        )

        # Full regime layers log line -- emitted for every trade decision.
        self.logger.info(
            "_process_asset_signal: asset_id=%d REGIME l0=%s l1=%s l2=%s l4=%s "
            "size_mult=%.3f gross_cap=%.2f | delta=%.6f side=%s",
            asset_id,
            regime_info["l0_label"] or "n/a",
            regime_info["l1_label"] or "n/a",
            regime_info["l2_label"] or "n/a",
            regime_info["l4_label"] or "disabled",
            regime_info["size_mult"],
            l4_gross_cap,
            float(delta),
            "buy" if delta > 0 else "sell",
        )

        if dry_run:
            self.logger.info(
                "[DRY RUN] asset_id=%d side=%s qty=%.6f price=%.2f (no DB writes)",
                asset_id,
                "buy" if delta > 0 else "sell",
                float(abs(delta)),
                float(current_price),
            )
            return {"order_generated": True, "fill_processed": False}

        # --- build canonical order ---
        side: str = "buy" if delta > 0 else "sell"
        order_qty = abs(delta)

        # Derive pair from asset -- use signal entry_price as sanity check only.
        # For paper trading we use a generic USD pair. In production this would
        # come from dim_assets or a routing table.
        pair = signal.get("pair", f"ASSET{asset_id}/USD")

        order = CanonicalOrder(
            pair=pair,
            side=side,  # type: ignore[arg-type]
            order_type="market",
            quantity=float(order_qty),
            asset_id=asset_id,
        )
        # CRITICAL: set signal_id before PaperOrderLogger.log_order so it
        # propagates through paper_orders -> orders -> ParityChecker.
        order.signal_id = config.signal_id

        # --- Phase 1: log to paper_orders ---
        paper_logger = PaperOrderLogger(db_url=str(self.engine.url))
        paper_uuid = paper_logger.log_order(
            order,
            exchange=config.exchange,
            environment=getattr(config, "_environment", "sandbox"),
        )

        # --- Phase 2: promote to orders ---
        environment = getattr(config, "_environment", "sandbox")
        order_id = OrderManager.promote_paper_order(
            self.engine, paper_uuid, environment
        )
        OrderManager.update_order_status(self.engine, order_id, "submitted")

        # --- Phase 3: simulate fill ---
        simulator_cfg = FillSimulatorConfig(
            slippage_mode=getattr(config, "_slippage_mode", "zero"),
            slippage_base_bps=getattr(config, "_slippage_base_bps", 3.0),
            slippage_noise_sigma=getattr(config, "_slippage_noise_sigma", 0.5),
            volume_impact_factor=getattr(config, "_volume_impact_factor", 0.1),
            rejection_rate=getattr(config, "_rejection_rate", 0.0),
            partial_fill_rate=getattr(config, "_partial_fill_rate", 0.0),
            execution_delay_bars=getattr(config, "_execution_delay_bars", 0),
        )
        simulator = FillSimulator(simulator_cfg)
        fill_result = simulator.simulate_fill(order_qty, current_price, side)

        if fill_result is None:
            # Simulated rejection
            OrderManager.update_order_status(
                self.engine, order_id, "rejected", reason="simulated_rejection"
            )
            self.logger.info(
                "_process_asset_signal: simulated rejection for asset_id=%d order_id=%s",
                asset_id,
                order_id,
            )
            return {"order_generated": True, "rejected": True, "fill_processed": False}

        # --- Phase 4: process fill with strategy_id ---
        fill_data = FillData(
            order_id=order_id,
            fill_qty=fill_result.fill_qty,
            fill_price=fill_result.fill_price,
            strategy_id=config.config_id,  # CRITICAL: multi-strategy position isolation
        )
        OrderManager.process_fill(self.engine, fill_data)

        self.logger.info(
            "_process_asset_signal: fill processed -- asset_id=%d side=%s "
            "qty=%s price=%s order_id=%s",
            asset_id,
            side,
            fill_result.fill_qty,
            fill_result.fill_price,
            order_id,
        )
        return {"order_generated": True, "fill_processed": True}

    # ------------------------------------------------------------------
    # Run log
    # ------------------------------------------------------------------

    def _write_run_log(
        self,
        config: ExecutorConfig,
        status: str,
        signals_read: int = 0,
        orders: int = 0,
        fills: int = 0,
        skipped: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """
        Insert an audit row into executor_run_log.

        Includes L4 audit columns (l4_regime, l4_size_mult) sourced from
        self._current_l4_label and self._current_l4_size_mult set during
        run() initialization. Uses getattr with None fallback so this
        method is safe even when called before run() sets those attributes
        (e.g. early-exit stale-signal path).

        Does not raise -- log failures should never crash the executor.
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO public.executor_run_log (
                            run_id, config_ids, status,
                            signals_read, orders_generated, fills_processed,
                            skipped_no_delta, error_message, finished_at,
                            l4_regime, l4_size_mult
                        ) VALUES (
                            :run_id, :config_ids, :status,
                            :signals_read, :orders_generated, :fills_processed,
                            :skipped_no_delta, :error_message, now(),
                            :l4_regime, :l4_size_mult
                        )
                        """
                    ),
                    {
                        "run_id": str(uuid.uuid4()),
                        "config_ids": json.dumps([config.config_id]),
                        "status": status,
                        "signals_read": signals_read,
                        "orders_generated": orders,
                        "fills_processed": fills,
                        "skipped_no_delta": skipped,
                        "error_message": error,
                        "l4_regime": getattr(self, "_current_l4_label", None),
                        "l4_size_mult": getattr(self, "_current_l4_size_mult", None),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "_write_run_log: failed to write run log for config=%s: %s",
                config.config_name,
                exc,
            )

    # ------------------------------------------------------------------
    # Alerting (optional)
    # ------------------------------------------------------------------

    def _try_telegram_alert(self, message: str) -> None:
        """
        Attempt to send a Telegram alert. Failures are logged and swallowed --
        alerting failure must never crash the executor.
        """
        try:
            from ta_lab2.notifications.telegram import send_critical_alert  # noqa: PLC0415

            send_critical_alert("executor", message)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "_try_telegram_alert: alerting unavailable (%s). Message: %s",
                exc,
                message,
            )
