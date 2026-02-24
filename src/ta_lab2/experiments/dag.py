"""DAG resolution for experimental feature dependencies.

Uses Python stdlib graphlib.TopologicalSorter (Python 3.9+) to resolve
the computation order of experimental features that reference each other
via 'depends_on' lists in their YAML spec.
"""

from __future__ import annotations

import graphlib
from typing import Any


def resolve_experiment_dag(features: dict[str, dict[str, Any]]) -> list[str]:
    """Resolve computation order for experimental features with dependencies.

    Builds a dependency graph from each feature's 'depends_on' list,
    then uses graphlib.TopologicalSorter to determine a valid execution
    order (dependencies computed before dependents).

    Dependencies that reference features NOT present in the input dict
    (e.g., promoted features or external tables) are silently filtered out
    of the graph edges -- only intra-registry dependencies affect ordering.

    Parameters
    ----------
    features:
        Mapping of feature_name -> spec dict. Each spec may contain an
        optional 'depends_on' list of other feature names.

    Returns
    -------
    list[str]
        Feature names in topological order (dependencies first).

    Raises
    ------
    graphlib.CycleError
        If a circular dependency is detected in the feature graph.

    Examples
    --------
    Simple case (no dependencies)::

        features = {"feat_a": {}, "feat_b": {}}
        order = resolve_experiment_dag(features)
        # Returns ["feat_a", "feat_b"] (or reversed, both valid)

    With dependency::

        features = {
            "base_vol": {},
            "vol_ratio": {"depends_on": ["base_vol"]},
        }
        order = resolve_experiment_dag(features)
        # "base_vol" always appears before "vol_ratio"
    """
    known_names = set(features.keys())

    # Build dependency graph: {feature_name: set_of_dependencies}
    deps: dict[str, set[str]] = {}
    for name, spec in features.items():
        raw_deps = spec.get("depends_on", [])
        # Only include dependencies that exist in this registry
        # (skip references to promoted/external features)
        intra_deps = {d for d in raw_deps if d in known_names}
        deps[name] = intra_deps

    sorter = graphlib.TopologicalSorter(deps)
    # static_order() raises graphlib.CycleError on circular dependencies
    return list(sorter.static_order())
