"""Integration smoke tests for the executor package."""

import dataclasses
from decimal import Decimal


class TestExecutorPackageImports:
    """Verify all executor package symbols are importable."""

    def test_import_paper_executor(self):
        from ta_lab2.executor import PaperExecutor

        assert PaperExecutor is not None

    def test_import_fill_simulator(self):
        from ta_lab2.executor import FillSimulator, FillSimulatorConfig

        assert FillSimulator is not None
        assert FillSimulatorConfig is not None

    def test_import_fill_result(self):
        from ta_lab2.executor import FillResult

        assert FillResult is not None

    def test_import_signal_reader(self):
        from ta_lab2.executor import SignalReader, StaleSignalError, SIGNAL_TABLE_MAP

        assert SignalReader is not None
        assert issubclass(StaleSignalError, Exception)
        assert "ema_crossover" in SIGNAL_TABLE_MAP

    def test_import_position_sizer(self):
        from ta_lab2.executor import PositionSizer, ExecutorConfig, compute_order_delta

        assert PositionSizer is not None
        assert ExecutorConfig is not None
        assert callable(compute_order_delta)

    def test_import_regime_multipliers(self):
        from ta_lab2.executor import REGIME_MULTIPLIERS

        assert isinstance(REGIME_MULTIPLIERS, dict)
        assert len(REGIME_MULTIPLIERS) > 0

    def test_import_parity_checker(self):
        from ta_lab2.executor import ParityChecker

        assert ParityChecker is not None

    def test_all_exports_present(self):
        import ta_lab2.executor as pkg

        expected = [
            "PaperExecutor",
            "FillSimulator",
            "FillSimulatorConfig",
            "FillResult",
            "SignalReader",
            "StaleSignalError",
            "SIGNAL_TABLE_MAP",
            "PositionSizer",
            "ExecutorConfig",
            "compute_order_delta",
            "REGIME_MULTIPLIERS",
            "ParityChecker",
        ]
        for name in expected:
            assert hasattr(pkg, name), f"Missing export: {name}"


class TestCrossModuleCompatibility:
    """Verify executor modules work together correctly."""

    def test_fill_simulator_config_defaults(self):
        from ta_lab2.executor import FillSimulatorConfig

        config = FillSimulatorConfig()
        # Default is "zero" (backtest parity mode)
        assert config.slippage_mode == "zero"
        assert config.seed == 42

    def test_fill_simulator_zero_mode(self):
        from ta_lab2.executor import FillSimulator, FillSimulatorConfig

        config = FillSimulatorConfig(slippage_mode="zero")
        sim = FillSimulator(config)
        price = sim.compute_fill_price(Decimal("50000"), "buy")
        assert price == Decimal("50000")

    def test_fill_simulator_lognormal_mode_reproducible(self):
        from ta_lab2.executor import FillSimulator, FillSimulatorConfig

        config = FillSimulatorConfig(slippage_mode="lognormal", seed=42)
        sim = FillSimulator(config)
        price = sim.compute_fill_price(Decimal("50000"), "buy")
        # With lognormal mode, buy fill is adverse (higher than base price)
        assert price > Decimal("50000")

    def test_fill_simulator_simulate_fill_returns_fill_result(self):
        from ta_lab2.executor import FillSimulator, FillSimulatorConfig, FillResult

        config = FillSimulatorConfig(slippage_mode="zero", rejection_rate=0.0)
        sim = FillSimulator(config)
        result = sim.simulate_fill(Decimal("0.5"), Decimal("50000"), "buy")
        assert result is not None
        assert isinstance(result, FillResult)
        assert result.fill_qty == Decimal("0.5")

    def test_position_sizer_order_delta(self):
        from ta_lab2.executor import compute_order_delta

        delta = compute_order_delta(Decimal("0"), Decimal("0.2"))
        assert delta == Decimal("0.2")

    def test_position_sizer_order_delta_sell(self):
        from ta_lab2.executor import compute_order_delta

        delta = compute_order_delta(Decimal("0.5"), Decimal("0.0"))
        assert delta == Decimal("-0.5")

    def test_signal_table_map_covers_all_types(self):
        from ta_lab2.executor import SIGNAL_TABLE_MAP

        assert "ema_crossover" in SIGNAL_TABLE_MAP
        assert "rsi_mean_revert" in SIGNAL_TABLE_MAP
        assert "atr_breakout" in SIGNAL_TABLE_MAP

    def test_signal_table_map_values_are_valid_table_names(self):
        from ta_lab2.executor import SIGNAL_TABLE_MAP

        for signal_type, table_name in SIGNAL_TABLE_MAP.items():
            assert table_name.startswith("signals_"), (
                f"{signal_type} maps to unexpected table: {table_name}"
            )

    def test_regime_multipliers_sum(self):
        from ta_lab2.executor import REGIME_MULTIPLIERS

        # bear_high_vol should be 0 (don't trade)
        assert REGIME_MULTIPLIERS["bear_high_vol"] == Decimal("0.0")
        # bull_low_vol should be 1.0 (full size)
        assert REGIME_MULTIPLIERS["bull_low_vol"] == Decimal("1.0")

    def test_regime_multipliers_all_decimal(self):
        from ta_lab2.executor import REGIME_MULTIPLIERS

        for label, mult in REGIME_MULTIPLIERS.items():
            assert isinstance(mult, Decimal), (
                f"REGIME_MULTIPLIERS[{label!r}] is not Decimal"
            )

    def test_executor_config_dataclass(self):
        from ta_lab2.executor import ExecutorConfig

        assert dataclasses.is_dataclass(ExecutorConfig)
        field_names = [f.name for f in dataclasses.fields(ExecutorConfig)]
        assert "config_id" in field_names
        assert "signal_type" in field_names
        assert "sizing_mode" in field_names

    def test_executor_config_instantiation(self):
        from ta_lab2.executor import ExecutorConfig

        cfg = ExecutorConfig(
            config_id=1,
            config_name="test",
            signal_type="ema_crossover",
            signal_id=1,
            exchange="paper",
            sizing_mode="fixed_fraction",
            position_fraction=0.1,
            max_position_fraction=0.5,
            fill_price_mode="bar_close",
            cadence_hours=26.0,
            last_processed_signal_ts=None,
        )
        assert cfg.config_id == 1
        assert cfg.initial_capital == Decimal("100000")

    def test_stale_signal_error_is_exception(self):
        from ta_lab2.executor import StaleSignalError

        err = StaleSignalError("test message")
        assert isinstance(err, Exception)
        assert str(err) == "test message"


class TestCLIEntryPoints:
    """Verify CLI scripts are importable (not runnable without DB)."""

    def test_run_paper_executor_importable(self):
        import ta_lab2.scripts.executor.run_paper_executor  # noqa: F401

    def test_seed_executor_config_importable(self):
        import ta_lab2.scripts.executor.seed_executor_config  # noqa: F401

    def test_run_parity_check_importable(self):
        import ta_lab2.scripts.executor.run_parity_check  # noqa: F401
