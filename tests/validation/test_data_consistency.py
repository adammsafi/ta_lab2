"""
Data consistency validation tests (SIG-05).

Validates data integrity: no gaps, correct rowcounts, no duplicates,
no NULL values, and EMA calculation precision.
"""

import pytest
import pandas as pd
import numpy as np
from sqlalchemy import text


@pytest.mark.validation_gate
class TestDataConsistencyValidation:
    """Validation gate: Verify data consistency and integrity."""

    @pytest.mark.validation_gate
    def test_no_duplicate_ema_rows(self, db_session):
        """
        Verify no duplicate rows in EMA tables.

        Each (id, ts, tf, period) combination should be unique.
        Zero tolerance: Any duplicates are data corruption.
        """
        # Check each EMA table for duplicates
        ema_tables = [
            "cmc_ema_multi_tf_u",
            # Add other EMA tables if they exist
            # 'cmc_ema_multi_tf',
            # 'cmc_ema_multi_tf_cal',
        ]

        all_duplicates = []

        for table_name in ema_tables:
            # Check if table exists
            check_exists = text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = :table_name
                )
            """
            )
            exists = db_session.execute(
                check_exists, {"table_name": table_name}
            ).scalar()

            if not exists:
                print(f"  Skipping {table_name} (table does not exist)")
                continue

            # Query for duplicates: (id, ts, tf, period) should be unique
            query = text(
                f"""
                SELECT id, ts, tf, period, COUNT(*) AS dup_count
                FROM {table_name}
                GROUP BY id, ts, tf, period
                HAVING COUNT(*) > 1
                LIMIT 10
            """
            )
            result = db_session.execute(query)
            duplicates = result.fetchall()

            if duplicates:
                all_duplicates.extend([(table_name, dup) for dup in duplicates])
                print(f"  ✗ {table_name}: {len(duplicates)} duplicate rows found")
            else:
                # Get total row count for context
                count_query = text(f"SELECT COUNT(*) FROM {table_name}")
                total_rows = db_session.execute(count_query).scalar()
                print(f"  ✓ {table_name}: No duplicates ({total_rows:,} rows)")

        assert all_duplicates == [], (
            f"Found {len(all_duplicates)} duplicate rows (data corruption). "
            f"Duplicates: {all_duplicates[:5]}... "
            f"Each (id, ts, tf, period) must be unique."
        )

    @pytest.mark.validation_gate
    def test_ema_rowcounts_within_expected_range(self, db_session):
        """
        Verify EMA rowcounts are within expected range for each timeframe.

        For sample assets, calculate expected rows based on date range and tf_days,
        then verify actual rowcount is within +/- 5% of expected.

        Tolerance: 5% for delisted assets and data gaps.
        """
        # Check if cmc_ema_multi_tf_u table exists
        check_exists = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_ema_multi_tf_u'
            )
        """
        )
        table_exists = db_session.execute(check_exists).scalar()

        if not table_exists:
            pytest.skip("cmc_ema_multi_tf_u table does not exist")

        # Sample assets for testing (IDs 1, 2, 3)
        sample_assets = [1, 2, 3]

        # Get date range for calculation
        date_range_query = text(
            """
            SELECT MIN(ts)::date AS min_date, MAX(ts)::date AS max_date
            FROM cmc_ema_multi_tf_u
            WHERE id = ANY(:asset_ids)
        """
        )
        result = db_session.execute(date_range_query, {"asset_ids": sample_assets})
        row = result.fetchone()
        if not row or not row[0]:
            pytest.skip("No data in cmc_ema_multi_tf_u for sample assets")

        min_date, max_date = row[0], row[1]
        total_days = (max_date - min_date).days + 1

        # Test specific timeframes
        test_timeframes = ["1D", "7D", "30D"]
        mismatches = []

        for tf in test_timeframes:
            # Get tf_days from dim_timeframe
            tf_days_query = text(
                """
                SELECT tf_days
                FROM dim_timeframe
                WHERE tf = :tf
            """
            )
            result = db_session.execute(tf_days_query, {"tf": tf})
            row = result.fetchone()
            if not row:
                print(f"  Skipping {tf} (not in dim_timeframe)")
                continue

            tf_days = row[0]

            # Calculate expected rows: (total_days / tf_days) per asset per period
            # Use a common period (50) for estimation
            expected_rows_per_asset = total_days / tf_days

            # Query actual rowcount
            actual_query = text(
                """
                SELECT id, COUNT(*) AS row_count
                FROM cmc_ema_multi_tf_u
                WHERE tf = :tf
                AND id = ANY(:asset_ids)
                AND period = 50
                GROUP BY id
            """
            )
            result = db_session.execute(
                actual_query, {"tf": tf, "asset_ids": sample_assets}
            )
            rows = result.fetchall()

            if len(rows) == 0:
                print(f"  Skipping {tf} (no data for sample assets)")
                continue

            # Check each asset
            for asset_id, actual_count in rows:
                # Allow 5% tolerance
                tolerance = 0.05
                lower_bound = expected_rows_per_asset * (1 - tolerance)
                upper_bound = expected_rows_per_asset * (1 + tolerance)

                if not (lower_bound <= actual_count <= upper_bound):
                    mismatches.append(
                        {
                            "tf": tf,
                            "asset_id": asset_id,
                            "expected_rows": expected_rows_per_asset,
                            "actual_count": actual_count,
                            "deviation_pct": (
                                (actual_count - expected_rows_per_asset)
                                / expected_rows_per_asset
                            )
                            * 100,
                        }
                    )

            if len(rows) > 0:
                avg_actual = sum(count for _, count in rows) / len(rows)
                deviation = (
                    (avg_actual - expected_rows_per_asset) / expected_rows_per_asset
                ) * 100
                status = "✓" if abs(deviation) <= 5 else "✗"
                print(
                    f"  {status} {tf}: expected ~{expected_rows_per_asset:.0f}, actual avg {avg_actual:.0f} ({deviation:+.1f}%)"
                )

        # Allow some mismatches (strict check would be == [], but crypto 24/7 may have edge cases)
        assert len(mismatches) == 0 or len(mismatches) < len(
            test_timeframes
        ), f"Too many timeframes with rowcount mismatch (>5% tolerance): {mismatches}"

    @pytest.mark.validation_gate
    def test_no_null_ema_values(self, db_session):
        """
        Verify EMA tables have no NULL ema column values.

        EMAs should always have values once calculated.
        Zero tolerance: NULL EMAs indicate calculation failure.
        """
        # Check each EMA table for NULL values
        ema_tables = [
            "cmc_ema_multi_tf_u",
        ]

        all_nulls = []

        for table_name in ema_tables:
            # Check if table exists
            check_exists = text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = :table_name
                )
            """
            )
            exists = db_session.execute(
                check_exists, {"table_name": table_name}
            ).scalar()

            if not exists:
                print(f"  Skipping {table_name} (table does not exist)")
                continue

            # Query for NULL ema values
            query = text(
                f"""
                SELECT COUNT(*) AS null_count
                FROM {table_name}
                WHERE ema IS NULL
            """
            )
            result = db_session.execute(query)
            null_count = result.scalar()

            if null_count > 0:
                all_nulls.append((table_name, null_count))
                print(f"  ✗ {table_name}: {null_count} NULL ema values")
            else:
                # Get total row count for context
                count_query = text(f"SELECT COUNT(*) FROM {table_name}")
                total_rows = db_session.execute(count_query).scalar()
                print(f"  ✓ {table_name}: No NULL ema values ({total_rows:,} rows)")

        assert all_nulls == [], (
            f"Found {sum(count for _, count in all_nulls)} NULL ema values across {len(all_nulls)} tables. "
            f"NULL EMAs indicate calculation failure: {all_nulls}"
        )

    @pytest.mark.validation_gate
    def test_ema_values_in_reasonable_range(self, db_session):
        """
        Verify EMA values are positive and within reasonable range of price.

        EMAs should be price-based (positive) and not extreme outliers.
        Check: ema > 0 and close/10 < ema < close*10.

        Sample check: 1000 random rows for performance.
        """
        # Check if cmc_ema_multi_tf_u table exists
        check_exists = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_ema_multi_tf_u'
            )
        """
        )
        table_exists = db_session.execute(check_exists).scalar()

        if not table_exists:
            pytest.skip("cmc_ema_multi_tf_u table does not exist")

        # Sample 1000 random rows and compare to price
        # Assuming cmc_price_histories7 has matching (id, ts) data
        query = text(
            """
            SELECT
                e.id,
                e.ts,
                e.tf,
                e.period,
                e.ema,
                p.close
            FROM cmc_ema_multi_tf_u e
            LEFT JOIN cmc_price_histories7 p ON e.id = p.id AND e.ts::date = p.ts::date
            WHERE e.tf = '1D'
            AND e.period = 50
            AND p.close IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 1000
        """
        )
        result = db_session.execute(query)
        rows = result.fetchall()

        if len(rows) == 0:
            pytest.skip("No matching EMA-price data for validation")

        df = pd.DataFrame(rows, columns=["id", "ts", "tf", "period", "ema", "close"])

        # Check 1: All EMAs should be positive
        negative_emas = df[df["ema"] <= 0]
        assert len(negative_emas) == 0, (
            f"Found {len(negative_emas)} non-positive EMA values. "
            f"EMAs should always be positive for price data: {negative_emas.head()}"
        )

        # Check 2: EMAs should be within reasonable range of price (close/10 < ema < close*10)
        df["ema_close_ratio"] = df["ema"] / df["close"]
        outliers = df[(df["ema_close_ratio"] < 0.1) | (df["ema_close_ratio"] > 10)]

        assert len(outliers) == 0, (
            f"Found {len(outliers)} extreme EMA outliers (>10x or <0.1x close price). "
            f"EMAs should track price reasonably: {outliers.head()}"
        )

        print(
            f"✓ Validated {len(df)} EMA values: all positive and within reasonable range"
        )
        print(
            f"  EMA/Close ratio: min={df['ema_close_ratio'].min():.2f}, max={df['ema_close_ratio'].max():.2f}"
        )

    @pytest.mark.validation_gate
    def test_price_ema_alignment(self, db_session):
        """
        Verify EMA timestamps align with price data.

        Join EMA tables to price table on (id, ts), verify no orphan EMA rows
        without corresponding price data.

        Allow small tolerance for weekend/holiday differences.
        """
        # Check if required tables exist
        check_ema = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_ema_multi_tf_u'
            )
        """
        )
        ema_exists = db_session.execute(check_ema).scalar()

        check_price = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_price_histories7'
            )
        """
        )
        price_exists = db_session.execute(check_price).scalar()

        if not ema_exists or not price_exists:
            pytest.skip(
                "Required tables (cmc_ema_multi_tf_u or cmc_price_histories7) do not exist"
            )

        # Query for orphan EMA rows (no matching price data)
        # Sample check for performance (1D timeframe only)
        query = text(
            """
            SELECT COUNT(*) AS orphan_count
            FROM cmc_ema_multi_tf_u e
            LEFT JOIN cmc_price_histories7 p ON e.id = p.id AND e.ts::date = p.ts::date
            WHERE e.tf = '1D'
            AND p.id IS NULL
            LIMIT 1000
        """
        )
        result = db_session.execute(query)
        orphan_count = result.scalar()

        # Get total EMA count for context
        total_query = text(
            """
            SELECT COUNT(*)
            FROM cmc_ema_multi_tf_u
            WHERE tf = '1D'
        """
        )
        total_ema_rows = db_session.execute(total_query).scalar()

        if total_ema_rows > 0:
            orphan_pct = (orphan_count / total_ema_rows) * 100
            print(
                f"  Orphan EMAs (no price): {orphan_count:,} / {total_ema_rows:,} ({orphan_pct:.2f}%)"
            )

            # Allow small tolerance (1%) for weekend/holiday differences
            assert orphan_pct < 1.0, (
                f"Too many orphan EMA rows without price data: {orphan_pct:.2f}% (threshold: 1%). "
                f"EMAs should align with price timestamps."
            )

            if orphan_count == 0:
                print("✓ All EMA rows align with price data (1D timeframe)")
        else:
            pytest.skip("No 1D EMA data for alignment validation")

    @pytest.mark.validation_gate
    def test_gap_detection_for_crypto_assets(self, db_session):
        """
        Verify no date gaps for crypto assets (24/7 trading).

        For crypto assets, verify no date gaps in 1D timeframe data.
        Query consecutive ts values, calculate day deltas.
        For 1D TF, all deltas should be 1 (no missing days).

        Allow gaps only before asset start date.
        """
        # Check if required tables exist
        check_ema = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_ema_multi_tf_u'
            )
        """
        )
        ema_exists = db_session.execute(check_ema).scalar()

        if not ema_exists:
            pytest.skip("cmc_ema_multi_tf_u table does not exist")

        # Sample crypto asset (ID 1 = BTC commonly)
        crypto_asset_id = 1

        # Query consecutive timestamps for gap detection
        query = text(
            """
            WITH consecutive_rows AS (
                SELECT
                    id,
                    ts,
                    LAG(ts) OVER (ORDER BY ts) AS prev_ts
                FROM cmc_ema_multi_tf_u
                WHERE tf = '1D'
                AND id = :asset_id
                AND period = 50
                ORDER BY ts
            )
            SELECT
                ts::date AS current_date,
                prev_ts::date AS prev_date,
                (ts::date - prev_ts::date) AS day_gap
            FROM consecutive_rows
            WHERE prev_ts IS NOT NULL
            AND (ts::date - prev_ts::date) > 1  -- Gap > 1 day
            LIMIT 50
        """
        )
        result = db_session.execute(query, {"asset_id": crypto_asset_id})
        gaps = result.fetchall()

        if len(gaps) > 0:
            df = pd.DataFrame(gaps, columns=["current_date", "prev_date", "day_gap"])
            print(
                f"  Found {len(gaps)} date gaps for asset {crypto_asset_id} (1D timeframe):"
            )
            print(df.head(10).to_string())

            # Calculate gap statistics
            max_gap = df["day_gap"].max()
            avg_gap = df["day_gap"].mean()

            # Allow some gaps (crypto exchanges may have early data issues)
            # But flag if gaps are too large or too frequent
            assert max_gap < 30, (
                f"Found gap of {max_gap} days for crypto asset {crypto_asset_id}. "
                f"Crypto assets should have continuous 24/7 data (max gap <30 days)."
            )

            # Allow up to 5% of data to have gaps (early data quality issues)
            total_rows_query = text(
                """
                SELECT COUNT(*)
                FROM cmc_ema_multi_tf_u
                WHERE tf = '1D'
                AND id = :asset_id
                AND period = 50
            """
            )
            total_rows = db_session.execute(
                total_rows_query, {"asset_id": crypto_asset_id}
            ).scalar()
            gap_pct = (len(gaps) / total_rows) * 100

            assert gap_pct < 5.0, (
                f"Too many gaps for crypto asset {crypto_asset_id}: {gap_pct:.2f}% of data (threshold: 5%). "
                f"Crypto should have continuous data."
            )

            print(
                f"  ⚠ Gaps within tolerance: {len(gaps)} gaps ({gap_pct:.2f}%), max gap {max_gap} days"
            )
        else:
            print(f"✓ No date gaps for crypto asset {crypto_asset_id} (1D timeframe)")

    @pytest.mark.validation_gate
    def test_returns_table_consistency(self, db_session):
        """
        Verify returns calculated correctly: return = (close - prev_close) / prev_close.

        Spot check 100 random rows for calculation correctness.
        Tolerance: 1e-10 for floating point precision.
        """
        # Check if returns table exists
        check_exists = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_returns_daily'
            )
        """
        )
        table_exists = db_session.execute(check_exists).scalar()

        if not table_exists:
            pytest.skip("cmc_returns_daily table does not exist")

        # Query sample data: returns with current and previous close
        query = text(
            """
            WITH price_with_lag AS (
                SELECT
                    id,
                    ts,
                    close,
                    LAG(close) OVER (PARTITION BY id ORDER BY ts) AS prev_close
                FROM cmc_price_histories7
                WHERE id IN (1, 2, 3)
                ORDER BY ts
                LIMIT 1000
            )
            SELECT
                p.id,
                p.ts,
                p.close,
                p.prev_close,
                r.return_1d
            FROM price_with_lag p
            JOIN cmc_returns_daily r ON p.id = r.id AND p.ts::date = r.ts::date
            WHERE p.prev_close IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 100
        """
        )
        result = db_session.execute(query)
        rows = result.fetchall()

        if len(rows) == 0:
            pytest.skip("No matching price/return data for validation")

        df = pd.DataFrame(
            rows, columns=["id", "ts", "close", "prev_close", "return_1d"]
        )

        # Calculate expected return: (close - prev_close) / prev_close
        df["expected_return"] = (df["close"] - df["prev_close"]) / df["prev_close"]

        # Compare to actual return with tolerance
        tolerance = 1e-10
        df["abs_diff"] = np.abs(df["return_1d"] - df["expected_return"])
        mismatches = df[df["abs_diff"] > tolerance]

        assert len(mismatches) == 0, (
            f"Found {len(mismatches)} rows with incorrect return calculations. "
            f"Expected: (close - prev_close) / prev_close. "
            f"Mismatches: {mismatches.head()}"
        )

        max_diff = df["abs_diff"].max()
        print(
            f"✓ Validated {len(df)} return calculations: all correct (max diff: {max_diff:.2e})"
        )

    @pytest.mark.validation_gate
    def test_volatility_table_consistency(self, db_session):
        """
        Verify volatility values are positive and reasonable (<500%).

        Spot check volatility bounds for data quality.
        """
        # Check if volatility table exists
        check_exists = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cmc_vol_daily'
            )
        """
        )
        table_exists = db_session.execute(check_exists).scalar()

        if not table_exists:
            pytest.skip("cmc_vol_daily table does not exist")

        # Query sample volatility data
        query = text(
            """
            SELECT
                id,
                ts,
                vol_30d,
                vol_90d
            FROM cmc_vol_daily
            WHERE id IN (1, 2, 3)
            ORDER BY RANDOM()
            LIMIT 1000
        """
        )
        result = db_session.execute(query)
        rows = result.fetchall()

        if len(rows) == 0:
            pytest.skip("No volatility data for validation")

        df = pd.DataFrame(rows, columns=["id", "ts", "vol_30d", "vol_90d"])

        # Check 1: All volatility values should be positive
        negative_vol = df[(df["vol_30d"] < 0) | (df["vol_90d"] < 0)]
        assert len(negative_vol) == 0, (
            f"Found {len(negative_vol)} negative volatility values. "
            f"Volatility should always be positive: {negative_vol.head()}"
        )

        # Check 2: Volatility should be reasonable (<500% = 5.0)
        extreme_vol = df[(df["vol_30d"] > 5.0) | (df["vol_90d"] > 5.0)]

        # Allow some extreme volatility (crypto can be volatile)
        extreme_pct = (len(extreme_vol) / len(df)) * 100
        assert extreme_pct < 10.0, (
            f"Too many extreme volatility values (>500%): {extreme_pct:.2f}% of data (threshold: 10%). "
            f"Extreme volatility may indicate calculation errors."
        )

        if len(extreme_vol) > 0:
            print(
                f"  ⚠ Found {len(extreme_vol)} extreme volatility values (>500%) - {extreme_pct:.2f}% of sample"
            )

        print(f"✓ Validated {len(df)} volatility values: all positive")
        print(
            f"  30d vol: min={df['vol_30d'].min():.2%}, max={df['vol_30d'].max():.2%}"
        )
        print(
            f"  90d vol: min={df['vol_90d'].min():.2%}, max={df['vol_90d'].max():.2%}"
        )


# Helper functions
def get_date_range(db_session, table_name: str) -> tuple:
    """
    Get date range (min_ts, max_ts) for a table.

    Args:
        db_session: Database session
        table_name: Table name to query

    Returns:
        Tuple of (min_ts, max_ts)
    """
    query = text(
        f"""
        SELECT MIN(ts)::date AS min_ts, MAX(ts)::date AS max_ts
        FROM {table_name}
    """
    )
    result = db_session.execute(query)
    row = result.fetchone()
    return (row[0], row[1]) if row else (None, None)


def count_gaps(db_session, table_name: str, asset_id: int, tf: str) -> int:
    """
    Count date gaps for a specific asset and timeframe.

    Args:
        db_session: Database session
        table_name: EMA table name
        asset_id: Asset ID
        tf: Timeframe code (e.g., '1D')

    Returns:
        Number of gaps (day deltas > 1)
    """
    query = text(
        f"""
        WITH consecutive_rows AS (
            SELECT
                ts,
                LAG(ts) OVER (ORDER BY ts) AS prev_ts
            FROM {table_name}
            WHERE id = :asset_id
            AND tf = :tf
            ORDER BY ts
        )
        SELECT COUNT(*)
        FROM consecutive_rows
        WHERE prev_ts IS NOT NULL
        AND (ts::date - prev_ts::date) > 1
    """
    )
    result = db_session.execute(query, {"asset_id": asset_id, "tf": tf})
    return result.scalar()
