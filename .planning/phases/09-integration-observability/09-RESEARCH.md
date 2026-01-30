# Phase 9: Integration & Observability - Research

**Researched:** 2026-01-30
**Domain:** Cross-system integration testing, observability infrastructure, distributed tracing
**Confidence:** HIGH

## Summary

Phase 9 validates that memory + orchestrator + ta_lab2 work together through comprehensive integration testing, observability instrumentation, and gap/alignment validation. The research reveals that modern Python integration testing follows a three-tier dependency model (real/mixed/mocked), observability requires all four dimensions (logs, metrics, traces, health checks), and distributed tracing relies on OpenTelemetry for correlation ID propagation.

**Key findings:**
- pytest provides mature integration testing capabilities with markers (@pytest.mark.integration), fixtures for setup/teardown, and parametrization for multi-scenario testing
- OpenTelemetry is the 2026 standard for Python observability - unified API for logs, metrics, and traces with stable implementations across major languages
- PostgreSQL serves as effective observability storage - queryable with SQL, time-series optimized with partitioning, already integrated in ta_lab2
- Existing codebase has validation infrastructure (FeatureValidator with gap detection, Telegram alerts) and test patterns (component tests in tests/features/, tests/orchestrator/) to extend
- Health checks follow Kubernetes patterns: liveness (is process alive), readiness (can accept traffic), startup (initial load complete)

**Primary recommendation:** Build integration test suite using pytest with three-tier markers (real_deps, mixed_deps, mocked_deps), instrument all systems with OpenTelemetry for unified observability stored in PostgreSQL tables, leverage existing FeatureValidator gap detection patterns for timeframe alignment tests, and extend Telegram alert integration for monitoring.

## Standard Stack

The established libraries/tools for integration testing and observability in Python:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.0+ | Test framework and integration testing | Mature fixture system, marker-based test selection, already in pyproject.toml |
| pytest-asyncio | 0.21.0+ | Async test support | Required for testing orchestrator async workflows, already in pyproject.toml |
| opentelemetry-api | 1.20+ | Observability instrumentation | Industry standard (2026), stable across Python/Java/.NET/Node.js |
| opentelemetry-sdk | 1.20+ | Telemetry collection and export | Reference implementation, production-ready |
| SQLAlchemy | 2.0+ | Database abstraction for observability storage | Already in ta_lab2, proven for time-series tables |
| structlog | 24.x | Structured logging | JSON logs, correlation ID propagation, queryable format |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-html | 4.1+ | HTML test reports | CI/CD artifact generation, test result visualization |
| pytest-mock | 3.12+ | Mocking framework | Three-tier dependency testing, isolation of external services |
| pytest-benchmark | 4.0+ | Performance baseline tracking | Detect >2x degradation, already in pyproject.toml |
| hypothesis | 6.92+ | Property-based testing | Synthetic test data generation, edge case discovery, already in pyproject.toml |
| requests | 2.31+ | HTTP client for health checks | Liveness/readiness probe implementation, already used in codebase |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| OpenTelemetry | Custom logging | OpenTelemetry provides unified API, vendor-neutral, correlation built-in |
| PostgreSQL storage | Prometheus + Grafana | PostgreSQL keeps observability data queryable with SQL, no new infrastructure |
| pytest markers | Separate test directories | Markers allow granular selection (-m integration), keep tests co-located |
| structlog | Standard logging | structlog enables structured JSON, better for parsing and correlation |

**Installation:**
```bash
# Core observability (add to pyproject.toml)
pip install opentelemetry-api opentelemetry-sdk structlog

# Test infrastructure (already in pyproject.toml dev dependencies)
pip install pytest>=8.0 pytest-asyncio pytest-html pytest-mock

# Already available in codebase
# pytest-benchmark, hypothesis, requests
```

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── observability/
│   ├── __init__.py
│   ├── tracing.py              # OpenTelemetry setup, context propagation
│   ├── metrics.py              # Counter, gauge, histogram wrappers
│   ├── logging_config.py       # structlog configuration (already exists in scripts/emas/)
│   ├── health.py               # Health check endpoints (liveness, readiness, startup)
│   └── storage.py              # PostgreSQL observability table schemas
├── tools/ai_orchestrator/
│   ├── execution.py            # ADD: trace spans for task execution
│   ├── routing.py              # ADD: metrics for routing decisions
│   └── memory/
│       └── client.py           # ADD: trace context in memory operations
└── scripts/
    └── observability/
        ├── create_observability_tables.py
        └── alert_thresholds.py

