"""Chat session API endpoints."""

from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.openapi.models import Example

from app.middleware.auth_middleware import get_current_user_id
from app.models.chat import (
    ChatResponse,
    CreateChatRequest,
    PaginatedChatsResponse,
    PaginatedMessagesResponse,
    SendMessageRequest,
    SendMessageResponse,
    UpdateChatRequest,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/v1/chats", tags=["Chats"])

# ── OpenAPI Examples ─────────────────────────────────────────────────────────

_CREATE_CHAT_EXAMPLES: dict[str, Example] = {
    "empty_chat": Example(
        summary="Create empty chat",
        description="Create a chat without an initial message. Returns a new chat with no title.",
        value={},
    ),
    "chat_with_message": Example(
        summary="Create chat with first message",
        description=(
            "Create a chat and immediately send the first message. "
            "The assistant will respond and the title will be auto-generated from the message."
        ),
        value={"message": "Help me find scholarships for computer science programs in Singapore"},
    ),
}

_SEND_MESSAGE_EXAMPLES: dict[str, Example] = {
    "scholarship_query": Example(
        summary="Ask about scholarships",
        description="Query about scholarship opportunities.",
        value={"content": "What scholarships are available for international students?"},
    ),
    "program_search": Example(
        summary="Search for programs",
        description="Search for academic programs by field.",
        value={"content": "Show me master's programs in AI and machine learning"},
    ),
    "eligibility_check": Example(
        summary="Check eligibility",
        description="Ask about eligibility requirements.",
        value={"content": "Am I eligible for the ASEAN scholarship with a 3.5 GPA?"},
    ),
    "application_help": Example(
        summary="Application assistance",
        description="Get help with application process.",
        value={"content": "What documents do I need for the NUS Graduate Fellowship application?"},
    ),
}

_UPDATE_CHAT_EXAMPLES: dict[str, Example] = {
    "rename": Example(
        summary="Rename chat",
        description="Update the chat title to something more descriptive.",
        value={"title": "My Singapore Scholarship Search"},
    ),
    "short_title": Example(
        summary="Short descriptive title",
        value={"title": "CS Scholarships 2026"},
    ),
}

# ── Response Examples for Documentation ──────────────────────────────────────

_CHAT_RESPONSE_EXAMPLE = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Help me find scholarships for computer...",
    "status": "active",
    "message_count": 2,
    "created_at": "2026-04-10T12:00:00Z",
    "updated_at": "2026-04-10T12:00:01Z",
}

_SEND_MESSAGE_RESPONSE_EXAMPLE = {
    "user_message": {
        "id": "msg-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "chat_id": "550e8400-e29b-41d4-a716-446655440000",
        "role": "user",
        "content": "What scholarships are available for international students?",
        "metadata": None,
        "created_at": "2026-04-10T12:05:00Z",
    },
    "assistant_message": {
        "id": "msg-b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "chat_id": "550e8400-e29b-41d4-a716-446655440000",
        "role": "assistant",
        "content": (
            "Thanks for your message! I'm Ouroboros, your AI assistant for discovering "
            "scholarships and programs. I'm currently being set up to help you with:\n\n"
            "• Finding scholarships that match your profile\n"
            "• Discovering graduate programs worldwide\n"
            "• Checking your eligibility for opportunities\n"
            "• Helping with your applications\n\n"
            "Full functionality is coming soon. Stay tuned!"
        ),
        "metadata": None,
        "created_at": "2026-04-10T12:05:01Z",
    },
    "chat": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "title": "What scholarships are available for...",
        "status": "active",
        "message_count": 4,
        "created_at": "2026-04-10T12:00:00Z",
        "updated_at": "2026-04-10T12:05:01Z",
    },
}

_PAGINATED_CHATS_RESPONSE_EXAMPLE = {
    "chats": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "title": "Singapore Scholarship Search",
            "status": "active",
            "message_count": 8,
            "created_at": "2026-04-10T12:00:00Z",
            "updated_at": "2026-04-10T14:30:00Z",
        },
        {
            "id": "660e8400-e29b-41d4-a716-446655440001",
            "title": "US Graduate Programs",
            "status": "active",
            "message_count": 4,
            "created_at": "2026-04-09T10:00:00Z",
            "updated_at": "2026-04-09T11:00:00Z",
        },
    ],
    "next_cursor": "MjAyNi0wNC0wOVQxMTowMDowMFo=",
    "total_count": 15,
}

_PAGINATED_MESSAGES_RESPONSE_EXAMPLE = {
    "messages": [
        {
            "id": "msg-001",
            "chat_id": "550e8400-e29b-41d4-a716-446655440000",
            "role": "user",
            "content": "Help me find scholarships",
            "metadata": None,
            "created_at": "2026-04-10T12:00:00Z",
        },
        {
            "id": "msg-002",
            "chat_id": "550e8400-e29b-41d4-a716-446655440000",
            "role": "assistant",
            "content": "Thanks for your message! I'm Ouroboros...",
            "metadata": None,
            "created_at": "2026-04-10T12:00:01Z",
        },
    ],
    "next_cursor": None,
}

# ── Service Instance ─────────────────────────────────────────────────────────

chat_service = ChatService()

# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ChatResponse,
    status_code=201,
    summary="Create a new chat",
    responses={
        201: {
            "description": "Chat created successfully",
            "content": {"application/json": {"example": _CHAT_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        422: {"description": "Validation error (message too long or invalid)"},
    },
)
async def create_chat(
    body: CreateChatRequest = Body(
        default=CreateChatRequest(message=None),
        openapi_examples=_CREATE_CHAT_EXAMPLES,
    ),
    user_id: str = Depends(get_current_user_id),
):
    """
    Create a new chat session.

    Optionally include a `message` to immediately send the first message.
    If provided, the assistant will respond and the chat title will be
    auto-generated from the message content.
    """
    return await chat_service.create_chat(
        user_id=user_id,
        initial_message=body.message,
    )


@router.get(
    "",
    response_model=PaginatedChatsResponse,
    summary="List user's chats",
    responses={
        200: {
            "description": "Paginated list of chats ordered by updated_at descending",
            "content": {"application/json": {"example": _PAGINATED_CHATS_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
    },
)
async def list_chats(
    limit: int = Query(20, ge=1, le=100, description="Number of chats to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor from previous response"),
    user_id: str = Depends(get_current_user_id),
):
    """
    List the authenticated user's chat sessions.

    Chats are ordered by `updated_at` descending (most recent first).
    Soft-deleted chats are excluded.

    Use the `next_cursor` from the response to fetch the next page.
    """
    return await chat_service.list_chats(
        user_id=user_id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{chat_id}",
    response_model=ChatResponse,
    summary="Get a single chat",
    responses={
        200: {
            "description": "Chat details",
            "content": {"application/json": {"example": _CHAT_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Chat not found or belongs to another user"},
    },
)
async def get_chat(
    chat_id: str = Path(..., description="Chat UUID"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Get a single chat by ID.

    Returns 404 if the chat doesn't exist or belongs to another user.
    """
    return await chat_service.get_chat(user_id=user_id, chat_id=chat_id)


@router.patch(
    "/{chat_id}",
    response_model=ChatResponse,
    summary="Update chat title",
    responses={
        200: {
            "description": "Chat updated with new title",
            "content": {"application/json": {"example": _CHAT_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Chat not found or belongs to another user"},
        422: {"description": "Validation error (title empty or too long)"},
    },
)
async def update_chat(
    chat_id: str = Path(..., description="Chat UUID"),
    body: UpdateChatRequest = Body(..., openapi_examples=_UPDATE_CHAT_EXAMPLES),
    user_id: str = Depends(get_current_user_id),
):
    """
    Update chat metadata.

    Currently only `title` can be updated.
    """
    return await chat_service.update_chat_title(
        user_id=user_id,
        chat_id=chat_id,
        title=body.title,
    )


@router.delete(
    "/{chat_id}",
    status_code=204,
    summary="Delete a chat",
    responses={
        204: {"description": "Chat soft-deleted (no response body)"},
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Chat not found or belongs to another user"},
    },
)
async def delete_chat(
    chat_id: str = Path(..., description="Chat UUID"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Soft-delete a chat.

    The chat is marked as deleted and excluded from list results.
    Messages are retained for potential future recovery.
    """
    await chat_service.delete_chat(user_id=user_id, chat_id=chat_id)


@router.post(
    "/{chat_id}/messages",
    response_model=SendMessageResponse,
    summary="Send a message",
    responses={
        200: {
            "description": "Message sent and assistant responded",
            "content": {"application/json": {"example": _SEND_MESSAGE_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Chat not found or belongs to another user"},
        422: {"description": "Validation error (content empty or too long)"},
    },
)
async def send_message(
    chat_id: str = Path(..., description="Chat UUID"),
    body: SendMessageRequest = Body(..., openapi_examples=_SEND_MESSAGE_EXAMPLES),
    user_id: str = Depends(get_current_user_id),
):
    """
    Send a message to a chat and receive the assistant's response.

    Returns both the user's message and the assistant's response,
    along with the updated chat metadata (including incremented message_count).

    **Note:** The assistant currently returns placeholder responses.
    Real agent integration is coming in a future update.
    """
    return await chat_service.send_message(
        user_id=user_id,
        chat_id=chat_id,
        content=body.content,
    )


@router.get(
    "/{chat_id}/messages",
    response_model=PaginatedMessagesResponse,
    summary="Get message history",
    responses={
        200: {
            "description": "Paginated list of messages for the chat",
            "content": {"application/json": {"example": _PAGINATED_MESSAGES_RESPONSE_EXAMPLE}},
        },
        400: {"description": "Invalid cursor format"},
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Chat not found or belongs to another user"},
    },
)
async def get_messages(
    chat_id: str = Path(..., description="Chat UUID"),
    limit: int = Query(50, ge=1, le=100, description="Number of messages to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor from previous response"),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order: asc (oldest first) or desc"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Get message history for a chat.

    Default order is `asc` (oldest first) for natural conversation display.
    Use `desc` to get newest messages first.

    Use the `next_cursor` from the response to fetch the next page.
    """
    return await chat_service.get_messages(
        user_id=user_id,
        chat_id=chat_id,
        limit=limit,
        cursor=cursor,
        order=order,
    )
