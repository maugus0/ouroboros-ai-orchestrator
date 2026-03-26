"""Proxy route to Student Profile agent service."""

from fastapi import APIRouter, Depends

from app.middleware.auth_middleware import get_current_user_id
from app.models.common import StandardResponse

router = APIRouter(prefix="/profiles", tags=["Profiles"])


@router.post("/parse")
async def parse_cv(_user_id: str = Depends(get_current_user_id)):
    """Upload and parse a CV via the Student Profile agent."""
    return StandardResponse(message="Parse CV — not yet implemented")


@router.get("/me")
async def get_profile(_user_id: str = Depends(get_current_user_id)):
    """Retrieve the current user's parsed profile."""
    return StandardResponse(message="Get profile — not yet implemented")
