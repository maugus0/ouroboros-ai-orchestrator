"""Data-access layer for the agent_call_logs audit table."""

import json
import uuid
from typing import Any

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentCallLogRepository:
    """Insert and query audit records for agent HTTP calls."""

    def __init__(self, pool: aiomysql.Pool):
        self.pool = pool

    async def insert(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        workflow_run_id: str,
        agent_name: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | None,
        http_status: int,
        latency_ms: int,
        trace_id: str | None = None,
    ) -> str:
        """Record an agent call for audit purposes."""
        log_id = str(uuid.uuid4())
        query = """
            INSERT INTO agent_call_logs
            (id, workflow_run_id, agent_name, request_payload, response_payload,
             http_status, latency_ms, trace_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        log_id,
                        workflow_run_id,
                        agent_name,
                        json.dumps(request_payload),
                        json.dumps(response_payload) if response_payload else None,
                        http_status,
                        latency_ms,
                        trace_id,
                    ),
                )
                await conn.commit()
        return log_id
