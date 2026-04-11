"""Data-access layer for chat sessions."""

from datetime import datetime
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_CHAT_COLS = """
    id, user_id, title, status, is_starred, project_id, message_count,
    created_at, updated_at, deleted_at
"""

_CHAT_LIST_COLS = """
    id, user_id, title, status, is_starred, project_id, message_count, created_at, updated_at
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
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new chat session."""
        query = """
            INSERT INTO chats (id, user_id, title, status, is_starred, project_id, message_count, created_at, updated_at)
            VALUES (%s, %s, %s, 'active', FALSE, %s, 0, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (chat_id, user_id, title, project_id))
                await conn.commit()

        logger.info("chat_created", chat_id=chat_id, user_id=user_id, project_id=project_id)
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

    async def list_by_user(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        user_id: str,
        limit: int = 20,
        cursor: Optional[datetime] = None,
        starred: Optional[bool] = None,
        project_id: Optional[str] = None,
        no_project: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List user's chats (non-deleted), ordered by updated_at DESC.
        Returns (chats, total_count).

        Filters:
        - starred: True = only starred, False = only non-starred, None = all
        - project_id: Only return chats in this project
        - no_project: Only return chats not assigned to any project
        """
        where_clauses = ["user_id = %s", "deleted_at IS NULL"]
        count_params: list[Any] = [user_id]

        if starred is True:
            where_clauses.append("is_starred = TRUE")
        elif starred is False:
            where_clauses.append("is_starred = FALSE")

        if project_id:
            where_clauses.append("project_id = %s")
            count_params.append(project_id)
        elif no_project:
            where_clauses.append("project_id IS NULL")

        where_sql = " AND ".join(where_clauses)

        count_query = f"SELECT COUNT(*) as cnt FROM chats WHERE {where_sql}"  # nosec B608

        list_params = list(count_params)
        if cursor:
            where_sql_with_cursor = f"{where_sql} AND updated_at < %s"
            list_params.append(cursor)
        else:
            where_sql_with_cursor = where_sql

        list_params.append(limit)

        list_query = f"""
            SELECT {_CHAT_LIST_COLS}
            FROM chats
            WHERE {where_sql_with_cursor}
            ORDER BY updated_at DESC
            LIMIT %s
        """  # nosec B608

        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(count_query, tuple(count_params))
                count_row = await cur.fetchone()
                total = count_row["cnt"] if count_row else 0

                await cur.execute(list_query, tuple(list_params))
                rows = await cur.fetchall()
                return [dict(r) for r in rows], total

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_title(self, chat_id: str, title: str) -> Optional[dict[str, Any]]:
        """Update chat title."""
        query = """
            UPDATE chats
            SET title = %s, updated_at = UTC_TIMESTAMP(6)
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

    async def update_starred(self, chat_id: str, is_starred: bool) -> Optional[dict[str, Any]]:
        """Update chat starred status."""
        query = """
            UPDATE chats
            SET is_starred = %s, updated_at = UTC_TIMESTAMP(6)
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (is_starred, chat_id))
                await conn.commit()
                if cur.rowcount == 0:
                    return None

        logger.info("chat_starred_updated", chat_id=chat_id, is_starred=is_starred)
        return await self.get_by_id(chat_id)

    async def update_project(self, chat_id: str, project_id: Optional[str]) -> Optional[dict[str, Any]]:
        """Update chat project assignment. Pass None to remove from project."""
        query = """
            UPDATE chats
            SET project_id = %s, updated_at = UTC_TIMESTAMP(6)
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (project_id, chat_id))
                await conn.commit()
                if cur.rowcount == 0:
                    return None

        logger.info("chat_project_updated", chat_id=chat_id, project_id=project_id)
        return await self.get_by_id(chat_id)

    async def get_project_id(self, chat_id: str) -> Optional[str]:
        """Get the current project_id for a chat (for updating counts)."""
        query = "SELECT project_id FROM chats WHERE id = %s AND deleted_at IS NULL"
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (chat_id,))
                row = await cur.fetchone()
                return row["project_id"] if row else None

    async def increment_message_count(self, chat_id: str, increment: int = 1) -> None:
        """Increment message_count and touch updated_at. Clamps at zero, skips deleted chats."""
        query = """
            UPDATE chats
            SET message_count = GREATEST(0, message_count + %s), updated_at = UTC_TIMESTAMP(6)
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (increment, chat_id))
                await conn.commit()

    async def set_title_if_empty(self, chat_id: str, title: str) -> None:
        """Set title only if currently NULL (for auto-title from first message)."""
        query = """
            UPDATE chats
            SET title = %s, updated_at = UTC_TIMESTAMP(6)
            WHERE id = %s AND title IS NULL AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (title, chat_id))
                await conn.commit()

    async def unassign_from_project(self, project_id: str) -> int:
        """
        Remove all chats from a project (set project_id to NULL).
        Called when a project is soft-deleted.
        Returns the number of chats unassigned.
        """
        query = """
            UPDATE chats
            SET project_id = NULL, updated_at = UTC_TIMESTAMP(6)
            WHERE project_id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (project_id,))
                await conn.commit()
                count = cur.rowcount

        if count > 0:
            logger.info("chats_unassigned_from_project", project_id=project_id, count=count)
        return count

    # ── Delete ────────────────────────────────────────────────────────────────

    async def soft_delete(self, chat_id: str) -> bool:
        """Soft delete a chat (set deleted_at). Returns True if deleted."""
        query = """
            UPDATE chats
            SET deleted_at = UTC_TIMESTAMP(6), updated_at = UTC_TIMESTAMP(6)
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
