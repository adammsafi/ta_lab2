# src/ta_lab2/regimes/policy_loader.py
from __future__ import annotations
from typing import Dict, Any, Optional
from pathlib import Path
import os

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore

# In-code defaults (used if YAML is missing/unavailable)
from .resolver import DEFAULT_POLICY_TABLE

# Reuse your existing root-config path discovery
try:
    # Prefer the packaged shim that points to the real root-level config.py
    from ta_lab2.config import project_root  # type: ignore
except Exception:
    # Fallback: local heuristic
    def project_root() -> Path:
        p = Path(__file__).resolve()
        for parent in [p, *p.parents]:
            if (parent / "pyproject.toml").exists():
                return parent
        return Path(__file__).resolve().parents[2]


def _default_policy_yaml_path() -> Path:
    """
    Default expected location: <repo_root>/configs/regime_policies.yaml
    (next to your existing configs/default.yaml)
    """
    return project_root() / "configs" / "regime_policies.yaml"


def load_policy_table(
    yaml_path: Optional[str | os.PathLike] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Load a policy overlay from YAML and merge it over DEFAULT_POLICY_TABLE.
    - If yaml_path is None, we try <repo_root>/configs/regime_policies.yaml.
    - If the file is missing or PyYAML isn't installed, we return defaults.

    YAML schema:
      rules:
        - match: "Up-Normal-Normal"
          size_mult: 1.0
          stop_mult: 1.5
          orders: "mixed"
          setups: ["breakout", "pullback"]
          gross_cap: 1.0
          pyramids: true
    Matching is substring-based on the regime key, same as DEFAULT_POLICY_TABLE.
    """
    merged = dict(DEFAULT_POLICY_TABLE)

    # Resolve path
    if yaml_path is None:
        candidate = _default_policy_yaml_path()
    else:
        candidate = Path(yaml_path)

    if not candidate.exists() or yaml is None:
        return merged  # silently fall back to defaults

    with candidate.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}

    rules = doc.get("rules", [])
    for rule in rules:
        match = str(rule.get("match", "")).strip()
        if not match:
            continue
        # Only accept known fields for robustness
        entry: Dict[str, Any] = {}
        for k in (
            "size_mult",
            "stop_mult",
            "orders",
            "setups",
            "gross_cap",
            "pyramids",
        ):
            if k in rule and rule[k] is not None:
                entry[k] = rule[k]
        if entry:
            merged[match] = entry
    return merged
