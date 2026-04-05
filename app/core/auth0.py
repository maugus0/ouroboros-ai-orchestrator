"""
Auth0 JWT validation using JWKS (JSON Web Key Set).
Validates tokens issued by Auth0 and extracts user claims.
"""

import time
from typing import Any, ClassVar

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("auth0")

JWKS_CACHE_TTL_SECONDS = 3600  # Cache JWKS for 1 hour


class _JwksCache:
    """Module-level JWKS cache (mutable class attributes, no ``global``)."""

    data: ClassVar[dict[str, Any] | None] = None
    fetched_at: ClassVar[float] = 0.0

    @classmethod
    def clear(cls) -> None:
        cls.data = None
        cls.fetched_at = 0.0


async def get_jwks() -> dict[str, Any]:
    """
    Fetch Auth0 JWKS (public keys) with caching.

    The JWKS endpoint returns the public keys used to verify JWT signatures.
    We cache this to avoid hitting Auth0 on every request.
    """
    now = time.time()
    if _JwksCache.data and (now - _JwksCache.fetched_at) < JWKS_CACHE_TTL_SECONDS:
        return _JwksCache.data

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.auth0_jwks_uri)
            response.raise_for_status()
            _JwksCache.data = response.json()
            _JwksCache.fetched_at = now
            logger.debug("jwks_fetched", uri=settings.auth0_jwks_uri)
            return _JwksCache.data
    except httpx.HTTPError as exc:
        logger.error("jwks_fetch_failed", error=str(exc), uri=settings.auth0_jwks_uri)
        if _JwksCache.data:
            logger.warning("jwks_using_stale_cache")
            return _JwksCache.data
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch authentication keys",
        ) from exc


def _get_rsa_key(jwks: dict[str, Any], token: str) -> dict[str, str] | None:
    """Extract the RSA key matching the token's kid (key ID) from JWKS."""
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        return None

    kid = unverified_header.get("kid")
    if not kid:
        return None

    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"],
            }
    return None


async def validate_auth0_token(token: str) -> dict[str, Any]:
    """
    Validate an Auth0 JWT and return the decoded payload.

    Verifies:
    - Token signature using Auth0's public key (JWKS)
    - Token has not expired
    - Issuer matches Auth0 domain
    - Audience matches configured API identifier

    Args:
        token: The JWT access token from Authorization header

    Returns:
        Decoded token payload containing claims (sub, email, etc.)

    Raises:
        HTTPException 401 if token is invalid, expired, or malformed
    """
    jwks = await get_jwks()
    rsa_key = _get_rsa_key(jwks, token)

    if not rsa_key:
        logger.warning("token_key_not_found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find appropriate signing key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=settings.get_auth0_algorithms(),
            audience=settings.AUTH0_API_AUDIENCE,
            issuer=settings.auth0_issuer,
        )
        logger.debug("token_validated", sub=payload.get("sub"))
        return payload

    except ExpiredSignatureError as exc:
        logger.info("token_expired", sub=_safe_get_sub(token))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except JWTClaimsError as exc:
        logger.warning("token_claims_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims (check audience/issuer)",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except JWTError as exc:
        logger.error("token_validation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _safe_get_sub(token: str) -> str | None:
    """Extract sub claim without validation (for logging only)."""
    try:
        unverified = jwt.get_unverified_claims(token)
        return unverified.get("sub")
    except JWTError:
        return None


def clear_jwks_cache() -> None:
    """Clear the JWKS cache (useful for testing)."""
    _JwksCache.clear()
