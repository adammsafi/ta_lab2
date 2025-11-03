# Re-export convenient entry points
from .performance import evaluate_signals, position_returns
from .parameter_sweep import grid, random_search
from .feature_eval import corr_matrix, redundancy_report, feature_target_correlations, quick_logit_feature_weights
from .regime_eval import metrics_by_regime, regime_transition_pnl