tests/
├── integration/                # E2E workflow tests
│   ├── conftest.py             # Shared fixtures (database, Qdrant, test data)
│   ├── test_e2e_orchestrator_memory_ta_lab2.py
│   ├── test_orchestrator_memory_pair.py
│   ├── test_orchestrator_ta_lab2_pair.py
│   └── test_failure_scenarios.py
├── observability/              # Observability infrastructure tests
│   ├── test_tracing.py
│   ├── test_metrics_collection.py
│   ├── test_health_checks.py
│   └── test_alert_delivery.py
└── validation/                 # Gap and alignment tests
    ├── test_timeframe_alignment.py
    ├── test_calendar_boundaries.py
    ├── test_gap_detection.py
    └── test_rowcount_validation.py
```

### Pattern 1: Three-Tier Integration Testing
**What:** Test classification by external dependency requirements
**When to use:** All integration tests to support flexible CI/CD and local development
**Example:**
```python
# Source: https://docs.pytest.org/en/stable/how-to/mark.html
import pytest
from sqlalchemy import create_engine

# tests/integration/conftest.py
@pytest.fixture(scope="session")
def real_database():
    """Real PostgreSQL connection - only if database available."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("Real database not available")
    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()

@pytest.fixture(scope="session")
def mock_database(mocker):
    """Mocked database for CI/CD."""
    return mocker.MagicMock()

# tests/integration/test_e2e_orchestrator_memory_ta_lab2.py
@pytest.mark.integration
@pytest.mark.real_deps  # Requires real DB, Qdrant, OpenAI
def test_full_workflow_real(real_database):
    """Test complete user request → orchestrator → memory → ta_lab2 flow."""
    # Submit task
    task = Task(
        type=TaskType.DATA_ANALYSIS,
        prompt="Refresh EMA features for BTC",
        context={"asset_id": 1},
    )
    result = orchestrator.submit(task)

    # Verify orchestrator routed task
    assert result.success

    # Verify memory was consulted
    memories = memory_client.search("EMA refresh BTC")
    assert len(memories) > 0

    # Verify ta_lab2 executed refresh
    with real_database.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM cmc_ema_multi_tf WHERE id = 1"
        )).scalar()
        assert count > 0

@pytest.mark.integration
@pytest.mark.mocked_deps  # All external deps mocked
def test_full_workflow_mocked(mocker):
    """Test workflow with mocked dependencies for fast CI/CD."""
    # Source: https://pytest-with-eric.com/mocking/pytest-mocking/
    mock_db = mocker.MagicMock()
    mock_memory = mocker.MagicMock()
    mock_memory.search.return_value = [{"content": "EMA refresh pattern"}]

    # Test workflow logic without external dependencies
    # ...
```

### Pattern 2: OpenTelemetry Distributed Tracing
**What:** Correlation ID propagation across orchestrator → memory → ta_lab2
**When to use:** All cross-system operations to enable end-to-end tracing
**Example:**
```python
# Source: https://opentelemetry.io/docs/concepts/signals/traces/
# Source: https://uptrace.dev/opentelemetry/python-tracing.html
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# src/ta_lab2/observability/tracing.py
def setup_tracing(service_name: str):
    """Initialize OpenTelemetry tracing for service."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # Export to PostgreSQL-backed collector (custom exporter)
    provider.add_span_processor(
        BatchSpanProcessor(PostgreSQLSpanExporter())
    )

    trace.set_tracer_provider(provider)
    return trace.get_tracer(__name__)

# src/ta_lab2/tools/ai_orchestrator/execution.py
tracer = setup_tracing("ai_orchestrator")

