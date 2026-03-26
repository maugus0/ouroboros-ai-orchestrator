"""Pydantic models for chat session endpoints."""

from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ChatResponse(BaseModel):
    id: str
    user_id: str
    title: str | None
    created_at: str
    updated_at: str


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    role: str = Field(default="user")


class MessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    metadata: dict | None = None
    created_at: str
