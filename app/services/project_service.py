"""Project management business logic."""

import base64
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, status

from app.core.database import get_pool
from app.core.logging import get_logger
from app.repositories.chat_repo import ChatRepository
from app.repositories.project_repo import ProjectRepository

logger = get_logger(__name__)


def _lazy_project_repo() -> ProjectRepository:
    return ProjectRepository(get_pool())


def _lazy_chat_repo() -> ChatRepository:
    return ChatRepository(get_pool())


class ProjectService:
    """Orchestrates project operations."""

    def __init__(
        self,
        project_repo: Optional[ProjectRepository] = None,
        chat_repo: Optional[ChatRepository] = None,
    ) -> None:
        self._project_repo = project_repo
        self._chat_repo = chat_repo

    @property
    def project_repo(self) -> ProjectRepository:
        if self._project_repo is None:
            self._project_repo = _lazy_project_repo()
        return self._project_repo

    @property
    def chat_repo(self) -> ChatRepository:
        if self._chat_repo is None:
            self._chat_repo = _lazy_chat_repo()
        return self._chat_repo

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_project(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: str,
        name: str,
        description: Optional[str] = None,
        color: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new project."""
        project_id = str(uuid.uuid4())

        project = await self.project_repo.create(
            project_id=project_id,
            user_id=user_id,
            name=name,
            description=description,
            color=color,
            icon=icon,
        )

        logger.info("project_created", user_id=user_id, project_id=project_id)
        return project

    async def get_project(self, user_id: str, project_id: str) -> dict[str, Any]:
        """Get a single project by ID. Validates ownership."""
        project = await self._get_project_or_404(project_id, user_id)
        return project

    async def list_projects(
        self,
        user_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """List user's projects with cursor pagination."""
        limit = min(max(1, limit), 100)

        cursor_dt: Optional[datetime] = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode("utf-8")
                cursor_dt = datetime.fromisoformat(decoded)
            except Exception as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from exc

        projects, total_count = await self.project_repo.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor=cursor_dt,
        )

        next_cursor: Optional[str] = None
        if projects and len(projects) == limit:
            last_updated = projects[-1].get("updated_at")
            if last_updated:
                cursor_str = last_updated.isoformat() if isinstance(last_updated, datetime) else str(last_updated)
                next_cursor = base64.b64encode(cursor_str.encode("utf-8")).decode("utf-8")

        return {
            "projects": projects,
            "next_cursor": next_cursor,
            "total_count": total_count,
        }

    async def update_project(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: str,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update project metadata. Validates ownership."""
        await self._get_project_or_404(project_id, user_id)

        project = await self.project_repo.update(
            project_id=project_id,
            name=name,
            description=description,
            color=color,
            icon=icon,
        )

        if not project:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        logger.info("project_updated", user_id=user_id, project_id=project_id)
        return project

    async def delete_project(self, user_id: str, project_id: str) -> None:
        """
        Soft delete a project. Validates ownership.

        Unassigns all chats from this project (sets project_id to NULL) before
        soft-deleting to ensure chats remain accessible via other filters.
        """
        await self._get_project_or_404(project_id, user_id)

        unassigned_count = await self.chat_repo.unassign_from_project(project_id)

        deleted = await self.project_repo.soft_delete(project_id)
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        logger.info(
            "project_deleted",
            user_id=user_id,
            project_id=project_id,
            chats_unassigned=unassigned_count,
        )

    # ── Private Helpers ───────────────────────────────────────────────────────

    async def _get_project_or_404(self, project_id: str, user_id: str) -> dict[str, Any]:
        """Get project and validate ownership."""
        project = await self.project_repo.get_by_id_with_user(project_id)

        if not project:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        if project.get("deleted_at") is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        if project.get("user_id") != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        return project
