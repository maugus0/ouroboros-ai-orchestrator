"""Chat session business logic — create, send messages, list, delete."""

import base64
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, status

from app.core.database import get_pool
from app.core.logging import get_logger
from app.repositories.chat_repo import ChatRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.project_repo import ProjectRepository

logger = get_logger(__name__)

MAX_AUTO_TITLE_LENGTH = 50


def _lazy_chat_repo() -> ChatRepository:
    return ChatRepository(get_pool())


def _lazy_message_repo() -> MessageRepository:
    return MessageRepository(get_pool())


def _lazy_project_repo() -> ProjectRepository:
    return ProjectRepository(get_pool())


class ChatService:
    """Orchestrates chat session operations."""

    def __init__(
        self,
        chat_repo: Optional[ChatRepository] = None,
        message_repo: Optional[MessageRepository] = None,
        project_repo: Optional[ProjectRepository] = None,
    ) -> None:
        self._chat_repo = chat_repo
        self._message_repo = message_repo
        self._project_repo = project_repo

    @property
    def chat_repo(self) -> ChatRepository:
        if self._chat_repo is None:
            self._chat_repo = _lazy_chat_repo()
        return self._chat_repo

    @property
    def message_repo(self) -> MessageRepository:
        if self._message_repo is None:
            self._message_repo = _lazy_message_repo()
        return self._message_repo

    @property
    def project_repo(self) -> ProjectRepository:
        if self._project_repo is None:
            self._project_repo = _lazy_project_repo()
        return self._project_repo

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_chat(
        self,
        user_id: str,
        initial_message: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Create a new chat session.

        If project_id is provided, validates ownership and increments chat_count.
        If initial_message is provided, sends it and auto-generates title.
        """
        if project_id:
            exists = await self.project_repo.exists_for_user(project_id, user_id)
            if not exists:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        chat_id = str(uuid.uuid4())

        chat = await self.chat_repo.create(
            chat_id=chat_id,
            user_id=user_id,
            title=None,
            project_id=project_id,
        )

        if project_id:
            await self.project_repo.increment_chat_count(project_id, 1)

        if initial_message:
            result = await self.send_message(
                user_id=user_id,
                chat_id=chat_id,
                content=initial_message,
            )
            return result["chat"]

        logger.info("chat_created", user_id=user_id, chat_id=chat_id, project_id=project_id, with_message=False)
        return chat

    async def get_chat(self, user_id: str, chat_id: str) -> dict[str, Any]:
        """Get a single chat by ID. Validates ownership."""
        chat = await self._get_chat_or_404(chat_id, user_id)
        return chat

    async def list_chats(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        user_id: str,
        limit: int = 20,
        cursor: Optional[str] = None,
        starred: Optional[bool] = None,
        project_id: Optional[str] = None,
        no_project: bool = False,
    ) -> dict[str, Any]:
        """
        List user's chats with cursor pagination and filters.

        Filters:
        - starred: True = only starred, False = only non-starred, None = all
        - project_id: Filter by specific project
        - no_project: True = only chats without a project
        """
        limit = min(max(1, limit), 100)

        cursor_dt: Optional[datetime] = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode("utf-8")
                cursor_dt = datetime.fromisoformat(decoded)
            except Exception as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from exc

        if project_id:
            exists = await self.project_repo.exists_for_user(project_id, user_id)
            if not exists:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        chats, total_count = await self.chat_repo.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor=cursor_dt,
            starred_only=starred is True,
            project_id=project_id,
            no_project=no_project,
        )

        next_cursor: Optional[str] = None
        if chats and len(chats) == limit:
            last_updated = chats[-1].get("updated_at")
            if last_updated:
                cursor_str = last_updated.isoformat() if isinstance(last_updated, datetime) else str(last_updated)
                next_cursor = base64.b64encode(cursor_str.encode("utf-8")).decode("utf-8")

        return {
            "chats": chats,
            "next_cursor": next_cursor,
            "total_count": total_count,
        }

    async def update_chat(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: str,
        chat_id: str,
        title: Optional[str] = None,
        is_starred: Optional[bool] = None,
        project_id: Optional[str] = None,
        remove_from_project: bool = False,
    ) -> dict[str, Any]:
        """
        Update chat metadata (title, starred status, project assignment).

        To remove from project, pass remove_from_project=True or project_id as empty string.
        """
        chat = await self._get_chat_or_404(chat_id, user_id)
        old_project_id = chat.get("project_id")

        if title is not None:
            await self.chat_repo.update_title(chat_id, title)

        if is_starred is not None:
            await self.chat_repo.update_starred(chat_id, is_starred)

        if remove_from_project or project_id == "":
            if old_project_id:
                await self.chat_repo.update_project(chat_id, None)
                await self.project_repo.increment_chat_count(old_project_id, -1)
        elif project_id is not None:
            exists = await self.project_repo.exists_for_user(project_id, user_id)
            if not exists:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

            await self.chat_repo.update_project(chat_id, project_id)

            if old_project_id and old_project_id != project_id:
                await self.project_repo.increment_chat_count(old_project_id, -1)
            if project_id != old_project_id:
                await self.project_repo.increment_chat_count(project_id, 1)

        updated_chat = await self.chat_repo.get_by_id(chat_id)
        logger.info("chat_updated", user_id=user_id, chat_id=chat_id)
        return updated_chat  # type: ignore

    async def delete_chat(self, user_id: str, chat_id: str) -> None:
        """Soft delete a chat. Validates ownership. Updates project chat_count."""
        chat = await self._get_chat_or_404(chat_id, user_id)
        project_id = chat.get("project_id")

        deleted = await self.chat_repo.soft_delete(chat_id)
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if project_id:
            await self.project_repo.increment_chat_count(project_id, -1)

        logger.info("chat_deleted", user_id=user_id, chat_id=chat_id)

    async def send_message(
        self,
        user_id: str,
        chat_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Send a user message and receive assistant response."""
        chat = await self._get_chat_or_404(chat_id, user_id)

        user_message_id = str(uuid.uuid4())
        user_message = await self.message_repo.create(
            message_id=user_message_id,
            chat_id=chat_id,
            role="user",
            content=content,
            metadata=None,
        )
        logger.info("message_sent", user_id=user_id, chat_id=chat_id, message_id=user_message_id, role="user")

        assistant_content = self._generate_placeholder_response(content)

        assistant_message_id = str(uuid.uuid4())
        assistant_message = await self.message_repo.create(
            message_id=assistant_message_id,
            chat_id=chat_id,
            role="assistant",
            content=assistant_content,
            metadata=None,
        )
        logger.info("message_sent", user_id=user_id, chat_id=chat_id, message_id=assistant_message_id, role="assistant")

        await self.chat_repo.increment_message_count(chat_id, increment=2)

        if chat.get("message_count", 0) == 0:
            auto_title = self._generate_title_from_message(content)
            await self.chat_repo.set_title_if_empty(chat_id, auto_title)

        updated_chat = await self.chat_repo.get_by_id(chat_id)

        return {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "chat": updated_chat,
        }

    async def get_messages(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: str,
        chat_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
        order: str = "asc",
    ) -> dict[str, Any]:
        """Get message history for a chat with cursor pagination."""
        await self._get_chat_or_404(chat_id, user_id)

        limit = min(max(1, limit), 100)

        if order.lower() not in ("asc", "desc"):
            order = "asc"

        cursor_dt: Optional[datetime] = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode("utf-8")
                cursor_dt = datetime.fromisoformat(decoded)
            except Exception as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from exc

        messages = await self.message_repo.list_by_chat(
            chat_id=chat_id,
            limit=limit,
            cursor=cursor_dt,
            order=order,
        )

        next_cursor: Optional[str] = None
        if messages and len(messages) == limit:
            last_created = messages[-1].get("created_at")
            if last_created:
                cursor_str = last_created.isoformat() if isinstance(last_created, datetime) else str(last_created)
                next_cursor = base64.b64encode(cursor_str.encode("utf-8")).decode("utf-8")

        return {
            "messages": messages,
            "next_cursor": next_cursor,
        }

    # ── Private Helpers ───────────────────────────────────────────────────────

    async def _get_chat_or_404(self, chat_id: str, user_id: str) -> dict[str, Any]:
        """Get chat and validate ownership."""
        chat = await self.chat_repo.get_by_id_with_user(chat_id)

        if not chat:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if chat.get("deleted_at") is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if chat.get("user_id") != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        return chat

    def _generate_placeholder_response(self, _user_message: str) -> str:
        """Generate a placeholder assistant response."""
        return (
            "Thanks for your message! I'm Ouroboros, your AI assistant for discovering "
            "scholarships and programs. I'm currently being set up to help you with:\n\n"
            "• Finding scholarships that match your profile\n"
            "• Discovering graduate programs worldwide\n"
            "• Checking your eligibility for opportunities\n"
            "• Helping with your applications\n\n"
            "Full functionality is coming soon. Stay tuned!"
        )

    def _generate_title_from_message(self, content: str) -> str:
        """Generate a chat title from the first message content."""
        clean = content.strip()
        if len(clean) <= MAX_AUTO_TITLE_LENGTH:
            return clean

        truncated = clean[:MAX_AUTO_TITLE_LENGTH]
        last_space = truncated.rfind(" ")
        if last_space > MAX_AUTO_TITLE_LENGTH // 2:
            truncated = truncated[:last_space]

        return truncated + "..."
