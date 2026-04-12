"""Pydantic request/response models for chat session management."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Request Models ───────────────────────────────────────────────────────────


class CreateChatRequest(BaseModel):
    """Create a new chat, optionally with an initial message and project assignment."""

    message: Optional[str] = Field(
        None,
        max_length=10000,
        description="Optional first message to send immediately after chat creation",
        examples=["Help me find scholarships for computer science programs in Singapore"],
    )
    project_id: Optional[str] = Field(
        None,
        description="Optional project ID to assign this chat to",
        examples=["proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )

    @field_validator("message")
    @classmethod
    def strip_message(cls, v: Optional[str]) -> Optional[str]:
        """Strip whitespace; coerce whitespace-only to None."""
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            return None
        return stripped


class SendMessageRequest(BaseModel):
    """Send a message to an existing chat."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Message content",
        examples=["What scholarships are available for international students?"],
    )

    @field_validator("content")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Message content cannot be empty or whitespace only")
        return stripped


class AssistantNoticeRequest(BaseModel):
    """Post an assistant-authored notice without creating a synthetic user message."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Assistant notice content",
        examples=["Thanks for uploading your CV. What is your target degree level?"],
    )
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional metadata to persist with the assistant notice",
    )

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Assistant notice content cannot be empty or whitespace only")
        return stripped


class UpdateChatRequest(BaseModel):
    """Update chat metadata (title, starred status, project assignment)."""

    title: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="New chat title",
        examples=["My Scholarship Search"],
    )
    is_starred: Optional[bool] = Field(
        None,
        description="Mark chat as starred/favorite",
        examples=[True],
    )
    project_id: Optional[str] = Field(
        None,
        description="Project ID to move chat to (use empty string to remove from project)",
        examples=["proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("Title cannot be empty or whitespace only")
        return stripped


# ── Response Models ──────────────────────────────────────────────────────────


class MessageResponse(BaseModel):
    """Single message in a chat."""

    id: str = Field(..., examples=["msg-a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    chat_id: str = Field(..., examples=["chat-a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    role: Literal["user", "assistant", "system"] = Field(..., examples=["user"])
    content: str = Field(..., examples=["Help me find scholarships"])
    metadata: Optional[dict[str, Any]] = Field(
        None,
        description="Additional data: agent_ids, routing, token counts (future use)",
    )
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatResponse(BaseModel):
    """Chat session metadata."""

    id: str = Field(..., examples=["chat-a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    title: Optional[str] = Field(None, examples=["Scholarship Search for CS Programs"])
    status: Literal["active", "archived"] = Field(..., examples=["active"])
    is_starred: bool = Field(default=False, examples=[False])
    project_id: Optional[str] = Field(None, examples=["proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    message_count: int = Field(..., examples=[4])
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SendMessageResponse(BaseModel):
    """Response after sending a message—includes both user and assistant messages."""

    user_message: MessageResponse
    assistant_message: MessageResponse
    chat: ChatResponse


class AssistantNoticeResponse(BaseModel):
    """Response after posting an assistant-authored notice."""

    assistant_message: MessageResponse
    chat: ChatResponse


class ChatWithMessagesResponse(BaseModel):
    """Chat with its recent messages (for single chat retrieval)."""

    chat: ChatResponse
    messages: list[MessageResponse] = Field(default_factory=list)


# ── Paginated Responses ──────────────────────────────────────────────────────


class PaginatedChatsResponse(BaseModel):
    """Paginated list of chats."""

    chats: list[ChatResponse]
    next_cursor: Optional[str] = Field(
        None,
        description="Cursor for next page (base64-encoded updated_at timestamp)",
    )
    total_count: int = Field(..., description="Total chats for this user (excluding deleted)")


class PaginatedMessagesResponse(BaseModel):
    """Paginated list of messages."""

    messages: list[MessageResponse]
    next_cursor: Optional[str] = Field(
        None,
        description='Cursor for next page (base64-encoded JSON: {"t": "ISO timestamp", "id": "message-uuid"})',
    )
