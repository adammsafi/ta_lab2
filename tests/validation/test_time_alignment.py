"""
Time alignment validation tests (SIG-04).

Validates that all EMA calculations use correct timeframes from dim_timeframe
and that dimension tables are properly populated.
"""

import pytest
import pandas as pd
from sqlalchemy import text


@pytest.mark.validation_gate
class TestTimeAlignmentValidation:
    """Validation gate: Verify all calculations use dim_timeframe correctly."""

    @pytest.mark.validation_gate
    def test_dim_timeframe_populated(self, db_session):
        """
        Verify dim_timeframe table is populated with expected number of timeframes.

        We expect at least 50 timeframes (199 total in production).
        Required columns: tf, tf_days, is_calendar, is_canonical.
        """
        # Query dim_timeframe
        query = text("""
            SELECT
                tf,
                tf_days,
                is_calendar,
                is_canonical,
                calendar_scheme,
                allow_partial_start,
                allow_partial_end
            FROM dim_timeframe
        """)
        result = db_session.execute(query)
        rows = result.fetchall()

        # Verify minimum row count (50+)
        assert len(rows) >= 50, (
            f"dim_timeframe should have at least 50 timeframes, found {len(rows)}. "
            f"Run ensure_dim_tables.py to populate dimension tables."
        )

        # Verify required columns are not NULL for most rows
        df = pd.DataFrame(rows, columns=['tf', 'tf_days', 'is_calendar', 'is_canonical',
                                          'calendar_scheme', 'allow_partial_start', 'allow_partial_end'])

        assert df['tf'].notna().sum() == len(df), "All rows must have tf (timeframe code)"
        assert df['tf_days'].notna().sum() == len(df), "All rows must have tf_days"
        assert df['is_calendar'].notna().sum() == len(df), "All rows must have is_calendar flag"
        assert df['is_canonical'].notna().sum() == len(df), "All rows must have is_canonical flag"

        print(f"✓ dim_timeframe populated: {len(rows)} timeframes")

    @pytest.mark.validation_gate
    def test_dim_sessions_populated(self, db_session):
        """
        Verify dim_sessions table is populated with CRYPTO and EQUITY sessions.

        Required: At least CRYPTO (24/7) and EQUITY (trading hours) sessions exist.
        """
        query = text("""
            SELECT
                asset_class,
                region,
                venue,
                session_type,
                timezone,
                session_open_local,
                session_close_local,
                is_24h
            FROM dim_sessions
            ORDER BY asset_class, region
        """)
        result = db_session.execute(query)
        rows = result.fetchall()

        # Verify at least 2 sessions (CRYPTO, EQUITY)
        assert len(rows) >= 2, (
            f"dim_sessions should have at least 2 sessions (CRYPTO, EQUITY), found {len(rows)}. "
            f"Run ensure_dim_tables.py to populate dimension tables."
        )

        # Convert to DataFrame for easier querying
        df = pd.DataFrame(rows, columns=['asset_class', 'region', 'venue', 'session_type',
                                          'timezone', 'session_open_local', 'session_close_local', 'is_24h'])

        # Verify CRYPTO session exists (24/7 trading)
        crypto_sessions = df[df['asset_class'] == 'CRYPTO']
        assert len(crypto_sessions) > 0, "CRYPTO session must exist in dim_sessions"
        assert crypto_sessions.iloc[0]['is_24h'] == True, "CRYPTO session should be marked as 24-hour trading"

        # Verify EQUITY session exists (trading hours)
        equity_sessions = df[df['asset_class'] == 'EQUITY']
        assert len(equity_sessions) > 0, "EQUITY session must exist in dim_sessions"
        assert equity_sessions.iloc[0]['is_24h'] == False, "EQUITY session should not be 24-hour trading"

        print(f"✓ dim_sessions populated: {len(rows)} sessions (CRYPTO: {len(crypto_sessions)}, EQUITY: {len(equity_sessions)})")

    @pytest.mark.validation_gate
    def test_all_ema_tables_reference_valid_timeframes(self, db_session):
        """
        Verify all EMA tables (multi_tf, multi_tf_cal, multi_tf_u) only reference
        timeframes that exist in dim_timeframe.

        Zero tolerance: No orphan timeframes allowed.
        """
        # Check each EMA table for orphan timeframes
        ema_tables = [
            'cmc_ema_multi_tf_u',
            # Add other EMA tables if they exist
            # 'cmc_ema_multi_tf',
            # 'cmc_ema_multi_tf_cal',
        ]

        all_orphans = []

        for table_name in ema_tables:
            # Check if table exists first
            check_exists = text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = :table_name
                )
            """)
            exists = db_session.execute(check_exists, {'table_name': table_name}).scalar()

            if not exists:
                print(f"  Skipping {table_name} (table does not exist)")
                continue

            # Query for orphan timeframes
            query = text(f"""
                SELECT DISTINCT e.tf
                FROM {table_name} e
                LEFT JOIN dim_timeframe d ON e.tf = d.tf
                WHERE d.tf IS NULL
            """)
            result = db_session.execute(query)
            orphan_tfs = [row[0] for row in result.fetchall()]

            if orphan_tfs:
                all_orphans.extend([(table_name, tf) for tf in orphan_tfs])
                print(f"  ✗ {table_name}: {len(orphan_tfs)} orphan timeframes: {orphan_tfs}")
            else:
                print(f"  ✓ {table_name}: All timeframes valid")

        assert all_orphans == [], (
            f"Found {len(all_orphans)} orphan timeframes (not in dim_timeframe): {all_orphans}. "
            f"All EMA calculations must reference valid dim_timeframe entries."
        )

    @pytest.mark.validation_gate
    def test_calendar_emas_use_calendar_timeframes(self, db_session):
        """
        Verify calendar EMA tables only use calendar-aligned timeframes.

        Calendar EMAs (e.g., cmc_ema_multi_tf_cal) should only use timeframes
        where is_calendar = TRUE in dim_timeframe.
        """
        # Check if cmc_ema_multi_tf_cal table exists
        check_exists = text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_ema_multi_tf_cal'
            )
        """)
        table_exists = db_session.execute(check_exists).scalar()

        if not table_exists:
            pytest.skip("cmc_ema_multi_tf_cal table does not exist")

        # Query for non-calendar timeframes in calendar EMA table
        query = text("""
            SELECT DISTINCT e.tf, d.is_calendar
            FROM cmc_ema_multi_tf_cal e
            JOIN dim_timeframe d ON e.tf = d.tf
            WHERE d.is_calendar = FALSE
        """)
        result = db_session.execute(query)
        non_calendar_tfs = [row[0] for row in result.fetchall()]

        assert non_calendar_tfs == [], (
            f"Calendar EMA table should only use calendar timeframes (is_calendar=TRUE), "
            f"but found {len(non_calendar_tfs)} non-calendar timeframes: {non_calendar_tfs}"
        )

        print(f"✓ cmc_ema_multi_tf_cal uses only calendar timeframes")

    @pytest.mark.validation_gate
    def test_trading_emas_use_trading_timeframes(self, db_session):
        """
        Verify trading EMA tables only use trading-day aligned timeframes.

        Trading EMAs (e.g., cmc_ema_multi_tf) should only use timeframes
        where is_calendar = FALSE in dim_timeframe.
        """
        # Check if cmc_ema_multi_tf table exists
        check_exists = text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_ema_multi_tf'
            )
        """)
        table_exists = db_session.execute(check_exists).scalar()

        if not table_exists:
            pytest.skip("cmc_ema_multi_tf table does not exist")

        # Query for calendar timeframes in trading EMA table
        query = text("""
            SELECT DISTINCT e.tf, d.is_calendar
            FROM cmc_ema_multi_tf e
            JOIN dim_timeframe d ON e.tf = d.tf
            WHERE d.is_calendar = TRUE
        """)
        result = db_session.execute(query)
        calendar_tfs = [row[0] for row in result.fetchall()]

        assert calendar_tfs == [], (
            f"Trading EMA table should only use trading timeframes (is_calendar=FALSE), "
            f"but found {len(calendar_tfs)} calendar timeframes: {calendar_tfs}"
        )

        print(f"✓ cmc_ema_multi_tf uses only trading timeframes")

    @pytest.mark.validation_gate
    def test_tf_days_matches_actual_data_cadence(self, db_session):
        """
        Verify tf_days in dim_timeframe matches actual data cadence in EMA tables.

        For sample assets, calculate actual day gaps between consecutive rows
        and compare to tf_days from dim_timeframe.

        Tolerance: 10% for holidays/missing days.
        """
        # Sample assets for testing (IDs 1, 2, 3)
        sample_assets = [1, 2, 3]

        # Check if cmc_ema_multi_tf_u table exists
        check_exists = text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_ema_multi_tf_u'
            )
        """)
        table_exists = db_session.execute(check_exists).scalar()

        if not table_exists:
            pytest.skip("cmc_ema_multi_tf_u table does not exist")

        # Query sample data for specific timeframes (1D, 7D, 30D)
        test_timeframes = ['1D', '7D', '30D']
        mismatches = []

        for tf in test_timeframes:
            # Get expected tf_days from dim_timeframe
            tf_days_query = text("""
                SELECT tf_days
                FROM dim_timeframe
                WHERE tf = :tf
            """)
            result = db_session.execute(tf_days_query, {'tf': tf})
            row = result.fetchone()
            if not row:
                print(f"  Skipping {tf} (not in dim_timeframe)")
                continue

            expected_tf_days = row[0]

            # Sample actual data cadence (consecutive ts gaps)
            cadence_query = text("""
                WITH consecutive_rows AS (
                    SELECT
                        id,
                        ts,
                        LAG(ts) OVER (PARTITION BY id ORDER BY ts) AS prev_ts
                    FROM cmc_ema_multi_tf_u
                    WHERE tf = :tf
                    AND id = ANY(:asset_ids)
                    AND period = 50  -- Use a common period
                )
                SELECT
                    id,
                    EXTRACT(EPOCH FROM (ts - prev_ts)) / 86400.0 AS day_gap
                FROM consecutive_rows
                WHERE prev_ts IS NOT NULL
                LIMIT 100
            """)
            result = db_session.execute(cadence_query, {'tf': tf, 'asset_ids': sample_assets})
            rows = result.fetchall()

            if len(rows) == 0:
                print(f"  Skipping {tf} (no data for sample assets)")
                continue

            # Calculate median day gap (more robust than mean)
            day_gaps = [row[1] for row in rows]
            actual_median_gap = pd.Series(day_gaps).median()

            # Allow 10% tolerance for holidays/missing days
            tolerance = 0.10
            lower_bound = expected_tf_days * (1 - tolerance)
            upper_bound = expected_tf_days * (1 + tolerance)

            if not (lower_bound <= actual_median_gap <= upper_bound):
                mismatches.append({
                    'tf': tf,
                    'expected_tf_days': expected_tf_days,
                    'actual_median_gap': actual_median_gap,
                    'sample_size': len(rows)
                })
                print(f"  ✗ {tf}: expected {expected_tf_days}d, actual {actual_median_gap:.2f}d (n={len(rows)})")
            else:
                print(f"  ✓ {tf}: expected {expected_tf_days}d, actual {actual_median_gap:.2f}d (n={len(rows)})")

        assert mismatches == [], (
            f"Found {len(mismatches)} timeframes with data cadence mismatch (>10% tolerance): "
            f"{mismatches}"
        )
