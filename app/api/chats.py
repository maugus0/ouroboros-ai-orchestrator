"""Chat session API endpoints."""

from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.openapi.models import Example

from app.middleware.auth_middleware import get_current_user_id
from app.models.chat import (
    AssistantNoticeRequest,
    AssistantNoticeResponse,
    ChatResponse,
    CreateChatRequest,
    PaginatedChatsResponse,
    PaginatedMessagesResponse,
    SendMessageRequest,
    SendMessageResponse,
    UpdateChatRequest,
)
from app.services.chat_service import ChatService
from app.services.profile_gate_service import ProfileGateService

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
    "chat_in_project": Example(
        summary="Create chat in a project",
        description="Create a chat assigned to a specific project.",
        value={
            "message": "What master's programs are available?",
            "project_id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        },
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
    "star_chat": Example(
        summary="Star a chat",
        description="Mark a chat as starred/favorite.",
        value={"is_starred": True},
    ),
    "unstar_chat": Example(
        summary="Unstar a chat",
        description="Remove starred status from a chat.",
        value={"is_starred": False},
    ),
    "move_to_project": Example(
        summary="Move chat to project",
        description="Assign the chat to a project folder.",
        value={"project_id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
    ),
    "remove_from_project": Example(
        summary="Remove chat from project",
        description="Remove the chat from its current project (use empty string).",
        value={"project_id": ""},
    ),
    "full_update": Example(
        summary="Update multiple fields",
        description="Update title, star status, and project in one request.",
        value={
            "title": "Important Research",
            "is_starred": True,
            "project_id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        },
    ),
}

# ── Response Examples for Documentation ──────────────────────────────────────

_CHAT_RESPONSE_EXAMPLE = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Help me find scholarships for computer...",
    "status": "active",
    "is_starred": False,
    "project_id": None,
    "message_count": 2,
    "created_at": "2026-04-10T12:00:00Z",
    "updated_at": "2026-04-10T12:00:01Z",
}

_CHAT_RESPONSE_STARRED_EXAMPLE = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Important Research",
    "status": "active",
    "is_starred": True,
    "project_id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "message_count": 8,
    "created_at": "2026-04-10T12:00:00Z",
    "updated_at": "2026-04-11T09:00:00Z",
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
        "is_starred": False,
        "project_id": None,
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
            "is_starred": True,
            "project_id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "message_count": 8,
            "created_at": "2026-04-10T12:00:00Z",
            "updated_at": "2026-04-10T14:30:00Z",
        },
        {
            "id": "660e8400-e29b-41d4-a716-446655440001",
            "title": "US Graduate Programs",
            "status": "active",
            "is_starred": False,
            "project_id": None,
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

chat_service = ChatService(profile_gate_service=ProfileGateService())

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
        404: {"description": "Project not found (if project_id provided)"},
        422: {"description": "Validation error (message too long or invalid)"},
    },
)
async def create_chat(
    body: CreateChatRequest = Body(
        default=CreateChatRequest(message=None, project_id=None),
        openapi_examples=_CREATE_CHAT_EXAMPLES,
    ),
    user_id: str = Depends(get_current_user_id),
):
    """
    Create a new chat session.

    Optionally:
    - Include a `message` to immediately send the first message
    - Include a `project_id` to assign the chat to a project
    """
    return await chat_service.create_chat(
        user_id=user_id,
        initial_message=body.message,
        project_id=body.project_id,
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
        404: {"description": "Project not found (if project_id filter provided)"},
    },
)
async def list_chats(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    limit: int = Query(20, ge=1, le=100, description="Number of chats to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor from previous response"),
    starred: Optional[bool] = Query(None, description="Filter: true=starred only, false=unstarred only, null=all"),
    project_id: Optional[str] = Query(None, description="Filter: only chats in this project"),
    no_project: bool = Query(False, description="Filter: only chats not assigned to any project"),
    user_id: str = Depends(get_current_user_id),
):
    """
    List the authenticated user's chat sessions.

    Chats are ordered by `updated_at` descending (most recent first).
    Soft-deleted chats are excluded.

    **Filters:**
    - `starred=true` — only starred chats
    - `starred=false` — only non-starred chats
    - `project_id=<uuid>` — only chats in specific project
    - `no_project=true` — only chats not in any project
    """
    return await chat_service.list_chats(
        user_id=user_id,
        limit=limit,
        cursor=cursor,
        starred=starred,
        project_id=project_id,
        no_project=no_project,
    )


@router.get(
    "/{chat_id}",
    response_model=ChatResponse,
    summary="Get a single chat",
    responses={
        200: {
            "description": "Chat details",
            "content": {"application/json": {"example": _CHAT_RESPONSE_STARRED_EXAMPLE}},
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
    summary="Update chat",
    responses={
        200: {
            "description": "Chat updated",
            "content": {"application/json": {"example": _CHAT_RESPONSE_STARRED_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Chat or project not found"},
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

    **Fields:**
    - `title` — rename the chat
    - `is_starred` — mark as favorite (true/false)
    - `project_id` — move to a project (UUID) or remove from project (empty string "")

    Only provided fields are updated; others remain unchanged.
    """
    return await chat_service.update_chat(
        user_id=user_id,
        chat_id=chat_id,
        title=body.title,
        is_starred=body.is_starred,
        project_id=body.project_id if body.project_id != "" else None,
        remove_from_project=body.project_id == "",
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
    Project chat_count is decremented if chat was in a project.
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


@router.post(
    "/{chat_id}/assistant-notice",
    response_model=AssistantNoticeResponse,
    summary="Post assistant notice",
    responses={
        200: {"description": "Assistant notice persisted"},
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Chat not found or belongs to another user"},
        422: {"description": "Validation error (content empty or too long)"},
    },
)
async def post_assistant_notice(
    chat_id: str = Path(..., description="Chat UUID"),
    body: AssistantNoticeRequest = Body(...),
    user_id: str = Depends(get_current_user_id),
):
    """Persist an assistant-authored system notice in the chat timeline."""
    return await chat_service.post_assistant_notice(
        user_id=user_id,
        chat_id=chat_id,
        content=body.content,
        metadata=body.metadata,
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
    cursor: Optional[str] = Query(
        None,
        description="Pagination cursor from previous response (base64 JSON with timestamp and message ID)",
    ),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order: asc (oldest first) or desc"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Get message history for a chat.

    Default order is `asc` (oldest first) for natural conversation display.
    Use `desc` to get newest messages first.

    **Cursor Format:**
    The cursor is a base64-encoded JSON object `{"t": "<ISO timestamp>", "id": "<message-uuid>"}`
    that includes both timestamp and message ID for stable pagination even when messages
    share the same timestamp.

    Use the `next_cursor` from the response to fetch the next page.
    """
    return await chat_service.get_messages(
        user_id=user_id,
        chat_id=chat_id,
        limit=limit,
        cursor=cursor,
        order=order,
    )
