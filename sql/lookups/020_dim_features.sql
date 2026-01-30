-- dim_features: Feature metadata and null handling configuration
--
-- Defines feature types and their null handling strategies for incremental refresh.
-- Used by FeatureStateManager to configure feature pipelines.
--
-- NULL strategies:
--   'skip'         : Skip NULL values, don't interpolate (e.g., returns - gaps in price data)
--   'forward_fill' : Carry forward last good value (e.g., volatility - smooth estimates)
--   'interpolate'  : Linear interpolation (e.g., technical indicators - smooth signals)

CREATE TABLE IF NOT EXISTS public.dim_features (
    feature_type        TEXT PRIMARY KEY,      -- 'returns', 'vol_parkinson', 'vol_gk', 'ta_rsi', 'ta_macd'
    feature_name        TEXT NOT NULL,         -- Human-readable name
    null_strategy       TEXT NOT NULL          -- 'skip', 'forward_fill', 'interpolate'
                        CHECK (null_strategy IN ('skip', 'forward_fill', 'interpolate')),
    min_data_points     INTEGER DEFAULT 1      -- Minimum required for calculation
                        CHECK (min_data_points > 0),
    is_normalized       BOOLEAN DEFAULT FALSE, -- Has z-score column
    description         TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Insert default feature configurations
INSERT INTO public.dim_features
(feature_type, feature_name, null_strategy, min_data_points, is_normalized, description)
VALUES
-- Returns: Skip NULLs - don't interpolate price gaps (preserves actual returns)
('returns', 'Bar-to-Bar Percentage Returns', 'skip', 2,
 FALSE, 'Simple percentage returns between consecutive bars. NULLs preserved to avoid interpolating missing data.'),

-- Volatility (Parkinson): Forward-fill - carry last good value for smooth estimates
('vol_parkinson', 'Parkinson High-Low Volatility', 'forward_fill', 20,
 FALSE, 'Parkinson volatility estimator using high-low range. Forward-fills to smooth gaps.'),

-- Volatility (Garman-Klass): Forward-fill - carry last good value
('vol_gk', 'Garman-Klass OHLC Volatility', 'forward_fill', 20,
 FALSE, 'Garman-Klass volatility estimator using full OHLC range. Forward-fills to smooth gaps.'),

-- RSI: Interpolate - smooth technical indicator signals
('ta_rsi', 'Relative Strength Index', 'interpolate', 14,
 FALSE, 'RSI momentum oscillator (0-100). Interpolates missing values to maintain signal continuity.'),

-- MACD: Interpolate - smooth technical indicator signals
('ta_macd', 'Moving Average Convergence Divergence', 'interpolate', 26,
 FALSE, 'MACD trend-following momentum indicator. Interpolates missing values to maintain signal continuity.')

ON CONFLICT (feature_type) DO NOTHING;
