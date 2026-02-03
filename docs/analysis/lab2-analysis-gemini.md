# `ta_lab2` Codebase Analysis

## 1. Purpose & Logic Flow

The `ta_lab2` package is a Python-based toolkit for technical analysis of financial time-series data, with a clear focus on Bitcoin (`BTC`). It's designed for multi-timeframe analysis, allowing users to resample daily data into various timeframes (weekly, monthly, etc.), compute a rich set of features, define market regimes, generate trading signals, and backtest strategies.

The logic flow is as follows:

1.  **Data Loading**: The process starts by loading OHLCV (Open, High, Low, Close, Volume) data, either from a local CSV file (`run_btc_pipeline`) or a PostgreSQL database (`load_cmc_ohlcv_daily`). The `config.py` module centralizes the configuration, including data paths and database connection strings (via the `TA_LAB2_DB_URL` environment variable).

2.  **Resampling**: The core `resample.py` module provides functions to bin the data by calendar periods (e.g., '1W' for weekly, '1M' for monthly) or by season. This allows for the creation of multiple timeframes from a single daily series.

3.  **Feature Engineering**: The `features` subpackage is responsible for calculating various technical indicators and features. This includes:
    *   **EMAs (Exponential Moving Averages)**: `features/ema.py` calculates EMAs and their first and second derivatives (slope and acceleration).
    *   **Returns**: `features/returns.py` computes both percentage and log returns.
    *   **Volatility**: `features/vol.py` calculates various volatility estimators, including Parkinson, Rogers-Satchell, and Garman-Klass.
    *   **Calendar Features**: `features/calendar.py` expands datetime information into numerous features like day of the week, week of the year, and moon phases (if `astronomy` package is installed).

4.  **Regime Definition**: The `regimes` subpackage uses the computed features to classify the market into different states or "regimes."
    *   `regimes/labels.py` defines functions to label the market trend (e.g., "Up," "Down," "Sideways"), volatility ("Low," "Normal," "High"), and liquidity. These are combined into a composite regime key (e.g., "Up-Normal-Normal").
    *   The labeling is done on multiple timeframes (monthly, weekly, daily, intraday), creating a layered view of the market.

5.  **Policy Resolution**: Based on the active regimes across different timeframes, `regimes/resolver.py` determines a "policy" for trading. The `resolve_policy_from_table` function uses a predefined mapping (in `DEFAULT_POLICY_TABLE` or a user-provided YAML file) to translate a set of regime labels into a `TightenOnlyPolicy` object. This policy dictates parameters like position size multiplier (`size_mult`), stop-loss multiplier (`stop_mult`), and allowed trade setups. The "tighten-only" logic ensures that higher-level (longer-term) regimes can only reduce risk, not increase it.

6.  **Signal Generation**: The `signals` subpackage generates trading signals based on the features and, optionally, the resolved policy.
    *   `signals/ema_trend.py` provides a classic EMA crossover strategy.
    *   `signals/rsi_mean_revert.py` implements a mean-reversion strategy based on the RSI.
    *   `signals/generator.py` orchestrates the signal generation process.

7.  **Execution and Analysis**: The `pipelines` and `backtests` subpackages consume the generated signals to run backtests and analyze performance.
    *   `pipelines/btc_pipeline.py` is the main entry point for running the entire process on BTC data.
    *   The `cli.py` module provides a command-line interface to run the pipeline, inspect regimes, and interact with the database.

## 2. Strengths

*   **Modular Design**: The separation of concerns into distinct layers (data, features, regimes, signals, backtesting) is a major strength. This makes the codebase easy to understand, maintain, and extend. For example, adding a new indicator only requires a new function in the `features` module, and adding a new strategy is a matter of creating a new signal generation function in the `signals` module.
*   **Multi-Timeframe Analysis**: The package is built from the ground up to support multi-timeframe analysis, which is a sophisticated and powerful approach to market analysis. The use of different "layers" (L0, L1, L2, L3) for regimes is a good implementation of this concept.
*   **Configuration-Driven**: The use of a central `config.py` and YAML files for configuration makes the package flexible and easy to customize without changing the code.
*   **Database Integration**: The package is designed to work with a PostgreSQL database, which is a robust solution for storing and retrieving financial data. The use of SQLAlchemy provides a good abstraction layer for database interactions.
*   **Command-Line Interface**: The `cli.py` module provides a convenient way to run the various components of the system from the command line, which is useful for automation and scripting.
*   **Good Documentation**: The presence of `README.md`, `ARCHITECTURE.md`, and `API_MAP.md` files, along with docstrings in the code, indicates a commitment to good documentation.

## 3. Weaknesses/Code Smells

*   **Tight Coupling to BTC**: While the package is designed to be modular, the main pipeline (`btc_pipeline.py`) is very specific to Bitcoin. It would be beneficial to generalize this to support other assets more easily. The `config.py` also has some BTC-specific defaults.
*   **Inconsistent Naming**: There are some inconsistencies in naming conventions. For example, `run_btc_pipeline` is in both `ta_lab2.pipeline` and `ta_lab2.regimes`. The `API_MAP.md` file also shows some inconsistencies in function and module naming.
*   **Potential for Circular Dependencies**: The `compare.py` module imports from `resample.py` and `features`, while `features` has its own `resample.py`. This could potentially lead to circular dependencies or confusion.
*   **Lack of Unit Tests for Core Logic**: While there are some tests, the test coverage seems low, especially for the core logic in the `features` and `regimes` modules. The existing tests are more like integration tests or smoke tests.
*   **Environment Variable Dependency**: The heavy reliance on the `TA_LAB2_DB_URL` environment variable can make the application less portable and harder to configure for new users. A more robust configuration management system could be beneficial.
*   **God Object Potential**: `config.py` is at risk of becoming a "god object" that knows everything about the system's configuration. Breaking it down into smaller, more focused configuration objects could improve maintainability.
*   **Old/Legacy Code**: The presence of an `old` directory in `src/ta_lab2/features/m_tf` suggests that there is some legacy code that has not been fully deprecated or removed. This can be confusing for new developers.

## 4. Recommended Next Steps

1.  **Refactor for Generality**: Refactor the `btc_pipeline.py` to be more generic, allowing it to work with any asset, not just BTC. This would likely involve moving asset-specific configurations out of the code and into configuration files.
2.  **Improve Test Coverage**: Add more unit tests for the core logic in the `features`, `regimes`, and `signals` modules. This will improve the robustness of the package and make it easier to refactor with confidence.
3.  **Standardize Naming and Structure**: Review and standardize the naming of modules, functions, and classes across the package to improve consistency and reduce confusion.
4.  **Decouple Configuration**: Decouple the configuration from the code as much as possible. Consider using a more advanced configuration library that supports different environments (e.g., development, testing, production) and allows for easier management of secrets.
5.  **Address Potential Circular Dependencies**: Review the import structure of the package to identify and resolve any potential circular dependencies.
6.  **Remove Legacy Code**: Deprecate and remove the legacy code in the `old` directories to simplify the codebase.
7.  **Improve Documentation**: Continue to improve the documentation, especially for the core modules and functions. Adding more examples and tutorials would also be beneficial.
