CREATE TABLE IF NOT EXISTS dim_period (
    period      integer PRIMARY KEY,
    label       text NOT NULL,
    description text
);

INSERT INTO dim_period (period, label, description) VALUES
(10, '10-period', 'Short-term EMA/indicator period'),
(14, '14-period', 'RSI standard'),
(20, '20-period', 'Volatility / Bollinger mid-term'),
(21, '21-period', 'EMA popular choice'),
(30, '30-period', 'Monthly approximation'),
(50, '50-period', 'Medium-term trend'),
(100, '100-period', 'Longer trend'),
(200, '200-period', 'Major trend / market regime'),
(252, '252-period', '1-year trading days'),
(365, '365-period', '1-year calendar days')
ON CONFLICT (period) DO NOTHING;
