@echo off
REM =====================================================
REM Complete Rebuild - All Bars and EMAs
REM =====================================================
REM This will rebuild everything from scratch
REM =====================================================

echo.
echo =====================================================
echo STEP 1: Drop All Existing Tables
echo =====================================================
echo.

psql -U postgres -d marketdata -f sql\ddl\drop_all_bars_and_emas.sql

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to drop tables
    pause
    exit /b 1
)

echo.
echo =====================================================
echo STEP 2: Recreate Dimension Tables
echo =====================================================
echo.

psql -U postgres -d marketdata -f sql\ddl\create_dim_assets.sql
psql -U postgres -d marketdata -f sql\ddl\create_dim_timeframe.sql
psql -U postgres -d marketdata -f sql\ddl\create_dim_period.sql
psql -U postgres -d marketdata -f sql\ddl\create_ema_alpha_lookup.sql

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to create dimension tables
    pause
    exit /b 1
)

echo.
echo =====================================================
echo STEP 3: Build All Bar Tables (~45 minutes)
echo =====================================================
echo.

python src\ta_lab2\scripts\bars\run_all_bar_builders.py --ids all

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Bar builders failed
    pause
    exit /b 1
)

echo.
echo =====================================================
echo STEP 4: Build All EMA Tables (~2 hours)
echo =====================================================
echo.

python src\ta_lab2\scripts\emas\run_all_ema_refreshes.py --ids all --periods all

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: EMA refreshers failed
    pause
    exit /b 1
)

echo.
echo =====================================================
echo REBUILD COMPLETE!
echo =====================================================
echo.
echo All bar and EMA tables have been rebuilt successfully.
echo.
pause
