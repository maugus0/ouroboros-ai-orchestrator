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

logger = get_logger(__name__)

MAX_AUTO_TITLE_LENGTH = 50


def _lazy_chat_repo() -> ChatRepository:
    return ChatRepository(get_pool())


def _lazy_message_repo() -> MessageRepository:
    return MessageRepository(get_pool())


class ChatService:
    """Orchestrates chat session operations."""

    def __init__(
        self,
        chat_repo: Optional[ChatRepository] = None,
        message_repo: Optional[MessageRepository] = None,
    ) -> None:
        self._chat_repo = chat_repo
        self._message_repo = message_repo

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

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_chat(
        self,
        user_id: str,
        initial_message: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Create a new chat session.

        If initial_message is provided:
        1. Create chat
        2. Store user message
        3. Generate placeholder assistant response
        4. Store assistant message
        5. Set title from first 50 chars of user message
        6. Return chat with both messages
        """
        chat_id = str(uuid.uuid4())

        chat = await self.chat_repo.create(chat_id=chat_id, user_id=user_id, title=None)

        if initial_message:
            result = await self.send_message(
                user_id=user_id,
                chat_id=chat_id,
                content=initial_message,
            )
            return result["chat"]

        logger.info("chat_created", user_id=user_id, chat_id=chat_id, with_message=False)
        return chat

    async def get_chat(self, user_id: str, chat_id: str) -> dict[str, Any]:
        """Get a single chat by ID. Validates ownership."""
        chat = await self._get_chat_or_404(chat_id, user_id)
        return chat

    async def list_chats(
        self,
        user_id: str,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        List user's chats with cursor pagination.
        Cursor is base64-encoded updated_at ISO timestamp.
        """
        limit = min(max(1, limit), 100)

        cursor_dt: Optional[datetime] = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode("utf-8")
                cursor_dt = datetime.fromisoformat(decoded)
            except Exception as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from exc

        chats, total_count = await self.chat_repo.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor=cursor_dt,
        )

        next_cursor: Optional[str] = None
        if chats and len(chats) == limit:
            last_updated = chats[-1].get("updated_at")
            if last_updated:
                if isinstance(last_updated, datetime):
                    cursor_str = last_updated.isoformat()
                else:
                    cursor_str = str(last_updated)
                next_cursor = base64.b64encode(cursor_str.encode("utf-8")).decode("utf-8")

        return {
            "chats": chats,
            "next_cursor": next_cursor,
            "total_count": total_count,
        }

    async def update_chat_title(
        self,
        user_id: str,
        chat_id: str,
        title: str,
    ) -> dict[str, Any]:
        """Update chat title. Validates ownership."""
        await self._get_chat_or_404(chat_id, user_id)

        chat = await self.chat_repo.update_title(chat_id, title)
        if not chat:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        logger.info("chat_title_updated", user_id=user_id, chat_id=chat_id)
        return chat

    async def delete_chat(self, user_id: str, chat_id: str) -> None:
        """Soft delete a chat. Validates ownership."""
        await self._get_chat_or_404(chat_id, user_id)

        deleted = await self.chat_repo.soft_delete(chat_id)
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        logger.info("chat_deleted", user_id=user_id, chat_id=chat_id)

    async def send_message(
        self,
        user_id: str,
        chat_id: str,
        content: str,
    ) -> dict[str, Any]:
        """
        Send a user message and receive assistant response.

        1. Validate chat ownership
        2. Store user message
        3. Generate placeholder assistant response
        4. Store assistant message
        5. Update chat (message_count, title if first message)
        6. Return both messages + updated chat
        """
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
        """
        Get message history for a chat with cursor pagination.
        Default order is ASC (oldest first) for conversation display.
        Cursor is base64-encoded created_at ISO timestamp.
        """
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
                if isinstance(last_created, datetime):
                    cursor_str = last_created.isoformat()
                else:
                    cursor_str = str(last_created)
                next_cursor = base64.b64encode(cursor_str.encode("utf-8")).decode("utf-8")

        return {
            "messages": messages,
            "next_cursor": next_cursor,
        }

    # ── Private Helpers ───────────────────────────────────────────────────────

    async def _get_chat_or_404(self, chat_id: str, user_id: str) -> dict[str, Any]:
        """
        Get chat and validate ownership.
        Returns 404 for both not-found and not-owned (prevents enumeration).
        """
        chat = await self.chat_repo.get_by_id_with_user(chat_id)

        if not chat:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if chat.get("deleted_at") is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if chat.get("user_id") != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        return chat

    def _generate_placeholder_response(self, _user_message: str) -> str:
        """
        Generate a placeholder assistant response.

        FUTURE: This method will be replaced with:
        1. Intent classification (what does the user want?)
        2. Agent routing (which agent(s) should handle this?)
        3. Agent calls (call Student Profile, Program Discovery, etc.)
        4. Response aggregation (combine agent responses)
        """
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
