-- ==================================================================================
-- Calendar Builder State Tables
-- ==================================================================================
--
-- Design Note: tz column is intentionally NOT part of PRIMARY KEY
--
-- Rationale:
-- - Calendar builders process single timezone per run (--tz CLI flag)
-- - Multiple timezones for same (id, tf) not supported in same state table
-- - tz column is metadata/audit only, not a discriminator
-- - If multi-timezone support needed in future, change PK to (id, tf, tz)
--
-- Current PK: (id, tf)
-- tz column: Tracks which timezone was used for this state entry
--
-- This design is CORRECT for current use case where each builder variant:
-- 1. Processes one timezone per execution
-- 2. Stores timezone metadata for audit/debugging
-- 3. Does not support mixing timezones in incremental refresh
--
-- GAP-M03 (from Phase 21 gap analysis) CLOSED: This is intentional design, not a bug.
-- ==================================================================================


-- ==================================================================================
-- US Calendar Builder (Sunday-start weeks)
-- ==================================================================================

CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_cal_us_state (
    id INTEGER NOT NULL,
    tf TEXT NOT NULL,
    tz TEXT,  -- NOT in PRIMARY KEY - see rationale above
    daily_min_seen TIMESTAMPTZ,
    daily_max_seen TIMESTAMPTZ,
    last_bar_seq INTEGER,
    last_time_close TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tf)
);

COMMENT ON TABLE public.cmc_price_bars_multi_tf_cal_us_state IS
'State tracking for US calendar bar builder (Sunday-start weeks). tz column tracks timezone used but is not part of PK.';

COMMENT ON COLUMN public.cmc_price_bars_multi_tf_cal_us_state.tz IS
'Timezone used for calendar alignment (metadata only, not part of PRIMARY KEY). See table comment for design rationale.';


-- ==================================================================================
-- ISO Calendar Builder (Monday-start weeks)
-- ==================================================================================

CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_cal_iso_state (
    id INTEGER NOT NULL,
    tf TEXT NOT NULL,
    tz TEXT,  -- NOT in PRIMARY KEY - see rationale above
    daily_min_seen TIMESTAMPTZ,
    daily_max_seen TIMESTAMPTZ,
    last_bar_seq INTEGER,
    last_time_close TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tf)
);

COMMENT ON TABLE public.cmc_price_bars_multi_tf_cal_iso_state IS
'State tracking for ISO calendar bar builder (Monday-start weeks). tz column tracks timezone used but is not part of PK.';

COMMENT ON COLUMN public.cmc_price_bars_multi_tf_cal_iso_state.tz IS
'Timezone used for calendar alignment (metadata only, not part of PRIMARY KEY). See table comment for design rationale.';


-- ==================================================================================
-- US Anchor Calendar Builder (Sunday-start, year-anchored)
-- ==================================================================================

CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_cal_anchor_us_state (
    id INTEGER NOT NULL,
    tf TEXT NOT NULL,
    tz TEXT,  -- NOT in PRIMARY KEY - see rationale above
    daily_min_seen TIMESTAMPTZ,
    daily_max_seen TIMESTAMPTZ,
    last_bar_seq INTEGER,
    last_time_close TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tf)
);

COMMENT ON TABLE public.cmc_price_bars_multi_tf_cal_anchor_us_state IS
'State tracking for US anchor calendar bar builder (year-anchored, Sunday-start weeks). tz column tracks timezone used but is not part of PK.';

COMMENT ON COLUMN public.cmc_price_bars_multi_tf_cal_anchor_us_state.tz IS
'Timezone used for calendar alignment (metadata only, not part of PRIMARY KEY). See table comment for design rationale.';


-- ==================================================================================
-- ISO Anchor Calendar Builder (Monday-start, year-anchored)
-- ==================================================================================

CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_cal_anchor_iso_state (
    id INTEGER NOT NULL,
    tf TEXT NOT NULL,
    tz TEXT,  -- NOT in PRIMARY KEY - see rationale above
    daily_min_seen TIMESTAMPTZ,
    daily_max_seen TIMESTAMPTZ,
    last_bar_seq INTEGER,
    last_time_close TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tf)
);

COMMENT ON TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso_state IS
'State tracking for ISO anchor calendar bar builder (year-anchored, Monday-start weeks). tz column tracks timezone used but is not part of PK.';

COMMENT ON COLUMN public.cmc_price_bars_multi_tf_cal_anchor_iso_state.tz IS
'Timezone used for calendar alignment (metadata only, not part of PRIMARY KEY). See table comment for design rationale.';


-- ==================================================================================
-- Migration Notes
-- ==================================================================================
--
-- If multi-timezone support is needed in the future:
--
-- 1. Change PRIMARY KEY to (id, tf, tz) for each state table
-- 2. Update calendar builder code to query state by (id, tf, tz) tuple
-- 3. Add UNIQUE constraint on (id, tf, tz) if needed for safety
-- 4. Consider timezone conversion logic for cross-timezone queries
--
-- Example migration (DO NOT RUN unless multi-timezone support is implemented):
--
-- ALTER TABLE public.cmc_price_bars_multi_tf_cal_us_state DROP CONSTRAINT cmc_price_bars_multi_tf_cal_us_state_pkey;
-- ALTER TABLE public.cmc_price_bars_multi_tf_cal_us_state ADD PRIMARY KEY (id, tf, tz);
--
-- ==================================================================================
