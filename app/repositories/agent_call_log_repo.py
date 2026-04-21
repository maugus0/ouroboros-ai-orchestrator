"""Data-access layer for downstream agent call audit logs."""

import json
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentCallLogRepository:
    """Persistence helpers for ``agent_call_logs``."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    async def create_log(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        log_id: str,
        workflow_run_id: Optional[str],
        user_id: str,
        chat_id: Optional[str],
        target_service: str,
        operation: str,
        request_method: Optional[str],
        request_path: Optional[str],
        attempt_number: int,
        status: str,
        http_status: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        request_payload: Optional[dict[str, Any]] = None,
        response_payload: Optional[dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        latency_ms: Optional[int] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> None:
        query = """
            INSERT INTO agent_call_logs (
                id, workflow_run_id, user_id, chat_id, target_service, operation,
                request_method, request_path, attempt_number, status, http_status,
                error_code, error_message, request_payload, response_payload,
                trace_id, session_id, latency_ms, retry_of_log_id, created_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, UTC_TIMESTAMP(6)
            )
        """

        request_json = json.dumps(request_payload) if request_payload is not None else None
        response_json = json.dumps(response_payload) if response_payload is not None else None

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        log_id,
                        workflow_run_id,
                        user_id,
                        chat_id,
                        target_service,
                        operation,
                        request_method,
                        request_path,
                        max(1, int(attempt_number)),
                        status,
                        http_status,
                        error_code,
                        error_message,
                        request_json,
                        response_json,
                        trace_id,
                        session_id,
                        latency_ms,
                        retry_of_log_id,
                    ),
                )
                await conn.commit()

        logger.info(
            "agent_call_log_created",
            log_id=log_id,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
            chat_id=chat_id,
            target_service=target_service,
            operation=operation,
            status=status,
            retry_of_log_id=retry_of_log_id,
        )

    async def get_latest_failed_log(
        self,
        *,
        user_id: str,
        chat_id: str,
        target_service: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        where = ["user_id = %s", "chat_id = %s", "status = 'failed'"]
        params: list[Any] = [user_id, chat_id]
        if target_service:
            where.append("target_service = %s")
            params.append(target_service)

        query = f"""
            SELECT id, workflow_run_id, operation, target_service, created_at
            FROM agent_call_logs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT 1
        """  # nosec B608

        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, tuple(params))
                row = await cur.fetchone()
                return dict(row) if row else None
