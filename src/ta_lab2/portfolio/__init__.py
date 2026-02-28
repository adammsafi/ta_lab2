"""Portfolio construction and position sizing.

Modules:
    optimizer       -- MV, CVaR, HRP portfolio optimization wrappers
    black_litterman -- BL allocation with market cap prior and signal views
    bet_sizing      -- Probability-based position scaling
    topk_selector   -- TopkDropout asset selection with turnover control
    rebalancer      -- Time/signal/threshold rebalancing scheduler
    cost_tracker    -- Turnover cost decomposition and tracking
    stop_ladder     -- Multi-tier stop-loss and take-profit exit scaling
"""


def load_portfolio_config(path: str = "configs/portfolio.yaml") -> dict:
    """Load portfolio configuration from YAML file."""
    import yaml
    from pathlib import Path

    with open(Path(path), "r") as f:
        return yaml.safe_load(f)


from ta_lab2.portfolio.optimizer import PortfolioOptimizer  # noqa: E402

__all__ = ["load_portfolio_config", "PortfolioOptimizer"]
