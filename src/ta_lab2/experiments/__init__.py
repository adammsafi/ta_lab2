"""ta_lab2.experiments: Feature experimentation framework.

Provides the YAML-driven feature registry and DAG resolver for the
Phase 38 feature experimentation framework.

Public API
----------
FeatureRegistry:
    Loads experimental feature definitions from YAML. Expands parameter
    sweeps, validates expressions/dotpaths, computes spec digests, and
    provides lifecycle-filtered listing.

resolve_experiment_dag:
    Resolves topological computation order for features with
    'depends_on' dependencies. Raises graphlib.CycleError on cycles.

ExperimentRunner:
    Core execution engine. Computes experimental features from YAML spec,
    scores with Phase 37 compute_ic(), applies BH correction across all rows,
    and returns results with cost tracking metadata.

Example usage::

    from ta_lab2.experiments import FeatureRegistry, resolve_experiment_dag
    from ta_lab2.experiments.runner import ExperimentRunner

    registry = FeatureRegistry("configs/experiments/features.yaml")
    registry.load()

    # List all experimental features (including sweep variants)
    experimental = registry.list_experimental()

    # Resolve computation order (respects depends_on)
    ordered = resolve_experiment_dag(registry.list_all())

    # Get spec for a single feature
    spec = registry.get_feature("ret_vol_ratio_period5")

    # Run an experiment
    runner = ExperimentRunner(registry, engine)
    result_df = runner.run("vol_ratio_30_7", [1, 2], "1D", train_start, train_end)
"""

from ta_lab2.experiments.dag import resolve_experiment_dag
from ta_lab2.experiments.registry import FeatureRegistry
from ta_lab2.experiments.runner import ExperimentRunner

__all__ = [
    "ExperimentRunner",
    "FeatureRegistry",
    "resolve_experiment_dag",
]
