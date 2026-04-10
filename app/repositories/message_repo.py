"""Data-access layer for chat messages."""

import json
from datetime import datetime
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_MESSAGE_COLS = "id, chat_id, role, content, metadata, created_at"


class MessageRepository:
    """CRUD operations on the ``messages`` table."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        message_id: str,
        chat_id: str,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a new message."""
        metadata_json = json.dumps(metadata) if metadata else None

        query = """
            INSERT INTO messages (id, chat_id, role, content, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP())
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (message_id, chat_id, role, content, metadata_json))
                await conn.commit()

        logger.info("message_created", message_id=message_id, chat_id=chat_id, role=role)
        result = await self.get_by_id(message_id)
        if result is None:
            raise RuntimeError(f"Message {message_id} not found after creation")
        return result

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, message_id: str) -> Optional[dict[str, Any]]:
        """Get a single message by ID."""
        query = f"SELECT {_MESSAGE_COLS} FROM messages WHERE id = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (message_id,))
                row = await cur.fetchone()
                if row:
                    result = dict(row)
                    result["metadata"] = self._parse_metadata(result.get("metadata"))
                    return result
                return None

    async def list_by_chat(
        self,
        chat_id: str,
        limit: int = 50,
        cursor: Optional[datetime] = None,
        order: str = "asc",
    ) -> list[dict[str, Any]]:
        """
        List messages for a chat.
        Default order is ASC (oldest first) for conversation display.
        Cursor pagination using created_at.
        """
        if order.lower() == "desc":
            if cursor:
                query = f"""
                    SELECT {_MESSAGE_COLS}
                    FROM messages
                    WHERE chat_id = %s AND created_at < %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """  # nosec B608
                params: tuple[Any, ...] = (chat_id, cursor, limit)
            else:
                query = f"""
                    SELECT {_MESSAGE_COLS}
                    FROM messages
                    WHERE chat_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """  # nosec B608
                params = (chat_id, limit)
        else:
            if cursor:
                query = f"""
                    SELECT {_MESSAGE_COLS}
                    FROM messages
                    WHERE chat_id = %s AND created_at > %s
                    ORDER BY created_at ASC
                    LIMIT %s
                """  # nosec B608
                params = (chat_id, cursor, limit)
            else:
                query = f"""
                    SELECT {_MESSAGE_COLS}
                    FROM messages
                    WHERE chat_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                """  # nosec B608
                params = (chat_id, limit)

        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
                results = []
                for row in rows:
                    r = dict(row)
                    r["metadata"] = self._parse_metadata(r.get("metadata"))
                    results.append(r)
                return results

    async def count_by_chat(self, chat_id: str) -> int:
        """Count messages in a chat."""
        query = "SELECT COUNT(*) as cnt FROM messages WHERE chat_id = %s"
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (chat_id,))
                row = await cur.fetchone()
                return row["cnt"] if row else 0

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_metadata(metadata: Any) -> Optional[dict[str, Any]]:
        """Parse JSON metadata from database."""
        if metadata is None:
            return None
        if isinstance(metadata, dict):
            return metadata
        if isinstance(metadata, str):
            try:
                return json.loads(metadata)
            except json.JSONDecodeError:
                return None
        return None
