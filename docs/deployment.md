# ta_lab2 Deployment Guide

Version: 0.4.0

This guide covers deploying ta_lab2 in development and production environments, including infrastructure setup, environment configuration, database migrations, and monitoring.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Database Setup](#database-setup)
- [Qdrant Setup (Memory System)](#qdrant-setup-memory-system)
- [Running Services](#running-services)
- [Monitoring & Observability](#monitoring--observability)
- [CI/CD Configuration](#cicd-configuration)
- [Troubleshooting](#troubleshooting)
- [Production Deployment](#production-deployment)

---

## Prerequisites

### Required Software

- **Python**: 3.10+ (3.11+ recommended for TaskGroup support)
- **PostgreSQL**: 14+ (16 recommended for better partitioning support)
- **Git**: For repository management
- **Docker**: (Optional) For Qdrant server mode

### Recommended System Resources

- **CPU**: 4+ cores (for parallel feature computation)
- **RAM**: 8GB+ (16GB recommended for large datasets)
- **Storage**: 50GB+ SSD (depends on historical data volume)
- **Network**: Stable internet for AI API calls (if using orchestrator)

### Operating System Support

- **Linux**: Primary platform (Ubuntu 20.04+, Debian 11+)
- **macOS**: Supported (10.15+)
- **Windows**: Supported (Windows 10+, PowerShell recommended)

---

## Installation

### Basic Installation (ta_lab2 only)

Install the core package without AI orchestrator dependencies:

```bash
# Clone the repository
git clone https://github.com/<your-username>/ta_lab2.git
cd ta_lab2

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install core package
pip install --upgrade pip
pip install -e .
```

### With AI Orchestrator

Install ta_lab2 with AI orchestration capabilities (Claude, ChatGPT, Gemini):

```bash
pip install -e ".[orchestrator]"
```

This installs:
- anthropic>=0.40.0 (Claude)
- openai>=1.50.0 (ChatGPT)
- google-generativeai>=0.8.0 (Gemini)
- mem0ai>=0.1.0 (Memory system)
- chromadb>=0.4.0 (Vector storage)
- fastapi>=0.104.0 (Memory REST API)
- pydantic>=2.0.0 (Validation)
- python-dotenv>=1.0.0 (Environment management)

### Full Development Setup

Install all dependencies including testing and development tools:

```bash
pip install -e ".[all]"
```

This includes:
- All orchestrator dependencies
- pytest>=8.0 (Testing framework)
- pytest-asyncio>=0.21.0 (Async test support)
- pytest-mock>=3.12.0 (Mocking utilities)
- pytest-cov>=4.0.0 (Coverage reporting)
- pytest-benchmark (Performance testing)
- ruff>=0.1.5 (Linting)
- mypy>=1.8 (Type checking)

### Verify Installation

```bash
# Check CLI is available
ta-lab2 --help

# Run smoke tests
pytest -m smoke -q
```

---

## Environment Variables

ta_lab2 uses environment variables for configuration. Create a `.env` file in the project root:

```bash
# Example .env file
cp .env.example .env  # If example exists
```

### Required Variables

| Variable | Required For | Description | Example |
|----------|-------------|-------------|---------|
| `TARGET_DB_URL` | Core | PostgreSQL connection string (primary) | `postgresql://user:pass@localhost:5432/ta_lab2` |
| `TA_LAB2_DB_URL` | Core | Alternative PostgreSQL connection string | Same as TARGET_DB_URL |

**Note**: Either `TARGET_DB_URL` or `TA_LAB2_DB_URL` must be set. `TARGET_DB_URL` takes precedence.

### AI Orchestrator Variables

| Variable | Required For | Description | Example |
|----------|-------------|-------------|---------|
| `OPENAI_API_KEY` | ChatGPT/Embeddings | OpenAI API key | `sk-proj-...` |
| `ANTHROPIC_API_KEY` | Claude | Anthropic API key | `sk-ant-...` |
| `GOOGLE_API_KEY` | Gemini | Google AI API key | `AIza...` |

### Memory System Variables

| Variable | Required For | Description | Example |
|----------|-------------|-------------|---------|
| `QDRANT_SERVER_MODE` | Memory | Enable Qdrant server mode | `true` (default) |
| `QDRANT_URL` | Memory | Qdrant server URL | `http://localhost:6333` |
| `QDRANT_PATH` | Memory | Qdrant local storage path | `./qdrant_data` (embedded mode) |

**Server Mode (Production)**:
- Set `QDRANT_SERVER_MODE=true`
- Requires Qdrant server running (Docker or binary)
- Persistent storage across restarts
- Better performance and reliability

**Embedded Mode (Testing)**:
- Set `QDRANT_SERVER_MODE=false`
- Uses local file storage
- Suitable for testing only
- No server required

### Observability & Alerts Variables

| Variable | Required For | Description | Example |
|----------|-------------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Alerts | Telegram bot token for notifications | `123456:ABC-DEF...` |
| `TELEGRAM_CHAT_ID` | Alerts | Telegram chat ID for alerts | `-1001234567890` |

**Obtaining Telegram Credentials**:

1. Create bot: Talk to [@BotFather](https://t.me/BotFather) on Telegram, use `/newbot` command
2. Get token: BotFather provides token after bot creation
3. Get chat ID: Start chat with your bot, then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find chat ID in JSON response under `message.chat.id`

### Setting Environment Variables

**Linux/macOS**:
```bash
export TARGET_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"
export OPENAI_API_KEY="sk-proj-..."
export QDRANT_SERVER_MODE="true"
```

**Windows (PowerShell)**:
```powershell
$env:TARGET_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"
$env:OPENAI_API_KEY="sk-proj-..."
$env:QDRANT_SERVER_MODE="true"
```

**Windows (Command Prompt)**:
```cmd
set TARGET_DB_URL=postgresql://user:pass@localhost:5432/ta_lab2
set OPENAI_API_KEY=sk-proj-...
set QDRANT_SERVER_MODE=true
```

**Using .env file** (recommended):
```bash
# Install python-dotenv (included in orchestrator dependencies)
pip install python-dotenv

# Create .env file in project root
echo 'TARGET_DB_URL=postgresql://user:pass@localhost:5432/ta_lab2' >> .env
echo 'OPENAI_API_KEY=sk-proj-...' >> .env

# Loads automatically via config.py
```

---

## Database Setup

### 1. Create Database

**Using createdb (recommended)**:
```bash
createdb ta_lab2
```

**Using psql**:
```sql
CREATE DATABASE ta_lab2;
```

**With specific encoding**:
```sql
CREATE DATABASE ta_lab2
  ENCODING 'UTF8'
  LC_COLLATE 'en_US.UTF-8'
  LC_CTYPE 'en_US.UTF-8'
  TEMPLATE template0;
```

### 2. Create Observability Schema

The observability schema holds metrics, traces, and workflow state:

```bash
psql -d ta_lab2 -f sql/ddl/create_observability_schema.sql
```

**Schema includes**:
- `observability.metrics` (month-partitioned)
- `observability.traces`
- `observability.workflow_state`
- Health check functions

### 3. Create Dimension Tables

Dimension tables define timeframes and trading sessions:

```bash
# Ensure dim_timeframe and dim_sessions exist
python -m ta_lab2.scripts.time.ensure_dim_tables
```

**Creates**:
- `dim_timeframe` (199 timeframe definitions: 1D-365D)
- `dim_sessions` (CRYPTO/EQUITY trading sessions)

**Idempotent**: Safe to run multiple times, checks existence before creating.

### 4. Create EMA Tables

EMA tables store multi-timeframe exponential moving averages:

```bash
# Create EMA state tracking
psql -d ta_lab2 -f sql/ddl/create_cmc_ema_refresh_state.sql

# Create unified multi-timeframe EMA table
psql -d ta_lab2 -f sql/ddl/create_cmc_ema_multi_tf_v2.sql
```

**Optional**: Create additional EMA variant tables if using older schemas:
```bash
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf.sql
psql -d ta_lab2 -f sql/ddl/create_cmc_returns_ema_multi_tf_cal_unified.sql
```

### 5. Create Price Bar Tables

Price bar tables store multi-timeframe OHLCV data:

```bash
# Create 1D price bars with state tracking
psql -d ta_lab2 -f sql/ddl/create_cmc_price_bars_1d_state.sql

# Create multi-timeframe price bars
psql -d ta_lab2 -f sql/ddl/price_bars__cmc_price_bars_multi_tf.sql
```

### 6. Create Returns Tables

Returns tables store return calculations across timeframes:

```bash
psql -d ta_lab2 -f sql/ddl/create_returns_tables_20251221.sql
psql -d ta_lab2 -f sql/ddl/ddl_cmc_returns_bars_multi_tf.sql
```

### 7. Verify Database Setup

```bash
# Check tables exist
psql -d ta_lab2 -c "\dt"

# Check dim_timeframe has data
psql -d ta_lab2 -c "SELECT COUNT(*) FROM dim_timeframe;"
# Expected: 199 rows

# Check dim_sessions has data
psql -d ta_lab2 -c "SELECT * FROM dim_sessions;"
# Expected: CRYPTO and EQUITY sessions
```

### Database Migrations

ta_lab2 currently uses SQL DDL files for schema management. For future migrations:

1. Create new DDL file in `sql/ddl/` with descriptive name
2. Document migration in `sql/migrations/README.md`
3. Run manually via `psql -d ta_lab2 -f sql/ddl/new_migration.sql`
4. Update database setup documentation

**Idempotency**: All DDL files should use `CREATE TABLE IF NOT EXISTS` or check for existence before creating.

---

## Qdrant Setup (Memory System)

Qdrant provides vector storage for the AI memory system. Two deployment modes:

### Docker (Recommended for Production)

Run Qdrant in server mode with persistent storage:

```bash
# Create volume for data persistence
docker volume create qdrant_storage

# Run Qdrant container
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  --restart unless-stopped \
  qdrant/qdrant

# Verify Qdrant is running
curl http://localhost:6333/health
# Expected: {"status":"ok"}
```

**Configuration**:
```bash
export QDRANT_SERVER_MODE=true
export QDRANT_URL=http://localhost:6333
```

**Data Persistence**:
- Volume mount: `-v qdrant_storage:/qdrant/storage`
- All 3,763 memories verified persisting across restarts
- Auto-restart enabled: `--restart unless-stopped`

### Local Binary (Development)

Download and run Qdrant binary directly:

```bash
# Download latest release
wget https://github.com/qdrant/qdrant/releases/download/v1.7.0/qdrant-x86_64-unknown-linux-gnu.tar.gz

# Extract
tar xzf qdrant-x86_64-unknown-linux-gnu.tar.gz

# Run with local storage
./qdrant --storage-path ./qdrant_data
```

### Embedded Mode (Testing Only)

For testing without a server:

```bash
export QDRANT_SERVER_MODE=false
export QDRANT_PATH=./qdrant_data
```

**Warning**: Embedded mode is suitable for testing only. Use server mode for production.

### Verify Qdrant Setup

```bash
# Check health endpoint
curl http://localhost:6333/health

# List collections (empty initially)
curl http://localhost:6333/collections

# Python verification
python -c "
from qdrant_client import QdrantClient
client = QdrantClient(url='http://localhost:6333')
print(f'Qdrant version: {client.get_collections()}')
"
```

---

## Running Services

### Memory API Server

The Memory API provides REST endpoints for memory operations:

```bash
# Start server on default port 8000
uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --host 0.0.0.0 --port 8000

# With auto-reload (development)
uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --reload

# Background (production)
nohup uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --host 0.0.0.0 --port 8000 > memory_api.log 2>&1 &
```

**Endpoints**:
- `GET /health` - Health check
- `POST /api/v1/memory/search` - Semantic search
- `GET /api/v1/memory/health` - Memory health report
- `GET /api/v1/memory/health/stale` - Stale memories list
- `POST /api/v1/memory/add` - Add memory
- `PUT /api/v1/memory/update` - Update memory

**Test endpoint**:
```bash
curl http://localhost:8000/health
# Expected: {"status":"healthy","checks":{...}}
```

### Feature Refresh Scripts

Refresh feature tables incrementally:

```bash
# Refresh daily features (returns, volatility, technical indicators)
python -m ta_lab2.scripts.features.ta_feature refresh --all

# Refresh specific feature types
python -m ta_lab2.scripts.features.ta_feature refresh --feature-type returns
python -m ta_lab2.scripts.features.ta_feature refresh --feature-type volatility
python -m ta_lab2.scripts.features.ta_feature refresh --feature-type indicators

# Refresh specific assets only
python -m ta_lab2.scripts.features.ta_feature refresh --ids 1,2,3

# Dry run (preview changes)
python -m ta_lab2.scripts.features.ta_feature refresh --all --dry-run
```

### Signal Generation

Generate trading signals from features:

```bash
# Run all signal refresh scripts
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Run specific signal type
python -m ta_lab2.scripts.signals.ema_crossover refresh --all
python -m ta_lab2.scripts.signals.rsi_mean_revert refresh --all
python -m ta_lab2.scripts.signals.atr_breakout refresh --all

# With validation
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate
```

### EMA Computation

Compute multi-timeframe EMAs:

```bash
# Refresh all EMA tables
python -m ta_lab2.scripts.emas.refresh_cmc_emas --ids all

# Refresh daily EMAs only
python -m ta_lab2.scripts.emas.refresh_cmc_ema_daily_only --ids all

# Refresh multi-timeframe EMAs
python -m ta_lab2.scripts.emas.refresh_cmc_ema_multi_tf_only --ids all

# Sync to unified table
python -m ta_lab2.scripts.emas.sync_cmc_ema_multi_tf_u --ids all
```

### Price Bar Updates

Update price bars from source data:

```bash
# Refresh daily price bars
python -m ta_lab2.scripts.bars.refresh_cmc_price_bars_1d --ids all

# Audit price bar integrity
python -m ta_lab2.scripts.bars.audit_price_bars_integrity
python -m ta_lab2.scripts.bars.audit_price_bars_tables
```

### Full Pipeline Execution

Run end-to-end daily refresh:

```bash
# Complete daily refresh (bars -> EMAs -> features -> signals)
python -m ta_lab2.scripts.pipeline.run_go_forward_daily_refresh

# With specific asset list
python -m ta_lab2.scripts.pipeline.run_go_forward_daily_refresh --ids 1,2,3

# Parallel execution (faster)
python -m ta_lab2.scripts.pipeline.run_go_forward_daily_refresh --parallel 4
```

---

## Monitoring & Observability

### Health Check Endpoints

The Memory API exposes health check endpoints:

```bash
# Overall health
curl http://localhost:8000/health
# Returns: {"status":"healthy","checks":{"database":"up","memory":"ok","qdrant":"connected"}}

# Liveness probe (process alive)
curl http://localhost:8000/health/liveness
# Returns: {"status":"alive"}

# Readiness probe (dependencies healthy)
curl http://localhost:8000/health/readiness
# Returns: {"status":"ready","dependencies":{...}}

# Startup probe (initialization complete)
curl http://localhost:8000/health/startup
# Returns: {"status":"initialized"}
```

### Observability Tables

Query metrics and traces directly from PostgreSQL:

```sql
-- Recent pipeline executions
SELECT metric_name, value, tags, recorded_at
FROM observability.metrics
WHERE metric_name = 'pipeline_duration'
  AND recorded_at > NOW() - INTERVAL '7 days'
ORDER BY recorded_at DESC
LIMIT 10;

-- Traces for specific correlation ID
SELECT trace_id, operation, start_time, end_time, status, metadata
FROM observability.traces
WHERE correlation_id = 'abc123...'
ORDER BY start_time;

-- Workflow state
SELECT workflow_id, type, phase, status, created_at, updated_at
FROM observability.workflow_state
WHERE status = 'running'
ORDER BY created_at DESC;

-- Metrics by tag
SELECT metric_name, AVG(value) as avg_value, COUNT(*) as count
FROM observability.metrics
WHERE tags->>'feature_type' = 'returns'
  AND recorded_at > NOW() - INTERVAL '1 day'
GROUP BY metric_name;
```

### Alert Configuration

Configure Telegram alerts for monitoring:

```bash
# Set Telegram credentials
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export TELEGRAM_CHAT_ID="-1001234567890"

# Test alert delivery
python -c "
from ta_lab2.observability.alerts import send_alert
send_alert(
    message='Test alert from ta_lab2',
    severity='info',
    component='deployment'
)
"
```

**Alert Severity Levels**:
- `info`: Informational (logged only)
- `warning`: Potential issue (Telegram + database)
- `error`: Error condition (Telegram + database)
- `critical`: Critical failure (Telegram + database + escalation)

**Severity Escalation Rules**:
- Integration failures: CRITICAL after >3 errors
- Resource exhaustion: CRITICAL at >=95%
- Data quality: CRITICAL with >10 issues

### Log Locations

ta_lab2 logs to stdout/stderr by default. For production, redirect to files:

```bash
# Feature refresh logs
python -m ta_lab2.scripts.features.ta_feature refresh --all > features.log 2>&1

# Signal generation logs
python -m ta_lab2.scripts.signals.run_all_signal_refreshes > signals.log 2>&1

# Memory API logs (with uvicorn)
uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app \
  --log-config logging.yaml \
  --access-log \
  >> memory_api.log 2>&1
```

---

## CI/CD Configuration

### GitHub Actions Workflow

ta_lab2 includes a validation workflow (`.github/workflows/validation.yml`):

**Triggers**:
- Push to main branch
- Pull requests to main branch

**Steps**:
1. Checkout code
2. Set up Python 3.11
3. Install dependencies (`pip install -e ".[orchestrator,dev]"`)
4. Start PostgreSQL service container (postgres:16)
5. Run validation tests with coverage
6. Upload coverage and validation reports

**PostgreSQL Service Container**:
```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: ta_lab2_validation
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
    ports:
      - 5432:5432
```

**Coverage Threshold**: 70% (build fails if coverage drops below 70%)

**Validation Gates**:
- Time alignment validation (SIG-04)
- Data consistency validation (SIG-05)
- Backtest reproducibility validation

### Running Validation Locally

Replicate CI validation locally:

```bash
# Create test database
createdb ta_lab2_validation

# Set environment variable
export TARGET_DB_URL="postgresql://postgres:postgres@localhost:5432/ta_lab2_validation"

# Run validation tests
pytest tests/validation/ \
  --maxfail=1 \
  -v \
  --cov=src/ta_lab2 \
  --cov-report=json:reports/coverage.json \
  --cov-report=markdown:reports/coverage.md \
  --cov-fail-under=70

# View coverage report
cat reports/coverage.md
```

---

## Troubleshooting

### Database Connection Issues

**Symptom**: `psycopg2.OperationalError: could not connect to server`

**Solutions**:
1. Verify PostgreSQL is running:
   ```bash
   pg_isready -h localhost -p 5432
   ```

2. Check connection string format:
   ```bash
   echo $TARGET_DB_URL
   # Should be: postgresql://user:pass@host:port/dbname
   ```

3. Test connection with psql:
   ```bash
   psql -d $TARGET_DB_URL
   ```

4. Check PostgreSQL logs:
   ```bash
   tail -f /var/log/postgresql/postgresql-16-main.log
   ```

### Qdrant Connection Issues

**Symptom**: `QdrantException: Could not connect to Qdrant`

**Solutions**:
1. Verify Qdrant is running:
   ```bash
   curl http://localhost:6333/health
   ```

2. Check Docker container status:
   ```bash
   docker ps | grep qdrant
   docker logs qdrant
   ```

3. Restart Qdrant container:
   ```bash
   docker restart qdrant
   ```

4. Check QDRANT_URL environment variable:
   ```bash
   echo $QDRANT_URL
   # Should be: http://localhost:6333
   ```

### Memory API Issues

**Symptom**: `ConnectionRefusedError` when accessing Memory API

**Solutions**:
1. Verify API is running:
   ```bash
   curl http://localhost:8000/health
   ```

2. Check process:
   ```bash
   ps aux | grep uvicorn
   ```

3. Start API server:
   ```bash
   uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --reload
   ```

4. Check logs for errors:
   ```bash
   tail -f memory_api.log
   ```

### AI API Authentication Issues

**Symptom**: `AuthenticationError: Invalid API key`

**Solutions**:
1. Verify API keys are set:
   ```bash
   echo $OPENAI_API_KEY | cut -c1-10
   echo $ANTHROPIC_API_KEY | cut -c1-10
   echo $GOOGLE_API_KEY | cut -c1-10
   ```

2. Test API key validity:
   ```bash
   # OpenAI
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"

   # Anthropic
   curl https://api.anthropic.com/v1/models \
     -H "x-api-key: $ANTHROPIC_API_KEY"
   ```

3. Check quota/rate limits:
   ```python
   from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker
   tracker = QuotaTracker()
   print(tracker.get_usage_summary())
   ```

### Feature Refresh Failures

**Symptom**: Feature refresh scripts fail with data errors

**Solutions**:
1. Check source data integrity:
   ```bash
   python -m ta_lab2.scripts.bars.audit_price_bars_integrity
   ```

2. Verify dimension tables exist:
   ```bash
   psql -d ta_lab2 -c "SELECT COUNT(*) FROM dim_timeframe;"
   psql -d ta_lab2 -c "SELECT COUNT(*) FROM dim_sessions;"
   ```

3. Run with dry-run to preview changes:
   ```bash
   python -m ta_lab2.scripts.features.ta_feature refresh --all --dry-run
   ```

4. Check state table watermarks:
   ```sql
   SELECT feature_type, feature_name, MAX(last_processed_ts)
   FROM feature_state
   GROUP BY feature_type, feature_name;
   ```

---

## Production Deployment

### System Service (Linux)

Create systemd service for Memory API:

```bash
# Create service file
sudo nano /etc/systemd/system/ta-lab2-memory.service
```

**Service configuration**:
```ini
[Unit]
Description=ta_lab2 Memory API
After=network.target postgresql.service docker.service

[Service]
Type=simple
User=ta_lab2
WorkingDirectory=/opt/ta_lab2
Environment="TARGET_DB_URL=postgresql://user:pass@localhost:5432/ta_lab2"
Environment="QDRANT_SERVER_MODE=true"
Environment="QDRANT_URL=http://localhost:6333"
ExecStart=/opt/ta_lab2/venv/bin/uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ta-lab2-memory
sudo systemctl start ta-lab2-memory
sudo systemctl status ta-lab2-memory
```

### Scheduled Jobs (Cron)

Schedule daily feature refresh:

```bash
# Edit crontab
crontab -e
```

**Example schedule**:
```cron
# Daily feature refresh at 2 AM
0 2 * * * cd /opt/ta_lab2 && /opt/ta_lab2/venv/bin/python -m ta_lab2.scripts.pipeline.run_go_forward_daily_refresh >> /var/log/ta_lab2/daily_refresh.log 2>&1

# Signal generation at 3 AM (after features)
0 3 * * * cd /opt/ta_lab2 && /opt/ta_lab2/venv/bin/python -m ta_lab2.scripts.signals.run_all_signal_refreshes >> /var/log/ta_lab2/signals.log 2>&1

# Health check every hour
0 * * * * curl -f http://localhost:8000/health || echo "Memory API health check failed" | mail -s "ta_lab2 Alert" admin@example.com
```

### Backup & Recovery

**Database backups**:
```bash
# Daily backup
pg_dump ta_lab2 | gzip > /backups/ta_lab2_$(date +%Y%m%d).sql.gz

# Restore from backup
gunzip -c /backups/ta_lab2_20260201.sql.gz | psql ta_lab2
```

**Qdrant backups**:
```bash
# Create snapshot
curl -X POST http://localhost:6333/snapshots/create

# List snapshots
curl http://localhost:6333/snapshots

# Backup volume
docker run --rm \
  -v qdrant_storage:/source \
  -v /backups:/backup \
  alpine tar czf /backup/qdrant_$(date +%Y%m%d).tar.gz -C /source .
```

### Security Hardening

1. **Restrict database access**:
   ```sql
   -- Create read-only user for monitoring
   CREATE USER ta_lab2_readonly WITH PASSWORD 'secure_password';
   GRANT CONNECT ON DATABASE ta_lab2 TO ta_lab2_readonly;
   GRANT USAGE ON SCHEMA public, observability TO ta_lab2_readonly;
   GRANT SELECT ON ALL TABLES IN SCHEMA public, observability TO ta_lab2_readonly;
   ```

2. **Firewall rules**:
   ```bash
   # Allow PostgreSQL only from localhost
   sudo ufw allow from 127.0.0.1 to any port 5432

   # Allow Qdrant only from localhost
   sudo ufw allow from 127.0.0.1 to any port 6333
   ```

3. **API key rotation**:
   - Rotate API keys quarterly
   - Use separate keys for dev/staging/prod
   - Store keys in secure vault (not .env in production)

---

*Last updated: 2026-02-01*
*Version: 0.4.0 release candidate*
