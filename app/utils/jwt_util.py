"""JWT token generation and validation (RS256, self-rolled)."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class JWTUtil:
    """Stateless RS256 JWT helper — access & refresh token lifecycle."""

    def __init__(self) -> None:
        self.algorithm = "RS256"
        self.access_ttl = settings.JWT_ACCESS_TOKEN_EXP_SECONDS
        self.refresh_ttl = settings.JWT_REFRESH_TOKEN_EXP_SECONDS
        self.issuer = settings.JWT_ISSUER
        self.audience = settings.JWT_AUDIENCE

        if not settings.JWT_PRIVATE_KEY or not settings.JWT_PUBLIC_KEY:
            logger.warning("jwt_keys_not_configured")

    # ── token generation ─────────────────────────────────────────

    def generate_access_token(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: str,
        username: Optional[str] = None,
        phone_number: Optional[str] = None,
        session_id: Optional[str] = None,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate a short-lived access token."""
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "sub": user_id,
            "token_type": "access",  # nosec B105
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "exp": now + timedelta(seconds=self.access_ttl),
            "jti": str(uuid.uuid4()),
        }
        if username:
            payload["username"] = username
        if phone_number:
            payload["phone"] = phone_number
        if session_id:
            payload["sid"] = session_id
        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=self.algorithm)

    def generate_refresh_token(
        self,
        user_id: str,
        session_id: str,
        token_id: Optional[str] = None,
    ) -> str:
        """Generate a long-lived refresh token. token_id is stored hashed in DB."""
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "sub": user_id,
            "token_type": "refresh",  # nosec B105
            "sid": session_id,
            "jti": token_id or secrets.token_urlsafe(64),
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "exp": now + timedelta(seconds=self.refresh_ttl),
        }
        return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=self.algorithm)

    # ── validation ───────────────────────────────────────────────

    def validate_token(self, token: str) -> Dict[str, Any]:
        """Decode and validate a JWT. Raises HTTPException on failure."""
        try:
            return jwt.decode(
                token,
                settings.JWT_PUBLIC_KEY,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
            )
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            logger.warning("invalid_token", error=str(exc))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def is_access_token(claims: Dict[str, Any]) -> bool:
        return claims.get("token_type") == "access"

    @staticmethod
    def is_refresh_token(claims: Dict[str, Any]) -> bool:
        return claims.get("token_type") == "refresh"

    @staticmethod
    def get_jti(claims: Dict[str, Any]) -> Optional[str]:
        return claims.get("jti")
