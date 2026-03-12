"""Unit tests for the Phase 38 feature experimentation framework.

Covers:
- FeatureRegistry: YAML loading, param expansion, expression validation,
  duplicate detection, lifecycle filtering, digest changes.
- resolve_experiment_dag: topological order, cycle detection.
- check_bh_gate: noise rejection, signal passing, NaN handling,
  min_pass_rate enforcement.
- ExperimentRunner._compute_feature: inline eval and dotpath dispatch.
- PromotionRejectedError: exception attributes.
- CLI --help: all 3 CLI scripts accept --help with exit code 0.

All tests run without a live database connection.
"""

from __future__ import annotations

import graphlib
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from ta_lab2.experiments import (
    FeatureRegistry,
    FeaturePromoter,
    PromotionRejectedError,
    resolve_experiment_dag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write a features YAML file to tmp_path and return its path."""
    p = tmp_path / "features.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _minimal_yaml(extra_features: str = "") -> str:
    """Return a minimal valid YAML with an optional extra features block."""
    return f"""\
        features:
          base_feature:
            lifecycle: experimental
            description: "Simple inline feature"
            compute:
              mode: inline
              expression: "close * 2"
            inputs:
              - table: price_bars_multi_tf_u
                columns: [close]
            tags: [test]
        {extra_features}
    """


# ---------------------------------------------------------------------------
# FeatureRegistry tests
# ---------------------------------------------------------------------------


class TestFeatureRegistryLoad:
    def test_load_yaml_basic(self, tmp_path: Path) -> None:
        """Load a minimal YAML and verify the feature is parsed correctly."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())
        reg = FeatureRegistry(str(yaml_path))
        reg.load()

        names = list(reg.list_all().keys())
        assert "base_feature" in names
        spec = reg.get_feature("base_feature")
        assert spec["lifecycle"] == "experimental"
        assert spec["compute"]["mode"] == "inline"
        assert spec["compute"]["expression"] == "close * 2"

    def test_expand_params_produces_variants(self, tmp_path: Path) -> None:
        """Param sweep with period: [5, 14] produces 2 named variants."""
        yaml_path = _write_yaml(
            tmp_path,
            """\
            features:
              rsi_sweep:
                lifecycle: experimental
                description: "RSI sweep"
                compute:
                  mode: inline
                  expression: "rsi_{period}"
                params:
                  period: [5, 14]
                inputs:
                  - table: ta_daily
                    columns: [rsi_14]
            """,
        )
        reg = FeatureRegistry(str(yaml_path))
        reg.load()

        names = list(reg.list_all().keys())
        assert "rsi_sweep_period5" in names
        assert "rsi_sweep_period14" in names
        assert len(names) == 2

    def test_expand_params_correct_expression(self, tmp_path: Path) -> None:
        """Each variant has its expression substituted with the correct param value."""
        yaml_path = _write_yaml(
            tmp_path,
            """\
            features:
              vol_sweep:
                lifecycle: experimental
                compute:
                  mode: inline
                  expression: "close.rolling({window}).std()"
                params:
                  window: [7, 30]
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
            """,
        )
        reg = FeatureRegistry(str(yaml_path))
        reg.load()

        spec_7 = reg.get_feature("vol_sweep_window7")
        spec_30 = reg.get_feature("vol_sweep_window30")
        assert "7" in spec_7["compute"]["expression"]
        assert "30" in spec_30["compute"]["expression"]

    def test_validate_inline_expression_valid(self, tmp_path: Path) -> None:
        """A valid pandas expression does not raise."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())
        reg = FeatureRegistry(str(yaml_path))
        # Should not raise
        reg.validate_expression("close * 2 + np.log(close)")

    def test_validate_inline_expression_invalid(self, tmp_path: Path) -> None:
        """A syntax error in an inline expression raises ValueError."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())
        reg = FeatureRegistry(str(yaml_path))
        with pytest.raises(ValueError, match="Invalid inline expression"):
            reg.validate_expression("close *** invalid")

    def test_duplicate_names_raise(self, tmp_path: Path) -> None:
        """Two features that expand to the same name raise ValueError.

        rsi_sweep with params period=[5] expands to 'rsi_sweep_period5'.
        A feature explicitly named 'rsi_sweep_period5' produces the same name.
        The registry must detect this collision and raise ValueError.
        """
        yaml_path = _write_yaml(
            tmp_path,
            """\
            features:
              rsi_sweep:
                lifecycle: experimental
                compute:
                  mode: inline
                  expression: "close"
                params:
                  period: [5]
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
              rsi_sweep_period5:
                lifecycle: experimental
                compute:
                  mode: inline
                  expression: "close * 2"
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
            """,
        )
        reg = FeatureRegistry(str(yaml_path))
        # rsi_sweep expands to 'rsi_sweep_period5', which collides with
        # the explicitly-defined 'rsi_sweep_period5' feature.
        with pytest.raises(ValueError, match="Duplicate feature name"):
            reg.load()

    def test_invalid_lifecycle_raises(self, tmp_path: Path) -> None:
        """A feature with an unknown lifecycle raises ValueError."""
        yaml_path = _write_yaml(
            tmp_path,
            """\
            features:
              bad_lifecycle:
                lifecycle: "invalid"
                compute:
                  mode: inline
                  expression: "close"
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
            """,
        )
        reg = FeatureRegistry(str(yaml_path))
        with pytest.raises(ValueError, match="invalid lifecycle"):
            reg.load()

    def test_list_experimental_filters_correctly(self, tmp_path: Path) -> None:
        """list_experimental returns only features with lifecycle=experimental."""
        yaml_path = _write_yaml(
            tmp_path,
            """\
            features:
              exp_feature:
                lifecycle: experimental
                compute:
                  mode: inline
                  expression: "close"
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
              promoted_feature:
                lifecycle: promoted
                compute:
                  mode: inline
                  expression: "close * 2"
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
              deprecated_feature:
                lifecycle: deprecated
                compute:
                  mode: inline
                  expression: "close / 2"
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
            """,
        )
        reg = FeatureRegistry(str(yaml_path))
        reg.load()

        experimental = reg.list_experimental()
        assert "exp_feature" in experimental
        assert "promoted_feature" not in experimental
        assert "deprecated_feature" not in experimental
        assert len(experimental) == 1

    def test_yaml_digest_changes_when_expression_changes(self, tmp_path: Path) -> None:
        """Changing the expression changes the yaml_digest."""
        yaml1 = _write_yaml(tmp_path, _minimal_yaml())
        reg1 = FeatureRegistry(str(yaml1))
        reg1.load()
        digest1 = reg1.get_feature("base_feature")["yaml_digest"]

        # Write a new YAML with a different expression
        yaml2 = _write_yaml(
            tmp_path,
            """\
            features:
              base_feature:
                lifecycle: experimental
                description: "Different expression"
                compute:
                  mode: inline
                  expression: "close * 3"
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
                tags: [test]
            """,
        )
        reg2 = FeatureRegistry(str(yaml2))
        reg2.load()
        digest2 = reg2.get_feature("base_feature")["yaml_digest"]

        assert digest1 != digest2, "Digest should change when expression changes"

    def test_yaml_digest_stable_for_same_content(self, tmp_path: Path) -> None:
        """Same YAML content produces the same digest on repeated loads."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())

        reg1 = FeatureRegistry(str(yaml_path))
        reg1.load()
        digest1 = reg1.get_feature("base_feature")["yaml_digest"]

        reg2 = FeatureRegistry(str(yaml_path))
        reg2.load()
        digest2 = reg2.get_feature("base_feature")["yaml_digest"]

        assert digest1 == digest2, "Digest should be stable for same content"


# ---------------------------------------------------------------------------
# DAG resolver tests
# ---------------------------------------------------------------------------


class TestResolveExperimentDag:
    def test_dag_no_deps_returns_all(self) -> None:
        """Features with no depends_on are all returned (order may vary)."""
        features = {
            "feat_a": {},
            "feat_b": {},
            "feat_c": {},
        }
        order = resolve_experiment_dag(features)
        assert set(order) == {"feat_a", "feat_b", "feat_c"}
        assert len(order) == 3

    def test_dag_linear_order(self) -> None:
        """A->B->C dependency chain returns A before B before C."""
        features = {
            "feat_a": {},
            "feat_b": {"depends_on": ["feat_a"]},
            "feat_c": {"depends_on": ["feat_b"]},
        }
        order = resolve_experiment_dag(features)
        assert order.index("feat_a") < order.index("feat_b")
        assert order.index("feat_b") < order.index("feat_c")

    def test_dag_cycle_raises_cycle_error(self) -> None:
        """Circular dependency A->B->A raises graphlib.CycleError."""
        features = {
            "feat_a": {"depends_on": ["feat_b"]},
            "feat_b": {"depends_on": ["feat_a"]},
        }
        with pytest.raises(graphlib.CycleError):
            resolve_experiment_dag(features)

    def test_dag_external_deps_filtered(self) -> None:
        """Dependencies referencing features not in the registry are silently ignored."""
        features = {
            "feat_a": {"depends_on": ["external_promoted_feature"]},
        }
        # Should not raise, external dep is filtered
        order = resolve_experiment_dag(features)
        assert "feat_a" in order

    def test_dag_fan_in(self) -> None:
        """Two roots converging to a single consumer: consumer comes last."""
        features = {
            "root_1": {},
            "root_2": {},
            "consumer": {"depends_on": ["root_1", "root_2"]},
        }
        order = resolve_experiment_dag(features)
        assert order.index("root_1") < order.index("consumer")
        assert order.index("root_2") < order.index("consumer")


# ---------------------------------------------------------------------------
# BH gate tests
# ---------------------------------------------------------------------------


class TestBhGate:
    """Tests for FeaturePromoter.check_bh_gate (mocked engine, no DB)."""

    @pytest.fixture()
    def promoter(self) -> FeaturePromoter:
        mock_engine = MagicMock()
        return FeaturePromoter(engine=mock_engine)

    def _make_df(self, p_values: list) -> pd.DataFrame:
        """Build a minimal ic_results DataFrame with the given p-values."""
        return pd.DataFrame({"ic_p_value": p_values})

    def test_bh_gate_rejects_noise(self, promoter: FeaturePromoter) -> None:
        """High p-values (noise) are rejected by the BH gate."""
        df = self._make_df([0.32, 0.45, 0.67])
        passed, enriched_df, reason = promoter.check_bh_gate(df, alpha=0.05)
        assert not passed
        assert "ic_p_value_bh" in enriched_df.columns
        assert "rejected" in reason.lower()

    def test_bh_gate_passes_signal(self, promoter: FeaturePromoter) -> None:
        """Very small p-values (strong signal) pass the BH gate."""
        df = self._make_df([0.001, 0.001, 0.001])
        passed, enriched_df, reason = promoter.check_bh_gate(df, alpha=0.05)
        assert passed
        assert "ic_p_value_bh" in enriched_df.columns
        assert "passed" in reason.lower()
        # At least one BH-adjusted p-value should be below alpha
        sig_count = (enriched_df["ic_p_value_bh"] < 0.05).sum()
        assert sig_count >= 1

    def test_bh_gate_handles_nan_rows(self, promoter: FeaturePromoter) -> None:
        """NaN p-values do not crash; NaN rows get NaN in ic_p_value_bh."""
        df = self._make_df([0.001, float("nan"), 0.001])
        passed, enriched_df, reason = promoter.check_bh_gate(df, alpha=0.05)
        # Should not raise
        assert "ic_p_value_bh" in enriched_df.columns
        # NaN row (index 1) should have NaN in ic_p_value_bh
        assert pd.isna(enriched_df.loc[1, "ic_p_value_bh"])
        # The two valid rows should produce finite BH values
        assert pd.notna(enriched_df.loc[0, "ic_p_value_bh"])
        assert pd.notna(enriched_df.loc[2, "ic_p_value_bh"])

    def test_bh_gate_all_nan_returns_false(self, promoter: FeaturePromoter) -> None:
        """All NaN p-values returns (False, ...) without crashing."""
        df = self._make_df([float("nan"), float("nan")])
        passed, enriched_df, reason = promoter.check_bh_gate(df, alpha=0.05)
        assert not passed
        assert "ic_p_value_bh" in enriched_df.columns
        assert (
            "NaN" in reason or "nan" in reason.lower() or "no valid" in reason.lower()
        )

    def test_bh_gate_min_pass_rate_enforced(self, promoter: FeaturePromoter) -> None:
        """With min_pass_rate=0.5, only 1/3 passing is insufficient."""
        # Use very small first p-value, high others
        df = self._make_df([0.0001, 0.4, 0.5])
        passed, enriched_df, reason = promoter.check_bh_gate(
            df, alpha=0.05, min_pass_rate=0.5
        )
        # 1 out of 3 pass rate (0.33) < 0.5 threshold
        assert not passed

    def test_bh_gate_min_pass_rate_met(self, promoter: FeaturePromoter) -> None:
        """With min_pass_rate=0.5 and 3/3 passing, gate passes."""
        df = self._make_df([0.0001, 0.0001, 0.0001])
        passed, enriched_df, reason = promoter.check_bh_gate(
            df, alpha=0.05, min_pass_rate=0.5
        )
        assert passed


# ---------------------------------------------------------------------------
# ExperimentRunner._compute_feature tests (mock-based, no DB)
# ---------------------------------------------------------------------------


class TestComputeFeature:
    """Tests for ExperimentRunner._compute_feature dispatch logic."""

    @pytest.fixture()
    def runner(self, tmp_path: Path) -> object:
        """Create an ExperimentRunner with a mocked engine and minimal registry."""
        from ta_lab2.experiments.runner import ExperimentRunner

        yaml_path = _write_yaml(
            tmp_path,
            """\
            features:
              dummy_feature:
                lifecycle: experimental
                compute:
                  mode: inline
                  expression: "close * 2"
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
            """,
        )
        reg = FeatureRegistry(str(yaml_path))
        reg.load()
        mock_engine = MagicMock()
        return ExperimentRunner(registry=reg, engine=mock_engine)

    def test_compute_feature_inline(self, runner: object) -> None:
        """Inline expression 'close * 2' returns close doubled."""
        from ta_lab2.experiments.runner import ExperimentRunner

        assert isinstance(runner, ExperimentRunner)

        input_df = pd.DataFrame(
            {"close": [10.0, 20.0, 30.0]},
            index=pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
        )
        spec = {
            "compute": {"mode": "inline", "expression": "close * 2"},
            "resolved_params": {},
        }
        result = runner._compute_feature(spec, input_df)

        assert isinstance(result, pd.Series)
        assert list(result.values) == [20.0, 40.0, 60.0]

    def test_compute_feature_inline_with_params(self, runner: object) -> None:
        """Inline expression with resolved_params (already substituted in expression)."""
        from ta_lab2.experiments.runner import ExperimentRunner

        assert isinstance(runner, ExperimentRunner)

        input_df = pd.DataFrame(
            {"close": [10.0, 20.0, 30.0, 40.0, 50.0]},
            index=pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC"),
        )
        # Expression already has param substituted (as done by _expand_params)
        spec = {
            "compute": {
                "mode": "inline",
                "expression": "close.rolling(3).std()",
            },
            "resolved_params": {"window": 3},
        }
        result = runner._compute_feature(spec, input_df)
        assert isinstance(result, pd.Series)
        # First 2 are NaN (window=3), remaining are non-NaN
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert pd.notna(result.iloc[2])

    def test_compute_feature_dotpath(self, runner: object, tmp_path: Path) -> None:
        """Dotpath mode calls the function with input_df and returns its result."""
        from ta_lab2.experiments.runner import ExperimentRunner

        assert isinstance(runner, ExperimentRunner)

        input_df = pd.DataFrame(
            {"close": [1.0, 2.0, 3.0]},
            index=pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
        )
        expected_series = input_df["close"] * 5

        mock_fn = MagicMock(return_value=expected_series)
        mock_mod = MagicMock()
        mock_mod.my_func = mock_fn

        spec = {
            "compute": {
                "mode": "dotpath",
                "function": "some.module:my_func",
            },
        }

        with patch("importlib.import_module", return_value=mock_mod):
            result = runner._compute_feature(spec, input_df)

        mock_fn.assert_called_once_with(input_df)
        assert isinstance(result, pd.Series)
        pd.testing.assert_series_equal(result, expected_series)

    def test_compute_feature_unknown_mode_raises(self, runner: object) -> None:
        """Unknown compute mode raises ValueError."""
        from ta_lab2.experiments.runner import ExperimentRunner

        assert isinstance(runner, ExperimentRunner)

        input_df = pd.DataFrame(
            {"close": [1.0]},
            index=pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
        )
        spec = {"compute": {"mode": "unknown_mode"}}
        with pytest.raises(ValueError, match="Unknown compute mode"):
            runner._compute_feature(spec, input_df)


# ---------------------------------------------------------------------------
# PromotionRejectedError tests
# ---------------------------------------------------------------------------


class TestPromotionRejectedError:
    def test_error_has_reason_attribute(self) -> None:
        """PromotionRejectedError stores the reason string."""
        bh_df = pd.DataFrame({"ic_p_value": [0.5], "ic_p_value_bh": [0.9]})
        exc = PromotionRejectedError(reason="BH gate rejected: noise", bh_results=bh_df)
        assert exc.reason == "BH gate rejected: noise"

    def test_error_has_bh_results_attribute(self) -> None:
        """PromotionRejectedError stores the bh_results DataFrame."""
        bh_df = pd.DataFrame({"ic_p_value": [0.5], "ic_p_value_bh": [0.9]})
        exc = PromotionRejectedError(reason="Rejected", bh_results=bh_df)
        pd.testing.assert_frame_equal(exc.bh_results, bh_df)

    def test_error_message_includes_reason(self) -> None:
        """str(exc) includes the reason string (passed to super().__init__)."""
        bh_df = pd.DataFrame({"ic_p_value_bh": [0.9]})
        reason = "BH gate rejected: 0/3 combos significant"
        exc = PromotionRejectedError(reason=reason, bh_results=bh_df)
        assert reason in str(exc)

    def test_error_is_exception_subclass(self) -> None:
        """PromotionRejectedError is a subclass of Exception."""
        bh_df = pd.DataFrame()
        exc = PromotionRejectedError(reason="test", bh_results=bh_df)
        assert isinstance(exc, Exception)

    def test_error_can_be_raised_and_caught(self) -> None:
        """PromotionRejectedError can be raised with pytest.raises."""
        bh_df = pd.DataFrame({"ic_p_value_bh": [0.5]})
        with pytest.raises(PromotionRejectedError) as exc_info:
            raise PromotionRejectedError(reason="gate failed", bh_results=bh_df)
        assert exc_info.value.reason == "gate failed"


# ---------------------------------------------------------------------------
# CLI --help tests
# ---------------------------------------------------------------------------


class TestCliHelp:
    """Verify all 3 CLI scripts accept --help with exit code 0."""

    def _run_help(self, module: str) -> subprocess.CompletedProcess:
        """Run a CLI module with --help and return the completed process."""
        return subprocess.run(
            [sys.executable, "-m", module, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_run_experiment_help(self) -> None:
        """run_experiment CLI accepts --help with exit code 0."""
        result = self._run_help("ta_lab2.scripts.experiments.run_experiment")
        assert result.returncode == 0, (
            f"run_experiment --help failed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        # Should print some usage information
        combined = result.stdout + result.stderr
        assert (
            "usage" in combined.lower()
            or "help" in combined.lower()
            or "option" in combined.lower()
        )

    def test_promote_feature_help(self) -> None:
        """promote_feature CLI accepts --help with exit code 0."""
        result = self._run_help("ta_lab2.scripts.experiments.promote_feature")
        assert result.returncode == 0, (
            f"promote_feature --help failed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert (
            "usage" in combined.lower()
            or "help" in combined.lower()
            or "option" in combined.lower()
        )

    def test_purge_experiment_help(self) -> None:
        """purge_experiment CLI accepts --help with exit code 0."""
        result = self._run_help("ta_lab2.scripts.experiments.purge_experiment")
        assert result.returncode == 0, (
            f"purge_experiment --help failed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert (
            "usage" in combined.lower()
            or "help" in combined.lower()
            or "option" in combined.lower()
        )


# ---------------------------------------------------------------------------
# Additional edge-case / coverage tests
# ---------------------------------------------------------------------------


class TestFeatureRegistryEdgeCases:
    def test_empty_yaml_loads_without_error(self, tmp_path: Path) -> None:
        """An empty YAML file (no features key) loads without raising."""
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        reg = FeatureRegistry(str(p))
        reg.load()
        assert reg.list_experimental() == []
        assert reg.list_all() == {}

    def test_load_resets_features_on_reload(self, tmp_path: Path) -> None:
        """Calling load() twice resets the internal features dict (no stale entries)."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())
        reg = FeatureRegistry(str(yaml_path))
        reg.load()
        reg.load()  # Second load should produce the same result
        assert len(reg.list_all()) == 1

    def test_get_feature_missing_raises_key_error(self, tmp_path: Path) -> None:
        """get_feature raises KeyError for unknown feature name."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())
        reg = FeatureRegistry(str(yaml_path))
        reg.load()
        with pytest.raises(KeyError):
            reg.get_feature("nonexistent_feature")

    def test_multi_param_sweep_product(self, tmp_path: Path) -> None:
        """Two params with [2, 3] values produce 4 variants (cartesian product)."""
        yaml_path = _write_yaml(
            tmp_path,
            """\
            features:
              multi_sweep:
                lifecycle: experimental
                compute:
                  mode: inline
                  expression: "close.rolling({window}).std() / close.rolling({period}).mean()"
                params:
                  window: [7, 30]
                  period: [14, 60]
                inputs:
                  - table: price_bars_multi_tf_u
                    columns: [close]
            """,
        )
        reg = FeatureRegistry(str(yaml_path))
        reg.load()
        names = list(reg.list_all().keys())
        assert len(names) == 4  # 2 x 2 = 4 combinations

    def test_validate_dotpath_invalid_format_raises(self, tmp_path: Path) -> None:
        """Dotpath without ':' separator raises ValueError."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())
        reg = FeatureRegistry(str(yaml_path))
        with pytest.raises(ValueError, match="Dotpath must use"):
            reg.validate_dotpath("module.without.colon")

    def test_validate_dotpath_missing_module_raises(self, tmp_path: Path) -> None:
        """Dotpath with nonexistent module raises ValueError."""
        yaml_path = _write_yaml(tmp_path, _minimal_yaml())
        reg = FeatureRegistry(str(yaml_path))
        with pytest.raises(ValueError, match="Cannot import module"):
            reg.validate_dotpath("nonexistent_module_xyz_abc:my_func")
