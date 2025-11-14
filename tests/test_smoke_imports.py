def test_import_root_and_key_modules():
    import ta_lab2

    # core
    import ta_lab2.cli
    import ta_lab2.io
    import ta_lab2.resample
    import ta_lab2.compare

    # features
    import ta_lab2.features
    import ta_lab2.features.calendar
    import ta_lab2.features.ema
    import ta_lab2.features.returns
    import ta_lab2.features.vol
    import ta_lab2.features.indicators
    import ta_lab2.features.segments
    import ta_lab2.features.trend
    import ta_lab2.features.resample as feat_resample
    import ta_lab2.features.ensure
    import ta_lab2.features.feature_pack

    # regimes
    import ta_lab2.regimes
    import ta_lab2.regimes.labels
    import ta_lab2.regimes.flips
    import ta_lab2.regimes.comovement
    import ta_lab2.regimes.data_budget
    import ta_lab2.regimes.feature_utils
    import ta_lab2.regimes.policy_loader
    import ta_lab2.regimes.resolver
    import ta_lab2.regimes.proxies
    import ta_lab2.regimes.telemetry
    import ta_lab2.regimes.regime_inspect

    # signals
    import ta_lab2.signals
    import ta_lab2.signals.registry
    import ta_lab2.signals.breakout_atr
    import ta_lab2.signals.ema_trend
    import ta_lab2.signals.rsi_mean_revert
    import ta_lab2.signals.rules
    import ta_lab2.signals.position_sizing
    import ta_lab2.signals.generator

    # backtests
    import ta_lab2.backtests
    import ta_lab2.backtests.btpy_runner
    import ta_lab2.backtests.vbt_runner
    import ta_lab2.backtests.splitters
    import ta_lab2.backtests.metrics
    import ta_lab2.backtests.reports
    import ta_lab2.backtests.costs
    import ta_lab2.backtests.orchestrator

    # analysis
    import ta_lab2.analysis
    import ta_lab2.analysis.performance
    import ta_lab2.analysis.feature_eval
    import ta_lab2.analysis.regime_eval
    import ta_lab2.analysis.parameter_sweep

    # pipelines
    import ta_lab2.pipelines
    import ta_lab2.pipelines.btc_pipeline

    # research
    import ta_lab2.research.queries.opt_cf_ema
    import ta_lab2.research.queries.opt_cf_ema_refine
    import ta_lab2.research.queries.opt_cf_ema_sensitivity
    import ta_lab2.research.queries.opt_cf_generic
    import ta_lab2.research.queries.run_ema_50_100
    import ta_lab2.research.queries.wf_validate_ema

    # viz + utils
    import ta_lab2.viz.all_plots
    import ta_lab2.utils.cache

    # basic sanity assertions (just to silence linters)
    assert ta_lab2 is not None
    assert feat_resample is not None
 