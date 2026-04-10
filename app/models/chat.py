"""Pydantic request/response models for chat session management."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Request Models ───────────────────────────────────────────────────────────


class CreateChatRequest(BaseModel):
    """Create a new chat, optionally with an initial message."""

    message: Optional[str] = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Optional first message to send immediately after chat creation",
        examples=["Help me find scholarships for computer science programs in Singapore"],
    )


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


class UpdateChatRequest(BaseModel):
    """Update chat metadata (currently only title)."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="New chat title",
        examples=["My Scholarship Search"],
    )

    @field_validator("title")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
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
    message_count: int = Field(..., examples=[4])
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SendMessageResponse(BaseModel):
    """Response after sending a message—includes both user and assistant messages."""

    user_message: MessageResponse
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
        description="Cursor for next page (base64-encoded created_at timestamp)",
    )
