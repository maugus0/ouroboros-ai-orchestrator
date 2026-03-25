"""
Self-rolled JWT RS256 authentication.
Orchestrator owns the private key (issues tokens).
Other services validate with the public key only.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status

from app.core.logging import get_logger

logger = get_logger(__name__)


def create_access_token(
    payload: dict[str, Any],
    private_key: str,
    issuer: str,
    audience: str,
    expires_seconds: int = 3600,
) -> str:
    """Issue a signed JWT access token (RS256)."""
    now = datetime.now(timezone.utc)
    claims = {
        **payload,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(seconds=expires_seconds),
        "type": "access",
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


def create_refresh_token(
    payload: dict[str, Any],
    private_key: str,
    issuer: str,
    audience: str,
    expires_seconds: int = 2592000,
) -> str:
    """Issue a signed JWT refresh token (RS256)."""
    now = datetime.now(timezone.utc)
    claims = {
        **payload,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(seconds=expires_seconds),
        "type": "refresh",
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


def decode_token(
    token: str,
    public_key: str,
    issuer: str,
    audience: str,
) -> dict[str, Any]:
    """Decode and validate a JWT token using the public key."""
    try:
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
        )
    except jwt.ExpiredSignatureError:
        logger.warning("token_expired")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidIssuerError:
        logger.warning("invalid_issuer")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token issuer")
    except jwt.InvalidAudienceError:
        logger.warning("invalid_audience")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token audience")
    except jwt.PyJWTError as exc:
        logger.error("jwt_decode_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
