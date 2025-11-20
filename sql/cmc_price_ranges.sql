INSERT INTO cmc_price_ranges (asset_id, low_min, low_max, high_min, high_max, note)
VALUES
    (1,     0.01, 200000,   100,  500000,  'BTC sanity bounds'),
    (1027,  0.01, 10000,    1,    100000,  'ETH sanity bounds'),
    (52,    0.0001, 10,     0.01,  1000,   'XRP sanity bounds'),
    (1839,  0.01,  5000,    1,    50000,   'BNB sanity bounds'),
    (1975,  0.001, 1000,    0.1,  100000,  'LINK sanity bounds'),
    (5426,  0.1,   1000,    1,    10000,   'SOL sanity bounds'),
    (32196, 0.1,   500,     1,    5000,    'Hyperliquid sanity bounds')
ON CONFLICT (asset_id) DO UPDATE
SET low_min  = EXCLUDED.low_min,
    low_max  = EXCLUDED.low_max,
    high_min = EXCLUDED.high_min,
    high_max = EXCLUDED.high_max,
    note     = EXCLUDED.note;