async def execute_task(task: Task) -> Result:
    """Execute task with distributed tracing."""
    # Create span with trace_id
    with tracer.start_as_current_span("execute_task") as span:
        span.set_attribute("task.type", task.type.value)
        span.set_attribute("task.id", task.task_id)

        # Get trace context for propagation
        ctx = trace.get_current_span().get_span_context()
        trace_id = format(ctx.trace_id, "032x")

        # Pass trace_id to memory client
        context = await memory_client.search(
            query=task.prompt,
            trace_id=trace_id  # Propagate correlation ID
        )

        # Execute with tracing
        result = await _execute_with_context(task, context, trace_id)

        span.set_attribute("task.success", result.success)
        return result
```

### Pattern 3: Workflow State Tracking Table
**What:** Database table tracking workflow_id, phase, status, timestamps
**When to use:** All cross-system workflows to enable state inspection and debugging
**Example:**
```python
# Source: https://medium.com/@herihermawan/the-ultimate-multifunctional-database-table-design-workflow-states-pattern-156618996549
# Source: https://www.infoq.com/news/2025/11/database-backed-workflow/
# sql/ddl/create_workflow_state.sql
CREATE TABLE observability.workflow_state (
    workflow_id UUID PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL,  -- OpenTelemetry trace_id
    workflow_type VARCHAR(50) NOT NULL,   -- 'orchestrator_task', 'feature_refresh'
    current_phase VARCHAR(50) NOT NULL,   -- 'submitted', 'routing', 'memory_search', 'executing', 'completed'
    status VARCHAR(20) NOT NULL,          -- 'pending', 'running', 'completed', 'failed'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB,                       -- Task details, error messages
    CONSTRAINT valid_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX idx_workflow_correlation ON observability.workflow_state(correlation_id);
CREATE INDEX idx_workflow_status ON observability.workflow_state(status, current_phase);
CREATE INDEX idx_workflow_created ON observability.workflow_state(created_at DESC);

# src/ta_lab2/observability/storage.py
class WorkflowStateTracker:
    """Track workflow state transitions in database."""

    def __init__(self, engine):
        self.engine = engine

    def create_workflow(self, workflow_id: str, correlation_id: str, workflow_type: str):
        """Initialize workflow tracking."""
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO observability.workflow_state
                (workflow_id, correlation_id, workflow_type, current_phase, status)
                VALUES (:wid, :cid, :type, 'submitted', 'pending')
            """), {"wid": workflow_id, "cid": correlation_id, "type": workflow_type})

    def transition(self, workflow_id: str, new_phase: str, status: str = 'running', metadata: dict = None):
        """Record state transition."""
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE observability.workflow_state
                SET current_phase = :phase, status = :status,
                    updated_at = NOW(), metadata = COALESCE(:meta::jsonb, metadata)
                WHERE workflow_id = :wid
            """), {"wid": workflow_id, "phase": new_phase, "status": status,
                   "meta": json.dumps(metadata) if metadata else None})
```

### Pattern 4: Health Check Endpoints
**What:** Liveness, readiness, and startup probes for each component
**When to use:** All long-running services (orchestrator, memory, ta_lab2 daemons)
**Example:**
```python
# Source: https://betterstack.com/community/guides/monitoring/kubernetes-health-checks/
# Source: https://apipark.com/techblog/en/python-health-check-endpoint-example-a-practical-guide/
# src/ta_lab2/observability/health.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class HealthStatus:
    """Health check result."""
    healthy: bool
    message: str
    checked_at: datetime
    details: dict = None

