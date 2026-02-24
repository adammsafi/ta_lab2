"""ta_lab2.experiments: Feature experimentation framework.

Provides the YAML-driven feature registry, DAG resolver, experiment runner,
and promotion pipeline for the Phase 38 feature experimentation framework.

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

FeaturePromoter:
    Orchestrates the experimental-to-promoted lifecycle transition.
    Applies Benjamini-Hochberg correction as a hard gate, writes to
    dim_feature_registry, generates an Alembic migration stub, and
    provides deprecation support.

PromotionRejectedError:
    Raised by FeaturePromoter.promote_feature() when the BH gate
    rejects the feature (all corrected p-values >= alpha).

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

    # Promote a feature after running experiments
    from ta_lab2.experiments import FeaturePromoter, PromotionRejectedError

    promoter = FeaturePromoter(engine, registry)
    try:
        stub_path = promoter.promote_feature("vol_ratio_30_7", confirm=False)
    except PromotionRejectedError as exc:
        print(f"Rejected: {exc.reason}")
"""

from ta_lab2.experiments.dag import resolve_experiment_dag
from ta_lab2.experiments.promoter import FeaturePromoter, PromotionRejectedError
from ta_lab2.experiments.registry import FeatureRegistry
from ta_lab2.experiments.runner import ExperimentRunner

__all__ = [
    "ExperimentRunner",
    "FeaturePromoter",
    "FeatureRegistry",
    "PromotionRejectedError",
    "resolve_experiment_dag",
]
