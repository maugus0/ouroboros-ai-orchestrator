"""Chat session CRUD route handlers."""

from fastapi import APIRouter, Depends

from app.middleware.auth_middleware import get_current_user_id
from app.models.common import StandardResponse

router = APIRouter(prefix="/chats", tags=["Chats"])


@router.post("/")
async def create_chat(_user_id: str = Depends(get_current_user_id)):
    """Create a new chat session tied to the authenticated user."""
    return StandardResponse(message="Create chat — not yet implemented")


@router.get("/")
async def list_chats(_user_id: str = Depends(get_current_user_id)):
    """List all chat sessions for the authenticated user."""
    return StandardResponse(message="List chats — not yet implemented", data=[])


@router.get("/{chat_id}")
async def get_chat(chat_id: str, _user_id: str = Depends(get_current_user_id)):
    """Retrieve a single chat session with its messages."""
    _ = chat_id
    return StandardResponse(message="Get chat — not yet implemented")


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, _user_id: str = Depends(get_current_user_id)):
    """Soft-delete a chat session."""
    _ = chat_id
    return StandardResponse(message="Delete chat — not yet implemented")
