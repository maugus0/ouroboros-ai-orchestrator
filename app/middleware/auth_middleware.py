"""
Auth0 JWT validation middleware and FastAPI dependencies.

Validates tokens issued by Auth0 and performs JIT (Just-In-Time) user provisioning
when a user authenticates for the first time.
"""

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth0 import validate_auth0_token
from app.core.database import get_pool
from app.core.logging import get_logger
from app.repositories.user_repo import UserRepository

logger = get_logger(__name__)

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    """
    FastAPI dependency — validates Auth0 JWT from Authorization header.

    Returns the decoded token claims from Auth0.
    Use this when you need access to the full token payload.
    """
    token = credentials.credentials
    claims = await validate_auth0_token(token)
    return claims


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    FastAPI dependency — validates Auth0 JWT and returns local user UUID.

    This is the primary authentication dependency for most routes.
    It performs JIT provisioning: if the Auth0 user doesn't exist locally,
    a new user record is created automatically.

    Returns:
        The local user UUID (users.id) for use in FK relationships.

    Raises:
        HTTPException 401 if token is invalid or missing.
    """
    token = credentials.credentials
    claims = await validate_auth0_token(token)

    auth0_sub = claims.get("sub")
    if not auth0_sub:
        logger.error("token_missing_sub")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject identifier",
        )

    pool = get_pool()
    user_repo = UserRepository(pool)
    user = await user_repo.get_by_auth0_sub(auth0_sub)

    if not user:
        email = claims.get("email", f"{auth0_sub}@auth0.placeholder")
        name = claims.get("name") or claims.get("nickname")
        user = await user_repo.create_from_auth0(auth0_sub, email, name)
        logger.info("jit_user_provisioned", auth0_sub=auth0_sub, user_id=user["id"])
    else:
        await user_repo.update_last_login(user["id"])

    return user["id"]


async def get_current_user_record(
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """
    FastAPI dependency — returns the full user record from database.

    Use this when you need access to user profile data (name, email, etc.)
    beyond just the user ID.
    """
    pool = get_pool()
    user_repo = UserRepository(pool)
    user = await user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user
