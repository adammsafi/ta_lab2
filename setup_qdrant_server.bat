@echo off
echo ========================================
echo Setting up Qdrant Server (One-time)
echo ========================================
echo.

REM Stop and remove any existing qdrant container
docker stop qdrant 2>nul
docker rm qdrant 2>nul

echo Starting Qdrant server with auto-restart...
echo.

docker run -d --restart unless-stopped --name qdrant -p 6333:6333 -p 6334:6334 -v "C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\qdrant_data:/qdrant/storage" qdrant/qdrant

if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS! Qdrant server started.
    echo.
    echo Waiting 5 seconds for startup...
    timeout /t 5 /nobreak >nul

    echo.
    echo Testing connection...
    curl -s http://localhost:6333/health

    echo.
    echo.
    echo ========================================
    echo Qdrant Server Running
    echo ========================================
    echo.
    echo API: http://localhost:6333
    echo Dashboard: http://localhost:6333/dashboard
    echo Data: C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\qdrant_data
    echo.
    echo Auto-restart: ENABLED
    echo - Starts automatically with Docker Desktop
    echo - Survives reboots
    echo.
    echo Commands:
    echo - Stop:    docker stop qdrant
    echo - Start:   docker start qdrant
    echo - Status:  docker ps -a
    echo.
    echo Press any key to continue with migration...
    pause
) else (
    echo.
    echo ERROR: Failed to start Qdrant server
    echo.
    echo Make sure Docker Desktop is running
    echo.
    pause
)