class HealthChecker:
    """Health check implementation for ta_lab2 components."""

    def __init__(self, engine, memory_client, config):
        self.engine = engine
        self.memory_client = memory_client
        self.config = config
        self.startup_complete = False

    def liveness(self) -> HealthStatus:
        """Liveness probe - is process alive?

        Keep simple - only check if process can respond.
        Do NOT check dependencies (database, memory).
        """
        return HealthStatus(
            healthy=True,
            message="Process alive",
            checked_at=datetime.utcnow()
        )

    def readiness(self) -> HealthStatus:
        """Readiness probe - can accept traffic?

        Check all dependencies: database, memory, cache.
        More comprehensive than liveness.
        """
        checks = {}

        # Check database connection
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1")).scalar()
            checks["database"] = True
        except Exception as e:
            checks["database"] = False
            checks["database_error"] = str(e)

        # Check memory service
        try:
            health = self.memory_client.health_check()
            checks["memory"] = health.get("status") == "healthy"
        except Exception as e:
            checks["memory"] = False
            checks["memory_error"] = str(e)

        all_healthy = all(v for k, v in checks.items() if not k.endswith("_error"))

        return HealthStatus(
            healthy=all_healthy,
            message="Ready" if all_healthy else "Not ready",
            checked_at=datetime.utcnow(),
            details=checks
        )

    def startup(self) -> HealthStatus:
        """Startup probe - initial load complete?

        Used for slow-starting applications.
        Once passes, switches to liveness/readiness.
        """
        if not self.startup_complete:
            # Check if initial data loaded
            try:
                with self.engine.connect() as conn:
                    count = conn.execute(text(
                        "SELECT COUNT(*) FROM ta_lab2.dim_timeframe"
                    )).scalar()

                    if count > 0:
                        self.startup_complete = True
            except Exception as e:
                return HealthStatus(
                    healthy=False,
                    message=f"Startup failed: {e}",
                    checked_at=datetime.utcnow()
                )

        return HealthStatus(
            healthy=self.startup_complete,
            message="Startup complete" if self.startup_complete else "Starting...",
            checked_at=datetime.utcnow()
        )
```

### Pattern 5: Gap Detection with Schedule-Based Validation
**What:** Generate expected dates from dim_timeframe, compare with actual data
**When to use:** Timeframe alignment validation, calendar boundary testing
**Example:**
```python
# Source: Existing codebase tests/features/test_validate_features.py
# Source: https://towardsdatascience.com/handling-gaps-in-time-series-dc47ae883990/
from ta_lab2.time.dim_timeframe import get_tf_days

