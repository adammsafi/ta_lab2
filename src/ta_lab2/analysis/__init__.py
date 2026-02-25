# Re-export convenient entry points

try:
    from ta_lab2.analysis.var_simulator import (  # noqa: F401
        VaRResult,
        compute_var_suite,
        cornish_fisher_var,
        historical_cvar,
        historical_var,
        parametric_var_normal,
        var_to_daily_cap,
    )
except ImportError:
    pass

try:
    from ta_lab2.analysis.stop_simulator import (  # noqa: F401
        STOP_THRESHOLDS,
        TIME_STOP_BARS,
        StopScenarioResult,
        compute_recovery_time,
        simulate_hard_stop,
        simulate_time_stop,
        simulate_trailing_stop,
        sweep_stops,
    )
except ImportError:
    pass
