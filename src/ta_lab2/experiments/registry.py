"""FeatureRegistry: YAML-driven experimental feature registry.

Loads feature definitions from a YAML file, validates lifecycle states,
expands parameter sweeps into named variants, and validates expressions
(inline: ast.parse; dotpath: importlib).
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import itertools
import json
from typing import Any

import yaml

# Valid lifecycle states for features
_VALID_LIFECYCLES = {"experimental", "promoted", "deprecated"}


class FeatureRegistry:
    """
    Loads and validates the YAML feature registry.

    Auto-expands parameter sweeps into named variants.
    Validates inline expressions via ast.parse and dotpath
    functions via importlib at load time.

    Example usage::

        registry = FeatureRegistry("configs/experiments/features.yaml")
        registry.load()
        names = registry.list_experimental()
        spec = registry.get_feature("vol_ratio_30_7")
    """

    def __init__(self, yaml_path: str) -> None:
        """
        Parameters
        ----------
        yaml_path:
            Path to the YAML feature registry file (UTF-8 encoded).
        """
        self.yaml_path = yaml_path
        self._features: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load and expand YAML feature definitions.

        Opens the YAML file with UTF-8 encoding, parses all feature entries,
        validates lifecycle states, validates compute expressions/dotpaths,
        and expands parameter sweeps into named variants.

        Raises
        ------
        FileNotFoundError
            If yaml_path does not exist.
        ValueError
            If a feature has an invalid lifecycle, an invalid expression or
            dotpath, or if duplicate feature names are produced after expansion.
        """
        with open(self.yaml_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if raw is None or "features" not in raw:
            return

        self._features = {}
        raw_features: dict[str, dict] = raw.get("features", {})

        for name, spec in raw_features.items():
            lifecycle = spec.get("lifecycle", "experimental")
            if lifecycle not in _VALID_LIFECYCLES:
                raise ValueError(
                    f"Feature '{name}' has invalid lifecycle '{lifecycle}'. "
                    f"Must be one of: {sorted(_VALID_LIFECYCLES)}"
                )

            # Validate compute spec before expansion
            self._validate_compute_spec(name, spec)

            variants = self._expand_params(name, spec)
            for variant in variants:
                vname = variant["name"]
                if vname in self._features:
                    raise ValueError(
                        f"Duplicate feature name after expansion: '{vname}'"
                    )
                self._features[vname] = variant

    def get_feature(self, name: str) -> dict[str, Any]:
        """Return expanded feature spec by name.

        Raises
        ------
        KeyError
            If the feature name is not in the registry.
        """
        return self._features[name]

    def list_experimental(self) -> list[str]:
        """Return names of all features with lifecycle='experimental'."""
        return [
            n
            for n, spec in self._features.items()
            if spec.get("lifecycle") == "experimental"
        ]

    @property
    def features(self) -> dict[str, dict[str, Any]]:
        """Public read-only view of the expanded feature dict (all lifecycles)."""
        return dict(self._features)

    def list_all(self) -> dict[str, dict[str, Any]]:
        """Return the full feature dict (all lifecycles)."""
        return dict(self._features)

    def validate_expression(self, expr: str) -> None:
        """Validate inline expression syntax using ast.parse.

        Parameters
        ----------
        expr:
            Python expression string (will be used with eval()).

        Raises
        ------
        ValueError
            If the expression has a syntax error.
        """
        try:
            ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            raise ValueError(
                f"Invalid inline expression syntax: {exc}\n  Expression: {expr!r}"
            ) from exc

    def validate_dotpath(self, dotpath: str) -> None:
        """Validate a dotpath function reference via importlib.

        The dotpath format is 'module.path:function_name'.

        Parameters
        ----------
        dotpath:
            Dotpath string, e.g. 'ta_lab2.experiments.my_feature:compute'.

        Raises
        ------
        ValueError
            If ':' separator is missing, the module cannot be imported, or the
            function is not found in the module.
        """
        if ":" not in dotpath:
            raise ValueError(
                f"Dotpath must use 'module.path:function_name' format, got: {dotpath!r}"
            )
        module_path, func_name = dotpath.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            raise ValueError(f"Cannot import module '{module_path}': {exc}") from exc
        if not hasattr(mod, func_name):
            raise ValueError(
                f"Function '{func_name}' not found in module '{module_path}'"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_compute_spec(self, name: str, spec: dict) -> None:
        """Validate the compute spec of a single (unexpanded) feature.

        For inline mode: validates each possible expression after param
        substitution. For dotpath mode: validates the dotpath exists.
        """
        compute = spec.get("compute", {})
        mode = compute.get("mode")

        if mode == "inline":
            expr = compute.get("expression", "")
            params = spec.get("params", {})
            if params:
                # Build one representative param combo to validate the template
                keys = list(params.keys())
                values = [(v if isinstance(v, list) else [v]) for v in params.values()]
                # Use first combo for validation
                combo = next(itertools.product(*values))
                variant_params = dict(zip(keys, combo))
                substituted = expr.format(**variant_params)
                self.validate_expression(substituted)
            else:
                self.validate_expression(expr)

        elif mode == "dotpath":
            dotpath = compute.get("function", "")
            self.validate_dotpath(dotpath)

        elif mode is not None:
            raise ValueError(
                f"Feature '{name}' has unknown compute mode: {mode!r}. "
                "Must be 'inline' or 'dotpath'."
            )

    def _expand_params(self, name: str, spec: dict) -> list[dict[str, Any]]:
        """Expand a parameter sweep into individual variant dicts.

        If no 'params' key exists, returns a single entry with the original
        name. Otherwise uses itertools.product to build one variant per
        parameter combination.

        Parameters
        ----------
        name:
            Base feature name from YAML.
        spec:
            Feature spec dict.

        Returns
        -------
        list of dicts, each with 'name' and 'yaml_digest' keys added.
        """
        params = spec.get("params", {})
        if not params:
            return [{"name": name, "yaml_digest": self._digest(spec), **spec}]

        keys = list(params.keys())
        values = [(v if isinstance(v, list) else [v]) for v in params.values()]

        variants: list[dict[str, Any]] = []
        for combo in itertools.product(*values):
            variant_params = dict(zip(keys, combo))
            param_str = "_".join(f"{k}{v}" for k, v in variant_params.items())
            variant_name = f"{name}_{param_str}"

            # Deep-copy the compute section with param substitution for inline
            compute = spec.get("compute", {})
            if compute.get("mode") == "inline":
                substituted_expr = compute["expression"].format(**variant_params)
                new_compute = {**compute, "expression": substituted_expr}
                variant_spec = {
                    **spec,
                    "compute": new_compute,
                    "resolved_params": variant_params,
                }
            else:
                variant_spec = {**spec, "resolved_params": variant_params}

            variant_spec["yaml_digest"] = self._digest(variant_spec)
            variants.append({"name": variant_name, **variant_spec})

        return variants

    def _digest(self, spec: dict) -> str:
        """Compute a short SHA-256 digest of the spec dict.

        Digest changes when any value in the spec changes, enabling
        detection of YAML edits between experiment runs.

        Parameters
        ----------
        spec:
            Feature spec dict (or variant spec).

        Returns
        -------
        First 16 hex characters of the SHA-256 hash.
        """
        content = json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(content).hexdigest()[:16]