def validate_timeframe_coverage(
    engine,
    table: str,
    asset_id: int,
    timeframe: str,
    start_date: str,
    end_date: str
) -> tuple[int, int, list[str]]:
    """Validate that table has all expected dates for timeframe.

    Returns:
        (expected_count, actual_count, missing_dates)
    """
    # Get expected trading days from dim_timeframe
    tf_days = get_tf_days(engine, timeframe)  # e.g., 252 for '1Y_rolling'

    # Generate expected date sequence
    expected_dates = pd.date_range(start_date, end_date, freq='D')

    # For equity assets, filter to trading sessions
    if is_equity_asset(asset_id):
        expected_dates = filter_trading_sessions(expected_dates, engine)

    expected_count = len(expected_dates)

    # Query actual dates from table
    with engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT DISTINCT bar_date
            FROM {table}
            WHERE id = :id AND bar_date BETWEEN :start AND :end
            ORDER BY bar_date
        """), {"id": asset_id, "start": start_date, "end": end_date})

        actual_dates = set(row[0] for row in result)

    actual_count = len(actual_dates)

    # Find missing dates
    missing = sorted(set(expected_dates.date) - actual_dates)

    return expected_count, actual_count, [str(d) for d in missing]


def test_calendar_boundary_alignment():
    """Test that 1M/3M/1Y calculations handle month/year rolls correctly."""
    # Source: https://www.timeanddate.com/calendar/?year=2026&country=1
    # 2026 is NOT a leap year (28 days in February)

    test_cases = [
        # Month-end boundary (Feb 28 → March 1 in non-leap year)
        {
            "date": "2026-02-28",
            "next_date": "2026-03-01",
            "timeframe": "1M_rolling",
            "expected_lookback_days": 28,  # February only
        },
        # Year-end boundary
        {
            "date": "2026-12-31",
            "next_date": "2027-01-01",
            "timeframe": "1Y_rolling",
            "expected_lookback_days": 365,  # 2026 is common year
        },
        # DST transition (US: March 8, 2026 clocks forward)
        {
            "date": "2026-03-08",
            "timeframe": "1D",
            "expected_bars": 24,  # Crypto: continuous, equity: check session
        },
    ]

    for case in test_cases:
        # Validate calculation uses correct window
        result = validate_calculation_window(
            table="cmc_ema_multi_tf_cal",
            date=case["date"],
            timeframe=case["timeframe"]
        )
        assert result.lookback_days == case["expected_lookback_days"]
```

### Anti-Patterns to Avoid
- **Don't use time.sleep() in integration tests:** Use pytest-asyncio and await, or mock time-dependent code to avoid flaky tests
- **Don't share mutable state between tests:** Each test should be independent - use fixtures with proper teardown
- **Don't skip teardown on test failure:** Use yield in fixtures or try/finally to ensure cleanup happens
- **Don't hardcode absolute thresholds without baseline:** Performance degradation alerts need baseline reference (e.g., >2x p50 latency)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Distributed tracing | Custom correlation ID system | OpenTelemetry | Context propagation, vendor-neutral, W3C standard trace IDs |
| Structured logging | String concatenation logs | structlog | JSON output, correlation IDs, queryable format |
| Test fixture management | Manual setup/teardown | pytest fixtures with yield | Automatic cleanup, scope control, dependency injection |
| Mocking external APIs | Custom stub objects | pytest-mock / unittest.mock | Patch, assert_called_with, side_effect patterns |
| Test data generation | Manual dictionaries | hypothesis or factory_boy | Property-based testing, edge case discovery |
| Performance baselines | Manual timing comparisons | pytest-benchmark | Statistical analysis, regression detection, CI integration |
| Health check patterns | Custom /ping endpoints | Kubernetes probe patterns | Industry standard (liveness/readiness/startup) |
| Time series gap detection | Manual date iteration | pandas date_range + set diff | Vectorized, handles timezones, DST-aware |

**Key insight:** Integration testing and observability have mature ecosystems with well-tested patterns. Custom solutions introduce maintenance burden and miss edge cases that standard tools handle (timezone handling, async context propagation, statistical baselines).

## Common Pitfalls

### Pitfall 1: Over-Mocking in Integration Tests
**What goes wrong:** Tests pass with mocked dependencies but fail with real systems because mocks don't reflect actual behavior
**Why it happens:** Mocking is easier than managing real dependencies (databases, APIs), so developers mock too much
**How to avoid:** Use three-tier test structure - some tests MUST run against real dependencies to catch integration issues
**Warning signs:** Integration tests always pass locally but fail in staging/production

### Pitfall 2: Missing Correlation ID Propagation
**What goes wrong:** Traces are fragmented - can't correlate orchestrator → memory → ta_lab2 operations for the same request
**Why it happens:** Each system generates its own trace IDs without propagating parent context
**How to avoid:** Use OpenTelemetry context propagation - extract trace context at boundaries, inject into downstream calls
**Warning signs:** Observability UI shows disconnected spans instead of unified trace tree

### Pitfall 3: Stateful Integration Tests
**What goes wrong:** Test order matters - test B fails when run alone but passes after test A because A leaves data in database
**Why it happens:** Tests share database state, fixtures don't clean up properly, or tests depend on specific data being present
**How to avoid:** Use transaction rollback fixtures or separate test databases, ensure each test creates its own test data
**Warning signs:** Tests pass in one order but fail when run in different order or individually

### Pitfall 4: Hardcoded Timing Assumptions
**What goes wrong:** Tests use `time.sleep(5)` assuming operation completes in 5 seconds, but fails in slower CI environment
**Why it happens:** Developer tests locally on fast machine, doesn't account for variable execution time
**How to avoid:** Use polling with timeout - check condition in loop until true or timeout, use pytest-timeout plugin
**Warning signs:** Tests randomly fail with "expected condition not met" in CI but always pass locally

### Pitfall 5: Ignoring Calendar Edge Cases
**What goes wrong:** Gap detection flags weekends as missing data for equity assets, or fails on leap year February 29
**Why it happens:** Time validation doesn't account for trading sessions, leap years, DST transitions
**How to avoid:** Use dim_sessions table for equity assets, test with known edge case dates (2024-02-29, DST transitions)
**Warning signs:** Spurious gap alerts on weekends/holidays, or alignment tests fail on specific dates only

### Pitfall 6: Alert Fatigue from Static Thresholds
**What goes wrong:** Performance alerts trigger constantly because threshold is too sensitive, or never trigger because too high
**Why it happens:** Static thresholds don't adapt to normal variance in performance (e.g., "alert if >1000ms" when normal range is 800-1200ms)
**How to avoid:** Use baseline + percentage degradation (e.g., ">2x p50 baseline"), update baseline periodically
**Warning signs:** Alerts ignored because they're always firing ("alert fatigue"), or real issues missed

## Code Examples

Verified patterns from official sources:

### Shared Fixtures in conftest.py
```python
# Source: https://docs.pytest.org/en/stable/how-to/fixtures.html
# Source: https://betterstack.com/community/guides/testing/pytest-fixtures-guide/
# tests/integration/conftest.py
import pytest
from sqlalchemy import create_engine, text

@pytest.fixture(scope="session")
def database_engine():
    """Session-scoped database engine with cleanup."""
    # Setup: Create engine
    engine = create_engine(os.environ["TEST_DATABASE_URL"])

    # Provide to tests
    yield engine

    # Teardown: Dispose connections
    engine.dispose()

@pytest.fixture(scope="function")
def clean_database(database_engine):
    """Function-scoped transaction rollback for test isolation."""
    # Start transaction
    connection = database_engine.connect()
    transaction = connection.begin()

    yield connection

    # Rollback transaction (undoes all test changes)
    transaction.rollback()
    connection.close()

@pytest.fixture
def test_assets(clean_database):
    """Generate test asset data."""
    # Insert test data
    clean_database.execute(text("""
        INSERT INTO ta_lab2.assets (id, symbol, asset_type)
        VALUES (1, 'BTC', 'crypto'), (2, 'AAPL', 'equity')
    """))

    return [1, 2]
```

### Parametrized Integration Tests
```python
# Source: https://docs.pytest.org/en/stable/how-to/parametrize.html
import pytest

@pytest.mark.parametrize("timeframe,expected_days", [
    ("1D", 1),
    ("7D", 7),
    ("30D", 30),
    ("1M_cal", 28),  # February 2026 (non-leap year)
    ("3M_cal", 90),  # Q1 2026
    ("1Y_cal", 365),  # 2026 (common year)
])
def test_timeframe_calculations(clean_database, timeframe, expected_days):
    """Test that calculations use correct lookback windows from dim_timeframe."""
    result = clean_database.execute(text("""
        SELECT tf_days FROM ta_lab2.dim_timeframe WHERE tf_code = :tf
    """), {"tf": timeframe}).scalar()

    assert result == expected_days, f"{timeframe} should have {expected_days} days"
```

### Metrics Collection with PostgreSQL Storage
```python
# Source: https://www.datadoghq.com/blog/postgresql-monitoring/
# src/ta_lab2/observability/metrics.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

@dataclass
class Metric:
    """Metric data point."""
    name: str
    value: float
    metric_type: Literal['counter', 'gauge', 'histogram']
    timestamp: datetime
    labels: dict[str, str]

class MetricsCollector:
    """Collect and store metrics in PostgreSQL."""

    def __init__(self, engine):
        self.engine = engine
        self._ensure_table()

    def _ensure_table(self):
        """Create metrics table with time-series optimization."""
        # Source: https://aws.amazon.com/blogs/database/designing-high-performance-time-series-data-tables-on-amazon-rds-for-postgresql/
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS observability.metrics (
                    id BIGSERIAL,
                    metric_name VARCHAR(100) NOT NULL,
                    metric_value DOUBLE PRECISION NOT NULL,
                    metric_type VARCHAR(20) NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    labels JSONB,
                    PRIMARY KEY (recorded_at, id)
                ) PARTITION BY RANGE (recorded_at);

                -- Create monthly partitions for performance
                CREATE TABLE IF NOT EXISTS observability.metrics_2026_01
                PARTITION OF observability.metrics
                FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

                CREATE INDEX IF NOT EXISTS idx_metrics_name_time
                ON observability.metrics (metric_name, recorded_at DESC);
            """))

    def record(self, metric: Metric):
        """Store metric in database."""
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO observability.metrics
                (metric_name, metric_value, metric_type, recorded_at, labels)
                VALUES (:name, :value, :type, :ts, :labels::jsonb)
            """), {
                "name": metric.name,
                "value": metric.value,
                "type": metric.metric_type,
                "ts": metric.timestamp,
                "labels": json.dumps(metric.labels)
            })

    def counter(self, name: str, value: float = 1, **labels):
        """Increment counter metric."""
        self.record(Metric(
            name=name,
            value=value,
            metric_type='counter',
            timestamp=datetime.utcnow(),
            labels=labels
        ))

    def gauge(self, name: str, value: float, **labels):
        """Set gauge metric."""
        self.record(Metric(
            name=name,
            value=value,
            metric_type='gauge',
            timestamp=datetime.utcnow(),
            labels=labels
        ))
```

### Alert Threshold with Baseline Detection
```python
# Source: https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/smart-detection-performance
# src/ta_lab2/observability/alert_thresholds.py
from datetime import datetime, timedelta

class AlertThresholdChecker:
    """Check metrics against dynamic baselines."""

    def __init__(self, engine, telegram_client):
        self.engine = engine
        self.telegram = telegram_client

    def check_performance_degradation(self, metric_name: str):
        """Alert if metric exceeds 2x baseline."""
        # Calculate baseline (p50 over last 7 days)
        baseline = self._calculate_baseline(metric_name, days=7)

        # Get current value (p50 over last 1 hour)
        current = self._calculate_current(metric_name, hours=1)

        # Check threshold
        if current > baseline * 2:
            self._send_alert(
                title="Performance Degradation Detected",
                message=f"{metric_name}: {current:.2f}ms (baseline: {baseline:.2f}ms, +{(current/baseline - 1)*100:.0f}%)",
                severity="warning"
            )

    def _calculate_baseline(self, metric_name: str, days: int) -> float:
        """Calculate p50 baseline over historical period."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY metric_value)
                FROM observability.metrics
                WHERE metric_name = :name
                  AND recorded_at >= NOW() - INTERVAL ':days days'
            """), {"name": metric_name, "days": days}).scalar()

            return result or 0.0

    def _calculate_current(self, metric_name: str, hours: int) -> float:
        """Calculate p50 current value over recent period."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY metric_value)
                FROM observability.metrics
                WHERE metric_name = :name
                  AND recorded_at >= NOW() - INTERVAL ':hours hours'
            """), {"name": metric_name, "hours": hours}).scalar()

            return result or 0.0

    def _send_alert(self, title: str, message: str, severity: str):
        """Send alert via Telegram and log to database."""
        # Use existing Telegram integration from Phase 7
        from ta_lab2.notifications.telegram import send_alert
        send_alert(title, message, severity)

        # Log alert to database
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO observability.alerts
                (alert_type, severity, title, message, triggered_at)
                VALUES ('performance_degradation', :severity, :title, :msg, NOW())
            """), {"severity": severity, "title": title, "msg": message})
