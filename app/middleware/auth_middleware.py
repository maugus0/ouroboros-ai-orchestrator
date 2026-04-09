"""JWT authentication dependencies (self-rolled RS256)."""

from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.logging import get_logger
from app.utils.jwt_util import JWTUtil

logger = get_logger(__name__)

security = HTTPBearer(scheme_name="HTTPBearer")
jwt_util = JWTUtil()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    """Validate access token and return its claims."""
    token = credentials.credentials if credentials else None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = jwt_util.validate_token(token)
    if not jwt_util.is_access_token(claims):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token required")
    return claims


async def get_current_user_id(
    user: dict[str, Any] = Depends(get_current_user),
) -> str:
    """Extract and return the user's UUID from token claims."""
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token: missing user ID")
    return uid


async def get_optional_user(request: Request) -> Optional[dict[str, Any]]:
    """Return claims if a valid Bearer token is present, else None."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    try:
        claims = jwt_util.validate_token(auth.removeprefix("Bearer "))
        if jwt_util.is_access_token(claims):
            return claims
    except HTTPException:
        pass
    return None


def get_client_info(request: Request) -> dict[str, Optional[str]]:
    """Extract IP and User-Agent from the request (handles X-Forwarded-For)."""
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return {"ip_address": ip, "user_agent": request.headers.get("User-Agent")}
