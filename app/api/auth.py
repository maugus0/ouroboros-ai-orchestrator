"""Authentication route handlers — signup, login, refresh, me."""

from fastapi import APIRouter, Depends

from app.middleware.auth_middleware import get_current_user
from app.models.common import StandardResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup")
async def signup():
    """Register a new user. (Implementation pending)"""
    return StandardResponse(message="Signup endpoint — not yet implemented")


@router.post("/login")
async def login():
    """Authenticate and receive JWT tokens. (Implementation pending)"""
    return StandardResponse(message="Login endpoint — not yet implemented")


@router.post("/refresh")
async def refresh_token():
    """Exchange a refresh token for a new access token. (Implementation pending)"""
    return StandardResponse(message="Refresh endpoint — not yet implemented")


@router.post("/logout")
async def logout(claims: dict = Depends(get_current_user)):
    """Invalidate the current session. (Implementation pending)"""
    return StandardResponse(message="Logout endpoint — not yet implemented")


@router.get("/me")
async def get_me(claims: dict = Depends(get_current_user)):
    """Return the authenticated user's profile. (Implementation pending)"""
    return StandardResponse(data={"user_id": claims.get("sub")})
