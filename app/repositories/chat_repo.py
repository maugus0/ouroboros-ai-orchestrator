"""Data-access layer for the chats and messages tables."""

from typing import Any

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)


class ChatRepository:
    """CRUD operations on ``chats`` and ``messages`` tables."""

    def __init__(self, pool: aiomysql.Pool):
        self.pool = pool

    async def get_by_id(self, chat_id: str) -> dict[str, Any] | None:
        """Get chat by ID."""
        query = "SELECT * FROM chats WHERE id = %s"
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (chat_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def list_by_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """List chats for a user, ordered by most recent first."""
        query = """
            SELECT * FROM chats
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id, limit))
                rows = await cur.fetchall()
                return [dict(row) for row in rows]
