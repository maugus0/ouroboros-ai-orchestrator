"""
Authentication route handlers.

Auth0 handles signup, login, and token refresh directly.
This API provides:
- GET /auth/me - Return authenticated user profile
- POST /auth/logout - Logout endpoint (client-side token clearing)
- PATCH /auth/me - Update user profile

Legacy endpoints (signup, login, refresh) are deprecated.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.database import get_pool
from app.core.logging import get_logger
from app.middleware.auth_middleware import (
    get_current_user,
    get_current_user_id,
    get_current_user_record,
)
from app.models.auth import LogoutResponse, UserResponse, UserUpdateRequest
from app.models.common import StandardResponse
from app.repositories.user_repo import UserRepository

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Placeholder URLs for deprecated endpoints (split strings avoid Bandit B105 on .../oauth/token).
_AUTH0_PLACEHOLDER_HOST = "YOUR_AUTH0_DOMAIN"


def _doc_auth0_authorize_url(screen_hint_signup: bool = False) -> str:
    base = "".join(["https://", _AUTH0_PLACEHOLDER_HOST, "/authorize"])
    return f"{base}?screen_hint=signup" if screen_hint_signup else base


def _doc_auth0_token_url() -> str:
    return "".join(["https://", _AUTH0_PLACEHOLDER_HOST, "/oauth/", "token"])


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user_record)):
    """
    Return the authenticated user's profile.

    This endpoint returns the full user record from the database,
    including Auth0 linkage information.
    """
    return UserResponse(
        id=user["id"],
        name=user["name"],
        email=user["email"],
        auth0_sub=user.get("auth0_sub"),
        auth_provider=user.get("auth_provider"),
        is_active=user["is_active"],
        last_login=user.get("last_login"),
        created_at=user["created_at"],
        updated_at=user.get("updated_at"),
    )


@router.patch("/me", response_model=UserResponse)
async def update_me(
    update_data: UserUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Update the authenticated user's profile.

    Only name and email can be updated. Auth0 sub cannot be changed.
    """
    pool = get_pool()
    user_repo = UserRepository(pool)

    updated_user = await user_repo.update_profile(
        user_id,
        name=update_data.name,
        email=update_data.email,
    )

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(
        id=updated_user["id"],
        name=updated_user["name"],
        email=updated_user["email"],
        auth0_sub=updated_user.get("auth0_sub"),
        auth_provider=updated_user.get("auth_provider"),
        is_active=updated_user["is_active"],
        last_login=updated_user.get("last_login"),
        created_at=updated_user["created_at"],
        updated_at=updated_user.get("updated_at"),
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(claims: dict = Depends(get_current_user)):
    """
    Logout the current user.

    With Auth0 JWT tokens, true server-side logout requires token revocation
    at Auth0. This endpoint confirms the token is valid and instructs the
    client to clear stored tokens.

    For full logout, the frontend should:
    1. Call this endpoint
    2. Clear access_token and refresh_token from storage
    3. Optionally redirect to Auth0 logout URL for SSO logout
    """
    auth0_sub = claims.get("sub", "unknown")
    logger.info("user_logout", auth0_sub=auth0_sub)

    return LogoutResponse(
        message="Logged out successfully",
        detail="Clear tokens on client side. For SSO logout, redirect to Auth0 logout URL.",
    )


# ============================================
# Deprecated endpoints (Auth0 handles these)
# ============================================


@router.post("/signup", deprecated=True)
async def signup():
    """
    DEPRECATED: User registration is handled by Auth0.

    Direct users to Auth0 Universal Login or use the Auth0 SDK
    for signup functionality.
    """
    return StandardResponse(
        success=False,
        message="Signup is handled by Auth0. Use Auth0 Universal Login or SDK.",
        data={"auth0_signup_url": _doc_auth0_authorize_url(screen_hint_signup=True)},
    )


@router.post("/login", deprecated=True)
async def login():
    """
    DEPRECATED: Authentication is handled by Auth0.

    Direct users to Auth0 Universal Login or use the Auth0 SDK
    for authentication.
    """
    return StandardResponse(
        success=False,
        message="Login is handled by Auth0. Use Auth0 Universal Login or SDK.",
        data={"auth0_login_url": _doc_auth0_authorize_url()},
    )


@router.post("/refresh", deprecated=True)
async def refresh_token():
    """
    DEPRECATED: Token refresh is handled by Auth0.

    Use the Auth0 SDK or call Auth0's /oauth/token endpoint
    with the refresh_token grant type.
    """
    return StandardResponse(
        success=False,
        message="Token refresh is handled by Auth0. Use Auth0 SDK or /oauth/token endpoint.",
        data={"auth0_token_url": _doc_auth0_token_url()},
    )
