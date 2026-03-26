"""Workflow orchestration route handlers."""

from fastapi import APIRouter, Depends

from app.middleware.auth_middleware import get_current_user_id
from app.models.common import StandardResponse

router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post("/{chat_id}/start")
async def start_workflow(chat_id: str, _user_id: str = Depends(get_current_user_id)):
    """Kick off the sequential agent workflow for a chat session."""
    _ = chat_id
    return StandardResponse(message="Start workflow — not yet implemented")


@router.get("/{chat_id}/status")
async def workflow_status(chat_id: str, _user_id: str = Depends(get_current_user_id)):
    """Return the current workflow state."""
    _ = chat_id
    return StandardResponse(message="Workflow status — not yet implemented")


@router.post("/{chat_id}/retry")
async def retry_workflow(chat_id: str, _user_id: str = Depends(get_current_user_id)):
    """Retry a failed workflow from the last successful state."""
    _ = chat_id
    return StandardResponse(message="Retry workflow — not yet implemented")