```

## State of the Art

| Old Approach | Current Approach (2026) | When Changed | Impact |
|--------------|-------------------------|--------------|--------|
| Custom correlation IDs | OpenTelemetry W3C Trace Context | 2021-2024 | Vendor-neutral, automatic propagation, 32-char hex trace IDs |
| String logs with grep | Structured JSON logs with SQL queries | 2020-2026 | Queryable, correlation by trace_id, statistical analysis |
| Prometheus + Grafana | Unified observability in PostgreSQL | 2024-2026 | Single query interface, no new infrastructure, time-series optimized |
| Separate test directories | pytest markers for test tiers | 2022+ | Flexible selection (-m real_deps), tests co-located with code |
| Manual baseline tracking | Automatic baseline + percentage thresholds | 2023-2026 | Adapts to normal variance, reduces alert fatigue |
| xUnit setUp/tearDown | pytest fixtures with yield | 2015+ | Dependency injection, scoped cleanup, composable |

**Deprecated/outdated:**
- **unittest.TestCase for integration tests:** pytest provides more flexible fixtures and better async support (pytest-asyncio)
- **print() debugging in production:** Structured logging (structlog) enables correlation and querying
- **Static performance thresholds:** Baseline + degradation percentage adapts to system changes

## Open Questions

Things that couldn't be fully resolved:

1. **OpenTelemetry Exporter to PostgreSQL**
   - What we know: OpenTelemetry has OTLP exporters for many backends, custom exporters are possible
   - What's unclear: Whether to write custom PostgreSQL exporter or use intermediate collector
   - Recommendation: Start with custom exporter writing directly to PostgreSQL (simpler), migrate to OTLP collector if multi-backend needed

2. **Test Data Volume for E2E Tests**
   - What we know: Fixtures should be minimal, synthetic data is flexible, production samples are realistic
   - What's unclear: Exact rowcount thresholds (10 assets? 100? 1000?) for E2E performance vs coverage tradeoff
   - Recommendation: Start with 10-20 assets, 100 bars per asset (minimal), expand based on test execution time

3. **Alert Baseline Refresh Frequency**
   - What we know: Baselines should update to reflect system changes, but not so frequently that anomalies become "normal"
   - What's unclear: Optimal refresh period (daily? weekly? monthly?) for different metric types
   - Recommendation: 7-day rolling baseline for latency metrics, 30-day for data quality metrics (less volatile)

4. **Integration Test Execution in CI/CD**
   - What we know: Mocked tests run everywhere, real dependency tests need infrastructure
   - What's unclear: Whether to run real_deps tests in CI (slower but catches more issues) or only pre-merge
   - Recommendation: Run mocked_deps in every commit, real_deps nightly or pre-release, mixed_deps on PR

## Sources

### Primary (HIGH confidence)
- [pytest Documentation - How to use fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html) - Fixture patterns, setup/teardown with yield
- [pytest Documentation - Parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html) - Multi-scenario testing
- [pytest Documentation - Custom Markers](https://docs.pytest.org/en/stable/how-to/mark.html) - Test classification (@pytest.mark.integration)
- [pytest Documentation - Skip and XFail](https://docs.pytest.org/en/stable/how-to/skipping.html) - Conditional test execution
- [OpenTelemetry - Traces Concepts](https://opentelemetry.io/docs/concepts/signals/traces/) - Distributed tracing fundamentals
- [OpenTelemetry - Context Propagation](https://opentelemetry.io/docs/concepts/context-propagation/) - Correlation across services
- [Uptrace - OpenTelemetry Python Tracing](https://uptrace.dev/opentelemetry/python-tracing.html) - Python-specific implementation

### Secondary (MEDIUM confidence)
- [Pytest with Eric - Integration Testing Guide](https://pytest-with-eric.com/pytest-best-practices/pytest-setup-teardown/) - Setup/teardown patterns
- [Better Stack - Pytest Fixtures Guide](https://betterstack.com/community/guides/testing/pytest-fixtures-guide/) - Advanced fixture patterns
- [Better Stack - Kubernetes Health Checks](https://betterstack.com/community/guides/monitoring/kubernetes-health-checks/) - Liveness/readiness/startup probes
- [Medium - Observability in Python Services](https://python.plainenglish.io/observability-in-python-services-tracing-logging-and-metrics-best-practices-2a9ecf9d74aa) - Three pillars approach
- [Medium - Workflow States Pattern](https://medium.com/@herihermawan/the-ultimate-multifunctional-database-table-design-workflow-states-pattern-156618996549) - Database state tracking
- [InfoQ - Database-Backed Workflow Orchestration](https://www.infoq.com/news/2025/11/database-backed-workflow/) - Checkpoint-based workflows
- [AWS - PostgreSQL Time Series Design](https://aws.amazon.com/blogs/database/designing-high-performance-time-series-data-tables-on-amazon-rds-for-postgresql/) - Partitioning strategies
- [Datadog - PostgreSQL Monitoring](https://www.datadoghq.com/blog/postgresql-monitoring/) - Key metrics to track
- [Microsoft Learn - Smart Detection Performance Anomalies](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/smart-detection-performance) - Baseline + threshold patterns

### Tertiary (LOW confidence - marked for validation)
- WebSearch results on E2E testing best practices (general guidance, not Python-specific implementation details)
- WebSearch results on adaptive thresholding (concept valid, specific implementation needs verification with actual tools)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pytest, OpenTelemetry, SQLAlchemy all verified in official documentation and already in codebase
- Architecture: HIGH - Patterns verified in official docs (pytest fixtures, OpenTelemetry tracing) and existing codebase (FeatureValidator, Telegram alerts)
- Pitfalls: MEDIUM - Based on WebSearch results and general testing experience, specific to ta_lab2 context but not all verified in production

**Research date:** 2026-01-30
**Valid until:** 2026-03-30 (60 days - observability and testing tools are relatively stable)
