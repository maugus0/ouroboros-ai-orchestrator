"""Dashboard route handlers — aggregated workflow results."""

from fastapi import APIRouter, Depends

from app.middleware.auth_middleware import get_current_user_id
from app.models.common import StandardResponse

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/{chat_id}")
async def get_dashboard(chat_id: str, _user_id: str = Depends(get_current_user_id)):
    """Return aggregated results from all agent stages for a workflow."""
    _ = chat_id
    return StandardResponse(message="Dashboard — not yet implemented")
