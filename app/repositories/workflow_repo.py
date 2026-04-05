"""Data-access layer for workflow_runs and workflow_results tables."""

from typing import Any

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)


class WorkflowRepository:
    """CRUD operations on ``workflow_runs`` and ``workflow_results`` tables."""

    def __init__(self, pool: aiomysql.Pool):
        self.pool = pool

    async def get_by_chat_id(self, chat_id: str) -> dict[str, Any] | None:
        """Get workflow run by chat ID."""
        query = "SELECT * FROM workflow_runs WHERE chat_id = %s"
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (chat_id,))
                row = await cur.fetchone()
                return dict(row) if row else None
