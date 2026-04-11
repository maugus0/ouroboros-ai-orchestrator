"""Data-access layer for projects."""

from datetime import datetime
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_PROJECT_COLS = """
    id, user_id, name, description, color, icon, chat_count,
    created_at, updated_at, deleted_at
"""

_PROJECT_LIST_COLS = """
    id, user_id, name, description, color, icon, chat_count, created_at, updated_at
"""


class ProjectRepository:
    """CRUD operations on the ``projects`` table."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        project_id: str,
        user_id: str,
        name: str,
        description: Optional[str] = None,
        color: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new project."""
        query = """
            INSERT INTO projects (id, user_id, name, description, color, icon, chat_count, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 0, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (project_id, user_id, name, description, color, icon))
                await conn.commit()

        logger.info("project_created", project_id=project_id, user_id=user_id)
        result = await self.get_by_id(project_id)
        if result is None:
            raise RuntimeError(f"Project {project_id} not found after creation")
        return result

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, project_id: str) -> Optional[dict[str, Any]]:
        """Get a single project by ID (excludes soft-deleted)."""
        query = f"SELECT {_PROJECT_COLS} FROM projects WHERE id = %s AND deleted_at IS NULL"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (project_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_by_id_with_user(self, project_id: str) -> Optional[dict[str, Any]]:
        """Get project including user_id for ownership validation (includes soft-deleted)."""
        query = f"SELECT {_PROJECT_COLS} FROM projects WHERE id = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (project_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def list_by_user(
        self,
        user_id: str,
        limit: int = 50,
        cursor: Optional[datetime] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List user's projects (non-deleted), ordered by updated_at DESC.
        Returns (projects, total_count).
        """
        count_query = """
            SELECT COUNT(*) as cnt FROM projects
            WHERE user_id = %s AND deleted_at IS NULL
        """

        if cursor:
            list_query = f"""
                SELECT {_PROJECT_LIST_COLS}
                FROM projects
                WHERE user_id = %s AND deleted_at IS NULL AND updated_at < %s
                ORDER BY updated_at DESC
                LIMIT %s
            """  # nosec B608
            list_params: tuple[Any, ...] = (user_id, cursor, limit)
        else:
            list_query = f"""
                SELECT {_PROJECT_LIST_COLS}
                FROM projects
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

    async def exists_for_user(self, project_id: str, user_id: str) -> bool:
        """Check if a project exists and belongs to user (not deleted)."""
        query = """
            SELECT 1 FROM projects
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (project_id, user_id))
                row = await cur.fetchone()
                return row is not None

    # ── Update ────────────────────────────────────────────────────────────────

    async def update(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update project fields. Only non-None values are updated."""
        updates: list[str] = []
        params: list[Any] = []

        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if description is not None:
            updates.append("description = %s")
            params.append(description)
        if color is not None:
            updates.append("color = %s")
            params.append(color)
        if icon is not None:
            updates.append("icon = %s")
            params.append(icon)

        if not updates:
            return await self.get_by_id(project_id)

        updates.append("updated_at = UTC_TIMESTAMP(6)")
        params.append(project_id)

        query = f"""
            UPDATE projects
            SET {', '.join(updates)}
            WHERE id = %s AND deleted_at IS NULL
        """  # nosec B608

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, tuple(params))
                await conn.commit()
                if cur.rowcount == 0:
                    return None

        logger.info("project_updated", project_id=project_id)
        return await self.get_by_id(project_id)

    async def increment_chat_count(self, project_id: str, increment: int = 1) -> None:
        """Increment chat_count (use negative for decrement). Clamps at zero."""
        query = """
            UPDATE projects
            SET chat_count = GREATEST(0, chat_count + %s), updated_at = UTC_TIMESTAMP(6)
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (increment, project_id))
                await conn.commit()

    # ── Delete ────────────────────────────────────────────────────────────────

    async def soft_delete(self, project_id: str) -> bool:
        """Soft delete a project. Returns True if deleted."""
        query = """
            UPDATE projects
            SET deleted_at = UTC_TIMESTAMP(6), updated_at = UTC_TIMESTAMP(6)
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (project_id,))
                await conn.commit()
                deleted = cur.rowcount > 0

        if deleted:
            logger.info("project_soft_deleted", project_id=project_id)
        return deleted
