"""
Backtest engine that reads signals from database and executes via vectorbt.

This module provides:
1. Loading signals from cmc_signals_* tables
2. Loading price data from cmc_daily_features
3. Running backtests via existing vbt_runner.py infrastructure
4. Extracting comprehensive metrics from vectorbt Portfolio
5. Saving results to cmc_backtest_* tables

All backtests are reproducible via feature hashing and parameter tracking.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Any
import uuid
import logging

import pandas as pd
import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.backtests.vbt_runner import run_vbt_on_split
from ta_lab2.backtests.costs import CostModel
from ta_lab2.backtests.splitters import Split
from ta_lab2.scripts.signals.signal_utils import compute_feature_hash, compute_params_hash

try:
    import vectorbt as vbt
    VBT_VERSION = vbt.__version__
except (ImportError, AttributeError):
    VBT_VERSION = "unknown"

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """
    Results from a single backtest run.

    Contains summary metrics and detailed trade/metric data for database storage.
    """
    run_id: str
    signal_type: str
    signal_id: int
    asset_id: int
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp

    # Summary metrics (denormalized from metrics dict for quick access)
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    trade_count: int

    # Detailed data
    trades_df: pd.DataFrame
    metrics: dict[str, Any]

    # Reproducibility metadata
    cost_model: dict[str, float]
    signal_params_hash: str
    feature_hash: Optional[str]
    signal_version: str
    vbt_version: str


@dataclass
class SignalBacktester:
    """
    Backtest engine for signals stored in database tables.

    Reads signals from cmc_signals_{signal_type} tables and executes backtests
    using vectorbt via the existing vbt_runner.py infrastructure.

    Supports both clean mode (no costs) and realistic mode (with fees/slippage).

    Attributes:
        engine: SQLAlchemy engine for database operations
        cost_model: CostModel with fee_bps, slippage_bps, funding_bps_day
    """
    engine: Engine
    cost_model: CostModel

    def load_signals_as_series(
        self,
        signal_type: str,
        signal_id: int,
        asset_id: int,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
    ) -> tuple[pd.Series, pd.Series]:
        """
        Load signals from database and convert to entry/exit boolean Series.

        Queries closed positions from cmc_signals_{signal_type} table and converts
        them to boolean Series indexed by timestamp for vectorbt compatibility.

        Args:
            signal_type: Signal table suffix ('ema_crossover', 'rsi_mean_revert', 'atr_breakout')
            signal_id: Signal configuration ID from dim_signals
            asset_id: Asset ID to filter
            start_ts: Start timestamp (inclusive)
            end_ts: End timestamp (inclusive)

        Returns:
            Tuple of (entries, exits) where each is a boolean Series indexed by timestamp.
            entries[ts] = True indicates entry signal at that timestamp.
            exits[ts] = True indicates exit signal at that timestamp.
        """
        table = f"cmc_signals_{signal_type}"

        sql = text(f"""
            SELECT entry_ts, exit_ts, direction, entry_price, exit_price
            FROM public.{table}
            WHERE id = :asset_id
              AND signal_id = :signal_id
              AND entry_ts >= :start_ts
              AND entry_ts <= :end_ts
              AND position_state = 'closed'
            ORDER BY entry_ts
        """)

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "asset_id": asset_id,
                    "signal_id": signal_id,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                }
            )
            rows = result.fetchall()

        logger.info(f"Loaded {len(rows)} closed positions for asset {asset_id}, signal {signal_id}")

        # Build complete time index from start to end
        # This ensures we have timestamps for all trading days
        price_df = self.load_prices(asset_id, start_ts, end_ts)
        if price_df.empty:
            # Return empty series if no price data
            empty_idx = pd.DatetimeIndex([])
            return pd.Series([], dtype=bool, index=empty_idx), pd.Series([], dtype=bool, index=empty_idx)

        time_index = price_df.index

        # Initialize boolean series (all False)
        entries = pd.Series(False, index=time_index)
        exits = pd.Series(False, index=time_index)

        # Mark entry and exit timestamps as True
        for row in rows:
            entry_ts = pd.Timestamp(row[0], tz='UTC')
            exit_ts = pd.Timestamp(row[1], tz='UTC') if row[1] else None

            # Set entry if timestamp exists in index
            if entry_ts in entries.index:
                entries.loc[entry_ts] = True

            # Set exit if timestamp exists in index
            if exit_ts and exit_ts in exits.index:
                exits.loc[exit_ts] = True

        logger.debug(f"Entry signals: {entries.sum()}, Exit signals: {exits.sum()}")

        return entries, exits

    def load_prices(
        self,
        asset_id: int,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
    ) -> pd.DataFrame:
        """
        Load price data from cmc_daily_features table.

        Args:
            asset_id: Asset ID to filter
            start_ts: Start timestamp (inclusive)
            end_ts: End timestamp (inclusive)

        Returns:
            DataFrame with 'close' column indexed by 'ts' (timestamp)
        """
        sql = text("""
            SELECT ts, close
            FROM public.cmc_daily_features
            WHERE id = :asset_id
              AND ts >= :start_ts
              AND ts <= :end_ts
            ORDER BY ts
        """)

        with self.engine.connect() as conn:
            df = pd.read_sql(
                sql,
                conn,
                params={
                    "asset_id": asset_id,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                },
                index_col='ts',
                parse_dates=['ts']
            )

        logger.info(f"Loaded {len(df)} price bars for asset {asset_id}")

        return df

    def run_backtest(
        self,
        signal_type: str,
        signal_id: int,
        asset_id: int,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
        clean_mode: bool = False,
    ) -> BacktestResult:
        """
        Run backtest for a single asset and signal configuration.

        Loads signals from database, executes backtest via vectorbt, and computes
        comprehensive metrics.

        Args:
            signal_type: 'ema_crossover', 'rsi_mean_revert', 'atr_breakout'
            signal_id: ID from dim_signals
            asset_id: Asset to backtest
            start_ts: Backtest start date
            end_ts: Backtest end date
            clean_mode: If True, ignore fees/slippage (zero cost model)

        Returns:
            BacktestResult with metrics, trades, and reproducibility metadata

        Raises:
            ValueError: If no price data or signals found
            RuntimeError: If vectorbt execution fails
        """
        logger.info(f"Running backtest: {signal_type}/{signal_id} on asset {asset_id}")
        logger.info(f"  Date range: {start_ts} to {end_ts}")
        logger.info(f"  Clean mode: {clean_mode}")

        # 1. Load signals from database
        entries, exits = self.load_signals_as_series(
            signal_type, signal_id, asset_id, start_ts, end_ts
        )

        if entries.empty:
            raise ValueError(f"No signals found for {signal_type}/{signal_id} on asset {asset_id}")

        # 2. Load prices
        prices = self.load_prices(asset_id, start_ts, end_ts)

        if prices.empty:
            raise ValueError(f"No price data found for asset {asset_id}")

        # 3. Determine cost model
        cost = CostModel() if clean_mode else self.cost_model
        logger.debug(f"Cost model: {cost.describe()}")

        # 4. Run vectorbt backtest
        split = Split("backtest", start_ts, end_ts)

        try:
            result_row = run_vbt_on_split(
                df=prices,
                entries=entries,
                exits=exits,
                size=None,  # Use default sizing from vbt
                cost=cost,
                split=split,
                price_col="close",
                freq_per_year=365,  # Daily data
            )
        except Exception as e:
            logger.error(f"Vectorbt execution failed: {e}")
            raise RuntimeError(f"Backtest execution failed: {e}") from e

        logger.info(f"Backtest complete: {result_row.trades} trades, "
                   f"return={result_row.total_return:.2%}, sharpe={result_row.sharpe:.2f}")

        # 5. Extract detailed trades from vectorbt
        # Rebuild portfolio to extract trade records
        pf = self._build_portfolio(prices, entries, exits, cost, start_ts, end_ts)
        trades_df = self._extract_trades(pf)

        # 6. Compute comprehensive metrics
        metrics = self._compute_comprehensive_metrics(pf, result_row)

        # 7. Load signal params for hashing
        signal_params = self._load_signal_params(signal_id)
        signal_params_hash = compute_params_hash(signal_params)

        # 8. Compute feature hash (optional - may be expensive)
        feature_hash = None
        # Skip feature hash computation for now - can be added later if needed

        # 9. Create result
        return BacktestResult(
            run_id=str(uuid.uuid4()),
            signal_type=signal_type,
            signal_id=signal_id,
            asset_id=asset_id,
            start_ts=start_ts,
            end_ts=end_ts,
            total_return=result_row.total_return,
            sharpe_ratio=result_row.sharpe,
            max_drawdown=result_row.mdd,
            trade_count=result_row.trades,
            trades_df=trades_df,
            metrics=metrics,
            cost_model={
                "fee_bps": cost.fee_bps,
                "slippage_bps": cost.slippage_bps,
                "funding_bps_day": cost.funding_bps_day,
            },
            signal_params_hash=signal_params_hash,
            feature_hash=feature_hash,
            signal_version="v1.0",  # Hardcoded for now
            vbt_version=VBT_VERSION,
        )

    def _build_portfolio(
        self,
        prices: pd.DataFrame,
        entries: pd.Series,
        exits: pd.Series,
        cost: CostModel,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
    ):
        """
        Build vectorbt Portfolio for trade extraction.

        This duplicates some logic from run_vbt_on_split but is needed to
        extract detailed trade information.
        """
        # Slice to window
        d = prices.loc[start_ts:end_ts]
        e_in = entries.loc[start_ts:end_ts].astype(bool)
        e_out = exits.loc[start_ts:end_ts].astype(bool)

        # Next-bar execution (shift signals by 1)
        e_in = e_in.shift(1, fill_value=False).astype(np.bool_)
        e_out = e_out.shift(1, fill_value=False).astype(np.bool_)

        # Build portfolio
        pf = vbt.Portfolio.from_signals(
            d["close"],
            entries=e_in.to_numpy(),
            exits=e_out.to_numpy(),
            size=None,
            **cost.to_vbt_kwargs(),
            init_cash=1_000.0,
            freq="D",
        )

        return pf

    def _extract_trades(self, pf) -> pd.DataFrame:
        """
        Extract trade records from vectorbt Portfolio.

        Converts vectorbt trade records to DataFrame with columns needed for
        cmc_backtest_trades table.

        Returns:
            DataFrame with columns: entry_ts, entry_price, exit_ts, exit_price,
            direction, size, pnl_pct, pnl_dollars, fees_paid, slippage_cost
        """
        if pf.trades.count() == 0:
            # Return empty DataFrame with correct schema
            return pd.DataFrame(columns=[
                'entry_ts', 'entry_price', 'exit_ts', 'exit_price',
                'direction', 'size', 'pnl_pct', 'pnl_dollars',
                'fees_paid', 'slippage_cost'
            ])

        # Extract trade records
        trades = pf.trades.records_readable

        # Map to our schema
        trades_df = pd.DataFrame({
            'entry_ts': pd.to_datetime(trades['Entry Timestamp']).dt.tz_localize('UTC'),
            'entry_price': trades['Entry Price'].astype(float),
            'exit_ts': pd.to_datetime(trades['Exit Timestamp']).dt.tz_localize('UTC'),
            'exit_price': trades['Exit Price'].astype(float),
            'direction': trades['Direction'].map({0: 'long', 1: 'short'}),
            'size': trades['Size'].astype(float),
            'pnl_pct': trades['Return'].astype(float) * 100,  # Convert to percentage
            'pnl_dollars': trades['PnL'].astype(float),
            'fees_paid': trades.get('Fees', 0.0).astype(float) if 'Fees' in trades else 0.0,
            'slippage_cost': 0.0,  # Vectorbt doesn't separate slippage from fees
        })

        return trades_df

    def _load_signal_params(self, signal_id: int) -> dict:
        """Load signal parameters from dim_signals for hashing."""
        sql = text("""
            SELECT params
            FROM public.dim_signals
            WHERE signal_id = :signal_id
        """)

        with self.engine.connect() as conn:
            result = conn.execute(sql, {"signal_id": signal_id})
            row = result.fetchone()

            if not row:
                raise ValueError(f"Signal ID {signal_id} not found in dim_signals")

            return row[0]  # JSONB auto-parsed to dict

    def _compute_comprehensive_metrics(self, pf, result_row) -> dict[str, Any]:
        """
        Extract comprehensive metrics from vectorbt Portfolio.

        Computes all metrics needed for cmc_backtest_metrics table.

        Args:
            pf: vectorbt Portfolio object
            result_row: ResultRow from run_vbt_on_split (contains some pre-computed metrics)

        Returns:
            Dictionary with metric names as keys
        """
        equity = pf.value()
        returns = pf.returns()

        # Basic metrics from result_row
        metrics = {
            'total_return': result_row.total_return,
            'cagr': result_row.cagr,
            'sharpe_ratio': result_row.sharpe,
            'max_drawdown': result_row.mdd,
            'calmar_ratio': result_row.mar,
        }

        # Sortino ratio (downside deviation)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0 and downside_returns.std() != 0:
            sortino = (returns.mean() * np.sqrt(252)) / (downside_returns.std() * np.sqrt(252))
            metrics['sortino_ratio'] = float(sortino)
        else:
            metrics['sortino_ratio'] = None

        # Drawdown duration
        drawdown_series = pf.drawdown()
        # Find longest continuous drawdown period
        is_dd = drawdown_series < 0
        if is_dd.any():
            dd_groups = (is_dd != is_dd.shift()).cumsum()[is_dd]
            if len(dd_groups) > 0:
                max_dd_duration = dd_groups.value_counts().max()
                metrics['max_drawdown_duration_days'] = int(max_dd_duration)
            else:
                metrics['max_drawdown_duration_days'] = None
        else:
            metrics['max_drawdown_duration_days'] = None

        # Trade statistics
        trades = pf.trades
        metrics['trade_count'] = int(trades.count())

        if metrics['trade_count'] > 0:
            # Win rate
            winning_trades = (trades.pnl.values > 0).sum()
            metrics['win_rate'] = float(winning_trades / metrics['trade_count'] * 100)

            # Profit factor
            gross_profit = trades.pnl.values[trades.pnl.values > 0].sum() if (trades.pnl.values > 0).any() else 0
            gross_loss = abs(trades.pnl.values[trades.pnl.values < 0].sum()) if (trades.pnl.values < 0).any() else 0

            if gross_loss > 0:
                metrics['profit_factor'] = float(gross_profit / gross_loss)
            else:
                metrics['profit_factor'] = None

            # Average win/loss
            winning_pnl = trades.pnl.values[trades.pnl.values > 0]
            losing_pnl = trades.pnl.values[trades.pnl.values < 0]

            metrics['avg_win'] = float((winning_pnl / trades.entry_price.values[trades.pnl.values > 0] * 100).mean()) if len(winning_pnl) > 0 else None
            metrics['avg_loss'] = float((losing_pnl / trades.entry_price.values[trades.pnl.values < 0] * 100).mean()) if len(losing_pnl) > 0 else None

            # Average holding period
            durations = (trades.exit_idx.values - trades.entry_idx.values)
            metrics['avg_holding_period_days'] = float(durations.mean())
        else:
            metrics['win_rate'] = None
            metrics['profit_factor'] = None
            metrics['avg_win'] = None
            metrics['avg_loss'] = None
            metrics['avg_holding_period_days'] = None

        # Risk metrics
        if len(returns) > 0:
            # VaR 95% (5th percentile)
            metrics['var_95'] = float(np.percentile(returns, 5))

            # Expected Shortfall (CVaR) - mean of returns below VaR
            var_threshold = metrics['var_95']
            tail_returns = returns[returns <= var_threshold]
            if len(tail_returns) > 0:
                metrics['expected_shortfall'] = float(tail_returns.mean())
            else:
                metrics['expected_shortfall'] = None
        else:
            metrics['var_95'] = None
            metrics['expected_shortfall'] = None

        return metrics

    def save_backtest_results(self, result: BacktestResult) -> str:
        """
        Save backtest run, trades, and metrics to database.

        Uses a single transaction to ensure atomicity. Handles conflicts via
        ON CONFLICT DO UPDATE for reruns with same run_id.

        Args:
            result: BacktestResult from run_backtest()

        Returns:
            run_id (UUID string) for reference
        """
        logger.info(f"Saving backtest results with run_id={result.run_id}")

        with self.engine.begin() as conn:
            # 1. Insert into cmc_backtest_runs
            run_sql = text("""
                INSERT INTO public.cmc_backtest_runs
                    (run_id, signal_type, signal_id, asset_id, start_ts, end_ts,
                     cost_model, signal_params_hash, feature_hash,
                     signal_version, vbt_version, run_timestamp,
                     total_return, sharpe_ratio, max_drawdown, trade_count)
                VALUES
                    (:run_id, :signal_type, :signal_id, :asset_id, :start_ts, :end_ts,
                     :cost_model, :signal_params_hash, :feature_hash,
                     :signal_version, :vbt_version, now(),
                     :total_return, :sharpe_ratio, :max_drawdown, :trade_count)
                ON CONFLICT (run_id) DO UPDATE SET
                    total_return = EXCLUDED.total_return,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    max_drawdown = EXCLUDED.max_drawdown,
                    trade_count = EXCLUDED.trade_count,
                    run_timestamp = now()
            """)

            conn.execute(run_sql, {
                'run_id': result.run_id,
                'signal_type': result.signal_type,
                'signal_id': result.signal_id,
                'asset_id': result.asset_id,
                'start_ts': result.start_ts,
                'end_ts': result.end_ts,
                'cost_model': result.cost_model,  # Dict auto-converted to JSONB
                'signal_params_hash': result.signal_params_hash,
                'feature_hash': result.feature_hash,
                'signal_version': result.signal_version,
                'vbt_version': result.vbt_version,
                'total_return': result.total_return,
                'sharpe_ratio': result.sharpe_ratio,
                'max_drawdown': result.max_drawdown,
                'trade_count': result.trade_count,
            })

            logger.debug(f"Inserted run record: {result.run_id}")

            # 2. Insert trades (batch via DataFrame.to_sql)
            if not result.trades_df.empty:
                trades_to_insert = result.trades_df.copy()
                trades_to_insert['run_id'] = result.run_id

                # Convert timestamps to timezone-aware
                for col in ['entry_ts', 'exit_ts']:
                    if col in trades_to_insert.columns:
                        trades_to_insert[col] = pd.to_datetime(trades_to_insert[col]).dt.tz_localize('UTC', ambiguous='NaT')

                trades_to_insert.to_sql(
                    'cmc_backtest_trades',
                    conn,
                    schema='public',
                    if_exists='append',
                    index=False,
                    method='multi',
                )

                logger.debug(f"Inserted {len(trades_to_insert)} trade records")

            # 3. Insert metrics
            metrics_sql = text("""
                INSERT INTO public.cmc_backtest_metrics
                    (run_id, total_return, cagr, sharpe_ratio, sortino_ratio, calmar_ratio,
                     max_drawdown, max_drawdown_duration_days,
                     trade_count, win_rate, profit_factor, avg_win, avg_loss,
                     avg_holding_period_days, var_95, expected_shortfall)
                VALUES
                    (:run_id, :total_return, :cagr, :sharpe_ratio, :sortino_ratio, :calmar_ratio,
                     :max_drawdown, :max_drawdown_duration_days,
                     :trade_count, :win_rate, :profit_factor, :avg_win, :avg_loss,
                     :avg_holding_period_days, :var_95, :expected_shortfall)
                ON CONFLICT (run_id) DO UPDATE SET
                    total_return = EXCLUDED.total_return,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    sortino_ratio = EXCLUDED.sortino_ratio,
                    calmar_ratio = EXCLUDED.calmar_ratio,
                    max_drawdown = EXCLUDED.max_drawdown,
                    trade_count = EXCLUDED.trade_count,
                    win_rate = EXCLUDED.win_rate,
                    profit_factor = EXCLUDED.profit_factor
            """)

            conn.execute(metrics_sql, {
                'run_id': result.run_id,
                **result.metrics
            })

            logger.debug(f"Inserted metrics record")

        logger.info(f"Backtest results saved successfully: {result.run_id}")
        return result.run_id
