"""
Observability storage module for PostgreSQL persistence.

Provides:
- ensure_observability_tables(): Idempotent schema/table creation
- WorkflowStateTracker: Workflow lifecycle management
- PostgreSQLSpanExporter: OpenTelemetry span export to database

Usage:
    from sqlalchemy import create_engine
    from ta_lab2.observability.storage import ensure_observability_tables, WorkflowStateTracker

    engine = create_engine(db_url)
    ensure_observability_tables(engine)

    tracker = WorkflowStateTracker(engine)
    workflow_id = uuid4()
    tracker.create_workflow(workflow_id, "corr-123", "ema_refresh")
    tracker.transition(workflow_id, "running", "success")
    state = tracker.get_workflow(workflow_id)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


# =============================================================================
# Schema Management
# =============================================================================

def ensure_observability_tables(engine: Engine) -> None:
    """
    Create observability schema and tables idempotently.

    Executes create_observability_schema.sql which includes:
    - observability schema
    - workflow_state table
    - metrics table (partitioned)
    - spans table
    - alerts table

    Args:
        engine: SQLAlchemy engine

    Raises:
        FileNotFoundError: If SQL file not found
        Exception: If SQL execution fails
    """
    # Find SQL file relative to this module
    sql_file = Path(__file__).parent.parent.parent.parent / "sql" / "ddl" / "create_observability_schema.sql"

    if not sql_file.exists():
        raise FileNotFoundError(f"Observability schema SQL not found: {sql_file}")

    logger.info(f"Executing observability schema SQL: {sql_file}")

    with open(sql_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    with engine.begin() as conn:
        # Execute statement by statement (PostgreSQL doesn't support multiple statements in text())
        for statement in sql.split(';'):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                conn.execute(text(statement))

    logger.info("Observability schema created successfully")


# =============================================================================
# Workflow State Tracker
# =============================================================================

class WorkflowStateTracker:
    """
    Tracks workflow lifecycle state in observability.workflow_state.

    Workflow lifecycle:
    1. create_workflow() -> status='pending'
    2. transition() -> status='running', phase updates
    3. transition() -> status='completed' or 'failed'

    Enables querying workflow history, debugging failures, and monitoring progress.
    """

    def __init__(self, engine: Engine):
        """
        Initialize tracker.

        Args:
            engine: SQLAlchemy engine
        """
        self.engine = engine

    def create_workflow(
        self,
        workflow_id: UUID,
        correlation_id: str,
        workflow_type: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Create new workflow in pending state.

        Args:
            workflow_id: Unique workflow identifier
            correlation_id: Correlation ID for cross-system tracing
            workflow_type: Workflow type (e.g., 'ema_refresh', 'backtest')
            metadata: Optional metadata dict

        Raises:
            Exception: If insert fails
        """
        query = text("""
            INSERT INTO observability.workflow_state
                (workflow_id, correlation_id, workflow_type, current_phase, status, metadata)
            VALUES
                (:workflow_id, :correlation_id, :workflow_type, NULL, 'pending', :metadata)
        """)

        params = {
            'workflow_id': str(workflow_id),
            'correlation_id': correlation_id,
            'workflow_type': workflow_type,
            'metadata': metadata if metadata else None,
        }

        with self.engine.begin() as conn:
            conn.execute(query, params)

        logger.debug(f"Created workflow {workflow_id} ({workflow_type})")

    def transition(
        self,
        workflow_id: UUID,
        new_phase: str,
        status: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Transition workflow to new phase/status.

        Args:
            workflow_id: Workflow identifier
            new_phase: New phase name
            status: New status ('pending', 'running', 'completed', 'failed', 'cancelled')
            metadata: Optional metadata to merge with existing

        Raises:
            Exception: If update fails or workflow not found
        """
        if metadata:
            # Merge with existing metadata
            query = text("""
                UPDATE observability.workflow_state
                SET current_phase = :new_phase,
                    status = :status,
                    updated_at = NOW(),
                    metadata = COALESCE(metadata, '{}'::jsonb) || :metadata::jsonb
                WHERE workflow_id = :workflow_id
            """)
            params = {
                'workflow_id': str(workflow_id),
                'new_phase': new_phase,
                'status': status,
                'metadata': metadata,
            }
        else:
            query = text("""
                UPDATE observability.workflow_state
                SET current_phase = :new_phase,
                    status = :status,
                    updated_at = NOW()
                WHERE workflow_id = :workflow_id
            """)
            params = {
                'workflow_id': str(workflow_id),
                'new_phase': new_phase,
                'status': status,
            }

        with self.engine.begin() as conn:
            result = conn.execute(query, params)

            if result.rowcount == 0:
                raise ValueError(f"Workflow {workflow_id} not found")

        logger.debug(f"Workflow {workflow_id} -> {new_phase} ({status})")

    def get_workflow(self, workflow_id: UUID) -> Optional[dict[str, Any]]:
        """
        Get current workflow state.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Dict with workflow state or None if not found
        """
        query = text("""
            SELECT
                workflow_id,
                correlation_id,
                workflow_type,
                current_phase,
                status,
                created_at,
                updated_at,
                metadata
            FROM observability.workflow_state
            WHERE workflow_id = :workflow_id
        """)

        with self.engine.connect() as conn:
            result = conn.execute(query, {'workflow_id': str(workflow_id)})
            row = result.fetchone()

            if not row:
                return None

            return {
                'workflow_id': row[0],
                'correlation_id': row[1],
                'workflow_type': row[2],
                'current_phase': row[3],
                'status': row[4],
                'created_at': row[5],
                'updated_at': row[6],
                'metadata': row[7],
            }

    def list_workflows(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        List recent workflows, optionally filtered by status.

        Args:
            status: Filter by status (None = all)
            limit: Maximum results (default 100)

        Returns:
            List of workflow state dicts, newest first
        """
        if status:
            query = text("""
                SELECT
                    workflow_id,
                    correlation_id,
                    workflow_type,
                    current_phase,
                    status,
                    created_at,
                    updated_at,
                    metadata
                FROM observability.workflow_state
                WHERE status = :status
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            params = {'status': status, 'limit': limit}
        else:
            query = text("""
                SELECT
                    workflow_id,
                    correlation_id,
                    workflow_type,
                    current_phase,
                    status,
                    created_at,
                    updated_at,
                    metadata
                FROM observability.workflow_state
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            params = {'limit': limit}

        workflows = []

        with self.engine.connect() as conn:
            result = conn.execute(query, params)

            for row in result:
                workflows.append({
                    'workflow_id': row[0],
                    'correlation_id': row[1],
                    'workflow_type': row[2],
                    'current_phase': row[3],
                    'status': row[4],
                    'created_at': row[5],
                    'updated_at': row[6],
                    'metadata': row[7],
                })

        return workflows


# =============================================================================
# PostgreSQL Span Exporter (for OpenTelemetry)
# =============================================================================

class PostgreSQLSpanExporter:
    """
    Exports OpenTelemetry spans to PostgreSQL observability.spans table.

    Used by tracing.py setup_tracing() when engine provided.
    Implements OpenTelemetry SpanExporter interface (export, shutdown).

    Note: This is a simplified implementation for database-centric observability.
    For production, consider Jaeger or Zipkin for richer trace visualization.
    """

    def __init__(self, engine: Engine):
        """
        Initialize exporter.

        Args:
            engine: SQLAlchemy engine
        """
        self.engine = engine
        self._shutdown = False

    def export(self, spans: list[Any]) -> None:
        """
        Export spans to database.

        Args:
            spans: List of OpenTelemetry Span objects

        Note: In real implementation, this would batch inserts for efficiency
        """
        if self._shutdown:
            logger.warning("SpanExporter already shutdown, ignoring export")
            return

        if not spans:
            return

        # Note: This is a placeholder implementation
        # Real implementation would extract span attributes and insert into DB
        # For now, just log that spans were received
        logger.debug(f"PostgreSQLSpanExporter received {len(spans)} spans")

        # In production, this would be:
        # query = text("""
        #     INSERT INTO observability.spans
        #     (trace_id, span_id, parent_span_id, operation_name, service_name,
        #      start_time, end_time, attributes, status)
        #     VALUES (:trace_id, :span_id, :parent_span_id, :operation_name,
        #             :service_name, :start_time, :end_time, :attributes, :status)
        # """)
        #
        # with self.engine.begin() as conn:
        #     for span in spans:
        #         params = extract_span_params(span)
        #         conn.execute(query, params)

    def shutdown(self) -> None:
        """
        Shutdown exporter.

        Called when tracer provider shuts down.
        """
        self._shutdown = True
        logger.debug("PostgreSQLSpanExporter shutdown")

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """
        Force flush pending spans.

        Args:
            timeout_millis: Timeout in milliseconds

        Returns:
            True if successful
        """
        # In real implementation, would flush any buffered spans
        return True
