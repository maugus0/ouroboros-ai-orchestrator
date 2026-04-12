"""Data-access layer for workflow run state persistence."""

import json
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_WORKFLOW_COLS = """
    id, user_id, chat_id, workflow_type, workflow_state, status,
    context, error_message, started_at, ended_at, created_at, updated_at
"""


class WorkflowRunRepository:
    """CRUD-like operations on the ``workflow_runs`` table."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    async def create_run(
        self,
        *,
        run_id: str,
        user_id: str,
        chat_id: Optional[str],
        workflow_type: str,
        workflow_state: str,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        query = """
            INSERT INTO workflow_runs (
                id, user_id, chat_id, workflow_type, workflow_state,
                status, context, started_at, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, 'in_progress', %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
        """
        context_json = json.dumps(context) if context is not None else None

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (run_id, user_id, chat_id, workflow_type, workflow_state, context_json))
                await conn.commit()

        logger.info(
            "workflow_run_created",
            run_id=run_id,
            user_id=user_id,
            chat_id=chat_id,
            workflow_type=workflow_type,
            workflow_state=workflow_state,
        )

    async def complete_run(
        self,
        *,
        run_id: str,
        status: str,
        workflow_state: Optional[str] = None,
        error_message: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        sets = ["status = %s", "ended_at = UTC_TIMESTAMP(6)", "updated_at = UTC_TIMESTAMP(6)"]
        params: list[Any] = [status]

        if workflow_state is not None:
            sets.append("workflow_state = %s")
            params.append(workflow_state)
        if error_message is not None:
            sets.append("error_message = %s")
            params.append(error_message)
        if context is not None:
            sets.append("context = %s")
            params.append(json.dumps(context))

        params.append(run_id)
        query = f"UPDATE workflow_runs SET {', '.join(sets)} WHERE id = %s"  # nosec B608

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, tuple(params))
                await conn.commit()

    async def get_by_id(self, run_id: str) -> Optional[dict[str, Any]]:
        query = f"SELECT {_WORKFLOW_COLS} FROM workflow_runs WHERE id = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (run_id,))
                row = await cur.fetchone()
                if not row:
                    return None
                result = dict(row)
                result["context"] = self._parse_json(result.get("context"))
                return result

    @staticmethod
    def _parse_json(value: Any) -> Any:
        if value is None or isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None
