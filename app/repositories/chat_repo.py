"""Data-access layer for chat sessions."""

from datetime import datetime
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_CHAT_COLS = """
    id, user_id, title, status, message_count,
    created_at, updated_at, deleted_at
"""

_CHAT_LIST_COLS = """
    id, user_id, title, status, message_count, created_at, updated_at
"""


class ChatRepository:
    """CRUD operations on the ``chats`` table."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        chat_id: str,
        user_id: str,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new chat session."""
        query = """
            INSERT INTO chats (id, user_id, title, status, message_count, created_at, updated_at)
            VALUES (%s, %s, %s, 'active', 0, UTC_TIMESTAMP(), UTC_TIMESTAMP())
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (chat_id, user_id, title))
                await conn.commit()

        logger.info("chat_created", chat_id=chat_id, user_id=user_id)
        result = await self.get_by_id(chat_id)
        if result is None:
            raise RuntimeError(f"Chat {chat_id} not found after creation")
        return result

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, chat_id: str) -> Optional[dict[str, Any]]:
        """Get a single chat by ID (excludes soft-deleted)."""
        query = f"SELECT {_CHAT_COLS} FROM chats WHERE id = %s AND deleted_at IS NULL"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (chat_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_by_id_with_user(self, chat_id: str) -> Optional[dict[str, Any]]:
        """Get chat including user_id for ownership validation (includes soft-deleted for check)."""
        query = f"SELECT {_CHAT_COLS} FROM chats WHERE id = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (chat_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def list_by_user(
        self,
        user_id: str,
        limit: int = 20,
        cursor: Optional[datetime] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List user's chats (non-deleted), ordered by updated_at DESC.
        Returns (chats, total_count).
        Cursor is the updated_at of the last item from previous page.
        """
        count_query = """
            SELECT COUNT(*) as cnt FROM chats
            WHERE user_id = %s AND deleted_at IS NULL
        """

        if cursor:
            list_query = f"""
                SELECT {_CHAT_LIST_COLS}
                FROM chats
                WHERE user_id = %s AND deleted_at IS NULL AND updated_at < %s
                ORDER BY updated_at DESC
                LIMIT %s
            """  # nosec B608
            list_params: tuple[Any, ...] = (user_id, cursor, limit)
        else:
            list_query = f"""
                SELECT {_CHAT_LIST_COLS}
                FROM chats
                WHERE user_id = %s AND deleted_at IS NULL
                ORDER BY updated_at DESC
                LIMIT %s
            """  # nosec B608
            list_params = (user_id, limit)

        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(count_query, (user_id,))
                count_row = await cur.fetchone()
                total = count_row["cnt"] if count_row else 0

                await cur.execute(list_query, list_params)
                rows = await cur.fetchall()
                return [dict(r) for r in rows], total

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_title(self, chat_id: str, title: str) -> Optional[dict[str, Any]]:
        """Update chat title."""
        query = """
            UPDATE chats
            SET title = %s, updated_at = UTC_TIMESTAMP()
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (title, chat_id))
                await conn.commit()
                if cur.rowcount == 0:
                    return None

        logger.info("chat_title_updated", chat_id=chat_id)
        return await self.get_by_id(chat_id)

    async def increment_message_count(self, chat_id: str, increment: int = 1) -> None:
        """Increment message_count and touch updated_at."""
        query = """
            UPDATE chats
            SET message_count = message_count + %s, updated_at = UTC_TIMESTAMP()
            WHERE id = %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (increment, chat_id))
                await conn.commit()

    async def set_title_if_empty(self, chat_id: str, title: str) -> None:
        """Set title only if currently NULL (for auto-title from first message)."""
        query = """
            UPDATE chats
            SET title = %s, updated_at = UTC_TIMESTAMP()
            WHERE id = %s AND title IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (title, chat_id))
                await conn.commit()

    # ── Delete ────────────────────────────────────────────────────────────────

    async def soft_delete(self, chat_id: str) -> bool:
        """Soft delete a chat (set deleted_at). Returns True if deleted."""
        query = """
            UPDATE chats
            SET deleted_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (chat_id,))
                await conn.commit()
                deleted = cur.rowcount > 0

        if deleted:
            logger.info("chat_soft_deleted", chat_id=chat_id)
        return deleted
