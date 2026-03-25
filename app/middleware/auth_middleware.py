"""JWT validation middleware and FastAPI dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.core.security import decode_token

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency — extracts and validates the JWT from the
    Authorization: Bearer <token> header.  Returns the decoded claims.
    """
    token = credentials.credentials
    claims = decode_token(
        token=token,
        public_key=settings.JWT_PUBLIC_KEY,
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )
    return claims


async def get_current_user_id(
    claims: dict = Depends(get_current_user),
) -> str:
    """Convenience dependency that returns only the user ID (``sub`` claim)."""
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identifier",
        )
    return user_id
