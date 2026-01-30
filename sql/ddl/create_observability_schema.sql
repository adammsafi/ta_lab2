-- Create observability schema for monitoring, metrics, and tracing
-- Usage: Run via ensure_observability_tables() in storage.py

CREATE SCHEMA IF NOT EXISTS observability;

-- Workflow state tracking table
-- Tracks workflow lifecycle: creation -> phase transitions -> completion
CREATE TABLE IF NOT EXISTS observability.workflow_state (
    workflow_id UUID PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL,
    workflow_type VARCHAR(100) NOT NULL,
    current_phase VARCHAR(100),
    status VARCHAR(50) NOT NULL,  -- 'pending', 'running', 'completed', 'failed'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB,

    -- Indexes for common queries
    CONSTRAINT valid_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_correlation_id ON observability.workflow_state(correlation_id);
CREATE INDEX IF NOT EXISTS idx_workflow_status ON observability.workflow_state(status);
CREATE INDEX IF NOT EXISTS idx_workflow_type ON observability.workflow_state(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_created_at ON observability.workflow_state(created_at DESC);

-- Metrics table (partitioned by month for scalability)
-- Stores counter, gauge, and histogram metrics
CREATE TABLE IF NOT EXISTS observability.metrics (
    id BIGSERIAL,
    metric_name VARCHAR(255) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    metric_type VARCHAR(50) NOT NULL,  -- 'counter', 'gauge', 'histogram'
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    labels JSONB,

    -- Partition key
    PRIMARY KEY (id, recorded_at),

    CONSTRAINT valid_metric_type CHECK (metric_type IN ('counter', 'gauge', 'histogram'))
) PARTITION BY RANGE (recorded_at);

-- Create initial partitions for current and next month
-- Note: In production, automate partition creation with pg_cron or similar
CREATE TABLE IF NOT EXISTS observability.metrics_2026_01
    PARTITION OF observability.metrics
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE TABLE IF NOT EXISTS observability.metrics_2026_02
    PARTITION OF observability.metrics
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

CREATE TABLE IF NOT EXISTS observability.metrics_2026_03
    PARTITION OF observability.metrics
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON observability.metrics(metric_name, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_labels ON observability.metrics USING GIN(labels);

-- Spans table for distributed tracing (OpenTelemetry)
-- Stores trace spans with parent-child relationships
CREATE TABLE IF NOT EXISTS observability.spans (
    trace_id VARCHAR(32) NOT NULL,
    span_id VARCHAR(16) NOT NULL,
    parent_span_id VARCHAR(16),
    operation_name VARCHAR(255) NOT NULL,
    service_name VARCHAR(100) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_ms BIGINT GENERATED ALWAYS AS (
        CASE
            WHEN end_time IS NOT NULL
            THEN EXTRACT(EPOCH FROM (end_time - start_time)) * 1000
            ELSE NULL
        END
    ) STORED,
    attributes JSONB,
    status VARCHAR(50),  -- 'ok', 'error', 'unset'

    PRIMARY KEY (trace_id, span_id),

    CONSTRAINT valid_span_status CHECK (status IN ('ok', 'error', 'unset') OR status IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON observability.spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_start_time ON observability.spans(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_spans_operation ON observability.spans(operation_name);
CREATE INDEX IF NOT EXISTS idx_spans_service ON observability.spans(service_name);
CREATE INDEX IF NOT EXISTS idx_spans_attributes ON observability.spans USING GIN(attributes);

-- Alerts table for threshold-based monitoring
-- Stores alert events with acknowledgement tracking
CREATE TABLE IF NOT EXISTS observability.alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(100) NOT NULL,
    severity VARCHAR(50) NOT NULL,  -- 'critical', 'warning', 'info'
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(100),
    metadata JSONB,

    CONSTRAINT valid_alert_severity CHECK (severity IN ('critical', 'warning', 'info'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_severity_time ON observability.alerts(severity, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON observability.alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON observability.alerts(acknowledged_at)
    WHERE acknowledged_at IS NULL;  -- Partial index for unacknowledged alerts

-- Comments for documentation
COMMENT ON SCHEMA observability IS 'Observability infrastructure: metrics, traces, workflows, alerts';
COMMENT ON TABLE observability.workflow_state IS 'Tracks workflow lifecycle across orchestrator, memory, and ta_lab2';
COMMENT ON TABLE observability.metrics IS 'Time-series metrics (counter, gauge, histogram) partitioned by month';
COMMENT ON TABLE observability.spans IS 'OpenTelemetry distributed tracing spans with parent-child relationships';
COMMENT ON TABLE observability.alerts IS 'Alert events with acknowledgement tracking for operational monitoring';
