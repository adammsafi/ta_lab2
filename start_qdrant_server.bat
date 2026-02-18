@echo off
REM Start Qdrant server using Docker
REM Data persists in: C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\qdrant_data

set QDRANT_DATA_PATH=C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\qdrant_data

echo ========================================
echo Starting Qdrant Server (Docker)
echo ========================================
echo.
echo Data location: %QDRANT_DATA_PATH%
echo API: http://localhost:6333
echo Dashboard: http://localhost:6333/dashboard
echo.

docker run -d ^
  --name qdrant ^
  -p 6333:6333 ^
  -p 6334:6334 ^
  -v "%QDRANT_DATA_PATH%:/qdrant/storage" ^
  qdrant/qdrant

echo.
echo Qdrant server starting...
echo Wait 5 seconds for startup...
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
echo To stop: docker stop qdrant
echo To remove: docker rm qdrant
echo.
